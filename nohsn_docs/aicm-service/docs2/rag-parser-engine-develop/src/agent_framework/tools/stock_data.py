"""실 주식 데이터 layer — pykrx (KRX 무료 데이터, API 키 없음).

Tool layer 도구:
- ``stock.quote``        — 단일 종목 시세
- ``stock.market_movers`` — 급등주 / 급락주 / 거래량 top
- (포트폴리오 도구는 ``stock_watch.py`` 에서)

설계 원칙:
- 종목명 ↔ 종목코드 매핑은 LLM 이 발화에서 추출한 **종목명** 을 받아 코드로 환원.
- 거래일 기준 (휴장일 / 주말 / 휴일 처리) — pykrx 가 가까운 영업일 데이터 반환.
- 캐시 TTL: 시세 60초, 종목 목록 24시간.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

_TZ = ZoneInfo("Asia/Seoul")

_TICKER_CACHE_TTL = 60 * 60 * 24  # 24h
_QUOTE_CACHE_TTL = 60  # 60s — 동일 종목 60초 안에 두 번 조회 시 cache hit
_MOVERS_CACHE_TTL = 60 * 5  # 5min

_TICKER_CACHE_KEY = "stock:ticker_map:v1"  # name → code
_REVERSE_CACHE_KEY = "stock:code_to_name:v1"  # code → name


_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _kst_business_date(today: date | None = None, lookback_days: int = 0) -> str:
    """KST 영업일 문자열 (YYYYMMDD).

    pykrx 는 휴장일에 빈 결과 — 토/일 / 공휴일을 backwards 로 보정.
    완벽한 한국 공휴일 캘린더는 외부 패키지에 의존하면 무거우므로,
    가까운 평일 1-3 일 lookback 후 데이터 비면 호출자가 추가 fallback.
    """
    base = (today or datetime.now(_TZ).date()) - timedelta(days=lookback_days)
    while base.weekday() >= 5:  # 토(5) / 일(6)
        base -= timedelta(days=1)
    return base.strftime("%Y%m%d")


async def _ensure_ticker_map() -> dict[str, str]:
    """종목명 → 코드 매핑 (KOSPI + KOSDAQ + KONEX). 24h Redis 캐시."""
    rds = _get_redis()
    cached = await rds.get(_TICKER_CACHE_KEY)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    log.info("stock_ticker_map_rebuild")
    loop = asyncio.get_running_loop()
    name_to_code: dict[str, str] = {}
    code_to_name: dict[str, str] = {}

    def _build():
        # 1차: FinanceDataReader.StockListing("KRX") — KRX 전체 리스트 (~2800 종목).
        # 2026-04-28: pykrx 의 get_market_ticker_list 가 빈 결과/JSON 파싱 에러 빈발.
        # FDR 의 KRX 리스트가 안정적 — 동일 데이터를 다른 엔드포인트로.
        try:
            import FinanceDataReader as fdr  # type: ignore
            df = fdr.StockListing("KRX")
            for _, row in df.iterrows():
                code = str(row.get("Code") or "").zfill(6)
                nm = str(row.get("Name") or "").strip()
                if code and nm and len(code) == 6:
                    name_to_code[nm] = code
                    code_to_name[code] = nm
            return name_to_code, code_to_name
        except Exception as e:  # noqa: BLE001
            log.warning("fdr_ticker_list_failed", error=str(e))

        # 2차 fallback: pykrx (불안정 — 빈 결과 가능)
        try:
            from pykrx import stock as kx

            biz = _kst_business_date()
            for market in ("KOSPI", "KOSDAQ"):
                try:
                    tickers = kx.get_market_ticker_list(biz, market=market)
                except Exception as e:  # noqa: BLE001
                    log.warning("pykrx_ticker_list_failed", market=market, error=str(e))
                    continue
                for code in tickers:
                    try:
                        nm = kx.get_market_ticker_name(code)
                    except Exception:
                        continue
                    if nm:
                        name_to_code[nm] = code
                        code_to_name[code] = nm
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx_unavailable", error=str(e))
        return name_to_code, code_to_name

    name_to_code, code_to_name = await loop.run_in_executor(None, _build)
    if name_to_code:
        await rds.set(_TICKER_CACHE_KEY, json.dumps(name_to_code, ensure_ascii=False), ex=_TICKER_CACHE_TTL)
        await rds.set(_REVERSE_CACHE_KEY, json.dumps(code_to_name, ensure_ascii=False), ex=_TICKER_CACHE_TTL)
    return name_to_code


# P11-19p (GPT-5.5 자문 #3) — 한국 주식 인기 종목 alias table.
# fdr.StockListing 의 정식 이름과 사용자 자주 쓰는 별칭 매핑.
# 미국 주식은 별도 — 'unsupported' 처리 명확화 (resolve 단계 X, 응답 단계 O).
_KR_STOCK_ALIASES: dict[str, str] = {
    # 흔한 변형
    "엘지전자": "066570",
    "LG전자": "066570",
    "lg전자": "066570",
    "엘지화학": "051910",
    "LG화학": "051910",
    "삼성전기": "009150",
    "삼성SDI": "006400",
    "삼성에스디아이": "006400",
    "현대차": "005380",
    "현대자동차": "005380",
    "기아차": "000270",
    "기아": "000270",
    "포스코": "005490",
    "POSCO": "005490",
    "포스코홀딩스": "005490",
    "셀트리온": "068270",
    # 영문 ticker 별칭
    "kakao": "035720",
    "naver": "035420",
    "samsung": "005930",
    "skhynix": "000660",
    "SK하이닉스": "000660",
    "sk하이닉스": "000660",
}


# 미국 주식 명시적 인식 (unsupported 안내용)
_US_STOCK_PATTERNS: tuple[str, ...] = (
    "테슬라", "tesla", "TSLA",
    "엔비디아", "NVDA", "nvidia",
    "애플", "apple", "AAPL",
    "구글", "google", "GOOGL", "GOOG",
    "마이크로소프트", "microsoft", "MSFT",
    "아마존", "amazon", "AMZN",
    "메타", "META", "facebook",
)


def is_us_stock_query(query: str) -> bool:
    """발화에 미국 주식 인디케이터가 있나? unsupported 응답 분기 시 사용."""
    q = (query or "").strip()
    return any(pat.lower() in q.lower() for pat in _US_STOCK_PATTERNS)


async def resolve_ticker(query: str) -> tuple[str | None, str | None]:
    """종목명 또는 코드 → (code, name).

    매칭 우선순위:
    1) 6 자리 숫자 → 그대로 코드 시도
    2) 정확 이름 매칭
    3) 부분 일치 (가장 짧은 이름 우선 — "삼성" → "삼성전자")

    실패 시 (None, None).
    """
    if not query:
        return (None, None)
    q = query.strip()
    if q.isdigit() and len(q) == 6:
        # code 인지 확인
        rds = _get_redis()
        rev = await rds.get(_REVERSE_CACHE_KEY)
        if rev:
            try:
                rev_map = json.loads(rev)
                nm = rev_map.get(q)
                if nm:
                    return (q, nm)
            except json.JSONDecodeError:
                pass
        # ticker map 강제 빌드 후 재시도
        await _ensure_ticker_map()
        rev = await rds.get(_REVERSE_CACHE_KEY)
        if rev:
            try:
                rev_map = json.loads(rev)
                nm = rev_map.get(q)
                if nm:
                    return (q, nm)
            except json.JSONDecodeError:
                pass
        return (q, None)  # 코드 형식이지만 이름 못 찾음 — 그대로 시도

    # P11-19p — alias 우선 매칭 (사용자 자주 쓰는 별칭).
    if q in _KR_STOCK_ALIASES:
        code = _KR_STOCK_ALIASES[q]
        # name 도 매핑 — reverse cache 또는 alias 자체.
        rds = _get_redis()
        rev = await rds.get(_REVERSE_CACHE_KEY)
        if rev:
            try:
                rev_map = json.loads(rev)
                nm = rev_map.get(code) or q
                return (code, nm)
            except json.JSONDecodeError:
                pass
        return (code, q)
    # case-insensitive alias 시도
    q_lower = q.lower()
    for alias, code in _KR_STOCK_ALIASES.items():
        if alias.lower() == q_lower:
            return (code, alias)

    name_map = await _ensure_ticker_map()
    if q in name_map:
        return (name_map[q], q)

    # 부분 일치 — 짧은 이름 우선
    candidates = [n for n in name_map if q in n]
    if candidates:
        candidates.sort(key=len)
        nm = candidates[0]
        return (name_map[nm], nm)

    return (None, None)


async def quote(args: dict[str, Any]) -> dict[str, Any]:
    """단일 종목 시세 + 직전 거래일 대비 등락률.

    args:
    - symbol|ticker|name: 종목명 또는 6자리 코드 (필수)

    반환: {success, code, name, close, prev_close, change_pct, volume, trade_date, summary}
    """
    # P11-19b — args 이름 일관성. plan_intents/stock.md 는 code_or_name 사용.
    # 옛 호출자 호환: symbol / ticker / name / query / code 모두 지원.
    raw = (
        args.get("code_or_name")
        or args.get("symbol")
        or args.get("ticker")
        or args.get("name")
        or args.get("query")
        or args.get("code")
    )
    code, name = await resolve_ticker(str(raw or ""))
    if not code:
        return {
            "success": False,
            "error": "종목을 찾을 수 없습니다",
            "query": raw,
            "summary": f"종목 인식 실패 ({raw}). 종목명 또는 6자리 코드로 다시 알려주세요.",
        }

    rds = _get_redis()
    ckey = f"stock:quote:{code}"
    cached = await rds.get(ckey)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    loop = asyncio.get_running_loop()

    def _fetch():
        end = datetime.now(_TZ).date()
        start = end - timedelta(days=10)

        # 1차: pykrx OHLCV (한국 종가 정확)
        try:
            from pykrx import stock as kx

            df = kx.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
            if df is not None and len(df) > 0:
                return ("pykrx", df)
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx_ohlcv_failed", code=code, error=str(e))

        # 2차 fallback: FinanceDataReader (네이버 금융 등에서)
        try:
            import FinanceDataReader as fdr  # type: ignore

            df2 = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if df2 is not None and len(df2) > 0:
                return ("fdr", df2)
        except Exception as e:  # noqa: BLE001
            log.warning("fdr_ohlcv_failed", code=code, error=str(e))
        return (None, None)

    try:
        source, df = await loop.run_in_executor(None, _fetch)
    except Exception as e:  # noqa: BLE001
        log.warning("stock_quote_fetch_failed", code=code, error=str(e))
        return {
            "success": False,
            "code": code,
            "name": name,
            "error": f"시세 조회 실패: {e}",
            "summary": f"{name or code} 시세 조회 실패 — 잠시 후 재시도",
        }

    if df is None or len(df) == 0:
        return {
            "success": False,
            "code": code,
            "name": name,
            "error": "데이터 없음",
            "summary": f"{name or code} 데이터 없음 (휴장 또는 신규 상장)",
        }

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    if source == "pykrx":
        close = int(last["종가"])
        prev_close = int(prev["종가"]) if len(df) > 1 else close
        volume = int(last["거래량"])
        op = int(last["시가"])
        hi = int(last["고가"])
        lo = int(last["저가"])
    else:  # fdr
        close = int(last["Close"])
        prev_close = int(prev["Close"]) if len(df) > 1 else close
        volume = int(last["Volume"])
        op = int(last["Open"])
        hi = int(last["High"])
        lo = int(last["Low"])
    change = close - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    trade_date = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])

    arrow = "▲" if change > 0 else ("▼" if change < 0 else "-")
    out = {
        "success": True,
        "code": code,
        "name": name or code,
        "close": close,
        "prev_close": prev_close,
        "change": change,
        "change_pct": round(change_pct, 2),
        "volume": volume,
        "open": op,
        "high": hi,
        "low": lo,
        "trade_date": trade_date,
        "source": source,
        "summary": (
            f"{name or code} ({code}) {close:,}원 {arrow} "
            f"{abs(change):,}({abs(change_pct):.2f}%) "
            f"거래량 {volume:,} · {trade_date} 종가"
        ),
    }
    await rds.set(ckey, json.dumps(out, ensure_ascii=False), ex=_QUOTE_CACHE_TTL)
    return out


async def market_movers(args: dict[str, Any]) -> dict[str, Any]:
    """급등주 top N + 급락주 top N + 거래량 top N.

    args:
    - market: "KOSPI" | "KOSDAQ" | "ALL" (default: "ALL")
    - top_n: int (default 5)

    반환: {success, gainers, losers, volume, market, trade_date, summary}
    """
    market = str(args.get("market") or "ALL").upper()
    if market not in ("KOSPI", "KOSDAQ", "ALL"):
        market = "ALL"
    top_n = int(args.get("top_n") or 5)
    top_n = max(1, min(top_n, 30))

    rds = _get_redis()
    ckey = f"stock:movers:{market}:{top_n}"
    cached = await rds.get(ckey)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    loop = asyncio.get_running_loop()

    def _fetch():
        # 1차: FinanceDataReader.StockListing('KRX') — Close/Changes/ChangesRatio 한 번에.
        # pykrx 의 get_market_price_change_by_ticker 가 KRX API 응답 빈 결과 자주.
        try:
            import FinanceDataReader as fdr  # type: ignore

            df = fdr.StockListing("KRX")
            rows: list[dict] = []
            for _, row in df.iterrows():
                code = str(row.get("Code") or "").zfill(6)
                nm = str(row.get("Name") or "").strip()
                m = str(row.get("Market") or "").upper()
                if market != "ALL" and m != market:
                    continue
                try:
                    close = int(row.get("Close") or 0)
                except (TypeError, ValueError):
                    close = 0
                # P11-4: fdr 의 컬럼명이 'ChagesRatio' (오타지만 라이브러리 내 실제
                # 이름). 'ChangesRatio'/'ChangeRatio' 외에 'ChagesRatio' 도 시도.
                try:
                    chg_pct = float(
                        row.get("ChangesRatio")
                        or row.get("ChangeRatio")
                        or row.get("ChagesRatio")
                        or 0
                    )
                except (TypeError, ValueError):
                    chg_pct = 0.0
                try:
                    vol = int(row.get("Volume") or 0)
                except (TypeError, ValueError):
                    vol = 0
                if not code or not nm or close <= 0:
                    continue
                rows.append({
                    "code": code,
                    "name": nm,
                    "close": close,
                    "change_pct": chg_pct,
                    "volume": vol,
                    "market": m,
                })
            return _kst_business_date(), rows
        except Exception as e:  # noqa: BLE001
            log.warning("fdr_movers_failed", error=str(e))

        # 2차 fallback: pykrx (불안정)
        try:
            from pykrx import stock as kx

            biz = _kst_business_date()
            prev_biz = _kst_business_date(lookback_days=1)
            attempts = 0
            while prev_biz == biz and attempts < 5:
                attempts += 1
                prev_biz = _kst_business_date(lookback_days=attempts + 1)

            markets = ["KOSPI", "KOSDAQ"] if market == "ALL" else [market]
            rows = []
            for m in markets:
                try:
                    df = kx.get_market_price_change_by_ticker(prev_biz, biz, market=m)
                except Exception as e:  # noqa: BLE001
                    log.warning("pykrx_movers_failed", market=m, error=str(e))
                    continue
                if df is None or len(df) == 0:
                    continue
                for code, row in df.iterrows():
                    try:
                        nm = kx.get_market_ticker_name(code)
                    except Exception:
                        nm = code
                    rows.append({
                        "code": code,
                        "name": nm,
                        "close": int(row["종가"]),
                        "change_pct": float(row["등락률"]),
                        "volume": int(row["거래량"]),
                        "market": m,
                    })
            return biz, rows
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx_movers_unavailable", error=str(e))
        return _kst_business_date(), []

    try:
        trade_date, rows = await loop.run_in_executor(None, _fetch)
    except Exception as e:  # noqa: BLE001
        log.warning("stock_movers_failed", error=str(e))
        return {
            "success": False,
            "error": f"시장 동향 조회 실패: {e}",
            "summary": "시장 동향 조회 실패 — 잠시 후 재시도",
        }

    if not rows:
        return {
            "success": False,
            "summary": "시장 동향 데이터 없음 (휴장 또는 데이터 미수신)",
        }

    rows = [r for r in rows if r.get("close", 0) > 0 and abs(r.get("change_pct", 0.0)) < 50.0]

    gainers = sorted(rows, key=lambda r: r["change_pct"], reverse=True)[:top_n]
    losers = sorted(rows, key=lambda r: r["change_pct"])[:top_n]
    volume = sorted(rows, key=lambda r: r["volume"], reverse=True)[:top_n]

    out = {
        "success": True,
        "market": market,
        "trade_date": trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:],
        "gainers": gainers,
        "losers": losers,
        "volume": volume,
        "summary": (
            f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {market} 시장 동향 — "
            f"급등 {len(gainers)} · 급락 {len(losers)} · 거래량 {len(volume)} top"
        ),
    }
    await rds.set(ckey, json.dumps(out, ensure_ascii=False), ex=_MOVERS_CACHE_TTL)
    return out

"""주식 종목 분석 — 객관적 정보 정리 (매수·매도 권고 X).

자비스 패턴: 코드는 *사실 + 신호*만 산출. LLM 은 자연어 narrative 만.
재무·법적 자문 면허 없음. 모든 응답에 면책 1줄 포함.

Tool 도구:
- ``stock.analyze`` — 한 종목의 시세 + 기술적 지표 + 추세 + (선택) 공시 + (선택) 뉴스 sentiment.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.agent_framework.tools import stock_data
from src.common.logging import get_logger

log = get_logger(__name__)

_TZ = ZoneInfo("Asia/Seoul")

_DISCLAIMER = "본 정보는 자동 분석 결과이며 투자 자문이 아닙니다."


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _compute_indicators(df) -> dict[str, Any]:
    """stockstats 로 RSI/MACD/Bollinger + 단순 통계.

    df: pandas DataFrame — pykrx ('종가'/'거래량') 또는 fdr ('Close'/'Volume') 컬럼.
    반환: 점·신호 dict (객관적 사실만).
    """
    import pandas as pd
    from stockstats import StockDataFrame

    if df is None or len(df) < 20:
        return {"insufficient_data": True}

    # 컬럼 정규화 → stockstats 가 요구하는 'close','high','low','open','volume'
    cols = list(df.columns)
    if "종가" in cols:
        norm = pd.DataFrame({
            "close": df["종가"].astype(float),
            "high": df["고가"].astype(float),
            "low": df["저가"].astype(float),
            "open": df["시가"].astype(float),
            "volume": df["거래량"].astype(float),
        }, index=df.index)
    else:
        norm = pd.DataFrame({
            "close": df["Close"].astype(float),
            "high": df["High"].astype(float),
            "low": df["Low"].astype(float),
            "open": df["Open"].astype(float),
            "volume": df["Volume"].astype(float),
        }, index=df.index)

    s = StockDataFrame.retype(norm.copy())
    last_idx = -1

    # 지표 — stockstats 는 column access 시 lazy 계산
    rsi14 = _safe_float(s["rsi_14"].iloc[last_idx])
    macd = _safe_float(s["macd"].iloc[last_idx])
    macd_signal = _safe_float(s["macds"].iloc[last_idx])
    macd_hist = _safe_float(s["macdh"].iloc[last_idx])
    bb_upper = _safe_float(s["boll_ub"].iloc[last_idx])
    bb_lower = _safe_float(s["boll_lb"].iloc[last_idx])
    bb_mid = _safe_float(s["boll"].iloc[last_idx])
    ma5 = _safe_float(s["close_5_sma"].iloc[last_idx])
    ma20 = _safe_float(s["close_20_sma"].iloc[last_idx])
    ma60 = _safe_float(s["close_60_sma"].iloc[last_idx]) if len(s) >= 60 else None

    close = _safe_float(norm["close"].iloc[last_idx])

    # 변동성 — 일별 수익률 표준편차 (최근 20일) → 연환산
    returns = norm["close"].pct_change().dropna()
    recent_returns = returns.tail(20)
    vol_daily = _safe_float(recent_returns.std()) if len(recent_returns) >= 5 else None
    vol_annualized = (vol_daily * (252 ** 0.5)) if vol_daily else None

    # 최근 5일·20일 누적수익률
    ret_5d = None
    ret_20d = None
    if len(norm) >= 6:
        c0 = _safe_float(norm["close"].iloc[-6])
        if c0 and close:
            ret_5d = (close - c0) / c0
    if len(norm) >= 21:
        c0 = _safe_float(norm["close"].iloc[-21])
        if c0 and close:
            ret_20d = (close - c0) / c0

    # 신호 — 객관적 사실 진술 (조언·의견 X)
    signals: list[str] = []
    if rsi14 is not None:
        if rsi14 >= 70:
            signals.append(f"RSI 14 = {rsi14:.1f} (과매수 영역)")
        elif rsi14 <= 30:
            signals.append(f"RSI 14 = {rsi14:.1f} (과매도 영역)")
        else:
            signals.append(f"RSI 14 = {rsi14:.1f} (중립)")
    if macd is not None and macd_signal is not None:
        cross = "MACD > signal (양봉)" if macd > macd_signal else "MACD < signal (음봉)"
        signals.append(f"MACD {macd:.1f} vs signal {macd_signal:.1f} — {cross}")
    if close is not None and ma20 is not None:
        signals.append(
            f"종가 {close:,.0f} vs 20일 평균 {ma20:,.0f} ({((close - ma20)/ma20*100):+.2f}%)"
        )
    if close is not None and ma60 is not None:
        signals.append(
            f"종가 vs 60일 평균 {ma60:,.0f} ({((close - ma60)/ma60*100):+.2f}%)"
        )
    if close is not None and bb_upper is not None and bb_lower is not None:
        if close >= bb_upper:
            signals.append("볼린저 상단 돌파")
        elif close <= bb_lower:
            signals.append("볼린저 하단 돌파")
    if vol_annualized is not None:
        signals.append(f"연환산 변동성 {vol_annualized*100:.1f}% (최근 20일)")
    if ret_5d is not None:
        signals.append(f"최근 5일 누적 {ret_5d*100:+.2f}%")
    if ret_20d is not None:
        signals.append(f"최근 20일 누적 {ret_20d*100:+.2f}%")

    return {
        "close": close,
        "rsi_14": rsi14,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_mid": bb_mid,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "vol_daily": vol_daily,
        "vol_annualized": vol_annualized,
        "return_5d": ret_5d,
        "return_20d": ret_20d,
        "signals": signals,
    }


async def _fetch_ohlcv_long(code: str, days: int = 90):
    """긴 기간 OHLCV — 지표 계산용 (60일 SMA 위해 90일+)."""
    loop = asyncio.get_running_loop()

    def _fetch():
        end = datetime.now(_TZ).date()
        start = end - timedelta(days=days)
        try:
            from pykrx import stock as kx
            df = kx.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
            if df is not None and len(df) > 0:
                return df
        except Exception as e:  # noqa: BLE001
            log.warning("pykrx_long_failed", error=str(e))
        try:
            import FinanceDataReader as fdr  # type: ignore
            df2 = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if df2 is not None and len(df2) > 0:
                return df2
        except Exception as e:  # noqa: BLE001
            log.warning("fdr_long_failed", error=str(e))
        return None

    return await loop.run_in_executor(None, _fetch)


async def _fetch_disclosures(name: str, days: int = 14) -> list[dict]:
    """DART 최근 공시 — DART_API_KEY env 필수.

    name: 종목명 (DART 는 종목명·종목코드 모두 검색).
    """
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        return []
    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            import OpenDartReader  # type: ignore
            dart = OpenDartReader(api_key)
            end = datetime.now(_TZ).date()
            start = end - timedelta(days=days)
            df = dart.list(name, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
            if df is None or len(df) == 0:
                return []
            out = []
            for _, row in df.head(20).iterrows():
                out.append({
                    "date": str(row.get("rcept_dt") or "")[:10],
                    "title": str(row.get("report_nm") or "").strip(),
                    "rcept_no": str(row.get("rcept_no") or ""),
                })
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("dart_fetch_failed", error=str(e))
            return []

    return await loop.run_in_executor(None, _fetch)


# 한국어 금융 sentiment — KR-FinBert. transformers 가 lazy 로드.
_FINBERT_PIPELINE = None


async def _fetch_news_sentiment(name: str, count: int = 5) -> dict[str, Any]:
    """종목명 뉴스 N건 → 평균 sentiment.

    transformers 미설치 또는 로드 실패 시 graceful skip.
    뉴스 검색은 기존 ``news_search`` 도구 사용.
    """
    try:
        from src.agent_framework.tools import news_search

        news = await news_search.search({"query": name + " 주식", "count": count})
    except Exception as e:  # noqa: BLE001
        log.warning("news_search_failed", error=str(e))
        return {"available": False, "reason": "news_search_failed"}

    items = news.get("items") if isinstance(news, dict) else None
    if not items:
        return {"available": False, "reason": "no_news"}

    headlines = []
    for it in items[:count]:
        title = (it.get("title") or "").strip()
        desc = (it.get("description") or it.get("summary") or "").strip()
        if title or desc:
            headlines.append({"title": title, "desc": desc[:200]})

    # KR-FinBert lazy load (CPU OK, ~400MB 처음 한번 다운로드)
    global _FINBERT_PIPELINE
    if _FINBERT_PIPELINE is None:
        try:
            loop = asyncio.get_running_loop()
            def _load():
                from transformers import pipeline  # type: ignore
                return pipeline(
                    "text-classification",
                    model="snunlp/KR-FinBert-SC",
                    tokenizer="snunlp/KR-FinBert-SC",
                )
            _FINBERT_PIPELINE = await loop.run_in_executor(None, _load)
        except Exception as e:  # noqa: BLE001
            log.warning("krfinbert_load_failed", error=str(e))
            return {
                "available": False,
                "reason": "model_load_failed",
                "headlines": headlines,
            }

    loop = asyncio.get_running_loop()

    def _classify():
        out = []
        for h in headlines:
            text = (h["title"] + " " + h["desc"]).strip()[:512]
            try:
                r = _FINBERT_PIPELINE(text, truncation=True)
                if isinstance(r, list) and r:
                    label = str(r[0].get("label") or "").lower()
                    score = float(r[0].get("score") or 0)
                    out.append({"title": h["title"], "label": label, "score": score})
            except Exception:
                continue
        return out

    classified = await loop.run_in_executor(None, _classify)
    if not classified:
        return {"available": False, "reason": "classify_empty", "headlines": headlines}

    # 라벨 카운트 + 가중평균 (KR-FinBert-SC: positive/negative/neutral)
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    weighted = 0.0
    for c in classified:
        lbl = c["label"]
        if "pos" in lbl:
            counts["positive"] += 1
            weighted += c["score"]
        elif "neg" in lbl:
            counts["negative"] += 1
            weighted -= c["score"]
        else:
            counts["neutral"] += 1
    avg = weighted / max(1, len(classified))
    tone = "강세" if avg > 0.2 else ("약세" if avg < -0.2 else "중립")
    return {
        "available": True,
        "items": classified,
        "counts": counts,
        "score": round(avg, 3),
        "tone": tone,
    }


async def analyze(args: dict[str, Any]) -> dict[str, Any]:
    """종합 분석 — 시세 + 지표 + 추세 + (옵션) 공시 + (옵션) 뉴스 sentiment.

    args:
    - symbol|name|ticker: 종목명 또는 6자리 코드 (필수)
    - include_disclosures: bool (default True — DART_API_KEY 있으면)
    - include_news: bool (default True — KR-FinBert 로드 가능 시)

    매수·매도 권고 X. 객관적 사실 + 신호 진술만.
    """
    # P11-19b — args 이름 일관성 (plan_intents/stock.md = code_or_name).
    raw = (
        args.get("code_or_name")
        or args.get("symbol")
        or args.get("name")
        or args.get("ticker")
        or args.get("code")
        or args.get("query")
    )
    code, name = await stock_data.resolve_ticker(str(raw or ""))
    if not code:
        return {
            "success": False,
            "error": "종목 인식 실패",
            "summary": f"종목 인식 실패 ({raw}). 종목명 또는 6자리 코드로 다시 알려주세요.",
        }

    # 1) 즉시 시세
    quote = await stock_data.quote({"symbol": code})

    # 2) 긴 기간 OHLCV → 지표
    df = await _fetch_ohlcv_long(code, days=120)
    indicators = _compute_indicators(df)

    # 3) DART 공시 (optional)
    include_disc = args.get("include_disclosures", True)
    disclosures = []
    if include_disc and (name or code):
        disclosures = await _fetch_disclosures(name or code, days=14)

    # 4) 뉴스 sentiment (optional)
    include_news = args.get("include_news", True)
    news = {"available": False, "reason": "skipped"}
    if include_news and name:
        news = await _fetch_news_sentiment(name, count=5)

    # 종합 summary 한 줄 — 사실만.
    summary_parts: list[str] = []
    if quote.get("success"):
        summary_parts.append(quote.get("summary", "").split(" · ")[0])
    sigs = indicators.get("signals") or []
    if sigs:
        summary_parts.append(" / ".join(sigs[:3]))
    if news.get("available"):
        summary_parts.append(f"뉴스 톤 {news.get('tone')} ({news.get('score')})")
    if disclosures:
        summary_parts.append(f"최근 14일 공시 {len(disclosures)}건")

    return {
        "success": True,
        "code": code,
        "name": name or code,
        "quote": quote,
        "indicators": indicators,
        "disclosures": disclosures,
        "news_sentiment": news,
        "disclaimer": _DISCLAIMER,
        "summary": (
            " · ".join(summary_parts)
            if summary_parts
            else f"{name or code} 분석 데이터 부족"
        ),
    }

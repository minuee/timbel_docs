"""SelfQueryParser — Phase 1.6 retriever 강화 (self-query metadata filter).

자연어 query → 1회 LLM 호출 → metadata filter (date_range / category /
status / priority / tenant) JSON 추출. Qdrant must/should/filter clause 로
변환해 retrieval 정확도를 높인다.

원칙:
- *standalone* 모듈 — 호출 callsite 없음. SOP/Tool RAG 통합은 flag-gated
  (`FEATURE_SELF_QUERY`). 시연 path 무영향.
- 한국어 시간/카테고리/상태 자연어 인식: "지난주", "5월", "긴급", "취소된",
  "예약/결제/배송" 등.
- LLM 호출 1회 (~150ms 목표) + 1초 timeout. 실패 시 *빈 filter* 반환
  (fail-open — caller 가 unfiltered retrieval 진행).
- (query_hash) → 60s LRU cache (동일 turn 내 중복 호출 방지).
- 결과는 *선언적 dict* — Qdrant payload key 매핑은 caller (retriever) 책임.

설계 참조:
- spec: docs/superpowers/specs/2026-05-07-retriever-enhancement.md (TBD)
- 사용자 권고 (2026-05-07): "내 5월 일정 → date filter 5월"
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from src.common.logging import get_logger

log = get_logger(__name__)


# --- Constants ----------------------------------------------------------------

DEFAULT_TIMEOUT_S = 1.0
CACHE_TTL_S = 60.0
CACHE_MAX_ENTRIES = 1000
DEFAULT_MAX_TOKENS = 256
DEFAULT_TEMPERATURE = 0.0  # deterministic JSON


# --- Public dataclass --------------------------------------------------------


@dataclass(frozen=True)
class SelfQueryFilter:
    """LLM 이 추출한 metadata filter.

    None / 빈 list 는 *해당 차원에 제약 없음*. caller 는 이 구조를
    Qdrant must/should clause 로 변환.

    Attributes:
        date_range: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} or None.
        category: 카테고리 후보 list (e.g. ["예약", "결제"]).
        status: 상태 후보 list (e.g. ["취소", "보류"]).
        priority: "high" | "medium" | "low" | None.
        tenant_filter: tenant_id 제약 — caller 가 명시 추출 시 사용.
        residual_query: filter 추출 후 *남은* keyword query — retrieval 본 질의용.
            LLM 이 비워두면 원본 query 그대로.
        raw: 원본 LLM JSON (디버그/감사).
    """

    date_range: Optional[dict[str, str]] = None
    category: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    priority: Optional[str] = None
    tenant_filter: Optional[str] = None
    residual_query: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """모든 차원이 비었는지 — 빈 filter = unfiltered retrieval signal."""
        return (
            self.date_range is None
            and not self.category
            and not self.status
            and self.priority is None
            and self.tenant_filter is None
        )


# --- LLM 인터페이스 -----------------------------------------------------------


class LLMClientLike(Protocol):
    """src.common.llm.base.BaseLLMClient 호환 최소 인터페이스."""

    async def generate(self, request: Any) -> Any: ...


# --- Default prompt -----------------------------------------------------------

_DEFAULT_SELF_QUERY_PROMPT = """\
당신은 한국어 자연어 질의에서 검색 metadata filter 를 추출합니다.

오늘 날짜: {today}

추출 대상:
- date_range: {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}} 또는 null
  - "지난주" → 가장 최근 월~일 7일 범위
  - "5월" → 올해 5월 1일 ~ 31일
  - "어제" → 단일 날짜 (start=end)
  - 시간 언급 없으면 null
- category: 도메인 카테고리 list (e.g. ["예약", "결제", "배송", "민원"]).
  - 명시 없으면 [].
- status: 상태 list (e.g. ["취소", "완료", "보류", "진행중"]).
  - 명시 없으면 [].
- priority: "high" | "medium" | "low" | null
  - "긴급/시급" → high. "참고" → low. 없으면 null.
- residual_query: 위 filter 를 *제거한 뒤* 남는 keyword 본 질의.
  - 원본에서 시간/상태/우선순위 어휘만 빼고 retrieval 에 쓸 핵심 키워드.

규칙:
1. *순수 JSON* 만 출력 — 머리말/꼬리말/markdown 금지.
2. 추출 불가능한 필드는 null 또는 [] (절대 추측 금지).
3. 빈 입력 → 모든 필드 null/[].

질의:
{query}

JSON:"""


# --- TTL LRU cache ------------------------------------------------------------


class _TTLCache:
    def __init__(self, max_size: int = CACHE_MAX_ENTRIES, ttl_s: float = CACHE_TTL_S, *, clock: Callable[[], float] | None = None) -> None:
        self._max = max_size
        self._ttl = ttl_s
        self._clock = clock or time.monotonic
        self._data: OrderedDict[str, tuple[float, SelfQueryFilter]] = OrderedDict()

    def get(self, key: str) -> Optional[SelfQueryFilter]:
        item = self._data.get(key)
        if item is None:
            return None
        ts, value = item
        if self._clock() - ts > self._ttl:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: SelfQueryFilter) -> None:
        self._data[key] = (self._clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


# --- Helpers ------------------------------------------------------------------


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(s: Any) -> Optional[str]:
    if not isinstance(s, str):
        return None
    s = s.strip()
    if _DATE_RE.match(s):
        return s
    return None


_VALID_PRIORITIES = {"high", "medium", "low"}


def _extract_json(text: str) -> Optional[dict]:
    """LLM 응답에서 JSON object 추출. 첫 ``{...}`` 블록.

    markdown code fence / 잡설 prefix 모두 제거.
    """
    if not text:
        return None
    # 1) code fence 안 우선.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        # 2) 첫 { 부터 마지막 } 까지 (greedy — JSON 한 객체 가정).
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def _coerce_filter(payload: dict[str, Any], original_query: str) -> SelfQueryFilter:
    """LLM JSON → SelfQueryFilter (validated). 잘못된 필드는 silent drop."""
    raw = dict(payload)

    # date_range
    dr_raw = payload.get("date_range")
    date_range: Optional[dict[str, str]] = None
    if isinstance(dr_raw, dict):
        start = _validate_date(dr_raw.get("start"))
        end = _validate_date(dr_raw.get("end"))
        if start and end:
            # start ≤ end 강제 (swap if not).
            if start > end:
                start, end = end, start
            date_range = {"start": start, "end": end}
        elif start and not end:
            date_range = {"start": start, "end": start}

    # category — list[str], 비어있는 항목 제거.
    cat_raw = payload.get("category") or []
    if not isinstance(cat_raw, list):
        cat_raw = []
    category = [str(x).strip() for x in cat_raw if isinstance(x, (str, int)) and str(x).strip()]

    # status — list[str].
    st_raw = payload.get("status") or []
    if not isinstance(st_raw, list):
        st_raw = []
    status = [str(x).strip() for x in st_raw if isinstance(x, (str, int)) and str(x).strip()]

    # priority — enum.
    pr_raw = payload.get("priority")
    priority: Optional[str] = None
    if isinstance(pr_raw, str):
        s = pr_raw.strip().lower()
        if s in _VALID_PRIORITIES:
            priority = s

    # tenant_filter — str.
    tn_raw = payload.get("tenant_filter")
    tenant_filter: Optional[str] = None
    if isinstance(tn_raw, str) and tn_raw.strip():
        tenant_filter = tn_raw.strip()

    # residual_query — LLM 결과 우선, 비어있으면 원본 query.
    rq_raw = payload.get("residual_query")
    if isinstance(rq_raw, str) and rq_raw.strip():
        residual_query = rq_raw.strip()
    else:
        residual_query = original_query.strip()

    return SelfQueryFilter(
        date_range=date_range,
        category=category,
        status=status,
        priority=priority,
        tenant_filter=tenant_filter,
        residual_query=residual_query,
        raw=raw,
    )


# --- SelfQueryParser ----------------------------------------------------------


class SelfQueryParser:
    """natural-language query → metadata filter JSON (1 LLM call).

    Args:
        llm_client: ``BaseLLMClient`` 호환.
        prompt_template: ``{today}`` / ``{query}`` 포함.
        timeout_s: 단일 LLM 호출 timeout.
        cache_ttl_s: query_hash → filter cache TTL (default 60s).
        clock: 테스트 시간 주입.
        today_provider: ``Callable[[], str]`` — "YYYY-MM-DD" 반환. 기본 ``date.today()``.

    공개 메서드:
        extract_filters(query) → SelfQueryFilter
    """

    def __init__(
        self,
        llm_client: LLMClientLike,
        *,
        prompt_template: Optional[str] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_ttl_s: float = CACHE_TTL_S,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        clock: Callable[[], float] | None = None,
        today_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        self._llm = llm_client
        self._prompt = prompt_template or _DEFAULT_SELF_QUERY_PROMPT
        self._timeout_s = float(timeout_s)
        self._max_tokens = int(max_tokens)
        self._temperature = float(temperature)
        self._cache = _TTLCache(max_size=CACHE_MAX_ENTRIES, ttl_s=cache_ttl_s, clock=clock)
        self._clock = clock or time.monotonic
        self._today_provider = today_provider or self._default_today

    @staticmethod
    def _default_today() -> str:
        from datetime import date

        return date.today().isoformat()

    # ----- public API -----

    async def extract_filters(self, query: str) -> SelfQueryFilter:
        """query → SelfQueryFilter.

        Behavior:
            - 빈 query → empty filter (residual_query="").
            - cache hit → LLM 호출 0.
            - LLM timeout / 예외 / parse 실패 → empty filter (residual=원본).
            - 모든 차원 검증 (date format / priority enum) — 잘못된 값 silent drop.
        """
        q = (query or "").strip()
        if not q:
            return SelfQueryFilter(residual_query="")

        qhash = _query_hash(q)
        cached = self._cache.get(qhash)
        if cached is not None:
            return cached

        today = self._today_provider() or ""
        prompt = self._prompt.format(today=today, query=q)

        try:
            response = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning("self_query_timeout", timeout_s=self._timeout_s)
            empty = SelfQueryFilter(residual_query=q)
            # timeout 결과는 cache 안 함 — 다음 turn 에서 재시도 가능하게.
            return empty
        except Exception as exc:  # noqa: BLE001
            log.warning("self_query_llm_failed", error=str(exc))
            return SelfQueryFilter(residual_query=q)

        text = self._extract_text(response)
        payload = _extract_json(text)
        if payload is None:
            log.info("self_query_parse_failed", text_head=(text or "")[:120])
            return SelfQueryFilter(residual_query=q)

        result = _coerce_filter(payload, q)
        self._cache.set(qhash, result)
        return result

    def clear_cache(self) -> None:
        self._cache.clear()

    # ----- internals -----

    async def _call_llm(self, prompt: str) -> Any:
        try:
            from src.common.llm.base import LLMRequest

            req = LLMRequest(
                prompt=prompt,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format="json",
            )
        except Exception:  # noqa: BLE001
            req = {  # type: ignore[assignment]
                "prompt": prompt,
                "max_tokens": self._max_tokens,
                "temperature": self._temperature,
                "response_format": "json",
            }
        return await self._llm.generate(req)

    @staticmethod
    def _extract_text(response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        if isinstance(response, dict):
            for key in ("text", "content", "output"):
                v = response.get(key)
                if isinstance(v, str):
                    return v
        return ""

"""D31d Phase 3 — KMS 관측성 통합 metrics 모듈 (#212).

Phase 3 신규 counter 4종 단일 모듈 정의 — DuplicateTimeSeries 방지.

기존 모듈과 명확히 분리:
- src/api/metrics.py — HTTP/API/LLM/Assist-stream metrics (aicm_*).
- src/pipeline/metrics.py — Pipeline stage / dispatcher metrics (aicm_*).
- src/search/metrics.py — Search engine metrics (aicm_*).
- src/common/metrics.py — Phase 3 KMS observability counters (kms_*) — 본 모듈.

비파괴 원칙: 본 모듈의 counter 는 모두 inc 만 수행. 기존 코드 동작 / 재시도 / 흐름 변경 X.
사전 GPT-5 v2 verdict: GO (2026-05-08).
"""

from __future__ import annotations

# D35 §3 (MUST 3) — prometheus_client ImportError NoOp 폴백.
# test / minimal 환경에서 prometheus_client 미설치 시 module load 자체 실패 방지 —
# Counter 호출 site 는 모두 try/except 로 감싸지만 import 단계에서도 안전 보장.
try:
    from prometheus_client import Counter, Gauge, Histogram
except ImportError:  # pragma: no cover — 의존성 미설치 환경 보호.
    class _NoOpCounter:  # type: ignore[no-redef]
        """prometheus_client 미설치 시 폴백 — labels/inc/set/observe no-op.

        D46-v3 §6 — Histogram 도 동일 NoOp 으로 fallback (observe 메서드 추가).
        모듈 import 단계 + 호출 site 모두 safe.
        """
        def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D401
            pass

        def labels(self, *args: object, **kwargs: object) -> "_NoOpCounter":
            return self

        def inc(self, *args: object, **kwargs: object) -> None:
            pass

        def set(self, *args: object, **kwargs: object) -> None:  # for Gauge fallback.
            pass

        def observe(self, *args: object, **kwargs: object) -> None:  # for Histogram fallback (D46-v3 §6).
            pass

    Counter = _NoOpCounter  # type: ignore[assignment,misc]
    Gauge = _NoOpCounter  # type: ignore[assignment,misc]
    Histogram = _NoOpCounter  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# §2 — RLS violation counter
# ---------------------------------------------------------------------------

KMS_RLS_VIOLATION_TOTAL = Counter(
    "kms_rls_violation_total",
    "RLS context 누락/미스매치 (가드 트립) 총 수 — Phase 3 §2",
    labelnames=["source", "table", "operation"],
    # source = middleware | payload_sync
    # table = any | documents | blocks | chunks | ...
    # operation = bind_system_scope_null_tenant
    #             | bind_agent_scope_invalid_id
    #             | tenant_slug_not_found
)

# ---------------------------------------------------------------------------
# §3 — ES 색인 retry / failure counter
# ---------------------------------------------------------------------------

KMS_ES_INDEX_RETRY_TOTAL = Counter(
    "kms_es_index_retry_total",
    "ES 색인/업데이트 재시도 총 수 (최종 실패 제외) — Phase 3 §3",
    labelnames=["reason"],  # timeout | conflict | connection | other
)

KMS_ES_INDEX_FAILURE_TOTAL = Counter(
    "kms_es_index_failure_total",
    "ES 색인/업데이트 최종 실패 (모든 재시도 후 실패) 총 수 — Phase 3 §3",
    labelnames=["reason"],
)

KMS_ES_INDEX_SUCCESS_TOTAL = Counter(
    "kms_es_index_success_total",
    "ES 색인/업데이트 최종 성공 총 수 — Phase 3 §3 (alert 분모 용)",
)


def classify_es_error(exc: BaseException) -> str:
    """ES 예외 → reason label.

    GPT-5 §3 pre verdict 권고 — isinstance 1순위, name fallback.
    매핑:
    - elasticsearch ConnectionTimeout / asyncio.TimeoutError / urllib3 ReadTimeout → "timeout"
    - elasticsearch ConflictError / status==409 → "conflict"
    - elasticsearch ConnectionError / ConnectionRefusedError → "connection"
    - 그 외 → "other"
    """
    # 1순위: isinstance (defensive import — elasticsearch / elastic_transport
    # 미설치 환경에서도 fallback 로 동작).
    try:
        import asyncio as _asyncio
        from elasticsearch import (  # type: ignore[import-not-found]
            ConflictError,
            ConnectionError as ESConnectionError,
            ConnectionTimeout,
        )

        if isinstance(exc, (ConnectionTimeout, _asyncio.TimeoutError)):
            return "timeout"
        if isinstance(exc, ConflictError):
            return "conflict"
        if isinstance(exc, ESConnectionError):
            return "connection"
    except Exception:  # noqa: BLE001 — 의존성 미설치 등.
        pass

    # 2순위: status_code / status 속성 체크.
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 409:
        return "conflict"

    # 3순위: 클래스명 string fallback.
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "conflict" in name:
        return "conflict"
    if "connection" in name or "refused" in name:
        return "connection"
    if isinstance(exc, ConnectionRefusedError):
        return "connection"

    return "other"

# ---------------------------------------------------------------------------
# §1 — Payload salvage counter
# ---------------------------------------------------------------------------

# op 라벨 값 상수 (오타/시계열 파편화 방지 — GPT-5 §1 권고).
SALVAGE_OP_BLOCKS_FULL_TO_BLOCKS = "blocks_full_to_blocks"
SALVAGE_OP_BLOCK_META_JSON = "block_meta_json_salvage"
SALVAGE_OP_MERGED_METADATA_TO_BLOCKS = "merged_metadata_to_blocks"
SALVAGE_OP_CHUNK_META_TO_BASE = "chunk_meta_to_base"

KMS_PAYLOAD_SALVAGE_TOTAL = Counter(
    "kms_payload_salvage_total",
    "KMS payload salvage (fallback) 발생 총 수 — fallback site (op) 별 — Phase 3 §1",
    labelnames=["op"],
    # op 값:
    # - blocks_full_to_blocks  (reseed_v4 의 blocks_full 부재 → blocks 3-tuple fallback)
    # - block_meta_json_salvage (block meta 의 비-JSON 데이터 → extracted_metadata 비움 후 재시도)
    # - merged_metadata_to_blocks (chunk merged_metadata 부재 → block-level 메타로 fallback)
    # - chunk_meta_to_base  (chunk_meta JSON 직렬화 실패 → base_chunk_meta fallback)
)


def inc_kms_payload_salvage(op: str) -> None:
    """Salvage counter inc — testability 용 wrapper.

    GPT-5 §1 권고: monkeypatch 가능한 함수 단위 — op 라벨 검증 용이.
    """
    try:
        KMS_PAYLOAD_SALVAGE_TOTAL.labels(op=op).inc()
    except Exception:  # noqa: BLE001 — registry 미초기화 등.
        pass


# ---------------------------------------------------------------------------
# D35 §3 — worker self-check fatal + per-event rebind failure counter (#215)
# ---------------------------------------------------------------------------

KMS_WORKER_SELF_CHECK_FATAL_TOTAL = Counter(
    "kms_worker_self_check_fatal_total",
    "worker 기동 시 RLS self-check fatal exit 횟수 — D35 §2 (#215)",
    labelnames=["reason"],
    # reason = bypass_rls_true_app_mode (현재 유일 — KMS_DB_ROLE=app + RLS_ENFORCE=true
    #          + 실 connect role 의 BYPASSRLS=true → 운영 오인 구성).
)


# rebind failure site label 화이트리스트 (cardinality 안전 — GPT-5 §3 §2 권고).
REBIND_SITE_SEQUENTIAL = "sequential_queue_processor"
REBIND_SITE_BLOCK_PARSED = "block_worker_parsed"
REBIND_SITE_BLOCK_PART_READY = "block_worker_part_ready"
REBIND_SITE_MERGE_PART_BLOCKED = "merge_worker_part_blocked"
REBIND_SITE_DOCUMENT_PROCESSOR = "document_processor"

ALLOWED_REBIND_SITES = frozenset(
    {
        REBIND_SITE_SEQUENTIAL,
        REBIND_SITE_BLOCK_PARSED,
        REBIND_SITE_BLOCK_PART_READY,
        REBIND_SITE_MERGE_PART_BLOCKED,
        REBIND_SITE_DOCUMENT_PROCESSOR,
    }
)

# topic 화이트리스트 — TOPIC_DOCUMENT_* (constants 와 동기화 필요 X — 본 모듈 안 동결).
ALLOWED_REBIND_TOPICS = frozenset(
    {
        "any",
        "aicm.document.uploaded",
        "aicm.document.parsed",
        "aicm.document.chunked",
        "aicm.document.blocked",
        "aicm.document.split",
        "aicm.document.part_ready",
        "aicm.document.part_blocked",
    }
)

ALLOWED_FATAL_REASONS = frozenset({"bypass_rls_true_app_mode"})

KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL = Counter(
    "kms_worker_per_event_rebind_failure_total",
    "worker per-event tenant_id 누락 / rebind 실패 횟수 — D35 §1 (#215)",
    labelnames=["site", "topic"],
    # site: REBIND_SITE_* 5종 화이트리스트 (미일치 → 'other').
    # topic: TOPIC_DOCUMENT_* 또는 'any' (미일치 → 'other').
)


def inc_kms_worker_rebind_failure(site: str, topic: str = "any") -> None:
    """per-event rebind failure counter inc — testability 용 wrapper.

    GPT-5 §3 §2 MUST: site / topic 라벨 카디널리티 강제 (미허용 값 → 'other').
    호출 site 화이트리스트 (5종) 외 입력 시 시계열 폭증 방지.

    Args:
        site: REBIND_SITE_* 상수 중 하나. 미허용 시 'other' 로 강제.
        topic: 'any' 또는 TOPIC_DOCUMENT_*. 미허용 시 'other' 로 강제.
    """
    safe_site = site if site in ALLOWED_REBIND_SITES else "other"
    safe_topic = topic if topic in ALLOWED_REBIND_TOPICS else "other"
    try:
        KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL.labels(
            site=safe_site, topic=safe_topic
        ).inc()
    except Exception:  # noqa: BLE001 — registry 미초기화 등.
        pass


def inc_kms_worker_self_check_fatal(reason: str = "bypass_rls_true_app_mode") -> None:
    """self-check fatal counter inc — testability 용 wrapper.

    GPT-5 §3 §2 MUST: reason 화이트리스트 강제 (미허용 → 'other').

    Args:
        reason: ALLOWED_FATAL_REASONS 중 하나. 미허용 시 'other'.
    """
    safe_reason = reason if reason in ALLOWED_FATAL_REASONS else "other"
    try:
        KMS_WORKER_SELF_CHECK_FATAL_TOTAL.labels(reason=safe_reason).inc()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# §1 — 유지보수 게이트 (D31d-E v2 #218)
# ---------------------------------------------------------------------------

KMS_MAINTENANCE_GATE_ON = Gauge(
    "kms_maintenance_gate_on",
    "유지보수 게이트 활성 여부 (1=on, 0=off) — D31d-E v2 §1 (#218)",
)

KMS_MAINTENANCE_BLOCKED_REQUESTS_TOTAL = Counter(
    "kms_maintenance_blocked_requests_total",
    "유지보수 게이트로 차단된 요청 수 — D31d-E v2 §1 (#218)",
    labelnames=["path", "proto", "status_code"],
    # path = deny prefix 매칭된 path (cardinality 보호 위해 path prefix 만 권장 —
    #         호출 site 가 truncate 권장).
    # proto = http | ws
    # status_code = 503 | 1013
)


# path 카디널리티 폭증 방지 — middleware 가 호출 site 에서 prefix 만 전달하도록
# 권장하지만, 안전망으로 본 모듈에서도 길이 제한.
_MAX_PATH_LABEL_LEN = 64


def set_maintenance_gate(on: bool) -> None:
    """유지보수 게이트 gauge 갱신 — testability 용 wrapper.

    Args:
        on: True → 1, False → 0.
    """
    try:
        KMS_MAINTENANCE_GATE_ON.set(1 if on else 0)
    except Exception:  # noqa: BLE001
        pass


def inc_maintenance_blocked(path: str, proto: str, status_code: str) -> None:
    """유지보수 게이트 차단 counter inc — testability 용 wrapper.

    path 라벨 카디널리티 보호: 64자 이상은 truncate.
    proto/status_code 화이트리스트 강제.

    Args:
        path: 차단된 path (truncate 적용).
        proto: 'http' | 'ws' (그 외 → 'other').
        status_code: '503' | '1013' (그 외 → 'other').
    """
    safe_path = (path or "")[:_MAX_PATH_LABEL_LEN] or "/"
    safe_proto = proto if proto in ("http", "ws") else "other"
    safe_status = status_code if status_code in ("503", "1013") else "other"
    try:
        KMS_MAINTENANCE_BLOCKED_REQUESTS_TOTAL.labels(
            path=safe_path, proto=safe_proto, status_code=safe_status
        ).inc()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# D46-v3 §6 — Pipeline stage observability (histogram + counter)
# + D46-v3 §3-b — merge_worker race retry counter
# ---------------------------------------------------------------------------

KMS_PIPELINE_STAGE_DURATION_SECONDS = Histogram(
    "kms_pipeline_stage_duration_seconds",
    "Pipeline stage 소요 시간 (초) — D46-v3 §6",
    labelnames=["stage"],
    # stage = reload | contextual | metadata | embedding | qdrant
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 900.0, 1800.0),
)

KMS_PIPELINE_STAGE_FAILURE_TOTAL = Counter(
    "kms_pipeline_stage_failure_total",
    "Pipeline stage 실패 (예외 발생) 총 수 — D46-v3 §6",
    labelnames=["stage", "error_type"],
)

KMS_PIPELINE_STAGE_COUNT_TOTAL = Counter(
    "kms_pipeline_stage_count_total",
    "Pipeline stage 진입 총 수 — D46-v3 §6",
    labelnames=["stage"],
)

KMS_PIPELINE_MERGE_PART_RETRY_TOTAL = Counter(
    "kms_pipeline_merge_part_retry_total",
    "merge_worker mark_part_completed transient retry 총 수 — D46-v3 §3-b",
)


def inc_kms_pipeline_stage_count(stage: str) -> None:
    """Pipeline stage 진입 counter inc — testability 용 wrapper."""
    try:
        KMS_PIPELINE_STAGE_COUNT_TOTAL.labels(stage=stage).inc()
    except Exception:  # noqa: BLE001
        pass


def observe_kms_pipeline_stage_duration(stage: str, duration_sec: float) -> None:
    """Pipeline stage duration histogram observe."""
    try:
        KMS_PIPELINE_STAGE_DURATION_SECONDS.labels(stage=stage).observe(duration_sec)
    except Exception:  # noqa: BLE001
        pass


def inc_kms_pipeline_stage_failure(stage: str, error_type: str) -> None:
    """Pipeline stage 실패 counter inc."""
    try:
        KMS_PIPELINE_STAGE_FAILURE_TOTAL.labels(
            stage=stage, error_type=error_type
        ).inc()
    except Exception:  # noqa: BLE001
        pass


def inc_kms_pipeline_merge_part_retry() -> None:
    """merge_worker transient retry counter inc — D46-v3 §3-b."""
    try:
        KMS_PIPELINE_MERGE_PART_RETRY_TOTAL.inc()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# D78 — P0 가드레일 모니터링 (D65/D68/D69/D70/D72/D74) — 6 신규 counter
# ---------------------------------------------------------------------------
# 사전 GPT-5 v1 GO_WITH_CHANGES 권고 반영:
# - agent_id / matched_keyword 라벨 *제거* (시계열 폭증 방지)
# - tool / pattern / brand / reason 모두 whitelist + 'other' fallback
# - layer 별 분모 metric kms_guard_input_total{layer} 추가 (rate% 계산용)
# ---------------------------------------------------------------------------

# 분모 metric — 각 layer 진입 횟수 (rate% / hit% 계산용)
KMS_GUARD_INPUT_TOTAL = Counter(
    "kms_guard_input_total",
    "각 가드레일 layer 진입 (검사 실행) 총 수 — D78 분모 (rate% 계산용)",
    labelnames=["layer"],
    # layer = tool_scope_filter | adversarial_checker | intent_gate
    #       | tool_guard | cross_brand_filter | safe_tool_call
)

ALLOWED_GUARD_LAYERS = frozenset(
    {
        "tool_scope_filter",
        "adversarial_checker",
        "intent_gate",
        "tool_guard",
        "cross_brand_filter",
        "safe_tool_call",
    }
)


def inc_guard_input(layer: str) -> None:
    """layer 진입 분모 inc — whitelist 강제."""
    safe = layer if layer in ALLOWED_GUARD_LAYERS else "other"
    try:
        KMS_GUARD_INPUT_TOTAL.labels(layer=safe).inc()
    except Exception:  # noqa: BLE001
        pass


# D65 — tool_scope_filter hit (post-generation 치환 발생)
KMS_TOOL_SCOPE_FILTER_HITS_TOTAL = Counter(
    "kms_tool_scope_filter_hits_total",
    "tool_scope_filter (D65 post-gen) T3 치환 발생 횟수 — D78",
    labelnames=["domain"],
    # domain = 일정 | 지출 | 메모 | 예약 | 메일 | 이메일 | 알림 | 리마인더 | 주문 | 결제 | other
)

ALLOWED_SCOPE_DOMAINS = frozenset(
    {"일정", "지출", "메모", "예약", "메일", "이메일", "알림", "리마인더", "주문", "결제"}
)


def inc_tool_scope_filter_hit(domain: str) -> None:
    """tool_scope_filter hit counter inc — domain whitelist."""
    safe = domain if domain in ALLOWED_SCOPE_DOMAINS else "other"
    try:
        KMS_TOOL_SCOPE_FILTER_HITS_TOTAL.labels(domain=safe).inc()
    except Exception:  # noqa: BLE001
        pass


# D68 — adversarial_apply hit (false-confirm 차단)
KMS_ADVERSARIAL_APPLY_HITS_TOTAL = Counter(
    "kms_adversarial_apply_hits_total",
    "adversarial_checker (D68) 패턴 매칭 + 치환 횟수 — D78",
    labelnames=["pattern"],
    # pattern = false_confirm | other
    # (현재 구현은 false_confirm 단일 패턴. 향후 확장 시 whitelist 갱신.)
)

ALLOWED_ADV_PATTERNS = frozenset({"false_confirm"})


def inc_adversarial_apply_hit(pattern: str = "false_confirm") -> None:
    """adversarial_apply hit counter inc — pattern whitelist."""
    safe = pattern if pattern in ALLOWED_ADV_PATTERNS else "other"
    try:
        KMS_ADVERSARIAL_APPLY_HITS_TOTAL.labels(pattern=safe).inc()
    except Exception:  # noqa: BLE001
        pass


# D70 — intent_gate reject (OOS 차단)
KMS_INTENT_GATE_REJECTS_TOTAL = Counter(
    "kms_intent_gate_rejects_total",
    "intent_gate (D70) OOS reject 횟수 — D78",
    labelnames=["reason"],
    # reason = oos_keyword_match | other
    # (matched_keyword 라벨은 GPT-5 권고로 제거 — high cardinality 위험)
)

ALLOWED_INTENT_REJECT_REASONS = frozenset({"oos_keyword_match"})


def inc_intent_gate_reject(reason: str = "oos_keyword_match") -> None:
    """intent_gate reject counter inc — reason whitelist."""
    safe = reason if reason in ALLOWED_INTENT_REJECT_REASONS else "other"
    try:
        KMS_INTENT_GATE_REJECTS_TOTAL.labels(reason=safe).inc()
    except Exception:  # noqa: BLE001
        pass


# D72 — tool_guard block (allowed_tools 위반 차단)
KMS_TOOL_GUARD_BLOCKS_TOTAL = Counter(
    "kms_tool_guard_blocks_total",
    "tool_guard (D72) allowed_tools 위반 차단 횟수 — D78",
    labelnames=["reason"],
    # reason = not_in_allowed | empty_allowed | other
    # (tool 라벨 제거 — high cardinality; reason 만 유지)
)

ALLOWED_TOOL_GUARD_REASONS = frozenset({"not_in_allowed", "empty_allowed"})


def inc_tool_guard_block(reason: str) -> None:
    """tool_guard block counter inc — reason whitelist."""
    safe = reason if reason in ALLOWED_TOOL_GUARD_REASONS else "other"
    try:
        KMS_TOOL_GUARD_BLOCKS_TOTAL.labels(reason=safe).inc()
    except Exception:  # noqa: BLE001
        pass


# D82-B — response_pii_filter hit (LLM 응답 본문 PII 마스킹)
# GPT-5.5 권고 (2026-05-11): type 만 라벨, agent_id 는 high cardinality 금지.
KMS_RESPONSE_PII_FILTER_HITS_TOTAL = Counter(
    "kms_response_pii_filter_hits_total",
    "response_pii_filter (D82-B) LLM 응답 본문 PII 매칭 + 마스킹 횟수",
    labelnames=["type"],
    # type = rrn | card | phone | business | email | filter_error | other
)

ALLOWED_RESPONSE_PII_TYPES = frozenset(
    {"rrn", "card", "phone", "business", "email", "filter_error"}
)


def inc_response_pii_hit(types: list[str]) -> None:
    """response_pii_filter hit counter inc — 각 hit type 별로 +1.

    types: ['rrn', 'phone', ...] — scrub_response_pii hits 리턴값 그대로.
    whitelist 외 값은 'other' 로 집계.
    """
    if not types:
        return
    for t in types:
        safe = t if t in ALLOWED_RESPONSE_PII_TYPES else "other"
        try:
            KMS_RESPONSE_PII_FILTER_HITS_TOTAL.labels(type=safe).inc()
        except Exception:  # noqa: BLE001
            pass


# D84 — strict knowledge_isolation no-evidence refusal (코드 차단).
# GPT-5.5 권고 (2026-05-13): entry 라벨 만 사용 (compose / stream). agent_id 는
# high cardinality 금지.
KMS_STRICT_NO_EVIDENCE_REFUSAL_TOTAL = Counter(
    "kms_strict_no_evidence_refusal_total",
    "strict knowledge_isolation 가 KMS no-meaningful-hit 시 LLM 호출 차단 후 "
    "중앙화된 거절 응답을 반환한 횟수 (D84).",
    labelnames=["entry"],
    # entry = compose | stream
)


# D69 — kms_rag cross-brand crosstalk drop
KMS_RAG_CROSSTALK_DROPS_TOTAL = Counter(
    "kms_rag_crosstalk_drops_total",
    "kms_rag (D69) cross-brand retrieval drop / citation refuse 횟수 — D78",
    labelnames=["stage"],
    # stage = retrieval_filter | citation_guard | tool_output | other
)

ALLOWED_CROSSTALK_STAGES = frozenset(
    {"retrieval_filter", "citation_guard", "tool_output"}
)


def inc_crosstalk_drop(stage: str) -> None:
    """cross-brand drop counter inc — stage whitelist."""
    safe = stage if stage in ALLOWED_CROSSTALK_STAGES else "other"
    try:
        KMS_RAG_CROSSTALK_DROPS_TOTAL.labels(stage=safe).inc()
    except Exception:  # noqa: BLE001
        pass


# D74 — safe_tool_call shadow compare
KMS_SAFE_TOOL_CALL_COMPARE_TOTAL = Counter(
    "kms_safe_tool_call_compare_total",
    "safe_tool_call (D74) FF shadow/enforce compare 횟수 — D78",
    labelnames=["mode", "would_block"],
    # mode = off | shadow | enforce | other
    # would_block = true | false
    # (tool 라벨 제거 — high cardinality)
)

ALLOWED_FF_MODES = frozenset({"off", "shadow", "enforce"})


def inc_safe_tool_call_compare(mode: str, would_block: bool) -> None:
    """safe_tool_call compare counter inc — mode whitelist."""
    safe_mode = mode if mode in ALLOWED_FF_MODES else "other"
    safe_block = "true" if would_block else "false"
    try:
        KMS_SAFE_TOOL_CALL_COMPARE_TOTAL.labels(
            mode=safe_mode, would_block=safe_block
        ).inc()
    except Exception:  # noqa: BLE001
        pass


# D74-canary — canary bucket 분포 + effective mode
# GPT-5.5 §4 권고 — bucket=inside/outside/missing/n_a, decision=off/shadow/enforce.
# agent_id 는 라벨 X (cardinality 폭발 방지).
# D82-C P1: source 라벨 추가 — engine 9 site 분리 (rft / plan_* / scheduled /
# sop_inject / execution_policy_guard / pr_e4_audit). scheduled 의 stale-context
# missing 과 실제 agent_id 추출 실패 missing 을 alert/dashboard 에서 분리 가능
# (GPT-5.5 사전 verdict §3 요구).
KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL = Counter(
    "kms_safe_tool_call_canary_bucket_total",
    "safe_tool_call (D74-canary) bucket 분포 + decision + source — D82-C 가시성",
    labelnames=["bucket", "decision", "source"],
    # bucket = inside | outside | missing | n_a | other
    # decision = off | shadow | enforce | other
    # source = rft | plan_pre_clarify | plan_serial | plan_parallel |
    #          plan_serial_fallback | scheduled | sop_inject |
    #          execution_policy_guard | pr_e4_audit | other
    # D82-C P1 / D82-residual #B: fallback 단일화 — 인자 누락 + whitelist 외 모두 "other".
)

ALLOWED_CANARY_BUCKETS = frozenset({"inside", "outside", "missing", "n_a"})

# D82-C P1 — engine _safe_tool_call source whitelist (9 site).
# D82-residual #B (2026-05-13) — fallback label 단일화: "unknown" 제거,
# 인자 누락 + 신규/임의 source 모두 "other" 로 통일 (GPT-5.5 verdict §B 권고).
ALLOWED_SAFE_TOOL_CALL_SOURCES = frozenset({
    "rft",
    "plan_pre_clarify",
    "plan_serial",
    "plan_parallel",
    "plan_serial_fallback",
    "scheduled",
    "sop_inject",
    "execution_policy_guard",
    "pr_e4_audit",
})

# D82-residual #B — fallback label 단일 source-of-truth.
# 인자 누락 (default) + ALLOWED 외 모두 동일 label 로 집계 — Prometheus
# cardinality / alert denominator / dashboard / test fixture 정합.
CANARY_SOURCE_FALLBACK = "other"


def inc_safe_tool_call_canary_bucket(
    bucket: str, decision: str, source: str = CANARY_SOURCE_FALLBACK
) -> None:
    """canary bucket counter inc — bucket/decision/source whitelist.

    D82-C P1: ``source`` 라벨 추가. ALLOWED_SAFE_TOOL_CALL_SOURCES 외 →
    ``CANARY_SOURCE_FALLBACK`` ("other").

    D82-residual #B: fallback 단일화 — 인자 누락 default 도 "other".
    "unknown" / "other" 의미 분리를 *제거* 하고 모든 fallback 을 하나로 통일.
    cardinality = 5 buckets × 4 decisions × ~10 sources = 200 — 안전.
    """
    safe_bucket = bucket if bucket in ALLOWED_CANARY_BUCKETS else "other"
    safe_decision = decision if decision in ALLOWED_FF_MODES else "other"
    safe_source = (
        source
        if source in ALLOWED_SAFE_TOOL_CALL_SOURCES
        else CANARY_SOURCE_FALLBACK
    )
    try:
        KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket=safe_bucket, decision=safe_decision, source=safe_source
        ).inc()
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "ALLOWED_ADV_PATTERNS",
    "ALLOWED_CANARY_BUCKETS",
    "ALLOWED_CROSSTALK_STAGES",
    "ALLOWED_FATAL_REASONS",
    "ALLOWED_FF_MODES",
    "ALLOWED_GUARD_LAYERS",
    "ALLOWED_INTENT_REJECT_REASONS",
    "ALLOWED_REBIND_SITES",
    "ALLOWED_REBIND_TOPICS",
    "ALLOWED_SAFE_TOOL_CALL_SOURCES",
    "ALLOWED_SCOPE_DOMAINS",
    "ALLOWED_TOOL_GUARD_REASONS",
    "CANARY_SOURCE_FALLBACK",
    "KMS_ADVERSARIAL_APPLY_HITS_TOTAL",
    "KMS_ES_INDEX_FAILURE_TOTAL",
    "KMS_ES_INDEX_RETRY_TOTAL",
    "KMS_ES_INDEX_SUCCESS_TOTAL",
    "KMS_GUARD_INPUT_TOTAL",
    "KMS_INTENT_GATE_REJECTS_TOTAL",
    "KMS_MAINTENANCE_BLOCKED_REQUESTS_TOTAL",
    "KMS_MAINTENANCE_GATE_ON",
    "KMS_PAYLOAD_SALVAGE_TOTAL",
    "KMS_RAG_CROSSTALK_DROPS_TOTAL",
    "KMS_SAFE_TOOL_CALL_COMPARE_TOTAL",
    "KMS_TOOL_GUARD_BLOCKS_TOTAL",
    "KMS_TOOL_SCOPE_FILTER_HITS_TOTAL",
    "KMS_PIPELINE_MERGE_PART_RETRY_TOTAL",
    "KMS_PIPELINE_STAGE_COUNT_TOTAL",
    "KMS_PIPELINE_STAGE_DURATION_SECONDS",
    "KMS_PIPELINE_STAGE_FAILURE_TOTAL",
    "KMS_RLS_VIOLATION_TOTAL",
    "KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL",
    "KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL",
    "KMS_WORKER_SELF_CHECK_FATAL_TOTAL",
    "REBIND_SITE_BLOCK_PARSED",
    "REBIND_SITE_BLOCK_PART_READY",
    "REBIND_SITE_DOCUMENT_PROCESSOR",
    "REBIND_SITE_MERGE_PART_BLOCKED",
    "REBIND_SITE_SEQUENTIAL",
    "SALVAGE_OP_BLOCKS_FULL_TO_BLOCKS",
    "SALVAGE_OP_BLOCK_META_JSON",
    "SALVAGE_OP_CHUNK_META_TO_BASE",
    "SALVAGE_OP_MERGED_METADATA_TO_BLOCKS",
    "classify_es_error",
    "inc_adversarial_apply_hit",
    "inc_crosstalk_drop",
    "inc_guard_input",
    "inc_intent_gate_reject",
    "inc_kms_payload_salvage",
    "inc_kms_pipeline_merge_part_retry",
    "inc_safe_tool_call_canary_bucket",
    "inc_safe_tool_call_compare",
    "inc_tool_guard_block",
    "inc_tool_scope_filter_hit",
    "inc_kms_pipeline_stage_count",
    "inc_kms_pipeline_stage_failure",
    "inc_kms_worker_rebind_failure",
    "inc_kms_worker_self_check_fatal",
    "inc_maintenance_blocked",
    "observe_kms_pipeline_stage_duration",
    "set_maintenance_gate",
]

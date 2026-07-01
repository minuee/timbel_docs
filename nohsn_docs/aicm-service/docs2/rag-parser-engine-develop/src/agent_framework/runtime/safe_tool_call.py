"""D74 (2026-05-11) — engine.py 의 도구 호출 7+2 site 통합 wrapper helper.

# 결함 배경
D73 deep-dive #3 — engine.py 의 `self.tools.call(...)` 직접 호출 site 7+2 곳
(2009, 2848, 3103, 3299, 3437, 5105, 5148, 5212, 5793). 각 site 가 같은 D72
choke point 가드를 통과하긴 하나, *추가 가드 (op_type evidence 검증 / audit
log / sender_context 진입점)* 가 site 별로 흩어져 일관성이 깨지고 향후 보강
(D74b 사전 거절 / sender_context 통합) 시 산만한 수정이 발생.

# 설계 (사전 GPT-5 verdict A 권고)
- *통합* + *관찰* + *회귀 0*. 기존 backend 재작성 금지 (사용자 절칙).
- 신규 wrapper = ``_safe_tool_call`` (engine method). 기존 ``_guarded_tool_call``
  (ExecutionPolicyGuard wrapper, line 5118) 와 이름 충돌 회피.
- ``KMS_FF_GUARD_UNIFY_TOOL_CALL`` env tristate:
  - ``off`` (default) : byte-equal 동작 — 옛 path 그대로. wrapper 통과만.
  - ``shadow``        : 옛 path = primary 결과. 부가 가드는 *log only* (would_block
    detect → metric/log, 차단 X). 24-48h 회귀 사전 감지.
  - ``enforce``       : 옛 path 결과 받음. write/delete 도구 ∧ confirm_id 미보유 ∧
    *성공 dict* → 결과 강제 다운그레이드 (`success=False, error='unsafe_needs_confirm'`).
    *예외 / 비-dict / 이미 실패* 는 그대로 패스. *사전 차단은 X* (D74b 별도 라운드).

# D74-canary (2026-05-12) — agent_id hash 분기
사전 GPT-5.5 권고 GO_WITH_CHANGES — base=enforce 일 때 ``KMS_FF_GUARD_CANARY_PERCENT``
(0~100) 기준으로 agent_id 일부만 enforce, 나머지는 shadow fallback.
- base 'off' → off (canary 무관)
- base 'shadow' → shadow (canary 무관)
- base 'enforce' ∧ agent_id 누락/공백 → shadow fallback + missing_agent_id metric
- base 'enforce' ∧ canary 안 → enforce
- base 'enforce' ∧ canary 밖 → shadow
hashing = sha256(agent_id)[:8] hex → int → mod 100. **server-issued agent_id only**.

# op_type 추론
도구 description 에 op_type 메타가 없으므로 *이름 suffix* 기반 휴리스틱:
- ``*.delete*`` / ``*.create*`` / ``*.update*`` / ``*.send`` / ``*.add_*`` / ``*.set_*``
  / ``*.publish`` → write
- 그 외 → read

호출자가 ``op_type`` 인자로 override 가능 (테스트/명시 case).

# confirm 증거 키
``args`` 안에 다음 중 하나라도 *truthy* 면 confirm 보유:
- ``confirm_id`` (canonical)
- ``confirmation_id``
- ``confirm_token``

shadow 기간 실데이터 기반으로 키 집합 확정 후 enforce 전환.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any
from uuid import UUID

from src.common.logging import get_logger

log = get_logger(__name__)


# FF tristate values.
FF_OFF = "off"
FF_SHADOW = "shadow"
FF_ENFORCE = "enforce"
_VALID_MODES = {FF_OFF, FF_SHADOW, FF_ENFORCE}

# D74-canary — bucket labels (low-cardinality).
CANARY_BUCKET_INSIDE = "inside"
CANARY_BUCKET_OUTSIDE = "outside"
CANARY_BUCKET_MISSING = "missing"
CANARY_BUCKET_N_A = "n_a"  # base != enforce 인 경우 canary 무관

# write op_type 추론 — 도구 이름 suffix / token.
# GPT-5 사전 권고: shadow 기간 분포 수집 후 보정.
_WRITE_SUFFIXES = (
    ".delete",
    ".create",
    ".update",
    ".add",
    ".add_watch",
    ".set",
    ".send",
    ".publish",
    ".cancel",
    ".remove",
    ".write",
    ".save",
    ".upsert",
    ".put",
)

# confirm_id 동의어 — GPT-5 사전 권고. shadow 기간 실데이터로 추가/축소.
_CONFIRM_KEYS = ("confirm_id", "confirmation_id", "confirm_token")


def get_ff_mode() -> str:
    """``KMS_FF_GUARD_UNIFY_TOOL_CALL`` env 읽기 — base mode (canary 무관).

    잘못된 값은 ``off`` 로 fallback (안전). canary 분기는
    :func:`get_ff_mode_for_agent` 사용.
    """
    raw = os.environ.get("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_OFF).strip().lower()
    if raw not in _VALID_MODES:
        return FF_OFF
    return raw


def get_canary_percent() -> int:
    """``KMS_FF_GUARD_CANARY_PERCENT`` env 읽기 — 0~100.

    잘못된 값 / 음수 / 100 초과 → clamp [0, 100]. 기본 0 (canary 비활성 = base
    enforce 일 때 모두 shadow fallback). GPT-5.5 권고 §1 — invalid 처리.
    """
    raw = os.environ.get("KMS_FF_GUARD_CANARY_PERCENT", "0").strip()
    try:
        pct = int(raw)
    except (ValueError, TypeError):
        return 0
    if pct < 0:
        return 0
    if pct > 100:
        return 100
    return pct


def _normalize_agent_id(value: Any) -> str | None:
    """D82-C P1 — agent_id normalize helper. ``str`` 또는 ``uuid.UUID`` 만 허용.

    GPT-5.5 사전 verdict §1: ``hasattr(.hex)``, ``bytes`` 등 광범위 허용 금지.
    *허용 namespace 두 가지*:
    - ``str`` : ``strip()`` 후 truthy → 그대로 반환 (기존 hash 안정성 보존).
    - ``uuid.UUID`` : ``str(uuid)`` (canonical "xxxxxxxx-...-xxxxxxxxxxxx" 형식) 반환.

    그 외 (``None``, ``int``, ``bytes``, ``list``, ``dict``, custom object) → ``None``.

    AgentContext.agent_id 가 ``UUID`` 인스턴스라서 기존 ``isinstance(_, str)``
    검사가 False → 100% missing 분류 (D80 결함). 본 helper 가 유일한
    정규화 진입점이며, ``_is_valid_agent_id`` / canary hashing 모두 이걸 거침.

    Returns
    -------
    str | None : 정규화된 agent_id 또는 ``None`` (invalid).
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    # int / float / bytes / list / dict / custom object → 거부.
    return None


def _is_valid_agent_id(agent_id: Any) -> bool:
    """server-issued agent_id 유효성 — ``_normalize_agent_id`` 통과 여부.

    GPT-5.5 §2 — 누락 처리. D82-C P1: UUID 인스턴스도 허용 (정규화 후 str).
    *validate/hash 경로 분기 X* — 동일 normalize 입력 사용으로 재발 방지.
    """
    return _normalize_agent_id(agent_id) is not None


def _is_canary_enabled(agent_id: Any, percent: int) -> bool:
    """agent_id sha256 hash 기반 consistent hashing.

    D82-C P1: 호출자가 *normalize 후* str 을 전달하는 게 정상이지만,
    안전망으로 본 함수도 normalize 한 번 더 적용 (UUID 직접 전달 호환).

    percent >= 100 → True (모든 트래픽). percent <= 0 → False (canary 비활성).
    그 외 → ``sha256(agent_id)[:8]`` hex int mod 100 < percent.

    분포 균등성 — sha256 첫 32bit. agent_id 가 다양하면 균등. 단일 agent 가
    트래픽 대부분 차지하면 실제 비율 != percent (GPT-5.5 §1 경고).
    """
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    normalized = _normalize_agent_id(agent_id)
    if normalized is None:
        # invalid → outside (canary 우회 방지). 호출자가 _is_valid_agent_id
        # 로 사전 분기하는 게 정상이지만, 직접 호출 안전망.
        return False
    h = int(hashlib.sha256(normalized.encode()).hexdigest()[:8], 16)
    return (h % 100) < percent


def canary_bucket(agent_id: Any, percent: int) -> str:
    """agent_id + percent → bucket label (low-cardinality metric용).

    Returns
    -------
    "inside" / "outside" / "missing".
    """
    if not _is_valid_agent_id(agent_id):
        return CANARY_BUCKET_MISSING
    if _is_canary_enabled(agent_id, percent):
        return CANARY_BUCKET_INSIDE
    return CANARY_BUCKET_OUTSIDE


def get_ff_mode_for_agent(agent_id: Any = None) -> tuple[str, str]:
    """canary 분기 적용 최종 mode 결정.

    Returns
    -------
    (effective_mode, bucket).
    - effective_mode ∈ {"off", "shadow", "enforce"}.
    - bucket ∈ {"inside", "outside", "missing", "n_a"}.

    Rules:
    - base 'off' → ("off", "n_a") — canary 무관.
    - base 'shadow' → ("shadow", "n_a") — canary 무관.
    - base 'enforce' ∧ agent_id 누락 → ("shadow", "missing") — 조용한 우회 방지
      위해 metric/log 로 가시성 확보 (호출자 책임).
    - base 'enforce' ∧ canary inside → ("enforce", "inside").
    - base 'enforce' ∧ canary outside → ("shadow", "outside") — fallback.
    """
    base = get_ff_mode()
    if base != FF_ENFORCE:
        return base, CANARY_BUCKET_N_A

    percent = get_canary_percent()
    if not _is_valid_agent_id(agent_id):
        return FF_SHADOW, CANARY_BUCKET_MISSING
    if _is_canary_enabled(agent_id, percent):
        return FF_ENFORCE, CANARY_BUCKET_INSIDE
    return FF_SHADOW, CANARY_BUCKET_OUTSIDE


def infer_op_type(tool_name: str) -> str:
    """tool 이름 suffix 기반 op_type 추론.

    Returns
    -------
    ``"write"`` 또는 ``"read"``.
    """
    if not tool_name:
        return "read"
    name = tool_name.lower()
    for suf in _WRITE_SUFFIXES:
        if name.endswith(suf) or suf + "_" in ("." + name + "_"):
            return "write"
    # split by '.' last segment 가 write verb 인 경우.
    last = name.rsplit(".", 1)[-1]
    if last in {
        "delete", "create", "update", "add", "send", "publish",
        "cancel", "remove", "write", "save", "upsert", "put", "set",
        "add_watch", "delete_all", "delete_duplicates",
    }:
        return "write"
    if last.startswith(("add_", "set_", "create_", "delete_", "update_", "send_")):
        return "write"
    return "read"


def has_confirm_evidence(tool_args: Any) -> bool:
    """``tool_args`` dict 안에 confirm_id 동의어 키가 *truthy* 면 True.

    dict 가 아니면 False (테스트/edge case 안전).
    """
    if not isinstance(tool_args, dict):
        return False
    for k in _CONFIRM_KEYS:
        v = tool_args.get(k)
        if v:
            return True
    return False


def emit_canary_bucket(
    *, bucket: str, decision: str, source: str = "unknown"
) -> None:
    """D74-canary — canary bucket 분포 metric emit.

    GPT-5.5 §4 권고 — bucket 분포 visibility 필수. high-cardinality 회피
    (agent_id 라벨 X). bucket ∈ {inside, outside, missing, n_a},
    decision ∈ {off, shadow, enforce}.

    D82-C P1: ``source`` 라벨 추가 — engine 9 site 별 호출 경로 분리. GPT-5.5
    사전 verdict §3 요구사항. scheduled (user-bound agent 없음) 의 missing 과
    실제 agent_id 추출 실패 missing 을 alert/dashboard 에서 분리 가능.
    """
    try:
        from src.common.metrics import inc_safe_tool_call_canary_bucket
        inc_safe_tool_call_canary_bucket(
            bucket=bucket, decision=decision, source=source
        )
    except Exception:  # noqa: BLE001
        pass


def emit_shadow_compare(
    *,
    tool: str,
    op_type: str,
    would_block: bool,
    mode: str,
) -> None:
    """D78 — shadow 모드 비교 결과 metric emit + structured log.

    GPT-5 사전 권고 §4: shadow path 외부 부작용 없음 보장 — log + metric 만.
    sampling 은 호출자 (engine._safe_tool_call) 가 ``KMS_FF_GUARD_UNIFY_TOOL_CALL_SHADOW_SAMPLING``
    적용 후 본 함수 호출.

    Parameters
    ----------
    tool : 도구 이름 (whitelist 안 함 — log 만 사용. metric label 은 mode/would_block).
    op_type : "read" | "write".
    would_block : enforce 였다면 차단됐는지 여부.
    mode : "off" | "shadow" | "enforce".
    """
    try:
        from src.common.metrics import inc_safe_tool_call_compare, inc_guard_input

        inc_guard_input("safe_tool_call")
        inc_safe_tool_call_compare(mode=mode, would_block=would_block)
    except Exception:  # noqa: BLE001
        pass
    # structured log — 운영자가 grep / Loki 로 분포 확인.
    log.info(
        "tool_call_safe_compare",
        tool=tool,
        op_type=op_type,
        would_block=would_block,
        mode=mode,
    )


def shadow_sampling_keep() -> bool:
    """D78 — shadow 모드 sampling rate (default 1.0 = 모두 기록).

    ``KMS_FF_GUARD_UNIFY_TOOL_CALL_SHADOW_SAMPLING`` env 가 0.0~1.0 사이.
    잘못된 값은 1.0 (모두 기록).
    """
    raw = os.environ.get("KMS_FF_GUARD_UNIFY_TOOL_CALL_SHADOW_SAMPLING", "1.0")
    try:
        rate = float(raw)
    except (ValueError, TypeError):
        rate = 1.0
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    # uniform random sampling — random.random() ∈ [0.0, 1.0).
    import random
    return random.random() < rate


def downgrade_to_unsafe(
    *,
    tool: str,
    op_type: str,
) -> dict[str, Any]:
    """enforce 모드의 confirm 미보유 다운그레이드 결과 dict.

    LLM 이 다음 턴에 "확인이 필요해요" 류로 안내하도록 user_message 동봉.
    """
    return {
        "success": False,
        "error": "unsafe_needs_confirm",
        "tool": tool,
        "op_type": op_type,
        "user_message": (
            "안전을 위해 이 작업은 한 번 더 확인이 필요해요. 확인 후 다시"
            " 진행해 드릴게요."
        ),
    }


__all__ = [
    "CANARY_BUCKET_INSIDE",
    "CANARY_BUCKET_MISSING",
    "CANARY_BUCKET_N_A",
    "CANARY_BUCKET_OUTSIDE",
    "FF_ENFORCE",
    "FF_OFF",
    "FF_SHADOW",
    "_normalize_agent_id",
    "canary_bucket",
    "downgrade_to_unsafe",
    "emit_canary_bucket",
    "emit_shadow_compare",
    "get_canary_percent",
    "get_ff_mode",
    "get_ff_mode_for_agent",
    "has_confirm_evidence",
    "infer_op_type",
    "shadow_sampling_keep",
]

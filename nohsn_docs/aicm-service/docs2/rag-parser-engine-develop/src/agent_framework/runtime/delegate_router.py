"""Agent delegate router — spec §3.

intent_gate out_of_domain 시 LLM 으로 위임 후보 선택 + target agent 의
turn 호출.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import UUID

from src.common.config import settings
from src.common.logging import get_logger
from src.common.llm.base import LLMRequest, LLMTask
from src.common.llm.router import llm_router

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# engine_turn — module-level async generator (circular import 방지용 lazy import).
# 테스트에서 patch("...delegate_router.engine_turn", ...) 로 교체 가능.
# ---------------------------------------------------------------------------
async def engine_turn(
    *,
    agent_ctx: Any,
    user_query: str,
    session_id: str,
    delegation_depth: int = 0,
) -> AsyncIterator[dict[str, Any]]:  # type: ignore[return]
    """Lazy-import wrapper around AgentEngine.turn.

    실 운영 경로: AgentEngine 싱글턴 인스턴스를 통해 turn() 을 호출.
    agent_ctx 가 이미 engine 인스턴스를 보유한 경우에는 agent_ctx.engine.turn()
    경로를 사용하고, 아닐 경우 기본 engine 모듈의 default_engine 을 통해 호출.

    위임 시 tenant_id / user_message 등은 agent_ctx 에서 파생.
    """
    # AgentEngine 인스턴스 획득 — get_agent_engine() 헬퍼 사용 (DI 와 동일 path).
    from src.agent_framework.api.dependencies import get_agent_engine  # noqa: PLC0415

    _engine_inst = await get_agent_engine()

    # turn() 은 AsyncGenerator — yield 로 relay
    _tenant_id = str(getattr(agent_ctx, "tenant_id", ""))
    _user_message = user_query
    async for ev in _engine_inst.turn(
        session_id=session_id,
        tenant_id=_tenant_id,
        user_message=_user_message,
        agent_context=agent_ctx,
        delegation_depth=delegation_depth,
    ):
        yield ev


@dataclass
class DelegateSelection:
    target_agent_id: UUID
    target_agent_name: str
    confidence: float
    reason: str


_PROMPT_TEMPLATE = """사용자 질문: {query}

현 봇: {current_name} — {current_desc}
이 질문은 현 봇의 도메인 외입니다. 다음 위임 후보 중 가장 적합한 1개를 선택:

{candidates_block}

JSON 응답:
{{"best_agent_id": "<uuid>", "confidence": 0~1, "reason": "한 문장"}}

위임 적합 후보 없으면: {{"best_agent_id": null, "confidence": 0, "reason": "..."}}
"""


def _format_candidates(candidates: list[Any]) -> str:
    parts = []
    for i, c in enumerate(candidates, 1):
        g = (getattr(c, "guidelines_md", None) or "")[:200]
        parts.append(
            f"[{i}] id={c.id} name={c.name}\n"
            f"    description={getattr(c, 'description', '') or ''}\n"
            f"    guidelines: {g}"
        )
    return "\n\n".join(parts)


async def _load_delegate_candidates(
    *,
    db: Any,
    delegate_ids: list[UUID],
    tenant_id: UUID,
) -> list[Any]:
    """spec §10.5 M1 — same tenant + is_active=True 만 반환.

    cross-tenant agent 가 delegate_to_agent_ids 에 있어도 조회 단계에서 제외.
    inactive / soft-deleted 도 제외.
    """
    if not delegate_ids:
        return []
    from sqlalchemy import select
    from src.core.models.agent import Agent

    stmt = select(Agent).where(
        Agent.id.in_(delegate_ids),
        Agent.tenant_id == tenant_id,
        Agent.is_active.is_(True),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _select_delegate_target(
    *,
    user_query: str,
    current_agent: Any,
    candidates: list[Any],
) -> DelegateSelection | None:
    """spec §3 — LLM 후보 선택. confidence>=threshold 시 DelegateSelection 반환."""
    if not candidates:
        return None

    prompt = _PROMPT_TEMPLATE.format(
        query=user_query,
        current_name=getattr(current_agent, "name", ""),
        current_desc=getattr(current_agent, "description", "") or "",
        candidates_block=_format_candidates(candidates),
    )
    try:
        resp = await llm_router.route(
            task=LLMTask.CHAT_INTENT,
            request=LLMRequest(
                prompt=prompt,
                system_prompt="당신은 agent 위임 라우터입니다. JSON 으로만 응답.",
                max_tokens=200,
                temperature=0.1,
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("delegate_skipped_llm_call_failed",
                    error=str(e), consumer_role="delegate")
        return None

    # markdown code fence (```json ... ```) 또는 plain JSON 모두 파싱.
    raw = (getattr(resp, "text", "") or "").strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, AttributeError, TypeError):
        # fence 안의 첫 { ... } object 추출 시도
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            log.warning("delegate_skipped_llm_parse",
                        text_preview=raw[:100],
                        consumer_role="delegate")
            return None
        try:
            data = json.loads(m.group(0))
        except (json.JSONDecodeError, AttributeError, TypeError):
            log.warning("delegate_skipped_llm_parse",
                        text_preview=raw[:100],
                        consumer_role="delegate")
            return None

    best = data.get("best_agent_id")
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(data.get("reason") or "")

    if not best:
        log.info("delegate_skipped_no_match",
                 confidence=confidence, reason=reason,
                 consumer_role="delegate")
        return None
    if confidence < settings.DELEGATE_CONFIDENCE_THRESHOLD:
        log.info("delegate_skipped_low_confidence",
                 confidence=confidence,
                 threshold=settings.DELEGATE_CONFIDENCE_THRESHOLD,
                 consumer_role="delegate")
        return None

    best_str = str(best).strip()
    try:
        target_id = UUID(best_str)
        target = next((c for c in candidates if c.id == target_id), None)
    except (ValueError, TypeError):
        # LLM 이 UUID 마지막 글자 truncate 한 경우 prefix match try
        target = None
        for c in candidates:
            cid = str(c.id)
            if cid.startswith(best_str) or best_str.startswith(cid[:35]):
                target = c
                target_id = c.id
                log.warning("delegate_uuid_prefix_match_recovery",
                            best=best_str, matched_id=cid,
                            consumer_role="delegate")
                break
    if target is None:
        log.warning("delegate_skipped_uuid_not_in_candidates",
                    best=best_str, consumer_role="delegate")
        return None

    return DelegateSelection(
        target_agent_id=target_id,
        target_agent_name=getattr(target, "name", ""),
        confidence=confidence,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# _try_delegate — spec §4 + §5 + §10.5 M4
# ---------------------------------------------------------------------------
async def _try_delegate(
    *,
    selection: DelegateSelection,
    user_query: str,
    session_id: str,
    delegation_depth: int,
    target_agent: Any,
) -> AsyncIterator[dict[str, Any]]:  # type: ignore[return]
    """spec §4 + §5 + §10.5 M4 — prefix stream + target turn 재귀.

    yield 순서:
      1. delegate event (M4 metadata)
      2. prefix token "이 질문은 *X* 이 답변드립니다."
      3. target turn 의 events 통과 — start/intent/delegate 는 suppress.
      4. target exception 시 error + done.
    """
    # 1) delegate event (M4)
    yield {
        "event": "delegate",
        "data": {
            "to_agent_id": str(selection.target_agent_id),
            "to_agent_name": selection.target_agent_name,
            "reason": selection.reason,
            "confidence": selection.confidence,
        },
    }

    # 2) prefix token
    yield {
        "event": "token",
        "data": {"text": f"이 질문은 *{selection.target_agent_name}* 이 답변드립니다.\n\n"},
    }

    # 3) target turn 재귀 호출 (engine_turn)
    try:
        async for event in engine_turn(
            agent_ctx=target_agent,
            user_query=user_query,
            session_id=session_id,
            delegation_depth=delegation_depth + 1,
        ):
            ev_name = (
                event.get("event") if isinstance(event, dict)
                else getattr(event, "event", None)
            )
            # spec §10.5 M4 — start/intent/delegate suppress
            if ev_name in ("start", "intent", "delegate"):
                continue
            yield event
    except Exception as e:  # noqa: BLE001
        log.error(
            "delegate_target_exception_after_prefix",
            target_agent_id=str(selection.target_agent_id),
            error=str(e), consumer_role="delegate",
        )
        yield {"event": "error", "data": {"message": f"위임 답변 생성 중 오류: {e}"}}
        yield {"event": "done"}

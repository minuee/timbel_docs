"""SOP context block builder — path-독립 helper.

#76 (2026-05-19) — engine.py 와 tool_calling_loop.py 가 동일 SOP inject
로직 공유. 모든 답변 LLM path 가 *같은* SOP block 으로 system prompt 받게
한다.

설계 원칙:
- *fail-open*: timeout/exception 시 빈 문자열 반환 (caller 가 무시). KMS
  장애가 답변 장애로 전파되지 않게.
- *raw markdown 통과* ([feedback_kms_lukas_separation]): SOP chunks 요약/
  재해석 X. 헤더 + 본문 그대로.
- *상수화* ([feedback_no_hardcoding_first_principle]): top_k / timeout 은
  ``sop_inject.py`` 의 env-override helper 사용.

GPT-5.5 post-commit verdict (2026-05-19) 권고 반영:
- §1 kill-switch path 독립: ``is_sop_rag_enabled_default_on()`` 가 helper
  진입부에서 검사. tool_calling_loop 가 engine method 우회해도 동일.
- §2 prefetch + fetch *전체* 작업에 single ``asyncio.wait_for`` (total budget).
- §3 ``extra_pre_used_tokens`` 인자 — caller path 별 static base/tools_doc
  비용 누락 방지.
- §4 final hard cap 복원 — estimator 오차로 system 한도 초과 시 후방 chunk
  제거 (failure_response_patterns 는 보존).
- §5 sop_scope 가 최종적으로 빈 경우 즉시 return — knowledge isolation 안전.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from src.agent_framework.runtime.sop_inject import (
    DEFAULT_SYSTEM_BUDGET_TOKENS,
    ENGINE_SYSTEM_OVERHEAD_TOKENS,
    SopInjectLayer,
    estimate_tokens,
    get_sop_inject_timeout_ms,
    get_sop_inject_top_k,
    is_sop_rag_enabled_default_on,
)
from src.common.logging import get_logger

log = get_logger(__name__)


SOP_BLOCK_HEADER = "[SOP CONTEXT — agent 절차/거절 정책/실패 패턴]"
SOP_BLOCK_FOOTER = "[/SOP CONTEXT]"


def _render_block(chunks: list[Any]) -> str:
    """SOP chunks → markdown block 문자열. whitespace-only chunk 제외.

    failure_response_patterns chunk 는 SopInjectLayer 가 1번 chunk 로 보장
    (deterministic include). 본 함수는 *순서 그대로* 출력.
    """
    lines: list[str] = [SOP_BLOCK_HEADER]
    appended = 0
    for c in chunks:
        text = (getattr(c, "text", "") or "").strip()
        if not text:
            continue
        head = (getattr(c, "heading", "") or "").strip()
        tag = (
            "[failure_response_patterns]"
            if getattr(c, "is_failure_pattern", False)
            else ""
        )
        if head:
            lines.append(f"## {head} {tag}".rstrip())
        elif tag:
            lines.append(tag)
        lines.append(text)
        appended += 1
    if appended == 0:
        return ""
    lines.append(SOP_BLOCK_FOOTER)
    return "\n\n".join(lines).strip()


def _apply_final_hard_cap(
    block: str, chunks: list[Any], cap: int
) -> str:
    """final hard cap (GPT-5.5 verdict §4 복원).

    greedy packing 후 최종 block 이 system 한도 초과면 후방 chunk 부터 제거.
    failure_response_patterns chunk (보통 1번) 는 보존 — 항상 1개 이상 남김.

    GPT-5.5 final verdict §3 추가: ``cap <= 0`` 또는 단일 chunk 도 cap 초과
    시 빈 문자열 반환 — system 한도 보호 (oversized chunk 가 prompt 깨뜨림 방지).
    """
    if not chunks:
        return block
    if cap <= 0:
        # budget 자체가 음수 — caller path 의 다른 prompt 가 이미 한도 채움.
        # SOP block 은 통째로 drop (system_prompt 안전 우선).
        return ""
    cur = list(chunks)
    while estimate_tokens(block) > cap and len(cur) > 1:
        cur.pop()
        block = _render_block(cur)
        if not block:
            break
    # 마지막 chunk 1개도 cap 초과면 drop (over-stuff 방지).
    if estimate_tokens(block) > cap:
        return ""
    return block


async def _build_chunks_with_timeout(
    *,
    sop_inject_layer: SopInjectLayer,
    agent_id: UUID,
    user_message: str,
    top_k: int,
    destructive: bool,
    guidelines_md: str,
    sop_scope: list[UUID],
    system_budget_tokens: int,
    pre_used: int,
) -> list[Any]:
    """prefetch + fetch_chunks 를 *순차* 호출. caller 가 total timeout
    적용. 본 함수 자체는 timeout 무관."""
    # prefetch — failure_response_patterns 캐시. 실패해도 silent (fetch 진행).
    try:
        await sop_inject_layer.prefetch(
            agent_id, guidelines_md, sop_scope
        )
    except Exception:  # noqa: BLE001
        pass
    return await sop_inject_layer.fetch_chunks(
        agent_id,
        user_message,
        top_k=top_k,
        destructive=destructive,
        guidelines_md=guidelines_md,
        system_budget_tokens=system_budget_tokens,
        pre_used_tokens=pre_used,
    )


async def build_sop_context_block(
    *,
    sop_inject_layer: SopInjectLayer,
    agent_ctx: Any,
    user_message: str,
    destructive: bool = False,
    extra_pre_used_tokens: int = 0,
) -> str:
    """SOP context block 빌드 — fail-open helper.

    Args:
        sop_inject_layer: caller 가 lazy init 한 SopInjectLayer.
        agent_ctx: AgentContext 또는 dict-like. None 이면 즉시 "" 반환.
        user_message: 검색 query 로 그대로 사용 (rewrite X — KMS 분리 절칙).
        destructive: True 시 ``SopInjectLayer.fetch_chunks`` 내부에서 후보
            폭을 20 으로 확장 (전달된 top_k 인자 override). 실제 inject 는
            여전히 budget 안 cap 적용.
        extra_pre_used_tokens: caller path 의 static base (tool_calling_loop 의
            tools_doc + _SYSTEM_BASE 등) token 비용. budget 계산에 합산.

    Returns:
        ``[SOP CONTEXT ...] ... [/SOP CONTEXT]`` block 문자열. 다음 케이스
        모두 빈 문자열 반환 (caller 가 무시 — fail-open):
            - kill-switch off (``FEATURE_SOP_RAG=false``)
            - agent_ctx None / agent_id 없음
            - 최종 sop_scope 빈 (sop_repo_ids / primary / fallback 모두 빈)
            - SOP search timeout (env SOP_INJECT_TIMEOUT_MS, default 1500ms —
              prefetch + fetch *전체* total budget)
            - SOP search exception
            - chunks 0
            - 모든 chunks whitespace-only

    Notes:
        - failure_response_patterns chunk 는 SopInjectLayer 가 deterministic
          include — 기존 동작 유지.
        - heading 만 있고 본문 없는 chunk skip (GPT-5.5 권고).
        - final hard cap 으로 estimator 오차에도 system 한도 안 보장.
    """
    # GPT-5.5 verdict §1: kill-switch path 독립.
    if not is_sop_rag_enabled_default_on():
        return ""
    if agent_ctx is None:
        return ""
    agent_id = getattr(agent_ctx, "agent_id", None)
    if agent_id is None:
        return ""

    # scope: sop_repo_ids 우선, 빈 시 primary+fallback (D84 동작).
    # GPT-5.5 verdict §5: 최종 scope 빈 시 즉시 return.
    sop_scope = list(getattr(agent_ctx, "sop_repo_ids", None) or [])
    if not sop_scope:
        sop_scope = (
            list(getattr(agent_ctx, "primary_repo_ids", []) or [])
            + list(getattr(agent_ctx, "fallback_repo_ids", []) or [])
        )
    if not sop_scope:
        # knowledge_isolation 안전 — scope 미지정 → 검색 호출 X.
        return ""

    # token budget 계산.
    binding_policy = ""
    try:
        binding_policy = (
            agent_ctx.to_binding_policy_block(sop_rag_mode=True) or ""
        )
    except TypeError:
        try:
            binding_policy = agent_ctx.to_binding_policy_block() or ""
        except Exception:  # noqa: BLE001
            binding_policy = ""
    except Exception:  # noqa: BLE001
        binding_policy = ""
    guidelines_text = getattr(agent_ctx, "guidelines_md", "") or ""
    # GPT-5.5 verdict §3: caller path 의 static base 비용 합산.
    pre_used = (
        estimate_tokens(binding_policy)
        + estimate_tokens(guidelines_text)
        + ENGINE_SYSTEM_OVERHEAD_TOKENS
        + max(0, int(extra_pre_used_tokens or 0))
    )

    # GPT-5.5 verdict §2: prefetch + fetch *전체* 작업에 single timeout
    # (total budget). prefetch hang 도 fail-open.
    timeout_s = get_sop_inject_timeout_ms() / 1000.0
    top_k = get_sop_inject_top_k()
    try:
        chunks = await asyncio.wait_for(
            _build_chunks_with_timeout(
                sop_inject_layer=sop_inject_layer,
                agent_id=agent_id,
                user_message=user_message,
                top_k=top_k,
                destructive=destructive,
                guidelines_md=guidelines_text,
                sop_scope=sop_scope,
                system_budget_tokens=DEFAULT_SYSTEM_BUDGET_TOKENS,
                pre_used=pre_used,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning(
            "sop_inject_total_timeout_fail_open",
            agent_id=str(agent_id),
            timeout_s=timeout_s,
        )
        return ""
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "sop_inject_fetch_failed_fail_open",
            agent_id=str(agent_id),
            error=str(exc),
        )
        return ""

    if not chunks:
        return ""

    block = _render_block(chunks)
    if not block:
        return ""

    # GPT-5.5 verdict §4: final hard cap 복원. estimator 오차 안전망.
    cap = DEFAULT_SYSTEM_BUDGET_TOKENS - pre_used
    block = _apply_final_hard_cap(block, chunks, cap)
    return block


__all__ = [
    "build_sop_context_block",
    "SOP_BLOCK_HEADER",
    "SOP_BLOCK_FOOTER",
]

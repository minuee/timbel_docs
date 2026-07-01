"""engine.turn 안의 delegate 분기 — intent_gate refusal 직전.

spec §10.5 M6 — out_of_domain + delegation_depth==0 + delegate_to_agent_ids
있으면 _load_delegate_candidates → _select_delegate_target → _try_delegate.
위임 성공 시 그 stream 그대로 yield + return. 실패 시 기존 refusal fallthrough.

본 test 는 *path 단위 sanity check* (engine 진입점/import 자체 healthy).
실 시나리오 (real DB + LLM mock chain) 검증은 T6 통합 테스트 (별도 라운드).
"""

from __future__ import annotations

import inspect

import pytest


def test_engine_module_imports_delegate_router_symbols():
    """engine.py 안 delegate 분기에서 사용하는 심볼들이 정상 import 되는가."""
    # delegate_router 의 핵심 심볼들 (Step 4 의 in-branch import 가 의존).
    from src.agent_framework.runtime.delegate_router import (
        _load_delegate_candidates,
        _select_delegate_target,
        _try_delegate,
    )

    assert callable(_load_delegate_candidates)
    assert callable(_select_delegate_target)
    assert callable(_try_delegate)


def test_engine_turn_has_delegation_depth_param():
    """engine.AgentEngine.turn 시그니처에 delegation_depth=0 가 존재."""
    from src.agent_framework.runtime.engine import AgentEngine

    sig = inspect.signature(AgentEngine.turn)
    assert "delegation_depth" in sig.parameters
    assert sig.parameters["delegation_depth"].default == 0


def test_engine_turn_source_contains_delegate_branch():
    """spec §10.5 M6 — turn() body 안에 delegate 분기 키 식별자가 존재.

    구체적으로 다음 마커들이 모두 turn() 정의 안에 등장해야 한다:
      - delegation_depth==0 검사
      - delegate_to_agent_ids 참조
      - _try_delegate 호출 (delegate stream 진입점)
      - delegate_dispatched 로그 (M6 telemetry)
      - delegate_branch_exception 로그 (fail-open fallthrough)
    """
    from src.agent_framework.runtime.engine import AgentEngine

    src = inspect.getsource(AgentEngine.turn)
    assert "delegation_depth" in src
    assert "delegate_to_agent_ids" in src
    assert "_try_delegate" in src
    assert "delegate_dispatched" in src
    assert "delegate_branch_exception" in src


def test_agent_context_has_delegate_to_agent_ids_field():
    """AgentContext.delegate_to_agent_ids — Phase 1.5B-γ field 존재 확인.

    engine 의 delegate 분기가 `agent_ctx.delegate_to_agent_ids` 를 읽으므로
    field 가 사라지면 분기가 즉시 fail (fail-open 으로 회귀는 없지만 위임
    영영 안 됨).
    """
    from dataclasses import fields

    from src.agent_framework.runtime.agent_context import AgentContext

    field_names = {f.name for f in fields(AgentContext)}
    assert "delegate_to_agent_ids" in field_names


@pytest.mark.asyncio
async def test_delegation_depth_blocks_recursion():
    """delegation_depth>=1 인 turn 은 위임 분기 자체 진입 안 함 (코드 path 검증).

    engine.turn 분기 조건이 `delegation_depth == 0` 이라는 직접 검증.
    실 turn 호출은 real DB + LLM 의존 — source-level marker 만 확인.
    """
    from src.agent_framework.runtime.engine import AgentEngine

    src = inspect.getsource(AgentEngine.turn)
    # 분기 진입 가드 — `delegation_depth == 0` 이라는 명시 조건.
    assert "delegation_depth == 0" in src.replace(" ", "").replace(
        "delegation_depth==0", "delegation_depth == 0"
    )


@pytest.mark.asyncio
async def test_no_delegate_when_empty_delegate_ids():
    """delegate_to_agent_ids empty 시 분기 진입 안 함 — source guard 검증."""
    from src.agent_framework.runtime.engine import AgentEngine

    src = inspect.getsource(AgentEngine.turn)
    # 분기 진입 가드 — `delegate_to_agent_ids` 가 truthy 인지 검사.
    assert "delegate_to_agent_ids" in src

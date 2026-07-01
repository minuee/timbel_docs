"""seed_demo_accounts 스크립트 smoke 테스트.

실제 DB 호출은 하지 않는다 (dry-run) — 모듈 import + 시그니처 검증 + dry-run Plan
수치가 4 profile 예상치와 일치하는지 확인.

restaurant_menu_info.yaml 이 존재하고 스키마 검증을 통과하는지도 같이 확인.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from src.agent_framework.runtime.loader import load_skill_from_path


def _load_seed_module():
    """scripts/migrate/seed_demo_accounts.py 를 import 경로 없이 직접 로드."""
    if "seed_demo_accounts_mod" in sys.modules:
        return sys.modules["seed_demo_accounts_mod"]
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "migrate" / "seed_demo_accounts.py"
    spec = importlib.util.spec_from_file_location("seed_demo_accounts_mod", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo_accounts_mod"] = module
    spec.loader.exec_module(module)
    return module


def test_restaurant_menu_info_yaml_loads():
    """새 skill YAML 이 스키마 검증을 통과."""
    path = Path("src/agent_framework/skills/restaurant_menu_info.yaml")
    skill = load_skill_from_path(path)
    assert skill.meta.id == "restaurant_menu_info"
    assert skill.availability.scope == "business_only"
    assert skill.availability.business_type == "retail"
    assert skill.availability.visibility == "opt-in"
    state_ids = [s.id for s in skill.states]
    for required in ("greet", "answer_menu", "answer_hours", "answer_reservation"):
        assert required in state_ids
    intents = {t.intent for t in skill.triggers}
    assert intents == {"ask_menu", "ask_hours", "ask_reservation"}


def test_seed_module_profile_table():
    """PROFILES dict 이 10개 프로파일을 정의하고 각자 phone/name/seeder 를 가진다.

    KMS-Plus persona library v1: 기존 4 + 신규 6 (콜센터/학원/제조/매장/간호사/시니어).
    """
    seed = _load_seed_module()

    profiles = seed.PROFILES
    assert set(profiles.keys()) == {
        "김의사", "박환자", "이사장", "정학생",
        "최상담", "강선생", "박작업", "윤점장", "김간호", "이어르신",
    }
    phones = {p["phone"] for p in profiles.values()}
    assert phones == {
        "010-1111-1111",
        "010-2222-2222",
        "010-3333-3333",
        "010-4444-4444",
        "010-5555-5555",
        "010-6666-6666",
        "010-7777-7777",
        "010-8888-8888",
        "010-9999-9999",
        "010-1010-1010",
    }
    for p in profiles.values():
        assert callable(p["seeder"])


def test_seed_dry_run_counts(monkeypatch):
    """dry-run 으로 Plan 예상 카운트 확인. DB 접속은 engine 생성만 하고 dispose — 쿼리 X."""
    seed = _load_seed_module()

    # create_async_engine 를 stub 으로 교체 — dry-run 경로는 conn 을 사용하지 않으므로
    # dispose() 만 구현된 dummy 면 충분.
    class _DummyEngine:
        async def dispose(self):
            pass

    def _stub_create_engine(*a, **kw):
        return _DummyEngine()

    monkeypatch.setattr(seed, "create_async_engine", _stub_create_engine)

    plan = asyncio.run(
        seed.run_seed(execute=False, wipe=False, only_profile=None)
    )

    # 10 accounts (4 기존 + 6 신규)
    assert plan.accounts == 10
    # business_tenants:
    #   김의사=강남피부과(1) + 이사장=우리식당(1) + 최상담=KB콜센터(1)
    #   + 강선생=한빛학원(1) + 박작업=한라정공(1) + 윤점장=한솥편의점(1)
    #   + 김간호=강남피부과(1, 같은 slug 재사용 — 카운트는 +1 로 표시되도록 계산됨)
    # 김간호 seeder 는 business_tenants 카운트를 늘리지 않는다 (기존 합류).
    assert plan.business_tenants == 6
    # memberships: 위 6개 + 김간호 = 7
    assert plan.memberships == 7
    # skills_enabled:
    #   김의사 appointment_derm=1
    #   이사장 restaurant_menu_info=1
    #   최상담 4 (product_inquiry/kyc_check/inbound_response/faq_assistant)
    #   강선생 3 (curriculum_guide/student_progress/parent_communication)
    #   박작업 4 (sop_lookup/safety_check/defect_report/msds_query)
    #   윤점장 3 (inventory_query/customer_loyalty/refund_process)
    #   김간호 3 (patient_intake/appointment_scheduling/appointment_reminder)
    #   = 19
    assert plan.skills_enabled == 19
    # documents:
    #   김의사 3 + 이사장 3 (기존 6)
    #   + 최상담 1 + 강선생 1 + 박작업 1 + 윤점장 1 + 김간호 1 + 이어르신 1 (신규 6)
    #   = 12
    assert plan.documents == 12
    # 김의사 3 + 박환자 5 + 이사장 4 + 정학생 1 + 이어르신 3 = 16
    assert plan.schedules == 16
    # 박환자 3 + 이사장 2 = 5 (변동 없음)
    assert plan.diaries == 5
    # 박환자 1 + 정학생 1 = 2 (변동 없음)
    assert plan.news_subs == 2


def test_seed_dry_run_single_profile(monkeypatch):
    """--profile 김의사 단독 실행 시 다른 프로파일 카운트는 0."""
    seed = _load_seed_module()

    class _DummyEngine:
        async def dispose(self):
            pass

    monkeypatch.setattr(
        seed, "create_async_engine", lambda *a, **kw: _DummyEngine()
    )

    plan = asyncio.run(
        seed.run_seed(execute=False, wipe=False, only_profile="김의사")
    )

    assert plan.accounts == 1
    assert plan.business_tenants == 1
    assert plan.documents == 3
    assert plan.schedules == 3
    assert plan.diaries == 0
    assert plan.news_subs == 0


def test_seed_dry_run_unknown_profile_raises(monkeypatch):
    seed = _load_seed_module()

    class _DummyEngine:
        async def dispose(self):
            pass

    monkeypatch.setattr(
        seed, "create_async_engine", lambda *a, **kw: _DummyEngine()
    )

    with pytest.raises(SystemExit):
        asyncio.run(
            seed.run_seed(execute=False, wipe=False, only_profile="없는프로파일")
        )

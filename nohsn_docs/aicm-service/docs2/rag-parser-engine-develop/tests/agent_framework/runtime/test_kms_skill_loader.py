"""KMS-backed skill loader unit tests.

실제 DB 없이 AsyncEngine.connect() 와 conn.execute() 를 모킹해서 로더가
processing_meta.yaml 을 꺼내 Skill 객체로 파싱하는지만 검증.

라이브 DB 검증은 scripts/migrate/seed_agent_skills.py + docker exec 로 수행
(run_book 스타일, 본 유닛 테스트와 별개).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.agent_framework.runtime.kms_skill_loader import load_all_skills_from_kms


_MINIMAL_YAML = """
skill:
  id: t_kms_smoke
  version: "0.1"
  domain: test
  description: kms loader smoke
triggers:
  - intent: t_kms_smoke_intent
slots: []
initial_state: s_init
states:
  - id: s_init
""".strip()


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.executed_sql: list[str] = []
        self.executed_params: list[dict[str, Any]] = []

    async def execute(self, stmt, params=None):
        self.executed_sql.append(str(stmt))
        self.executed_params.append(dict(params or {}))
        return _FakeResult(self._rows)


class _FakeEngine:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.conn = _FakeConn(rows)

    def connect(self):
        @asynccontextmanager
        async def _ctx():
            yield self.conn

        return _ctx()


@pytest.mark.asyncio
async def test_loads_skill_from_processing_meta_yaml():
    doc_id = uuid4()
    rows = [
        (
            doc_id,
            "t_kms_smoke",
            {"yaml": _MINIMAL_YAML, "skill_id": "t_kms_smoke"},
        )
    ]
    engine = _FakeEngine(rows)

    skills = await load_all_skills_from_kms(engine)  # type: ignore[arg-type]

    assert list(skills.keys()) == ["t_kms_smoke"]
    s = skills["t_kms_smoke"]
    assert s.meta.id == "t_kms_smoke"
    assert s.meta.domain == "test"
    # 쿼리에 tenant_id / repo_name / doctype name 이 바인드 됐는지 확인
    bound = engine.conn.executed_params[0]
    assert bound["dt_name"] == "agent_skill"
    assert bound["repo_name"] == "agent_framework_library"
    assert bound["tid"] == UUID("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_missing_yaml_in_meta_is_skipped():
    rows = [
        (uuid4(), "broken_one", {"skill_id": "broken_one"}),  # yaml 없음
        (uuid4(), "t_kms_smoke", {"yaml": _MINIMAL_YAML}),
    ]
    engine = _FakeEngine(rows)

    skills = await load_all_skills_from_kms(engine)  # type: ignore[arg-type]

    assert list(skills.keys()) == ["t_kms_smoke"]


@pytest.mark.asyncio
async def test_invalid_yaml_is_skipped_not_raised():
    rows = [
        (uuid4(), "bad", {"yaml": "skill: [unclosed"}),
        (uuid4(), "t_kms_smoke", {"yaml": _MINIMAL_YAML}),
    ]
    engine = _FakeEngine(rows)

    # loader 는 개별 파싱 에러를 로그만 남기고 나머지를 계속 로드해야 함
    skills = await load_all_skills_from_kms(engine)  # type: ignore[arg-type]
    assert list(skills.keys()) == ["t_kms_smoke"]


@pytest.mark.asyncio
async def test_empty_result_returns_empty_dict():
    engine = _FakeEngine([])
    skills = await load_all_skills_from_kms(engine)  # type: ignore[arg-type]
    assert skills == {}

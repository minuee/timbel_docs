"""Phase 1.5A — 056 마이그레이션이 추가한 모델 필드 smoke test.

확인 항목:
- ``Agent.sop_repo_ids`` — list[UUID], nullable=False, default=list.
- ``CustomTool.risk_metadata`` — dict, nullable=False, default=dict.
- ``Document.body_hash`` — Optional[str(64)], nullable=True. Memo 는 별도
  테이블이 없고 ``documents`` 의 ``document_type='agent_memo'`` row 로
  저장되므로 ``body_hash`` 는 documents 컬럼이다.
"""
from __future__ import annotations

from uuid import uuid4

from src.core.models.agent import Agent
from src.core.models.custom_tool import CustomTool
from src.core.models.document import Document


def test_agent_has_sop_repo_ids_field() -> None:
    col = Agent.__table__.c.sop_repo_ids
    assert col is not None
    assert col.nullable is False
    # ARRAY(UUID) — server_default='{}' 적용 확인.
    assert col.server_default is not None


def test_agent_sop_repo_ids_accepts_uuid_list() -> None:
    rid_a, rid_b = uuid4(), uuid4()
    a = Agent(
        tenant_id=uuid4(),
        name="t",
        goal="g" * 10,
        guidelines_md="m" * 10,
        sop_repo_ids=[rid_a, rid_b],
    )
    assert a.sop_repo_ids == [rid_a, rid_b]


def test_agent_sop_repo_ids_default_empty_list() -> None:
    # Python 측 default — ORM hydrate 전이라도 default factory 는 list.
    col = Agent.__table__.c.sop_repo_ids
    # default 는 CallableColumnDefault wrapper.
    assert col.default is not None
    # SQLAlchemy 가 list 를 functools wrapping 하므로 호출 결과로 검사.
    arg = col.default.arg
    assert callable(arg)
    # wrapping 된 callable 은 ctx 인자를 받는다 — 빈 ctx 로 호출.
    assert arg(None) == []


def test_custom_tool_has_risk_metadata_field() -> None:
    col = CustomTool.__table__.c.risk_metadata
    assert col is not None
    assert col.nullable is False
    assert col.server_default is not None


def test_custom_tool_risk_metadata_accepts_dict() -> None:
    t = CustomTool(
        tenant_id=uuid4(),
        name="custom.foo",
        description="desc",
        endpoint_url="https://example.com/hook",
        config_encrypted=b"\x00",
        risk_metadata={"risk_tier": "low", "approval": "auto"},
    )
    assert t.risk_metadata == {"risk_tier": "low", "approval": "auto"}


def test_custom_tool_risk_metadata_default_empty_dict() -> None:
    col = CustomTool.__table__.c.risk_metadata
    assert col.default is not None
    arg = col.default.arg
    assert callable(arg)
    assert arg(None) == {}


def test_document_has_body_hash_field() -> None:
    col = Document.__table__.c.body_hash
    assert col is not None
    assert col.nullable is True
    # String(64) — SHA-256 hex digest 길이.
    assert getattr(col.type, "length", None) == 64


def test_document_body_hash_accepts_str_or_none() -> None:
    d_with_hash = Document(
        tenant_id=uuid4(),
        repository_id=uuid4(),
        title="memo body",
        body_hash="a" * 64,
    )
    assert d_with_hash.body_hash == "a" * 64

    d_without = Document(
        tenant_id=uuid4(),
        repository_id=uuid4(),
        title="non-memo doc",
    )
    # 미설정 시 None (또는 SQLAlchemy default 미적용).
    assert d_without.body_hash is None

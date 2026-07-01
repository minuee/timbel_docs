"""PR-Z11A — inbox_intake.process_email 단위 테스트.

검증 (mocking 위주):
- KMS 저장 helper 호출 + log INSERT 가 한 번씩 일어남
- classifier 가 stub LLM 으로 동작
- KMS 저장 실패해도 log INSERT 는 성립 (document_id=NULL)
- get_or_create_email_inbox_repo 가 ON CONFLICT SQL 발행

DB 는 진짜 안 띄움 — engine.begin() / connect() 를 AsyncMock 으로 fake.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.integration.mail import inbox_intake
from src.integration.mail.classifier import EmailClassifier


@dataclass
class _StubEmail:
    uid: str = "42"
    message_id: str | None = "<unique@x.com>"
    from_address: str | None = "boss@company.com"
    from_domain: str | None = "company.com"
    to_address: str | None = "me@me.com"
    subject: str | None = "test subject"
    date_iso: str | None = "Mon, 28 Apr 2026 10:00:00 +0900"
    body_text: str = "안녕하세요, 내일 오후 3시 미팅 가능?"
    body_html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    raw_size: int = 100


def _make_fake_engine() -> MagicMock:
    """db_engine.begin() / connect() 둘 다 컨텍스트 매니저로 fake."""
    engine = MagicMock(name="AsyncEngine")

    fake_conn = MagicMock(name="AsyncConnection")
    fake_conn.execute = AsyncMock()
    # scalar_one() 호출 — get_or_create_email_inbox_repo 의 RETURNING id
    repo_uuid = uuid4()
    exec_result = MagicMock()
    exec_result.scalar_one = MagicMock(return_value=repo_uuid)
    fake_conn.execute.return_value = exec_result

    @asynccontextmanager
    async def _begin_cm():
        yield fake_conn

    @asynccontextmanager
    async def _connect_cm():
        yield fake_conn

    engine.begin = _begin_cm
    engine.connect = _connect_cm
    engine._fake_conn = fake_conn
    engine._fake_repo_uuid = repo_uuid
    return engine


@pytest.mark.asyncio
async def test_get_or_create_email_inbox_repo_returns_uuid():
    engine = _make_fake_engine()
    tid = uuid4()
    out = await inbox_intake.get_or_create_email_inbox_repo(engine, tid)
    assert isinstance(out, UUID)
    # 반환값이 mock 의 scalar_one 결과와 동일해야 함
    assert out == engine._fake_repo_uuid


@pytest.mark.asyncio
async def test_process_email_full_flow_with_stub_llm():
    """stub LLM → classifier → KMS save (mocked) → log INSERT."""
    engine = _make_fake_engine()
    account_id = uuid4()
    mail_account_id = uuid4()
    fake_doc_id = uuid4()

    async def _stub_llm(prompt: str) -> str:
        return json.dumps(
            {
                "category": "meeting_request",
                "subcategory_reason": "회의 일정",
                "trust_score": 0.9,
                "trust_factors": ["domain match"],
                "priority": "high",
                "extracted_entities": {
                    "datetime_iso": "2026-04-29T15:00",
                    "datetime_natural": "내일 오후 3시",
                    "location": "",
                    "attendees": [],
                    "action_required": "응답",
                    "subject_summary": "내일 미팅",
                },
                "needs_user_attention": True,
                "needs_meeting_prep": True,
            },
            ensure_ascii=False,
        )

    classifier = EmailClassifier(llm=_stub_llm)

    # _save_to_kms 만 mock — webhook helper 의 실제 ORM 의존성을 우회
    async def _fake_save_to_kms(*, tenant_id: UUID, fetched_email: Any, db_engine: Any) -> UUID:
        assert tenant_id == account_id
        assert fetched_email.subject == "test subject"
        return fake_doc_id

    with patch.object(inbox_intake, "_save_to_kms", _fake_save_to_kms):
        result = await inbox_intake.process_email(
            account_id=account_id,
            fetched_email=_StubEmail(),
            mail_account_id=mail_account_id,
            db_engine=engine,
            classifier=classifier,
            tenant_id=account_id,
        )

    assert result["document_id"] == fake_doc_id
    assert isinstance(result["log_id"], UUID)
    cls_dict = result["classification"]
    assert cls_dict["category"] == "meeting_request"
    assert cls_dict["priority"] == "high"
    assert cls_dict["trust_score"] == 0.9

    # log INSERT SQL 이 호출되었는지 검증 — execute 호출 한 번 이상.
    assert engine._fake_conn.execute.await_count >= 1
    last_call = engine._fake_conn.execute.await_args_list[-1]
    sql_text = str(last_call.args[0])
    assert "email_processing_log" in sql_text
    params = last_call.args[1]
    assert params["aid"] == account_id
    assert params["maid"] == mail_account_id
    assert params["did"] == fake_doc_id
    # classification JSON serialized
    parsed_cls = json.loads(params["cls"])
    assert parsed_cls["category"] == "meeting_request"


@pytest.mark.asyncio
async def test_process_email_kms_save_fails_log_still_inserted():
    """KMS 저장 실패 → document_id=None 로 log INSERT (디버깅 위해 유지)."""
    engine = _make_fake_engine()
    account_id = uuid4()
    mail_account_id = uuid4()

    async def _stub_llm(prompt: str) -> str:
        return json.dumps(
            {
                "category": "newsletter",
                "subcategory_reason": "subscription",
                "trust_score": 0.3,
                "trust_factors": [],
                "priority": "low",
                "extracted_entities": {},
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            }
        )

    classifier = EmailClassifier(llm=_stub_llm)

    async def _broken_save(**kwargs: Any) -> UUID:
        raise RuntimeError("KMS down")

    with patch.object(inbox_intake, "_save_to_kms", _broken_save):
        result = await inbox_intake.process_email(
            account_id=account_id,
            fetched_email=_StubEmail(),
            mail_account_id=mail_account_id,
            db_engine=engine,
            classifier=classifier,
            tenant_id=account_id,
        )

    assert result["document_id"] is None
    assert isinstance(result["log_id"], UUID)
    assert result["classification"]["category"] == "newsletter"

    # log INSERT 여전히 일어남
    last_call = engine._fake_conn.execute.await_args_list[-1]
    sql_text = str(last_call.args[0])
    assert "email_processing_log" in sql_text
    assert last_call.args[1]["did"] is None


@pytest.mark.asyncio
async def test_process_email_classifier_no_llm_uses_uncertain_fallback():
    """LLM 미주입 — classifier 가 fallback uncertain 반환. 그래도 log INSERT 성공."""
    engine = _make_fake_engine()
    account_id = uuid4()
    mail_account_id = uuid4()
    fake_doc_id = uuid4()

    classifier = EmailClassifier(llm=None)

    async def _fake_save(*, tenant_id: UUID, fetched_email: Any, db_engine: Any) -> UUID:
        return fake_doc_id

    with patch.object(inbox_intake, "_save_to_kms", _fake_save):
        result = await inbox_intake.process_email(
            account_id=account_id,
            fetched_email=_StubEmail(),
            mail_account_id=mail_account_id,
            db_engine=engine,
            classifier=classifier,
            tenant_id=account_id,
        )

    assert result["classification"]["category"] == "uncertain"
    assert result["classification"]["trust_score"] == 0.5
    assert result["document_id"] == fake_doc_id
    assert isinstance(result["log_id"], UUID)

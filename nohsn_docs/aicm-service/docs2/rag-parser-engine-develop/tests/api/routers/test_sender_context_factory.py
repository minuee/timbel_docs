"""Phase 1.5A Task 7 — SenderContext factory unit tests.

chat_v1._build_sender_context_from_session +
external_agent_v1._build_sender_context_from_channel.

5 회귀 케이스:
  1. chat_v1 web admin session → tier=admin
  2. chat_v1 personal user (member role) → tier=verified
  3. external_agent unmapped (NULL internal_user_id+internal_account_id) → tier=guest
  4. external_agent mapped + role=member → tier=verified
  5. external_agent mapped + role=admin → tier=admin

helper 자체에 대한 단위 테스트 — DB / FastAPI 의존성 없음.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.agent_framework.runtime.sender_context import SenderContext
from src.api.routers.chat_v1 import _build_sender_context_from_session
from src.api.routers.external_agent_v1 import _build_sender_context_from_channel


# ---------------------------------------------------------------------------
# chat_v1 — web session
# ---------------------------------------------------------------------------


def test_chat_v1_admin_session_tier_admin():
    user_id = uuid4()
    tenant_id = uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="admin")
    ctx = _build_sender_context_from_session(user, channel_kind="web")
    assert isinstance(ctx, SenderContext)
    assert ctx.tier == "admin"
    assert ctx.internal_user_id == user_id
    assert ctx.tenant_id == tenant_id
    assert ctx.channel_kind == "web"
    assert ctx.verified_via == "session_login"
    assert ctx.confirm_token is None


def test_chat_v1_owner_session_tier_admin():
    """role=owner 는 admin 동급."""
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="owner")
    ctx = _build_sender_context_from_session(user, channel_kind="web")
    assert ctx.tier == "admin"


def test_chat_v1_personal_user_session_tier_verified():
    """member / 임의 role → verified."""
    user_id = uuid4()
    tenant_id = uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="member")
    ctx = _build_sender_context_from_session(user, channel_kind="web")
    assert ctx.tier == "verified"
    assert ctx.internal_user_id == user_id
    assert ctx.tenant_id == tenant_id
    assert ctx.verified_via == "session_login"


def test_chat_v1_role_none_defaults_verified():
    """role 미설정 (None) → verified default — guest 로 떨어지지 않음."""
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role=None)
    ctx = _build_sender_context_from_session(user, channel_kind="web")
    assert ctx.tier == "verified"


# ---------------------------------------------------------------------------
# external_agent — channel webhook
# ---------------------------------------------------------------------------


def test_external_agent_unmapped_guest():
    """internal_user_id IS NULL AND internal_account_id IS NULL → tier=guest."""
    mapping = SimpleNamespace(
        channel_id=uuid4(),
        external_user_id="123",
        internal_user_id=None,
        internal_account_id=None,
        verified_via=None,
    )
    tenant_id = uuid4()
    ctx = _build_sender_context_from_channel(
        mapping=mapping,
        tenant_id=tenant_id,
        channel_kind="telegram",
    )
    assert ctx.tier == "guest"
    assert ctx.internal_user_id is None
    assert ctx.tenant_id == tenant_id
    assert ctx.channel_kind == "telegram"
    assert ctx.verified_via is None
    assert ctx.confirm_token is None


def test_external_agent_mapped_verified_default():
    """internal_user_id 존재 + role 미지정 → tier=verified."""
    mapped_user_id = uuid4()
    mapping = SimpleNamespace(
        channel_id=uuid4(),
        external_user_id="123",
        internal_user_id=mapped_user_id,
        internal_account_id=None,
        verified_via=None,
    )
    tenant_id = uuid4()
    ctx = _build_sender_context_from_channel(
        mapping=mapping,
        tenant_id=tenant_id,
        channel_kind="phone",
    )
    assert ctx.tier == "verified"
    assert ctx.internal_user_id == mapped_user_id
    assert ctx.verified_via == "channel_mapping"  # default


def test_external_agent_mapped_with_explicit_verified_via():
    """mapping.verified_via 가 set 이면 그 값 보존."""
    mapping = SimpleNamespace(
        channel_id=uuid4(),
        external_user_id="999",
        internal_user_id=uuid4(),
        internal_account_id=None,
        verified_via="phone_otp",
    )
    ctx = _build_sender_context_from_channel(
        mapping=mapping,
        tenant_id=uuid4(),
        channel_kind="phone",
    )
    assert ctx.tier == "verified"
    assert ctx.verified_via == "phone_otp"


def test_external_agent_mapped_admin_role_tier_admin():
    """admin role 사용자가 channel mapping 했어도 tier=admin (caller 가 role 전달)."""
    mapping = SimpleNamespace(
        channel_id=uuid4(),
        external_user_id="789",
        internal_user_id=uuid4(),
        internal_account_id=None,
        verified_via="phone_otp",
    )
    ctx = _build_sender_context_from_channel(
        mapping=mapping,
        tenant_id=uuid4(),
        channel_kind="telegram",
        role="admin",
    )
    assert ctx.tier == "admin"
    assert ctx.verified_via == "phone_otp"


def test_external_agent_mapped_only_internal_account_id():
    """internal_user_id 가 NULL 이어도 internal_account_id set 이면 mapped (verified)."""
    mapping = SimpleNamespace(
        channel_id=uuid4(),
        external_user_id="123",
        internal_user_id=None,
        internal_account_id=uuid4(),
        verified_via=None,
    )
    ctx = _build_sender_context_from_channel(
        mapping=mapping,
        tenant_id=uuid4(),
        channel_kind="telegram",
    )
    assert ctx.tier == "verified"
    assert ctx.internal_user_id is None  # 헬퍼는 internal_user_id 만 SenderContext 에 저장
    assert ctx.verified_via == "channel_mapping"


# ---------------------------------------------------------------------------
# meets() 동작 — guest/verified/admin hierarchy 회귀
# ---------------------------------------------------------------------------


def test_tier_hierarchy_meets():
    """admin meets verified, verified meets guest, guest does not meet verified."""
    admin = SenderContext(
        tier="admin",
        internal_user_id=uuid4(),
        tenant_id=uuid4(),
        channel_kind="web",
        verified_via="session_login",
        confirm_token=None,
    )
    verified = SenderContext(
        tier="verified",
        internal_user_id=uuid4(),
        tenant_id=uuid4(),
        channel_kind="telegram",
        verified_via="channel_mapping",
        confirm_token=None,
    )
    guest = SenderContext(
        tier="guest",
        internal_user_id=None,
        tenant_id=uuid4(),
        channel_kind="telegram",
        verified_via=None,
        confirm_token=None,
    )
    assert admin.meets("verified")
    assert admin.meets("guest")
    assert verified.meets("guest")
    assert verified.meets("verified")
    assert not verified.meets("admin")
    assert not guest.meets("verified")
    assert guest.is_guest
    assert verified.is_verified
    assert admin.is_admin

import pytest
from uuid import uuid4
from src.agent_framework.runtime.sender_context import SenderContext


def test_guest_context():
    ctx = SenderContext(
        tier="guest",
        internal_user_id=None,
        tenant_id=uuid4(),
        channel_kind="telegram",
        verified_via=None,
        confirm_token=None,
    )
    assert ctx.tier == "guest"
    assert ctx.is_guest is True
    assert ctx.is_verified is False
    assert ctx.is_admin is False


def test_verified_context():
    ctx = SenderContext(
        tier="verified", internal_user_id=uuid4(), tenant_id=uuid4(),
        channel_kind="phone", verified_via="phone_otp", confirm_token=None,
    )
    assert ctx.is_verified is True
    assert ctx.is_admin is False


def test_admin_context():
    ctx = SenderContext(
        tier="admin", internal_user_id=uuid4(), tenant_id=uuid4(),
        channel_kind="web", verified_via="session_login", confirm_token=None,
    )
    assert ctx.is_admin is True


def test_tier_ordering():
    """tier 비교 — guest < verified < admin."""
    from src.agent_framework.runtime.sender_context import tier_rank
    assert tier_rank("guest") < tier_rank("verified") < tier_rank("admin")


def test_meets_required_tier():
    guest = SenderContext(tier="guest", internal_user_id=None, tenant_id=uuid4(),
                          channel_kind="web", verified_via=None, confirm_token=None)
    verified = SenderContext(tier="verified", internal_user_id=uuid4(), tenant_id=uuid4(),
                              channel_kind="web", verified_via="login", confirm_token=None)
    admin = SenderContext(tier="admin", internal_user_id=uuid4(), tenant_id=uuid4(),
                           channel_kind="web", verified_via="login", confirm_token=None)

    assert guest.meets("guest") is True
    assert guest.meets("verified") is False
    assert guest.meets("admin") is False
    assert verified.meets("guest") is True
    assert verified.meets("verified") is True
    assert verified.meets("admin") is False
    assert admin.meets("guest") is True
    assert admin.meets("verified") is True
    assert admin.meets("admin") is True


def test_immutable_frozen():
    ctx = SenderContext(tier="guest", internal_user_id=None, tenant_id=uuid4(),
                        channel_kind="web", verified_via=None, confirm_token=None)
    with pytest.raises(Exception):
        ctx.tier = "admin"  # type: ignore

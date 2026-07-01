# src/agent_framework/runtime/sender_context.py
"""SenderContext — chat 요청자의 trust tier + 매핑 정보.

dispatcher 가 매 turn 생성, engine guard 가 tool 호출마다 검사.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


_TIER_ORDER = {"guest": 0, "verified": 1, "admin": 2}


def tier_rank(tier: str) -> int:
    return _TIER_ORDER.get(tier, -1)


@dataclass(frozen=True)
class SenderContext:
    tier: Literal["guest", "verified", "admin"]
    internal_user_id: UUID | None
    tenant_id: UUID
    channel_kind: str | None              # 'web' / 'telegram' / 'phone' / 'instagram'
    verified_via: str | None              # 'session_login' / 'phone_otp' / 'instagram_oauth' / None
    confirm_token: str | None             # destructive 도구 confirm 시

    @property
    def is_guest(self) -> bool:
        return self.tier == "guest"

    @property
    def is_verified(self) -> bool:
        return self.tier == "verified"

    @property
    def is_admin(self) -> bool:
        return self.tier == "admin"

    def meets(self, required_tier: str) -> bool:
        """sender 의 tier 가 required_tier 이상인지."""
        return tier_rank(self.tier) >= tier_rank(required_tier)

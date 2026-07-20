"""사용자 저장소 연동 지점.

==============================================================================
인증서버 담당자가 손댈 곳은 사실상 여기 하나다.
기존 인증서버의 사용자 조회/비밀번호 검증 로직을 UserAuthenticator 프로토콜에
맞춰 구현해서 main.create_app(authenticator=...) 로 넣으면 나머지는 그대로 돈다.
==============================================================================
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UserIdentity:
    """JWT 에 실릴 최소 신원 정보. (PPT 3.6 클레임 최소화)

    소속·개인정보 등 민감정보는 토큰에 넣지 않는다 — 앱이 USER_HOST 로 조회한다.
    """

    sub: str  # UUID
    acc: str  # 계정
    c_id: str | None = None
    cd: str | None = None
    role: str | None = None
    a_name: str | None = None

    def claims(self) -> dict:
        # 현행 토큰의 클레임 이름을 그대로 유지한다(앱들이 이미 이 키를 읽는다).
        claims = {"acc": self.acc}
        for key, value in (("cId", self.c_id), ("cd", self.cd), ("role", self.role), ("aName", self.a_name)):
            if value is not None:
                claims[key] = value
        return claims


class UserAuthenticator(Protocol):
    async def authenticate(self, account: str, password: str) -> UserIdentity | None:
        """ID/PW 검증. 실패하면 None."""

    async def get_by_sub(self, sub: str) -> UserIdentity | None:
        """refresh 시 최신 신원/role 을 다시 읽는다.

        None 을 반환하면(퇴사·비활성화) 갱신이 거부되고 세션이 무효화된다.
        """


class DemoUserAuthenticator:
    """데모용. 절대 운영에 쓰지 말 것 — 실제 사용자 저장소로 교체 대상."""

    def __init__(self, users: dict[str, tuple[str, UserIdentity]]):
        # account -> (sha256(password), identity)
        self._users = users

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    async def authenticate(self, account: str, password: str) -> UserIdentity | None:
        entry = self._users.get(account)
        if entry is None:
            return None
        expected, identity = entry
        if not hmac.compare_digest(expected, self.hash_password(password)):
            return None
        return identity

    async def get_by_sub(self, sub: str) -> UserIdentity | None:
        for _, identity in self._users.values():
            if identity.sub == sub:
                return identity
        return None

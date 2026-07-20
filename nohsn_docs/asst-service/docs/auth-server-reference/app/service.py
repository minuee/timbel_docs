"""인증 핵심 로직 — 발급 / Rotation / 재사용 감지 / Grace 윈도우.

PPT "인증서버 담당에게 요청할 것" 1·3·4번이 전부 이 파일에 있다.
"""

import asyncio
import logging
import secrets
import uuid
from dataclasses import dataclass

import jwt

from .config import Settings
from .errors import (
    InvalidCredentials,
    InvalidGrant,
    SessionAbsoluteTimeout,
    SessionIdleTimeout,
    TokenReuseDetected,
)
from .store import RefreshStore
from .tokens import TokenService, now_ts
from .users import UserAuthenticator, UserIdentity

logger = logging.getLogger("auth")


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: int
    refresh_expires_at: int
    csrf_token: str
    sid: str
    #: grace 윈도우로 "직전에 발급한 동일 쌍"을 그대로 돌려준 경우 True
    replayed: bool = False

    @property
    def access_expires_in(self) -> int:
        return max(0, self.access_expires_at - now_ts())

    @property
    def refresh_expires_in(self) -> int:
        return max(0, self.refresh_expires_at - now_ts())


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        tokens: TokenService,
        store: RefreshStore,
        authenticator: UserAuthenticator,
    ):
        self._settings = settings
        self._tokens = tokens
        self._store = store
        self._authenticator = authenticator

    # ── 로그인 ─────────────────────────────────────────────────
    async def login(self, account: str, password: str) -> TokenPair:
        user = await self._authenticator.authenticate(account, password)
        if user is None:
            raise InvalidCredentials()

        sid = uuid.uuid4().hex
        csrf_token = secrets.token_urlsafe(32)
        pair = self._issue_pair(user, sid=sid, csrf_token=csrf_token)
        await self._store.start_family(
            sid=sid,
            sub=user.sub,
            jti=self._jti_of(pair.refresh_token),
            csrf_token=csrf_token,
            expires_at=pair.refresh_expires_at,
        )
        logger.info("login ok account=%s sid=%s", account, sid)
        return pair

    # ── 갱신 ───────────────────────────────────────────────────
    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = self._tokens.decode(refresh_token, expected_typ="refresh")
        jti = payload["jti"]

        record = await self._store.get(jti)
        if record is None:
            # 서명은 멀쩡한데 기록이 없다 = 이미 무효화된 세션이거나 만료된 것.
            raise InvalidGrant()

        # ① 이미 회전된 토큰이 다시 왔다
        if record.is_rotated:
            return await self._replay_or_detect_reuse(record)

        # ② 같은 refresh 로 동시에 갱신 요청이 몰린 경우(앱 간 경합) — 1회만 회전시킨다
        if not await self._store.acquire_rotation_lock(jti):
            return await self._wait_for_replay(jti)

        try:
            record = await self._store.get(jti)
            if record is None:
                raise InvalidGrant()
            if record.is_rotated:  # 락 잡는 사이에 끝났다
                return await self._replay_or_detect_reuse(record)
            return await self._rotate(record)
        finally:
            await self._store.release_rotation_lock(jti)

    async def _rotate(self, record) -> TokenPair:
        family = await self._store.get_family(record.sid)
        if family is None:
            raise InvalidGrant()

        now = now_ts()
        idle = self._settings.session_idle_timeout_seconds
        absolute = self._settings.session_absolute_ttl_seconds
        if idle and now - family.last_seen > idle:
            await self._store.revoke_family(record.sid)
            raise SessionIdleTimeout()
        if absolute and now - family.created_at > absolute:
            await self._store.revoke_family(record.sid)
            raise SessionAbsoluteTimeout()

        # 갱신 시점의 최신 role/신원을 다시 읽는다 (퇴사·권한변경 반영)
        user = await self._authenticator.get_by_sub(record.sub)
        if user is None:
            await self._store.revoke_family(record.sid)
            raise InvalidGrant("사용자를 찾을 수 없거나 비활성 상태입니다.")

        pair = self._issue_pair(user, sid=record.sid, csrf_token=family.csrf_token)

        # 새 것을 먼저 등록하고, 그 다음 구 토큰을 폐기한다.
        # (순서가 반대면 두 요청 사이 짧은 순간에 유효한 refresh 가 하나도 없게 된다)
        await self._store.register(
            sid=record.sid,
            sub=record.sub,
            jti=self._jti_of(pair.refresh_token),
            expires_at=pair.refresh_expires_at,
        )
        await self._store.mark_rotated(
            jti=record.jti,
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            csrf_token=pair.csrf_token,
            access_expires_at=pair.access_expires_at,
            refresh_expires_at=pair.refresh_expires_at,
        )
        await self._store.touch(record.sid, expires_at=pair.refresh_expires_at)
        logger.info("rotate sid=%s old_jti=%s", record.sid, record.jti)
        return pair

    async def _replay_or_detect_reuse(self, record) -> TokenPair:
        """폐기된 refresh 가 다시 온 경우: grace 안이면 경합, 밖이면 탈취."""
        elapsed = now_ts() - record.rotated_at
        if elapsed <= self._settings.refresh_grace_seconds and record.replay_refresh:
            logger.info("grace replay sid=%s jti=%s elapsed=%ss", record.sid, record.jti, elapsed)
            return TokenPair(
                access_token=record.replay_access,
                refresh_token=record.replay_refresh,
                access_expires_at=record.replay_access_expires_at,
                refresh_expires_at=record.replay_refresh_expires_at,
                csrf_token=record.replay_csrf or "",
                sid=record.sid,
                replayed=True,
            )

        # grace 를 넘겨 재등장 = 탈취로 간주하고 계보 전체를 끊는다 (RFC 9700)
        logger.warning("refresh reuse detected — 세션 무효화 sid=%s jti=%s", record.sid, record.jti)
        await self._store.revoke_family(record.sid)
        raise TokenReuseDetected()

    async def _wait_for_replay(self, jti: str) -> TokenPair:
        """락 경쟁에서 진 요청: 승자가 발급한 쌍이 붙을 때까지 잠깐 기다렸다가 그대로 받는다."""
        deadline = now_ts() + 3
        while now_ts() <= deadline:
            await asyncio.sleep(0.05)
            record = await self._store.get(jti)
            if record is None:
                raise InvalidGrant()
            if record.is_rotated and record.replay_refresh:
                return await self._replay_or_detect_reuse(record)
        raise InvalidGrant("갱신이 지연되었습니다. 다시 시도해 주세요.")

    # ── 로그아웃 ───────────────────────────────────────────────
    async def logout(self, refresh_token: str | None) -> None:
        """세션 전체(그 계보의 모든 refresh)를 무효화한다.

        주의: 이미 발급된 access 는 JWKS 자체검증이라 만료(수 분) 전까지 유효하다.
        즉시 차단이 필요하면 access 수명을 더 줄이거나 별도 차단 목록이 필요하다.
        """
        if not refresh_token:
            return
        try:
            payload = self._tokens.decode(refresh_token, expected_typ="refresh")
        except InvalidGrant:
            return
        sid = payload.get("sid")
        if sid:
            await self._store.revoke_family(sid)
            logger.info("logout sid=%s", sid)

    # ── 내부 ───────────────────────────────────────────────────
    def _issue_pair(self, user: UserIdentity, *, sid: str, csrf_token: str) -> TokenPair:
        access = self._tokens.issue(
            typ="access",
            sub=user.sub,
            sid=sid,
            ttl=self._settings.access_ttl_seconds,
            claims=user.claims(),
        )
        # refresh 에는 신원 클레임을 싣지 않는다 — 갱신 때 저장소에서 다시 읽는다.
        refresh = self._tokens.issue(
            typ="refresh",
            sub=user.sub,
            sid=sid,
            ttl=self._settings.refresh_ttl_seconds,
        )
        return TokenPair(
            access_token=access.token,
            refresh_token=refresh.token,
            access_expires_at=access.expires_at,
            refresh_expires_at=refresh.expires_at,
            csrf_token=csrf_token,
            sid=sid,
        )

    def _jti_of(self, token: str) -> str:
        return jwt.decode(token, options={"verify_signature": False})["jti"]

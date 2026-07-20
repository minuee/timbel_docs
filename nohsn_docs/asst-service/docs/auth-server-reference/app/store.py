"""refresh 토큰 상태 저장소 (Redis).

여기에 담기는 것:
  - 발급된 refresh 의 상태(active / rotated)  → 재사용 감지의 근거
  - rotation 계보를 묶는 세션 패밀리(sid)     → 탈취 감지 시 "세션 전체" 무효화 단위
  - grace 윈도우용 직전 발급 토큰 쌍          → 앱 간 동시 갱신 경합 시 동일 쌍 반환

access 토큰은 저장하지 않는다. 각 앱이 JWKS 로 자체 검증하므로 서버 상태가 필요 없다.

키 구조
  {prefix}:rt:{jti}       HASH    sid, sub, status, rotated_at, replay_*
  {prefix}:fam:{sid}      HASH    sub, csrf, created_at, last_seen
  {prefix}:fam:{sid}:jtis SET     해당 세션에서 발급된 모든 refresh jti
  {prefix}:lock:{jti}     STRING  회전 락 (동시 갱신 요청을 1회로 합침)
"""

from dataclasses import dataclass

from redis.asyncio import Redis

from .config import Settings
from .tokens import now_ts

STATUS_ACTIVE = "active"
STATUS_ROTATED = "rotated"


@dataclass(frozen=True)
class RefreshRecord:
    jti: str
    sid: str
    sub: str
    status: str
    rotated_at: int
    replay_access: str | None
    replay_refresh: str | None
    replay_csrf: str | None
    replay_access_expires_at: int
    replay_refresh_expires_at: int

    @property
    def is_rotated(self) -> bool:
        return self.status == STATUS_ROTATED


@dataclass(frozen=True)
class FamilyRecord:
    sid: str
    sub: str
    csrf_token: str
    created_at: int
    last_seen: int


class RefreshStore:
    def __init__(self, redis: Redis, settings: Settings):
        self._redis = redis
        self._settings = settings

    # ── 키 ─────────────────────────────────────────────────────
    def _rt(self, jti: str) -> str:
        return f"{self._settings.redis_prefix}:rt:{jti}"

    def _fam(self, sid: str) -> str:
        return f"{self._settings.redis_prefix}:fam:{sid}"

    def _fam_jtis(self, sid: str) -> str:
        return f"{self._settings.redis_prefix}:fam:{sid}:jtis"

    def _lock(self, jti: str) -> str:
        return f"{self._settings.redis_prefix}:lock:{jti}"

    # ── 쓰기 ───────────────────────────────────────────────────
    async def start_family(
        self, *, sid: str, sub: str, jti: str, csrf_token: str, expires_at: int
    ) -> None:
        ts = now_ts()
        pipe = self._redis.pipeline()
        pipe.hset(
            self._fam(sid),
            mapping={"sub": sub, "csrf": csrf_token, "created_at": ts, "last_seen": ts},
        )
        pipe.expireat(self._fam(sid), expires_at)
        await pipe.execute()
        await self.register(sid=sid, sub=sub, jti=jti, expires_at=expires_at)

    async def register(self, *, sid: str, sub: str, jti: str, expires_at: int) -> None:
        """새 refresh 를 active 로 등록한다."""
        pipe = self._redis.pipeline()
        pipe.hset(
            self._rt(jti),
            mapping={"sid": sid, "sub": sub, "status": STATUS_ACTIVE, "rotated_at": 0},
        )
        # 재사용 감지를 위해 refresh 가 만료될 때까지는 기록을 살려둔다.
        # (일찍 지우면 "폐기된 토큰의 재등장"과 "모르는 토큰"을 구분할 수 없다)
        pipe.expireat(self._rt(jti), expires_at)
        pipe.sadd(self._fam_jtis(sid), jti)
        pipe.expireat(self._fam_jtis(sid), expires_at)
        pipe.expireat(self._fam(sid), expires_at)
        await pipe.execute()

    async def mark_rotated(
        self,
        *,
        jti: str,
        access_token: str,
        refresh_token: str,
        csrf_token: str,
        access_expires_at: int,
        refresh_expires_at: int,
    ) -> None:
        """구 refresh 를 폐기하고, grace 윈도우용으로 새로 발급한 쌍을 붙여둔다."""
        await self._redis.hset(
            self._rt(jti),
            mapping={
                "status": STATUS_ROTATED,
                "rotated_at": now_ts(),
                "replay_access": access_token,
                "replay_refresh": refresh_token,
                "replay_csrf": csrf_token,
                "replay_access_exp": access_expires_at,
                "replay_refresh_exp": refresh_expires_at,
            },
        )

    # ── 회전 락 (single-flight) ────────────────────────────────
    async def acquire_rotation_lock(self, jti: str, ttl: int = 10) -> bool:
        """같은 refresh 에 대한 동시 갱신 중 하나만 실제 회전하게 한다."""
        return bool(await self._redis.set(self._lock(jti), "1", nx=True, ex=ttl))

    async def release_rotation_lock(self, jti: str) -> None:
        await self._redis.delete(self._lock(jti))

    async def touch(self, sid: str, *, expires_at: int) -> None:
        pipe = self._redis.pipeline()
        pipe.hset(self._fam(sid), "last_seen", now_ts())
        pipe.expireat(self._fam(sid), expires_at)
        await pipe.execute()

    async def revoke_family(self, sid: str) -> int:
        """세션 전체 무효화. 재사용 감지·로그아웃 시 호출."""
        jtis = await self._redis.smembers(self._fam_jtis(sid))
        keys = [self._rt(_decode(j)) for j in jtis] + [self._fam(sid), self._fam_jtis(sid)]
        if keys:
            await self._redis.delete(*keys)
        return len(jtis)

    # ── 읽기 ───────────────────────────────────────────────────
    async def get(self, jti: str) -> RefreshRecord | None:
        data = await self._redis.hgetall(self._rt(jti))
        if not data:
            return None
        data = {_decode(k): _decode(v) for k, v in data.items()}
        return RefreshRecord(
            jti=jti,
            sid=data["sid"],
            sub=data["sub"],
            status=data.get("status", STATUS_ACTIVE),
            rotated_at=int(data.get("rotated_at") or 0),
            replay_access=data.get("replay_access"),
            replay_refresh=data.get("replay_refresh"),
            replay_csrf=data.get("replay_csrf"),
            replay_access_expires_at=int(data.get("replay_access_exp") or 0),
            replay_refresh_expires_at=int(data.get("replay_refresh_exp") or 0),
        )

    async def get_family(self, sid: str) -> FamilyRecord | None:
        data = await self._redis.hgetall(self._fam(sid))
        if not data:
            return None
        data = {_decode(k): _decode(v) for k, v in data.items()}
        return FamilyRecord(
            sid=sid,
            sub=data["sub"],
            csrf_token=data.get("csrf", ""),
            created_at=int(data["created_at"]),
            last_seen=int(data["last_seen"]),
        )


def _decode(value) -> str:
    return value.decode() if isinstance(value, bytes) else value

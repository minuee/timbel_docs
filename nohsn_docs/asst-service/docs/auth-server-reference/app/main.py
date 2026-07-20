"""앱 조립 + 실행 엔트리.

  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from .config import Settings, get_settings
from .errors import AuthError
from .keys import KeyRing
from .routers import auth as auth_router
from .routers import jwks as jwks_router
from .service import AuthService
from .store import RefreshStore
from .tokens import TokenService
from .users import DemoUserAuthenticator, UserAuthenticator, UserIdentity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _demo_authenticator() -> DemoUserAuthenticator:
    """데모 계정. 실제 인증서버에서는 기존 사용자 저장소 구현으로 교체한다."""
    identity = UserIdentity(
        sub="00000000-0000-0000-0000-000000000001",
        acc="agent01",
        c_id="timbel",
        cd="0001",
        role="agent",
        a_name="상담사01",
    )
    return DemoUserAuthenticator({"agent01": (DemoUserAuthenticator.hash_password("password"), identity)})


def create_app(
    *,
    settings: Settings | None = None,
    redis_client: Redis | None = None,
    authenticator: UserAuthenticator | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    authenticator = authenticator or _demo_authenticator()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        redis = redis_client or Redis.from_url(settings.redis_url)
        keyring = KeyRing.from_settings(settings)
        store = RefreshStore(redis, settings)

        app.state.settings = settings
        app.state.keyring = keyring
        app.state.redis = redis
        app.state.auth_service = AuthService(
            settings=settings,
            tokens=TokenService(settings, keyring),
            store=store,
            authenticator=authenticator,
        )
        yield
        if redis_client is None:
            await redis.aclose()

    app = FastAPI(title="Timbel 포털 인증서비스", version="1.0.0", lifespan=lifespan)

    # 쿠키를 쓰려면 오리진을 명시해야 한다 — allow_credentials 와 "*" 는 함께 못 쓴다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AuthError)
    async def _auth_error_handler(_: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})

    app.include_router(auth_router.router)
    app.include_router(jwks_router.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()

"""비동기 데이터베이스 세션 팩토리 및 FastAPI 의존성."""

from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

# D32 §1 — KMS_DB_ROLE 기반 DB URL 분기. effective_database_url property
# (config.py) 가 app/migration/super 별 환경변수 자동 선택.
engine = create_async_engine(
    settings.effective_database_url,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=10,
    echo=settings.DATABASE_ECHO,
    pool_pre_ping=True,
)


# D32 §2 — begin 훅 입력 검증 allowlist (GPT-5 BLOCKER 패치).
_VALID_SCOPES = frozenset({"", "admin", "agent", "role", "superadmin", "system"})


class RLSStrictTenantError(RuntimeError):
    """Phase 2 T2.4 — RLS_STRICT_TENANT_REQUIRED 모드에서 tenant_id 미설정 fail-fast.

    bare ``except Exception`` 이 잡아먹지 않도록 별도 sentinel 클래스. begin 훅의
    하단 RuntimeError 처리절이 본 클래스만 명시적으로 re-raise 한다.
    """
    pass


def _validated_uuid(value: str | None) -> str:
    """UUID 파싱 실패 시 빈 문자열 (RLS default-deny). value=='' 도 그대로 통과."""
    if not value:
        return ""
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        logger.warning("rls_session_vars_invalid_uuid", value=value)
        return ""


def _validated_scope(scope: str | None) -> str:
    """allowlist 외 값은 빈 문자열로 강등 (default-deny)."""
    if scope is None:
        return ""
    if scope in _VALID_SCOPES:
        return scope
    logger.warning("rls_session_vars_invalid_scope", scope=scope)
    return ""


# ---------------------------------------------------------------------------
# D25 (#158) — RLS session vars on transaction begin
# ---------------------------------------------------------------------------

@event.listens_for(engine.sync_engine, "begin")
def _rls_set_session_vars(conn) -> None:  # type: ignore[no-untyped-def]
    """transaction begin 시 RLS session 변수 (SET LOCAL) 주입.

    ``src.api.middleware.rls_context.set_rls_context`` 로 contextvar 가 등록된
    상태이면, transaction 시작 즉시 ``app.current_agent_id`` / ``app.current_scope``
    / ``app.current_tenant_id`` 를 ``SET LOCAL`` 으로 주입.

    contextvar 가 없으면 (legacy path / set_rls_context 호출 누락) 빈 값 → RLS
    정책상 SELECT 0 결과 / INSERT 거부 (default-deny). 운영 phase 1 (KMS_DB_ROLE
    =migration BYPASSRLS) 에서는 default-deny 가 우회되어 회귀 0.

    bypass 는 *PostgreSQL role attribute* (BYPASSRLS) — GUC 토글 0. application
    role (kms_app) 이 NOBYPASSRLS 면 SET LOCAL 으로 우회 불가능.
    """
    if not settings.RLS_ENFORCE:
        # D32 §1 — RLS_ENFORCE=False 일 때 begin 훅 발행 X (rollback safety).
        return
    try:
        from src.api.middleware.rls_context import get_rls_context

        ctx = get_rls_context()
        if ctx is None:
            return

        # D32 §2 — GPT-5 BLOCKER 패치 — scope allowlist + UUID 강등.
        scope_val = _validated_scope(ctx.scope)
        agent_val = _validated_uuid(ctx.agent_id)
        tenant_val = _validated_uuid(ctx.tenant_id)

        # Phase 2 T2.4 (spec §8.1) — strict tenant_id 모드.
        # tenant_val 빈 값 + superadmin 아닌 scope → 명시 RLSStrictTenantError.
        # default deny 의 silent 0-row 대신 caller 가 인지 가능한 실패로 격상.
        # 자체 sentinel 예외 클래스 (RuntimeError 서브) 로 bare except 통과 후 재던짐.
        if (
            getattr(settings, "RLS_STRICT_TENANT_REQUIRED", False)
            and not tenant_val
            and scope_val != "superadmin"
        ):
            raise RLSStrictTenantError(
                "rls_strict_tenant_required: app.current_tenant_id 미설정 "
                "(scope=%s). set_rls_context 호출 누락 확인." % (scope_val or "<empty>")
            )

        # SET LOCAL 은 transaction-scope — connection pool reuse 시 leak 0.
        # set_config(setting_name, new_value, is_local) — is_local=true → SET LOCAL.
        conn.execute(
            text("SELECT set_config('app.current_agent_id', :v, true)"),
            {"v": agent_val},
        )
        conn.execute(
            text("SELECT set_config('app.current_scope', :v, true)"),
            {"v": scope_val},
        )
        conn.execute(
            text("SELECT set_config('app.current_tenant_id', :v, true)"),
            {"v": tenant_val},
        )
    except RLSStrictTenantError:
        # Phase 2 T2.4 — strict tenant 모드의 명시 fail-fast 는 그대로 전파.
        # bare except 가 잡아먹지 않도록 sentinel 클래스로 분리.
        raise
    except Exception as exc:  # noqa: BLE001
        # rollout phase 1 에서 hook 자체가 실패해도 application 전체 fail 회피.
        # logger.warning 만 남기고 RLS 정책은 BYPASSRLS role attribute 가 처리.
        logger.warning("rls_session_vars_set_failed", error=str(exc))

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성: 비동기 DB 세션을 주입한다.

    요청당 하나의 세션을 생성하고, 요청 완료 시 자동 종료한다.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """애플리케이션 시작 시 DB 연결 확인."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda _: None)
    logger.info("database_connected", url=settings.DATABASE_URL.split("@")[-1])


async def close_db() -> None:
    """애플리케이션 종료 시 DB 연결 정리."""
    await engine.dispose()
    logger.info("database_disconnected")

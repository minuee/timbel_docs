"""감사 로그 서비스 — append-only + sha256 row hash chain.

Phase 1.5A Task 8d: stub 였던 함수들을 실 INSERT 로 구현.

핵심 보장:
- INSERT-only: UPDATE/DELETE 안 하는 경로만 노출.
- row_hash = sha256( (prev_row_hash or '') + canonical_json(payload) )
  → 어느 row 든 mutate 하면 다음 row 의 hash 가 불일치.
- per-tenant chain: SELECT FOR UPDATE 로 직전 row 잠근 뒤 INSERT
  → concurrent 호출이 같은 chain 을 중복 fork 하지 않음.

DB role 로 audit_logs UPDATE/DELETE 권한 박탈은 별도 deploy script (이 모듈 범위 외).

Backwards compatibility:
- 기존 callers (record_action / fire_and_forget_audit) 는 wrapper 로 살려둠.
  → 인자 시그니처 그대로 유지 + 내부적으로 record_event 호출.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import async_session_factory
from src.core.models.audit_log import AuditAction, AuditLog

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# canonical event JSON
# -----------------------------------------------------------------------------
def _canonical_json(payload: dict[str, Any]) -> str:
    """sort_keys + default=str 로 deterministic JSON 직렬화.

    UUID/datetime/Enum 도 안전하게 str() 로 fallback.
    """
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def compute_row_hash(prev_row_hash: str | None, canonical_json: str) -> str:
    """sha256( (prev_row_hash or '') + canonical_json ) — chain hash."""
    h = hashlib.sha256()
    h.update((prev_row_hash or "").encode("utf-8"))
    h.update(canonical_json.encode("utf-8"))
    return h.hexdigest()


def verify_chain(rows: list[AuditLog]) -> tuple[bool, int | None]:
    """주어진 row list (created_at 오름차순) 의 hash chain 무결성 검증.

    Returns:
        (ok, broken_index): 모든 link 이 일치하면 (True, None).
        i 번째 row 의 prev_row_hash 가 i-1 의 row_hash 와 다르거나,
        i 번째 row_hash 가 재계산값과 다르면 (False, i).
    """
    prev_hash: str | None = None
    for i, row in enumerate(rows):
        if (row.prev_row_hash or None) != prev_hash:
            return False, i
        canonical = _build_canonical_for_row(row)
        expected = compute_row_hash(prev_hash, canonical)
        if row.row_hash != expected:
            return False, i
        prev_hash = row.row_hash
    return True, None


def _build_canonical_for_row(row: AuditLog) -> str:
    """row 객체로부터 canonical payload 재구성 (verify 용).

    record_event 가 INSERT 시 어떤 필드를 hash 했는지와 *반드시* 일치해야 함.
    """
    payload = _build_payload(
        tenant_id=row.tenant_id,
        actor_id=row.user_id,
        actor_tier=row.actor_tier,
        event_kind=row.event_kind,
        tool_name=row.tool_name,
        args_redacted=row.args_redacted,
        outcome=row.outcome,
        created_at=row.created_at,
        row_id=row.id,
    )
    return _canonical_json(payload)


def _build_payload(
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    actor_tier: str | None,
    event_kind: str | None,
    tool_name: str | None,
    args_redacted: dict | None,
    outcome: str | None,
    created_at: datetime | None,
    row_id: UUID | None,
) -> dict[str, Any]:
    """hash chain 입력으로 사용할 payload dict.

    NOTE: 키 집합이 record_event 와 _build_canonical_for_row 사이에 *반드시*
    동일해야 함. 변경 시 기존 row 검증이 깨지므로 신중히.
    """
    return {
        "id": str(row_id) if row_id else None,
        "tenant_id": str(tenant_id),
        "actor_id": str(actor_id) if actor_id else None,
        "actor_tier": actor_tier,
        "event_kind": event_kind,
        "tool_name": tool_name,
        "args_redacted": args_redacted,
        "outcome": outcome,
        "created_at": created_at.isoformat() if created_at else None,
    }


# -----------------------------------------------------------------------------
# core record_event
# -----------------------------------------------------------------------------
async def record_event(
    *,
    tenant_id: UUID,
    actor_id: UUID | None = None,
    actor_tier: str | None = None,
    event_kind: str,
    tool_name: str | None = None,
    args_redacted: dict | None = None,
    outcome: str = "success",
    db: AsyncSession | None = None,
    # legacy fields — backward-compat callers 가 채울 수 있게 받음
    action: str | AuditAction | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    detail: dict | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    # === D24 §1 (alembic 076) — agent 격리 메타 ===
    # owner_scope: 'admin' | 'agent' | 'role' | None (legacy pre-D24).
    # owner_agent_id: agent 가 produce 한 row 의 source agent.
    # hash chain payload 에 불포함 — legacy row 와 hash 호환 유지.
    owner_scope: str | None = None,
    owner_agent_id: UUID | None = None,
) -> AuditLog:
    """Append-only audit event 기록.

    같은 tenant 의 직전 row 의 row_hash 를 SELECT FOR UPDATE 로 잠그고
    chain 을 이어서 INSERT 한다. 호출 측 transaction 안에서 동작 (db 세션
    인자) 또는 자체 세션 사용.

    Returns:
        커밋된 AuditLog row.
    """
    own_session = db is None
    session = db if db is not None else async_session_factory()

    try:
        if own_session:
            # async_sessionmaker() 는 컨텍스트로 사용해야 close 가 정확.
            async with session as inner:  # type: ignore[union-attr]
                return await _record_event_inner(
                    inner,
                    commit=True,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    actor_tier=actor_tier,
                    event_kind=event_kind,
                    tool_name=tool_name,
                    args_redacted=args_redacted,
                    outcome=outcome,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    detail=detail,
                    old_value=old_value,
                    new_value=new_value,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    request_id=request_id,
                    owner_scope=owner_scope,
                    owner_agent_id=owner_agent_id,
                )
        else:
            return await _record_event_inner(
                session,  # type: ignore[arg-type]
                commit=False,
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_tier=actor_tier,
                event_kind=event_kind,
                tool_name=tool_name,
                args_redacted=args_redacted,
                outcome=outcome,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=detail,
                old_value=old_value,
                new_value=new_value,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                owner_scope=owner_scope,
                owner_agent_id=owner_agent_id,
            )
    except Exception as e:
        logger.error("audit_record_event_failed", exc_info=e)
        raise


async def _record_event_inner(
    db: AsyncSession,
    *,
    commit: bool,
    tenant_id: UUID,
    actor_id: UUID | None,
    actor_tier: str | None,
    event_kind: str,
    tool_name: str | None,
    args_redacted: dict | None,
    outcome: str,
    action: str | AuditAction | None,
    resource_type: str | None,
    resource_id: UUID | None,
    detail: dict | None,
    old_value: dict | None,
    new_value: dict | None,
    ip_address: str | None,
    user_agent: str | None,
    request_id: str | None,
    owner_scope: str | None = None,
    owner_agent_id: UUID | None = None,
) -> AuditLog:
    """실제 INSERT 로직. commit=True 면 함수 안에서 커밋.

    동일 tenant 의 chain head 를 SELECT FOR UPDATE — concurrent inserts 를
    serialize 한다 (row-level lock).
    """
    # RLS context: background task(fire-and-forget)에서 실행될 때
    # HTTP 미들웨어의 contextvar가 이미 reset되어 begin 훅이 SET LOCAL을
    # 발행하지 못한다. own_session(commit=True)일 때 명시적으로 설정.
    if commit:
        await db.execute(
            text("SELECT set_config('app.current_tenant_id', :v, true)"),
            {"v": str(tenant_id)},
        )
        await db.execute(
            text("SELECT set_config('app.current_scope', :v, true)"),
            {"v": "admin"},
        )

    # === 1. 직전 row 의 row_hash 잠근 채로 SELECT ===
    # advisory lock 으로 같은 tenant 의 chain 진입을 직렬화.
    # pg_advisory_xact_lock(tenant_hash) — transaction 단위.
    tenant_lock_key = int.from_bytes(
        hashlib.sha256(str(tenant_id).encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": tenant_lock_key}
    )

    # advisory lock 안에서 직전 row 조회 — 다른 transaction 은 이 lock 에 걸려
    # 대기하므로 stale read 위험 없음.
    prev_row_hash = await _get_latest_row_hash(db, tenant_id)

    # === 2. row id / created_at 결정 — payload 에 포함되어야 hash 안정 ===
    # NOTE: 일부 deploy 의 audit_logs.created_at 컬럼은 TIMESTAMP (no tz) — DB
    # 라운드트립 시 tzinfo 가 떨어진다. hash 안정성을 위해 처음부터 naive
    # UTC 로 저장하여 재계산 결과가 일치하게 한다.
    row_id = uuid4()
    created_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    # === 3. canonical payload + row_hash 계산 ===
    payload = _build_payload(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_tier=actor_tier,
        event_kind=event_kind,
        tool_name=tool_name,
        args_redacted=args_redacted,
        outcome=outcome,
        created_at=created_at,
        row_id=row_id,
    )
    canonical = _canonical_json(payload)
    row_hash = compute_row_hash(prev_row_hash, canonical)

    # === 4. INSERT (raw values 로 created_at / id 명시 — server_default 우회) ===
    # NOTE: owner_scope/owner_agent_id 는 hash chain payload 에 *불포함*.
    # 신규 메타이므로 legacy row 와 hash 호환 유지 — verify_chain 그대로 통과.
    audit = AuditLog(
        id=row_id,
        tenant_id=tenant_id,
        user_id=actor_id,
        actor_tier=actor_tier,
        event_kind=event_kind,
        tool_name=tool_name,
        args_redacted=args_redacted,
        outcome=outcome,
        prev_row_hash=prev_row_hash,
        row_hash=row_hash,
        created_at=created_at,
        # legacy fields (선택) — 기존 callers 호환
        action=_coerce_action(action) if action is not None else None,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        # D24 §1 — agent 격리 메타
        # RLS 정책: owner_agent_id IS NOT NULL OR owner_scope IN ('admin','system') 필수.
        # background task(fire-and-forget)에서 owner_scope 미지정 시 'system' 기본값.
        owner_scope=owner_scope or "system",
        owner_agent_id=owner_agent_id,
    )
    db.add(audit)
    await db.flush()

    if commit:
        await db.commit()

    return audit


async def _get_latest_row_hash(
    db: AsyncSession, tenant_id: UUID
) -> str | None:
    """같은 tenant 의 가장 최근 row 의 row_hash 반환 (chain head)."""
    stmt = (
        select(AuditLog.row_hash)
        .where(AuditLog.tenant_id == tenant_id)
        .where(AuditLog.row_hash.is_not(None))
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.first()
    return row[0] if row and row[0] else None


def _coerce_action(action: str | AuditAction | None) -> AuditAction | None:
    """legacy callers 가 str 로 보낸 action 을 enum 으로 변환."""
    if action is None:
        return None
    if isinstance(action, AuditAction):
        return action
    try:
        return AuditAction(str(action).upper())
    except ValueError:
        return None


# -----------------------------------------------------------------------------
# Backward-compatible wrappers (legacy callers — pii.py / blocks.py / etc.)
# -----------------------------------------------------------------------------
# 기존 callers (blocks.py / notes.py / documents.py / pii.py / confidentiality.py /
# rag.py / search.py) 는 `record_action(...)` / `fire_and_forget_audit(...)` 를
# *await 없이* 호출 (stub 였을 때 동기처럼 부르던 패턴).
#
# 호환을 위해 wrapper 는:
#   1. 동기 함수처럼 즉시 return (None).
#   2. running event loop 가 있으면 background task 로 schedule.
#   3. 실패는 log 로만 남김 (audit 실패가 요청을 깨트리지 않음).
#
# 신규 코드는 `await record_event(...)` 직접 사용 권장.

def _schedule_or_run(coro) -> None:
    """coroutine 을 현재 loop 의 background task 로 schedule (실패는 log)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        task = loop.create_task(_safe_await(coro))
        # task 참조 보관 — 가비지 콜렉션 방지
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    else:
        # event loop 없는 sync context — 동기적으로 run.
        try:
            asyncio.run(_safe_await(coro))
        except Exception as e:  # noqa: BLE001
            logger.warning("audit_sync_run_failed: %s", e)


_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _safe_await(coro) -> None:
    try:
        await coro
    except Exception as e:  # noqa: BLE001
        logger.warning("audit_background_task_failed: %s", e)


def record_action(
    tenant_id: UUID,
    user_id: UUID | None,
    action: str | AuditAction,
    resource_type: str,
    resource_id: UUID | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    *,
    owner_scope: str | None = None,
    owner_agent_id: UUID | None = None,
) -> None:
    """Legacy wrapper — record_event 로 forward.

    원래 stub 이었음. 이제 background task 로 실 INSERT 한다.
    Caller 는 await 없이 호출 가능 (기존 패턴 유지). 실패해도 throw 하지 않음.

    D24 §1: owner_scope/owner_agent_id 옵트인 forwarding (default None).
    """
    coro = record_event(
        tenant_id=tenant_id,
        actor_id=user_id,
        event_kind=(
            f"{resource_type}.{action}".lower() if action else (resource_type or "unknown")
        ),
        outcome="success",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        ip_address=ip,
        user_agent=user_agent,
        owner_scope=owner_scope,
        owner_agent_id=owner_agent_id,
    )
    _schedule_or_run(coro)


def fire_and_forget_audit(**kwargs) -> None:
    """Legacy wrapper — record_event 로 forward (await 없이 호출 가능).

    pii.py / confidentiality.py 가 사용. action / resource_type / new_value 등
    legacy 키를 받아서 record_event 로 변환 + background task 로 schedule.

    D24 §1: kwargs 에 owner_scope/owner_agent_id 가 있으면 record_event 로
    그대로 forward (옵트인). 두 키 모두 default None.
    """
    tenant_id = kwargs.get("tenant_id")
    if tenant_id is None:
        logger.warning("fire_and_forget_audit_missing_tenant")
        return
    action = kwargs.get("action")
    resource_type = kwargs.get("resource_type")
    coro = record_event(
        tenant_id=tenant_id,
        actor_id=kwargs.get("user_id"),
        event_kind=(
            f"{resource_type}.{action}".lower()
            if (resource_type and action)
            else (resource_type or "unknown")
        ),
        outcome=kwargs.get("outcome", "success"),
        action=action,
        resource_type=resource_type,
        resource_id=kwargs.get("resource_id"),
        detail=kwargs.get("detail"),
        old_value=kwargs.get("old_value"),
        new_value=kwargs.get("new_value"),
        ip_address=kwargs.get("ip") or kwargs.get("ip_address"),
        user_agent=kwargs.get("user_agent"),
        request_id=kwargs.get("request_id"),
        owner_scope=kwargs.get("owner_scope"),
        owner_agent_id=kwargs.get("owner_agent_id"),
    )
    _schedule_or_run(coro)


# 모듈 export 명시 (도구가 introspect 할 때 도움)
__all__ = [
    "compute_row_hash",
    "verify_chain",
    "record_event",
    "record_action",
    "fire_and_forget_audit",
]

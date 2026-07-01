"""tool_invocations CRUD — pending_confirm / pending_resume / 결과기록 (델타 #5).

Phase 1.5A Task 8b — confirm_token 보안 강화:
- ``issue_token`` — secrets.token_urlsafe(32) raw + sha256 hash + TTL +
  tenant/account/session/tool/input_hash 5축 binding 으로 INSERT.
- ``consume_token`` — SELECT FOR UPDATE → bind 일치 + expires_at>now() +
  status='pending_confirm' 검증 → 통과 시 status='consumed' 일회용 마킹.
  실패 reason 은 (mismatch / expired / already_consumed / unknown) 으로 분류.

기존 ``insert_pending`` / ``load_pending`` (plaintext token) 은 *deprecated* —
시연 path 호환을 위해 유지. 신규 호출자는 ``issue_token`` / ``consume_token``
을 사용해야 한다. 점진적 마이그레이션 후 제거 예정.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


# 환경변수 — env 로 override 가능. default 5분.
def _ttl_seconds() -> int:
    try:
        return int(os.environ.get("CONFIRM_TOKEN_TTL_SECONDS", "300"))
    except ValueError:
        return 300


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_input_hash(input_args: dict) -> str:
    """tool 입력 인자의 canonical sha256.

    JSON serialize 시 sort_keys + ensure_ascii=False + 압축 separator 로
    *결정적* 직렬화. consume 시점에 동일 args 라면 동일 hash 가 나오도록.
    """
    s = json.dumps(input_args or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_hex(s)


class ToolInvocationStore:
    def __init__(self, db):
        self.db = db

    # -----------------------------------------------------------------
    # Phase 1.5A Task 8b — secure confirm token (issue / consume)
    # -----------------------------------------------------------------

    async def issue_token(
        self,
        *,
        tenant_id: str,
        account_id: str,
        session_id: str | None,
        turn_id: str | None,
        skill_id: str,
        cc_pair_id: str | None,
        tool_name: str,
        input_args: dict,
        ttl_seconds: int | None = None,
    ) -> tuple[str, str, str]:
        """destructive tool 실행 전 confirm token 발급.

        Returns
        -------
        (invocation_id, raw_token, token_hash)
            raw_token 은 호출자가 사용자에게 한 번만 전달해야 한다 (UI 또는 채팅
            메시지). DB 에는 token_hash 만 저장된다. token_hash 는 디버그/로깅
            용도로 함께 반환 (기록 시 raw 대신 hash 만 남기도록).

        binding (5축):
            tenant_id × account_id × session_id × tool_name × input_hash.
            consume 시 모두 일치해야 통과.
        """
        inv_id = f"inv_{uuid.uuid4().hex[:16]}"
        raw_token = secrets.token_urlsafe(32)
        token_hash = _sha256_hex(raw_token)
        ttl = ttl_seconds if ttl_seconds is not None else _ttl_seconds()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        input_hash = canonical_input_hash(input_args)
        # session_id NULL 인 경우는 빈 문자열로 binding (NULL=NULL 비교 회피).
        bound_session = session_id if session_id is not None else ""
        self.db.execute(
            text(
                """
                INSERT INTO tool_invocations
                  (id, tenant_id, session_id, turn_id, skill_id, cc_pair_id,
                   tool_name, input_args, status, resume_token, token_hash,
                   expires_at, bound_tenant_id, bound_account_id,
                   bound_session_id, bound_tool, bound_input_hash, dry_run)
                VALUES
                  (:id, :t, :sid, :tid, :sk, :cc, :tn, CAST(:args AS jsonb),
                   'pending_confirm', :rt_legacy, :token_hash, :expires_at,
                   :b_tenant, :b_account, :b_session, :b_tool, :b_input,
                   FALSE)
                """
            ),
            {
                "id": inv_id,
                "t": tenant_id,
                "sid": session_id,
                "tid": turn_id,
                "sk": skill_id,
                "cc": cc_pair_id,
                "tn": tool_name,
                "args": json.dumps(input_args, ensure_ascii=False, separators=(",", ":")),
                # 시연 path 호환 — 기존 plaintext column 도 채움 (deprecated).
                # 신규 보안 검증은 token_hash + 5축 binding 으로만 수행.
                "rt_legacy": raw_token,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "b_tenant": tenant_id,
                "b_account": account_id,
                "b_session": bound_session,
                "b_tool": tool_name,
                "b_input": input_hash,
            },
        )
        self.db.commit()
        return inv_id, raw_token, token_hash

    async def consume_token(
        self,
        raw_token: str,
        *,
        tenant_id: str,
        account_id: str,
        session_id: str | None,
        tool_name: str,
        input_args: dict,
    ) -> tuple[bool, str, str | None]:
        """raw_token 검증 + 일회용 consume.

        SELECT FOR UPDATE 로 row lock → status='pending_confirm' AND
        expires_at>now() AND 5축 binding 일치 시 status='consumed',
        consumed_at=now() 로 마킹.

        Returns
        -------
        (ok, reason, invocation_id)
            ok=True 일 때 reason='consumed', invocation_id 반환.
            ok=False 일 때 reason ∈ {'unknown','expired','already_consumed',
            'binding_mismatch'} + invocation_id None 또는 발견된 row id.
        """
        if not raw_token:
            return False, "unknown", None
        token_hash = _sha256_hex(raw_token)
        bound_session = session_id if session_id is not None else ""
        input_hash = canonical_input_hash(input_args)

        # 트랜잭션 시작 — SELECT FOR UPDATE 로 동시성 제어.
        # 기존 conn 이 autocommit 모드면 명시 begin 필요. SQLAlchemy 1.x 호환
        # 패턴: ``in_transaction()`` 체크 후 begin.
        # 단순화 — db.begin() 로 nested savepoint or 신규 트랜잭션.
        try:
            row = self.db.execute(
                text(
                    """
                    SELECT id, status, expires_at,
                           bound_tenant_id, bound_account_id,
                           bound_session_id, bound_tool, bound_input_hash,
                           consumed_at
                      FROM tool_invocations
                     WHERE token_hash = :h
                     FOR UPDATE
                    """
                ),
                {"h": token_hash},
            ).mappings().first()

            if row is None:
                return False, "unknown", None

            inv_id = row["id"]
            status = row["status"]

            # 이미 사용된 token.
            if status in ("consumed", "succeeded", "failed", "canceled", "expired", "revoked"):
                return False, "already_consumed", inv_id
            if status not in ("pending_confirm", "pending_resume"):
                return False, "already_consumed", inv_id

            # 만료 확인.
            now_utc = datetime.now(timezone.utc)
            exp = row["expires_at"]
            if exp is None:
                # legacy row — token_hash 는 있으나 expires_at 미설정.
                # 보안 상 거부 (TTL 강제).
                return False, "expired", inv_id
            # exp 가 naive 인 경우 utc 로 가정.
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now_utc:
                # 만료 표시.
                self.db.execute(
                    text("UPDATE tool_invocations SET status='expired' WHERE id=:i"),
                    {"i": inv_id},
                )
                self.db.commit()
                return False, "expired", inv_id

            # 5축 binding 검증.
            if (
                row["bound_tenant_id"] != tenant_id
                or row["bound_account_id"] != account_id
                or (row["bound_session_id"] or "") != bound_session
                or row["bound_tool"] != tool_name
                or row["bound_input_hash"] != input_hash
            ):
                return False, "binding_mismatch", inv_id

            # 통과 — consumed 마킹 (일회용).
            self.db.execute(
                text(
                    """
                    UPDATE tool_invocations
                       SET status='consumed', consumed_at=NOW()
                     WHERE id=:i
                    """
                ),
                {"i": inv_id},
            )
            self.db.commit()
            return True, "consumed", inv_id
        except Exception:
            # 예외 시 rollback — 호출자에게 실패 시그널.
            try:
                self.db.rollback()
            except Exception:
                pass
            raise

    async def revoke_token(self, invocation_id: str) -> None:
        """관리자 또는 cleanup 이 명시 만료 마킹."""
        self.db.execute(
            text(
                "UPDATE tool_invocations SET status='revoked' "
                "WHERE id=:i AND status IN ('pending_confirm','pending_resume')"
            ),
            {"i": invocation_id},
        )
        self.db.commit()

    # -----------------------------------------------------------------
    # Legacy API — 시연 path 호환 (deprecated). 새 코드는 issue_token 사용.
    # -----------------------------------------------------------------

    async def insert_pending(
        self, *, tenant_id: str, session_id: str | None, turn_id: str | None,
        skill_id: str, cc_pair_id: str | None,
        tool_name: str, input_args: dict,
    ) -> tuple[str, str]:
        """[DEPRECATED] plaintext token 발급. 시연 path 호환만 유지.

        새 코드는 ``issue_token`` 을 사용해야 함 (TTL + binding + sha256).
        """
        inv_id = f"inv_{uuid.uuid4().hex[:16]}"
        token = secrets.token_urlsafe(24)
        self.db.execute(text("""
            INSERT INTO tool_invocations
              (id, tenant_id, session_id, turn_id, skill_id, cc_pair_id,
               tool_name, input_args, status, resume_token, dry_run)
            VALUES (:id, :t, :sid, :tid, :sk, :cc, :tn, CAST(:args AS jsonb),
                    'pending_confirm', :rt, FALSE)
        """), {
            "id": inv_id, "t": tenant_id, "sid": session_id, "tid": turn_id,
            "sk": skill_id, "cc": cc_pair_id, "tn": tool_name,
            "args": json.dumps(input_args, ensure_ascii=False, separators=(",", ":")),
            "rt": token,
        })
        self.db.commit()
        return inv_id, token

    async def confirm_result(
        self, invocation_id: str, *, status: str, output: dict | None = None,
        error: str | None = None, duration_ms: int = 0,
        confirmed_by_user_id: str | None = None,
    ) -> None:
        self.db.execute(text("""
            UPDATE tool_invocations
               SET status=:s, output=CAST(:out AS jsonb), error=:err,
                   duration_ms=:dms, executed_at=NOW(),
                   confirmed_by_user=CASE WHEN :by IS NOT NULL THEN TRUE ELSE confirmed_by_user END,
                   confirmed_by_user_id=COALESCE(:by, confirmed_by_user_id)
             WHERE id=:id
        """), {"id": invocation_id, "s": status,
               "out": json.dumps(output or {}, ensure_ascii=False, separators=(",", ":")),
               "err": error, "dms": duration_ms, "by": confirmed_by_user_id})
        self.db.commit()

    async def record_executed(
        self,
        *,
        tenant_id: str,
        session_id: str | None,
        turn_id: str | None,
        skill_id: str,
        tool_name: str,
        input_args: dict,
        output: dict | None,
        status: str,  # 'succeeded' | 'failed' | 'dry_run'
        error: str | None = None,
        duration_ms: int = 0,
    ) -> str:
        """PR-E4 — guard 미주입 경로의 직접 audit. ExecutionPolicyGuard 가
        주관하지 않는 read_only / 일반 tool 호출도 모든 turn 의 모든 tool 을
        ``tool_invocations`` 에 1행씩 영속. PR-D 의 chat_messages.trace 와 결합 —
        turn 단위 trace + tool 단위 audit 두 layer.

        invocation_id 반환 — 호출자가 trace event 의 ``data.invocation_id`` 로
        담아 frontend 가 audit row 로 deep-link 가능.
        """
        inv_id = f"inv_{uuid.uuid4().hex[:16]}"
        self.db.execute(text("""
            INSERT INTO tool_invocations
              (id, tenant_id, session_id, turn_id, skill_id, tool_name,
               input_args, output, status, error, duration_ms, executed_at, dry_run)
            VALUES (:id, :t, :sid, :tid, :sk, :tn,
                    CAST(:args AS jsonb), CAST(:out AS jsonb), :s, :err, :dms, NOW(),
                    :dr)
        """), {
            "id": inv_id, "t": tenant_id, "sid": session_id, "tid": turn_id,
            "sk": skill_id, "tn": tool_name,
            "args": json.dumps(input_args, ensure_ascii=False, separators=(",", ":")),
            "out": json.dumps(output or {}, ensure_ascii=False, separators=(",", ":")),
            "s": status, "err": error, "dms": duration_ms,
            "dr": status == "dry_run",
        })
        self.db.commit()
        return inv_id

    async def get_usage_today(self, skill_id: str) -> int:
        row = self.db.execute(text("""
            SELECT COUNT(*) AS n FROM tool_invocations
             WHERE skill_id=:sk
               AND executed_at IS NOT NULL
               AND executed_at >= date_trunc('day', NOW())
               AND status IN ('succeeded','failed')
        """), {"sk": skill_id}).mappings().first()
        return int(row["n"])

    async def get_last_invocation(self, skill_id: str, input_hash: str) -> dict | None:
        row = self.db.execute(text("""
            SELECT executed_at, output
              FROM tool_invocations
             WHERE skill_id=:sk AND executed_at IS NOT NULL
               AND md5(input_args::text) = :h
             ORDER BY executed_at DESC LIMIT 1
        """), {"sk": skill_id, "h": input_hash}).mappings().first()
        return dict(row) if row else None

    async def load_pending(self, invocation_id: str, *, resume_token: str) -> dict | None:
        row = self.db.execute(text("""
            SELECT id, tenant_id, skill_id, cc_pair_id, tool_name, input_args, status
              FROM tool_invocations
             WHERE id=:id AND resume_token=:t
               AND status IN ('pending_confirm','pending_resume')
        """), {"id": invocation_id, "t": resume_token}).mappings().first()
        return dict(row) if row else None

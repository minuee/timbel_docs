"""PR-Z11A — 등록된 메일 계정 백그라운드 polling worker.

루프 (1분 check interval, 계정별 ``poll_interval_seconds`` 5-60분):

    while not stop:
        for each account where (last_polled_at IS NULL
                                OR last_polled_at + poll_interval < NOW())
                              AND enabled = TRUE:
            try:
                fetch_new(last_uid)
                for mail in fetched: process_email(mail)
                update last_polled_at, last_uid_synced, last_error=NULL
            except Exception as e:
                update last_polled_at=NOW(), last_error=str(e)
                # 계정별 격리 — 한 계정 실패가 다른 계정 polling 안 막음.
        await sleep(check_interval)

원칙:
- 비밀번호 메모리 노출 최소화 — 복호화 후 fetch_new 호출 즉시, 변수 None 으로 폐기.
- ``MAIL_CRED_KEY`` 미설정 시 worker graceful no-op (log warning + idle loop).
- worker 는 *백그라운드* 라 stdout 주의: print() X, logger 만.
- enabled=true 유지 — 사용자가 비밀번호 변경 후 재시도하도록 자동 disable 안 함.
- LLM 미주입 시에도 분류기는 fallback uncertain 으로 동작 (KMS 저장 + 로그 보존).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.common.logging import get_logger
from src.integration.mail import credentials as mail_creds
from src.integration.mail.classifier import EmailClassifier
from src.integration.mail.client import fetch_new
from src.integration.mail.inbox_intake import process_email

log = get_logger(__name__)


DEFAULT_CHECK_INTERVAL = 60        # 초 — 메인 루프 깨어나는 주기
DEFAULT_MAX_FETCH = 50              # 한 계정당 한 polling tick 에 fetch 할 최대 메일
LAST_ERROR_MAX_LEN = 500            # user_mail_accounts.last_error VARCHAR(500)


class MailMirrorWorker:
    """Mail account polling background worker.

    구성:
        - ``db_engine``: SQLAlchemy AsyncEngine
        - ``llm``: classifier 에 주입할 LLM (None 이면 fallback 분류만)
        - ``check_interval``: 메인 루프 sleep 초
        - ``max_fetch_per_tick``: 한 계정당 한 tick 의 fetch 상한

    수명:
        - ``await worker.start()`` — 백그라운드 task 생성
        - ``await worker.stop()`` — task cancel + await
    """

    def __init__(
        self,
        db_engine: AsyncEngine,
        *,
        llm: Any = None,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        max_fetch_per_tick: int = DEFAULT_MAX_FETCH,
    ) -> None:
        self.db_engine = db_engine
        self.llm = llm
        self.check_interval = max(15, int(check_interval))
        self.max_fetch_per_tick = max(1, int(max_fetch_per_tick))
        self._classifier = EmailClassifier(llm=llm)
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # ───────────────── lifecycle ─────────────────

    async def start(self) -> None:
        """백그라운드 polling task 시작. MAIL_CRED_KEY 미설정 시 no-op idle."""
        if self._task is not None and not self._task.done():
            log.info("mail_mirror_worker_already_running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="mail-mirror-worker")
        log.info(
            "mail_mirror_worker_started",
            check_interval=self.check_interval,
            max_fetch_per_tick=self.max_fetch_per_tick,
            creds_available=mail_creds.is_available(),
        )

    async def stop(self) -> None:
        """task cancel + await. 이미 종료된 경우 no-op."""
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        log.info("mail_mirror_worker_stopped")

    # ───────────────── main loop ─────────────────

    async def _loop(self) -> None:
        """폴링 루프. 어떤 예외도 외부로 새지 않도록 wrap."""
        while not self._stop_event.is_set():
            if mail_creds.is_available():
                try:
                    await self._poll_due_accounts()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning("mail_mirror_poll_tick_failed", error=str(exc))
            else:
                # MAIL_CRED_KEY 미설정 — graceful no-op. WARN 은 1회만.
                if not getattr(self, "_warned_no_key", False):
                    log.warning("mail_mirror_idle_no_cred_key")
                    self._warned_no_key = True

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.check_interval
                )
                # stop event triggered → exit
                break
            except asyncio.TimeoutError:
                continue

    # ───────────────── per-tick logic ─────────────────

    async def poll_account_now(
        self, *, mail_account_id: UUID, account_id: UUID
    ) -> dict[str, Any]:
        """수동 동기화 — 단일 메일 계정 즉시 polling.

        Frontend '동기화' 버튼이 호출. due 와 무관하게 강제 실행. 권한 검증은
        호출자 (router) 가 수행 (mail_account.account_id == 인증 account.id).
        watermark 갱신/에러 기록은 _process_account 가 담당.
        """
        async with self.db_engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT id, account_id, host, port, protocol, username,
                               password_encrypted, last_uid_synced,
                               last_polled_at, poll_interval_seconds, enabled
                        FROM user_mail_accounts
                        WHERE id = :mid AND account_id = :aid
                        LIMIT 1
                        """
                    ),
                    {"mid": mail_account_id, "aid": account_id},
                )
            ).first()
        if row is None:
            return {"success": False, "error": "메일 계정을 찾을 수 없습니다"}
        if not row.enabled:
            return {"success": False, "error": "비활성화된 계정"}
        acct = dict(row._mapping)
        try:
            await self._process_account(acct)
            return {
                "success": True,
                "mail_account_id": str(mail_account_id),
                "summary": "동기화 완료",
            }
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "mail_mirror_manual_sync_failed",
                mail_account_id=str(mail_account_id),
                error=str(exc),
            )
            await self._record_account_error(mail_account_id, str(exc))
            return {"success": False, "error": str(exc)}

    async def poll_all_for_account_now(
        self, *, account_id: UUID
    ) -> dict[str, Any]:
        """사용자 의 모든 활성 메일 계정 일괄 동기화."""
        async with self.db_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT id FROM user_mail_accounts
                        WHERE account_id = :aid AND enabled = TRUE
                        """
                    ),
                    {"aid": account_id},
                )
            ).all()
        if not rows:
            return {"success": False, "error": "활성 메일 계정이 없습니다"}
        results = []
        for r in rows:
            res = await self.poll_account_now(
                mail_account_id=UUID(str(r.id)), account_id=account_id
            )
            results.append({"mail_account_id": str(r.id), **res})
        ok = sum(1 for r in results if r.get("success"))
        return {
            "success": ok > 0,
            "polled": len(results),
            "ok": ok,
            "failed": len(results) - ok,
            "results": results,
        }

    async def _poll_due_accounts(self) -> None:
        """due 한 계정 SELECT → 계정별 격리 처리."""
        accounts = await self._fetch_due_accounts()
        if not accounts:
            return
        log.debug("mail_mirror_due_accounts", count=len(accounts))
        for acct in accounts:
            try:
                await self._process_account(acct)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # 계정 단위 격리 — 다음 계정으로 진행
                log.warning(
                    "mail_mirror_account_failed",
                    mail_account_id=str(acct.get("id")),
                    account_id=str(acct.get("account_id")),
                    error=str(exc),
                )
                await self._record_account_error(
                    UUID(str(acct["id"])), str(exc)
                )

    async def _fetch_due_accounts(self) -> list[dict[str, Any]]:
        """``SELECT * FROM user_mail_accounts WHERE enabled AND due``."""
        async with self.db_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT id, account_id, host, port, protocol, username,
                               password_encrypted, last_uid_synced,
                               last_polled_at, poll_interval_seconds
                        FROM user_mail_accounts
                        WHERE enabled = TRUE
                          AND (
                              last_polled_at IS NULL
                              OR last_polled_at +
                                 (poll_interval_seconds || ' seconds')::interval
                                 < NOW()
                          )
                        ORDER BY last_polled_at ASC NULLS FIRST
                        LIMIT 50
                        """
                    )
                )
            ).all()
        return [dict(r._mapping) for r in rows]

    async def _process_account(self, acct: dict[str, Any]) -> None:
        """1 계정의 한 tick — 복호화 → fetch → process_email per mail → watermark 갱신."""
        mail_account_id = UUID(str(acct["id"]))
        account_id = UUID(str(acct["account_id"]))
        # account_id 는 accounts.id (PK), 그러나 KMS document/repository 의
        # tenant_id FK 는 tenants 테이블을 가리킨다. accounts 의
        # personal_tenant_id 가 그 사용자의 tenant. NULL 인 경우 (legacy)
        # account_id 폴백이지만, FK 위반은 여전히 발생.
        personal_tenant_id: UUID | None = None
        try:
            async with self.db_engine.connect() as conn:
                row = await conn.execute(
                    text(
                        "SELECT personal_tenant_id FROM accounts WHERE id = :aid"
                    ),
                    {"aid": account_id},
                )
                ptid = row.scalar()
                if ptid:
                    personal_tenant_id = UUID(str(ptid))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "mail_mirror_personal_tenant_lookup_failed",
                account_id=str(account_id),
                error=str(exc),
            )
        host = str(acct["host"])
        port = int(acct["port"])
        protocol = str(acct["protocol"])
        username = str(acct["username"])
        last_uid = acct.get("last_uid_synced")

        # 비밀번호 복호화 — fetch_new 호출 직후 None 으로 폐기.
        password: str | None = None
        try:
            password = mail_creds.decrypt(bytes(acct["password_encrypted"]))
        except Exception as exc:  # noqa: BLE001
            await self._record_account_error(
                mail_account_id, f"자격증명 복호화 실패: {exc}"
            )
            return

        try:
            fetched, new_last_uid = await fetch_new(
                host=host,
                port=port,
                protocol=protocol,
                username=username,
                password=password,
                last_uid=str(last_uid) if last_uid else None,
                max_fetch=self.max_fetch_per_tick,
            )
        finally:
            # 메모리 노출 최소화 — 복호화된 평문 즉시 폐기.
            password = None
            del password

        log.info(
            "mail_mirror_fetched",
            mail_account_id=str(mail_account_id),
            account_id=str(account_id),
            count=len(fetched),
            new_last_uid=new_last_uid,
        )

        # 첨부 detect 로그 — 향후 OCR 파이프라인 트리거 디버깅 위해 별도 라인.
        # 메일별 attachments 길이 합산 + 비어있지 않은 메일 수.
        attachments_total = 0
        mails_with_attachments = 0
        for mail in fetched:
            atts = getattr(mail, "attachments", None) or []
            if atts:
                attachments_total += len(atts)
                mails_with_attachments += 1
        if attachments_total:
            log.info(
                "mail_mirror_attachments_detected",
                mail_account_id=str(mail_account_id),
                account_id=str(account_id),
                count=attachments_total,
                mails=mails_with_attachments,
            )

        # 메일별 처리 — 한 메일 실패가 다음 메일 막지 않게 격리.
        for mail in fetched:
            try:
                await process_email(
                    account_id=account_id,
                    fetched_email=mail,
                    mail_account_id=mail_account_id,
                    db_engine=self.db_engine,
                    classifier=self._classifier,
                    tenant_id=personal_tenant_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "mail_mirror_process_email_failed",
                    mail_account_id=str(mail_account_id),
                    uid=getattr(mail, "uid", None),
                    error=str(exc),
                )

        # watermark 갱신 — fetch 자체는 성공했으므로 last_polled_at 업데이트 +
        # last_error clear. 0 통이라도 polling 은 성공이므로 watermark 갱신.
        await self._update_watermark(
            mail_account_id=mail_account_id,
            new_last_uid=new_last_uid,
            error=None,
        )

    # ───────────────── DB write helpers ─────────────────

    async def _update_watermark(
        self,
        *,
        mail_account_id: UUID,
        new_last_uid: str | None,
        error: str | None,
    ) -> None:
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE user_mail_accounts
                       SET last_polled_at = NOW(),
                           last_uid_synced = COALESCE(:uid, last_uid_synced),
                           last_error = :err,
                           updated_at = NOW()
                     WHERE id = :id
                    """
                ),
                {
                    "id": mail_account_id,
                    "uid": new_last_uid,
                    "err": (error or None) and (error or "")[:LAST_ERROR_MAX_LEN],
                },
            )

    async def _record_account_error(
        self, mail_account_id: UUID, error_msg: str
    ) -> None:
        """계정 실패 시 ``last_error`` + ``last_polled_at`` 만 갱신.
        ``enabled`` 는 *건드리지 않음* — 한 번 실패가 재시도를 막지 않게.
        """
        truncated = error_msg[:LAST_ERROR_MAX_LEN] if error_msg else None
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE user_mail_accounts
                       SET last_polled_at = NOW(),
                           last_error = :err,
                           updated_at = NOW()
                     WHERE id = :id
                    """
                ),
                {"id": mail_account_id, "err": truncated},
            )

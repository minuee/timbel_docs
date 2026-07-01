"""mail.send — SMTP 발송 도구.

사용자 발화 "X 한테 회신 보내줘" / "Y 메일 발송" 류 plan_orchestrator 가 호출.
user_mail_accounts.smtp_* 자격증명을 Fernet 복호화 후 aiosmtplib 로 발송.

Args:
- to (str | list[str]): 받는 사람 (콤마 분리도 OK).
- subject (str): 제목.
- body_text (str): 본문 (plain).
- body_html (str, 옵션): HTML 본문.
- cc (str | list, 옵션) / bcc (str | list, 옵션).
- in_reply_to (str, 옵션): 회신할 원본 message_id.
- mail_account_id (str, 옵션): 발송 계정 — 미지정 시 사용자 첫 SMTP 활성 계정.
- mail_account_label / mail_account_query (str, 옵션): 부분 매칭으로 계정 선택.
- account_id (str): engine 자동 주입.

반환: {success, message_id?, error?, summary}
"""
from __future__ import annotations

import smtplib
import ssl
import asyncio
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings
from src.common.logging import get_logger
from src.integration.mail import credentials as mail_creds


log = get_logger(__name__)
_ENG: AsyncEngine | None = None


def _engine() -> AsyncEngine:
    global _ENG
    if _ENG is None:
        _ENG = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _ENG


def _coerce_recipients(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, str) and x.strip():
                out.extend([s.strip() for s in x.split(",") if s.strip()])
        return out
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []


async def send(args: dict[str, Any]) -> dict[str, Any]:
    account_id = args.get("account_id")
    if not account_id:
        return {"success": False, "error": "account_id required (engine 자동 주입 미설정)"}

    to_list = _coerce_recipients(args.get("to"))
    cc_list = _coerce_recipients(args.get("cc"))
    bcc_list = _coerce_recipients(args.get("bcc"))
    subject = (args.get("subject") or "").strip()
    body_text = (args.get("body_text") or args.get("body") or "").strip()
    body_html = args.get("body_html") or None
    in_reply_to = args.get("in_reply_to") or None
    mail_account_id = args.get("mail_account_id")
    label_query = (
        args.get("mail_account_label")
        or args.get("mail_account_query")
        or args.get("account_filter")
    )

    if not to_list:
        return {"success": False, "error": "to (받는 사람) 슬롯이 비어있습니다"}
    if not subject and not body_text:
        return {"success": False, "error": "subject 와 body_text 중 하나는 필요합니다"}

    eng = _engine()
    # 발송 계정 선택 — id > label 매칭 > 사용자 첫 활성 SMTP 계정.
    async with eng.connect() as conn:
        if mail_account_id:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT id, label, username,
                               smtp_host, smtp_port, smtp_username,
                               smtp_password_encrypted, smtp_use_tls
                          FROM user_mail_accounts
                         WHERE id = cast(:mid as uuid)
                           AND account_id = cast(:aid as uuid)
                           AND enabled = TRUE
                         LIMIT 1
                        """
                    ),
                    {"mid": str(mail_account_id), "aid": str(account_id)},
                )
            ).first()
        elif label_query:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT id, label, username,
                               smtp_host, smtp_port, smtp_username,
                               smtp_password_encrypted, smtp_use_tls
                          FROM user_mail_accounts
                         WHERE account_id = cast(:aid as uuid)
                           AND enabled = TRUE
                           AND (
                                LOWER(label) LIKE :q
                             OR LOWER(username) LIKE :q
                             OR LOWER(host) LIKE :q
                           )
                         ORDER BY created_at ASC
                         LIMIT 1
                        """
                    ),
                    {
                        "aid": str(account_id),
                        "q": f"%{str(label_query).strip().lower()}%",
                    },
                )
            ).first()
        else:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT id, label, username,
                               smtp_host, smtp_port, smtp_username,
                               smtp_password_encrypted, smtp_use_tls
                          FROM user_mail_accounts
                         WHERE account_id = cast(:aid as uuid)
                           AND enabled = TRUE
                           AND smtp_host IS NOT NULL
                           AND smtp_password_encrypted IS NOT NULL
                         ORDER BY created_at ASC
                         LIMIT 1
                        """
                    ),
                    {"aid": str(account_id)},
                )
            ).first()

    if row is None:
        return {
            "success": False,
            "error": "발송 가능한 메일 계정을 찾지 못했습니다. 설정에서 SMTP 정보를 등록해주세요.",
        }
    if not row.smtp_host or not row.smtp_password_encrypted:
        return {
            "success": False,
            "error": (
                f"메일 계정 '{row.label or row.username}' 에 SMTP 정보가 없습니다. "
                "설정에서 SMTP host/port/username/password 를 등록해주세요."
            ),
        }

    try:
        password = mail_creds.decrypt(bytes(row.smtp_password_encrypted))
    except Exception as exc:  # noqa: BLE001
        log.warning("mail_send_decrypt_failed", error=str(exc))
        return {"success": False, "error": f"SMTP 자격증명 복호화 실패: {exc}"}

    sender_addr = row.smtp_username or row.username
    msg = EmailMessage()
    msg["From"] = sender_addr
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject or "(제목 없음)"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-Id"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text or "(본문 없음)")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    all_rcpts = to_list + cc_list + bcc_list

    # Path 5 — cooldown: 동일 user × 첫 수신자에 60s 내 재전송 차단.
    # Redis 미가용 시 silent-pass (발송 허용) — 안정성 우선.
    _COOLDOWN_SECONDS = 60
    if to_list:
        try:
            from src.common.redis import get_redis_client as _get_redis
            _redis = await _get_redis()
            _cooldown_key = f"mail_cooldown:{account_id}:{to_list[0]}"
            if await _redis.exists(_cooldown_key):
                return {
                    "success": False,
                    "error": (
                        f"cooldown: 동일 수신자({to_list[0]})에게 {_COOLDOWN_SECONDS}s 내 재전송 차단됩니다. "
                        "잠시 후 다시 시도해주세요."
                    ),
                }
            await _redis.setex(_cooldown_key, _COOLDOWN_SECONDS, "1")
        except Exception as _cd_exc:  # noqa: BLE001
            log.debug("mail_send_cooldown_skip", reason=repr(_cd_exc)[:100])

    def _smtp_send_blocking() -> dict[str, Any]:
        host = row.smtp_host
        port = int(row.smtp_port or (465 if not row.smtp_use_tls else 587))
        ctx = ssl.create_default_context()
        diag: dict[str, Any] = {"steps": []}

        # Path 3 — 포트/TLS 분기 정확화.
        # 465 → SMTP_SSL (Implicit SSL).
        # 587 + smtp_use_tls=True → SMTP + STARTTLS.
        # 그 외 (smtp_use_tls=False + 587 포함) → 평문 SMTP.
        def _open_smtp_on_port(h: str, p: int, use_starttls: bool) -> smtplib.SMTP:
            # path 4: 기본 10s — user_mail_accounts 에 smtp_timeout 컬럼이
            # 없으므로 (alembic 064 까지 미정의) 상수 fallback. row 에 해당 컬
            # 럼이 추가될 경우 getattr 로 자동 픽업.
            timeout = getattr(row, "smtp_timeout", None) or 10
            if p == 465:
                return smtplib.SMTP_SSL(h, p, timeout=timeout, context=ctx)
            s = smtplib.SMTP(h, p, timeout=timeout)
            s.ehlo()
            if use_starttls:
                s.starttls(context=ctx)
                s.ehlo()
            return s

        _use_ssl = (port == 465)
        _use_starttls = bool(row.smtp_use_tls) and not _use_ssl

        def _open_smtp() -> smtplib.SMTP:
            return _open_smtp_on_port(host, port, _use_starttls)

        def _open_smtp_with_fallback() -> tuple[smtplib.SMTP, int]:
            """default_port 시도, ConnectionRefused/SSL 에러 시 587 STARTTLS fallback."""
            try:
                return _open_smtp_on_port(host, port, _use_starttls), port
            except (ConnectionRefusedError, ssl.SSLError, smtplib.SMTPException) as e:
                if port != 587:
                    log.warning(
                        "smtp_port_fallback",
                        host=host,
                        from_port=port,
                        reason=repr(e)[:120],
                    )
                    diag["steps"].append(("port_fallback", port, 587, repr(e)[:120]))
                    return _open_smtp_on_port(host, 587, True), 587
                raise

        def _reconnect() -> smtplib.SMTP:
            """fresh SMTP 세션. RSET 시도 안 함 (서버가 RSET 후 TCP drop 하므로)."""
            s = _open_smtp()
            try:
                login_code, login_resp = s.login(sender_addr, password)
                diag["steps"].append(("reconnect_login", login_code, str(login_resp)[:80]))
            except smtplib.SMTPNotSupportedError:
                diag["steps"].append(("reconnect_login", "skipped_not_supported"))
            return s

        def _attempt_send(smtp_obj: smtplib.SMTP) -> None:
            """mail/rcpt/data 시퀀스 단일 시도. 실패 시 예외 전파."""
            code, resp = smtp_obj.mail(sender_addr)
            diag["steps"].append(("mail", code, str(resp)[:120]))
            if not (200 <= code < 300):
                raise smtplib.SMTPResponseException(code, resp)

            for rcpt in all_rcpts:
                code, resp = smtp_obj.rcpt(rcpt)
                diag["steps"].append(("rcpt", rcpt, code, str(resp)[:120]))
                if not (200 <= code < 300):
                    raise smtplib.SMTPResponseException(code, resp)

            code, resp = smtp_obj.data(msg.as_string())
            diag["steps"].append(("data", code, str(resp)[:120]))
            if not (200 <= code < 300):
                raise smtplib.SMTPResponseException(code, resp)

        smtp, _used_port = _open_smtp_with_fallback()
        diag["steps"].append(("open_smtp", _used_port))
        try:
            # 1) login — Hanbiro 처럼 implicit auth 가 다음 명령에 영향 주는 경우
            # 대비해 login 응답 코드 검증.
            try:
                login_code, login_resp = smtp.login(sender_addr, password)
                diag["steps"].append(("login", login_code, str(login_resp)[:80]))
            except smtplib.SMTPNotSupportedError:
                # 일부 서버는 AUTH 미지원이지만 익명 송신 OK (드뭄)
                diag["steps"].append(("login", "skipped_not_supported"))
            # 1.5) RSET — 일부 SMTP (Hanbiro 등) 가 LOGIN 직후 MAIL 을 또 다른
            # AUTH 로 해석해 503 'already authenticated' 반환. RSET 으로 트랜
            # 잭션 상태 리셋 후 MAIL 시도. 표준 SMTP 명령이라 모든 서버 호환.
            try:
                rset_code, rset_resp = smtp.rset()
                diag["steps"].append(("rset", rset_code, str(rset_resp)[:80]))
            except smtplib.SMTPResponseException as e:
                diag["steps"].append(("rset", e.smtp_code, str(e.smtp_error)[:80]))
            except (smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError) as e:
                # Path 1a: RSET 자체가 disconnect 예외 — 즉시 reconnect.
                # OSError 는 의도적으로 제외: SMTPResponseException 이 OSError 를 상속하므로
                # 5xx 응답 오류까지 catch 되는 것을 방지.
                diag["steps"].append(("rset_disconnected", repr(e)[:120]))
                try:
                    smtp.quit()
                except Exception:  # noqa: BLE001
                    pass
                smtp = _reconnect()
            else:
                # Path 1b: RSET 성공했더라도 Hanbiro 는 TCP drop 할 수 있음.
                # noop() 으로 server-alive probe — 실패 시 reconnect.
                try:
                    noop_code, noop_resp = smtp.noop()
                    diag["steps"].append(("post_rset_noop", noop_code, str(noop_resp)[:80]))
                except (smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError) as e:
                    diag["steps"].append(("post_rset_noop_disconnected", repr(e)[:120]))
                    try:
                        smtp.quit()
                    except Exception:  # noqa: BLE001
                        pass
                    smtp = _reconnect()
            # 2) mail/rcpt/data — Path 2: disconnect 류 예외 시 1회 재시도.
            # OSError 제외: SMTPResponseException(OSError) 까지 retry 되지 않도록.
            try:
                _attempt_send(smtp)
            except (smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError) as e:
                diag["steps"].append(("send_disconnected_retry", repr(e)[:120]))
                try:
                    smtp.quit()
                except Exception:  # noqa: BLE001
                    pass
                smtp = _reconnect()
                _attempt_send(smtp)  # 두 번째 실패 시 그대로 outer except 로 전파
        finally:
            try:
                smtp.quit()
                diag["steps"].append(("quit", "ok"))
            except smtplib.SMTPResponseException as e:
                diag["steps"].append(("quit", e.smtp_code, str(e.smtp_error)[:80]))
            except Exception:  # noqa: BLE001
                pass
        return diag

    diag_result: dict[str, Any] | None = None
    try:
        diag_result = await asyncio.to_thread(_smtp_send_blocking)
        log.info(
            "mail_send_smtp_diagnostic",
            host=row.smtp_host,
            port=row.smtp_port,
            steps=diag_result.get("steps") if diag_result else None,
        )
    except smtplib.SMTPResponseException as exc:
        # P11-19 — 일부 SMTP 서버 (예: Hanbiro) 가 비표준 250 응답 ('flushed')
        # 을 SMTPResponseException 으로 raise. 250 은 성공 코드라 메일은 실
        # 발송되었을 가능성 높음. quit() 단계의 변칙 응답 무시.
        if 200 <= int(exc.smtp_code) < 300:
            log.info(
                "mail_send_unusual_2xx_treated_as_ok",
                host=row.smtp_host,
                port=row.smtp_port,
                code=int(exc.smtp_code),
                detail=str(exc.smtp_error)[:100],
            )
        else:
            log.warning(
                "mail_send_smtp_failed",
                host=row.smtp_host,
                port=row.smtp_port,
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return {"success": False, "error": f"SMTP 발송 실패 ({exc.smtp_code}): {exc.smtp_error!r}"}
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "mail_send_smtp_failed",
            host=row.smtp_host,
            port=row.smtp_port,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return {"success": False, "error": f"SMTP 발송 실패: {exc}"}
    finally:
        password = ""  # noqa: F841 — 평문 폐기

    # 발송 로그 — email_processing_log 에 outbound row INSERT (사용자가 챗에서
    # '내가 보낸 메일' 검색 가능하도록).
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        outbound_classification = {
            "category": "sent",
            "direction": "outbound",
            "priority": "normal",
            "extracted_entities": {"to": to_list, "cc": cc_list, "bcc": bcc_list},
        }
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO email_processing_log
                      (account_id, mail_account_id, message_id,
                       from_address, from_domain, subject,
                       received_at, classification, trust_score,
                       actions_taken)
                    VALUES
                      (cast(:aid as uuid), cast(:mid as uuid), :msgid,
                       :from_addr, :from_dom, :subj,
                       :recv, CAST(:cls AS jsonb), 1.0,
                       CAST(:actions AS jsonb))
                    """
                ),
                {
                    "aid": str(account_id),
                    "mid": str(row.id),
                    "msgid": (msg["Message-Id"] or "")[:500],
                    "from_addr": sender_addr,
                    "from_dom": sender_addr.split("@")[-1] if "@" in sender_addr else "",
                    "subj": subject[:500],
                    "recv": _dt.now(_tz.utc),
                    "cls": _json.dumps(outbound_classification, ensure_ascii=False),
                    "actions": _json.dumps(
                        [
                            {
                                "kind": "send",
                                "to": to_list,
                                "ts": _dt.now(_tz.utc).isoformat(),
                            }
                        ],
                        ensure_ascii=False,
                    ),
                },
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("mail_send_log_insert_failed", error=str(exc))

    log.info(
        "mail_send_ok",
        sender=sender_addr,
        to=len(to_list),
        cc=len(cc_list),
        bcc=len(bcc_list),
        subject=subject[:60],
    )
    return {
        "success": True,
        "from": sender_addr,
        "to": to_list,
        "cc": cc_list,
        "subject": subject,
        "message_id": msg["Message-Id"],
        "summary": f"메일 발송 완료 — '{subject}' → {', '.join(to_list)}",
    }

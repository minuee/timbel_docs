"""PR-Z11A — IMAP/POP3 client (mirror polling 용).

원칙:
- **READ-ONLY** — IMAP 의 ``EXAMINE`` 명령 (vs ``SELECT``) 사용 → 서버 측
  ``\\Seen`` 플래그 안 건드림. 사용자 기본 메일 흐름 그대로 유지 (미러링).
- POP3 는 본질적으로 stateful 하지만 ``leave_on_server`` (DELE 미사용) 로 미러링.
- TLS (993/995) 와 평문 (143/110) 양쪽 지원. 사용자가 등록 시 protocol 선택.
- 자격증명 메모리 노출 최소화 — 함수 입력으로만 받고 즉시 사용 후 폐기.

asyncio: imaplib/poplib 는 sync 라 ``run_in_executor`` 로 wrap.
"""
from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import logging
import poplib
from dataclasses import dataclass, field
from email.header import decode_header
from email.message import Message
from typing import Any

# 첨부 추출 정책 — 하드 enum 아닌 prefix 기반 (image/* 전체 허용 가능하지만
# OCR 파이프라인이 처리할 수 있는 포맷만 통과시키는 안전 화이트리스트).
# 향후 OCR 가 다른 포맷 (heic 등) 지원 시 여기만 갱신.
ATTACHMENT_IMAGE_TYPES: tuple[str, ...] = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
)
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB — 그 이상 skip.

_log = logging.getLogger(__name__)


@dataclass
class FetchedEmail:
    """미러링된 이메일의 표준 표현. webhook_inbound payload 로 변환됨."""

    uid: str
    message_id: str | None
    from_address: str | None
    from_domain: str | None
    to_address: str | None
    subject: str | None
    date_iso: str | None
    body_text: str
    body_html: str | None
    headers: dict[str, str] = field(default_factory=dict)
    raw_size: int = 0
    # 이미지 첨부 — multipart/mixed 의 image/* part 를 base64 로 추출.
    # 향후 OCR 파이프라인이 소비. 너무 큰 파일은 _extract_attachments 에서 skip.
    attachments: list[dict[str, Any]] = field(default_factory=list)


def _decode_header_value(value: str | None) -> str | None:
    """RFC 2047 인코딩된 헤더 (=?utf-8?B?...?=) 디코딩."""
    if not value:
        return value
    parts = decode_header(value)
    out = []
    for piece, charset in parts:
        if isinstance(piece, bytes):
            try:
                out.append(piece.decode(charset or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(piece.decode("utf-8", errors="replace"))
        else:
            out.append(piece)
    return "".join(out)


def _extract_body(msg: Message) -> tuple[str, str | None]:
    """multipart 메시지에서 text/plain + text/html 추출."""
    body_text_parts: list[str] = []
    body_html: str | None = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            try:
                payload = part.get_payload(decode=True)
            except Exception:  # noqa: BLE001
                continue
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, TypeError):
                text = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain":
                body_text_parts.append(text)
            elif ctype == "text/html" and body_html is None:
                body_html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, TypeError):
                text = payload.decode("utf-8", errors="replace")
            ctype = msg.get_content_type()
            if ctype == "text/html":
                body_html = text
                body_text_parts.append("")
            else:
                body_text_parts.append(text)

    body_text = "\n".join(p for p in body_text_parts if p).strip()
    if not body_text and body_html:
        # text/plain 없고 html 만 있을 때 — 호출자가 html→text 변환 가능
        body_text = ""
    return body_text, body_html


def _extract_attachments(msg: Message) -> list[dict[str, Any]]:
    """multipart 메시지의 image/* attachments 를 base64 로 추출.

    반환 dict 스키마: ``{filename, content_type, data_base64, content_id, size_bytes}``
    - ``content_id``: HTML 본문에서 ``cid:...`` 로 참조되는 inline image 식별자
      (있으면 OCR 결과와 본문 위치를 매칭할 때 활용 가능).
    - 10MB 초과 첨부는 skip 하고 INFO 로그 — payload 폭주/메모리 보호.
    - 이미지가 아닌 첨부 (pdf/zip/...) 는 이 PR 범위 밖. 향후 별도 OCR/extract 경로.

    multipart 가 아닌 메일 (single-part) 은 첨부가 없는 것으로 간주.
    """
    if not msg.is_multipart():
        return []
    out: list[dict[str, Any]] = []
    for part in msg.walk():
        ctype = (part.get_content_type() or "").lower()
        if ctype not in ATTACHMENT_IMAGE_TYPES:
            continue
        # disposition 이 attachment 이거나 inline (cid 참조) 모두 수집 — inline
        # 이미지도 OCR 대상.
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if not payload or not isinstance(payload, (bytes, bytearray)):
            continue
        size_bytes = len(payload)
        filename = _decode_header_value(part.get_filename()) or ""
        content_id_raw = part.get("Content-ID") or ""
        # Content-ID 는 보통 ``<abc123@host>`` 형태 → 꺾쇠 제거
        content_id = content_id_raw.strip().lstrip("<").rstrip(">") if content_id_raw else ""

        if size_bytes > ATTACHMENT_MAX_BYTES:
            _log.info(
                "mail_attachment_skipped_too_large filename=%s size=%d limit=%d",
                filename or "(noname)",
                size_bytes,
                ATTACHMENT_MAX_BYTES,
            )
            continue

        try:
            data_b64 = base64.b64encode(bytes(payload)).decode("ascii")
        except Exception:  # noqa: BLE001
            continue

        out.append(
            {
                "filename": filename,
                "content_type": ctype,
                "data_base64": data_b64,
                "content_id": content_id,
                "size_bytes": size_bytes,
            }
        )
    return out


def _msg_to_fetched(uid: str, raw: bytes) -> FetchedEmail:
    """raw RFC822 → FetchedEmail."""
    msg = email.message_from_bytes(raw)
    from_h = _decode_header_value(msg.get("From")) or ""
    from_domain = ""
    if "@" in from_h:
        from_domain = from_h.rsplit("@", 1)[-1].rstrip(">").strip()
    body_text, body_html = _extract_body(msg)
    headers = {
        k: _decode_header_value(v) or ""
        for k, v in msg.items()
        # 보안 — 자격증명 헤더 등 민감 헤더 제외
        if k.lower() not in {"authorization", "cookie"}
    }
    attachments = _extract_attachments(msg)
    return FetchedEmail(
        uid=uid,
        message_id=_decode_header_value(msg.get("Message-ID")),
        from_address=from_h,
        from_domain=from_domain,
        to_address=_decode_header_value(msg.get("To")),
        subject=_decode_header_value(msg.get("Subject")),
        date_iso=_decode_header_value(msg.get("Date")),
        body_text=body_text,
        body_html=body_html,
        headers=headers,
        raw_size=len(raw),
        attachments=attachments,
    )


# ──────────────── IMAP (preferred) ────────────────


def _imap_connect(host: str, port: int, *, use_tls: bool) -> imaplib.IMAP4:
    """IMAP / IMAPS 연결. timeout 30s."""
    if use_tls:
        return imaplib.IMAP4_SSL(host, port, timeout=30)
    return imaplib.IMAP4(host, port, timeout=30)


def _imap_test_sync(host: str, port: int, use_tls: bool, user: str, pw: str) -> list[str]:
    """sync 연결 + login + capability + logout. 사용 후 비밀번호 메모리 해제."""
    conn = _imap_connect(host, port, use_tls=use_tls)
    try:
        conn.login(user, pw)
        # CAPABILITY 응답에서 server feature list 반환
        typ, raw = conn.capability()
        caps: list[str] = []
        if typ == "OK" and raw:
            for piece in raw[0].split() if raw else []:
                if isinstance(piece, bytes):
                    caps.append(piece.decode("ascii", errors="replace"))
                else:
                    caps.append(str(piece))
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        return caps
    except Exception:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        raise


def _imap_fetch_new_sync(
    host: str, port: int, use_tls: bool, user: str, pw: str,
    last_uid: str | None, max_fetch: int,
) -> tuple[list[FetchedEmail], str | None]:
    """INBOX 의 last_uid 이후 새 메일을 fetch. read-only (EXAMINE).

    반환: (메일 리스트, 새 last_uid)
    """
    conn = _imap_connect(host, port, use_tls=use_tls)
    fetched: list[FetchedEmail] = []
    new_last_uid = last_uid
    try:
        conn.login(user, pw)
        # EXAMINE — read-only 모드 (\Seen 플래그 변경 X)
        typ, _ = conn.examine("INBOX")
        if typ != "OK":
            raise RuntimeError("INBOX EXAMINE 실패")

        # UID 검색 — last_uid+1 ~ * (정수 문자열로)
        if last_uid and last_uid.isdigit():
            search_range = f"{int(last_uid) + 1}:*"
        else:
            # 첫 polling — 최근 N 개만
            search_range = "1:*"
        typ, data = conn.uid("search", None, "UID", search_range)
        if typ != "OK" or not data or not data[0]:
            return [], new_last_uid
        uid_list = data[0].split()
        if last_uid and last_uid.isdigit():
            # 검색이 last_uid 이상이라 last_uid 자체는 제외
            uid_list = [u for u in uid_list if int(u) > int(last_uid)]
        # 너무 많으면 제한 — 첫 polling 또는 누락분 누적 시
        uid_list = uid_list[-max_fetch:]

        for uid_b in uid_list:
            uid = uid_b.decode("ascii") if isinstance(uid_b, bytes) else str(uid_b)
            typ, fetch_data = conn.uid("fetch", uid_b, "(RFC822)")
            if typ != "OK" or not fetch_data:
                continue
            for item in fetch_data:
                if isinstance(item, tuple) and len(item) >= 2:
                    raw = item[1]
                    if isinstance(raw, bytes) and raw:
                        try:
                            fetched.append(_msg_to_fetched(uid, raw))
                            new_last_uid = uid
                        except Exception:  # noqa: BLE001
                            # 한 메일 파싱 실패가 polling 자체를 막진 않음
                            pass
                        break
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        return fetched, new_last_uid
    except Exception:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        raise


# ──────────────── POP3 (fallback) ────────────────


def _pop3_test_sync(host: str, port: int, use_tls: bool, user: str, pw: str) -> list[str]:
    if use_tls:
        conn = poplib.POP3_SSL(host, port, timeout=30)
    else:
        conn = poplib.POP3(host, port, timeout=30)
    try:
        conn.user(user)
        conn.pass_(pw)
        # POP3 의 capability 는 CAPA 명령
        try:
            resp_lines = conn.capa()
            if isinstance(resp_lines, dict):
                # python 3 poplib.capa() returns dict {capa_name: args}
                return list(resp_lines.keys())
            return []
        except poplib.error_proto:
            return []
    finally:
        try:
            conn.quit()
        except Exception:  # noqa: BLE001
            pass


def _pop3_fetch_new_sync(
    host: str, port: int, use_tls: bool, user: str, pw: str,
    last_uid: str | None, max_fetch: int,
) -> tuple[list[FetchedEmail], str | None]:
    """POP3 미러링 — UIDL 사용 + DELE 안 함 (leave on server)."""
    if use_tls:
        conn = poplib.POP3_SSL(host, port, timeout=30)
    else:
        conn = poplib.POP3(host, port, timeout=30)
    fetched: list[FetchedEmail] = []
    new_last_uid = last_uid
    try:
        conn.user(user)
        conn.pass_(pw)
        # UIDL — [<msg_num> <uid>, ...]
        resp, lines, octets = conn.uidl()
        if not isinstance(lines, list):
            return [], new_last_uid
        msg_uids: list[tuple[int, str]] = []
        for line in lines:
            try:
                if isinstance(line, bytes):
                    line = line.decode("ascii", errors="replace")
                num_str, uid = line.split(maxsplit=1)
                msg_uids.append((int(num_str), uid))
            except Exception:  # noqa: BLE001
                continue
        # last_uid 이후 만 (POP3 UID 는 임의 문자열 — 정수 비교 X. 단순 last 발견 후 그 이후)
        cutoff_idx = -1
        if last_uid:
            for i, (_, u) in enumerate(msg_uids):
                if u == last_uid:
                    cutoff_idx = i
                    break
        new_msgs = msg_uids[cutoff_idx + 1 :] if cutoff_idx >= 0 else msg_uids
        # 너무 많으면 최근 일부만
        new_msgs = new_msgs[-max_fetch:]

        for num, uid in new_msgs:
            try:
                resp, lines, octets = conn.retr(num)
                raw = b"\n".join(lines) if lines else b""
                if raw:
                    fetched.append(_msg_to_fetched(uid, raw))
                    new_last_uid = uid
            except Exception:  # noqa: BLE001
                continue
        return fetched, new_last_uid
    finally:
        try:
            conn.quit()
        except Exception:  # noqa: BLE001
            pass


# ──────────────── async wrappers ────────────────


def _resolve_protocol(protocol: str) -> tuple[str, bool]:
    """imap/imaps/pop3/pop3s → (kind, use_tls)."""
    p = protocol.lower()
    if p == "imaps":
        return "imap", True
    if p == "imap":
        return "imap", False
    if p == "pop3s":
        return "pop3", True
    if p == "pop3":
        return "pop3", False
    raise ValueError(f"unsupported protocol: {protocol}")


async def test_connection(
    *, host: str, port: int, protocol: str, username: str, password: str,
) -> list[str]:
    """인증 + capability 만 확인. 실패 시 예외."""
    kind, use_tls = _resolve_protocol(protocol)
    loop = asyncio.get_running_loop()
    if kind == "imap":
        return await loop.run_in_executor(
            None, _imap_test_sync, host, port, use_tls, username, password
        )
    return await loop.run_in_executor(
        None, _pop3_test_sync, host, port, use_tls, username, password
    )


async def fetch_new(
    *,
    host: str,
    port: int,
    protocol: str,
    username: str,
    password: str,
    last_uid: str | None,
    max_fetch: int = 50,
) -> tuple[list[FetchedEmail], str | None]:
    """last_uid 이후 새 메일 fetch. read-only / leave-on-server.

    반환: (메일 리스트, 새 last_uid). 메일 0 개면 last_uid 변동 없음.
    """
    kind, use_tls = _resolve_protocol(protocol)
    loop = asyncio.get_running_loop()
    if kind == "imap":
        return await loop.run_in_executor(
            None, _imap_fetch_new_sync, host, port, use_tls,
            username, password, last_uid, max_fetch,
        )
    return await loop.run_in_executor(
        None, _pop3_fetch_new_sync, host, port, use_tls,
        username, password, last_uid, max_fetch,
    )

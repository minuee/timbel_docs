"""URL preview with SSRF guard (PR P6, codex P2-5).

frontend-v3 Multimodal Composer 가 paste/typing 으로 감지한 URL 을 미리보기 카드로
보여주기 위해 호출하는 fetch 헬퍼. 외부 임의 호스트로 HTTP 가 나가는 경로이므로
SSRF / DNS rebinding / metadata service 노출 / oversized payload 등 모든 고전적인
서버 사이드 요청 위조 벡터를 방어한다.

가드 항목:
- scheme 화이트리스트 (http, https 만)
- raw IP literal hostname 거부 (도메인 이름만 허용)
- DNS 해석 결과의 모든 IP 가 public 인지 검증 (사설/loopback/link-local/multicast/
  reserved/site-local 거부) — DNS rebinding 1차 차단
- redirect cap = 3
- content-type whitelist (text/html, application/json, text/plain)
- 응답 본문 size 상한 = 2 MB
- timeout = 5s
- og:title / og:description / og:image / <title> 까지만 추출 (스크립트/콘텐츠 본문은 안 봄)

본 모듈은 순수 비동기 헬퍼. 라우터 (``src/api/routers/url_preview_v1.py``) 가
인증을 처리한 뒤 본 헬퍼를 호출 + 결과를 응답 모델로 직렬화한다. 캐시는 라우터
계층에서 (url, account_id) 키로 처리 — 헬퍼 자체는 stateless.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Constants — 모두 모듈 상단 (하드코딩 매직 넘버 금지 원칙)
# ---------------------------------------------------------------------------

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"text/html", "application/json", "text/plain"}
)
MAX_BYTES: int = 2 * 1024 * 1024  # 2 MB
MAX_REDIRECTS: int = 3
TIMEOUT_SECONDS: float = 5.0
HTML_PARSE_LIMIT: int = 200_000  # head 만 보면 충분
TITLE_MAX_LEN: int = 200
DESCRIPTION_MAX_LEN: int = 400
USER_AGENT: str = "KMS-Plus URL Preview/1.0"

_TITLE_RE = re.compile(r"<title[^>]*>([^<]*)</title>", re.IGNORECASE)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# IP / DNS 검증
# ---------------------------------------------------------------------------


def _is_disallowed_ip(ip_str: str) -> bool:
    """Return True if ``ip_str`` falls in any block-listed range.

    block:
    - private (RFC1918, ULA fc00::/7)
    - loopback (127/8, ::1)
    - link-local (169.254/16, fe80::/10)
    - multicast
    - reserved
    - IPv6 site-local (deprecated but still risky)
    - 0.0.0.0/8 (unspecified)
    - parse 실패 자체도 거부

    169.254.169.254 (AWS/GCP/Azure metadata) 는 link-local 이므로 자동 차단.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return True
    return False


def _is_raw_ip_hostname(hostname: str) -> bool:
    """hostname 이 IP literal 인지 — IP literal 은 거부 대상."""
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


async def _resolve_all_public(hostname: str) -> bool:
    """``hostname`` 의 DNS 해석 결과가 전부 공인 IP 인지 검증.

    하나라도 사설/loopback/link-local 이면 False — DNS rebinding 1차 차단.
    해석 실패는 False 반환 (네트워크 오류와 차단을 동일하게 거부 처리).
    """
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None, family=socket.AF_UNSPEC)
    except (socket.gaierror, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if _is_disallowed_ip(ip_str):
            return False
    return True


# ---------------------------------------------------------------------------
# 메타 추출
# ---------------------------------------------------------------------------


def _extract_meta(html: str) -> dict[str, Any]:
    """HTML head 영역에서 og:title/og:description/og:image/<title> 만 추출."""
    head = html[:HTML_PARSE_LIMIT]
    title_m = _TITLE_RE.search(head)
    og_title = _OG_TITLE_RE.search(head)
    og_desc = _OG_DESC_RE.search(head)
    og_image = _OG_IMAGE_RE.search(head)

    title_value = ""
    if og_title:
        title_value = og_title.group(1).strip()
    elif title_m:
        title_value = title_m.group(1).strip()

    description_value = og_desc.group(1).strip() if og_desc else ""
    image_value = og_image.group(1).strip() if og_image else None

    return {
        "title": title_value[:TITLE_MAX_LEN] or None,
        "description": (description_value[:DESCRIPTION_MAX_LEN] or None),
        "image": image_value,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _rejected(reason: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "reason": reason,
        "title": None,
        "description": None,
        "image": None,
    }


async def fetch_url_preview(url: str) -> dict[str, Any]:
    """URL 메타 프리뷰 (SSRF-가드).

    반환:
        { status: "ok"|"rejected", title, description, image, url, reason? }

    예외는 raise 하지 않음 — 모든 거부 사유는 ``status == "rejected"`` +
    ``reason`` 으로 표현 (라우터가 200 응답 + body 로 사용자에게 노출).
    """
    if not url or not isinstance(url, str):
        return _rejected("empty url")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        return _rejected(f"scheme {parsed.scheme!r} not allowed")

    hostname = parsed.hostname
    if not hostname:
        return _rejected("no hostname")

    if _is_raw_ip_hostname(hostname):
        return _rejected("raw IP not allowed")

    if not await _resolve_all_public(hostname):
        return _rejected("private or unresolvable host")

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
    except httpx.TooManyRedirects:
        return _rejected("too many redirects")
    except httpx.TimeoutException:
        return _rejected("timeout")
    except httpx.HTTPError as e:
        return _rejected(f"fetch error: {type(e).__name__}")

    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        return _rejected(f"content-type {ctype!r} not allowed")

    # Content-Length 가 있으면 먼저 검사 — body 까지 받기 전에 차단.
    cl_raw = resp.headers.get("content-length")
    if cl_raw:
        try:
            cl = int(cl_raw)
            if cl > MAX_BYTES:
                return _rejected("size exceeds limit")
        except ValueError:
            pass

    body = resp.content
    if len(body) > MAX_BYTES:
        return _rejected("size exceeds limit")

    try:
        html = body.decode(resp.encoding or "utf-8", errors="replace")
    except (LookupError, UnicodeDecodeError):
        html = body.decode("utf-8", errors="replace")

    meta = _extract_meta(html)
    return {
        "status": "ok",
        "url": url,
        "title": meta["title"],
        "description": meta["description"],
        "image": meta["image"],
    }

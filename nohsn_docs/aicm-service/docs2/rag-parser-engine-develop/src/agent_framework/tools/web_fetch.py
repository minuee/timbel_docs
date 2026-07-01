"""web.fetch — URL 본문 추출 도구 (외부 지식 습득 2단계).

자비스 비전 시나리오 1 의 ``web.search`` 다음 단계. 검색 결과 상위 URL 의
본문을 받아 LLM 이 합성·요약할 수 있게 정제.

본문 추출:
- httpx GET (User-Agent 명시, follow_redirects=True, 8초 timeout).
- Content-Type 이 ``text/html`` 류면 BeautifulSoup 으로 ``<script>``/
  ``<style>``/``<nav>``/``<footer>`` 등 노이즈 제거 후 텍스트 추출.
- ``<title>`` 태그 추출.
- max_chars 만큼 절단 (기본 5000) — vLLM 입력 길이 보호.

SSRF 방어 (보안 가드 — 사례 enum 아닌 *원리*):
- scheme 은 http/https 만 허용. file://, data://, gopher:// 등 차단.
- hostname 이 localhost / 127.x / 10.x / 172.16-31.x / 192.168.x / ::1 / fe80::
  같은 *내부 네트워크* 이면 차단. 정규식 / IP 비교로 결정 — 화이트리스트가
  아닌 블랙리스트 (외부 호출은 *기본 허용*, 내부망만 *명시 차단*).
- ``localhost`` / ``host.docker.internal`` / metadata.google.internal 같이
  유명한 내부 호스트 이름도 차단.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from src.common.logging import get_logger

log = get_logger(__name__)


# 외부에 노출하지 말아야 할 호스트 이름 (literal name 차단).
# IP 차단은 ipaddress.is_private + is_loopback + is_link_local 로 *원리적* 처리.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "host.docker.internal",
        "metadata.google.internal",
        "metadata",
        "169.254.169.254",  # AWS / GCP / Azure metadata IP literal
    }
)

# user-agent 는 일반 브라우저처럼 보이게 (네이버/매체 일부가 빈 UA 차단).
_DEFAULT_UA = (
    "Mozilla/5.0 (compatible; AICM-Agent/1.0; +https://aicm.local) "
    "WebFetchTool/1.0"
)


def _is_safe_url(url: str) -> tuple[bool, str]:
    """SSRF 가드. 차단 사유를 함께 반환 (사용자에게 설명 가능하도록)."""
    try:
        parsed = urlparse(url)
    except Exception as e:  # noqa: BLE001
        return False, f"URL parse 실패: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"허용되지 않은 scheme: {parsed.scheme!r} (http/https 만)"

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "hostname 없음"

    if host in _BLOCKED_HOSTNAMES:
        return False, f"내부 호스트 차단: {host}"

    # IP literal 검증
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False, f"내부/특수 IP 차단: {host}"
        if ip.is_reserved or ip.is_unspecified:
            return False, f"예약/미지정 IP 차단: {host}"
    except ValueError:
        # hostname (DNS 이름) — IP 가 아님. 호출 시 OS resolver 가 처리.
        pass

    return True, ""


def _extract_text(html: str, max_chars: int) -> tuple[str, str]:
    """간단한 readability — script/style 등 제거 후 본문 텍스트.

    bs4 미설치 / 파싱 실패 시: HTML 원문에서 태그만 거칠게 strip 한 텍스트
    fallback. 아예 fail 하지 않도록 *graceful*.

    Returns: (title, content).
    """
    title = ""
    content = ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        for tag in soup(
            ["script", "style", "noscript", "nav", "footer", "aside", "form"]
        ):
            tag.decompose()
        content = soup.get_text(separator="\n", strip=True)
    except Exception as e:  # noqa: BLE001
        log.debug("web_fetch_bs4_failed", error=str(e))
        # 매우 거친 fallback: tag 제거. LLM 이 정리하도록 그대로 전달.
        import re

        content = re.sub(r"<[^>]+>", " ", html or "")
        content = re.sub(r"\s+", " ", content).strip()

    if max_chars > 0 and len(content) > max_chars:
        content = content[:max_chars]
    return title, content


async def fetch(args: dict[str, Any]) -> dict[str, Any]:
    """web.fetch — URL 본문 추출.

    Args:
        url (str, required): 가져올 URL. http/https 만.
        max_chars (int, default=5000): 본문 길이 제한 (vLLM 입력 보호).

    Returns:
        ``{success, url, title, content, fetched_at, status}``.

        - success=true 면 본문 추출 성공.
        - status: HTTP 상태코드 또는 차단 사유 string ("blocked: <reason>").
        - fetched_at: ISO8601 UTC.
    """
    url = str(args.get("url") or "").strip()
    try:
        max_chars = int(args.get("max_chars") or 5000)
    except (TypeError, ValueError):
        max_chars = 5000
    max_chars = max(0, min(max_chars, 50000))

    if not url:
        return {
            "success": False,
            "url": "",
            "title": "",
            "content": "",
            "status": "missing_url",
            "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        }

    ok, reason = _is_safe_url(url)
    if not ok:
        log.info("web_fetch_blocked", url=url, reason=reason)
        return {
            "success": False,
            "url": url,
            "title": "",
            "content": "",
            "status": f"blocked: {reason}",
            "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        }

    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": _DEFAULT_UA},
        ) as client:
            r = await client.get(url)
            status = r.status_code
            ctype = (r.headers.get("content-type") or "").lower()
            body = r.text or ""
    except httpx.TimeoutException:
        return {
            "success": False,
            "url": url,
            "title": "",
            "content": "",
            "status": "timeout",
            "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:  # noqa: BLE001
        log.debug("web_fetch_failed", url=url, error=str(e))
        return {
            "success": False,
            "url": url,
            "title": "",
            "content": "",
            "status": f"error: {type(e).__name__}",
            "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        }

    if status >= 400:
        return {
            "success": False,
            "url": url,
            "title": "",
            "content": "",
            "status": status,
            "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        }

    # HTML 이면 readability, 아니면 그대로 텍스트 (일부 사이트는 plain).
    if "html" in ctype or "<html" in body[:500].lower():
        title, content = _extract_text(body, max_chars)
    else:
        title = ""
        content = body[:max_chars] if max_chars > 0 else body

    return {
        "success": bool(content),
        "url": url,
        "title": title,
        "content": content,
        "status": status,
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
    }

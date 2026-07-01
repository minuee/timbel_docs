"""``/api/v1/citations`` — citation [N] popup 정보 조회 (모든 채널 공용).

사용자 명시 (2026-05-08):
> "테스트챗창이나, 텔레그램에서는 참조 문서를 링크가 없어. 그래서 볼수가 없는데,
>  링크를 활성화 해주고, 그 링크에 해당 하는 정보를 보여 줄 수 있는 방법을 찾아줘."

사용자 명시 (2026-05-11):
> "Telegram landing page도 같이 처리해"

GET /api/v1/citations/{block_id}
  Accept: application/json (default)  → JSON (frontend / OpenAI / API client)
  Accept: text/html                   → HTML preview (Telegram 모바일 브라우저)
  Headers: Authorization: Bearer <jwt> (또는 X-Tenant-Id) — Web/API client.
  Query: t=<hmac_token>&exp=<unix_ts> — Telegram guest (JWT 없음).

  block_id: UUID (engine `_build_citation_items` 의 stable_id 가 block_id 일 때만 매칭)
  Returns (JSON): { "data": {
    id, title, document_id, document_title, repo_id, repo_name, block_type,
    page_number, section_title, snippet (200), content (4000 자 표시용 자름),
    source_format
  } }
  — Phase 0 byte-equal JSON snapshot 보존.

D41 (Phase 2 — 2026-05-11) — HTML preview + HMAC token:
- JWT 우선 / token 후순위 (Web 사용자 회귀 0).
- guest token-only path → HTML 강제 (게스트에 JSON 스키마 노출 차단).
- Accept q-value 파싱 (default JSON, 하드코딩 회피).
- HTML 응답 헤더: CSP / no-store / no-referrer / nosniff / Vary: Accept.
- 모든 placeholder HTML escape (XSS 차단).
- cross-tenant: token/JWT tenant ↔ block.repository.tenant_id → 404 (generic).
- HMAC 서명 → 만료 순서 (oracle 차단, citation_token.py 안에서 enforce).

GPT-5 P0 fix (Phase 0 검증):
- 합성 ID (`doc_id#idx`) 수용 X — 오로지 block_id (UUID) 만 lookup.
- tenant 격리 강제 — block.repository.tenant_id == 인증 측 tenant_id.

본 endpoint 는 *조회 only* — write 없음. PII / 민감 도메인 체크는 RBAC layer
가 별도로 수행 (현재는 tenant 일치만).
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import _decode_bearer
from src.common.logging import get_logger
from src.common.security.citation_token import verify_citation_token
from src.core.database import get_db
from src.core.models.block import Block
from src.core.models.document import Document
from src.core.models.repository import Repository

log = get_logger(__name__)

router = APIRouter(prefix="/citations", tags=["인용 (citations)"])


_SNIPPET_LEN = 200
_CONTENT_LEN = 4000  # 사용자 표시용 — chunk 본문이 매우 길면 자름.

# HTML 응답 헤더 — D41 spec §1, §4 (GPT-5 P0).
# CSP 매우 엄격 — inline style 만 허용 (`<style>` 안 CSS), script/img/font/connect
# 모두 차단. base-uri/frame-ancestors none — clickjack 차단.
_HTML_HEADERS = {
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",  # defense-in-depth (CSP frame-ancestors 보완)
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "Vary": "Accept",
}

# JSON 응답 헤더 — CDN/proxy 캐시 mix 차단 + 민감 자료 no-store.
_JSON_VARY = "Accept, Authorization"


# ---------------------------------------------------------------------------
# Accept header q-value 파싱 helper
# ---------------------------------------------------------------------------
def _preferred_html_media(accept_header: str) -> str | None:
    """Accept header q-value 파싱. default = JSON (None 반환).

    GPT-5 phase 0 v3 P0 fix:
    - UA sniffing 제거 (하드코딩 회피).
    - Accept 누락 / ``*/*`` only → JSON (Web frontend 보호).
    - ``application/json`` 명시 시 우선 (q 동률이어도).
    - text/html 또는 application/xhtml+xml q > json q → 더 높은 쪽 media_type 반환.

    Returns:
        ``"text/html"`` 또는 ``"application/xhtml+xml"`` 또는 ``None`` (= JSON).
    """
    if not accept_header:
        return None
    parts = [p.strip() for p in accept_header.split(",")]
    json_q = -1.0
    html_q = -1.0
    xhtml_q = -1.0
    for p in parts:
        media, *params = p.split(";")
        media = media.strip().lower()
        q = 1.0
        for pr in params:
            pr = pr.strip()
            if pr.startswith("q="):
                try:
                    q = float(pr[2:])
                except ValueError:
                    q = 0.0
        if media == "text/html":
            html_q = max(html_q, q)
        elif media == "application/xhtml+xml":
            xhtml_q = max(xhtml_q, q)
        elif media == "application/json":
            json_q = max(json_q, q)
    best_html = max(html_q, xhtml_q)
    # JSON 이 명시 + html 보다 크거나 같으면 JSON 우선 (Web frontend 보호).
    if json_q >= 0 and json_q >= best_html:
        return None
    if best_html < 0:
        return None
    # 더 높은 쪽 media_type 반환 (Content-Type 정합).
    if xhtml_q > html_q:
        return "application/xhtml+xml"
    return "text/html"


# ---------------------------------------------------------------------------
# HTML escape + template
# ---------------------------------------------------------------------------
def _esc(s: Any) -> str:
    """HTML escape — XSS 차단 (spec §2 P0).

    ``&`` → ``&amp;`` (먼저), ``<`` → ``&lt;``, ``>`` → ``&gt;``, ``"`` → ``&quot;``.
    None / 빈 값은 빈 문자열.
    """
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# inline HTML template — jinja2 의존 회피 (보안 surface 최소화, spec §2 P0).
# 모든 placeholder 는 _esc 처리된 값으로 대체. 조건부 meta span 은 빈 값이면 omit.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_for_title} - 근거 자료</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
               "Noto Sans KR", sans-serif;
  max-width: 720px;
  margin: 0 auto;
  padding: 1rem 1.25rem;
  line-height: 1.65;
  color: #1f2937;
  background: #ffffff;
}}
header {{
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.75rem;
  margin-bottom: 1.25rem;
}}
h1 {{
  font-size: 1.2rem;
  margin: 0 0 0.4rem 0;
  color: #111827;
  word-break: keep-all;
}}
.meta {{
  color: #6b7280;
  font-size: 0.875rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}}
.meta span {{ white-space: nowrap; }}
main {{
  font-size: 1rem;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f9fafb;
  padding: 1rem;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}}
footer {{
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid #e5e7eb;
  font-size: 0.8rem;
  color: #9ca3af;
  text-align: center;
}}
.badge {{
  display: inline-block;
  padding: 0.1rem 0.45rem;
  font-size: 0.75rem;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 3px;
}}
</style>
</head>
<body>
<header>
<h1>{title}</h1>
<div class="meta">{meta_spans}</div>
</header>
<main>{content}</main>
<footer>Locus KMS - 근거 자료</footer>
</body>
</html>"""


def _render_html(data: dict) -> str:
    """citation data → 안전한 HTML 문자열.

    모든 placeholder _esc 처리. 빈 값 meta span 은 omit.
    """
    # 메타 span 들 — 조건부 omit (빈 값이면 출력 X).
    spans: list[str] = []
    repo_name = data.get("repo_name")
    if repo_name:
        spans.append(f'<span class="badge">{_esc(repo_name)}</span>')
    section_title = data.get("section_title")
    if section_title:
        spans.append(f'<span>{_esc(section_title)}</span>')
    page_number = data.get("page_number")
    if page_number is not None and page_number != "":
        spans.append(f'<span>p.{_esc(page_number)}</span>')
    block_type = data.get("block_type")
    if block_type:
        spans.append(f'<span>{_esc(block_type)}</span>')
    meta_spans = "".join(spans)

    title = _esc(data.get("title") or data.get("document_title") or "(제목 없음)")
    # <title> 태그용 — HTML escape 와 동일하지만, 더 명시적.
    title_for_title = title  # 이미 escape 됨.
    content = _esc(data.get("content") or "")

    return _HTML_TEMPLATE.format(
        title=title,
        title_for_title=title_for_title,
        meta_spans=meta_spans,
        content=content,
    )


# ---------------------------------------------------------------------------
# tenant_id 결정 — JWT 우선, token 후순위 (spec §4 변경 2).
# ---------------------------------------------------------------------------
async def _resolve_auth(
    *,
    request: Request,
    block_id: uuid.UUID,
    t: str | None,
    exp: int | None,
    authorization: str | None,
    x_tenant_id: str | None,
) -> tuple[uuid.UUID, bool]:
    """인증 우선순위 처리.

    1) JWT (Authorization: Bearer ...) 이 valid 면 그것 사용 (Web 회귀 0).
    2) X-Tenant-Id 헤더 (legacy 미들웨어 path) — 있으면 사용.
    3) HMAC token (t + exp query) — Telegram guest path.
    4) 모두 없으면 401.

    Returns:
        ``(tenant_id, authed_via_token)`` — authed_via_token=True 면 guest path
        로 HTML 강제 (JSON 차단).

    Raises:
        HTTPException 401 (인증 누락 / token 서명 invalid).
        HTTPException 410 (token 만료).
    """
    # 1) JWT path — Web / API client. valid JWT 면 token 만료 무관.
    payload = _decode_bearer(authorization)
    if payload:
        tid_from_jwt = payload.get("tenant_id")
        if tid_from_jwt:
            try:
                return uuid.UUID(str(tid_from_jwt)), False
            except (ValueError, TypeError):
                pass  # invalid tenant_id in JWT — fall through.

    # 2) request.state.tenant_id (legacy 미들웨어가 set) 또는 X-Tenant-Id 헤더.
    #    Web/admin path 의 기존 동작 보존.
    state_tid = getattr(request.state, "tenant_id", None)
    if state_tid:
        try:
            return uuid.UUID(str(state_tid)), False
        except (ValueError, TypeError):
            pass
    if x_tenant_id:
        try:
            return uuid.UUID(str(x_tenant_id)), False
        except (ValueError, TypeError):
            pass

    # 3) HMAC token path — Telegram guest. JWT 없는 사용자만 도달.
    if t is not None and exp is not None:
        result = verify_citation_token(
            block_id=str(block_id),
            token=t,
            exp=exp,
        )
        if result.signature_invalid:
            # 만료 오라클 차단 — 서명 invalid 와 만료 모두 401 처럼 보이게 X.
            # spec 은 signature_invalid = 401, expired = 410 분리.
            raise HTTPException(status_code=401, detail="유효하지 않은 링크")
        if result.expired:
            raise HTTPException(status_code=410, detail="링크가 만료되었습니다")
        # 통과
        assert result.tenant_id is not None
        return result.tenant_id, True

    # 4) 모두 없음 — 인증 누락. 개발 환경 호환 (기존 get_current_tenant_id 의
    #    APP_ENV=development fallback) 은 *불허* — guest landing 의 안전 보장.
    raise HTTPException(status_code=401, detail="인증이 필요합니다")


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------
@router.get(
    "/{block_id}",
    summary="citation [N] popup 정보 조회 (JSON or HTML preview)",
)
async def get_citation_detail(
    block_id: uuid.UUID,
    request: Request,
    response: Response,
    t: str | None = Query(None, description="HMAC token (Telegram guest path)"),
    exp: int | None = Query(None, description="token expiration unix ts"),
    authorization: str | None = Header(None),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    """citation marker `[N]` 클릭 시 frontend / Telegram / OpenAI compatible 가 호출.

    응답 분기:
    - Accept: application/json (default) → JSON {data: {...}}
    - Accept: text/html → HTML preview (Telegram 모바일 브라우저)
    - guest token-only path → HTML 강제 (Accept 무관, JSON 차단)

    block_id 가 인증 tenant 의 repository 에 속하지 않으면 404 (tenant 격리).
    block 미존재도 404.
    """
    # 1) 인증 — JWT 우선, token 후순위. guest token 이면 authed_via_token=True.
    tenant_id, authed_via_token = await _resolve_auth(
        request=request,
        block_id=block_id,
        t=t, exp=exp,
        authorization=authorization,
        x_tenant_id=x_tenant_id,
    )

    # 2) block lookup
    stmt = select(Block).where(Block.id == block_id)
    block = (await db.execute(stmt)).scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="citation 을 찾을 수 없습니다")

    # 3) repository — tenant 격리 검증 (token 도, JWT 도 동일하게 비교).
    repo_stmt = select(Repository).where(Repository.id == block.repository_id)
    repo = (await db.execute(repo_stmt)).scalar_one_or_none()
    if repo is None or repo.tenant_id != tenant_id:
        # GPT-5 P0 — tenant 누출 차단. 메시지는 generic 으로 (enumeration 방지).
        # token tenant_id 와 block.repository.tenant_id mismatch 시도 동일하게 404.
        raise HTTPException(status_code=404, detail="citation 을 찾을 수 없습니다")

    # 4) document — title / source_format 조회.
    doc_stmt = select(Document).where(Document.id == block.document_id)
    doc = (await db.execute(doc_stmt)).scalar_one_or_none()
    if doc is None:
        # block 은 있지만 document 가 없는 경우 — soft-deleted 등.
        raise HTTPException(status_code=404, detail="citation 을 찾을 수 없습니다")

    # 5) page_number / section_title — block.source_location / properties 에서 추출.
    page_number = None
    section_title = None
    if isinstance(block.source_location, dict):
        page_number = block.source_location.get("page_number") or block.source_location.get("page")
        section_title = block.source_location.get("section_title") or block.source_location.get("heading")
    if isinstance(block.meta_info, dict):
        if section_title is None:
            section_title = block.meta_info.get("section_title") or block.meta_info.get("heading")

    # 6) content — 사용자 표시용 자름.
    content_full = block.content or ""
    snippet = content_full[:_SNIPPET_LEN]
    content_clipped = content_full[:_CONTENT_LEN]

    data = {
        "id": str(block.id),
        "title": doc.title or "(제목 없음)",
        "document_id": str(doc.id),
        "document_title": doc.title or None,
        "repo_id": str(repo.id),
        "repo_name": repo.name or None,
        "block_type": block.block_type or None,
        "page_number": page_number,
        "section_title": section_title,
        "snippet": snippet,
        "content": content_clipped,
        "source_format": doc.source_format or None,
    }

    # 7) 응답 분기 — Accept q-value + guest token 강제 분기.
    preferred_media = _preferred_html_media(request.headers.get("accept", ""))
    # GPT-5 phase 0 v3 — guest token path 는 *HTML 만* (게스트에 JSON 스키마 노출 차단).
    if authed_via_token and preferred_media is None:
        preferred_media = "text/html"

    if preferred_media:
        html = _render_html(data)
        return HTMLResponse(
            content=html,
            media_type=preferred_media,
            headers=_HTML_HEADERS,
        )

    # JSON 응답 (Web / API client) — Vary: Accept, Authorization 으로 CDN 분리.
    response.headers["Vary"] = _JSON_VARY
    response.headers["Cache-Control"] = "no-store, private"
    return {"data": data}


__all__ = ["router"]

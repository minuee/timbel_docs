"""``/api/v1/knowledge`` — 지식 자동 초안 생성 (LLM 기반).

NoteCreateDialog (frontend-v3) 의 *자동 생성* 모드가 호출하는 엔드포인트.
사용자가 제목·주제 요약·키워드·길이를 주면 vLLM (gemma-4-31b/26b-MoE) 으로
한국어 markdown 본문을 1 회 호출 → 사용자가 NotionEditor 에서 검토·수정 후
기존 KMS upload 흐름을 통해 저장한다.

설계 원칙:
- 본 엔드포인트는 *생성 only*. 저장 (documents INSERT) 은 호출자(프런트)가
  /agent/chat/upload 또는 /api/v1/doc-draft/register-knowledge 로 별도 처리.
- JWT 인증 필수. tenant 스코프는 따로 강제하지 않음 — 어떤 활성 tenant 에서든
  지식 작성을 보조하는 도구이고, 실제 저장 시점에 해당 tenant scope 적용.
- LLM timeout 30s. 에러 시 502 (외부 LLM 장애) — 프런트는 다이얼로그 내 토스트.
- 입력 schema 위반 422 (FastAPI 기본).

memory: 이모지 X, 한국어 prompt/응답.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["지식 자동 작성"])


# ── Schemas ──────────────────────────────────────────────────────────────


TargetLength = Literal["short", "standard", "detailed"]


class AutoDraftRequest(BaseModel):
    """지식 자동 초안 요청.

    - title: 문서 제목 (1-200자, 필수).
    - topic_summary: 주제 1-3줄 요약 (1-2000자, 필수).
    - keywords: 강조 키워드 (선택, 최대 30개).
    - context_hint: 배경/출처 hint (선택, 최대 4000자).
    - target_length: short(~500) / standard(~1500) / detailed(~3000).
    """

    title: str = Field(..., min_length=1, max_length=200)
    topic_summary: str = Field(..., min_length=1, max_length=2000)
    keywords: list[str] | None = Field(default=None, max_length=30)
    context_hint: str | None = Field(default=None, max_length=4000)
    target_length: TargetLength = "standard"

    @field_validator("keywords")
    @classmethod
    def _strip_keywords(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [k.strip() for k in v if isinstance(k, str) and k.strip()]
        return cleaned[:30] or None


class AutoDraftResponse(BaseModel):
    markdown: str
    generated_at: datetime
    model: str
    target_length: TargetLength


# ── Auth helper ──────────────────────────────────────────────────────────


def _account_id_from_bearer(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    try:
        payload = decode_token(token)
    except InvalidToken as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    return str(sub)


# ── Prompt build ─────────────────────────────────────────────────────────


_LENGTH_HINTS: dict[str, str] = {
    "short": (
        "분량: 약 500 토큰 내외 (간단). 핵심 4-5 섹션만 사용 — 개요, 핵심 내용, "
        "주의사항, Q&A. 각 섹션 2-4문장."
    ),
    "standard": (
        "분량: 약 1500 토큰 내외 (표준). 7 섹션 권장 — 개요, 배경, 핵심 내용, "
        "예시, 주의사항, 참고자료, Q&A. 각 섹션 4-8문장 또는 4-6 항목."
    ),
    "detailed": (
        "분량: 약 3000 토큰 내외 (상세). 7 섹션 모두 포함하고 각 섹션을 충실히 "
        "확장 — 표·코드 블록·예시 다수 활용. 각 섹션 8-15문장."
    ),
}


def _build_system_prompt(target_length: str) -> str:
    return (
        "당신은 한국어 지식 베이스 큐레이터다. 사용자가 제공한 주제를 받아 "
        "팀 위키에 등록할 수 있는 *Markdown* 형식의 한국어 지식 문서를 작성한다.\n"
        "\n"
        "출력 규칙:\n"
        "- 첫 줄은 '# {제목}' 형식 — 사용자가 준 title 을 그대로 사용.\n"
        "- 섹션은 ## (h2) 로 구성. 필요 시 ### (h3) 하위 섹션.\n"
        "- 권장 7 섹션: 개요 / 배경 / 핵심 내용 / 예시 / 주의사항 / 참고자료 / Q&A.\n"
        "- 한국어 존댓말, 비즈니스 격식.\n"
        "- 추측·창작 금지 — 사용자가 제공한 topic_summary/keywords/context_hint "
        "  범위 안에서만 서술. 모르는 사실은 '추가 조사 필요' 로 표시.\n"
        "- 표·글머리 기호·코드 블록 적극 활용 (가독성 우선).\n"
        "- 출력은 Markdown 본문 *그대로*. 인사말/메타 코멘트/```markdown 펜스 X.\n"
        "\n"
        f"## 길이 조정\n{_LENGTH_HINTS[target_length]}"
    )


def _build_user_prompt(req: AutoDraftRequest) -> str:
    parts: list[str] = []
    parts.append(f"# 제목\n{req.title}")
    parts.append(f"# 주제 요약\n{req.topic_summary}")
    if req.keywords:
        parts.append("# 강조 키워드\n" + ", ".join(req.keywords))
    if req.context_hint:
        parts.append(f"# 배경/출처 hint\n{req.context_hint}")
    parts.append(
        "위 내용을 바탕으로 한국어 Markdown 지식 문서를 작성하시오. "
        "title 을 # 헤더로 시작하고, 권장 섹션 구성을 따른다."
    )
    return "\n\n".join(parts)


# ── vLLM 호출 (non-streaming) ────────────────────────────────────────────


_MAX_TOKENS_BY_LENGTH: dict[str, int] = {
    "short": 1024,
    "standard": 2560,
    "detailed": 4096,
}


async def _call_vllm(system: str, user: str, target_length: str) -> tuple[str, str]:
    """vLLM chat/completions 단일 호출. (markdown, model_name) 반환."""
    base = (
        getattr(settings, "VLLM_URL", None)
        or getattr(settings, "SLLM_GEMMA_URL", "http://vllm:8000/v1")
    )
    model = (
        getattr(settings, "VLLM_MODEL", None)
        or getattr(settings, "SLLM_GEMMA_MODEL", "gemma-4-31b")
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": _MAX_TOKENS_BY_LENGTH.get(target_length, 2560),
        "temperature": 0.3,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base}/chat/completions", json=payload)
    except httpx.TimeoutException as exc:
        log.warning("knowledge_auto_draft_llm_timeout", error=str(exc))
        raise HTTPException(502, "LLM timeout (30s) — 잠시 후 다시 시도해 주세요.") from exc
    except httpx.HTTPError as exc:
        log.warning("knowledge_auto_draft_llm_http_error", error=str(exc))
        raise HTTPException(502, f"LLM 호출 실패: {exc}") from exc

    if resp.status_code >= 400:
        body = resp.text[:300]
        log.warning(
            "knowledge_auto_draft_llm_status_error",
            status=resp.status_code,
            body=body,
        )
        raise HTTPException(502, f"LLM error {resp.status_code}: {body!r}")

    try:
        obj = resp.json()
        content = (
            ((obj.get("choices") or [{}])[0]).get("message", {}).get("content")
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("knowledge_auto_draft_llm_parse_failed", error=str(exc))
        raise HTTPException(502, f"LLM response parse failed: {exc}") from exc

    if not isinstance(content, str) or not content.strip():
        raise HTTPException(502, "LLM 응답이 비어 있습니다.")

    return content.strip(), str(model)


def _normalize_markdown(text: str, title: str) -> str:
    """LLM 응답 후처리.

    - 일부 모델이 ```markdown ... ``` 펜스로 감싸는 경우 제거.
    - 첫 줄에 # 헤더가 없으면 title 헤더 추가.
    """
    s = text.strip()
    # ```markdown ... ``` fence 제거
    if s.startswith("```"):
        # fence 첫 줄과 마지막 ``` 라인 제거
        first_nl = s.find("\n")
        if first_nl != -1:
            inner = s[first_nl + 1:]
            if inner.rstrip().endswith("```"):
                inner = inner.rstrip()[:-3]
            s = inner.strip()
    # 첫 줄에 h1 (# ) 헤더가 없으면 title 추가.
    # ## (h2) 로 시작하는 경우도 h1 부재로 간주 — 사용자 title 을 최상위로 보장.
    first_line = s.split("\n", 1)[0].strip()
    has_h1 = first_line.startswith("# ") and not first_line.startswith("## ")
    if not has_h1:
        s = f"# {title.strip()}\n\n{s}"
    return s


# ── Endpoint ─────────────────────────────────────────────────────────────


@router.post(
    "/auto-draft",
    response_model=AutoDraftResponse,
    summary="지식 자동 초안 생성 (LLM 1회 호출)",
)
async def auto_draft(
    body: AutoDraftRequest,
    authorization: str = Header(...),
) -> AutoDraftResponse:
    """주제·키워드·길이를 받아 한국어 markdown 지식 문서를 LLM 으로 1회 생성.

    - 시간: standard 길이 기준 평균 5-15초 (vLLM gemma-4-31b/26b-MoE).
    - timeout: 30s, 초과 시 502.
    - 출력은 NotionEditor 가 그대로 받을 수 있는 markdown 본문.
    """
    _ = _account_id_from_bearer(authorization)  # JWT 검증만 수행

    system = _build_system_prompt(body.target_length)
    user = _build_user_prompt(body)

    log.info(
        "knowledge_auto_draft_start",
        title=body.title[:60],
        target_length=body.target_length,
        keywords_count=len(body.keywords or []),
    )

    raw, model = await _call_vllm(system, user, body.target_length)
    markdown = _normalize_markdown(raw, body.title)

    log.info(
        "knowledge_auto_draft_done",
        title=body.title[:60],
        markdown_chars=len(markdown),
        model=model,
    )

    return AutoDraftResponse(
        markdown=markdown,
        generated_at=datetime.now(timezone.utc),
        model=model,
        target_length=body.target_length,
    )

"""kms.save_research — agent 가 합성한 본문을 KMS 에 저장 (외부 지식 습득 3단계).

자비스 비전 시나리오 1 의 마무리. ``web.search`` → ``web.fetch`` → ``reasoning``
(LLM 합성) 의 산출물을 KMS documents 테이블에 active 로 박아두면 다음 turn
부터 ``kms_rag.search`` 로 재검색 가능.

저장 경로:
- ``agent_document_store.create_item`` 사용 — async-engine 기반, tenant 격리,
  ``__agent_data__`` repository + ``research_note`` (default) document_type.
- 본문은 ``processing_meta.body.content`` 에 저장. ``source_urls`` /
  ``original_query`` / ``generated_at`` 메타 첨부.
- status='active' 즉시 저장 (parse worker 우회 — 합성 본문은 이미 정제 상태).

확장 여지: 추후 RAG 인덱싱 (chunking + embedding) 이 필요하면 별도 워커가
``research_note`` 타입 문서를 polling 해 청크/임베딩 채워 넣을 수 있음. 본 도구
인터페이스는 그대로 유지.

원칙:
- tenant_id 는 engine ``_enrich_plan_tool_args`` 가 자동 주입. 호출자 LLM 은
  명시 X.
- title / content 는 호출자 reasoning step 이 합성. 본 도구는 *저장만* — 어떤
  내용이 중요한가는 판단 X.
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import create_async_engine

from src.agent_framework.storage import agent_document_store
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


_DEFAULT_DOC_TYPE = "research_note"


def _coerce_tenant_id(raw: Any) -> UUID | None:
    """tenant_id 는 engine 이 str 또는 UUID 로 주입. UUID 로 정규화."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def save(args: dict[str, Any]) -> dict[str, Any]:
    """kms.save_research — agent 합성 본문을 KMS 에 active document 로 저장.

    Args:
        title (str, required): 문서 제목. 호출자 reasoning step 이 합성.
        content (str, required): 본문 (합성된 정리). 호출자가 web.fetch 결과들을
            요약·통합한 결과.
        source_type (str, default="research_note"): document_type 이름. 기본은
            ``research_note`` 이지만 호출자가 다른 분류 (예: ``meeting_note``,
            ``reference_doc``) 사용 가능.
        source_urls (list[str], optional): 출처 URL 들. metadata 에 보관 — 사용자가
            "어디서 가져온 정보야?" 물으면 reasoning step 이 활용.
        original_query (str, optional): 사용자 원래 발화 (예: "B200 KV cache
            영향 정리해줘"). 재검색 시 매칭 단서.
        tenant_id (str/UUID, *engine 자동 주입*): tenant 격리 필수. 호출자 LLM 은
            args 에 명시 안 해도 됨 — engine ``_enrich_plan_tool_args`` 가 채움.

    Returns:
        ``{success, document_id, summary, source_type, tenant_id}``.

        - success=false 면 tenant_id 누락 / DB 오류. summary 에 사유.
    """
    title = str(args.get("title") or "").strip()
    content = str(args.get("content") or "").strip()
    source_type = str(args.get("source_type") or _DEFAULT_DOC_TYPE).strip() or _DEFAULT_DOC_TYPE
    source_urls = args.get("source_urls") or []
    original_query = str(args.get("original_query") or "").strip()

    if not title:
        return {
            "success": False,
            "document_id": None,
            "summary": "kms.save_research: title 미명시.",
        }
    if not content:
        return {
            "success": False,
            "document_id": None,
            "summary": "kms.save_research: content 미명시.",
        }

    tenant_uuid = _coerce_tenant_id(args.get("tenant_id"))
    if tenant_uuid is None:
        return {
            "success": False,
            "document_id": None,
            "summary": (
                "kms.save_research: tenant_id 미주입 (engine 자동 주입 실패). "
                "사용자 인증 컨텍스트 확인 필요."
            ),
        }

    # source_urls 는 list 가 아니면 단일 string 으로 받았을 수 있음 — 정규화.
    if isinstance(source_urls, str):
        source_urls = [source_urls] if source_urls.strip() else []
    elif not isinstance(source_urls, (list, tuple)):
        source_urls = []
    source_urls = [str(u).strip() for u in source_urls if str(u).strip()]

    body = {
        "content": content,
        "source_urls": source_urls,
        "original_query": original_query,
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "_synthesized_by": "agent.web_research",
    }

    eng = create_async_engine(settings.DATABASE_URL)
    try:
        doc_id = await agent_document_store.create_item(
            engine=eng,
            tenant_id=tenant_uuid,
            document_type_name=source_type,
            title=title,
            body=body,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "kms_save_research_failed",
            tenant_id=str(tenant_uuid),
            source_type=source_type,
            error=str(exc),
        )
        return {
            "success": False,
            "document_id": None,
            "summary": f"kms.save_research DB 오류: {type(exc).__name__}",
        }
    finally:
        await eng.dispose()

    log.info(
        "kms_save_research_ok",
        tenant_id=str(tenant_uuid),
        document_id=str(doc_id),
        source_type=source_type,
        content_chars=len(content),
        url_count=len(source_urls),
    )
    return {
        "success": True,
        "document_id": str(doc_id),
        "tenant_id": str(tenant_uuid),
        "source_type": source_type,
        "summary": (
            f"KMS 저장 완료: '{title}' ({len(content)}자, "
            f"출처 {len(source_urls)}건, type={source_type})"
        ),
    }

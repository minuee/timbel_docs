"""Document Type Classifier — 신규 업로드 문서의 *유형* 자동 분류.

★ 자비스 비전 시나리오 2 (2026-04-28): 사용자가 "작년 STT 발표 자료 어딨지?"
같이 *문서 유형* 으로 자기 자료를 검색할 수 있도록, 업로드 시점에 LLM 한
번 호출로 문서를 의미적으로 분류해 ``documents.processing_meta.document_type``
및 block.metadata 에 저장한다. SearchService 의 ``document_type_hint`` /
``document_type_ids`` 필터가 이 값을 활용한다.

원칙 (제 1원칙):
1. **하드코딩 금지** — file extension 으로 *기계적 매핑* 하지 않는다 (PDF=발표
   같은 사례 enum 금지). LLM 이 title + 본문 + extension *힌트* 를 종합 판단.
2. **카테고리 prompt 는 *원리* 명시** — 슬라이드 형식 + 청중 안내 톤 등 *왜*
   해당 유형인지의 의미적 기준을 prompt 에 박는다. 새 유형 발견 시 LLM 이
   가까운 카테고리 + reason 으로 분류.
3. **enum 강제 X** — 가이드용 6+1 카테고리 (presentation / manual / memo /
   research_note / email / report / other). LLM 이 자유 어휘로 답할 수 있되
   *정규화 단계* 에서 가까운 카테고리로 매핑.

기존 ``DocumentClassifier`` (skills/prompts/document_auto_classify) 와의 차이:
- DocumentClassifier 는 domain (finance/medical/...) + doc_type 동시 분류 →
  *전사 분류* 용. JSON 6키 무거움.
- 이 enricher 는 *오로지 document_type* 1축에 집중 → 더 가볍고 prompt 정밀.
  knowledge_compiler 옆에서 빠르게 1콜.

파이프라인 wire-up: ``DocumentProcessor._enrich`` 와 ``merge_worker`` 의
KnowledgeCompiler 호출 직후 (extractor 후, embedder 전). env flag
``KMS_DOC_TYPE_CLASSIFY_ENABLED`` (default true) — 비활성 시 no-op.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from src.common.logging import get_logger

log = get_logger(__name__)


# 가이드용 카테고리 — LLM prompt 에 *원리* 와 함께 노출. enum 강제 X (정규화
# 단계에서 가까운 값으로 매핑 + other fallback).
_GUIDE_CATEGORIES: dict[str, str] = {
    "presentation": (
        "발표 자료. 슬라이드 형식 (페이지당 핵심 메시지 1~2개), 청중 안내 톤, "
        "큰 제목 + 짧은 불릿. PPT/PDF 발표용."
    ),
    "manual": (
        "매뉴얼·절차서·운영 가이드. 단계별 지시문, How-to, 정책·규정. "
        "독자가 *수행* 하기 위한 문서."
    ),
    "memo": (
        "메모·회의록·노트. 짧은 비공식 기록. 결정 사항, 액션 아이템, "
        "회의 요약. 형식 자유."
    ),
    "research_note": (
        "외부 지식 정리·리서치 노트. 외부 자료·논문·기사를 자기 언어로 요약·"
        "정리. 출처·인용·비교 분석 톤."
    ),
    "email": (
        "이메일 본문. 인사말 + 본문 + 서명, To/From/Subject 메타. "
        "1대1 또는 1대다 커뮤니케이션."
    ),
    "report": (
        "분석 보고서. 배경 → 분석 → 결론 구조. 표·차트 포함, "
        "의사결정 지원 톤."
    ),
    "other": (
        "위 카테고리에 명확히 들어맞지 않는 문서. fallback. 새 유형이라면 "
        "rationale 에 어떤 형태인지 자세히 적을 것."
    ),
}

_ALLOWED = set(_GUIDE_CATEGORIES.keys())


class DocumentTypeClassifier:
    """문서 1건을 LLM 1회 호출로 document_type 분류.

    Parameters
    ----------
    llm_client : object | None
        ``chat_completion_json`` 또는 ``generate`` 메서드를 가진 LLM 어댑터.
        None 이면 분류 skip (other fallback).
    timeout_s : float
        LLM 호출 타임아웃 (초). 초과 시 other fallback.
    """

    def __init__(self, llm_client: object | None = None, *, timeout_s: float = 12.0):
        self._llm = llm_client
        self._timeout_s = timeout_s

    async def classify(
        self,
        *,
        title: str,
        text_sample: str,
        file_extension: str = "",
    ) -> dict[str, Any]:
        """문서를 분류한다.

        Parameters
        ----------
        title : str
            문서 제목.
        text_sample : str
            본문 앞 ~1000자.
        file_extension : str
            파일 확장자 (".pdf", ".docx", ".pptx" 등). 힌트로만 사용 — *기계적
            매핑* 하지 않는다.

        Returns
        -------
        dict
            {"document_type": str, "confidence": float, "reason": str}
        """
        if self._llm is None:
            return self._fallback("LLM 클라이언트 미주입")

        prompt = self._build_prompt(
            title=title,
            text_sample=text_sample[:1000],
            file_extension=file_extension,
        )

        try:
            raw = await self._call_llm(prompt)
        except Exception as exc:
            log.warning(
                "document_type_classifier_llm_error",
                title=title[:80],
                error=str(exc),
            )
            return self._fallback(f"LLM 오류: {exc}")

        return self._parse_and_normalize(raw)

    # ------------------------------------------------------------------ prompt

    @staticmethod
    def _build_prompt(*, title: str, text_sample: str, file_extension: str) -> str:
        """카테고리 *원리* 를 명시한 prompt. 키워드/사례 enum 매핑 X."""
        guide_lines = [
            f"- `{name}`: {desc}" for name, desc in _GUIDE_CATEGORIES.items()
        ]
        return (
            "당신은 문서의 *유형* 을 의미적으로 분류하는 전문가입니다.\n"
            "아래 카테고리는 *원리* 로 정의됩니다. 키워드 매칭이 아니라, 문서의\n"
            "*형식·톤·목적* 을 보고 어느 카테고리에 가까운지 판단하세요.\n\n"
            "## 카테고리 (원리)\n"
            + "\n".join(guide_lines)
            + "\n\n"
            "## 판단 원칙\n"
            "- 파일 확장자는 *힌트* 일 뿐 — 결정 근거가 아닙니다 (PDF 라고 무조건\n"
            "  발표 자료 X, DOCX 라고 무조건 매뉴얼 X).\n"
            "- 본문의 *형식·톤·목적* 이 결정 기준입니다.\n"
            "- 어느 카테고리에도 명확히 들어맞지 않으면 `other` + rationale 에\n"
            "  어떤 형태인지 자세히 적으세요.\n"
            "- confidence 는 0.0~1.0. 본문이 짧거나 모호하면 낮게.\n\n"
            f"## 문서\n"
            f"- 제목: {title or '(제목 없음)'}\n"
            f"- 파일 확장자 (힌트): {file_extension or '(미상)'}\n"
            f"- 본문 앞부분 (~1000자):\n{text_sample or '(본문 비어있음)'}\n\n"
            "## 출력 (JSON 한 객체만, 다른 텍스트 절대 금지)\n"
            '{"document_type": "<카테고리>", "confidence": <0.0~1.0>, "reason": "<한 줄>"}'
        )

    # ------------------------------------------------------------------ llm

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출. ``chat_completion_json`` 우선, 없으면 ``generate``."""
        import asyncio

        if hasattr(self._llm, "chat_completion_json"):
            messages = [
                {
                    "role": "system",
                    "content": (
                        "문서 유형 분류 전문가. JSON 한 객체만 출력. "
                        "마크다운 코드 펜스, 설명 문장 금지."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            return await asyncio.wait_for(
                self._llm.chat_completion_json(  # type: ignore[union-attr]
                    messages,
                    temperature=0.1,
                    max_tokens=200,
                ),
                timeout=self._timeout_s,
            )

        if hasattr(self._llm, "generate"):
            return await asyncio.wait_for(
                self._llm.generate(prompt),  # type: ignore[union-attr]
                timeout=self._timeout_s,
            )

        # OpenAI-호환 폴백
        try:
            from openai import AsyncOpenAI  # noqa: F401 — type only

            response = await asyncio.wait_for(
                self._llm.chat.completions.create(  # type: ignore[union-attr]
                    model=getattr(self._llm, "model", "gpt-4o-mini"),
                    messages=[
                        {
                            "role": "system",
                            "content": "문서 유형 분류 전문가. JSON 한 객체만 출력.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=200,
                ),
                timeout=self._timeout_s,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise RuntimeError(f"unsupported LLM client: {exc}") from exc

    # ------------------------------------------------------------------ parse

    def _parse_and_normalize(self, raw: str) -> dict[str, Any]:
        """LLM 응답 파싱 + 정규화."""
        from src.common.llm_utils import extract_json_object

        try:
            parsed = extract_json_object(raw) or {}
        except Exception as exc:
            log.warning("document_type_parse_failed", error=str(exc), raw=raw[:200])
            return self._fallback("LLM 출력 파싱 실패")

        if not isinstance(parsed, dict):
            return self._fallback("LLM 출력이 dict 가 아님")

        # document_type — enum 매핑. 자유 어휘면 가까운 카테고리로.
        dt_raw = str(parsed.get("document_type") or "").strip().lower()
        if dt_raw in _ALLOWED:
            doc_type = dt_raw
        elif dt_raw:
            doc_type = self._closest_category(dt_raw)
        else:
            doc_type = "other"

        # confidence
        conf_raw = parsed.get("confidence", 0.0)
        try:
            conf = float(conf_raw)
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.0

        reason = str(parsed.get("reason") or parsed.get("rationale") or "").strip()
        if not reason:
            reason = "LLM rationale 미제공"

        return {
            "document_type": doc_type,
            "confidence": conf,
            "reason": reason[:300],
        }

    @staticmethod
    def _closest_category(value: str) -> str:
        """정의된 카테고리 외 자유 어휘 → 가장 의미가 가까운 항목으로 매핑.

        하드코딩 키워드 매칭이 아니라 카테고리 *문자열 자체* 의 prefix/contains
        매칭만 (LLM 이 변형 표기를 낸 경우의 안전망). 의미 매핑은 LLM 이 이미
        prompt 에서 수행한 결과를 신뢰.
        """
        v = value.lower()
        for cat in _ALLOWED:
            if cat in v or v in cat:
                return cat
        return "other"

    @staticmethod
    def _fallback(reason: str) -> dict[str, Any]:
        return {
            "document_type": "other",
            "confidence": 0.0,
            "reason": reason,
        }


# ---------------------------------------------------------------------- public


async def classify_and_store(
    *,
    document_id: UUID,
    title: str,
    text_sample: str,
    file_extension: str = "",
    llm_client: object | None = None,
    db_session_factory: Any = None,
) -> dict[str, Any] | None:
    """분류 후 ``documents.processing_meta.document_type`` 에 병합 저장.

    파이프라인 워커에서 호출하는 high-level 헬퍼. **non-critical** —
    분류 또는 저장 실패해도 silent fallback (None 반환), 파이프라인 본류는
    그대로 진행한다.

    env flag ``KMS_DOC_TYPE_CLASSIFY_ENABLED`` (default true) — 비활성 시 no-op.

    Returns
    -------
    dict | None
        {"document_type": str, "confidence": float, "reason": str,
         "classified_at": ISO str} on success. None on skip/failure.
    """
    if os.environ.get("KMS_DOC_TYPE_CLASSIFY_ENABLED", "true").lower() in (
        "false", "0", "no", "off",
    ):
        log.info(
            "document_type_classify_skipped_disabled",
            document_id=str(document_id),
        )
        return None

    classifier = DocumentTypeClassifier(llm_client=llm_client)
    result = await classifier.classify(
        title=title,
        text_sample=text_sample,
        file_extension=file_extension,
    )
    result["classified_at"] = datetime.utcnow().isoformat() + "Z"

    # DB 저장 (실패해도 silent)
    persisted = await _persist(
        document_id=document_id,
        result=result,
        db_session_factory=db_session_factory,
    )
    if persisted:
        log.info(
            "document_type_classified",
            document_id=str(document_id),
            document_type=result["document_type"],
            confidence=result["confidence"],
        )
    return result


async def _persist(
    *,
    document_id: UUID,
    result: dict[str, Any],
    db_session_factory: Any = None,
) -> bool:
    """processing_meta.document_type_classification 에 병합 저장."""
    try:
        if db_session_factory is None:
            from src.core.database import async_session_factory as _default_factory

            db_session_factory = _default_factory

        from src.core.services.document_service import DocumentService

        async with db_session_factory() as session:
            svc = DocumentService(session)
            await svc.update_processing_meta(
                document_id,
                processing_meta={"document_type_classification": result},
            )
            await session.commit()
        return True
    except Exception as exc:
        log.warning(
            "document_type_persist_failed",
            document_id=str(document_id),
            error=str(exc),
        )
        return False


def derive_extension(source_path: str | None) -> str:
    """source_path 에서 확장자 추출 (".pdf" 등). 없으면 빈 문자열."""
    if not source_path:
        return ""
    try:
        ext = Path(source_path).suffix
        return ext.lower() if ext else ""
    except Exception:
        return ""

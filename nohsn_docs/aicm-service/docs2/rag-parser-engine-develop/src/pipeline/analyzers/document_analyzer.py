"""문서 업로드 후 AI 기반 품질 분석 + 검색 예측 + 개선 제안 서비스.

파싱·청킹 결과를 입력받아 구조/표/OCR/중복/검색 키워드를 분석하고,
Qwen3.5-35B를 활용하여 종합 리포트를 생성한다.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Analysis Report 모델
# ---------------------------------------------------------------------------


class StructureAnalysis(BaseModel):
    """문서 구조 분석 결과."""

    has_toc: bool = False
    heading_count: int = 0
    max_depth: int = 0
    section_count: int = 0


class TableAnalysis(BaseModel):
    """표 분석 결과."""

    table_count: int = 0
    total_rows: int = 0
    tables_with_headers: int = 0
    header_quality: str = "unknown"  # good / fair / poor / unknown


class OCRAnalysis(BaseModel):
    """OCR 분석 결과."""

    total_pages: int = 0
    low_confidence_pages: list[int] = Field(default_factory=list)
    suspected_garbled_pages: list[int] = Field(default_factory=list)
    average_confidence: float = 0.0


class DuplicateCheck(BaseModel):
    """중복 검사 결과."""

    has_potential_duplicate: bool = False
    similar_documents: list[dict] = Field(default_factory=list)
    max_similarity: float = 0.0


class SearchPrediction(BaseModel):
    """검색 예측 결과."""

    keyword: str
    relevance_score: float = 0.0


class ImprovementSuggestion(BaseModel):
    """개선 제안."""

    category: str  # structure / content / formatting / metadata
    severity: str  # info / warning / critical
    message: str


class AnalysisReport(BaseModel):
    """AI 문서 분석 리포트."""

    quality_score: int = Field(0, ge=0, le=100, description="문서 품질 점수 (0-100)")
    structure_analysis: StructureAnalysis = Field(default_factory=StructureAnalysis)
    table_analysis: TableAnalysis = Field(default_factory=TableAnalysis)
    ocr_analysis: OCRAnalysis = Field(default_factory=OCRAnalysis)
    duplicate_check: DuplicateCheck = Field(default_factory=DuplicateCheck)
    search_predictions: list[SearchPrediction] = Field(default_factory=list)
    improvement_suggestions: list[ImprovementSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ai_analysis: dict = Field(default_factory=dict, description="Qwen AI 분석 원문")
    analyzed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Document Analyzer
# ---------------------------------------------------------------------------


class DocumentAnalyzer:
    """문서 업로드 후 AI가 품질 분석 + 검색 예측 + 개선 제안을 제공."""

    async def analyze(
        self,
        parse_result: dict | None,
        chunks: list[dict],
        doc_title: str,
        *,
        existing_docs: list[dict] | None = None,
    ) -> AnalysisReport:
        """파싱+청킹 결과를 받아 AI 분석 리포트를 생성한다.

        Args:
            parse_result: 파서 출력 (sections, tables, ocr_info 등)
            chunks: 청크 리스트 [{"content": str, "metadata": dict, ...}]
            doc_title: 문서 제목
            existing_docs: 동일 저장소 기존 문서 [{title, content_preview}] (중복 체크용)

        Returns:
            AnalysisReport 객체
        """
        parse_result = parse_result or {}
        existing_docs = existing_docs or []

        # 1. 구조 분석
        structure = self._analyze_structure(parse_result, chunks)

        # 2. 표 분석
        tables = self._analyze_tables(parse_result, chunks)

        # 3. OCR 분석
        ocr = self._analyze_ocr(parse_result)

        # 4. 중복 검사
        full_content = " ".join(c.get("content", "") for c in chunks)
        duplicate = self._check_duplicates(doc_title, full_content[:500], existing_docs)

        # 5. 검색 키워드 추출 (규칙 기반)
        rule_keywords = self._extract_keywords(full_content, doc_title)

        # 6. 규칙 기반 품질 점수 + 개선 제안
        base_score, suggestions, warnings = self._compute_quality(
            structure, tables, ocr, duplicate, chunks
        )

        # 7. AI 분석 (Qwen)
        ai_result = await self._run_ai_analysis(doc_title, full_content[:3000])

        # AI 결과 병합
        ai_score = ai_result.get("quality_score", base_score)
        final_score = (base_score + ai_score) // 2

        ai_keywords = ai_result.get("search_keywords", [])
        ai_suggestions_raw = ai_result.get("suggestions", [])
        ai_issues = ai_result.get("issues", [])

        # 검색 예측 병합
        search_predictions: list[SearchPrediction] = []
        seen_kw: set[str] = set()
        for kw in rule_keywords + ai_keywords:
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in seen_kw:
                seen_kw.add(kw_lower)
                search_predictions.append(
                    SearchPrediction(keyword=kw, relevance_score=0.8)
                )

        # AI 개선 제안 병합
        for sug in ai_suggestions_raw:
            if isinstance(sug, str):
                suggestions.append(
                    ImprovementSuggestion(
                        category="content", severity="info", message=sug
                    )
                )

        for issue in ai_issues:
            if isinstance(issue, str):
                warnings.append(issue)

        return AnalysisReport(
            quality_score=max(0, min(100, final_score)),
            structure_analysis=structure,
            table_analysis=tables,
            ocr_analysis=ocr,
            duplicate_check=duplicate,
            search_predictions=search_predictions[:20],
            improvement_suggestions=suggestions,
            warnings=warnings,
            ai_analysis=ai_result,
        )

    # ------------------------------------------------------------------
    # 구조 분석
    # ------------------------------------------------------------------

    def _analyze_structure(
        self, parse_result: dict, chunks: list[dict]
    ) -> StructureAnalysis:
        """문서 구조를 분석한다 (목차, 제목 수, 계층 깊이, 섹션 수)."""
        sections = parse_result.get("sections", [])
        headings = [s for s in sections if s.get("level", 0) > 0]
        max_depth = max((s.get("level", 0) for s in sections), default=0)

        # 목차 존재 여부: 헤딩이 3개 이상이면 목차 있다고 간주
        has_toc = len(headings) >= 3

        # 청크 메타데이터에서도 heading 정보 추출
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            heading_path = meta.get("heading_path", [])
            if heading_path:
                max_depth = max(max_depth, len(heading_path))

        return StructureAnalysis(
            has_toc=has_toc,
            heading_count=len(headings),
            max_depth=max_depth,
            section_count=len(sections),
        )

    # ------------------------------------------------------------------
    # 표 분석
    # ------------------------------------------------------------------

    def _analyze_tables(
        self, parse_result: dict, chunks: list[dict]
    ) -> TableAnalysis:
        """표 품질을 분석한다."""
        tables = parse_result.get("tables", [])
        if not tables:
            # 청크에서 표 관련 메타 확인
            table_chunks = [
                c for c in chunks if c.get("metadata", {}).get("is_table", False)
            ]
            if not table_chunks:
                return TableAnalysis()
            return TableAnalysis(
                table_count=len(table_chunks),
                total_rows=0,
                tables_with_headers=0,
                header_quality="unknown",
            )

        table_count = len(tables)
        total_rows = sum(len(t.get("rows", [])) for t in tables)
        with_headers = sum(1 for t in tables if t.get("headers"))
        quality = "good" if with_headers == table_count else (
            "fair" if with_headers > 0 else "poor"
        )

        return TableAnalysis(
            table_count=table_count,
            total_rows=total_rows,
            tables_with_headers=with_headers,
            header_quality=quality,
        )

    # ------------------------------------------------------------------
    # OCR 분석
    # ------------------------------------------------------------------

    def _analyze_ocr(self, parse_result: dict) -> OCRAnalysis:
        """OCR 품질을 분석한다 (저신뢰도 페이지, 글자 깨짐 의심)."""
        ocr_info = parse_result.get("ocr_info", {})
        if not ocr_info:
            return OCRAnalysis()

        pages = ocr_info.get("pages", [])
        total = len(pages)
        if total == 0:
            return OCRAnalysis()

        low_conf: list[int] = []
        garbled: list[int] = []
        total_conf = 0.0

        for page in pages:
            page_num = page.get("page_number", 0)
            confidence = page.get("confidence", 1.0)
            total_conf += confidence
            if confidence < 0.7:
                low_conf.append(page_num)
            # 글자 깨짐 감지: 특수문자 비율이 높은 경우
            text = page.get("text", "")
            if text:
                garble_ratio = sum(
                    1 for c in text if not c.isalnum() and not c.isspace()
                ) / max(len(text), 1)
                if garble_ratio > 0.3:
                    garbled.append(page_num)

        return OCRAnalysis(
            total_pages=total,
            low_confidence_pages=low_conf,
            suspected_garbled_pages=garbled,
            average_confidence=total_conf / total if total else 0.0,
        )

    # ------------------------------------------------------------------
    # 중복 검사
    # ------------------------------------------------------------------

    def _check_duplicates(
        self,
        title: str,
        content_preview: str,
        existing_docs: list[dict],
    ) -> DuplicateCheck:
        """기존 문서와 제목/내용 기반 유사도를 검사한다."""
        if not existing_docs:
            return DuplicateCheck()

        similar: list[dict] = []
        max_sim = 0.0

        for doc in existing_docs:
            # 제목 유사도 (간단한 토큰 겹침 기반)
            title_sim = self._token_similarity(title, doc.get("title", ""))
            # 내용 유사도
            content_sim = self._token_similarity(
                content_preview, doc.get("content_preview", "")
            )
            combined = title_sim * 0.4 + content_sim * 0.6

            if combined > 0.5:
                similar.append({
                    "document_id": doc.get("document_id", ""),
                    "title": doc.get("title", ""),
                    "similarity": round(combined, 3),
                })
                max_sim = max(max_sim, combined)

        return DuplicateCheck(
            has_potential_duplicate=max_sim > 0.7,
            similar_documents=sorted(similar, key=lambda x: x["similarity"], reverse=True)[:5],
            max_similarity=round(max_sim, 3),
        )

    @staticmethod
    def _token_similarity(a: str, b: str) -> float:
        """두 텍스트의 토큰 기반 Jaccard 유사도."""
        if not a or not b:
            return 0.0
        tokens_a = set(a.lower().split())
        tokens_b = set(b.lower().split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    # ------------------------------------------------------------------
    # 검색 키워드 추출
    # ------------------------------------------------------------------

    def _extract_keywords(self, content: str, title: str) -> list[str]:
        """규칙 기반 검색 키워드 추출 (단어 빈도 + 제목 토큰)."""
        # 한국어+영문 토큰 추출 (2글자 이상)
        tokens = re.findall(r"[가-힣a-zA-Z]{2,}", content[:5000])
        counter = Counter(tokens)

        # 불용어 제거 (기본적인 한국어/영어)
        stopwords = {
            "the", "and", "for", "that", "this", "with", "from", "are", "was",
            "which", "have", "has", "been", "being", "will", "would",
            "것이", "하는", "있는", "것을", "대한", "에서", "으로", "것은",
            "하여", "되는", "같은", "통해", "위한", "따른", "관련",
        }
        for sw in stopwords:
            counter.pop(sw, None)

        # 상위 빈도 단어
        keywords = [word for word, _ in counter.most_common(10)]

        # 제목 토큰 추가
        title_tokens = re.findall(r"[가-힣a-zA-Z]{2,}", title)
        for t in title_tokens:
            if t.lower() not in {k.lower() for k in keywords}:
                keywords.append(t)

        return keywords[:15]

    # ------------------------------------------------------------------
    # 품질 점수 + 개선 제안
    # ------------------------------------------------------------------

    def _compute_quality(
        self,
        structure: StructureAnalysis,
        tables: TableAnalysis,
        ocr: OCRAnalysis,
        duplicate: DuplicateCheck,
        chunks: list[dict],
    ) -> tuple[int, list[ImprovementSuggestion], list[str]]:
        """규칙 기반 품질 점수와 개선 제안을 생성한다."""
        score = 70  # 기본 점수
        suggestions: list[ImprovementSuggestion] = []
        warnings: list[str] = []

        # 구조 평가
        if structure.has_toc:
            score += 10
        else:
            suggestions.append(ImprovementSuggestion(
                category="structure",
                severity="info",
                message="문서에 목차(제목 계층)가 부족합니다. 제목을 추가하면 검색 품질이 향상됩니다.",
            ))

        if structure.max_depth >= 2:
            score += 5
        if structure.section_count == 0:
            score -= 10
            suggestions.append(ImprovementSuggestion(
                category="structure",
                severity="warning",
                message="문서에 섹션 구분이 없습니다. 구조화된 문서가 더 나은 검색 결과를 제공합니다.",
            ))

        # 표 평가
        if tables.table_count > 0 and tables.header_quality == "poor":
            score -= 5
            suggestions.append(ImprovementSuggestion(
                category="formatting",
                severity="warning",
                message="표에 헤더가 없습니다. 헤더를 추가하면 표 내용 검색이 개선됩니다.",
            ))

        # OCR 평가
        if ocr.low_confidence_pages:
            penalty = min(len(ocr.low_confidence_pages) * 3, 15)
            score -= penalty
            warnings.append(
                f"OCR 저신뢰도 페이지 감지: {ocr.low_confidence_pages}. "
                "스캔 품질을 확인하세요."
            )

        if ocr.suspected_garbled_pages:
            score -= 10
            warnings.append(
                f"글자 깨짐 의심 페이지: {ocr.suspected_garbled_pages}. "
                "원본 문서 확인이 필요합니다."
            )

        # 청크 수 평가
        if len(chunks) < 2:
            score -= 10
            suggestions.append(ImprovementSuggestion(
                category="content",
                severity="warning",
                message="문서 내용이 매우 짧습니다. 충분한 내용이 있어야 검색에 효과적입니다.",
            ))
        elif len(chunks) > 200:
            suggestions.append(ImprovementSuggestion(
                category="content",
                severity="info",
                message="문서가 매우 길어 200개 이상의 청크로 분할되었습니다. "
                        "문서를 여러 개로 나누는 것을 고려하세요.",
            ))

        # 중복 평가
        if duplicate.has_potential_duplicate:
            score -= 10
            warnings.append(
                f"유사한 기존 문서가 발견되었습니다 (유사도: {duplicate.max_similarity:.0%}). "
                "버전 관리 또는 중복 제거를 고려하세요."
            )

        return max(0, min(100, score)), suggestions, warnings

    # ------------------------------------------------------------------
    # AI 분석 (Qwen vLLM)
    # ------------------------------------------------------------------

    async def _run_ai_analysis(self, title: str, content: str) -> dict:
        """Qwen3.5-35B를 사용하여 AI 기반 문서 분석을 수행한다.

        Args:
            title: 문서 제목
            content: 문서 내용 (첫 3000자)

        Returns:
            AI 분석 결과 dict
        """
        prompt = (
            "문서를 분석하고 다음 JSON 형식으로 평가하세요:\n"
            "- quality_score (0-100): 문서 품질 점수\n"
            "- issues: 발견된 문제점 리스트 (문자열 배열)\n"
            "- suggestions: 개선 제안 리스트 (문자열 배열)\n"
            "- search_keywords: 이 문서에서 검색될 수 있는 핵심 키워드 10개 (문자열 배열)\n\n"
            "반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.\n\n"
            f"문서 제목: {title}\n"
            f"문서 내용 (첫 3000자):\n{content}"
        )

        try:
            import httpx

            body = json.dumps({
                "model": settings.VLLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.3,
            })

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.VLLM_URL}/chat/completions",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                result = resp.json()

            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            # JSON 파싱 시도
            parsed = self._parse_json_response(text)
            logger.info(
                "ai_analysis_completed",
                title=title,
                quality_score=parsed.get("quality_score"),
            )
            return parsed

        except Exception as exc:
            logger.warning(
                "ai_analysis_failed",
                title=title,
                error=str(exc),
            )
            return {
                "quality_score": 70,
                "issues": [],
                "suggestions": [],
                "search_keywords": [],
                "error": str(exc),
            }

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """AI 응답에서 JSON을 추출하여 파싱한다."""
        # 먼저 그대로 파싱 시도
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # ```json ... ``` 블록 추출
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # { ... } 블록 추출
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return {
            "quality_score": 70,
            "issues": [],
            "suggestions": [],
            "search_keywords": [],
            "parse_error": "AI 응답을 JSON으로 파싱할 수 없습니다.",
        }

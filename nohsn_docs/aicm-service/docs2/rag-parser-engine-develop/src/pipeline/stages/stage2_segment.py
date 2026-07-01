"""2단계: 페이지 범위별 블럭 분할.

5페이지씩 배치로 처리. 1단계 DocumentContext를 참고.
페이지 이미지 + 추출 텍스트를 동시에 분석.
"""

from __future__ import annotations

from src.common.logging import get_logger
from src.pipeline.prompts.block_segmentation import _DOC_TYPE_HINTS
from src.pipeline.stages.doc_type_map import to_slug
from src.pipeline.stages.llm_client import VisionLLMClient
from src.pipeline.stages.models import DocumentContext, PageData, RawBlock

log = get_logger(__name__)

BATCH_SIZE = 4  # 한 번에 처리할 페이지 수 (vLLM limit_mm_per_prompt=4)

# ---------------------------------------------------------------------------
# 프롬프트 템플릿
# ---------------------------------------------------------------------------
_STAGE2_PROMPT_TEMPLATE = """문서: {doc_type} — "{title}"
노이즈: {noise_patterns}

아래 페이지들을 **검색/RAG용** 의미 블럭으로 분할하세요.

[페이지별 텍스트]
{page_texts}

## 블럭 타입
heading_1/2/3, paragraph, table, image, bulleted_list, numbered_list, code, quote, callout, noise, divider, **slide**

## PPT/슬라이드형 페이지 처리 (중요)
다음 조건에 해당하면 **페이지 전체를 slide 타입 1개 블럭**으로 처리하세요:
- 페이지의 텍스트가 300자 미만이고 이미지가 주를 이룸 (발표자료, 프로그램 설명서)
- 화면 캡처에 번호(①②③, 1,2,3)가 붙고 아래에 번호별 설명이 있는 구조
- 다이어그램/공정도에 화살표와 단계별 설명이 함께 있는 구조
- 이미지와 텍스트가 밀접하게 결합되어 분리하면 의미를 잃는 경우

slide 블럭의 content에는:
- 페이지 제목
- 이미지에 보이는 모든 내용 (번호→설명 매핑 포함)
- 텍스트 설명
을 **종합적으로 자연어로 서술**하세요. 이 블럭 하나로 페이지 전체를 이해할 수 있어야 합니다.

## 블럭 사이즈 규칙 (중요)
이 블럭들은 두 가지 용도로 사용됩니다:
1. **문서 검색**: 사용자가 검색하면 블럭이 위치를 알려주고 문서 전체가 로딩됨
2. **RAG 답변**: Top 3-5 블럭이 LLM에 전달되어 답변을 생성함

따라서:
- **paragraph 블럭은 최소 100자 이상** — 2-3문장 이상이 하나의 블럭
- **너무 짧은 블럭 금지** — 한 문장만 있으면 앞뒤 문맥과 합쳐서 하나의 블럭으로
- **heading은 단독 블럭** — 하지만 heading 직후 짧은 도입문은 heading과 합쳐도 됨
- **표/리스트는 통째로** — 하나의 표를 여러 블럭으로 쪼개지 말 것
- **최대 800자** 초과 시 자연스러운 지점에서 분할

## noise 분류 (필수)
목차 페이지 전체, FAQ 질문만 나열(답변 없이), 페이지 번호, 반복 헤더/푸터, 장식 이미지, 워터마크

{doc_type_hint}
{table_hint}
## table 필수 규칙 (D85c — 시각 도표 포함)
**table 의 범위** — 다음 모두 table 로 분류한다:
- 헤더 행 + 데이터 행이 있는 표 (전형)
- 헤더 없는 *N-column 박스형 도표* (예: 항목 비교 / 매트릭스 / 단계별 책임)
- 시각적 *세로/가로 정렬 패턴* 으로 N개의 병렬 항목을 보여주는 구조
- 화살표·연결선 등으로 *cell 간 관계* 를 표현하는 도표
- **숫자 + 단위 + 라벨 grid** — 예: `6 8 / 개 개 / 기관 기관 / 7 10 / 개 개 / 수요 수요` 같이
  세로/가로 정렬로 *N분류 × N 지표* 의 의미를 가진 grid. 텍스트 flatten 하지 말고
  *반드시 table 로*. row 라벨 / column 라벨을 시각 위치로 추론하여 부여.

→ 시각적 layout 이 의미를 담으면 *paragraph / numbered_list 가 아닌 table*.

**content 형식 — 반드시 markdown 표**:
```
| col1 header | col2 header | col3 header |
|---|---|---|
| row1 col1 | row1 col2 | row1 col3 |
| row2 col1 | row2 col2 | row2 col3 |
```
- 헤더 없는 도표는 *컬럼명을 시각 위치 / 항목명* 으로 자체 부여 (예: `| 항목1 | 항목2 | 항목3 |`).
- 행/열 경계가 명확하면 *cell 단위로 분할* — 절대 한 cell 본문에 다른 cell 내용 혼합 금지.
- N-tier (예: 3개 법령) 매트릭스는 *N 컬럼 그대로* 보존. 통합·축약 금지.
- **D85c-잔존 (2026-05-13)** — column-major 텍스트 (헤더 row 와 cell row 가 따로
  떨어져 있는 PDF 추출) 도 *반드시 column 별 매핑 복원* 후 markdown 표 생성. 예:
  `전자정부법 / 정보자원 통합기준 / 클라우드컴퓨팅법` 가 첫 줄, 다음 줄에 각각의
  조항이 있으면 row 1 = 헤더, row 2 = 조항. 모든 column 본문을 하나의 paragraph 로
  concat 금지.

**table_nl 필수**: 표 내용을 자연어 3-5문장으로 변환. 예: "이 표에 따르면 …"

## list/table 경계 규칙 (D85c-잔존 — page boundary 분리 방지)
**한 list/table 이 *batch 경계 또는 page 경계* 에서 끊긴 것으로 보이면**:
- 첫 chunk 에 *list/table 제목 (예: "3. 추진 절차")* 이 있고 step 1 만 있음,
  그리고 같은 batch 다음 페이지에 step 2-5 가 있는 경우 → **반드시 하나의 list 로 결합**.
- batch 범위를 벗어나면 (다음 batch) — 부득이 분리되나, 두 번째 chunk 의 type 도
  같은 list/table type 유지. *원 제목을 현재 batch 안에서 확인 가능한 경우만*
  content 첫 줄에 명시 (예: "(연속) 추진 절차 step 2-5"). 직전 batch 의 제목을
  *추측·복원하지 X* — hallucination 차단.
- 즉 *부모 제목 누락* 으로 step 2-5 chunk 가 검색되지 않는 사고 방지.

## table 오분류 negative guard (D85c-잔존)
다음은 *table 이 아니다* — paragraph / numbered_list / bulleted_list 로 분류:
- 단순 줄바꿈 / 일반 문단 — 줄 간 *세로 정렬* 이 의미를 담지 않으면 paragraph.
- 2단 편집 (예: 책 본문의 좌우 칼럼) — 단순 layout 이고 cell 간 의미 관계 X → 두
  단을 합쳐 paragraph.
- 들여쓰기만 다른 list — bulleted_list / numbered_list 유지.
- *시각 layout 이 의미를 담는다는 증거가 없으면 table 로 만들지 않는다*.

## image 필수 규칙
- 이미지를 보고 content에 설명 (2-3문장)
- 장식/로고/아이콘은 noise로

JSON 배열만 반환:
[{{"type":"paragraph","content":"원문 100자 이상","page":1}},{{"type":"table","content":"| col1 | col2 |\\n|---|---|\\n| a | b |","page":1,"table_nl":"자연어 해석"}},{{"type":"noise","content":"75","page":1,"reason":"페이지 번호"}}]"""


def _build_table_hint(batch: list[PageData]) -> str:
    """Stage1.5 LayoutMapper 가 감지한 표/도표 영역을 Stage2 prompt hint 로.

    좌표를 명시해 Stage2 가 "이 영역은 table — 열 우선 직렬화" 지시를 받게 한다.
    감지된 표가 없으면 빈 문자열 (prompt 무변화).
    """
    lines: list[str] = []
    for p in batch:
        for t in p.detected_tables or []:
            bbox = t.get("bbox", [])
            kind = t.get("kind", "table")
            lines.append(f"- 페이지 {p.page_num}: {kind} 영역 bbox={bbox}")
    if not lines:
        return ""
    return (
        "## 사전 감지된 표/도표 영역 (Stage1.5 LayoutMapper)\n"
        "아래 페이지에 표/도표 영역이 *존재*함이 사전 감지됨. 좌표(bbox)는 정밀 매칭용이\n"
        "아니라 위치 참고용 신호 — 좌표계가 grid/box 별로 다를 수 있으니 페이지 이미지를\n"
        "보고 해당 표/도표를 반드시 table 블럭으로 분할하고, 열(column) 경계를 보존해\n"
        "*열 우선* 으로 markdown 표를 만들 것. 행 우선 flatten 금지.\n"
        + "\n".join(lines)
        + "\n"
    )


class BlockSegmentation:
    """2단계: 블럭 분할 스테이지."""

    def __init__(self, llm_client: VisionLLMClient) -> None:
        self._client = llm_client

    async def segment_all(
        self,
        pages: list[PageData],
        context: DocumentContext,
    ) -> list[RawBlock]:
        """전체 페이지를 배치로 분할. 배치 간 순차, 배치 내 1회 호출.

        Args:
            pages: 페이지 데이터 리스트 (page_num, image_bytes, extracted_text).
            context: 1단계 문서 이해 결과.

        Returns:
            모든 블럭 리스트.
        """
        all_blocks: list[RawBlock] = []

        for batch_start in range(0, len(pages), BATCH_SIZE):
            batch = pages[batch_start : batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(pages) + BATCH_SIZE - 1) // BATCH_SIZE

            log.info(
                "stage2_batch_start",
                batch=f"{batch_num}/{total_batches}",
                pages=[p.page_num for p in batch],
            )

            blocks = await self._segment_batch(batch, context)
            all_blocks.extend(blocks)

            log.info(
                "stage2_batch_complete",
                batch=f"{batch_num}/{total_batches}",
                block_count=len(blocks),
            )

        return all_blocks

    async def _segment_batch(
        self,
        batch: list[PageData],
        context: DocumentContext,
    ) -> list[RawBlock]:
        """배치 단위 세그멘테이션. 1회 Vision 호출."""
        # 이미지 수집
        images: list[bytes] = [p.image_bytes for p in batch if p.image_bytes]

        # 페이지 텍스트 조합
        page_texts_parts: list[str] = []
        for p in batch:
            text_preview = p.extracted_text[:2000] if p.extracted_text else "(텍스트 없음)"
            page_texts_parts.append(f"--- 페이지 {p.page_num} ---\n{text_preview}")
        page_texts = "\n\n".join(page_texts_parts)

        # 노이즈 패턴 요약 (200자 이내)
        noise_str = ", ".join(context.noise_patterns[:5]) if context.noise_patterns else "없음"
        if len(noise_str) > 200:
            noise_str = noise_str[:197] + "..."

        prompt = _STAGE2_PROMPT_TEMPLATE.format(
            doc_type=context.document_type or "문서",
            title=context.title or "제목 없음",
            noise_patterns=noise_str,
            page_texts=page_texts,
            table_hint=_build_table_hint(batch),
            doc_type_hint=_DOC_TYPE_HINTS.get(to_slug(context.document_type), ""),
        )

        raw = await self._client.call(
            prompt=prompt,
            images=images if images else None,
            max_tokens=8192,
        )

        parsed = self._client.parse_json(raw)

        if not isinstance(parsed, list):
            log.warning(
                "stage2_parse_failed",
                raw_preview=raw[:300],
                batch_pages=[p.page_num for p in batch],
            )
            # 파싱 실패 시 원본 텍스트를 paragraph 블럭으로 폴백
            return self._fallback_blocks(batch)

        blocks: list[RawBlock] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                block = RawBlock(
                    type=item.get("type", "paragraph"),
                    content=item.get("content", ""),
                    page=item.get("page", batch[0].page_num),
                    reason=item.get("reason", ""),
                    table_nl=item.get("table_nl", ""),
                    image_description=item.get("image_description", ""),
                )
                blocks.append(block)
            except Exception as e:
                log.warning("stage2_block_parse_error", error=str(e), item=str(item)[:200])

        if not blocks:
            log.warning("stage2_empty_result", batch_pages=[p.page_num for p in batch])
            return self._fallback_blocks(batch)

        return blocks

    @staticmethod
    def _fallback_blocks(batch: list[PageData]) -> list[RawBlock]:
        """LLM 파싱 실패 시 원본 텍스트를 paragraph 블럭으로 변환."""
        blocks: list[RawBlock] = []
        for p in batch:
            if p.extracted_text and p.extracted_text.strip():
                blocks.append(
                    RawBlock(
                        type="paragraph",
                        content=p.extracted_text.strip(),
                        page=p.page_num,
                        reason="fallback: LLM 파싱 실패",
                    )
                )
        return blocks

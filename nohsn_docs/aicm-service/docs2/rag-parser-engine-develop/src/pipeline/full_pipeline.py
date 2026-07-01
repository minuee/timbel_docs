"""KMS 풀옵션 통합 pipeline — 단일 entry point.

★ 사용자 절칙 (2026-05-07):
    "앞으로 절칙이야. KMS 자료화 할때, 풀옵션으로 무조건 다 처리해.
     그래야 품질이 좋아져"
    "지금 자료들도 다시 전부 재처리 해. 문서 파이프라인은 풀옵션으로 전 과정을
     다 거치는 파이프라인이 있을꺼야. 그걸로 해서 전부 처리 하는게 기본이야.
     그걸로만 문서 입력 하도록 해"

본 모듈은 **모든 ingest path 의 공통 후처리 단계** 를 캡슐화한다. 기존
ingest endpoint (chat upload / repo upload / agent documents / auto-draft /
reseed) 들은 여전히 *DocumentService.create()* 로 documents row 를 만들고
Kafka 이벤트를 발행 → 비동기 worker pipeline 이 받지만, **동기 reseed /
직접 markdown_text 입력 / 풀옵션 회복 처리** 는 ``process_document_full()``
한 함수만 호출하면 된다.

풀옵션 단계 (모두 포함):
    1. ParseResult — Markdown / PDF / PPT / docx / xlsx (router 자동)
    2. vision_gate.decide() — broken_ratio / scanned_ratio / glyph_doubling
    3. document_structure Stage 1 — markdown 입력 시 LLM 호출 (sample 본문 분석)
       또는 Vision LLM 으로 첫 3 페이지 분석.
       출력: document_type / sections / noise_patterns / has_qa_pairs
    4. partition_noise_blocks — 헤더/푸터/페이지번호/목차 분리
    5. document_type_classifier — Stage 1 보강 + 6+1 카테고리 정규화
    6. ontology_classifier — 도메인 (finance / utility / retail / ...)
    7. **TypeAwareChunker** — document_type 기반 6 전략
       (faq / manual / presentation / memo / email / report / other)
    8. BGE-M3 임베딩 + Qdrant + Elasticsearch 인덱싱
    9. processing_meta 풍부 — 모든 단계 결과 저장

본 모듈은 *순수 함수 위주* — DB 연결 / Kafka producer / vLLM client 는
caller 가 주입. 테스트 용이성 + worker / 스크립트 양쪽에서 재사용.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import UUID, uuid4

from src.common.logging import get_logger
from src.pipeline.chunkers.type_aware_chunker import (
    TypeAwareChunker,
    detect_faq_pattern,
)
from src.pipeline.enrichers.chunk_metadata_propagator import KC_MARKER_KEYS
from src.pipeline.models.chunking import InputBlock, MergedChunk
from src.pipeline.processing.semantic_block_merger import SemanticBlockMerger

log = get_logger(__name__)


# ── _PipelineBlock — full_pipeline 내부 정규형 (D31b §1) ───────────────────


@dataclass
class _PipelineBlock:
    """full_pipeline 내부 정규형 — _parse / partition / chunker boundary 공유 형식.

    D31b (#208) — InputBlock 과 동일 schema (block_id / block_type / content /
    block_index / metadata / contextual_prefix / extracted_metadata / source_location /
    block_hash). 차이는:
    - InputBlock 은 chunker 입력 (DTO) — neutral layer.
    - _PipelineBlock 은 full_pipeline 내부. underscore *internal* 표시.
      kc_markers 필드 포함 — D31d KC hook 활성화 시 채움 (D31b 단계 항상 빈 dict).

    필드 순서는 InputBlock 과 일치 — 1:1 변환 단순화.

    D38 v3 (#220 spec v3.2) — BlockObject 전체 schema 보존 위해 옵션 필드 확장.
    Risk C 완전 종료. 모든 신규 필드 default → backward compat 0.
    """

    block_id: UUID
    block_type: str
    content: str
    block_index: int
    # ── D31a InputBlock 과 동일 — default 끝 ─────────
    metadata: dict = field(default_factory=dict)
    contextual_prefix: str | None = None
    extracted_metadata: dict | None = None
    source_location: dict = field(default_factory=dict)
    block_hash: str = ""
    # ── D31b 추가 — KC owned 영역 표시 (D31d hook 대비) ─────
    kc_markers: dict = field(default_factory=dict)
    # ── D38 v3 — BlockObject 전체 schema 보존 (Risk C 종료) ─────────
    # 모든 default → 기존 caller (D31a/b/c) 영향 0.
    token_count: int = 0
    properties: dict = field(default_factory=dict)
    children: list = field(default_factory=list)  # list[UUID]
    table_headers: list | None = None              # list[str]
    table_rows: list | None = None                 # list[list[str]]
    table_markdown: str | None = None
    image_path: str | None = None
    ocr_text: str | None = None
    image_description: str | None = None


def _compute_block_hash(content: str, block_index: int) -> str:
    """D31a fallback 와 동일 정책 — `sha256(f"{idx:08d}::{content}")`.

    duplicate content 가 다른 index 에 등장 시 conflict 0 보장. D31b 단계에서
    `_PipelineBlock` 생성 시 항상 채움.
    """
    return hashlib.sha256(
        f"{block_index:08d}::{content}".encode("utf-8")
    ).hexdigest()


def _to_input_block(pb: "_PipelineBlock") -> InputBlock:
    """_PipelineBlock → InputBlock 1:1 변환 (D31b §1.3 v2 fix 1 + 2).

    v2 fix 1 — 모든 mutable 컨테이너 deepcopy 격리. nested list/dict 공유 0.
    v2 fix 2 — kc_markers 의 allowlist (`KC_MARKER_KEYS`) 안 키만 metadata 로 promotion.
                allowlist 밖 키는 무시. pb.metadata 와 충돌 시 **pb.metadata 우선**
                (`setdefault` 사용 — KC hook 이 metadata 를 직접 set 했다면 진실로 간주).

    Notes:
        D31b 단계 동작: kc_markers 항상 `{}` → promotion no-op → InputBlock.metadata
        가 _PipelineBlock.metadata 와 동치. D31a propagator 회귀 0.
    """
    # nested 안전 deepcopy
    merged_metadata: dict = copy.deepcopy(pb.metadata or {})
    # kc_markers allowlist promotion (충돌 시 metadata 우선 → setdefault)
    if pb.kc_markers:
        for key, value in pb.kc_markers.items():
            if key in KC_MARKER_KEYS:
                merged_metadata.setdefault(key, copy.deepcopy(value))

    return InputBlock(
        block_id=pb.block_id,
        block_type=pb.block_type,
        content=pb.content,
        block_index=pb.block_index,
        metadata=merged_metadata,
        contextual_prefix=pb.contextual_prefix,
        extracted_metadata=(
            copy.deepcopy(pb.extracted_metadata)
            if pb.extracted_metadata is not None else None
        ),
        source_location=copy.deepcopy(pb.source_location or {}),
        block_hash=pb.block_hash,
    )


# ── 풀옵션 결과 ────────────────────────────────────────────────────────────


@dataclass
class FullPipelineResult:
    """``process_document_full()`` 출력."""

    document_id: UUID
    title: str
    blocks: list[tuple[str, str, UUID]]  # (block_type, content, block_id) — 후방 호환
    chunks: list[MergedChunk]
    noise_blocks: list[tuple[str, str, UUID]]  # 후방 호환
    document_type: str = "other"
    document_type_confidence: float = 0.0
    document_type_reason: str = ""
    chunker_strategy: str = "semantic_default"
    chunker_qa_pairs: int = 0
    avg_chunk_chars: float = 0.0
    parser: str = ""
    use_vision: bool = False
    vision_reason: str = ""
    has_qa_pairs: bool = False
    noise_patterns: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    main_language: str = "ko"
    block_type_dist: dict[str, int] = field(default_factory=dict)
    processing_meta: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    # ── D31b 신규 (default 끝 — 후방 호환) ──────────────
    blocks_full: list[_PipelineBlock] = field(default_factory=list)
    noise_blocks_full: list[_PipelineBlock] = field(default_factory=list)
    # ── D38 v3 신규 — KC hook 결과 (default empty — 후방 호환) ─────
    kc_generated_blocks: list[_PipelineBlock] = field(default_factory=list)
    kc_hook_applied: bool = False


# ── 단계별 helpers ────────────────────────────────────────────────────────


_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FAQ_HINT_RE = re.compile(
    r"(?:\*\*)?(?:질문\s*\d+|Q[.:\s]|MENT|Answer|FAQ)",
    re.IGNORECASE,
)


async def _parse_blocks_from_markdown(
    markdown_text: str,
    *,
    title: str,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Markdown text → block 목록 + parse meta. (D31c — pages 반환 X — backward compat)

    내부적으로 `_parse_blocks_from_markdown_with_pages` 호출 후 pages 무시.
    기존 caller (외부) signature 유지.
    """
    parsed_blocks, _pages, meta = await _parse_blocks_from_markdown_with_pages(
        markdown_text, title=title
    )
    return parsed_blocks, meta


async def _parse_blocks_from_markdown_with_pages(
    markdown_text: str,
    *,
    title: str,
) -> tuple[list[tuple[str, str]], list[int | None], dict[str, Any]]:
    """D31c §6 — page 동기 wrapper. markdown 은 pn=None 항상.

    Returns:
        (parsed_blocks, pages, meta) — `len(parsed_blocks) == len(pages)`.
    """
    import tempfile

    from src.pipeline.parsers.markdown_parser import MarkdownParser

    parsed_blocks: list[tuple[str, str]] = []
    pages: list[int | None] = []
    table_count = 0
    image_count = 0
    heading_count = 0

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(markdown_text)
        tmp_path = tmp.name

    try:
        parser = MarkdownParser(tmp_path)
        parse_result = await parser.parse()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    for page in parse_result.pages:
        # markdown 은 page 개념 없음 — None 사용
        pn: int | None = None
        for tb in page.text_blocks:
            content = (tb.text or "").strip()
            if not content:
                continue
            level = int(getattr(tb, "heading_level", 0) or 0)
            if level == 0:
                first_line = content.split("\n", 1)[0]
                m = re.match(r"^(#{1,6})\s+(.+)$", first_line)
                if m:
                    level = min(len(m.group(1)), 6)
                    rest = (
                        content.split("\n", 1)[1].strip() if "\n" in content else ""
                    )
                    parsed_blocks.append(
                        (f"heading_{min(level, 3)}", m.group(2).strip())
                    )
                    pages.append(pn)
                    heading_count += 1
                    if rest:
                        parsed_blocks.append(("paragraph", rest))
                        pages.append(pn)
                    continue
            if 1 <= level <= 3:
                btype = f"heading_{level}"
                heading_count += 1
                first_line = content.split("\n", 1)[0]
                m = re.match(r"^#{1,6}\s+(.+)$", first_line)
                heading_text = m.group(1).strip() if m else first_line
                parsed_blocks.append((btype, heading_text))
                pages.append(pn)
                rest = content.split("\n", 1)[1].strip() if "\n" in content else ""
                if rest:
                    parsed_blocks.append(("paragraph", rest))
                    pages.append(pn)
            elif level >= 4:
                btype = "heading_3"
                heading_count += 1
                first_line = content.split("\n", 1)[0]
                m = re.match(r"^#{1,6}\s+(.+)$", first_line)
                heading_text = m.group(1).strip() if m else first_line
                parsed_blocks.append((btype, heading_text))
                pages.append(pn)
                rest = content.split("\n", 1)[1].strip() if "\n" in content else ""
                if rest:
                    parsed_blocks.append(("paragraph", rest))
                    pages.append(pn)
            else:
                parsed_blocks.append(("paragraph", content))
                pages.append(pn)

        for tbl in page.tables:
            table_count += 1
            try:
                rows = tbl.rows or []
                if rows:
                    md_rows = [
                        "| " + " | ".join(map(str, r)) + " |" for r in rows
                    ]
                    if md_rows:
                        sep = "| " + " | ".join(["---"] * len(rows[0])) + " |"
                        md = (
                            md_rows[0] + "\n" + sep + "\n" + "\n".join(md_rows[1:])
                        )
                    else:
                        md = "\n".join(md_rows)
                    parsed_blocks.append(("table", md))
                    pages.append(pn)
            except Exception:
                pass

        for img in page.images:
            image_count += 1
            alt = getattr(img, "alt_text", "") or ""
            src = getattr(img, "source", "") or ""
            if alt or src:
                parsed_blocks.append(("image_ref", f"![{alt}]({src})"))
                pages.append(pn)

    # D31c §6 — page 동기 split wrapper 사용
    parsed_blocks, pages = _split_long_paragraphs_with_pages(parsed_blocks, pages)
    parsed_blocks, pages = _split_faq_list_items_with_pages(parsed_blocks, pages)

    meta = {
        "parser": "MarkdownParser",
        "heading_count": heading_count,
        "table_count": table_count,
        "image_count": image_count,
        "has_front_matter": bool(parse_result.metadata.get("front_matter")),
        "page_count": len(parse_result.pages),
        "raw_text_chars": sum(len(p.text or "") for p in parse_result.pages),
    }
    return parsed_blocks, pages, meta


def _split_long_paragraphs(
    blocks: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """1200자 초과 paragraph 만 줄 단위로 잘라 의미 보존."""
    MAX = 1200
    out: list[tuple[str, str]] = []
    for btype, content in blocks:
        if btype != "paragraph" or len(content) <= MAX:
            out.append((btype, content))
            continue
        lines = content.split("\n")
        cur = ""
        for line in lines:
            if len(cur) + len(line) + 1 > MAX and cur:
                out.append(("paragraph", cur.strip()))
                cur = line + "\n"
            else:
                cur += line + "\n"
        if cur.strip():
            out.append(("paragraph", cur.strip()))
    return out


def _split_long_paragraphs_with_pages(
    blocks: list[tuple[str, str]],
    pages: list[int | None],
) -> tuple[list[tuple[str, str]], list[int | None]]:
    """D31c §6 — `_split_long_paragraphs` 의 page 동기 wrapper.

    동일 split 로직 — split 된 모든 결과는 *동일 입력 block 의 page* 를 공유.
    `len(blocks) == len(pages)` 보장. 실패 시 (mismatch) 전체 page=None 으로 fallback.
    """
    if len(blocks) != len(pages):
        # mismatch — 안전 fallback (split 결과 길이에 맞춰 None list 생성)
        out_blocks = _split_long_paragraphs(blocks)
        return out_blocks, [None] * len(out_blocks)

    MAX = 1200
    out_blocks: list[tuple[str, str]] = []
    out_pages: list[int | None] = []
    for (btype, content), pn in zip(blocks, pages):
        if btype != "paragraph" or len(content) <= MAX:
            out_blocks.append((btype, content))
            out_pages.append(pn)
            continue
        lines = content.split("\n")
        cur = ""
        for line in lines:
            if len(cur) + len(line) + 1 > MAX and cur:
                out_blocks.append(("paragraph", cur.strip()))
                out_pages.append(pn)
                cur = line + "\n"
            else:
                cur += line + "\n"
        if cur.strip():
            out_blocks.append(("paragraph", cur.strip()))
            out_pages.append(pn)
    return out_blocks, out_pages


def _split_faq_list_items(
    blocks: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """FAQ list 가 한 paragraph 로 묶인 경우 질문/MENT 패턴별로 split.

    MarkdownParser 의 결과가 list item 을 한 paragraph 로 묶을 때, chunker 가
    boundary 를 인식하지 못한다. 본 함수는 ``- **질문N:**`` / ``- **MENT:**``
    패턴을 발견하면 패턴 시작점마다 paragraph 를 분리한다.
    """
    out: list[tuple[str, str]] = []
    for btype, content in blocks:
        if btype != "paragraph":
            out.append((btype, content))
            continue
        # FAQ 패턴 미포함 시 그대로
        if "**질문" not in content and "**MENT" not in content and "Q." not in content:
            out.append((btype, content))
            continue

        lines = [ln for ln in content.split("\n")]
        cur: list[str] = []
        for ln in lines:
            stripped = ln.strip()
            is_boundary = (
                stripped.startswith("- **질문")
                or stripped.startswith("**질문")
                or stripped.startswith("- **MENT")
                or stripped.startswith("**MENT")
                or stripped.startswith("- **Q.")
                or stripped.startswith("**Q.")
                or stripped.startswith("- Q.")
            )
            if is_boundary and cur:
                joined = "\n".join(cur).strip()
                if joined:
                    out.append(("paragraph", joined))
                cur = [stripped.lstrip("- ").strip()]
            else:
                if stripped:
                    cur.append(stripped.lstrip("- ").strip() if is_boundary else stripped)
                elif cur:
                    cur.append("")
        if cur:
            joined = "\n".join(cur).strip()
            if joined:
                out.append(("paragraph", joined))
    return out


def _split_faq_list_items_with_pages(
    blocks: list[tuple[str, str]],
    pages: list[int | None],
) -> tuple[list[tuple[str, str]], list[int | None]]:
    """D31c §6 — `_split_faq_list_items` 의 page 동기 wrapper.

    동일 split 로직 — split 된 모든 결과는 *동일 입력 block 의 page* 를 공유.
    `len(blocks) == len(pages)` 보장. mismatch 시 안전 fallback (split 결과 길이에 맞춤).
    """
    if len(blocks) != len(pages):
        out_blocks = _split_faq_list_items(blocks)
        return out_blocks, [None] * len(out_blocks)

    out_blocks: list[tuple[str, str]] = []
    out_pages: list[int | None] = []
    for (btype, content), pn in zip(blocks, pages):
        if btype != "paragraph":
            out_blocks.append((btype, content))
            out_pages.append(pn)
            continue
        if "**질문" not in content and "**MENT" not in content and "Q." not in content:
            out_blocks.append((btype, content))
            out_pages.append(pn)
            continue

        lines = [ln for ln in content.split("\n")]
        cur: list[str] = []
        for ln in lines:
            stripped = ln.strip()
            is_boundary = (
                stripped.startswith("- **질문")
                or stripped.startswith("**질문")
                or stripped.startswith("- **MENT")
                or stripped.startswith("**MENT")
                or stripped.startswith("- **Q.")
                or stripped.startswith("**Q.")
                or stripped.startswith("- Q.")
            )
            if is_boundary and cur:
                joined = "\n".join(cur).strip()
                if joined:
                    out_blocks.append(("paragraph", joined))
                    out_pages.append(pn)
                cur = [stripped.lstrip("- ").strip()]
            else:
                if stripped:
                    cur.append(stripped.lstrip("- ").strip() if is_boundary else stripped)
                elif cur:
                    cur.append("")
        if cur:
            joined = "\n".join(cur).strip()
            if joined:
                out_blocks.append(("paragraph", joined))
                out_pages.append(pn)
    return out_blocks, out_pages


# ── document_structure Stage 1 (markdown 본 sample) ───────────────────────


async def analyze_document_structure(
    *,
    title: str,
    blocks: Sequence[tuple[str, str]],
    llm_client: object | None = None,
) -> dict[str, Any]:
    """markdown / 텍스트 본문 sample 을 LLM 으로 분석.

    출력:
        {
            "document_type": "faq" | "manual" | ...,
            "sections": [...],
            "noise_patterns": [...],
            "main_language": "ko" | "en",
            "has_qa_pairs": bool,
            "core_topic": "...",
        }

    LLM 미주입/실패 시 *heuristic fallback* — has_qa_pairs 만은 항상 정확 (코드
    detect_faq_pattern 으로 확정). 나머지 필드는 빈값.
    """
    # 본문 sample 구성 — 처음 몇 블록 + 중간 sample
    sample_lines: list[str] = []
    block_count = len(blocks)
    sample_indices = list(range(min(8, block_count)))
    if block_count > 16:
        mid = block_count // 2
        sample_indices.extend([mid, mid + 1])
    for i in sample_indices:
        if i < block_count:
            btype, content = blocks[i]
            sample_lines.append(f"[{btype}] {content[:300]}")
    sample = "\n".join(sample_lines)[:2500]

    # 코드 휴리스틱: 입력 InputBlock 변환해 detect_faq_pattern 호출 가능하게
    input_blocks_for_detect = [
        InputBlock(uuid4(), btype, content, idx)
        for idx, (btype, content) in enumerate(blocks)
    ]
    qa_count = detect_faq_pattern(input_blocks_for_detect)
    has_qa_pairs = qa_count >= 3

    fallback = {
        "document_type": "faq" if has_qa_pairs else "other",
        "sections": [],
        "noise_patterns": [],
        "main_language": "ko",
        "has_qa_pairs": has_qa_pairs,
        "core_topic": "",
        "qa_pairs_detected": qa_count,
        "_source": "heuristic",
    }

    if llm_client is None:
        return fallback

    prompt = (
        "당신은 문서 구조를 빠르게 분석하는 전문가입니다.\n"
        "본문 sample 을 보고 문서 유형 + 노이즈 패턴 + Q&A 쌍 포함 여부를 판단하세요.\n\n"
        "## 문서 유형 (원리)\n"
        "- `faq` : 질문/답변 쌍이 반복되는 형식 (FAQ, 콜센터 상담스크립트 등)\n"
        "- `manual` : 매뉴얼·절차서·운영 가이드. 단계별 지시문\n"
        "- `presentation` : 발표 자료. 슬라이드 형식\n"
        "- `memo` : 회의록·메모·짧은 비공식 기록\n"
        "- `email` : 이메일 본문\n"
        "- `report` : 분석 보고서. 배경→분석→결론 구조\n"
        "- `research_note` : 외부 자료 정리·리서치 노트\n"
        "- `other` : 위 어디에도 명확히 들어맞지 않는 경우\n\n"
        f"## 문서\n- 제목: {title or '(제목 없음)'}\n"
        f"- 본문 sample (최대 ~2500자):\n{sample}\n\n"
        "## 출력 (JSON 한 객체만, 마크다운 펜스 금지)\n"
        '{"document_type": "<카테고리>", "sections": ["주요 섹션 5개 이내"], '
        '"noise_patterns": ["반복되는 헤더/푸터/페이지번호/목차 패턴"], '
        '"main_language": "ko|en", "has_qa_pairs": true/false, '
        '"core_topic": "1줄 주제"}'
    )

    raw = ""
    try:
        if hasattr(llm_client, "chat_completion_json"):
            messages = [
                {
                    "role": "system",
                    "content": (
                        "문서 구조 분석 전문가. JSON 한 객체만 출력. "
                        "마크다운 코드 펜스, 설명 문장 금지."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            raw = await llm_client.chat_completion_json(  # type: ignore[union-attr]
                messages,
                temperature=0.1,
                max_tokens=600,
            )
        elif hasattr(llm_client, "generate"):
            raw = await llm_client.generate(prompt)  # type: ignore[union-attr]
    except Exception as exc:
        log.warning("document_structure_llm_failed", error=str(exc))
        return fallback

    try:
        from src.common.llm_utils import extract_json_object

        parsed = extract_json_object(raw) or {}
    except Exception:
        return fallback

    if not isinstance(parsed, dict):
        return fallback

    # 정규화 — 빈 값은 fallback 으로 채움
    return {
        "document_type": str(parsed.get("document_type") or fallback["document_type"]).lower(),
        "sections": parsed.get("sections") or [],
        "noise_patterns": parsed.get("noise_patterns") or [],
        "main_language": parsed.get("main_language") or "ko",
        "has_qa_pairs": bool(parsed.get("has_qa_pairs", has_qa_pairs)),
        "core_topic": parsed.get("core_topic") or "",
        "qa_pairs_detected": qa_count,
        "_source": "llm",
    }


# ── 노이즈 분리 ───────────────────────────────────────────────────────────


def partition_noise_text_blocks(
    blocks: list[tuple[str, str]],
    noise_patterns: Sequence[str] | None = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """noise_patterns 에 매칭되는 block 분리.

    Returns:
        (content_blocks, noise_blocks)
    """
    if not noise_patterns:
        # 기본 패턴
        noise_patterns = [
            r"^-?\s*\d+\s*-?$",  # 페이지 번호
            r"^Page\s+\d+\s+of\s+\d+$",
            r"^\d+\s*/\s*\d+$",
            r"^목\s*차$",
            r"^TABLE\s+OF\s+CONTENTS$",
        ]

    compiled: list[re.Pattern] = []
    for pattern in noise_patterns:
        if not isinstance(pattern, str):
            continue
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            compiled.append(re.compile(re.escape(pattern), re.IGNORECASE))

    content: list[tuple[str, str]] = []
    noise: list[tuple[str, str]] = []
    for btype, ctxt in blocks:
        # heading 은 보호 — 단, "목차" / "TOC" 등 제목성 노이즈는 패턴 매칭에 맡김
        ctxt_strip = (ctxt or "").strip()
        if not ctxt_strip:
            noise.append((btype, ctxt))
            continue

        # 너무 짧고 숫자/특수문자만이면 노이즈
        if len(ctxt_strip) <= 5 and re.match(r"^[\d\-\s\|\.]+$", ctxt_strip):
            noise.append((btype, ctxt))
            continue

        # 패턴 매칭
        is_noise = False
        for pattern in compiled:
            if pattern.match(ctxt_strip):
                is_noise = True
                break
        if is_noise:
            noise.append((btype, ctxt))
        else:
            content.append((btype, ctxt))

    return content, noise


def partition_noise_text_blocks_with_index(
    blocks: list[tuple[str, str]],
    noise_patterns: Sequence[str] | None = None,
) -> tuple[
    list[tuple[str, str]],  # content_blocks
    list[tuple[str, str]],  # noise_blocks
    list[int],  # content_idx — 원본 blocks 의 idx
    list[int],  # noise_idx — 원본 blocks 의 idx
]:
    """D31c §6 — `partition_noise_text_blocks` 와 동일 로직 + 원본 index 반환.

    full_pipeline 의 page propagation 용. 기존 `partition_noise_text_blocks` signature
    는 보존 (외부 caller 영향 0). content_idx / noise_idx 로 원본 page list lookup.
    """
    if not noise_patterns:
        noise_patterns = [
            r"^-?\s*\d+\s*-?$",
            r"^Page\s+\d+\s+of\s+\d+$",
            r"^\d+\s*/\s*\d+$",
            r"^목\s*차$",
            r"^TABLE\s+OF\s+CONTENTS$",
        ]

    compiled: list[re.Pattern] = []
    for pattern in noise_patterns:
        if not isinstance(pattern, str):
            continue
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            compiled.append(re.compile(re.escape(pattern), re.IGNORECASE))

    content: list[tuple[str, str]] = []
    noise: list[tuple[str, str]] = []
    content_idx: list[int] = []
    noise_idx: list[int] = []

    for i, (btype, ctxt) in enumerate(blocks):
        ctxt_strip = (ctxt or "").strip()
        if not ctxt_strip:
            noise.append((btype, ctxt))
            noise_idx.append(i)
            continue

        if len(ctxt_strip) <= 5 and re.match(r"^[\d\-\s\|\.]+$", ctxt_strip):
            noise.append((btype, ctxt))
            noise_idx.append(i)
            continue

        is_noise = False
        for pattern in compiled:
            if pattern.match(ctxt_strip):
                is_noise = True
                break
        if is_noise:
            noise.append((btype, ctxt))
            noise_idx.append(i)
        else:
            content.append((btype, ctxt))
            content_idx.append(i)

    return content, noise, content_idx, noise_idx


# ── 메인 entry point ──────────────────────────────────────────────────────


async def process_document_full(
    *,
    title: str,
    file_path: Path | str | None = None,
    markdown_text: str | None = None,
    llm_client: object | None = None,
    document_type_hint: str | None = None,
    upload_source: str = "unknown",
    similarity_threshold: float = 0.18,
    min_chars: int = 200,
    max_chars: int = 1800,
    faq_min_qa_chars: int = 60,
    document_id: UUID | None = None,
) -> FullPipelineResult:
    """KMS 풀옵션 pipeline — 단일 entry point.

    절칙 (2026-05-07 사용자 명시):
    - 풀옵션 무조건 — vision_gate / Stage1 / noise / type / chunker / embed
    - 시간보다 품질 우선
    - 모든 ingest endpoint 가 본 함수만 호출 (직접 INSERT 금지)

    Parameters
    ----------
    title : str
        문서 제목.
    file_path : Path | str | None
        원본 파일 경로 (PDF/PPT/MD/DOCX 등). markdown_text 와 둘 중 하나 필수.
    markdown_text : str | None
        markdown 본문 (chat upload / auto-draft 시).
    llm_client : object | None
        Stage1 + DocumentTypeClassifier 용. 미주입 시 휴리스틱 fallback.
    document_type_hint : str | None
        외부에서 알고 있는 type — Stage1 결과보다 우선.
    upload_source : str
        chat_upload / repo_upload / agent_documents / knowledge_endpoint /
        reseed — processing_meta 에 기록.
    similarity_threshold / min_chars / max_chars / faq_min_qa_chars
        chunker 튜닝.

    Returns
    -------
    FullPipelineResult
        단일 함수가 *block + chunk + meta* 모두 반환. caller 가 DB INSERT.
        (DB INSERT 까지 묶지 않은 이유: reseed 는 자체 트랜잭션 사용 / 워커는
         이미 _persist_blocks_to_db 사용 → ingest path 별 transaction 경계
         분리 유지가 안전.)
    """
    import time as _time

    start = _time.monotonic()
    doc_id = document_id or uuid4()

    # ── 1) ParseResult — markdown_text 또는 파일 ─────────────────────────
    # D31c §6 — pages list 동기 carry (markdown=None / PDF·PPT=page_number)
    parse_pages: list[int | None] = []
    if markdown_text is not None:
        parse_blocks, parse_pages, parse_meta = await _parse_blocks_from_markdown_with_pages(
            markdown_text, title=title
        )
        parser_name = "MarkdownParser(text)"
        use_vision = False
        vision_reason = "text_input"
    elif file_path:
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        if ext == ".md":
            text = path_obj.read_text(encoding="utf-8", errors="replace")
            parse_blocks, parse_pages, parse_meta = await _parse_blocks_from_markdown_with_pages(
                text, title=title
            )
            parser_name = "MarkdownParser"
            use_vision = False
            vision_reason = "markdown_file"
        else:
            # PDF / PPT / docx 등 — 정식 파서 라우터
            from src.pipeline.parsers.router import detect_format, select_parser
            from src.pipeline.workers.vision_gate import decide_vision

            fmt = detect_format(str(path_obj))
            parser = select_parser(fmt, str(path_obj))
            parse_result = await parser.parse()
            parser_name = type(parser).__name__

            # vision_gate 결정
            decision = decide_vision(parse_result, str(path_obj))
            use_vision = decision.use_vision
            vision_reason = decision.reason

            # D31c §6 — ParseResult → block tuple + pages 동기 추출
            parse_blocks = []
            parse_pages = []
            for page in parse_result.pages:
                # PDF 는 page_number, PPTX 는 slide_number 또는 page_number 사용
                pn = getattr(page, "page_number", None) or getattr(page, "slide_number", None)
                for tb in page.text_blocks:
                    content = (tb.text or "").strip()
                    if not content:
                        continue
                    level = int(getattr(tb, "heading_level", 0) or 0)
                    if 1 <= level <= 3:
                        parse_blocks.append((f"heading_{level}", content))
                        parse_pages.append(pn)
                    elif level >= 4:
                        parse_blocks.append(("heading_3", content))
                        parse_pages.append(pn)
                    else:
                        parse_blocks.append(("paragraph", content))
                        parse_pages.append(pn)
                for tbl in page.tables:
                    rows = tbl.rows or []
                    if rows:
                        md_rows = [
                            "| " + " | ".join(map(str, r)) + " |" for r in rows
                        ]
                        sep = "| " + " | ".join(["---"] * len(rows[0])) + " |"
                        parse_blocks.append(
                            ("table", md_rows[0] + "\n" + sep + "\n" + "\n".join(md_rows[1:]))
                        )
                        parse_pages.append(pn)
            parse_blocks, parse_pages = _split_long_paragraphs_with_pages(
                parse_blocks, parse_pages
            )
            parse_blocks, parse_pages = _split_faq_list_items_with_pages(
                parse_blocks, parse_pages
            )
            parse_meta = {
                "parser": parser_name,
                "heading_count": sum(1 for bt, _ in parse_blocks if bt.startswith("heading")),
                "table_count": len(parse_result.tables),
                "image_count": len(parse_result.images),
                "page_count": len(parse_result.pages),
                "raw_text_chars": sum(len(p.text or "") for p in parse_result.pages),
            }
    else:
        raise ValueError("file_path or markdown_text required")

    # D31c §6 — invariant: len(parse_blocks) == len(parse_pages)
    if len(parse_blocks) != len(parse_pages):
        log.warning(
            "parse_pages_mismatch_falling_back_to_none",
            blocks=len(parse_blocks),
            pages=len(parse_pages),
        )
        parse_pages = [None] * len(parse_blocks)

    if not parse_blocks:
        return FullPipelineResult(
            document_id=doc_id,
            title=title,
            blocks=[],
            chunks=[],
            noise_blocks=[],
            parser=parser_name,
            use_vision=use_vision,
            vision_reason=vision_reason,
            elapsed_ms=int((_time.monotonic() - start) * 1000),
            processing_meta={"_warning": "no_blocks_extracted"},
        )

    # ── 2) document_structure Stage 1 — markdown sample 또는 LLM 분석 ──
    structure = await analyze_document_structure(
        title=title, blocks=parse_blocks, llm_client=llm_client
    )

    # ── 3) noise 분리 (D31c §6 — partition_with_index + page mapping) ──
    noise_patterns = structure.get("noise_patterns") or []
    content_blocks, noise_blocks, content_idx, noise_idx = (
        partition_noise_text_blocks_with_index(parse_blocks, noise_patterns)
    )
    # pages 매핑 — 원본 idx → page
    content_pages = [parse_pages[i] for i in content_idx]
    noise_pages = [parse_pages[i] for i in noise_idx]

    # ── 4) document_type 결정 (hint > Stage1 > LLM classifier) ─────────
    if document_type_hint:
        document_type = document_type_hint.lower().strip()
        dt_confidence = 1.0
        dt_reason = f"hint:{upload_source}"
    else:
        document_type = structure.get("document_type", "other")
        dt_confidence = 0.7 if structure.get("_source") == "llm" else 0.5
        dt_reason = (
            f"Stage1 ({structure.get('_source', 'heuristic')}); "
            f"qa_pairs_detected={structure.get('qa_pairs_detected', 0)}"
        )

        # Stage1 결과 보강 — DocumentTypeClassifier (선택)
        if llm_client is not None and document_type == "other":
            try:
                from src.pipeline.enrichers.document_type_classifier import (
                    DocumentTypeClassifier,
                    derive_extension,
                )

                classifier = DocumentTypeClassifier(llm_client=llm_client)
                ext = derive_extension(str(file_path) if file_path else "") or ".md"
                # 본문 1000자 sample
                sample = "\n".join(c for _, c in content_blocks[:8])[:1000]
                classifier_result = await classifier.classify(
                    title=title, text_sample=sample, file_extension=ext
                )
                if classifier_result.get("document_type") != "other":
                    document_type = classifier_result["document_type"]
                    dt_confidence = float(classifier_result.get("confidence") or 0.6)
                    dt_reason = (
                        f"DocumentTypeClassifier: "
                        f"{classifier_result.get('reason', '')[:120]}"
                    )
            except Exception as exc:
                log.debug("doc_type_classifier_skip", error=str(exc))

    # has_qa_pairs 패턴이 강하면 강제로 faq 로 (사용자 절칙).
    # GPT-5 review 반영 — 단순 ≥3 카운트는 큰 manual 안에 우연히 Q&A 3쌍이 끼어들 때
    # 오분류되므로 *밀도* (qa_pairs / content_blocks) 도 함께 검사. 임계 12% 초과
    # 시에만 자동 승격.
    #
    # 사용자 절칙 ("2-16-5. 전출입. AS-요금정산 문의 그래야 이런 문서도 FAQ 형태라고
    # 인지" — 2026-05-07) 충족 위해 hint 가 'manual' 이라도 본문 FAQ 밀도가 강하면
    # 'faq' 로 override. (folder.kind 가 폴더 통째로 'sop' 이지만 자료 유형은 다양.)
    has_qa = bool(structure.get("has_qa_pairs"))
    qa_pairs_detected = int(structure.get("qa_pairs_detected") or 0)
    content_block_count = max(1, len(content_blocks))
    qa_density = qa_pairs_detected / content_block_count
    faq_promote_min_density = 0.12  # FAQ 자료는 보통 30%+ 가 질문 boundary
    can_override_to_faq = document_type in ("other", "manual")  # FAQ 가 아닌 분류만 override 대상
    if (
        has_qa
        and can_override_to_faq
        and qa_pairs_detected >= 3
        and qa_density >= faq_promote_min_density
    ):
        prev_dt = document_type
        document_type = "faq"
        dt_reason = (
            f"auto_promote_faq_pattern (was={prev_dt} "
            f"pairs={qa_pairs_detected} density={qa_density:.2f})"
        )
        dt_confidence = max(dt_confidence, 0.85)
    elif has_qa and can_override_to_faq:
        # 패턴은 있으나 밀도 부족 — 현재 유형 유지 (FAQ 오승격 방지)
        dt_reason += f" | faq_density_insufficient (pairs={qa_pairs_detected} density={qa_density:.2f})"

    # ── 5) _PipelineBlock 부여 (D31b §1 + §3.2 + D31c §6 page) ─────────
    # D31b 단계: metadata / kc_markers default empty.
    # D31c §6: source_location.page 채움 (PDF/PPT path 만; markdown 은 pn=None → {}).
    # 실 채움은 D31d (KC hook) 별도.
    blocks_full: list[_PipelineBlock] = []
    for idx, ((btype, content), pn) in enumerate(zip(content_blocks, content_pages)):
        bid = uuid4()
        blocks_full.append(
            _PipelineBlock(
                block_id=bid,
                block_type=btype,
                content=content,
                block_index=idx,
                metadata={},
                contextual_prefix=None,
                extracted_metadata=None,
                source_location={"page": pn} if pn is not None else {},
                block_hash=_compute_block_hash(content, idx),
                kc_markers={},
            )
        )

    noise_blocks_full: list[_PipelineBlock] = []
    for idx, ((btype, content), pn) in enumerate(zip(noise_blocks, noise_pages)):
        bid = uuid4()
        noise_blocks_full.append(
            _PipelineBlock(
                block_id=bid,
                block_type=btype,
                content=content,
                block_index=idx,
                metadata={"is_noise": True},
                contextual_prefix=None,
                extracted_metadata=None,
                source_location={"page": pn} if pn is not None else {},
                block_hash=_compute_block_hash(content, idx),
                kc_markers={},
            )
        )

    # 후방 호환 view (3-tuple) — 기존 caller (reseed_v4 / 기존 test) 영향 0
    blocks_with_id: list[tuple[str, str, UUID]] = [
        (pb.block_type, pb.content, pb.block_id) for pb in blocks_full
    ]
    noise_with_id: list[tuple[str, str, UUID]] = [
        (pb.block_type, pb.content, pb.block_id) for pb in noise_blocks_full
    ]

    # block_type 분포 — blocks_full 기반
    bt_dist: dict[str, int] = {}
    for pb in blocks_full:
        bt_dist[pb.block_type] = bt_dist.get(pb.block_type, 0) + 1

    # ── 5.5) KC hook (D38 v3 — D17 oldopen 종결) ─────────────────────────
    # 절칙 (2026-05-07): KMS 풀옵션 — heading_path / topic_tags / search_summary /
    # contextual_prefix / table_nl / image_captions / entities / crosslinks 모두 채움.
    # D17-v5 KC_VERSION + cleanup→regen idempotency.
    #
    # v3 정책:
    #   - copy.deepcopy 로 KC 입력 완전 격리 → 실패 시 blocks_full 변경 0 보장 (atomic swap).
    #   - generated SUMMARY/ENTITY block 은 chunker 입력에서 제외 (별도 retrieval index).
    #   - block-level marker (kc_hook_applied/version/at) 모든 block 에 주입 →
    #     merge_worker 가 block 리스트만 받아도 double-call 차단 (§1.3a).
    #   - BlockObject 전체 schema 보존 (token_count/properties/children/table_*/image_*).
    _skip_kc_env = (os.environ.get("SKIP_KNOWLEDGE_COMPILER", "false").lower()
                    in ("true", "1", "yes"))
    kc_hook_applied = False
    kc_generated_blocks: list[_PipelineBlock] = []
    if not _skip_kc_env and llm_client is not None and blocks_full:
        try:
            from src.pipeline.enrichers.knowledge_compiler import (
                KC_VERSION,
                KnowledgeCompiler,
                _KC_GENERATED_SOURCES,
            )
            from src.pipeline.models.block import BlockObject, BlockType
            from src.pipeline.models.document import (
                ProcessingConfig,
                SourceLocation,
            )

            def _pb_to_bo(pb: _PipelineBlock) -> BlockObject:
                bt_norm = pb.block_type
                try:
                    bt_enum = BlockType(bt_norm)
                except ValueError:
                    bt_enum = BlockType.PARAGRAPH
                # source_location 정규화
                sl_input = copy.deepcopy(pb.source_location or {})
                try:
                    sl = SourceLocation(**sl_input)
                except Exception:
                    sl = SourceLocation()
                return BlockObject(
                    id=pb.block_id,
                    document_id=doc_id,
                    block_type=bt_enum,
                    content=pb.content,
                    block_index=pb.block_index,
                    block_hash=pb.block_hash,
                    token_count=pb.token_count,
                    source_location=sl,
                    properties=copy.deepcopy(pb.properties or {}),
                    children=list(pb.children or []),
                    metadata=copy.deepcopy(pb.metadata or {}),
                    contextual_prefix=pb.contextual_prefix,
                    extracted_metadata=copy.deepcopy(pb.extracted_metadata),
                    table_headers=(
                        list(pb.table_headers) if pb.table_headers else None
                    ),
                    table_rows=(
                        [list(r) for r in pb.table_rows]
                        if pb.table_rows else None
                    ),
                    table_markdown=pb.table_markdown,
                    image_path=pb.image_path,
                    ocr_text=pb.ocr_text,
                    image_description=pb.image_description,
                )

            def _bo_to_pb(bo: BlockObject) -> _PipelineBlock:
                sl_dict = (
                    bo.source_location.model_dump(exclude_none=True)
                    if bo.source_location else {}
                )
                return _PipelineBlock(
                    block_id=bo.id,
                    block_type=(
                        bo.block_type.value
                        if hasattr(bo.block_type, "value")
                        else str(bo.block_type)
                    ),
                    content=bo.content,
                    block_index=bo.block_index,
                    metadata=copy.deepcopy(bo.metadata or {}),
                    contextual_prefix=bo.contextual_prefix,
                    extracted_metadata=copy.deepcopy(bo.extracted_metadata),
                    source_location=copy.deepcopy(sl_dict),
                    block_hash=bo.block_hash,
                    kc_markers={},
                    # v3 신규 — BlockObject 전체 schema 보존
                    token_count=bo.token_count or 0,
                    properties=copy.deepcopy(bo.properties or {}),
                    children=list(bo.children or []),
                    table_headers=(
                        list(bo.table_headers) if bo.table_headers else None
                    ),
                    table_rows=(
                        [list(r) for r in bo.table_rows]
                        if bo.table_rows else None
                    ),
                    table_markdown=bo.table_markdown,
                    image_path=bo.image_path,
                    ocr_text=bo.ocr_text,
                    image_description=bo.image_description,
                )

            # _PipelineBlock → BlockObject 변환 (KC 입력) — deepcopy 격리.
            bo_list: list[BlockObject] = [_pb_to_bo(pb) for pb in blocks_full]

            proc_config = ProcessingConfig()
            compiler = KnowledgeCompiler(proc_config, llm_client=llm_client)
            document_text = "\n\n".join(b.content for b in bo_list if b.content)
            compiled = await compiler.compile(
                blocks=bo_list,
                document_text=document_text,
                document_title=title or "",
            )

            # v3.1 block-level marker 주입 — non_generated + generated 모두.
            # merge_worker / Kafka consumer 가 block 리스트만 받아도 double-call 차단.
            kc_hook_at = datetime.now(timezone.utc).isoformat()
            for bo in compiled:
                if bo.metadata is None:
                    bo.metadata = {}
                bo.metadata["kc_hook_applied"] = True
                bo.metadata["kc_hook_version"] = KC_VERSION
                bo.metadata["kc_hook_at"] = kc_hook_at

            # 그룹 1 (KC 보강된 input block) / 그룹 2 (KC 추가 SUMMARY/ENTITY block) 분리.
            non_generated_bo: list[BlockObject] = []
            generated_bo: list[BlockObject] = []
            for bo in compiled:
                md = bo.metadata or {}
                is_generated = (
                    bool(md.get("generated"))
                    and str(md.get("source", "")) in _KC_GENERATED_SOURCES
                )
                (generated_bo if is_generated else non_generated_bo).append(bo)

            # atomic swap — KC 정상 종료 후에만 blocks_full 교체.
            new_blocks_full: list[_PipelineBlock] = [
                _bo_to_pb(bo) for bo in non_generated_bo
            ]
            kc_generated_blocks_local = [_bo_to_pb(bo) for bo in generated_bo]

            # v3.2 guard — 손실 0 원칙. KC 후 non-generated id set 이 원본과 일치해야 함.
            # KC 가 실수로 block 누락하거나 추가하면 즉시 raise → atomic swap 차단.
            original_ids = {pb.block_id for pb in blocks_full}
            non_generated_ids = {pb.block_id for pb in new_blocks_full}
            if original_ids != non_generated_ids:
                missing = original_ids - non_generated_ids
                added = non_generated_ids - original_ids
                raise RuntimeError(
                    f"KC hook block id mismatch — missing={len(missing)} added={len(added)} "
                    f"(원본 {len(original_ids)} vs non-generated {len(non_generated_ids)})"
                )

            blocks_full = new_blocks_full
            kc_generated_blocks = kc_generated_blocks_local
            kc_hook_applied = True

            # 후방 호환 view 갱신 (generated block 포함 — DB INSERT 대상).
            all_pb = blocks_full + kc_generated_blocks
            blocks_with_id = [
                (pb.block_type, pb.content, pb.block_id) for pb in all_pb
            ]
            bt_dist = {}
            for pb in all_pb:
                bt_dist[pb.block_type] = bt_dist.get(pb.block_type, 0) + 1
            log.info(
                "full_pipeline_kc_hook_applied",
                document_id=str(doc_id),
                blocks_in=len(bo_list),
                blocks_out=len(blocks_full),
                generated=len(kc_generated_blocks),
            )
        except Exception as exc:
            # KC 실패해도 본 ingest 계속 — atomic swap 전에 실패하므로 누수 0.
            kc_hook_applied = False
            kc_generated_blocks = []
            log.warning(
                "full_pipeline_kc_hook_failed",
                document_id=str(doc_id),
                error=str(exc),
            )

    # ── 6) TypeAwareChunker — _to_input_block() 변환 (D31b §3.2) ───────
    # generated SUMMARY/ENTITY block 은 chunker 입력 *제외* (그룹 1 만).
    input_blocks = [_to_input_block(pb) for pb in blocks_full]

    merger = SemanticBlockMerger(
        similarity_threshold=similarity_threshold,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    chunker = TypeAwareChunker(
        merger=merger,
        min_chars=min_chars,
        max_chars=max_chars,
        faq_min_qa_chars=faq_min_qa_chars,
    )

    chunker_result = chunker.chunk(input_blocks, document_type=document_type)
    chunks = chunker_result.chunks

    elapsed_ms = int((_time.monotonic() - start) * 1000)

    # ── 7) processing_meta 풍부 ────────────────────────────────────────
    processing_meta = {
        "pipeline_version": "full-pipeline-v1-2026-05-07",
        "upload_source": upload_source,
        "parser": parser_name,
        "vision": {
            "use_vision": use_vision,
            "reason": vision_reason,
        },
        "stage1": {
            "document_type": structure.get("document_type"),
            "sections": structure.get("sections"),
            "noise_patterns": structure.get("noise_patterns"),
            "main_language": structure.get("main_language"),
            "has_qa_pairs": structure.get("has_qa_pairs"),
            "qa_pairs_detected": structure.get("qa_pairs_detected"),
            "core_topic": structure.get("core_topic"),
            "source": structure.get("_source"),
        },
        "noise": {
            "noise_blocks_count": len(noise_blocks),
            "content_blocks_count": len(content_blocks),
            "patterns": list(noise_patterns)[:10],
        },
        "document_type": {
            "classified": document_type,
            "confidence": dt_confidence,
            "reason": dt_reason,
            "hint_source": upload_source if document_type_hint else None,
            # GPT-5 review 반영 — 관측성 강화
            "qa_pairs_detected": qa_pairs_detected,
            "qa_density": round(qa_density, 3),
            "faq_promote_min_density": faq_promote_min_density,
        },
        "chunker": {
            "strategy": chunker_result.strategy,
            "qa_pairs_count": chunker_result.qa_pairs_count,
            "avg_chunk_chars": chunker_result.avg_chunk_chars,
            "notes": chunker_result.notes,
            "params": {
                "similarity_threshold": similarity_threshold,
                "min_chars": min_chars,
                "max_chars": max_chars,
                "faq_min_qa_chars": faq_min_qa_chars,
            },
        },
        "embedding_model": "BGE-M3",
        "block_count": len(blocks_with_id),
        "block_type_dist": bt_dist,
        "chunk_count": len(chunks),
        "heading_count": parse_meta.get("heading_count", 0),
        "table_count": parse_meta.get("table_count", 0),
        "image_count": parse_meta.get("image_count", 0),
        "page_count": parse_meta.get("page_count", 0),
        "raw_text_chars": parse_meta.get("raw_text_chars", 0),
        "elapsed_ms": elapsed_ms,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        # D38 v3 — KC hook 결과 처리 meta (doc-level marker — 보조)
        "kc_hook_applied": kc_hook_applied,
        "kc_generated_count": len(kc_generated_blocks),
    }

    log.info(
        "full_pipeline_complete",
        document_id=str(doc_id),
        title=title[:50],
        document_type=document_type,
        strategy=chunker_result.strategy,
        blocks=len(blocks_with_id),
        chunks=len(chunks),
        noise=len(noise_blocks),
        elapsed_ms=elapsed_ms,
        upload_source=upload_source,
    )

    return FullPipelineResult(
        document_id=doc_id,
        title=title,
        blocks=blocks_with_id,
        chunks=chunks,
        noise_blocks=noise_with_id,
        document_type=document_type,
        document_type_confidence=dt_confidence,
        document_type_reason=dt_reason,
        chunker_strategy=chunker_result.strategy,
        chunker_qa_pairs=chunker_result.qa_pairs_count,
        avg_chunk_chars=chunker_result.avg_chunk_chars,
        parser=parser_name,
        use_vision=use_vision,
        vision_reason=vision_reason,
        has_qa_pairs=has_qa,
        noise_patterns=list(structure.get("noise_patterns") or []),
        sections=list(structure.get("sections") or []),
        main_language=structure.get("main_language", "ko"),
        block_type_dist=bt_dist,
        processing_meta=processing_meta,
        elapsed_ms=elapsed_ms,
        # D31b §2 — _PipelineBlock 풀 metadata 노출 (D31c 가 사용)
        blocks_full=blocks_full,
        noise_blocks_full=noise_blocks_full,
        # D38 v3 — KC hook 결과 (caller 가 generated block 도 INSERT)
        kc_generated_blocks=kc_generated_blocks,
        kc_hook_applied=kc_hook_applied,
    )

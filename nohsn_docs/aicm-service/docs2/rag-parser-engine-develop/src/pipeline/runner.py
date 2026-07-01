"""Pipeline Runner -- 단일 문서를 파싱 -> 청킹 -> 임베딩 -> Qdrant 저장까지 처리.

Kafka 없이 동기적으로 실행되는 독립 스크립트.

Usage:
    python -m src.pipeline.runner /path/to/file.pdf --collection aicm_test_chunks
    python -m src.pipeline.runner /path/to/file.doc --collection aicm_test_chunks
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

# ---------------------------------------------------------------------------
# 프로젝트 루트를 PYTHONPATH 에 추가
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 환경 변수 로드 (.env)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    # python-dotenv 가 없으면 .env 파일을 수동 파싱
    env_file = os.path.join(_PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

from src.common.logging import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)

from src.pipeline.models.document import (
    ChunkObject,
    ChunkStrategy,
    ProcessingConfig,
    ProcessingDifficulty,
    SourceLocation,
)
from src.pipeline.models.parse_result import (
    ImageContent,
    PageContent,
    ParseResult,
    TableContent,
    TextBlock,
)

# ---------------------------------------------------------------------------
# 유틸리티: 스테이지 타이밍
# ---------------------------------------------------------------------------

class StageTimer:
    """파이프라인 스테이지별 소요 시간 기록."""

    def __init__(self) -> None:
        self.stages: list[dict[str, Any]] = []
        self._start: float = 0.0

    def start(self, name: str) -> None:
        self._start = time.time()
        self._current_name = name

    def stop(self) -> dict[str, Any]:
        elapsed = round(time.time() - self._start, 3)
        entry = {"stage": self._current_name, "elapsed_sec": elapsed}
        self.stages.append(entry)
        return entry


# ---------------------------------------------------------------------------
# Stage 1: Format detection
# ---------------------------------------------------------------------------

def detect_format(file_path: str) -> str:
    """파일 포맷 감지. 확장자 + magic bytes 기반."""
    ext = os.path.splitext(file_path)[1].lower()
    ext_map = {
        ".pdf": "pdf",
        ".doc": "doc",
        ".docx": "docx",
        ".hwp": "hwp",
        ".hwpx": "hwpx",
        ".xlsx": "xlsx",
        ".txt": "txt",
    }
    fmt = ext_map.get(ext, "unknown")

    # magic bytes 확인
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)
        if header[:4] == b"%PDF":
            fmt = "pdf"
        elif header[:4] == b"PK\x03\x04" and ext in (".docx", ".xlsx", ".hwpx"):
            pass  # 확장자 기반 유지
        elif header[:4] == b"\xd0\xcf\x11\xe0":
            if ext == ".doc":
                fmt = "doc"
            elif ext == ".hwp":
                fmt = "hwp"
    except OSError:
        pass

    return fmt


# ---------------------------------------------------------------------------
# Stage 2: Format conversion (DOC/HWP -> PDF)
# ---------------------------------------------------------------------------

def convert_to_pdf(file_path: str, fmt: str) -> str:
    """DOC/HWP 파일을 LibreOffice 로 PDF 변환. 이미 PDF 면 그대로 반환."""
    if fmt == "pdf":
        return file_path

    output_dir = os.path.dirname(file_path) or "/tmp"
    base = os.path.splitext(os.path.basename(file_path))[0]
    output_pdf = os.path.join(output_dir, f"{base}.pdf")

    if os.path.exists(output_pdf):
        log.info("conversion_skipped_existing", output=output_pdf)
        return output_pdf

    # Docker 컨테이너 내부 LibreOffice 사용 시도
    try:
        result = subprocess.run(
            [
                "docker", "exec", "kms-input-pipeline-api-1",
                "libreoffice", "--headless", "--convert-to", "pdf",
                "--outdir", output_dir, file_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and os.path.exists(output_pdf):
            log.info("converted_via_docker_libreoffice", output=output_pdf)
            return output_pdf
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # 로컬 LibreOffice 시도
    try:
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--convert-to", "pdf",
                "--outdir", output_dir, file_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and os.path.exists(output_pdf):
            log.info("converted_via_local_libreoffice", output=output_pdf)
            return output_pdf
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    log.warning("conversion_failed_using_original", format=fmt, path=file_path)
    return file_path


# ---------------------------------------------------------------------------
# Stage 3-5: Extract text, images, tables (pdfplumber)
# ---------------------------------------------------------------------------

def extract_pdf_content(pdf_path: str) -> ParseResult:
    """pdfplumber 로 텍스트/표/이미지를 추출한다."""
    import pdfplumber

    pages: list[PageContent] = []
    all_tables: list[TableContent] = []
    all_images: list[ImageContent] = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        total_char_offset = 0

        for page_idx, page in enumerate(pdf.pages):
            page_number = page_idx + 1
            width = float(page.width)
            height = float(page.height)

            # 헤더/푸터 마진 제거
            header_footer_margin = 50
            top_margin = min(header_footer_margin, height * 0.1)
            bottom_margin = max(height - header_footer_margin, height * 0.9)

            if height > top_margin + (height * 0.1):
                try:
                    cropped = page.crop((0, top_margin, width, bottom_margin))
                except Exception:
                    cropped = page
            else:
                cropped = page

            # 텍스트 추출
            try:
                text = cropped.extract_text() or ""
            except Exception:
                text = page.extract_text() or ""

            # TextBlock 생성
            text_blocks: list[TextBlock] = []
            try:
                words = cropped.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=3)
                if words:
                    # 라인 그룹핑
                    lines: list[list[dict]] = []
                    current_line: list[dict] = [words[0]]
                    current_y = words[0]["top"]
                    for w in words[1:]:
                        if abs(w["top"] - current_y) <= 3.0:
                            current_line.append(w)
                        else:
                            lines.append(current_line)
                            current_line = [w]
                            current_y = w["top"]
                    lines.append(current_line)

                    running_offset = total_char_offset
                    for line_words in lines:
                        line_text = " ".join(w["text"] for w in line_words)
                        if not line_text.strip():
                            continue
                        bbox = [
                            float(line_words[0]["x0"]),
                            float(min(w["top"] for w in line_words)),
                            float(line_words[-1]["x1"]),
                            float(max(w["bottom"] for w in line_words)),
                        ]
                        text_blocks.append(TextBlock(
                            text=line_text,
                            start_char_offset=running_offset,
                            end_char_offset=running_offset + len(line_text),
                            bbox=bbox,
                        ))
                        running_offset += len(line_text) + 1
            except Exception:
                if text.strip():
                    text_blocks.append(TextBlock(
                        text=text,
                        start_char_offset=total_char_offset,
                        end_char_offset=total_char_offset + len(text),
                    ))

            # OCR 필요 여부
            ocr_needed = len(text.strip()) < 50

            # 표 추출
            page_tables: list[TableContent] = []
            try:
                found_tables = page.find_tables()
                if found_tables:
                    for t_idx, table_obj in enumerate(found_tables):
                        data = table_obj.extract()
                        if not data or len(data) < 2:
                            continue
                        headers = [
                            str(cell).replace("\n", " ").strip() if cell else ""
                            for cell in data[0]
                        ]
                        rows: list[list[str]] = []
                        for row in data[1:]:
                            rows.append([
                                str(cell).replace("\n", " ").strip() if cell else ""
                                for cell in row
                            ])
                        # Markdown 변환
                        md_lines = [
                            "| " + " | ".join(headers) + " |",
                            "| " + " | ".join("---" for _ in headers) + " |",
                        ]
                        for row in rows:
                            padded = row + [""] * max(0, len(headers) - len(row))
                            md_lines.append("| " + " | ".join(padded[:len(headers)]) + " |")
                        md = "\n".join(md_lines)

                        bbox_raw = table_obj.bbox
                        bbox = (
                            [float(bbox_raw[0]), float(bbox_raw[1]),
                             float(bbox_raw[2]), float(bbox_raw[3])]
                            if bbox_raw else None
                        )
                        page_tables.append(TableContent(
                            page_number=page_number,
                            table_index=t_idx,
                            headers=headers,
                            rows=rows,
                            markdown=md,
                            confidence=1.0,
                            bbox=bbox,
                        ))
            except Exception as exc:
                log.warning("table_extraction_failed", page=page_number, error=str(exc))

            all_tables.extend(page_tables)

            # 이미지 메타 수집
            page_images: list[ImageContent] = []
            try:
                if page.images:
                    for img_idx, img in enumerate(page.images):
                        bbox = [
                            float(img.get("x0", 0)),
                            float(img.get("top", 0)),
                            float(img.get("x1", 0)),
                            float(img.get("bottom", 0)),
                        ]
                        page_images.append(ImageContent(
                            page_number=page_number,
                            image_index=img_idx,
                            image_path="",
                            bbox=bbox,
                        ))
            except Exception:
                pass

            all_images.extend(page_images)

            pages.append(PageContent(
                page_number=page_number,
                text=text,
                text_blocks=text_blocks,
                tables=page_tables,
                images=page_images,
                layout_type="single",
                ocr_used=ocr_needed,
            ))
            total_char_offset += len(text)

    raw_text = "\n".join(p.text for p in pages)

    # 메타데이터
    metadata: dict[str, Any] = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            info = pdf.metadata or {}
            metadata["title"] = info.get("Title", "")
            metadata["author"] = info.get("Author", "")
            metadata["page_count"] = len(pdf.pages)
    except Exception:
        pass

    return ParseResult(
        raw_text=raw_text,
        pages=pages,
        tables=all_tables,
        images=all_images,
        metadata=metadata,
        source_file_path=pdf_path,
    )


# ---------------------------------------------------------------------------
# Stage 6: OCR fallback (no-op passthrough)
# ---------------------------------------------------------------------------
#
# 실제 OCR 폴백은 src/pipeline/parsers/ocr_engine.py 의 OCREngine 가 담당한다
# (PaddleOCR 1차 → 내부 vLLM Vision 2차). 여기서는 통계 로그만 남기고
# parse_result 를 그대로 반환한다.

def ocr_fallback_pages(parse_result: ParseResult, pdf_path: str) -> ParseResult:
    """텍스트가 부족한 페이지 통계만 남기는 pass-through (실제 OCR 은 OCREngine 에서)."""
    ocr_pages = sum(1 for p in parse_result.pages if p.ocr_used)
    if ocr_pages > 0:
        log.info("ocr_pages_detected", count=ocr_pages)
    return parse_result


# ---------------------------------------------------------------------------
# Stage 7: Structure analysis (heading detection)
# ---------------------------------------------------------------------------

_HEADING_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^\s*제\s*\d+\s*편"), 1),
    (re.compile(r"^\s*제\s*\d+\s*장"), 1),
    (re.compile(r"^\s*제\s*\d+\s*조"), 2),
    (re.compile(r"^\s*\d+\.\s+\S"), 3),
    (re.compile(r"^\s*[①-⑮]"), 4),
    (re.compile(r"^\s*[가-하]\.\s"), 4),
    (re.compile(r"^\s*Q[.:]\s"), 3),
    (re.compile(r"^#{1}\s+\S"), 1),
    (re.compile(r"^#{2}\s+\S"), 2),
    (re.compile(r"^#{3}\s+\S"), 3),
    # English heading patterns
    (re.compile(r"^\s*Chapter\s+\d+", re.IGNORECASE), 1),
    (re.compile(r"^\s*Section\s+\d+", re.IGNORECASE), 2),
    (re.compile(r"^\s*\d+\.\d+\s+\S"), 3),
    (re.compile(r"^\s*[A-Z][A-Z\s]{5,}$"), 2),  # ALL CAPS headings
]


def detect_heading(text: str) -> Optional[tuple[str, int]]:
    """텍스트가 제목이면 (제목, 레벨) 반환."""
    text = text.strip()
    if not text or len(text) > 100:
        return None
    if len(text) > 20 and text.endswith((".", ",")):
        return None
    for pattern, level in _HEADING_PATTERNS:
        if pattern.match(text):
            return (text, level)
    return None


def analyze_structure(parse_result: ParseResult) -> list[dict[str, Any]]:
    """문서 구조를 분석하여 헤딩 트리를 반환한다."""
    headings: list[dict[str, Any]] = []
    heading_stack: list[str] = []

    for page in parse_result.pages:
        for line in page.text.split("\n"):
            line = line.strip()
            if not line:
                continue
            result = detect_heading(line)
            if result:
                title, level = result
                # 스택 조정
                while len(heading_stack) >= level:
                    heading_stack.pop()
                heading_stack.append(title)
                headings.append({
                    "title": title,
                    "level": level,
                    "page": page.page_number,
                    "path": list(heading_stack),
                })

    return headings


# ---------------------------------------------------------------------------
# Stage 8: Difficulty assessment
# ---------------------------------------------------------------------------

def assess_difficulty(
    parse_result: ParseResult,
) -> tuple[ProcessingDifficulty, float, dict[str, float]]:
    """난이도 평가. difficulty.py 로직 인라인."""
    weights = {
        "table_density": 0.3,
        "image_density": 0.25,
        "layout_complexity": 0.2,
        "ocr_dependency": 0.15,
        "doc_size": 0.1,
    }

    factors: dict[str, float] = {}
    total_pages = max(len(parse_result.pages), 1)

    table_chars = sum(len(t.markdown) for t in parse_result.tables)
    total_chars = len(parse_result.raw_text) + table_chars
    factors["table_density"] = min(table_chars / max(total_chars, 1), 1.0)

    image_pages = len({img.page_number for img in parse_result.images})
    factors["image_density"] = min(image_pages / total_pages, 1.0)

    complex_pages = sum(1 for p in parse_result.pages if p.layout_type != "single")
    factors["layout_complexity"] = min(complex_pages / total_pages, 1.0)

    ocr_pages = sum(1 for p in parse_result.pages if p.ocr_used)
    factors["ocr_dependency"] = min(ocr_pages / total_pages, 1.0)

    factors["doc_size"] = min(total_pages / 100, 1.0)

    score = sum(factors[k] * weights[k] for k in weights)

    if score < 0.3:
        difficulty = ProcessingDifficulty.LOW
    elif score < 0.6:
        difficulty = ProcessingDifficulty.MEDIUM
    elif score < 0.8:
        difficulty = ProcessingDifficulty.HIGH
    else:
        difficulty = ProcessingDifficulty.CRITICAL

    return difficulty, round(score, 4), factors


# ---------------------------------------------------------------------------
# Stage 9-10: Chunking (text)
# ---------------------------------------------------------------------------

def chunk_text_pages(
    parse_result: ParseResult,
    difficulty: ProcessingDifficulty,
    config: ProcessingConfig,
    source_file_path: str,
) -> list[ChunkObject]:
    """텍스트 페이지를 청킹한다. 난이도에 따라 Semantic/Hierarchical 선택."""
    if difficulty in (ProcessingDifficulty.LOW, ProcessingDifficulty.MEDIUM):
        from src.pipeline.chunkers.semantic import SemanticChunker
        chunker = SemanticChunker(config)
    else:
        from src.pipeline.chunkers.hierarchical import HierarchicalChunker
        chunker = HierarchicalChunker(config)

    doc_id = str(uuid4())
    chunks = asyncio.run(
        chunker.chunk(
            parse_result.pages,
            source_file_path=source_file_path,
            document_id=doc_id,
        )
    )
    return chunks


# ---------------------------------------------------------------------------
# Stage 11: Table 3-layer chunking
# ---------------------------------------------------------------------------

def chunk_tables(
    tables: list[TableContent],
    config: ProcessingConfig,
    source_file_path: str,
) -> list[ChunkObject]:
    """표를 3중 레이어로 청킹한다."""
    from src.pipeline.chunkers.table_chunker import TableChunker
    chunker = TableChunker(config)
    all_chunks: list[ChunkObject] = []
    doc_id = str(uuid4())

    for table in tables:
        table_title = _guess_table_title(table)
        chunks = asyncio.run(
            chunker.chunk(
                table,
                document_id=doc_id,
                source_file_path=source_file_path,
                table_title=table_title,
            )
        )
        all_chunks.extend(chunks)

    return all_chunks


def _guess_table_title(table: TableContent) -> str:
    """표 제목을 헤더에서 추정한다."""
    if table.headers:
        return f"Table (p{table.page_number}, #{table.table_index})"
    return f"Table p{table.page_number}"


# ---------------------------------------------------------------------------
# Stage 12: BGE-M3 Embedding
# ---------------------------------------------------------------------------

def embed_chunks(chunks: list[ChunkObject], batch_size: int = 8) -> list[ChunkObject]:
    """BGE-M3 로 청크를 임베딩한다."""
    if not chunks:
        return chunks

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder

    embedder = BGEM3Embedder(
        model_name=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
        device=os.environ.get("EMBEDDING_DEVICE", "cpu"),
        use_fp16=False,  # CPU 에서는 fp16 비활성
        max_length=512,
    )

    texts = [c.content for c in chunks]

    # 배치 처리
    results = asyncio.run(embedder.embed_batch(texts, batch_size=batch_size))

    for chunk, emb in zip(chunks, results):
        chunk.dense_vector = emb.dense
        chunk.sparse_vector = emb.sparse

    return chunks


# ---------------------------------------------------------------------------
# Stage 13: Qdrant upsert
# ---------------------------------------------------------------------------

def upsert_to_qdrant(
    chunks: list[ChunkObject],
    collection_name: str,
    qdrant_url: str = "",
) -> int:
    """청크를 Qdrant 에 업서트한다."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        SparseIndexParams,
        SparseVectorParams,
        SparseVector,
        VectorParams,
    )

    url = qdrant_url or os.environ.get("QDRANT_URL", "http://localhost:3520")
    client = QdrantClient(url=url)

    # 컬렉션 생성 (없으면)
    try:
        client.delete_collection(collection_name)
        log.info("qdrant_collection_deleted", collection=collection_name)
    except Exception:
        pass

    # Dense 벡터 차원 확인
    dim = 1024
    if chunks and chunks[0].dense_vector:
        dim = len(chunks[0].dense_vector)

    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "dense": VectorParams(size=dim, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
            ),
        },
    )
    log.info("qdrant_collection_created", collection=collection_name, dim=dim)

    # PointStruct 빌드 및 업서트 (배치)
    batch_size = 100
    total_stored = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        points: list[PointStruct] = []

        for chunk in batch:
            if not chunk.dense_vector:
                continue

            payload: dict[str, Any] = {
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "strategy": chunk.strategy.value,
                "token_count": chunk.token_count,
                "chunk_hash": chunk.chunk_hash,
                "document_id": str(chunk.document_id),
            }

            # source_location
            sl = chunk.source_location
            if sl:
                payload["source_location"] = {
                    "file_path": sl.file_path,
                    "page_number": sl.page_number,
                    "heading_path": sl.heading_path,
                    "table_index": sl.table_index,
                    "bbox": sl.bbox,
                }

            # metadata
            if chunk.metadata:
                payload["metadata"] = chunk.metadata

            vectors: dict[str, Any] = {"dense": chunk.dense_vector}
            if chunk.sparse_vector:
                sparse_indices = list(chunk.sparse_vector.keys())
                sparse_values = list(chunk.sparse_vector.values())
                vectors["sparse"] = SparseVector(
                    indices=sparse_indices, values=sparse_values
                )

            points.append(PointStruct(
                id=str(chunk.id),
                vector=vectors,
                payload=payload,
            ))

        if points:
            client.upsert(collection_name=collection_name, points=points)
            total_stored += len(points)

    log.info("qdrant_upserted", collection=collection_name, count=total_stored)
    return total_stored


# ---------------------------------------------------------------------------
# Search test
# ---------------------------------------------------------------------------

def search_test(
    queries: list[str],
    collection_name: str,
    qdrant_url: str = "",
) -> list[dict[str, Any]]:
    """Qdrant 검색 테스트."""
    from qdrant_client import QdrantClient
    from src.pipeline.embedders.bge_m3 import BGEM3Embedder

    url = qdrant_url or os.environ.get("QDRANT_URL", "http://localhost:3520")
    client = QdrantClient(url=url)

    embedder = BGEM3Embedder(
        model_name=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
        device=os.environ.get("EMBEDDING_DEVICE", "cpu"),
        use_fp16=False,
        max_length=512,
    )

    results_list: list[dict[str, Any]] = []
    for query in queries:
        emb = asyncio.run(embedder.embed_single(query))
        hits = client.search(
            collection_name=collection_name,
            query_vector=("dense", emb.dense),
            limit=3,
        )
        result = {
            "query": query,
            "hits": [],
        }
        for hit in hits:
            payload = hit.payload or {}
            result["hits"].append({
                "score": round(hit.score, 4),
                "content_preview": (payload.get("content", ""))[:120],
                "page": payload.get("source_location", {}).get("page_number"),
                "strategy": payload.get("strategy", ""),
            })
        results_list.append(result)

    return results_list


# ===========================================================================
# Main pipeline orchestrator
# ===========================================================================

def process_document(file_path: str, collection_name: str) -> dict[str, Any]:
    """단일 문서를 전체 파이프라인으로 처리한다."""
    timer = StageTimer()
    result: dict[str, Any] = {
        "file": file_path,
        "format": "",
        "pages": 0,
        "tables_found": 0,
        "images_found": 0,
        "chunks_created": 0,
        "vectors_stored": 0,
        "difficulty": "",
        "difficulty_score": 0.0,
        "stages": [],
    }

    # --- Stage 1: Format detection ---
    timer.start("1_format_detection")
    fmt = detect_format(file_path)
    result["format"] = fmt
    entry = timer.stop()
    print(f"  [Stage 1] Format: {fmt} ({entry['elapsed_sec']}s)")

    # --- Stage 2: Convert if needed ---
    timer.start("2_conversion")
    pdf_path = convert_to_pdf(file_path, fmt)
    entry = timer.stop()
    if pdf_path != file_path:
        print(f"  [Stage 2] Converted to: {pdf_path} ({entry['elapsed_sec']}s)")
    else:
        print(f"  [Stage 2] No conversion needed ({entry['elapsed_sec']}s)")

    # --- Stage 3-5: Extract text, images, tables ---
    timer.start("3-5_extraction")
    parse_result = extract_pdf_content(pdf_path)
    entry = timer.stop()
    result["pages"] = len(parse_result.pages)
    result["tables_found"] = len(parse_result.tables)
    result["images_found"] = len(parse_result.images)
    print(f"  [Stage 3-5] Extracted: {result['pages']} pages, "
          f"{result['tables_found']} tables, {result['images_found']} images "
          f"({entry['elapsed_sec']}s)")

    # Per-page summary
    for page in parse_result.pages:
        text_len = len(page.text)
        n_tables = len(page.tables)
        n_images = len(page.images)
        ocr_flag = " [OCR_NEEDED]" if page.ocr_used else ""
        print(f"    Page {page.page_number:2d}: {text_len:5d} chars, "
              f"{n_tables} tables, {n_images} images{ocr_flag}")

    # Tables detail
    if parse_result.tables:
        print(f"\n  Tables found:")
        for t in parse_result.tables:
            print(f"    Page {t.page_number}, Table #{t.table_index}: "
                  f"{len(t.rows)} rows x {len(t.headers)} cols "
                  f"| Headers: {t.headers[:5]}")

    # --- Stage 6: OCR fallback ---
    timer.start("6_ocr_fallback")
    parse_result = ocr_fallback_pages(parse_result, pdf_path)
    entry = timer.stop()
    print(f"  [Stage 6] OCR fallback ({entry['elapsed_sec']}s)")

    # --- Stage 7: Structure analysis ---
    timer.start("7_structure_analysis")
    headings = analyze_structure(parse_result)
    entry = timer.stop()
    print(f"  [Stage 7] Structure: {len(headings)} headings detected ({entry['elapsed_sec']}s)")
    for h in headings[:10]:
        indent = "  " * h["level"]
        print(f"    {indent}L{h['level']}: {h['title'][:60]} (p{h['page']})")
    if len(headings) > 10:
        print(f"    ... and {len(headings) - 10} more")

    # --- Stage 8: Difficulty assessment ---
    timer.start("8_difficulty")
    difficulty, score, factors = assess_difficulty(parse_result)
    entry = timer.stop()
    result["difficulty"] = difficulty.value
    result["difficulty_score"] = score
    print(f"  [Stage 8] Difficulty: {difficulty.value} (score={score}) ({entry['elapsed_sec']}s)")
    for k, v in factors.items():
        print(f"    {k}: {v:.4f}")

    # --- Stage 9-10: Text chunking ---
    timer.start("9-10_text_chunking")
    config = ProcessingConfig(
        chunk_size=500,
        chunk_overlap=50,
        min_chunk_size=50,
    )
    text_chunks = chunk_text_pages(parse_result, difficulty, config, file_path)
    entry = timer.stop()
    print(f"  [Stage 9-10] Text chunks: {len(text_chunks)} ({entry['elapsed_sec']}s)")

    # --- Stage 11: Table chunking ---
    timer.start("11_table_chunking")
    table_chunks = chunk_tables(parse_result.tables, config, file_path)
    entry = timer.stop()

    # Count by layer
    layer_counts: dict[str, int] = {}
    for c in table_chunks:
        layer = c.metadata.get("layer", "unknown")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    print(f"  [Stage 11] Table chunks: {len(table_chunks)} ({entry['elapsed_sec']}s)")
    for layer, count in sorted(layer_counts.items()):
        print(f"    {layer}: {count}")

    # Combine all chunks
    all_chunks = text_chunks + table_chunks
    for i, c in enumerate(all_chunks):
        c.chunk_index = i

    result["chunks_created"] = len(all_chunks)
    result["chunk_breakdown"] = {
        "text": len(text_chunks),
        **layer_counts,
    }

    print(f"\n  Total chunks: {len(all_chunks)}")
    print(f"    Text chunks: {len(text_chunks)}")
    for layer, count in sorted(layer_counts.items()):
        print(f"    {layer}: {count}")

    # --- Stage 12: Embedding ---
    timer.start("12_embedding")
    all_chunks = embed_chunks(all_chunks, batch_size=8)
    entry = timer.stop()
    embedded_count = sum(1 for c in all_chunks if c.dense_vector)
    print(f"  [Stage 12] Embedded: {embedded_count}/{len(all_chunks)} chunks "
          f"({entry['elapsed_sec']}s)")

    # --- Stage 13: Qdrant upsert ---
    timer.start("13_qdrant_upsert")
    try:
        stored = upsert_to_qdrant(all_chunks, collection_name)
        result["vectors_stored"] = stored
        entry = timer.stop()
        print(f"  [Stage 13] Qdrant: {stored} vectors stored ({entry['elapsed_sec']}s)")
    except Exception as exc:
        entry = timer.stop()
        print(f"  [Stage 13] Qdrant ERROR: {exc} ({entry['elapsed_sec']}s)")
        result["vectors_stored"] = 0

    result["stages"] = timer.stages
    return result


# ===========================================================================
# CLI entry point
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="AICM Document Pipeline Runner")
    parser.add_argument("file", nargs="?", help="Path to document file")
    parser.add_argument("--collection", default="aicm_realtest_documents_chunks",
                        help="Qdrant collection name")
    parser.add_argument("--run-test", action="store_true",
                        help="Run with test documents")
    parser.add_argument("--search-queries", nargs="*",
                        help="Search queries to test after processing")
    args = parser.parse_args()

    if args.run_test:
        # 테스트 모드: 두 개의 테스트 문서 처리
        test_files = []

        pdf1 = "/home/Ricky-Dev/KMS-Input-Pipeline/HPG User manual.pdf"
        if os.path.exists(pdf1):
            test_files.append(pdf1)
        else:
            print(f"WARNING: Test file not found: {pdf1}")

        pdf2 = "/tmp/반도체공정순서도.pdf"
        if os.path.exists(pdf2):
            test_files.append(pdf2)
        else:
            # DOC 원본 확인
            doc2 = "/tmp/반도체공정순서도.doc"
            if os.path.exists(doc2):
                test_files.append(doc2)
            else:
                print(f"WARNING: Test file not found: {pdf2} or {doc2}")

        if not test_files:
            print("ERROR: No test files found!")
            sys.exit(1)

        collection = args.collection
        all_results = []

        for fpath in test_files:
            print(f"\n{'='*80}")
            print(f"Processing: {fpath}")
            print(f"Collection: {collection}")
            print(f"{'='*80}")

            result = process_document(fpath, collection)
            all_results.append(result)

            print(f"\n--- Result Summary ---")
            print(json.dumps({
                k: v for k, v in result.items() if k != "stages"
            }, indent=2, ensure_ascii=False))

        # 검색 테스트
        print(f"\n{'='*80}")
        print(f"SEARCH TESTS")
        print(f"{'='*80}")

        # 문서별 검색 쿼리
        queries_per_doc = [
            # HPG User manual queries (English)
            [
                "installation instructions",
                "system requirements",
                "troubleshooting",
                "configuration settings",
                "user interface",
            ],
            # 반도체공정순서도 queries (Korean)
            [
                "반도체 공정",
                "웨이퍼 처리",
                "식각 공정",
                "포토리소그래피",
                "산화 공정",
            ],
        ]

        for i, fpath in enumerate(test_files):
            if i < len(queries_per_doc):
                queries = queries_per_doc[i]
            else:
                queries = ["test query"]

            print(f"\n--- Search: {os.path.basename(fpath)} ---")
            search_results = search_test(queries, collection)
            for sr in search_results:
                print(f"\n  Q: {sr['query']}")
                for hit in sr["hits"]:
                    print(f"    [{hit['score']:.4f}] (p{hit['page']}, {hit['strategy']}) "
                          f"{hit['content_preview'][:80]}...")

        # 총 요약
        print(f"\n{'='*80}")
        print(f"PIPELINE COMPLETE")
        print(f"{'='*80}")
        for r in all_results:
            total_time = sum(s["elapsed_sec"] for s in r["stages"])
            print(f"  {os.path.basename(r['file'])}: "
                  f"{r['pages']}p, {r['chunks_created']} chunks, "
                  f"{r['vectors_stored']} vectors, {total_time:.1f}s total")

    elif args.file:
        # 단일 파일 처리
        if not os.path.exists(args.file):
            print(f"ERROR: File not found: {args.file}")
            sys.exit(1)

        print(f"\n{'='*80}")
        print(f"Processing: {args.file}")
        print(f"Collection: {args.collection}")
        print(f"{'='*80}")

        result = process_document(args.file, args.collection)

        print(f"\n--- Result Summary ---")
        print(json.dumps({
            k: v for k, v in result.items() if k != "stages"
        }, indent=2, ensure_ascii=False))

        # 검색 테스트
        if args.search_queries:
            print(f"\n--- Search Test ---")
            search_results = search_test(args.search_queries, args.collection)
            for sr in search_results:
                print(f"\n  Q: {sr['query']}")
                for hit in sr["hits"]:
                    print(f"    [{hit['score']:.4f}] {hit['content_preview'][:100]}...")

        total_time = sum(s["elapsed_sec"] for s in result["stages"])
        print(f"\nTotal time: {total_time:.1f}s")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

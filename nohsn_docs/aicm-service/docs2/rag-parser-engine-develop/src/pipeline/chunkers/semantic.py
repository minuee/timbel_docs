"""Semantic 청커 -- KSS 한국어 문장 분리 + 코사인 유사도 경계 감지.

specs/02 4.1 알고리즘을 구현한다.
chunk_service/pipeline/stages/chunk_process.py 의 병합 전략을 참고하되,
문장 임베딩 기반 유사도 경계 감지를 추가하였다.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Optional
from uuid import UUID, uuid4

import numpy as np

from src.common.logging import get_logger
from src.pipeline.models.document import ChunkObject, ChunkStrategy, ProcessingConfig, SourceLocation
from src.pipeline.models.parse_result import PageContent, TextBlock
from src.pipeline.chunkers.base import BaseChunker

log = get_logger(__name__)

# 코사인 유사도 임계값 -- 이 값 이하에서 청크 경계를 생성
_DEFAULT_SIMILARITY_THRESHOLD = 0.5


class SemanticChunker(BaseChunker):
    """KSS 기반 문장 분리 + 코사인 유사도 경계 감지 청커.

    알고리즘
    --------
    1. 전체 페이지 텍스트를 KSS 로 문장 분리
    2. 각 문장의 경량 임베딩 계산 (문장 분할 목적이므로 TF-IDF 기반)
    3. 인접 문장 간 코사인 유사도 계산
    4. 유사도가 threshold 이하인 지점에서 분할
    5. min/max 토큰 수 제약 조건으로 병합/분할
    6. source_location 을 원본 TextBlock 에서 상속
    """

    def __init__(
        self,
        config: ProcessingConfig,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        embedder: Optional[object] = None,
    ) -> None:
        super().__init__(config)
        self.similarity_threshold = similarity_threshold
        self._embedder = embedder  # BGEM3Embedder 인스턴스 (옵션)

    async def chunk(
        self,
        pages: list[PageContent],
        *,
        source_file_path: str = "",
        source_file_url: str = "",
        document_id: str = "",
    ) -> list[ChunkObject]:
        """페이지 목록 -> 청크 목록."""
        # 1) 문장 분리 + source 매핑
        sentences, sentence_sources = self._split_sentences(
            pages, source_file_path, source_file_url
        )
        if not sentences:
            return []

        # 2) 유사도 기반 분할 지점 결정
        split_points = await self._find_split_points(sentences)

        # 3) 청크 빌드 (토큰 제약 적용)
        doc_uuid = UUID(document_id) if document_id else uuid4()
        chunks = self._build_chunks(sentences, sentence_sources, split_points, doc_uuid)

        log.info(
            "semantic_chunking_complete",
            sentences=len(sentences),
            chunks=len(chunks),
            split_points=len(split_points),
        )
        return chunks

    # ------------------------------------------------------------------
    # 문장 분리
    # ------------------------------------------------------------------
    def _split_sentences(
        self,
        pages: list[PageContent],
        source_file_path: str,
        source_file_url: str = "",
    ) -> tuple[list[str], list[SourceLocation]]:
        """KSS 로 문장 분리하고 각 문장의 source_location 을 추적한다."""
        try:
            import kss
        except ImportError:
            log.warning("kss_not_installed_fallback_to_newline_split")
            return self._fallback_split(pages, source_file_path, source_file_url)

        sentences: list[str] = []
        sources: list[SourceLocation] = []

        for page in pages:
            if not page.text.strip():
                continue

            page_sentences = kss.split_sentences(page.text)

            for sent in page_sentences:
                sent = sent.strip()
                if not sent:
                    continue
                sentences.append(sent)

                # TextBlock 에서 가장 가까운 source_location 을 찾는다
                sl = self._find_source_location(sent, page, source_file_path, source_file_url)
                sources.append(sl)

        return sentences, sources

    def _fallback_split(
        self,
        pages: list[PageContent],
        source_file_path: str,
        source_file_url: str = "",
    ) -> tuple[list[str], list[SourceLocation]]:
        """KSS 가 없을 때 줄바꿈 기반 분리."""
        sentences: list[str] = []
        sources: list[SourceLocation] = []

        for page in pages:
            for line in page.text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                sentences.append(line)
                sources.append(
                    SourceLocation(
                        file_path=source_file_path,
                        file_url=source_file_url or None,
                        page_number=page.page_number,
                    )
                )
        return sentences, sources

    @staticmethod
    def _find_source_location(
        sentence: str,
        page: PageContent,
        source_file_path: str,
        source_file_url: str = "",
    ) -> SourceLocation:
        """문장에 가장 근접한 TextBlock 의 위치 정보를 상속한다."""
        best_block: Optional[TextBlock] = None
        best_overlap = 0

        for tb in page.text_blocks:
            # 단순 문자열 포함 비율로 근접도 판단
            overlap = len(set(sentence) & set(tb.text))
            if overlap > best_overlap:
                best_overlap = overlap
                best_block = tb

        if best_block:
            return SourceLocation(
                file_path=source_file_path,
                file_url=source_file_url or None,
                page_number=page.page_number,
                start_char_offset=best_block.start_char_offset,
                end_char_offset=best_block.end_char_offset,
                bbox=best_block.bbox,
                paragraph_index=best_block.paragraph_index,
            )

        return SourceLocation(
            file_path=source_file_path,
            file_url=source_file_url or None,
            page_number=page.page_number,
        )

    # ------------------------------------------------------------------
    # 유사도 분석
    # ------------------------------------------------------------------
    async def _find_split_points(self, sentences: list[str]) -> list[int]:
        """인접 문장 간 코사인 유사도를 계산하여 분할 지점을 결정한다."""
        if len(sentences) <= 1:
            return []

        # BGE-M3 임베더가 있으면 사용, 없으면 TF-IDF 기반 경량 벡터
        if self._embedder is not None:
            embeddings = await self._embed_with_model(sentences)
        else:
            embeddings = self._tfidf_embeddings(sentences)

        if embeddings is None or len(embeddings) < 2:
            return []

        # 인접 코사인 유사도
        similarities: list[float] = []
        for i in range(len(embeddings) - 1):
            sim = self._cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)

        # 임계값 이하인 지점 = 분할 경계
        split_points = [
            i + 1 for i, sim in enumerate(similarities) if sim < self.similarity_threshold
        ]
        return split_points

    async def _embed_with_model(self, sentences: list[str]) -> Optional[np.ndarray]:
        """BGE-M3 임베더로 문장 벡터를 계산한다."""
        try:
            from src.pipeline.embedders.bge_m3 import BGEM3Embedder

            embedder: BGEM3Embedder = self._embedder  # type: ignore[assignment]
            results = await embedder.embed_batch(sentences)
            return np.array([r.dense for r in results])
        except Exception as exc:
            log.warning("model_embedding_failed_fallback_tfidf", error=str(exc))
            return None

    @staticmethod
    def _tfidf_embeddings(sentences: list[str]) -> np.ndarray:
        """경량 TF-IDF 기반 문장 벡터. 외부 모델 없이도 동작하도록 한다."""
        # 전체 어휘 수집
        vocab: dict[str, int] = {}
        tokenized: list[list[str]] = []

        for sent in sentences:
            tokens = sent.split()
            tokenized.append(tokens)
            for t in tokens:
                if t not in vocab:
                    vocab[t] = len(vocab)

        if not vocab:
            return np.zeros((len(sentences), 1))

        # TF 행렬
        matrix = np.zeros((len(sentences), len(vocab)))
        for i, tokens in enumerate(tokenized):
            for t in tokens:
                matrix[i, vocab[t]] += 1

        # L2 정규화
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        matrix = matrix / norms

        return matrix

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    # ------------------------------------------------------------------
    # 청크 빌드
    # ------------------------------------------------------------------
    def _build_chunks(
        self,
        sentences: list[str],
        sources: list[SourceLocation],
        split_points: list[int],
        document_id: UUID,
    ) -> list[ChunkObject]:
        """분할 지점 기준으로 문장을 묶어 청크를 생성한다."""
        if not sentences:
            return []

        # 분할 지점으로 그룹 생성
        groups: list[list[int]] = []
        prev = 0
        for sp in sorted(set(split_points)):
            if sp > prev:
                groups.append(list(range(prev, sp)))
            prev = sp
        if prev < len(sentences):
            groups.append(list(range(prev, len(sentences))))

        # 토큰 제약 적용: 너무 작은 그룹은 다음과 병합
        merged_groups = self._merge_small_groups(groups, sentences)

        chunks: list[ChunkObject] = []
        for chunk_idx, group in enumerate(merged_groups):
            text = "\n".join(sentences[i] for i in group)
            if not text.strip():
                continue

            # 너무 큰 청크는 강제 분할
            sub_texts = self._force_split_if_needed(text)

            for sub_idx, sub_text in enumerate(sub_texts):
                chunk_hash = hashlib.sha256(sub_text.encode("utf-8")).hexdigest()
                token_count = len(sub_text)  # 문자 수 기반 (실제 토큰화는 임베딩 시)

                # source_location: 그룹 내 첫/마지막 문장의 위치 병합
                first_src = sources[group[0]] if group else SourceLocation(file_path="")
                last_src = sources[group[-1]] if group else first_src

                sl = SourceLocation(
                    file_path=first_src.file_path,
                    file_url=first_src.file_url,
                    page_number=first_src.page_number,
                    page_range=(
                        [first_src.page_number, last_src.page_number]
                        if first_src.page_number and last_src.page_number
                        and first_src.page_number != last_src.page_number
                        else None
                    ),
                    start_char_offset=first_src.start_char_offset,
                    end_char_offset=last_src.end_char_offset,
                    bbox=first_src.bbox,
                    paragraph_index=first_src.paragraph_index,
                    # D46-v3 §4 — heading_path 상속 누락 fix.
                    # 이전: 무조건 [] → retrieval (qdrant_dense / es_keyword) 의
                    # source_location.heading_path 가 0% 채움.
                    # 이후: first_src 의 heading_path 를 그대로 상속.
                    heading_path=list(first_src.heading_path or []),
                )

                global_idx = chunk_idx * len(sub_texts) + sub_idx
                chunks.append(
                    ChunkObject(
                        id=uuid4(),
                        document_id=document_id,
                        content=sub_text,
                        chunk_index=global_idx,
                        chunk_hash=chunk_hash,
                        token_count=token_count,
                        strategy=ChunkStrategy.SEMANTIC,
                        source_location=sl,
                    )
                )

        # chunk_index 재정렬
        for i, c in enumerate(chunks):
            c.chunk_index = i

        return chunks

    def _merge_small_groups(
        self,
        groups: list[list[int]],
        sentences: list[str],
    ) -> list[list[int]]:
        """min_tokens 미만인 그룹을 인접 그룹과 병합한다."""
        if not groups:
            return groups

        merged: list[list[int]] = [groups[0]]
        for g in groups[1:]:
            prev_text = " ".join(sentences[i] for i in merged[-1])
            curr_text = " ".join(sentences[i] for i in g)

            if len(prev_text) < self.min_tokens:
                merged[-1].extend(g)
            elif len(curr_text) < self.min_tokens:
                merged[-1].extend(g)
            else:
                merged.append(g)

        return merged

    def _force_split_if_needed(self, text: str) -> list[str]:
        """max_tokens 초과 시 강제 분할한다."""
        if len(text) <= self.max_tokens:
            return [text]

        parts: list[str] = []
        while len(text) > self.max_tokens:
            # 최대 크기 지점에서 가장 가까운 줄바꿈 또는 마침표에서 분할
            cut = self.max_tokens
            for sep in ("\n", ". ", ", ", " "):
                pos = text.rfind(sep, 0, cut)
                if pos > self.min_tokens:
                    cut = pos + len(sep)
                    break

            parts.append(text[:cut].strip())
            # 오버랩 적용
            overlap_start = max(0, cut - self.overlap)
            text = text[overlap_start:]

        if text.strip():
            parts.append(text.strip())

        return parts

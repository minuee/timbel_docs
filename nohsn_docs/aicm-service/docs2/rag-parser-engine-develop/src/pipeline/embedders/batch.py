"""배치 임베딩 프로세서 -- 청크 목록을 배치 단위로 임베딩하고 결과를 부착.

Phase 3: 동적 배치 크기 조정 + OOM 자동 폴백.
"""

from __future__ import annotations

from src.common.config import settings
from src.common.logging import get_logger
from src.pipeline.embedders.bge_m3 import BGEM3Embedder, EmbeddingResult
from src.pipeline.metrics import PIPELINE_METRICS
from src.pipeline.models.document import ChunkObject

log = get_logger(__name__)

# OOM 시 배치 크기 축소 비율
_OOM_SHRINK_FACTOR = 0.5
_MIN_BATCH_SIZE = 1


class BatchEmbeddingProcessor:
    """청크 목록을 설정된 배치 크기로 나누어 임베딩하고 결과를 ChunkObject 에 부착한다.

    Phase 3 개선:
    - GPU 메모리 기반 동적 배치 크기 결정
    - OOM 발생 시 자동으로 배치 크기를 절반으로 줄여 재시도
    """

    def __init__(
        self,
        embedder: BGEM3Embedder | None = None,
        batch_size: int = 0,
    ) -> None:
        self._embedder = embedder or BGEM3Embedder()
        self._batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self._effective_batch_size = self._batch_size

    def _estimate_batch_size_from_gpu(self) -> int | None:
        """GPU 가용 메모리를 기반으로 적정 배치 크기를 추정한다.

        Returns
        -------
        int | None
            추정된 배치 크기. GPU 가 없거나 확인 실패 시 None.
        """
        try:
            import torch

            if not torch.cuda.is_available():
                return None

            free_memory_mb = torch.cuda.mem_get_info()[0] / (1024 * 1024)

            # 대략적 추정: BGE-M3 기준 1 텍스트 당 ~10MB GPU 메모리
            # 안전 마진 70% 적용
            estimated = int((free_memory_mb * 0.7) / 10)
            estimated = max(_MIN_BATCH_SIZE, min(estimated, 256))

            log.debug(
                "gpu_batch_size_estimated",
                free_memory_mb=round(free_memory_mb, 1),
                estimated_batch_size=estimated,
            )
            return estimated

        except ImportError:
            return None
        except Exception as exc:
            log.debug("gpu_memory_check_failed", error=str(exc))
            return None

    async def embed_chunks(self, chunks: list[ChunkObject]) -> list[ChunkObject]:
        """청크 목록을 임베딩하여 dense_vector / sparse_vector 를 채운다.

        이미 임베딩된 청크(dense_vector 가 존재)는 건너뛴다.
        OOM 발생 시 배치 크기를 줄여 자동 재시도한다.
        """
        to_embed: list[tuple[int, ChunkObject]] = []
        for idx, chunk in enumerate(chunks):
            if chunk.dense_vector is None:
                to_embed.append((idx, chunk))

        if not to_embed:
            log.info("all_chunks_already_embedded", total=len(chunks))
            return chunks

        # GPU 메모리 기반 동적 배치 크기 결정
        gpu_batch_size = self._estimate_batch_size_from_gpu()
        if gpu_batch_size is not None:
            self._effective_batch_size = min(self._batch_size, gpu_batch_size)
            log.info(
                "batch_size_adjusted",
                configured=self._batch_size,
                effective=self._effective_batch_size,
            )
        else:
            self._effective_batch_size = self._batch_size

        texts = [chunk.content for _, chunk in to_embed]
        total = len(texts)
        embedded_count = 0
        batch_size = self._effective_batch_size

        batch_start = 0
        while batch_start < total:
            batch_end = min(batch_start + batch_size, total)
            batch_texts = texts[batch_start:batch_end]

            try:
                results: list[EmbeddingResult] = await self._embedder.embed_batch(
                    batch_texts, batch_size=batch_size
                )

                for j, result in enumerate(results):
                    orig_idx = to_embed[batch_start + j][0]
                    chunks[orig_idx].dense_vector = result.dense
                    chunks[orig_idx].sparse_vector = result.sparse

                embedded_count += len(results)

                # 메트릭 기록
                PIPELINE_METRICS.embedding_batch_size.observe(len(batch_texts))

                log.debug(
                    "batch_embedded",
                    batch_start=batch_start,
                    batch_size=len(batch_texts),
                    progress=f"{embedded_count}/{total}",
                )

                batch_start = batch_end

            except (RuntimeError, Exception) as exc:
                # OOM 또는 CUDA 관련 에러 감지
                error_msg = str(exc).lower()
                is_oom = (
                    "out of memory" in error_msg
                    or "cuda" in error_msg
                    or "oom" in error_msg
                )

                if is_oom and batch_size > _MIN_BATCH_SIZE:
                    new_batch_size = max(
                        _MIN_BATCH_SIZE, int(batch_size * _OOM_SHRINK_FACTOR)
                    )
                    log.warning(
                        "oom_detected_reducing_batch_size",
                        current_batch_size=batch_size,
                        new_batch_size=new_batch_size,
                        error=str(exc),
                    )
                    batch_size = new_batch_size

                    # GPU 캐시 클리어 시도
                    try:
                        import torch

                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass

                    # 같은 batch_start 에서 재시도 (배치 크기만 줄임)
                    continue
                else:
                    # OOM 이 아니거나 배치 크기가 이미 최소 -> 에러 전파
                    raise

        log.info("batch_embedding_complete", total_chunks=total, embedded=embedded_count)
        return chunks

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        """텍스트 배열을 직접 임베딩한다. 블럭 파이프라인용."""
        if not texts:
            return []

        gpu_batch_size = self._estimate_batch_size_from_gpu()
        batch_size = gpu_batch_size or self._batch_size

        all_results: list[EmbeddingResult] = []
        i = 0
        while i < len(texts):
            batch = texts[i : i + batch_size]
            try:
                results = await self._embedder.embed_batch(batch, batch_size=batch_size)
                all_results.extend(results)
                i += len(batch)
            except (RuntimeError, Exception) as exc:
                if ("out of memory" in str(exc).lower() or "cuda" in str(exc).lower()) and batch_size > _MIN_BATCH_SIZE:
                    batch_size = max(_MIN_BATCH_SIZE, int(batch_size * _OOM_SHRINK_FACTOR))
                    log.warning("embed_texts_oom_reducing", new_size=batch_size)
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass
                else:
                    raise

        log.info("embed_texts_complete", total=len(texts), results=len(all_results))
        return all_results

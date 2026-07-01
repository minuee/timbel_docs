from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


class EmbedBatcher:
    """동시 단일텍스트 /embed 요청을 짧은 윈도로 모아 1회 encode로 처리하는 동적 배처.

    predict_fn(texts: list[str]) -> dict (동기; BGEM3FlagModel.encode 래핑,
    keys dense_vecs/lexical_weights). submit(text)로 텍스트 등록 후 그 요청 몫의
    (dense_vec, lexical_weights)를 await. encode는 단일 소비 루프에서 1개씩 직렬
    실행 -> 동시 encode 경합 제거(단일 GPU 유리).
    """

    def __init__(
        self,
        predict_fn: Callable[[list], dict],
        max_batch_texts: int = 32,
        batch_wait_ms: int = 6,
        max_queue: int = 1000,
    ) -> None:
        self._predict_fn = predict_fn
        self._max_batch_texts = max_batch_texts
        self._batch_wait_s = batch_wait_ms / 1000.0
        self._max_queue = max_queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def submit(self, text: str) -> tuple:
        if self._queue.qsize() >= self._max_queue:
            raise RuntimeError("embed batcher queue overflow")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((text, fut))
        return await fut

    async def _run_loop(self) -> None:
        while True:
            batch: list = []
            try:
                text0, fut0 = await self._queue.get()
                batch = [(text0, fut0)]
                deadline = time.monotonic() + self._batch_wait_s
                # 윈도 내 추가 수집(큐에 있으면 즉시, 없으면 잠깐 대기). soft cap.
                while len(batch) < self._max_batch_texts:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        text_i, fut_i = await asyncio.wait_for(
                            self._queue.get(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        break
                    batch.append((text_i, fut_i))

                texts = [t for t, _ in batch]
                try:
                    out = await asyncio.to_thread(self._predict_fn, texts)
                except Exception as exc:  # noqa: BLE001 -- 배치 실패는 future로 전파(폴백)
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(exc)
                    continue

                dense_vecs = out.get("dense_vecs")
                if dense_vecs is None:
                    dense_vecs = []
                lexical_weights = out.get("lexical_weights")
                if lexical_weights is None:
                    lexical_weights = []
                for i, (_, fut) in enumerate(batch):
                    if not fut.done():
                        dv = dense_vecs[i] if i < len(dense_vecs) else None
                        lw = lexical_weights[i] if i < len(lexical_weights) else {}
                        fut.set_result((dv, lw))
            except Exception:  # noqa: BLE001 -- 루프 보호 + 미완료 future 전파(hang 차단)
                log.exception("embed batcher run loop error")
                for _, fut in batch:
                    if not fut.done():
                        fut.set_exception(RuntimeError("embed batcher internal error"))
                continue

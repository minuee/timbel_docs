from __future__ import annotations

import asyncio
import time
from typing import Callable


class RerankBatcher:
    """동시 /rerank 요청을 짧은 윈도로 모아 1회 predict로 처리하는 동적 배처.

    predict_fn(all_pairs: list[list[str]]) -> list[float] (동기; CrossEncoder.predict 래핑).
    submit(pairs)로 요청별 pairs 등록 후 그 요청 몫의 score 리스트를 await.
    predict는 단일 소비 루프에서 1개씩 직렬 실행 -> 동시 predict 경합 제거(단일 GPU 유리).
    """

    def __init__(
        self,
        predict_fn: Callable[[list], list],
        max_batch_pairs: int = 256,
        batch_wait_ms: int = 5,
        max_queue: int = 1000,
    ) -> None:
        self._predict_fn = predict_fn
        self._max_batch_pairs = max_batch_pairs
        self._batch_wait_s = batch_wait_ms / 1000.0
        self._max_queue = max_queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def submit(self, pairs: list) -> list:
        if self._queue.qsize() >= self._max_queue:
            raise RuntimeError("rerank batcher queue overflow")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((pairs, fut))
        return await fut

    async def _run_loop(self) -> None:
        while True:
            try:
                pairs0, fut0 = await self._queue.get()
                batch = [(pairs0, fut0)]
                total = len(pairs0)
                deadline = time.monotonic() + self._batch_wait_s
                # 윈도 내 추가 수집(큐에 있으면 즉시, 없으면 잠깐 대기). soft cap.
                while total < self._max_batch_pairs:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        pairs_i, fut_i = await asyncio.wait_for(
                            self._queue.get(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        break
                    batch.append((pairs_i, fut_i))
                    total += len(pairs_i)  # 마지막 항목이 max를 약간 넘을 수 있음(soft cap)

                all_pairs = [p for pairs, _ in batch for p in pairs]
                try:
                    scores = await asyncio.to_thread(self._predict_fn, all_pairs)
                except Exception as exc:  # noqa: BLE001 -- 배치 실패는 future로 전파(폴백)
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(exc)
                    continue

                off = 0
                for pairs, fut in batch:
                    n = len(pairs)
                    if not fut.done():
                        fut.set_result(list(scores[off:off + n]))
                    off += n
            except Exception:  # noqa: BLE001 -- 루프 보호(개별 배치 실패가 루프를 죽이지 않게)
                continue

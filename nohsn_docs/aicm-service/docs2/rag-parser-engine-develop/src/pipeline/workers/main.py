"""Kafka Consumer 메인 루프 -- 파이프라인 워커 진입점.

각 토픽의 메시지를 소비하여 해당 워커에 디스패치한다.
DLQ 핸들러를 통해 최대 3회 재시도, 실패 시 aicm.document.dlq 로 전송.
SIGTERM/SIGINT 시 graceful shutdown: 진행 중인 메시지 완료 후 오프셋 커밋.

사용법::

    python -m src.pipeline.workers.main
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from typing import Any

from src.api.middleware.rls_context import bind_system_scope
from src.common.config import settings
from src.common.constants import (
    TOPIC_DOCUMENT_BLOCKED,
    TOPIC_DOCUMENT_CHUNKED,
    TOPIC_DOCUMENT_PARSED,
    TOPIC_DOCUMENT_PART_BLOCKED,
    TOPIC_DOCUMENT_PART_READY,
    TOPIC_DOCUMENT_SPLIT,
    TOPIC_DOCUMENT_UPLOADED,
    TOPIC_DOCUMENT_UPLOADED_LARGE,
    TOPIC_DOCUMENT_UPLOADED_SMALL,
)
from src.common.logging import get_logger, setup_logging
from src.pipeline.metrics import PIPELINE_METRICS, start_pipeline_metrics_server, track_stage
from src.pipeline.models.events import (
    DocumentBlockedEvent,
    DocumentChunkedEvent,
    DocumentParsedEvent,
    DocumentPartBlockedEvent,
    DocumentPartReadyEvent,
    DocumentSplitEvent,
    DocumentUploadedEvent,
)
from src.pipeline.workers.dlq import DLQHandler
from src.pipeline.workers.dlq_scheduler import dlq_scheduler_loop
from src.pipeline.workers.recovery import recover_stale_documents

log = get_logger(__name__)

# fix A — Per-doc Lock (race 차단 + refcount cleanup). spec §3.2.
_doc_locks: dict[str, asyncio.Lock] = {}
_doc_lock_refcount: dict[str, int] = {}


async def _acquire_doc_lock(doc_id: str) -> asyncio.Lock:
    """spec §3.2 — same-doc concurrent processing 직렬화. refcount 로 lifecycle 추적."""
    lock = _doc_locks.get(doc_id)
    if lock is None:
        lock = asyncio.Lock()
        _doc_locks[doc_id] = lock
        _doc_lock_refcount[doc_id] = 0
    _doc_lock_refcount[doc_id] += 1
    return lock


def _release_doc_lock(doc_id: str) -> None:
    """refcount 0 도달 시 dict 에서 제거 (장기 운영 시 누적 방지)."""
    _doc_lock_refcount[doc_id] = _doc_lock_refcount.get(doc_id, 1) - 1
    if _doc_lock_refcount[doc_id] <= 0:
        _doc_locks.pop(doc_id, None)
        _doc_lock_refcount.pop(doc_id, None)


# fix B — Dedup key helpers (discriminator 추가). spec §3.3.
def _dedup_key(document_id: str, stage: str, discriminator: str = "main") -> str:
    """Dedup key — doc_id + stage + discriminator (part_index 또는 'main').

    spec §3.3 — 이전 stall 의 dedup 마커가 새 dispatch part 처리를
    영구 skip 시키던 결함 해소 (last incident — part 0 가 이전 dispatch 의
    merge_part 마커로 영구 skip 됨).
    """
    return f"aicm:processing:{document_id}:{stage}:{discriminator}"


def _dedup_key_part(document_id: str, part_index: int, stage: str) -> str:
    """Part 단위 dedup key."""
    return _dedup_key(document_id, stage, discriminator=str(part_index))


_SHUTDOWN_EVENT = asyncio.Event()
_IN_PROGRESS_COUNT = 0
_SHUTDOWN_TIMEOUT_SECONDS = 30

# 글로벌 DLQ 핸들러 (run_consumer_loop 에서 초기화)
_dlq_handler: DLQHandler | None = None

# DLQ 자동 재처리 스케줄러 태스크
_dlq_scheduler_task: asyncio.Task | None = None

# 순차 처리 큐: uploaded 이벤트를 큐에 넣고, 백그라운드 태스크가 하나씩 처리
# 중간 이벤트(parsed, blocked 등)는 컨슈머에서 즉시 처리
# B200 LLM이 동시 4채널을 지원하므로 4개 워커 풀 운영
_doc_queue: asyncio.Queue | None = None  # run_consumer_loop에서 초기화
_pipeline_complete: dict[str, asyncio.Event] = {}  # doc_id → 완료 시그널
_queue_tasks: list[asyncio.Task] = []  # N개 워커 태스크 풀
_PIPELINE_PARALLEL_WORKERS = 4  # B200 LLM 동시 처리 한도

# fix A — Supervisor pattern (asyncio.gather 대체). spec §3.7.
_CONSUMER_BACKOFF_INITIAL_SEC = 5
_CONSUMER_BACKOFF_MAX_SEC = 60


async def _consumer_supervisor(name: str, run_fn) -> None:
    """spec §3.7 — crash 회복 + clean exit 정책.

    - run_fn 이 Exception 으로 죽으면 backoff 후 재시작
    - SHUTDOWN_EVENT 가 set 이고 run_fn 이 return → 정상 종료
    - SHUTDOWN_EVENT 안 set 인데 run_fn 이 return → silent exit, crash 취급 재시작
    """
    backoff = _CONSUMER_BACKOFF_INITIAL_SEC
    while not _SHUTDOWN_EVENT.is_set():
        try:
            await run_fn()
        except Exception as e:  # noqa: BLE001
            log.error(
                f"consumer_{name}_crashed",
                error=str(e), backoff_sec=backoff,
                consumer_role=name,
            )
        else:
            if _SHUTDOWN_EVENT.is_set():
                log.info(f"consumer_{name}_shutdown_clean", consumer_role=name)
                return
            log.warning(
                f"consumer_{name}_silent_exit_treated_as_crash",
                consumer_role=name, backoff_sec=backoff,
            )
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _CONSUMER_BACKOFF_MAX_SEC)
    log.info(f"consumer_{name}_shutdown_event_set", consumer_role=name)


# ---------------------------------------------------------------------------
# fix A — Readiness barrier (spec §3.10): merge consumer 가 partition assign
# 받고 baseline commit 후 main consumer 시작. main 이 먼저 시작하면
# part_blocked 가 main 의 latest 이전에 쌓여 있을 때 skip 되는 race 차단.
# ---------------------------------------------------------------------------
_merge_consumer_ready = asyncio.Event()


def _make_merge_readiness_listener(consumer: Any) -> Any:
    """spec §3.10 — ConsumerRebalanceListener 동적 생성.

    aiokafka import 를 함수 안으로 미뤄 단위 테스트가 import 시점에 깨지지 않게.
    listener semantics:
      - on_partitions_revoked: _merge_consumer_ready.clear() (다음 assign 까지 main 차단)
      - on_partitions_assigned:
          - committed offset 있는 partition → seek (pending part_blocked 보존)
          - committed 없는 partition → end_offset baseline commit + seek
          - 둘 다 처리 후 _merge_consumer_ready.set()
    """
    from aiokafka import ConsumerRebalanceListener  # type: ignore
    from aiokafka.structs import OffsetAndMetadata  # type: ignore

    class _MergeReadinessListener(ConsumerRebalanceListener):  # type: ignore[misc]
        def __init__(self, cons: Any) -> None:
            self._consumer = cons

        async def on_partitions_revoked(self, revoked: Any) -> None:
            # restart / rebalance 시 readiness 무효화 — main 이 다음 readiness 대기.
            _merge_consumer_ready.clear()
            log.info(
                "merge_consumer_partitions_revoked",
                partitions=[str(tp) for tp in (revoked or [])],
                consumer_role="merge",
            )

        async def on_partitions_assigned(self, assigned: Any) -> None:
            if not assigned:
                # assign 없음 — main barrier 해제는 안 함 (다음 assign 대기).
                return
            try:
                committed = {
                    tp: await self._consumer.committed(tp) for tp in assigned
                }
                end_offsets = await self._consumer.end_offsets(list(assigned))
                # GPT-5.5 v2 verdict #1 — retention 으로 committed < beginning 인 케이스.
                # aiokafka 0.11+ 에서는 beginning_offsets 지원.
                try:
                    begin_offsets = await self._consumer.beginning_offsets(list(assigned))
                except Exception:  # noqa: BLE001
                    begin_offsets = {tp: 0 for tp in assigned}
                offsets_to_commit: dict[Any, Any] = {}
                seek_targets: dict[Any, int] = {}
                out_of_range_high: list[str] = []
                out_of_range_low: list[str] = []
                for tp in assigned:
                    end_off = end_offsets.get(tp, 0)
                    begin_off = begin_offsets.get(tp, 0)
                    if committed[tp] is None:
                        offsets_to_commit[tp] = OffsetAndMetadata(
                            end_off, "readiness_baseline"
                        )
                        seek_targets[tp] = end_off
                    else:
                        committed_off = committed[tp]
                        # spec §3.10 + GPT-5.5 v2 — committed 가 [begin, end] 범위 밖이면 clamp.
                        # high (committed>end): truncation / log reset → end 로 clamp.
                        # low  (committed<begin): retention/compaction → begin 로 clamp.
                        if committed_off > end_off:
                            out_of_range_high.append(
                                f"{tp}:committed={committed_off},end={end_off}"
                            )
                            seek_targets[tp] = end_off
                            # 잘못된 committed 를 새 baseline 으로 덮어쓰기.
                            offsets_to_commit[tp] = OffsetAndMetadata(
                                end_off, "readiness_clamp_high"
                            )
                        elif committed_off < begin_off:
                            out_of_range_low.append(
                                f"{tp}:committed={committed_off},begin={begin_off}"
                            )
                            seek_targets[tp] = begin_off
                            # retention 으로 사라진 offset — begin 으로 덮어쓰기 (재처리).
                            offsets_to_commit[tp] = OffsetAndMetadata(
                                begin_off, "readiness_clamp_low"
                            )
                        else:
                            seek_targets[tp] = committed_off
                if offsets_to_commit:
                    await self._consumer.commit(offsets_to_commit)
                for tp, off in seek_targets.items():
                    self._consumer.seek(tp, off)
                if out_of_range_high:
                    log.warning(
                        "merge_consumer_committed_offset_out_of_range_high",
                        partitions=out_of_range_high,
                        consumer_role="merge",
                        action="clamped_to_end_offset",
                    )
                if out_of_range_low:
                    log.warning(
                        "merge_consumer_committed_offset_out_of_range_low",
                        partitions=out_of_range_low,
                        consumer_role="merge",
                        action="clamped_to_beginning_offset_replay_from_begin",
                    )
                _merge_consumer_ready.set()
                log.info(
                    "merge_consumer_ready",
                    partitions=[str(tp) for tp in assigned],
                    baseline_committed=len(offsets_to_commit),
                    resumed_from_committed=len(assigned) - len(offsets_to_commit),
                    consumer_role="merge",
                )
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "merge_consumer_readiness_commit_failed",
                    error=str(exc),
                    consumer_role="merge",
                )
                # ready set 안 함 — main 이 timeout 후 supervisor crash → 재시작.

    return _MergeReadinessListener(consumer)


# ---------------------------------------------------------------------------
# D48 §1 — 워커 프로파일 (small / large) + Early Divert
# ---------------------------------------------------------------------------
# - PIPELINE_WORKER_PROFILE=small : small + legacy topic 흡수, 동시성 4
# - PIPELINE_WORKER_PROFILE=large : large topic 만 구독, 동시성 1
# - 미설정 (legacy 운영) : 기존 동작 — 모든 topic 구독 (PIPELINE_LARGE_TOPIC_ENABLED 무시)
#
# Early Divert: small 워커가 legacy topic 의 large 메시지를 받으면 즉시 large topic
# 재발행 + skip. small 처리 큐가 막히지 않도록 보호.
def _resolve_worker_profile() -> str:
    raw = os.environ.get("PIPELINE_WORKER_PROFILE", "").strip().lower()
    if raw in ("small", "large"):
        return raw
    return "legacy"


def _resolve_uploaded_topics_for_profile(profile: str) -> list[str]:
    """프로파일별 구독할 uploaded* topic 목록."""
    if profile == "small":
        return [TOPIC_DOCUMENT_UPLOADED_SMALL, TOPIC_DOCUMENT_UPLOADED]
    if profile == "large":
        return [TOPIC_DOCUMENT_UPLOADED_LARGE]
    # legacy — 모든 토픽 흡수 (역호환)
    return [
        TOPIC_DOCUMENT_UPLOADED,
        TOPIC_DOCUMENT_UPLOADED_SMALL,
        TOPIC_DOCUMENT_UPLOADED_LARGE,
    ]


# ---------------------------------------------------------------------------
# D58 §A — Profile-aware 전체 topic 구독 (single source of truth)
# ---------------------------------------------------------------------------
# D57 153p PDF E2E 에서 *각 part 2회 처리* 결함 발견. 두 워커 (small + large) 가
# 서로 다른 consumer group 으로 동일 SPLIT/PART_READY/PART_BLOCKED 를 구독 →
# Kafka 정의상 group 별 fan-out → 같은 메시지 양쪽에 배달 → 처리 시간 2배.
#
# 본 함수는 *프로파일별 모든 topic* 의 단일 출처. unit test 가 이 함수를 기준으로
# 검증 → 토픽 개수 불일치 회귀 차단.
def _resolve_main_topics(profile: str) -> list[str]:
    """main consumer 가 구독할 topic 목록.

    part_blocked 는 제외 — merge consumer 가 별도 group_id 로 구독.
    spec §3.1.
    """
    uploaded = _resolve_uploaded_topics_for_profile(profile)

    if profile == "small":
        return [
            *uploaded,
            TOPIC_DOCUMENT_PARSED,
            TOPIC_DOCUMENT_CHUNKED,
            TOPIC_DOCUMENT_BLOCKED,
        ]
    if profile == "large":
        return [
            *uploaded,
            TOPIC_DOCUMENT_SPLIT,
            TOPIC_DOCUMENT_PART_READY,
            TOPIC_DOCUMENT_PARSED,
            TOPIC_DOCUMENT_CHUNKED,
            TOPIC_DOCUMENT_BLOCKED,
        ]
    return [
        *uploaded,
        TOPIC_DOCUMENT_PARSED,
        TOPIC_DOCUMENT_CHUNKED,
        TOPIC_DOCUMENT_BLOCKED,
        TOPIC_DOCUMENT_SPLIT,
        TOPIC_DOCUMENT_PART_READY,
        TOPIC_DOCUMENT_PART_BLOCKED,
    ]


def _resolve_merge_topics(profile: str) -> list[str]:
    """merge consumer 가 구독할 topic 목록.

    large profile 만 part_blocked 구독. small/legacy 는 빈 list.
    spec §3.1.
    """
    if profile == "large":
        return [TOPIC_DOCUMENT_PART_BLOCKED]
    return []


def _resolve_topics_for_profile(profile: str) -> list[str]:
    """레거시 호환 — main + merge 합산 반환."""
    return _resolve_main_topics(profile) + _resolve_merge_topics(profile)


def _resolve_parallel_workers(profile: str) -> int:
    """프로파일별 병렬 워커 수."""
    if profile == "large":
        raw = os.environ.get("PIPELINE_PARALLEL_WORKERS_LARGE")
        if raw:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        return 1
    if profile == "small":
        raw = os.environ.get("PIPELINE_PARALLEL_WORKERS_SMALL")
        if raw:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        return 4
    # legacy
    return _PIPELINE_PARALLEL_WORKERS


def _early_divert_enabled() -> bool:
    raw = os.environ.get("PIPELINE_EARLY_DIVERT_ENABLED", "true").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    # PIPELINE_LARGE_TOPIC_ENABLED=false 시 divert 무력화 (대상 토픽 부재 — 블랙홀 방지).
    large_topic_raw = os.environ.get("PIPELINE_LARGE_TOPIC_ENABLED", "true").strip().lower()
    if large_topic_raw in ("0", "false", "no", "off"):
        return False
    return True


def _should_divert_to_large(
    *,
    value_bytes: bytes,
    profile: str,
    incoming_topic: str,
) -> bool:
    """small 워커가 legacy 메시지를 large 로 즉시 재발행해야 하는지 판정.

    조건:
    - profile == "small"
    - incoming_topic == TOPIC_DOCUMENT_UPLOADED (legacy)
    - upload_classification.profile == "large" 또는 file_size_bytes 가 threshold 이상

    분류 메타가 없는 (예: legacy publisher 가 발행한) 메시지는 file_size 로 추정.
    """
    if not _early_divert_enabled():
        return False
    if profile != "small":
        return False
    if incoming_topic != TOPIC_DOCUMENT_UPLOADED:
        return False
    try:
        import json as _json
        from src.pipeline.services.upload_topic_classifier import classify_upload_topic

        raw = _json.loads(value_bytes)
        classification = raw.get("upload_classification") or {}
        if classification.get("profile") == "large":
            return True
        # classification 없음 — file_size 로 재분류
        size_bytes: int | None = classification.get("file_size_bytes")
        source_path = raw.get("source_path")
        if size_bytes is None and source_path:
            try:
                size_bytes = os.path.getsize(source_path)
            except OSError:
                size_bytes = None
        decision = classify_upload_topic(
            file_size_bytes=size_bytes,
            source_path=source_path,
            source_format=raw.get("source_format"),
        )
        return decision.profile == "large"
    except Exception as exc:  # noqa: BLE001
        log.warning("early_divert_classify_failed", error=str(exc))
        return False


async def _divert_to_large(value_bytes: bytes, producer: Any) -> bool:
    """legacy 메시지를 large topic 으로 재발행. 성공 시 True."""
    if producer is None:
        log.warning("early_divert_no_producer_skip")
        return False
    try:
        await producer.send_and_wait(TOPIC_DOCUMENT_UPLOADED_LARGE, value=value_bytes)
        log.info(
            "early_divert_published",
            from_topic=TOPIC_DOCUMENT_UPLOADED,
            to_topic=TOPIC_DOCUMENT_UPLOADED_LARGE,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("early_divert_publish_failed", error=str(exc))
        return False

# 글로벌 LLM 클라이언트 (블럭 세그멘테이션용)
_llm_client: object | None = None


# ---------------------------------------------------------------------------
# D46-v3 §3-a — pipeline_queue_timeout 비례 (clamp 가드 + size=0 fallback)
# ---------------------------------------------------------------------------
# 회귀 가드:
# - `_TIMEOUT_MIN_SEC` clamp 가 legacy(1800s) 이상 → 작은 자료도 절대 회귀 없음.
# - `file_size <= 0` (MinIO/S3 lazy key, OSError 등) → legacy(MIN_SEC) fallback.
# - env override 로 운영자가 명시적 조정 가능.
PIPELINE_QUEUE_TIMEOUT_BASE_SEC = float(
    getattr(settings, "PIPELINE_QUEUE_TIMEOUT_BASE_SEC", 600)
)
PIPELINE_QUEUE_TIMEOUT_PER_PAGE_SEC = float(
    getattr(settings, "PIPELINE_QUEUE_TIMEOUT_PER_PAGE_SEC", 30)
)
PIPELINE_QUEUE_TIMEOUT_MIN_SEC = float(
    getattr(settings, "PIPELINE_QUEUE_TIMEOUT_MIN_SEC", 1800)
)
PIPELINE_QUEUE_TIMEOUT_MAX_SEC = float(
    getattr(settings, "PIPELINE_QUEUE_TIMEOUT_MAX_SEC", 7200)
)
_PIPELINE_PAGES_PER_MB = float(
    getattr(settings, "PIPELINE_QUEUE_TIMEOUT_PAGES_PER_MB", 5)
)


def _compute_queue_timeout(source_path: str | None) -> float:
    """D46-v3 §3-a — file_size 비례 timeout 산출 (회귀 0 보장).

    원칙
    ----
    - source_path 가 None/빈 문자열 → MIN_SEC (legacy 1800s).
    - os.path.getsize 실패 (FileNotFoundError / 원격 키 등 OSError) → MIN_SEC fallback.
    - size <= 0 → MIN_SEC fallback (MinIO/S3 lazy key 보호).
    - 정상 추정 시: BASE + (estimated_pages × PER_PAGE_SEC), clamp [MIN_SEC, MAX_SEC].
    - clamp MIN_SEC = 1800 → 작은 자료에서도 절대 회귀 없음.
    """
    if not source_path:
        return PIPELINE_QUEUE_TIMEOUT_MIN_SEC
    try:
        size_bytes = os.path.getsize(source_path)
    except OSError:
        return PIPELINE_QUEUE_TIMEOUT_MIN_SEC
    if size_bytes <= 0:
        return PIPELINE_QUEUE_TIMEOUT_MIN_SEC
    size_mb = size_bytes / (1024 * 1024)
    est_pages = size_mb * _PIPELINE_PAGES_PER_MB
    timeout = PIPELINE_QUEUE_TIMEOUT_BASE_SEC + (
        est_pages * PIPELINE_QUEUE_TIMEOUT_PER_PAGE_SEC
    )
    return max(
        PIPELINE_QUEUE_TIMEOUT_MIN_SEC,
        min(timeout, PIPELINE_QUEUE_TIMEOUT_MAX_SEC),
    )


def get_dlq_handler() -> DLQHandler | None:
    """글로벌 DLQ 핸들러 인스턴스를 반환한다."""
    return _dlq_handler


async def _init_llm_client() -> object | None:
    """파이프라인 LLM 클라이언트를 초기화한다 (vLLM / OpenAI-compatible only)."""
    log.info("llm_init_start", provider="vllm")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.VLLM_URL,
            api_key=settings.VLLM_API_KEY or "dummy",
        )
        log.info(
            "llm_client_initialized",
            model=settings.VLLM_MODEL,
            provider="vllm",
            url=settings.VLLM_URL,
        )
        return client
    except Exception as exc:
        log.warning("llm_client_init_failed", error=str(exc))

    log.warning("no_llm_client_available_using_fallback_segmenter")
    return None


def _handle_signal(sig: int, frame: Any) -> None:
    """SIGTERM/SIGINT 시 graceful shutdown 시작."""
    log.info("shutdown_signal_received", signal=sig)
    _SHUTDOWN_EVENT.set()


async def _create_producer() -> Any:
    """Kafka producer 를 생성한다.

    D48 §1 — early divert 시 메시지 손실/중복 위험을 줄이기 위해 idempotent producer
    + acks=all 사용. legacy 동작은 동일하나 신뢰성 강화.
    """
    try:
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            enable_idempotence=True,
            acks="all",
        )
        await producer.start()
        return producer
    except ImportError:
        log.warning("aiokafka_not_installed_producer_disabled")
        return None


async def _create_consumer(
    topics: list[str],
    *,
    group_id: str | None = None,
    auto_offset_reset: str | None = None,
    enable_auto_commit: bool = False,
    max_poll_interval_ms: int | None = None,
    session_timeout_ms: int | None = None,
) -> Any:
    """Kafka consumer 를 생성한다 (수동 커밋 모드 기본).

    Args:
        topics: 즉시 assign 할 topic list. 비어 있으면 caller 가 subscribe() 로
            listener 등록 (spec §3.10 readiness barrier 용).
        group_id: consumer group. None 이면 settings.KAFKA_CONSUMER_GROUP.
        auto_offset_reset: None 이면 settings.KAFKA_AUTO_OFFSET_RESET.
        enable_auto_commit: 기본 False (graceful shutdown 수동 커밋).
        max_poll_interval_ms: aiokafka heartbeat 보호 (merge consumer 등).
        session_timeout_ms: aiokafka session timeout.
    """
    try:
        from aiokafka import AIOKafkaConsumer

        kwargs: dict[str, Any] = dict(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id or settings.KAFKA_CONSUMER_GROUP,
            auto_offset_reset=auto_offset_reset or settings.KAFKA_AUTO_OFFSET_RESET,
            enable_auto_commit=enable_auto_commit,
        )
        if max_poll_interval_ms is not None:
            kwargs["max_poll_interval_ms"] = max_poll_interval_ms
        if session_timeout_ms is not None:
            kwargs["session_timeout_ms"] = session_timeout_ms

        consumer = AIOKafkaConsumer(*topics, **kwargs)
        await consumer.start()
        return consumer
    except ImportError:
        log.error("aiokafka_not_installed_cannot_start_consumer")
        raise


async def _dedup_check(document_id: str, stage: str) -> bool:
    """Redis 기반 중복 처리 방지. 이미 처리 중이면 True (skip)."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        key = _dedup_key(document_id, stage)
        # SET NX + TTL 10분: 해당 stage가 이미 처리 중이면 False 반환
        acquired = await r.set(key, "1", nx=True, ex=600)
        await r.aclose()
        if not acquired:
            log.info(
                "dedup_skip",
                document_id=document_id,
                stage=stage,
                reason="already_processing",
            )
            return True
        return False
    except Exception:
        # Redis 접근 실패 시 중복 체크 없이 통과 (안전)
        return False


async def _dedup_clear(document_id: str, stage: str) -> None:
    """처리 완료 후 dedup 키 제거."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.delete(_dedup_key(document_id, stage))
        await r.aclose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# D58 §A — Part-level dedup (PART_READY / PART_BLOCKED)
# ---------------------------------------------------------------------------
# 기존 _dedup_check 는 doc 단위 (doc_id + stage). part_ready / part_blocked 는
# 같은 doc 내 part_index 별로 처리되므로 part_index 도 키에 포함해야 한다.
# 사전 GPT-5 §3 권고: PART_* 도 최소 dedup 추가 — 동일 group 내 producer 재시도/
# 네트워크 중복 대비. TTL 기본 7200s (2시간) — 사후 GPT-5 #1: 장시간 part 처리
# (>10분) 시 TTL 만료 위험 차단. env `PART_DEDUP_TTL_SEC` 로 override 가능.
_PART_DEDUP_TTL_SEC = int(os.environ.get("PART_DEDUP_TTL_SEC", "7200"))


async def _dedup_check_part(document_id: str, part_index: int, stage: str) -> bool:
    """Redis 기반 part 단위 중복 처리 방지. 이미 처리 중이면 True (skip)."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        key = _dedup_key_part(document_id, part_index, stage)
        acquired = await r.set(key, "1", nx=True, ex=_PART_DEDUP_TTL_SEC)
        await r.aclose()
        if not acquired:
            log.info(
                "dedup_skip_part",
                document_id=document_id,
                part_index=part_index,
                stage=stage,
                reason="already_processing",
            )
            return True
        return False
    except Exception:
        # Redis 접근 실패 시 중복 체크 없이 통과 (D17-v5 idempotent upsert 보장)
        return False


async def _dedup_clear_part(document_id: str, part_index: int, stage: str) -> None:
    """처리 완료 후 part 단위 dedup 키 제거."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.delete(_dedup_key_part(document_id, part_index, stage))
        await r.aclose()
    except Exception:
        pass


def _pipeline_done_key(doc_id: str) -> str:
    return f"aicm:pipeline_done:{doc_id}"


async def _redis_mark_pipeline_done(doc_id: str) -> None:
    """완료를 Redis 에 표시 — cross-process 슬롯 해제용.

    early-divert 로 완료 신호가 슬롯 보유 워커와 *다른 프로세스* 에서 발생해도,
    슬롯 보유 워커가 이 키를 폴링해 감지할 수 있게 한다(in-memory asyncio.Event 는
    프로세스 로컬이라 cross-process 전달 불가). TTL=max queue timeout(7200)+여유.
    """
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.set(_pipeline_done_key(doc_id), "1", ex=7800)
        await r.aclose()
    except Exception:
        pass


async def _redis_check_pipeline_done(doc_id: str) -> bool:
    """Redis 완료 표시 존재 여부(cross-process 완료 감지)."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        v = await r.get(_pipeline_done_key(doc_id))
        await r.aclose()
        return v is not None
    except Exception:
        return False


async def _redis_clear_pipeline_done(doc_id: str) -> None:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.delete(_pipeline_done_key(doc_id))
        await r.aclose()
    except Exception:
        pass


async def _signal_pipeline_complete(doc_id: str) -> None:
    """문서 파이프라인 완료를 시그널한다 (큐의 다음 문서 시작).

    cross-process 안전: 완료 신호가 슬롯 보유 워커와 다른 프로세스(early-divert)에서
    발생해도 Redis 키로 감지되도록 항상 표시한다. 동일 프로세스면 asyncio.Event 도 즉시 set.
    """
    await _redis_mark_pipeline_done(doc_id)
    evt = _pipeline_complete.pop(doc_id, None)
    if evt is not None:
        evt.set()
        log.info("pipeline_complete_signaled", document_id=doc_id)


async def _sequential_queue_processor(producer: Any, worker_id: int = 0) -> None:
    """백그라운드 워커 태스크: uploaded 이벤트를 큐에서 꺼내 처리.

    여러 워커가 동시에 큐에서 꺼내 N개 문서를 병렬로 파이프라인 통과.
    각 워커는 한 문서의 전체 파이프라인(parse→block→embed)이 완료될 때까지
    다음 문서를 꺼내지 않는다.
    """
    from src.pipeline.workers.parse_worker import handle_document_uploaded

    log.info("queue_worker_started", worker_id=worker_id)

    while not _SHUTDOWN_EVENT.is_set():
        try:
            # 큐에서 다음 문서 대기
            event = await asyncio.wait_for(
                _doc_queue.get(),  # type: ignore[union-attr]
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            break

        doc_id = str(event.document_id)
        log.info(
            "pipeline_queue_start",
            worker_id=worker_id,
            document_id=doc_id,
            queue_size=_doc_queue.qsize(),  # type: ignore[union-attr]
            active_workers=sum(1 for t in _queue_tasks if not t.done()),
        )

        # 완료 시그널 등록
        complete_evt = asyncio.Event()
        _pipeline_complete[doc_id] = complete_evt

        # D34 §1 — bind_system_scope per-event wrap. 큐 적재 task 와 다른 task
        # 컨텍스트이므로 _dispatch_message wrap 과 별개로 명시 wrap.
        # 사전 GPT-5 §2 권고: write-heavy path (handle_document_uploaded) 이므로
        # tenant_id 필수 — allow_null_tenant=False, 누락 시 fail-fast.
        _event_tid = str(getattr(event, "tenant_id", "")) or None
        if not _event_tid:
            # D35 §1 — per-event rebind failure metric. tenant_id 누락 시 즉시 inc
            # → kms_worker_per_event_rebind_failure_total alert 트리거.
            try:
                from src.common.metrics import (
                    REBIND_SITE_SEQUENTIAL,
                    inc_kms_worker_rebind_failure,
                )

                inc_kms_worker_rebind_failure(
                    REBIND_SITE_SEQUENTIAL, "aicm.document.uploaded"
                )
            except Exception:  # noqa: BLE001 — metrics 미초기화 방어.
                pass
            log.error(
                "missing_tenant_id",
                worker_id=worker_id,
                document_id=doc_id,
                where="_sequential_queue_processor",
            )
            _pipeline_complete.pop(doc_id, None)
            continue
        # D46-v3 §3-a — file_size 비례 timeout (회귀 0 보장 clamp).
        _queue_timeout = _compute_queue_timeout(getattr(event, "source_path", None))
        try:
            async with bind_system_scope(_event_tid, allow_null_tenant=False):
                # parse 시작 (이후 parsed→block→embed은 컨슈머 루프에서 처리)
                await handle_document_uploaded(event, producer)

            # 전체 파이프라인 완료 대기 (embed_worker가 signal).
            # cross-process(early-divert)로 다른 워커에서 완료 신호가 나면 asyncio.Event 는
            # set 되지 않으므로, Redis 완료 키를 함께 폴링해 슬롯을 제때 해제한다(30분 timeout 방지).
            _poll_sec = 5.0
            _deadline = time.monotonic() + _queue_timeout
            _done = False
            while time.monotonic() < _deadline:
                try:
                    await asyncio.wait_for(complete_evt.wait(), timeout=_poll_sec)
                    _done = True
                    break
                except asyncio.TimeoutError:
                    if await _redis_check_pipeline_done(doc_id):
                        _done = True
                        break
            _pipeline_complete.pop(doc_id, None)
            await _redis_clear_pipeline_done(doc_id)
            if _done:
                log.info(
                    "pipeline_queue_document_done",
                    worker_id=worker_id,
                    document_id=doc_id,
                    timeout_sec=int(_queue_timeout),
                )
            else:
                log.warning(
                    "pipeline_queue_timeout",
                    worker_id=worker_id,
                    document_id=doc_id,
                    timeout_sec=int(_queue_timeout),
                )
        except Exception as exc:
            log.error(
                "pipeline_queue_error",
                worker_id=worker_id,
                document_id=doc_id,
                error=str(exc),
            )
            _pipeline_complete.pop(doc_id, None)
            await _redis_clear_pipeline_done(doc_id)

    log.info("queue_worker_stopped", worker_id=worker_id)


async def _check_step_by_step_pause(doc_id: str, topic: str, value: bytes) -> bool:
    """step_by_step 모드인 문서의 다음 단계 진입 전 자동 일시정지.

    Returns True if paused (caller should skip dispatch).
    JSONB merge(||)를 사용하여 다른 워커의 meta 업데이트와 경합 방지.
    """
    if not doc_id:
        return False
    try:
        import json as _json

        from sqlalchemy import text

        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT processing_meta FROM documents WHERE id = :did"),
                {"did": doc_id},
            )
            row = result.fetchone()
            meta = (row[0] if row else None) or {}

            if not meta.get("step_by_step"):
                return False

            # 이미 pause 상태면 중복 방지
            if meta.get("control_signal") == "pause":
                return True

            # resume 직후 재진입: 플래그 소비 후 통과
            if meta.get("step_by_step_resume_pending"):
                await session.execute(
                    text(
                        "UPDATE documents "
                        "SET processing_meta = processing_meta || CAST(:patch AS jsonb) "
                        "WHERE id = :did"
                    ),
                    {"did": doc_id, "patch": _json.dumps({"step_by_step_resume_pending": False})},
                )
                await session.commit()
                log.info("step_by_step_resume_consumed", document_id=doc_id)
                return False

            # 일시정지 설정 + 재개 시 재발행할 이벤트 저장
            stage_map = {
                TOPIC_DOCUMENT_PARSED: "blocking",
                TOPIC_DOCUMENT_BLOCKED: "embedding",
            }
            next_stage = stage_map.get(topic, "unknown")

            patch = {
                "control_signal": "pause",
                "paused_before_stage": next_stage,
                "paused_event_topic": topic,
                "paused_event_data": value.decode("utf-8"),
            }
            await session.execute(
                text(
                    "UPDATE documents "
                    "SET processing_meta = processing_meta || CAST(:patch AS jsonb) "
                    "WHERE id = :did"
                ),
                {"did": doc_id, "patch": _json.dumps(patch)},
            )
            await session.commit()

            log.info(
                "step_by_step_auto_pause",
                document_id=doc_id,
                paused_before=next_stage,
            )
            return True
    except Exception as exc:
        log.warning(
            "step_by_step_check_failed",
            document_id=doc_id,
            error=str(exc),
        )
        return False


def _flush_logging_handlers() -> None:
    """D35 §2 — fatal exit 직전 logging handler flush.

    GPT-5 §2 MUST: SystemExit 직전 로그 버퍼 flush — 종료 시점 가시성.
    GPT-5 §2 SHOULD (사후 권고): root + 비루트 핸들러 모두 flush + stdout/stderr +
    logging.shutdown() 호출. 비동기 핸들러 / 비표준 핸들러까지 보장.
    """
    import logging as _logging
    import sys as _sys

    # 1) root + 모든 명명된 logger 의 handler flush.
    for h in _logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:  # noqa: BLE001
            pass
    for name in list(_logging.Logger.manager.loggerDict.keys()):
        lg = _logging.getLogger(name)
        for h in getattr(lg, "handlers", []):
            try:
                h.flush()
            except Exception:  # noqa: BLE001
                pass
    # 2) stdout/stderr 직접 flush (structlog → stdout 경로 보강).
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    # 3) logging.shutdown — 모든 핸들러 close (재진입 안전).
    try:
        _logging.shutdown()
    except Exception:  # noqa: BLE001
        pass


async def _worker_rls_self_check() -> None:
    """D34 §2 + D35 §2 — 기동 시 1회 DB role + RLS 활성 확인.

    KMS_DB_ROLE_WORKER=app + RLS_ENFORCE=true 환경에서 kms_app (NOBYPASSRLS) 으로
    connect 됐는지 확인.

    D35 §2 — fatal 분기:
        KMS_DB_ROLE=app + RLS_ENFORCE=true + bypass_rls=True → 운영 오인 구성
        (RLS 무력화 가능). raise SystemExit(99) — pipeline-worker 즉시 종료 +
        Pod CrashLoop / docker exit_code=99 → operator 인식 + log-based alert.

    fatal X 분기 (false positive 회피):
        - KMS_DB_ROLE=migration / super: BYPASSRLS=true 가 의도 → 정보 log 만.
        - RLS_ENFORCE=false: RLS 무력화 의도 (test/dev) → 정보 log 만.
        - bypass_rls=False: 정상 운영 → 정보 log.
        - bypass_rls=None: DB role 조회 실패 → warning log + 진행 (DB 일시 장애).

    DB query 자체 실패는 worker 차단 X (warning log 후 계속).
    """
    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory

        # bind_system_scope wrap — kms_app 인 경우 default-deny 회피.
        async with bind_system_scope(None, allow_null_tenant=True):
            async with async_session_factory() as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT current_user, "
                            "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) "
                            "AS bypassrls"
                        )
                    )
                ).fetchone()
                if row:
                    _bypass = bool(row[1]) if row[1] is not None else None
                    _enforce = bool(getattr(settings, "RLS_ENFORCE", False))
                    _role_str = str(
                        getattr(settings, "KMS_DB_ROLE", "(default)")
                    ).strip().lower()

                    # D35 §2 — fatal 조건: KMS_DB_ROLE=app + RLS_ENFORCE=true +
                    # bypass=True. migration / super 는 BYPASSRLS=true 가 의도 → fatal X.
                    # bypass=None (DB query 실패) 도 fatal X — false positive 회피.
                    _fatal = (
                        _role_str == "app" and _enforce and _bypass is True
                    )

                    if _fatal:
                        # metric inc (counter — pull 모델은 process 종료 직후 scrape
                        # 실패 가능. log-based alert / Pod exit_code=99 가 보조).
                        try:
                            from src.common.metrics import (
                                inc_kms_worker_self_check_fatal,
                            )

                            inc_kms_worker_self_check_fatal(
                                "bypass_rls_true_app_mode"
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        # 구조화 fatal log — log aggregation (Loki/fluentd) 가 수집.
                        log.error(
                            "worker_rls_self_check_fatal",
                            current_user=str(row[0]),
                            bypassrls=_bypass,
                            kms_db_role=_role_str,
                            rls_enforce=_enforce,
                            reason="bypass_rls_true_app_mode",
                            hint=(
                                "KMS_DB_ROLE=app + RLS_ENFORCE=true 인데 worker 가 "
                                "BYPASSRLS role 로 connect — RLS 무력화 가능. "
                                "fatal exit (exit code 99). docker-compose 의 "
                                "KMS_DB_ROLE 환경변수 / DATABASE_URL_APP 의 user 확인."
                            ),
                        )
                        # GPT-5 §2 MUST: SystemExit 직전 log flush.
                        _flush_logging_handlers()
                        # GPT-5 §2 MUST: sys.exit 대신 raise SystemExit — asyncio.run
                        # 의 task 정리 보장 (consumer/producer 미할당 단계 — 누수 X).
                        raise SystemExit(99)
                    elif _enforce and _bypass:
                        # warning — RLS_ENFORCE=true + bypass=True 인데 role 이
                        # migration/super 인 경우 (의도된 break-glass). 운영 가시성 유지.
                        log.warning(
                            "worker_rls_self_check_bypass_active",
                            current_user=str(row[0]),
                            bypassrls=_bypass,
                            kms_db_role=_role_str,
                            rls_enforce=_enforce,
                            hint=(
                                "RLS_ENFORCE=true 인데 worker 가 BYPASSRLS role 로 "
                                "connect — KMS_DB_ROLE=app 권장 (현재 "
                                f"role={_role_str})."
                            ),
                        )
                    else:
                        log.info(
                            "worker_rls_self_check",
                            current_user=str(row[0]),
                            bypassrls=_bypass,
                            kms_db_role=_role_str,
                            rls_enforce=_enforce,
                        )
    except SystemExit:
        # D35 §2 — fatal 경로 SystemExit 은 propagate (asyncio.run 까지).
        raise
    except Exception as exc:  # noqa: BLE001
        # GPT-5 SHOULD: bypass=None / DB query 실패 시 구조화 필드.
        log.warning(
            "worker_rls_self_check_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )


def _extract_tenant_from_event(value: bytes) -> str | None:
    """D34 §1 — 이벤트 JSON 에서 tenant_id 추출 (bind_system_scope 진입용).

    이벤트 모델 (DocumentUploadedEvent / DocumentParsedEvent 등) 모두 ``tenant_id``
    필드 포함 (events.py). 추출 실패 시 None — bind_system_scope 가
    allow_null_tenant=True 로 진행 (SELECT 만 가능, write 시 RLS 차단).

    Args:
        value: kafka message payload (UTF-8 JSON).

    Returns:
        tenant_id string (UUID format) or None.
    """
    import json as _json

    try:
        raw = _json.loads(value)
        tid = raw.get("tenant_id", "")
        return str(tid) if tid else None
    except Exception:  # noqa: BLE001
        return None


async def _dispatch_message(topic: str, value: bytes, producer: Any) -> None:
    """토픽별 워커 디스패치.

    순차 처리 큐:
      uploaded 이벤트 → _doc_queue에 넣고 즉시 반환 (백그라운드 태스크가 순차 처리)
      중간 단계(parsed, blocked 등) → 컨슈머에서 즉시 처리
      blocked(embed 완료) → 완료 시그널 → 큐의 다음 문서 시작

    D34 §1: 본 함수 진입부에 bind_system_scope() wrap — RLSContext.scope='system' +
    tenant_id (event 에서 추출) 등록 → SQLAlchemy begin 훅이 SET LOCAL 발행 →
    alembic 079 의 system 분기 활성화.
    """
    import json as _json

    from src.pipeline.workers.embed_worker import handle_document_blocked, handle_document_chunked

    # 이벤트에서 document_id 추출
    doc_id = ""
    try:
        raw = _json.loads(value)
        doc_id = raw.get("document_id", "")
    except Exception:
        pass

    # D34 §1 — bind_system_scope wrap. tenant_id 추출 실패 시 allow_null_tenant=True
    # 로 SELECT 만 가능 (write 는 RLS 정책이 차단).
    _event_tid = _extract_tenant_from_event(value)
    async with bind_system_scope(_event_tid, allow_null_tenant=True):
        await _dispatch_message_inner(topic, value, producer, doc_id=doc_id)


async def _dispatch_message_inner(
    topic: str, value: bytes, producer: Any, *, doc_id: str
) -> None:
    """D34 §1 — bind_system_scope wrap 안에서 실행. 분리는 가독성 + RLS context 명확."""
    from src.pipeline.workers.embed_worker import handle_document_blocked, handle_document_chunked

    if topic in (
        TOPIC_DOCUMENT_UPLOADED,
        TOPIC_DOCUMENT_UPLOADED_SMALL,
        TOPIC_DOCUMENT_UPLOADED_LARGE,
    ):
        # D48 §1 — Early Divert: small 워커가 legacy 의 large 메시지 수신 시 즉시
        # large topic 으로 재발행하고 skip. small 큐가 막히지 않도록 보호.
        _profile = _resolve_worker_profile()
        if _should_divert_to_large(
            value_bytes=value, profile=_profile, incoming_topic=topic
        ):
            diverted = await _divert_to_large(value, producer)
            if diverted:
                log.info(
                    "early_divert_done",
                    incoming_topic=topic,
                    doc_id=doc_id,
                )
                # 본 메시지는 skip — large 워커가 새 토픽에서 처리.
                return
            # 재발행 실패 — fallback 으로 본 워커에서 처리 (drop 방지)
            log.warning("early_divert_fallback_local_process", doc_id=doc_id)

        # 큐에 넣고 즉시 반환 — 백그라운드 태스크가 순차 처리
        event = DocumentUploadedEvent.model_validate_json(value)
        await _doc_queue.put(event)  # type: ignore[union-attr]
        log.info(
            "pipeline_queue_enqueued",
            document_id=str(event.document_id),
            incoming_topic=topic,
            queue_size=_doc_queue.qsize(),  # type: ignore[union-attr]
        )

    elif topic == TOPIC_DOCUMENT_PARSED:
        # step_by_step: 파싱 완료 후 블럭 단계 진입 전 자동 일시정지
        if await _check_step_by_step_pause(doc_id, topic, value):
            return
        if doc_id and await _dedup_check(doc_id, "block"):
            return
        from src.pipeline.workers.block_worker import handle_document_parsed_for_blocks

        event = DocumentParsedEvent.model_validate_json(value)  # type: ignore[assignment]

        # Stage B-Core-4 (KMS-Plus): auto_classification — 블럭 파이프라인과 병렬.
        # non-critical, 실패해도 본류 안 막는다.
        # feature flag:
        #   - AGENT_AUTO_CLASSIFY=off → no-op (기존 호환)
        #   - ENABLE_INTENT_CLASSIFICATION=false → 등록 skip (Phase 1 T1.2)
        #   - LUCAS_PRODUCT=kms → agent_framework 미존재 환경 — skip
        # KMS-only 배포 시 agent_framework import 가 실패하지 않도록 외곽 try.
        _enable_classify = (
            os.environ.get("ENABLE_INTENT_CLASSIFICATION", "true").strip().lower()
            not in ("false", "0", "off", "no")
            and os.environ.get("LUCAS_PRODUCT", "full").strip().lower() != "kms"
        )
        if _enable_classify:
            try:
                from src.pipeline.workers.classify_worker import (
                    handle_document_parsed_for_classify,
                )

                asyncio.create_task(
                    handle_document_parsed_for_classify(event),
                    name=f"classify_{doc_id[:12] if doc_id else 'x'}",
                )
            except ImportError as exc:
                # agent_framework 미설치 환경 (KMS-only) — silent skip
                log.debug("classify_worker_skipped_no_agent_framework",
                          error=str(exc))
            except Exception as exc:  # noqa: BLE001
                log.debug("classify_worker_dispatch_failed", error=str(exc))

        try:
            await handle_document_parsed_for_blocks(event, producer, llm_client=_llm_client)
        finally:
            if doc_id:
                await _dedup_clear(doc_id, "block")

    elif topic == TOPIC_DOCUMENT_BLOCKED:
        # step_by_step: 블럭 완료 후 임베딩 단계 진입 전 자동 일시정지
        if await _check_step_by_step_pause(doc_id, topic, value):
            return
        if doc_id and await _dedup_check(doc_id, "embed"):
            # embed 가 다른 경로/중복 blocked 이벤트로 이미 진행 중 — 실제 임베딩은 키를 선점한
            # 경로가 수행한다. 단, 순차 큐 워커는 이 문서의 complete_evt 가 set 되기를 기다리므로
            # (main:_sequential_queue_processor) skip 시에도 반드시 완료 시그널을 보내야 한다.
            # 안 보내면 그 워커가 queue_timeout(파일크기 비례, 수~십수분)까지 블록 → 후속 문서 정체.
            await _signal_pipeline_complete(doc_id)
            return
        event = DocumentBlockedEvent.model_validate_json(value)  # type: ignore[assignment]
        try:
            await handle_document_blocked(event, producer)
        finally:
            if doc_id:
                await _dedup_clear(doc_id, "embed")
            # embed 완료 → 순차 큐에 완료 시그널
            await _signal_pipeline_complete(doc_id)

    elif topic == TOPIC_DOCUMENT_SPLIT:
        from src.pipeline.workers.split_worker import handle_document_split

        event = DocumentSplitEvent.model_validate_json(value)  # type: ignore[assignment]
        await handle_document_split(event, producer)

    elif topic == TOPIC_DOCUMENT_PART_READY:
        from src.pipeline.workers.block_worker import handle_document_part_ready

        event = DocumentPartReadyEvent.model_validate_json(value)  # type: ignore[assignment]
        # D58 §A — part 단위 dedup (doc_id+part_index+stage). 동일 group 내
        # producer 재시도/네트워크 중복 대비. small worker 구독 제거 (§A) 와
        # defense-in-depth.
        _part_doc_id = str(event.document_id)
        _part_idx = int(event.part_index)
        if await _dedup_check_part(_part_doc_id, _part_idx, "block_part"):
            return
        try:
            await handle_document_part_ready(event, producer, llm_client=_llm_client)
        finally:
            await _dedup_clear_part(_part_doc_id, _part_idx, "block_part")

    elif topic == TOPIC_DOCUMENT_PART_BLOCKED:
        from src.pipeline.workers.merge_worker import handle_document_part_blocked

        event = DocumentPartBlockedEvent.model_validate_json(value)  # type: ignore[assignment]
        # D58 §A — merge 단계도 part 단위 dedup. merge_worker.mark_part_completed
        # 는 이미 idempotent (split_tracker.py:94) 이지만 호출 자체를 차단해서
        # CPU/LLM 부하 절감.
        _part_doc_id = str(event.document_id)
        _part_idx = int(event.part_index)
        if await _dedup_check_part(_part_doc_id, _part_idx, "merge_part"):
            return
        try:
            await handle_document_part_blocked(event, producer, llm_client=_llm_client)
        finally:
            await _dedup_clear_part(_part_doc_id, _part_idx, "merge_part")

    elif topic == TOPIC_DOCUMENT_CHUNKED:
        event = DocumentChunkedEvent.model_validate_json(value)  # type: ignore[assignment]
        await handle_document_chunked(event, producer)  # type: ignore[arg-type]

    else:
        log.warning("unknown_topic", topic=topic)


def _extract_doc_id(msg: Any) -> str:
    """Kafka message payload (JSON bytes) 에서 document_id 추출.

    spec §3.2 — per-doc Lock 적용 전 doc_id 필요. 추출 실패 시 빈 문자열 반환
    (caller 가 lock acquire skip / 별도 처리).
    """
    import json as _json

    value = getattr(msg, "value", None)
    if value is None:
        return ""
    try:
        if isinstance(value, (bytes, bytearray)):
            raw = _json.loads(value)
        elif isinstance(value, str):
            raw = _json.loads(value)
        else:
            return ""
        return str(raw.get("document_id", "") or "")
    except Exception:  # noqa: BLE001
        return ""


async def _handle_consumed_message(
    msg: Any, producer: Any, consumer: Any, *, consumer_role: str = "unknown"
) -> None:
    """단일 메시지 dispatch + DLQ retry + offset commit.

    spec §3.1 — main/merge 두 consumer 가 공통으로 호출. per-doc Lock 은 caller 가
    감싼다 (spec §3.2 — 같은 doc 동시 진입 직렬화).

    spec §3.12 — consumer_role kwarg 로 observability 강화 (main/merge/dlq_scheduler 구분).
    """
    global _IN_PROGRESS_COUNT

    try:
        from aiokafka.structs import OffsetAndMetadata, TopicPartition
    except ImportError:
        OffsetAndMetadata = None  # type: ignore[assignment]
        TopicPartition = None  # type: ignore[assignment]

    # 큐 메트릭 갱신
    if _doc_queue is not None:
        PIPELINE_METRICS.pipeline_queue_size.set(_doc_queue.qsize())
    PIPELINE_METRICS.pipeline_active_workers.set(
        sum(1 for t in _queue_tasks if not t.done())
    )

    _IN_PROGRESS_COUNT += 1
    try:
        if _dlq_handler is None:
            log.error(
                "dlq_handler_not_initialized_drop",
                topic=msg.topic,
                offset=msg.offset,
                consumer_role=consumer_role,
            )
            return
        success = await _dlq_handler.handle_with_retry(
            topic=msg.topic,
            value=msg.value,
            offset=msg.offset,
            partition=msg.partition,
            dispatch_fn=_dispatch_message,
        )

        if success:
            log.debug(
                "message_processed_successfully",
                topic=msg.topic,
                offset=msg.offset,
                consumer_role=consumer_role,
            )
        else:
            log.warning(
                "message_sent_to_dlq_after_retries",
                topic=msg.topic,
                offset=msg.offset,
                consumer_role=consumer_role,
            )

        # D58 §B — Per-partition 명시 commit (success 또는 DLQ 확정 후).
        try:
            if OffsetAndMetadata is not None and TopicPartition is not None:
                tp = TopicPartition(msg.topic, msg.partition)
                await consumer.commit(
                    offsets={tp: OffsetAndMetadata(msg.offset + 1, "")}
                )
            else:
                await consumer.commit()
        except Exception as commit_exc:
            # CommitFailedError / RebalanceInProgress 시 재처리 허용 (commit X)
            log.warning(
                "offset_commit_failed",
                topic=msg.topic,
                offset=msg.offset,
                partition=msg.partition,
                error=str(commit_exc),
                consumer_role=consumer_role,
            )
    finally:
        _IN_PROGRESS_COUNT -= 1


async def _run_main_consumer(producer: Any) -> None:
    """spec §3.1 — main topics 구독 (uploaded/parsed/split/part_ready/chunked/blocked).

    spec §3.10 — merge consumer 가 ready 신호 보낼 때까지 wait.
    timeout 시 RuntimeError raise → supervisor 가 crash 로 인식하고 재시작 (fail-fast).
    shutdown-aware: SHUTDOWN_EVENT 가 readiness 보다 먼저 set 되면 조용히 return
    (GPT-5.5 verdict #1 — shutdown 중 불필요한 supervisor restart 차단).
    """
    ready_task = asyncio.create_task(_merge_consumer_ready.wait())
    shutdown_task = asyncio.create_task(_SHUTDOWN_EVENT.wait())
    try:
        done, pending = await asyncio.wait(
            [ready_task, shutdown_task],
            timeout=settings.PIPELINE_MERGE_READINESS_TIMEOUT_SEC,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for t in (ready_task, shutdown_task):
            if not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    if _SHUTDOWN_EVENT.is_set():
        log.info("main_consumer_skipped_due_to_shutdown", consumer_role="main")
        return
    if not _merge_consumer_ready.is_set():
        # timeout 그리고 shutdown 아님 → supervisor 재시작.
        raise RuntimeError(
            "merge consumer not ready within "
            f"{settings.PIPELINE_MERGE_READINESS_TIMEOUT_SEC}s"
        )

    profile = _resolve_worker_profile()
    topics = _resolve_main_topics(profile)
    # settings.KAFKA_CONSUMER_GROUP 가 이미 profile 포함 (env 의 aicm-pipeline-large)
    # 인 경우와 base prefix (aicm-pipeline) 인 경우 모두 동작하도록 endswith 가드.
    _base = settings.KAFKA_CONSUMER_GROUP
    main_group = _base if _base.endswith(f"-{profile}") else f"{_base}-{profile}"
    consumer = await _create_consumer(
        topics,
        group_id=main_group,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
        enable_auto_commit=False,
        # [수정 2026-06-01]
        # 이슈 내용: 대형 문서 처리가 무한 재처리 루프에 빠지고 status가 오락가락하며 승인 불가
        # 원인: main 컨슈머에 max_poll_interval_ms 미지정 → aiokafka 기본 5분. 단일 문서 처리(>5분)
        #       중 rebalance 발생 → offset commit 실패(IllegalGeneration) → 같은 메시지 재소비 루프
        # 수정 내용: merge 컨슈머처럼 max_poll_interval_ms/session_timeout_ms를 명시 (config의 MAIN_CONSUMER_*)
        max_poll_interval_ms=settings.MAIN_CONSUMER_MAX_POLL_INTERVAL_MS,
        session_timeout_ms=settings.MAIN_CONSUMER_SESSION_TIMEOUT_MS,
    )
    log.info(
        "pipeline_consumer_started",
        topics=topics,
        group=main_group,
        consumer_role="main",
        bootstrap=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    try:
        async for msg in consumer:
            if _SHUTDOWN_EVENT.is_set():
                log.info("shutdown_in_progress_stop_consuming", consumer_role="main")
                break
            doc_id = _extract_doc_id(msg)
            if doc_id:
                lock = await _acquire_doc_lock(doc_id)
                try:
                    async with lock:
                        await _handle_consumed_message(
                            msg, producer, consumer, consumer_role="main"
                        )
                finally:
                    _release_doc_lock(doc_id)
            else:
                # doc_id 추출 실패 — lock 없이 처리 (legacy 호환).
                await _handle_consumed_message(
                    msg, producer, consumer, consumer_role="main"
                )
    finally:
        try:
            await consumer.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("main_consumer_stop_failed", error=str(exc), consumer_role="main")


async def _run_merge_consumer(producer: Any) -> None:
    """spec §3.1 — merge topics (part_blocked) 만 구독.

    spec §3.10 — listener 가 partition assign 시 baseline commit + ready set.
    small/legacy 는 merge topic 없음 → ready set 즉시 후 종료 (main barrier 통과).
    """
    _merge_consumer_ready.clear()
    profile = _resolve_worker_profile()
    topics = _resolve_merge_topics(profile)
    if not topics:
        # small/legacy — merge consumer 없음. ready set 해서 main barrier 통과.
        _merge_consumer_ready.set()
        log.info(
            "merge_consumer_skipped",
            profile=profile,
            reason="no_merge_topics",
            consumer_role="merge",
        )
        # SHUTDOWN_EVENT 까지 대기 (silent return 시 supervisor 가 crash 취급 재시작).
        await _SHUTDOWN_EVENT.wait()
        return

    # main_group 산출 (endswith 가드와 동일) + merge suffix
    _base = settings.KAFKA_CONSUMER_GROUP
    _main_g = _base if _base.endswith(f"-{profile}") else f"{_base}-{profile}"
    merge_group = f"{_main_g}{settings.KAFKA_CONSUMER_GROUP_MERGE_SUFFIX}"
    consumer = await _create_consumer(
        [],  # subscribe 로 listener 등록
        group_id=merge_group,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
        enable_auto_commit=False,
        max_poll_interval_ms=settings.MERGE_CONSUMER_MAX_POLL_INTERVAL_MS,
        session_timeout_ms=settings.MERGE_CONSUMER_SESSION_TIMEOUT_MS,
    )
    consumer.subscribe(topics=topics, listener=_make_merge_readiness_listener(consumer))
    log.info(
        "pipeline_consumer_started",
        topics=topics,
        group=merge_group,
        consumer_role="merge",
        bootstrap=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    try:
        async for msg in consumer:
            if _SHUTDOWN_EVENT.is_set():
                log.info("shutdown_in_progress_stop_consuming", consumer_role="merge")
                break
            doc_id = _extract_doc_id(msg)
            if doc_id:
                lock = await _acquire_doc_lock(doc_id)
                try:
                    async with lock:
                        await _handle_consumed_message(
                            msg, producer, consumer, consumer_role="merge"
                        )
                finally:
                    _release_doc_lock(doc_id)
            else:
                await _handle_consumed_message(
                    msg, producer, consumer, consumer_role="merge"
                )
    finally:
        try:
            await consumer.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("merge_consumer_stop_failed", error=str(exc), consumer_role="merge")


async def _wait_for_in_progress(timeout: float = _SHUTDOWN_TIMEOUT_SECONDS) -> None:
    """진행 중인 메시지 처리가 완료될 때까지 대기한다."""
    global _IN_PROGRESS_COUNT

    if _IN_PROGRESS_COUNT <= 0:
        log.info("no_messages_in_progress")
        return

    log.info(
        "waiting_for_in_progress_messages",
        count=_IN_PROGRESS_COUNT,
        timeout_seconds=timeout,
    )

    start = asyncio.get_event_loop().time()
    while _IN_PROGRESS_COUNT > 0:
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed >= timeout:
            log.warning(
                "shutdown_timeout_exceeded",
                remaining_messages=_IN_PROGRESS_COUNT,
                timeout_seconds=timeout,
            )
            break
        await asyncio.sleep(0.5)
        log.debug("waiting_for_in_progress", count=_IN_PROGRESS_COUNT)

    log.info("in_progress_wait_complete", remaining=_IN_PROGRESS_COUNT)


async def run_consumer_loop() -> None:
    """메인 컨슈머 루프 (DLQ + graceful shutdown 통합)."""
    global _dlq_handler, _llm_client, _IN_PROGRESS_COUNT, _doc_queue, _queue_tasks

    setup_logging()

    # Prometheus 메트릭 HTTP 서버 시작 (포트 8001)
    start_pipeline_metrics_server()

    _llm_client = await _init_llm_client()

    # D48 §1 — 프로파일별 topic 구독 + 동시성 결정
    # D58 §A — 전체 topic 분리 (small 은 split/part_* 제외 → 각 part 2회 처리 차단)
    _profile = _resolve_worker_profile()
    _uploaded_topics = _resolve_uploaded_topics_for_profile(_profile)
    topics = _resolve_topics_for_profile(_profile)
    log.info(
        "worker_profile_resolved",
        profile=_profile,
        uploaded_topics=_uploaded_topics,
        all_topics=topics,
        topic_count=len(topics),
        parallel_workers=_resolve_parallel_workers(_profile),
    )

    producer = await _create_producer()

    # D34 §2 — worker self-check (GPT-5 권고). KMS_DB_ROLE / current_user 확인.
    # KMS_DB_ROLE_WORKER=app + RLS_ENFORCE=true 운영 환경에서 kms_app + bypassrls=False
    # 확인. migration role 인 경우 BYPASSRLS=true 로그 — RLS 무력화 인식.
    await _worker_rls_self_check()

    # ── 시작 시 중단된 문서 자동 복구 (컨슈머 루프 시작 전 1회) ──
    # D34 §1 — bind_system_scope wrap. tenant 파악 전 SELECT 만 — allow_null_tenant=True.
    try:
        async with bind_system_scope(None, allow_null_tenant=True):
            recovered = await recover_stale_documents(producer)
        if recovered:
            log.info("startup_recovery_complete", recovered_count=recovered)
    except Exception as exc:
        log.warning(
            "startup_recovery_failed",
            error=str(exc),
            hint="복구 실패는 워커 시작을 차단하지 않습니다.",
        )

    # spec §3.1, §3.8 — main + merge 두 consumer instance 로 분리.
    # 각 instance 별 _create_consumer 는 _run_main_consumer / _run_merge_consumer
    # 내부에서 호출 (group_id 가 다름 — main: -<profile>, merge: -<profile>-merge).

    # DLQ 핸들러 초기화
    _dlq_handler = DLQHandler(producer=producer)

    # DLQ 자동 재처리 스케줄러 시작 (독립 백그라운드 태스크)
    global _dlq_scheduler_task
    _dlq_scheduler_task = asyncio.create_task(
        dlq_scheduler_loop(producer, _SHUTDOWN_EVENT),
        name="dlq-scheduler",
    )
    log.info("dlq_scheduler_task_created")

    # 병렬 처리 큐 + N개 워커 풀 시작 (B200 동시 4채널 활용)
    # D48 §1 — 프로파일별 동시성: small=4, large=1, legacy=4.
    _doc_queue = asyncio.Queue()
    _parallel_count = _resolve_parallel_workers(_profile)
    _queue_tasks = [
        asyncio.create_task(
            _sequential_queue_processor(producer, worker_id=i),
            name=f"pipeline-worker-{_profile}-{i}",
        )
        for i in range(_parallel_count)
    ]
    log.info(
        "parallel_queue_workers_started",
        profile=_profile,
        worker_count=_parallel_count,
    )

    # Phase 1 T1.5 — KMS / Agent worker registry 분리.
    # LUCAS_PRODUCT env (default=full) 기반 분기:
    #   - full: registry_kms + registry_agent 양쪽 등록 (기존 동작)
    #   - kms : registry_agent skip — reminder_worker import 안 함
    # ImportError 발생해도 graceful — Lucas-KMS 단독 환경 안전망.
    _lucas_product = (os.getenv("LUCAS_PRODUCT") or "full").strip().lower()

    # KMS registry — 항상 활성화 (분리 후에도 KMS 단독 배포의 진입점).
    _kms_bg_tasks: list[asyncio.Task] = []
    try:
        from src.pipeline.workers import registry_kms as _kms_registry

        _kms_bg_tasks = _kms_registry.start_background_tasks(_SHUTDOWN_EVENT)
        log.info(
            "kms_registry_loaded",
            product=_lucas_product,
            workers=list(_kms_registry.list_workers()),
            bg_tasks=len(_kms_bg_tasks),
        )
    except Exception as _ke:  # noqa: BLE001
        log.warning("kms_registry_load_failed", error=str(_ke))

    # Agent registry — LUCAS_PRODUCT=kms 시 skip.
    _agent_bg_tasks: list[asyncio.Task] = []
    if _lucas_product == "kms":
        log.info(
            "agent_registry_skipped",
            product=_lucas_product,
            reason="LUCAS_PRODUCT=kms — agent worker 미등록 (Lucas-KMS 단독 배포)",
        )
    else:
        try:
            from src.pipeline.workers import registry_agent as _agent_registry

            _agent_bg_tasks = _agent_registry.start_background_tasks(_SHUTDOWN_EVENT)
            log.info(
                "agent_registry_loaded",
                product=_lucas_product,
                workers=list(_agent_registry.list_workers()),
                bg_tasks=len(_agent_bg_tasks),
            )
        except Exception as _ae:  # noqa: BLE001
            # agent_framework 미포함 환경에서도 KMS 가 죽지 않도록 graceful.
            log.warning(
                "agent_registry_load_failed",
                error=str(_ae),
                hint="agent_framework 미포함 가능 — KMS 단독 모드라면 LUCAS_PRODUCT=kms 권장",
            )

    log.info(
        "pipeline_consumer_dispatch_starting",
        main_topics=_resolve_main_topics(_profile),
        merge_topics=_resolve_merge_topics(_profile),
        group_prefix=settings.KAFKA_CONSUMER_GROUP,
        profile=_profile,
        bootstrap=settings.KAFKA_BOOTSTRAP_SERVERS,
    )

    # spec §3.7, §3.8 — main + merge 두 consumer supervisor 동시 실행.
    # supervisor 가 SHUTDOWN_EVENT 따라 종료. ALL_COMPLETED 까지 대기.
    t_merge = asyncio.create_task(
        _consumer_supervisor("merge", lambda: _run_merge_consumer(producer)),
        name="consumer_merge_supervisor",
    )
    t_main = asyncio.create_task(
        _consumer_supervisor("main", lambda: _run_main_consumer(producer)),
        name="consumer_main_supervisor",
    )

    try:
        await asyncio.wait(
            [t_main, t_merge],
            return_when=asyncio.ALL_COMPLETED,
        )
    finally:
        log.info("consumer_shutting_down")

        # Graceful shutdown: 진행 중인 메시지 완료 대기
        await _wait_for_in_progress()

        # DLQ 스케줄러 정리 (_SHUTDOWN_EVENT 로 자연 종료 대기)
        if _dlq_scheduler_task is not None and not _dlq_scheduler_task.done():
            try:
                await asyncio.wait_for(_dlq_scheduler_task, timeout=5.0)
            except asyncio.TimeoutError:
                _dlq_scheduler_task.cancel()
                try:
                    await _dlq_scheduler_task
                except asyncio.CancelledError:
                    pass
            except Exception:
                pass
            log.info("dlq_scheduler_stopped")

        # 병렬 큐 워커 풀 정리
        for task in _queue_tasks:
            if not task.done():
                task.cancel()
        for task in _queue_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        log.info("queue_workers_stopped", worker_count=len(_queue_tasks))

        # supervisor task 정리 (이미 종료됐어야 정상, 안전 cancel)
        for sup_task in (t_main, t_merge):
            if not sup_task.done():
                sup_task.cancel()
                try:
                    await sup_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
        log.info("consumer_supervisors_stopped")

        if producer:
            await producer.stop()
            log.info("producer_stopped")

        log.info("graceful_shutdown_complete")


def main() -> None:
    """CLI 진입점."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    asyncio.run(run_consumer_loop())


if __name__ == "__main__":
    main()

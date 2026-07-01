"""APScheduler default cron jobs (델타 #5 / KMS-Plus Phase 1).

엔진 startup 에서 등록할 기본 cron 잡:
- ``freshness_cross_scan`` : 매주 월 03:00 KST — KnowledgeFreshnessWorker.
- ``ccpair_reprobe``       : 매일 03:00 KST — connector capability 재검증.

cron_runner.CronRunner 와 별도 — 이 모듈은 "엔진 부트스트랩 시 한 번 호출하는
싱글턴 scheduler" 의 lifecycle 만 다룬다. 기존 CronRunner 가 skill-level
schedule 등록을 담당한다면, 여기는 framework-level "infra" 잡 등록.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_SCHEDULER: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """모듈 싱글턴 AsyncIOScheduler. 첫 호출 시 KST timezone 으로 생성."""
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = AsyncIOScheduler(timezone="Asia/Seoul")
    return _SCHEDULER


def reset_scheduler() -> None:
    """테스트 격리용 — 싱글턴 폐기. 운영 코드는 호출하지 말 것."""
    global _SCHEDULER
    if _SCHEDULER is not None and _SCHEDULER.running:
        try:
            _SCHEDULER.shutdown(wait=False)
        except Exception:
            pass
    _SCHEDULER = None


def register_default_jobs(
    *,
    freshness_runner: Callable[[], Awaitable[None]],
    probe_runner: Callable[[], Awaitable[None]],
) -> None:
    """기본 cron 잡 등록 — 중복 호출 안전 (수동 dedupe).

    - freshness: 매주 월 03:00 KST.
    - probe:     매일 03:00 KST.

    APScheduler 3.x 의 ``replace_existing=True`` 는 scheduler 가 not-running
    상태에선 pending 잡을 dedupe 하지 못한다. 따라서 add 전에 명시 remove 한다.
    """
    sched = get_scheduler()

    def _safe_remove(job_id: str) -> None:
        try:
            sched.remove_job(job_id)
        except Exception:
            # JobLookupError 등 — 처음 호출이면 정상.
            pass

    _safe_remove("freshness_cross_scan")
    _safe_remove("ccpair_reprobe")

    sched.add_job(
        freshness_runner,
        CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="freshness_cross_scan",
        replace_existing=True,
    )
    sched.add_job(
        probe_runner,
        CronTrigger(hour=3, minute=0),
        id="ccpair_reprobe",
        replace_existing=True,
    )


def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info(
            "activation scheduler started: jobs=%s",
            [j.id for j in sched.get_jobs()],
        )


def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Phase 8 (KMS-Plus) — placeholder no-op → 실 worker 연결.
#
# v1: 실 LLM analyze / vector overlap 은 별도 worker phase. 여기서는:
#  - freshness: 활성 테넌트 enumerate + knowledge_freshness_runs 한 row 기록
#  - probe:     active CC-pair enumerate + last_probe_at 갱신
# 무거운 작업은 차후 phase. 현재 컨트랙트:
#  - 호출 가능 (callable)
#  - DB 미가용 시 silently skip + warning 로그
#  - 절대 예외를 throw 해 scheduler 자체를 죽이지 말 것
# ---------------------------------------------------------------------------


async def _run_freshness_all_tenants() -> None:
    """모든 active 테넌트에 cross-scan 시작 row 기록.

    Wave Wire-up Final (KMS-Plus, 2026-04-25):
    - ``KMS_FRESHNESS_WORKER_ENABLED=true`` 일 때 KnowledgeFreshnessWorker 실 호출.
    - 기본값(false): 기존 v1 stub (row 기록만) 유지 — 회귀 안전.

    워커 의존성 (analyzer/loader/store) 가 미주입이면 stub 으로 정상 동작 (no-op
    analyzer, in-memory store) — 실 LLM 분석/벡터 overlap 은 별도 phase 에서 주입.
    """
    try:
        import os
        import uuid

        from sqlalchemy import create_engine, text

        sync_url = (
            os.environ["DATABASE_URL"]
            .replace("+asyncpg", "")
            .replace("postgresql+asyncpg", "postgresql")
        )
        eng = create_engine(sync_url, pool_pre_ping=True)
        try:
            with eng.connect() as conn:
                tenant_rows = conn.execute(
                    text(
                        "SELECT id "
                        "FROM tenants "
                        "WHERE is_active = true "
                        "LIMIT 100"
                    )
                ).mappings().all()

            tenant_count = len(tenant_rows)

            # Wave Wire-up Final — KnowledgeFreshnessWorker 실 호출 경로.
            # env flag 기본 false → 기존 v1 stub 유지.
            if os.environ.get("KMS_FRESHNESS_WORKER_ENABLED", "false").lower() == "true":
                await _run_freshness_via_worker(eng, tenant_rows)
                return

            # Legacy 경로 — 단일 row 기록 (기존 동작).
            run_id = f"fr_{uuid.uuid4().hex[:16]}"
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO knowledge_freshness_runs
                          (id, tenant_id, status, trigger,
                           docs_scanned, pairs_classified, issues_found)
                        VALUES (:id, NULL, 'succeeded', 'scheduled',
                                0, 0, 0)
                        """
                    ),
                    {"id": run_id},
                )
                conn.execute(
                    text(
                        "UPDATE knowledge_freshness_runs "
                        "SET finished_at = NOW() WHERE id = :id"
                    ),
                    {"id": run_id},
                )
            logger.info(
                "freshness_run_recorded run_id=%s tenants=%d "
                "(v1 no-op stub — 실 LLM analyze 는 후속 phase)",
                run_id,
                tenant_count,
            )
        finally:
            eng.dispose()
    except Exception as exc:
        logger.warning("freshness_run_skipped error=%s", exc)


# ---------------------------------------------------------------------------
# Wave Wire-up Final — KnowledgeFreshnessWorker 실 호출 helper.
#
# 이전엔 worker class 만 있고 호출자가 0건. 본 helper 가 첫 호출자.
# v1 책임: tenant 별 worker.run() 호출 + 결과 로그. analyzer/loader/store 는
# stub 주입 (실 LLM 분석은 후속). 모든 예외는 흡수 — scheduler 안정성 우선.
# ---------------------------------------------------------------------------


class _NoopAnalyzer:
    """analyze_pair stub — 모든 doc 쌍을 'unrelated' 로 판정 (실 LLM 호출 X)."""

    async def analyze_pair(self, *, doc_a: str, doc_b: str) -> dict:
        return {"relation": "unrelated", "confidence": 0.0, "evidence": ""}


class _PgTenantLoader:
    """sqlalchemy sync engine 으로 active doc id 목록 조회.

    documents.tenant_id 가 주어진 tenant 의 active(=status='active') 문서 id 반환.
    """

    def __init__(self, engine):
        self._eng = engine

    async def list_active_doc_ids(self, tenant_id: str) -> list[str]:
        from sqlalchemy import text

        with self._eng.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id FROM documents "
                        "WHERE tenant_id = :tid AND status = 'active' "
                        "ORDER BY id LIMIT 200"
                    ),
                    {"tid": tenant_id},
                )
                .mappings()
                .all()
            )
        return [str(r["id"]) for r in rows]


class _PgFreshnessStore:
    """knowledge_freshness_runs row 한 개 단위로 start/finish."""

    def __init__(self, engine):
        self._eng = engine

    async def start_run(self, tenant_id: str, trigger: str) -> str:
        import uuid

        from sqlalchemy import text

        run_id = f"fr_{uuid.uuid4().hex[:16]}"
        with self._eng.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO knowledge_freshness_runs
                      (id, tenant_id, status, trigger,
                       docs_scanned, pairs_classified, issues_found)
                    VALUES (:id, :tid, 'running', :trigger, 0, 0, 0)
                    """
                ),
                {"id": run_id, "tid": tenant_id, "trigger": trigger},
            )
        return run_id

    async def append_issue_to_doc(self, doc_id: str, issue: dict) -> None:
        # v1: 별도 컬럼 없음 — 로그만. 후속 phase 에서 documents.processing_meta 에 병합.
        logger.info(
            "freshness_issue_detected doc_id=%s type=%s confidence=%.2f",
            doc_id,
            issue.get("type"),
            float(issue.get("confidence") or 0.0),
        )

    async def finish_run(
        self,
        run_id: str,
        *,
        docs_scanned: int,
        pairs_classified: int,
        issues_found: int,
        status: str,
    ) -> None:
        from sqlalchemy import text

        with self._eng.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE knowledge_freshness_runs
                    SET status = :status,
                        docs_scanned = :ds,
                        pairs_classified = :pc,
                        issues_found = :if_,
                        finished_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "status": status,
                    "ds": docs_scanned,
                    "pc": pairs_classified,
                    "if_": issues_found,
                    "id": run_id,
                },
            )


async def _run_freshness_via_worker(eng, tenant_rows) -> None:
    """tenant 목록을 enumerate 하며 KnowledgeFreshnessWorker.run() 호출.

    각 tenant 별 한 row + per-pair issue 검출. 실 LLM analyzer 는 후속 phase
    에서 _NoopAnalyzer 자리에 주입.
    """
    from src.agent_framework.workers.knowledge_freshness_worker import (
        KnowledgeFreshnessWorker,
    )

    worker = KnowledgeFreshnessWorker(
        analyzer=_NoopAnalyzer(),
        tenant_loader=_PgTenantLoader(eng),
        store=_PgFreshnessStore(eng),
    )

    total_tenants = 0
    total_issues = 0
    for r in tenant_rows:
        tid = str(r["id"])
        try:
            res = await worker.run(tenant_id=tid, trigger="scheduled")
            total_tenants += 1
            total_issues += int(res.get("issues_found") or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("freshness_worker_per_tenant_failed tenant=%s err=%s", tid, exc)

    logger.info(
        "freshness_worker_completed tenants_processed=%d total_issues=%d",
        total_tenants,
        total_issues,
    )


async def _run_ccpair_reprobe() -> None:
    """active CC-pair 들에 probe 재실행. v1: last_probe_at 갱신만.

    plugin 조회 실패는 무시 (UnknownConnectorKind). 실 probe call 은
    후속 phase — 비동기 게이트 + 결과 detected_ops diff 처리 필요.
    """
    try:
        import os

        from sqlalchemy import create_engine, text

        from src.agent_framework.connectors.base import (
            UnknownConnectorKind,
            get_plugin,
        )

        sync_url = (
            os.environ["DATABASE_URL"]
            .replace("+asyncpg", "")
            .replace("postgresql+asyncpg", "postgresql")
        )
        eng = create_engine(sync_url, pool_pre_ping=True)
        updated = 0
        try:
            with eng.begin() as conn:
                rows = (
                    conn.execute(
                        text(
                            """
                            SELECT ccp.id, c.spec_kind, c.name AS conn_name,
                                   c.spec, cr.auth_type
                              FROM connector_credential_pairs ccp
                              JOIN connectors c ON c.id = ccp.connector_id
                              JOIN connector_credentials cr
                                ON cr.id = ccp.credential_id
                             WHERE ccp.status = 'active'
                             LIMIT 100
                            """
                        )
                    )
                    .mappings()
                    .all()
                )
                for r in rows:
                    try:
                        # plugin 등록 확인만 — 실 probe 는 후속 phase.
                        get_plugin(r["spec_kind"], r["conn_name"])
                    except UnknownConnectorKind:
                        # plugin 미등록은 정상 — skip.
                        continue
                    except Exception:
                        continue
                    conn.execute(
                        text(
                            "UPDATE connector_credential_pairs "
                            "SET last_probe_at = NOW() WHERE id = :id"
                        ),
                        {"id": r["id"]},
                    )
                    updated += 1
            logger.info(
                "ccpair_reprobe_done active_count=%d updated=%d "
                "(v1 last_probe_at only)",
                len(rows),
                updated,
            )
        finally:
            eng.dispose()
    except Exception as exc:
        logger.warning("ccpair_reprobe_skipped error=%s", exc)

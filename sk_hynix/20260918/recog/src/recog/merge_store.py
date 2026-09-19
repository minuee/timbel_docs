"""SQLite record store for merge jobs.

Two jobs in one file:

1. **Durability** — a restart no longer loses work. Jobs that were mid-flight
   are re-queued from the stored request; finished ones answer status queries
   exactly as before.
2. **History** — every merge that ever ran stays queryable for 90 days, so
   volume, timings and failure causes can be inspected without the server.

`sqlite3` ships with Python, so this adds no pip dependency. The database lives
on the bind-mounted runtime volume and therefore survives container restarts.

    sqlite3 runtime/merge.db "SELECT room_no, status, finished_at FROM merge_jobs"
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS merge_jobs (
    job_id        TEXT PRIMARY KEY,
    room_no       TEXT NOT NULL,
    source        TEXT NOT NULL,
    status        TEXT NOT NULL,
    stage         TEXT,
    progress      INTEGER NOT NULL DEFAULT 0,
    request       TEXT NOT NULL,
    output        TEXT,
    alignment     TEXT,
    timing        TEXT,
    error         TEXT,
    result_path   TEXT,
    retried_from  TEXT,
    requeue_count INTEGER NOT NULL DEFAULT 0,
    accepted_at   TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_merge_room_no     ON merge_jobs(room_no);
CREATE INDEX IF NOT EXISTS idx_merge_status      ON merge_jobs(status);
CREATE INDEX IF NOT EXISTS idx_merge_accepted_at ON merge_jobs(accepted_at);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_COLUMNS = (
    "job_id", "room_no", "source", "status", "stage", "progress", "request",
    "output", "alignment", "timing", "error", "result_path", "retried_from",
    "requeue_count", "accepted_at", "started_at", "finished_at",
)

_UPSERT = f"""
INSERT INTO merge_jobs ({", ".join(_COLUMNS)})
VALUES ({", ".join("?" for _ in _COLUMNS)})
ON CONFLICT(job_id) DO UPDATE SET
    status        = excluded.status,
    stage         = excluded.stage,
    progress      = excluded.progress,
    output        = excluded.output,
    alignment     = excluded.alignment,
    timing        = excluded.timing,
    error         = excluded.error,
    result_path   = excluded.result_path,
    requeue_count = excluded.requeue_count,
    started_at    = excluded.started_at,
    finished_at   = excluded.finished_at
"""


def _dumps(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _loads(value):
    return None if value is None else json.loads(value)


class MergeRecordStore:
    """Thread-safe SQLite access for the merge worker pool.

    A connection is opened per operation rather than shared: the write volume is
    a handful of rows per job, and it keeps the worker threads from having to
    coordinate cursor state. WAL mode lets readers proceed during a write.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Serializes writers. SQLite handles this itself, but taking the lock
        # locally turns lock contention into a wait instead of a "database is
        # locked" error under the default 5s timeout.
        self._write_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._write_lock, closing(self._connect()) as connection, connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # ------------------------------------------------------------------ write

    def save(self, record: dict) -> None:
        """Insert or update one job row. Called on every state transition."""
        values = (
            record["job_id"],
            record["room_no"],
            record["source"],
            record["status"],
            record.get("stage"),
            record.get("progress", 0),
            _dumps(record["request"]),
            _dumps(record.get("output")),
            _dumps(record.get("alignment")),
            _dumps(record.get("timing")),
            _dumps(record.get("error")),
            record.get("result_path"),
            record.get("retried_from"),
            record.get("requeue_count", 0),
            record["accepted_at"],
            record.get("started_at"),
            record.get("finished_at"),
        )
        with self._write_lock, closing(self._connect()) as connection, connection:
            connection.execute(_UPSERT, values)

    def purge_older_than(self, days: int) -> int:
        """Drop finished rows past the retention window. Returns rows removed."""
        if days <= 0:
            return 0
        with self._write_lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                DELETE FROM merge_jobs
                 WHERE finished_at IS NOT NULL
                   AND finished_at < datetime('now', ?)
                """,
                (f"-{int(days)} days",),
            )
            return cursor.rowcount or 0

    # ------------------------------------------------------------------- read

    @staticmethod
    def _to_record(row: sqlite3.Row) -> dict:
        return {
            "job_id": row["job_id"],
            "room_no": row["room_no"],
            "source": row["source"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": row["progress"],
            "request": _loads(row["request"]),
            "output": _loads(row["output"]),
            "alignment": _loads(row["alignment"]),
            "timing": _loads(row["timing"]),
            "error": _loads(row["error"]),
            "result_path": row["result_path"],
            "retried_from": row["retried_from"],
            "requeue_count": row["requeue_count"],
            "accepted_at": row["accepted_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    def get(self, job_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM merge_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def load_unfinished(self) -> list[dict]:
        """Rows that were mid-flight when the process stopped."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM merge_jobs
                 WHERE status IN ('WAITING', 'RUNNING')
                 ORDER BY accepted_at
                """
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def load_recent_finished(self, limit: int = 500) -> list[dict]:
        """Recently completed rows, warmed into memory so status polls stay fast."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM merge_jobs
                 WHERE status IN ('DONE', 'ERROR')
                 ORDER BY finished_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def recent(self, *, room_no: str | None = None, limit: int = 50) -> list[dict]:
        """Newest-first history, optionally narrowed to one room."""
        limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM merge_jobs"
        params: list = []
        if room_no:
            query += " WHERE room_no = ?"
            params.append(room_no)
        query += " ORDER BY accepted_at DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._to_record(row) for row in rows]

    def active_room_numbers(self) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT room_no FROM merge_jobs WHERE status IN ('WAITING','RUNNING')"
            ).fetchall()
        return {row["room_no"] for row in rows}

    def stats(self) -> dict:
        """Counts by status — used by /metrics and for a quick health read."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM merge_jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: row["total"] for row in rows}

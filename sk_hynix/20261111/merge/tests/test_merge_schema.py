"""merge.db 스키마 마이그레이션.

이미지를 새 버전으로 갈아끼울 때 merge.db 는 호스트에 그대로 남는다.
그래서 새 버전이 컬럼을 추가하면 기존 파일에도 그 컬럼이 생겨야 하고,
쌓여 있던 병합 이력은 하나도 사라지면 안 된다.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from recog import merge_store
from recog.merge_store import MergeRecordStore


def _record(job_id: str, room_no: str = "R-1") -> dict:
    return {
        "job_id": job_id,
        "room_no": room_no,
        "source": "upload",
        "status": "DONE",
        "stage": None,
        "progress": 100,
        "request": {},
        "output": None,
        "alignment": None,
        "timing": None,
        "error": None,
        "result_path": None,
        "retried_from": None,
        "requeue_count": 0,
        "accepted_at": "2026-09-21T00:00:00Z",
        "started_at": None,
        "finished_at": "2026-09-21T00:00:01Z",
    }


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Path(tempfile.mkdtemp()) / "merge.db"
        self._version = merge_store.SCHEMA_VERSION
        self._migrations = dict(merge_store._MIGRATIONS)  # noqa: SLF001

    def tearDown(self) -> None:
        merge_store.SCHEMA_VERSION = self._version
        merge_store._MIGRATIONS = self._migrations  # noqa: SLF001

    # ------------------------------------------------------------- helpers

    def _columns(self) -> list[str]:
        with sqlite3.connect(self.db) as con:
            return [row[1] for row in con.execute("PRAGMA table_info(merge_jobs)")]

    def _version_in_db(self) -> str | None:
        with sqlite3.connect(self.db) as con:
            row = con.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        return None if row is None else row[0]

    def _rows(self) -> int:
        with sqlite3.connect(self.db) as con:
            return con.execute("SELECT COUNT(*) FROM merge_jobs").fetchone()[0]

    def _bump_to(self, version: int, *migrations: tuple[int, str]) -> None:
        merge_store.SCHEMA_VERSION = version
        merge_store._MIGRATIONS = {v: (sql,) for v, sql in migrations}  # noqa: SLF001

    # --------------------------------------------------------------- tests

    def test_fresh_database_records_current_version(self) -> None:
        MergeRecordStore(self.db)
        self.assertEqual(self._version_in_db(), str(merge_store.SCHEMA_VERSION))

    def test_reopening_unchanged_database_is_a_noop(self) -> None:
        MergeRecordStore(self.db).save(_record("mrg_a"))
        columns = self._columns()
        MergeRecordStore(self.db)
        self.assertEqual(self._columns(), columns)
        self.assertEqual(self._rows(), 1)

    def test_new_column_is_added_to_an_existing_database(self) -> None:
        MergeRecordStore(self.db).save(_record("mrg_a"))
        self.assertNotIn("uploaded_by", self._columns())

        self._bump_to(2, (2, "ALTER TABLE merge_jobs ADD COLUMN uploaded_by TEXT"))
        MergeRecordStore(self.db)

        self.assertIn("uploaded_by", self._columns())
        self.assertEqual(self._version_in_db(), "2")
        self.assertEqual(self._rows(), 1, "쌓여 있던 이력은 유지되어야 한다")

    def test_migration_does_not_run_twice(self) -> None:
        MergeRecordStore(self.db).save(_record("mrg_a"))
        self._bump_to(2, (2, "ALTER TABLE merge_jobs ADD COLUMN uploaded_by TEXT"))
        MergeRecordStore(self.db)
        # 같은 이미지로 컨테이너를 다시 띄우는 상황. 두 번째 ALTER 는 duplicate 로 실패한다.
        MergeRecordStore(self.db)
        self.assertEqual(self._columns().count("uploaded_by"), 1)

    def test_several_versions_are_applied_in_order(self) -> None:
        """0.0.1 로 뜬 서버를 0.0.3 으로 바로 올리는 경우 (중간 버전을 건너뜀)."""
        MergeRecordStore(self.db).save(_record("mrg_a"))
        self._bump_to(
            3,
            (2, "ALTER TABLE merge_jobs ADD COLUMN uploaded_by TEXT"),
            (3, "ALTER TABLE merge_jobs ADD COLUMN device_id TEXT"),
        )
        MergeRecordStore(self.db)

        columns = self._columns()
        self.assertIn("uploaded_by", columns)
        self.assertIn("device_id", columns)
        self.assertEqual(self._version_in_db(), "3")
        self.assertEqual(self._rows(), 1)

    def test_rollback_to_an_older_image_still_starts(self) -> None:
        """0.0.2 가 올려놓은 DB 에 0.0.1 이미지를 다시 띄우는 경우."""
        MergeRecordStore(self.db).save(_record("mrg_a"))
        self._bump_to(2, (2, "ALTER TABLE merge_jobs ADD COLUMN uploaded_by TEXT"))
        MergeRecordStore(self.db)

        merge_store.SCHEMA_VERSION = 1
        merge_store._MIGRATIONS = {}  # noqa: SLF001
        store = MergeRecordStore(self.db)  # 죽지 않아야 한다

        self.assertEqual(self._version_in_db(), "2", "옛 코드가 버전을 되돌리면 안 된다")
        store.save(_record("mrg_b", room_no="R-2"))
        self.assertEqual(self._rows(), 2, "옛 코드도 계속 쓸 수 있어야 한다")

    def test_database_without_a_version_row_is_treated_as_v1(self) -> None:
        """schema_meta 가 없던 시절의 파일도 마이그레이션 대상이 되어야 한다."""
        MergeRecordStore(self.db).save(_record("mrg_a"))
        with sqlite3.connect(self.db) as con:
            con.execute("DELETE FROM schema_meta WHERE key='version'")

        self._bump_to(2, (2, "ALTER TABLE merge_jobs ADD COLUMN uploaded_by TEXT"))
        MergeRecordStore(self.db)

        self.assertIn("uploaded_by", self._columns())
        self.assertEqual(self._version_in_db(), "2")
        self.assertEqual(self._rows(), 1)

    def test_a_broken_migration_fails_loudly(self) -> None:
        MergeRecordStore(self.db).save(_record("mrg_a"))
        self._bump_to(2, (2, "ALTER TABLE merge_jobs ADD COLUMN"))  # 문법 오류
        with self.assertRaises(sqlite3.OperationalError) as caught:
            MergeRecordStore(self.db)
        self.assertIn("migration to v2", str(caught.exception))
        self.assertEqual(self._version_in_db(), "1", "실패했으면 버전을 올리면 안 된다")


if __name__ == "__main__":
    unittest.main()

"""Structured logging: the envelope, the level routing, and URL redaction.

The redaction tests matter most. A presigned URL's query string is effectively a
credential, and container logs are both written to the host and rendered in a
browser, so a regression here leaks storage access rather than merely making the
logs untidy.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog import logs


class _Capture:
    """Swaps the logger's handler for one writing to a buffer."""

    def __enter__(self) -> _Capture:
        self.buffer = io.StringIO()
        self.logger = logging.getLogger(logs.LOGGER_NAME)
        self.saved = list(self.logger.handlers)
        self.saved_level = self.logger.level
        handler = logging.StreamHandler(self.buffer)
        handler.setFormatter(logs._JsonFormatter())  # noqa: SLF001
        self.logger.handlers = [handler]
        self.logger.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc) -> None:
        self.logger.handlers = self.saved
        self.logger.setLevel(self.saved_level)

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.buffer.getvalue().splitlines() if line.strip()]

    def one(self) -> dict:
        rows = self.lines()
        assert len(rows) == 1, f"expected exactly one line, got {len(rows)}"
        return rows[0]


class EnvelopeTests(unittest.TestCase):
    def test_every_line_is_one_json_object(self) -> None:
        with _Capture() as cap:
            logs.info("merge_done", "merged in 858ms", job="mrg_1", totalMs=858)
            logs.warn("proxy_detected", "via a proxy", path="/health")
        rows = cap.lines()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event"], "merge_done")
        self.assertEqual(rows[0]["message"], "merged in 858ms")
        self.assertEqual(rows[0]["job"], "mrg_1")
        self.assertEqual(rows[0]["totalMs"], 858)

    def test_level_is_carried_for_dozzle_to_colour_by(self) -> None:
        with _Capture() as cap:
            logs.debug("a")
            logs.info("b")
            logs.warn("c")
            logs.error("d")
        self.assertEqual(
            [row["level"] for row in cap.lines()], ["DEBUG", "INFO", "WARNING", "ERROR"]
        )

    def test_timestamp_is_utc_with_milliseconds(self) -> None:
        with _Capture() as cap:
            logs.info("x")
        ts = cap.one()["ts"]
        self.assertTrue(ts.endswith("Z"), ts)
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_message_defaults_to_the_event_name(self) -> None:
        with _Capture() as cap:
            logs.info("merge_stage")
        row = cap.one()
        self.assertEqual(row["message"], "merge_stage")

    def test_envelope_fields_cannot_be_overwritten(self) -> None:
        """A caller passing level=... must not be able to mislabel a line."""
        with _Capture() as cap:
            logs.error("boom", "failed", level="INFO", ts="1999", traceback="fake")
        row = cap.one()
        self.assertEqual(row["level"], "ERROR")
        self.assertNotEqual(row["ts"], "1999")
        self.assertNotIn("traceback", row)

    def test_event_as_a_field_collides_loudly(self) -> None:
        """``event`` is already filled positionally, so Python rejects it as a
        field before the envelope filter sees it. That is what we want: the
        caller finds out at once instead of losing a field silently."""
        with self.assertRaises(TypeError):
            logs.info("boom", event="other")

    def test_message_may_be_passed_by_keyword(self) -> None:
        with _Capture() as cap:
            logs.info("boom", message="spelled out")
        self.assertEqual(cap.one()["message"], "spelled out")

    def test_korean_is_not_escaped(self) -> None:
        with _Capture() as cap:
            logs.info("x", "병합 완료")
        self.assertIn("병합 완료", cap.buffer.getvalue())

    def test_unserialisable_values_do_not_break_the_line(self) -> None:
        with _Capture() as cap:
            logs.info("x", path=Path("/tmp/a"))
        self.assertEqual(cap.one()["path"], "/tmp/a")


class TracebackTests(unittest.TestCase):
    def test_exc_info_attaches_the_traceback(self) -> None:
        """The generic except in the worker used to discard this, leaving an
        unexpected failure with no cause recorded anywhere."""
        with _Capture() as cap:
            try:
                raise ValueError("kaboom")
            except ValueError:
                logs.error("merge_crashed", "unexpected", exc_info=True, job="mrg_1")
        row = cap.one()
        self.assertIn("ValueError: kaboom", row["traceback"])
        self.assertIn("raise ValueError", row["traceback"])

    def test_no_traceback_field_when_not_asked_for(self) -> None:
        with _Capture() as cap:
            logs.error("merge_failed", "E4101")
        self.assertNotIn("traceback", cap.one())


class RedactionTests(unittest.TestCase):
    PRESIGNED = (
        "http://timblo-minio:9000/default.timblo.io/kms/fileKey"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeefcafe"
    )

    def test_signature_is_stripped(self) -> None:
        cleaned = logs.safe_url(self.PRESIGNED)
        self.assertNotIn("X-Amz-Signature", cleaned)
        self.assertNotIn("deadbeefcafe", cleaned)

    def test_host_and_object_path_survive(self) -> None:
        """Enough to tell which storage and which object, which is what a
        transfer failure needs."""
        self.assertEqual(
            logs.safe_url(self.PRESIGNED),
            "http://timblo-minio:9000/default.timblo.io/kms/fileKey",
        )

    def test_nothing_in_nothing_out(self) -> None:
        self.assertIsNone(logs.safe_url(None))
        self.assertIsNone(logs.safe_url(""))

    def test_a_malformed_url_is_still_safe(self) -> None:
        self.assertEqual(logs.safe_url("not a url at all"), "<relative>")

    def test_redacted_url_survives_the_round_trip_into_a_line(self) -> None:
        with _Capture() as cap:
            logs.error("merge_download_failed", "E4101", url=logs.safe_url(self.PRESIGNED))
        self.assertNotIn("deadbeefcafe", cap.buffer.getvalue())


class LevelTests(unittest.TestCase):
    def test_debug_is_suppressed_at_info(self) -> None:
        with _Capture() as cap:
            cap.logger.setLevel(logging.INFO)
            logs.debug("expensive_detail", ffmpegCommand="...")
            logs.info("kept")
        rows = cap.lines()
        self.assertEqual([row["event"] for row in rows], ["kept"])

    def test_is_debug_guards_costly_fields(self) -> None:
        with _Capture() as cap:
            cap.logger.setLevel(logging.INFO)
            self.assertFalse(logs.is_debug())
            cap.logger.setLevel(logging.DEBUG)
            self.assertTrue(logs.is_debug())


if __name__ == "__main__":
    unittest.main()

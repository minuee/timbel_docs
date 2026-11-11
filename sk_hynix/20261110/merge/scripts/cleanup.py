#!/usr/bin/env python3
"""recog-backend host-side cleanup + reconciliation.

Runs out-of-container (host systemd timer) so the cleanup lifecycle is
independent of `aimm-recog-backend` restarts.

Responsibilities:
1. Reconcile sessions stuck in state=closing (closed_at > 5 min ago):
   retry the artifacts move + work-dir rmtree, then flip state=closed.
2. Purge archive/sessions/{id}/ entries with mtime > 7 days.
3. Emit one JSON metric line per run to `<runtime>/cleanup.log`.

Stdlib-only. Expects `RUNTIME_DIR` env to point at the recog-backend
bind-mounted `runtime/` directory.
"""
from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STALE_CLOSING_SECONDS = 5 * 60
PURGE_AGE_SECONDS = 7 * 24 * 60 * 60
RETRY_MAX = 3
RETRY_BACKOFF_SECONDS = 60
RETRY_ERRNOS = {errno.EACCES, errno.EAGAIN}

log = logging.getLogger("recog.cleanup")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _retry_on_transient(action, description: str, dry_run: bool):
    """Run ``action()`` up to RETRY_MAX times on EACCES/EAGAIN."""
    last_exc: Exception | None = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            if dry_run:
                log.info("[dry-run] would %s", description)
                return
            action()
            return
        except OSError as exc:
            last_exc = exc
            if exc.errno not in RETRY_ERRNOS:
                raise
            if attempt >= RETRY_MAX:
                break
            log.warning(
                "transient error on %s (errno=%s); retry %d/%d in %ds",
                description, exc.errno, attempt, RETRY_MAX, RETRY_BACKOFF_SECONDS,
            )
            time.sleep(RETRY_BACKOFF_SECONDS)
    assert last_exc is not None
    raise last_exc


def _dir_size_bytes(path: Path) -> int:
    """Recursively compute size, ignoring dangling symlinks."""
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        try:
            stat = entry.stat(follow_symlinks=False)
        except (OSError, FileNotFoundError):
            continue
        if stat.st_mode & 0o170000 == 0o040000:  # directory
            continue
        total += stat.st_size
    return total


def reconcile_session(session_dir: Path, dry_run: bool) -> tuple[bool, str | None]:
    """Best-effort reconciliation. Returns (reconciled, reason_if_skipped)."""
    session_json = session_dir / "session.json"
    if not session_json.exists():
        return False, "missing_session_json"
    try:
        payload = json.loads(session_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"unreadable:{exc}"
    if payload.get("state") != "closing":
        return False, "not_closing"
    closed_at = _parse_iso(payload.get("closed_at"))
    if closed_at is None:
        return False, "no_closed_at"
    age = (datetime.now(timezone.utc) - closed_at).total_seconds()
    if age < STALE_CLOSING_SECONDS:
        return False, "too_recent"

    session_id = payload.get("session_id") or session_dir.name
    runtime_root = session_dir.parent.parent  # runtime/
    archive_artifacts = runtime_root / "archive" / "sessions" / session_id / "artifacts"
    active_artifacts = session_dir / "artifacts"

    def _move_artifacts():
        if active_artifacts.exists():
            archive_artifacts.parent.mkdir(parents=True, exist_ok=True)
            if archive_artifacts.exists():
                shutil.rmtree(archive_artifacts)
            shutil.move(str(active_artifacts), str(archive_artifacts))

    def _purge_work_dirs():
        for sub in ("work", "canonical", "aligned", "uploads"):
            candidate = session_dir / sub
            if candidate.exists():
                shutil.rmtree(candidate)

    try:
        _retry_on_transient(_move_artifacts, f"move artifacts for {session_id}", dry_run)
        _retry_on_transient(_purge_work_dirs, f"rmtree work dirs for {session_id}", dry_run)
    except OSError as exc:
        log.error("reconcile failed for %s: %s", session_id, exc)
        return False, f"io_error:{exc}"

    if dry_run:
        return True, None
    payload["state"] = "closed"
    payload["archive_dir"] = str(archive_artifacts.parent)
    payload["updated_at"] = _utcnow_iso()
    _atomic_write_json(session_json, payload)
    return True, None


def purge_archive(archive_root: Path, dry_run: bool) -> tuple[int, int]:
    """Remove archive entries older than PURGE_AGE_SECONDS.

    Returns (purged_count, bytes_freed).
    """
    if not archive_root.exists():
        return 0, 0
    now = time.time()
    purged = 0
    bytes_freed = 0
    for entry in archive_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            continue
        if now - mtime < PURGE_AGE_SECONDS:
            continue
        size_before = _dir_size_bytes(entry)
        try:
            if dry_run:
                log.info("[dry-run] would purge %s (%d bytes)", entry, size_before)
            else:
                shutil.rmtree(entry)
        except OSError as exc:
            log.error("purge failed for %s: %s", entry, exc)
            continue
        purged += 1
        bytes_freed += size_before
    return purged, bytes_freed


def run_once(runtime_dir: Path, log_path: Path, dry_run: bool) -> dict:
    sessions_root = runtime_dir / "sessions"
    archive_root = runtime_dir / "archive" / "sessions"

    stuck_ids: list[str] = []
    reconciled = 0

    if sessions_root.exists():
        for session_dir in sessions_root.iterdir():
            if not session_dir.is_dir():
                continue
            ok, reason = reconcile_session(session_dir, dry_run=dry_run)
            if ok:
                reconciled += 1
            elif reason and reason.startswith("io_error") or reason == "not_closing" and (session_dir / "session.json").exists():
                # Distinguish "stuck" from "healthy not_closing". We only record
                # sessions whose state IS closing but reconciliation failed.
                try:
                    payload = json.loads((session_dir / "session.json").read_text())
                except Exception:
                    continue
                if payload.get("state") == "closing":
                    stuck_ids.append(session_dir.name)

    purged, bytes_freed = purge_archive(archive_root, dry_run=dry_run)

    metric = {
        "ts": _utcnow_iso(),
        "stuck_count": len(stuck_ids),
        "stuck_ids": stuck_ids,
        "reconciled": reconciled,
        "purged": purged,
        "bytes_freed": bytes_freed,
    }

    if not dry_run:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(metric, ensure_ascii=False) + "\n")
    else:
        log.info("[dry-run] metric: %s", json.dumps(metric, ensure_ascii=False))
    return metric


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="recog-backend host cleanup + reconcile")
    parser.add_argument(
        "--runtime-dir",
        default=os.environ.get("RUNTIME_DIR"),
        help="recog-backend runtime directory (env: RUNTIME_DIR)",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("CLEANUP_LOG"),
        help="Metric log file path (default: <runtime>/cleanup.log)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.runtime_dir:
        log.error("RUNTIME_DIR is required (env or --runtime-dir)")
        return 2
    runtime_dir = Path(args.runtime_dir)
    if not runtime_dir.is_dir():
        log.error("runtime dir does not exist: %s", runtime_dir)
        return 2

    log_path = Path(args.log_file) if args.log_file else runtime_dir / "cleanup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    metric = run_once(runtime_dir, log_path, dry_run=args.dry_run)
    print(json.dumps(metric, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

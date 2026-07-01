"""dlq_handler — DLQHandler 공개 진입점.

spec §3.4 — schedule_retry + _mark_doc_failed_with_summary 가 추가된
DLQHandler 를 재내보낸다. 구현은 dlq.py 에 위치.
"""

from src.pipeline.workers.dlq import DLQHandler  # noqa: F401

__all__ = ["DLQHandler"]

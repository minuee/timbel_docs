"""Wave 6 — Orchestrator 실 실행 wire.

ProcessRunner factory + compound 답변 통합 entry. engine.py 가 import.
"""
from src.agent_framework.runtime.orchestrator.factory import (
    OrchestratorDeps,
    make_process_runner_factory,
)

__all__ = ["OrchestratorDeps", "make_process_runner_factory"]

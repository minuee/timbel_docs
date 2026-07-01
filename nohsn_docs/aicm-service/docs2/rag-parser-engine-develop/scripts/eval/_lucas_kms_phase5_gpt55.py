"""Phase 5 T5.6 — GPT-5.5 adversarial final verification.

본 스크립트는 spec + Phase 0-5 의 핵심 commit diff + 운영 정책 코드 + artifact scan
+ regression 결과를 한 묶음으로 GPT-5.5 에 제출해 *최종 PASS / GO_WITH_CHANGES /
FAIL_WITH_NOTES* verdict 를 받는다.

**중요 — 자동 실행 금지** (메모리 절칙 feedback_gpt55_review_mandatory):
- 본 스크립트는 *호출 직전 사용자 명시 동의 필수*.
- 동의 없이 실행 시 OpenAI 키 비용 + 분리 검토 결과 누락.
- 운영자: `python -m scripts.eval._lucas_kms_phase5_gpt55 --confirm` 같이 명시 옵션 필요.

본 task 에서는 스크립트만 작성하고 실 호출은 보류한다.

사용법 (사용자 동의 후):
    OPENAI_API_KEY=... python -m scripts.eval._lucas_kms_phase5_gpt55 --confirm

출력:
    Doc/research/2026-05-19-lucas-kms-phase5-final.gpt55.txt

비교 baseline:
    Doc/research/2026-05-19-lucas-kms-spec.gpt55.txt  (T5.6 의 spec-only 1차 verdict)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md"
OUT_PATH = REPO_ROOT / "Doc/research/2026-05-19-lucas-kms-phase5-final.gpt55.txt"

# Phase 5 신설 artifact (commit hash 미정 — 본 task 의 작업물)
PHASE5_ARTIFACTS = [
    "tests/integration/test_vllm_failure_modes.py",
    "tools/docker_scan/scan.sh",
    "tools/docker_scan/CHECKLIST.md",
    "scripts/regression/locus_smoke.sh",
    "tests/perf/scenarios.yml",
    "Doc/regression/2026-05-19-locus-smoke.md",
    "Doc/perf/2026-05-19-integrated-baseline/report.md",
]

# Phase 0-4 의 핵심 commits — git log 에서 dynamically 가져옴
PHASE_COMMIT_PATTERNS = [
    "phase0",
    "phase1",
    "phase2",
    "phase3",
    "phase4",
    "perf(baseline",
    "perf(lucas-kms",
    "deploy(lucas-kms",
]


def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> str:
    """Helper to run a shell command and return stdout (empty on error)."""
    try:
        return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _collect_recent_commits(branch: str = "KMS-Plus", limit: int = 40) -> list[tuple[str, str]]:
    """Recent commits (sha, subject) matching Phase 0-5 patterns."""
    log = _run(["git", "log", branch, f"-n{limit}", "--pretty=format:%h|%s"])
    rows: list[tuple[str, str]] = []
    for line in log.splitlines():
        if "|" not in line:
            continue
        sha, subj = line.split("|", 1)
        if any(pat in subj.lower() for pat in (p.lower() for p in PHASE_COMMIT_PATTERNS)):
            rows.append((sha, subj))
    return rows


def _read_file(path: Path, max_chars: int = 30000) -> str:
    """Read a file with safe truncation."""
    if not path.exists():
        return f"<file missing: {path.relative_to(REPO_ROOT)}>"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"<read error {path.name}: {e}>"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n... [truncated {len(text) - max_chars} chars]"
    return text


def _commit_diff(sha: str, max_chars: int = 8000) -> str:
    """Get a commit diff with safe truncation."""
    diff = _run(["git", "show", "--stat", sha])
    if len(diff) > max_chars:
        diff = diff[:max_chars] + f"\n\n... [truncated]"
    return diff


def build_prompt() -> tuple[str, str]:
    """Build (system_msg, user_msg) for GPT-5.5 final verification."""
    spec_text = _read_file(SPEC_PATH, max_chars=60000)
    commits = _collect_recent_commits()

    # 핵심 artifact 파일 내용 묶음
    artifact_sections: list[str] = []
    for rel in PHASE5_ARTIFACTS:
        artifact_sections.append(
            f"### {rel}\n```\n{_read_file(REPO_ROOT / rel, max_chars=8000)}\n```"
        )

    commit_sections: list[str] = []
    for sha, subj in commits[:15]:
        commit_sections.append(f"### {sha} — {subj}\n```\n{_commit_diff(sha)}\n```")

    system_msg = (
        "You are GPT-5.5 acting as an adversarial *final-stage* verifier for the "
        "Lucas-KMS separation project's Phase 5 (release). You already reviewed the "
        "design spec earlier. Now Phase 0-5 implementation is complete. Verify:\n"
        " 1) Did Phase 5 deliverables actually close the spec's Section 6.2 "
        "    operational policy gaps? (vLLM auth/TLS/timeout/retry/circuit/health)\n"
        " 2) Are the artifact scans (Section 12.1) really 4-layer (static / dynamic / "
        "    artifact / repo-history)? OpenAPI + SBOM additions sufficient?\n"
        " 3) Locus regression smoke covers Section 12.3 minimums?\n"
        " 4) Cold-path measurement actually validates a meaningful protocol?\n"
        " 5) Any RLS / tenant isolation regression risk introduced in Phase 5?\n"
        " 6) Deployment runbook risks (env var leakage / secret handling)?\n\n"
        "Be specific, cite file paths + line ranges. Verdict: PASS / "
        "GO_WITH_CHANGES / FAIL_WITH_NOTES. Korean OK."
    )

    user_msg_parts = [
        "다음 자료를 종합 검토 — Lucas-KMS 분리 작업의 Phase 5 최종 verdict.",
        "",
        "## 1. spec (Phase 0-5 의 정의)",
        "```markdown",
        spec_text,
        "```",
        "",
        "## 2. Phase 0-5 commits 요약",
    ]
    for sha, subj in commits:
        user_msg_parts.append(f"- `{sha}` {subj}")
    user_msg_parts.append("")
    user_msg_parts.append("## 3. Phase 5 핵심 commit diff (top 15)")
    user_msg_parts.extend(commit_sections)
    user_msg_parts.append("")
    user_msg_parts.append("## 4. Phase 5 작업물 파일 본문")
    user_msg_parts.extend(artifact_sections)
    user_msg_parts.append("")
    user_msg_parts.append(
        "**Verdict + 보강 권고 — 한국어, line range 포함.** 특히:\n"
        " - vLLM 운영 정책 (Section 6.2) 항목별 코드/테스트 coverage 표\n"
        " - artifact scan 의 [1]-[7] layer 별 충분성 평가\n"
        " - 통합 솔루션 회귀가 Section 12.3 minimums 를 채웠는지\n"
        " - 운영 자료 (CHECKLIST/runbook) 의 모호성 / risk\n"
        " - PASS 가 아니라면 PASS 까지 무엇이 더 필요한지 (구체 task ID)"
    )
    user_msg = "\n".join(user_msg_parts)

    return system_msg, user_msg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 final GPT-5.5 verification — requires explicit --confirm.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="실제 OpenAI 호출 (사용자 명시 동의 후에만).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="prompt 만 stdout 으로 출력 (호출 없음, 사람 사전 검토용).",
    )
    args = parser.parse_args()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    system_msg, user_msg = build_prompt()

    if args.dry_run:
        print("# === SYSTEM ===")
        print(system_msg)
        print()
        print("# === USER ===")
        print(user_msg[:8000])
        print(f"\n[... total user_msg = {len(user_msg)} chars, truncated to 8000 for dry-run]")
        return 0

    if not args.confirm:
        print(
            "[WARN] 본 스크립트는 호출 전 사용자 명시 동의가 필수입니다.\n"
            "       메모리 절칙 feedback_gpt55_review_mandatory.\n"
            "       prompt 미리 보려면 --dry-run, 실 호출은 --confirm.",
            file=sys.stderr,
        )
        return 2

    if "OPENAI_API_KEY" not in os.environ:
        print("[ERROR] OPENAI_API_KEY env 가 .env 또는 shell 에 없음.", file=sys.stderr)
        return 3

    # 지연 import — confirm 안 한 경우 openai 패키지 미설치라도 dry-run 가능
    try:
        from openai import OpenAI
    except ImportError:
        print("[ERROR] openai 패키지 미설치: pip install openai", file=sys.stderr)
        return 4

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model="gpt-5.5",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )
    text = resp.choices[0].message.content or ""
    OUT_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[saved -> {OUT_PATH.relative_to(REPO_ROOT)}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

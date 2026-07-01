"""Phase 0 T0.3 — Alembic branch audit.

src/core/models 의 모든 SQLAlchemy model 을 스캔하여 각 model 의
branch (kms / agent / shared) 소속을 spec Section 4 기반으로 분류.
누락 (unknown) 시 비-0 종료.

출력: tools/alembic_audit/model_branches.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/alembic_audit/model_branches.json"

KMS_TABLES = {
    "repositories", "documents", "chunks", "blocks", "sections",
    "categories", "document_categories", "document_types",
    "library_folders", "notes", "search_logs", "intent_logs",
}
AGENT_TABLES = {
    "agents", "agent_channels", "agent_documents",
    "channel_user_mappings", "channel_inbound_dedup",
    "custom_tools", "scheduled_actions", "lifecycle_feedback",
}
SHARED_TABLES = {
    "tenants", "users", "api_keys", "user_repository_access",
    "audit_logs", "integrations", "llm_usage",
    "anonymization_logs", "dlq_messages",
    # cross-tenant / lifecycle stubs (양쪽이 사용 가능)
    "tenant_links", "transition_events", "lifecycle_policies",
}


def scan_models() -> list[dict]:
    models_dir = ROOT / "src/core/models"
    table_re = re.compile(r'__tablename__\s*=\s*["\'](\w+)["\']')
    out = []
    for p in sorted(models_dir.rglob("*.py")):
        if p.name == "__init__.py":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in table_re.finditer(text):
            out.append({
                "table": m.group(1),
                "file": str(p.relative_to(ROOT)),
            })
    return out


def classify(table: str) -> str:
    if table in KMS_TABLES:
        return "kms"
    if table in AGENT_TABLES:
        return "agent"
    if table in SHARED_TABLES:
        return "shared"
    return "unknown"


def main() -> int:
    found = scan_models()
    by_branch: dict[str, list[dict]] = {
        "kms": [], "agent": [], "shared": [], "unknown": []
    }
    for e in found:
        b = classify(e["table"])
        by_branch[b].append(e)

    OUT.write_text(
        json.dumps(
            {
                "total": len(found),
                "by_branch_count": {k: len(v) for k, v in by_branch.items()},
                "by_branch": by_branch,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"saved: {OUT.relative_to(ROOT)}")
    print()
    for b in ("kms", "agent", "shared", "unknown"):
        rows = by_branch[b]
        print(f"=== {b} ({len(rows)}) ===")
        for r in rows[:30]:
            print(f"  {r['table']:30s}  {r['file']}")
        if len(rows) > 30:
            print(f"  ... and {len(rows) - 30} more")

    if by_branch["unknown"]:
        print()
        print(f"FAIL: {len(by_branch['unknown'])} unknown tables — "
              f"분류 필요 (spec Section 4 또는 본 스크립트의 *_TABLES 갱신)")
        return 1
    print()
    print("PASS: 모든 model 의 branch 분류 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())

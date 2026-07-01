"""Phase 0 T0.2 — Router / Worker / DB Model inventory.

src/api/routers/, src/pipeline/workers/, src/core/models/ 를 스캔해
각 항목의 책임 + KMS/Agent/Shared 분류 후보를 JSON 으로 출력.

출력: tools/import_audit/inventory.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/import_audit/inventory.json"

KMS_ROUTERS = {
    "repositories", "documents", "blocks", "chunks", "search",
    "rag", "rag_assist", "categories", "document_types",
    "library_folders_v1", "notes", "preview", "playground",
    "sections",
}
AGENT_ROUTERS = {
    "agents_v1", "chat_v1", "agent_management", "activation",
    "external_agent_v1", "agent_documents_v1", "tools_v1",
    "custom_tools_v1", "skills_catalog_v1", "manifest",
    "context_v1", "feed_v1", "schedule_v1", "diary_v1",
    "expense_v1", "stock_v1", "memo_v1", "sop_samples_v1",
    "verification_v1", "doc_draft_v1",
}

KMS_MODELS = {
    "Repository", "Document", "Chunk", "Block", "Section",
    "Category", "DocumentCategory", "DocumentType",
    "LibraryFolder", "Note", "SearchLog", "IntentLog",
}
AGENT_MODELS = {
    "Agent", "AgentChannel", "AgentDocument", "ChannelUserMapping",
    "ChannelInboundDedup", "CustomTool", "ScheduledAction",
    "LifecycleFeedback",
}
SHARED_MODELS = {
    "Tenant", "User", "ApiKey", "UserRepositoryAccess",
    "AuditLog", "Integration", "LlmUsage",
    "AnonymizationLog", "DlqMessage",
}


def scan_routers() -> dict:
    routers_dir = ROOT / "src/api/routers"
    out = {"kms": [], "agent": [], "shared_or_unknown": []}
    for p in sorted(routers_dir.glob("*.py")):
        if p.name == "__init__.py":
            continue
        name = p.stem
        if name in KMS_ROUTERS:
            out["kms"].append(name)
        elif name in AGENT_ROUTERS:
            out["agent"].append(name)
        else:
            out["shared_or_unknown"].append(name)
    return out


def scan_workers() -> list[dict]:
    worker_dir = ROOT / "src/pipeline/workers"
    out = []
    for p in sorted(worker_dir.glob("*.py")):
        if p.name == "__init__.py":
            continue
        out.append({"name": p.stem, "path": str(p.relative_to(ROOT))})
    return out


def scan_models() -> dict:
    models_dir = ROOT / "src/core/models"
    found = {"kms": [], "agent": [], "shared": [], "unknown": []}
    class_re = re.compile(r"^class\s+(\w+)\s*\(")
    for p in sorted(models_dir.glob("*.py")):
        if p.name == "__init__.py":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in class_re.finditer(text):
            cls = m.group(1)
            entry = {"class": cls, "file": str(p.relative_to(ROOT))}
            if cls in KMS_MODELS:
                found["kms"].append(entry)
            elif cls in AGENT_MODELS:
                found["agent"].append(entry)
            elif cls in SHARED_MODELS:
                found["shared"].append(entry)
            else:
                found["unknown"].append(entry)
    return found


def main() -> int:
    result = {
        "routers": scan_routers(),
        "workers": scan_workers(),
        "models": scan_models(),
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"inventory saved: {OUT.relative_to(ROOT)}")
    print()
    print("=== Routers ===")
    for k, v in result["routers"].items():
        print(f"  {k}: {len(v)} files")
    print(f"=== Workers: {len(result['workers'])} files ===")
    print("=== Models ===")
    for k, v in result["models"].items():
        print(f"  {k}: {len(v)} classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

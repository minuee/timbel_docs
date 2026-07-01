"""Phase 0 T0.1 — 현 src/ 의 import 의존성 그래프 생성.

출력: tools/import_audit/graph.json

사용법:
    python3 tools/import_audit/build_graph.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import grimp
except ImportError:
    print("grimp 미설치. pip install grimp", file=sys.stderr)
    sys.exit(2)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/import_audit/graph.json"


def main() -> int:
    graph = grimp.build_graph("src", include_external_packages=False)
    modules = sorted(graph.modules)
    edges = []
    for m in modules:
        targets = sorted(graph.find_modules_directly_imported_by(m))
        if targets:
            edges.append({"from": m, "to": targets})

    OUT.write_text(
        json.dumps(
            {
                "modules": modules,
                "module_count": len(modules),
                "edge_count": sum(len(e["to"]) for e in edges),
                "edges": edges,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"graph saved: {len(modules)} modules, "
          f"{sum(len(e['to']) for e in edges)} edges")
    print(f"output: {OUT.relative_to(ROOT)}")

    cross_violations = []
    agent_prefixes = (
        "src.agent_framework",
        "src.api.routers.agents_v1",
        "src.api.routers.chat_v1",
        "src.api.routers.agent_management",
        "src.api.routers.external_agent_v1",
        "src.api.routers.agent_documents_v1",
        "src.api.routers.tools_v1",
        "src.api.routers.custom_tools_v1",
        "src.api.routers.skills_catalog_v1",
        "src.api.routers.manifest",
        "src.api.routers.activation",
    )
    kms_prefixes = (
        "src.api.routers.repositories",
        "src.api.routers.documents",
        "src.api.routers.blocks",
        "src.api.routers.chunks",
        "src.api.routers.search",
        "src.api.routers.rag",
        "src.pipeline",
        "src.search",
    )

    for e in edges:
        src = e["from"]
        if src.startswith(kms_prefixes):
            for tgt in e["to"]:
                if tgt.startswith(agent_prefixes):
                    cross_violations.append((src, tgt))

    print()
    print(f"=== KMS → Agent cross-import violations: {len(cross_violations)} ===")
    for src, tgt in cross_violations[:50]:
        print(f"  {src}  ->  {tgt}")
    if len(cross_violations) > 50:
        print(f"  ... and {len(cross_violations) - 50} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

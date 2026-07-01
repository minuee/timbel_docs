"""Phase 0 T0.4 — Frontend API call inventory.

frontend/ (V1) + frontend-v3/src/ 에서 호출하는 /api/v1/... endpoint 를 grep
으로 추출하여 inventory.

출력: tools/import_audit/frontend_api_calls.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/import_audit/frontend_api_calls.json"

ENDPOINT_RE = re.compile(r'["\']\/api\/v1\/([^"\'?\s)]+)')


def scan_dir(root: Path) -> set[str]:
    found: set[str] = set()
    if not root.exists():
        return found
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in (".js", ".jsx", ".ts", ".tsx", ".html", ".vue"):
            continue
        if any(skip in str(p) for skip in ("node_modules", "dist", "build", ".next")):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in ENDPOINT_RE.finditer(text):
            found.add(m.group(1).rstrip("/"))
    return found


def main() -> int:
    v1 = sorted(scan_dir(ROOT / "frontend"))
    v3 = sorted(scan_dir(ROOT / "frontend-v3/src"))

    only_v1 = sorted(set(v1) - set(v3))
    only_v3 = sorted(set(v3) - set(v1))
    common = sorted(set(v1) & set(v3))

    OUT.write_text(
        json.dumps(
            {
                "frontend_v1_count": len(v1),
                "frontend_v3_count": len(v3),
                "common": common,
                "only_v1": only_v1,
                "only_v3": only_v3,
                "all_v1": v1,
                "all_v3": v3,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved: {OUT.relative_to(ROOT)}")
    print(f"V1 endpoints: {len(v1)}")
    print(f"V3 endpoints: {len(v3)}")
    print(f"common: {len(common)}")
    print(f"only V1: {len(only_v1)}")
    print(f"only V3: {len(only_v3)}")
    print()
    print("=== V3 only (V1 patch 시 backport 후보) ===")
    for e in only_v3[:40]:
        print(f"  {e}")
    if len(only_v3) > 40:
        print(f"  ... and {len(only_v3) - 40} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

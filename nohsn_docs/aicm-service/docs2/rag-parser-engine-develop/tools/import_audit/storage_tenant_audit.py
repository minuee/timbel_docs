"""Phase 0 T0.5 — Storage tenant-scope audit.

Qdrant collection / ES index / MinIO bucket / Redis key / Kafka topic 의
naming pattern + tenant_id 사용 현황 을 grep 으로 추출.

출력: tools/import_audit/storage_tenant.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/import_audit/storage_tenant.json"

PATTERNS = {
    "qdrant_collection": [
        re.compile(r"collection_name\s*=\s*[fr]?[\"']([^\"']+)[\"']"),
        re.compile(r"qdrant.*upsert\([^)]*[\"']([^\"']+)[\"']", re.DOTALL),
    ],
    "es_index": [
        re.compile(r"index=[fr]?[\"']([^\"']+)[\"']"),
    ],
    "minio_bucket": [
        re.compile(r"bucket(?:_name)?\s*=\s*[fr]?[\"']([^\"']+)[\"']"),
    ],
    "redis_key": [
        re.compile(r"redis.*\.(?:set|get|delete|incr)\([^,)]*[\"']([^\"']+)[\"']"),
    ],
    "kafka_topic": [
        re.compile(r"topic\s*=\s*[fr]?[\"'](aicm\.[^\"']+)[\"']"),
        re.compile(r"send_and_wait\([^,)]*[\"'](aicm\.[^\"']+)[\"']"),
    ],
}


def scan() -> dict:
    out: dict[str, dict] = {k: {} for k in PATTERNS}
    for p in (ROOT / "src").rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, regexes in PATTERNS.items():
            for r in regexes:
                for m in r.finditer(text):
                    name = m.group(1)
                    if any(skip in name for skip in ("\\n", "{", "}}")):
                        continue
                    out[key].setdefault(name, []).append(str(p.relative_to(ROOT)))
    return out


def main() -> int:
    found = scan()
    OUT.write_text(json.dumps(found, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"saved: {OUT.relative_to(ROOT)}")
    for k, items in found.items():
        print(f"=== {k}: {len(items)} unique ===")
        for name, files in list(items.items())[:10]:
            print(f"  {name}  ({len(files)} files)")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")
    print()
    print("점검 항목 (spec Section 8 기반):")
    print("- Qdrant collection naming 에 {tenant_id} 포함 여부")
    print("- ES index naming 에 {tenant_id} 포함 여부")
    print("- MinIO bucket 에 tenant 분리 여부")
    print("- Redis key 에 tenant prefix 여부")
    print("- Kafka topic 의 message body 에 tenant_id field 필수 여부")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

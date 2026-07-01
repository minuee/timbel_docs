"""Domain manifest 인프라 — frontend schema-driven UI 카탈로그.

신규 도메인 추가 시 ``manifest/domains/<id>.yaml`` 한 파일만 추가하면
frontend 가 manifest 를 fetch 해 sidebar / dashboard 자동 렌더.
"""
from src.agent_framework.manifest.loader import (
    DOMAINS_DIR,
    ManifestLoadError,
    load_all_manifests,
    load_manifest_from_path,
)
from src.agent_framework.manifest.registry import (
    ActionDef,
    ColumnDef,
    DomainManifest,
    WidgetDef,
)

__all__ = [
    "ActionDef",
    "ColumnDef",
    "DOMAINS_DIR",
    "DomainManifest",
    "ManifestLoadError",
    "WidgetDef",
    "load_all_manifests",
    "load_manifest_from_path",
]

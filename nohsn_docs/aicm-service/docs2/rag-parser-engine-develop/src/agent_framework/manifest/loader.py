"""Manifest YAML loader — domains/*.yaml → list[DomainManifest].

사용 예::

    from src.agent_framework.manifest.loader import load_all_manifests

    manifests = load_all_manifests()
    for m in manifests:
        print(m.id, m.status)

스키마 위반 / 파일 손상은 개별 파일만 skip 후 로깅 — 전체 manifest 응답이
한 파일 때문에 망가지지 않게.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.agent_framework.manifest.registry import (
    ActionDef,
    ColumnDef,
    DomainManifest,
    WidgetDef,
)
from src.common.logging import get_logger

log = get_logger(__name__)

# manifest/domains/ 디렉토리 — 이 파일 옆에 위치.
DOMAINS_DIR = Path(__file__).resolve().parent / "domains"


class ManifestLoadError(Exception):
    """단일 manifest 파일 파싱 실패."""


def _coerce_columns(raw: list[Any] | None) -> list[ColumnDef]:
    if not raw:
        return []
    out: list[ColumnDef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestLoadError(f"column entry must be mapping: {item!r}")
        out.append(
            ColumnDef(
                key=str(item["key"]),
                label=str(item["label"]),
                format=str(item.get("format", "text")),  # type: ignore[arg-type]
            )
        )
    return out


def _coerce_widgets(raw: list[Any] | None) -> list[WidgetDef]:
    if not raw:
        return []
    out: list[WidgetDef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestLoadError(f"widget entry must be mapping: {item!r}")
        out.append(
            WidgetDef(
                type=str(item["type"]),  # type: ignore[arg-type]
                label=str(item["label"]),
                key=str(item["key"]),
                kind=item.get("kind"),
                format=str(item.get("format", "text")),  # type: ignore[arg-type]
            )
        )
    return out


def _coerce_actions(raw: list[Any] | None) -> list[ActionDef]:
    if not raw:
        return []
    out: list[ActionDef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestLoadError(f"action entry must be mapping: {item!r}")
        out.append(
            ActionDef(
                id=str(item["id"]),
                label=str(item["label"]),
                method=str(item.get("method", "POST")),
                endpoint=item.get("endpoint"),
                form_schema=item.get("form_schema"),
            )
        )
    return out


def load_manifest_from_path(path: Path) -> DomainManifest:
    """단일 YAML 파일을 DomainManifest 로 파싱."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ManifestLoadError(f"manifest not found: {path}") from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestLoadError(f"invalid YAML at {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ManifestLoadError(f"manifest root must be mapping at {path}")

    required = ("id", "label", "icon", "status")
    for key in required:
        if key not in raw:
            raise ManifestLoadError(f"missing required field '{key}' at {path}")

    status = str(raw["status"])
    if status not in ("active", "available", "upcoming", "deprecated"):
        raise ManifestLoadError(
            f"invalid status '{status}' at {path} "
            "(allowed: active|available|upcoming|deprecated)"
        )

    raw_groups = raw.get("available_for_groups") or []
    if not isinstance(raw_groups, list):
        raise ManifestLoadError(
            f"available_for_groups must be list at {path}, got {type(raw_groups).__name__}"
        )
    available_for_groups = [str(g) for g in raw_groups]

    return DomainManifest(
        id=str(raw["id"]),
        label=str(raw["label"]),
        icon=str(raw["icon"]),
        status=status,  # type: ignore[arg-type]
        list_endpoint=raw.get("list_endpoint"),
        summary_endpoint=raw.get("summary_endpoint"),
        detail_endpoint=raw.get("detail_endpoint"),
        list_columns=_coerce_columns(raw.get("list_columns")),
        summary_widgets=_coerce_widgets(raw.get("summary_widgets")),
        quick_actions=_coerce_actions(raw.get("quick_actions")),
        chat_intents=list(raw.get("chat_intents") or []),
        card_renderer=raw.get("card_renderer"),
        upcoming_message=raw.get("upcoming_message"),
        available_for_groups=available_for_groups,
        sort_order=int(raw.get("sort_order", 100)),
    )


def load_all_manifests(dir_path: Path | None = None) -> list[DomainManifest]:
    """디렉토리 내 모든 *.yaml 을 로드하고 sort_order, id 순으로 정렬해 반환.

    한 파일 파싱 실패 시 그 파일만 skip 후 로그.
    """
    base = dir_path or DOMAINS_DIR
    if not base.exists():
        log.warning("manifest_domains_dir_missing", path=str(base))
        return []

    out: list[DomainManifest] = []
    for yaml_file in sorted(base.glob("*.yaml")):
        try:
            out.append(load_manifest_from_path(yaml_file))
        except ManifestLoadError as e:
            log.error(
                "manifest_load_failed", path=str(yaml_file), error=str(e)
            )
    out.sort(key=lambda m: (m.sort_order, m.id))
    return out


__all__ = [
    "DOMAINS_DIR",
    "ManifestLoadError",
    "load_all_manifests",
    "load_manifest_from_path",
]

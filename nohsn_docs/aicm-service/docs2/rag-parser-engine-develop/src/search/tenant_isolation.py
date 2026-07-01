"""D32 §3 — Qdrant / ES tenant isolation instrumentation.

사용자 절칙: namespace 위반 즉시 차단 (silent drop 0).
사전 GPT-5 R3 권고:
- caller_tenant_slug 와 scope 가 search 호출에 propagate.
- superadmin/system + allow_cross_namespace=True 일 때만 namespace 미스매치 허용.
- contextvar 기반 instrumentation hook (객체 필드 race 회피).
- ValueError 대신 CrossTenantSearchError (도메인 예외).

namespace 패턴: ``aicm_{tenant_slug}_blocks`` (qdrant collection / ES index 동일).
"""
from __future__ import annotations

import contextvars
import os
import re
from dataclasses import dataclass
from typing import Any

from src.common.constants import QDRANT_COLLECTION_PREFIX
from src.common.logging import get_logger

log = get_logger(__name__)


class CrossTenantSearchError(Exception):
    """다른 tenant 의 namespace 를 호출한 보안 사고. application 즉시 차단.

    Args:
        caller_slug: 호출자가 expected 한 tenant_slug.
        target_namespace: 실제 query 한 collection / index 이름.
        scope: caller 의 RLS scope (admin / agent / superadmin / system).
    """

    def __init__(self, caller_slug: str, target_namespace: str, scope: str | None) -> None:
        self.caller_slug = caller_slug
        self.target_namespace = target_namespace
        self.scope = scope or ""
        super().__init__(
            f"cross_tenant_search_attempted: caller_slug={caller_slug!r} "
            f"target_namespace={target_namespace!r} scope={self.scope!r}"
        )


@dataclass(frozen=True)
class _SearchAuditEntry:
    """instrumentation 용 마지막 query payload (테스트/감사)."""

    caller_slug: str
    namespace: str
    scope: str
    backend: str  # 'qdrant_dense' / 'qdrant_sparse' / 'es'


_LAST_SEARCH_CTX: contextvars.ContextVar[_SearchAuditEntry | None] = contextvars.ContextVar(
    "rls_search_last", default=None
)


def get_last_search_audit() -> _SearchAuditEntry | None:
    """test/audit 용 — 직전 search 의 (caller_slug, namespace, scope, backend)."""
    return _LAST_SEARCH_CTX.get(None)


# audit hook 활성화 flag (env). 프로덕션 default off — PII / 로깅 비용 회피.
_AUDIT_ENABLED = os.environ.get("SEARCH_AUDIT_ENABLED", "0").lower() in ("1", "true", "yes")


# namespace pattern: ``aicm_{tenant_slug}_blocks``.
# tenant_slug 는 lowercase 영숫자 + 언더스코어 + 하이픈 — 슬러그 정규식과 일치.
_NS_RE = re.compile(
    rf"^{re.escape(QDRANT_COLLECTION_PREFIX)}_(?P<slug>[a-z0-9_\-]+)_blocks$"
)


def parse_namespace_slug(namespace: str) -> str | None:
    """namespace 이름에서 tenant_slug 추출. 패턴 mismatch 시 None."""
    if not namespace:
        return None
    m = _NS_RE.match(namespace)
    return m.group("slug") if m else None


def assert_tenant_namespace(
    *,
    namespace: str,
    caller_slug: str,
    scope: str | None = None,
    allow_cross_namespace: bool = False,
    backend: str = "qdrant",
) -> None:
    """namespace 가 caller_slug 의 tenant 와 일치하는지 검증.

    Args:
        namespace: 실제 호출되는 collection / index 이름.
        caller_slug: caller 의 expected tenant_slug.
        scope: caller 의 RLS scope (admin / agent / superadmin / system).
        allow_cross_namespace: scope ∈ {superadmin, system} + 명시 True 인 경우에만
            cross-namespace 허용 (admin global view 등).
        backend: instrumentation hook 의 backend 라벨.

    Raises:
        CrossTenantSearchError — caller_slug 가 namespace 에서 추출한 slug 와 다르고,
            cross-namespace 허용 조건도 미충족.
    """
    # 사후 GPT-5 §2+§3 권고 — audit hook 진입 시 초기화 (재진입 시 stale 값 회피).
    if _AUDIT_ENABLED:
        try:
            _LAST_SEARCH_CTX.set(None)
        except Exception:  # noqa: BLE001
            pass

    parsed = parse_namespace_slug(namespace)

    # cross-namespace 허용 조건 — superadmin / system + 명시 True.
    is_cross_allowed = (
        allow_cross_namespace
        and (scope or "") in {"superadmin", "system"}
    )

    if not is_cross_allowed:
        if not parsed:
            # 예) external test collection / migration intermediate — 보안상 거부.
            raise CrossTenantSearchError(
                caller_slug=caller_slug,
                target_namespace=namespace,
                scope=scope,
            )
        if parsed != caller_slug:
            raise CrossTenantSearchError(
                caller_slug=caller_slug,
                target_namespace=namespace,
                scope=scope,
            )

    # 검증 통과 — 마지막 query payload 기록.
    if _AUDIT_ENABLED:
        try:
            _LAST_SEARCH_CTX.set(
                _SearchAuditEntry(
                    caller_slug=caller_slug,
                    namespace=namespace,
                    scope=scope or "",
                    backend=backend,
                )
            )
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "CrossTenantSearchError",
    "assert_tenant_namespace",
    "get_last_search_audit",
    "parse_namespace_slug",
]

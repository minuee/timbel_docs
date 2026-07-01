"""Lucas-KMS Phase 2 T2.6 — Elasticsearch tenant isolation 헬퍼.

핵심 책임:

- ES query (search / update_by_query / delete_by_query) 의 ``bool/filter`` 에
  ``tenant_id`` term 을 강제로 주입 (이중 안전망).
- 인덱싱 시 doc 에 ``tenant_id`` 필드가 채워졌는지 검증 (fail-fast).
- index naming 은 기존 ``build_block_es_index_name`` 그대로 사용 (회귀 방지).

설계 원칙 (사용자 절칙):

- 키워드 / 정해진 enum 하드코딩 금지 — tenant_id 는 caller 가 변수로 넘김.
- 기존 backend 재작성 금지 — 추가 헬퍼만 도입.
- naming pattern 은 그대로 유지 (``aicm_{tenant_slug}_blocks``).

T2.5 (Qdrant) 의 ``payload-level tenant_id must filter`` 와 짝.
"""

from __future__ import annotations

from typing import Any


class MissingTenantIdError(ValueError):
    """ES doc 인덱싱 시 ``tenant_id`` field 누락 — fail-fast.

    Phase 2 T2.6: tenant isolation 의 ``payload`` 레벨 안전망. 누락은 cross-tenant
    누수 위험이므로 즉시 차단.
    """


def with_tenant_term(
    query: dict[str, Any] | None,
    tenant_id: str | None,
) -> dict[str, Any]:
    """주어진 ES query 에 ``tenant_id`` term filter 를 *추가* 한다.

    동작:

    - query 가 None / 빈 dict 면 ``{"bool": {"filter": [tenant_term]}}`` 반환.
    - query 가 이미 ``bool`` 이면 ``filter`` 리스트에 term 추가.
    - query 가 그 외 leaf query (e.g. ``term``, ``match``) 면 ``bool/must``
      안에 wrap 하고 ``filter`` 에 tenant term 추가.
    - tenant_id 가 None 이면 query 그대로 (legacy 호환 — 호출측이 책임).

    Parameters
    ----------
    query : dict | None
        기존 ES query body 의 ``query`` 부분.
    tenant_id : str | None
        강제 적용할 tenant_id (UUID 문자열). None 이면 no-op.

    Returns
    -------
    dict
        tenant_id term 이 합쳐진 새로운 query (원본 mutate 하지 않음).
    """
    if not tenant_id:
        return dict(query) if query else {}

    tenant_term = {"term": {"tenant_id": str(tenant_id)}}

    if not query:
        return {"bool": {"filter": [tenant_term]}}

    # bool query — filter 에 append.
    if "bool" in query:
        # shallow copy 로 원본 보호.
        bool_body = {**query["bool"]}
        existing_filter = list(bool_body.get("filter", []))
        existing_filter.append(tenant_term)
        bool_body["filter"] = existing_filter
        return {"bool": bool_body}

    # leaf query — bool/must 로 wrap.
    return {
        "bool": {
            "must": [query],
            "filter": [tenant_term],
        }
    }


def ensure_tenant_id_field(doc: dict[str, Any], expected_tenant_id: str) -> None:
    """ES doc 에 ``tenant_id`` field 가 채워졌는지 검증.

    - field 누락 / 빈 값 → ``MissingTenantIdError``.
    - field 가 expected 와 다르면 → ``MissingTenantIdError`` (cross-tenant 누수
      방어).

    fail-fast 정책: 인덱싱 stage 에서 잘못된 doc 이 들어오면 *즉시* 차단해서
    누수 chunk 가 ES 에 영구 저장되는 사고를 막는다.

    Parameters
    ----------
    doc : dict
        인덱싱 직전 doc.
    expected_tenant_id : str
        caller 가 알고 있는 tenant_id (보통 ``event.tenant_id``).

    Raises
    ------
    MissingTenantIdError
        doc[``tenant_id``] 가 빈 값이거나 expected 와 다른 경우.
    """
    if not expected_tenant_id:
        raise MissingTenantIdError(
            "ensure_tenant_id_field_called_without_expected: "
            "caller 가 tenant_id 를 모른 채 호출 — cross-tenant 누수 위험."
        )

    actual = doc.get("tenant_id")
    if not actual:
        raise MissingTenantIdError(
            f"es_doc_missing_tenant_id: block_id={doc.get('block_id')!r} "
            f"document_id={doc.get('document_id')!r}"
        )
    if str(actual) != str(expected_tenant_id):
        raise MissingTenantIdError(
            f"es_doc_tenant_id_mismatch: actual={actual!r} "
            f"expected={expected_tenant_id!r} block_id={doc.get('block_id')!r}"
        )


__all__ = [
    "MissingTenantIdError",
    "with_tenant_term",
    "ensure_tenant_id_field",
]

"""KMS documents 백엔드 agent 데이터 저장소.

각 아이템 (일정/일기/뉴스구독/리마인더) = 1 document.
- repository: ``__agent_data__`` (tenant 별, 자동 생성)
- document_type: 카테고리별 (``agent_schedule``, ``agent_diary``, ``agent_news_sub``,
  ``agent_reminder``). ``(tenant_id, name)`` UNIQUE 이므로 tenant 스코프로 생성.
- title: 사용자 표시 제목
- processing_meta.body: 구조화 JSON (서비스별 필드)

chunking/embedding/retrieval 파이프라인은 건드리지 않는다 —
이 문서들은 indexing 대상이 아니라 단순 structured storage.

## 스키마 확인 (2026-04-25, Phase 11)
- ``documents`` 에 ``tenant_id`` 직접 컬럼 추가됨 (migration 030). 본 저장소는
  insert 시 ``tenant_id`` 를 직접 채우고, 모든 SELECT 는 ``d.tenant_id`` 와
  기존 ``r.tenant_id`` 양쪽을 모두 검사 — defense-in-depth (둘 중 하나만
  비정상이라도 다른 한쪽이 격리).
- ``documents.status`` default 는 ``'draft'`` — 본 저장소는 ``'active'`` 로 명시 insert,
  soft delete 시 ``'archived'`` 로 전환.
- ``repositories`` 는 ``search_mode``/``display_config``/``llm_config`` NOT NULL —
  insert 시 모두 채움.
- ``document_types`` 는 ``(tenant_id, name)`` UNIQUE (전역 아님). ``updated_at`` 컬럼 없음.
- ``list_items_global_doctype`` / ``list_tenants_with_doctype`` 은 cross-tenant
  helper — 각각 ``tenant_id`` kwarg 를 추가로 받아 단일 tenant 로 좁히는 것도
  지원 (admin UI 의 tenant 선택 모드용).

## D23 §7 — include_null_owner admin sentinel (2026-05-08)

GPT-5 phase 0 R4 GO 후 적용. 일반 caller 가 ``include_null_owner=True`` 를
임의로 넘기면 NULL bucket (격리 안 된 row) 가 노출 — admin 전용 enforcement.

**defense-in-depth 3 layer**:
- L1 (engine): LLM payload 의 bool True → admin 검증 후 sentinel 변환
- L2 (storage, 본 모듈): 일반 bool True 거부 (ValueError) — sentinel only
- L3 (admin endpoint): membership role 검증 후 sentinel 명시 전달

``ADMIN_NULL_OWNER_OK`` 는 객체 identity 로 검증 — 외부에서 spoof 못 함.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

AGENT_DATA_REPO_NAME = "__agent_data__"


# D23 §7 — admin null-owner sentinel (2026-05-08, GPT-5 phase 0 R4 GO).
# include_null_owner 인자는 일반 bool 거부 — sentinel identity 만 통과.
class _AdminNullOwnerOk:
    """include_null_owner 우회 차단 — 객체 identity 로 strict 검증.

    *모듈 수준 단일 인스턴스* (``ADMIN_NULL_OWNER_OK``) 로만 사용. 일반 bool
    True 는 ``list_items*`` 에서 ValueError. caller (engine 의 admin 검증
    layer) 만 sentinel 을 storage 로 전달.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover — debugging 보조
        return "ADMIN_NULL_OWNER_OK"

    def __bool__(self) -> bool:
        # admin path 에서 ``if include_null_owner`` 같은 truthy 검사 호환.
        return True


ADMIN_NULL_OWNER_OK = _AdminNullOwnerOk()


def _resolve_include_null_owner(value: Any) -> bool:
    """include_null_owner 값을 *효과 bool* 로 변환.

    Strict contract:
        - ``False`` (default) → False (격리)
        - ``ADMIN_NULL_OWNER_OK`` (sentinel identity) → True (NULL bucket 노출)
        - 일반 bool ``True`` → ValueError (admin enforcement 우회 차단)
        - 그 외 truthy 값 → ValueError
    """
    if value is False or value is None:
        return False
    if value is ADMIN_NULL_OWNER_OK:
        return True
    # 일반 bool True / 1 / "yes" / 다른 객체 — 모두 거부.
    raise ValueError(
        "include_null_owner 는 admin 전용. "
        "ADMIN_NULL_OWNER_OK sentinel (agent_document_store import) 만 허용. "
        f"got: {value!r}"
    )


async def _get_or_create_repo_and_doctype(
    conn, tenant_id: UUID, document_type_name: str
) -> tuple[UUID, UUID]:
    """repo + document_type 확보. 없으면 자동 생성.

    ``ON CONFLICT`` 은 두 테이블 모두 ``(tenant_id, name)`` UNIQUE 를 이용.
    """
    # 1. repository
    r = await conn.execute(
        text(
            """
            INSERT INTO repositories
              (id, tenant_id, name, description,
               config, search_mode, display_config, llm_config, is_active)
            VALUES
              (gen_random_uuid(), :tid, :name, 'Agent 운영 데이터 (구조화 저장)',
               '{}'::jsonb, 'simple', '{}'::jsonb, '{}'::jsonb, true)
            ON CONFLICT ON CONSTRAINT uq_repositories_tenant_name
              DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"tid": tenant_id, "name": AGENT_DATA_REPO_NAME},
    )
    repo_id: UUID = r.scalar_one()

    # 2. document_type (tenant-scoped)
    r = await conn.execute(
        text(
            """
            INSERT INTO document_types
              (id, tenant_id, name, description, is_system)
            VALUES
              (gen_random_uuid(), :tid, :name, :desc, true)
            ON CONFLICT ON CONSTRAINT uq_document_types_tenant_name
              DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {
            "tid": tenant_id,
            "name": document_type_name,
            "desc": f"Agent 데이터 타입 (non-indexed structured storage): {document_type_name}",
        },
    )
    dt_id: UUID = r.scalar_one()
    return repo_id, dt_id


async def _verify_owner_agent_in_tenant(
    conn, tenant_id: UUID, owner_agent_id: UUID
) -> bool:
    """``owner_agent_id`` 가 *동일 tenant* 의 agent 인지 검증.

    Phase 1 / 알렘빅 072 + GPT-5 검증 (2026-05-07): cross-tenant 지정 차단.
    호출측이 agent_id 를 페이로드에 임의 넣어도 본 함수가 false 면 INSERT 거부.
    """
    r = await conn.execute(
        text("SELECT 1 FROM agents WHERE id = :aid AND tenant_id = :tid"),
        {"aid": owner_agent_id, "tid": tenant_id},
    )
    return r.first() is not None


async def create_item(
    engine: AsyncEngine,
    tenant_id: UUID,
    document_type_name: str,
    title: str,
    body: dict[str, Any],
    *,
    scope_group: str | None = None,
    owner_agent_id: UUID | None = None,
) -> UUID:
    """새 document insert. ``processing_meta.body`` 에 structured JSON 저장.

    ``scope_group`` 이 주어지면 ``documents.scope_group`` 컬럼 + body 내부에도
    동일 키로 기록 (UI 가 body 만 읽어도 노출 가능). KMS 본문 등 무관 도메인은
    None 으로 두면 컬럼이 NULL 로 남고 기존 동작 유지.

    ``owner_agent_id`` (Phase 1 / 알렘빅 072) 는 *agent scope hardcode* 도구
    (현재 schedule.*, 추후 memo/expense/...) 에서 채움. None 이면 NULL —
    legacy/admin 경로 동작 그대로.

    GPT-5 검증 반영: ``owner_agent_id`` 가 주어지면 *동일 tenant* 인지 검증 후
    INSERT (cross-tenant 지정 차단). 검증 실패 → ValueError.

    Returns the new document UUID.
    """
    async with engine.begin() as conn:
        # Phase 1 — cross-tenant agent_id 차단.
        if owner_agent_id is not None:
            if not await _verify_owner_agent_in_tenant(
                conn, tenant_id, owner_agent_id
            ):
                raise ValueError(
                    f"owner_agent_id {owner_agent_id} not in tenant {tenant_id}"
                )
        repo_id, dt_id = await _get_or_create_repo_and_doctype(
            conn, tenant_id, document_type_name
        )
        doc_id = uuid4()
        meta_body = dict(body)
        if scope_group is not None:
            meta_body.setdefault("scope_group", scope_group)
        await conn.execute(
            text(
                """
                INSERT INTO documents
                  (id, tenant_id, repository_id, document_type_id, title,
                   processing_meta, status, scope_group, owner_agent_id)
                VALUES
                  (:id, :tid, :rid, :dtid, :title, CAST(:meta AS jsonb),
                   'active', :sg, :oaid)
                """
            ),
            {
                "id": doc_id,
                "tid": tenant_id,
                "rid": repo_id,
                "dtid": dt_id,
                "title": title,
                "meta": json.dumps({"body": meta_body}, ensure_ascii=False),
                "sg": scope_group,
                "oaid": owner_agent_id,
            },
        )
        return doc_id


async def list_items(
    engine: AsyncEngine,
    tenant_id: UUID,
    document_type_name: str,
    *,
    scope_group: str | None = None,
    owner_agent_id: UUID | None = None,
    include_null_owner: bool | _AdminNullOwnerOk = False,
) -> list[dict[str, Any]]:
    """tenant + document_type 의 active 아이템들. ``id`` + ``title`` + body 필드 반환.

    ``scope_group`` 이 명시되면 매칭 row 만 반환. None 이면 scope 무관 — 기존
    호출자(KMS) 와 호환.

    ``owner_agent_id`` (Phase 1 / 알렘빅 072):
        - UUID 가 주어지면 *해당 agent* 의 row 만 반환 (default-deny 격리).
        - ``include_null_owner=ADMIN_NULL_OWNER_OK`` (sentinel) 면 NULL owner
          도 함께 반환 (admin 전용 경로). D23 §7 — 일반 bool True 는 ValueError.
        - 둘 다 None / False 이면 owner 필터 없음 — 기존 호출자 호환.

    GPT-5 검증 반영: owner_agent_id 격리 시 NULL row 는 default 비가시.
    legacy/admin 경로 (e.g. backfill, admin UI) 만 ``ADMIN_NULL_OWNER_OK``
    sentinel 로 옵트인해서 NULL 를 함께 본다 — bool True 는 admin enforcement
    우회 차단 (D23 §7, GPT-5 phase 0 R4 GO).

    생성 순서 (created_at ASC) 로 정렬.
    """
    # D23 §7 — bool True 거부, sentinel 만 통과.
    effective_include_null = _resolve_include_null_owner(include_null_owner)
    sql = """
        SELECT d.id, d.title, d.processing_meta
        FROM documents d
        JOIN document_types dt ON d.document_type_id = dt.id
        JOIN repositories r ON d.repository_id = r.id
        WHERE r.tenant_id = :tid
          AND dt.tenant_id = :tid
          AND (d.tenant_id = :tid OR d.tenant_id IS NULL)
          AND dt.name = :dt
          AND r.name = :repo
          AND d.status = 'active'
    """
    params: dict[str, Any] = {
        "tid": tenant_id,
        "dt": document_type_name,
        "repo": AGENT_DATA_REPO_NAME,
    }
    if scope_group is not None:
        sql += " AND d.scope_group = :sg"
        params["sg"] = scope_group
    if owner_agent_id is not None:
        if effective_include_null:
            sql += " AND (d.owner_agent_id = :oaid OR d.owner_agent_id IS NULL)"
        else:
            sql += " AND d.owner_agent_id = :oaid"
        params["oaid"] = owner_agent_id
    sql += " ORDER BY d.created_at ASC"
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    out: list[dict[str, Any]] = []
    for doc_id, title, meta in rows:
        body = ((meta or {}).get("body")) or {}
        item = {"id": str(doc_id), "title": title}
        # body 의 필드를 top-level 로 풀어서 expose — UI/툴이 기존 mock 과 동일
        # shape 을 소비하도록 맞춘다.
        item.update(body)
        out.append(item)
    return out


async def list_items_filtered(
    engine: AsyncEngine,
    tenant_id: UUID,
    document_type_name: str,
    *,
    title_contains: str | None = None,
    body_equals: dict[str, Any] | None = None,
    body_text_contains: tuple[str, str] | None = None,
    order_desc: bool = False,
    limit: int | None = None,
    sort: str | None = None,
    scope_group: str | None = None,
    owner_agent_id: UUID | None = None,
    include_null_owner: bool | _AdminNullOwnerOk = False,
) -> list[dict[str, Any]]:
    """``list_items`` 의 필터링 버전.

    D23 §7 — ``include_null_owner`` 는 ``ADMIN_NULL_OWNER_OK`` sentinel 만 허용.
    일반 bool ``True`` 는 ValueError (admin enforcement 우회 차단).

    Parameters
    ----------
    title_contains
        ``d.title ILIKE %val%`` 부분 일치 (대소문자 무시).
    body_equals
        ``processing_meta -> 'body' ->> key = val`` 의 AND 조합.
    body_text_contains
        ``(key, substring)`` — ``processing_meta -> 'body' ->> key ILIKE %sub%``.
    order_desc
        True 이면 ``created_at DESC``, 아니면 ``ASC`` (``list_items`` 와 동일).
    sort
        ``"trust"`` 일 때 ``processing_meta -> 'activation' ->> 'trust_score'``
        를 numeric 으로 캐스트한 뒤 내림차순. NULL 은 0 으로 처리해 뒤로 밀어
        검색 ranker 가 검증된 문서를 우선 노출하도록 한다. None 이면 기존
        ``created_at`` 정렬.
    limit
        SQL ``LIMIT`` — None 이면 제한 없음.
    """
    # D23 §7 — bool True 거부, sentinel 만 통과.
    effective_include_null = _resolve_include_null_owner(include_null_owner)

    clauses: list[str] = [
        "r.tenant_id = :tid",
        "dt.tenant_id = :tid",
        "(d.tenant_id = :tid OR d.tenant_id IS NULL)",
        "dt.name = :dt",
        "r.name = :repo",
        "d.status = 'active'",
    ]
    params: dict[str, Any] = {
        "tid": tenant_id,
        "dt": document_type_name,
        "repo": AGENT_DATA_REPO_NAME,
    }

    if title_contains:
        clauses.append("d.title ILIKE :t_like")
        params["t_like"] = f"%{title_contains}%"

    if scope_group is not None:
        clauses.append("d.scope_group = :sg")
        params["sg"] = scope_group

    if owner_agent_id is not None:
        # Phase 1 (알렘빅 072) — 격리 옵트인. sentinel 통과 시 NULL 도 함께.
        if effective_include_null:
            clauses.append(
                "(d.owner_agent_id = :oaid OR d.owner_agent_id IS NULL)"
            )
        else:
            clauses.append("d.owner_agent_id = :oaid")
        params["oaid"] = owner_agent_id

    if body_equals:
        # 각 key 마다 AND 추가. 파라미터 이름 충돌 방지를 위해 인덱스 suffix.
        for i, (k, v) in enumerate(body_equals.items()):
            k_param = f"be_k_{i}"
            v_param = f"be_v_{i}"
            # JSONB key 는 바인드할 수 없으므로 식별자를 문자열 포맷으로 주입.
            # k 는 dict key 라 내부에서 통제 (외부 입력은 호출측에서 sanitize).
            clauses.append(
                f"d.processing_meta -> 'body' ->> :{k_param} = :{v_param}"
            )
            params[k_param] = k
            params[v_param] = v

    if body_text_contains:
        bkey, bsub = body_text_contains
        clauses.append(
            "d.processing_meta -> 'body' ->> :btc_k ILIKE :btc_like"
        )
        params["btc_k"] = bkey
        params["btc_like"] = f"%{bsub}%"

    order_sql = "DESC" if order_desc else "ASC"
    if sort == "trust":
        # activation.trust_score 는 verify() 단계에서 0~1 score 로 박힘.
        # NULL → 0 처리 (검증 안 된 문서는 뒤로). NULLS LAST 명시 (Postgres
        # DESC 기본은 NULLS FIRST). created_at 보조키로 정렬 안정성 확보.
        order_clause = (
            "COALESCE(NULLIF(d.processing_meta -> 'activation' ->> 'trust_score', '')::numeric, 0) "
            "DESC NULLS LAST, "
            "d.created_at DESC"
        )
    else:
        order_clause = f"d.created_at {order_sql}"
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT :lim"
        params["lim"] = int(limit)

    sql = f"""
        SELECT d.id, d.title, d.processing_meta
        FROM documents d
        JOIN document_types dt ON d.document_type_id = dt.id
        JOIN repositories r ON d.repository_id = r.id
        WHERE {" AND ".join(clauses)}
        ORDER BY {order_clause}
        {limit_sql}
    """

    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()

    out: list[dict[str, Any]] = []
    for doc_id, title, meta in rows:
        body = ((meta or {}).get("body")) or {}
        item = {"id": str(doc_id), "title": title}
        item.update(body)
        out.append(item)
    return out


async def update_item(
    engine: AsyncEngine,
    tenant_id: UUID,
    document_type_name: str,
    item_id: str,
    *,
    title: str | None = None,
    body_patch: dict[str, Any] | None = None,
    owner_agent_id: UUID | None = None,
) -> bool:
    """item 의 title 또는 body 일부 갱신. body_patch 는 깊이 1 머지.

    ``owner_agent_id`` (Phase 1 / 알렘빅 072):
        - UUID 가 주어지면 해당 agent 의 row 만 매칭 — *다른 agent 의 row 는
          매칭조차 안 되어 silently False 반환*. PermissionError 안 던지고
          False 를 돌려 호출측이 "찾지 못함" 처리.
        - None 이면 owner 필터 없음 (기존 호출자 호환). 단 호출측이 격리 모드
          (schedule_store) 에서는 *반드시* 채워야 한다.
        - ``owner_agent_id`` 자체는 *immutable* — body_patch / title 외에
          owner_agent_id 를 갱신하지 않는다 (SQL UPDATE 에서 제외).

    Returns: True 면 업데이트, False 면 매칭 row 없음 (404 또는 owner mismatch).
    """
    if not title and not body_patch:
        return False
    async with engine.begin() as conn:
        # 현재 row 조회 (tenant + doctype + (선택) owner 일치 + active).
        owner_clause = ""
        params: dict[str, Any] = {
            "id": item_id,
            "tid": tenant_id,
            "repo": AGENT_DATA_REPO_NAME,
            "dt": document_type_name,
        }
        if owner_agent_id is not None:
            owner_clause = " AND d.owner_agent_id = :oaid"
            params["oaid"] = owner_agent_id
        cur = (
            await conn.execute(
                text(
                    f"""
                    SELECT d.id, d.title, d.processing_meta
                      FROM documents d
                      JOIN document_types dt ON d.document_type_id = dt.id
                      JOIN repositories r ON d.repository_id = r.id
                     WHERE d.id = :id
                       AND d.status = 'active'
                       AND r.tenant_id = :tid AND r.name = :repo
                       AND dt.tenant_id = :tid AND dt.name = :dt
                       {owner_clause}
                    """
                ),
                params,
            )
        ).first()
        if cur is None:
            return False
        cur_meta = dict(cur.processing_meta or {})
        cur_body = dict(cur_meta.get("body") or {})
        new_title = title if title is not None else cur.title
        new_body = cur_body
        if body_patch:
            new_body = {**cur_body, **body_patch}
        cur_meta["body"] = new_body
        await conn.execute(
            text(
                """
                UPDATE documents
                   SET title = :title,
                       processing_meta = CAST(:meta AS jsonb),
                       updated_at = NOW()
                 WHERE id = :id
                """
            ),
            {
                "id": item_id,
                "title": new_title,
                "meta": json.dumps(cur_meta, ensure_ascii=False),
            },
        )
        return True


async def delete_item(
    engine: AsyncEngine,
    tenant_id: UUID,
    document_type_name: str,
    item_id: str,
    *,
    owner_agent_id: UUID | None = None,
) -> bool:
    """document status='archived' (soft delete).

    tenant + document_type 조합이 일치하고 현재 active 일 때만 성공 — False 면 no-op.

    ``owner_agent_id`` (Phase 1 / 알렘빅 072):
        - UUID 가 주어지면 해당 agent 의 row 만 매칭 — 다른 agent 의 row 는
          UPDATE 가 0 row 영향 → False 반환 (silent no-op).
        - None 이면 owner 필터 없음 (기존 호출자 호환).
    """
    async with engine.begin() as conn:
        owner_clause = ""
        params: dict[str, Any] = {
            "id": item_id,
            "tid": tenant_id,
            "repo": AGENT_DATA_REPO_NAME,
            "dt": document_type_name,
        }
        if owner_agent_id is not None:
            owner_clause = " AND owner_agent_id = :oaid"
            params["oaid"] = owner_agent_id
        r = await conn.execute(
            text(
                f"""
                UPDATE documents
                SET status = 'archived', updated_at = NOW()
                WHERE id = :id
                  AND status = 'active'
                  AND repository_id IN (
                    SELECT r.id FROM repositories r
                    WHERE r.tenant_id = :tid AND r.name = :repo
                  )
                  AND document_type_id IN (
                    SELECT dt.id FROM document_types dt
                    WHERE dt.tenant_id = :tid AND dt.name = :dt
                  )
                  {owner_clause}
                """
            ),
            params,
        )
        return (r.rowcount or 0) > 0


# ── Cross-tenant helpers (Stage B-4/B-5, admin/scheduler 전용) ─────────
#
# 일반 사용자 흐름에서는 절대 호출하지 말 것. ``list_subscribers``,
# scheduled trigger fan-out, 관리자 리포트 뷰 등 명확히 tenant 경계를 넘는
# 경로에서만 쓴다. 호출측이 의도를 주석으로 남겨야 한다.


async def list_tenants_with_doctype(
    engine: AsyncEngine,
    document_type_name: str,
    *,
    tenant_id: UUID | str | None = None,
) -> list[UUID]:
    """해당 doctype 의 active document 를 하나라도 가진 tenant_id 들.

    scheduled trigger 가 "이 스킬을 구독한 모든 사용자" 를 돌 때 쓰는 쿼리.
    - repository 는 ``AGENT_DATA_REPO_NAME`` 로 한정 — 다른 repo 의 문서는 무시.
    - document_types 는 ``(tenant_id, name)`` UNIQUE 라 tenant 당 최대 1 row.
    - DISTINCT + status='active' — 삭제된 구독자는 제외.
    - ``tenant_id`` 가 주어지면 해당 tenant 만 검사 (admin UI 의 단일 tenant
      모드용). None 이면 기존대로 전 tenant 스캔.
    """
    extra_clause = ""
    params: dict[str, Any] = {
        "dt": document_type_name,
        "repo": AGENT_DATA_REPO_NAME,
    }
    if tenant_id is not None:
        extra_clause = " AND r.tenant_id = :tid AND (d.tenant_id = :tid OR d.tenant_id IS NULL)"
        params["tid"] = tenant_id

    sql = f"""
        SELECT DISTINCT r.tenant_id
        FROM documents d
        JOIN document_types dt ON d.document_type_id = dt.id
        JOIN repositories r ON d.repository_id = r.id
        WHERE dt.name = :dt
          AND r.name = :repo
          AND d.status = 'active'
          AND dt.tenant_id = r.tenant_id
          {extra_clause}
    """
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    return [row[0] for row in rows]


async def list_items_global_doctype(
    engine: AsyncEngine,
    document_type_name: str,
    *,
    limit: int | None = None,
    order_desc: bool = False,
    tenant_id: UUID | str | None = None,
) -> list[dict[str, Any]]:
    """tenant 필터 없이 doctype 전역 조회 — 관리자/스케줄러 경로 전용.

    보안 주의: 일반 사용자 호출 금지. reminder.list_recent 같은 관리 UI 의
    "모든 사용자의 reminder" 전역 뷰, 또는 scheduled trigger 의 관리 리포트에서만 쓴다.
    반환 shape 은 ``list_items`` 와 동일 (id + title + body 풀어놓기) + 소속
    ``tenant_id`` 추가 — 호출자가 누구 데이터인지 구분할 수 있도록.

    ``tenant_id`` 가 주어지면 해당 tenant 로 스코프 좁힘 (admin UI 의 단일
    tenant 보기). None 이면 기존대로 전역.
    """
    order_sql = "DESC" if order_desc else "ASC"
    limit_sql = ""
    params: dict[str, Any] = {
        "dt": document_type_name,
        "repo": AGENT_DATA_REPO_NAME,
    }
    extra_clause = ""
    if tenant_id is not None:
        extra_clause = " AND r.tenant_id = :tid AND (d.tenant_id = :tid OR d.tenant_id IS NULL)"
        params["tid"] = tenant_id
    if limit is not None:
        limit_sql = "LIMIT :lim"
        params["lim"] = int(limit)

    sql = f"""
        SELECT d.id, d.title, d.processing_meta, r.tenant_id
        FROM documents d
        JOIN document_types dt ON d.document_type_id = dt.id
        JOIN repositories r ON d.repository_id = r.id
        WHERE dt.name = :dt
          AND r.name = :repo
          AND d.status = 'active'
          AND dt.tenant_id = r.tenant_id
          {extra_clause}
        ORDER BY d.created_at {order_sql}
        {limit_sql}
    """
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()

    out: list[dict[str, Any]] = []
    for doc_id, title, meta, tenant_id in rows:
        body = ((meta or {}).get("body")) or {}
        item: dict[str, Any] = {
            "id": str(doc_id),
            "title": title,
            "tenant_id": str(tenant_id),
        }
        item.update(body)
        out.append(item)
    return out

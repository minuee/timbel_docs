"""KMS Meta tool — tenant 인벤토리 자기 소개 (read_only).

자기 소개적 메타 질의("내 워크스페이스에 뭐 있어?", "지식 몇 개 등록됐어?",
"활성 스킬 무엇?") 에 대해 현재 tenant 의 자료 인벤토리를 한 번에 돌려준다.

기존 ``kms_inventory.get_summary`` 는 documents 의 status 분포·용량·7일 변동
중심이지만, ``kms_meta.get_my_inventory`` 는 그것 + 저장소 / 외부 에이전트 /
agent_data (schedule, diary, news_sub) / 활성 스킬 / 마지막 문서 업데이트 시각
까지 한 호출로 묶어 주어 사용자가 "내가 가진 게 뭐야?" 한 마디로 모든 카테
고리의 갯수를 받게 한다.

side_effect_level=read_only — Phase 8 ExecutionPolicyGuard 우회 (consequential
아님) 으로 즉시 실행.

사용처:
- ``kms_meta_query`` skill 의 ``tool: kms_meta.get_my_inventory``
- 향후 capability_briefing / 자기소개 응답 보강에 인용 가능.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


def get_my_inventory(
    *,
    db_conn: Any,
    tenant_id: str | None = None,
    personal_tenant_id: str | None = None,
) -> dict[str, Any]:
    """현재 tenant 의 자료 인벤토리 + 한국어 요약.

    Args:
      db_conn: SQLAlchemy sync Connection.
      tenant_id: 우선 적용. 비즈니스 / 공유 tenant.
      personal_tenant_id: tenant_id 미지정 시 fallback (개인 tenant).

    Returns:
      {
        "summary_ko": "...",
        "raw": {
          "documents": int,            # active 문서 수
          "repositories": int,         # is_active 저장소 수
          "agents": int,               # is_active 외부 에이전트 수
          "schedules": int,            # agent_schedule 타입 active document
          "diaries": int,              # agent_diary 타입 active document
          "news_subscriptions": int,   # agent_news_sub 타입 active document
          "active_skills": int,        # tenant_skills row count
          "last_doc_update": str|None  # ISO-8601 또는 None
        }
      }

    tenant_id 가 None 이면 personal_tenant_id 로 fallback. 둘 다 None 이면
    빈 결과 + summary_ko = "tenant 가 지정되지 않았습니다." 를 돌려준다.
    """
    tid_str = tenant_id or personal_tenant_id
    if tid_str is None:
        return {
            "summary_ko": "현재 tenant 가 지정되지 않아 인벤토리를 조회하지 못했습니다.",
            "raw": {},
        }

    raw: dict[str, Any] = {
        "documents": 0,
        "blocks": 0,
        "indexed_blocks": 0,
        "repositories": 0,
        "agents": 0,
        "schedules": 0,
        "diaries": 0,
        "news_subscriptions": 0,
        "active_skills": 0,
        "last_doc_update": None,
    }

    # documents — active 만, tenant_id 직접 컬럼 사용 (migration 030)
    row = db_conn.execute(
        text(
            """
            SELECT COUNT(*) FROM documents
             WHERE tenant_id = CAST(:tid AS uuid)
               AND status = 'active'
            """
        ),
        {"tid": tid_str},
    ).first()
    raw["documents"] = int(row[0]) if row and row[0] is not None else 0

    # blocks — tenant 의 active document 에 속한 active block 수 (P11-17)
    row = db_conn.execute(
        text(
            """
            SELECT COUNT(*) FROM blocks b
              JOIN documents d ON d.id = b.document_id
             WHERE d.tenant_id = CAST(:tid AS uuid)
               AND d.status = 'active'
               AND b.validity_status = 'active'
            """
        ),
        {"tid": tid_str},
    ).first()
    raw["blocks"] = int(row[0]) if row and row[0] is not None else 0

    # indexed_blocks — vector index 에 등록된 활성 block (검색 가능 단위)
    row = db_conn.execute(
        text(
            """
            SELECT COUNT(*) FROM blocks b
              JOIN documents d ON d.id = b.document_id
             WHERE d.tenant_id = CAST(:tid AS uuid)
               AND d.status = 'active'
               AND b.validity_status = 'active'
               AND b.is_indexed = true
            """
        ),
        {"tid": tid_str},
    ).first()
    raw["indexed_blocks"] = int(row[0]) if row and row[0] is not None else 0

    # repositories — is_active 만
    row = db_conn.execute(
        text(
            """
            SELECT COUNT(*) FROM repositories
             WHERE tenant_id = CAST(:tid AS uuid)
               AND is_active = true
            """
        ),
        {"tid": tid_str},
    ).first()
    raw["repositories"] = int(row[0]) if row and row[0] is not None else 0

    # agents — is_active 만
    row = db_conn.execute(
        text(
            """
            SELECT COUNT(*) FROM agents
             WHERE tenant_id = CAST(:tid AS uuid)
               AND is_active = true
            """
        ),
        {"tid": tid_str},
    ).first()
    raw["agents"] = int(row[0]) if row and row[0] is not None else 0

    # agent_data documents (schedule / diary / news_sub) — document_types 조인.
    # document_types 는 (tenant_id, name) UNIQUE 지만 system 타입은 default
    # tenant 에 정의되어 있을 수 있어 name 만으로 매칭.
    for doctype, key in (
        ("agent_schedule", "schedules"),
        ("agent_diary", "diaries"),
        ("agent_news_sub", "news_subscriptions"),
    ):
        row = db_conn.execute(
            text(
                """
                SELECT COUNT(*) FROM documents d
                  JOIN document_types t ON d.document_type_id = t.id
                 WHERE d.tenant_id = CAST(:tid AS uuid)
                   AND t.name = :doctype
                   AND d.status = 'active'
                """
            ),
            {"tid": tid_str, "doctype": doctype},
        ).first()
        raw[key] = int(row[0]) if row and row[0] is not None else 0

    # active_skills — tenant_skills row 수 (per-tenant enabled 집합)
    row = db_conn.execute(
        text(
            """
            SELECT COUNT(*) FROM tenant_skills
             WHERE tenant_id = CAST(:tid AS uuid)
            """
        ),
        {"tid": tid_str},
    ).first()
    raw["active_skills"] = int(row[0]) if row and row[0] is not None else 0

    # last_doc_update — 가장 최근 documents.updated_at (status 무관)
    row = db_conn.execute(
        text(
            """
            SELECT MAX(updated_at) FROM documents
             WHERE tenant_id = CAST(:tid AS uuid)
            """
        ),
        {"tid": tid_str},
    ).first()
    if row and row[0] is not None:
        raw["last_doc_update"] = row[0].isoformat()

    # 한국어 요약 — 0 인 항목은 자연스럽게 생략하도록 부분 문장으로 구성.
    parts: list[str] = []
    if raw["documents"]:
        parts.append(f"문서 {raw['documents']:,}건")
    if raw["blocks"]:
        if raw["indexed_blocks"] and raw["indexed_blocks"] != raw["blocks"]:
            parts.append(
                f"블록 {raw['blocks']:,}개 (검색 색인 {raw['indexed_blocks']:,}개)"
            )
        else:
            parts.append(f"블록 {raw['blocks']:,}개")
    if raw["repositories"]:
        parts.append(f"저장소 {raw['repositories']:,}개")
    if raw["agents"]:
        parts.append(f"외부 에이전트 {raw['agents']:,}개")
    if raw["schedules"]:
        parts.append(f"일정 {raw['schedules']:,}건")
    if raw["diaries"]:
        parts.append(f"일기 {raw['diaries']:,}건")
    if raw["news_subscriptions"]:
        parts.append(f"뉴스 구독 {raw['news_subscriptions']:,}건")
    if raw["active_skills"]:
        parts.append(f"활성 스킬 {raw['active_skills']:,}개")

    if parts:
        first = "현재 워크스페이스에 " + ", ".join(parts) + "가 있습니다."
    else:
        first = "현재 워크스페이스에 등록된 자료가 아직 없습니다."

    if raw["last_doc_update"]:
        first += f" 마지막 문서 업데이트는 {raw['last_doc_update']} 입니다."

    return {"summary_ko": first, "raw": raw}

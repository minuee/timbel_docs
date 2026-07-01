"""개인 일정 저장소 — Redis (legacy) / KMS documents (Stage B-2) dual backend.

env ``AGENT_DATA_STORE`` 로 백엔드 선택:
- ``redis`` (기본, 하위호환) — 기존 ``_redis_store`` 리스트에 JSON item 저장.
- ``kms``               — KMS ``documents`` 테이블에 한 일정 = 한 document.

KMS 경로는 tenant 격리를 위해 ``tenant_id`` (UUID string) 를 args 에서 요구한다.
Engine 의 ``_resolve_args`` 가 ``$personal_tenant_id`` 치환을 제공.

Week 5 polish B 의 Redis 리스트 설계는 유지 — B-2/3/4/5 전환이 끝날 때까지
하위호환 경로로 남겨둔다.

PR-C (KMS-Plus, 2026-04-27) — idempotency.
``(scope_key, when, title)`` 해시 기반으로 동일 일정 재등록을 silent skip.
사용자가 "내일 저녁 6시 윤찬우 만남 등록해" 를 두 번 말해도 일정 뷰에 두 줄
나타나지 않으며 두 번째 호출은 ``{"duplicate": True, "summary": "이미 등록된 일정입니다"}``
를 추가로 돌려줘 페르소나 LLM 이 "이미 있어요" 류 응대를 유도.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.common.config import settings

_CATEGORY = "schedule"
_DOCUMENT_TYPE = "agent_schedule"


# ── Engine 싱글턴 (KMS 경로에서만 사용) ─────────────────────────────────
_SHARED_ENGINE: AsyncEngine | None = None


def _get_shared_engine() -> AsyncEngine:
    """KMS 모드에서 재사용할 AsyncEngine. lazy lazy lazy.

    테스트에서 ``_reset_engine_for_tests()`` 로 비우고 재생성 가능.
    """
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _SHARED_ENGINE


async def _reset_engine_for_tests() -> None:
    """테스트 전용 — engine 싱글턴 dispose + 재생성 강제."""
    global _SHARED_ENGINE
    if _SHARED_ENGINE is not None:
        await _SHARED_ENGINE.dispose()
        _SHARED_ENGINE = None


def _store_mode() -> str:
    """``AGENT_DATA_STORE`` 환경 변수 읽기 (redis | kms). 기본 redis."""
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _reset() -> None:
    """하위 호환 sync 인터페이스 — conftest async fixture 가 실제 flush."""
    rs._reset_sync()


# ── Idempotency helper ───────────────────────────────────────────────


def _coerce_scalar(v: Any) -> Any:
    """LLM 이 unresolved plan 의존 ({"args_from_step": N}) 을 string 슬롯에
    흘려넣은 경우 차단. 정상값 (str/int/float/None) 은 그대로 통과.

    DB 에 dict 가 저장되면 frontend 가 React error #31 로 죽는다 (객체 child).
    여기서 None 으로 떨어뜨려 누출을 막고, dedup_signature 등도 ``str(None)``
    로 해석되어 안전.
    """
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return None


def _dedup_signature(when: Any, title: Any) -> str:
    """``(when, title)`` 정규화 해시 — scope (phone/tenant) 와 결합해 dedup key.

    공백/대소문자 차이만으로 중복 분실 안 되도록 strip+lower. 한국어는 lower 영향 X.
    None 은 빈 문자열 처리 — 어차피 collect 가드가 None 을 막지만 안전판.
    """
    norm_when = str(when or "").strip()
    norm_title = str(title or "").strip().lower()
    raw = f"{norm_when}|{norm_title}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _duplicate_response(
    existing_id: str,
    *,
    title: str | None = None,
    when: str | None = None,
    where: str | None = None,
) -> dict[str, Any]:
    """idempotent 재호출 응답 — P11-19l: 정보 echo 추가.

    이전엔 '이미 등록된 일정입니다' 한 줄 → judge fail (시각/제목 echo 누락).
    title + when + where 받아 응답 본문에 명시.
    """
    parts = []
    if title:
        parts.append(title)
    if when:
        parts.append(when)
    if where:
        parts.append(where)
    detail = " · ".join(parts)
    summary = (
        f"이미 등록된 일정입니다 — {detail}"
        if detail
        else "이미 등록된 일정입니다"
    )
    return {
        "id": existing_id,
        "success": True,
        "duplicate": True,
        "title": title,
        "when": when,
        "where": where,
        "summary": summary,
    }


# ── Public tool entry points ─────────────────────────────────────────


def _title_key(title: Any) -> str:
    """제목 정규화 — 공백·대소문자 무시. 같은 일정 식별자."""
    return str(title or "").strip().lower()


async def create(args: dict[str, Any]) -> dict[str, Any]:
    """일정 등록 — P11-15 (2026-04-29) 같은 title 있으면 update merge.

    KMS 모드에서는 ``tenant_id`` (UUID string) 를 args 에서 받는다. Redis 모드는
    기존 ``phone`` scope 을 유지.

    Dedup 로직 (P11-15 강화):
    - 1st: 완전히 같은 (when, title) → silent skip + duplicate 플래그 (옛 PR-C).
    - 2nd: 같은 title 만 매칭 (when 다름) → 기존 row 의 when/where/who/recurrence
      를 새 값으로 *merge*. 사용자 케이스: "5월 4일 송어횟집 등록" → "오후 4시야"
      → 시간 추가는 update 인데 옛엔 새 row 추가.

    Phase 1 — agent scope 격리 (알렘빅 072 + 사용자 명시 2026-05-07):
        ``args["agent_id"]`` 는 engine ``_resolve_args_with_defaults`` 가 자동
        주입 (LLM 명시값은 *항상* 덮어씀 — 보안). 들어오면 owner_agent_id 로
        INSERT 하고 dedup 도 *해당 agent 의 row 만* 검사. agent_id 없으면 (CLI
        / 어드민 직접 호출 등) NULL 로 INSERT — legacy 동작 유지. 다른 agent
        가 등록한 일정과는 dedup 도 격리.
    """
    sig = _dedup_signature(args.get("when"), args.get("title"))
    target_title_key = _title_key(args.get("title"))
    # Phase 1 — owner_agent_id 추출 (engine 가 server-side 주입; LLM payload 의
    # agent_id 도 같은 슬롯에 들어가지만 engine 이 항상 server 값으로 덮어쓰는
    # 책임을 짐).
    raw_agent_id = args.get("agent_id")
    owner_agent_uuid: UUID | None = None
    if raw_agent_id:
        try:
            owner_agent_uuid = UUID(str(raw_agent_id))
        except (ValueError, TypeError):
            owner_agent_uuid = None

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "success": False,
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        scope_group = args.get("scope_group") or "personal"
        # dedup — 같은 tenant + scope + (옵션) owner_agent 안에서 검사.
        try:
            existing = await agent_document_store.list_items(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                scope_group=scope_group,
                owner_agent_id=owner_agent_uuid,
            )
        except Exception:
            existing = []
        # P11-15 + P11-19n: 진짜 dup (title + when + where + who 모두 동일) 만
        # silent skip. (title, when) 만 같고 where/who 다르면 → update merge 로 진행.
        for it in existing:
            if (
                _dedup_signature(it.get("when"), it.get("title")) == sig
                and (it.get("where") or "") == (args.get("where") or "")
                and (it.get("who") or "") == (args.get("who") or "")
            ):
                return _duplicate_response(
                    str(it.get("id", "")),
                    title=args.get("title"),
                    when=args.get("when"),
                    where=args.get("where"),
                )
        for it in existing:
            if _title_key(it.get("title")) == target_title_key and target_title_key:
                # 같은 제목 다른 시간 — update merge.
                merged_body: dict[str, Any] = {}
                for k in ("when", "who", "where", "recurrence"):
                    if args.get(k) is not None:
                        merged_body[k] = _coerce_scalar(args[k])
                if merged_body:
                    await agent_document_store.update_item(
                        _get_shared_engine(),
                        UUID(str(tenant_id)),
                        _DOCUMENT_TYPE,
                        str(it.get("id")),
                        body_patch=merged_body,
                        owner_agent_id=owner_agent_uuid,
                    )
                return {
                    "id": str(it.get("id")),
                    "success": True,
                    "merged": True,
                    "summary": f"{args.get('title')} 일정 업데이트 — {merged_body.get('when') or '시간 동일'}",
                }

        try:
            doc_id = await agent_document_store.create_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                title=_coerce_scalar(args["title"]),
                body={
                    "when": _coerce_scalar(args.get("when")),
                    "who": _coerce_scalar(args.get("who")),
                    "where": _coerce_scalar(args.get("where")),
                    "recurrence": _coerce_scalar(args.get("recurrence")),
                },
                scope_group=scope_group,
                owner_agent_id=owner_agent_uuid,
            )
        except ValueError as exc:
            # cross-tenant agent_id 차단 (agent_document_store 의 보안 검증).
            return {"success": False, "error": str(exc)}
        return {
            "id": str(doc_id),
            "success": True,
            "scope_group": scope_group,
            "owner_agent_id": str(owner_agent_uuid) if owner_agent_uuid else None,
        }

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy) — phone-scoped dedup + title-merge.
    phone = args["phone"]
    try:
        existing = await rs.list_items(_CATEGORY, phone)
    except Exception:
        existing = []
    for it in existing:
        if (
            _dedup_signature(it.get("when"), it.get("title")) == sig
            and (it.get("where") or "") == (args.get("where") or "")
            and (it.get("who") or "") == (args.get("who") or "")
        ):
            return _duplicate_response(
                str(it.get("id", "")),
                title=args.get("title"),
                when=args.get("when"),
                where=args.get("where"),
            )
    # P11-15: 같은 title 매칭 시 update merge.
    for it in existing:
        if _title_key(it.get("title")) == target_title_key and target_title_key:
            merged = dict(it)
            for k in ("when", "who", "where", "recurrence"):
                if args.get(k) is not None:
                    merged[k] = _coerce_scalar(args[k])
            new_items = [
                merged if (isinstance(x, dict) and x.get("id") == it.get("id")) else x
                for x in existing
            ]
            await rs.replace_items(_CATEGORY, phone, new_items)
            return {
                "id": str(it.get("id")),
                "success": True,
                "merged": True,
                "summary": f"{args.get('title')} 일정 업데이트 — {merged.get('when') or '시간 동일'}",
            }

    item = {
        "id": str(uuid.uuid4()),
        "title": _coerce_scalar(args["title"]),
        "when": _coerce_scalar(args["when"]),
        "who": _coerce_scalar(args.get("who")),
        "where": _coerce_scalar(args.get("where")),
        "recurrence": _coerce_scalar(args.get("recurrence")),
    }
    await rs.rpush_item(_CATEGORY, phone, item)
    return {"id": item["id"], "success": True}


async def update(args: dict[str, Any]) -> dict[str, Any]:
    """일정 수정 — id + 변경 필드. redis/kms 모드 양쪽 지원.

    args: {id, tenant_id?, phone?, agent_id?, title?, when?, who?, where?,
           recurrence?, scope_group?}

    Phase 1 — ``agent_id`` 가 들어오면 *해당 agent 의 row 만* 매칭. 다른 agent
    소유의 일정 id 가 와도 update 는 silently False 반환 (PermissionError 없이
    "찾지 못함" UX 로 처리 — 옛 not-found 와 동일 path).
    """
    item_id = args.get("id")
    if not item_id:
        return {"success": False, "error": "id required"}
    tenant_id = args.get("tenant_id")
    raw_agent_id = args.get("agent_id")
    owner_agent_uuid: UUID | None = None
    if raw_agent_id:
        try:
            owner_agent_uuid = UUID(str(raw_agent_id))
        except (ValueError, TypeError):
            owner_agent_uuid = None
    if _store_mode() != "kms":
        # redis 모드는 list 에서 item 찾아 교체. agent 격리는 redis 경로에서
        # 적용 안 함 (redis = legacy/local, KMS 본격 격리는 KMS 경로).
        phone = args.get("phone")
        if not phone:
            return {"success": False, "error": "phone required (redis mode)"}
        items = await rs.list_items(_CATEGORY, phone)
        new_items = []
        found = False
        for it in items:
            if str(it.get("id")) == str(item_id):
                merged = {**it, **{k: v for k, v in args.items()
                                    if k in ("title","when","who","where","recurrence")
                                    and v is not None}}
                new_items.append(merged)
                found = True
            else:
                new_items.append(it)
        if not found:
            return {"success": False, "error": "not found"}
        await rs.replace_items(_CATEGORY, phone, new_items)
        return {"success": True}

    if not tenant_id:
        return {"success": False, "error": "tenant_id required (kms mode)"}
    body_patch: dict[str, Any] = {}
    for k in ("when", "who", "where", "recurrence"):
        if args.get(k) is not None:
            body_patch[k] = _coerce_scalar(args[k])
    title = _coerce_scalar(args.get("title"))
    ok = await agent_document_store.update_item(
        _get_shared_engine(),
        UUID(str(tenant_id)),
        _DOCUMENT_TYPE,
        str(item_id),
        title=title,
        body_patch=body_patch or None,
        owner_agent_id=owner_agent_uuid,
    )
    if not ok:
        return {"success": False, "error": "not found"}
    return {"success": True}


async def list_all(args: dict[str, Any]) -> dict[str, Any]:
    """일정 목록 조회.

    ``scope_group`` 이 args 에 명시되면 해당 scope 만 반환. None / 미지정이면
    scope 무관 (모든 일정).

    Phase 1 — ``agent_id`` 가 들어오면 *해당 agent 의 일정만* 반환. ``include_null_owner``
    가 True 면 (admin / legacy 회복 경로) NULL owner 도 함께 노출 — default
    False (격리). agent_id 없으면 owner 필터 없이 tenant 전체 — admin / legacy
    호환 경로.
    """
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"items": [], "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        scope_group = args.get("scope_group")
        raw_agent_id = args.get("agent_id")
        owner_agent_uuid: UUID | None = None
        if raw_agent_id:
            try:
                owner_agent_uuid = UUID(str(raw_agent_id))
            except (ValueError, TypeError):
                owner_agent_uuid = None
        # D23 §7 (2026-05-08) — admin 경로 / legacy 회복은 *sentinel only*.
        # args.get("include_null_owner") 의 bool True 는 *직접 storage 로 전달 안 함*.
        # engine 의 _resolve_args_with_defaults 가 admin 검증 후 reserved key
        # ``_admin_null_owner_sentinel`` 에 ADMIN_NULL_OWNER_OK 를 set. 그 외에는
        # 키 부재 = default-deny 격리 (sentinel 부재).
        sentinel = args.get("_admin_null_owner_sentinel")
        include_null_arg: Any
        if sentinel is agent_document_store.ADMIN_NULL_OWNER_OK:
            include_null_arg = agent_document_store.ADMIN_NULL_OWNER_OK
        else:
            include_null_arg = False
        items = await agent_document_store.list_items(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            scope_group=scope_group,
            owner_agent_id=owner_agent_uuid,
            include_null_owner=include_null_arg,
        )
        return {"items": items}

    items = await rs.list_items(_CATEGORY, args["phone"])
    return {"items": items}


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    """일정 삭제 — id / title / when 중 하나로 매칭.

    P11-19z (2026-05-06): id 가 없으면 title (substring 무시 대소문자) +
    optional when prefix (날짜 부분만) 으로 list_all 후 단일 매칭이면 즉시
    삭제. 다중 매칭이면 후보 echo 하면서 disambiguate 요청.
    """
    item_id = args.get("id")
    title_q = (args.get("title") or "").strip().lower()
    when_q = (str(args.get("when") or "")).strip()
    raw_agent_id = args.get("agent_id")
    owner_agent_uuid: UUID | None = None
    if raw_agent_id:
        try:
            owner_agent_uuid = UUID(str(raw_agent_id))
        except (ValueError, TypeError):
            owner_agent_uuid = None

    # ── id 우선 ─────────────────────────────────────
    if item_id:
        if _store_mode() == "kms":
            tenant_id = args.get("tenant_id")
            if not tenant_id:
                return {"success": False, "error": "tenant_id required when AGENT_DATA_STORE=kms"}
            ok = await agent_document_store.delete_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                str(item_id),
                owner_agent_id=owner_agent_uuid,
            )
            return {"success": ok}
        ok = await rs.remove_by_id(_CATEGORY, args.get("phone"), str(item_id))
        return {"success": ok}

    # ── title / when 매칭 fallback ───────────────────
    if not title_q and not when_q:
        return {"success": False, "error": "id 또는 (title / when) 중 하나 이상 필요"}

    listed = await list_all(args)
    items = listed.get("items") or []

    def _match(it: dict[str, Any]) -> bool:
        t = (it.get("title") or "").strip().lower()
        w = str(it.get("when") or "")
        title_ok = bool(title_q) and (title_q in t or t in title_q)
        when_ok = bool(when_q) and (w.startswith(when_q[:10]) or when_q[:10] in w)
        if title_q and when_q:
            return title_ok and when_ok
        return title_ok or when_ok

    candidates = [it for it in items if isinstance(it, dict) and _match(it)]
    if not candidates:
        return {
            "success": False,
            "matched": 0,
            "summary": (
                f"'{args.get('title') or args.get('when')}' 와 일치하는 일정을 찾지 못했습니다."
            ),
        }
    if len(candidates) > 1:
        # disambiguate 후보 echo — 답변 LLM 이 사용자에게 "어떤 거?" 라고 묻게.
        previews = [
            f"- {c.get('title')} · {c.get('when')}" for c in candidates[:5]
        ]
        return {
            "success": False,
            "matched": len(candidates),
            "candidates": candidates[:5],
            "summary": (
                f"매칭되는 일정이 {len(candidates)}건입니다. 어떤 일정을 삭제할까요?\n"
                + "\n".join(previews)
            ),
        }
    target = candidates[0]
    target_id = str(target.get("id") or "")
    if not target_id:
        return {"success": False, "matched": 1, "error": "매칭된 일정에 id 가 없습니다"}
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required (kms mode)"}
        ok = await agent_document_store.delete_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            target_id,
        )
    else:
        ok = await rs.remove_by_id(_CATEGORY, args.get("phone"), target_id)
    return {
        "success": bool(ok),
        "matched": 1,
        "id": target_id,
        "title": target.get("title"),
        "when": target.get("when"),
        "summary": (
            f"일정을 삭제했습니다 — {target.get('title')} · {target.get('when')}"
            if ok
            else "삭제에 실패했습니다."
        ),
    }


# ── Bulk operations (P11-19y — 2026-05-06) ───────────────────────────
# 단건 id 없이 *조건 기반* 일괄 삭제. plan_orchestrator 가 "다 삭제" / "중복 정리"
# 같은 발화를 단일 tool 로 처리하도록 — N 개 step 분해 부담 제거.


def _signature_for_dedup(it: dict[str, Any]) -> tuple:
    """일정 dedup signature — 같은 title/when[:10]/where/who 면 같은 항목.

    title 정규화 (strip+lower) + when 의 날짜 부분만 (시각 차이는 별 의미 없는 경우
    가 많지만 dedup 은 보수적으로 운영). where/who 는 빈 string 통일.
    """
    title = (it.get("title") or "").strip().lower()
    when = (str(it.get("when") or ""))[:10]
    where = (it.get("where") or "").strip()
    who = (it.get("who") or "").strip()
    return (title, when, where, who)


async def delete_duplicates(args: dict[str, Any]) -> dict[str, Any]:
    """동일 (title, 날짜, 장소, 참석자) signature 의 중복 row 들을 정리.

    각 그룹의 *첫 항목* 을 보존하고 나머지를 삭제. 사용자 발화 "중복 일정 정리해줘",
    "겹치는거 다 지워" 류 매핑.
    """
    listed = await list_all(args)
    items: list[dict[str, Any]] = listed.get("items") or []
    seen: dict[tuple, str] = {}
    to_delete: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sig = _signature_for_dedup(it)
        rid = str(it.get("id") or "")
        if not rid:
            continue
        if sig in seen:
            to_delete.append(rid)
        else:
            seen[sig] = rid

    deleted = 0
    failed: list[str] = []
    for rid in to_delete:
        try:
            r = await delete({**args, "id": rid})
            if r.get("success"):
                deleted += 1
            else:
                failed.append(rid)
        except Exception:  # noqa: BLE001
            failed.append(rid)

    return {
        "success": True,
        "scanned": len(items),
        "groups": len(seen),
        "deleted": deleted,
        "failed": len(failed),
        "summary": (
            f"전체 {len(items)}건 중 {deleted}건 중복 삭제, "
            f"{len(seen)}건 보존."
        ),
    }


async def delete_all(args: dict[str, Any]) -> dict[str, Any]:
    """모든 일정 삭제. 사용자 발화 "전부 다 지워줘" / "다 삭제" + scope 가 명시되면
    그 scope 만. 보수적: 결과만 알리고 *되돌릴 수 없음* 안내는 답변 LLM 이.
    """
    listed = await list_all(args)
    items: list[dict[str, Any]] = listed.get("items") or []
    deleted = 0
    failed: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rid = str(it.get("id") or "")
        if not rid:
            continue
        try:
            r = await delete({**args, "id": rid})
            if r.get("success"):
                deleted += 1
            else:
                failed.append(rid)
        except Exception:  # noqa: BLE001
            failed.append(rid)
    return {
        "success": True,
        "scanned": len(items),
        "deleted": deleted,
        "failed": len(failed),
        "summary": f"전체 {len(items)}건 중 {deleted}건 삭제.",
    }

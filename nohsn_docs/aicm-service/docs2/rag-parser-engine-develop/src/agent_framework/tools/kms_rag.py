"""KMS RAG tool — 실제 SearchService 호출 어댑터.

agent_framework 의 tool_calling_loop / 상태머신 엔진이 문서 검색을 할 때
이 tool 을 통해 기존 KMS 의 SearchService 에 쿼리. 결과는 LLM 이 읽기 좋은
형태 (title/content/score) 로 압축.

Chokepoint 2 (2026-05-07) — strict isolation post-filter:
- SearchService 가 어떤 사유로든 (rerank, fallback, cross_tenant, broaden 분기)
  agent.allowed_repo_ids 외 chunk 를 반환하면, 본 layer 에서 *결과 제거 + 위배
  로그 + telemetry counter*. enforce_repo_ids=True (strict) 일 때만 적용.
- 즉 SearchService 는 "최선의 결과 시도", isolation enforcement 의 *최종 라인*
  은 본 tool 어댑터.

v1 제약: tenant 매핑 없음. 모든 agent 호출은 `DEFAULT_TENANT` 로 보냄. 사용자
업로드 문서가 같은 tenant 에 있어야 검색됨. Phase 2 에서 phone→tenant 매핑.

★ 자비스 비전 시나리오 2 (2026-04-28): "작년 STT 발표 자료 어딨지?" 같은
사용자 기존 자료 검색을 위해 시간/타입 필터 args 확장.
- created_after / created_before (ISO str): 시간 범위 — Qdrant payload `created_at`
  range 필터 + 결과 post-filter 로 보강.
- document_type (list[str]): "presentation/manual/memo/research_note/email/report"
  중 하나 이상. Qdrant payload `metadata.document_type` 매칭 + post-filter.
- source_type (list[str]): 파일 포맷 (pdf/docx/pptx 등) 또는 origin 태그.
  post-filter 로 result.metadata.source_format / metadata.source_type 매칭.

원칙: 새 args 모두 optional default None — 기존 호출 회귀 0. SearchService
자체 (BGE-M3 + reranker) 는 변경 X — 사용자 메모리 ★ KMS 검색 API + reranker
적극 활용 (2026-04-26 통찰).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from uuid import UUID

from src.common.feature_flags import FeatureFlag, is_enabled
from src.common.logging import get_logger

log = get_logger(__name__)


def _cross_brand_filter_enabled() -> bool:
    """D85 (2026-05-13) — 사용자 절칙 'KMS + 루카스 분리' 적용. default = false.

    루카스가 KMS retrieval 결과를 *재해석/후가공* 하면 사용자 절칙 위배. backend
    `_execute_pipeline` 가 이미 `repo_ids_filter` 로 검색해서 정상 hit 를 반환
    하는데, post-filter 가 hit 의 `repository_id` 가 비어 있다는 이유로 모두
    drop → false negative (M48 식 cross-brand leak 차단이 의도였으나 backend 가
    이미 보장하면 redundant).

    진짜 KMS 결함 (cross-brand chunk leak / repo_id 누락) 은 *KMS 측에서* fix.
    이전 동작이 필요한 경우 `KMS_CROSS_BRAND_FILTER_ENABLED=true` 로 명시.
    """
    raw = os.getenv("KMS_CROSS_BRAND_FILTER_ENABLED")
    if raw is None:
        raw = os.getenv("KMS_CROSS_BRAND_FILTER", "false")
    return (raw or "").strip().lower() not in ("0", "false", "no", "off")


# v1 단일 테넌트 고정.
DEFAULT_TENANT_UUID = UUID("00000000-0000-0000-0000-000000000000")
DEFAULT_TENANT_SLUG = "default-tenant"


def _parse_iso(value: str | None) -> datetime | None:
    """ISO 8601 문자열 → naive datetime. 실패 시 None.

    "2025-04-01", "2025-04-01T00:00:00", "2025-04-01T00:00:00Z" 모두 허용.
    """
    if not value:
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1]
        return datetime.fromisoformat(cleaned)
    except (TypeError, ValueError):
        return None


def _to_image_serve_url(image_path: str) -> str:
    """raw image_path → fetchable URL (GPT-5 P0-3 fix).

    KMS API 의 ``/api/v1/preview/images/{image_path:path}`` 가 /tmp/aicm_* /
    /data/* 만 화이트리스트 허용. 환경변수 ``KMS_PUBLIC_BASE_URL`` 가 있으면
    절대 URL, 없으면 상대경로 (frontend 동일 origin proxy).
    이미 http(s):// 면 그대로 통과 (외부 URL 호환).
    """
    if not image_path:
        return ""
    p = image_path.strip()
    if p.startswith(("http://", "https://")):
        return p
    # 선행 슬래시 제거 후 path-only encode (FastAPI path param 이 디코드).
    rel = p.lstrip("/")
    import os as _os

    base = _os.environ.get("KMS_PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}/api/v1/preview/images/{rel}"
    return f"/api/v1/preview/images/{rel}"


def _normalize_str_list(value: Any) -> list[str] | None:
    """str | list[str] | None → 정제된 list[str] 또는 None."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return [v.lower()] if v else None
    if isinstance(value, list):
        out = [str(v).strip().lower() for v in value if str(v).strip()]
        return out or None
    return None


def _get_hit_field(hit: object, *keys: str) -> Any:
    """SearchResultItem-like 객체에서 첫 매칭 attribute 반환.

    metadata 딕셔너리 안쪽도 함께 탐색 (e.g. metadata["document_type"]).
    """
    for key in keys:
        if "." in key:
            head, tail = key.split(".", 1)
            container = getattr(hit, head, None)
            if isinstance(container, dict):
                v = container.get(tail)
                if v is not None:
                    return v
        else:
            v = getattr(hit, key, None)
            if v is not None:
                return v
    return None


def _search_hit_to_public_hit_dict(r: object, *, content: str) -> dict[str, Any]:
    """SearchHit-like 객체 → KMSRagTool 응답의 public hit dict 변환.

    GPT-5.5 D85c-잔존 P1 (2026-05-13) — 변환 로직을 ``__call__`` body 에서 분리.
    직접 unit test 가능 + 다른 KMS tool (kms_sop 등) 재사용 여지.

    surface 필드:
    - id / document_id — 기존
    - block_id / repository_id / section_title / page_number / document_title —
      D85c-잔존 신규 (citation full_url + section 표시용)
    - title — 기존 (document_title alias)
    - section — 기존 legacy alias (section_title 와 동일 값)
    - content — 본문 (caller 가 content cap 처리 후 전달)
    - score — float

    KMS+루카스 분리 절칙 정합 — 단순 필드 surface, 재해석 X.
    """
    _src_loc = getattr(r, "source_location", None)
    _repo_id_attr = getattr(r, "repository_id", None)
    _block_id_attr = getattr(r, "block_id", None) or getattr(r, "chunk_id", None)
    _section_title = getattr(r, "section_title", None)
    _doc_title = getattr(r, "document_title", "") or ""
    return {
        "id": str(getattr(r, "chunk_id", "")),
        "document_id": str(getattr(r, "document_id", "")),
        "block_id": str(_block_id_attr) if _block_id_attr else None,
        "repository_id": str(_repo_id_attr) if _repo_id_attr else None,
        "title": _doc_title,
        "document_title": _doc_title,
        "section_title": _section_title or "",
        # legacy alias — 기존 caller 가 "section" 으로 읽는 호환 유지.
        "section": _section_title or "",
        "page_number": (
            getattr(_src_loc, "page_number", None) if _src_loc else None
        ),
        "content": content[:4000],
        "score": float(getattr(r, "score", 0.0) or 0.0),
    }


def _hit_passes_filters(
    hit: object,
    *,
    created_after: datetime | None,
    created_before: datetime | None,
    document_types: list[str] | None,
    source_types: list[str] | None,
) -> bool:
    """하나의 SearchResultItem 이 사후 필터를 통과하는지 검사.

    - 누락 메타는 *통과* 로 간주 (검색 결과 자체 신뢰 + post-filter 가 ranking
      을 무너뜨리지 않도록 conservatism). 사용자가 명시적으로 필터를 걸었을
      때만 *명시 mismatch* 를 차단.
    """
    if created_after or created_before:
        ts_raw = _get_hit_field(hit, "created_at", "metadata.created_at")
        ts = None
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif isinstance(ts_raw, str):
            ts = _parse_iso(ts_raw)
        if ts is not None:
            # naive vs aware 정규화 — naive 로 통일
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if created_after and ts < created_after:
                return False
            if created_before and ts > created_before:
                return False
        # ts 누락 → 통과 (보수적)

    if document_types:
        dt = _get_hit_field(hit, "document_type", "metadata.document_type")
        if isinstance(dt, str) and dt.strip():
            if dt.strip().lower() not in document_types:
                return False
        # 누락 → 통과

    if source_types:
        sf = _get_hit_field(
            hit,
            "source_format",
            "metadata.source_format",
            "metadata.source_type",
        )
        if isinstance(sf, str) and sf.strip():
            if sf.strip().lower() not in source_types:
                return False
        # 누락 → 통과

    return True


class KMSRagTool:
    """Tool registry 에 `kms_rag.search` 로 등록되는 callable.

    인자:
        query: str — 검색 쿼리 (필수)
        top_k: int — 결과 수 (1~10, 기본 3)
        tenant_id: str — 테넌트 ID (옵션, v1 기본 DEFAULT_TENANT)
        created_after: str — ISO 8601 (옵션) — 이 날짜 이후 문서만
        created_before: str — ISO 8601 (옵션) — 이 날짜 이전 문서만
        document_type: str | list[str] — (옵션) "presentation"/"manual"/"memo"/
            "research_note"/"email"/"report"/"other" 중 하나 이상
        source_type: str | list[str] — (옵션) 파일 포맷 또는 origin 태그
        repo_ids: list[UUID|str] — (옵션) 검색 범위 repo 한정. cross-industry
            isolation 용. role agent 의 knowledge_isolation='strict' 시 engine 의
            ``_enrich_plan_tool_args`` 가 agent.primary_repo_ids 를 자동 inject.
            빈 list 가 들어오면 "결과 0건 보장" (sentinel) 으로 동작.
        enforce_repo_ids: bool — (옵션, 기본 False) True 면 SearchService 의
            level-4 fallback 에서도 repo 제한 유지. strict isolation 시 자동 True.

    반환: {hits: [{id, title, content, score}], total: int} 또는 {hits: [], error: str}
    """

    def __init__(self):
        self._svc = None

    async def _get_svc(self):
        """SearchService 지연 초기화."""
        if self._svc is None:
            try:
                from src.search.factory import create_search_service

                self._svc = await create_search_service()
            except Exception as exc:
                log.error("kms_rag_service_init_failed", error=str(exc))
                self._svc = None
        return self._svc

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        from src.search.models import SearchRequest

        query = str(args.get("query") or "").strip()
        if not query:
            return {"hits": [], "error": "empty query"}

        svc = await self._get_svc()
        if svc is None:
            return {"hits": [], "error": "search service unavailable"}

        # 2026-05-08 — assist-stream align (사용자 명시). default 3 → 5 로 변경.
        # multimodal_blocks cap 5 와 정합. caller 가 명시 시 그대로 사용.
        top_k = int(args.get("top_k", 5))

        # 새 args — 모두 optional. None 이면 필터 미적용.
        created_after = _parse_iso(args.get("created_after"))
        created_before = _parse_iso(args.get("created_before"))
        document_types = _normalize_str_list(args.get("document_type"))
        source_types = _normalize_str_list(args.get("source_type"))

        # 사후 필터가 걸리면 SearchService 후보를 더 많이 받아 filter 후
        # top_k 로 잘라야 ranking 손실 최소화.
        has_post_filter = bool(
            created_after or created_before or document_types or source_types
        )
        # 단일 hint 만 SearchRequest 에 넘길 수 있으므로 (Qdrant 쪽 인덱스
        # mismatch 시 0 결과 위험), 안전하게 SearchService 는 top_k 그대로
        # 두되 post-filter 시에는 후보 풀 (~10) 까지 받아 후 자른다.
        effective_top_k = max(1, min(top_k, 10))
        request_top_k = (
            min(10, max(effective_top_k, effective_top_k * 3))
            if has_post_filter
            else effective_top_k
        )

        # cross-industry isolation (KMS-Plus, 2026-05-07) — args 에 repo_ids 가
        # 들어오면 SearchRequest.repository_ids 로 전파. engine 의
        # ``_enrich_plan_tool_args`` 가 agent_context.knowledge_isolation 분기로
        # 자동 주입한다 (strict / priority).
        # 빈 list ("") sentinel — strict + primary_repo_ids 가 비면 "결과 0건"
        # 보장 위해 의도적으로 빈 list 그대로 둔다 (broad 가 아님).
        repo_ids_raw = args.get("repo_ids")
        repo_ids_filter: list[UUID] | None = None
        repo_ids_explicit = "repo_ids" in args  # None vs 미전달 구분
        # D69 (2026-05-12, GPT-5 권고) — list/tuple/set 모두 허용 (외부 caller 의
        # 다양한 입력 타입 견고화). 기존: list 만 허용 → tuple/set 가 들어오면 silent skip 위험.
        if isinstance(repo_ids_raw, (list, tuple, set)):
            parsed_repo: list[UUID] = []
            for rid in repo_ids_raw:
                try:
                    parsed_repo.append(UUID(str(rid)))
                except (ValueError, TypeError):
                    log.debug("kms_rag_invalid_repo_id_skipped", repo_id=str(rid))
            repo_ids_filter = parsed_repo  # 빈 list 도 살림 (sentinel)
        elif repo_ids_raw is None and repo_ids_explicit:
            # 명시적 None — broad 와 동일 처리.
            repo_ids_filter = None

        enforce_repo_ids = bool(args.get("enforce_repo_ids", False))

        # strict isolation sentinel — primary_repo_ids 가 비고 enforce 라면 hard 0건.
        if enforce_repo_ids and isinstance(repo_ids_filter, list) and not repo_ids_filter:
            log.info(
                "kms_rag_strict_isolation_zero_repo",
                reason="agent has no primary_repo_ids and enforce=True",
            )
            return {
                "hits": [],
                "total": 0,
                "success": True,
                "summary": "검색 범위 repo 가 비어 있음 (strict isolation)",
                "evidence_count": 0,
            }

        # P10k (2026-04-29) — caller 가 args 에 tenant_id / tenant_slug 주입했으면
        # 사용. 미주입 시 DEFAULT_TENANT 로 fallback. plan_orchestrator 가 호출 시
        # 반드시 sess.tenant_id / personal_tenant_id 를 inject 해야 정확한 ES/Qdrant
        # 인덱스에 검색.
        from uuid import UUID as _UUID

        caller_tenant_id = args.get("tenant_id")
        caller_tenant_slug = args.get("tenant_slug")
        try:
            effective_tenant_id = (
                _UUID(str(caller_tenant_id))
                if caller_tenant_id
                else DEFAULT_TENANT_UUID
            )
        except (ValueError, TypeError):
            effective_tenant_id = DEFAULT_TENANT_UUID
        # tenant_slug 가 안 들어오면 effective_tenant_id 로 DB 조회.
        effective_tenant_slug = caller_tenant_slug or DEFAULT_TENANT_SLUG
        if not caller_tenant_slug and caller_tenant_id:
            try:
                from sqlalchemy import text as _sql_text
                from src.core.database import async_session_factory

                async with async_session_factory() as _s:
                    row = (
                        await _s.execute(
                            _sql_text("SELECT slug FROM tenants WHERE id = :tid"),
                            {"tid": effective_tenant_id},
                        )
                    ).first()
                    if row and row[0]:
                        effective_tenant_slug = str(row[0])
            except Exception as exc:  # noqa: BLE001
                log.debug("kms_rag_tenant_slug_lookup_failed", error=str(exc))

        try:
            # 2026-05-08 — assist-stream path 와 align (사용자 명시).
            # enable_llm_rewrite=True: 대화 history 활용한 query 재작성.
            # use_hyde=False: rewrite 가 이미 구체화 — 가상답변 중복 회피.
            # conversation_history: args 에서 받아 전달 (multi-turn 대명사 해소).
            _history_arg = args.get("conversation_history")
            if not isinstance(_history_arg, list):
                _history_arg = None
            req_kwargs: dict[str, Any] = dict(
                query=query,
                tenant_id=effective_tenant_id,
                top_k=request_top_k,
                search_mode="hybrid",
                rerank=True,
                include_content=True,
                enable_llm_rewrite=True,
                use_hyde=False,
                conversation_history=_history_arg,
            )
            # cross-industry isolation — repo_ids 가 명시되면 SearchRequest 에 전파.
            # 빈 list 도 그대로 보냄 (Qdrant/ES 가 0 결과로 응답 — 의도된 동작).
            if repo_ids_filter is not None:
                req_kwargs["repository_ids"] = repo_ids_filter
                req_kwargs["enforce_repository_ids"] = enforce_repo_ids
            # SearchRequest 에 단일 document_type_hint 가 있으면 활용 (Qdrant
            # 쪽 1차 필터 — 매칭 안 되면 post-filter 가 받아냄). 다중일 경우
            # post-filter 에 위임.
            if document_types and len(document_types) == 1:
                req_kwargs["document_type_hint"] = document_types[0]
            req = SearchRequest(**req_kwargs)
            resp = await svc.search(request=req, tenant_slug=effective_tenant_slug)
            log.info(
                "kms_rag_search_ok",
                tenant_id=str(effective_tenant_id),
                tenant_slug=effective_tenant_slug,
                result_count=len(getattr(resp, "results", []) or []),
                repo_ids_count=(
                    len(repo_ids_filter) if repo_ids_filter is not None else None
                ),
                enforce_repo_ids=enforce_repo_ids,
            )
        except Exception as exc:
            log.warning(
                "kms_rag_search_failed",
                error=str(exc),
                query=query[:80],
                tenant_id=str(effective_tenant_id),
                tenant_slug=effective_tenant_slug,
            )
            return {"hits": [], "error": str(exc), "success": False}

        raw_results = list(getattr(resp, "results", []) or [])

        # Chokepoint 2 — cross-brand isolation post-filter (D69, 2026-05-12).
        # GPT-5 보강: repo_ids_filter 가 non-empty list 면 *priority 모드 포함* 항상
        # post-filter (벨트+서스펜더). enforce_repo_ids=False (priority) 일 때도
        # SearchService level-4 fallback 이 다른 브랜드 repo chunk 를 받아오면 여기서
        # 제거. M48 사례 (baemin 봇 → 삼척리 VOC 발화 → samchully repo chunk leak)
        # 직접 차단. repository_id 누락 (None / 빈 문자열) 는 enforce 와 무관하게
        # *항상* 드랍 — KMS chunk 는 repo_id 없으면 신뢰 불가.
        # D78 — 분모 metric (post-filter 진입 횟수).
        try:
            from src.common.metrics import inc_guard_input

            inc_guard_input("cross_brand_filter")
        except Exception:  # noqa: BLE001
            pass
        # D78 kill-switch — bypass 시 post-filter 우회 (회귀 0; default=true).
        _cb_enabled = _cross_brand_filter_enabled()
        if (
            _cb_enabled
            and isinstance(repo_ids_filter, list)
            and repo_ids_filter
        ):
            allowed_set: set[str] = {str(r) for r in repo_ids_filter}
            kept: list[object] = []
            leaked: list[str] = []
            for r in raw_results:
                rid = getattr(r, "repository_id", None)
                rid_str = str(rid) if rid is not None else ""
                if rid_str and rid_str in allowed_set:
                    kept.append(r)
                elif rid_str == "":
                    # repository_id 누락 — *항상* 차단 (priority 도 포함).
                    # KMS chunk 신뢰 기준 = repo_id 보유. 누락 시 cross-brand 재유입
                    # 위험. GPT-5 B 권고.
                    leaked.append("(missing-repo-id)")
                else:
                    leaked.append(rid_str)
            if leaked:
                log.warning(
                    "kms_rag_isolation_violation_post_filter",
                    agent_repo_count=len(allowed_set),
                    leaked_repo_count=len(leaked),
                    leaked_sample=leaked[:5],
                    query=query[:80],
                    enforce_repo_ids=enforce_repo_ids,
                )
                # D78 — drop hit counter (retrieval_filter stage).
                try:
                    from src.common.metrics import inc_crosstalk_drop

                    for _ in leaked:
                        inc_crosstalk_drop("retrieval_filter")
                except Exception:  # noqa: BLE001
                    pass
            raw_results = kept

        # 사후 필터 적용 — ranking 순서 보존 (filter only, sort 변경 X).
        filtered: list[object] = []
        if has_post_filter:
            for r in raw_results:
                if _hit_passes_filters(
                    r,
                    created_after=created_after,
                    created_before=created_before,
                    document_types=document_types,
                    source_types=source_types,
                ):
                    filtered.append(r)
        else:
            filtered = raw_results

        # top_k 절단 (사용자 요청 top_k 만큼)
        filtered = filtered[:effective_top_k]

        hits: list[dict] = []
        for r in filtered:
            content = getattr(r, "content", "") or ""
            # D85b (2026-05-13) — 사용자 절칙 'KMS+루카스 분리'. assist-stream 의
            # sources_payload 는 원문 그대로 (h.content or ""). 루카스가 500자 cap
            # 으로 자르면 fact (22% 비용 절감 등) 가 chunk 후반에 있을 때 LLM 에
            # 미전달 → "명시되지 않다" 오답. KMS citations endpoint 의 _CONTENT_LEN
            # (4000) 과 일치시켜 사용자 절칙 정합.
            # D85c-잔존 (2026-05-13) — 사용자 보고 "citation full_url None /
            # title 빈 값" 의 hot path. SearchHit 에 채워진 repository_id /
            # block_id / section_title / page_number 를 hit_dict 가 누락 →
            # engine 의 _h.get("repository_id") = None → full_url 계산 불가.
            # 명시적 surface 로 정정 (KMS layer 내부 — 루카스 재해석 아님).
            # GPT-5.5 D85c-잔존 P1 — 변환 로직을 helper 로 추출, 직접 회귀 테스트 가능.
            hit_dict: dict[str, Any] = _search_hit_to_public_hit_dict(
                r, content=content
            )

            # KMS-Plus 2026-05-07 — multimodal block surface (사용자 절칙).
            # block_type 별로 답변에 첨부 가능한 형태 (markdown_table / image_url /
            # caption / ocr_text) 를 hit 에 포함. response_renderer / engine 의
            # _structured_card emit 가 본 필드를 보고 ImageBlock / TableBlock 빌드.
            block_type = getattr(r, "block_type", None)
            if block_type:
                hit_dict["block_type"] = str(block_type)

            metadata = getattr(r, "metadata", {}) or {}
            if isinstance(metadata, dict):
                # 표 — markdown 우선, headers/rows 보조.
                table_md = metadata.get("table_markdown")
                if isinstance(table_md, str) and table_md.strip():
                    # GPT-5 (2026-05-08) — content cap 500 char 와 정합 위해 cap 축소.
                    # 12000 → 2500 (대략 600 토큰). LLM compose tool_results JSON
                    # dump 시 표 본문이 prompt token 의 70%+ 를 점유하던 결함 fix.
                    # 큰 표는 행 truncate 가 정보 손실 적음 — markdown 자체가 행
                    # 단위로 line break 되므로 순서대로 잘라도 상위 행 보존.
                    hit_dict["markdown_table"] = table_md.strip()[:2500]
                table_headers = metadata.get("table_headers")
                if isinstance(table_headers, list) and table_headers:
                    hit_dict["table_headers"] = table_headers
                # GPT-5 P1-6 — table_rows 도 surface (markdown 없을 때 builder 재구성).
                table_rows = metadata.get("table_rows") or metadata.get("rows")
                if isinstance(table_rows, list) and table_rows:
                    hit_dict["table_rows"] = table_rows
                # 2026-05-08 — table_nl (자연어 표 요약) surface. compose prompt
                # 가 markdown_table 보다 짧은 자연어 요약을 우선 활용 가능.
                table_nl = metadata.get("table_nl")
                if isinstance(table_nl, str) and table_nl.strip():
                    hit_dict["table_nl"] = table_nl.strip()[:1500]

                # 이미지 — image_path → 외부 접근 가능 URL 로 변환 (GPT-5 P0-3).
                # /api/v1/preview/images/<path> endpoint 가 /tmp/aicm_* /data/*
                # 만 허용 (이미 ACL 있음). raw 내부 경로 노출 X.
                image_path = metadata.get("image_path")
                if isinstance(image_path, str) and image_path.strip():
                    hit_dict["image_url"] = _to_image_serve_url(image_path.strip())
                image_desc = metadata.get("image_description")
                if isinstance(image_desc, str) and image_desc.strip():
                    hit_dict["image_caption"] = image_desc.strip()
                ocr_text = metadata.get("ocr_text")
                if isinstance(ocr_text, str) and ocr_text.strip():
                    hit_dict["ocr_text"] = ocr_text.strip()[:500]

            hits.append(hit_dict)
        # P10k+: success 명시 — hits 0개여도 검색은 성공한 것 (no error). plan_step ok=true.
        # plan executor 가 _tout.get("success", True) 평가하므로 hits 빈 list 도 ok.
        # 그리고 grounding 정합 — citations event 도 함께 emit (frontend 가 [N] 인용
        # 마커 + Evidence Panel 동등 표시 가능).
        summary = (
            f"검색 결과 {len(hits)}건"
            + (
                f" · 최상위: {hits[0].get('title') or '(제목 없음)'}"
                if hits
                else ""
            )
        )
        result: dict[str, Any] = {
            "hits": hits,
            "total": len(hits),
            "success": True,
            "summary": summary,
            # plan_step 후 reasoning step 이 hits 의 content 를 evidence 로 사용 가능.
            "evidence_count": len(hits),
        }

        # KMS-Plus 2026-05-07 — multimodal blocks aggregated for response renderer.
        # hit 에 묶여 있는 표/이미지를 *result level* 에서도 한 번에 노출 — engine
        # 의 structured_block emit 가 본 list 를 그대로 SSE 로 흘려 frontend
        # 에 표/이미지 같이 첨부 렌더된다. Telegram 도 동일 list 로 공유.
        # 사용자 절칙 (2026-05-07): "표나 그림 등의 자료를 보여줘야 답변 가능".
        #
        # GPT-5 검증 후 보강:
        # - P0-4 _structured_card 와 multimodal_blocks 중복 emit 차단 — _structured_card 제거.
        #   engine 이 multimodal_blocks list 만 보고 SSE 로 흘림.
        # - P1-4 block 5개 cap (SSE 비대화 / chat freeze 차단).
        # - P1-5 dedup by (kind, source_chunk_id, image_url|markdown hash).
        MAX_MULTIMODAL_BLOCKS = 5
        multimodal_blocks: list[dict[str, Any]] = []
        seen_keys: set[tuple] = set()
        for h in hits:
            if len(multimodal_blocks) >= MAX_MULTIMODAL_BLOCKS:
                break
            md = h.get("markdown_table")
            if md:
                # dedup key — 같은 chunk + 같은 markdown 시그니처.
                key = ("table", h.get("id"), hash(md[:512]))
                if key not in seen_keys:
                    seen_keys.add(key)
                    multimodal_blocks.append({
                        "kind": "table",
                        "title": h.get("title") or "",
                        "markdown": md,
                        "headers": h.get("table_headers") or [],
                        "rows": h.get("table_rows") or [],
                        "source_chunk_id": h.get("id"),
                        "source_doc_id": h.get("document_id"),
                    })
                    if len(multimodal_blocks) >= MAX_MULTIMODAL_BLOCKS:
                        break
            iurl = h.get("image_url")
            if iurl:
                key = ("image", h.get("id"), iurl)
                if key not in seen_keys:
                    seen_keys.add(key)
                    multimodal_blocks.append({
                        "kind": "image",
                        "title": h.get("title") or "",
                        "image_url": iurl,
                        "caption": h.get("image_caption") or h.get("ocr_text") or "",
                        "source_chunk_id": h.get("id"),
                        "source_doc_id": h.get("document_id"),
                    })
        if multimodal_blocks:
            result["multimodal_blocks"] = multimodal_blocks

        # Option β Stage 2 — KMS_FIRST_EARLY_RETURN
        # flag on 시만 sufficiency 키 추가. flag off 면 dict shape 동일 (byte-equal).
        # Threshold heuristic: top_score > 0.7 AND rank_gap > 0.15 (BGE-M3 sigmoid
        # 정규화 가정). 다음 stage 에서 LLM judge 로 교체 가능 — 주석으로 명시.
        if is_enabled(FeatureFlag.KMS_FIRST_EARLY_RETURN):
            from src.agent_framework.runtime.sufficiency.kms_sufficiency import (
                KmsHit,
                extract_kms_features,
                is_sufficient,
            )

            hits_for_features = [
                KmsHit(
                    score=float(h.get("score") or 0),
                    title=str(h.get("title") or ""),
                    snippet=str(h.get("content") or ""),
                    source=str(h.get("kind") or "kms_chunk"),
                )
                for h in hits
            ]
            features = extract_kms_features(hits_for_features)
            result["_kms_features"] = features.to_dict()
            try:
                result["kms_sufficient"] = is_sufficient(features)
            except Exception as e:
                log.warning(f"kms sufficiency evaluation failed: {e!r}")
                result["kms_sufficient"] = False

        return result

"""Grounding orchestrator — engine 의 ``_retrieve_persona_grounding`` 진입점.

흐름:
1. KMS ``SearchService.search()`` 호출 (search_mode=hybrid + rerank=True) — BGE-M3 reranker
   가 의미 기반 ranking. 코드에 token_freq/recency/relation boost 박지 않음 (사용자
   원칙: 모든 판단자 LLM-driven).
2. 결과 SearchHit 들의 block_id 로 ``block_extraction_index`` 조회 →
   miss/low-confidence 면 lazy ``extract.extract_temporal_labels`` (LLM, DB 영속).
3. Top-K block 사이 ``block_relations`` 조회 → missing pair 는 lazy
   ``distill.distill_pair`` (LLM, DB 영속).
4. ``domain_knowledge_summary`` 조회 (없거나 24h+ 경과 시 lazy refresh, LLM, DB 영속).
5. 페르소나 prompt 컨텍스트 build — reranker 결정 ranking 그대로 + freshness 라벨 +
   relations 라벨 + domain_summary inject. 답변 LLM 이 라벨 보고 자율 인용.

``KMS_GROUNDING_DISTILL=0`` 으로 distillation 우회 (V5 회귀 호환).
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog

from src.agent_framework.runtime.grounding import distill as _distill
from src.agent_framework.runtime.grounding import extract as _extract
from src.agent_framework.runtime.grounding import summary as _summary

log = structlog.get_logger(__name__)


async def _kms_search(
    *,
    query: str,
    tenant_id: str,
    tenant_slug: str | None,
    knowledge_scope: list[str] | None,
    top_k: int,
    conversation_history: list[dict] | None = None,
    repository_ids: list[Any] | None = None,
) -> list[Any]:
    """KMS SearchService 1차 retrieval + reranker. 실패 시 빈 리스트.

    PR-B 풍부화: ``enable_llm_rewrite=True`` (오타·대화체 재구성), ``use_hyde=True``
    (hypothetical document expansion), ``conversation_history`` (멀티턴 대명사·생략
    복원) 을 명시 전달. ``/search`` 엔드포인트와 동일한 retrieval 품질 확보.
    """
    try:
        from src.search.factory import create_search_service
        from src.search.models import SearchRequest
    except Exception as e:  # noqa: BLE001
        log.warning("search_import_failed", error=str(e))
        return []
    try:
        svc = await create_search_service()
    except Exception as e:  # noqa: BLE001
        log.warning("search_service_init_failed", error=str(e))
        return []
    if svc is None:
        return []

    try:
        tid = UUID(str(tenant_id)) if tenant_id else None
    except (ValueError, TypeError):
        tid = None
    if tid is None:
        return []

    # PR-F — repository_ids 자동 타겟팅. intent_classifier 가 발화·카탈로그
    # 매칭으로 결정한 repo id 들이 호출자에서 전달됨. None 또는 빈 리스트면
    # 옛 동작 (전체 저장소 교차) 유지.
    _repo_uuids: list[UUID] | None = None
    if repository_ids:
        _converted: list[UUID] = []
        for r in repository_ids:
            try:
                _converted.append(r if isinstance(r, UUID) else UUID(str(r)))
            except (ValueError, TypeError):
                continue
        if _converted:
            _repo_uuids = _converted

    try:
        req = SearchRequest(
            query=query,
            tenant_id=tid,
            top_k=max(1, min(top_k, 8)),
            search_mode="hybrid",
            rerank=True,
            include_content=True,
            # PR-B 풍부화 — /search 엔드포인트와 동등한 retrieval 품질
            enable_llm_rewrite=True,
            use_hyde=True,
            conversation_history=conversation_history,
            # PR-F — 자동 타겟팅된 repo 만 검색 scope 으로.
            repository_ids=_repo_uuids,
            # enable_sufficiency_check 는 cost 영향 큼 → default(False) 유지.
        )
    except Exception as e:  # noqa: BLE001
        log.warning("search_request_build_failed", error=str(e))
        return []

    try:
        resp = await svc.search(request=req, tenant_slug=tenant_slug or "")
    except Exception as e:  # noqa: BLE001
        log.warning("kms_search_failed", error=str(e), query=query[:80])
        return []
    return list(getattr(resp, "results", []) or [])


async def _documents_fallback(
    *,
    query: str,
    tenant_id: str,
    db_url: str,
    top_k: int,
    max_chars_per_block: int,
) -> list[Any]:
    """SearchService 결과가 비었을 때의 fallback — documents.processing_meta.body_text
    의 token-freq + ## block 분할 기반 retrieval (V5 호환).

    ``blocks`` 테이블이 아직 ingest 안 된 tenant 에서도 documents 만으로 grounding
    가능하게 함. 결과는 SearchHit 호환 dict-likes (간단 namespace) 로 반환.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from types import SimpleNamespace
    import uuid as _uuid

    terms = [t for t in query.replace(",", " ").split() if len(t) >= 2]
    if not terms or not tenant_id:
        return []

    eng = create_async_engine(db_url)
    try:
        async with eng.begin() as conn:
            like_clauses = " OR ".join(
                [f"processing_meta->>'body_text' ILIKE :t{i}" for i in range(len(terms))]
            )
            params: dict[str, Any] = {"tid": tenant_id}
            for i, t in enumerate(terms):
                params[f"t{i}"] = f"%{t}%"
            sql = (
                f"SELECT id, title, processing_meta, updated_at "
                f"FROM documents "
                f"WHERE tenant_id = cast(:tid as uuid) AND status='active' "
                f"  AND ({like_clauses}) "
                f"ORDER BY updated_at DESC LIMIT 12"
            )
            rows = (await conn.execute(text(sql), params)).all()
    finally:
        await eng.dispose()

    def _split(body: str) -> list[tuple[str, str]]:
        if not body:
            return []
        lines = body.splitlines()
        blocks: list[tuple[str, list[str]]] = [("(intro)", [])]
        for ln in lines:
            s = ln.strip()
            if s.startswith("##") or s.startswith("###"):
                blocks.append((s.lstrip("#").strip(), []))
            else:
                blocks[-1][1].append(ln)
        out: list[tuple[str, str]] = []
        for h, ls in blocks:
            text_ = "\n".join(ls).strip()
            if text_:
                out.append((h, text_))
        return out

    def _score(block_text: str, terms: list[str]) -> int:
        if not block_text:
            return 0
        body_lc = block_text.lower()
        return sum(body_lc.count(t.lower()) for t in terms)

    scored: list[Any] = []
    for r in rows:
        meta = r.processing_meta or {}
        body = meta.get("body_text") or ""
        if not body:
            continue
        blocks = _split(body)
        for idx, (heading, block_text) in enumerate(blocks):
            sc = _score(block_text, terms)
            if sc == 0:
                continue
            synth_id = _uuid.uuid5(
                _uuid.UUID("00000000-0000-0000-0000-000000000000"),
                f"{r.id}#{idx}",
            )
            hit = SimpleNamespace(
                block_id=synth_id,
                chunk_id=synth_id,
                document_id=r.id,
                document_title=r.title,
                section_title=heading,
                content=block_text[:max_chars_per_block],
                document_type=meta.get("doctype", ""),
                metadata={"product_name": meta.get("product_name", "")},
                score=float(sc),
                rerank_score=None,
            )
            scored.append((sc, hit))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:top_k]]


async def _lazy_extract_for_hits(
    *,
    conn: Any,
    hits: list[Any],
    tenant_id: str,
    llm_client: Any,
    extractor_model: str,
) -> dict[str, dict[str, Any]]:
    """block_extraction_index hit 의 캐시 + 누락분 LLM extract → upsert.

    반환: ``{block_id: {effective_date, version_label, topic_keywords, confidence}}``.
    """
    from sqlalchemy import text

    block_ids: list[str] = []
    bid_to_hit: dict[str, Any] = {}
    for h in hits:
        bid = getattr(h, "block_id", None) or getattr(h, "chunk_id", None)
        if not bid:
            continue
        sid = str(bid)
        block_ids.append(sid)
        bid_to_hit[sid] = h

    cached: dict[str, dict[str, Any]] = {}
    if not block_ids:
        return cached
    try:
        rows = (await conn.execute(
            text("""
                SELECT block_id::text AS block_id, effective_date,
                       version_label, topic_keywords, confidence
                FROM block_extraction_index
                WHERE block_id = ANY(cast(:ids as uuid[]))
            """),
            {"ids": block_ids},
        )).all()
        for r in rows:
            cached[r.block_id] = dict(r._mapping)
    except Exception as e:  # noqa: BLE001
        log.debug("extraction_index_query_failed", error=str(e))

    if llm_client is None:
        return cached

    # missing 또는 confidence < 0.5 인 block 을 병렬 LLM 호출
    targets: list[tuple[str, str]] = []
    for sid in block_ids:
        cur = cached.get(sid)
        if cur and (cur.get("confidence") or 0) >= 0.5:
            continue
        h = bid_to_hit[sid]
        text_body = getattr(h, "content", "") or ""
        if not text_body:
            continue
        targets.append((sid, text_body))

    if not targets:
        return cached

    tasks = [
        _extract.extract_temporal_labels(
            block_id=bid,
            tenant_id=tenant_id,
            block_text=body,
            llm_client=llm_client,
            extractor_model=extractor_model,
        )
        for bid, body in targets
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (bid, _body), res in zip(targets, results):
        if isinstance(res, Exception):
            continue
        cached[bid] = {
            "effective_date": res.effective_date,
            "version_label": res.version_label,
            "topic_keywords": res.topic_keywords,
            "confidence": res.confidence,
        }
        try:
            await _extract.upsert_extraction(conn, res)
        except Exception as e:  # noqa: BLE001
            log.debug("extract_upsert_skipped", error=str(e), block_id=bid)
    return cached


async def _lazy_distill_relations(
    *,
    conn: Any,
    hits: list[Any],
    extractions: dict[str, dict[str, Any]],
    llm_client: Any,
    max_pairs: int = 6,
) -> list[dict[str, Any]]:
    """Top-K hit 들의 페어 관계 lazy distill. confidence ≥ 0.85 만 active 로 반환."""
    from itertools import combinations
    block_ids = []
    bid_meta: dict[str, dict[str, Any]] = {}
    for h in hits:
        bid = getattr(h, "block_id", None) or getattr(h, "chunk_id", None)
        if not bid:
            continue
        sid = str(bid)
        block_ids.append(sid)
        meta = extractions.get(sid) or {}
        bid_meta[sid] = {
            "block_id": sid,
            "text": (getattr(h, "content", "") or "")[:1500],
            "effective_date": meta.get("effective_date"),
            "topic_keywords": meta.get("topic_keywords") or [],
        }

    if len(block_ids) < 2:
        return []

    # 기존 relations 조회
    relations: list[dict[str, Any]] = []
    try:
        relations = await _distill.fetch_relations_for_blocks(conn, block_ids)
    except Exception as e:  # noqa: BLE001
        log.debug("fetch_relations_failed", error=str(e))

    if llm_client is None:
        return relations

    seen = {(r["from_block_id"], r["to_block_id"], r["relation"]) for r in relations} | \
           {(r["to_block_id"], r["from_block_id"], r["relation"]) for r in relations}

    pairs = list(combinations(block_ids, 2))[:max_pairs]
    new_pair_tasks = []
    new_pair_keys = []
    for a, b in pairs:
        # 이미 어떤 relation 이라도 있으면 건너뜀 (LLM 비용 절감)
        if any(((a, b, rel) in seen or (b, a, rel) in seen)
               for rel in ("supersedes", "conflicts", "duplicate", "complementary")):
            continue
        new_pair_keys.append((a, b))
        new_pair_tasks.append(_distill.distill_pair(
            block_a=bid_meta[a],
            block_b=bid_meta[b],
            llm_client=llm_client,
        ))

    if not new_pair_tasks:
        return relations

    results = await asyncio.gather(*new_pair_tasks, return_exceptions=True)
    for (a, b), res in zip(new_pair_keys, results):
        if isinstance(res, Exception) or res is None:
            continue
        try:
            await _distill.upsert_relation(conn, res)
        except Exception as e:  # noqa: BLE001
            log.debug("relation_upsert_skipped", error=str(e))
        if res.confidence >= 0.85:
            relations.append({
                "from_block_id": res.from_block_id,
                "to_block_id": res.to_block_id,
                "relation": res.relation,
                "confidence": res.confidence,
                "reasoning": res.reasoning,
            })
    return relations


async def _lazy_domain_summary(
    *,
    conn: Any,
    tenant_id: str,
    tenant_kind: str | None,
    hits_with_meta: list[dict[str, Any]],
    llm_client: Any,
    generator_model: str,
) -> str | None:
    """domain_knowledge_summary lazy refresh. cache hit 면 그대로, miss/stale 이면 LLM."""
    if llm_client is None or not hits_with_meta:
        return None
    try:
        cached = await _summary.fetch_summary(conn, tenant_id, repository_id=None)
    except Exception as e:  # noqa: BLE001
        log.debug("summary_fetch_failed", error=str(e))
        cached = None
    if cached and cached.get("summary_text"):
        return cached["summary_text"]
    try:
        sres = await _summary.refresh_domain_summary(
            tenant_id=tenant_id,
            repository_id=None,
            tenant_kind=tenant_kind,
            blocks=hits_with_meta,
            llm_client=llm_client,
            generator_model=generator_model,
        )
        if sres:
            try:
                await _summary.upsert_summary(conn, sres)
            except Exception as e:  # noqa: BLE001
                log.debug("summary_upsert_skipped", error=str(e))
            return sres.summary_text
    except Exception as e:  # noqa: BLE001
        log.warning("summary_refresh_failed", error=str(e))
    return None


async def _web_search_for_grounding(
    *,
    query: str,
    top_k: int,
    max_chars: int = 900,
) -> list[dict[str, Any]]:
    """069 (Plan A v3) — web.search 결과를 grounding_doc 형태로 변환.

    citation 정책 일치: ``source='stub'`` 결과는 *제외* (외부 검색 미설정 시).
    top_k 까지 잘라 반환. 실패 시 빈 리스트 (caller 가 회복).
    """
    if not query.strip() or top_k <= 0:
        return []
    try:
        from src.agent_framework.tools.web_search import search as _web_search
    except Exception as e:  # noqa: BLE001
        log.warning("web_search_import_failed", error=str(e))
        return []
    try:
        resp = await _web_search({"query": query, "count": max(top_k, 3)})
    except Exception as e:  # noqa: BLE001
        log.warning("web_search_call_failed", error=str(e))
        return []
    if not isinstance(resp, dict):
        return []
    if not resp.get("success"):
        return []
    backend = str(resp.get("source") or "")
    if backend == "stub":
        # citation_guard 와 일치 — stub 결과는 grounding 에 포함 안 함.
        return []
    items = resp.get("items") or []
    out: list[dict[str, Any]] = []
    for i, it in enumerate(items[:top_k]):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        snippet = str(it.get("snippet") or "").strip()
        url = str(it.get("link") or "").strip()
        if not (title or snippet):
            continue
        out.append({
            "block_id": f"web::{i}",
            "doc_id": "",
            "repo_id": "",
            "title": title or url,
            "heading": "",
            "snippet": snippet[:max_chars],
            # web score scale 알 수 없음 — 0.5 (중립값) 부여. blended 정렬 시
            # KMS 와 비교 가능. separate 는 정렬 영향 X (분리 prompt 표시).
            "score": 0.5,
            "doctype": "web",
            "product_name": "",
            "effective_date": None,
            "version_label": None,
            "relations": [],
            "source": title or url,
            "source_kind": "web",
            "url": url,
            "backend": backend,
        })
    return out


async def build_grounding_context(
    *,
    tenant_id: str | None,
    tenant_kind: str | None,
    tenant_slug: str | None = None,
    query: str,
    knowledge_scope: list[str] | None,
    llm_client: Any,
    db_url: str,
    top_k: int = 4,
    max_chars_per_block: int = 900,
    enable_distillation: bool = True,
    extractor_model: str = "gpt-5.5",
    conversation_history: list[dict] | None = None,
    repository_ids: list[Any] | None = None,
    prior_cited_doc_ids: list[str] | None = None,
    web_search_mode: str = "off",
) -> dict[str, Any]:
    """L1+L2+L3 통합 grounding 컨텍스트 build.

    069 (Plan A v3, 2026-05-07) — ``web_search_mode`` 4-mode:
    - ``off``      : KMS only (현재 동작 그대로).
    - ``separate`` : KMS + web 병렬 → ``grounding_docs`` 안 *분리 라벨*
                     (`source_kind`: ``kms`` / ``web``). LLM prompt 가 두 섹션
                     으로 가시화돼 답변에 출처 구분.
    - ``blended``  : KMS + web 결과 합쳐 score 기준 단일 list. 출처 라벨은
                     붙되 ranking 통합.
    - ``web_only`` : KMS skip, web 만.

    반환:
    ```
    {
      "grounding_docs": [{block_id, doc_id, title, heading, snippet, score,
                          effective_date, version_label, relations, source,
                          source_kind, url?}],
      "domain_summary": str | None,
    }
    ```
    """
    if not tenant_id or not query.strip():
        return {"grounding_docs": [], "domain_summary": None}

    # mode 정규화 — 잘못된 값은 'off' 로 폴백 (회귀 안전망).
    mode = (web_search_mode or "off").lower()
    if mode not in ("off", "separate", "blended", "web_only"):
        mode = "off"

    # 1) KMS SearchService → reranker 까지 거친 hits
    #    Wave 6 default: SearchService 우회 + documents fallback (blocks 미ingest tenant 회귀 안전).
    #    KMS_GROUNDING_USE_SEARCH=1 명시 시 SearchService 활성. 자료 ingest 일관성 검증 후 활성화.
    # 069 — web_only 모드는 KMS 자체 skip.
    import os as _os
    _use_search = _os.environ.get("KMS_GROUNDING_USE_SEARCH", "0") in ("1", "true", "True")
    if mode == "web_only":
        hits = []
    elif _use_search:
        hits = await _kms_search(
            query=query,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            knowledge_scope=knowledge_scope,
            top_k=max(top_k * 2, 6),
            conversation_history=conversation_history,
            repository_ids=repository_ids,
        )
    else:
        hits = []
    if not hits and mode != "web_only":
        # SearchService 빈 결과 — documents.body_text fallback (blocks 미ingest tenant 호환)
        try:
            hits = await _documents_fallback(
                query=query,
                tenant_id=tenant_id,
                db_url=db_url,
                top_k=max(top_k * 2, 6),
                max_chars_per_block=max_chars_per_block,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("documents_fallback_failed", error=str(e))
            hits = []
    # 069 — off 모드 + KMS 0건 = 옛 동작 그대로 빈 context. 단, web 활성 모드면
    # KMS 0건이어도 web 만으로 진행.
    if not hits and mode == "off":
        return {"grounding_docs": [], "domain_summary": None}

    # 2) distillation lazy (L1 + L2 + L3) — DB 영속
    extractions: dict[str, dict[str, Any]] = {}
    relations: list[dict[str, Any]] = []
    domain_summary: str | None = None

    if enable_distillation and llm_client is not None:
        try:
            from sqlalchemy.ext.asyncio import create_async_engine
            eng = create_async_engine(db_url)
            try:
                async with eng.begin() as conn:
                    extractions = await _lazy_extract_for_hits(
                        conn=conn,
                        hits=hits,
                        tenant_id=tenant_id,
                        llm_client=llm_client,
                        extractor_model=extractor_model,
                    )
                    relations = await _lazy_distill_relations(
                        conn=conn,
                        hits=hits[:top_k],  # top-K 페어만 distill
                        extractions=extractions,
                        llm_client=llm_client,
                    )
                    # domain summary 입력은 top-K hit + freshness 메타
                    summary_input = []
                    for h in hits[:top_k]:
                        bid = getattr(h, "block_id", None) or getattr(h, "chunk_id", None)
                        if not bid:
                            continue
                        sid = str(bid)
                        meta = extractions.get(sid) or {}
                        summary_input.append({
                            "block_id": sid,
                            "title": getattr(h, "document_title", ""),
                            "heading": getattr(h, "section_title", "") or "",
                            "snippet": (getattr(h, "content", "") or "")[:max_chars_per_block],
                            "effective_date": meta.get("effective_date"),
                            "version_label": meta.get("version_label"),
                            "relations": [
                                {"to": r["to_block_id"] if r["from_block_id"] == sid
                                                       else r["from_block_id"],
                                 "relation": r["relation"]}
                                for r in relations
                                if sid in (r["from_block_id"], r["to_block_id"])
                            ],
                        })
                    domain_summary = await _lazy_domain_summary(
                        conn=conn,
                        tenant_id=tenant_id,
                        tenant_kind=tenant_kind,
                        hits_with_meta=summary_input,
                        llm_client=llm_client,
                        generator_model=extractor_model,
                    )
            finally:
                await eng.dispose()
        except Exception as e:  # noqa: BLE001
            log.warning("distillation_db_error", error=str(e))

    # P11-19v (2026-05-06) — 직전 턴 cited doc id boost.
    # 같은 세션 multi-turn 에서 사용자가 같은 자료에 대해 follow-up 하는 경우,
    # 그 자료가 후순위로 밀려 prompt 에 안 들어가는 현상을 방지. 매칭 hits 를
    # 안정 정렬로 앞으로 끌어올린 뒤 top_k slice. matching=0, non=1 이 sort key.
    if prior_cited_doc_ids:
        _cited_set = {str(d) for d in prior_cited_doc_ids if d}
        if _cited_set:
            hits = sorted(
                hits,
                key=lambda _h: (
                    0 if str(getattr(_h, "document_id", "") or "") in _cited_set else 1,
                ),
            )

    # 3) grounding_docs build — reranker ranking 그대로 (코드 boost X)
    # 069 — KMS hits 는 source_kind='kms'. 069 web 모드는 후속 단계에서 추가.
    grounding_docs: list[dict[str, Any]] = []
    # 069 — top_k 분배: separate / blended 일 때 KMS 와 web 양쪽이 prompt 에 들어가
    # 도록 KMS 는 top_k 의 절반 이상 확보 (3:1 비율). web_only 는 0.
    if mode == "off":
        kms_quota = top_k
    elif mode == "web_only":
        kms_quota = 0
    else:  # separate / blended
        kms_quota = max(top_k - 1, 1)  # web 1 개 자리 확보, 최소 1.

    for h in hits[:kms_quota]:
        bid_obj = getattr(h, "block_id", None) or getattr(h, "chunk_id", None)
        sid = str(bid_obj) if bid_obj else ""
        meta = extractions.get(sid) or {}
        eff_date = meta.get("effective_date")
        if eff_date is not None:
            eff_date = str(eff_date)
        rels_for_block = []
        for r in relations:
            if sid in (r.get("from_block_id"), r.get("to_block_id")):
                target = (r["to_block_id"] if r["from_block_id"] == sid
                          else r["from_block_id"])
                rels_for_block.append({
                    "to": target,
                    "from": sid if r["from_block_id"] == sid else target,
                    "relation": r["relation"],
                    "confidence": float(r.get("confidence") or 0.0),
                })
        # PR-G — repo_id 노출. CitationModal 의 "전체 문서 보기" 링크가 (repo_id,
        # doc_id) 쌍을 요구하는데 옛 grounding_doc dict 에 repo_id 가 빠져 링크가
        # 안 그려졌다. SearchHit.repository_id 가 이미 있으므로 그대로 노출.
        _repo_id = getattr(h, "repository_id", None)
        grounding_docs.append({
            "block_id": sid,
            "doc_id": str(getattr(h, "document_id", "") or ""),
            "repo_id": str(_repo_id) if _repo_id else "",
            "title": getattr(h, "document_title", "") or "",
            "heading": getattr(h, "section_title", "") or "",
            "snippet": (getattr(h, "content", "") or "")[:max_chars_per_block],
            "score": float(getattr(h, "score", 0.0) or 0.0),
            "doctype": getattr(h, "document_type", "") or "",
            "product_name": (getattr(h, "metadata", {}) or {}).get("product_name", ""),
            "effective_date": eff_date,
            "version_label": meta.get("version_label"),
            "relations": rels_for_block,
            "source": getattr(h, "document_title", "") or "",
            "source_kind": "kms",
        })

    # 069 — web search 추가 (separate / blended / web_only 일 때만).
    if mode in ("separate", "blended", "web_only"):
        web_quota = top_k if mode == "web_only" else max(top_k - len(grounding_docs), 1)
        try:
            web_docs = await _web_search_for_grounding(
                query=query,
                top_k=max(web_quota, 1),
                max_chars=max_chars_per_block,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("web_search_grounding_failed", error=str(e), mode=mode)
            web_docs = []
        if web_docs:
            grounding_docs.extend(web_docs[:web_quota])

    # 069 — blended 면 score 통합 정렬. KMS 와 web score scale 이 다르므로,
    # web score 는 0.5 (중립값) 로 강제 부여 해 KMS 와 비교 가능. blended 는
    # 단순 score desc + block_id tie-break (정렬 안정성).
    if mode == "blended":
        grounding_docs = sorted(
            grounding_docs,
            key=lambda d: (
                -float(d.get("score") or 0.0),
                str(d.get("block_id") or ""),
            ),
        )[:top_k]
    # 069 fix (gpt-5 review) — separate / web_only 도 총량 top_k 컷 (KMS+web
    # 합 이 top_k 초과하지 않게). 위 quota 계산이 +1 자리 확보를 위해 약간 over
    # 할 수 있어 prompt 토큰 폭증 방지.
    elif mode in ("separate", "web_only"):
        grounding_docs = grounding_docs[:top_k]

    log.info(
        "grounding_built",
        tenant_id=tenant_id,
        docs=len(grounding_docs),
        summary=bool(domain_summary),
        distillation=enable_distillation,
        relations=len(relations),
    )
    return {
        "grounding_docs": grounding_docs,
        "domain_summary": domain_summary,
    }

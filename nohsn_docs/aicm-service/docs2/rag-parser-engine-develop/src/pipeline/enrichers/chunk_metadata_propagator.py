"""Chunk metadata propagator — block 단위 의미 메타를 chunk 단위로 전파.

D17 (2026-05-08) 신규 — P1 step 5. GPT-5 G3 (KMS 풀옵션 default true) 반영.

block 의 search_summary / topic_tags / query_keywords / synonyms / image_caption /
table_nl 같은 메타가 chunks 테이블에는 *전파되지 않음* (audit Phase 0.7) — chunk
metadata 에 source_block_ids 만 있고 의미 메타 0%. 본 헬퍼는 chunk 생성 직후
seed/reseed 또는 embed_worker 가 source block 들의 metadata 를 집계해서 chunk
metadata 에 inject 한다.

**Qdrant payload cap 보호** (GPT-5 G3 가 우려한 65KB 초과):
- topic_tags ≤ 10, 항목당 ≤ 80자
- search_summaries ≤ 5, 항목당 ≤ 256자
- query_keywords ≤ 10, 항목당 ≤ 80자
- synonyms ≤ 10, 항목당 ≤ 80자
- image_captions ≤ 5, 항목당 ≤ 120자
- table_nls ≤ 3, 항목당 ≤ 512자
- 총 합 ≤ 8KB (안전 margin 8x).

**KMS 풀옵션 절칙**: feature flag default = true. env override 가능
(`PROPAGATE_BLOCK_META_TO_CHUNK=0` 으로만 비활성화).
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from src.common.logging import get_logger

log = get_logger(__name__)


# 항목당 길이 cap (Qdrant payload 안전)
_CAP_TOPIC_TAG = 80
_CAP_SUMMARY = 256
_CAP_QUERY_KEYWORD = 80
_CAP_SYNONYM = 80
_CAP_IMAGE_CAPTION = 120
_CAP_TABLE_NL = 512

# 항목 수 cap
_TOP_K_TOPIC_TAGS = 10
_TOP_K_SUMMARIES = 5
_TOP_K_QUERY_KEYWORDS = 10
_TOP_K_SYNONYMS = 10
_TOP_K_IMAGE_CAPTIONS = 5
_TOP_K_TABLE_NLS = 3

# 총합 cap (bytes — Qdrant payload 안전 margin)
_TOTAL_PAYLOAD_CAP_BYTES = 8192


def is_enabled() -> bool:
    """env PROPAGATE_BLOCK_META_TO_CHUNK — KMS 풀옵션 절칙으로 default true.

    `0` / `false` / `no` 명시 시만 비활성화. 그 외 (env 미설정 포함) 활성.
    """
    raw = os.environ.get("PROPAGATE_BLOCK_META_TO_CHUNK", "true").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def _cap_str(s: object, max_len: int) -> str:
    """문자열 cap. None/non-str 안전."""
    if s is None:
        return ""
    text = str(s).strip()
    return text[:max_len]


def _dedup_top_k(items: list[str], top_k: int) -> list[str]:
    """순서 보존 dedup + top-k cap."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= top_k:
            break
    return out


# ── D31a (#206 v5) — KC marker / extracted_metadata aggregation ────────────────

# v5 fix 3 — KC owned contextual_prefix allowlist
# D38 v3 — full_pipeline KC hook 가 주입한 marker (kc_hook_applied/version/at) 추가.
# block-level marker 가 chunk/Qdrant/ES payload 까지 전파됨.
# 주의: marker 는 *관측/디버그* 용도 — ranking feature 로 사용 X.
_KC_MARKER_KEYS = (
    "source",                       # llm_summary / stats_summary / entity_page
    "generated",                    # bool — KC 가 만든 block 표시
    "crosslinks",                   # list — block_id 참조
    "kc_owned",                     # bool — D17-v5 §1 cleanup→regen 마커
    "kc_compiled_at",               # ISO timestamp
    "_kc_owned_contextual_prefix",  # KC 가 만든 prefix (original 와 분리)
    "_kc_owned_extracted_metadata", # KC 가 만든 extracted (original 과 분리)
    "is_decorative",                # 노이즈 추적
    "noise_reason",                 # 노이즈 사유
    # ── D38 v3 — full_pipeline KC hook marker (block-level) ──────────
    "kc_hook_applied",              # bool — D38 KC hook 적용 표시
    "kc_hook_version",              # int — KC_VERSION (idempotency)
    "kc_hook_at",                   # ISO timestamp
)

# D31b (#208 v3 fix A) — public alias for full_pipeline._to_input_block kc_markers promotion.
# `_KC_MARKER_KEYS` 와 동일 source of truth (tuple immutable). full_pipeline 의 `_to_input_block`
# 이 import 해서 allowlist promotion 정책 적용.
KC_MARKER_KEYS = _KC_MARKER_KEYS

# v5 fix 4 — extracted_metadata aggregate cap
_TOP_K_EXT_KEYWORDS = 20
_TOP_K_EXT_ENTITIES = 20
_TOP_K_EXT_TOPICS = 5
_CAP_EXT_KEYWORD = 80
_CAP_EXT_ENTITY = 80
_CAP_EXT_TOPIC = 80


def aggregate_provenance(
    source_blocks_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    """KC marker + provenance 전파 — original metadata 보호.

    D31a (#206 v5 §2.3) — KC owned contextual_prefix / generated / crosslinks 등
    KC marker 만 chunk-level 에 합산. original block metadata 는 보호.

    화이트리스트 키 (`_KC_MARKER_KEYS`):
    - source: 첫 non-empty 값 (block 단위 'llm_summary' / 'stats_summary' 등)
    - generated: any(True) — KC 가 만든 SUMMARY/ENTITY 표시
    - crosslinks: list 합산 (dedup top-k)
    - is_decorative: any(True) — 노이즈 처리 추적
    - noise_reason: 첫 non-empty 값
    - _kc_owned_contextual_prefix / _kc_owned_extracted_metadata: 첫 non-empty
    """
    if not source_blocks_meta:
        return {}

    out: dict[str, Any] = {}
    for key in _KC_MARKER_KEYS:
        values = [m.get(key) for m in source_blocks_meta if isinstance(m, dict)]
        if key in ("generated", "kc_owned", "is_decorative", "kc_hook_applied"):
            # any(True) — D38 v3: kc_hook_applied 도 동일 집계 (관측용)
            if any(bool(v) for v in values):
                out[key] = True
        elif key == "crosslinks":
            # list 합산 dedup
            merged: list[Any] = []
            seen: set[str] = set()
            for v in values:
                if isinstance(v, list):
                    for item in v:
                        key_str = str(item)
                        if key_str not in seen:
                            seen.add(key_str)
                            merged.append(item)
                if len(merged) >= 20:
                    break
            if merged:
                out[key] = merged[:20]
        else:
            # 첫 non-empty
            for v in values:
                if v:
                    out[key] = v
                    break
    return out


def _flatten_entities(raw: object, cap: int = 80) -> list[str]:
    """entities 를 list[str] 로 정규화. dict / list / nested str / nested dict 모두 안전.

    D31a 사후 패치 (#206 v5 fix 1) — _es_normalize_entities 와 공유 helper.
    """
    out: list[str] = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and x:
                out.append(x[:cap])
            elif isinstance(x, dict):
                out.extend(_flatten_entities(x, cap))
    elif isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list):
                out.extend(_flatten_entities(v, cap))
            elif isinstance(v, str) and v:
                out.append(v[:cap])
            elif isinstance(v, dict):
                out.extend(_flatten_entities(v, cap))
    elif isinstance(raw, str) and raw:
        out.append(raw[:cap])
    return out


def es_normalize_keywords(meta: dict[str, Any]) -> list[str]:
    """meta 의 query_keywords + topic_tags + keywords 를 dedup 해서 ES keywords 로 통합.

    D31a 사후 패치 (#206 v5 fix 1) — D31c reseed_v4 에서 import. cap 20.
    """
    out: list[str] = []
    for src_key in ("query_keywords", "topic_tags", "keywords"):
        for k in meta.get(src_key) or []:
            if isinstance(k, str) and k:
                out.append(k[:80])
    # extracted_metadata 보강
    extracted = meta.get("extracted_metadata") or {}
    if isinstance(extracted, dict):
        for src_key in ("query_keywords", "keywords"):
            for k in extracted.get(src_key) or []:
                if isinstance(k, str) and k:
                    out.append(k[:80])
    seen: set[str] = set()
    deduped: list[str] = []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            deduped.append(k)
    return deduped[:20]


def es_normalize_entities(meta: dict[str, Any]) -> list[str]:
    """entities 를 ES keyword[] 로 정규화 — meta + extracted_metadata 모두 flatten.

    D31a 사후 패치 (#206 v5 fix 1) — D31c reseed_v4 의 es_index 에서 import. cap 20.

    예시:
    - meta.entities = ["홍길동", "강남구청"]                  → ["홍길동", "강남구청"]
    - meta.entities = {"people": [...], "orgs": [...]}      → flatten
    - meta.extracted_metadata.entities = list / dict        → 보강
    - nested str (dict[str, str]) 도 안전
    """
    out: list[str] = []
    out.extend(_flatten_entities(meta.get("entities")))
    extracted = meta.get("extracted_metadata") or {}
    if isinstance(extracted, dict):
        out.extend(_flatten_entities(extracted.get("entities")))
    seen: set[str] = set()
    deduped: list[str] = []
    for e in out:
        if e and e not in seen:
            seen.add(e)
            deduped.append(e)
    return deduped[:20]


# ── underscore alias (사후 패치 — D31a v5 spec 명칭 정합) ──────────────────────


def _es_normalize_entities(meta: dict[str, Any]) -> list[str]:
    """spec v5 §4.4 의 명칭 그대로 — es_normalize_entities 의 alias.

    D31c reseed_v4 의 es_index 가 import 시 두 명칭 모두 수용 가능.
    """
    return es_normalize_entities(meta)


def _es_normalize_keywords(meta: dict[str, Any]) -> list[str]:
    """spec v5 §4.4 의 명칭 그대로 — es_normalize_keywords 의 alias."""
    return es_normalize_keywords(meta)


def aggregate_extracted_metadata(
    source_extracted_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    """InputBlock.extracted_metadata dict 목록을 chunk-level 에 합산.

    D31a (#206 v5 fix 2) — 입력 타입 list[dict] 통일 (helper caller 와 정합).
    caller: ``[b.extracted_metadata for b in source_blocks if b.extracted_metadata]``

    D31a 사후 패치 — query_keywords / synonyms 추가.

    합산 keys:
    - keywords (list[str]) — dedup + cap 20
    - entities — _flatten_entities 사용 (list[str]/dict/nested 안전)
    - topic / topics — list[str] dedup + cap 5
    - query_keywords — extracted_metadata 의 query_keywords 보강 (cap 20)
    - synonyms — extracted_metadata 의 synonyms 보강 (cap 20)
    """
    if not source_extracted_meta:
        return {}

    keywords: list[str] = []
    entities: list[str] = []
    topics: list[str] = []
    query_keywords: list[str] = []
    synonyms: list[str] = []
    out: dict[str, Any] = {}

    for em in source_extracted_meta:
        if not isinstance(em, dict):
            continue
        for kw in em.get("keywords") or []:
            capped = _cap_str(kw, _CAP_EXT_KEYWORD)
            if capped:
                keywords.append(capped)
        # entities — flatten helper 재사용
        entities.extend(_flatten_entities(em.get("entities"), _CAP_EXT_ENTITY))
        # topic / topics
        raw_topic = em.get("topic")
        if isinstance(raw_topic, str) and raw_topic:
            topics.append(_cap_str(raw_topic, _CAP_EXT_TOPIC))
        for t in em.get("topics") or []:
            capped = _cap_str(t, _CAP_EXT_TOPIC)
            if capped:
                topics.append(capped)
        # query_keywords / synonyms (extracted_metadata 보강)
        for q in em.get("query_keywords") or []:
            capped = _cap_str(q, _CAP_QUERY_KEYWORD)
            if capped:
                query_keywords.append(capped)
        # synonyms — list / dict 둘 다 안전 (사후 패치 D31a)
        raw_syn = em.get("synonyms")
        syn_values: list[Any] = []
        if isinstance(raw_syn, list):
            syn_values = list(raw_syn)
        elif isinstance(raw_syn, dict):
            for v in raw_syn.values():
                if isinstance(v, list):
                    syn_values.extend(v)
                elif isinstance(v, str) and v:
                    syn_values.append(v)
        for s in syn_values:
            capped = _cap_str(s, _CAP_SYNONYM)
            if capped:
                synonyms.append(capped)

    if keywords:
        out["keywords"] = _dedup_top_k(keywords, _TOP_K_EXT_KEYWORDS)
    if entities:
        out["entities"] = _dedup_top_k(entities, _TOP_K_EXT_ENTITIES)
    if topics:
        deduped_topics = _dedup_top_k(topics, _TOP_K_EXT_TOPICS)
        out["topics"] = deduped_topics
        # singular 보강 — 사후 패치 (spec v5 keys: topic 명시)
        if deduped_topics:
            out["topic"] = deduped_topics[0]
    if query_keywords:
        out["query_keywords"] = _dedup_top_k(query_keywords, _TOP_K_QUERY_KEYWORDS)
    if synonyms:
        out["synonyms"] = _dedup_top_k(synonyms, _TOP_K_SYNONYMS)

    _enforce_total_cap(out)
    return out


def aggregate_block_metadata(
    source_blocks_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    """source block 들의 metadata 를 집계해서 chunk metadata 에 inject 할 dict 반환.

    Parameters
    ----------
    source_blocks_meta : list[dict]
        각 source block 의 metadata 사본 (DB row 의 metadata jsonb 또는
        BlockObject.metadata). image block 은 추가로 caption / image_type /
        is_decorative 도 포함될 수 있음.

    Returns
    -------
    dict
        chunk metadata 에 inject 할 키-값 dict. 모든 항목은 cap 적용.
    """
    if not source_blocks_meta:
        return {}

    topic_tags: list[str] = []
    summaries: list[str] = []
    query_keywords: list[str] = []
    synonyms: list[str] = []
    image_captions: list[str] = []
    table_nls: list[str] = []

    for meta in source_blocks_meta:
        if not isinstance(meta, dict):
            continue

        # topic_tags (block.metadata.topic_tags 보통 list)
        for tag in meta.get("topic_tags") or []:
            capped = _cap_str(tag, _CAP_TOPIC_TAG)
            if capped:
                topic_tags.append(capped)

        # search_summary (block 별 1개) + search_summaries 복수 키 호환
        ss = _cap_str(meta.get("search_summary"), _CAP_SUMMARY)
        if ss:
            summaries.append(ss)
        for s in (meta.get("search_summaries") or []):
            capped_s = _cap_str(s, _CAP_SUMMARY)
            if capped_s:
                summaries.append(capped_s)

        # query_keywords / synonyms (extracted_metadata 또는 metadata 둘 다 검색)
        for kw in (meta.get("query_keywords") or []):
            capped = _cap_str(kw, _CAP_QUERY_KEYWORD)
            if capped:
                query_keywords.append(capped)
        for syn in (meta.get("synonyms") or []):
            capped = _cap_str(syn, _CAP_SYNONYM)
            if capped:
                synonyms.append(capped)

        # image caption (image block)
        cap = _cap_str(meta.get("caption"), _CAP_IMAGE_CAPTION)
        if cap and not bool(meta.get("is_decorative", False)):
            image_captions.append(cap)

        # table_nl (table block)
        tnl = _cap_str(meta.get("table_nl"), _CAP_TABLE_NL)
        if tnl:
            table_nls.append(tnl)

    out: dict[str, Any] = {}
    if topic_tags:
        out["topic_tags"] = _dedup_top_k(topic_tags, _TOP_K_TOPIC_TAGS)
    if summaries:
        out["search_summaries"] = _dedup_top_k(summaries, _TOP_K_SUMMARIES)
    if query_keywords:
        out["query_keywords"] = _dedup_top_k(query_keywords, _TOP_K_QUERY_KEYWORDS)
    if synonyms:
        out["synonyms"] = _dedup_top_k(synonyms, _TOP_K_SYNONYMS)
    if image_captions:
        out["image_captions"] = _dedup_top_k(image_captions, _TOP_K_IMAGE_CAPTIONS)
    if table_nls:
        out["table_nls"] = _dedup_top_k(table_nls, _TOP_K_TABLE_NLS)

    # 총 payload 크기 cap (안전망)
    _enforce_total_cap(out)

    return out


def _enforce_total_cap(meta: dict[str, Any]) -> None:
    """총 payload byte 합이 cap 초과 시 가장 긴 list 부터 절단."""
    import json

    while True:
        try:
            size = len(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        except Exception:
            return
        if size <= _TOTAL_PAYLOAD_CAP_BYTES:
            return
        # 가장 긴 list 항목 1개 제거
        longest_key = None
        longest_len = 0
        for k, v in meta.items():
            if isinstance(v, list) and len(v) > longest_len:
                longest_key = k
                longest_len = len(v)
        if longest_key is None or longest_len == 0:
            return
        meta[longest_key].pop()
        if not meta[longest_key]:
            del meta[longest_key]


def propagate(
    chunk_metadata: dict[str, Any],
    source_blocks_meta: list[dict[str, Any]],
    *,
    source_extracted_meta: list[dict[str, Any]] | None = None,
    source_kc_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """기존 chunk metadata 에 block-level 의미 메타 전파.

    feature flag (env PROPAGATE_BLOCK_META_TO_CHUNK) 가 비활성이면 *no-op*.
    활성이면 aggregate_block_metadata 결과를 chunk_metadata 에 merge (기존 키
    덮어쓰지 않음 — chunk 가 이미 가진 값 우선).

    D31a (#206 v5 §2.3) — 신규 인자 (default None — 후방 호환):
    - source_extracted_meta: aggregate_extracted_metadata 호출용
    - source_kc_markers: aggregate_provenance 호출용 (없으면 source_blocks_meta 자체 사용)
    """
    if not is_enabled():
        return chunk_metadata
    if not source_blocks_meta and not source_extracted_meta:
        return chunk_metadata

    if source_blocks_meta:
        propagated = aggregate_block_metadata(source_blocks_meta)
        for k, v in propagated.items():
            if k not in chunk_metadata or not chunk_metadata.get(k):
                chunk_metadata[k] = v

        # KC marker / provenance — source_kc_markers 명시 시 그 값 사용 (빈 list 도 명시),
        # None 일 때만 source_blocks_meta 자체에서 KC marker 추출.
        kc_source = (
            source_kc_markers
            if source_kc_markers is not None
            else source_blocks_meta
        )
        provenance = aggregate_provenance(kc_source)
        for k, v in provenance.items():
            if k not in chunk_metadata or not chunk_metadata.get(k):
                chunk_metadata[k] = v

    if source_extracted_meta:
        ext_propagated = aggregate_extracted_metadata(source_extracted_meta)
        for k, v in ext_propagated.items():
            if k not in chunk_metadata or not chunk_metadata.get(k):
                chunk_metadata[k] = v

    log.debug(
        "chunk_meta_propagated",
        block_count=len(source_blocks_meta),
        ext_count=len(source_extracted_meta or []),
    )
    return chunk_metadata

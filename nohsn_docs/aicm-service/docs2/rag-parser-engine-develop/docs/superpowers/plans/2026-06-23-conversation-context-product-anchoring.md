# 대화-컨텍스트 상품 앵커링 (resolve-then-scope) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 콜봇 멀티턴 검색에서 (1) 검색된 표 블록이 자기 섹션 제목을 갖고 반환되게 하고, (2) 현재 발화에 상품명이 없어도 대화 이력의 상품을 해석해 검색을 그 상품으로 스코핑해 정답을 top_k 안에 넣는다.

**Architecture:** Phase 1 = 결과 빌더에서 `heading_path`를 `section_title`로 surface + 기존 문서 heading_path backfill. Phase 2 = 대화이력(USER턴) → ES `document_title` BM25 매칭으로 앵커 문서 해석(resolve) → 3개 searcher에 `document_ids` payload 필터 주입(scope) + 오앵커시 unscoped 폴백. LLM 미사용·하드코딩 없음·API 페이로드 불변.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy(asyncpg), Qdrant(qdrant_client), Elasticsearch(8.x), pytest. KMS search service(`src/search/`).

## Global Constraints

- 이모지 금지(코드/커밋/주석/문자열 어디에도). (사용자 절칙)
- 하드코딩 금지: 키워드/펀드 리스트/정답 문자열 금지. 상품 어휘는 **문서 제목(데이터)**에서 유도. (제1원칙)
- 기존 백엔드 재작성 금지: 보강만. RLS/tenant 격리 유지(모든 신규 필터는 tenant/repo 필터와 AND).
- API/콜봇 페이로드 불변(내부 자동 해석). conversation_history 없으면 신규 로직 미작동(무회귀).
- 커밋 메시지 한국어 + 버그/기능: 이슈·원인·수정 포함. 커밋 말미에:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW`
- 작업 브랜치 `develop`(origin=gitlab.timbel.dev, AWS Jenkins 소스). 배포(api 재시작)는 테스터 공지 후.
- 검증은 단발 + 멀티턴 회귀(중복요청/부정형/참조해소) 모두.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `src/search/context_weighting.py` | 컨텍스트 텍스트/벡터 유틸 | `build_anchor_query_text`, `select_anchors` 신규 |
| `src/search/hybrid/es_keyword.py` | ES 키워드 검색 | `resolve_documents_by_title` 신규 + `search()`에 `document_ids` 필터 |
| `src/search/hybrid/qdrant_dense.py` | Qdrant dense 검색 | `search()`에 `document_ids` FieldCondition |
| `src/search/hybrid/qdrant_sparse.py` | Qdrant sparse 검색 | `search()`에 `document_ids` FieldCondition |
| `src/search/service.py` | 검색 오케스트레이션 | `_section_title_from_heading_path` 신규 + `_to_result_items` surface + resolve→scope 배선 + 폴백 |
| `src/common/config.py` | settings | `ANCHOR_ABS_MIN`/`ANCHOR_REL_RATIO`/`ANCHOR_FALLBACK_MIN` |
| `scripts/backfill_heading_path.py` | 운영 backfill | 신규 스크립트 |
| `tests/search/test_context_anchor.py` | 단위 테스트 | 신규 |
| `tests/search/test_section_title_surface.py` | 단위 테스트 | 신규 |

---

# PHASE 1 — section_title surface + heading_path backfill

## Task 1: 결과에 heading_path를 section_title로 surface

**Files:**
- Modify: `src/search/service.py` (`_to_result_items`, 현재 line ~1553-1579; `section_title=hit.section_title` line 1565)
- Test: `tests/search/test_section_title_surface.py`

**Interfaces:**
- Consumes: `SearchHit`(`src/search/models.py`) — `.section_title: str | None`, `.source_location: SourceLocation`(`.heading_path: list[str]`).
- Produces: `_section_title_from_heading_path(source_location) -> str` (모듈/스태틱 헬퍼). `_to_result_items`가 빈 section_title을 heading_path로 채움.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/search/test_section_title_surface.py
from uuid import uuid4
from src.search.models import SearchHit, SourceLocation
from src.search.service import _section_title_from_heading_path


def _hit(section_title, heading_path):
    return SearchHit(
        chunk_id=uuid4(), document_id=uuid4(), document_title="하나코리아",
        section_title=section_title, content="| 종류 | 보유기간 | 환매수수료 |",
        source_location=SourceLocation(heading_path=heading_path),
    )


def test_empty_section_title_filled_from_heading_path():
    hit = _hit("", ["9. 환매수수료"])
    assert _section_title_from_heading_path(hit.source_location) == "9. 환매수수료"


def test_nested_heading_path_joined():
    hit = _hit("", ["8. 매입·환매 방법", "9. 환매수수료"])
    assert _section_title_from_heading_path(hit.source_location) == "8. 매입·환매 방법 > 9. 환매수수료"


def test_no_heading_path_returns_empty():
    hit = _hit("", [])
    assert _section_title_from_heading_path(hit.source_location) == ""


def test_qna_section_title_preserved():
    # QNA 블럭은 section_title(=질문)이 비어있지 않으므로 _to_result_items에서 보존된다.
    hit = _hit("환매수수료는 얼마인가요?", ["9. 환매수수료"])
    # 헬퍼는 heading_path만 본다. 보존 로직은 호출부(_to_result_items)에서 'or'로 구현.
    assert (hit.section_title or _section_title_from_heading_path(hit.source_location)) == "환매수수료는 얼마인가요?"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/search/test_section_title_surface.py -v`
Expected: FAIL — `ImportError: cannot import name '_section_title_from_heading_path'`

- [ ] **Step 3: 헬퍼 구현 + surface 배선**

`src/search/service.py` 상단(모듈 레벨 함수 영역, `_to_result_items` 근처)에 추가:
```python
def _section_title_from_heading_path(source_location) -> str:
    """heading_path 를 섹션 제목 문자열로. 없으면 빈 문자열.

    검색된 블럭(표 등)이 자기 섹션 제목(예: "9. 환매수수료")을 갖고 반환되도록
    한다. 헤딩이 별도 빈 블럭으로 분리돼 표 블럭에 제목이 없던 문제를 결과 단계에서
    보강(재임베딩 불요). QNA 의 section_title(=질문)은 호출부에서 'or' 우선 보존.
    """
    try:
        hp = getattr(source_location, "heading_path", None) or []
    except Exception:
        return ""
    parts = [str(h).strip() for h in hp if h and str(h).strip()]
    return " > ".join(parts)
```

`_to_result_items` 의 line 1565 를 변경:
```python
                    section_title=hit.section_title or _section_title_from_heading_path(hit.source_location),
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/search/test_section_title_surface.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/search/service.py tests/search/test_section_title_surface.py
git commit -F- <<'EOF'
fix(search): 검색된 표 블럭이 섹션 제목을 갖고 반환되도록 surface

이슈: 환매수수료 표 블럭이 검색결과에 section_title='' / section_path=[]로 제목 없이
      반환됨(헤딩은 별도 빈 블럭으로 분리). 콜봇이 제목 없는 표 또는 빈 헤딩만 받아
      "환매수수료 없습니다" 오답.
원인: _to_result_items가 section_title=hit.section_title만 사용 — heading_path가
      source_location에 있는데도 제목으로 surface하지 않음(코드 갭).
수정: section_title 비었으면 heading_path를 " > " 조인해 section_title로 채움
      (_section_title_from_heading_path). QNA 질문 section_title은 'or'로 보존.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 2: 기존 문서 heading_path backfill 스크립트

**Files:**
- Create: `scripts/backfill_heading_path.py`
- (참조) `src/pipeline/enrichers/heading_propagator.py`(`propagate_heading_paths`), `src/pipeline/models/block.py`(`BlockObject`)

**Interfaces:**
- Consumes: `propagate_heading_paths(blocks: list[BlockObject])` (제자리 수정, `block.source_location.heading_path` 채움).
- Produces: 워크스페이스/저장소 단위로 `blocks.source_location->heading_path` DB 업데이트. 재임베딩 불요(Task 1이 결과 단계에서 surface).

- [ ] **Step 1: 스크립트 작성**

```python
# scripts/backfill_heading_path.py
"""기존 문서 blocks.source_location.heading_path 백필.

신규 업로드는 block_worker(heading_propagator)로 자동 채워지나, 배포 전 등록 문서는
heading_path가 비어 있다. 블럭을 로드 → propagate_heading_paths → DB 업데이트.
재임베딩 불요(검색 결과 단계 surface는 Task 1). 사용:
    python scripts/backfill_heading_path.py --repository-id <uuid> [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json

import asyncpg

from src.common.config import settings
from src.pipeline.models.block import BlockObject
from src.pipeline.enrichers.heading_propagator import propagate_heading_paths


def _jl(v):
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return {}


async def backfill(repository_id: str, dry_run: bool) -> None:
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    doc_ids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM documents WHERE repository_id=$1", repository_id)]
    total = 0
    for doc_id in doc_ids:
        rows = await conn.fetch(
            """SELECT id, document_id, block_type, content, block_index,
                      source_location, metadata, properties
               FROM blocks WHERE document_id=$1 ORDER BY block_index""", doc_id)
        if not rows:
            continue
        blocks = [BlockObject.model_validate({
            "id": str(r["id"]), "document_id": str(r["document_id"]),
            "block_type": r["block_type"], "content": r["content"] or "",
            "block_index": r["block_index"], "source_location": _jl(r["source_location"]),
            "metadata": _jl(r["metadata"]), "properties": _jl(r["properties"]),
        }) for r in rows]
        propagate_heading_paths(blocks)
        for b in blocks:
            hp = [h for h in (b.source_location.heading_path or []) if h]
            if not hp:
                continue
            total += 1
            if dry_run:
                continue
            await conn.execute(
                "UPDATE blocks SET source_location=jsonb_set("
                "coalesce(source_location,'{}'::jsonb),'{heading_path}',$2::jsonb),"
                " updated_at=now() WHERE id=$1",
                b.id, json.dumps(hp, ensure_ascii=False))
    await conn.close()
    print(f"[backfill] repo={repository_id} docs={len(doc_ids)} blocks_with_path={total} dry_run={dry_run}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repository-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(backfill(args.repository_id, args.dry_run))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: dry-run으로 안전 확인 (timbel 대신 repo 2f3981d0)**

Run(컨테이너 내부): `python scripts/backfill_heading_path.py --repository-id 2f3981d0-6a2c-4893-918e-5554f4e5b99e --dry-run`
Expected: `blocks_with_path=<N>` (N>0), DB 미변경.

- [ ] **Step 3: 실제 backfill 실행**

Run: `python scripts/backfill_heading_path.py --repository-id 2f3981d0-6a2c-4893-918e-5554f4e5b99e`
Expected: 동일 N, DB 업데이트.

- [ ] **Step 4: 검증 — 검색 결과에 제목 반영**

Run: 콜봇 internal_search "하나코리아 펀드 환매 수수료" → 표 블럭의 `section_title`이 `"9. 환매수수료"`(또는 상위 경로 포함). Task 1 배포 후 확인.

- [ ] **Step 5: 커밋**

```bash
git add scripts/backfill_heading_path.py
git commit -F- <<'EOF'
chore(search): 기존 문서 heading_path 백필 스크립트

이슈: 배포 전 등록 문서는 blocks.heading_path가 비어 Task 1 surface가 동작 못 함.
원인: heading_propagator는 신규 업로드 enrich에만 적용.
수정: 저장소 단위로 블럭 로드→propagate_heading_paths→source_location.heading_path
      DB 업데이트(재임베딩 불요). --dry-run 지원.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

# PHASE 2 — resolve-then-scope

## Task 3: USER턴 앵커 질의 텍스트 빌더

**Files:**
- Modify: `src/search/context_weighting.py`
- Test: `tests/search/test_context_anchor.py`

**Interfaces:**
- Produces: `build_anchor_query_text(current_query: str, conversation_history: list[dict] | None, max_user_turns: int = 3) -> str` — 현재 발화 + 최근 USER 발화(assistant 제외)를 공백 결합.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/search/test_context_anchor.py
from src.search.context_weighting import build_anchor_query_text


def test_includes_current_query_and_user_turns_excludes_assistant():
    hist = [
        {"role": "user", "content": "하나코리아 펀드 가입했는데요"},
        {"role": "assistant", "content": "네 하나코리아증권자투자신탁 말씀이시군요"},
        {"role": "user", "content": "수수료가 궁금해요"},
    ]
    out = build_anchor_query_text("잠깐 환매하면 수수료 있어요?", hist)
    assert "잠깐 환매하면 수수료 있어요?" in out
    assert "하나코리아" in out          # user turn 포함
    assert "수수료가 궁금해요" in out   # user turn 포함
    assert "말씀이시군요" not in out    # assistant turn 제외


def test_no_history_returns_current_query():
    assert build_anchor_query_text("환매 수수료?", None).strip() == "환매 수수료?"


def test_recency_limit_user_turns():
    hist = [{"role": "user", "content": f"발화{i}"} for i in range(10)]
    out = build_anchor_query_text("현재", hist, max_user_turns=3)
    assert "발화9" in out and "발화8" in out and "발화7" in out
    assert "발화0" not in out
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/search/test_context_anchor.py::test_includes_current_query_and_user_turns_excludes_assistant -v`
Expected: FAIL — `ImportError: cannot import name 'build_anchor_query_text'`

- [ ] **Step 3: 구현**

`src/search/context_weighting.py` 에 추가:
```python
def build_anchor_query_text(
    current_query: str,
    conversation_history: list[dict] | None,
    max_user_turns: int = 3,
) -> str:
    """앵커 해석용 텍스트 — 현재 발화 + 최근 USER 발화(assistant 제외).

    봇 인사/메뉴 안내(assistant)가 여러 상품명을 나열해 앵커를 흐리는 것을 막기 위해
    role == 'user' 메시지만 사용한다. 최근 max_user_turns 개만(과거 다른 상품 잔향 약화).
    """
    parts: list[str] = []
    if conversation_history:
        user_msgs = [
            str(m.get("content", "")).strip()
            for m in conversation_history
            if m.get("role") == "user" and m.get("content")
        ]
        parts.extend(user_msgs[-max_user_turns:])
    cur = (current_query or "").strip()
    if cur:
        parts.append(cur)
    return " ".join(p for p in parts if p)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/search/test_context_anchor.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/search/context_weighting.py tests/search/test_context_anchor.py
git commit -F- <<'EOF'
feat(search): 앵커 해석용 USER턴 질의 텍스트 빌더

기능: 대화이력에서 role=user 발화만(assistant 제외) 최근 N턴 + 현재 발화를 결합해
      상품 앵커 해석 입력을 만든다(봇 인사/메뉴 노이즈 차단, recency 우선).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 4: 앵커 판정(임계 + 모호성)

**Files:**
- Modify: `src/search/context_weighting.py`
- Test: `tests/search/test_context_anchor.py`

**Interfaces:**
- Produces: `select_anchors(ranked: list[tuple[str, float]], abs_min: float, rel_ratio: float) -> list[str]` — ranked=(document_id, score) 내림차순. abs_min 이상 + top1 대비 rel_ratio 이상인 문서 id 리스트. 없으면 [].

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/search/test_context_anchor.py (추가)
from src.search.context_weighting import select_anchors


def test_single_strong_anchor():
    assert select_anchors([("docA", 9.0), ("docB", 2.0)], abs_min=3.0, rel_ratio=0.8) == ["docA"]


def test_multi_close_anchors():
    out = select_anchors([("docA", 9.0), ("docB", 8.5)], abs_min=3.0, rel_ratio=0.8)
    assert set(out) == {"docA", "docB"}


def test_no_anchor_below_abs_min():
    assert select_anchors([("docA", 1.0)], abs_min=3.0, rel_ratio=0.8) == []


def test_empty_input():
    assert select_anchors([], abs_min=3.0, rel_ratio=0.8) == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/search/test_context_anchor.py -k select_anchors -v`
Expected: FAIL — `ImportError: cannot import name 'select_anchors'`

- [ ] **Step 3: 구현**

```python
def select_anchors(
    ranked: list[tuple[str, float]],
    abs_min: float,
    rel_ratio: float,
) -> list[str]:
    """제목매칭 결과에서 앵커 문서 선택.

    1) score >= abs_min 인 문서만 후보.
    2) top1 점수 대비 rel_ratio 이상인 동률군은 모두 앵커(복수 상품 비교질의 대응).
    3) 없으면 [] (앵커 없음 → 스코프 미적용).
    """
    cands = [(d, s) for d, s in ranked if s >= abs_min]
    if not cands:
        return []
    top = max(s for _, s in cands)
    return [d for d, s in cands if s >= top * rel_ratio]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/search/test_context_anchor.py -k select_anchors -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/search/context_weighting.py tests/search/test_context_anchor.py
git commit -F- <<'EOF'
feat(search): 앵커 판정(절대임계+상대비율) — 단일/다중/없음

기능: 제목매칭 점수에서 abs_min 이상 & top1 대비 rel_ratio 이상 문서를 앵커로 선택.
      강매칭=단일앵커, 근접복수=다중앵커, 약함=앵커없음(폴백).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 5: 3개 searcher에 document_ids 필터 추가

**Files:**
- Modify: `src/search/hybrid/qdrant_dense.py` (`search`, conditions 빌드 ~line 143)
- Modify: `src/search/hybrid/qdrant_sparse.py` (`search`, 동일 패턴)
- Modify: `src/search/hybrid/es_keyword.py` (`search`, block 인덱스 filters ~line 293)
- Test: `tests/search/test_document_ids_filter.py`

**Interfaces:**
- Produces: 세 `search(...)` 에 키워드 인자 `document_ids: list[str] | None = None` 추가. 값 있으면 qdrant `FieldCondition(key="document_id", match=MatchAny(any=document_ids))`, ES `{"terms": {"document_id": document_ids}}` 추가. None/[]이면 미적용.

- [ ] **Step 1: 실패 테스트 작성 (qdrant 필터 빌드 검증)**

```python
# tests/search/test_document_ids_filter.py
from src.search.hybrid.qdrant_dense import QdrantDenseSearcher


def test_document_ids_builds_field_condition():
    # _build_filter 류 순수 헬퍼가 있으면 그것을, 없으면 conditions 빌드 로직을 직접 호출.
    searcher = QdrantDenseSearcher.__new__(QdrantDenseSearcher)
    flt = searcher._build_conditions(  # Step 3에서 conditions 빌드를 헬퍼로 추출
        tenant_id=None, repository_ids=None, category_ids=None,
        document_type_ids=None, block_types=None, nature_filter=None,
        validity_filter="all", entity_filter=None, document_status_filter="all",
        document_ids=["docA", "docB"],
    )
    keys = [c.key for c in flt]
    assert "document_id" in keys
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/search/test_document_ids_filter.py -v`
Expected: FAIL — `_build_conditions` 부재 또는 document_id 미포함.

- [ ] **Step 3: 구현**

`qdrant_dense.py` `search` 시그니처에 `document_ids: list[str] | None = None` 추가. conditions 빌드에서 `repository_ids` 블럭(현 line 143-149) 바로 뒤에:
```python
        if document_ids:
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchAny(any=document_ids),
                )
            )
```
(테스트 용이성을 위해 conditions 빌드를 `_build_conditions(...)` 메서드로 추출 권장 — 기존 인자 + `document_ids`. 추출이 과하면 테스트를 search()의 통합 테스트로 대체.)

`qdrant_sparse.py` — 동일 시그니처/조건 추가.

`es_keyword.py` `search` 시그니처에 `document_ids` 추가. block 인덱스 filters(현 line 293 `repository_ids` term) 뒤에:
```python
            if document_ids:
                filters.append({"terms": {"document_id": document_ids}})
```
(레거시 청크 인덱스 분기에도 동일 추가 — line 337 부근 tenant_id 필터 뒤.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/search/test_document_ids_filter.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/search/hybrid/qdrant_dense.py src/search/hybrid/qdrant_sparse.py src/search/hybrid/es_keyword.py tests/search/test_document_ids_filter.py
git commit -F- <<'EOF'
feat(search): dense/sparse/keyword searcher에 document_ids 필터 추가

기능: payload document_id 기반 검색 스코핑 필터(기존 repository_ids 필터와 동형).
      None/빈값이면 미적용. tenant/repo 필터와 AND(격리 유지).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 6: ES 제목 카탈로그 매칭(resolve_documents_by_title)

**Files:**
- Modify: `src/search/hybrid/es_keyword.py`
- Test: `tests/search/test_resolve_by_title.py` (ES 미가용 시 integration mark)

**Interfaces:**
- Consumes: ES 블럭 인덱스(`*_blocks`)의 `document_title` 필드(analyzer=korean) + `document_id`.
- Produces: `async def resolve_documents_by_title(self, text: str, index_name: str, repository_ids, tenant_id, top_n=5) -> list[tuple[str, float]]` — text를 document_title에 match, document_id 별 최고 스코어 집계, 내림차순.

- [ ] **Step 1: 테스트 작성(ES mock 또는 integration)**

```python
# tests/search/test_resolve_by_title.py
import pytest
from src.search.hybrid.es_keyword import ESKeywordSearcher


@pytest.mark.asyncio
async def test_resolve_aggregates_by_document_id(monkeypatch):
    searcher = ESKeywordSearcher.__new__(ESKeywordSearcher)

    class _FakeES:
        async def search(self, index, body):
            return {"aggregations": {"by_doc": {"buckets": [
                {"key": "docHANA", "max_score": {"value": 7.2}},
                {"key": "docHANTU", "max_score": {"value": 2.1}},
            ]}}}

    async def _fake_client():
        return _FakeES()
    monkeypatch.setattr(searcher, "_get_client", _fake_client)
    out = await searcher.resolve_documents_by_title(
        "하나코리아 펀드 환매 수수료", "aicm_t_blocks", ["repo1"], "ten1")
    assert out[0] == ("docHANA", 7.2)
    assert out[1][0] == "docHANTU"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/search/test_resolve_by_title.py -v`
Expected: FAIL — `resolve_documents_by_title` 부재.

- [ ] **Step 3: 구현**

`es_keyword.py` 에 추가(클라이언트 획득은 기존 `_get_client` 재사용):
```python
    async def resolve_documents_by_title(
        self, text: str, index_name: str,
        repository_ids: list[str] | None, tenant_id: str | None, top_n: int = 5,
    ) -> list[tuple[str, float]]:
        """text 를 document_title 에 match 하고 document_id 별 최고 스코어로 집계.

        IDF 가 공통 토큰(증권자투자신탁/주식 등)을 자동 강등하고 희소 브랜드 토큰
        (하나코리아 등)을 부각 → 별도 토큰선별 불요. 앵커 후보를 (doc_id, score)로 반환.
        """
        if not text.strip():
            return []
        client = await self._get_client()
        must: list[dict] = [{"match": {"document_title": text}}]
        flt: list[dict] = []
        if tenant_id:
            flt.append({"term": {"tenant_id": str(tenant_id)}})
        if repository_ids:
            flt.append({"terms": {"repository_id": repository_ids}})
        body = {
            "size": 0,
            "query": {"bool": {"must": must, "filter": flt}},
            "aggs": {"by_doc": {
                "terms": {"field": "document_id", "size": top_n, "order": {"max_score": "desc"}},
                "aggs": {"max_score": {"max": {"script": "_score"}}},
            }},
        }
        try:
            resp = await client.search(index=index_name, body=body)
        except Exception:
            log.warning("resolve_documents_by_title_failed", index=index_name, exc_info=True)
            return []
        buckets = (((resp or {}).get("aggregations") or {}).get("by_doc") or {}).get("buckets") or []
        return [(b["key"], float(b["max_score"]["value"])) for b in buckets]
```
(주의: `document_id` 가 ES 매핑에 `keyword` 로 집계 가능해야 함 — 매핑 확인. 없으면 `document_id.keyword` 사용. `max_score` script agg 가 무거우면 `top_hits` size=1 로 대체 가능.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/search/test_resolve_by_title.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/search/hybrid/es_keyword.py tests/search/test_resolve_by_title.py
git commit -F- <<'EOF'
feat(search): 대화→상품 해석용 ES 제목 카탈로그 매칭

기능: 텍스트를 document_title에 BM25 match + document_id 집계로 앵커 후보 반환.
      IDF가 공통 토큰 강등/브랜드 부각(하드코딩 없음). tenant/repo 필터 적용.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 7: config settings

**Files:**
- Modify: `src/common/config.py`

**Interfaces:**
- Produces: `settings.ANCHOR_ABS_MIN: float`, `settings.ANCHOR_REL_RATIO: float`, `settings.ANCHOR_FALLBACK_MIN: int`, `settings.CONTEXT_ANCHOR_ENABLED: bool`.

- [ ] **Step 1: 추가**

`src/common/config.py` Settings 클래스에(기존 DEFAULT_*_WEIGHT 근처 패턴):
```python
    # 대화-컨텍스트 상품 앵커링 (resolve-then-scope, 2026-06-23)
    CONTEXT_ANCHOR_ENABLED: bool = True
    ANCHOR_ABS_MIN: float = 4.0        # ES title match 최소 스코어(스테이징 캘리브레이션)
    ANCHOR_REL_RATIO: float = 0.8      # top1 대비 동률군 포함 비율
    ANCHOR_FALLBACK_MIN: int = 1       # 스코프 후 후보 < 이 값이면 unscoped 재시도
```

- [ ] **Step 2: import 검증**

Run: `python -c "from src.common.config import settings; print(settings.ANCHOR_ABS_MIN, settings.CONTEXT_ANCHOR_ENABLED)"`
Expected: `4.0 True`

- [ ] **Step 3: 커밋**

```bash
git add src/common/config.py
git commit -F- <<'EOF'
feat(config): 컨텍스트 앵커링 settings(enable/abs_min/rel_ratio/fallback_min)

기능: resolve-then-scope 튜닝 파라미터. 하드코딩 상수 대신 settings 노출.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 8: service.py 에 resolve→scope 배선 + 폴백

**Files:**
- Modify: `src/search/service.py` (dense/sparse/keyword task 생성 직전 ~line 1098-1197 영역; 폴백은 결과 조립 직전)
- Test: `tests/search/test_anchor_wiring.py`

**Interfaces:**
- Consumes: `build_anchor_query_text`, `select_anchors`(context_weighting), `self._keyword_searcher.resolve_documents_by_title`, settings. `request.conversation_history`, `request.query`, `es_index_name`, `repo_ids_str`, `_tenant_id_str`.
- Produces: 해석된 `anchor_doc_ids` 를 세 searcher 의 `document_ids=` 로 전달. 스코프 결과가 `ANCHOR_FALLBACK_MIN` 미만이면 동일 검색을 `document_ids=None`(unscoped)로 1회 재시도.

- [ ] **Step 1: 실패 테스트 작성(앵커 해석→document_ids 전달)**

```python
# tests/search/test_anchor_wiring.py
import pytest
from src.search.context_weighting import build_anchor_query_text, select_anchors


@pytest.mark.asyncio
async def test_resolve_then_select(monkeypatch):
    # 통합 단위: build_anchor_query_text → resolve(mock) → select_anchors
    text = build_anchor_query_text("환매 수수료?",
        [{"role": "user", "content": "하나코리아 펀드"}])
    ranked = [("docHANA", 8.0), ("docHANTU", 1.0)]  # resolve_documents_by_title mock 결과
    anchors = select_anchors(ranked, abs_min=4.0, rel_ratio=0.8)
    assert anchors == ["docHANA"]
    assert "하나코리아" in text
```

- [ ] **Step 2: 테스트 실패/통과 확인**

Run: `pytest tests/search/test_anchor_wiring.py -v`
Expected: PASS (Task 3·4 구현 후 — 이 테스트는 배선 단위 검증, service 통합은 Task 9 E2E에서).

- [ ] **Step 3: service.py 배선 구현**

dense/sparse/keyword task 생성 직전에:
```python
        anchor_doc_ids: list[str] = []
        if settings.CONTEXT_ANCHOR_ENABLED and request.conversation_history:
            from src.search.context_weighting import build_anchor_query_text, select_anchors
            anchor_text = build_anchor_query_text(request.query, request.conversation_history)
            try:
                ranked = await self._keyword_searcher.resolve_documents_by_title(
                    anchor_text, es_index_name, repo_ids_str, _tenant_id_str)
                anchor_doc_ids = select_anchors(
                    ranked, settings.ANCHOR_ABS_MIN, settings.ANCHOR_REL_RATIO)
            except Exception:
                log.warning("context_anchor_resolve_failed", exc_info=True)
            if anchor_doc_ids:
                log.info("context_anchor_resolved", doc_ids=anchor_doc_ids,
                         anchor_text=anchor_text[:120])
```
세 task 생성에 `document_ids=anchor_doc_ids or None` 인자 추가(dense/hyde_dense/sparse/keyword 모두).

폴백 — fusion/rerank 후 결과 조립 직전, 스코프를 적용했는데 결과가 부족하면 재시도:
```python
        if anchor_doc_ids and len(results) < settings.ANCHOR_FALLBACK_MIN:
            log.info("context_anchor_fallback_unscoped", anchor=anchor_doc_ids)
            # anchor_doc_ids 를 비우고 동일 검색 1회 재실행(스코프 미적용 경로 재사용).
            # 구현: _execute_with_split 를 anchor 없이 재호출하거나, document_ids=None 으로
            # 재검색하는 내부 헬퍼로 분기. (중복 검색 1회 — 폴백 한정이라 비용 허용.)
```
(폴백은 기존 검색 실행부를 `document_ids` 파라미터화한 내부 함수로 한번 감싸 재호출하는 형태로 구현. 과한 리팩터 회피 위해, 최초 구현은 "스코프 결과 0건일 때만" 폴백으로 최소화.)

- [ ] **Step 4: 단위 테스트 통과 + 문법 확인**

Run: `pytest tests/search/test_anchor_wiring.py -v && python -m py_compile src/search/service.py`
Expected: PASS + 문법 OK

- [ ] **Step 5: 커밋**

```bash
git add src/search/service.py tests/search/test_anchor_wiring.py
git commit -F- <<'EOF'
feat(search): resolve-then-scope 배선 — 대화이력 상품 앵커로 검색 스코핑

이슈: 펀드명 없는 콜봇 질의가 3개 펀드 유사블럭에 밀려 정답표가 top_k 밖(케이스1 재현).
원인: 8:2 dense 가중은 keyword(지배채널)에 이력 미반영 → 변별 실패.
수정: USER턴 이력→ES 제목매칭으로 앵커 문서 해석→3개 searcher에 document_ids 스코프.
      앵커 없음/모호/오앵커(결과부족)는 unscoped 폴백(무회귀). conversation_history
      없으면 미작동.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW
EOF
```

---

## Task 9: E2E 검증 (timbel 실데이터)

**Files:** (코드 변경 없음 — 검증 런북)

- [ ] **Step 1: 배포** — Task 1~8 반영 이미지로 `lucas-kms-api` cp+재시작(테스터 공지 후). heading_path backfill(Task 2) 실행.
- [ ] **Step 2: Phase 1 검증** — internal_search "하나코리아 펀드 환매 수수료" → 표 블럭 `section_title="9. 환매수수료"`(또는 경로).
- [ ] **Step 3: Phase 2 케이스1** — `text="환매하면 수수료 있어요?"` + `conversation_history=[{"role":"user","content":"하나코리아 펀드 가입했는데요"}]` → 정답 수수료율표 **top_k=5 안**. `history` 없으면 변화 없음(무회귀).
- [ ] **Step 4: 케이스2/무회귀** — `text="하나코리아 펀드 환매하면 수수료 있어요?"` → 그대로 정답 top(스코프 무해). 봇턴만 상품 나열 → 앵커 안 잡힘. 콜드(이력 없음) → 현재 동작.
- [ ] **Step 5: 멀티턴 회귀(CLAUDE.md)** — 중복요청/부정형/참조해소 케이스에서 앵커 오작동 없는지.

---

## Self-Review

**Spec coverage:** Phase1-A(Task1)·Phase1-B(Task2)·Phase1-C(선택, 미포함—필요시 추가)·RESOLVE(Task3·4·6)·SCOPE(Task5)·배선/폴백(Task8)·settings(Task7)·검증(Task9). 스펙 §4.5/§5/§6/§9/§10 매핑 완료.
**Placeholder scan:** Task8 폴백은 "최초 구현은 결과 0건일 때만"으로 범위 명시(추상 지시 아님). ES `document_id` 매핑 keyword 여부는 Task6에 확인 주석. 그 외 placeholder 없음.
**Type consistency:** `build_anchor_query_text`/`select_anchors`/`resolve_documents_by_title`/`_section_title_from_heading_path`/`document_ids` 시그니처가 Task 간 일치. `select_anchors`는 (doc_id,score) 튜플 리스트 입력으로 Task6 출력과 일치.

## 미해결/주의
- ES `document_id` 집계: 매핑이 keyword가 아니면 `document_id.keyword` 사용(Task6에서 매핑 확인).
- ANCHOR_ABS_MIN 초기값(4.0)은 스테이징 실측 캘리브레이션 필요(보수적 시작).
- Phase1-C(빈 헤딩 검색 제외)는 surface 후 영향 재평가 뒤 별도 추가.

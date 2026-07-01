# 청크 임베딩 컨텍스트 prefix 구현 계획 (#1 검색오류)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인덱싱 시 각 블록의 임베딩 입력 텍스트 앞에 `[문서제목 > 섹션]`을 결정적으로 prepend해, 펀드명이 본문에 없는 표 chunk도 제품 특정 질의에 매칭되게 한다.

**Architecture:** `embed_worker.handle_document_blocked`에서 BGE-M3에 넣는 텍스트(`block.embedding_text()`) 앞에만 컨텍스트를 붙인다. 저장 블록·Qdrant/ES payload·검색 반환·rerank 텍스트는 불변(임베딩 벡터에만 영향). 순수 헬퍼 함수로 분리해 단위 테스트.

**Tech Stack:** Python 3.11, pydantic BlockObject, pytest(asyncio_mode=auto), BGE-M3(FlagEmbedding).

**Spec:** `docs/superpowers/specs/2026-06-22-chunk-embedding-context-prefix-design.md`

## Global Constraints
- 이모지 금지(코드/커밋/파일). (rag-parser CLAUDE.md §2)
- 하드코딩 금지(도메인 키워드/정답 문자열). 본 작업의 파일 확장자 집합은 구조적 상수(도메인 키워드 아님)로 허용.
- 검증 시 multi-turn 회귀(중복요청/부정형조회/시간slot/참조해소) 포함. (CLAUDE.md §2 — 운영 검증 §Rollout)
- 임베딩 입력 텍스트만 변경. payload `content`/ES `content`/검색 반환/rerank 텍스트는 절대 불변.
- branch: `develop`. 커밋 메시지 한국어.
- 헬퍼는 LLM 미사용·결정적.

## File Structure
- Modify: `src/pipeline/workers/embed_worker.py` — 헬퍼 함수 2개 추가(`_clean_doc_title`, `_embedding_text_with_context`) + `handle_document_blocked` 임베딩 입력부 배선(제목 선조회).
- Create(Test): `tests/pipeline/workers/test_embed_context_prefix.py` — 헬퍼 단위 테스트.

---

### Task 1: 컨텍스트 prefix 헬퍼 (`_clean_doc_title`, `_embedding_text_with_context`)

**Files:**
- Modify: `src/pipeline/workers/embed_worker.py` (모듈 레벨 헬퍼 추가; 기존 `_get_document_meta`(1048) 인접 위치면 충분)
- Test: `tests/pipeline/workers/test_embed_context_prefix.py` (신규)

**Interfaces:**
- Produces:
  - `_clean_doc_title(title: str | None) -> str` — 제목에서 문서 확장자 제거, None/빈값 안전, strip.
  - `_embedding_text_with_context(block, document_title: str) -> str` — `block`은 `.embedding_text() -> str`, `.contextual_prefix`, `.source_location.heading_path: list[str]` 속성을 가진 객체(BlockObject 덕타이핑). 반환 = prefix가 붙은 임베딩 입력 텍스트(또는 prefix 불가 시 원본).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/pipeline/workers/test_embed_context_prefix.py`:
```python
from types import SimpleNamespace

from src.pipeline.workers.embed_worker import (
    _clean_doc_title,
    _embedding_text_with_context,
)


class _StubBlock:
    """BlockObject 덕타이핑 스텁 — 헬퍼가 쓰는 속성/메서드만 노출."""

    def __init__(self, *, content="본문내용", heading_path=None, contextual_prefix=None):
        self.contextual_prefix = contextual_prefix
        self.source_location = SimpleNamespace(heading_path=heading_path or [])
        self._content = content

    def embedding_text(self):
        return self._content


def test_clean_doc_title_strips_known_extension():
    assert _clean_doc_title("미래에셋차세대Fun인덱스증권자투자신탁.docx") == "미래에셋차세대Fun인덱스증권자투자신탁"


def test_clean_doc_title_keeps_non_extension_dot():
    # 확장자가 아닌 점은 보존(예: 버전·배수 표기)
    assert _clean_doc_title("1.5배 레버리지 안내") == "1.5배 레버리지 안내"


def test_clean_doc_title_none_and_blank():
    assert _clean_doc_title(None) == ""
    assert _clean_doc_title("   ") == ""


def test_prefix_title_and_section():
    b = _StubBlock(content="| 구분 | 15시 30분 |", heading_path=["환매수수료"])
    out = _embedding_text_with_context(b, "미래에셋차세대Fun인덱스증권자투자신탁.docx")
    assert out == "미래에셋차세대Fun인덱스증권자투자신탁 > 환매수수료\n\n| 구분 | 15시 30분 |"


def test_prefix_section_empty_uses_title_only():
    b = _StubBlock(content="본문", heading_path=[])
    out = _embedding_text_with_context(b, "미래에셋.docx")
    assert out == "미래에셋\n\n본문"


def test_prefix_title_empty_uses_section_only():
    b = _StubBlock(content="본문", heading_path=["환매수수료", "지급시점"])
    out = _embedding_text_with_context(b, "")
    assert out == "환매수수료 > 지급시점\n\n본문"


def test_prefix_both_empty_returns_base():
    b = _StubBlock(content="본문", heading_path=[])
    assert _embedding_text_with_context(b, "") == "본문"


def test_contextual_prefix_present_skips_prepend():
    b = _StubBlock(content="본문", heading_path=["환매수수료"], contextual_prefix="[문서: X | 섹션: Y]")
    # contextual_prefix 가 있으면 embedding_text() 원본 그대로(이중 문서맥락 회피)
    assert _embedding_text_with_context(b, "미래에셋.docx") == "본문"


def test_heading_path_filters_empty_segments():
    b = _StubBlock(content="본문", heading_path=["", "환매수수료", ""])
    out = _embedding_text_with_context(b, "미래에셋")
    assert out == "미래에셋 > 환매수수료\n\n본문"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/pipeline/workers/test_embed_context_prefix.py -v`
Expected: FAIL — `ImportError: cannot import name '_clean_doc_title'`(또는 `_embedding_text_with_context`).

- [ ] **Step 3: 헬퍼 구현**

`src/pipeline/workers/embed_worker.py` 상단 import 영역에 `os`가 import 돼 있는지 확인하고 없으면 추가:
```python
import os
```

`_get_document_meta` 함수(약 1048행) 위 또는 인접한 모듈 레벨에 추가:
```python
# 임베딩 입력 컨텍스트 prefix 용 문서 확장자 집합(제목 정리용 — 구조적 상수, 도메인 키워드 아님)
_DOC_EXTENSIONS = {
    ".docx", ".doc", ".pdf", ".hwp", ".hwpx",
    ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md",
}


def _clean_doc_title(title) -> str:
    """문서 제목에서 파일 확장자를 제거한다. None/빈값 안전."""
    if not title:
        return ""
    t = str(title).strip()
    root, ext = os.path.splitext(t)
    if ext.lower() in _DOC_EXTENSIONS:
        return root.strip()
    return t


def _embedding_text_with_context(block, document_title: str) -> str:
    """블록 임베딩 입력 앞에 [문서제목 > 섹션] 컨텍스트를 결정적으로 prepend.

    표(table) 등 본문에 문서명이 없는 블록도 제품 특정 질의에 매칭되게 한다.
    저장 블록/payload/검색 반환/rerank 텍스트는 불변(임베딩 입력만 변경).
    contextual_prefix(LLM 맥락)가 이미 있으면 이중 문서맥락 회피 위해 skip.
    제목/섹션이 모두 없으면 원본 embedding_text() 그대로 반환.
    """
    base = block.embedding_text()
    if getattr(block, "contextual_prefix", None):
        return base
    title = _clean_doc_title(document_title)
    heading_path = getattr(block.source_location, "heading_path", None) or []
    section = " > ".join(h for h in heading_path if h)
    if title and section:
        prefix = f"{title} > {section}"
    elif title:
        prefix = title
    elif section:
        prefix = section
    else:
        return base
    return f"{prefix}\n\n{base}"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/pipeline/workers/test_embed_context_prefix.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/workers/embed_worker.py tests/pipeline/workers/test_embed_context_prefix.py
git commit -m "feat(embedding-prefix): 문서제목+섹션 컨텍스트 prefix 헬퍼 + 단위테스트"
```

---

### Task 2: `handle_document_blocked` 임베딩 입력 배선 (제목 선조회)

**Files:**
- Modify: `src/pipeline/workers/embed_worker.py:596-616` (`handle_document_blocked` 임베딩 입력부)

**Interfaces:**
- Consumes: Task 1의 `_embedding_text_with_context(block, document_title)`, 기존 `_get_document_meta(document_id, repository_id) -> (title, repo_name)`.
- Produces: 동작 변경 없음(공개 인터페이스 불변). 임베딩 입력 텍스트만 컨텍스트 포함으로 변경.

- [ ] **Step 1: 현재 코드 확인**

Run: `sed -n '596,616p' src/pipeline/workers/embed_worker.py`
Expected: 596행 주석 `# 임베딩 텍스트 준비 ...`, 597행 `embedding_texts = [b.embedding_text() for b in blocks]`, 612~616행에 `_get_document_category_ids` + `_get_document_meta`(document_title 조회)가 임베딩 *이후*에 위치.

- [ ] **Step 2: 임베딩 입력부 교체 (제목 선조회 + 헬퍼 적용)**

596~616행 구간을 다음으로 교체. `_get_document_meta`(제목/저장소명) 호출을 임베딩 *앞*으로 이동하고, 임베딩 텍스트 생성에 헬퍼 적용. `_get_document_category_ids`는 위치 유지.

기존:
```python
        # 임베딩 텍스트 준비 (contextual_prefix + content)
        embedding_texts = [b.embedding_text() for b in blocks]
        results = await batch_processor.embed_texts(embedding_texts)

        for block, result in zip(blocks, results):
            block.dense_vector = result.dense
            block.sparse_vector = result.sparse

        # 3.4) 의미 중복 제거 (BGE-M3 임베딩 기반 near-dup)
        try:
            from src.pipeline.enrichers.semantic_deduper import deduplicate_by_embedding

            blocks = deduplicate_by_embedding(blocks)
        except Exception as exc:
            log.debug("semantic_dedup_failed", error=str(exc))

        # 3.5) 문서 메타 조회 (카테고리, 제목, 저장소명 — Qdrant/ES payload에 포함)
        category_ids = await _get_document_category_ids(event.document_id)
        document_title, repository_name = await _get_document_meta(
            event.document_id, event.repository_id
        )
```

교체 후:
```python
        # 3.5-pre) 문서 제목 선조회 — 임베딩 입력에 [문서제목 > 섹션] 컨텍스트 prepend 용
        document_title, repository_name = await _get_document_meta(
            event.document_id, event.repository_id
        )

        # 임베딩 텍스트 준비 (문서 컨텍스트 prefix + contextual_prefix + content)
        embedding_texts = [
            _embedding_text_with_context(b, document_title) for b in blocks
        ]
        results = await batch_processor.embed_texts(embedding_texts)

        for block, result in zip(blocks, results):
            block.dense_vector = result.dense
            block.sparse_vector = result.sparse

        # 3.4) 의미 중복 제거 (BGE-M3 임베딩 기반 near-dup)
        try:
            from src.pipeline.enrichers.semantic_deduper import deduplicate_by_embedding

            blocks = deduplicate_by_embedding(blocks)
        except Exception as exc:
            log.debug("semantic_dedup_failed", error=str(exc))

        # 3.5) 문서 카테고리 조회 (Qdrant/ES payload에 포함; 제목/저장소명은 위에서 선조회)
        category_ids = await _get_document_category_ids(event.document_id)
```

- [ ] **Step 3: payload content 불변 확인(누출 방지 회귀)**

Run: `grep -nE '"content": block\.content|content=payload' src/pipeline/workers/embed_worker.py | head`
Expected: Qdrant/ES payload가 여전히 `block.content`(raw)를 사용(약 836·1008행). 즉 prefix는 임베딩 입력에만, payload엔 미반영.

- [ ] **Step 4: 문법/import 스모크 + 기존 워커 테스트 회귀**

Run: `python -c "import ast; ast.parse(open('src/pipeline/workers/embed_worker.py',encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

Run: `python -m pytest tests/pipeline/workers/ -v`
Expected: 기존 `test_d47_load_blocks_sanitize` 등 + 신규 prefix 테스트 모두 PASS(또는 기존 통과분 무회귀).

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/workers/embed_worker.py
git commit -m "feat(embedding-prefix): handle_document_blocked 임베딩 입력에 문서 컨텍스트 prefix 배선(제목 선조회)"
```

---

## Rollout & Validation (운영 — 코드 작업 후, 사전 공지 필요)

> 코드 머지 후 운영 단계. 배포는 사전 공지([[feedback_deploy_announce]]) 후. 절차는 [[project_perm_deploy_recipe]](worker rebuild).

1. **timbel(개발) 배포**: 변경 src 동기화 → `lucas-kms` worker(small/large) rebuild → up.
2. **재임베딩**: 펀드 문서가 있는 워크스페이스에서 `from_stage='embedding'` 재시도(재파싱 없이 재임베딩만). 먼저 미래에셋 등 펀드 문서 1~수건 → 전체.
3. **효과 검증**: `/search/internal/document` 로 Q1("미래에셋 차세대Fun 펀드 환매수수료") top_k=20 비교 — 미래에셋 환매수수료 chunk가 8위 → top-3 진입 확인.
4. **회귀 검증(필수, multi-turn 포함)**:
   - Q2("미래에셋 환매수수료") 정상 유지.
   - 일반 토픽("환매수수료")·비펀드 문서 무영향.
   - rerank ON 점수분포 도입 전/후 비교(중복요청·부정형조회·시간slot·참조해소 회귀 케이스)로 콜봇 threshold(0.5) 통과율 안정 확인.
   - payload content에 prefix 미포함(누출 0) 실데이터 확인.
5. **AWS(POC)**: timbel 검증 통과 후 worker 빌드 → 재임베딩 → 동일 검증.
6. **롤백**: prefix 비활성 = 코드 revert + 재임베딩(이미 임베딩된 벡터는 재임베딩해야 원복). flag는 두지 않음(YAGNI; 롤백은 revert+재임베딩).

## Self-Review (작성자 체크 결과)
- Spec coverage: §3·4(prepend/포맷/빈값가드/contextual skip)=Task1; §4.1 조회순서 정정=Task2; §4.3 불변경계=Task2 Step3; §5 재임베딩·§7 검증=Rollout; §8 테스트=Task1 단위. 누락 없음.
- Placeholder: 없음(모든 step에 실제 코드/명령).
- Type consistency: `_embedding_text_with_context(block, document_title)` 시그니처가 Task1 정의=Task2 호출 일치. `_clean_doc_title` 동일.

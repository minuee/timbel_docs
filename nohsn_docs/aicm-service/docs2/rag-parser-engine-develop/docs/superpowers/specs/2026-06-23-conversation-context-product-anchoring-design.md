# 대화-컨텍스트 상품 앵커링 (resolve-then-scope) 설계

> 작성 2026-06-23. 콜봇/어드바이저 멀티턴 검색에서, 현재 발화에 상품명이 없어도
> 대화 이력의 상품을 해석(resolve)해 검색 범위를 그 상품으로 좁혀(scope) 정답이
> top_k 안에 들어오게 한다.

## 1. 문제

한 저장소에 유사 구조의 다상품 문서(예: 펀드 간이투자설명서 N종)가 공존한다.

- **현재 발화에 상품명이 있으면**(예: "하나코리아 펀드 환매 수수료") — reranker가
  document_title을 보고 변별 → 정답 top (2026-06-23 reranker fix, 커밋 2109512).
- **현재 발화에 상품명이 없으면**(예: "잠깐 환매하면 수수료 있어요?") — 3개 펀드의
  유사 "환매수수료" 블록이 경쟁하고, 빈 헤딩(`### 9. 환매수수료`)·기준시점표·종류형
  설명이 top_k=5를 잠식해 **정답 수수료율표가 top_k 밖으로 밀림** → 콜봇 "정보 없음".

상품 단서는 **대화 이력 텍스트에만** 있다(콜봇/IVR/세션 메타데이터엔 없음 — 운영 확인).
기존 8:2 context-weighting은 **dense 벡터에만, 0.2 가중**으로 결합하고 sparse·keyword
(지배 채널, RRF 0.5)는 현재 발화만 쓰므로(어휘 오염 차단 설계), 실측상 이력의 상품명이
순위를 **전혀 바꾸지 못한다**(이력에 "하나코리아" 넣고/빼고 결과 바이트 동일).

top_k는 콜봇 고정(증설 불가). 따라서 **정답 블록이 top_k 안에 retrieval 되도록**
이력의 상품을 검색 *전*에 반영해야 한다.

## 2. 목표

- 대화 이력(+현재 발화)의 USER 발화에서 **언급된 상품 문서를 결정적(LLM 없이)으로
  해석**하고, 검색을 그 문서(들)로 **스코핑**해 정답 블록을 top_k 안으로 올린다.
- **무하드코딩**: 상품 어휘 = 저장소 문서 제목(데이터 유래). 키워드/펀드 리스트 없음.
- **무회귀 안전**: 상품 해석 실패/모호 시 **현재 동작 그대로**(앵커 없음 → 스코프 없음).
- **스케일**: 문서 2~3만개에서도 동작(해석=ES 제목 검색, 스코프=payload 필터).

## 3. 비목표 (out of scope)

- LLM 기반 엔티티 추출/의도 분류(latency·비결정·콜봇 부적합). 결정적 매칭만.
- 다중질문 분해(별도 thread). 세그멘테이션/블록 병합(별도). API 스키마 변경(불요).
- 콜봇/세션 메타데이터 기반 상품 전달(현재 그 경로 없음 — 이력만).

## 4. 아키텍처 — resolve-then-scope

```
요청(query + conversation_history)            ← 콜봇 페이로드 (변경 없음)
        │
        ▼
[RESOLVE]  user 발화(현재+최근 이력) → ES document_title BM25 매칭
        │     → 앵커 document_id 집합 + 신뢰도 (임계 미달/모호 → 앵커 없음)
        ▼
[SCOPE]   앵커 있으면 3개 searcher(dense/sparse/keyword)에 document_ids 필터 주입
        │     → 앵커 문서 블록만 retrieval → fusion → rerank
        │   앵커 없으면 필터 미주입(현재 동작)
        ▼
   (안전망) 스코프 결과가 너무 적으면 unscoped 재시도(폴백)
```

핵심: 후보군 자체를 앵커 상품으로 좁히므로, 30만 문서에서도 정답 블록이 후보에 든다
(후처리 부스트는 대규모에서 정답이 후보에 못 들어 실패 — 그래서 retrieval 단계 스코프).

## 4.5 Phase 1 (선행): section_title surface + heading_path backfill

테스터 재현으로 드러난 별개·선행 결함: **검색된 표 블록이 자기 섹션 제목을 안 들고 온다.**
실측(timbel) — fee table 블록: `section_title=''`, `section_path=[]` 인데
`source_location.heading_path=['9. 환매수수료']` 는 있음. 즉 **결과 빌더가 heading_path
를 제목으로 surface 하지 않는 코드 갭.** 헤딩은 별도 빈 블록(`### 9. 환매수수료`, 숫자 0)
으로 분리돼, 콜봇은 *제목만(빈헤딩)* 또는 *숫자만(제목없는 표)* 을 받아 "없습니다" 로 답한다.

**Phase 1-A (surface, 경량·재임베딩 불요)** — `service.py:_to_result_items` (line 1565):
```python
section_title=hit.section_title or _section_title_from_heading_path(hit.source_location),
```
`_section_title_from_heading_path`: heading_path 가 있으면 `" > ".join(heading_path)`(또는
최심 요소), 없으면 "". **QNA 의 section_title(=질문)은 비어있지 않으므로 보존**(or 단락 우선).
→ 표 블록이 "9. 환매수수료" 제목을 갖고 반환 → 콜봇이 표를 인식. 빈 헤딩 블록 의존 제거.

**Phase 1-B (데이터)** — heading_path 가 채워져 있어야 함:
- 신규 업로드: heading_propagator(커밋 7fafedd, 워커 배포됨)로 자동.
- **기존 AWS 문서**: heading_path 가 비어있음 → backfill(timbel be0ddf95 에 적용했던 방식 —
  블록 로드 → propagate_heading_paths → `source_location.heading_path` DB 업데이트, 재임베딩
  불요). 워크스페이스 단위 일괄 스크립트.

**(선택) Phase 1-C** — content-empty 헤딩 블록(`### 9. …` 본문 0)을 검색에서 제외
(is_noise/search_excluded 또는 결과 필터). 표가 제목을 갖추면 빈 헤딩은 redundant.

## 5. RESOLVE 상세

### 5.1 입력 텍스트 구성 (USER턴 + recency)
`context_weighting.py`에 신규 함수:

```python
def build_anchor_query_text(
    current_query: str,
    conversation_history: list[dict] | None,
    max_user_turns: int = 3,
) -> str:
    """앵커 해석용 텍스트 — 현재 발화 + 최근 USER 발화만(assistant 제외).

    - role == 'user' 메시지만 사용(봇 인사말/메뉴 안내 노이즈 차단).
    - 최근 max_user_turns개 USER 발화 + 현재 발화를 결합(최근=현재발화 포함).
    - assistant/그 외 role 은 제외.
    """
```
- **assistant 턴 제외** 이유: 봇이 인사·메뉴에서 여러 상품명을 나열("하나코리아·한투·미래에셋
  중...")하면 전 상품이 매칭돼 변별 불가. 고객(USER)이 말한 상품만 신뢰.
- **recency**: 최근 USER 발화 우선(과거 다른 상품 문의 잔향 약화). 현재 발화 포함.

### 5.2 제목 카탈로그 매칭 (ES BM25, IDF=자동 DF필터)
`es_keyword.py`에 신규 메서드:

```python
async def resolve_documents_by_title(
    text: str, index_name: str, repository_ids: list[str] | None,
    tenant_id: str | None, top_n: int = 5,
) -> list[tuple[str, float]]:
    """text 를 블록 인덱스의 document_title 필드에 match → document_id 별 최고
    스코어 집계 → [(document_id, score)] 내림차순. tenant/repo 필터 동일 적용."""
```
- ES `match`(document_title, text) + `collapse`/aggregation by `document_id`.
- **IDF가 곧 DF필터**: "증권자투자신탁/주식/간이투자설명서"는 모든 제목에 흔해 IDF↓(무시),
  "하나코리아/미래에셋차세대"는 희소해 IDF↑(부각). 별도 토큰 선별 로직 불필요.
- 한국어 형태소 분석 불필요(부분 매칭 + ES korean analyzer로 충분, 공백 정규화 보조).

### 5.3 앵커 판정 (임계 + 모호성)
```python
def select_anchors(ranked: list[tuple[str,float]],
                   abs_min: float, rel_ratio: float) -> list[str]:
    # 1) score >= abs_min 인 문서만 후보.
    # 2) top1 점수 대비 rel_ratio 이상인 동률군은 모두 앵커(복수 상품 비교질의 대응).
    # 3) 후보 0개면 [] (앵커 없음 → 스코프 없음).
```
- `abs_min`/`rel_ratio` 는 settings 노출(튜닝 가능, 하드코딩 상수 아님). 초기값은
  스테이징 실측으로 캘리브레이션(예: abs_min 은 "브랜드 1개 매칭" 수준).
- 단일 강매칭 → 단일 앵커. 복수 근접 → 다중 앵커(둘 다 스코프). 약하면 → 앵커 없음.

## 6. SCOPE 상세

### 6.1 searcher 에 document_ids 필터 추가
qdrant_dense / qdrant_sparse / es_keyword 의 `search(...)` 에 `document_ids: list[str] | None`
추가. payload 에 `document_id` 가 이미 있으므로 기존 repository_ids 필터와 동형:

```python
# qdrant (dense/sparse)
if document_ids:
    conditions.append(FieldCondition(key="document_id", match=MatchAny(any=document_ids)))
# es_keyword
if document_ids:
    filter_clauses.append({"terms": {"document_id": document_ids}})
```

### 6.2 service.py 에서 resolve → scope 연결
`SearchService.search`(또는 `_execute_with_split`) 에서 dense/sparse/keyword task 생성 전:

```python
anchor_doc_ids: list[str] = []
if request.conversation_history:  # 콜봇/멀티턴 경로 한정
    anchor_text = build_anchor_query_text(request.query, request.conversation_history)
    ranked = await self._keyword_searcher.resolve_documents_by_title(
        anchor_text, es_index_name, repo_ids_str, _tenant_id_str)
    anchor_doc_ids = select_anchors(ranked, settings.ANCHOR_ABS_MIN, settings.ANCHOR_REL_RATIO)
    if anchor_doc_ids:
        log.info("context_anchor_resolved", doc_ids=anchor_doc_ids, ...)
```
이후 3개 task 에 `document_ids=anchor_doc_ids or None` 전달.

- **현재 발화에 상품명이 있는 경우**(케이스2)도 resolve 가 같은 문서를 앵커 → 스코프가
  reranker 와 같은 방향(무해, 오히려 강건). 즉 케이스1·2 통합.

### 6.3 폴백 (안전망)
스코프 retrieval 결과가 비정상적으로 적으면(예: fusion 후 후보 < `ANCHOR_FALLBACK_MIN`)
**unscoped 로 1회 재시도**. 오앵커(잘못된 문서로 좁힘)로 인한 "결과 없음"을 방지.
- 8:2 dense context-weighting 은 **유지**(상호 보완). resolve 는 그 위에 retrieval 스코프를 더함.

## 7. 무회귀 / 안전

- conversation_history 없는 요청(웹 단발 등): resolve 미수행 → 완전히 현재 동작.
- 앵커 미해석/모호: 스코프 없음 → 현재 동작.
- 오앵커: 폴백 재시도로 빈 결과 방지.
- 스코프는 **tenant/repo 필터와 AND** — cross-tenant 누수 위험 0(기존 격리 그대로).

## 8. 스케일 (2~3만 문서)

- resolve = ES `document_title` 검색(집계) → 코퍼스 크기 무관 수 ms.
- scope = payload `document_id` 필터 → 후보를 앵커 문서로 한정 → 정답 블록이 반드시 후보.
- **한계(정직)**: 유사명 상품 다수면 단일 문서로 못 좁힘 → 다중 앵커(동률군 스코프).
  대화에 변별 정보 없으면 어떤 방법(LLM 포함)도 단일 확정 불가 → 다중 스코프/폴백.

## 9. 영향 컴포넌트

| 파일 | 변경 |
|---|---|
| `src/search/context_weighting.py` | `build_anchor_query_text`, `select_anchors` 신규 |
| `src/search/hybrid/es_keyword.py` | `resolve_documents_by_title` 신규 + `search` 에 `document_ids` 필터 |
| `src/search/hybrid/qdrant_dense.py` | `search` 에 `document_ids` FieldCondition |
| `src/search/hybrid/qdrant_sparse.py` | `search` 에 `document_ids` FieldCondition |
| `src/search/service.py` | resolve 호출 → 3 task 에 `document_ids` 주입 + 폴백 |
| `src/common/config.py` | `ANCHOR_ABS_MIN`/`ANCHOR_REL_RATIO`/`ANCHOR_FALLBACK_MIN` settings |
| `src/api/schemas/search.py` | (선택) 내부 전용 — API 노출 불요. 콜봇 페이로드 불변 |

## 10. 검증

- **단위**: build_anchor_query_text(assistant 제외·recency), select_anchors(임계/모호),
  resolve_documents_by_title(브랜드 매칭·generic 무시), searcher document_ids 필터.
- **실데이터 E2E (timbel, 3펀드)**:
  - 케이스1: text="환매하면 수수료 있어요?", history=[user "하나코리아 …"] →
    정답 수수료율표가 **top_k=5 안**(현재 밖). history 없으면 변화 없음(무회귀).
  - 케이스2: text="하나코리아 펀드 환매 …" → 그대로 정답 top(스코프 무해 확인).
  - 봇노이즈: assistant 턴에 3상품 나열 → 앵커 안 잡힘(USER턴 한정 확인).
  - 콜드(이력 없음/상품 없음) → 현재 동작 동일.
- **멀티턴 회귀**(CLAUDE.md): 중복요청·부정형·시간slot·참조해소 케이스 점검.

## 11. 리스크

- resolve 1회 ES 호출 추가(~수 ms) — 콜봇 latency 영향 미미. context_weighted 캐시와
  유사하게 앵커 결과도 fingerprint 캐시 가능(후속).
- 임계 캘리브레이션 필요(abs_min/rel_ratio) — 스테이징 실측. 초기 보수적(강매칭만 앵커).
- ES korean analyzer/STT 깨짐 시 매칭 실패 → 폴백(현재 동작), 손해 없음.

## 12. 결정 사항 요약

- 매칭: **결정적 ES 제목 BM25**(IDF=DF필터), LLM 미사용.
- 스코프 적용: **신뢰도 게이트 hard-scope(document_ids 필터) + unscoped 폴백**.
- 입력: **현재 발화 + 최근 USER턴**(assistant 제외, recency).
- 위치: **KMS search service**(conversation_history 가 이미 흐르는 곳).
- API/콜봇 페이로드 **불변**(내부 자동 해석).

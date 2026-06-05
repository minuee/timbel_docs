# Knowledge Panel 2-패널 재설계

> 작성일: 2026-04-20
> 범위: `asst-web` 프론트엔드 Knowledge 패널 UI/데이터 흐름

## 배경

현재 지식저장소 패널은 고객 발화에 대한 assist-stream SSE 결과를 받자마자 `sources` 5건 중 **첫 번째 문서를 자동으로 열어** content를 보여준다. 뒤늦게 도착한 `distilled.selected_refs`가 그 문서를 제외하면 다른 문서로 재선택되지만, 이미 사용자는 관련 없는 문서를 읽고 있었을 수 있다.

또한 현 설계는 여러 고객 발화에서 클릭된 문서를 최대 3개까지 가로 카드로 쌓아 보여주는 구조라 단일 문서에 집중하기 어렵다.

## 목표

- `distilled`의 판단 결과를 기다린 뒤 사용자가 의도적으로 문서를 선택하도록 UX 변경.
- Knowledge 패널을 좌(문서 content) / 우(문서 리스트) **2-패널 구조**로 통일.
- Chat / AISearch / manualSearch 세 모드 모두 동일 레이아웃.

## 레이아웃

```
┌─────────────────── Knowledge Panel ──────────────────┐
│ Header (기존 유지)                                       │
├─────────────────────┬────────────────────────────────┤
│                     │ 참고문서                            │
│  문서 content        │ ┌──────────────────────────────┐ │
│                     │ │ [1] 📄 문서A    ★ (하이라이트)  │ │
│  (혹은 빈 상태 +       │ ├──────────────────────────────┤ │
│   "리스트에서 선택")   │ │ [2] 📄 문서B                  │ │
│                     │ ├──────────────────────────────┤ │
│  ※ AI/Chat 모드면     │ │ [3] 📄 문서C    ★            │ │
│    상단에 LLM 요약     │ ├──────────────────────────────┤ │
│                     │ │ [4] 📄 문서D                  │ │
│                     │ └──────────────────────────────┘ │
└─────────────────────┴────────────────────────────────┘
      (왼쪽 content)            (오른쪽 리스트 패널)
```

좌우 1:1 비율 시작. 기존 카드 확장/축소 토글은 제거.

## 모드별 동작

| 모드 | 오른쪽 리스트 | 하이라이트 | 왼쪽 초기 | LLM 요약 |
|------|--------------|-----------|----------|----------|
| Chat | `sources` 5건 | `distilled.selected_refs` | 빈 상태 (안내문) | 있음 |
| AISearch | `retrieved_docs` | 전체 (모두 참고문서) | 빈 상태 (안내문) | 있음 |
| manualSearch | `retrieved_docs` (탭 그룹) | 없음 | 빈 상태 (안내문) | 없음 |

비하이라이트 문서는 `opacity: 0.6`으로 dim 처리하되 클릭 가능. 사용자가 AI 판단이 틀렸다고 느낄 때 원본 5건 중 다른 걸 확인할 수 있게 한다.

## 상태 관리

### knowledge/index.vue

**제거**
- `allSelectedItems`, `expandedCardIndex`, `gridTemplateColumns`
- `getContentItemsForCard`, `getBlockMapsForCard`, `handleCardToggle`
- `selection-card` 그리드 템플릿 블록 전체

**신규**
```ts
const documentList = ref<Document[]>([])
const highlightedRefs = ref<Set<number>>(new Set())
const selectedDoc = ref<Document | null>(null)
const listMode = ref<'chat' | 'ai' | 'manual' | null>(null)
```

**유지 (재활용)**
- `contentItemsMap`, `currentBlockMaps` — 단일 doc 기준으로 간소화
- `DocumentCard`, `DocumentDetailView`, `DocumentDetailModal`
- 최근 열람 문서 행 (현재 빈 배열)

### Props 추가
```ts
chatDocumentList?: Document[]   // Chat: 전체 sources
chatSelectedRefs?: number[]     // Chat: distilled.selected_refs
```

## 데이터 흐름 변경

### chat/index.vue

**제거**
- `isAutoSearch` 첫 문서 auto-click ([L2159-L2189](asst-web/src/view/advisor/components/chat/index.vue#L2159-L2189))
- `distilled` 수신 시 content 필터링 + 재선택 로직 ([L2257-L2298](asst-web/src/view/advisor/components/chat/index.vue#L2257-L2298))

**유지**
- 버블 아래 detail item 칩 표시 (distilled 필터링 동작 그대로)
- 칩 클릭 시 `detailItemClick` emit

**신규**
- `sources` 수신 시 `emit("updateChatDocumentList", { messageId, list })`
- `distilled` 수신 시 `emit("updateChatSelectedRefs", { messageId, refs })`

### agent/index.vue

- `handleDetailItemClick`의 다중 doc 중복 체크/focusExistingTab 경로 제거 → 단순 "단일 선택 교체".
- `handleAddKnowledgeDocuments`는 다중 탭 전제 → 단일 doc 선택으로 변경하거나 제거.
- 신규 prop으로 `chatDocumentList` / `chatSelectedRefs`를 Knowledge 컴포넌트에 전달.

### AISearch / manualSearch (knowledge/index.vue 내부)

- 기존 `KnowledgeAPI.instance.retrieveDoc` 호출 결과를 동일한 `documentList` state에 주입.
- AISearch: 리스트 모두 하이라이트. LLM 요약은 `aiSearchResultText`(assistStreamText) 그대로 구독.
- manualSearch: 하이라이트 없음. 탭 그룹은 리스트 상단 필터로 유지.

## 렌더링

### 왼쪽 content 패널
- `selectedDoc === null` → 중앙 안내문
- Chat/AI 모드 & `aiSearchResultText`/`assistStreamSummary` 있음 → 상단에 LLM 요약 박스 (`search-results-ai-result` 스타일 재사용)
- 하단에 `DocumentDetailView` (기존 컴포넌트)

### 오른쪽 리스트 패널
- `DocumentCard` 세로 나열
- `ref_num ∈ highlightedRefs` → 테두리 강조 + "참고" 라벨/★ 뱃지
- 비하이라이트 → `opacity: 0.6`, 클릭 가능
- 선택된 문서 → 리스트 아이템 배경 하이라이트
- manualSearch → 리스트 상단에 `ECPTabs`로 doc_type 필터

## 호환성

- `TabTypeKnowledgeIndex.vue`는 이 변경 범위에 포함하지 않음 (별도 라우트/용도 확인 필요).
- `assist-snapshot.api.spec.ts` payload 형태 불변 — 기존 테스트 통과해야 함.
- SSE 이벤트 핸들러 (`intent`/`sources`/`distilled`/`token`/`done`) API 형태 불변.

## 테스트

- knowledge/index.vue Vitest 유닛: 리스트 렌더, 하이라이트 분기, 클릭 시 `selectedDoc` 교체.
- chat/index.vue: auto-click 제거 후 `sources`/`distilled` 수신만으로 Knowledge 패널이 올바르게 채워지는지 확인.
- E2E 수동 확인: Chat → AISearch → manualSearch 경로 전환 시 레이아웃 일관.

## 리스크

- `handleDetailItemClick`의 content 가공 분기(outline / 직접 content / keyword 배열 / 기본 fallback) 4가지가 단일 doc 선택 경로에서 모두 동작해야 함.
- `selection-card` 제거로 이미 열려있던 다중 선택 UX가 사라짐 — 사용자 교육 필요.
- manualSearch의 탭 구조를 리스트 상단 필터로 바꿀 때 기존 `activeTab` 관련 computed 재작성 필요.

## 단계별 커밋 전략

1. Knowledge 패널 레이아웃을 좌/우 2-패널로 교체 (모드별 분기 포함, 동작은 기존 흐름 최대한 보존)
2. Chat 경로 데이터 흐름 연결 (`sources`/`distilled` → `documentList`/`highlightedRefs`)
3. chat/index.vue의 auto-click 및 distilled 필터 후 재선택 로직 제거
4. agent/index.vue 다중 선택 로직 정리, 테스트 추가

# ADR-004: 검색 API 응답에 컨텍스트 스니펫(인접 블록) 포함

- **상태**: 승인됨
- **날짜**: 2026-03-24
- **의사결정자**: 개발팀
- **관련 문서**: [03-search.md](../01-requirements/flows/search-rag/03-search.md), [00-overview.md](../02-architecture/data/README.md), [02-chunking.md](../01-requirements/flows/search-rag/02-chunking.md), [01-system-overview.md](../02-architecture/01-system-overview.md)

---

## 1. 컨텍스트

### 1.1 기존 설계: 인접 블록은 LLM 전용

Window Context(인접 블록 확장)는 검색으로 히트된 블록의 전후 블록(sequence ± window_size)을 함께 가져오는 메커니즘이다. 기존 설계에서 이 인접 블록은 **LLM 컨텍스트 구성 전용**이며, 사용자에게는 표시하지 않았다.

| 대상 | 사용자 노출 (기존) | LLM 컨텍스트 |
|------|:---:|:---:|
| 히트 블록 | O — 출처 표시, 하이라이트 | 포함 |
| 인접 블록 | **X — 표시하지 않음** | 보충 문맥으로 포함 |

### 1.2 짧은 블록의 맥락 부족 문제

블록 에디터 기반 문서에서 블록은 자유롭게 분리된다. "준비물을 지참하세요."처럼 한 문장짜리 블록이 검색에 히트되면, 이 블록만으로는 **무슨 맥락인지 파악할 수 없다**.

```
검색 결과 (기존):
  📄 계좌 개설 매뉴얼
     "준비물을 지참하세요."          ← 뭔 준비물? 무슨 절차?
```

이 문제는 AICM 검색 API를 소비하는 **모든 클라이언트**에서 동일하게 발생한다.

### 1.3 영향 범위: 모든 API 소비자

AICM의 검색 API(`aicm-service`)를 호출하는 클라이언트는 다음과 같다.

| 클라이언트 | 연동 방식 | 사용 시나리오 |
|-----------|----------|-------------|
| **aicm-web** | HTTP REST / WebSocket | 문서 검색 결과 리스트, RAG 출처 표시 |
| **AICC 모듈 (상담어드바이져)** | HTTP REST | 통화 중 지식 검색 — 즉시 맥락 파악 필요 |
| **AICC 모듈 (에이전트빌더)** | HTTP REST | 자동 응답 시나리오에서 검색 결과 활용 |
| **향후 외부 클라이언트** | HTTP REST | AICM 검색 API를 호출하는 모든 신규 서비스 |

특정 클라이언트를 위한 대응이 아니라, **검색 API 응답 자체를 개선**하면 모든 소비자가 동일하게 혜택을 받는다.

---

## 2. 결정

### 2.1 Window Context를 API 응답에도 포함

검색 API 응답에 히트 블록뿐 아니라 **인접 블록(Window Context)도 함께 반환**한다. 기존에 LLM 컨텍스트 구성에만 사용하던 인접 블록 확장 로직을 API 응답 조립에도 적용한다.

### 2.2 히트/인접 블록 구분 마커

각 블록에 `is_hit` 플래그를 부여하여 **검색 근거(히트)와 배경 문맥(인접)을 명확히 구분**한다. 인접 블록을 출처(source)로 표시하지 않는 기존 원칙은 유지한다.

| 구분 | `is_hit` | UI 표시 | 의미 |
|------|:---:|------|------|
| 히트 블록 | `true` | 하이라이트 (강조 배경) | 검색 근거 — 출처로 표시 |
| 인접 블록 | `false` | 연한 배경 (배경 문맥) | 가독성 보충 — 출처로 표시하지 않음 |

### 2.3 섹션 헤딩 breadcrumb

Contextual Chunking에서 이미 관리하는 **섹션 헤딩 정보**(`section_title`)를 스니펫 상단에 breadcrumb으로 표시한다. 짧은 블록이라도 "이 블록이 문서의 어느 섹션에 속하는지"를 즉시 파악할 수 있다.

```
검색 결과 (개선 후):
  📄 계좌 개설 매뉴얼 > 계좌 개설 절차      ← 섹션 breadcrumb
  ┌──────────────────────────────────
  │ 영업점 방문 시 아래 서류가 필요합니다.    ← 인접 블록 (is_hit=false, 연한 배경)
  │ **준비물을 지참하세요.**                  ← 히트 블록 (is_hit=true, 하이라이트)
  │ 신분증, 도장, 통장 사본을 준비하세요.     ← 인접 블록 (is_hit=false, 연한 배경)
  └──────────────────────────────────
```

### 2.4 API 응답 구조

```typescript
interface SearchResultBlock {
  block_id: string;
  sequence: number;
  content_text: string;
  block_type: string;
  is_hit: boolean;
}

interface SearchResultItem {
  document_id: string;
  document_title: string;
  board_id: string;
  section_title?: string;
  score: number;
  context_blocks: SearchResultBlock[];
  document_url: string;
}
```

### 2.5 접근 제한 필터링

인접 블록이 속한 문서에 DocumentRestriction이 설정되어 있고 현재 사용자에게 권한이 없으면, 해당 문서의 블록은 **컨텍스트 스니펫에서도 제외**한다. 블록 단위 접근 제한(BlockRestriction)은 ADR-012에서 제거되었다.

---

## 3. 근거

### 3.1 Block:Chunk = 1:N 불변 원칙과 양립

청킹 전략의 불변 원칙은 **저장·임베딩은 Block:Chunk = 1:N, 검색 결과 반환은 N:M**으로 명확히 분리되어 있다. 컨텍스트 스니펫은 검색 결과 반환(N:M) 레이어에서의 변경이므로, 저장/임베딩 구조에 영향이 없다.

| 레이어 | 원칙 | 영향 |
|--------|------|:---:|
| 저장·임베딩 | Block:Chunk = 1:N (불변) | 변경 없음 |
| 검색 결과 반환 | N:M 자유 조합 (이미 허용) | 여기서 확장 |

### 3.2 인프라 추가 불필요

컨텍스트 스니펫 구성에 필요한 모든 인프라가 이미 존재한다.

| 필요 기능 | 현재 상태 |
|----------|----------|
| `BlockSnapshot.sequence`로 인접 블록 조회 | 이미 구현 (LLM 컨텍스트용) |
| Window Context 확장 로직 (sequence ± N) | 이미 구현 |
| DocumentRestriction 권한 필터 | 이미 적용 중 (BlockRestriction은 ADR-012에서 제거됨) |
| 섹션 헤딩 정보 (`section_title`) | Contextual Chunking에서 이미 관리 |

### 3.3 검색 API 레벨 개선의 이점

| 방식 | 채택 여부 | 사유 |
|------|----------|------|
| **API 응답에 `context_blocks` 포함** | **채택** | 모든 소비자가 별도 구현 없이 혜택. API 계약 한 번 변경으로 전체 커버 |
| 각 클라이언트가 개별 구현 | 기각 | 클라이언트마다 인접 블록 조회 로직 중복. 블록 권한 필터링도 각자 처리해야 함 |
| 히트 블록 텍스트만 확장 (앞뒤 잘라 붙이기) | 기각 | 블록 경계가 무시되어 출처 추적 불가. `is_hit` 구분 불가능 |

### 3.4 출처 표시 원칙 유지

인접 블록은 **검색 근거가 아니라 배경 문맥**이다. `is_hit` 마커로 구분하여 출처 표시 원칙을 유지한다. 사용자가 "이 블록이 검색 근거다"라고 오인하지 않도록, UI에서 히트 블록과 인접 블록의 시각적 구분을 강제한다.

---

## 4. 영향

### 4.1 문서 갱신

| 문서 | 변경 내용 |
|------|----------|
| [03-search.md](../01-requirements/flows/search-rag/03-search.md) | 7.3절 테이블 갱신 (컨텍스트 스니펫 노출 컬럼 추가), 7.6절 컨텍스트 스니펫 전략 신규 추가 |
| [00-overview.md](../02-architecture/data/README.md) | 3절 "사용자에게 보여주는 단위" 테이블에서 인접 블록 행 갱신, 출처 표시 흐름 예시 갱신 |

### 4.2 코드 영향

| 영역 | 영향 |
|------|------|
| 검색 API 응답 DTO | `context_blocks[]` 필드 추가, `SearchResultBlock` 타입 정의 |
| `RagSearchService` | 기존 LLM 컨텍스트용 인접 블록 조회 로직을 API 응답 조립에도 재사용 |
| 문서 검색 서비스 | ES `inner_hits`의 히트 블록에 대해 인접 블록 조회 후 `context_blocks`로 조립 |
| aicm-web 검색 UI | `context_blocks`의 `is_hit` 플래그에 따라 하이라이트/연한 배경 분기 렌더링 |
| AICC 모듈 연동 | API 응답 구조 변경에 따른 클라이언트 업데이트 (하위 호환 — 기존 필드 유지) |

---

## 5. 컨텍스트 스니펫 구성 예시

```
문서: "계좌 개설 매뉴얼" (5개 블록)
  [1] heading2: "계좌 개설 절차"
  [2] paragraph: "영업점 방문 시 아래 서류가 필요합니다."
  [3] paragraph: "준비물을 지참하세요."          ← ★ 검색 히트
  [4] paragraph: "신분증, 도장, 통장 사본을 준비하세요."
  [5] paragraph: "창구에서 신청서를 작성합니다."

→ 컨텍스트 스니펫 (window_size=1):
  section_title: "계좌 개설 절차"
  context_blocks:
    { block_id=[2], seq=2, text="영업점 방문 시...",  is_hit=false }
    { block_id=[3], seq=3, text="준비물을 지참하세요.", is_hit=true  }
    { block_id=[4], seq=4, text="신분증, 도장, 통장...", is_hit=false }
```

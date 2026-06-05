# AI 어시스턴트 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-AI |
| 버전 | 1.2 |
| 작성일 | 2026-03-31 |
| 기준 문서 | AICM 새 기능정의서 v1 §8 |

> **UC 정합 방침**: UC-AI-AI어시스턴트.md와 본 FD 간 기술적 세부(수동 요약 저장 정책, AI 수정 추적 여부 등)가 상이할 경우, **M2/M3 단계의 설계 결정에 따라 본 FD(기능정의서)의 기술 규칙이 최종 기준**이다. UC는 사용자 시나리오 관점의 서술로 별도 정합 작업이 진행된다.

---

## 1. 문서 요약

### 1.1 개요

문서 본문을 LLM에 전달하여 다양한 형태의 요약을 생성하는 기능이다. 긴 운영 문서의 빠른 파악, 검색 미리보기, RAG 컨텍스트 강화에 활용한다.

### 1.2 자동 요약 (Published 시점)

- 문서가 `published` 상태로 전환될 때 백그라운드로 요약 자동 생성 → Document 엔티티의 `auto_summary` 필드에 저장 [BR-AI-001]
- **별도 Bull(Redis) 큐(`ai-summary`)**에서 비동기 처리 — 임베딩 큐(`embedding`)와 분리 운영하여 상호 간 지연 영향 차단
- **요약 실패해도 문서 게시는 막지 않음** — 요약은 있으면 좋은 부가 정보이지 필수가 아님, 실패 시 검색 결과에서 제목으로만 표시 [BR-AI-002]
- 활용처: 검색 결과 미리보기 카드, 문서 목록 썸네일, RAG 답변의 문서 요약 컨텍스트
- 문서 수정 후 재배포 시 요약도 재생성 — `content_hash` 비교로 내용 변경이 없으면 재생성 스킵 (문서 단위 해시) [BR-AI-003]
- 재시도 정책: 실패 시 지수 백오프로 최대 3회 재시도, 최종 실패 시 `summary_status = failed`로 마킹 + 관리자 알림

### 1.3 수동 요약 (온디맨드)

- 문서 열람 페이지에서 "AI 요약" 버튼 클릭 → 실시간 스트리밍으로 요약 생성
- 요약 타입 선택 가능:
  - **한줄 요약**: 1~2문장으로 핵심 내용 압축 — 문서 목록/카드 표시용
  - **핵심 포인트**: 3~5개 불릿 포인트로 주요 내용 정리
  - **섹션별 요약**: 헤딩 블록([FD-DOC](FD-DOC-문서관리.md) §1.2) 기준으로 섹션 단위 요약 생성
  - **맞춤 요약**: 사용자가 컨텍스트를 지정하여 요약 (예: "신입 상담원 관점에서 요약해줘", "변경된 부분만 요약해줘")
- 생성된 수동 요약은 DB(`AiSummaryCache`)에 저장 — 동일 문서 버전 + 동일 요약 타입 조합이 이미 저장되어 있으면 저장된 결과를 즉시 반환 [BR-AI-004]
- **"재요약" 버튼** 제공 — 사용자가 명시적으로 재생성을 요청하면 LLM을 호출하고 DB의 기존 요약을 최신 결과로 갱신 [BR-AI-005]

### 1.4 요약 저장 전략

- **자동 요약**: Document 엔티티의 `auto_summary` 필드(TEXT)에 저장
- **수동 요약**: `AiSummaryCache` 엔티티에 저장 — 문서 버전 ID + 요약 타입 + (맞춤 요약 시) 사용자 지시를 키로 관리
- **캐시 무효화**: 문서 내용 변경(`content_hash` 변경) 시 해당 문서의 모든 요약(자동 + 수동) 무효화 [BR-AI-006]
  - 자동 요약: `auto_summary` 필드 NULL + `summary_status = pending`으로 전환 → 재생성 큐 등록
  - 수동 요약: `AiSummaryCache`에서 해당 `document_id`의 레코드 전체 삭제

### 1.5 RAG 연동

- 자동 요약 텍스트를 별도 청크로 임베딩 → "OO 문서 요약해줘" 같은 질의에 즉시 대응 [BR-AI-007]
- 요약 청크의 메타데이터에 `chunk_type: 'summary'` 태깅 — 일반 청크와 구분
- 상세: [FD-EMB](FD-EMB-임베딩파이프라인.md)

---

## 2. 단락별 AI 글쓰기 개선

### 2.1 개요

블록 에디터([FD-DOC](FD-DOC-문서관리.md) §1.2) 편집 모드에서 선택한 블록의 텍스트를 LLM으로 개선하는 인라인 AI 어시스턴트이다.

> **AI 수정 추적 미지원**: AI가 수정한 블록에 대한 별도 추적(ai_touched 플래그, AI 수정 이력 등)은 지원하지 않는다. 승인 워크플로의 버전 diff로 변경 사항을 확인하며, 이것으로 충분하다. [BR-AI-008]

### 2.2 트리거 방식

- 블록 선택 → 플로팅 툴바의 **AI 버튼** (✨ 아이콘)
- 텍스트 범위 선택 → 컨텍스트 메뉴에서 "AI로 개선"
- 슬래시 명령 `/ai` → AI 개선 유형 선택 메뉴 표시

### 2.3 개선 유형

- **문장 다듬기**: 어색한 표현 교정, 문법 오류 수정, 자연스러운 문장으로 재작성
- **톤 변경**: 격식체 ↔ 비격식체, 고객 응대용 ↔ 내부 보고용, 간결체 ↔ 설명체
- **간결하게**: 군더더기 제거, 핵심만 남김, 문장 수 축소
- **상세하게**: 부족한 설명 보충, 예시 추가, 맥락 확장
- **번역**: 한국어 ↔ 영어 (금융권 글로벌 고객사 대응) — 언어 쌍 추가 시 프롬프트 슬롯(`writing_translate_{lang_pair}`) 확장으로 대응하며, UI 언어 목록은 활성 슬롯 기반으로 동적 생성
- **자유 지시**: 사용자가 직접 개선 방향을 입력 (예: "초등학생도 이해할 수 있게 바꿔줘")

### 2.4 결과 표시 및 적용

- **단일/다중 블록 개선**: 원본과 개선안을 **인라인 diff 형태**로 편집 위치에서 바로 표시 — 변경된 부분 하이라이트, 편집 맥락 유지 [BR-AI-009]
- **전체 문서 개선**: **사이드바 비교** 형태로 원본/개선안을 좌우 나란히 표시 — 전체 변경사항 한눈에 비교 [BR-AI-009]
- 금융권 문서는 한 글자가 법적 의미를 바꿀 수 있으므로 AI가 변경한 부분을 명확히 시각화
- 액션 버튼: **"적용"** (개선안으로 교체) / **"원본 유지"** (변경 취소) / **"재생성"** (다른 결과 요청)
- 적용 시 Undo 지원 — `Ctrl+Z`로 원본 복구 가능 [BR-AI-011]

### 2.5 적용 범위

- **단일 블록**: 하나의 블록 선택 후 개선
- **다중 블록**: 여러 블록 선택 후 일괄 개선
- **전체 문서**: "전체 문서 다듬기" 옵션 — 섹션별로 순차 처리, 각 섹션마다 적용 여부 선택 [BR-AI-010]

---

## 3. 프롬프트 관리

### 3.1 개요

AI 어시스턴트 기능(§1, §2)에 사용되는 프롬프트는 **AICM이 직접 관리**한다. 프롬프트 저장, 버전 관리, 테스트를 AICM 내부에서 처리하며, 관리/수정은 **`manage_prompts` AdminPermission** 보유자만 수행한다. [BR-AI-012]

> **LLM 호출 방식**: AICM은 LLM을 직접 호출하지 않고, 반드시 **LLM Orchestrator**를 경유하여 호출한다. LLM Orchestrator는 모델 라우팅과 호출을 담당하는 공통 인프라이며, 프롬프트·슬롯·버전 등 AI 기능의 비즈니스 로직은 AICM이 소유한다.

### 3.2 프롬프트 관리 원칙

AICM은 프롬프트를 단일 관리 대상으로 운영하며, 기능별 슬롯 단위로 관리한다. [BR-AI-013]

- **관리 주체 제한**: 프롬프트 조회/편집/테스트/저장은 **`manage_prompts` AdminPermission** 보유자만 가능
- **기능별 독립 관리**: 요약, 글쓰기 개선, RAG 답변 등 기능별로 슬롯을 분리해 운영
- **즉시 반영**: 저장된 프롬프트는 해당 기능 호출 시 즉시 적용 [BR-AI-014]

### 3.3 기능별 프롬프트 슬롯

각 AI 기능마다 독립된 프롬프트 슬롯을 관리한다:

| 슬롯 키 | 기능 |
|---------|------|
| `doc_summary_oneline` | 한줄 요약 |
| `doc_summary_keypoints` | 핵심 포인트 요약 |
| `doc_summary_section` | 섹션별 요약 |
| `doc_summary_custom` | 맞춤 요약 |
| `writing_polish` | 문장 다듬기 |
| `writing_tone_formal` | 격식체 변환 |
| `writing_tone_casual` | 비격식체 변환 |
| `writing_concise` | 간결하게 |
| `writing_elaborate` | 상세하게 |
| `writing_translate` | 번역 |
| `writing_freeform` | 자유 지시 |
| `tag_recommend` | 태그 추천 (§6) |

기능 추가 시 프롬프트 슬롯도 확장 가능하다. 슬롯은 `PromptSlot` 엔티티(§8)로 DB에 저장되므로 코드 변경 없이 런타임에 추가할 수 있다.

### 3.4 머지 전략

- 기능별 슬롯마다 단일 프롬프트 본문을 관리한다.
- 저장 시 최신 프롬프트 버전이 즉시 활성화된다.
- 호출 시에는 선택된 슬롯의 최신 활성 버전을 사용한다.

### 3.5 프롬프트 테스트 (미리보기)

- `manage_prompts` 보유자가 프롬프트 수정 후 **샘플 문서/텍스트로 즉시 테스트** 가능 [BR-AI-015]
- 테스트 결과를 확인한 후 저장/적용 — 프롬프트 변경이 운영에 바로 영향을 주지 않도록 방어
- 관리자 테스트: 여러 샘플 문서에 대해 일괄 테스트 → 결과 비교 (A/B 테스트 형태)

### 3.6 프롬프트 버전 관리

- 프롬프트 수정 이력 전체 추적 — 누가 언제 어떤 프롬프트를 어떻게 변경했는지 [BR-AI-016]
- 이전 버전으로 롤백 가능 — 롤백 시 해당 버전을 새 버전으로 복제하여 active 전환 (상태 모델은 §9 참조)
- 슬롯별 변경 이력 기준으로 영향 범위를 확인할 수 있음

---

## 4. AI 어시스턴트 사용 이력 및 통계

### 4.1 사용 이력 로깅

- 모든 AI 기능 호출 이력을 기록: 기능 유형, 입력 텍스트(마스킹 처리), 출력 결과, 사용 모델, 토큰 수, 응답 시간 [BR-AI-017]
- 사용자별/문서별/기능별 AI 사용 이력 조회 가능 (관리자)
- 멀티 테넌트 환경에서 테넌트 간 데이터 격리 보장 [BR-AI-019]
- **감사 로그 비동기 수집**: AI 사용 이력은 이벤트(`ai.usage.logged`)를 통해 비동기로 **LogEventModule**에 전달 — 동기 쓰기로 인한 AI 응답 지연 방지 [BR-AI-018]

### 4.2 사용자 피드백

- AI 결과에 대해 👍/👎 피드백 수집
- 부정확 피드백은 사유(잘못된 수치/존재하지 않는 내용/맥락 오류/기타)와 함께 저장

### 4.3 관리자 통계 대시보드

- AI 기능별 사용 빈도, 적용률(생성 후 실제 적용한 비율), 피드백 분포
- 테넌트별 토큰 사용량/비용 집계, 월간 추이
- 프롬프트 버전별 성과 비교 (적용률, 피드백 점수)

---

## 5. Hallucination 탐지 및 완화

### 5.1 개요

- RAG 기반 답변에서 LLM이 제공된 컨텍스트 청크에 근거하지 않는 내용을 생성(hallucination)하는 것을 탐지하고 사용자에게 경고
- 금융 상담 시나리오에서 잘못된 수수료율, 금리, 규정을 안내하면 컴플라이언스 이슈가 되므로, 출처 근거 검증이 필수

### 5.2 출처 검증 (Grounding Check)

- RAG 답변 생성 시 답변의 각 문장/구절에 대해 **근거 청크 ID를 매핑**하여 반환 [BR-AI-020]
- 응답 구조에 `grounding_info` 필드 추가:

```typescript
interface RagAnswerResponse {
  answer: string;
  grounding: GroundingInfo[];
  confidence_score: number;    // 0.0 ~ 1.0
  disclaimer: string;          // 면책 문구
}

interface GroundingInfo {
  sentence_index: number;      // 답변 내 문장 순서
  source_chunk_ids: string[];  // 근거 청크 ID 목록 (빈 배열 = 근거 없음)
  grounded: boolean;           // 근거 여부
}
```

- `grounded = false`인 문장은 UI에서 시각적으로 구분 (회색 처리 또는 ⚠️ 경고 아이콘) [BR-AI-021]
- 사용자가 해당 문장에 호버하면 "이 내용은 확인된 출처가 없습니다. 원문을 직접 확인해 주세요." 툴팁 표시

### 5.3 신뢰도 점수 (Confidence Score)

- 답변 전체에 대한 **근거 충분도 점수**(0.0~1.0)를 산출
- 산출 기준: 근거 있는 문장 비율, 컨텍스트 청크와의 의미적 유사도
- 임계값 기반 경고 [BR-AI-022]:

| 점수 구간 | 상태 | UI 표시 |
|-----------|------|---------|
| 0.8 이상 | 높음 | 기본 표시 (경고 없음) |
| 0.5 ~ 0.8 | 보통 | 노란색 경고 배너: "일부 내용의 출처가 불확실합니다" |
| 0.5 미만 | 낮음 | 빨간색 경고 배너: "답변의 정확성이 낮습니다. 원문을 직접 확인해 주세요" |

- 임계값은 관리자가 SystemConfig에서 조정 가능 (`pm:ai.confidence_threshold_high`, `pm:ai.confidence_threshold_low`)

### 5.4 면책 문구 및 사용자 피드백

- 모든 RAG 답변에 **면책 문구** 기본 포함: "이 답변은 AI가 생성한 것이며, 정확성을 보장하지 않습니다. 중요한 정보는 원문을 직접 확인해 주세요." [BR-AI-023]
- 면책 문구는 테넌트별 커스터마이징 가능
- **사용자 피드백 수집**: 답변 하단에 "정확함 / 부정확함" 버튼 제공
  - "부정확함" 선택 시 선택적 사유 입력 (드롭다운: "잘못된 수치", "존재하지 않는 내용", "맥락 오류", "기타")
  - 피드백 데이터는 관리자 통계에서 조회 가능

---

## 6. AI 태그 추천

### 6.1 개요

문서 본문을 분석하여 기존 태그 풀에서 적합한 태그를 추천하는 기능이다. 자유 입력 태그 방식([FD-DOC](FD-DOC-문서관리.md) §8)의 태그 품질 저하(중복 생성, 미부착) 문제를 완화한다.

핵심 원칙: **새 태그를 만들기보다 기존 태그를 재사용하도록 유도**한다. 태그 풀의 일관성을 유지하면서 사용자의 태그 부착 부담을 줄인다. [BR-AI-024]

### 6.2 추천 방식

- 문서의 제목 + 본문 텍스트를 LLM에 전달하고, 기존 태그 목록을 함께 제공하여 **기존 태그 중 문서에 적합한 것**을 선별하도록 요청
- 추천 결과는 최대 **5개** — 너무 많으면 선택 부담, 너무 적으면 유용성 저하 [BR-AI-025]
- 추천 우선순위: ① 문서 내용과의 의미적 관련성 → ② 현재 게시판 내 사용 빈도 → ③ 전체 사용 빈도
- 문서에 이미 부착된 태그는 추천에서 제외 [BR-AI-026]
- 기존 태그 중 적합한 것이 부족한 경우, **새 태그 후보**를 별도 영역("새 태그 제안")으로 분리하여 제안 — 기존 태그 재사용과 새 태그 생성을 시각적으로 구분

### 6.3 트리거 방식

- **수동 트리거**: 태그 입력 영역의 "AI 태그 추천" 버튼 클릭 [BR-AI-028]
- 본문이 **100자 이상**이어야 동작 — 부족하면 "본문을 좀 더 작성한 후 다시 시도해 주세요" 안내 (기준값은 SystemConfig `pm:ai.tag_recommend_min_length`로 조정 가능) [BR-AI-029]

### 6.4 LLM 입력/출력

**입력**:
- 문서 제목
- 문서 본문 텍스트 (토큰 한도 내에서 전달, 초과 시 앞부분 우선 + 섹션 헤딩 보존)
- 기존 태그 목록 (`{ name, usage_count }[]`) — 게시판 내 빈도 기준 상위 태그 우선 전달
- 문서에 이미 부착된 태그 목록 (제외 대상)

**출력**:
- `existing_tags`: 기존 태그 중 추천 목록 (`{ tag_id, name, reason }[]`)
- `new_tag_suggestions`: 새 태그 제안 목록 (`{ name, reason }[]`) — 기존 태그에 적합한 것이 없을 때만

### 6.5 캐싱 전략

- 동일 문서 버전(`content_hash`) + 동일 태그 풀 상태에서는 추천 결과를 캐싱하여 재호출 방지
- 문서 내용이 변경되거나 태그 풀이 변경(병합/삭제)되면 캐시 무효화

### 6.6 제약 사항

- AI 태그 추천은 **제안일 뿐** — 최종 태그 선택은 사용자가 결정
- 문서당 최대 태그 수(기본 10개) 제한은 그대로 적용 — 이미 10개 부착된 경우 추천 버튼 비활성화 [BR-AI-027]
- 추천 결과에 대한 사용자 피드백(👍/👎)은 §4(사용 이력)와 동일한 방식으로 수집

---

## 7. 비즈니스 규칙 카탈로그

### 7.1 문서 요약 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-001 | 자동 요약은 문서가 published 상태로 전환될 때에만 백그라운드 생성한다 | §1.2 |
| BR-AI-002 | 요약 실패해도 문서 게시를 차단하지 않는다 — 실패 시 검색 결과에서 제목으로만 표시 | §1.2 |
| BR-AI-003 | content_hash(문서 단위 해시) 비교로 내용 변경이 없으면 자동 요약 재생성을 스킵한다 | §1.2 |
| BR-AI-004 | 수동 요약 결과는 DB(AiSummaryCache)에 저장 — 동일 문서 버전 + 동일 요약 타입이면 저장된 결과를 즉시 반환한다 | §1.3 |
| BR-AI-005 | "재요약" 버튼으로 기존 저장 결과를 LLM 재호출 후 갱신한다 | §1.3 |
| BR-AI-006 | 문서 내용 변경(content_hash 변경) 시 해당 문서의 모든 요약(자동 + 수동)을 무효화한다 | §1.4 |
| BR-AI-007 | 자동 요약 텍스트를 별도 청크로 임베딩하며 chunk_type: 'summary'로 태깅한다 | §1.5 |

### 7.2 글쓰기 개선 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-008 | AI 수정 추적 미지원 — 별도 ai_touched 플래그나 수정 이력을 두지 않으며, 승인 워크플로의 버전 diff로 변경을 확인한다 | §2.1 |
| BR-AI-009 | 단일/다중 블록 개선은 인라인 diff, 전체 문서 개선은 사이드바 비교로 표시한다 | §2.4 |
| BR-AI-010 | 전체 문서 개선 시 섹션별 순차 처리하며, 각 섹션마다 적용 여부를 선택한다 | §2.5 |
| BR-AI-011 | AI 개선 적용 후 Undo(Ctrl+Z)로 원본 복구가 가능하다 | §2.4 |

### 7.3 프롬프트 관리 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-012 | 프롬프트 조회/편집/테스트/저장은 `manage_prompts` AdminPermission 보유자만 가능하다 | §3.1 |
| BR-AI-013 | 기능별 슬롯 단위로 독립 관리한다 | §3.2 |
| BR-AI-014 | 슬롯별 최신 활성 버전을 즉시 적용한다 | §3.2 |
| BR-AI-015 | 프롬프트 수정 후 샘플 테스트를 거쳐 저장한다 (운영 방어) | §3.5 |
| BR-AI-016 | 프롬프트 수정 이력을 전체 추적하며, 이전 버전으로 롤백이 가능하다 | §3.6 |

### 7.4 사용 이력 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-017 | 모든 AI 기능 호출 이력을 기록한다 — 입력 텍스트는 마스킹 처리 | §4.1 |
| BR-AI-018 | 감사 로그는 비동기로 수집한다 — 동기 쓰기로 인한 AI 응답 지연 방지 | §4.1 |
| BR-AI-019 | 멀티 테넌트 환경에서 테넌트 간 데이터를 격리한다 | §4.1 |

### 7.5 Hallucination 완화 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-020 | RAG 답변의 각 문장에 근거 청크 ID를 매핑하여 반환한다 | §5.2 |
| BR-AI-021 | grounded=false 문장은 UI에서 시각적으로 구분한다 (회색 또는 ⚠️) | §5.2 |
| BR-AI-022 | 신뢰도 점수 임계값(0.5/0.8) 기반으로 경고를 표시한다 | §5.3 |
| BR-AI-023 | 모든 RAG 답변에 면책 문구를 포함한다 — 테넌트별 커스터마이징 가능 | §5.4 |

### 7.6 태그 추천 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-024 | 기존 태그 재사용을 우선하며, 새 태그 제안은 별도 영역에 분리한다 | §6.1 |
| BR-AI-025 | 추천 결과는 최대 5개이다 | §6.2 |
| BR-AI-026 | 이미 부착된 태그는 추천에서 제외한다 | §6.2 |
| BR-AI-027 | 문서당 최대 태그 수 도달 시 추천 버튼을 비활성화한다 | §6.6 |
| BR-AI-028 | 수동 트리거만 지원한다 (자동 추천 없음) | §6.3 |
| BR-AI-029 | 본문 100자 이상이어야 추천이 동작한다 (SystemConfig 조정 가능) | §6.3 |

### 7.7 시스템 보호 규칙

| ID | 규칙 | 참조 |
|----|------|------|
| BR-AI-030 | LLM Orchestrator 장애 또는 응답 시간 초과 시 사용자에게 재시도를 안내하고 요청을 차단한다 | §10, §12 |
| BR-AI-031 | 조직 일일 AI 사용 한도(`lm:ai.daily_quota`)를 초과하면 요청을 거부한다 | §13 |
| BR-AI-032 | 입력 텍스트가 기능별 최대 토큰 한도(§12, §13)를 초과하면 요청을 거부하고 입력 축소를 안내한다 | §12, §13 |
| BR-AI-033 | 조직 설정(`lm:ai.*_enabled`)에서 비활성화된 AI 기능은 호출을 차단한다 | §13 |
| BR-AI-034 | 민감 정보 등급이 AI 처리 제한인 문서에 대한 AI 요청을 차단한다 | §10 |
| BR-AI-035 | 다른 사용자가 동일 블록을 편집 중이면 AI 글쓰기 개선 요청을 거부한다 | §2 |
| BR-AI-036 | 동일 블록에 대한 재생성 횟수가 `lm:ai.max_regeneration_count`를 초과하면 재생성을 거부한다 | §13 |

---

## 8. 데이터 모델

### 8.1 PromptSlot 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | |
| slot_key | VARCHAR(100) | UNIQUE, NOT NULL | 슬롯 식별 키 (예: `doc_summary_oneline`) |
| feature_group | VARCHAR(50) | NOT NULL | 기능 그룹 (`summary`, `writing`, `tag`) |
| description | VARCHAR(500) | NULL | 슬롯 설명 |
| active_version_id | UUID | FK(PromptVersion), NULL | 현재 활성 버전 |
| tenant_id | UUID | NOT NULL | 테넌트 식별자 |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |

### 8.2 PromptVersion 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | |
| slot_id | UUID | FK(PromptSlot), NOT NULL | 소속 슬롯 |
| version_number | INTEGER | NOT NULL | 슬롯 내 순번 (자동 증가) |
| prompt_body | TEXT | NOT NULL | 프롬프트 본문 |
| status | ENUM('active', 'archived') | NOT NULL, DEFAULT 'active' | 버전 상태 |
| created_by | UUID | FK(User), NOT NULL | 생성자 |
| created_at | TIMESTAMP | NOT NULL | |
| change_note | VARCHAR(500) | NULL | 변경 사유 |

### 8.3 AiUsageLog 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | |
| tenant_id | UUID | NOT NULL | 테넌트 식별자 |
| user_id | UUID | FK(User), NOT NULL | 사용자 |
| feature_type | ENUM('summary_auto', 'summary_manual', 'writing_improve', 'tag_recommend', 'rag_answer') | NOT NULL | 기능 유형 |
| document_id | UUID | FK(Document), NULL | 대상 문서 |
| input_hash | VARCHAR(64) | NOT NULL | 입력 텍스트 SHA-256 해시 (원문 미저장) |
| output_preview | VARCHAR(500) | NULL | 출력 앞부분 미리보기 |
| model_name | VARCHAR(100) | NOT NULL | 사용 모델명 |
| input_tokens | INTEGER | NOT NULL | 입력 토큰 수 |
| output_tokens | INTEGER | NOT NULL | 출력 토큰 수 |
| response_time_ms | INTEGER | NOT NULL | 응답 시간 (밀리초) |
| prompt_slot_key | VARCHAR(100) | NULL | 사용된 프롬프트 슬롯 키 |
| prompt_version_id | UUID | FK(PromptVersion), NULL | 사용된 프롬프트 버전 |
| created_at | TIMESTAMP | NOT NULL | |

### 8.4 AiFeedback 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | |
| usage_log_id | UUID | FK(AiUsageLog), NOT NULL | 대상 사용 이력 |
| feedback_type | ENUM('positive', 'negative') | NOT NULL | 피드백 유형 |
| reason | ENUM('inaccurate', 'nonexistent_content', 'context_error', 'meaning_changed', 'unnecessary_change', 'other') | NULL | 부정 피드백 사유 |
| comment | VARCHAR(500) | NULL | 추가 의견 |
| user_id | UUID | FK(User), NOT NULL | 피드백 작성자 |
| created_at | TIMESTAMP | NOT NULL | |

### 8.5 AiSummaryCache 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | |
| document_id | UUID | FK(Document), NOT NULL | 대상 문서 |
| document_version_id | UUID | FK(DocumentVersion), NOT NULL | 문서 버전 |
| content_hash | VARCHAR(64) | NOT NULL | 문서 content_hash (무효화 판단용) |
| summary_type | ENUM('oneline', 'keypoints', 'section', 'custom') | NOT NULL | 요약 타입 |
| custom_instruction | TEXT | NULL | 맞춤 요약 시 사용자 지시문 |
| summary_text | TEXT | NOT NULL | 요약 결과 |
| model_name | VARCHAR(100) | NOT NULL | 생성에 사용된 모델명 |
| tenant_id | UUID | NOT NULL | 테넌트 식별자 |
| created_by | UUID | FK(User), NOT NULL | 요약 요청자 |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | 재요약 시 갱신 |

### 8.6 엔티티 관계

```
PromptSlot 1 ──── * PromptVersion
PromptSlot 1 ──── 0..1 PromptVersion  (active_version_id)

AiUsageLog * ──── 1 User
AiUsageLog * ──── 0..1 Document
AiUsageLog * ──── 0..1 PromptVersion

AiFeedback * ──── 1 AiUsageLog

AiSummaryCache * ──── 1 Document
```

> Document 엔티티에 `auto_summary`(TEXT, NULL)와 `summary_status`(ENUM, DEFAULT 'none') 필드를 추가한다. 상세는 §9.1 참조.

---

## 9. 상태 모델

### 9.1 자동 요약 생성 상태 (`summary_status`)

Document 엔티티에 `summary_status` 필드를 추가하여 자동 요약의 처리 상태를 추적한다.

```
[none] ──published 전환──→ pending ──워커 시작──→ processing
                                                    │
                                          ┌─────────┴─────────┐
                                          ▼                   ▼
                                      completed             failed
                                          │                   │
                               content_hash 변경 시    수동 재시도/재배포 시
                                          └─────→ pending ←───┘
```

| 상태 | 설명 |
|------|------|
| `none` | 요약 미생성 (draft 등 비게시 상태) |
| `pending` | 요약 큐(`ai-summary`) 대기 중 |
| `processing` | LLM 요약 생성 진행 중 |
| `completed` | 요약 생성 완료 — `auto_summary` 필드에 결과 저장됨 |
| `failed` | 요약 생성 실패 — 최대 재시도 후 실패 확정, 관리자 알림 |

### 9.2 프롬프트 버전 상태

```
(신규 저장) ──→ active ──동일 슬롯에 새 버전 저장──→ archived
                  ▲                                      │
                  └──────────롤백(새 버전으로 복제)────────┘
```

| 상태 | 설명 |
|------|------|
| `active` | 현재 슬롯에서 사용 중인 활성 버전 (슬롯당 1개) |
| `archived` | 새 버전으로 대체된 이전 버전 |

---

## 10. 에러 코드

| 에러 코드 | HTTP | 설명 | 관련 규칙 |
|-----------|------|------|-----------|
| AI_SERVICE_UNAVAILABLE | 503 | AI 서비스(LLM Orchestrator)에 연결할 수 없음 | BR-AI-030 |
| AI_SERVICE_TIMEOUT | 504 | AI 서비스 응답 시간 초과 | BR-AI-030 |
| AI_QUOTA_EXCEEDED | 429 | 조직의 AI 사용 한도 초과 | BR-AI-031 |
| AI_CONTENT_TOO_LONG | 400 | 입력 텍스트가 기능별 최대 토큰 한도 초과 | BR-AI-032 |
| AI_CONTENT_TOO_SHORT | 400 | 입력 텍스트가 최소 분량 미달 | BR-AI-029 |
| AI_FEATURE_DISABLED | 403 | 해당 AI 기능이 조직 설정에서 비활성화됨 | BR-AI-033 |
| AI_SENSITIVE_RESTRICTED | 403 | 민감 정보 AI 처리 제한 등급에 의해 차단 | BR-AI-034 |
| AI_CONCURRENT_CONFLICT | 409 | 동시 편집 충돌 — 다른 사용자가 동일 블록을 수정함 | BR-AI-035 |
| AI_REGENERATION_LIMIT | 429 | 동일 블록에 대한 재생성 횟수 초과 | BR-AI-036 |
| AI_PROMPT_TEST_FAILED | 500 | 프롬프트 테스트 실행 실패 | BR-AI-015 |
| AI_SUMMARY_FAILED | 500 | 자동 요약 생성 실패 (재시도 소진) | BR-AI-002 |

---

## 11. 이벤트 계약

### 11.1 ai-assistant 모듈이 발행하는 이벤트

| 이벤트명 | 큐/토픽 | 트리거 | 페이로드 |
|----------|---------|--------|----------|
| `ai.summary.requested` | `ai-summary` (Bull) | 문서 published 전환 수신 시 | `{ schemaVersion: 1, documentId: UUID, versionId: UUID, contentHash: string, tenantId: UUID, priority: number }` |
| `ai.summary.completed` | 이벤트 버스 | 자동 요약 생성 완료 시 | `{ schemaVersion: 1, documentId: UUID, versionId: UUID, summaryText: string, modelName: string, tokenCount: number, tenantId: UUID }` |
| `ai.summary.failed` | 이벤트 버스 | 자동 요약 생성 최종 실패 시 | `{ schemaVersion: 1, documentId: UUID, versionId: UUID, errorCode: string, retryCount: number, tenantId: UUID }` |
| `ai.cache.invalidated` | 이벤트 버스 | 문서 content_hash 변경 감지 시 | `{ schemaVersion: 1, documentId: UUID, contentHash: string, invalidatedTypes: string[], tenantId: UUID }` |
| `ai.usage.logged` | 이벤트 버스 | AI 기능 호출 이력 기록 시 | `{ schemaVersion: 1, usageLogId: UUID, featureType: string, documentId: UUID, tenantId: UUID }` |

### 11.2 ai-assistant 모듈이 소비하는 이벤트

| 이벤트명 | 발행 모듈 | 처리 |
|----------|-----------|------|
| `document.published` | document | 자동 요약 트리거 — `ai.summary.requested`를 `ai-summary` 큐에 등록 |
| `document.content.changed` | document | 요약 캐시 무효화 — `ai.cache.invalidated` 발행 |

### 11.3 큐 설계

| 큐명 | 기술 | 용도 | 재시도 정책 |
|------|------|------|-------------|
| `ai-summary` | Bull(Redis) | 자동 요약 비동기 처리 | 지수 백오프(초기 5s, ×2), 최대 3회, DLQ: `ai-summary-dlq` |

> `embedding` 큐([FD-EMB](FD-EMB-임베딩파이프라인.md) §1.4)와 **별도 큐**로 운영하여, 임베딩 처리 지연이 요약에 영향을 주지 않도록 격리한다.

**DLQ 처리 절차** (`ai-summary-dlq`):
1. 최대 재시도(3회) 소진 후 실패한 작업이 DLQ에 적재된다
2. `summary_status = failed`로 마킹 + 관리자 알림 발송 [BR-AI-002]
3. 관리자는 대시보드에서 DLQ 항목을 확인하고, 수동으로 **재시도**(큐 재등록) 또는 **폐기**(DLQ에서 삭제)를 선택한다
4. 재시도 시 `summary_status = pending`으로 복귀하여 `ai-summary` 큐에 재등록된다

---

## 12. 비기능 요구사항

| 항목 | 요구사항 | 비고 |
|------|----------|------|
| AI 요약 응답 시간 (p95) | 10초 이내 | 스트리밍 첫 토큰 2초 이내 |
| AI 글쓰기 개선 응답 시간 (p95) | 8초 이내 | 스트리밍 첫 토큰 2초 이내 |
| AI 태그 추천 응답 시간 (p95) | 5초 이내 | — |
| 자동 요약 처리 시간 (p95) | 30초 이내 | 비동기 큐 처리, 사용자 대기 없음 |
| 기능별 최대 입력 토큰 | 요약: 32K, 개선: 8K, 태그: 16K | SystemConfig 조정 가능 |
| 기능별 최대 출력 토큰 | 요약: 2K, 개선: 4K, 태그: 1K | SystemConfig 조정 가능 |
| 테넌트당 동시 AI 요청 수 | 10건 | SystemConfig 조정 가능 |
| AI 서비스 가용률 목표 | 99% 이상 | — |
| AI 사용 이력 보관 기간 | 1년 (금융권 5년) | 감사 로그 보관 정책과 동일 |
| 자동 요약 재시도 정책 | 지수 백오프, 최대 3회 | 최종 실패 시 `summary_status = failed` + 관리자 알림 |

---

## 13. 설정 가능 항목

| 설정 항목 | 키 | 타입 | 기본값 | 설명 |
|-----------|-----|------|--------|------|
| AI 요약 기능 활성화 | `lm:ai.summary_enabled` | boolean | true | 조직 단위 on/off |
| AI 글쓰기 개선 활성화 | `lm:ai.writing_improve_enabled` | boolean | true | 조직 단위 on/off |
| AI 태그 추천 활성화 | `lm:ai.tag_recommend_enabled` | boolean | true | 조직 단위 on/off |
| 일일 AI 사용 한도 | `lm:ai.daily_quota` | integer | 1000 | 조직 일일 AI 호출 횟수 제한 |
| 동시 AI 요청 수 | `lm:ai.concurrent_requests` | integer | 10 | 테넌트당 동시 처리 제한 |
| 요약 최대 입력 토큰 | `lm:ai.summary_max_input_tokens` | integer | 32000 | — |
| 개선 최대 입력 토큰 | `lm:ai.writing_max_input_tokens` | integer | 8000 | — |
| 태그 추천 최소 본문 길이 | `pm:ai.tag_recommend_min_length` | integer | 100 | 자 단위 |
| 재생성 최대 횟수 | `lm:ai.max_regeneration_count` | integer | 5 | 동일 블록 재생성 제한 |
| 자동 요약 재시도 횟수 | `pm:ai.summary_max_retries` | integer | 3 | — |
| 신뢰도 상한 임계값 | `pm:ai.confidence_threshold_high` | number | 0.8 | 이 이상이면 "높음" |
| 신뢰도 하한 임계값 | `pm:ai.confidence_threshold_low` | number | 0.5 | 이 미만이면 "낮음" |
| AI 사용 이력 보관 기간 | `pm:ai.usage_log_retention_years` | integer | 1 | 년 단위, 금융권 5년 |
| 자동 비활성화 오류율 임계치 | `pm:ai.auto_disable_error_rate` | number | 0.3 | 초과 시 해당 기능 자동 비활성화 |

---

## 부록 A. 주요 API/DTO 스키마

> FD 수준에서 프론트·백엔드 공통 타입 합의를 위해 주요 API의 요청/응답 DTO를 정의한다. 전체 엔드포인트는 모듈 스펙(api.md)에서 확정한다.

### A.1 자동 요약 조회

```typescript
// GET /api/documents/:documentId/auto-summary
interface GetAutoSummaryResponse {
  documentId: string;
  summaryStatus: 'none' | 'pending' | 'processing' | 'completed' | 'failed';
  autoSummary: string | null;
  contentHash: string;
  updatedAt: string;          // ISO 8601
}
```

### A.2 수동 요약 요청 (스트리밍)

```typescript
// POST /api/documents/:documentId/summary
interface RequestManualSummaryDto {
  summaryType: 'oneline' | 'keypoints' | 'section' | 'custom';
  customInstruction?: string; // summaryType='custom'일 때 필수
  forceRegenerate?: boolean;  // true면 캐시 무시, 재요약 [BR-AI-005]
}
```

**캐시 히트 시** (`forceRegenerate=false`, 동일 버전+타입 캐시 존재 [BR-AI-004]):

```typescript
// Content-Type: application/json (비스트리밍)
interface CachedSummaryResponse {
  cached: true;
  summaryId: string;
  summaryText: string;
  summaryType: string;
  createdAt: string;
}
```

**캐시 미스 또는 재생성 시** (SSE 스트리밍):

```
Content-Type: text/event-stream

event: chunk
data: {"content":"요약 텍스트 일부..."}

event: chunk
data: {"content":"이어지는 텍스트..."}

event: done
data: {"summaryId":"<uuid>","summaryType":"oneline","modelName":"gpt-4o","tokenCount":512}

event: error
data: {"errorCode":"AI_SERVICE_TIMEOUT","message":"AI 서비스 응답 시간 초과"}
```

### A.3 글쓰기 개선 요청 (스트리밍)

```typescript
// POST /api/documents/:documentId/writing-improve
interface RequestWritingImproveDto {
  blockIds: string[];
  scope: 'block' | 'document';
  improveType: 'polish' | 'tone_formal' | 'tone_casual'
             | 'concise' | 'elaborate' | 'translate' | 'freeform';
  targetLanguage?: string;      // improveType='translate'일 때 (예: 'en', 'ko')
  freeformInstruction?: string; // improveType='freeform'일 때 필수
}
```

**SSE 스트리밍 응답**:

```
Content-Type: text/event-stream

event: chunk
data: {"blockId":"<block-uuid>","content":"개선된 텍스트 일부..."}

event: done
data: {"blockId":"<block-uuid>","originalText":"원본","improvedText":"전체 개선 결과","modelName":"gpt-4o"}

event: error
data: {"errorCode":"AI_CONCURRENT_CONFLICT","message":"다른 사용자가 동일 블록을 수정 중입니다"}
```

> 전체 문서 개선(`scope='document'`) 시 섹션별로 `event: section-start` → `event: chunk` × N → `event: section-done`을 반복한다 [BR-AI-010].

### A.4 프롬프트 관리

```typescript
// GET /api/admin/prompt-slots
interface PromptSlotListResponse {
  slots: {
    id: string;
    slotKey: string;
    featureGroup: 'summary' | 'writing' | 'tag';
    description: string | null;
    activeVersion: {
      id: string;
      versionNumber: number;
      status: 'active' | 'archived';
      createdBy: string;
      createdAt: string;
      changeNote: string | null;
    } | null;
  }[];
}

// POST /api/admin/prompt-slots/:slotId/versions
interface CreatePromptVersionDto {
  promptBody: string;
  changeNote?: string;
}

// POST /api/admin/prompt-slots/:slotId/test
interface TestPromptDto {
  promptBody: string;
  sampleDocumentId?: string;
  sampleText?: string;
}

interface TestPromptResponse {
  result: string;
  modelName: string;
  inputTokens: number;
  outputTokens: number;
  responseTimeMs: number;
}
```

### A.5 태그 추천

```typescript
// POST /api/documents/:documentId/tag-recommend
interface RequestTagRecommendDto {
  maxCount?: number;          // 추천 최대 수 (기본 5) [BR-AI-025]
}

interface TagRecommendResponse {
  existingTags: {
    tagId: string;
    name: string;
    reason: string;
  }[];
  newTagSuggestions: {
    name: string;
    reason: string;
  }[];
  modelName: string;
  inputTokens: number;
  outputTokens: number;
}
```

### A.6 공통 SSE 이벤트 규격

| 이벤트 타입 | 용도 | 데이터 필드 |
|-------------|------|-------------|
| `chunk` | 스트리밍 텍스트 청크 | `content: string` (+ 선택: `blockId`) |
| `done` | 스트리밍 완료 신호 | 기능별 메타데이터 (`summaryId`, `modelName` 등) |
| `error` | 스트리밍 중 에러 | `errorCode: string, message: string` |
| `section-start` | 전체 문서 개선 시 섹션 시작 | `sectionIndex: number, sectionTitle: string` |
| `section-done` | 전체 문서 개선 시 섹션 완료 | `sectionIndex: number` |

> 클라이언트는 `text/event-stream` 응답을 EventSource 또는 fetch + ReadableStream으로 소비한다. 연결 끊김 시 자동 재연결하지 않으며, 사용자에게 재시도를 안내한다.

---

## 결정사항

| 항목 | 결정 | 근거 |
|------|------|------|
| 자동 요약 생성 시점 | **published 시점** — 별도 `ai-summary` 큐에서 비동기 처리 | 요약 실패해도 문서 게시는 막지 않음 |
| 자동 요약·임베딩 큐 분리 | **별도 큐 운영** — `ai-summary` 큐와 `embedding` 큐를 분리 | 상호 간 지연 영향 차단, 독립 재시도·DLQ 운영 |
| 수동 요약 저장 방식 | **DB(AiSummaryCache)에 저장** — 자동/수동 요약 모두 DB에 영구 저장, "재요약" 버튼으로 갱신 | 동일 요약 반복 호출 방지, LLM 비용 절감 |
| AI 글쓰기 결과 표시 | **단일 블록 = 인라인 diff, 전체 문서 = 사이드바 비교** | 편집 맥락 유지 + 전체 비교 |
| AI 수정 추적 | **미지원** — ai_touched 플래그 등 별도 추적 없음 | 승인 워크플로의 버전 diff로 충분, 별도 추적은 과잉 |
| 프롬프트 관리 주체 | **AICM이 직접 관리** — LLM Orchestrator는 LLM 호출만 담당 | 프롬프트 비즈니스 로직은 AICM 소유, LLM Orchestrator는 공통 인프라 |
| LLM 호출 방식 | **LLM Orchestrator 경유** — LLM 직접 호출 금지 | 모델 라우팅/프로바이더 관리를 공통 인프라에 위임 |
| 프롬프트 관리 권한 | **`manage_prompts` 보유자만 편집 가능** | 운영 안정성 및 변경 통제 |
| 프롬프트 슬롯 확장 방식 | **DB 기반 동적 확장** — PromptSlot 엔티티로 런타임 추가 가능 | 코드 배포 없이 기능 확장 |
| Hallucination 탐지 | **출처 검증 + 신뢰도 점수 + 면책 문구** 3단계 | 금융 컴플라이언스 대응 |
| 프롬프트 반영 방식 | **슬롯별 최신 버전 즉시 적용** | 기능 단위 운영 단순화 및 추적성 확보 |
| AI 태그 추천 전략 | **기존 태그 재사용 우선** — 새 태그 제안은 기존 태그에 적합한 것이 없을 때만 별도 영역에 표시 | 태그 풀 일관성 유지, 중복 태그 생성 억제 |
| AI 태그 추천 트리거 | **수동 트리거만** — 자동 추천 없음 | 사용자 편집 흐름 방해 방지, AI 호출 비용 통제 |
| 감사 로그 수집 방식 | **비동기 수집** — 이벤트 기반으로 LogEventModule에 전달 | AI 응답 지연 방지 |

---

## 관련 문서

| 문서 | 참조 내용 |
|------|----------|
| [FD-DOC](FD-DOC-문서관리.md) | 블록 에디터(§1.2), 버전 관리(§1.1.1), 헤딩 블록 |
| [FD-EMB](FD-EMB-임베딩파이프라인.md) | 임베딩 큐, 요약 청크 임베딩 |
| [FD-SCH](FD-SCH-검색.md) | RAG 검색/답변(§2) — Hallucination 완화 연동 |
| [FD-DOC](FD-DOC-문서관리.md) §8 | 태그 입력 방식, 자동완성 정렬, 태그 관리 |
| [UC-AI](../usecases/user/UC-AI-AI어시스턴트.md) | UC-AI-01 ~ UC-AI-04 |

# 검색 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-SCH |
| 버전 | 1.3 |
| 작성일 | 2026-03-31 |
| 수정일 | 2026-04-02 |
| 기준 문서 | AICM 새 기능정의서 v1 §2 |

---

## 1. 전통적 검색 (키워드 기반)

- **[BR-SCH-001]** 제목, 본문, 태그, 작성자 등 필드별 검색
- Elasticsearch 또는 OpenSearch 기반 풀텍스트 검색
- **[BR-SCH-002]** 한국어 형태소 분석기(nori) 적용 — "관리하다" 검색 시 "관리", "관리자" 등 매칭
- 필터링: [게시판](FD-DOC-문서관리.md)(하위 게시판 포함 옵션), 기간, 작성자, [태그](FD-DOC-문서관리.md) §8, **[템플릿](FD-DOC-문서관리.md) §4(문서 유형)** 조합
- 검색어 자동완성(autocomplete) / 오타 교정(fuzzy matching)
- 검색 결과 하이라이팅
- **[BR-SCH-003]** 사용자가 열람 권한(`BoardPermission(VIEW)`)을 가진 게시판의 문서만 결과에 포함 — 게시판 권한이 없는 문서는 표시하지 않음
- **[BR-SCH-004] 메타정보 VIEW 바이패스 시 검색 결과 제한**: `BoardPermission(VIEW)` 없이 AdminPermission 메타정보 바이패스로만 접근하는 게시판의 문서는 검색 결과에 **메타정보만** 표시(제목, 태그, 게시판명, 상태, 작성자, 날짜). 본문 스니펫·하이라이팅은 제거 — 상세: [FD-ACL](FD-ACL-권한체계.md) §4.1
- **[BR-SCH-005] 접근 제한(Restriction) 문서 검색 제외**: [FD-ACL](FD-ACL-권한체계.md) §8의 `restricted = true` 문서는 허용 목록(User/Group)에 포함되지 않은 사용자의 키워드 검색 결과에서 **완전 제외** — 문서 존재 자체가 노출되지 않음
- **[BR-SCH-029] 긴급 검색 제외(키워드)**: 보안 사고·법적 조치·민감 정보 유출 등 긴급 상황에서 `manage_search` 권한 보유자가 특정 문서 또는 특정 게시판 전체를 키워드 검색 결과에서 즉시 제외할 수 있다 — ES `is_search_excluded` 메타데이터 필터 적용. **모든 사용자**의 검색 결과에서 완전 제외되며, 제외 사유·시각이 감사 로그에 기록된다. 권한 보유자가 "검색 복원"을 실행하면 필터 해제 후 즉시 재포함 — 상세: [UC-ADM-07](../usecases/admin/UC-ADM-검색파이프라인.md) 긴급 검색 제외

---

## 2. 문서 RAG (AI 기반 검색/답변)

- 사용자 질의에 대해 관련 문서 청크를 검색하고 LLM이 답변 생성
- 답변 시 출처 문서 링크 제공 (인용 표시)
- 벡터 DB(Milvus 등)에서 시맨틱 검색 → 상위 K개 청크 → LLM 컨텍스트로 전달
- 하이브리드 검색: 키워드 검색(BM25) + 벡터 검색 결과를 가중합산(RRF 등)
- **[BR-SCH-006]** [FD-ACL](FD-ACL-권한체계.md) 게시판 권한에 따라 검색 범위 제한 — 접근 불가 게시판의 문서는 RAG 결과에서도 제외
- **[BR-SCH-007] 메타정보 VIEW 바이패스 문서의 RAG 제외**: `BoardPermission(VIEW)` 없이 AdminPermission 메타정보 바이패스로만 접근 가능한 게시판의 문서는 **RAG 소스에서 제외** — 바이패스는 메타정보 수준이므로 본문 기반 답변 생성 불가, RAG 답변에 본문이 간접 노출되는 우회 경로 차단. 상세: [FD-ACL](FD-ACL-권한체계.md) §4.1
- **[BR-SCH-008] 접근 제한(Restriction) 문서 RAG 제외**: `restricted = true` 문서는 허용 목록에 포함되지 않은 사용자의 RAG 소스에서 완전 제외 — 문서 존재 여부도 노출되지 않음
- **[BR-SCH-030] 긴급 검색 제외(RAG)**: BR-SCH-029의 `search_excluded = true` 문서는 RAG 소스에서도 완전 제외 — Milvus `is_search_excluded` 스칼라 필터로 ES와 동시 적용
- **[BR-SCH-009]** [FD-EMB](FD-EMB-임베딩파이프라인.md) §1 임베딩 미완료(`pending`/`processing`) 문서는 RAG 검색 대상에서 자동 제외 — 키워드 검색(BM25)에는 포함되되 상태 표시 부착
- **[BR-SCH-010] Hallucination 완화**: RAG 답변 생성 시 LLM Orchestrator가 출처 검증(grounding check)을 수행하여 각 문장의 근거 청크를 매핑. 근거 없는 문장은 시각적으로 구분하고, 전체 답변에 신뢰도 점수를 부여 — 상세: [FD-AI](FD-AI-AI어시스턴트.md) §5
- **[BR-SCH-011] 면책 문구**: 모든 RAG 답변에 "AI 생성 답변이며 정확성을 보장하지 않습니다" 면책 문구를 기본 포함

---

## 3. 자동 청킹

- **[BR-SCH-012] 블록 에디터 문서 청킹**: [FD-DOC](FD-DOC-문서관리.md) §2(블록 에디터)로 작성된 문서는 블록 JSON을 직접 파싱하여 청킹 — 블록 타입별 최적 청킹 전략 적용
  - 텍스트/헤딩 블록: 인접 블록을 의미 단위로 그룹핑하여 청크 구성 (헤딩을 섹션 구분자로 활용)
  - 테이블 블록: 표 전체를 하나의 청크로 처리, 대형 표는 행 그룹 단위로 분할. 마크다운/HTML 테이블 형식으로 변환하여 LLM이 구조를 이해할 수 있도록 전달
  - 이미지 블록: 캡션 + 멀티모달 분석 결과를 텍스트 청크로 변환
  - 코드 블록: 코드 + 인접 설명 블록을 하나의 청크로 구성
  - **[BR-SCH-013]** [FD-DOC](FD-DOC-문서관리.md) §5(공통 컨텐츠) 참조 블록: 참조 원본의 최신 내용을 resolve하여 청킹 — 원본 수정 시 참조 블록 포함 문서의 재청킹 트리거 (트리거 범위: 해당 공통 컨텐츠를 참조하는 모든 문서)
  - 접기(토글) 블록: 펼친 상태의 전체 내용을 청킹 대상에 포함
- **[BR-SCH-014] 파일 업로드 문서 청킹**: 파일 첨부 블록으로 업로드된 PDF, DOCX, HWP/HWPX, PPTX 등 → 텍스트 추출 → 자동 청킹
  - **[BR-SCH-015]** HWP 파일 처리: 확장자 분기 — HWPX는 XML 직접 파싱, 구 HWP(바이너리)는 LibreOffice headless로 DOCX 변환 후 파싱
  - 변환 품질 미달 문서는 예외 목록으로 분리하여 수동 검수 흐름 제공
- 청킹 전략: 고정 토큰 수 / 의미 단위(heading 기반) / 슬라이딩 윈도우 등 설정 가능
- **[BR-SCH-016] 템플릿 기반 청킹**: 문서의 `template_id`([FD-DOC](FD-DOC-문서관리.md) §4)에 따라 청킹 전략 자동 분기 — FAQ 템플릿은 Q&A 쌍 단위, SOP 템플릿은 스텝 단위, 체크리스트는 항목 단위 등
- **[BR-SCH-017]** 청킹 결과에 메타데이터 부착: 원본 문서 ID, 블록 ID, 블록 타입, 섹션 제목, 템플릿 ID
- 청크별 임베딩 생성 → 벡터 DB 저장
- **[BR-SCH-018]** 원본 문서 수정/삭제 시 관련 청크도 동기화(재청킹 or 삭제)

### 3.1 ParsingConfig — 청킹 설정 엔티티

청킹 파이프라인의 설정은 **ParsingConfig** 전용 엔티티로 관리한다. SystemConfig Key-Value가 아닌 구조화된 전용 테이블로, 변경 시 영향 문서의 재청킹/재임베딩이 필요하므로 독립적으로 관리한다.

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `default_chunking_strategy` | enum | `semantic` | 기본 청킹 전략 (`fixed_token` / `semantic` / `sliding_window`) |
| `chunk_size` | number | `512` | 청크 최대 토큰 수 (aicm-service 설정값). retrieval-service는 sLLM 임베딩 모델 최적 범위에 따라 실제 `max_tokens`를 256으로 운영할 수 있다 — [retriever 데이터 아키텍처](../../02-architecture/data/retriever/README.md) §2.4 참조 |
| `chunk_overlap_percent` | number | `10` | 오버랩 비율 (%) |

**하위 엔티티:**

- **BoardParsingOverride** (1:N) — 게시판별 청킹 파라미터 오버라이드 (chunk_size, overlap, strategy)
- **TemplateChunkingRule** (1:N) — 템플릿별 청킹 전략 매핑 (FAQ→Q&A 쌍 단위, SOP→스텝 단위, 체크리스트→항목 단위 등)

**동기화 패턴**: aicm-service가 `POST /ingest/embed` 요청 시 해당 문서에 적용할 청킹 설정을 `chunking_config` 파라미터로 동봉한다. retrieval-service는 파싱 설정을 캐싱하지 않는다 (stateless).

- 상세: [ADR-009](../../adr/009-search-config-singleton-merge.md)

---

## 4. 문서 영역별 임베딩/가시성 제어

- [FD-DOC](FD-DOC-문서관리.md) §2(블록 에디터)의 각 블록이 독립적인 제어 단위 — 블록 메타데이터의 `embeddable`, `visible` 플래그로 관리
- **[BR-SCH-019]** 블록 선택 → 블록 메뉴에서 "임베딩 제외" / "숨김" 토글 — 해당 블록은 청킹/임베딩 파이프라인에서 스킵
  - 사용 예시: 사내 민감 정보, 아직 확정되지 않은 초안 영역, 개인정보 포함 구간 등
- 동일 블록에 대해 **사용자 가시성** 별도 제어 가능 — 허용되는 조합 3가지:
  - 임베딩 포함 + 사용자에게 보임: 일반 블록 (기본값)
  - 임베딩 제외 + 사용자에게 보임: RAG 답변에는 안 나오지만 문서 열람 시에는 보임
  - 임베딩 제외 + 사용자에게 안 보임: RAG에도 안 나오고 열람 시에도 숨김 (관리자/작성자만 확인 가능)
  - **[BR-SCH-020]** ~~임베딩 포함 + 사용자에게 안 보임~~: **미허용** — 사용자가 볼 수 없는 콘텐츠는 RAG 답변의 근거로도 쓸 수 없음 (원칙: 출처 검증 불가한 근거 차단)
- 블록 단위 메타데이터로 관리: `{ embeddable: boolean, visible: boolean }` 플래그
- **[BR-SCH-021]** 문서 수정 시 플래그 변경되면 해당 블록만 재청킹/[FD-EMB](FD-EMB-임베딩파이프라인.md) 재임베딩 트리거

---

## 5. RAG 고도화 — 표/중첩 표/이미지 분석

### 5.1 표(Table) 파싱

블록 에디터 내 테이블 블록의 기본 청킹 전략은 §3에서 정의한다. 이 절은 **파일 업로드 문서**에서 추출된 표와 **LLM 전달 시 구조 보존** 측면을 보완한다.

- 파일 업로드(PDF, DOCX, HWP 등)에서 추출된 표: 행/열 관계를 보존한 채 청킹
- 마크다운/HTML 테이블 형식으로 변환하여 LLM이 구조를 이해할 수 있도록 전달

### 5.2 중첩 표(표 안의 표) 처리

- **[BR-SCH-022]** 중첩 깊이 **2depth**로 제한 — 실제 금융 문서에서 진짜 중첩 표는 드묾, 대부분 셀 병합으로 표현된 복잡한 단일 표
- 레이아웃용 바깥 표는 벗겨내고 안쪽 데이터 표만 취하는 전략
- **핵심 과제: 셀 병합 처리** — 금융 문서의 복잡한 표는 중첩이 아니라 행/열 병합 때문에 어려움, 병합된 셀의 컨텍스트를 청킹 시 보존하는 전략이 실질적 과제

### 5.3 이미지 분석

- **[BR-SCH-023]** 문서 내 삽입된 이미지에 대해 **LLM Orchestrator를 경유**하여 멀티모달 LLM으로 설명 텍스트 생성
- 생성된 설명 텍스트를 임베딩하여 벡터 DB에 저장 — 이미지 내용도 RAG 검색 대상
- 이미지 내 표/차트 인식: OCR + 구조 분석으로 데이터 추출
- 이미지 캡션과 원본 이미지를 함께 저장하여 출처 표시 시 이미지도 제공 가능

### 5.4 파이프라인 흐름

문서 저장(블록 JSON) → 블록 타입별 처리 분기(텍스트 추출 / 표 구조 파싱 / 이미지 분석) → 블록별 임베딩 제외 필터(§4) → 청킹(§3) → [FD-EMB](FD-EMB-임베딩파이프라인.md) 임베딩 → 벡터 DB 저장

---

## 6. 검색 튜닝

### 6.1 레거시 검색 튜닝

**관리자 튜닝 영역**

- **동의어 사전 관리**: "고객센터" = "콜센터" = "CS센터" 등 동의어 그룹 등록/수정/삭제
- **불용어 관리**: 검색에서 제외할 단어 설정
- **부스팅 규칙**: 특정 게시판/태그/문서를 검색 결과 상위로 올리는 가중치 규칙
- **필드별 가중치 조정**: 제목 vs 본문 vs 태그 vs 댓글 각각의 검색 스코어 비중 설정
- **형태소 분석기 설정**: nori 사용자 사전 등록 (도메인 용어, 사내 약어 등)

**사용자 튜닝 영역**

- **개인 검색 선호 설정**: 기본 정렬 기준(관련도순/최신순/인기순), 기본 검색 범위(전체/특정 게시판)
- **검색 필터 프리셋 저장**: 자주 쓰는 필터 조합(게시판 + 기간 + 태그)을 저장하여 재사용 — 상세: §6.7 SearchFilterPreset 엔티티
- **검색 결과 피드백**: 결과에 대해 "관련 있음/없음" 피드백 → 개인화 랭킹에 반영 (선택적 기능)

### 6.2 RAG 검색 튜닝

**관리자 튜닝 영역**

- **청킹 전략 설정**: 청킹 사이즈, 오버랩 비율, 분할 방식(고정 토큰/의미 단위) 조정, **[FD-DOC](FD-DOC-문서관리.md) §4(템플릿)별 청킹 전략 매핑**
- **검색 파라미터**: 상위 K값, 유사도 임계값(threshold), 하이브리드 검색 가중치(키워드 vs 벡터 비율)
- **리랭킹 설정**: 검색 결과 리랭킹 모델 사용 여부 및 파라미터
- **프롬프트 템플릿 관리**: RAG 답변 생성 시 사용하는 시스템 프롬프트 편집 (게시판별 커스텀 가능)
- **모델 선택**: 임베딩 모델, 답변 생성 모델 선택 (비용/품질 트레이드오프)
- **RAG 파이프라인 on/off**: 게시판 단위로 RAG 대상 여부 설정

**사용자 튜닝 영역**

- **답변 스타일 선호**: 간결한 답변 vs 상세한 답변, 출처 표시 방식 선택
- **검색 범위 지정**: RAG 질의 시 특정 게시판(하위 포함)/태그/**[FD-DOC](FD-DOC-문서관리.md) §4(템플릿, 문서 유형)**으로 범위 한정
- **대화 컨텍스트 (Phase 2)**: 이전 질의와 이어서 대화할지, 새 질의로 시작할지 선택 — MVP에서는 매 질문이 독립적인 단발 질의로 처리. Phase 2에서 대화 세션 내 후속 질문 지원 예정 ([UC-SCH-02](../usecases/user/UC-SCH-검색.md) 대안 흐름 참조)

### 6.3 검색 테스트 환경 (Playground)

**관리자용 테스트**

- **레거시 검색 테스트**: 쿼리 입력 → 현재 설정 기반 결과 확인 → 파라미터 변경 → 재검색 비교
- **RAG 테스트**: 질의 입력 → 검색된 청크 목록 + 유사도 스코어 + 최종 답변을 한눈에 확인
- **A/B 비교**: 설정 A와 설정 B를 나란히 놓고 동일 쿼리에 대한 결과 비교
- **배포 전 검증**: 튜닝한 설정을 운영 반영 전에 테스트 환경에서 검증 → 승인 후 운영 적용 (스테이징 개념)
- **검색 로그 기반 리플레이**: 실제 사용자 검색 로그에서 상위 N개 쿼리를 자동 실행하여 변경 전후 결과 차이 확인

**사용자용 테스트**

- **RAG 미리보기**: 질의를 보내기 전에 어떤 문서/청크가 검색될지 미리 확인 가능
- **출처 확인**: RAG 답변의 각 문장이 어떤 청크에서 나왔는지 하이라이트로 표시

### 6.4 검색 품질 모니터링

- **검색 로그 분석**: 많이 검색된 키워드, 검색 후 클릭률(CTR), 검색 실패(0건) 키워드
- **RAG 품질 지표**: 답변 생성 시 참조 청크 수, 평균 유사도 스코어, 사용자 피드백(👍/👎) 비율
- **알림**: 검색 실패율 급증, RAG 품질 지표 하락 시 관리자 알림
- **[FD-EMB](FD-EMB-임베딩파이프라인.md) 파이프라인 지표**: 임베딩 대기 문서 수, 평균 처리 시간, 실패율, 큐 적체량 — 임계값 초과 시 관리자 알림
- **Hallucination 비율**: 신뢰도 점수 0.5 미만 답변의 비율 추적, 임계값 초과 시 관리자 알림 — 프롬프트 또는 청킹 전략 조정 필요 신호

### 6.5 검색 설정 엔티티 구조

검색 관련 설정은 **변경 주기·소비자·동기화 대상**에 따라 2개 전용 엔티티로 분리 관리한다. 범용 SystemConfig Key-Value에는 포함하지 않는다.

| 엔티티 | 담당 영역 | 소비자 | 동기화 대상 |
|--------|----------|--------|-----------|
| **SearchConfig** | 키워드 검색(필드 가중치, 동의어, 불용어, 부스팅, 사용자 사전) + RAG 검색(하이브리드 가중치, 리랭킹, top_k, 유사도 임계값) | aicm-service → SearchRepository(ElasticsearchSearchAdapter) + retrieval-service | 검색 엔진 설정 동기화 (ES: 인덱스 close/open), retrieval-service namespace 캐시 (이벤트 기반 무효화) |
| **ParsingConfig** | 청킹 전략, 청크 사이즈, 오버랩, 게시판별/템플릿별 오버라이드 | 임베딩 파이프라인 워커 | `POST /ingest/embed` 요청 시 동봉 |

#### SearchConfig 필드 정의

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `id` | UUID | — | PK |
| `field_weights` | JSONB | `{ "title": 3.0, "body": 1.0, "tags": 2.0, "comments": 0.5 }` | 키워드 검색 필드별 가중치 |
| `nori_user_dictionary` | TEXT[] | `[]` | nori 사용자 사전 단어 목록 (도메인 용어, 사내 약어) |
| `hybrid_keyword_weight` | DECIMAL(3,2) | `0.50` | 하이브리드 검색 키워드(BM25) 비중 (0.00~1.00) |
| `hybrid_vector_weight` | DECIMAL(3,2) | `0.50` | 하이브리드 검색 벡터 비중 (0.00~1.00, keyword + vector = 1.00) |
| `default_top_k` | INTEGER | `10` | RAG 검색 상위 K개 청크 |
| `default_similarity_threshold` | DECIMAL(3,2) | `0.70` | 벡터 검색 유사도 임계값 |
| `reranking_enabled` | BOOLEAN | `false` | 검색 결과 리랭킹 모델 사용 여부 |
| `updated_at` | TIMESTAMP | — | 최종 수정 시각 |
| `updated_by` | UUID, FK(User) | — | 최종 수정자 |
| `version` | INTEGER | `1` | 낙관적 동시성 제어용 버전 |

**SearchConfig 하위 엔티티:**

| 하위 엔티티 | 관계 | 주요 필드 | 설명 |
|------------|------|----------|------|
| **Synonym** | 1:N | `id`, `group_id` (UUID), `word` (VARCHAR) | 동의어 그룹 — 같은 `group_id`를 공유하는 단어들이 동의어 관계 |
| **StopWord** | 1:N | `id`, `word` (VARCHAR, UNIQUE) | 불용어 — 검색에서 제외할 단어 |
| **BoostRule** | 1:N | `id`, `target_type` (ENUM: `board`/`tag`/`document`), `target_id` (UUID), `boost_weight` (DECIMAL) | 부스팅 규칙 — 특정 대상의 검색 스코어 가중치 |
| **BoardRagConfig** | 1:N | `id`, `board_id` (UUID, FK), `rag_enabled` (BOOLEAN), `top_k` (INTEGER, NULL), `similarity_threshold` (DECIMAL, NULL) | 게시판별 RAG 설정 오버라이드 — NULL이면 SearchConfig 기본값 사용 |

**[BR-SCH-024] 설정 변경 동기화 패턴** (캐시 + 이벤트 무효화):

1. 관리자가 SearchConfig를 수정·저장한다
2. aicm-service가 `search.config.updated` 이벤트를 발행한다 (§9 이벤트 계약 참조)
3. **즉시 반영 항목** (필드 가중치, RAG 파라미터, 리랭킹 설정): 다음 검색 요청부터 적용
4. **인덱스 재구성 필요 항목** (동의어, 불용어, 사용자 사전): ES 인덱스 close → 설정 적용 → reopen 비동기 진행. 재구성 중 기존 인덱스로 검색 가능, 완료 시 자동 전환
5. retrieval-service가 이벤트를 소비하여 namespace 캐시를 무효화하고 최신 설정을 반영한다

**[BR-SCH-031] 설정 저장 낙관적 동시성 제어**: 관리자가 SearchConfig를 저장할 때 요청 본문의 `version`과 DB 현재 `version`을 비교한다. 불일치 시 `SCH_CONFIG_VERSION_CONFLICT`(409)를 반환하고 저장을 차단한다 — 클라이언트는 최신 값을 다시 불러온 뒤 병합·재시도. ParsingConfig에도 동일 패턴을 적용한다.

**ParsingConfig 하위 엔티티**: BoardParsingOverride(1:N), TemplateChunkingRule(1:N) — §3.1 참조

- 상세: [ADR-009](../../adr/009-search-config-singleton-merge.md), [04-search-tuning](../flows/search-rag/04-search-tuning.md) §2

### 6.6 SearchLog 엔티티 — 검색 이력

검색 이력은 금융권 감사 대비 핵심 요구사항이다 ([UC-SCH](../usecases/user/UC-SCH-검색.md) 시나리오 6). SearchLog는 **검색 모듈** 소속으로, 감사 로그(FD-AUD)와 별도로 관리한다. 감사 로그는 관리자 액션(설정 변경, 인덱스 재구성 등)을 기록하고, SearchLog는 사용자 검색 행위를 기록한다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID, PK | — |
| `user_id` | UUID, FK(User), NOT NULL | 검색 실행자 |
| `tenant_id` | UUID, FK(Tenant), NOT NULL | 테넌트 |
| `query` | TEXT, NOT NULL | 검색어 (키워드) 또는 질의 (RAG) |
| `search_type` | ENUM(`keyword`, `rag`), NOT NULL | 검색 방식 |
| `filters` | JSONB, NULL | 적용된 필터 조건 (board_ids, date_range, tag_ids, template_id 등) |
| `result_count` | INTEGER, NOT NULL | 검색 결과 건수 |
| `clicked_document_ids` | UUID[], NULL | 사용자가 클릭한 문서 ID 목록 (이벤트 기반 비동기 수집) |
| `rag_source_chunk_ids` | UUID[], NULL | RAG 답변 생성 시 참조한 청크 ID 목록 (`search_type = rag`일 때) |
| `rag_confidence_score` | DECIMAL(3,2), NULL | RAG 답변 전체 신뢰도 점수 (`search_type = rag`일 때) |
| `response_time_ms` | INTEGER, NOT NULL | 검색 응답 시간 (밀리초) |
| `created_at` | TIMESTAMP, NOT NULL | 검색 실행 시각 |

**[BR-SCH-025] 보관 정책**: 최소 **5년** 보관 — 금융권 감사 증빙 요구사항. 보관 기간 경과 후 콜드 스토리지 아카이빙 또는 삭제는 관리자 설정에 따름.

**조회/내보내기**: 관리자 대시보드에서 기간·사용자·게시판·검색 방식별 필터링 조회, CSV/PDF 내보내기 지원 ([UC-SCH](../usecases/user/UC-SCH-검색.md) 시나리오 6).

### 6.7 SearchFilterPreset 엔티티 — 검색 필터 프리셋

사용자가 자주 사용하는 검색 필터 조합을 저장하고 재사용한다 ([UC-SCH-03](../usecases/user/UC-SCH-검색.md)).

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID, PK | — |
| `user_id` | UUID, FK(User), NOT NULL | 소유자 |
| `name` | VARCHAR(100), NOT NULL | 프리셋 이름 (예: "CS팀 FAQ만 보기") |
| `filters` | JSONB, NOT NULL | 필터 조건 (`{ board_ids, date_range, author_id, tag_ids, template_id, bookmark_only }`) |
| `sort_order` | INTEGER, NOT NULL | 표시 순서 |
| `created_at` | TIMESTAMP, NOT NULL | 생성 시각 |
| `updated_at` | TIMESTAMP, NOT NULL | 수정 시각 |

**비즈니스 규칙:**

- **[BR-SCH-026]** 사용자당 저장 상한: 기본값 **20개** (관리자 설정 가능). 상한 도달 시 "저장 가능한 필터 수를 초과했습니다" 안내 + 에러 코드 `SCH_PRESET_LIMIT_EXCEEDED`
- **[BR-SCH-027]** 필터 대상 게시판 삭제 시: 해당 필터 적용 시 삭제된 게시판 조건을 제외하고 나머지 조건만으로 검색 실행 + 안내 메시지
- **[BR-SCH-028]** 필터 대상 태그 삭제/병합 시: 태그 병합된 경우 새 태그명으로 자동 전환, 태그 삭제된 경우 해당 조건 제외 + 안내 메시지

---

## 7. 검색 요청/응답 스키마

### 7.1 키워드 검색

**요청 (SearchRequest)**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `query` | string | O | 검색어 |
| `filters.board_ids` | UUID[] | — | 대상 게시판 (하위 포함 옵션) |
| `filters.date_range` | `{ from, to }` | — | 기간 필터 |
| `filters.author_id` | UUID | — | 작성자 필터 |
| `filters.tag_ids` | UUID[] | — | 태그 필터 |
| `filters.template_id` | UUID | — | 문서 양식(템플릿) 필터 |
| `filters.bookmark_only` | boolean | — | 내 북마크에서만 검색 |
| `sort` | enum | — | 정렬 기준 (`relevance` / `newest` / `popular`), 기본값: `relevance` |
| `page` | integer | — | 페이지 번호, 기본값: `1` |
| `size` | integer | — | 페이지당 결과 수, 기본값: `20` |

**응답 (SearchResponse)**

| 필드 | 타입 | 설명 |
|------|------|------|
| `results` | SearchResultItem[] | 검색 결과 목록 |
| `total` | integer | 전체 결과 수 |
| `page` | integer | 현재 페이지 |
| `total_pages` | integer | 전체 페이지 수 |
| `spell_suggestion` | string, NULL | 오타 교정 제안어 |

**SearchResultItem**

| 필드 | 타입 | 설명 |
|------|------|------|
| `document_id` | UUID | 문서 ID |
| `title` | string | 문서 제목 |
| `snippet` | string | 본문 발췌 (하이라이팅 마크업 포함) |
| `highlights` | `{ field: string[] }` | 필드별 하이라이팅 텍스트 |
| `score` | number | 검색 관련도 스코어 |
| `board_id` | UUID | 소속 게시판 ID |
| `board_name` | string | 소속 게시판명 |
| `author_name` | string | 작성자명 |
| `tags` | string[] | 태그 목록 |
| `embedding_status` | enum | 임베딩 상태 (`completed` / `pending` / `processing` / `failed` / `partial`) |
| `published_at` | timestamp | 게시 시각 |
| `is_admin_bypass` | boolean | 메타정보 바이패스(AdminPermission 기반) 접근 여부 — `true`이면 `snippet`, `highlights` 제외 (필드명은 호환용) |

### 7.2 RAG 검색

**요청 (RagSearchRequest)**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `query` | string | O | 자연어 질의 |
| `filters.board_ids` | UUID[] | — | 대상 게시판 (하위 게시판 포함 옵션) |
| `filters.tag_ids` | UUID[] | — | 태그 필터 |
| `filters.template_id` | UUID | — | 문서 양식 필터 |
| `answer_style` | enum | — | 답변 스타일 (`concise` / `detailed`), 기본값: `concise` |

**응답 (RagSearchResponse)**

| 필드 | 타입 | 설명 |
|------|------|------|
| `answer` | string | AI 생성 답변 (스트리밍 시 청크 단위 전달) |
| `confidence_score` | number | 전체 답변 신뢰도 점수 (0.0~1.0) |
| `disclaimer` | string | 면책 문구 |
| `sources` | RagSource[] | 출처 문서 목록 |
| `chunks` | RagChunk[] | 참조된 청크 상세 |

**RagSource**

| 필드 | 타입 | 설명 |
|------|------|------|
| `document_id` | UUID | 출처 문서 ID |
| `title` | string | 출처 문서 제목 |
| `board_name` | string | 소속 게시판명 |
| `relevance_score` | number | 관련도 스코어 |

**RagChunk**

| 필드 | 타입 | 설명 |
|------|------|------|
| `chunk_id` | UUID | 청크 ID |
| `document_id` | UUID | 원본 문서 ID |
| `content` | string | 청크 텍스트 |
| `similarity_score` | number | 벡터 유사도 스코어 |
| `grounded` | boolean | grounding check 통과 여부 |

### 7.3 검색 튜닝 관리 API

관리자(`manage_search`)가 SearchConfig를 조회·수정하는 엔드포인트.

**SearchConfig 조회 — `GET /admin/search/config`**

| 응답 필드 | 타입 | 설명 |
|-----------|------|------|
| `config` | SearchConfigDto | §6.5 SearchConfig 전체 필드 + `version` |
| `synonyms` | SynonymGroupDto[] | 동의어 그룹 목록 |
| `stop_words` | StopWordDto[] | 불용어 목록 |
| `boost_rules` | BoostRuleDto[] | 부스팅 규칙 목록 |
| `board_rag_configs` | BoardRagConfigDto[] | 게시판별 RAG 오버라이드 |

**SearchConfig 수정 — `PUT /admin/search/config`**

| 요청 필드 | 타입 | 필수 | 설명 |
|-----------|------|------|------|
| `version` | integer | O | 현재 버전 — BR-SCH-031 OCC 비교용 |
| `field_weights` | object | — | 필드별 가중치 |
| `hybrid_keyword_weight` | decimal | — | BM25 비중 |
| `hybrid_vector_weight` | decimal | — | 벡터 비중 |
| `default_top_k` | integer | — | 상위 K |
| `default_similarity_threshold` | decimal | — | 유사도 임계값 |
| `reranking_enabled` | boolean | — | 리랭킹 사용 여부 |

- 응답: 수정된 SearchConfigDto + 새 `version`
- 에러: `SCH_CONFIG_VERSION_CONFLICT`(409) 시 최신 config를 응답 본문에 포함

**동의어 관리**

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/admin/search/synonyms` | GET | 동의어 그룹 전체 조회 |
| `/admin/search/synonyms` | POST | 동의어 그룹 추가 — 요청: `{ words: string[] }` |
| `/admin/search/synonyms/:groupId` | PUT | 동의어 그룹 수정 |
| `/admin/search/synonyms/:groupId` | DELETE | 동의어 그룹 삭제 |

**불용어·부스팅·게시판 RAG 설정**도 동일 CRUD 패턴 (`/admin/search/stopwords`, `/admin/search/boost-rules`, `/admin/search/board-rag-configs`).

### 7.4 필터 프리셋 관리 API

사용자가 검색 필터 프리셋을 관리하는 엔드포인트.

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/search/presets` | GET | 내 프리셋 목록 조회 |
| `/search/presets` | POST | 프리셋 저장 — 요청: `{ name, filters, sort_order }`. 상한 초과 시 `SCH_PRESET_LIMIT_EXCEEDED` |
| `/search/presets/:id` | PUT | 프리셋 수정 |
| `/search/presets/:id` | DELETE | 프리셋 삭제 |

**PresetDto**

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | 프리셋 ID |
| `name` | string | 프리셋 이름 |
| `filters` | object | §6.7 SearchFilterPreset.filters와 동일 구조 |
| `sort_order` | integer | 표시 순서 |
| `created_at` | timestamp | 생성 시각 |
| `updated_at` | timestamp | 수정 시각 |

### 7.5 관리자 검색 대시보드 API

관리자(`manage_search`)가 검색 품질·성능 지표를 조회하는 엔드포인트.

**검색 품질 대시보드 — `GET /admin/search/dashboard`**

| 응답 필드 | 타입 | 설명 |
|-----------|------|------|
| `keyword_search.total_count` | integer | 키워드 검색 총 요청 수 (최근 24시간) |
| `keyword_search.zero_result_rate` | decimal | 검색 무결과율 (%) |
| `keyword_search.avg_response_ms` | integer | 평균 응답 시간 (ms) |
| `rag_search.total_count` | integer | RAG 검색 총 요청 수 (최근 24시간) |
| `rag_search.avg_confidence_score` | decimal | 평균 신뢰도 점수 |
| `rag_search.positive_feedback_rate` | decimal | 긍정 피드백 비율 (%) |
| `rag_search.hallucination_rate` | decimal | Hallucination 비율 (신뢰도 < 0.5) |
| `index_status.pending_documents` | integer | 검색 반영 대기 문서 수 |
| `index_status.failed_documents` | integer | 검색 반영 실패 문서 수 |
| `top_keywords` | `{ keyword: string, count: integer }[]` | 인기 검색어 Top 10 |
| `zero_result_keywords` | `{ keyword: string, count: integer }[]` | 무결과 검색어 Top 10 |

**검색 이력 조회 — `GET /admin/search/logs`**

| 요청 필드 | 타입 | 필수 | 설명 |
|-----------|------|------|------|
| `from` | timestamp | — | 조회 시작 시각 |
| `to` | timestamp | — | 조회 종료 시각 |
| `search_type` | enum | — | `keyword` \| `rag` |
| `user_id` | UUID | — | 특정 사용자 필터 |
| `page` | integer | — | 페이지 번호, 기본값 1 |
| `size` | integer | — | 페이지당 건수, 기본값 50 |

- 응답: `Page<SearchLogDto>` — §6.6 SearchLog 엔티티 필드와 동일 구조

---

## 8. 에러 코드

| 에러 코드 | HTTP 상태 | 트리거 | 사용자 메시지 | 관련 BR |
|-----------|----------|--------|-------------|---------|
| `SCH_SEARCH_FAILED` | 503 | ES 검색 시스템 장애 | "검색 서비스에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해 주세요" | — |
| `SCH_RAG_TIMEOUT` | 504 | AI 답변 생성 제한 시간 초과 | "답변 생성에 시간이 너무 오래 걸리고 있습니다. 질문을 짧게 바꾸거나 키워드 검색을 이용해 주세요" | — |
| `SCH_RAG_UNAVAILABLE` | 503 | AI 서비스 장애/연결 불가 | "AI 답변을 생성할 수 없습니다. 키워드 검색을 이용해 주세요" | — |
| `SCH_PERMISSION_DENIED` | 403 | 검색 권한 없음 (열람 가능 게시판 0개) | "검색 권한이 없습니다. 관리자에게 문의해 주세요" | BR-SCH-003 |
| `SCH_PRESET_LIMIT_EXCEEDED` | 422 | 필터 프리셋 저장 상한 초과 | "저장 가능한 필터 수를 초과했습니다. 기존 필터를 삭제한 후 다시 저장해 주세요" | BR-SCH-026 |
| `SCH_CHUNKING_FAILED` | 500 (내부) | 청킹 파이프라인 오류 | — (관리자 알림, 사용자 비노출) | BR-SCH-012 |
| `SCH_INDEX_REBUILD_FAILED` | 500 (내부) | ES 인덱스 재구성 실패 | — (관리자 알림, 기존 인덱스 유지) | BR-SCH-024 |
| `SCH_SYNONYM_CONFLICT` | 422 | 동의어가 불용어 목록에 존재하거나 순환 참조 | "등록하려는 동의어가 제외어 목록에 포함되어 있습니다" | — |
| `SCH_CONFIG_VERSION_CONFLICT` | 409 | SearchConfig/ParsingConfig 저장 시 version 불일치 | "다른 관리자가 설정을 먼저 변경했습니다. 최신 설정을 확인한 후 다시 저장해 주세요" | BR-SCH-031 |
| `SCH_CONFIG_SYNC_FAILED` | 500 (내부) | SearchConfig 동기화 실패 (retrieval-service 이벤트 처리 실패) | — (관리자 알림, 재시도 스케줄링) | BR-SCH-024 |
| `SCH_NO_RESULTS` | 200 | 검색 결과 0건 (정상 응답) | "검색 결과가 없습니다" + 검색어 수정/오타 교정 제안 | — |
| `SCH_RAG_NO_SOURCES` | 200 | RAG 참고 문서 0건 (정상 응답) | "관련 문서를 찾을 수 없습니다. 다른 표현으로 질문해 보세요" | — |

---

## 9. 이벤트 계약

### 9.1 발행 이벤트 (search 모듈 → 외부)

| 이벤트명 | 트리거 | 소비자 | 페이로드 |
|----------|--------|--------|---------|
| `search.config.updated` | SearchConfig 저장 | retrieval-service | `{ config_id, changed_fields: string[], requires_reindex: boolean }` |
| `search.reindex.completed` | ES 인덱스 재구성 완료 | notification | `{ scope: 'full' \| 'partial', duration_ms, document_count, triggered_by }` |
| `search.reindex.failed` | ES 인덱스 재구성 실패 | notification | `{ scope, error_code, error_message, triggered_by }` |

**전송 채널**: `search.*` 이벤트는 BullMQ `search-events` 큐로 발행한다. `search.config.updated`는 재시도 3회(지수 백오프, 초기 1초, 최대 30초), `search.reindex.*`는 재시도 없음(알림 전용).

### 9.2 소비 이벤트 (외부 → search 모듈)

| 이벤트명 | 발행 모듈 | search 모듈 처리 |
|----------|----------|-----------------|
| `document.published` | document | ES 인덱스에 문서 추가 + 청킹 작업을 임베딩 큐(FD-EMB)에 발행 |
| `document.content-updated` | document | ES 인덱스 갱신 + content_hash 비교 후 변경 블록만 재청킹 |
| `document.deleted` | document | ES 인덱스에서 문서 제거 + 벡터 DB 청크 삭제 |
| `document.suspended` | document | ES 인덱스 `is_suspended` 메타데이터 갱신 (검색 시 필터 적용) |
| `document.unsuspended` | document | ES 인덱스 `is_suspended` 메타데이터 복원 |
| `shared-content.updated` | shared-content | 해당 공통 컨텐츠를 참조하는 모든 문서의 재청킹 트리거 |
| `block.visibility-changed` | document | 해당 블록의 `embeddable`/`visible` 플래그에 따라 재청킹/재임베딩 트리거 |

### 9.3 청킹 작업 페이로드

청킹 완료 후 [FD-EMB](FD-EMB-임베딩파이프라인.md) §1.4 임베딩 큐(Bull/Redis)에 발행하는 작업 페이로드:

```
{
  document_id: UUID,
  version: number,
  changed_block_ids: UUID[] | null,   // null이면 전체 블록 대상
  chunking_config: {
    strategy: 'fixed_token' | 'semantic' | 'sliding_window',
    chunk_size: number,
    overlap_percent: number,
    template_rule: string | null       // TemplateChunkingRule 적용 시
  },
  priority: 'high' | 'normal' | 'low'  // 신규 배포 > 수정 > 대량 재처리
}
```

---

## 10. 비기능 요구사항

[UC-SCH](../usecases/user/UC-SCH-검색.md) 운영 참고 시나리오 §운영 4의 KPI 기준값을 기능정의서 수준으로 승격한다.

### 10.1 성능 SLA

| 지표 | 목표값 | 비고 |
|------|--------|------|
| 키워드 검색 응답 시간 (p95) | **1초 이내** | 상담사 통화 중 검색 시나리오 기준 |
| RAG 답변 검색 응답 시간 (p95) | **5초 이내** | LLM 생성 포함, 스트리밍 첫 토큰 기준 |
| 검색 서비스 가용률 | **99.5% 이상** | 월 기준 |
| 검색 반영 대기 문서 수 | **50건 미만** | 초과 시 관리자 경고 알림 |
| 검색 반영 실패 문서 수 | **10건 미만** | 초과 시 관리자 경고 알림 |

### 10.2 품질 KPI

| 지표 | 기준값 | 비고 |
|------|--------|------|
| 검색 무결과율 | **20% 미만** | 초과 시 문서 보강 알림 |
| AI 답변 긍정 피드백 비율 | **60% 이상** | 미달 시 품질 점검 알림 |
| Hallucination 비율 (신뢰도 < 0.5) | 모니터링 | 임계값 초과 시 프롬프트/청킹 전략 조정 |

### 10.3 데이터 보관

| 대상 | 보관 기간 | 근거 |
|------|----------|------|
| 검색 이력 (SearchLog) | **최소 5년** | 금융권 감사 증빙 — [UC-SCH](../usecases/user/UC-SCH-검색.md) 시나리오 6 |
| 검색 설정 변경 이력 | 감사 로그 보관 정책에 따름 | [FD-AUD](FD-AUD-감사로그.md) — 감사 로그에서 집중 관리 |

---

## 비즈니스 규칙 카탈로그

| BR-ID | 섹션 | 규칙명 | 트리거 | 조건 | 동작 |
|-------|------|--------|--------|------|------|
| BR-SCH-001 | §1 | 필드별 키워드 검색 | 검색 실행 | 키워드 입력 | 제목, 본문, 태그, 작성자 필드에서 검색 |
| BR-SCH-002 | §1 | nori 형태소 분석 | 키워드 검색 실행 | 한국어 검색어 | nori 형태소 분석기로 어근 매칭 |
| BR-SCH-003 | §1 | 게시판 권한 필터 | 검색 결과 반환 | 사용자 BoardPermission(VIEW) 미보유 | 해당 게시판 문서 결과 제외 |
| BR-SCH-004 | §1 | 메타정보 바이패스 결과 제한 | 검색 결과 반환 | VIEW 없이 메타정보 바이패스만 가능 | 메타정보만 표시, 스니펫·하이라이팅 제거 |
| BR-SCH-005 | §1 | Restriction 문서 검색 제외 | 검색 결과 반환 | restricted=true, 사용자가 허용 목록 외 | 결과에서 완전 제외 (존재 비노출) |
| BR-SCH-006 | §2 | RAG 게시판 권한 제한 | RAG 검색 | VIEW 미보유 게시판 | RAG 소스에서 제외 |
| BR-SCH-007 | §2 | 메타정보 바이패스 문서 RAG 제외 | RAG 검색 | VIEW 없이 메타정보 바이패스만 가능 | RAG 소스에서 제외 |
| BR-SCH-008 | §2 | Restriction 문서 RAG 제외 | RAG 검색 | restricted=true, 허용 목록 외 | RAG 소스에서 완전 제외 |
| BR-SCH-009 | §2 | 임베딩 미완료 문서 RAG 제외 | RAG 검색 | embedding_status ∈ {pending, processing} | RAG 제외, BM25 포함 + 상태 표시 |
| BR-SCH-010 | §2 | Hallucination 완화 | RAG 답변 생성 | 항상 | grounding check → 근거 없는 문장 구분, 신뢰도 점수 부여 |
| BR-SCH-011 | §2 | 면책 문구 표시 | RAG 답변 표시 | 항상 | 면책 문구 기본 포함 |
| BR-SCH-012 | §3 | 블록 타입별 청킹 | 문서 published | 블록 에디터 문서 | 블록 타입에 따라 최적 청킹 전략 적용 |
| BR-SCH-013 | §3 | 공통 컨텐츠 수정 시 재청킹 | 공통 컨텐츠 원본 수정 | 참조 블록 존재 | 참조 블록 포함 문서 전체 재청킹 |
| BR-SCH-014 | §3 | 파일 업로드 자동 청킹 | 파일 첨부 문서 published | PDF/DOCX/HWP/PPTX | 텍스트 추출 → 자동 청킹 |
| BR-SCH-015 | §3 | HWP 이중 파이프라인 | HWP 텍스트 추출 | 확장자 분기 | HWPX→XML, 구 HWP→LibreOffice→DOCX |
| BR-SCH-016 | §3 | 템플릿 기반 청킹 분기 | 청킹 실행 | template_id 설정됨 | TemplateChunkingRule에 따라 전략 분기 |
| BR-SCH-017 | §3 | 청킹 메타데이터 부착 | 청킹 완료 | 항상 | 문서 ID, 블록 ID, 블록 타입, 섹션 제목, 템플릿 ID |
| BR-SCH-018 | §3 | 문서 수정/삭제 시 청크 동기화 | 문서 수정/삭제 | 벡터 DB에 기존 청크 존재 | 재청킹 또는 삭제 |
| BR-SCH-019 | §4 | 블록 임베딩/가시성 토글 | 블록 메뉴 토글 | 사용자 선택 | embeddable/visible 플래그 변경 → 청킹 스킵/포함 |
| BR-SCH-020 | §4 | 임베딩O+가시성X 미허용 | 가시성 설정 | embeddable=true, visible=false | 설정 차단 (출처 검증 원칙) |
| BR-SCH-021 | §4 | 플래그 변경 시 재처리 | 플래그 변경 | published 문서 | 해당 블록만 재청킹/재임베딩 트리거 |
| BR-SCH-022 | §5 | 중첩 표 2depth 제한 | 중첩 표 파싱 | 중첩 깊이 > 2 | 2depth 초과 무시, 레이아웃 표 제거 |
| BR-SCH-023 | §5 | 이미지 멀티모달 분석 | 이미지 블록 처리 | 이미지 포함 | LLM Orchestrator 경유 → 설명 텍스트 생성 |
| BR-SCH-024 | §6.5 | 설정 변경 캐시 무효화 | SearchConfig 저장 | 설정 변경됨 | 이벤트 발행 → retrieval-service 캐시 무효화 |
| BR-SCH-025 | §6.6 | 검색 이력 5년 보관 | 검색 이력 저장 | 항상 | 최소 5년 보관 (금융권 감사) |
| BR-SCH-026 | §6.7 | 필터 프리셋 저장 상한 | 프리셋 저장 | 사용자당 ≥ 상한(기본 20개) | 저장 차단 + 안내 |
| BR-SCH-027 | §6.7 | 프리셋 게시판 삭제 처리 | 프리셋 적용 | 필터 내 게시판 삭제됨 | 해당 조건 제외 + 나머지로 검색 + 안내 |
| BR-SCH-028 | §6.7 | 프리셋 태그 변경 처리 | 프리셋 적용 | 필터 내 태그 삭제/병합 | 병합 시 자동 전환, 삭제 시 조건 제외 + 안내 |
| BR-SCH-029 | §1 | 긴급 검색 제외(키워드) | 관리자 긴급 제외 실행 | search_excluded=true | 키워드 검색 결과에서 완전 제외, 감사 로그 기록 |
| BR-SCH-030 | §2 | 긴급 검색 제외(RAG) | 관리자 긴급 제외 실행 | search_excluded=true | RAG 소스에서 완전 제외 (Milvus 스칼라 필터) |
| BR-SCH-031 | §6.5 | 설정 저장 OCC | SearchConfig/ParsingConfig 저장 | version 불일치 | 저장 차단 + SCH_CONFIG_VERSION_CONFLICT(409) |

---

## 결정 사항

| 항목 | 결정 | 근거 | 날짜 |
|------|------|------|------|
| 멀티 언어 검색 | **한국어 전용** — 향후 확장 시 다국어 검색은 별도 Phase에서 검토 | 금융 컨택센터 KMS 사용자는 한국 상담사. UC의 다국어 흐름은 향후 확장 가능성을 위한 것으로, MVP에서는 한국어 전용 | 2026-03-31 |
| HWP 파일 지원 | **이중 파이프라인**: HWPX→XML, 구 HWP→LibreOffice→DOCX | 금융권 레거시 대응 | 2026-03-25 |
| 이미지 분석 모델 | **필수 + LLM Orchestrator 경유** | 온프렘/SaaS 공통 | 2026-03-25 |
| 중첩 표 파싱 깊이 | **2depth** + 셀 병합 처리 전략 | 금융 문서의 과제는 셀 병합 | 2026-03-25 |
| 블록 가시성 "임베딩O + 가시성X" | **미허용** | 출처 검증 원칙 | 2026-03-25 |
| 대화 컨텍스트 | **Phase 2** — MVP에서는 단발 질의만 지원 | UC-SCH-02 대안 흐름과 일치, 대화 세션 저장소 설계는 Phase 2에서 별도 진행 | 2026-03-31 |
| 설정 변경 동기화 | **캐시 + 이벤트 기반 무효화** | retrieval-service가 설정을 캐싱하되, `search.config.updated` 이벤트로 무효화하여 직접 API 호출 의존 제거 | 2026-03-31 |
| 이벤트 정의 책임 | **발행측 모듈에서 정의** | search 모듈이 발행하는 이벤트는 FD-SCH에서 정의, document 모듈이 발행하는 이벤트는 FD-DOC에서 정의 | 2026-03-31 |
| 감사 액션 관리 | **FD-AUD에서 집중 관리** | 검색 설정 변경, 인덱스 재구성 등 관리자 액션의 감사 로그 기록 규칙은 FD-AUD에 위임 | 2026-03-31 |

---

## 관련 문서

| 문서 | 설명 |
|------|------|
| [FD-DOC](FD-DOC-문서관리.md) | 블록 에디터(§2), 템플릿(§4), 공통 컨텐츠(§5), 게시판 트리(§7), 태그(§8) |
| [FD-EMB](FD-EMB-임베딩파이프라인.md) | 임베딩 상태 관리(§1), 상태 변경 시 임베딩 전략(§2) |
| [FD-AI](FD-AI-AI어시스턴트.md) | 문서 요약(§1), 프롬프트 관리(§3) — RAG 답변 생성과 연동 |
| [FD-ACL](FD-ACL-권한체계.md) | 권한 체계(§4 메타정보 VIEW 바이패스), 접근 제한(§8 Restriction) |
| [FD-AUD](FD-AUD-감사로그.md) | 감사 로그 — 검색 설정 변경, 인덱스 재구성 등 관리자 액션 기록 |
| [UC-SCH](../usecases/user/UC-SCH-검색.md) | 검색 유즈케이스 (UC-SCH-01~03) |
| [UC-ADM-검색파이프라인](../usecases/admin/UC-ADM-검색파이프라인.md) | 관리자 검색 설정(UC-ADM-07), 임베딩 모니터링(UC-ADM-09) |
| [검색/RAG 흐름도](../flows/search-rag/) | 파싱→청킹→임베딩→검색 파이프라인 |
| [ADR-009](../../adr/009-search-config-singleton-merge.md) | SearchConfig/ParsingConfig 분리 결정 |

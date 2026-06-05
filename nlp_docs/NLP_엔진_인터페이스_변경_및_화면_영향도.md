# NLP 엔진 인터페이스 변경 및 ai-agent-service 화면 영향도 분석

> **구 엔진**: `nlp_engine_service` (통합형 NLP 서비스)
> **신 엔진**: `nlp_engine_finetune_service` (학습 전용 서비스)
> **연동 서비스**: `ai-agent-service` (NLP 엔진 호출측)
> **작성일**: 2026-02-23

---

## 목차

1. [인터페이스 변경 상세 분석](#1-인터페이스-변경-상세-분석)
2. [ai-agent-service 화면 영향도 분석](#2-ai-agent-service-화면-영향도-분석)
3. [인터페이스 변경 설계 의도 분석](#3-인터페이스-변경-설계-의도-분석)

---

## 1. 인터페이스 변경 상세 분석

> 이 섹션은 `ai-agent-service`에서 NLP 엔진을 교체할 때 필요한 인터페이스 변경사항을 상세히 다룬다.

### 1.1 API 엔드포인트 매핑 (구 → 신)

| 구 엔진 엔드포인트 | 신 엔진 엔드포인트 | 변경 내용 |
|---|---|---|
| `POST /api/finetune/request` | `POST /api/finetune/intent` | 경로 변경 + 파라미터 대폭 추가 |
| _(없음)_ | `POST /api/finetune/ner` | **완전 신규** - NER 파인튜닝 |
| _(없음)_ | `POST /api/finetune/mecab` | **완전 신규** - MeCab 사전 생성 |
| `GET /api/trained_models/get_models` | `GET /api/training/jobs` | 경로 변경 + 응답 구조 변경 |
| `POST /api/trained_models/promote_model` | _(확인 필요)_ | 모델 프로모션 방식 변경 가능 |
| `POST /api/analysis/analyze_text` | _(구 엔진 유지)_ | 추론은 여전히 구 엔진이 담당 |
| `POST /api/dictionaries/refresh_dicts` | `POST /api/finetune/mecab` | 수동 새로고침 → 파이프라인 기반 생성으로 변경 |
| _(없음)_ | `POST /api/finetune/status` | **신규** - 범용 태스크 상태 조회 |
| _(없음)_ | `GET /api/training/jobs/{id}` | **신규** - 학습 작업 상세 조회 |
| _(없음)_ | `GET /api/training/jobs/{id}/epochs` | **신규** - 에폭별 로그 조회 |

### 1.2 Intent 파인튜닝 요청 파라미터 변경

#### 현재 ai-agent-service가 보내는 요청 (구 엔진)

```json
{
  "tenant_id": "tenant_001",
  "workspace_id": "ws_001",
  "task_id": "advisor",
  "name": "intent_model_v1",
  "dataset_obj_name": "ce/datasets/ws_001/{checksum}/snapshot-{timestamp}.ndjson",
  "epochs": 50
}
```

- `ai-agent-service`의 `ModelService.requestTraining()`에서 호출
- `task_id`는 항상 `"advisor"` (상수)
- `dataset_obj_name`은 ai-agent-service가 직접 생성하여 MinIO에 업로드한 NDJSON 경로
- 파라미터가 6개로 단순

#### 신 엔진에 보내야 하는 요청

```json
{
  "workspace_id": "ws_001",
  "task_id": "advisor",
  "model_name": "intent_model_v1",
  "dataset_obj_name": "datasets/{checksum}/snapshot-{timestamp}.ndjson",

  "augment_enabled": true,
  "augment_platform": "hybrid",
  "augment_total_per_intent": 100,
  "augment_max_context_turns": 4,
  "augment_singleton_ratio": 0.3,
  "augment_multiturn_ratio": 0.7,
  "augment_no_intent_ratio": 0.1,
  "augment_turn_distribution": "{\"1\": 0.1, \"2\": 0.2, \"3\": 0.3, \"4\": 0.4}",

  "epochs": 50,
  "batch_size": 8,
  "learning_rate": 2e-5,
  "max_seq_length": 512,
  "val_ratio": 0.15,
  "test_ratio": 0.15,
  "random_state": 42,
  "seed": null,
  "base_model_name": "monologg/kobert-lm"
}
```

#### 파라미터별 변경 분석

| 파라미터 | 구 엔진 | 신 엔진 | 변경 이유 |
|---------|--------|--------|----------|
| `tenant_id` | 요청 본문에 포함 | **제거** (헤더 인증에서 추출) | 보안 강화 - 본문에 tenant_id를 넣으면 위변조 가능 |
| `name` | `name` | `model_name` | 필드명 명확화 |
| `dataset_obj_name` | 전체 경로 (prefix 포함) | **상대 경로만** (`ce/` prefix 제외) | 경로 규칙 표준화 - 서버가 prefix를 자동 추가 |
| `generated_data_path` | _(없음)_ | **신규** (상호 배타적) | LLM 생성 데이터 재사용 지원 |
| `augment_enabled` | _(없음)_ | **신규** (기본 true) | LLM 데이터 증강 활성화/비활성화 제어 |
| `augment_platform` | _(없음)_ | **신규** (기본 "hybrid") | LLM 플랫폼 선택 (openai/google/hybrid) |
| `augment_total_per_intent` | _(없음)_ | **신규** (기본 100) | Intent별 생성 데이터 양 제어 |
| `augment_singleton_ratio` | _(없음)_ | **신규** (기본 0.3) | 싱글턴 vs 멀티턴 비율 제어 |
| `augment_multiturn_ratio` | _(없음)_ | **신규** (기본 0.7) | 멀티턴 비율 제어 |
| `augment_max_context_turns` | _(없음)_ | **신규** (기본 4) | 멀티턴 최대 턴 수 |
| `augment_no_intent_ratio` | _(없음)_ | **신규** (기본 0.1) | no_intent 데이터 비율 |
| `augment_turn_distribution` | _(없음)_ | **신규** (기본 null) | 턴 수별 세부 분포 제어 |
| `batch_size` | _(없음, 고정값)_ | **신규** (기본 8) | 학습 하이퍼파라미터 외부 제어 |
| `learning_rate` | _(없음, 고정 2e-5)_ | **신규** (기본 2e-5) | 학습률 외부 제어 |
| `max_seq_length` | _(없음, 고정 256)_ | **신규** (기본 512) | 시퀀스 길이 확장 및 외부 제어 |
| `val_ratio` | _(없음, 고정 0.2)_ | **신규** (기본 0.15) | 데이터 분할 비율 제어 |
| `test_ratio` | _(없음, 고정 0.2)_ | **신규** (기본 0.15) | 데이터 분할 비율 제어 |

### 1.3 경로(Path) 규칙 변경

구 엔진과 신 엔진의 가장 혼동되기 쉬운 변경점 중 하나가 **MinIO 경로 규칙**이다.

#### 구 엔진: 전체 경로 직접 전달

```
ai-agent-service가 직접 전체 경로를 구성:
  "dataset_obj_name": "ce/datasets/ws_001/abc123/snapshot-20260223.ndjson"
                       ^^^ prefix 포함

NLP 엔진이 이 경로를 그대로 사용해서 MinIO에서 다운로드
```

#### 신 엔진: 상대 경로만 전달 (prefix 자동 추가)

```
ai-agent-service가 상대 경로만 전달:
  "dataset_obj_name": "datasets/ws_001/abc123/snapshot-20260223.ndjson"
                       ^^^ prefix 없음!

신 엔진이 자동으로 prefix 추가:
  Seed 데이터: "ce/{workspace_id}/" + 상대경로
  생성 데이터: "nlp/{workspace_id}/" + 상대경로
  
⚠️ 주의: "ce/" 또는 "nlp/" prefix가 포함되면 400 에러 발생!
```

**변경 이유**:
- CE 영역(시드 데이터)과 NLP 영역(생성 데이터/모델)을 명확히 분리
- workspace_id 기반 자동 라우팅으로 잘못된 경로 접근 방지
- 호출자가 내부 경로 구조를 몰라도 되도록 추상화

### 1.4 응답 형식 변경

#### 파인튜닝 요청 응답

```
[구 엔진 응답]
{
  "name": "intent_model_v1",
  "task_id": "celery-task-uuid",     ← Celery Task ID
  "train_ratio": 0.6,
  "val_ratio": 0.2,
  "test_ratio": 0.2,
  "epochs": 50
}

[신 엔진 응답]
{
  "celery_task_id": "celery-task-uuid",  ← 필드명 변경!
  "status": "QUEUED",                    ← 신규
  "message": "queued",                   ← 신규
  "name": "intent_model_v1",
  "workspace_id": "ws_001",              ← 신규
  "pipeline_type": "intent",             ← 신규 (intent/ner/mecab)
  "train_ratio": 0.7,
  "val_ratio": 0.15,
  "test_ratio": 0.15,
  "epochs": 50
}
```

**핵심 변경**: `task_id` → `celery_task_id` (필드명 변경)
- ai-agent-service에서 `nluJobId`로 저장하는 값의 소스 필드가 변경됨

#### 학습 상태 조회

```
[구 엔진]
별도 학습 상태 API 없음 → Redis Stream으로만 상태 수신

[신 엔진]
POST /api/finetune/status 로 직접 조회 가능 (Pull 방식 추가)
+ Redis Stream도 병행 가능 (Push 방식)
```

#### 학습 모델 목록 조회

```
[구 엔진 - GET /api/trained_models/get_models]
{
  "total": 10,
  "page": 1,
  "limit": 20,
  "models": [{
    "id": "registry-uuid",
    "stage": "production",
    "active_run_id": "metadata-uuid",
    "eval_acc": 0.95,
    "num_intents": 15,
    "num_similar_queries": 300,
    "epoch": 50
  }]
}

[신 엔진 - GET /api/training/jobs]
{
  "total": 10,
  "page": 1,
  "limit": 20,
  "total_pages": 1,                   ← 신규
  "jobs": [{
    "id": "job-uuid",
    "celery_task_id": "celery-uuid",
    "pipeline_type": "intent",         ← 신규 (intent/ner/mecab 구분)
    "model_name": "intent_model_v1",
    "status": "SUCCESS",
    "final_accuracy": 0.95,
    "final_f1": 0.93,                  ← 신규 (F1 스코어 추가)
    "final_loss": 0.12,                ← 신규
    "early_stopped": false,            ← 신규
    "duration_seconds": 3600.5,        ← 신규
    "definition_path": "...",          ← 신규
    "generated_data_path": "...",      ← 신규
    "model_output_path": "..."         ← 신규
  }]
}
```

### 1.5 NER 파인튜닝 인터페이스 (완전 신규)

#### 왜 NER 파인튜닝이 추가되었는가

구 엔진에서는 NER을 사전학습된 범용 모델(`KoELECTRA NER`)로만 처리했다. 이 모델은 인명(PS), 장소(LC), 조직(OG), 날짜(DT), 시간(TI), 수량(QT) 같은 **일반적인 개체명**만 인식할 수 있었다.

그러나 AICC(컨택센터) 도메인에서는 **"상품명", "주문번호", "배송번호", "서비스명"** 같은 **도메인 특화 엔티티**를 인식해야 한다. 범용 NER 모델로는 이를 처리할 수 없었고, 그래서 도메인 엔티티를 학습할 수 있는 NER 파인튜닝 파이프라인이 추가된 것이다.

#### NER 파인튜닝에 필요한 입력 데이터

```json
// 엔티티 정의 파일 (MinIO: ce/{workspace_id}/data/ner/entities.json)
{
  "entities": [
    {
      "tag": "PRODUCT",
      "name": "Product Name",
      "name_ko": "상품명",
      "description": "고객이 문의하는 상품의 이름",
      "examples": ["갤럭시 S25", "아이폰 16", "맥북 프로"],
      "custom_examples": [
        {"text": "갤럭시 S25 울트라", "hint": "삼성 최신 스마트폰"},
        {"text": "에어팟 프로 2", "hint": "애플 무선 이어폰"}
      ]
    },
    {
      "tag": "ORDER_NO",
      "name": "Order Number",
      "name_ko": "주문번호",
      "description": "주문 식별 번호",
      "examples": ["ORD-2024-001", "20240101-12345"],
      "custom_examples": []
    }
  ]
}
```

#### 현재 ai-agent-service에 해당 기능이 있는가?

현재 `ai-agent-service`에는 NER 엔티티를 정의하는 전용 화면/기능이 **없다**. `IntentTemplateVariable` 엔티티가 있지만 이는 인텐트별 템플릿 변수 매핑 용도이며, NER 학습용 엔티티 정의와는 다르다.

### 1.6 MeCab 사전 생성 인터페이스 (변경)

#### 구 엔진: 수동 사전 새로고침

```
POST /api/dictionaries/refresh_dicts
{ "workspace_id": "ws_001" }

→ DB에 저장된 사전 데이터를 읽어 MeCab 사전 재컴파일
→ 사전 데이터 자체는 ai-agent-service에서 별도 관리
```

#### 신 엔진: 어휘 정의 기반 자동 생성

```
POST /api/finetune/mecab
{
  "workspace_id": "ws_001",
  "task_id": "advisor",
  "vocab_definition_path": "data/mecab/vocab_config.json"
}

→ 어휘 정의 파일을 기반으로 LLM이 사전 항목을 자동 생성
→ CSV 형식 사전 파일 생성 및 MinIO 업로드
```

**변경 이유**: 도메인 용어를 수동으로 하나하나 등록하는 대신, 카테고리와 예시만 제공하면 LLM이 관련 용어를 자동 생성하여 사전을 풍부하게 만듦.

---

## 2. ai-agent-service 화면 영향도 분석

> 이 섹션은 `ai-agent-service`에서 신형 NLP 엔진으로 교체할 때 **어떤 화면이 변경/추가되어야 하는지**를 분석한다.

### 2.1 현재 ai-agent-service의 NLP 관련 화면 구조

현재 `ai-agent-service`가 프론트엔드에 제공하는 NLP 관련 API(= 화면 기능)는 다음과 같다:

```
┌──────────────────────────────────────────────────────┐
│              현재 NLP 관련 화면 구성                    │
│                                                      │
│  📂 인텐트 관리 (/nlu-catalog/intents)                │
│     • 인텐트 CRUD (생성/조회/수정/삭제)               │
│     • depth1~4 카테고리 설정                          │
│     • 봇 연결 관리                                    │
│     • 일괄 등록 (JSON/NDJSON/Excel)                  │
│     • 엑셀 내보내기/템플릿                             │
│                                                      │
│  📂 유사질의 관리 (/nlu-catalog/utterances)            │
│     • 유사질의 CRUD                                   │
│     • 인텐트별 유사질의 추가/제거                      │
│     • 중복 체크                                       │
│                                                      │
│  📂 모델 관리 (/nlu-model)                            │
│     • 모델 생성/조회/수정                              │
│     • 학습 요청 (epochs만 설정 가능)                   │
│     • 학습 작업 상태 조회                              │
│     • 활성 모델 변경 (프로모션)                        │
│     • NLU 학습 완료 모델 조회                          │
│                                                      │
│  📂 엔티티 관리 → ❌ 없음                              │
│  📂 NER 학습 → ❌ 없음                                 │
│  📂 MeCab 사전 정의 → ❌ 없음                          │
└──────────────────────────────────────────────────────┘
```

### 2.2 신형 엔진 도입 후 필요한 화면 변경

```
┌──────────────────────────────────────────────────────┐
│           신형 NLP 엔진 적용 후 필요한 화면            │
│                                                      │
│  📂 인텐트 관리 → 변경 없음 (기존 유지)               │
│     (인텐트/유사질의 CRUD는 동일하게 유지)             │
│                                                      │
│  📂 모델 관리 → ⚠️ 대폭 변경 필요                     │
│     [기존] epochs만 설정 가능                         │
│     [변경] 아래 세부 항목 참조                         │
│                                                      │
│  📂 엔티티 정의 관리 → ✨ 완전 신규 화면              │
│                                                      │
│  📂 MeCab 사전 정의 → ✨ 완전 신규 화면               │
│                                                      │
│  📂 학습 이력/모니터링 → ✨ 대폭 강화 가능             │
└──────────────────────────────────────────────────────┘
```

### 2.3 [변경] 모델 학습 요청 화면

#### 현재 화면에서 사용자가 입력하는 것

```
┌────────────────────────────────────────┐
│         Intent 모델 학습 요청           │
│                                        │
│  모델명: [________________]            │
│  에폭:   [50___]                       │
│                                        │
│  [학습 시작]                            │
└────────────────────────────────────────┘

→ 나머지는 시스템이 자동으로 처리:
  - dataset_obj_name: 인텐트+유사질의를 NDJSON으로 변환하여 MinIO 업로드
  - workspace_id, task_id: 세션에서 자동 설정
```

#### 신형 엔진에서 필요한 화면

학습 요청 화면이 3개로 분리되고, 각각 설정할 항목이 크게 늘어난다.

##### A) Intent 학습 요청 화면

```
┌──────────────────────────────────────────────────────┐
│              Intent 모델 학습 요청                     │
│                                                      │
│  ── 기본 설정 ──                                      │
│  모델명: [________________]                           │
│                                                      │
│  데이터 소스:                                         │
│    ○ 새로 생성 (시드 데이터 기반 LLM 증강)            │
│    ○ 기존 생성 데이터 재사용                          │
│                                                      │
│  ── LLM 데이터 증강 설정 ── (새로 생성 선택 시)       │
│  데이터 증강 활성화: [✓]                              │
│  LLM 플랫폼: [hybrid ▾] (openai/google/hybrid)       │
│  Intent별 생성 수: [100__]                            │
│                                                      │
│  ── 대화 유형 비율 설정 ──                             │
│  싱글턴 비율:    [0.3_] ████████░░░░░░░ 30%          │
│  멀티턴 비율:    [0.7_] ██████████████░ 70%          │
│  no_intent 비율: [0.1_] ███░░░░░░░░░░░ 10%          │
│                                                      │
│  ── 멀티턴 상세 설정 ──                               │
│  최대 턴 수: [4__]                                    │
│  턴 분포 (선택):                                      │
│    1턴: [0.1] 2턴: [0.2] 3턴: [0.3] 4턴: [0.4]      │
│                                                      │
│  ── 학습 하이퍼파라미터 (고급) ──                      │
│  에폭:           [50__]                               │
│  배치 크기:       [8___]                               │
│  학습률:          [2e-5]                               │
│  최대 시퀀스 길이: [512_]                              │
│  검증 데이터 비율: [0.15]                              │
│  테스트 비율:     [0.15]                               │
│                                                      │
│  [학습 시작]                                          │
└──────────────────────────────────────────────────────┘
```

**설계 권장사항**:
- LLM 증강 설정과 하이퍼파라미터는 "고급 설정" 토글로 접어둘 수 있게 하면 좋음
- 기본값이 이미 최적화되어 있으므로 일반 사용자는 모델명만 입력하고 학습 시작 가능
- "기존 생성 데이터 재사용" 선택 시 이전 학습의 generated_data_path를 드롭다운으로 제공

##### B) NER 학습 요청 화면 (완전 신규)

```
┌──────────────────────────────────────────────────────┐
│               NER 모델 학습 요청                      │
│                                                      │
│  ── 기본 설정 ──                                      │
│  모델명: [________________]                           │
│                                                      │
│  ── 엔티티 정의 ── (필수)                              │
│  ┌──────────────────────────────────────────────┐    │
│  │ 엔티티 목록                        [+ 추가]  │    │
│  │                                              │    │
│  │ 📌 PRODUCT (상품명)                          │    │
│  │    설명: 고객이 문의하는 상품의 이름           │    │
│  │    예시: 갤럭시 S25, 아이폰 16, 맥북 프로     │    │
│  │    커스텀 예시: 갤럭시 S25 울트라 (삼성 최신)  │    │
│  │    [수정] [삭제]                              │    │
│  │                                              │    │
│  │ 📌 ORDER_NO (주문번호)                        │    │
│  │    설명: 주문 식별 번호                        │    │
│  │    예시: ORD-2024-001, 20240101-12345         │    │
│  │    [수정] [삭제]                              │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ── LLM 데이터 생성 설정 ──                           │
│  LLM 플랫폼: [hybrid ▾]                              │
│  엔티티당 생성 수: [200__]                             │
│                                                      │
│  ── 학습 하이퍼파라미터 (고급) ──                      │
│  에폭:      [5___]                                    │
│  배치 크기:  [16__]                                    │
│  학습률:     [5e-5]                                    │
│  Warmup 비율: [0.1_]                                  │
│  Weight Decay: [0.01]                                 │
│                                                      │
│  [학습 시작]                                          │
└──────────────────────────────────────────────────────┘
```

**핵심 신규 요소**: 엔티티 정의 관리 UI
- 태그(tag), 한국어명, 설명, 예시 목록, 커스텀 예시(hint 포함)를 입력하는 폼
- 이 데이터를 JSON으로 변환하여 MinIO에 업로드 후 `entity_definition_path`로 전달

##### C) MeCab 사전 생성 화면 (완전 신규)

```
┌──────────────────────────────────────────────────────┐
│              MeCab 사전 생성 요청                      │
│                                                      │
│  ── 어휘 정의 ──                                      │
│  도메인: [전자상거래___]                               │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 카테고리 목록                      [+ 추가]  │    │
│  │                                              │    │
│  │ 📁 상품명                                     │    │
│  │    생성 수: [100]                             │    │
│  │    예시: 스마트폰, 노트북, 태블릿              │    │
│  │    [수정] [삭제]                              │    │
│  │                                              │    │
│  │ 📁 브랜드명                                   │    │
│  │    생성 수: [50]                              │    │
│  │    예시: 삼성, LG, 애플                       │    │
│  │    [수정] [삭제]                              │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  LLM 플랫폼: [hybrid ▾]                              │
│                                                      │
│  [사전 생성 시작]                                     │
└──────────────────────────────────────────────────────┘
```

### 2.4 [강화] 학습 이력/모니터링 화면

구 엔진에서는 학습 상태를 Redis Stream 메시지로만 받아 ModelJob의 status만 업데이트했다. 신 엔진에서는 훨씬 상세한 학습 이력 API가 제공되므로, 모니터링 화면을 강화할 수 있다.

#### 현재 모니터링 (구 엔진 연동)

```
┌─────────────────────────────────┐
│       학습 작업 상태             │
│                                 │
│  모델명       상태    생성일     │
│  ──────────  ──────  ─────────  │
│  model_v1   성공     2026-02-20 │
│  model_v2   학습중   2026-02-23 │
└─────────────────────────────────┘
```

#### 가능한 모니터링 (신 엔진 API 활용)

```
┌──────────────────────────────────────────────────────┐
│              학습 작업 이력 (강화)                     │
│                                                      │
│  필터: [파이프라인: 전체 ▾] [상태: 전체 ▾]            │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ intent_model_v2        Intent     성공        │    │
│  │ 2026-02-23 10:00 ~ 11:00 (1시간)             │    │
│  │ Accuracy: 0.95 | F1: 0.93 | Loss: 0.12      │    │
│  │ Early Stopped: No | 에폭: 50/50              │    │
│  │ [상세 보기]                                   │    │
│  ├──────────────────────────────────────────────┤    │
│  │ ner_model_v1           NER       성공         │    │
│  │ 2026-02-22 14:00 ~ 14:30 (30분)              │    │
│  │ Entity F1: 0.91 | Loss: 0.15                 │    │
│  │ Early Stopped: Yes (에폭 3/5)                │    │
│  │ [상세 보기]                                   │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ── 상세 보기 (에폭별 로그) ──                        │
│                                                      │
│  에폭  Train Loss  Val Loss  Train Acc  Val Acc      │
│  ────  ──────────  ────────  ────────  ────────      │
│    1      0.85       0.82     0.75      0.73         │
│    2      0.52       0.48     0.85      0.83         │
│    3      0.31       0.35     0.92      0.90         │
│   ...                                                │
│   50      0.08       0.12     0.98      0.95         │
│                                                      │
│  📈 [학습 곡선 차트] (loss/accuracy 추이)             │
└──────────────────────────────────────────────────────┘
```

### 2.5 화면 변경 우선순위 및 작업 범위 요약

#### 🔴 필수 변경 (신 엔진 연동에 반드시 필요)

| 우선순위 | 화면/기능 | 작업 내용 | 난이도 |
|---------|---------|---------|-------|
| **P0** | Intent 학습 요청 | API 호출부 변경 (엔드포인트, 파라미터, 경로 규칙) | 중 |
| **P0** | 학습 응답 처리 | `task_id` → `celery_task_id` 필드명 매핑 변경 | 하 |
| **P0** | 학습 모델 조회 | `GET /api/trained_models/get_models` → `GET /api/training/jobs` 변경 | 중 |
| **P0** | MinIO 경로 | 전체 경로 → 상대 경로로 변경 (`ce/` prefix 제거) | 하 |

#### 🟡 권장 변경 (신 엔진 기능 활용)

| 우선순위 | 화면/기능 | 작업 내용 | 난이도 |
|---------|---------|---------|-------|
| **P1** | Intent 학습 고급 설정 | LLM 증강 옵션, 멀티턴 설정, 하이퍼파라미터 UI 추가 | 중 |
| **P1** | 데이터 재사용 | `generated_data_path` 선택 UI (이전 생성 데이터 목록) | 중 |
| **P1** | 학습 이력 강화 | 에폭별 로그, F1 스코어, Early Stopping 표시 | 중 |

#### 🟢 신규 추가 (새로운 기능)

| 우선순위 | 화면/기능 | 작업 내용 | 난이도 |
|---------|---------|---------|-------|
| **P2** | 엔티티 정의 관리 | 엔티티 CRUD UI + MinIO 업로드 + NER 학습 요청 | 상 |
| **P2** | NER 학습 요청 | NER 파인튜닝 요청 화면 + 결과 조회 | 상 |
| **P3** | MeCab 사전 정의 | 어휘 카테고리 정의 UI + MeCab 빌드 요청 | 중 |

### 2.6 ai-agent-service 코드 변경 포인트

#### ModelService 변경이 필요한 메서드

```
src/nlu-model/services/model.service.ts

1. requestTraining() (line 363-642)
   변경: API 엔드포인트, 요청 파라미터, 경로 규칙, 응답 파싱

2. getTrainedModelsFromNlu() (line 204-266)
   변경: API 엔드포인트, 응답 구조 매핑

3. promoteModelToNlu() (line 271-361)
   확인: 프로모션 API 존재 여부 및 변경사항 확인 필요

4. (신규) requestNerTraining()
   추가: NER 파인튜닝 요청 메서드

5. (신규) requestMecabBuild()
   추가: MeCab 사전 생성 요청 메서드
```

#### 환경 변수 변경

```
현재: NLU_BASE_URL=http://nlp-engine-service-svc
추가: NLU_FINETUNE_BASE_URL=http://nlp-engine-finetune-service-svc  (학습용)
유지: NLU_BASE_URL=http://nlp-engine-service-svc  (추론용, 변경 없음)
```

- 추론 API(`analyze_text`)는 기존 `nlp_engine_service`를 계속 사용
- 학습 API(`finetune/*`, `training/*`)만 신 엔진으로 변경

#### DB 엔티티 변경 가능성

```
현재 엔티티:
  - NluModel, ModelJob, DatasetManifest → 기존 유지 + 필드 추가 가능

신규 엔티티 후보:
  - EntityDefinition (NER 엔티티 정의 저장)
  - VocabDefinition (MeCab 어휘 정의 저장)
  - ModelJob에 pipeline_type 필드 추가 (intent/ner/mecab 구분)
```

---

## 3. 인터페이스 변경 설계 의도 분석

### 3.1 왜 엔드포인트를 파이프라인별로 분리했는가

```
[구 엔진]  POST /api/finetune/request      ← Intent만 가능
[신 엔진]  POST /api/finetune/intent       ← Intent 전용
           POST /api/finetune/ner          ← NER 전용
           POST /api/finetune/mecab        ← MeCab 전용
```

**설계 의도**:
- 각 파이프라인은 필요한 입력 데이터와 파라미터가 완전히 다름
- Intent는 시드 데이터(NDJSON) + LLM 증강 옵션이 필요
- NER은 엔티티 정의(JSON) + 커스텀 예시가 필요
- MeCab은 어휘 정의(JSON) + 카테고리 설정이 필요
- 하나의 엔드포인트에 모든 파라미터를 넣으면 복잡해지고, 유효성 검증이 어려워짐
- 파이프라인별 분리로 각각의 입력 검증을 명확하게 수행 가능

### 3.2 왜 경로에서 prefix를 제거했는가

**설계 의도**:
- **보안**: 호출자가 임의의 MinIO 경로에 접근하는 것을 방지
- **추상화**: 호출자는 내부 스토리지 구조(`ce/`, `nlp/`)를 알 필요가 없음
- **일관성**: 서버가 workspace_id 기반으로 자동 라우팅하여 잘못된 워크스페이스 데이터 접근 방지
- **유연성**: 내부 경로 구조가 변경되어도 API 호출 코드는 변경 불필요

### 3.3 왜 generated_data_path를 분리했는가

```
[구 엔진]  dataset_obj_name 하나만 사용 → 항상 원본 데이터에서 시작
[신 엔진]  dataset_obj_name (원본) ↔ generated_data_path (생성본) 상호 배타적
```

**설계 의도**:
- LLM 데이터 생성은 시간(수십 분)과 비용(API 호출료)이 소요됨
- 동일 데이터로 하이퍼파라미터만 바꿔서 재학습할 때 LLM 생성을 반복하는 것은 낭비
- 생성 데이터를 저장해두고 재사용함으로써:
  - API 비용 절감
  - 학습 시간 단축 (생성 단계 스킵)
  - 학습 재현성 보장 (동일 데이터로 비교 실험 가능)

### 3.4 왜 학습 파라미터가 대폭 늘어났는가

구 엔진은 `epochs` 1개만 외부에서 제어 가능했고, 나머지(batch_size, learning_rate 등)는 코드에 하드코딩되어 있었다. 신 엔진은 이를 모두 API 파라미터로 노출했다.

**설계 의도**:
- **실험 유연성**: 다양한 하이퍼파라미터 조합을 시도하여 최적 모델 탐색
- **도메인 적응**: 데이터 양, 복잡도에 따라 최적 설정이 다름
- **운영 편의**: 코드 수정 없이 API 호출만으로 설정 변경
- **기본값 최적화**: 모든 파라미터에 합리적인 기본값이 있어 일반 사용자는 건드릴 필요 없음

### 3.5 왜 tenant_id를 요청 본문에서 제거했는가

```
[구 엔진]  요청 본문에 tenant_id 포함 → 위변조 가능
[신 엔진]  X-auth-token 헤더에서만 추출 → 인증 기반 자동 식별
```

**설계 의도**:
- **보안 강화**: 요청 본문의 tenant_id는 클라이언트가 임의로 변경 가능
- **무결성**: 인증 토큰에서 추출한 tenant_id만 신뢰
- **단순화**: 호출자가 tenant_id를 직접 관리할 필요 없음

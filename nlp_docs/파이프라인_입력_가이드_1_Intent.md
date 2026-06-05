# Intent 파이프라인 입력 데이터 가이드

> **대상**: `POST /api/finetune/intent`
> **목적**: Intent(의도) 분류 모델 파인튜닝
> **작성일**: 2026-02-23

---

## 한 줄 요약

> **시드 데이터(NDJSON)에 인텐트별 예시 발화를 넣어주면, LLM이 그걸 보고 싱글턴/멀티턴/no_intent 학습 데이터를 대량으로 자동 생성한다.**

---

## 1. 전체 흐름



```
사용자가 준비하는 것              신 엔진이 자동으로 하는 것
─────────────────────          ──────────────────────────────

┌───────────────────┐          ┌─────────────────────────────┐
│ 시드 데이터 (NDJSON)│          │ LLM이 데이터 대량 생성       │
│                   │    →     │ • 싱글턴 30개/intent         │
│ • 인텐트별 예시 발화│          │ • 멀티턴 70개/intent         │
│ • depth 카테고리   │          │ • no_intent 자동 생성        │
└───────────────────┘          └─────────────────────────────┘
                                          │
                                          ▼
                               ┌─────────────────────────────┐
                               │ KoBERT 모델 학습             │
                               │ • Early Stopping 적용        │
                               │ • 평가 후 모델 저장          │
                               └─────────────────────────────┘
```

---

## 2. 시드 데이터 형식 (NDJSON)

### NDJSON이란?

각 줄이 하나의 독립적인 JSON 객체인 파일 형식이다. 줄바꿈으로 구분된다.

### 파일 예시

```json
{"id": "order_status", "depth1": "주문", "depth2": "배송", "depth3": "배송 조회", "utterances": [{"text": "제 택배 어디쯤 왔나요?", "type": "standard"}, {"text": "배송 추적 좀 해주세요", "type": "similar"}]}
{"id": "order_cancel", "depth1": "주문", "depth2": "취소", "utterances": [{"text": "주문 취소하고 싶어요", "type": "standard"}, {"text": "방금 주문한 거 취소됩니다?", "type": "similar"}]}
{"id": "refund_request", "depth1": "환불", "depth2": "환불 요청", "utterances": [{"text": "환불 받고 싶습니다", "type": "standard"}]}
```

### 가독성 좋게 풀어쓴 구조 (하나의 인텐트)

```json
{
  "id": "order_status",

  "depth1": "주문",
  "depth2": "배송",
  "depth3": "배송 조회",
  "depth4": null,

  "utterances": [
    {
      "text": "제 택배 어디쯤 왔나요?",
      "type": "standard"
    },
    {
      "text": "배송 추적 좀 해주세요",
      "type": "similar"
    },
    {
      "text": "주문번호 {주문번호} 배송 상태 알려주세요",
      "type": "standard"
    }
  ]
}
```

### 필드 설명


| 필드                  | 필수  | 타입     | 설명                                              |
| ------------------- | --- | ------ | ----------------------------------------------- |
| `id`                | 필수  | string | 인텐트 고유 ID. 학습 시 라벨(label)로 사용됨                  |
| `depth1`            | 선택  | string | 1단계 분류 (예: "주문", "환불", "문의")                    |
| `depth2`            | 선택  | string | 2단계 분류 (예: "배송", "취소")                          |
| `depth3`            | 선택  | string | 3단계 분류                                          |
| `depth4`            | 선택  | string | 4단계 분류                                          |
| `utterances`        | 필수  | array  | 해당 인텐트의 예시 발화 목록                                |
| `utterances[].text` | 필수  | string | 발화 텍스트                                          |
| `utterances[].type` | 선택  | string | `"standard"` 또는 `"similar"` (기본값: `"standard"`) |


### depth가 중요한 이유

depth1~4는 LLM이 데이터를 생성할 때 **"어떤 맥락의 발화를 만들어야 하는지"**를 알려주는 가이드 역할을 한다.

```
depth_path 예시: "주문 > 배송 > 배송 조회"

LLM 프롬프트에 이렇게 들어감:
  "상담 유형: 주문 > 배송 > 배송 조회 에 해당하는
   새로운 고객 발화를 생성해주세요."
```

depth가 없으면 LLM이 맥락 없이 발화를 생성하므로, **depth를 넣을수록 생성 품질이 좋아진다.**

### utterances에 몇 개를 넣어야 하나?

- **최소 1개** 이상이면 동작함
- **3~10개** 정도가 적당 (LLM이 참고할 예시가 충분히 있어야 다양한 생성이 가능)
- 너무 적으면 생성 품질 저하, 너무 많으면 프롬프트 길이만 늘어남

---

## 3. LLM 데이터 증강 옵션

시드 데이터를 넣으면 LLM이 **3가지 유형**의 학습 데이터를 자동 생성한다.

### 3.1 싱글턴 (Singleton) - 단일 발화

```
입력 예시 (시드): "배송 추적 좀 해주세요"

LLM이 생성하는 것:
  "택배 어디까지 왔는지 확인해주실 수 있나요?"
  "주문한 물건이 지금 어디에 있는지 알고 싶어요"
  "배송 현황 좀 볼 수 있을까요?"
  ...

→ 맥락(context) 없이 단일 발화만 생성
→ 기본 비율: 전체의 30%
```

### 3.2 멀티턴 (Multiturn) - 대화 맥락 포함

```
LLM이 생성하는 것:

  [이전 대화]
  USER: 어제 주문한 건데요
  AGENT: 네, 주문번호 알려주시겠어요?
  USER: 12345678이요
  AGENT: 확인해보겠습니다.

  [현재 발화 - 이 발화의 intent가 "order_status"]
  USER: 지금 배송이 어디쯤인가요?

→ 이전 대화(context)가 있는 상태에서 마지막 발화의 의도를 분류
→ 기본 비율: 전체의 70%
→ 턴 수 분포: 4턴(50%) > 3턴(25%) > 2턴(15%) > 1턴(10%)
```

### 3.3 no_intent - 의도 없는 발화

```
LLM이 생성하는 것:

  싱글턴 no_intent:
    "네 알겠습니다", "감사합니다", "네네", "좋아요" ...

  멀티턴 no_intent:
    AGENT: 더 필요하신 건 있으신가요?
    USER: "아니요 없어요"  ← 이건 intent가 아님

    AGENT: 환불 처리 완료되었습니다.
    USER: "네 확인했어요"  ← 이것도 intent가 아님

→ 특정 의도가 없는 마무리/확인 발화
→ 기본 비율: 전체 데이터의 10%
```

### 비율 설정 예시

인텐트가 10개이고 기본 설정을 쓴다면:

```
Intent당 생성: 100개
  • 싱글턴: 30개 (30%)
  • 멀티턴: 70개 (70%)

전체 Intent 데이터: 10 × 100 = 1,000개
no_intent 데이터:   1,000 × 0.1 = 100개

총 학습 데이터: 약 1,100개
```

---

## 4. API 파라미터 가이드

### 최소한의 요청 (기본값 사용)

```json
{
  "workspace_id": "ws_001",
  "task_id": "advisor",
  "model_name": "intent_model_v1",
  "dataset_obj_name": "datasets/snapshot-20260223.ndjson"
}
```

이것만 보내면 나머지는 전부 기본값으로 동작한다.

### 전체 파라미터


| 파라미터                        | 기본값                    | 설명                                       |
| --------------------------- | ---------------------- | ---------------------------------------- |
| **기본**                      |                        |                                          |
| `workspace_id`              | (필수)                   | 워크스페이스 ID                                |
| `task_id`                   | (필수)                   | 태스크 ID                                   |
| `model_name`                | (필수)                   | 모델 이름                                    |
| **데이터 소스 (택 1)**            |                        |                                          |
| `dataset_obj_name`          | null                   | 시드 데이터 상대 경로 (새로 생성)                     |
| `generated_data_path`       | null                   | 기존 생성 데이터 경로 (재사용)                       |
| **LLM 증강**                  |                        |                                          |
| `augment_enabled`           | `true`                 | LLM 증강 활성화 여부                            |
| `augment_platform`          | `"hybrid"`             | LLM 플랫폼 (`openai` / `google` / `hybrid`) |
| `augment_total_per_intent`  | `100`                  | 인텐트별 총 생성 수                              |
| `augment_singleton_ratio`   | `0.3`                  | 싱글턴 비율 (30%)                             |
| `augment_multiturn_ratio`   | `0.7`                  | 멀티턴 비율 (70%)                             |
| `augment_no_intent_ratio`   | `0.1`                  | no_intent 비율 (10%)                       |
| `augment_max_context_turns` | `4`                    | 멀티턴 최대 턴 수                               |
| `augment_turn_distribution` | null                   | 턴 수별 분포 JSON                             |
| **학습**                      |                        |                                          |
| `epochs`                    | `50`                   | 학습 에폭 수                                  |
| `batch_size`                | `8`                    | 배치 크기                                    |
| `learning_rate`             | `2e-5`                 | 학습률                                      |
| `max_seq_length`            | `512`                  | 최대 시퀀스 길이                                |
| `val_ratio`                 | `0.15`                 | 검증 데이터 비율                                |
| `test_ratio`                | `0.15`                 | 테스트 데이터 비율                               |
| `base_model_name`           | `"monologg/kobert-lm"` | 베이스 모델                                   |
| `seed`                      | null                   | 학습 시드 (null이면 랜덤)                        |


### 경로 규칙

```
dataset_obj_name에는 상대 경로만 입력:
  ✅ "datasets/snapshot-20260223.ndjson"
  ❌ "ce/ws_001/datasets/snapshot-20260223.ndjson"  ← 400 에러!

서버가 자동으로 prefix 추가:
  시드 데이터 → "ce/{workspace_id}/" + 상대경로
  생성 데이터 → "nlp/{workspace_id}/" + 상대경로
```

---

## 5. 학습 데이터가 최종적으로 어떻게 변환되는가

모든 데이터(싱글턴/멀티턴)는 학습 전에 하나의 텍스트 문자열로 변환된다.

### 싱글턴 → 학습용 텍스트

```
원본: { "text": "배송 추적 좀 해주세요", "context": [] }

변환 결과: "[USER] 배송 추적 좀 해주세요"
라벨: "order_status"
```

### 멀티턴 → 학습용 텍스트

```
원본: {
  "text": "지금 배송이 어디쯤인가요?",
  "context": [
    {"role": "user", "content": "어제 주문한 건데요"},
    {"role": "agent", "content": "네, 주문번호 알려주시겠어요?"},
    {"role": "user", "content": "12345678이요"},
    {"role": "agent", "content": "확인해보겠습니다."}
  ]
}

변환 결과:
  "[USER] 어제 주문한 건데요 [AGENT] 네, 주문번호 알려주시겠어요?
   [USER] 12345678이요 [AGENT] 확인해보겠습니다.
   [USER] 지금 배송이 어디쯤인가요?"

라벨: "order_status"
```

이 변환은 `context_to_text()` 함수가 수행하며, **학습 시와 추론 시 동일한 변환**을 적용해야 한다.

---

## 6. 생성 데이터 재사용

첫 번째 학습 후 LLM이 생성한 데이터는 MinIO에 저장된다. 두 번째 학습부터는 이 데이터를 재사용할 수 있다.

```
[첫 번째 학습]
dataset_obj_name: "datasets/snapshot.ndjson"  → LLM 생성 실행 (수십 분)

[두 번째 학습 - 하이퍼파라미터만 변경]
generated_data_path: "generated/intent/advisor/20260223/model_v1/generated_intent.json"
→ LLM 생성 스킵! 바로 학습 시작
```

**재사용 장점**:

- LLM API 비용 절감
- 학습 시간 단축 (데이터 생성 단계 스킵)
- 동일 데이터로 비교 실험 가능


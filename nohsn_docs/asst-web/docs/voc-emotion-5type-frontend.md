# [프론트 전달] VOC 고객감정 — 3종 → 5종 변경 안내

## 한 줄 요약
실시간/요약 VOC 응답의 **고객 감정(`emotion.type`)** 값이 기존 3종(긍정/중립/부정)에서 **신규 5종**으로 바뀝니다.
**민원위험(complaintRisk) / 이탈징후(churnRisk) 2축은 변경 없습니다.** 점수·근거 구조도 그대로입니다.

---

## 1. 신규 5종 감정 값 (`emotion.type`)

| 영문 키(전달값) | 한글 의미 | 설명 |
|---|---|---|
| `angry` | 화남 | 강한 분노 표출 (욕설·위협·책임자 요구·인격 공격 등) |
| `dissatisfied` | 불만 | 부정적 평가·불편 (차분~중간 강도, 분노까지는 아님) |
| `normal` | 일반 | 감정어 없는 사실·정보 교환 (기본값) |
| `satisfied` | 만족 | 응대·결과에 대한 긍정적 평가 ("잘 처리됐네요" 등) |
| `thanks` | 감사 | 명시적 고마움 표현 ("감사합니다" 등) |

- 우선순위(한 발화에 여러 감정이 겹칠 때 하나만): `angry > dissatisfied > satisfied > thanks > normal`
- `emotion.score`(0~1 감정 강도), `emotion.summary`(근거 한 문장)는 **기존과 동일**.

## 2. ⚠️ 레거시 3종도 들어올 수 있음 (과거 콜이력 한정)

DB에는 이전에 저장된 **레거시 값 3종**이 그대로 남아있습니다. **과거 통화를 조회할 때만** 나타날 수 있습니다.

| 레거시 키 | 매핑되는 신규 의미(참고) |
|---|---|
| `negative` | 부정 (≈ angry/dissatisfied) |
| `neutral` | 중립 (≈ normal) |
| `positive` | 긍정 (≈ satisfied/thanks) |

> **프론트 권장 처리:** `emotion.type` switch에 신규 5종을 추가하되, 레거시 3종도 fallback으로 함께 처리(아이콘/라벨 매핑)해 주세요. 정의되지 않은 값이 오면 `normal` 취급 권장.
> **앞으로 새로 생성되는 통화는 무조건 5종만** 저장/전달됩니다. 레거시 3종은 신규로 절대 생성되지 않습니다.

## 3. 변경이 반영되는 위치 (값 받는 곳)

| 경로 | 설명 | emotion.type |
|---|---|---|
| 실시간 소켓 — `{env}:{vendor_tenant_id}:{cc_cti_id}:call:voc` 채널 payload | 통화 중 실시간 VOC push | **신규 5종** |
| `POST /assist-stream` 흐름이 만들어내는 위 소켓 push | (프론트 추가 호출 없음, 구독만) | **신규 5종** |
| `POST /summary` 응답의 `emotion` | 통화 종료 후 요약 | **신규 5종** |
| `GET /summary/data/{callstats_id}` 응답의 `emotion` | 콜이력 상세조회 | 신규 5종 / 과거건은 레거시 3종 |
| `GET /callstat/calls/{id}` 응답의 `voc.emotion` | 콜이력 상세조회 | 신규 5종 / 과거건은 레거시 3종 |

소켓 payload 형태(변경 없음, `emotion.type` 값만 5종):
```json
{
  "agent_id": "56356659",
  "call_id": "698590897500",
  "turn_idx": 5,
  "emotion":       { "type": "angry", "score": 0.87, "summary": "환불 지연으로 화가 난 상태" },
  "complaintRisk": { "score": 0.6, "summary": "책임자 연결을 요구하며 항의 강도가 높음" },
  "churnRisk":     { "score": 0.3, "summary": "해지를 언급했으나 확정적이지 않음" }
}
```

## 4. 프론트 체크리스트
- [x] `emotion.type` 분기에 신규 5종(`angry/dissatisfied/normal/satisfied/thanks`) 아이콘·라벨 추가
- [x] 레거시 3종(`negative/neutral/positive`) fallback 매핑 유지 (과거 콜이력 표시용)
- [x] 미정의 값은 `normal`로 안전 처리
- [x] `complaintRisk` / `churnRisk` 는 변경 없음 — 그대로 사용

## 5. 프론트 노출 색상/라벨 (확정 — 2026-06-17)

화면에 노출되는 감정 라벨/색상. 단일 소스: `src/utils/emotionVoc.ts` 의 `EMOTION_TYPE_META` / `resolveEmotionType(type)`.

| `emotion.type` | 라벨 | 색상(HEX) | 색 설명 |
|---|---|---|---|
| `angry` | 화남 | `#ef4444` | red |
| `dissatisfied` | 불만 | `#a855f7` | 보라 |
| `normal` | 일반 | `#94a3b8` | 중립색(회색) |
| `satisfied` | 만족 | `#22c55e` | 긍정색(초록) |
| `thanks` | 감사 | `#ec4899` | 핑크 |
| `negative` (레거시) | 부정 | `#ef4444` | red (기존 그대로) |
| `neutral` (레거시) | 중립 | `#94a3b8` | 회색 (기존 그대로) |
| `positive` (레거시) | 긍정 | `#22c55e` | 초록 (기존 그대로) |

- 표시 형식: `● <라벨> : <summary> (<score>)` — 색점(●)과 라벨에 위 색상 적용.
- 미정의/누락 `type` → `normal`(일반/회색)로 안전 처리.
- ⚠️ 실시간 소켓 `emotion` payload는 `sentiment_type` 없이 **`type`만** 내려옴 → 프론트가 `type`(8종)을 직접 정규화.
- 적용 위치: 실시간 패널(`CustomerVocPanel.vue`), 상담내용 헤더 인라인 VOC(`chat/index.vue`), 통화종료/콜이력 상세 박스(`VocDetailBox.vue`).

---

## 6. `emotion.score` 구간 재정렬 (백엔드 보정 — 2026-06-26)

### 배경
- 백엔드가 `emotion.type` 별 `emotion.score` 분포를 재정렬해서 보낼 예정.
- 핵심: **score 를 "긍정→부정 단조(monotonic) 스케일"로 정렬** (낮을수록 긍정, 높을수록 부정).

### 신규 score 구간 (백엔드 전달값)
| `emotion.type` | 새 score 구간 |
|---|---|
| `thanks` (감사) | 0.0 ~ 0.2 |
| `satisfied` (만족) | 0.2 ~ 0.4 |
| `normal` (일반) | 0.4 ~ 0.6 |
| `dissatisfied` (불만) | 0.6 ~ 0.8 |
| `angry` (화남) | 0.8 ~ 1.0 |

> 이전 분포는 `normal=0.0~0.19` / `satisfied=0.4~0.59` 처럼 긍정 감정이 중간값에 떠서, score 를 위험도로 쓰는 프론트 로직과 어긋났음. 이번 재정렬로 **score = 부정도(=위험 기여도)** 가 되어 가정과 일치.

### 프론트 영향 — **코드 수정 없음 (오히려 정확도 ↑)**
프론트는 이미 score 를 "긍정→부정 단조 스케일"로 가정해 동작 중이라, 백엔드 보정만으로 결과가 더 정확해짐.

| 화면 | 코드 위치 | score 사용 방식 | 영향 |
|---|---|---|---|
| chat 헤더 감정점수 뱃지 | `chat/index.vue:233,746` | `0.00` 숫자만 표기 (라벨·색은 `emotion.type` 에서 별도) | 표시 숫자만 바뀜, 판정 로직 없음 → 안전 |
| chat 헤더 스파크라인 | `chat/index.vue:228` | turn별 score 추이 선 | 안전. "위로 갈수록 부정" 일관성 ↑ |
| 실시간 패널 | `CustomerVocPanel.vue:32` | `(0.xx)` 괄호 숫자만 | 숫자만 바뀜 → 안전 |
| 감정변화 타임라인 그래프 | `VocHistoryModal.vue` | score 를 Y축 플롯 (위=위험), 가이드선 `0.8 위험`/`0.5 주의` | ⭐ 새 구간과 딱 맞음 (angry→위험선 위, satisfied/thanks→안전구간) |
| 종합위험도 | `emotionVoc.ts:159` `computeVocRisk` | emotion.score 를 위험 입력(가중치 0.4)으로 사용 | 긍정=저위험 / 부정=고위험 자연 정합 |

### 전제 조건 (백엔드 책임)
- 프론트는 `emotion.type` 과 `emotion.score` 를 **독립적으로** 표시함 (type→라벨/색, score→숫자/그래프).
- 따라서 백엔드가 type 과 score 를 **서로 일치**시켜 보내야 함. (예: type=`satisfied` 인데 score=0.9 면 화면에 "만족 0.90" 모순 노출.)
- 프론트에서 type-score 정합 검증/보정은 현재 **하지 않음** (필요 시 추후 별도 작업).

### 결론
**프론트 무손실 + 백엔드 score 재정렬로 정확도 향상.** 종합위험도 계산·타임라인 임계선(0.5/0.8)·스파크라인 모두 새 스케일과 자연스럽게 정합됨.

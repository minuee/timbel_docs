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

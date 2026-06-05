# STT / NLP 엔진 Redis 메시지 Contract

> 외부 STT/NLP 엔진(NeMo 등)이 Redis Pub/Sub으로 보내는 메시지의 스펙.
> Advisor 와 외부 엔진 간의 **인터페이스 계약**입니다.

**1차 담당**: 콜 인프라 (이태희 수석님, 김현철 수석님) + RAG/NLP (손영훈 이사님)

---

## 1. 채널 명명 규칙

```
{environment}:{tenant_id}:{agent_id}:call:{event_type}
```

| 부분 | 의미 | 예시 |
|------|------|------|
| `environment` | 환경 prefix | `dev`, `prod` |
| `tenant_id` | 테넌트 식별자 | `4609686` |
| `agent_id` | 상담원 CTI ID | `agent-001` |
| `event_type` | 이벤트 종류 | `events`, `nlp:partial`, `nlp:complete`, `orchestrator:persisted`, `stt:final` |

### 전체 채널 목록

| 채널 suffix | 발행 주체 | 구독 주체 | 빈도 |
|------------|----------|----------|------|
| `call:events` | STT 엔진 | 프론트 (`useChatMessageParser`) | 통화당 2회 (start/end) |
| `call:nlp:partial` | NLP 엔진 | 프론트 | 발화 중 수십~수백 회 |
| `call:nlp:complete` | NLP 엔진 | 프론트 | 턴당 1회 |
| `call:orchestrator:persisted` | DB 저장 시스템 | 프론트 | 통화 종료 후 1회 |
| `call:stt:final` | STT 엔진 (예약) | (현재 빈 핸들러) | - |

> 환경 prefix는 [redisKey.ts](../../asst-web/src/utils/redisKey.ts) 의 `process.env.VITE_USER_NODE_ENV` 값 기준.

---

## 2. `call:events` — 통화 시작/종료

### 2-1. type: "start"

```json
{
  "type": "start",
  "call_id": "call-019913cc-...",
  "agent_id": "agent-001",
  "tenant_id": "4609686",
  "customerNum": "01012345678",
  "timestamp": "2026-05-15T14:30:12.000Z"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `type` | `"start"` | ✅ | 이벤트 타입 |
| `call_id` | string | ✅ | 통화 식별자. 프론트의 `callSummaryInfoStore.callId` 로 저장 |
| `agent_id` 또는 `agentId` | string | ✅ | 상담원 CTI ID. 프론트는 `cc_cti_id` 와 비교 |
| `customerNum` 또는 `customer_num` | string | - | 고객 전화번호. 화면에 표시 |
| `timestamp` | ISO 8601 | ✅ | 발행 시각 |

→ 프론트 처리 ([useChatMessageParser.ts:127-194](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L127-L194)):
- 상담원 상태 → `ON_CALL`
- `chatContent` clear
- 통화 타이머 시작
- system 메시지 "상담이 시작되었습니다." 추가

### 2-2. type: "end"

```json
{
  "type": "end",
  "call_id": "call-019913cc-...",
  "agent_id": "agent-001",
  "timestamp": "2026-05-15T14:38:42.000Z"
}
```

→ 프론트 처리 ([useChatMessageParser.ts:196-242](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L196-L242)):
- 진행 중인 스트리밍 버블 강제 확정
- 상담원 상태 → `AFTER_CALL`
- 타이머 중지

---

## 3. `call:nlp:partial` — 발화 중 누적 텍스트

```json
{
  "tenant_id": "4609686",
  "agent_id": "agent-001",
  "call_id": "call-019913cc-...",
  "turn_idx": 10,
  "speaker": "customer",
  "start_ms": 12500,
  "end_ms": 13200,
  "origin_text": "안녕하세요 환불",
  "masked_text": "",
  "nlp": null,
  "timestamp": "2026-05-15T14:30:24.500Z"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `turn_idx` | number | ✅ | 발화 턴 번호 (같은 발화의 partial 들은 동일) |
| `speaker` | `"customer"` \| `"agent"` | ✅ | 발화자 |
| `start_ms` | number | ✅ | 통화 시작 후 발화 시작 시점 (ms) |
| `end_ms` | number | ✅ | 발화 종료 시점 (ms, partial은 진행 중) |
| `origin_text` | string | ✅ | **누적 텍스트** (이전까지의 모든 단어 포함) |
| `masked_text` | `""` | ✅ | partial은 항상 빈 문자열 |
| `nlp` | `null` | ✅ | partial은 항상 null |

### 중요 규약

- **`origin_text`는 누적**: "안녕" → "안녕하세요" → "안녕하세요 환불" 처럼 점점 길어짐 (replace, not append)
- **같은 `turn_idx`는 같은 발화**: partial 여러 개가 같은 turn_idx를 가짐
- **`masked_text`와 `nlp`는 빈 값**: partial 단계에서는 마스킹/분석 미수행

### 프론트 처리

[useChatMessageParser.ts:245-309](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L245-L309):

1. `streamingBySpeaker[sender]` 에 같은 `turn_idx` 가 있으면 → 텍스트만 update
2. 없으면 → 새 버블 생성 (`isStreaming: true`)
3. 깜빡이는 커서 UI 표시

---

## 4. `call:nlp:complete` — 발화 확정

```json
{
  "tenant_id": "4609686",
  "agent_id": "agent-001",
  "call_id": "call-019913cc-...",
  "turn_idx": 10,
  "speaker": "customer",
  "start_ms": 12500,
  "end_ms": 14800,
  "origin_text": "안녕하세요, 환불 가능한가요?",
  "masked_text": "안녕하세요, 환불 가능한가요?",
  "nlp": {
    "intent": [
      { "intent": "REFUND_INQUIRY", "score": 0.95 },
      { "intent": "GENERAL_INQUIRY", "score": 0.03 }
    ],
    "keywords": ["환불"],
    "search_query": "환불 정책",
    "entities": [
      { "type": "PRODUCT", "value": "...", "start": 5, "end": 10 }
    ]
  },
  "timestamp": "2026-05-15T14:30:26.800Z"
}
```

### 필드 추가

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `masked_text` | string | ✅ | 개인정보 마스킹 적용 텍스트 (카드번호 등) |
| `nlp.intent` | Array | ✅ | 인텐트 분류 결과 (점수 내림차순) |
| `nlp.intent[].intent` | string | ✅ | 인텐트 ID |
| `nlp.intent[].score` | number | ✅ | 0.0 ~ 1.0 신뢰도 |
| `nlp.keywords` | string[] | - | 추출된 키워드 |
| `nlp.search_query` | string | - | RAG 검색용 쿼리 (선택) |
| `nlp.entities` | Array | - | NER 엔티티 (위치 정보 포함) |

### 프론트 처리

[useChatMessageParser.ts:311-484](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L311-L484):

1. 같은 `turn_idx` 스트리밍 버블이 있으면 확정 (`isStreaming: false`)
2. NLP 데이터 적용 (인텐트 배지, 키워드 버튼)
3. **고객 발화 + 유효 인텐트** → `handleAssistStream()` 호출 (assist-stream SSE)
4. `callAnalyticsData.segments` 에 push

---

## 5. `call:orchestrator:persisted` — DB 저장 완료

```json
{
  "call_id": "call-019913cc-...",
  "callstats_id": "019913cc-5a51-75ba-...",
  "agent_id": "agent-001",
  "tenant_id": "4609686",
  "timestamp": "2026-05-15T14:38:45.000Z"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `callstats_id` | UUID | 통화 통계 데이터 식별자. 요약 API 호출 시 사용 |

→ 프론트 처리 ([useChatMessageParser.ts:485-490](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L485-L490)):
- `callSummaryInfoStore.callId` / `callstatsId` 설정
- `emit("orchestrator-persisted")` → 부모 컴포넌트가 요약 API 호출 트리거

---

## 6. `call:stt:final` — (예약, 현재 미사용)

[useChatMessageParser.ts:243-244](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L243-L244):

```typescript
} else if (raw.message.channel.includes("stt:final")) {
  // stt:final 이벤트는 현재 처리 없음
}
```

STT 엔진의 발화 종료 알림용으로 예약된 채널. 향후 EOU 처리 강화 시 활용.

---

## 7. 메시지 순서 보장

### 7-1. 정상 흐름

```
call:events {type: start}
   ↓
nlp:partial #1 (turn 1)
nlp:partial #2 (turn 1)
...
nlp:complete (turn 1)
   ↓
nlp:partial #1 (turn 2)
...
nlp:complete (turn 2)
   ↓
call:events {type: end}
   ↓
orchestrator:persisted
```

### 7-2. 깨질 수 있는 경우

| 상황 | 영향 | Advisor 대응 |
|------|------|------|
| partial 일부 누락 | 텍스트 일부 사라짐 | complete 시점에 전체 origin_text로 보정 |
| complete가 먼저 옴 (partial 없이) | 스트리밍 버블 없이 신규 생성 | 하위 호환 경로 동작 |
| 같은 turn_idx의 complete 중복 | 두 번째는 무시 | turn_idx 중복 dedup |
| call:events end 누락 | 통화 종료 처리 안 됨 | 사용자가 새로고침해야 함 |
| 순서 뒤바뀜 | 버블 잘못 표시 | turn_idx 기준 정렬 (현재 미구현) |

---

## 8. 인접 EOU 문제 (NeMo)

STT 엔진이 발화 종료 시점(EOU)을 잘못 판단해서 **한 발화가 두 개 turn으로 쪼개지는 경우**가 있음. 자세한 분석:

- [adv_docs/specs/turn-eou-mismatch-report.md](turn-eou-mismatch-report.md)
- [adv_docs/specs/nemo-turn-eou-mismatch-server-request.md](nemo-turn-eou-mismatch-server-request.md)

### Advisor 측 대응

[useChatMessageParser.ts](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts) 의 `pendingMergeBySpeker` 로직:
- `nlp:complete` 직후 들어온 `nlp:partial` 을 같은 버블에 합침
- `TURN_MERGE_TIMEOUT_MS` 내에 다음 발화 미도착 시 별도 발화로 확정

---

## 9. Contract 변경 시 영향 범위

이 contract 변경 시 양쪽 모두 수정 필요:

### STT/NLP 엔진 측
- 메시지 publish 형식 변경
- 새 필드 추가 시 backward compatible 우선

### Advisor 측

| 변경 | 수정 위치 |
|------|----------|
| 채널명 규칙 변경 | [asst-web/src/utils/redisKey.ts](../../asst-web/src/utils/redisKey.ts) |
| 새 채널 추가 | 위 + [chat/index.vue:1213-](../../asst-web/src/view/advisor/components/chat/index.vue#L1213) socketChannels 배열 |
| 필드 추가 | [useChatMessageParser.ts](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts) 의 해당 핸들러 |
| NLP 형식 변경 | useChatMessageParser + 채팅 버블 UI |

---

## 10. 테스트 / 시뮬레이션

### 로컬에서 메시지 발행

```bash
# 통화 시작
redis-cli PUBLISH dev:tenant1:agent01:call:events '{
  "type":"start",
  "call_id":"test-001",
  "agent_id":"agent01",
  "customerNum":"01012345678",
  "timestamp":"2026-05-15T14:30:00Z"
}'

# 발화 partial (누적)
redis-cli PUBLISH dev:tenant1:agent01:call:nlp:partial '{
  "tenant_id":"tenant1",
  "agent_id":"agent01",
  "call_id":"test-001",
  "turn_idx":1,
  "speaker":"customer",
  "start_ms":1000,
  "end_ms":2000,
  "origin_text":"안녕하세요",
  "masked_text":"",
  "nlp":null,
  "timestamp":"2026-05-15T14:30:02Z"
}'

# 발화 complete
redis-cli PUBLISH dev:tenant1:agent01:call:nlp:complete '{...}'

# 통화 종료
redis-cli PUBLISH dev:tenant1:agent01:call:events '{
  "type":"end",
  "call_id":"test-001",
  "timestamp":"2026-05-15T14:38:00Z"
}'
```

### 자동 테스트

[useChatMessageParser.spec.ts](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.spec.ts) 에 `makePartialMessage()`, `makeCompleteMessage()` 팩토리 함수 존재. 신규 contract 변경 시 이 spec 도 함께 갱신.

---

## 11. 인계 시 강조 포인트

1. **이 contract는 비공식 문서** — 정식 스펙 문서가 STT/NLP 엔진 측에 존재하는지 확인 필요
2. **NeMo EOU 이슈가 진행 중** — 엔진 업그레이드 시 양쪽 검증
3. **순서 보장 없음** — Redis는 순서 보장 안 함 (특히 다중 publisher 시). Advisor 측 dedup/merge 로직 의존.
4. **개인정보 노출 위험** — `origin_text` 에는 마스킹 전 데이터가 들어옴. 로깅 시 주의 (`masked_text` 사용 권장).
5. **`agent_id` vs `agentId`** — STT 엔진이 양쪽 모두 사용. Advisor는 둘 다 처리.

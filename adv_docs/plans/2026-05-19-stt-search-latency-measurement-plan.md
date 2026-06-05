# STT 검색 지연 실측 계측 구현 계획

**작성일**: 2026-05-19
**브랜치**: `feat/stt-search-latency-probe` (asst-web)

## 목표

speculative-prefetch(선검색 캐시) 도입 여부를 추정이 아닌 데이터로 결정하기 위해, 실통화에서 **"누적 발화가 처음 문법적으로 완성된 시점 ~ 검색이 실제 트리거되는 시점(`ending=final`) ~ 첫 검색 결과(`sources`) 도착 시점"** 의 분포를 비침습으로 계측한다. 검색 동작은 일절 바꾸지 않는다(관측만 추가).

## 왜 이 항목들인가

논의에서 도출된 결론: speculative의 속도 이득 상한 = **`T_final − T_firstComplete` 간격**. 이 간격이 ~0이면 클라이언트 트리거를 아무리 손봐도 벌 속도가 없고 keep-alive·업스트림만 남는다. 또한 캐시 히트 가능성은 `textAtFirstComplete ↔ textAtFinal` 유사도에 달려 있다. 이 두 분포 + RAG 자체 지연을 모르면 후속 결정이 추정 위에 짓는 것이 된다.

## 측정 항목 (고객 발화 단위, key = 머지 버블 messageId)

| 필드 | 의미 | 훅 지점 |
|------|------|---------|
| `callId`, `turnIdx`, `messageId` | 그룹핑 컨텍스트 | parser |
| `tFirstComplete` | 누적 텍스트가 처음 문법완성된 시각 (클라 종결어미 휴리스틱) | `useChatMessageParser` nlp:complete |
| `textAtFirstComplete` | 그 시점의 누적 텍스트 | 〃 |
| `tFinal` | `ending=final` 도착 시각 (= 현재 실제 검색 트리거) | `useChatMessageParser` Step D |
| `textAtFinal` | final 시점 누적 텍스트(`displayText`) | 〃 |
| `tSearchCall` | `handleAssistStream` 호출 시각 | `useChatAssist` 진입 |
| `tFirstSources` | 첫 `sources` SSE 도착 시각 (결과 첫 가용) | `useChatAssist` sources 콜백 |
| `mergeChainLen` | final까지 합쳐진 nlp:complete 턴 수 | parser |

### 파생 지표 (probe 내부 계산·로그)

- `budgetMs = tFinal − tFirstComplete` — speculative 속도 예산(핵심)
- `ragLatencyMs = tFirstSources − tSearchCall` — RAG 파이프라인 자체 지연(= speculative가 숨기는 대상)
- `textDivergence` — `textAtFirstComplete` vs `textAtFinal` 정규화 편집거리/접두포함 (캐시 히트 가능성 대리지표)
- `firstCompleteSeen` — 한 발화에서 문법완성 체크포인트가 final 전에 존재했는지(없으면 budget=0 케이스)

## 변경 대상 파일

- `asst-web/src/utils/sttLatencyProbe.ts` — (신규) 싱글톤 probe. 완성도 휴리스틱 + 레코드 조립 + JSON 로그 + `window.__sttLatency` 버퍼. enable 상수 1곳으로 토글, 기본 ON(계측 브랜치 한정)
- `asst-web/src/utils/sttLatencyProbe.spec.ts` — (신규) 완성도 휴리스틱·레코드 조립 단위 테스트
- `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts` — nlp:complete에서 `observeAccumulated()`(첫 완성 기록), Step D에서 `markFinal()` 호출. **검색 로직 무변경, observe 호출만 추가**
- `asst-web/src/view/advisor/components/chat/composables/useChatAssist.ts` — `handleAssistStream` 진입 `markSearchCall()`, sources 콜백 `markFirstSources()`(레코드 flush)

## 구현 단계

1. [ ] `sttLatencyProbe.ts`: `isLikelyComplete(text)`(서버 종결어미 룰 미러: 평서/의문/감탄 종결어미=완성, 연결어미/조사끝/≤3자=미완), `observeAccumulated/markFinal/markSearchCall/markFirstSources`, flush 시 파생지표 계산 후 `console.info("[stt-latency-probe]", json)` + 링버퍼
2. [ ] parser 와이어링 (observe/ markFinal). 동작 무변경 확인
3. [ ] useChatAssist 와이어링 (markSearchCall / markFirstSources)
4. [ ] 단위 테스트 작성·실행
5. [ ] `npx tsc --noEmit` + `npm run lint` + `npm run test:unit`

## 리스크 & 고려사항

- **동작 회귀 금지**: probe 호출은 try/catch로 감싸 계측 실패가 검색·표시에 영향 0. observe 호출은 순수 부수효과 없음
- 클라 완성도 휴리스틱 ≠ 서버 게이트와 100% 일치 불필요 — budget 분포의 *경향* 파악이 목적이므로 근사로 충분(편차는 로그로 사후 보정 가능)
- key는 머지 체인 내 안정적인 `targetBubbleId`(=messageId). turnIdx는 null 가능 → messageId를 정본 key로
- 첫 완성이 final과 동일 nlp:complete에서 일어나면 `budgetMs≈0` — 이 케이스 비율 자체가 핵심 결과물
- PII: 로그에 원문 텍스트 포함됨. **로컬/스테이징 실측 전용**, 프로덕션 상시 적재 금지(enable 상수 OFF가 기본 운영값)

## 검증 방법

- 단위 테스트로 휴리스틱·파생지표 정확성 확인
- 로컬 개발 서버에서 실통화/모의 발화 → 콘솔 `[stt-latency-probe]` JSON 1발화당 1줄 출력 확인
- `window.__sttLatency`로 누적 레코드 export → `budgetMs`/`ragLatencyMs`/`textDivergence` 분포 산출
- 동작 회귀 없음: 검색 트리거·머지·표시 타이밍이 계측 전과 동일한지 수동 확인

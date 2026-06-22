# assist-stream vs stream — 응답 속도 차이 분석

> 작성일: 2026-06-21
> 주제: 실시간(`POST /assist-stream`)과 수동검색(`POST /stream`)의 프론트 체감 속도 차이 원인 분석

---

## 1. 문제 정의 (관찰된 증상)

프론트가 두 API를 호출해 **화면에 문서 + AI 요약문이 노출되기까지의 시간**(end-to-end 체감):

| API | 성격 | 체감 속도 |
|---|---|---|
| `POST /stream` | 수동 검색 | 평균 **~1s** (안정적) |
| `POST /assist-stream` | 실시간 상담보조 | **1s ~ 10s** (편차 매우 큼) |

- 핵심 특징: **일관되게 느린 게 아니라 편차가 큼.** 빠를 땐 1초 안, 느릴 땐 5~10초.
- 두 API 모두 외부 RAG 엔드포인트 `${SEARCH_HOST}/api/v1/rag/assist-stream` 를 호출하고, 결과를 받아 프론트로 중계한다.

---

## 2. 두 API 구조 분석

### 2-1. 결론: 두 API는 동일한 처리 프로세스를 탄다

asst-service 입장에서 두 API는 **거의 동일한 얇은 SSE 프록시**다.

- **요청 흐름**: 프론트 body → asst-service가 RAG 규격으로 변환 → RAG 호출 → RAG 응답(SSE)을 받아 → `res.write()` 로 프론트에 그대로 중계
- **프론트로 보내는 구간(SSE 릴레이)은 두 API가 글자 단위로 동일**:
  - `assist-stream.service.ts:150` → `res.write(decoder.decode(value, { stream: true }))`
  - `search.service.ts:119` → `res.write(decoder.decode(value, { stream: true }))`
- SSE 헤더 세팅, reader 루프, 에러 처리 모두 사실상 복붙 수준으로 동일.

### 2-2. 가설 검증: assist-stream이 Redis publish / 소켓을 추가로 하는가? → ❌ 아니다

의심했던 "RAG 응답을 받은 뒤 Redis로 구독 클라이언트에 publish해서 느린 것" 가설을 코드로 검증.

- `grep` 결과: assist-stream / search 경로 **전체에 redis / socket / publish / emit / broadcast / VOC 호출이 단 한 줄도 없음** (유일한 매치는 `BAD_GATEWAY` 에러 상수 단어).
- `assist-stream.controller` 가 주입받는 의존성은 `AssistStreamService` **하나뿐** (SocketGateway·RedisService 안 받음).
- 즉 **이 소스에서는 "RAG 응답을 받은 뒤 어딘가로 뿌리는" 후처리가 존재하지 않는다.** 두 API의 후처리는 동일.

> 참고: 별도 history 기록상의 실시간 VOC publish 작업이 배포 서버에 있더라도, 그것은 `void handleUtterance(...)` **fire-and-forget**(병렬 실행 + `.catch` 흡수)이라 SSE 응답을 막지 않음 → 9초 지연의 범인이 되기 구조적으로 어려움.

### 2-3. 두 API의 실제 차이점

프론트가 보내는 body가 다르고, 그 body를 RAG로 넘길 때만 차이가 생긴다.

| 항목 | assist-stream | stream | 성격 |
|---|---|---|---|
| 프론트 body | `{query, conversationHistory, callId}` | `{query}` | 프론트 차이 |
| RAG payload: `conversation_history` 가공 | `toRagHistory()` 실제 수행 (speaker→role 매핑, 화자당 최근 3턴 컷) | 빈 배열 통과 (데이터 없음) | **데이터 차이** |
| RAG payload: `distill` | `distill: false` (코드에 하드코딩) | 키 없음 → RAG 기본값 사용 | **코드 차이** |
| 컨트롤러 인터셉터 | 없음 | `DbCleanupInterceptor` | (속도 무관) |

#### body → RAG payload 변환 (가벼운 가공)

- `conversationHistory` 변환은 두 서비스 다 `toRagHistory()` 를 호출하지만, `conversation-history.util.ts:13` 의 `if (!history || history.length === 0) return []` 때문에 **데이터가 있는 assist-stream에서만 실제 변환이 일어남.**
- 이 변환들은 배열 자르기/매핑 수준이라 **CPU상 거의 공짜** → 지연 원인 아님.
- 지연은 어디까지나 **변환된 payload를 RAG가 받아서 처리하는 시간**에서 발생.

#### `distill` 파라미터 (※ 추정, RAG 서버 소스 미확인)

- 의미(추정): `distill: true` = 검색된 문서를 LLM이 한 번 더 가공/요약하는 **추가 LLM 단계** → 느림. `false` = 추가 가공 없이 반환 → 빠름.
- 근거: history 기록상 RAG/AICM의 `enable_distill` **기본값 true**, 기존에 일부러 false로 꺼서 "요약 미사용" 유지.
- ⚠️ **방향이 증상과 반대**: assist-stream은 `false`(빨라야 함)인데 느리고, stream은 기본 `true`(느려야 함)인데 빠름 → **distill은 이번 지연의 범인이 아닐 가능성이 큼.**

---

## 3. 원인 후보 소거 과정

| # | 가설 | 판정 | 근거 |
|---|---|---|---|
| 1 | assist-stream이 Redis/소켓 publish로 느림 | ❌ 배제 | 해당 코드 자체가 없음 (grep 확인) |
| 2 | `conversationHistory` 가 RAG를 느리게 함 | ❌ 약화/배제 | **어제 테스트: 첫 메시지(conversationHistory=`[]` 빈 배열)에서도 느렸음** → 빈 배열이면 stream과 content 동일한데도 느림 → 단독 범인 아님 |
| 3 | `distill: false` 가 느리게 함 | ❌ 가능성 낮음 | 편차가 큼 = 고정 코드 경로로는 설명 불가. 게다가 방향이 반대 |
| 4 | 변환(가공) 작업이 느림 | ❌ 배제 | 배열 매핑 수준, CPU 공짜 |
| 5 | **RAG/LLM 서버의 처리 시간 변동** | ✅ **유력** | 편차가 큰 것(1s↔10s)은 고정 구조가 아니라 부하/타이밍 의존 요인의 전형 |

### 핵심 논리

1. **두 API의 asst-service 후처리는 동일** → 지연은 우리 서버 안이 아님.
2. **편차가 크다(일관되게 느린 게 아님)** → distill·conversationHistory 같은 **고정 코드 경로 차이로는 설명 불가**. 고정 차이면 일정한 오프셋이 생기지 출렁이지 않음.
3. 편차의 전형적 원인 = **RAG 뒤 LLM의 변동성**:
   - LLM 추론 시간 자체가 원래 1s~10s로 들쭉날쭉 (입력/모델 서버 상태에 따라)
   - RAG/LLM은 **공유 인프라** (내 관리영역 아님) → 다른 트래픽으로 바쁠 때 들어가면 느림
   - ⭐ **샘플링 착시 가능성**: assist-stream은 통화당 발화마다 수십 번 호출 → 느린 꼬리값을 자주 봄. stream은 수동이라 몇 번 안 눌러봐서 아직 느린 케이스를 안 만났을 수도.

### 단독 테스트 환경 전제

- 현재 테스트는 **혼자** 진행 → "여러 상담사 동시 호출로 인한 큐잉" 시나리오는 배제됨.
- 단, RAG/LLM 서버는 공유 인프라라 "나 혼자"가 "RAG도 한가함"을 의미하지 않음.

---

## 4. 잠정 결론

- **asst-service(이 백엔드) 코드는 두 API 모두 죄가 없을 가능성이 높다.** 단순 통과 + 동일 SSE 릴레이.
- 지연(특히 1s~10s 편차)의 병목은 **외부 RAG/LLM 서버의 처리 시간 변동**으로 추정.
- 단, RAG 서버는 관리영역 밖이라 코드만으로 확정 불가 → **실측 데이터로 구간을 특정해야 함.**

---

## 5. 내일 회사에서 할 테스트 (우선순위 순)

### ✅ 테스트 1. 샘플링 착시 확인 (가장 빠름, 도구 불필요)

- **방법**: 수동검색 `/stream` 을 **연속으로 10번 이상** 호출(검색 버튼 연타).
- **판정**:
  - 그 중 가끔 5~10초 나오면 → **샘플링 착시 확정.** 두 API 차이 없음, RAG가 원래 들쭉날쭉한 것.
  - 매번 1초 안쪽으로 일정하면 → stream은 진짜 빠른 것 → 두 API에 실제 차이 존재 (테스트 2·3으로)

### ✅ 테스트 2. 구간별 지연 측정 (코드에 이미 있는 기능 활용)

- **방법**: 환경변수 **`ASSIST_STREAM_LATENCY_LOG=1`** 켜고 통화 테스트 → 느린 케이스 로그 수집.
- **로그 위치**: `assist-stream.service.ts:139` (`[assist-stream-latency]`)
- **판정 (느린 요청의 어느 값이 큰가)**:

  | 큰 구간 | 의미 | 범인 |
  |---|---|---|
  | `inToFetchMs` | asst-service 진입 → RAG 호출 직전 | 우리 서버 (가능성 낮음) |
  | `fetchToHeadersMs` | RAG 요청 → 응답 헤더 도착 | **RAG 큐잉/처리 지연** (유력) |
  | `headersToFirstChunkMs` | 헤더 → 첫 데이터 청크 | **RAG의 LLM 추론 지연** (유력) |

- 느린 케이스 몇 개의 이 값들을 기록해두면 "우리 서버 vs RAG" 가 한 방에 판명됨.

### ✅ 테스트 3. RAG 직접 호출로 변수 완전 제거 (선택)

- **방법**: `curl` 로 RAG 엔드포인트(`${SEARCH_HOST}/api/v1/rag/assist-stream`)를 직접 호출. asst-service·프론트를 변수에서 제외하고 순수 RAG 시간만 측정.
- **비교 케이스** (같은 query로 각각 여러 번):
  - A) `{query, conversation_history: [], distill: false}` ← assist-stream과 동일
  - B) `{query, conversation_history: []}` ← stream과 동일 (distill 미지정)
  - C) `{query, conversation_history: [2턴], distill: false}` ← 맥락 있을 때
- **판정**:
  - A가 B보다 일관되게 느림 → distill 범인
  - A·B 모두 빠름 → RAG 무죄 → 프론트 렌더링 의심
  - 셋 다 들쭉날쭉 → RAG 변동성 확정 (잠정 결론 부합)

### ✅ 테스트 4. distill 동작 확정

- 회사 **최종 소스**에서 `assist-stream` / `stream` 의 `distill` 실제값 확인.
- **RAG 서버 담당자에게 문의**: `distill`(또는 `enable_distill`) 파라미터가 실제로 무슨 동작을 하는지, true/false 시 처리 시간 차이가 있는지.

### (참고) 추가로 해둘 수 있는 코드 작업

- `/stream` 에도 `assist-stream`과 동일한 latency 로그를 추가하면 → **같은 부하 시점에 두 API를 나란히 비교** 가능 (현재 stream엔 측정 로그 없음). 필요 시 요청.

---

## 6. 핵심 요약 (한 줄)

> 두 API는 asst-service 안에서 동일하게 처리되고 동일하게 SSE로 중계된다. 차이는 프론트 body(→ RAG로 가는 입력)뿐이며, 1s~10s의 큰 편차는 고정 코드 경로가 아니라 **외부 RAG/LLM 서버의 처리 시간 변동**일 가능성이 가장 높다. 내일 latency 로그와 stream 연타 테스트로 "우리 서버 vs RAG"를 실측 판명한다.

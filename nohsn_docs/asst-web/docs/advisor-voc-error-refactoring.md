# VOC 실시간 채널 간헐 미수신 — 원인 규명 및 수정

> **작성일:** 2026-07-14
> **대상:** `asst-web` (프론트) / `asst-service` (백엔드)
> **결론 요약:** 채널명·구독구조는 정상. **프론트 버그 2개**(소켓 재연결 시 VOC 룸 재조인 누락 + `currentCallId` 굳음)가 원인. 양쪽 다 수정 완료.

---

## 1. 증상

- 다른 실시간 채널은 **정상 동작**하는데 **VOC(`call:voc`) 채널만 간헐적으로 수신되지 않음.**

  | 채널 | Redis 키 | 상태 |
  |---|---|---|
  | STT 완료/부분 | `{env}:{vendor_tenant_id}:{cc_cti_id}:call:nlp:complete` / `:partial` | ✅ 정상 |
  | 상담사 상태 | `{env}:{vendor_tenant_id}:{cc_cti_id}:call:events` | ✅ 정상 |
  | DB 저장 | `{env}:{vendor_tenant_id}:{cc_cti_id}:call:orchestrator:persisted` | ✅ 정상 |
  | 코칭 / 코칭요청 | `{env}:{vendor_tenant_id}:{agent.id}:coaching` / `:coaching_request` | ✅ 정상 |
  | **VOC(감정/민원/이탈)** | `{env}:{vendor_tenant_id}:{cc_cti_id}:call:voc` | ⚠️ **간헐 미수신** |

### ⚠️ 식별자 주의 — 채널마다 두 번째 세그먼트의 정체가 다르다

`getRedisKey(tenantId, agentId, serviceName)` (`src/utils/redisKey.ts`) 는 **같은 함수인데 채널별로 넘기는 `agentId` 의 의미가 다르다.** 혼동하면 엉뚱한 채널을 구독하게 된다.

| 채널 | 2번째 세그먼트 | 실제 값 | 호출부 |
|---|---|---|---|
| `voc` / `nlp` / `partial` / `db` / `events` | **`cc_cti_id`** (CTI 숫자 ID) | `agent.cc_cti_id`<br>(관리자는 `props.agentId` = `consultant.agentId`, 이 역시 `cc_cti_id`) | `chat/index.vue:1345` |
| `coaching` / `coaching_request` | **`agent.id`** (UUID) | `agent.id` (= `receiver_key`) | `agent/index.vue:607`<br>`admin/index.vue:455` |

- 1번째 세그먼트 `tenantId` 는 **모든 채널 공통으로 `company.vendor_tenant_id`.**
- 실제 예시(백엔드 발행/프론트 구독 동일): **`dev:4609686:56356659:call:voc`**
  → `dev` = `CHANNEL_ENV`, `4609686` = `vendor_tenant_id`, `56356659` = **`cc_cti_id`**
- ⚠️ 문서·대화에서 `{agent}` 처럼 뭉뚱그려 쓰면 **VOC(`cc_cti_id`)와 코칭(`agent.id`)을 혼동**하게 된다. 반드시 구분해 표기할 것.

- **상담사 화면 / 관리자 멀티뷰 양쪽**에서 발생.
- **새로고침하면 다시 정상 동작.**
- ⭐ **DB에는 매 턴 정상 저장됨** — 즉 백엔드는 VOC 계산·저장까지 성공하고 있었다.
- 재현 조건이 불명확해 "간간히 안 된다"는 상태로 장기 방치. 프론트·백엔드가 서로 원인을 지목하며 진전 없음.

---

## 2. 원인

### 2-1. 결론

**프론트 버그 2개.** 채널명 불일치도, 구독 구조 문제도, 백엔드 발행 누락도 아니었다.

| # | 버그 | 파일 | 영향 |
|---|---|---|---|
| **1** | 소켓 재연결 시 VOC 룸 **재조인 누락** (`once("connect")`) | `useChatSocket.ts` | **직접 원인.** 재연결 이후 VOC 영구 미수신 |
| **2** | `currentCallId` 가 이전 콜에 **굳어** 새 콜 VOC를 전부 폐기 | `useChatMessageParser.ts` | **2차 원인.** `call:start` 유실 시 VOC 전량 drop |

---

### 2-2. 버그 1 — 소켓 재연결 시 VOC 룸 재조인 누락 (직접 원인)

**문제 코드** (`src/view/advisor/components/chat/composables/useChatSocket.ts:40`)

```js
const socket = getSocket();

if (socket.connected) {
  requestAndJoin();
} else {
  socket.once("connect", requestAndJoin);   // ❌ 최초 연결 때 딱 한 번만 join
}
```

**메커니즘**

1. **Socket.IO의 룸 멤버십은 소켓 id 기준으로만 관리된다.** 재연결하면 소켓 id가 새로 발급되므로 **이전 룸 정보가 전부 소멸**한다.
2. 백엔드(`socket.gateway.ts`)는 **룸을 복구해주지 않는다.** `client.join()` 호출부는 `@SubscribeMessage('join-room')` 핸들러 **딱 하나**이며, `handleConnection()` 은 로그와 `connection-confirmed` 이벤트만 보내고 끝난다. 서버 어디에도 "이 사용자가 원래 어떤 방에 있었다"는 기록이 없다. *(백엔드 코드 확인 완료)*
3. 따라서 **재조인은 전적으로 클라이언트 책임**인데, `once` 로 등록되어 있어 **최초 연결 때만 join** 된다.
4. → **재연결 이후 `voc` / `nlp:partial` / `db` 룸에 영영 돌아가지 못한다.**

**왜 VOC만 티가 났나 (핵심)**

같은 소켓을 쓰는데도 채널마다 등록 방식이 달랐다:

| 채널 | 등록 방식 | 재연결 시 |
|---|---|---|
| `events` (`admin/index.vue:311`) | **`on("connect")`** | ✅ 재조인됨 |
| `coaching_request` (`admin/index.vue:467`) | **`on("connect")`** | ✅ 재조인됨 |
| **`voc` / `nlp` / `partial` / `db`** (`useChatSocket.ts:40`) | **`once("connect")`** | ❌ **재조인 안 됨** |

→ 재연결이 일어나면 **상담사 상태·코칭·공지는 살아남고 VOC만 조용히 죽는다.** "새로고침하면 되는" 이유도 이것(새로고침 = 최초 연결 = `once` 발동).

**백엔드 로그의 결정적 증거**

> *"소켓 `2kPJ`가 재연결 2초 뒤 **6개 방만 join**, **voc 없음**"*

그 6개가 바로 `on("connect")` 으로 재조인된 `events` 계열이고, `once` 인 VOC는 빠졌다. 관측 결과가 코드와 정확히 일치.

---

### 2-3. 버그 2 — `currentCallId` 굳음 → `[voc] drop stale` (2차 원인)

**문제 코드** (`src/view/advisor/components/chat/composables/useChatMessageParser.ts`)

VOC 메시지에는 "이전 콜 잔상 방지" 필터가 걸려 있다:

```js
// :316 — voc.call_id 가 현재 콜과 다르면 버림
if (currentCallId.value && vocCallId && vocCallId !== currentCallId.value) {
  console.warn(`[voc] drop stale — voc.call=${vocCallId} current=${currentCallId.value}`);
  return;
}
```

그런데 `currentCallId` 를 채우는 경로가 취약했다:

```js
// :238 — call:events 의 start. 새 콜마다 갱신 (정상)
currentCallId.value = messageData.call_id;

// :421 — nlp:complete 백업. ❌ "비어 있을 때만" 채움
if (!currentCallId.value) {
  currentCallId.value = messageData.call_id;
}
```

**메커니즘**

1. `currentCallId` 는 **어디에서도 `""` 로 리셋되지 않는다.** (`call:end` 에도 리셋 없음)
2. 따라서 통화가 끝나도 **이전 콜의 `call_id` 가 계속 남아 있다.**
3. 어떤 이유로든 **`call:start` 를 한 번 놓치면** (재연결 / 관리자가 통화 도중 카드 열기 / 관리자 카드에서 상담사 교체) → `currentCallId` 가 **이전 콜에 영구히 굳는다.**
4. `nlp:complete` 백업은 `if (!currentCallId.value)` 조건이라 **비어있지 않으니 갱신하지 못한다.** → 복구 불가.
5. → 새 콜의 VOC 는 `voc.call_id !== currentCallId` 이므로 **전량 `[voc] drop stale`.**
6. ⭐ **STT는 이 필터를 타지 않으므로 정상 표시된다** → **"STT는 나오는데 VOC만 안 나온다"**

**버그 1과의 연쇄**: 버그 1로 룸이 이탈된 동안 `call:start` 를 놓치고, 그 결과 버그 2가 발동해 룸이 복구된 뒤에도 VOC가 계속 버려진다.

---

### 2-4. 헛다리 짚은 가설들 (재발 시 반복하지 말 것)

| # | 가설 | 판정 | 근거 |
|---|---|---|---|
| 1 | 채널명 불일치 | ❌ | 발행·구독 모두 `dev:4609686:56356659:call:voc` 로 **동일**. `getRedisKey()` 산출값과 백엔드 발행값 일치 |
| 2 | 구독 구조(agent 단위)가 문제 | ❌ | Redis pub/sub은 구독자 N명 전원에게 broadcast. 상담사 1 + 관리자 N 동시구독 **정상 동작** |
| 3 | 프론트가 `cc_cti_id` 를 안 보내 백엔드가 발행 못 함 | ❌ | 상담사 화면은 사실상 항상 전송. 예외 경로는 있으나 **간헐 증상을 설명 못 함** |
| 4 | 프론트가 `unsubscribe` 를 호출해 남의 구독까지 파괴 | ❌ | **프론트는 `unsubscribe` 를 어디서도 호출하지 않음.** API 정의·래퍼는 있으나 **호출부 0개(dead code)**. 백엔드 전용(Swagger) |
| 5 | `assist-stream` 호출 실패로 발행 누락 | ❌ | **DB에 매 턴 저장된다 = 호출은 성공했다.** 이 관찰 하나로 가설 제거 |

---

## 3. 해결방안

### 3-1. 채택한 방안

| 대상 | 조치 | 상태 |
|---|---|---|
| **프론트 (필수)** | `once("connect")` → **`on("connect")`** — 재연결마다 재구독·재조인 | ✅ **완료** |
| **프론트 (필수)** | `currentCallId` set-once → **"call_id 가 바뀌면 갱신"** — 자동 복구 | ✅ **완료** |
| **백엔드 (안전망, 선택)** | 재연결 시 서버가 룸 자동 복구 | 🔲 논의 중 |
| **백엔드 (근본 개선)** | VOC 발행을 `nlp:complete` 구독 기반으로 **백엔드 자체 트리거** | 🔲 미착수 |

### 3-2. 폐기한 방안

- **`call:end` 에서 `currentCallId` 리셋** — ⚠️ **위험.** 통화 종료 후에도 상담요약·할일이 `currentCallId` 를 사용한다(`chat/index.vue:534`, `:633`). 비우면 해당 기능이 깨진다. 버그 2 수정만으로 굳음은 이미 해결되므로 불필요.
- **채널 키를 `call_id` 기준(`{env}:{vendor_tenant_id}:{call_id}:voc`)으로 변경** — **실익이 적어 폐기.** §3-4 참조.

### 3-3. 현재 채널 구조(상담사 단위)는 문제 없다 — 판단 근거

> **채널명을 의심하기 전에 이 절을 먼저 읽을 것.** (분석 과정에서 두 번 의심했고, 두 번 다 무죄였다)

`cc_cti_id` 는 **통화가 아니라 상담사(자리)의 키**다. 따라서 VOC 채널은 상담사 단위로 하나이고, **그 상담사가 처리하는 모든 통화의 VOC가 같은 채널로 흐른다.** `call_id` 는 채널명이 아니라 **payload 안에** 있다 (백엔드 `voc-realtime.service.ts:766-773` 확인):

```js
{
  agent_id: ccCtiId,   // ← 필드명은 agent_id 인데 값은 cc_cti_id
  call_id: dto.callId,
  turn_idx: ...,
  emotion, complaintRisk, churnRisk
}
```
*(프론트 타입에도 동일하게 명시돼 있다 — `voc.type.ts:45`: `agent_id: string; // 값 = cc_cti_id`)*

> **채널 = 누구(상담사) / payload = 어느 통화.**
> **구독자는 채널로 상담사를 고르고, `call_id` 로 통화를 걸러야 한다.**

**그래도 문제가 없는 이유: 상담사의 지정 자리는 하나뿐이라 동시 통화가 없다.**
- → 한 채널에 **여러 통화의 VOC가 동시에 섞이는 일은 발생하지 않는다.**
- → 섞이더라도 **순차적으로만**(직전 통화의 잔상 vs 현재 통화), 그리고 이는 payload의 `call_id` 필터로 완전히 분리된다.
- → 즉 **`call_id` 필터가 정상 동작하기만 하면 채널 구조는 아무 문제가 없다.** 이번 버그 2는 그 필터가 *고장 나 있던* 것이지, 채널 구조의 결함이 아니다.

⚠️ **`call_id` 필터는 프론트가 임의로 넣은 방어 코드가 아니라, 이 설계가 구독자에게 요구하는 필수 책임이다.** 제거하면 안 된다.

### 3-4. 채널 키를 `call_id` 로 바꾸는 안 — 폐기 사유

- **얻는 것:** `currentCallId` 필터가 불필요해짐.
- **잃는 것:** 콜 시작 전엔 `call_id` 를 알 수 없으므로 **구독 시점을 `call:start` 이후로 옮겨야 한다**(현재는 화면 진입 시 미리 구독). 상담사·관리자 양쪽의 구독 생명주기를 전면 재설계해야 하는 **대규모 변경.**
- **판단:** §3-3 대로 **상담사 동시 통화가 없어 현재 구조로 충분하다.** 손익이 맞지 않아 **폐기.**

### 3-5. 버그 2 수정의 트레이드오프 (검토 완료 — 현재 안 유지)

`currentCallId` 를 `nlp:complete` 의 `call_id` 로 갱신하도록 바꾸면서, 이론상 다음 리스크가 생긴다:

> STT 메시지가 **순서 역전**되어 이전 통화의 지각 `nlp:complete` 가 새 통화 시작 후 도착하면, `currentCallId` 가 일시적으로 과거로 되돌아가 그 순간의 VOC 몇 건을 버릴 수 있다.

**그럼에도 현재 안을 유지한다:**

| | 기존 (set-once) | 수정 후 ("바뀌면 갱신") |
|---|---|---|
| 최악의 경우 | **해당 통화 VOC 영구 전량 손실** (복구 불가) | 일시적으로 1~2턴 누락, **다음 STT가 즉시 정정** (자동 복구) |
| 실제 발생 | **실제로 발생했음** (이번 증상) | STT는 순차 스트림이라 **콜 경계를 넘는 역전은 사실상 없음** |

→ **영구 손실 vs 일시적·자동복구 손실.** 후자가 명백히 낫다. (사용자 검토·승인 완료)

### 3-6. 근본 개선 (별건, 미착수) — 남아있는 진짜 구조적 취약점

**현재 구조의 구조적 취약성:** VOC는 다른 채널과 달리 **프론트가 `/assist-stream` 을 호출해야 백엔드가 계산해 발행하는 "요청 파생" 이벤트**다. 즉 VOC만 **"브라우저가 살아있고 네트워크 호출이 성공해야 존재하는 데이터"** 가 된다.

**개선 방향:** 백엔드 `asst-service` 가 `nlp:complete` 를 **직접 구독**해 고객 발화 확정 시마다 스스로 VOC를 계산·발행. 그러면 프론트는 상담사·관리자 모두 **구독만 하는 대칭 구조**가 되고, 다른 채널과 동일한 "밀려오는 브로드캐스트"가 된다.

**관건:** 현재 프론트가 payload로 넘기는 `workspace_id` / `category_ids` / `company` 를 백엔드가 콜 시작 시점에 **자체적으로 확보 가능한지** (`useChatAssist.ts:444-452`).

---

## 4. 수정사항

### 4-1. `src/view/advisor/components/chat/composables/useChatSocket.ts`

**변경: `once("connect")` → `on("connect")` + 중복 등록 방지 + 언마운트 시 정리**

```js
// 재연결 시 재구독·재조인 핸들러. 매 connect 마다 실행돼야 하므로 인스턴스별로 보관해 off/on 한다.
let rejoinOnConnect: (() => void) | null = null;

const subscribeChannels = async (socketChannels: string[]) => {
  subscribedChannels.value = socketChannels;

  const requestAndJoin = () => { /* ... 기존 구독 + joinRoom ... */ };

  const socket = getSocket();

  // ⚠️ once 가 아니라 on 이어야 한다.
  // Socket.IO 룸 멤버십은 소켓 id 기준이라 재연결하면 이전 룸이 전부 소멸하고,
  // 서버(socket.gateway)는 룸을 복구해주지 않는다(재조인은 전적으로 클라이언트 책임 — 백엔드 확인됨).
  // once 로 두면 최초 연결 때만 join 되어, 재연결 이후 voc/nlp/db 룸에 영영 못 돌아온다
  // (events/coaching 은 on 이라 살아남음 → "상태·공지는 되는데 VOC 만 죽는" 증상의 원인).
  if (rejoinOnConnect) socket.off("connect", rejoinOnConnect);
  rejoinOnConnect = requestAndJoin;
  socket.on("connect", rejoinOnConnect);

  if (socket.connected) requestAndJoin();
};
```

`teardownListeners()` 에 핸들러 정리 추가 (리스너 누수 방지):

```js
socket.off("redis-message", onMessage);
socket.off("connect", onConnectCallback);
if (rejoinOnConnect) {
  socket.off("connect", rejoinOnConnect);
  rejoinOnConnect = null;
}
```

> **참고:** `useChatSocket.ts:77` 의 `socket.once("connect", onConnectCallback)` 는 **그대로 유지**했다. 이것은 룸 조인이 아니라 **`redis-message` 리스너 등록**용이며, **클라이언트 이벤트 리스너는 같은 socket 객체에 붙어 있어 재연결해도 유지**되므로 재등록이 필요 없다.

### 4-2. `src/view/advisor/components/chat/composables/useChatMessageParser.ts`

**변경: `currentCallId` set-once → "call_id 가 바뀌면 갱신" (자동 복구)**

```js
// before (:421)
if (!currentCallId.value) {                       // ❌ 굳으면 영영 복구 불가
  currentCallId.value = messageData.call_id;
}

// after (:421-429)
// call:start 를 놓쳐 currentCallId 가 이전 콜에 굳으면, voc 필터(:call:voc 의 stale drop)가
// 새 콜 VOC 를 전부 버린다(STT 는 이 필터를 안 타서 정상 표시 → "VOC 만 안 나옴"). set-once 가 아니라
// "call_id 가 바뀌면 갱신"으로 두어, start 유실 시에도 첫 nlp:complete 로 자동 복구시킨다.
const nlpCallId = (messageData.call_id || messageData.callId || "") as string;
if (nlpCallId && currentCallId.value !== nlpCallId) {
  currentCallId.value = nlpCallId;
  seenVocKeys.clear();        // 새 콜 → voc 중복수신 추적 초기화
  assistedTurnIdx.clear();    // 새 콜 → 발화 호출추적 초기화
}
```

**효과:** `call:start` 를 어떤 이유로 놓쳐도(재연결 / 카드 도중 열기 / 상담사 교체) **첫 `nlp:complete` 한 건으로 `currentCallId` 가 현재 콜로 스스로 정정**된다. 굳는 현상 자체가 원천 소멸.

### 4-3. 적용 범위

두 파일 모두 **공용 composable** 이므로 **기존 화면(`advisor`)과 리뉴얼 화면(`advisor-renual`)에 동시 적용**된다.

- `src/view/advisor/components/chat/index.vue`
- `src/view/advisor-renual/chat/components/RenualChatPanel.vue`

### 4-4. 검증

- ✅ 타입체크(`vue-tsc`) 통과.
- ⚠️ `useChatMessageParser.spec.ts` 는 **이번 수정 이전부터 실패 상태**다. spec이 `vocStore` 를 mock 하지 않아 `useVocStore()` 호출 시점(`parser:72`)에 pinia 미초기화로 터진다. 이번 변경과 무관하며, 별도 과제로 남는다.

---

## 5. 백엔드와의 협의 기록

### Q1. (백엔드→프론트) 상담사 화면이 `POST /assist-stream` 에 `cc_cti_id` 를 실어 보내는가?

**A.** 보낸다. `useChatAssist.ts:452` 에서 요청 객체에 담고, `assist-stream.api.ts:44` 의 `body: JSON.stringify(req)` 로 전송된다.

```js
const resolvedAgentId =
  isAdmin?.value === true || isViewer?.value === true
    ? agentId?.value                      // 관리자/뷰어: 보고 있는 상담사의 cc_cti_id
    : userProfileStore.agent?.cc_cti_id;  // 상담사 본인: get_user 응답값
...
cc_cti_id: resolvedAgentId || undefined
```

- 상담사 화면은 **사실상 항상 전송**한다(프로필이 로드돼야 상담 화면 진입이 가능하고, 호출 직전 `ensureUserProfile()` 보험까지 있음).
- ⚠️ 단, 값이 없으면 `undefined` 가 되는데 **`JSON.stringify` 는 `undefined` 키를 body에서 통째로 삭제**한다. 백엔드는 `""` 나 `null` 이 아니라 **필드 자체가 없는 요청**을 받게 된다.
- **결론: 이번 증상의 원인은 아니었다.** (DB에 매 턴 저장된다는 사실이 호출 성공을 증명)

### Q2. (백엔드→프론트) 로그아웃 / 화면 이탈 / 통화 종료 시 `DELETE /redis-monitor/unsubscribe/{channel}` 또는 `unsubscribe-all` 을 호출하는가?

**A. 아니오. 프론트는 어디에서도 호출하지 않는다.**

| 항목 | 상태 |
|---|---|
| `DELETE /redis-monitor/unsubscribe/{channel}` | API 정의만 존재(`subscribe.api.ts:28`) — **호출부 0개** |
| `unsubscribe-all` | 프론트 코드에 **아예 없음** |
| `useChatSocket.unsubscribeChannels` | 래퍼만 존재, `chat/index.vue:1199` 에서 구조분해만 함 — **호출 없음 (dead code)** |
| `SocketChannelManager.unsubscribeChannel/Multiple` | export만 존재 — **호출부 0개** |

**의도적이다.** `useChatSocket.ts:77` 주석: *"단일 소켓을 공유하므로 한 컴포넌트가 룸/구독을 해제하면 admin 페이지 등 다른 컴포넌트의 구독까지 파괴됨"*

프론트가 하는 것은 `leaveRoom()`(socket.io 룸 이탈)과 리스너 제거뿐이며, **백엔드의 Redis 구독은 한 번 걸면 해제하지 않는다.**
(※ 해당 API는 백엔드 전용 — Swagger에서만 사용)

### Q3. (백엔드→프론트) 소켓을 왜 이렇게 자주 재생성하나? 21분에 8번, 짧게는 12초 만에 끊고 다시 붙는다. `useEffect` cleanup에서 `socket.disconnect()` 를 부르는데 의존성이 자주 바뀌는 구조 아닌가?

**A. 전제가 틀렸다. 이 프로젝트는 React가 아니라 Vue이며, `useEffect` 자체가 없다. 그리고 "의존성이 바뀌어 소켓을 재생성하는 구조"도 없다.**

1. **`initSocket()` 은 멱등하다.** `socketIOPlugin.ts:17` 에 `if (inited) return;` 가드가 있어 **앱 전체에서 소켓을 단 한 번만 생성**한다. 컴포넌트가 재렌더돼도 재생성되지 않는다.
2. **`socket.disconnect()` 호출부는 단 한 곳** — `advisorSession.ts:27` 의 `clearAdvisorSessionState()`. 이는 **로그아웃 / 토큰만료 강제 로그아웃 시에만** 호출된다(`init.ts:46`, `postMessage.ts:98`). 21분에 8번 로그아웃했을 리 없다.
3. 화면 이탈 시엔 `leaveRoom()` 만 하고 **소켓은 끊지 않는다.**

→ **프론트가 능동적으로 끊는 코드는 없다.** 관측된 재연결은 **비자발적 끊김 후 Socket.IO 자동 재연결**로 판단된다.

### A1~A3. (백엔드→프론트) 백엔드 답변

**A1. 서버가 소켓을 끊나? → 아니오.**
`src/common/gateways/`, `main.ts` 전체 확인 — `socket.disconnect()` / `disconnectSockets()` / `.close()` **한 줄도 없음.** 서버가 능동적으로 끊는 일은 없다.

**A2. Ingress/프록시 WebSocket idle timeout → 확인 불가.**
Ingress 설정은 ArgoCD 별도 레포에 있어 확인 불가. 다만 원인일 가능성은 낮다고 판단:
- 서버 Socket.IO 설정이 `pingInterval: 25000` — 25초마다 ping이 오가 연결이 idle 상태가 되지 않는다. 통상적인 LB idle timeout(60초 이상)에 걸리지 않는다.
- disconnect 사유가 **전부 `transport close`, `ping timeout` 은 0건.** 네트워크 정지로 끊긴 거라면 `ping timeout` 이 떠야 한다.

**A3. 재연결 시 서버가 룸을 복구해주나? → 아니오. 클라이언트가 다시 `join-room` 해야 한다.** ⭐ **결정타**

> 코드로 확정. `client.join()` 을 부르는 곳은 `@SubscribeMessage('join-room')` 핸들러 딱 하나(`socket.gateway.ts:302`). `handleConnection()` 은 로그를 찍고 `connection-confirmed` 이벤트만 보내고 끝 — **룸 복구 로직이 전혀 없다.**
>
> 그리고 Socket.IO는 룸 멤버십을 **소켓 id 기준으로만** 들고 있다. 재연결하면 소켓 id가 새로 발급되니 이전 룸 정보는 전부 소멸한다. 서버엔 "이 사용자가 원래 어떤 방에 있었다"는 기록이 어디에도 없다.
>
> → **즉 `once("connect")` 버그는 지금 실제로 터지고 있다.** 재연결될 때마다 voc·nlp:partial 룸에 재조인이 안 되고, 서버는 그걸 복구해주지 않는다. 로그에서 본 것(**`2kPJ` 가 재연결 2초 뒤 6개 방만 join, voc 없음**)이 정확히 이 결과다.

### "누가 끊었나"는 미제 — 그리고 중요하지 않다

프론트도 안 끊고, 서버도 안 끊고, `ping timeout` 도 아니다. 남은 후보는 브라우저 탭 닫힘/새로고침/페이지 이동(정상) 또는 게이트웨이·ALB의 중간 절단. 21분에 8번이라면 그 시간에 여러 명이 테스트하며 탭을 여닫은 자연스러운 수치일 수도 있다. **원인 특정 실패.**

**그러나 이는 중요하지 않다.** 끊김의 원인이 무엇이든 **재연결은 반드시 일어나고, 그때마다 룸이 날아간다.** 끊김을 0으로 만드는 것은 불가능하다(사용자가 지하철에 타면 끊긴다).

> ⭐ **고쳐야 할 것은 "끊김"이 아니라 "재연결 후 복구가 안 되는 것"이다.**

### 합의된 조치

| 주체 | 조치 | 상태 |
|---|---|---|
| **프론트 (즉시)** | `once("connect")` → `on("connect")`. 이것으로 증상은 사라진다 | ✅ 완료 |
| **백엔드 (근본/안전망)** | 재연결 시 서버가 룸을 자동 복구 | 🔲 논의 중 |

**서버 룸 자동 복구에 대한 프론트 의견:** "클라이언트가 재조인한다"가 Socket.IO 정석 패턴이다. 서버가 복구하려면 재연결된 새 소켓이 "이전에 어느 방에 있었는지" 알아야 하는데, 소켓 id가 새로 발급되므로 **인증 주체(사용자/agent) 기준 룸 매핑을 서버가 별도로 보유**해야 한다. 없는 것을 새로 만드는 일이다.

→ **프론트 재조인 = 필수(완료).** **서버 자동 복구 = 있으면 좋은 안전망**(클라이언트가 여럿이라 같은 실수 반복을 막아주는 가치는 분명하나, 우선순위는 프론트 수정 뒤).

---

## 6. 재발 시 판별법

증상 재현 시 **브라우저 콘솔만 보면 프론트/백엔드가 즉시 갈린다.** (진단 로그는 이미 코드에 심어져 있음)

| 콘솔 로그 | 의미 | 책임 |
|---|---|---|
| `[voc] drop stale — voc.call=A current=B` | 메시지는 **도착했으나** 프론트 필터가 버림 | **프론트** (버그 2) |
| `[voc] received` 자체가 없음 | 메시지가 **아예 안 옴** → 룸 이탈 또는 미발행 | 버그 1 또는 **백엔드** (publish 로그와 대조) |
| 재연결 후 `[chat-sub] 채널 구독 및 룸 참가 완료: ...:call:voc` 가 **다시 안 찍힘** | 룸 재조인 실패 | **프론트** (버그 1) |
| `[voc-diag] agent_id mismatch drop` | `agent_id` 불일치 | 이 필터는 **STT와 공유**하므로, STT가 정상이면 이 경우는 아님 |

**정상 동작 확인법:** 소켓 재연결이 일어나도 콘솔에 `[chat-sub] 채널 구독 및 룸 참가 완료: {env}:{vendor_tenant_id}:{cc_cti_id}:call:voc` (예: `dev:4609686:56356659:call:voc`) 가 **매번 다시 찍히면** 정상이다.

---

## 7. 교훈

1. **"VOC만 안 되고 STT는 된다" 같은 선택적 증상은, 두 채널이 공유하지 않는 코드 경로를 찾으면 범인이 나온다.**
   - `drop stale` 필터 = VOC 전용
   - `once` vs `on` = 채널별 등록 방식 차이

2. **`once` vs `on` 은 재연결 안전성의 문제다.**
   - 소켓 **룸/구독**처럼 **연결마다 다시 세워야 하는 것** → 반드시 **`on`**
   - **이벤트 리스너**처럼 socket 객체에 붙어 유지되는 것 → `once` 로 충분

3. **책임 핑퐁이 붙으면 "말"이 아니라 "로그가 답을 정하게" 만들어라.** 6장의 판별표 한 장이면 프론트/백엔드가 즉시 갈린다.

4. **"DB에 매 턴 저장된다"는 관찰 하나가 가설 하나를 통째로 날렸다.** 증상 분석 시 **무엇이 성공했는지**를 먼저 확정하면 탐색 범위가 급격히 줄어든다.

5. **VOC 발행을 프론트 `/assist-stream` 호출에 종속시킨 설계는 실패작이다.** VOC만 "브라우저가 살아있고 네트워크가 성공해야 존재하는 데이터"가 되었다. 근본 해법은 백엔드가 `nlp:complete` 를 직접 구독해 자체 발행하는 것 — 다른 채널과 동일한 구조(§3-6). **이번 수정으로 증상은 잡히지만 구조적 취약성은 그대로 남아있다.**

6. **채널명(`cc_cti_id` 단위)은 무죄다 — 두 번 의심했고 두 번 다 아니었다.** 상담사의 지정 자리가 하나라 동시 통화가 없으므로, 채널이 상담사 단위여도 `call_id` 필터만 정상 동작하면 충분하다(§3-3). **채널명을 다시 의심하기 전에 §3-3 을 읽을 것.**

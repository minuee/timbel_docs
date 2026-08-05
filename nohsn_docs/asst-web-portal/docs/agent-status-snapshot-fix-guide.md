# 관리자 모니터링 — 상담사 상태 표시 수정 이관 가이드

> **대상** 다른 레포지토리의 `asst-web` (프론트, Vue 3 + Pinia)
> **범위** 관리자 모니터링 화면 전용. 상담사 본인 화면은 건드리지 않는다.
> **상태** 기준 레포 적용 완료 (`vue-tsc` 코드 에러 0, eslint 신규 위반 0)
>
> 두 가지를 다룬다. 서로 독립적이지만 **같은 파일을 건드리므로 함께 이관**하는 것을 권장한다.
>
> | 부 | 내용 |
> |---|---|
> | **1부** | 진입/새로고침 시 상담사 상태가 전부 "업무 외"로 뜨는 문제 |
> | **2부** | 모니터링 목록에 상담사(AGENT)가 아닌 계정까지 노출되는 문제 |

---

# 1부. 진입/새로고침 시 상태가 전부 "업무 외"

## 1-1. 증상

- 관리자 모니터링 진입 또는 **F5 새로고침** → 좌측 상담사 카드가 전부 **"업무 외"**.
- 실제로 통화 중인 상담사도 "업무 외"로 보인다.
- **그 상담사가 다음 상태 변경을 할 때까지** 틀린 상태로 남는다 (변경되는 순간 정상화).
- 목록을 스크롤해 추가 로드하면, 통화중이던 카드가 "업무 외"로 되돌아가기도 한다.

## 1-2. 상태가 화면에 뜨는 두 경로

이 구분이 이 문서 전체의 전제다.

| 경로 | 시점 | 담당 |
|---|---|---|
| **① 초기 pull** | 진입 / 새로고침 시 **1회** | `GET /agents` (주) → 실패 시 Redis 상태 해시 (폴백) |
| **② 실시간 push** | 상담사가 상태를 바꿀 때마다 | `/status` → Redis pub/sub → `agent-status-update` 소켓 |

**②는 이미 정상 동작하고 있고, 이 수정에서 손대지 않는다.** 고장난 건 ①이다.

> 실시간 이벤트는 성격상 "구독 시점 이후"만 전달된다. 새로고침한 브라우저는 소켓을 새로 연결하므로 과거 이벤트를 받을 방법이 없고, Redis pub/sub은 백로그도 없다. **따라서 새로고침 직후 화면을 채우는 것은 반드시 ①이어야 한다.** "상태 변경 시 발행하는 기능을 추가"하는 접근으로는 이 문제가 풀리지 않는다 (그 기능은 이미 있다).

### 초기 pull에 쓰는 API

```
GET {ASST_API_PREFIX}/agents        # 게이트웨이가 /api/asst/v1/agents 로 리라이트
헤더: x-auth-token: {토큰}

[{ "cc_cti_id": "ecp-4", "name": "나상담", "status": "AFTER_CALL", "updated_at": "..." }]
```

- `status` 5종 = `NOT_WORKING` / `WAITING` / `ON_CALL` / `AFTER_CALL` / `BREAK` — 프론트 `AgentStatus` enum과 동일.
- **프론트에 이미 있는 `AgentAPI.instance.getAgentList()` 가 이 엔드포인트다. 신규 API 개발 불필요.**

> ⚠️ **매칭 키 함정.** 위 응답의 `cc_cti_id` 값이 `"ecp-4"`인데, 상담사 목록 API에서 `ecp-4`는 **`agent_id`**이고 `cc_cti_id`는 `"56356659"`다. 즉 **필드명과 실제 값의 계열이 어긋나 있다.**
> 화면 카드는 `cc_cti_id` 기준으로 매칭하므로, 한쪽 키만 믿으면 **상태가 하나도 안 붙는다.**
> → 이 가이드는 **등록·조회 모두 `cc_cti_id` / `agent_id` 양쪽을 키 후보로** 둔다. 백엔드가 나중에 필드를 바로잡아도 계속 동작한다.

## 1-3. 근본 원인

### (A) 초기 pull을 너무 늦게 함 — 레이스 조건 (핵심)

카드를 만드는 `mapAgentToConsultant`는 상태값이 `undefined`면 `applyAgentStatusToConsultant`의 `default:` 분기를 타서 `nonActiveType: "offline"` → **"업무 외"**가 된다.

실행 순서가 이렇다:

| 순서 | 주체 | 동작 |
|---|---|---|
| ① | 리스트 컴포넌트 `onMounted` | **자체 API로 목록 조회 후 즉시 카드 매핑** |
| ② | 부모 관리자 화면 | `await Promise.allSettled([...API 6개...])` |
| ③ | 부모 관리자 화면 | `await getAgentsStatus()` → **여기서 처음으로** 상태 머지 |

①은 ②③과 병렬로 시작하고 API 하나만 기다리므로 **거의 항상 ③보다 먼저 끝난다.** 그 시점엔 상태 정보가 없어 전부 "업무 외"로 그려진다.

### (B) 늦게 온 상태가 반영 안 됨

`mapAgentToConsultant`는 한 번만 돌고, 만들어진 consultant는 평범한 객체다. `userListStore`를 감시하던 watch는 **주석 처리**되어 있어, ③이 나중에 값을 채워도 이미 그려진 카드는 갱신되지 않는다.

### (C) Redis 키 하드코딩

폴백 경로가 쓰는 해시 키가 두 화면에 `dev:global:call:status:active`로 **하드코딩**되어 있었다. 다른 채널은 전부 `CHANNEL_ENV` prefix를 쓰는데 이것만 `dev:` 고정이라, **운영 배포 시 키가 어긋나 항상 비게 된다.**

## 1-4. 조치

수정 대상 **6개 파일**. 대부분은 "두 화면에 복붙된 로직을 store 한 곳으로 이관"이라 실제 신규 로직은 적다.

| 파일 | 성격 |
|---|---|
| `src/utils/redisKey.ts` | 추가 (폴백 키) |
| `src/stores/modules/agentStatus.ts` | 추가 — **핵심** |
| `src/common/interface/user.ts` | 타입 1줄 |
| 리스트 컴포넌트 ×2 | 수정 |
| 관리자 화면 ×2 | **삭제** (로직이 store로 이관됨) |

> ⚠️ **현행 화면과 리뉴얼 화면 양쪽 모두** 같은 버그를 각자 갖고 있다. 한쪽만 고치면 다른 쪽은 그대로 남는다. 레포에 리뉴얼 화면이 없으면 해당 파일은 건너뛴다.
>
> | | 현행 | 리뉴얼 |
> |---|---|---|
> | 리스트 | `view/advisor/components/ConsultantDrawer/index.vue` | `view/advisor-renual/admin/monitoring/RenualConsultantList.vue` |
> | 관리자 화면 | `view/advisor/admin/index.vue` | `view/advisor-renual/admin/monitoring/index.vue` |

---

### 1-4-1. `src/utils/redisKey.ts` — 폴백 키 공용화

파일 맨 끝에 추가:

```ts
/**
 * 상담사 상태 스냅샷 해시 키 (field=cc_cti_id, value=status).
 *
 * `GET /agents` 가 실패하거나 status 를 안 줄 때의 **폴백 경로**에서 쓴다.
 *
 * 과거 두 화면에 `dev:global:call:status:active` 로 하드코딩돼 있었다. 다른 채널과 달리
 * 환경 prefix 가 안 붙어 운영에선 키가 어긋날 수 있어 voc 와 동일한 CHANNEL_ENV 로 통일한다.
 * CHANNEL_ENV 기본값이 'dev' 라 기존 환경은 동작 변화 없음.
 */
export const getAgentStatusSnapshotKey = () => `${CHANNEL_ENV}:global:call:status:active`;
```

> `CHANNEL_ENV`는 같은 파일에 이미 있는 `process.env.VITE_REDIS_CHANNEL_ENV || "dev"`다. 기본값이 `dev`라 **기존 환경은 동작이 100% 동일**하고, 운영에 `VITE_REDIS_CHANNEL_ENV=prd`를 넣을 때만 바뀐다.
>
> ⚠️ 운영 적용 전 **백엔드가 이 해시를 어떤 prefix로 쓰는지 확인**할 것. voc 채널은 `CHANNEL_ENV`로 합의되어 있으나 이 status 해시는 명시된 근거가 없다.

---

### 1-4-2. `src/stores/modules/agentStatus.ts` — 핵심

**import 추가:**

```ts
import { useUserListStore } from "@/stores/modules/userList";
import { getAgentStatusSnapshotKey } from "@/utils/redisKey";
```

**`useAgentStatusStore` 정의 위에 추가:**

```ts
/** 임의의 값이 유효한 AgentStatus 인지 (백엔드가 예상 밖 값을 줘도 화면이 깨지지 않도록) */
export const isAgentStatus = (value: unknown): value is AgentStatus =>
  typeof value === "string" && Object.values(AgentStatus).includes(value as AgentStatus);

/**
 * 상담사 항목이 내려준 상태 필드.
 *
 * ⚠️ `cc_status` 는 CTI 계정 상태라 **다른 개념**이므로 여기 넣으면 안 된다.
 * 필드명이 환경마다 다를 수 있어 후보를 두고, 유효한 AgentStatus 값일 때만 채택한다.
 */
const readStatusFromAgentItem = (agent: any): AgentStatus | undefined => {
  const candidates = [agent?.status, agent?.agent_status];
  return candidates.find(isAgentStatus);
};

/**
 * 상담사 1명을 스냅샷에서 찾을 때 쓸 키 후보.
 *
 * ⚠️ `GET /agents` 응답의 `cc_cti_id` 에 실제로는 agent_id 계열 값(예: "ecp-4")이 담겨 오는 사례가
 * 확인돼, 한쪽 키만 믿으면 매칭이 통째로 실패한다. 그래서 등록·조회 양쪽 모두 후보를 넓게 잡는다.
 */
const statusKeyCandidates = (agent: any): string[] =>
  [agent?.cc_cti_id, agent?.agent_id, agent?.ctiId, agent?.agentId].filter(
    (key): key is string => typeof key === "string" && key.length > 0
  );

/**
 * 상담사 카드에 표시할 상태 해석 — 우선순위 단일 소스.
 *
 *  1) 소켓으로 실시간 갱신된 값 (`_agentStatusTimestamp` 동반) — 스냅샷 API 응답보다 최신이므로 최우선.
 *     (이게 없으면, 상태가 막 바뀐 직후 목록을 다시 불러올 때 오래된 값이 최신값을 덮어쓴다)
 *  2) 상담사 목록 항목이 직접 들고 있는 status — 관리자 목록 API 가 status 를 포함하게 되면 여기 걸린다.
 *  3) userListStore 머지값(`_agentStatus`) — 스냅샷 유래.
 *  4) 상태 스냅샷(`GET /agents`) 조회값 — 목록을 자체 API 로 받는 컴포넌트가 userListStore 로드 전에 그려질 때.
 */
export const resolveAgentStatusFrom = (agent: any, snapshot: Record<string, string>): AgentStatus | undefined => {
  if (agent?._agentStatusTimestamp && isAgentStatus(agent._agentStatus)) return agent._agentStatus;

  const fromApi = readStatusFromAgentItem(agent);
  if (fromApi) return fromApi;

  if (isAgentStatus(agent?._agentStatus)) return agent._agentStatus;

  const fromSnapshot = statusKeyCandidates(agent)
    .map(key => snapshot?.[key])
    .find(isAgentStatus);
  return fromSnapshot;
};

/** 다양한 응답 래핑(`[]` / `{agents:[]}` / `{data:[]}` / `{data:{agents:[]}}`)에서 배열을 꺼낸다. */
const extractAgentArray = (payload: any): any[] => {
  const candidates = [payload, payload?.data, payload?.agents, payload?.data?.agents, payload?.data?.data];
  return candidates.find(Array.isArray) ?? [];
};

/**
 * 주 경로 — `GET {ASST_API_PREFIX}/agents` 로 상담사별 현재 상태를 받아 (식별자 → status) 맵으로 만든다.
 *
 * 응답의 `cc_cti_id` 에 agent_id 계열 값이 담겨 오는 사례가 있어, 한 상담사를 **여러 키로 등록**한다.
 * 어느 식별자로 조회해도 매칭되게 하기 위함이며, 키가 겹칠 일은 실질적으로 없다.
 *
 * 유효한 status 가 하나도 없으면 `null` 을 반환해 호출부가 Redis 폴백을 타게 한다.
 */
const fetchStatusMapFromAgentList = async (): Promise<Record<string, string> | null> => {
  try {
    const response = await AgentAPI.instance.getAgentList();
    const agents = extractAgentArray(response?.data ?? response);
    const statusMap: Record<string, string> = {};

    agents.forEach((agent: any) => {
      const status = readStatusFromAgentItem(agent);
      if (!status) return;
      statusKeyCandidates(agent).forEach(key => {
        statusMap[key] = status;
      });
    });

    if (Object.keys(statusMap).length === 0) {
      console.log("[AgentStatus] GET /agents 응답에 유효한 status 없음 → Redis 스냅샷으로 폴백");
      return null;
    }

    return statusMap;
  } catch (error) {
    console.warn("[AgentStatus] GET /agents 조회 실패 → Redis 스냅샷으로 폴백:", error);
    return null;
  }
};

/**
 * 폴백 경로 — Redis 상태 해시(field=cc_cti_id, value=status) 직접 조회.
 * `GET /agents` 가 실패하거나 status 를 안 줄 때만 쓴다.
 */
const fetchStatusMapFromRedis = async (): Promise<Record<string, string> | null> => {
  const response = await AgentAPI.instance.getAgentStatusFromRedis(getAgentStatusSnapshotKey());
  return (response?.data ?? null) as Record<string, string> | null;
};

/**
 * 진행 중인 스냅샷 요청. 관리자 화면(부모)과 상담사 목록(자식)이 각각 호출해도
 * 실제 API 는 1회만 나가고 모두 같은 완료 시점을 기다리도록 공유한다.
 * (자식 onMounted 가 부모보다 먼저 도는 구조라 호출 주체를 한쪽으로 몰 수 없음)
 */
let snapshotInflight: Promise<void> | null = null;
```

**`state`에 추가:**

```ts
  state: () => ({
    currentStatus: AgentStatus.NOT_WORKING as AgentStatus,
    /**
     * 상담사 상태 스냅샷 (식별자 → status). **관리자 모니터링 전용** — 진입/새로고침 시 1회 조회.
     *
     * 상담사 본인 화면에서는 쓰지 않는다(본인 상태는 currentStatus).
     * 같은 상담사가 cc_cti_id / agent_id 양쪽 키로 등록될 수 있다(statusKeyCandidates 주석 참고).
     */
    statusByCtiId: {} as Record<string, string>,
    /** 스냅샷을 1회라도 조회했는지 (빈 스냅샷과 미조회를 구분) */
    snapshotLoaded: false
  }),
```

**`actions`에 추가:**

```ts
    /**
     * 상담사 상태 스냅샷을 조회해 store + userListStore 에 반영한다. **관리자 모니터링 전용.**
     *
     * 주 경로는 `GET {ASST_API_PREFIX}/agents` (게이트웨이가 `/api/asst/v1/agents` 로 리라이트).
     * 응답 예: `[{ cc_cti_id, name, status, updated_at }, ...]` — status 5종은 AgentStatus 와 동일.
     *
     * 이 조회는 **진입/새로고침 시 1회성**이다. 이후 상담사가 상태를 바꾸면
     * `/status` → Redis pub/sub → `agent-status-update` 소켓 이벤트로 실시간 갱신된다(그 경로는 그대로).
     * 동시 호출은 in-flight promise 를 공유해 API 가 중복으로 나가지 않는다.
     */
    async fetchStatusSnapshot(): Promise<void> {
      if (snapshotInflight) return snapshotInflight;

      // finally 에서 snapshotInflight 를 비우므로, 반환값은 지역 변수로 잡아둔다.
      const request = (async () => {
        try {
          const statusMap = (await fetchStatusMapFromAgentList()) ?? (await fetchStatusMapFromRedis());

          this.snapshotLoaded = true;

          if (!statusMap || Object.keys(statusMap).length === 0) {
            console.log("[AgentStatus] 상담사 상태 스냅샷 없음");
            return;
          }

          this.statusByCtiId = { ...statusMap };

          // userListStore 에도 머지 — HeaderActionBar 등이 agent._agentStatus 를 읽는다.
          const userListStore = useUserListStore();
          const agents = userListStore.agents;
          let hasChange = false;

          const updatedAgents = agents.map((agent: any) => {
            const status = statusKeyCandidates(agent)
              .map(key => statusMap[key])
              .find(isAgentStatus);
            if (!status) return agent;
            // socket 이벤트로 이미 더 최신 상태를 받았다면 덮어쓰지 않음
            if (agent._agentStatusTimestamp) return agent;
            if (agent._agentStatus === status) return agent;

            hasChange = true;
            return { ...agent, _agentStatus: status };
          });

          if (hasChange) {
            userListStore.setAgents(updatedAgents);
          }

          console.log(`[AgentStatus] 상담사 상태 스냅샷 로드 완료 (${Object.keys(statusMap).length}건)`);
        } catch (error) {
          console.error("[AgentStatus] 상담사 상태 스냅샷 조회 실패:", error);
        } finally {
          snapshotInflight = null;
        }
      })();

      snapshotInflight = request;
      return request;
    },

    /** 소켓으로 받은 개별 상태를 스냅샷에도 반영 (뒤늦게 그려지는 카드가 최신값을 쓰도록) */
    setSnapshotStatus(ccCtiId: string, status: string) {
      if (!ccCtiId || !status) return;
      this.statusByCtiId = { ...this.statusByCtiId, [ccCtiId]: status };
    }
```

> **모든 실패를 store 안에서 삼킨다.** `GET /agents` 실패 → Redis 폴백, 그것도 실패 → `catch`로 로그만. 호출부가 `await` 해도 reject되지 않으므로 **목록 로딩은 무조건 정상 진행**된다. 이게 "최악의 경우 = 수정 전과 동일"을 보장하는 지점이다.

---

### 1-4-3. `src/common/interface/user.ts` — 타입 자리 마련

`Agent` 인터페이스에 추가 (`assigned_workspace_id` 아래쯤):

```ts
  /**
   * 상담사 근무 상태(AgentStatus: NOT_WORKING/WAITING/ON_CALL/AFTER_CALL/BREAK).
   *
   * 관리자 상담사 목록 API 응답에는 아직 없어서 optional.
   * 내려오기 시작하면 `resolveAgentStatusFrom`(stores/modules/agentStatus.ts)이
   * 자동으로 이 값을 우선 사용한다 — 프론트 추가 작업 불필요.
   *
   * ⚠️ 위의 `cc_status` 는 CTI 계정 상태로 **다른 개념**이다. 혼동 주의.
   */
  status?: string;
```

---

### 1-4-4. 리스트 컴포넌트 ×2

**현행·리뉴얼 둘 다 동일하게** 4곳을 고친다.

**(1) import + store 인스턴스**

```ts
import { AgentStatus, useAgentStatusStore, resolveAgentStatusFrom } from "@/stores/modules/agentStatus";
// ...
const agentStatusStore = useAgentStatusStore();
```

**(2) `onMounted` — 카드를 그리기 전에 스냅샷 확보** ← 레이스 해소의 핵심

```ts
onMounted(async () => {            // ← async 로 변경
  const socket = getSocket();
  if (socket.connected) {
    onSocketConnected();
  } else {
    socket.once("connect", onSocketConnected);
  }

  // 카드를 그리기 전에 상태 스냅샷을 먼저 확보한다.
  // (스냅샷이 없으면 전부 "업무 외"로 그려지고, 이 컴포넌트는 한 번 그린 카드를
  //  다시 매핑하지 않아 새로고침 때마다 오표시됐음)
  await agentStatusStore.fetchStatusSnapshot();

  void preloadInitialConsultantLists();
});
```

> 소켓 리스너 등록은 `await` **앞**에 그대로 두어야 이벤트를 놓치지 않는다.
> 리뉴얼 컴포넌트에 `await ensureBootstrapped()`가 있으면 그 **다음**에 넣는다.

**(3) 상태 해석을 공용 함수로 + 매핑에 적용**

```ts
/** 상담사의 현재 상태 해석. 우선순위 정의는 stores/modules/agentStatus.ts 의 resolveAgentStatusFrom 참고. */
const resolveAgentStatus = (agent: any) => resolveAgentStatusFrom(agent, agentStatusStore.statusByCtiId);
```

`mapAgentToConsultant` 안의 두 곳을 교체:

```diff
-    agentStatus: fallbackAgent._agentStatus as AgentStatus,
+    agentStatus: resolveAgentStatus(fallbackAgent),
```
```diff
-  applyAgentStatusToConsultant(consultant, fallbackAgent._agentStatus as AgentStatus);
+  applyAgentStatusToConsultant(consultant, resolveAgentStatus(fallbackAgent));
```

**(4) 소켓 핸들러에서 스냅샷도 갱신 + 늦은 스냅샷용 watch**

`handleAgentStatusUpdate` 첫 줄에 추가:

```ts
  agentStatusStore.setSnapshotStatus(data.cc_cti_id, status);
```

> 이게 **스크롤 추가로드 시 통화중 카드가 "업무 외"로 리셋되던 버그**를 막는다. 새로 매핑되는 카드가 스냅샷에서 최신값을 집어오기 때문.

`mapAgentToConsultant` 아래에 watch 추가:

```ts
/**
 * 스냅샷이 카드보다 늦게 도착한 경우의 안전망.
 * 아직 상태가 정해지지 않은(=기본 "업무 외"로 그려진) 카드만 채운다.
 * 소켓 이벤트로 이미 상태를 받은 카드는 agentStatus 가 있으므로 덮어쓰지 않는다.
 */
watch(
  () => agentStatusStore.statusByCtiId,
  statusMap => {
    updateLoadedConsultants(
      consultant => !consultant.agentStatus && Boolean(statusMap[consultant.ctiId]),
      consultant => {
        applyAgentStatusToConsultant(consultant, statusMap[consultant.ctiId] as AgentStatus);
      }
    );
  }
);
```

> `!consultant.agentStatus` 조건이 **소켓으로 받은 최신값을 덮어쓰지 않게** 하는 가드다. 빼면 안 된다.

---

### 1-4-5. 관리자 화면 ×2 — 중복 로직 삭제

양쪽에서 `getAgentsStatus` **함수 본문 전체(약 30줄)를 지우고** 한 줄로 교체:

```ts
// 상담사 상태 스냅샷 조회는 agentStatus store 로 이관(리스트 컴포넌트와 공유).
// 자식 onMounted 가 부모보다 먼저 돌기 때문에 양쪽에서 호출하되,
// store 가 in-flight 를 공유해 API 는 1회만 나간다.
const getAgentsStatus = () => useAgentStatusStore().fetchStatusSnapshot();
```

`import { useAgentStatusStore } from "@/stores/modules/agentStatus";` 추가.

`onAgentStatusUpdate` 핸들러 첫 줄에도 추가:

```ts
  // 스냅샷에도 반영 — 이 이벤트 이후에 그려지는 카드(스크롤 추가로드/탭 전환)가 최신값을 쓰도록
  useAgentStatusStore().setSnapshotStatus(data.cc_cti_id, data.status);
```

> 기존 호출부(`await getAgentsStatus()`, 드로어 펼침 watch 등)는 **그대로 두면 된다.** 반환 타입이 `Promise<void>`로 동일하다.
> `AgentAPI`가 그 파일에서 더 이상 안 쓰이면 import를 지운다 (lint 경고 방지).

## 1-5. 검증

### 콘솔 로그로 경로 판별

```
[AgentStatus] 상담사 상태 스냅샷 로드 완료 (N건)                    ← 정상
[AgentStatus] GET /agents 응답에 유효한 status 없음 → Redis 폴백    ← API는 되나 status 미포함
[AgentStatus] GET /agents 조회 실패 → Redis 스냅샷으로 폴백: ...    ← API 오류(권한/경로 확인)
[AgentStatus] 상담사 상태 스냅샷 없음                               ← 두 경로 모두 빈 결과
```

> **"로드 완료 (N건)"이 떴는데도 카드가 여전히 "업무 외"라면 매칭 키 문제다.** 콘솔에서 스냅샷 키와 카드의 `ctiId`를 대조할 것. (그래서 키 후보를 넓게 잡아뒀다)

### 체크리스트

- [ ] 관리자 모니터링 진입 → 통화중 상담사가 "상담 중"으로 표시되는가
- [ ] **F5 새로고침** → 상태가 유지되는가 ← 이번 수정의 핵심
- [ ] 목록 스크롤로 추가 로드 → 기존 통화중 카드가 "업무 외"로 리셋되지 않는가
- [ ] 검색/필터 적용 → 상태가 유지되는가
- [ ] 드로어 접었다 펴기 → 상태가 유지되는가
- [ ] 상담사가 실제로 상태를 바꿈 → **실시간으로 카드가 바뀌는가** (기존 기능 회귀 확인)

### 빌드 검증

```bash
npx vue-tsc --noEmit        # 코드 에러 0 (tsconfig deprecation 경고는 무관)
npx eslint <수정한 파일들>
```

> 기존 prettier 위반이 많은 레포가 있다. **수정 전 위반 개수를 미리 세어두고 비교**하면 이번 변경이 새 위반을 만들었는지 알 수 있다. 기존 위반을 `--fix`로 일괄 정리하면 변경 범위가 뒤섞이니 권장하지 않는다.

## 1-6. 리스크

| 항목 | 평가 |
|---|---|
| `GET /agents` 실패 | Redis 폴백 → 그것도 실패하면 `catch`. **목록 로딩은 정상 진행** |
| 두 경로 모두 실패/빈 결과 | 전부 "업무 외" = **수정 전과 동일** (악화 없음) |
| 소켓 실시간 기능 | 건드리지 않음. watch 가드로 최신값 덮어쓰기 방지 |
| 매칭 키 불일치 | `cc_cti_id`/`agent_id` 양쪽 등록·조회로 방어 |
| 예상 밖 status 값 | `isAgentStatus()`로 검증 후 다음 순위로 폴백 |
| 변경량 | 커 보이나 대부분 "두 화면 중복 로직 → store 이관". 관리자 화면 2개는 **순감소** |

**최악의 경우가 "수정 전과 동일"**이라 다운사이드가 없다.

---

# 2부. 모니터링 목록에 AGENT 역할만 노출

## 2-1. 증상

관리자 모니터링 좌측 목록에 **상담사가 아닌 계정까지 전부** 노출된다. (`ADMIN`, `SUPERVISOR`, `SYSTEM`, 배치 전용 계정 등)

## 2-2. 제약과 함정

서버 API(`GET /agents/assignable`)에 **role 필터 파라미터가 없다.** 지원하는 건 `center_id` / `team_id` / `part_id` / `part_ids` / `name` / `favorite_only` / `page` / `limit` 뿐. → **클라이언트 필터로 처리한다.**

이때 페이지네이션과 충돌하는 함정이 있다:

```
1페이지 요청 → 10건 수신 → 전부 ADMIN/SUPERVISOR → 필터 후 0건
  ↓
화면이 비어 보임 + 스크롤이 안 생김 → 다음 페이지 로드가 영영 트리거 안 됨 ❌
```

그래서 **결과가 0건이면 다음 페이지를 자동으로 이어받아야** 한다.

## 2-3. 조치

### (1) `src/common/interface/user.ts` — 공용 함수 추가

`getAgentsOfAdminPage` 아래에 추가:

```ts
/** 관리자 모니터링 상담사 목록에 노출할 역할 (SUPERVISOR/ADMIN/SYSTEM 등은 제외) */
const MONITORING_ROLE = "AGENT";

/**
 * AGENT 역할만 남긴다.
 *
 * ⚠️ `role` 필드가 아예 없는 응답(구버전/타 환경)은 **통과시킨다.**
 * 엄격히 걸렀다가 role 을 안 내려주는 환경에서 목록이 통째로 비어버리는 사고를 막기 위함.
 */
export const keepAgentRoleOnly = (items: any[]): any[] =>
  items.filter(item => item?.role == null || item.role === MONITORING_ROLE);

/**
 * 관리자 모니터링용 상담사 목록 — **AGENT 역할만** 반환.
 *
 * 서버(`/agents/assignable`)에 role 필터 파라미터가 없어 클라이언트에서 거른다.
 * 그러다 보니 해당 페이지가 전부 관리자/슈퍼바이저면 결과가 0건이 되는데,
 * 그대로 두면 목록이 비어 보이고 스크롤도 안 생겨 다음 페이지 로드가 영영 트리거되지 않는다.
 * → 결과가 0건이면 다음 페이지를 **자동으로 이어 받는다.**
 *
 * page 를 지정하지 않은 호출(검색 시 전체 조회)은 페이지 개념이 없으므로 필터만 적용한다.
 *
 * (백엔드에 role 필터 파라미터가 추가되면 이 함수는 서버 파라미터 전달로 단순화 가능)
 */
export async function getMonitoringAgentsPage(
  type = "permission",
  params: AdminAgentQueryParams = {},
  maxPageScan = 10
): Promise<AdminAgentPageResult> {
  // 전체 조회(page 미지정): 이어받기 없이 필터만
  if (params.page === undefined) {
    const result = await getAgentsOfAdminPage(type, params);
    return { items: keepAgentRoleOnly(result.items), meta: result.meta };
  }

  let page = params.page;
  let result = await getAgentsOfAdminPage(type, { ...params, page });
  let items = keepAgentRoleOnly(result.items);
  let scanned = 1;

  // AGENT 가 한 명도 없으면 다음 페이지로 계속 진행 (maxPageScan 은 무한루프 가드)
  while (items.length === 0 && result.meta.has_next && scanned < maxPageScan) {
    page += 1;
    result = await getAgentsOfAdminPage(type, { ...params, page });
    items = keepAgentRoleOnly(result.items);
    scanned += 1;
  }

  if (scanned > 1) {
    console.log(`[API: user] 모니터링 목록 — 비-AGENT 페이지 ${scanned - 1}개 건너뜀 (최종 page=${result.meta.page})`);
  }

  return { items, meta: result.meta };
}
```

### (2) 리스트 컴포넌트 ×2 — 호출 함수만 교체

**`getAgentsOfAdminPage` → `getMonitoringAgentsPage`** 로 전부 치환. import 1곳 + 호출 3곳(총 4곳)이다. 시그니처가 동일해서 **호출 인자는 그대로** 둔다.

## 2-4. 건드리지 않는 것 (의도적)

- **관리자 화면 부모의 `setAgentsOfAdminInStore`(→ `userListStore`)** 는 그대로 둔다.
  `userListStore`는 좌측 목록 전용이 아니라 소켓 채널 구독(`setAgentMessageListener`)·상태 매칭·`HeaderActionBar` 등에서 공용으로 쓰인다. 여기를 필터하면 부수효과 범위가 커진다.
  비-AGENT 계정은 대체로 `cc_cti_id`가 `null`이라 채널 구독 대상에서 자연 배제되므로 실익도 적다.
- **사용자 관리 화면**(`advisor-renual/admin/agents/index.vue` 등)은 `getAgentsOfAdminPage`를 계속 쓴다. 거기선 전체 역할이 보여야 정상이다. → **치환은 리스트 컴포넌트 2개에서만.**

## 2-5. 검증

- [ ] 모니터링 좌측 목록에 `ADMIN` / `SUPERVISOR` / `SYSTEM` 계정이 안 보이는가
- [ ] 스크롤 추가 로드가 정상 동작하는가
- [ ] 이름 검색 결과에도 AGENT만 나오는가
- [ ] 관심(즐겨찾기) 탭도 AGENT만 나오는가
- [ ] 사용자 관리 화면에는 여전히 **전체 역할**이 보이는가 (회귀 확인)

---

# 부록. 백엔드에 요청하면 좋은 것

모두 **이 수정과 무관하게 진행 가능**하며, 반영되면 프론트가 자동으로 더 나은 경로를 탄다.

| # | 요청 | 효과 |
|---|---|---|
| 1 | `GET /agents` 응답의 **`cc_cti_id` 필드값 정합성 확인** | 현재 `agent_id` 계열 값이 담겨 오는 것으로 보인다. 바로잡히면 키 후보 방어가 불필요해진다 (그대로 둬도 무해) |
| 2 | 관리자 상담사 목록 API에 **`status` 포함** | `resolveAgentStatusFrom` 2순위로 자동 채택 → 스냅샷 조회(`fetchStatusSnapshot`)를 통째로 제거 가능. 필드명은 `status` 권장 (`cc_status`는 CTI 계정 상태라 별개) |
| 3 | `GET /agents/assignable` 에 **`role` 쿼리 파라미터** | 2부의 페이지 스캔 로직 제거, 페이지네이션 메타(`total_count`)도 정확해짐 |
| 4 | Redis 상태 해시의 **환경 prefix 확인** (운영 배포 전) | 현재 키 `{CHANNEL_ENV}:global:call:status:active`. 프론트만 `prd`로 바뀌면 폴백 경로가 어긋난다 |

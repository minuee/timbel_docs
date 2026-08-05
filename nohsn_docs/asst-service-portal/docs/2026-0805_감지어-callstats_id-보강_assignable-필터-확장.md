# 2026-08-05 작업 이력 — 감지어 이력 `callstats_id` 보강 / assignable 필터 확장 / 통화이력 API 확장 / Dozzle 그룹핑

## 요약

네 갈래 작업.

1. **감지어 탐지 이력 목록에 `callstats_id` 추가** — 어제 만든 기능의 보완. 이력에서 통화 상세로 넘어갈 키가 없던 문제
2. **`GET /agents/assignable` 파라미터 2건 대응** — `agent_id`(400 나던 것) / `role`(신규 필터)
3. **Dozzle 컨테이너 그룹핑** — 그룹핑 조건 조사 후 라벨 적용
4. **통화이력 API 확장** — 프론트 요청서(`docs/call-history-admin-api-request.md`) 7개 항목 전건 반영

관련 커밋: `c135e57` 감지어의 id 추가 / `1356b6a` get_user 의존성 제거 / `90eac5e` 상담사리스트조회 필터 추가 / `08edb26` docker setup

---

## 1. 감지어 탐지 이력에 `callstats_id` 추가

### 문제

`advisor.keyword_detect_logs` 는 `call_id`(assist-stream `dto.callId`)만 들고 있는데,
요약(`advisor.summary`) · 감정(`advisor.emotions`) · 할일(`advisor.todos`) 은 전부
`raw_call.callstats_call.id` 를 키로 쓴다. 그래서 이력 목록에서 통화 상세로 연결할 방법이 없었다.

### 결정: 컬럼 추가 대신 **조회 시점 조인**

감지는 통화 **중**에 일어나고 `callstats_call` 행은 통화 **종료 후** 적재된다.
저장 시점에 `callstats_id` 를 컬럼으로 박아두면 대부분 NULL 이 된다.
이미 `agent_name`·`keyword_update_at` 을 조회 시점에 채우는 `attachDisplayInfo()` 패턴이 있어 거기에 얹었다.
**DB 스키마 변경 없음.**

### 구현

- `KeywordDetectLogService.loadCallstatsIds()` 신설
  - 그 페이지 행들의 distinct `call_id` 를 모아 `raw_call.callstats_call` 을 **쿼리 1회**로 조회
    (`id IN (...) OR call_id IN (...)`)
  - `call_id → callstats_call.id` 맵을 만들되, **id 매칭이 call_id 매칭을 이기도록** 나중에 덮는다
    (호출측이 어느 쪽 값을 `callId` 로 넘겼는지 시점·환경마다 다를 수 있음 — `summary.service.ts:126-135` 와 같은 관례)
- `KeywordDetectLogWithAgentDto.callstats_id: string | null` 추가
- `call_id` 는 **그대로 둔다.** 덮어쓰지 않고 필드만 추가했다.

### 프론트 주의사항

- 통화 상세 연결은 `callstats_id` 를 쓴다
- **아직 적재되지 않은 통화(진행 중이거나 적재 전)는 `null`** — 그 행엔 링크를 걸지 말 것
- 집계 API(`/keyword-detect-logs/stats`)와 필터에는 넣지 않았다. 목록 전용

문서: `docs/keyword-detect-logs-api.md` 갱신 완료

---

## 2. `GET /agents/assignable` 파라미터 대응

### 2-1. `agent_id` — 400 나던 문제

**증상**

```
GET /agents/assignable?...&favorite_only=true&agent_id=170db32f-...
→ 400 {"message":["property agent_id should not exist"]}
```

**원인**

`AppValidationPipe` 가 `/assist-stream` 을 뺀 전 경로에 `forbidNonWhitelisted: true` 로 걸려 있는데
(`src/common/pipes/app-validation.pipe.ts:62`), `QueryAdminAssignableAgentsDto` 에 `agent_id` 가 없었다.
**컨트롤러 진입 전에** 잘린 것이라 서버 로직 문제가 아니다.

**프론트의 의도** (확인함)

- `favorite_only=true` → 필터 스위치 ("즐겨찾기만 줘")
- `agent_id=<UUID>` → 그 필터의 **주인** ("내 즐겨찾기 기준으로")

**조치**

`agent_id` 를 DTO에 추가하고, 즐겨찾기 조회의 `user_key` 로 직접 썼다.
그 결과 **`getCurrentUser()` (= `GET /api/user/get_user`) 호출을 이 경로에서 제거**했다 — 요청당 외부 호출 1회 감소.

```ts
// 변경 전: 주인을 토큰으로 알아내려고 user-service 를 매 요청 호출
const currentUser = await this.userInfoService.getCurrentUser(validatedToken);
where: { user_key: currentUser.agent.id }

// 변경 후: 프론트가 보낸 값을 그대로 사용
if (!queryDto.agent_id) throw new BadRequestException('favorite_only=true 인 경우 agent_id...');
where: { user_key: queryDto.agent_id }
```

폴백(없으면 `get_user` 호출)을 **두지 않은 이유**: 프론트에서 `favorite_only=true` 는 항상 `agent_id` 를
동반한다고 확인받았고, `get_user` 의존 제거가 진행 중인 방향이기 때문.
→ `docs/user-info-payload-migration.md` 의 "프론트 작업 2건" 중 **즐겨찾기 `agent_id` 건 완료.**
남은 건 코칭 `vendor_tenant_id`.

### 2-2. `role` — 신규 필터

```
GET /agents/assignable?...&role=AGENT     ← 상담사만 추출
```

**구현**: `role?: string` DTO 추가 + `matchesRoleFilter()` (기존 `matchesNameFilter()` 와 같은 자리·패턴).
`name` 필터와 함께 **페이지 계산 전에** 걸리므로 `agents_cnt` / `meta.total_count` 도 필터 후 기준으로 정확하다.

**판단 3건**

| 판단 | 이유 |
|---|---|
| user-service 로 위임하지 않고 **서버에서 거른다** | `/api/user/assignable` 의 `role` 지원 여부를 확인할 수 없었고, 응답 객체(`AssignableAgentInfo.role`)에 값이 이미 있다. `name`·`favorite_only` 도 이미 로컬 필터라 방식도 일관됨. 상위 지원이 확인되면 위임으로 바꾸는 편이 효율적 |
| 값 목록을 **고정하지 않는다** (`@IsIn` 미사용) | 확인된 값은 `AGENT` 뿐인데 목록을 박으면 새 role 이 생겼을 때 400 으로 프론트가 먼저 깨진다. 어제 `/assist-stream` 400 사고와 같은 종류 |
| 대소문자·공백 정규화 후 비교 | `role=agent` 로 와도 동작. 단 role 이 빈 사용자는 필터가 걸리면 제외됨 |

---

## 3. Dozzle 컨테이너 그룹핑

### 그룹핑 조건 (조사 결과)

Dozzle 은 **라벨**로 자동 그룹핑하며 우선순위는:

1. `com.docker.swarm.service.name` (swarm 모드)
2. `com.docker.compose.project` ← 기존에 걸려 있던 것
3. `dev.dozzle.group` (커스텀)

백엔드와 dozzle 이 한 그룹이던 이유: **Compose 는 `-p` 가 없으면 프로젝트명을 "compose 파일이 있는
디렉터리 이름"에서 뽑는다.** `-f` 로 파일을 달리 지정해도 프로젝트명은 안 바뀐다.
두 compose 파일을 같은 디렉터리에서 올려서 프로젝트명이 같아진 것.

### 조치

`docker-compose.dev.portal.yml`(asst-service) / `docker-compose.monitor.yml`(dozzle) 두 곳에 라벨 추가:

```yaml
labels:
  - dev.dozzle.group=aicc-madeby-noh-service
```

> 라벨은 컨테이너 **생성 시점**에 박히므로 `restart` 로는 반영되지 않는다. `up -d` 로 recreate 필요.

### 남은 일

- **asst-web 은 아직 미적용** (다른 저장소). 같은 라벨을 같은 값으로 넣어야 한다 — 대소문자·오타 하나라도 다르면 그룹이 쪼개진다.
- 커스텀 라벨과 compose 프로젝트 그룹핑의 우선순위를 **공식 문서가 명시하지 않는다.** 라벨이 안 먹으면
  대안은 asst-web compose 최상단에 `name: <프로젝트명>` 을 박아 프로젝트명을 맞추는 것.
  단 그 경우 기존 프로젝트명으로 먼저 `down` 해야 하고(컨테이너 이름 충돌), external 이 아닌 볼륨/네트워크는 새로 생성된다.

참고: [Container Groups | Dozzle](https://dozzle.dev/guide/container-groups) ·
[Specify a project name | Docker Docs](https://docs.docker.com/compose/how-tos/project-name/)

---

## 4. 통화이력 API 확장 (`GET /callstat/call-history`)

프론트 요청서 `docs/call-history-admin-api-request.md` 대응. 관리자 통화이력 화면이
`/callstat/calls` → `/callstat/call-history` 로 갈아탈 수 있게 하는 게 목적이다.

### 반영 내역

| 요청 | 결과 |
|---|---|
| `agent_id` 필수 → 선택 | ✅ 생략 시 전체 상담사 |
| `sort_order` | ✅ `desc` 기본, `/callstat/calls` 와 동일 규격 |
| `agent_name` (+`agent_cti_id`) | ✅ `advisor.agents` 조인 |
| `center_id`/`team_id`/`part_id` | ✅ assignable 경유 `IN` 필터 |
| 콜별 감지어 건수 | ✅ 1안 채택 — `detect_count`, `detects[{type,count}]` |
| `/keyword-detect-logs` `callstats_id` 필터 | ✅ 목록·집계 양쪽 |
| 권한 정책 확정 | ✅ **게이트 안 걸기로 결정** (아래) |

추가로 `direction`(I/O) 필터도 넣었다 — 요청서에는 없었지만 프론트가 보내기로 해서다.

### 결정 1: 생략 호출에 권한 게이트를 걸지 않는다

프론트는 "관리자 권한에서만 허용"을 요청했지만, 조사 결과 **이 서비스에는 권한 게이트가 아예 없다.**

- `AdminGuard` 는 존재하지만 **어디에도 붙어 있지 않다** (`AdminOnly` 사용처 0건)
- 그 가드가 읽는 `request.userRole` 은 **아무 데서도 채워지지 않는다** (선언만 있음)
- **`/callstat/calls` 는 이미 org-wide 다** — 필터가 전부 선택값이라, 지금도 아무 상담사 토큰으로
  호출하면 조직 전체 통화가 나온다

즉 `call-history` 의 `agent_id` 를 선택으로 바꾸는 것은 **새로 뚫는 구멍이 아니라 기존 구멍과 동일**하다.
검토 초안에서는 "assignable 결과로 IN 필터를 걸어 권한 게이트를 대신하자"고 제안했으나,
옆 API 와 동작만 어긋나고 실익이 없어 **철회했다.**

> ⚠️ **별건으로 남김**: 통화 이력 org-wide 노출에 권한 통제가 없다는 것 자체.
> 손대려면 `userRole` 을 채우는 인증 미들웨어부터 만들어야 한다.

### 결정 2: 상담사를 특정 못 하면 이름을 비운다

프론트는 *"cc_cti_id 중복 때문에 조인이 실패하니 백엔드가 이름을 실어주면 해결된다"* 고 봤지만,
**조인 위치만 옮겨질 뿐 중복은 그대로다.** `56356659` 가 두 계정(agent40·agent41)을 가리키면
서버가 조인해도 어느 이름인지 모른다.

그래서 **모호하면 임의로 고르지 않고 `null` + 경고 로그**로 처리했다.
준법감시 성격의 화면에서 *남의 이름이 통화에 붙는 것*은 빈칸보다 위험하다는 판단이다.

```
통화이력 상담사 특정 실패 — 키 중복으로 이름을 비움: agent_id=..., 후보=...
```

근본 대책은 user-service 계정 데이터 정리(별건, 프론트에 회신 완료).

### 구현 메모

- `callstats_call.agent_id` 에 **CTI ID 계열이 올지 agent_id 계열이 올지 통화마다 다르다.**
  `advisor.service.ts:97-106`(`getCallableAgentIds`)이 두 값을 모두 후보로 쓰는 이유이고,
  이번에 추가한 `loadAgentDisplays()` / `resolveOrgAgentIds()` 도 같은 관례를 따랐다.
- 감지어 건수도 같은 이유로 `call.id` 와 `call.call_id` 를 모두 후보 키로 넣어 집계한다.
- 감지어·상담사 조회는 **실패해도 목록 전체가 500 이 되지 않게 격리**했다(0건/null 로 응답).
  VOC 조회가 이미 쓰던 방식과 같다.
- 조직 필터가 하나도 없으면 user-service 호출 자체를 하지 않는다.

### 부수 영향

- `CallStatsQueryDto` 를 공유하는 `/callstat/agent-summary`, `/callstat/agent-summary/stats` 도
  `agent_id` 가 선택이 됐다. 생략하면 전체 기준으로 나온다.
- `meta.agent_id` 가 `string | null` 이 됐다(전체 조회 시 null).
- raw 조회에 중복으로 걸려 있던 `agent_id` 조건을 제거했다(이미 필터를 통과한 id 목록을 다시
  거르던 코드라 결과는 동일).

### `direction` 관련 확인 사항

- 값은 `I`(인바운드) / `O`(아웃바운드) 로 저장된다. 한때 `IN`/`OUT` 이었으나 **I/O 로 정리됨.**
- 서버는 원본 값을 그대로 내려준다. 화면의 `I/B`·`O/B` 표기는 프론트가 매핑한다.
- **`direction` 이 null 인 과거 통화는 필터를 걸면 양쪽 어디에도 안 잡힌다.** 전체 조회에서만 보인다.

---

## 변경 파일

| 파일 | 내용 |
|---|---|
| `src/advisor/keyword-detect/services/keyword-detect-log.service.ts` | `loadCallstatsIds()` 신설, `attachDisplayInfo()` 에서 `callstats_id` 채움 |
| `src/advisor/keyword-detect/dto/query-keyword-detect-log.dto.ts` | `callstats_id` 응답 필드 |
| `src/advisor/agent/dto/query-admin-assignable-agents.dto.ts` | `agent_id`, `role` 쿼리 필드 |
| `src/advisor/agent/services/agent.service.ts` | 즐겨찾기 `user_key` 를 `agent_id` 로, `getCurrentUser()` 호출 제거, `matchesRoleFilter()` 추가 |
| `src/advisor/call/dto/call-stats-query.dto.ts` | `agent_id` 선택화, `sort_order`·`direction`·조직 3종 필터 |
| `src/advisor/call/services/call-stats.service.ts` | `resolveOrgAgentIds()`·`loadAgentDisplays()`·`loadDetectSummaries()` 신설, 정렬/필터 조건부화 |
| `src/advisor/call/controllers/call-stats.controller.ts` | 응답 스키마에 `agent_name`·`detect_count`·`detects` 반영, `meta.agent_id` nullable |
| `src/advisor/keyword-detect/services/keyword-detect-log.service.ts` | `resolveCallIdCandidates()` 신설(`callstats_id` 필터) |
| `docker-compose.dev.portal.yml`, `docker-compose.monitor.yml` | `dev.dozzle.group` 라벨 |
| `docs/keyword-detect-logs-api.md` | `callstats_id` 응답 예시·주의사항 |

**검증**: `tsc --noEmit` 통과 / `eslint` 무경고 / `jest src/advisor` 70건 통과.
`assist-stream` 2건 실패는 **이번 변경 이전부터 있던 것**으로, stash 후 재실행해 무관함을 확인했다.
(agent·call 모듈은 테스트 파일 없음) / 감지어·assignable 건은 배포 후 실동작 확인 완료

## 남은 일

- 통화 이력 org-wide 노출에 **권한 통제 없음** — `userRole` 을 채우는 인증 미들웨어부터 필요(별건)
- **cc_cti_id 중복·공백 계정** 정리 — user-service 계정 데이터 문제. 정리 전까지 일부 통화의 `agent_name` 은 null
- 프론트 요청서 3장의 미적재 필드(`통화 결과` 등)는 이번 범위 밖
- Dozzle: **asst-web 라벨 미적용** (다른 저장소)

# 다기기 동기화 녹음(그룹녹음) — Mobile ↔ master-api 인터페이스

> 최대 5명이 각자 기기로 동시에 녹음 → 서버가 하나로 병합 → STT/요약 1회 →
> 참여자 전원에게 회의록 1개씩(유저당 1개) 복사해 제공하는 파이프라인의 **모바일 ↔ master-api** 계약.
>
> 대상: timblo-mobile 개발자. 병합 엔진(recog) 계약은 별도 문서(`MERGE_API_SPEC`) 참조.
> 상태: 기능은 구현 완료(도먼트). `RECOG_API_URL` 주입 + 모바일 연동 시 활성화.

---

## 0. 용어 · 전제

| 항목 | 내용 |
|---|---|
| 방장(host) | 방을 생성한 사용자. 녹음 시작/종료/마감, 템플릿·제목 선택 권한 보유. |
| 참가자(participant) | 방장 포함 최대 **5명**. |
| roomId | 방 UUID. **Redis에만** 존재(DB 영속 X), TTL 6시간. |
| code | 4자리 참가 코드(혼동문자 0/O·1/I 제외 대문자+숫자). |
| 회의록 | 병합본 기준으로 참여자별 **각 1개** 생성(소유자별 복사, 공유 아님). |

- **인증**: 기존 모바일과 동일한 timblo 토큰 헤더(`Authorization: Bearer <token>`)를 그대로 사용. 방 API·업로드 모두 인증 필수.
- **베이스 URL / 게이트웨이**: 기존 녹음 업로드가 쓰는 host/prefix 규칙을 그대로 따른다(아래 경로는 master-api 내부 라우트 기준).
- **응답 봉투**: 모든 응답은 `{ "message": string, "httpCode": number, "data": object }`. 이하 예시는 `data`만 표기.

---

## 1. 전체 플로우

```
1. 방장  POST /rooms                     → { roomId, code }
2. 참가자 POST /rooms/:code/join          → { roomId, code, memberCount }   (각 기기)
3. 방장  POST /rooms/:roomId/start        → 전원 SSE RECORDING_START → 각 기기 beep + 녹음 시작
4. 방장  POST /rooms/:roomId/stop         → 전원 SSE RECORDING_STOP  → 녹음 종료, 업로드 단계
5. 각자  POST /contents/upload/encryption/files (roomId + 방장은 templateId·title)
                                          → 도착할 때마다 전원 SSE UPLOAD_STATUS
6. (수집완료/방장 finish/타이머) 서버 병합 → STT/요약 1회 → 회의록 N개 복사
7. 전원  SSE MERGE_DONE | MERGE_FAILED    → 회의록 준비완료 / 실패·부분누락 안내
```

시퀀스:

```mermaid
sequenceDiagram
  autonumber
  actor H as 방장·참가자 (Mobile)
  participant M as master-api
  participant N as notification-api (SSE)
  H->>M: POST /rooms (방장)
  H->>M: POST /rooms/:code/join (참가자, 각 기기)
  H->>M: POST /rooms/:roomId/start (방장)
  M->>N: RECORDING_START (참가자별)
  N-->>H: SSE RECORDING_START
  Note over H: 각 기기 beep 재생 + 녹음
  H->>M: POST /rooms/:roomId/stop (방장)
  M->>N: RECORDING_STOP
  N-->>H: SSE RECORDING_STOP
  H->>M: 암호화 업로드 (roomId; 방장은 +templateId +title)
  M->>N: UPLOAD_STATUS (업로드마다)
  N-->>H: SSE UPLOAD_STATUS
  Note over M: 수집완료/finish/타이머 → 병합 → STT/요약 1회 → 회의록 N개
  M->>N: MERGE_DONE | MERGE_FAILED
  N-->>H: SSE 결과 안내
```

---

## 2. 방 라이프사이클 API

### 2.1 방 생성 — `POST /rooms` (방장)

방장이 된다. **템플릿·제목은 여기서 선택하지 않는다**(녹음 종료 후 방장 업로드에 실어 전달).

- Request body(선택):
```json
{ "beepSource": "leader" }   // 동기 beep 재생 주체. "leader"(기본) | "all". §5 참고
```
- Response `data`:
```json
{ "roomId": "uuid", "code": "AB23" }
```
- `beepSource`는 방 단위로 저장돼 병합 시 recog로 전달된다. **모바일의 실제 beep 재생 방식과 반드시 일치**시켜야 정렬 패드가 맞는다. 허용값 외 → `1000`.

### 2.2 방 참가 — `POST /rooms/:code/join` (참가자, 각 기기)

`:code`는 4자리 코드 또는 roomId. 정원 5명(방장 포함) 초과 시 거부. 같은 사용자의 재참가는 멱등(정원 소모 없음), 다기기는 `deviceId`만 누적.

**참가 가능 시점**: 신규 참가는 **녹음 시작 전(status=`active`)에만** 가능. 방장이 `start`로 녹음을 시작한 뒤에는 신규 참가 거부(`1000 "recording already started, cannot join"`). 단, **이미 참가한 멤버의 재접속·다기기 추가는 녹음 중에도 허용**(멱등).

- Request body:
```json
{ "deviceId": "기기 식별자 (선택, 다기기 대응)" }
```
- Response `data`:
```json
{ "roomId": "uuid", "code": "AB23", "memberCount": 3 }
```
- 에러: 정원 초과 `1000 "room is full"`, 없는 방 `1000 "room not found"`, 녹음 시작 후 신규참가 `1000 "recording already started, cannot join"`.

### 2.3 녹음 시작 — `POST /rooms/:roomId/start` (방장만)

전원에게 `RECORDING_START` SSE 발행. 각 기기는 **수신 즉시** beep 재생 + 녹음 시작(server-authoritative, 별도 예약시각 없음).

- Response `data`: `{ "roomId": "uuid", "status": "recording" }`
- 에러: 방장 아님 `1003 "only host can control the room"`.

### 2.4 녹음 종료 — `POST /rooms/:roomId/stop` (방장만)

전원에게 `RECORDING_STOP` SSE. 상태가 `collecting`으로 전환되고 **수집 마감 타이머(stall/cap)** 가 무장된다. 이후 각 기기는 파일 업로드.

- Response `data`: `{ "roomId": "uuid", "status": "collecting" }`

### 2.5 수집 마감(수동) — `POST /rooms/:roomId/finish` (방장만)

도착한 업로드분으로 **즉시 병합 트리거**. (전원 업로드 완료 시 자동, 미완 시 타이머로도 트리거되므로 선택적.)

- Response `data`: `{ "roomId": "uuid", "status": "merge-queued" }`

### 2.6 방 상태 조회 — `GET /rooms/:roomId` (방장 UI / 폴백 / 시작신호 캐치업)

방장 화면의 "N/전체 업로드" 체크리스트, SSE 유실 시 폴백 조회용. **`start` SSE를 놓친 기기의 캐치업**에도 사용한다.

- Response `data`:
```json
{
  "roomId": "uuid",
  "code": "AB23",
  "status": "recording",
  "hostMemberId": "m1",
  "templateId": "DEF-BASIC",
  "title": "9월 정기 회의",
  "beepSource": "leader",
  "recording": true,
  "startedAt": 1727680000000,
  "elapsedMs": 3200,
  "serverTime": 1727680003200,
  "participants": [
    { "memberId": "m1", "nickName": "홍길동", "uploadStatus": "waiting", "deviceIds": ["d1"] },
    { "memberId": "m2", "nickName": "김철수", "uploadStatus": "waiting", "deviceIds": ["d2"] }
  ]
}
```
- `status` 전이: `active → recording → collecting → merging → transcribing → done | failed`
- `uploadStatus` ∈ `waiting | done | failed` — **진행률(%)은 제공하지 않는다**(서버는 완료/대기만 앎). UI는 참가자별 ✅/⏳ 체크리스트로 표현.
- `nickName`은 `UserProfile.nickName`(참가/생성 시점 스냅샷). 표시명으로 사용.

**캐치업 필드(시작신호 유실 대비)**
| 필드 | 의미 |
|---|---|
| `recording` | `true`면 아직 녹음 중 → 아직 녹음 안 시작한 기기는 **즉시 녹음 시작**(캐치업) |
| `startedAt` | 녹음 시작 시각(ms, 숫자). 미시작이면 `null` |
| `elapsedMs` | 녹음 시작 후 경과(ms). **beep 캡처 가능 여부 판단** 참고(경과가 beep 재생창을 넘겼으면 정렬 폴백될 수 있음) |
| `serverTime` | 서버 기준 현재시각(ms). 기기 시계 보정용 |

> **권장 사용**: 소켓 재접속/포그라운드 복귀 시 `GET /rooms/:roomId` 호출 → `recording === true`이고 본인이 아직 녹음 안 시작했으면 즉시 녹음 시작. `elapsedMs`가 beep 재생창 이후면 해당 기기는 beep 정렬이 안 될 수 있음을 감안(그래도 녹음·업로드하면 timestamp/none 폴백 또는 부분 제외).

---

## 3. 녹음 파일 업로드 (기존 암호화 업로드 재사용 + `roomId`)

**기존 모바일 암호화 업로드를 그대로** 사용하되 `roomId`를 추가하면 그룹녹음 경로로 처리된다. `roomId`가 없으면 기존 단일 업로드 동작(개별 회의록/STT 생성).

- 다파일: `POST /contents/upload/encryption/files`
- 단일(청크): `POST /contents/upload/encryption`

### multipart/form-data 필드

| 필드 | 필수 | 설명 |
|---|---|---|
| `files` (또는 `file`) | ✅ | 암호화된 청크 파일(기존과 동일) |
| `deviceId` | ✅ | 기기 식별자(기존과 동일) |
| `fileName` | ✅ | 폴더/파일명(기존과 동일) |
| `totalNum` | ✅ | 청크 총 개수(기존과 동일). 단일 청크 API는 `num`도 사용 |
| `roomId` | 그룹녹음 ✅ | **신규** — 방 API로 받은 roomId. 있으면 그룹녹음 수집 경로 |
| `attendeeNum`, `lang` | 선택 | 기존과 동일 |
| `templateId` | 선택 | **방장 업로드만** 방 템플릿으로 채택(참가자 값 무시). 미지정 시 병합 때 `DEF-BASIC` |
| `title` | 선택 | 회의록 제목. **단일 업로드**는 그대로 `editedTitle`로 저장. **그룹녹음**은 **방장 업로드만** 방 제목으로 채택 → 회의록 전원 동일 적용. 미입력 시 기존 자동 제목 규칙 |
| `startedAt` | 선택/향후 | 녹음 시작시각(ISO8601, ms). 현재 병합은 beep 우선이라 미사용. timestamp 정렬 폴백 도입 대비 **가능하면 지금부터 전송 권장** |

### 응답

- 그룹녹음(최종 청크까지 완료): `data = { "room": true, "roomId": "uuid", "fileKey": "..." }`
- 청크 진행 중: `{}` 또는 `{ "missingFiles": [...] }` (기존과 동일)
- 병합/회의록 생성은 수집 완료 후 서버가 **비동기** 진행 → 결과는 SSE로 통지.

> **방장 UX 권장**: `stop` 직후 화면에서 **템플릿 + 제목**을 입력받아 방장의 업로드 요청에 함께 실어 보낸다. 방장이 업로드하지 않으면 템플릿은 `DEF-BASIC`, 제목은 자동 규칙으로 떨어진다.

---

## 4. SSE 이벤트 (기존 `/events` 스트림)

기존 알림 SSE(`eventflux`, `/events`)를 그대로 구독하면 아래 `action`이 도착한다.
봉투: `{ type, channel: "event", action, majorType, data, time }`. 앱은 **`action`으로 분기**한다.

| action | data | 앱 처리 |
|---|---|---|
| `RECORDING_START` | `{ roomId, recording: true }` | beep 재생 + 녹음 시작 |
| `RECORDING_STOP` | `{ roomId, recording: false }` | 녹음 종료 → 업로드 시작 |
| `UPLOAD_STATUS` | `{ roomId, participants: [{ memberId, nickName, uploadStatus }] }` | 방장 체크리스트 갱신(done/waiting) |
| `MERGE_DONE` | `{ roomId, status: "DONE", excludedMemberIds: [] }` | 회의록 준비완료. **참석자 전원에게 회의록 생성**(업로드 실패자 포함). `excludedMemberIds`는 **본인 음성이 병합에 미포함**된 참가자(회의록은 받음, 안내용) |
| `MERGE_FAILED` | `{ roomId, status: "FAILED" }` | 실패 안내 |

- SSE는 유실 가능하므로 회의록 목록/`GET /rooms/:roomId`로 **폴백 조회** 가능하게 구현 권장.

---

## 5. 동기 신호(beep)

- 시작 방식은 **신호 즉시 시작**(절대 예약시각 없음). 방장 `start` → SSE 수신 즉시 각 기기가 녹음 + beep 재생.
- **beep 자체는 모바일이 생성/재생**(정렬용 마커). 서버·recog는 beep를 감지해 트랙을 정렬한다.
- beep 상수(주파수/길이/반복)는 recog와 **공유 상수**로 일치시켜야 함 → recog 담당과 합의(별도 문서/공유 asset).
- pause/resume 허용(모바일 기존 무음 패딩 로직 유지). 회의록은 유저당 1개.

### beep 재생 주체 — `beepSource` (leader | all)
recog `/v1/merge`가 두 모드를 지원하며, master-api는 **방 생성 시 받은 `beepSource`를 병합에 그대로 전달**한다(미지정 시 `leader`).

| 모드 | 의미 | 모바일 동작 |
|---|---|---|
| `leader` (기본) | **방장만** beep 재생 | 방장 기기만 beep 재생. 다른 기기는 방 안에 울린 beep가 마이크에 잡혀 정렬됨 |
| `all` | **전원** beep 재생 | 모든 기기가 start 신호 수신 즉시 각자 beep 재생(수십 ms 내 동시) |

- 정렬 검출·offset 계산은 두 모드 동일. 차이는 **beep 블록 폭(trim/mute 패드)** 뿐이라, **모바일 재생 방식과 `beepSource` 값이 어긋나면 정렬 절단/뮤트 구간이 틀어질 수 있다** → 반드시 일치시킬 것.
- 아직 모드 미정 시: 방 생성에서 `beepSource` 생략(=leader)하고, 전원 beep로 정하면 `beepSource:"all"`로 방 생성.

---

## 6. 동작 규칙 · 합의사항

| 항목 | 규칙 |
|---|---|
| 수신 대상 | 모든 SSE는 **참여자 전원**에게 발행 |
| 다기기 | 허용(같은 유저 여러 기기). 단 **회의록은 유저당 1개** |
| 템플릿 | **방장 업로드**의 `templateId`만 방 단위 1개로 채택 → 회의록 전원 동일. 미지정 `DEF-BASIC` |
| 제목 | **방장 업로드**의 `title`만 방 제목으로 채택 → 회의록 전원 동일 `editedTitle`. 미입력 시 기존 자동 제목 규칙 |
| 수집 마감(grace) | ① 전원 업로드 완료 즉시 ② 방장 수동 `finish` ③ stall 90s / cap 600s 타이머 중 먼저 도달하는 시점 |
| 회의록 대상 | **방 참석자 전원**에게 회의록 생성(업로드 실패자 포함). 업로드 실패자는 병합 오디오에 본인 음성만 빠짐 |
| 지각/실패 업로드 | 마감 후 도착분은 **재병합 없음**. 해당 유저는 `excludedMemberIds`로 안내되나 **회의록 자체는 받음**(음성만 미포함) |
| 업로드 진행률 | **미제공**(done/waiting 이진). 진행률 바 대신 완료 체크로 표현 |
| 원본 파일 | 병합 전 개별 원본은 기존 워크스페이스 **보존정책에 위임** |

---

## 7. 에러 코드(주요)

| code | 의미 | 상황 |
|---|---|---|
| `1000` | Bad Request | 필수 파라미터 누락, 방 없음(`room not found`), 정원 초과(`room is full`), 녹음 시작 후 신규참가(`recording already started, cannot join`), `templateId is required` 등 |
| `1003` | Forbidden | 비회원, 방장 전용 동작을 참가자가 호출(`only host can control the room`) |

---

## 8. 담당 경계 · 미결

- **Mobile**: 방 UI(생성/참가/시작·종료), beep 생성/재생, 업로드에 `roomId`(+방장은 `templateId`·`title`), SSE `action` 분기, 체크리스트/폴백 조회.
- **master-api**: 방 상태(Redis), SSE 발행, 업로드 수집, recog `/v1/merge` 오케스트레이션, STT/요약 1회 + 회의록 N벌 복사.
- **recog**: `/v1/merge` 배포, beep 감지·정렬·amix, 병합본 PUT. (별도 문서)
- 활성화 전제: `RECOG_API_URL` 주입, recog 배포, beep 공유 상수 합의.
```

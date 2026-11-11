# 음성 병합 API 스펙 (`/v1/merge`)

작성일: 2026-09-14
갱신일: 2026-09-19 (설계 확정 반영 — 3절 변경 이력 참조)
대상 서버: recog (오디오 병합 서버)
호출 주체: master-api (백엔드)

---

## 1. 개요

master-api가 오브젝트 스토리지에 올려둔 참가자별 녹음 파일 여러 개를
recog 서버가 내려받아 **하나의 음성 파일로 겹쳐 합친 뒤 다시 업로드**하고,
master-api가 폴링으로 결과를 가져가는 API.

```
[master-api]
   │  ① POST /v1/merge  { roomNo, files[], output, options }
   ▼
[recog]  ② 202 즉시 응답 { jobId, status:"WAITING" }
   │
   │  ── 백그라운드 ──────────────────────
   │  ③ presigned GET URL로 파일 N개 다운로드
   │  ④ 16kHz mono 정규화
   │  ⑤ 겹쳐서 믹스다운 → flac 1개
   │  ⑥ presigned PUT URL로 업로드
   │  ──────────────────────────────────
   │
   ▲  ⑦ GET /v1/merge/{jobId}  ← master-api가 주기적으로 조회
[master-api]     status: WAITING → RUNNING → DONE
```

**recog가 하는 일**: 다운로드 → 정규화 → 겹치기 → 업로드
**recog가 하지 않는 일**: STT 전사, 화자분리, 요약, DB 기록

### 1.1 "겹치기"의 의미

참가자 5명이 1시간 회의했으면 **결과물도 1시간**이다.

모든 트랙을 같은 타임라인에 올려놓고 합산한다(ffmpeg `amix`).
순차 연결(concatenation)이 아니다. master-api가 기존에 하는
"한 기기의 조각을 시간순으로 이어붙이기"와는 축이 다르다.

```
겹치기 (이 API):        이어붙이기 (master-api 기존 방식):
p1 ──────────           p1 ──────────
p2 ──────────                       p2 ──────────
p3 ──────────                                   p3 ──────────
   = 1시간                             = 3시간
```

---

## 2. 전제 조건

### 2.1 인증 — 없음

recog와 master-api는 **같은 도커 네트워크 안**에서 통신한다.
네트워크 경계가 인증을 대신하므로 API 토큰을 두지 않는다.

> 외부에서 접근 가능한 경로가 생기면 그때 토큰을 도입한다. 현재 범위 밖.

### 2.2 네트워크

recog 컨테이너는 MinIO·master-api와 **같은 도커 네트워크**에 속해야 한다.

```yaml
# deploy/docker-compose.yml
services:
  recog-backend:
    networks:
      - timblo-net-package
networks:
  timblo-net-package:
    external: true
```

presigned URL의 호스트는 내부 DNS 이름(`timblo-minio:9000` 등)으로 발급된다.
recog가 같은 네트워크에 없으면 이름 해석에 실패한다.

> 네트워크명·컨테이너명이 배포 환경과 다르면 compose 파일에서 조정한다.

### 2.3 스토리지 접근

recog는 스토리지 자격증명을 **보유하지 않는다.**
접근은 전부 master-api가 발급한 **presigned URL**로만 이루어진다.

스토리지 실체는 온프렘 MinIO다(`@timbel-timblo-onpremise/minio-js`, 순정 `minio/minio` 서버).
S3 호환 API(SigV4)를 제공하므로 recog 입장에서는 표준 S3와 동일하게 다룬다.
나중에 실제 AWS S3로 전환해도 recog 코드는 영향받지 않는다.

### 2.4 파일 암호화 — 없음

**스토리지에 저장된 녹음 파일은 암호화되어 있지 않다.**

master-api의 AES-256-CBC 암호화는 *모바일 앱 → master-api 전송 구간*에만 적용된다.
`decryptFilesAesCbc()` → `convertPcmToFlac()` → `putObject()` 순서라 저장 시점엔 평문이다.
서버사이드 암호화(SSE) 헤더도 사용하지 않는다.

**→ recog는 AES 키 없이 받아서 바로 ffmpeg에 넣는다.**

---

## 3. 변경 이력

2026-09-19 설계 확정. 이전 버전과 달라진 점:

| 항목 | 이전 | 변경 후 | 사유 |
|---|---|---|---|
| 상태 전달 | 콜백 주 + 폴링 보조 | **폴링 단일** | master-api가 HAIV 연동에서 이미 쓰는 패턴. 양쪽 구현 최소 |
| 콜백 | `callbackUrl` 필수급 | **제거** | 지금 안 쓸 코드를 미리 만들지 않음. 필요 시 추가 |
| 인증 | `Bearer` 토큰 | **제거** | 같은 도커 네트워크 내부 통신 |
| 정렬 | 상호상관 + 신뢰도 게이트 | **`none` / `timestamp` 2택** | 아래 3.1 |
| 시작시각 | 파일명 파싱 (초 단위) | **`startedAt` 필드 (밀리초)** | 아래 3.1 |
| 스토리지 | "AWS S3" | **MinIO (S3 호환)** | 소스 확인 결과 |

### 3.1 정렬 방식을 바꾼 이유

**상호상관을 폐기했다.**

`normalized_correlation()`이 순수 파이썬 이중 루프라 비용이 크다.
1시간 녹음 기준 envelope 프레임 180,000개 × lag 탐색 3,001회 × 3패스
≈ **16억 연산**. 참가자 쌍마다 반복하면 작업 타임아웃(30분)을 정렬 단계에서만 넘길 수 있다.

효과도 제한적이다. 참가자들이 각자 다른 장소에 있으면 녹음 사이에 공통 신호가 없어
신뢰도 게이트에 걸려 어차피 `offset = 0`으로 폴백한다. 즉 대부분의 경우
**비싼 연산을 돌린 끝에 정렬을 안 한 것과 같은 결과**가 나온다.

**파일명 파싱도 폐기했다.**

파일명 형식이 `A.Biz_[wm]_rec_YYYYMMDD_HHmmss`로 **초 단위**다. 밀리초가 없다.
그런데 녹음은 방장이 시작을 누르면 참가자 전원에게 전파되는 구조라,
실제 시작 차이는 네트워크 지연 수준인 **수백 ms**다. 정밀도가 오차보다 거칠다.

초 경계를 사이에 두고 갈라지면 결과가 나빠진다:

| 실제 시작 | 파일명 값 | 계산 offset | 실제 차이 | 결과 |
|---|---|---|---|---|
| A `10:00:00.900`, B `10:00:01.100` | `100000`, `100001` | 1000ms | 200ms | **800ms 더 어긋남** |
| A `10:00:00.100`, B `10:00:00.900` | `100000`, `100000` | 0ms | 800ms | 보정 없음 |

**→ 요청 본문의 `startedAt`(ISO8601, 밀리초 포함)을 받는다.**
파일명 규칙은 master-api 내부 사정이므로 recog가 파싱하지 않는다.

---

## 4. 병합 요청

### `POST /v1/merge`

#### Request Body

```json
{
  "roomNo": "R-20260919-001",
  "files": [
    {
      "participantId": "p1",
      "startedAt": "2026-09-19T14:30:52.104Z",
      "getUrl": "http://timblo-minio:9000/default.timblo.io/<kms>/<fileKey>?X-Amz-Algorithm=...",
      "fileName": "A.Biz_m_rec_20260919_143052.flac"
    },
    {
      "participantId": "p2",
      "startedAt": "2026-09-19T14:30:52.371Z",
      "getUrl": "http://timblo-minio:9000/default.timblo.io/<kms>/<fileKey>?X-Amz-Algorithm=...",
      "fileName": "A.Biz_m_rec_20260919_143052.flac"
    }
  ],
  "output": {
    "putUrl": "http://timblo-minio:9000/default.timblo.io/<kms>/<fileKey>?X-Amz-Algorithm=...",
    "originalname": "R-20260919-001_merged.flac",
    "format": "flac"
  },
  "options": {
    "align": "none"
  }
}
```

#### 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `roomNo` | string | ✅ | 회의룸 번호. 로그·추적용 식별자 |
| `files` | array | ✅ | 병합 대상. 최소 1개, 최대 5개 |
| `files[].participantId` | string | ✅ | 참가자 식별자. 고유값. 결과 리포트의 키 |
| `files[].getUrl` | string | ✅ | 다운로드용 presigned GET URL |
| `files[].startedAt` | string | 조건부 | 녹음 시작 시각(ISO8601, 밀리초). `align: "timestamp"`일 때 **필수** |
| `files[].fileName` | string | — | 원본 파일명. 로그 가독성 용도 |
| `output.putUrl` | string | ✅ | 업로드용 presigned PUT URL |
| `output.originalname` | string | ✅ | 결과 파일명. 아래 4.1 참조 |
| `output.format` | string | — | `flac`(기본) / `wav` |
| `options.align` | string | — | `none`(기본) / `timestamp`. 아래 4.2 참조 |

### 4.1 `originalname` — 요청측 필수 준수 사항

master-api는 다운로드 시 파일명을 **오브젝트 메타데이터**에서 읽는다
(`utils/file/stream.util.js` → `metaData['originalname']` → `Content-Disposition`).
이 메타데이터가 없으면 사용자가 병합본을 받을 때 파일명이 깨진다.

presigned PUT은 서명이 헤더를 고정하므로, 아래 두 가지가 **모두** 지켜져야 한다:

1. master-api는 `putUrl` 발급 시 **`x-amz-meta-originalname`을 서명에 포함**한다
2. 바디의 `output.originalname`에 **서명에 넣은 값과 완전히 동일한 문자열**을 담는다

recog는 받은 값을 그대로 `x-amz-meta-originalname` 헤더에 실어 PUT한다.
한 글자라도 다르면 서명 불일치로 `403`이 난다.

**값은 퍼센트 인코딩된 ASCII여야 한다.** HTTP 헤더는 latin-1만 담을 수 있고,
recog는 서명 일치를 위해 값을 가공하지 않으므로 한글이 그대로 오면 헤더에 넣을 수 없다.
master-api는 이미 `encodeURIComponent(originalname)`으로 저장하고 있으므로
(`utils/drive.util.js` `createPutParams`) 그 값을 그대로 주면 된다.
non-ASCII가 오면 접수 단계에서 `E4007`로 거부한다.

### 4.2 `options.align`

| 값 | 동작 | 요구 필드 | 비용 |
|---|---|---|---|
| `"none"` (기본) | 모든 트랙을 0초 지점에서 겹친다 | — | 없음 |
| `"timestamp"` | 가장 이른 `startedAt`을 기준으로, 차이만큼 각 트랙 앞에 무음을 넣는다 | `files[].startedAt` | 뺄셈 N회 |

**기본값이 `"none"`인 이유**: 방장이 녹음 시작을 누르면 참가자 전원에게 전파되는
구조라 거의 동시에 시작된다. 또한 `startedAt`이 없거나 부정확할 때 안전한 쪽으로 떨어진다.

**이상값 가드**: `timestamp` 모드에서 계산된 offset이 `MERGE_MAX_OFFSET_MS`(기본 60000)를
넘으면 해당 트랙만 `offsetMs: 0`으로 폴백하고 응답에 표시한다.
시계가 틀어진 기기 하나가 전체 결과를 망치는 것을 막는다.

#### Response — `202 Accepted`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260919-001",
  "status": "WAITING",
  "fileCount": 5,
  "acceptedAt": "2026-09-19T14:35:00.000Z",
  "retryAfterMs": 5000
}
```

요청은 큐에 적재되고 **즉시 반환**된다. 실제 병합은 백그라운드에서 진행된다.

---

## 5. 상태 조회 (폴링)

### `GET /v1/merge/{jobId}`

master-api가 이 엔드포인트를 주기적으로 호출해 진행 상황을 확인한다.

#### 진행 중 — `200 OK`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260919-001",
  "status": "RUNNING",
  "stage": "MIXING",
  "progress": 45,
  "retryAfterMs": 5000,
  "acceptedAt": "2026-09-19T14:35:00.000Z",
  "startedAt": "2026-09-19T14:35:02.100Z",
  "finishedAt": null
}
```

#### 완료 — `200 OK`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260919-001",
  "status": "DONE",
  "stage": null,
  "progress": 100,
  "output": {
    "format": "flac",
    "sampleRate": 16000,
    "channels": 1,
    "durationMs": 3612480,
    "sizeBytes": 28431052,
    "originalname": "R-20260919-001_merged.flac"
  },
  "alignment": {
    "mode": "timestamp",
    "reference": "p1",
    "tracks": [
      { "participantId": "p1", "offsetMs": 0,   "fallback": false },
      { "participantId": "p2", "offsetMs": 267, "fallback": false },
      { "participantId": "p3", "offsetMs": 0,   "fallback": true  }
    ]
  },
  "timing": {
    "downloadMs": 18200,
    "processMs": 92300,
    "uploadMs": 9100,
    "totalMs": 119600
  },
  "acceptedAt": "2026-09-19T14:35:00.000Z",
  "startedAt": "2026-09-19T14:35:02.100Z",
  "finishedAt": "2026-09-19T14:37:01.700Z"
}
```

`align: "none"`이면 `alignment`는 `{ "mode": "none" }`만 반환한다.
`fallback: true`는 이상값 가드에 걸려 0으로 되돌린 트랙이다.

#### 실패 — `200 OK`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260919-001",
  "status": "ERROR",
  "error": {
    "code": "E4102",
    "message": "presigned URL expired for participantId=p3",
    "participantId": "p3"
  },
  "finishedAt": "2026-09-19T14:36:12.000Z"
}
```

> 작업 실패도 **조회 자체는 성공**이므로 HTTP `200`이다.
> `status` 필드로 판별한다. `404`는 jobId 자체가 없을 때만 반환한다.

#### `status` 값

| 값 | 의미 |
|---|---|
| `WAITING` | 큐 대기 중 |
| `RUNNING` | 처리 중 (`stage`로 세부 단계 확인) |
| `DONE` | 완료. 업로드까지 끝남 |
| `ERROR` | 실패. `error` 필드에 사유 |

#### `stage` 값

`DOWNLOADING` → `NORMALIZING` → `MIXING` → `UPLOADING`

### 5.1 `retryAfterMs`

다음 조회까지 기다릴 시간을 recog가 제안한다. master-api는 이 값을 따르면
주기를 하드코딩할 필요가 없고, recog는 단계별로 조절할 수 있다.

| 상황 | 값 |
|---|---|
| `WAITING` (큐 대기) | 10000 |
| `RUNNING` / `DOWNLOADING`·`NORMALIZING`·`MIXING` | 5000 |
| `RUNNING` / `UPLOADING` | 2000 |
| `DONE` / `ERROR` | 미포함 (폴링 종료) |

### 5.2 결과 보존 기간

완료된 작업의 상태는 `MERGE_JOB_TTL_SEC`(기본 86400, 24시간) 동안 조회 가능하다.
이후 `404`. 폴링을 놓쳐도 하루 안에는 결과를 가져갈 수 있다.

---

## 6. 처리 동작 상세

### 6.1 다운로드

`files[].getUrl`로 병렬 다운로드한다. 하나라도 실패하면 작업 전체를 실패 처리한다
(일부만 빠진 채 병합하면 대화가 누락되기 때문).

`urllib.request`만 사용한다. presigned URL이므로 서명 계산이 불필요하다.

### 6.2 정규화

모든 입력을 **16kHz / mono / 16bit**로 통일한다.
master-api가 생성하는 flac이 이미 이 규격이므로(`utils/file/audio.util.js`
→ `-f s16le -ar 16000 -ac 1`) 대부분 변환 비용이 없다.
입력별로 샘플레이트나 채널 수가 달라도 이 단계에서 흡수된다.

### 6.3 겹치기

`align` 값에 따라 ffmpeg 필터그래프를 구성한다.

**`align: "none"`**

```
amix=inputs=N:dropout_transition=0:normalize=0,alimiter=limit=0.95
```

**`align: "timestamp"`** — 각 입력 앞에 `adelay`로 무음을 삽입한 뒤 합산

```
[0:a]adelay=0|0[a0];
[1:a]adelay=267|267[a1];
[2:a]adelay=812|812[a2];
[a0][a1][a2]amix=inputs=3:dropout_transition=0:normalize=0,alimiter=limit=0.95
```

- 결과 길이 = 가장 긴 트랙 기준
- `normalize=0`으로 자동 감쇠를 끄고, `alimiter`로 클리핑을 방지한다

### 6.4 업로드

`output.putUrl`로 `PUT` 한다. `x-amz-meta-originalname` 헤더를 반드시 포함한다(4.1 참조).
업로드 성공 확인 후 로컬 임시 파일을 즉시 삭제한다.

### 6.5 정리

작업 디렉터리는 완료·실패 여부와 무관하게 삭제한다.
고아 파일 대비로 호스트 cleanup 스크립트(커밋 `7b8a367`)가
24시간 이상 된 잔여물을 주기적으로 제거한다.

---

## 7. 에러 코드

| 코드 | HTTP | 의미 | 조치 |
|---|:---:|---|---|
| `E4001` | 400 | 필수 필드 누락 | 요청 본문 확인 |
| `E4002` | 400 | `files`가 비어 있음 | 최소 1개 필요 |
| `E4003` | 400 | `files` 개수 초과 | 최대 5개 |
| `E4004` | 400 | `participantId` 중복 | 고유값으로 전달 |
| `E4005` | 400 | `align: "timestamp"`인데 `startedAt` 누락 | 전 파일에 포함 |
| `E4006` | 400 | `startedAt` 형식 오류 | ISO8601 (밀리초 포함) |
| `E4007` | 400 | `originalname`에 non-ASCII 포함 | `encodeURIComponent`로 퍼센트 인코딩 |
| `E4040` | 404 | `jobId` 없음 (또는 TTL 만료) | 조회 대상 확인 |
| `E4090` | 409 | 동일 `roomNo` 작업이 이미 진행 중 | 완료 후 재요청 |
| `E4101` | — | 다운로드 실패 | URL·권한 확인 |
| `E4102` | — | presigned URL 만료 | 유효기간 늘려 재요청 |
| `E4103` | — | 오디오 디코딩 실패 (손상 파일) | 원본 확인 |
| `E4104` | — | 병합 실패 (ffmpeg 오류) | 로그 확인 |
| `E4105` | — | 업로드 실패 | `putUrl`·서명 헤더 확인 |
| `E4106` | — | 작업 타임아웃 (30분 초과) | 파일 크기·서버 부하 확인 |
| `E5000` | 500 | 내부 오류 | 로그 확인 |

`E41xx`대는 큐 처리 중 발생하므로 HTTP 응답이 아니라
**상태 조회 응답의 `error.code`**로 전달된다.

---

## 8. 제약 사항

| 항목 | 값 | 환경변수 |
|---|---|---|
| 파일 개수 | 1 ~ 5개 | `MERGE_MAX_FILES` |
| 파일당 최대 크기 | 2GB | `MERGE_MAX_FILE_BYTES` |
| 지원 입력 포맷 | flac, wav, mp3, m4a, pcm(s16le 16kHz mono) | — |
| 출력 포맷 | flac (기본), wav | — |
| 동시 처리 | 3건 | `MERGE_WORKERS` |
| 작업 타임아웃 | 30분 | `MERGE_JOB_TIMEOUT_SEC` |
| 이상 offset 가드 | 60초 | `MERGE_MAX_OFFSET_MS` |
| 결과 보존 | 24시간 | `MERGE_JOB_TTL_SEC` |

**동시 처리 3건**이란 recog가 **같은 시각에 실제로 병합을 돌리는 개수**다.
API 요청은 그보다 많이 받아도 되며, 넘치는 요청은 큐에서 대기하다가 순서대로 처리된다.
즉 4번째 요청도 `202`로 정상 접수되고 `WAITING` 상태로 대기한다. **거절되지 않는다.**

**작업 타임아웃 30분**은 한 건이 `RUNNING`으로 들어간 뒤 30분 안에 못 끝내면
중단하고 `ERROR`(`E4106`)로 처리한다는 뜻이다. 큐 대기 시간은 포함되지 않는다.

---

## 9. master-api 연동 흐름

```
① presigned URL 발급 (GET N개 + PUT 1개)
     └ PUT은 x-amz-meta-originalname을 서명에 포함

② POST /v1/merge  → jobId 수령

③ GET /v1/merge/{jobId} 를 retryAfterMs 간격으로 반복
     └ status === 'DONE'  → ④
     └ status === 'ERROR' → 실패 처리

④ statObject로 업로드 실체 검증 (크기·존재)

⑤ 기존 STT 경로에 합류
     contentModel.createContent()   콘텐츠 레코드 생성
     recogService.addTask()         STT 큐 투입 (기존 로직 그대로)
```

기존 모바일 업로드 경로(`drive.service.js` `uploadEncryptionContent`)가
`decryptFilesAesCbc` → `convertPcmToFlac` → `put` → `recogService.addTask` 순서인 것과 같다.
**앞의 세 단계를 recog가 대신 수행한 형태이므로 마지막 단계만 이어 붙이면 된다.**

④가 필요한 이유: presigned 방식은 `put()` 직후에 묶여 있던
DB 기록 → 캐시 워밍 → STT 큐 투입 → 실패 롤백의 연결을 끊는다.
업로드 실체를 확인한 뒤 후속 처리를 이어야 한다.

---

## 10. 기존 recog API와의 관계

recog에는 이미 `/rooms`, `/sessions` 계열 엔드포인트가 있다.
클라이언트가 방을 만들고 실시간으로 참여해 녹음을 업로드하는 경로다.

`/v1/merge`는 **그 경로와 독립적으로 추가**되며, 기존 엔드포인트는 변경하지 않는다.

| | 기존 `/sessions` 경로 | 신규 `/v1/merge` |
|---|---|---|
| 입력 | 클라이언트가 multipart 업로드 | presigned GET URL |
| 출력 | 로컬 보관 + HTTP GET 제공 | presigned PUT 업로드 |
| 결과물 | 정렬 트랙 + 믹스 + 매니페스트 | 믹스 1개 |
| 정렬 | 상호상관 + drift 보정 | 없음 또는 timestamp |
| 응답 | 동기 | 비동기 (jobId + 폴링) |
| 인증 | 없음 | 없음 |

**DSP 모듈(`src/audio_sync/dsp/`)은 `/v1/merge`에서 사용하지 않는다.**
상호상관·drift 보정을 폐기했으므로 공유 지점이 없다. 기존 경로는 그대로 유지된다.

---
---

# 부록 A. 작업 메모 (내부용)

> master-api 담당자에게 공유하는 문서가 아니다. 구현 재개 시 여기부터 읽는다.
> 공유용 문서는 `newDocs/MERGE_API_GUIDE.md`.

## A.1 현재 상태 (2026-09-19 기준)

- 설계 확정 완료. **코드는 한 줄도 작성하지 않음.**
- master-api 소스 분석 완료 (`newDocs/master-api/`)
- 다음 단계: 구현 착수
- 브랜치: `skHynix_nohsn`

## A.2 소스 분석으로 확인된 사실

| 사실 | 근거 |
|---|---|
| 스토리지는 **MinIO**다 (AWS S3 아님) | `src/utils/drive.util.js` `@timbel-timblo-onpremise/minio-js`. 레포 전체에 `aws-sdk`/`@aws-sdk`/`S3Client`/`amazonaws` 0건 |
| MinIO 서버는 **순정**이다 | `newDocs/minio-main/Dockerfile` → `FROM minio/minio:latest`. S3 호환 API·presigned 완전 지원 |
| presigned URL은 **현재 사용처 0건**이다 | 전체 검색 `presigned`/`getSignedUrl`/`signedUrl` 0건. master-api가 신규 구현해야 함 |
| **저장 파일은 평문이다** | `drive.service.js`가 `decryptFilesAesCbc` → `convertPcmToFlac` → `put` 순. SSE 헤더도 없음 |
| `kms`는 암호화가 **아니다** | `generate.keyFromString(salt)` — 사용자별 격리 경로 prefix. 키는 `{bucket}/{kms}/{fileKey}` |
| `originalname` 메타데이터가 **파일명을 결정**한다 | `utils/file/stream.util.js` → `Content-Disposition` |
| 자격증명은 Consul KV 한 곳에서만 관리된다 | `minio-main/timbloInit.sh`가 `mc admin accesskey create` 후 `timblo/common/credentials`에 PUT. master-api가 watch |
| master-api의 비동기 연동은 **폴링**이다 | `src/utils/engines/Haiv/utils/get.js` `pollStatusAndResults` — `setInterval(…, 5000)` + `percentage` |
| 파일별 시작시각은 DB에 **없다** | Prisma `File` 모델에 duration만 존재. `Content.meetingStartTime`은 회의 단위이고 파일명 파싱 실패 시 `new Date()`로 폴백 |
| 발화자정보는 **STT 결과물**이다 | Prisma `SpeakerInfo`는 `TranscribeResult` 하위. 병합 시점엔 존재하지 않음 |
| 버킷·네트워크 | `default.timblo.io`(비공개) / `default.public.timblo.io`(공개), 네트워크 `timblo-net-package`, 컨테이너 `timblo-minio` |

## A.3 확정된 설계 결정과 근거

| 결정 | 근거 |
|---|---|
| presigned URL로만 접근 | recog는 pip 의존성 0개(stdlib + ffmpeg). 자격증명 직통 전달은 SigV4 구현이나 minio 클라이언트 추가를 요구. 또한 자격증명이 Consul 한 곳에서만 관리되는 현 구조를 열어야 함 |
| 비동기 (jobId + 폴링) | 5명 1시간이면 2~5분 소요. 동기 응답은 타임아웃 |
| 폴링 단일, 콜백 제거 | master-api가 HAIV에서 이미 쓰는 패턴. 내부망 5초 폴링은 부하 무의미. 안 쓸 코드를 미리 만들지 않음 |
| 소켓/SSE 미채택 | 연결 유지·재연결·프록시 타임아웃 대응이 붙는데 얻는 건 "5초 빨리 앎" |
| 인증 없음 | 같은 도커 네트워크 내부 통신 |
| 출력은 믹스 1개 | 사용자 결정. 화자분리는 master-api의 STT 엔진이 처리 |
| 정렬 `none` 기본 | 방장 트리거로 전원 거의 동시 시작. `startedAt` 부재 시 안전 폴백 |
| `startedAt` 밀리초 수령 | 파일명은 초 단위라 실제 오차(수백 ms)보다 거칢. 3.1 표 참조 |
| 16kHz 작업 포맷 | master-api가 만드는 flac이 16kHz mono. 48kHz로 올려도 정보량 증가 없이 CPU만 3배 |

### 폐기된 검토 사항 (다시 꺼내지 말 것)

- **상호상관 정렬** — 1시간 기준 16억 연산으로 타임아웃 위협. 다른 장소면 어차피 폴백. 3.1 참조
- **drift 보정** — 상호상관에 종속. 정렬이 폴백되면 자동 무력화되므로 함께 폐기
- **파일명에서 시작시각 파싱** — 초 단위 한계 + master-api 내부 규칙에 결합됨. `startedAt`으로 대체
- **콜백 (`callbackUrl`)** — 폴링으로 충분. 필요해지면 스펙 변경 없이 추가 가능
- **API 토큰** — 내부망
- **지배 트랙 선택(dominant mix)** — 공용 마이크 전제였으나 실제는 참가자별 개인 기기. 단순 `amix`로 충분
- **화자분리** — `src/recog/models.py` `speaker_diarization: False`. 계속 미지원

## A.4 구현 시 건드릴 파일

| 파일 | 작업 |
|---|---|
| `src/recog/s3_transfer.py` (신규) | presigned URL 다운로드/업로드. `urllib.request`만 사용. PUT 시 `x-amz-meta-originalname` 헤더 |
| `src/recog/merge_job.py` (신규) | 작업 큐, 상태 관리, 워커 스레드, TTL 만료 |
| `src/recog/api.py` | `POST /v1/merge`, `GET /v1/merge/{jobId}` 라우트 추가. 기존 라우팅이 `if method == ... and path == ...` 나열식이라 같은 패턴으로 추가 |
| `src/recog/audio.py` | `mix_tracks()` 재사용. `adelay` 지원을 위해 필터그래프 구성부만 확장 |
| `deploy/docker-compose.yml` | `networks: [timblo-net-package]` 추가 (external) |
| `tests/test_merge_api.py` (신규) | 기존 테스트가 unittest 기반이므로 동일하게 |

**신규 파일 3개.** `callback.py`, 정렬 모듈은 만들지 않는다.

구현 순서: `s3_transfer.py` → `merge_job.py` → `api.py` 라우트 → 테스트

## A.5 구현 시 주의점

**`originalname` 서명 일치.** presigned PUT은 서명이 헤더를 고정한다.
바디의 `output.originalname`을 **가공 없이 그대로** 헤더에 실어야 한다.
인코딩·트림·정규화를 하면 서명이 깨진다. 4.1 참조.

**동시 처리 3건 = 실제 워커 수.** 요청은 큐에 무제한 적재되고 `WAITING`으로 대기한다.
4번째 요청을 거절하면 안 된다 (8절에 명시).

**실패도 HTTP 200.** 상태 조회는 작업이 실패해도 조회 자체는 성공이다.
`404`는 jobId가 없을 때만. master-api가 `status` 필드로 판별하도록 되어 있다.

**임시 파일 정리.** 성공·실패 무관하게 작업 디렉터리 삭제.
호스트 cleanup 스크립트(커밋 `7b8a367`)가 이미 있으므로 그 경로 규칙과 맞출 것.

**도커 네트워크.** presigned URL 호스트가 내부 DNS 이름이라
recog가 `timblo-net-package`에 붙지 않으면 이름 해석에 실패한다. 2.2 참조.

**DSP 모듈 미사용.** `src/audio_sync/dsp/`는 기존 `/sessions` 경로 전용이다.
`canonicalize.py`의 `DEFAULT_WORKING_SAMPLE_RATE`(48000)를 건드릴 이유도 없어졌다.

## A.6 master-api 쪽 참고 코드 위치

공유받은 `newDocs/master-api/` 기준.

| 경로 | 내용 |
|---|---|
| `src/utils/drive.util.js` | MinIO 클라이언트 + `put`/`getObject`/`removeObject`. **스토리지 접근의 핵심** |
| `src/utils/file/stream.util.js` | `metaData['originalname']` → `Content-Disposition` |
| `src/services/system/drive.service.js` | 업로드 전체 흐름 (`uploadContent`, `uploadEncryptionContent`) |
| `src/utils/secure.util.js` | AES 복호화 — **전송 구간 전용**, 저장 시점엔 평문 |
| `src/utils/file/audio.util.js` | `convertPcmToFlac` — `-f s16le -ar 16000 -ac 1` → flac |
| `src/utils/engines/Haiv/utils/get.js` | **폴링 패턴 참고** — `setInterval(…, 5000)` + state/percentage |
| `src/services/engine/recog.service.js` | 비동기 패턴 참고 — ticketId 발급 + 큐 + notify |
| `src/configs/discovery-config.js` | Consul watch → `storageChanged` → 클라이언트 재생성 |
| `docs/s3-upload-architecture.md` | 스토리지 구조 선행 분석 문서 |
| `docs/prisma-2-release/schema/` | DB 스키마 (File / Content / TranscribeResult / SpeakerInfo) |
| `../minio-main/` | MinIO 서버 배포 설정 (Dockerfile, compose, init 스크립트) |

## A.7 요청측(master-api) 확인 사항

1. presigned URL 발급 구현 — `presignedGetObject` / `presignedPutObject`
   (SDK는 표준 minio-js 8.0.6 포크. `node_modules` 미설치로 메서드 존재 여부 직접 확인은 못 함)
2. PUT 서명에 `x-amz-meta-originalname` 포함시키는 방법
3. `startedAt`을 밀리초 정밀도로 제공 가능한지 → 불가하면 `align: "none"`만 사용
4. presigned URL 유효기간 6시간 이상
5. 제약값 검증 — 파일 5개 / 2GB / 동시 3건 / 30분이 실제 운영 규모에 맞는지

## A.8 다음 세션 시작 지점

1. A.7 항목 중 답이 온 것 반영
2. 구현 착수 — A.4 파일 목록 순서대로
3. 망분리 배포 준비 (오프라인 이미지 번들 + compose 네트워크 설정)

# 음성 병합 API 스펙 (`/v1/merge`)

작성일: 2026-09-14
대상 서버: recog (오디오 병합 서버)
호출 주체: master-api (백엔드)

---

## 1. 개요

master-api가 S3에 올려둔 참가자별 녹음 파일 여러 개를 recog 서버가 내려받아
**하나의 음성 파일로 합친 뒤 다시 S3에 업로드**하고, 결과를 콜백으로 알려주는 API.

```
[master-api]
   │  ① POST /v1/merge  { roomNo, files[], output, callbackUrl }
   ▼
[recog]  ② 202 즉시 응답 { jobId, status:"WAITING" }
   │
   │  ── 백그라운드 ──────────────────────────────
   │  ③ presigned GET URL로 파일 N개 다운로드
   │  ④ 16kHz mono 정규화
   │  ⑤ 시간축 정렬 (신뢰도 낮으면 자동 생략)
   │  ⑥ 믹스다운 → flac 1개
   │  ⑦ presigned PUT URL로 S3 업로드
   │  ────────────────────────────────────────
   ▼
[master-api]  ⑧ 콜백 수신 { jobId, status:"DONE", output, alignment[] }
```

**recog가 하는 일**: 다운로드 → 정규화 → 정렬 → 병합 → 업로드
**recog가 하지 않는 일**: STT 전사, 화자분리, 요약, DB 기록

---

## 2. 인증

recog는 AWS 자격증명을 보유하지 않는다. S3 접근은 전부 master-api가 발급한
**presigned URL**로만 이루어진다.

API 호출 자체는 공유 토큰으로 보호한다.

```
Authorization: Bearer {MERGE_API_TOKEN}
```

토큰은 양쪽 환경변수로 관리하며 값이 불일치하면 `401`을 반환한다.

---

## 3. 병합 요청

### `POST /v1/merge`

#### Request Body

```json
{
  "roomNo": "R-20260914-001",
  "files": [
    {
      "participantId": "p1",
      "getUrl": "https://bucket.s3.ap-northeast-2.amazonaws.com/rec/R-001/p1.flac?X-Amz-Algorithm=...",
      "fileName": "p1.flac"
    },
    {
      "participantId": "p2",
      "getUrl": "https://bucket.s3.ap-northeast-2.amazonaws.com/rec/R-001/p2.flac?X-Amz-Algorithm=...",
      "fileName": "p2.flac"
    }
  ],
  "output": {
    "putUrl": "https://bucket.s3.ap-northeast-2.amazonaws.com/merged/R-001/mix.flac?X-Amz-Algorithm=...",
    "format": "flac"
  },
  "options": {
    "align": true
  },
  "callbackUrl": "https://master-api.internal/v1/internal/merge-callback"
}
```

#### 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `roomNo` | string | ✅ | 회의룸 번호. 로그·추적용 식별자 |
| `files` | array | ✅ | 병합 대상 목록. 최소 1개, 최대 5개 |
| `files[].participantId` | string | ✅ | 참가자 식별자. 결과 리포트에서 어느 파일인지 구분하는 키 |
| `files[].getUrl` | string | ✅ | S3 다운로드용 presigned GET URL |
| `files[].fileName` | string | — | 원본 파일명. 로그 가독성 용도 |
| `output.putUrl` | string | ✅ | S3 업로드용 presigned PUT URL |
| `output.format` | string | — | 출력 포맷. `flac`(기본) / `wav` |
| `options.align` | boolean | — | 시간축 정렬 수행 여부. 기본 `true` |
| `callbackUrl` | string | — | 완료 통보를 받을 URL. 생략 시 폴링으로만 확인 |

> **presigned URL 유효기간은 6시간 이상**을 권장한다.
> 대용량 회의는 다운로드·병합·업로드까지 수 분이 걸리고, 큐가 밀리면 대기 시간이 더해진다.

#### Response — `202 Accepted`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260914-001",
  "status": "WAITING",
  "fileCount": 5,
  "acceptedAt": "2026-09-14T10:00:00.000Z"
}
```

요청은 큐에 적재되고 **즉시 반환**된다. 실제 병합은 백그라운드에서 진행된다.

---

## 4. 상태 조회

### `GET /v1/merge/{jobId}`

#### Response — `200 OK`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260914-001",
  "status": "RUNNING",
  "progress": 45,
  "stage": "MIXING",
  "acceptedAt": "2026-09-14T10:00:00.000Z",
  "startedAt": "2026-09-14T10:00:02.100Z",
  "finishedAt": null
}
```

#### `status` 값

| 값 | 의미 |
|---|---|
| `WAITING` | 큐 대기 중 |
| `RUNNING` | 처리 중 (`stage`로 세부 단계 확인) |
| `DONE` | 완료. S3 업로드까지 끝남 |
| `ERROR` | 실패. `error` 필드에 사유 |

#### `stage` 값

`DOWNLOADING` → `NORMALIZING` → `ALIGNING` → `MIXING` → `UPLOADING`

`options.align`이 `false`면 `ALIGNING` 단계는 건너뛴다.

---

## 5. 완료 콜백

작업이 끝나면 recog가 `callbackUrl`로 `POST`한다.

### 성공

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260914-001",
  "status": "DONE",
  "output": {
    "format": "flac",
    "sampleRate": 16000,
    "channels": 1,
    "durationMs": 3612480,
    "sizeBytes": 28431052
  },
  "alignment": {
    "applied": true,
    "reference": "p1",
    "tracks": [
      { "participantId": "p1", "offsetMs": 0,     "confidence": 1.00, "durationMs": 3600120 },
      { "participantId": "p2", "offsetMs": -1240, "confidence": 0.93, "durationMs": 3598400 },
      { "participantId": "p3", "offsetMs": 820,   "confidence": 0.88, "durationMs": 3612480 }
    ]
  },
  "timing": {
    "downloadMs": 18200,
    "processMs": 142300,
    "uploadMs": 9100,
    "totalMs": 169600
  },
  "finishedAt": "2026-09-14T10:02:49.600Z"
}
```

### 실패

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260914-001",
  "status": "ERROR",
  "error": {
    "code": "E4102",
    "message": "presigned URL expired for participantId=p3",
    "participantId": "p3"
  },
  "finishedAt": "2026-09-14T10:01:12.000Z"
}
```

### 콜백 재시도

| 항목 | 정책 |
|---|---|
| 성공 판정 | HTTP `2xx` 응답 |
| 재시도 | 최대 5회 |
| 간격 | 10초 → 30초 → 2분 → 5분 → 15분 |
| 최종 실패 시 | 로그 기록 후 중단. 결과는 `GET /v1/merge/{jobId}`로 조회 가능 |

> 콜백은 중복 도착할 수 있다. master-api는 `jobId` 기준으로 **멱등 처리**할 것.

---

## 6. 처리 동작 상세

### 6.1 다운로드

`files[].getUrl`로 병렬 다운로드한다. 하나라도 실패하면 작업 전체를 실패 처리한다
(일부만 빠진 채 병합하면 대화가 누락되기 때문).

### 6.2 정규화

모든 입력을 **16kHz / mono / 16bit** 로 통일한다.
master-api가 생성하는 flac이 이미 이 규격이므로(`utils/file/audio.util.js`) 대부분 변환 비용이 없다.
입력 파일별로 샘플레이트나 채널 수가 달라도 이 단계에서 흡수된다.

### 6.3 정렬 (`options.align: true`일 때)

참가자 녹음들 사이의 **시작 시점 어긋남**을 보정한다.

1. 첫 번째 파일을 기준(reference)으로 삼는다
2. 나머지 파일마다 정규화 상호상관으로 offset과 신뢰도를 구한다
3. **신뢰도가 임계값(0.5) 미만이면 해당 트랙은 `offsetMs: 0`으로 폴백**한다

3번이 중요하다. 참가자들이 각자 다른 장소에 있었다면 녹음 사이에 공통된 소리가 없어
상호상관이 의미 없는 값을 낸다. 이때 그 값을 적용하면 결과가 오히려 나빠지므로,
신뢰도로 걸러내어 **정렬 없이 겹치는 것과 동일한 결과**로 되돌린다.

즉 참가자 위치와 무관하게 손해 보지 않는다. 맞출 수 있으면 맞추고, 아니면 그대로 겹친다.

정렬이 적용된 구간에 한해 drift(기기별 클럭 오차) 보정도 함께 수행한다.
보정폭이 0.5%를 넘으면 이상값으로 판단해 보정하지 않는다.

### 6.4 병합

정렬된 트랙을 **모두 같은 타임라인에 겹쳐서** 하나로 합산한다 (ffmpeg `amix`).
순차 연결(concatenation)이 아니다.

- 결과 길이 = 가장 긴 트랙 기준
- 합산 후 리미터를 적용해 클리핑을 방지한다

### 6.5 업로드

`output.putUrl`로 `PUT` 한다. 업로드 성공 확인 후 로컬 임시 파일을 즉시 삭제한다.

### 6.6 정리

작업 디렉터리는 완료·실패 여부와 무관하게 삭제한다.
고아 파일 대비로 호스트 cleanup 스크립트가 24시간 이상 된 잔여물을 주기적으로 제거한다.

---

## 7. 에러 코드

| 코드 | HTTP | 의미 | 조치 |
|---|:---:|---|---|
| `E4001` | 400 | 필수 필드 누락 | 요청 본문 확인 |
| `E4002` | 400 | `files`가 비어 있음 | 최소 1개 필요 |
| `E4003` | 400 | `files` 개수 초과 | 최대 5개 |
| `E4004` | 400 | `participantId` 중복 | 고유값으로 전달 |
| `E4010` | 401 | 토큰 불일치 | `Authorization` 헤더 확인 |
| `E4040` | 404 | `jobId` 없음 | 조회 대상 확인 |
| `E4090` | 409 | 동일 `roomNo` 작업이 이미 진행 중 | 완료 후 재요청 |
| `E4101` | — | S3 다운로드 실패 | URL·권한 확인 |
| `E4102` | — | presigned URL 만료 | 유효기간 늘려 재요청 |
| `E4103` | — | 오디오 디코딩 실패 (손상 파일) | 원본 확인 |
| `E4104` | — | 병합 실패 (ffmpeg 오류) | 로그 확인 |
| `E4105` | — | S3 업로드 실패 | `putUrl`·권한 확인 |
| `E5000` | 500 | 내부 오류 | 로그 확인 |

`E41xx`대는 큐 처리 중 발생하므로 HTTP 응답이 아니라 **콜백의 `error.code`**로 전달된다.

---

## 8. 제약 사항

| 항목 | 값 |
|---|---|
| 파일 개수 | 1 ~ 5개 |
| 파일당 최대 크기 | 2GB |
| 지원 입력 포맷 | flac, wav, mp3, m4a, pcm(s16le 16kHz mono) |
| 출력 포맷 | flac (기본), wav |
| 동시 처리 | 3건 (환경변수로 조정) |
| 작업 타임아웃 | 30분 |

**동시 처리 3건**이란 recog 서버가 **같은 시각에 실제로 병합 작업을 돌리는 개수**를 말한다.
API 요청은 그보다 많이 받아도 되며, 넘치는 요청은 큐에서 대기하다가 앞 작업이 끝나면 순서대로 처리된다.
즉 4번째 요청도 `202`로 정상 접수되고 `status: "WAITING"` 상태로 대기한다. 거절되지 않는다.

**작업 타임아웃 30분**은 한 건이 `RUNNING`으로 들어간 뒤 30분 안에 못 끝내면
중단하고 `ERROR`로 처리한다는 뜻이다. 큐 대기 시간은 여기에 포함되지 않는다.

---

## 9. master-api 연동 가이드

### 9.1 호출 예시

```js
const res = await fetch(`${process.env.MERGE_API_URL}/v1/merge`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${process.env.MERGE_API_TOKEN}`,
  },
  body: JSON.stringify({
    roomNo,
    files: participants.map(p => ({
      participantId: p.id,
      getUrl: presignGet(p.fileKey, { expiresIn: 21600 }),
      fileName: p.fileName,
    })),
    output: {
      putUrl: presignPut(mergedKey, { expiresIn: 21600 }),
      format: 'flac',
    },
    callbackUrl: `${process.env.API_BASE_URL}/v1/internal/merge-callback`,
  }),
});

const { jobId } = await res.json();
```

### 9.2 콜백 수신 후 처리

콜백을 받으면 병합 파일이 이미 S3에 올라가 있는 상태다.
이어서 기존 STT 경로에 태우면 된다.

```
콜백 수신
  → contentModel.createContent()      콘텐츠 레코드 생성
  → recogService.addTask()            STT 큐 투입 (기존 로직 그대로)
```

기존 모바일 업로드 경로(`drive.service.js:uploadEncryptionContent`)가
`convertPcmToFlac` → `drive.put` → `recogService.addTask` 순서인 것과 동일하다.
앞의 두 단계를 recog 서버가 대신 수행한 형태이므로 **마지막 단계만 이어 붙이면 된다.**

### 9.3 확인 사항

- 콜백 엔드포인트는 `jobId` 기준 멱등 처리 (중복 도착 가능)
- presigned URL 유효기간 6시간 이상
- `alignment.applied`가 `false`거나 `confidence`가 전반적으로 낮으면
  정렬 없이 단순 병합된 것 — 결과 품질 이슈 추적 시 이 값부터 확인

---

## 10. 기존 recog API와의 관계

recog에는 이미 `/rooms`, `/sessions` 계열 엔드포인트가 있다.
클라이언트가 방을 만들고 실시간으로 참여해 녹음을 업로드하는 경로다.

`/v1/merge`는 **그 경로와 독립적으로 추가**되며, 기존 엔드포인트는 변경하지 않는다.

| | 기존 `/sessions` 경로 | 신규 `/v1/merge` |
|---|---|---|
| 입력 | 클라이언트가 multipart 업로드 | S3 presigned URL |
| 출력 | 로컬 보관 + HTTP GET 제공 | S3 업로드 |
| 결과물 | 정렬 트랙 + 믹스 + 매니페스트 | 믹스 1개 |
| 응답 | 동기 | 비동기 (jobId + 콜백) |

내부 DSP 모듈(`src/audio_sync/dsp/`)은 양쪽이 공유한다.

---
---

# 부록 A. 작업 메모 (내부용)

> master-api 담당자에게 공유하는 문서가 아니다. 구현 재개 시 여기부터 읽는다.
> 공유용 문서는 `newDocs/MERGE_API_GUIDE.md`.

## A.1 현재 상태 (2026-09-14 기준)

- 스펙 확정 완료. **코드는 한 줄도 작성하지 않음.**
- 다음 단계: master-api 담당자 리뷰 → 수정사항 반영 → 구현 착수
- 브랜치: `skHynix_nohsn`

## A.2 확정된 설계 결정과 근거

| 결정 | 근거 |
|---|---|
| S3 접근은 presigned URL로만 | recog는 현재 pip 의존성 0개(stdlib + ffmpeg). boto3 추가 시 그 정책이 깨짐. 표준 `urllib`로 해결 가능 |
| 비동기 (jobId + 콜백) | 5명 1시간이면 3~5분 소요. 동기 응답은 타임아웃 |
| 출력은 믹스 1개 | 사용자 결정. 화자분리는 master-api의 STT 엔진이 처리 |
| 정렬은 켜되 신뢰도 게이트 | 이미 구현된 기능이라 켜는 비용이 낮음. 신뢰도 폴백으로 최악의 경우에도 단순 겹침과 동일 |
| 16kHz 작업 포맷 | master-api가 만드는 flac이 16kHz mono. 48kHz로 올려도 정보량 증가 없이 CPU만 3배 |

### 폐기된 검토 사항 (다시 꺼내지 말 것)

- **지배 트랙 선택(dominant mix)** — 같은 회의실 공용 마이크 상황을 전제로 제안했으나,
  실제로는 참가자별 개인 기기 녹음이라 전제가 틀렸음. 단순 `amix` 합산으로 충분.
- **`startedAt` 메타데이터 요구** — 앱/백엔드 수정이 필요해 범위 밖. 상호상관으로 대체.
- **화자분리** — `src/recog/models.py:246`에 `speaker_diarization: False` 명시. 계속 미지원.

## A.3 구현 시 건드릴 파일

| 파일 | 작업 |
|---|---|
| `src/recog/api.py` | `POST /v1/merge`, `GET /v1/merge/{jobId}` 라우트 추가. 기존 라우팅이 `if method == ... and path == ...` 나열식이라 같은 패턴으로 추가 |
| `src/recog/merge_job.py` (신규) | 작업 큐, 상태 관리, 워커 스레드 |
| `src/recog/s3_transfer.py` (신규) | presigned URL 다운로드/업로드. `urllib.request`만 사용 |
| `src/recog/callback.py` (신규) | 콜백 POST + 재시도 (10s/30s/2m/5m/15m) |
| `src/recog/pipeline.py` | 정렬 로직 재사용. 신뢰도 게이트(0.5) 추가 필요 |
| `src/recog/audio.py:406` | `mix_tracks()` 그대로 사용 가능 (`amix` + `alimiter`) |
| `src/audio_sync/dsp/canonicalize.py:7` | `DEFAULT_WORKING_SAMPLE_RATE`를 48000 → 16000 검토. 기존 `/sessions` 경로 영향 확인 후 결정 |
| `tests/test_merge_api.py` (신규) | 기존 테스트가 unittest 기반이므로 동일하게 |

## A.4 구현 시 주의점

**정렬 신뢰도 게이트가 핵심.**
`src/audio_sync/dsp/alignment.py:102` `normalized_correlation()`이 `(lag, confidence)`를 반환한다.
`confidence < 0.5`면 해당 트랙 `offset = 0`으로 강제. 이게 없으면 참가자들이 각자 다른 장소에 있을 때
의미 없는 offset으로 트랙을 밀어버려 결과가 망가진다. **반드시 테스트로 검증할 것**
(공통 신호가 없는 합성 코퍼스로 → offset이 0으로 떨어지는지 확인).

**drift 보정은 정렬에 종속.**
`src/audio_sync/dsp/drift.py:10` `fit_piecewise_drift()`는 landmark 2개 이상을 요구하고,
보정폭이 `max_correction_delta=0.005`를 넘으면 스스로 `correction_factor=1.0`으로 되돌린다.
정렬이 폴백되면 drift도 자동으로 무력화되므로 별도 가드는 불필요.

**동시 처리 3건 = 실제 워커 수.** 요청은 큐에 무제한 적재되고 `WAITING`으로 대기한다.
4번째 요청을 거절하면 안 된다 (문서 8절에 명시함).

**임시 파일 정리.** 성공·실패 무관하게 작업 디렉터리 삭제.
호스트 cleanup 스크립트(커밋 `7b8a367`)가 이미 있으므로 그 경로 규칙과 맞출 것.

**인증.** recog에는 현재 인증이 전혀 없다(`api.py`에 토큰/JWT 검증 없음).
`/v1/merge`에는 `Authorization: Bearer` 검사를 붙인다. 기존 엔드포인트는 이번 범위 밖.

## A.5 master-api 쪽 참고 코드 위치

공유받은 `newDocs/master-api/` 기준.

| 경로 | 내용 |
|---|---|
| `controller/content/upload.controller.js:129` | 다중 파일 업로드 진입점 (`uploadEncryptionFilesContent`) |
| `services/system/drive.service.js:186` | 조각 병합 전체 흐름 (`uploadEncryptionContent`) |
| `utils/secure.util.js:28` | 실제 병합 = AES 복호화하며 `flags:'a'`로 **바이트 단순 이어붙이기** |
| `utils/file/audio.util.js:81` | `convertPcmToFlac` — `-f s16le -ar 16000 -ac 1` → flac |
| `utils/drive.util.js:88` | 스토리지 업로드 (`put`) |
| `services/recog.service.js:94` | **비동기 패턴 참고** — ticketId 발급 + BullMQ 큐 + notify 푸시 |
| `utils/queue/cluster.util.js` | BullMQ 래퍼 |

### 확인된 사실

- **스토리지가 MinIO다** (`@timbel-timblo-onpremise/minio-js`). AWS SDK는 레포 전체에 없음
  (`aws-sdk`, `@aws-sdk`, `S3Client`, `amazonaws`, `getSignedUrl` 전부 검색 결과 0건).
  사용자는 "AWS S3"라고 했으므로 master-api 쪽에서 신규 추가할 예정. → 협의사항 1·3번
- **S3에 올라간 flac은 암호화되어 있지 않다.** AES는 모바일→서버 전송 구간에만 적용되고,
  `decryptFilesAesCbc` → `convertPcmToFlac` → `put` 순서라 저장 시점엔 평문.
  → **우리는 AES 키 없이 받아서 바로 ffmpeg에 넣으면 된다.**
- master-api의 "merge"는 **한 기기의 조각을 시간순 이어붙이기**. 우리의 merge(겹치기)와 축이 다르다.
  코드 재사용 불가, 구조만 참고.

## A.6 미해결 / 확인 대기

1. 병합 서버 주소·네트워크 경로 (내부망? VPC?)
2. `MERGE_API_TOKEN` 값과 전달 방법
3. S3 버킷명·리전·결과물 키 규칙
4. 제약값 검증 — 파일 5개 / 2GB / 동시 3건 / 30분이 실제 운영 규모에 맞는지
5. **참가자들이 같은 공간인지 각자 다른 장소인지** — 정렬 신뢰도가 실제로 어떻게 나올지 예측에 필요.
   설계상 어느 쪽이든 동작하지만, 각자 다른 장소라면 정렬이 항상 폴백될 것이므로
   `options.align` 기본값을 `false`로 바꾸는 게 CPU 낭비를 줄인다.
6. `canonicalize.py`의 작업 샘플레이트를 16kHz로 내릴 때 기존 `/sessions` 경로 회귀 여부

## A.7 다음 세션 시작 지점

1. master-api 담당자 리뷰 결과 확인 → 이 문서와 `MERGE_API_GUIDE.md` 수정
2. A.6의 미해결 항목 중 답이 온 것 반영
3. 구현 착수 시 A.3 파일 목록 순서대로:
   `s3_transfer.py` → `merge_job.py` → `api.py` 라우트 → `callback.py` → 테스트

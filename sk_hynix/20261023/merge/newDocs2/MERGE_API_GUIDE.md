# 음성 병합 서버 연동 가이드

> master-api 담당자용 문서입니다.
> 작성일 2026-09-14 · 갱신 2026-09-19

---

## 1. 이 서버가 하는 일

참가자별로 따로 녹음된 파일 여러 개를 받아 **하나로 겹쳐 합쳐서** 스토리지에 올려드립니다.

```
p1.flac  (1시간)  ┐
p2.flac  (1시간)  ├──►  merged.flac  (1시간)
p3.flac  (1시간)  ┘
```

**결과물은 1시간짜리 1개입니다.** 참가자 수만큼 길어지지 않습니다.
모든 트랙을 같은 타임라인에 올려놓고 합산하기 때문입니다.

> master-api가 기존에 하는 "한 기기의 조각을 시간순으로 이어붙이기"와는 다릅니다.
> 그건 3시간짜리가 나오지만, 이건 1시간짜리가 나옵니다.

**하지 않는 일**: STT 전사, 화자분리, 요약, DB 기록
전부 기존처럼 master-api가 처리하시면 됩니다. 저희는 오디오만 합칩니다.

---

## 2. 연동에 필요한 작업 3가지

| # | 작업 | 난이도 |
|---|---|---|
| 1 | presigned URL 발급 (GET N개 + PUT 1개) | 신규 구현 필요 |
| 2 | `POST /v1/merge` 호출 | 간단 |
| 3 | `GET /v1/merge/{jobId}` 폴링 | HAIV 연동과 동일 패턴 |

3번은 기존 `utils/engines/Haiv/utils/get.js`의 `pollStatusAndResults`와
구조가 같습니다. 그 코드를 참고하시면 빠릅니다.

**인증은 없습니다.** 같은 도커 네트워크 안이라 토큰·헤더 불필요합니다.

---

## 3. 먼저 알아야 할 것 — presigned URL

저희 서버는 **스토리지 자격증명을 갖고 있지 않습니다.**
파일 접근은 전부 master-api가 발급해주신 presigned URL로만 합니다.

이렇게 한 이유:

- 저희 서버는 현재 외부 라이브러리 의존성이 0개입니다 (파이썬 표준 + ffmpeg).
  MinIO 클라이언트를 추가하면 그 정책이 깨집니다.
- MinIO 자격증명이 Consul KV 한 곳(`timblo/common/credentials`)에서만 관리되고
  런타임에 회전됩니다. 저희에게 나눠주면 그 관리 범위가 넓어지고, 회전 때마다
  양쪽을 맞춰야 합니다.

presigned URL이면 이 문제가 없습니다. 키는 master-api가 계속 독점하시고,
저희는 한시적 URL만 받습니다.

### 3.1 발급 예시

```js
import { Client } from '@timbel-timblo-onpremise/minio-js';

const EXPIRES = 6 * 60 * 60;   // 6시간

// 다운로드용 — 참가자 파일마다
const getUrl = await minio.presignedGetObject(
    BUCKET_NAME,
    `${kms}/${fileKey}`,
    EXPIRES
);

// 업로드용 — 결과물 1개
const putUrl = await minio.presignedPutObject(
    BUCKET_NAME,
    `${kms}/${mergedFileKey}`,
    EXPIRES
);
```

**유효기간은 6시간 이상**으로 잡아주세요.
대용량 회의는 다운로드·병합·업로드까지 수 분이 걸리고, 큐가 밀리면 대기 시간이 더해집니다.

### 3.2 ⚠️ `originalname` — 가장 주의할 부분입니다

master-api는 다운로드 시 파일명을 오브젝트 메타데이터에서 읽습니다
(`utils/file/stream.util.js` → `metaData['originalname']` → `Content-Disposition`).

이 메타데이터가 빠지면 **사용자가 병합본을 받을 때 파일명이 깨집니다.**

presigned PUT은 서명이 헤더를 고정하기 때문에, 두 가지가 **모두** 필요합니다:

1. `putUrl` 발급 시 **`x-amz-meta-originalname`을 서명에 포함**
2. 요청 본문 `output.originalname`에 **서명에 넣은 값과 완전히 같은 문자열** 전달

저희는 받은 값을 **가공 없이 그대로** 헤더에 실어 PUT합니다.
한 글자라도 다르면 서명 불일치로 `403`이 납니다.

**퍼센트 인코딩된 ASCII로 주세요.** HTTP 헤더는 latin-1만 담을 수 있어서
한글이 그대로 오면 헤더에 넣을 수가 없습니다. 저희가 임의로 인코딩하면
서명이 깨지므로, non-ASCII가 오면 `E4007`로 거부합니다.

이미 `createPutParams()`에서 `encodeURIComponent(originalname)`으로 저장하고 계시니
(`utils/drive.util.js`) **그 값을 그대로 주시면 됩니다.** 다운로드 쪽 `ensureEncoded()`도
인코딩된 값을 전제로 동작하고 있어서 기존 흐름과 일치합니다.

> `presignedPutObject(bucket, object, expiry)`에는 메타데이터 인자가 없습니다.
> 메타데이터를 서명에 넣으려면 `presignedUrl(method, bucket, object, expiry, reqParams)`
> 계열을 쓰셔야 할 수 있습니다. SDK 쪽 확인 부탁드립니다.

### 3.3 URL 호스트

presigned URL의 호스트는 **내부 DNS 이름**(`timblo-minio:9000` 등)으로 발급해주시면 됩니다.
저희 컨테이너를 같은 도커 네트워크(`timblo-net-package`)에 붙이겠습니다.

---

## 4. 병합 요청

### `POST {병합서버주소}/v1/merge`

```json
{
  "roomNo": "R-20260919-001",
  "files": [
    {
      "participantId": "p1",
      "startedAt": "2026-09-19T14:30:52.104Z",
      "getUrl": "http://timblo-minio:9000/default.timblo.io/...?X-Amz-Algorithm=...",
      "fileName": "A.Biz_m_rec_20260919_143052.flac"
    },
    {
      "participantId": "p2",
      "startedAt": "2026-09-19T14:30:52.371Z",
      "getUrl": "http://timblo-minio:9000/default.timblo.io/...?X-Amz-Algorithm=...",
      "fileName": "A.Biz_m_rec_20260919_143052.flac"
    }
  ],
  "output": {
    "putUrl": "http://timblo-minio:9000/default.timblo.io/...?X-Amz-Algorithm=...",
    "originalname": "R-20260919-001_merged.flac",
    "format": "flac"
  },
  "options": {
    "align": "none"
  }
}
```

### 필드 설명

| 필드 | 필수 | 설명 |
|---|:---:|---|
| `roomNo` | ✅ | 회의룸 번호. 로그 추적용 |
| `files[].participantId` | ✅ | 참가자 식별자. 중복 불가 |
| `files[].getUrl` | ✅ | 다운로드용 presigned GET URL |
| `files[].startedAt` | 조건부 | 녹음 시작 시각. `align: "timestamp"`일 때만 필수 |
| `files[].fileName` | — | 로그 가독성용 |
| `output.putUrl` | ✅ | 업로드용 presigned PUT URL |
| `output.originalname` | ✅ | 결과 파일명. **3.2 참조** |
| `output.format` | — | `flac`(기본) / `wav` |
| `options.align` | — | `none`(기본) / `timestamp`. **4.1 참조** |

### 4.1 `options.align` — 두 가지 중 고르시면 됩니다

| 값 | 동작 | 언제 쓰나 |
|---|---|---|
| **`"none"`** (기본) | 모든 트랙을 0초 지점에서 겹칩니다 | 참가자들이 거의 동시에 녹음을 시작하는 경우 |
| **`"timestamp"`** | `startedAt` 차이만큼 각 트랙 앞에 무음을 넣어 맞춥니다 | 시작 시점이 제각각이거나, 더 정확히 맞추고 싶은 경우 |

방장이 시작을 누르면 참가자 전원에게 전파되는 구조라고 들었습니다.
그러면 **`"none"`으로 충분**할 가능성이 높아서 기본값으로 두었습니다.

`"timestamp"`를 쓰시려면 `startedAt`을 **밀리초 단위**로 주셔야 합니다.

> **초 단위로 주시면 오히려 나빠질 수 있습니다.**
> 네트워크 지연으로 인한 실제 차이가 수백 ms인데 초 단위로 반올림하면,
> 0.2초 차이를 1초로 밀어버리는 경우가 생깁니다.
> 밀리초를 못 주시는 상황이면 `"none"`을 쓰시는 게 낫습니다.

저희 쪽 안전장치: 계산된 offset이 60초를 넘으면 해당 트랙만 0으로 되돌립니다.
시계가 틀어진 기기 하나가 전체를 망치지 않도록요. 결과에 표시해드립니다.

### 응답 — `202 Accepted`

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

요청은 큐에 넣고 **즉시 반환**합니다. 실제 병합은 백그라운드에서 진행됩니다.

### 호출 코드 예시

```js
const res = await fetch(`${process.env.MERGE_API_URL}/v1/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        roomNo,
        files: participants.map(p => ({
            participantId: p.id,
            startedAt: p.recordStartedAt.toISOString(),
            getUrl: await presignGet(p.fileKey),
            fileName: p.fileName,
        })),
        output: {
            putUrl: await presignPut(mergedKey, encodeURIComponent(mergedFileName)),
            originalname: encodeURIComponent(mergedFileName),
            format: 'flac',
        },
        options: { align: 'none' },
    }),
});

const { jobId, retryAfterMs } = await res.json();
```

---

## 5. 상태 조회 (폴링)

### `GET {병합서버주소}/v1/merge/{jobId}`

이 엔드포인트를 주기적으로 호출해주시면 됩니다.
**HAIV 연동에서 쓰시는 방식과 같습니다.**

### 진행 중

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "status": "RUNNING",
  "stage": "MIXING",
  "progress": 45,
  "retryAfterMs": 5000
}
```

### 완료

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260919-001",
  "status": "DONE",
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
      { "participantId": "p2", "offsetMs": 267, "fallback": false }
    ]
  },
  "timing": { "downloadMs": 18200, "processMs": 92300, "uploadMs": 9100, "totalMs": 119600 },
  "finishedAt": "2026-09-19T14:37:01.700Z"
}
```

완료 시점엔 **병합 파일이 이미 스토리지에 올라가 있습니다.**

### 실패

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "status": "ERROR",
  "error": {
    "code": "E4102",
    "message": "presigned URL expired for participantId=p3",
    "participantId": "p3"
  },
  "finishedAt": "2026-09-19T14:36:12.000Z"
}
```

> **작업이 실패해도 HTTP는 `200`입니다.** 조회 자체는 성공했으니까요.
> `status` 필드로 판별해주세요. `404`는 `jobId`가 아예 없을 때만 나옵니다.

### `status` 값

| 값 | 의미 |
|---|---|
| `WAITING` | 큐 대기 중 |
| `RUNNING` | 처리 중 (`stage`로 세부 단계) |
| `DONE` | 완료 |
| `ERROR` | 실패 |

`stage`: `DOWNLOADING` → `NORMALIZING` → `MIXING` → `UPLOADING`

### 5.1 `retryAfterMs` — 폴링 주기를 저희가 제안합니다

응답에 다음 조회까지 기다릴 시간을 담아드립니다.
이 값을 쓰시면 주기를 하드코딩하실 필요가 없습니다.

| 상황 | 값 |
|---|---|
| 큐 대기 중 | 10초 |
| 다운로드·정규화·믹싱 중 | 5초 |
| 업로드 중 (곧 끝남) | 2초 |
| 완료·실패 | 없음 (폴링 종료) |

고정 5초로 도시더라도 동작에는 문제없습니다.

### 폴링 코드 예시

```js
const pollMergeResult = async (jobId) => {
    while (true) {
        const res = await fetch(`${process.env.MERGE_API_URL}/v1/merge/${jobId}`);
        const data = await res.json();

        if (data.status === 'DONE')  return data;
        if (data.status === 'ERROR') throw new Error(`[${data.error.code}] ${data.error.message}`);

        await new Promise(r => setTimeout(r, data.retryAfterMs ?? 5000));
    }
};
```

### 5.2 결과 보존 기간

완료된 작업은 **24시간** 동안 조회 가능합니다. 이후 `404`.
폴링을 놓치셔도 하루 안에는 결과를 가져가실 수 있습니다.

---

## 6. 완료 후 처리

```
GET 응답이 status: 'DONE'
  → statObject()                    업로드 실체 검증 (크기·존재)
  → contentModel.createContent()    콘텐츠 레코드 생성
  → recogService.addTask()          STT 큐 투입 (기존 로직 그대로)
```

기존 모바일 업로드 경로(`drive.service.js` `uploadEncryptionContent`)가
`decryptFilesAesCbc` → `convertPcmToFlac` → `put` → `recogService.addTask` 순서인데,
**앞의 세 단계를 저희가 대신한 형태입니다. 마지막 단계만 이어 붙이시면 됩니다.**

`statObject` 검증을 권해드리는 이유: presigned 방식은 `put()` 직후에 묶여 있던
DB 기록 → 캐시 워밍 → STT 큐 투입 → 실패 롤백의 연결을 끊습니다.
업로드 실체를 한 번 확인하신 뒤 후속 처리를 이으시는 게 안전합니다.

---

## 7. 제약 사항

| 항목 | 값 |
|---|---|
| 파일 개수 | 1 ~ 5개 |
| 파일당 최대 크기 | 2GB |
| 지원 입력 포맷 | flac, wav, mp3, m4a, pcm(s16le 16kHz mono) |
| 출력 포맷 | flac (기본), wav |
| 동시 처리 | 3건 |
| 작업 타임아웃 | 30분 |
| 결과 보존 | 24시간 |

### "동시 처리 3건"의 의미

저희가 **같은 시각에 실제로 병합을 돌리는 개수**입니다.
요청은 그보다 많이 보내셔도 됩니다.

4번째 요청도 `202`로 정상 접수되고 `WAITING` 상태로 대기하다가
앞 작업이 끝나면 순서대로 처리됩니다. **거절되지 않습니다.**

### "작업 타임아웃 30분"의 의미

한 건이 `RUNNING`으로 들어간 뒤 30분 안에 못 끝내면 중단하고 `ERROR`(`E4106`)로 처리합니다.
큐 대기 시간은 포함되지 않습니다.

---

## 8. 에러 코드

### 요청 즉시 반환 (HTTP 응답)

| 코드 | HTTP | 의미 |
|---|:---:|---|
| `E4001` | 400 | 필수 필드 누락 |
| `E4002` | 400 | `files`가 비어 있음 |
| `E4003` | 400 | `files` 개수 초과 (최대 5개) |
| `E4004` | 400 | `participantId` 중복 |
| `E4005` | 400 | `align: "timestamp"`인데 `startedAt` 누락 |
| `E4006` | 400 | `startedAt` 형식 오류 (ISO8601 필요) |
| `E4007` | 400 | `originalname`에 non-ASCII 포함 (퍼센트 인코딩 필요) |
| `E4040` | 404 | `jobId` 없음 (또는 24시간 경과) |
| `E4090` | 409 | 동일 `roomNo` 작업이 이미 진행 중 |
| `E5000` | 500 | 내부 오류 |

### 처리 중 발생 (상태 조회 응답의 `error.code`)

| 코드 | 의미 | 조치 |
|---|---|---|
| `E4101` | 다운로드 실패 | URL·권한 확인 |
| `E4102` | presigned URL 만료 | 유효기간 늘려 재요청 |
| `E4103` | 오디오 디코딩 실패 (손상 파일) | 원본 확인 |
| `E4104` | 병합 실패 (ffmpeg 오류) | 저희 로그 확인 |
| `E4105` | 업로드 실패 | `putUrl`·서명 헤더 확인 |
| `E4106` | 작업 타임아웃 | 파일 크기·서버 부하 확인 |

---

## 9. 연동 체크리스트

- [ ] presigned GET URL 발급 구현 (`presignedGetObject`)
- [ ] presigned PUT URL 발급 구현 — **`x-amz-meta-originalname`을 서명에 포함**
- [ ] presigned 유효기간 6시간 이상
- [ ] presigned URL 호스트를 내부 DNS 이름으로 발급
- [ ] `POST /v1/merge` 호출
- [ ] `GET /v1/merge/{jobId}` 폴링 (`status`로 판별, HTTP 200이어도 실패일 수 있음)
- [ ] `DONE` 수신 후 `statObject`로 업로드 검증
- [ ] `contentModel.createContent()` + `recogService.addTask()` 연결
- [ ] `align` 모드 결정 (`none` / `timestamp`)

---

## 10. 확인 부탁드리는 사항

1. **`presignedGetObject` / `presignedPutObject` 사용 가능 여부**
   `@timbel-timblo-onpremise/minio-js`가 표준 minio-js 8.0.6 포크인 건 확인했는데,
   포크에서 이 메서드들이 유지되는지는 `node_modules`를 못 봐서 확인하지 못했습니다.
   ```bash
   grep -rn "presigned" node_modules/@timbel-timblo-onpremise/minio-js/dist/ | head
   ```

2. **PUT 서명에 `x-amz-meta-originalname`을 넣는 방법** (3.2 참조)

3. **`startedAt`을 밀리초 단위로 주실 수 있는지**
   가능하면 `align: "timestamp"`, 어려우면 `align: "none"`으로 갑니다.

4. **병합 서버 주소** — 컨테이너명·포트, 그리고 도커 네트워크명
   (저희는 `timblo-net-package`로 알고 있습니다)

5. **제약값이 실제 운영 규모에 맞는지** — 파일 5개 / 2GB / 동시 3건 / 30분

---

## 11. 참고 — 이전 협의에서 정리된 것

| 항목 | 결정 |
|---|---|
| 인증 | **없음.** 같은 도커 네트워크 내부 통신 |
| 상태 전달 | **폴링.** 콜백·소켓·SSE 미사용 |
| 병합 방식 | **겹치기.** 5명 1시간 → 결과 1시간 |
| 파일 암호화 | **없음.** 스토리지의 flac은 평문이므로 AES 키 불필요 |
| 정렬 | `none` 기본 / `timestamp` 선택 |
| 출력 | 믹스 1개. 화자분리는 master-api STT 엔진이 처리 |

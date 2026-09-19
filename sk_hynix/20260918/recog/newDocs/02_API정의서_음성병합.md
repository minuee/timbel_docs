# 음성 병합 API 정의서

| 항목 | 내용 |
|---|---|
| 서비스명 | recog 음성 병합 서버 |
| 버전 | 1.0.0 |
| 작성일 | 2026-09-19 |
| Base URL | `http://<병합서버>:28080` |
| 인증 | 없음 (도커 네트워크 내부 통신) |
| Content-Type | `application/json` |
| Swagger | `http://<병합서버>:28080/docs` — Basic 인증 (계정은 별도 전달) |

---

## 1. 개요

참가자별로 따로 녹음된 파일 여러 개를 **하나로 겹쳐서** 합친 뒤 오브젝트 스토리지에 올린다.

```
p1.flac (1시간) ┐
p2.flac (1시간) ├──►  merged.flac (1시간)
p3.flac (1시간) ┘
```

**결과물은 1시간짜리 1개다.** 참가자 수만큼 길어지지 않는다.
모든 트랙을 같은 타임라인에 올려놓고 합산하기 때문이다.

> 기존 master-api의 "한 기기 조각을 시간순으로 이어붙이기"와는 축이 다르다.
> 그건 3시간짜리가 나오지만, 이건 1시간짜리가 나온다.

### 수행 범위

| 한다 | 하지 않는다 |
|---|---|
| presigned URL로 다운로드 | STT 전사 |
| 16kHz mono 정규화 | 화자분리 |
| 겹쳐서 믹스다운 | 요약 |
| presigned URL로 업로드 | DB 기록 |

---

## 2. 엔드포인트 목록

| Method | Path | 설명 | 인증 |
|---|---|---|:---:|
| `POST` | `/v1/merge` | 병합 작업 접수 | — |
| `GET` | `/v1/merge/{jobId}` | 작업 상태 조회 (폴링) | — |
| `POST` | `/v1/merge/{jobId}/retry` | 재작업 (저장된 요청으로 재실행) | — |
| `GET` | `/v1/merge` | 병합 이력 조회 | — |
| `POST` | `/v1/merge/upload` | 파일 직접 업로드 (테스트용) | — |
| `GET` | `/v1/merge/{jobId}/download` | 결과 파일 다운로드 (테스트용) | — |
| `GET` | `/health` | 헬스체크 | — |
| `GET` | `/docs` | Swagger UI | ✅ Basic |
| `GET` | `/openapi.json` | OpenAPI 문서 | ✅ Basic |

---

## 3. 연동 흐름

```
① presigned URL 발급 (GET N개 + PUT 1개)
      └ PUT은 x-amz-meta-originalname 을 서명에 포함

② POST /v1/merge                    → 202 { jobId }

③ GET /v1/merge/{jobId} 반복 호출     ← retryAfterMs 간격
      status === 'DONE'  → ④
      status === 'ERROR' → 실패 처리

④ statObject 로 업로드 실체 검증

⑤ contentModel.createContent()
   recogService.addTask()            기존 STT 경로에 합류
```

기존 모바일 업로드 경로가 `복호화 → flac 변환 → 업로드 → STT 큐` 순인 것과 같다.
**앞의 세 단계를 병합 서버가 대신한 형태이므로 마지막 단계만 이어 붙이면 된다.**

---

## 4. `POST /v1/merge` — 병합 작업 접수

요청을 큐에 넣고 **즉시 반환**한다. 실제 병합은 백그라운드에서 진행된다.

### 4.1 Request

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

### 4.2 필드 정의

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|:---:|---|---|
| `roomNo` | string | ✅ | — | 회의룸 번호. 로그·추적용 |
| `files` | array | ✅ | — | 병합 대상. 1 ~ 5개 |
| `files[].participantId` | string | ✅ | — | 참가자 식별자. **중복 불가** |
| `files[].getUrl` | string | ✅ | — | 다운로드용 presigned GET URL |
| `files[].startedAt` | string | 조건부 | — | 녹음 시작 시각(ISO8601). `align: "timestamp"`일 때 **필수** |
| `files[].fileName` | string | — | — | 원본 파일명. 로그 가독성용 |
| `output.putUrl` | string | ✅ | — | 업로드용 presigned PUT URL |
| `output.originalname` | string | ✅ | — | 결과 파일명. **5절 참조** |
| `output.format` | string | — | `flac` | `flac` / `wav` |
| `options.align` | string | — | `none` | `none` / `timestamp`. **6절 참조** |

### 4.3 Response — `202 Accepted`

```json
{
  "jobId": "mrg_e2b7d3a662394c418669",
  "roomNo": "R-20260919-001",
  "status": "WAITING",
  "fileCount": 2,
  "acceptedAt": "2026-09-19T14:35:00.000Z",
  "retryAfterMs": 10000
}
```

### 4.4 호출 예시

```js
const res = await fetch(`${process.env.MERGE_API_URL}/v1/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        roomNo,
        files: participants.map(p => ({
            participantId: p.id,
            startedAt: p.recordStartedAt.toISOString(),
            getUrl: await presignGet(p.fileKey, { expiresIn: 21600 }),
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

## 5. ⚠️ `originalname` — 필수 준수 사항

master-api는 다운로드 시 파일명을 **오브젝트 메타데이터**에서 읽는다
(`utils/file/stream.util.js` → `metaData['originalname']` → `Content-Disposition`).
이 메타데이터가 빠지면 사용자가 병합본을 받을 때 파일명이 깨진다.

presigned PUT은 서명이 헤더를 고정하므로 **두 가지가 모두** 지켜져야 한다.

### 5.1 서명에 포함

`putUrl` 발급 시 `x-amz-meta-originalname`을 서명 대상에 넣는다.

> `presignedPutObject(bucket, object, expiry)`에는 메타데이터 인자가 없다.
> `presignedUrl(method, bucket, object, expiry, reqParams)` 계열이 필요할 수 있다.

### 5.2 동일한 값을 바디에

`output.originalname`에 **서명에 넣은 값과 완전히 같은 문자열**을 담는다.
병합 서버는 받은 값을 **가공 없이 그대로** 헤더에 실어 PUT한다.
한 글자라도 다르면 서명 불일치로 `403`이 난다.

### 5.3 퍼센트 인코딩된 ASCII여야 한다

HTTP 헤더는 latin-1만 담을 수 있다. 한글이 그대로 오면 헤더에 넣을 수 없고,
병합 서버가 임의로 인코딩하면 서명이 깨진다. 그래서 **접수 단계에서 `E4007`로 거부**한다.

```js
// 이미 이렇게 저장하고 계시므로 그 값을 그대로 주시면 됩니다
// utils/drive.util.js createPutParams()
originalname: encodeURIComponent(originalname),
```

| 값 | 판정 |
|---|---|
| `R-20260919-001_merged.flac` | ✅ |
| `%ED%9A%8C%EC%9D%98%EB%A1%9D_merged.flac` | ✅ |
| `회의록_merged.flac` | ❌ `E4007` |

다운로드 쪽 `ensureEncoded()`도 인코딩된 값을 전제로 동작하므로 기존 흐름과 일치한다.

---

## 6. `options.align` — 정렬 방식

| 값 | 동작 | 요구 필드 |
|---|---|---|
| **`"none"`** (기본) | 모든 트랙을 0초 지점에서 겹친다 | — |
| **`"timestamp"`** | 가장 이른 `startedAt` 기준으로 차이만큼 각 트랙 앞에 무음을 넣는다 | `files[].startedAt` |

방장이 시작을 누르면 참가자 전원에게 전파되는 구조이므로 **`"none"`으로 충분**할 가능성이
높아 기본값으로 두었다.

### 6.1 `startedAt`은 밀리초 단위로

```
✅  2026-09-19T14:30:52.104Z
❌  2026-09-19T14:30:52Z
```

> **초 단위로 주면 오히려 나빠질 수 있다.**
> 네트워크 지연으로 인한 실제 차이가 수백 ms인데 초 단위로 반올림하면,
> 0.2초 차이를 1초로 밀어버리는 경우가 생긴다.
> 밀리초를 못 주는 상황이면 `"none"`을 쓰는 편이 낫다.

| 실제 시작 | 초 단위 값 | 계산 offset | 실제 차이 | 결과 |
|---|---|---|---|---|
| A `10:00:00.900`, B `10:00:01.100` | `100000`, `100001` | 1000ms | 200ms | ❌ 800ms 더 어긋남 |

### 6.2 이상값 가드

계산된 offset이 **60초**를 넘으면 해당 트랙만 `offsetMs: 0`으로 되돌리고
응답에 `fallback: true`로 표시한다. 시계가 틀어진 기기 하나가 전체를 망치지 않도록 한다.

---

## 7. `GET /v1/merge/{jobId}` — 상태 조회 (폴링)

이 엔드포인트를 주기적으로 호출해 진행 상황을 확인한다.
HAIV STT 엔진 연동에서 쓰는 방식과 같다.

### 7.1 진행 중 — `200 OK`

```json
{
  "jobId": "mrg_e2b7d3a662394c418669",
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

### 7.2 완료 — `200 OK`

```json
{
  "jobId": "mrg_e2b7d3a662394c418669",
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
      { "participantId": "p2", "offsetMs": 267, "fallback": false }
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

완료 시점엔 **병합 파일이 이미 스토리지에 올라가 있다.**
`align: "none"`이면 `alignment`는 `{ "mode": "none" }`만 반환한다.

### 7.3 실패 — `200 OK`

```json
{
  "jobId": "mrg_e2b7d3a662394c418669",
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

> ### 🔴 작업이 실패해도 HTTP는 `200`이다
> 조회 자체는 성공했기 때문이다. **`status` 필드로 판별한다.**
> `404`는 `jobId`가 아예 없을 때만 나온다.

### 7.4 상태 값

| `status` | 의미 |
|---|---|
| `WAITING` | 큐 대기 중 |
| `RUNNING` | 처리 중 (`stage`로 세부 단계) |
| `DONE` | 완료. 업로드까지 끝남 |
| `ERROR` | 실패. `error` 필드에 사유 |

| `stage` | 진행률 |
|---|---|
| `DOWNLOADING` | 0 ~ 40% |
| `NORMALIZING` | 40 ~ 60% |
| `MIXING` | 60 ~ 85% |
| `UPLOADING` | 85 ~ 99% |

### 7.5 `retryAfterMs`

다음 조회까지 기다릴 시간을 병합 서버가 제안한다. 이 값을 쓰면 주기를 하드코딩할 필요가 없다.

| 상황 | 값 |
|---|---|
| `WAITING` | 10초 |
| `RUNNING` (다운로드·정규화·믹싱) | 5초 |
| `RUNNING` (업로드 — 곧 끝남) | 2초 |
| `DONE` / `ERROR` | 필드 없음 (폴링 종료) |

고정 5초로 돌려도 동작에는 문제없다.

### 7.6 폴링 예시

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

### 7.7 결과 보존과 유실 방지

모든 작업은 **SQLite에 기록**된다(`runtime/merge.db`). 메모리가 아니라 디스크이므로
서버가 재시작돼도 남는다.

| 상황 | 결과 |
|---|---|
| 통신 끊김 · 폴링 중단 | ✅ `jobId`로 언제든 재조회 |
| master-api 재시작 | ✅ `jobId`만 보관했다면 재조회 |
| **병합 서버 재시작** | ✅ **기록 유지. 진행 중이던 작업은 자동 재실행** |

**보존 기간은 90일**이다. 이후 기록이 정리되고 `404`가 난다.
(환경변수 `MERGE_RECORD_TTL_DAYS`로 조정 가능. `0`이면 영구 보관)

### 7.8 서버 재시작 시 동작

| 재시작 시점의 상태 | 처리 |
|---|---|
| `DONE` | 그대로 복원. 파일은 이미 스토리지에 있음 |
| `ERROR` | 그대로 복원 |
| `WAITING` / `RUNNING` | **자동으로 큐에 다시 들어가 처음부터 재실행** |

진행 중이던 작업은 임시 파일이 사라져 이어서 할 수 없지만, 요청 원본이 기록에 남아
있으므로 처음부터 다시 실행된다. presigned URL 유효기간(권장 6시간) 안이면 그대로 성공한다.

응답의 `requeueCount`가 재큐잉 횟수다. 이 값이 계속 올라가면 해당 입력에서
서버가 반복 실패하고 있다는 신호다.

> 업로드 테스트 경로(`/v1/merge/upload`) 작업은 원본 파일이 디스크에 남아 있을 때만
> 재실행된다. 없으면 `E5002`로 실패 처리한다.

---

## 8. `POST /v1/merge/{jobId}/retry` — 재작업

끝난 작업을 **저장된 요청 그대로 다시 실행**한다. 요청 본문을 새로 조립할 필요가 없다.

### 요청

본문은 **생략 가능**하다. 대부분 presigned URL 만료로 실패하므로, 새 URL만 실어 보낸다.

```json
{
  "files": [
    { "participantId": "p1", "getUrl": "http://timblo-minio:9000/...새URL" },
    { "participantId": "p2", "getUrl": "http://timblo-minio:9000/...새URL" }
  ],
  "output": { "putUrl": "http://timblo-minio:9000/...새URL" }
}
```

**바꿀 수 있는 건 presigned URL뿐이다.** 참가자 구성·정렬 모드·결과 파일명은 원래 요청을
그대로 재사용한다. 재작업이 슬쩍 다른 작업이 되는 것을 막기 위해서다.

### 응답 — `202 Accepted`

```json
{
  "jobId": "mrg_6c3e8a67eb2e4489a832",
  "retriedFrom": "mrg_cb39cf8ababe4c588a8e",
  "roomNo": "R-20260919-001",
  "status": "WAITING",
  "fileCount": 2,
  "retryAfterMs": 10000
}
```

**새 `jobId`가 발급된다.** 원래 작업은 `retriedFrom`으로 연결되어 두 시도가 모두 이력에 남는다.
이후 폴링은 새 `jobId`로 한다.

### 거부되는 경우

| 상황 | 코드 | HTTP |
|---|---|:---:|
| `jobId` 없음 | `E4040` | 404 |
| 아직 진행 중 (`WAITING`/`RUNNING`) | `E4091` | 409 |
| 업로드 테스트 경로 작업 | `E4092` | 409 |
| 같은 `roomNo` 작업이 진행 중 | `E4090` | 409 |
| override에 없는 `participantId` | `E4001` | 400 |

### 사용 예시

```js
const state = await pollMergeResult(jobId).catch(e => e);

if (state?.error?.code === 'E4102') {          // presigned 만료
    const retried = await fetch(`${MERGE_API_URL}/v1/merge/${jobId}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            files: participants.map(p => ({
                participantId: p.id,
                getUrl: await presignGet(p.fileKey, { expiresIn: 21600 }),
            })),
            output: { putUrl: await presignPut(mergedKey, encodedName) },
        }),
    }).then(r => r.json());

    return pollMergeResult(retried.jobId);     // 새 jobId 로 폴링
}
```

---

## 9. `GET /v1/merge` — 이력 조회

```
GET /v1/merge?roomNo=R-20260919-001&limit=50
```

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `roomNo` | — | 특정 회의룸으로 좁힌다 |
| `limit` | 50 | 최대 500 |

```json
{
  "count": 3,
  "jobs": [
    { "job_id": "mrg_6c3e...", "room_no": "R-001", "status": "DONE",
      "retried_from": "mrg_cb39...", "requeue_count": 0,
      "accepted_at": "...", "finished_at": "...", "output": {...}, "timing": {...} }
  ]
}
```

서버를 거치지 않고 직접 조회할 수도 있다.

```bash
sqlite3 runtime/merge.db "SELECT room_no, status, finished_at FROM merge_jobs ORDER BY accepted_at DESC LIMIT 20"

# 실패 원인 분포
sqlite3 runtime/merge.db "SELECT json_extract(error,'\$.code'), COUNT(*) FROM merge_jobs WHERE status='ERROR' GROUP BY 1"

# 평균 소요시간
sqlite3 runtime/merge.db "SELECT AVG(json_extract(timing,'\$.totalMs')) FROM merge_jobs WHERE status='DONE'"
```

---

## 10. 테스트용 엔드포인트

스토리지 없이 병합 동작만 확인할 수 있다. **동일한 큐·워커·믹싱 코드를 타므로**
실제 동작을 그대로 검증할 수 있다.

### 10.1 `POST /v1/merge/upload`

`multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `files` | File | ✅ | 병합할 오디오 파일. **같은 키로 여러 개 첨부** (1~5개) |
| `align` | Text | — | `none`(기본) / `timestamp` |
| `startedAt` | Text | 조건부 | 파일 순서대로 콤마 구분 ISO8601 목록 |
| `format` | Text | — | `flac`(기본) / `wav` |
| `roomNo` | Text | — | 식별용 |

```bash
curl -X POST http://<서버>:28080/v1/merge/upload \
  -F "files=@p1.flac" \
  -F "files=@p2.flac" \
  -F "files=@p3.flac" \
  -F "align=timestamp" \
  -F "startedAt=2026-09-19T14:30:52.000Z,2026-09-19T14:30:52.267Z,2026-09-19T14:30:52.812Z" \
  -F "roomNo=TEST-001"
```

응답은 `POST /v1/merge`와 동일한 `202`다. 이후 `GET /v1/merge/{jobId}`로 폴링한다.

완료되면 응답에 `downloadUrl`이 추가된다.

```json
{
  "status": "DONE",
  "source": "upload",
  "downloadUrl": "/v1/merge/mrg_.../download"
}
```

### 10.2 `GET /v1/merge/{jobId}/download`

병합 결과 파일을 반환한다.

```bash
curl -o merged.flac http://<서버>:28080/v1/merge/mrg_.../download
```

> presigned 경로(`POST /v1/merge`)로 만든 작업은 결과를 스토리지에 올리고
> 로컬에서 지우므로 `404`가 난다. 테스트로 만든 것만 받을 수 있다.

### 10.3 Postman 설정

```
Method : POST
URL    : http://<서버>:28080/v1/merge/upload
Body   : form-data
         files    [File]  p1.flac      ← key 이름을 files 로 여러 번 추가
         files    [File]  p2.flac
         files    [File]  p3.flac
         align    [Text]  none
         roomNo   [Text]  TEST-001
```

Swagger UI(`/docs`)의 "Try it out"으로도 바로 된다.

---

## 11. 에러 코드

### 11.1 요청 즉시 반환 (HTTP 응답)

```json
{ "error": { "code": "E4001", "message": "roomNo is required" } }
```

| 코드 | HTTP | 의미 | 조치 |
|---|:---:|---|---|
| `E4001` | 400 | 필수 필드 누락 | 요청 본문 확인 |
| `E4002` | 400 | `files`가 비어 있음 | 최소 1개 필요 |
| `E4003` | 400 | `files` 개수 초과 | 최대 5개 |
| `E4004` | 400 | `participantId` 중복 | 고유값으로 전달 |
| `E4005` | 400 | `align: "timestamp"`인데 `startedAt` 누락 | 전 파일에 포함 |
| `E4006` | 400 | `startedAt` 형식 오류 | ISO8601 (밀리초 포함) |
| `E4007` | 400 | `originalname`에 non-ASCII 포함 | `encodeURIComponent` 적용 |
| `E4040` | 404 | `jobId` 없음 (또는 24시간 경과) | 조회 대상 확인 |
| `E4090` | 409 | 동일 `roomNo` 작업이 이미 진행 중 | 완료 후 재요청 |
| `E4091` | 409 | 재작업 대상이 아직 진행 중 | 완료 후 재시도 |
| `E4092` | 409 | 업로드 경로 작업은 재작업 불가 | 파일을 다시 업로드 |
| `E5000` | 500 | 내부 오류 | 서버 로그 확인 |

### 11.2 처리 중 발생 (상태 조회 응답의 `error.code`)

| 코드 | 의미 | 조치 |
|---|---|---|
| `E4101` | 다운로드 실패 | URL·권한 확인 |
| `E4102` | presigned URL 만료 | 유효기간 늘려 재요청 |
| `E4103` | 오디오 디코딩 실패 (손상 파일) | 원본 확인 |
| `E4104` | 병합 실패 (ffmpeg 오류) | 서버 로그 확인 |
| `E4105` | 업로드 실패 | `putUrl`·서명 헤더 확인 |
| `E4106` | 작업 타임아웃 (30분 초과) | 파일 크기·서버 부하 확인 |
| `E5002` | 재시작 후 업로드 원본 파일 소실 | 파일을 다시 업로드 (테스트 경로 전용) |

---

## 12. 제약 사항

| 항목 | 값 | 환경변수 |
|---|---|---|
| 파일 개수 | 1 ~ 5개 | `MERGE_MAX_FILES` |
| 파일당 최대 크기 | 2GB | `MERGE_MAX_FILE_BYTES` |
| 업로드 테스트 경로 합계 | 512MB | `MERGE_UPLOAD_MAX_BYTES` |
| 지원 입력 포맷 | flac, wav, mp3, m4a, pcm(s16le 16kHz mono) | — |
| 출력 포맷 | flac (기본), wav | — |
| 동시 처리 | 3건 | `MERGE_WORKERS` |
| 작업 타임아웃 | 30분 | `MERGE_JOB_TIMEOUT_SEC` |
| 이상 offset 가드 | 60초 | `MERGE_MAX_OFFSET_MS` |
| 상태 메모리 캐시 | 24시간 | `MERGE_JOB_TTL_SEC` |
| **기록 보존** | **90일** | `MERGE_RECORD_TTL_DAYS` |
| presigned 유효기간 권장 | 6시간 이상 | — |

### "동시 처리 3건"의 의미

병합 서버가 **같은 시각에 실제로 병합을 돌리는 개수**다. 요청은 그보다 많이 보내도 된다.

4번째 요청도 `202`로 정상 접수되고 `WAITING` 상태로 대기하다가 앞 작업이 끝나면
순서대로 처리된다. **거절되지 않는다.**

### "작업 타임아웃 30분"의 의미

한 건이 `RUNNING`으로 들어간 뒤 30분 안에 못 끝내면 중단하고 `ERROR`(`E4106`)로 처리한다.
**큐 대기 시간은 포함되지 않는다.**

---

## 13. 기술 사양

| 항목 | 값 |
|---|---|
| 작업 포맷 | 16kHz / mono / 16bit |
| 병합 방식 | ffmpeg `amix` (겹치기, 합산) |
| 클리핑 방지 | `alimiter=limit=0.95` |
| 정렬 구현 | ffmpeg `adelay` (무음 삽입) |
| 결과 길이 | 가장 긴 트랙 기준 |

입력 파일별로 샘플레이트나 채널 수가 달라도 정규화 단계에서 흡수된다.
master-api가 생성하는 flac이 이미 16kHz mono이므로 대부분 변환 비용이 없다.

### 파일 암호화

**스토리지에 저장된 녹음 파일은 암호화되어 있지 않다.**
AES-256-CBC는 *모바일 앱 → master-api 전송 구간*에만 적용되고, 저장 시점엔 평문이다.
따라서 병합 서버는 AES 키 없이 받아서 바로 처리한다.

---

## 14. 네트워크 요구사항

`/v1/merge`는 **양방향 통신**이 필요하다.

```
① 병합서버 → MinIO      presigned URL 호스트가 내부 DNS 이름이므로
                        병합서버가 그 이름을 해석할 수 있어야 한다
② master-api → 병합서버  폴링으로 상태를 조회하므로 병합서버에 닿아야 한다
```

양쪽 모두 `timblo-net-package` 도커 네트워크에 속해야 한다.

| 항목 | 값 |
|---|---|
| 네트워크 | `timblo-net-package` (external) |
| 컨테이너명 | `aimm-recog-backend` |
| 포트 | 28080 (호스트) → 8080 (컨테이너) |

presigned URL 호스트는 **내부 DNS 이름**(`timblo-minio:9000` 등)으로 발급한다.

---

## 15. 연동 체크리스트

- [ ] presigned GET URL 발급 구현 (`presignedGetObject`)
- [ ] presigned PUT URL 발급 구현 — **`x-amz-meta-originalname`을 서명에 포함**
- [ ] `output.originalname`에 `encodeURIComponent` 적용한 값 전달
- [ ] presigned 유효기간 6시간 이상
- [ ] presigned URL 호스트를 내부 DNS 이름으로 발급
- [ ] `POST /v1/merge` 호출
- [ ] `GET /v1/merge/{jobId}` 폴링 — **`status` 필드로 판별** (HTTP 200이어도 실패일 수 있음)
- [ ] `DONE` 수신 후 `statObject`로 업로드 검증
- [ ] `contentModel.createContent()` + `recogService.addTask()` 연결
- [ ] `align` 모드 결정 (`none` / `timestamp`)
- [ ] 실패 시 `POST /v1/merge/{jobId}/retry` 사용 검토 (새 URL만 전달)

---

## 16. 확인 요청 사항

1. **`presignedGetObject` / `presignedPutObject` 사용 가능 여부**
   `@timbel-timblo-onpremise/minio-js`가 표준 minio-js 8.0.6 포크인 것은 확인했으나,
   포크에서 해당 메서드가 유지되는지는 확인하지 못했습니다.
   ```bash
   grep -rn "presigned" node_modules/@timbel-timblo-onpremise/minio-js/dist/ | head
   ```

2. **PUT 서명에 `x-amz-meta-originalname`을 넣는 방법** (5절 참조)

3. **`startedAt`을 밀리초 단위로 제공 가능한지**
   가능하면 `align: "timestamp"`, 어려우면 `align: "none"`으로 진행합니다.

4. **병합 서버 주소** — 컨테이너명·포트, 도커 네트워크명

5. **제약값이 실제 운영 규모에 맞는지** — 파일 5개 / 2GB / 동시 3건 / 30분

---

## 부록 · 결정 사항 요약

| 항목 | 결정 | 근거 |
|---|---|---|
| 스토리지 접근 | presigned URL만 | 병합 서버는 자격증명 미보유. 현재 Consul KV 한 곳에서만 관리되는 구조를 열지 않음 |
| 상태 전달 | 폴링 | HAIV 연동과 동일 패턴. 소켓·SSE는 얻는 것 대비 복잡도가 큼 |
| 콜백 | 미사용 | 폴링으로 충분. 필요해지면 스펙 변경 없이 추가 가능 |
| 기록 저장 | SQLite (`runtime/merge.db`) | 파이썬 표준 라이브러리라 의존성 0개 유지. 재시작 복구와 90일 이력을 한 파일로 |
| 재시작 시 진행중 작업 | 자동 재큐잉 | 요청 원본이 기록에 있고 presigned URL이 보통 아직 유효 |
| 인증 | 없음 (API) / Basic (문서) | 도커 네트워크 내부 통신. `/docs`만 브라우저로 여는 화면이라 보호 |
| 병합 방식 | 겹치기(mix) | 5명 1시간 → 결과 1시간 |
| 파일 암호화 | 없음 | 저장 시점엔 평문 |
| 정렬 | `none` 기본 / `timestamp` 선택 | 방장 트리거로 거의 동시 시작 |
| 출력 | 믹스 1개 | 화자분리는 master-api STT 엔진이 처리 |

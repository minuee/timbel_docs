# 음성 병합 서버 연동 가이드

> **대상**: master-api 개발 담당
> **버전**: v1 (2026-09-14)

---

## 1. 이 서버가 하는 일

회의 참가자들이 **각자 자기 휴대폰으로 녹음한 음성 파일 여러 개**를
**하나의 음성 파일로 합쳐주는 서버**

```
참가자 5명이 각자 녹음
   → master-api가 S3에 업로드 (기존 그대로)
   → ★ 병합 서버에 "이 파일들 합쳐줘" 요청     ← 이 문서가 다루는 부분
   → 병합 서버가 합쳐서 S3에 다시 업로드
   → master-api가 결과 받아서 STT 태우기 (기존 그대로)
```

병합 서버가 하는 건 **음성 합치기 하나뿐**.
STT 전사, 화자분리, 요약, DB 저장은 하지 않음. 기존 master-api 로직 그대로 사용.

---

## 2. 연동에 필요한 작업 3가지

| # | 할 일 | 난이도 |
|:---:|---|---|
| 1 | S3 presigned URL 발급 코드 추가 | 보통 (AWS SDK 필요) |
| 2 | 병합 요청 API 호출 | 쉬움 |
| 3 | 완료 콜백 수신 엔드포인트 1개 추가 | 쉬움 |

---

## 3. 먼저 알아야 할 것 — presigned URL

병합 서버는 **AWS 자격증명(액세스 키)을 보유하지 않음.** 의도적인 설계.
서버 하나가 뚫려도 S3 버킷 전체가 노출되지 않도록 하기 위함.

대신 **master-api가 "이 파일 하나만, 이 시간 동안만" 접근 가능한 URL을 만들어서 전달**하는 방식.
이것이 presigned URL.

```
master-api: "rec/R-001/p1.flac 파일을, 다운로드용으로, 앞으로 6시간만"
            ↓ AWS SDK로 서명 URL 생성
   https://bucket.s3.ap-northeast-2.amazonaws.com/rec/R-001/p1.flac
     ?X-Amz-Algorithm=AWS4-HMAC-SHA256
     &X-Amz-Expires=21600
     &X-Amz-Signature=3f7a2b...        ← 이 서명이 권한 증명

병합 서버: 이 URL로 GET 요청만 보내면 파일 수신. AWS 키 불필요.
```

**다운로드용(GET), 업로드용(PUT) 두 종류를 생성해서 전달.**

### 발급 코드

현재 master-api에 AWS SDK가 없으므로 패키지 추가 필요.

```bash
npm install @aws-sdk/client-s3 @aws-sdk/s3-request-presigner
```

```js
import { S3Client, GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

const s3 = new S3Client({ region: process.env.AWS_REGION });
const BUCKET = process.env.AWS_BUCKET_NAME;
const EXPIRES = 21600; // 6시간

// 다운로드용
export const presignGet = key =>
  getSignedUrl(s3, new GetObjectCommand({ Bucket: BUCKET, Key: key }), { expiresIn: EXPIRES });

// 업로드용
export const presignPut = key =>
  getSignedUrl(s3, new PutObjectCommand({ Bucket: BUCKET, Key: key }), { expiresIn: EXPIRES });
```

> ⚠️ **유효기간 6시간 이상 권장.**
> 파일이 크거나 앞선 작업이 밀려 있으면 처리 시작까지 시간이 걸림.
> 짧게 설정하면 작업 도중 URL이 만료되어 실패.

---

## 4. 병합 요청

### `POST {병합서버주소}/v1/merge`

```
Content-Type: application/json
Authorization: Bearer {MERGE_API_TOKEN}
```

### 요청 본문

```json
{
  "roomNo": "R-20260914-001",
  "files": [
    {
      "participantId": "p1",
      "getUrl": "https://bucket.s3.../p1.flac?X-Amz-Signature=...",
      "fileName": "p1.flac"
    },
    {
      "participantId": "p2",
      "getUrl": "https://bucket.s3.../p2.flac?X-Amz-Signature=...",
      "fileName": "p2.flac"
    }
  ],
  "output": {
    "putUrl": "https://bucket.s3.../merged/R-001/mix.flac?X-Amz-Signature=...",
    "format": "flac"
  },
  "callbackUrl": "https://master-api.internal/v1/internal/merge-callback"
}
```

### 필드 설명

| 필드 | 필수 | 설명 |
|---|:---:|---|
| `roomNo` | ✅ | 회의룸 번호. 로그 추적용이며 병합 로직에는 영향 없음 |
| `files` | ✅ | 합칠 파일 목록. **최소 1개, 최대 5개** |
| `files[].participantId` | ✅ | 참가자 구분값. 결과 리포트에서 파일을 식별하는 키 |
| `files[].getUrl` | ✅ | 다운로드용 presigned URL |
| `files[].fileName` | — | 원본 파일명. 로그 가독성 용도 |
| `output.putUrl` | ✅ | 결과물 업로드용 presigned URL |
| `output.format` | — | `flac`(기본) 또는 `wav` |
| `callbackUrl` | — | 완료 통보받을 주소. 없으면 상태 조회로만 확인 가능 |

### 응답 — `202 Accepted`

```json
{
  "jobId": "mrg_01J8XK2P9QWERTY",
  "roomNo": "R-20260914-001",
  "status": "WAITING",
  "fileCount": 5,
  "acceptedAt": "2026-09-14T10:00:00.000Z"
}
```

**응답은 즉시 반환.** 병합 완료가 아니라 "요청 접수" 상태.
실제 병합은 백그라운드에서 진행되고, 완료 시 콜백으로 통보.

> 1시간짜리 회의 5명 기준 병합에 3~5분 소요.
> HTTP 요청을 붙잡고 대기하면 타임아웃이 발생하므로 비동기 방식 채택.

### 호출 코드 예시

```js
const requestMerge = async (roomNo, participants, mergedKey) => {
  const files = await Promise.all(
    participants.map(async p => ({
      participantId: p.id,
      getUrl: await presignGet(p.fileKey),
      fileName: p.fileName,
    }))
  );

  const res = await fetch(`${process.env.MERGE_API_URL}/v1/merge`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.MERGE_API_TOKEN}`,
    },
    body: JSON.stringify({
      roomNo,
      files,
      output: { putUrl: await presignPut(mergedKey), format: 'flac' },
      callbackUrl: `${process.env.API_BASE_URL}/v1/internal/merge-callback`,
    }),
  });

  if (!res.ok) {
    const err = await res.json();
    log.e('[MergeService] 병합 요청 실패', err);
    throw new HttpError(1000, err.message);
  }

  const { jobId } = await res.json();
  log.i(`[MergeService] 병합 요청 접수 jobId=${jobId} roomNo=${roomNo}`);
  return jobId;
};
```

---

## 5. 완료 콜백

병합 완료 시 병합 서버가 `callbackUrl`로 `POST` 전송.
**이 엔드포인트는 master-api 쪽에서 구현 필요.**

### 성공 시 수신 내용

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
      { "participantId": "p1", "offsetMs": 0,     "confidence": 1.00 },
      { "participantId": "p2", "offsetMs": -1240, "confidence": 0.93 },
      { "participantId": "p3", "offsetMs": 820,   "confidence": 0.88 }
    ]
  },
  "timing": { "downloadMs": 18200, "processMs": 142300, "uploadMs": 9100, "totalMs": 169600 },
  "finishedAt": "2026-09-14T10:02:49.600Z"
}
```

| 필드 | 쓰임새 |
|---|---|
| `output.durationMs` | 콘텐츠 재생시간. `contentModel` 저장 시 사용 |
| `output.sizeBytes` | 파일 크기 |
| `alignment` | 참가자별 보정량(ms). **문제 발생 시 원인 파악용** |
| `timing` | 단계별 소요 시간. 성능 모니터링용 |

### 실패 시 수신 내용

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

### 콜백 처리 코드 예시

```js
// POST /v1/internal/merge-callback
async mergeCallback(req, res, next) {
  try {
    const { jobId, roomNo, status, output, error } = req.body;

    // ① 멱등 처리 — 같은 jobId가 두 번 올 수 있음
    if (await mergeJobModel.isProcessed(jobId)) {
      return base.sendSuccess(res, { ok: true });
    }

    if (status === 'ERROR') {
      log.e(`[mergeCallback] 병합 실패 jobId=${jobId} code=${error.code} ${error.message}`);
      await mergeJobModel.markFailed(jobId, error);
      return base.sendSuccess(res, { ok: true });   // ← 실패여도 2xx로 응답
    }

    // ② 성공 — 병합 파일은 이미 S3에 업로드된 상태
    await mergeJobModel.markDone(jobId, output);

    // ③ 기존 STT 경로에 연결
    //    await contentModel.createContent(...)
    //    await recogService.addTask(auth, params, user)

    base.sendSuccess(res, { ok: true });
  } catch (err) {
    next(err);
  }
}
```

### 콜백 주의사항

| 항목 | 내용 |
|---|---|
| **항상 `2xx` 응답** | `2xx`가 아니면 실패로 판단해 재시도. 실패 콜백 수신 시에도 `2xx`로 응답 |
| **중복 도착 가능** | 재시도 중 네트워크 문제로 동일 콜백이 중복 도착 가능. **`jobId` 기준 멱등 처리 필수** |
| **재시도 정책** | 최대 5회 (10초 → 30초 → 2분 → 5분 → 15분) |
| **최종 실패 시** | 콜백 전송에 끝내 실패하면 로그만 기록. 결과는 상태 조회 API로 확인 가능 |

---

## 6. 상태 조회 (보조 수단)

콜백이 주 경로이며, 이것은 확인용.

### `GET {병합서버주소}/v1/merge/{jobId}`

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

| `status` | 의미 |
|---|---|
| `WAITING` | 큐 대기 중 (앞 작업 완료 대기) |
| `RUNNING` | 처리 중 |
| `DONE` | 완료. S3 업로드까지 종료 |
| `ERROR` | 실패 |

`stage` 진행 순서: `DOWNLOADING` → `NORMALIZING` → `ALIGNING` → `MIXING` → `UPLOADING`

---

## 7. 제약 사항

| 항목 | 값 |
|---|---|
| 한 번에 합칠 수 있는 파일 | **최대 5개** |
| 파일당 최대 크기 | 2GB |
| 지원 입력 포맷 | flac, wav, mp3, m4a, pcm |
| 출력 포맷 | flac (기본), wav |
| 결과물 규격 | 16kHz / mono / 16bit |
| 동시 처리 | 3건 |
| 작업 타임아웃 | 30분 |

### "동시 처리 3건"의 의미

병합 서버가 **같은 시각에 실제로 처리하는 작업 개수**가 3건이라는 뜻.
요청은 그보다 많이 전송해도 무방. 4번째 요청도 정상적으로 `202`로 접수되고
`WAITING` 상태로 큐에서 대기하다가 앞 작업 완료 시 자동 처리. **거절되지 않음.**

### "작업 타임아웃 30분"의 의미

한 건이 `RUNNING`에 진입한 뒤 30분 내에 완료되지 않으면 중단하고 `ERROR` 처리.
큐 대기 시간은 포함되지 않음.

---

## 8. 에러 코드

### 요청 즉시 반환 (HTTP 응답)

| 코드 | HTTP | 의미 | 조치 |
|---|:---:|---|---|
| `E4001` | 400 | 필수 필드 누락 | 요청 본문 확인 |
| `E4002` | 400 | `files`가 비어 있음 | 최소 1개 필요 |
| `E4003` | 400 | 파일 개수 초과 | 최대 5개 |
| `E4004` | 400 | `participantId` 중복 | 고유값으로 전달 |
| `E4010` | 401 | 토큰 불일치 | `Authorization` 헤더 확인 |
| `E4040` | 404 | `jobId` 없음 | 조회 대상 확인 |
| `E4090` | 409 | 동일 `roomNo` 작업이 이미 진행 중 | 완료 후 재요청 |
| `E5000` | 500 | 내부 오류 | 병합 서버 쪽으로 전달 |

### 처리 중 발생 (콜백으로 전달)

| 코드 | 의미 | 조치 |
|---|---|---|
| `E4101` | S3 다운로드 실패 | URL·버킷 권한 확인 |
| `E4102` | **presigned URL 만료** | 유효기간 연장 후 재요청 |
| `E4103` | 오디오 디코딩 실패 (파일 손상) | 원본 파일 확인 |
| `E4104` | 병합 실패 | 병합 서버 쪽으로 전달 |
| `E4105` | S3 업로드 실패 | `putUrl`·버킷 권한 확인 |

---

## 9. 참고 사항

**파일을 순서대로 이어붙이는 것이 아님**
**같은 시간대에 겹쳐서** 합치는 방식. 회의 참가자들이 동시에 나눈 대화이기 때문.
순차 연결 시 "A가 1시간 말한 뒤 → B가 1시간 말하는" 형태가 됨.
결과물 길이는 가장 긴 파일 기준.

**콜백의 `alignment`**
참가자마다 녹음 시작 시각이 조금씩 다름. 그대로 겹치면 대화가 어긋나므로
병합 서버가 음성을 분석해 자동 보정. `offsetMs`가 그 보정값.

보정 근거를 찾지 못하면 (예: 참가자들이 각자 다른 장소에 있어 녹음에 공통된 소리가 없는 경우)
보정 없이 그대로 겹침. 이때 `confidence`가 낮게 출력됨.
**결과 품질 이슈 발생 시 이 값부터 확인.**

**화자분리 미지원**
병합 서버는 화자분리를 하지 않음. 기존대로 STT 엔진에서 처리.

**원본 파일은 삭제되지 않음**
병합 서버는 S3 파일을 **읽기만** 함. 서버 로컬에 받아둔 임시 파일만 작업 후 정리.

**파일 1개도 가능**
포맷 변환만 수행 후 업로드.

**재병합**
앞 작업 완료 후 새 `putUrl`로 재요청. 진행 중 동일 `roomNo`로 요청 시 `E4090` 반환.

---

## 10. 연동 체크리스트

- [ ] `@aws-sdk/client-s3`, `@aws-sdk/s3-request-presigner` 패키지 설치
- [ ] presigned URL 발급 함수 추가 (유효기간 **6시간 이상**)
- [ ] 환경변수 설정: `MERGE_API_URL`, `MERGE_API_TOKEN`
- [ ] 병합 요청 호출 코드 작성
- [ ] 콜백 수신 엔드포인트 `POST /v1/internal/merge-callback` 추가
- [ ] 콜백 **멱등 처리** (`jobId` 기준 중복 방지)
- [ ] 콜백은 성공·실패 관계없이 **`2xx` 응답**
- [ ] 콜백 이후 기존 STT 경로(`recogService.addTask`) 연결
- [ ] 병합 작업 상태 저장용 테이블/컬렉션 (`jobId`, `roomNo`, `status`)

---

## 11. 협의 사항

미확정 항목. 확인 후 회신 요청.

| # | 항목 | 비고 |
|:---:|---|---|
| 1 | 병합 서버 주소 및 네트워크 경로 | 내부망 / VPC 접근 가능 여부 |
| 2 | `MERGE_API_TOKEN` 값 결정 및 전달 방법 | |
| 3 | S3 버킷명, 리전, 결과물 저장 경로 규칙 | 예: `merged/{roomNo}/mix.flac` |
| 4 | 제약값이 실제 운영 규모에 적합한지 | 파일 5개 / 2GB / 동시 3건 / 30분 |
| 5 | 참가자들이 같은 공간에 모이는지, 각자 다른 장소인지 | 정렬 정확도 예측에 참고 |

---

*상세 기술 스펙은 `MERGE_API_SPEC.md` 참고*

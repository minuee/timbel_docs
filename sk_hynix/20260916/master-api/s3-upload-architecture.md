# master-api 오브젝트 스토리지(S3) 업로드 구조

> 작성 목적: 신규 서버에서 스토리지 접근 방식을 결정하기 위한 현행 구조 정리
> 기준 브랜치: `2-release` / 기준 파일: `src/utils/drive.util.js`

---

## 1. 결론

master-api는 **AWS S3 SDK를 쓰지 않습니다.** MinIO SDK 포크(`@timbel-timblo-onpremise/minio-js`)로 **S3 호환 API**를 호출하며, 기본 접속 대상은 온프렘 MinIO(`timblo-minio:9000`)입니다.

presigned URL은 **코드베이스 전체에서 사용처가 0건**입니다. 업로드·다운로드 모두 API 서버가 바이트를 직접 통과시킵니다.

---

## 2. 클라이언트 구성

`src/utils/drive.util.js:11-32`

```js
let MinioClient = null;

process.on('storageChanged', () => {
    // ... 기존 클라이언트 destroy/end 정리 ...
    MinioClient = new Client({
        endPoint: env.END_POINT || 'timblo-minio',
        port: env.END_POINT_PORT ? Number(env.END_POINT_PORT) : 9000,
        accessKey: env.ACCESS_KEY_ID,
        secretKey: env.SECRET_ACCESS_KEY,
        region: env.REGION || 'ap-northeast-2',
        useSSL: env.USE_SSL === 'true',
    });
});
```

### 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `END_POINT` | `timblo-minio` | 스토리지 호스트 |
| `END_POINT_PORT` | `9000` | 포트 |
| `ACCESS_KEY_ID` | — | 액세스 키 |
| `SECRET_ACCESS_KEY` | — | 시크릿 키 |
| `REGION` | `ap-northeast-2` | 리전 |
| `USE_SSL` | `false` (문자열 `'true'`일 때만 활성) | HTTPS 여부 |
| `BUCKET_NAME` | — | 미디어 원본 버킷 (비공개) |
| `PUB_BUCKET_NAME` | — | 썸네일 버킷 (public-read) |
| `IMAGE_END_POINT` | — | 썸네일 공개 URL 호스트 |

### 자격증명 공급 경로

```
Consul KV  timblo/common/credentials
    └─ watcherMinio.on('change')            configs/discovery-config.js:73
         └─ parseWatcherAndEmit(Value, 'storageChanged')
              ├─ process.env 에 키 덮어쓰기
              └─ process.emit('storageChanged')
                   └─ MinioClient 재생성      utils/drive.util.js:11
```

자격증명이 Consul에서 회전되면 런타임에 클라이언트가 교체됩니다. 재배포가 필요 없습니다.

> **주의:** `MinioClient`의 초기값은 `null`이며 생성 코드가 `storageChanged` 핸들러 안에만 있습니다. 부팅 시 Consul watch가 초기 `change` 이벤트를 한 번 발생시켜야 클라이언트가 만들어집니다. Consul 접속 실패 시 모든 스토리지 연산이 `Cannot read properties of null`로 실패합니다.

---

## 3. AWS S3로 전환 가능한가

가능합니다. MinIO SDK는 S3 호환 프로토콜(SigV4)을 쓰므로 `END_POINT=s3.ap-northeast-2.amazonaws.com`, `USE_SSL=true`, `END_POINT_PORT=443`으로 바꾸면 실제 AWS S3를 향합니다.

다만 코드 수정 없이 되지는 않습니다:

- **썸네일 공개 URL이 하드코딩된 조립식**입니다 — `` `https://${IMAGE_END_POINT}/${PUB_BUCKET_NAME}/${key}` `` (`drive.util.js:223`). AWS의 virtual-hosted 스타일(`{bucket}.s3.{region}.amazonaws.com/{key}`)과 형태가 다릅니다.
- `x-amz-acl: public-read` (`drive.util.js:214`)를 쓰는데, 최근 생성된 S3 버킷은 기본적으로 ACL이 비활성(Object Ownership = Bucket owner enforced)이라 이 요청이 거부됩니다.

---

## 4. 사용 중인 오브젝트 연산

| 연산 | 위치 | 대상 버킷 | 비고 |
|---|---|---|---|
| `putObject` | `drive.util.js:96` (`put`) | `BUCKET_NAME` | 미디어 원본 신규 업로드 |
| `putObject` | `drive.util.js:245` (`replaceObject`) | `BUCKET_NAME` | 기존 키 덮어쓰기 + 캐시 무효화 |
| `putObject` | `drive.util.js:216` (`putThumbnailObject`) | `PUB_BUCKET_NAME` | 썸네일, `public-read` |
| `statObject` | `drive.util.js:126` | `BUCKET_NAME` | 헤드 조회, Redis 캐시 |
| `getObject` | `drive.util.js:167` | `BUCKET_NAME` | 스트림 → tmp 파일 |
| `removeObject` | `drive.util.js:198` | `BUCKET_NAME` | 업로드 실패 롤백 / 생명주기 삭제 |

멀티파트 업로드(`uploadPart`/`composeObject`)는 직접 호출하지 않습니다. `putObject`에 버퍼를 통째로 넘깁니다.

---

## 5. 오브젝트 키 구조

```
{BUCKET_NAME}/{kms}/{fileKey}          ← 미디어 원본
{PUB_BUCKET_NAME}/{encryptECB(pid/thumbnail)}  ← 썸네일
```

- `kms` = `generate.keyFromString(salt)` — 사용자 salt에서 파생된 해시. 사용자별 격리 prefix 역할 (`handlers/authorize.handler.js:65`).
- `fileKey` = `generate.fileKey()` — 서버가 발급하는 랜덤 키.

**키 발급 권한은 전적으로 master-api에 있습니다.** 클라이언트가 경로를 정하는 구조가 아닙니다.

---

## 6. 오브젝트 메타데이터 계약

`createPutParams()` (`drive.util.js:42-50`)

```js
{
    'Content-Type': mimetype,
    'Content-Length': size,
    originalname: encodeURIComponent(originalname),
}
```

`originalname`은 **다운로드 시 파일명을 결정하는 필수 값**입니다. `utils/file/stream.util.js:23`에서 `metaData['originalname']`을 읽어 `Content-Disposition` 헤더를 만듭니다. 이 메타데이터 없이 올라간 오브젝트는 다운로드 파일명이 깨집니다.

---

## 7. 업로드 전체 경로

### 7.1 일반 업로드

```
POST /content/upload
  └─ multer.uploadFileWithTimeout()        memoryStorage, 상한 2GB, 타임아웃 3h
       └─ contentController.uploadContent
            └─ driveService.uploadContent          services/system/drive.service.js:70
                 ├─ drive.put(file)                 → putObject (전체 버퍼)
                 ├─ media.parseMediaFile()          duration 추출
                 ├─ contentModel.createContent()
                 ├─ contentModel.createFileContent()
                 ├─ drive.fastLoadFile()            head 캐시 + tmp 캐시 워밍
                 └─ recogService.addTask()          STT 큐 투입
```

실패 시 `removeObject` + DB 레코드 삭제로 롤백합니다 (`drive.service.js:130-132`). `put()` 자체가 실패하면 버퍼를 로컬 `./failedUploadFile/`에 백업합니다 (`drive.util.js:64`).

### 7.2 모바일 암호화 조각 업로드

```
POST /content/upload/encryption[/files]
  └─ driveService.uploadEncryptionContent        drive.service.js:196
       ├─ media.parsePcmFile()        조각을 pcmDir에 파일로 저장
       ├─ (end !== true) → return, 조각 계속 수집
       ├─ checkFileList()             누락 조각 번호 검사
       ├─ secure.decryptFilesAesCbc() AES-256-CBC 복호화 + append 병합 → 단일 .pcm
       ├─ convert.convertPcmToFlac()  flac 인코딩
       └─ uploadContent()             → 7.1 경로로 합류, putObject 1회
```

조각은 스토리지가 아니라 **컨테이너 로컬 디스크**(`/usr/src/app/tmp`, docker volume)에 쌓였다가 병합 후 한 번에 올라갑니다. 즉 S3 멀티파트가 아니라 애플리케이션 레벨 병합입니다.

---

## 8. 현재 방식의 비용

| 항목 | 값 | 출처 |
|---|---|---|
| 파일 버퍼링 | 힙 메모리 전체 적재 | `multer.util.js:94-98` (memoryStorage) |
| 파일 크기 상한 | 2GB | `multer.util.js:96` |
| 업로드 타임아웃 | 3시간 (`UPLOAD_TIMEOUT`) | `multer.util.js:5` |
| 다운로드 | `getObject` → tmp 파일 → Range 스트림 | `drive.util.js:167`, `stream.util.js` |

업로드 바이트와 다운로드 바이트가 모두 API 서버를 통과합니다. 동시 업로드가 늘면 메모리가 선형으로 증가합니다.

---

## 9. 신규 서버가 presigned URL 방식으로 갈 때의 제약

presigned를 쓰더라도 아래 세 가지는 현행 구조와 반드시 정합을 맞춰야 합니다.

1. **키는 master-api가 발급해야 합니다.**
   경로가 `{kms}/{fileKey}`이고 `kms`는 사용자 salt 파생값입니다. 업로더가 경로를 정하면 사용자별 격리가 무너집니다. presigned 발급 응답에 경로를 확정해서 내려주는 형태여야 합니다.

2. **`originalname` 메타데이터를 서명에 포함해야 합니다.**
   6절 참조. presigned PUT 시 업로더가 이 헤더를 함께 전송해야 하고, 서명 대상 헤더에도 포함돼야 합니다. 누락되면 다운로드 파일명이 깨집니다.

3. **업로드 완료 통지 API가 필요합니다.**
   현재 `put()` 직후에 DB 기록(`createFileContent`), 캐시 워밍(`fastLoadFile`), STT 큐 투입(`recogService.addTask`), 실패 롤백(`removeObject`)이 하나의 흐름으로 묶여 있습니다. presigned는 이 연결을 끊으므로, 완료 콜백에서 `statObject`로 실제 존재·크기를 검증한 뒤 동일한 후속 처리를 이어가는 엔드포인트가 있어야 합니다.

추가로, 신규 서버가 스토리지에 직접 쓰는 방식을 택하면 MinIO 자격증명 배포 범위가 넓어집니다. 현재 자격증명은 Consul KV `timblo/common/credentials` 한 곳에서만 관리됩니다.

---

## 10. 미확인 사항

- 이 리포지토리에 `node_modules`가 설치돼 있지 않아 `@timbel-timblo-onpremise/minio-js`의 **presigned 관련 메서드 지원 여부를 직접 확인하지 못했습니다.** 표준 minio-js는 `presignedPutObject` / `presignedGetObject`를 제공하지만, 이 포크에서 유지되는지는 `npm install` 후 확인이 필요합니다.
- 실제 배포 환경의 `END_POINT` 값(온프렘 MinIO인지 AWS S3인지)은 Consul KV에 있어 코드만으로는 확정할 수 없습니다. 기본값 기준으로는 온프렘 MinIO입니다.

10절 항목은 아래 11절 명령어로 확인할 수 있습니다.

---

## 11. 확인 명령어

모두 도커 네트워크(`aimm-net` 등) 내부에서 실행하는 것을 전제로 합니다. 호스트에서 바로 실행할 경우 `consul-discovery` / `timblo-minio` 별칭 대신 실제 IP:포트로 바꿔야 합니다.

### 11.1 스토리지 자격증명 KV 실값

`storageChanged`를 발생시키는 KV의 실제 키 이름과 값을 확인합니다.

```bash
curl -s http://consul-discovery:8500/v1/kv/timblo/common/credentials \
  | jq -r '.[0].Value' | base64 -d
```

`ACCESS_KEY_ID` / `SECRET_ACCESS_KEY` / `END_POINT` / `BUCKET_NAME` 등이 이 JSON 안에 들어 있는지 확인합니다 (2절 환경변수 표 대조). Consul ACL 토큰은 코드상 사용처가 없으므로 토큰 없이 조회됩니다.

### 11.2 배포 환경의 실제 스토리지 엔드포인트

컨테이너에 주입된 최종 값을 확인합니다. Consul watch로 런타임에 덮어써지므로 KV와 다를 수 있습니다.

```bash
docker exec <master-api 컨테이너> printenv \
  | grep -E 'END_POINT|BUCKET_NAME|USE_SSL|REGION'
```

`END_POINT`가 `timblo-minio` 계열이면 온프렘 MinIO, `*.amazonaws.com`이면 실제 AWS S3입니다 (3절 참조).

### 11.3 배포용 KV (참고)

`deploy-env-fetch.sh`가 `.env` 생성에 쓰는 별도 키입니다. 스토리지 자격증명과는 다른 KV입니다.

```bash
curl -s http://localhost:38500/v1/kv/timblo/master/deploy \
  | jq -r '.[0].Value' | base64 -d
```

### 11.4 SDK의 presigned 메서드 지원 여부

10절 첫 번째 항목 확인용입니다. `node_modules` 설치 후 실행합니다.

```bash
npm install
grep -rn "presigned" node_modules/@timbel-timblo-onpremise/minio-js/dist/ | head
```

`presignedPutObject` / `presignedGetObject`가 잡히면 9절의 presigned 방식을 이 SDK만으로 구현할 수 있습니다.

> **주의:** 11.1 / 11.3 출력에는 평문 자격증명이 포함됩니다. 터미널 로그나 이슈 트래커에 그대로 붙여넣지 마십시오.

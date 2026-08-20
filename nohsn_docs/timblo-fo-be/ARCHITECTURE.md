# master-api 아키텍처 · 플로우 분석

> 작성일: 2026-08-14 · 기준 커밋: `3d141cc6` (release)
> 코드를 직접 읽고 작성했다. 파일·라인 참조는 위 커밋 기준이다.
> 로컬 구동 방법은 [LOCAL_SETUP.md](./LOCAL_SETUP.md) 참조.

---

## 1. 이 서비스의 위치

master-api 는 Timblo 온프레미스 제품군의 **핵심 도메인 서비스**다.
회의·음성 콘텐츠의 업로드부터 STT(음성인식), AI 요약, 노트·공유·검색까지를 담당한다.

주변 서비스와의 관계:

```
                    ┌──────────────┐
                    │   Consul     │  설정 KV + 서비스 레지스트리
                    └──────┬───────┘
                           │ 등록 / 설정 조회 / watch
   ┌───────────────────────┼───────────────────────┐
   │                       │                       │
┌──┴────────┐      ┌───────┴────────┐      ┌───────┴────────┐
│ auth-api  │◀─────│  master-api    │─────▶│ notification   │
│  (인증)   │ 인증  │   (이 서비스)   │ Kafka │   -api (알림)  │
└───────────┘ 검증  └───┬────────┬───┘      └────────────────┘
                        │        │
                        │        └──Kafka──▶ ┌──────────────┐
                        │                     │ datasync-api │
                        │                     └──────────────┘
        ┌───────────────┼───────────────┬──────────────┐
        │               │               │              │
   ┌────┴────┐    ┌─────┴────┐    ┌─────┴───┐   ┌──────┴─────┐
   │ MariaDB │    │ MongoDB  │    │  Redis  │   │   MinIO    │
   │ (관계)  │    │(전사결과)│    │ (큐)    │   │  (파일)    │
   └─────────┘    └──────────┘    └─────────┘   └────────────┘
                        │
              ┌─────────┴──────────┐
              │  ASR / LLM 엔진    │  HAIV · Naver Clova · OpenAI 호환 · SKAX
              └────────────────────┘
```

### DB 를 두 개 쓰는 이유

| DB | 담는 것 | 모델 수 |
|---|---|---|
| **MariaDB** | 관계형 데이터 — 사용자, 워크스페이스, 콘텐츠 메타, 공유, 정책, 사용량 | 58 |
| **MongoDB** | 비정형·대용량 — **전사 결과(segments)**, 노트, 메모, 하이라이트, 템플릿 | 12 |

전사 결과는 세그먼트 배열이 수천 개까지 늘어나는 문서형 데이터라 MongoDB 에 둔다.
`TranscribeResult.segments` / `mergedSegments` / `speakerInfo` / `aiResult(Json)` 이 그것이다.

> ⚠️ Prisma 의 MongoDB 커넥터는 **replica set** 을 요구한다. 로컬 단독 mongod 로는 붙지 않는다.

---

## 2. 계층 구조

```
routes/       URL → 컨트롤러 매핑. 미들웨어(multer 등) 부착
   ↓
controller/   요청 파싱 · 검증 · 응답 조립. 비즈니스 로직 없음
   ↓
services/     비즈니스 로직. 트랜잭션 경계
   ↓
models/       Prisma 접근. BaseDatabase 상속
   ↓
MariaDB / MongoDB
```

가로지르는 관심사:

```
handlers/     미들웨어 (인증 · 인가 · 에러 · 라이프사이클 · 스트림 grant)
utils/        공통 유틸 (큐 · 드라이브 · 알림 · 전사 · 요약 · 변환 …)
configs/      Consul 디스커버리 · Swagger · i18n
```

### 배럴(barrel) 파일 주의

`src/utils/index.js` 와 `src/services/index.js` 가 전체를 재수출한다.
편리하지만 **순환 참조 위험**이 있어, 실제로 회피 코드가 존재한다:

```js
// src/services/contentCapture.service.js:9
import notify from '../utils/notify.util.js'; // ★반드시 직접 경로 — utils/index.js 경유 금지(순환)
```

새 모듈 추가 시 배럴 경유가 순환을 만들지 않는지 확인할 것.

### 데이터 접근 계층 — Prisma 래퍼

`@timbel-timblo-onpremise/prisma` 는 **일반적인 Prisma 사용법과 다르다.** 처음 보면 반드시 헷갈리는 부분이라 따로 정리한다.

#### 일반 Prisma 프로젝트와의 차이

보통은 내 리포에 스키마를 두고 클라이언트를 생성한다. 이 리포에는 **그게 전부 없다.**

| 항목 | 일반 Prisma | 이 프로젝트 |
|---|---|---|
| `prisma/schema.prisma` | 내 리포에 작성 | ❌ 없음 |
| `prisma generate` | 내가 실행 | ❌ 스크립트 없음 |
| `prisma` · `@prisma/client` 의존성 | 직접 선언 | ❌ 없음 (전이 의존성으로만 존재) |
| 스키마 수정 | 내가 직접 | ❌ **불가** — 별도 리포 소관 |

대신 **스키마 · 생성된 클라이언트 · 쿼리 엔진 바이너리가 통째로 npm 패키지 안에 들어 있다.**

```
node_modules/@timbel-timblo-onpremise/prisma/
└── dist/
    ├── index.esm.js                      BaseDatabase 클래스
    └── libs/prismaService/
        ├── mariaDB/
        │   ├── schema.prisma             ← 스키마 원본 (모델 58개)
        │   ├── index.js                  ← 생성된 PrismaClient
        │   └── libquery_engine-*.node    ← 쿼리 엔진
        └── mongoDB/
            ├── schema.prisma             ← 스키마 원본 (모델 12개)
            ├── index.js
            └── libquery_engine-*.node
```

즉 **다른 리포에서 `prisma generate` 를 미리 돌려 완제품을 배포**하고, 이 리포는 받아 쓰기만 한다.

> `package.json` 에서 이 패키지만 `"1.3.1"` 로 **정확히 고정**돼 있다 (`^` 없음).
> 나머지 사내 패키지 3종은 `^` 범위인 것과 대조적이다 — 스키마 불일치가 곧 런타임 장애라서다.

> 🔗 로컬에서 겪는 "darwin-arm64 엔진 없음" 문제의 근원이 이 구조다.
> 생성 시점이 리눅스 빌드머신이라 macOS 엔진이 패키지에 없다. → [LOCAL_SETUP.md 4-3](./LOCAL_SETUP.md)

#### 왜 감쌌나 — DB 두 개를 하나의 진입점으로

Prisma 는 보통 스키마 하나 = DB 하나다. 이 시스템은 MariaDB 와 MongoDB 를 **동시에** 쓰므로 클라이언트가 두 벌 필요하다. 그 둘을 한 클래스로 묶은 것이 `BaseDatabase` 다.

```js
// dist/index.esm.js:85
class BaseDatabase {
    constructor(className) {
        this.className = className ?? 'unknown';
        this.mariaDB = new PrismaClient({ log: prismaLogConfig, transactionOptions });
        this.mongoDB = new PrismaClient$1({ log: prismaLogConfig, transactionOptions });

        if (process.env.NODE_ENV === 'development') {
            this.queryEventHandler();   // [mariaDB : UserModel : 12ms] : SELECT ...
            this.errorEventHandler();
        }
    }
    Enums = Enums;    // 두 DB 의 enum 을 합쳐 노출
}
```

모델은 이걸 상속해서 쓴다. **쿼리 문법은 표준 Prisma 그대로**이고, 앞에 DB 선택자만 붙는다.

```js
// src/models/bookmark.model.js
class BookmarkModel extends BaseDatabase {
    constructor() { super('BookmarkModel'); }   // ← className 은 로깅 라벨용

    async findItemId(...) {
        return await this.mongoDB.transcribeResult.findFirst({ where });
        //           ^^^^^^^^^^^^ 여기서 DB 선택
    }
}
export default new BookmarkModel();   // 싱글턴
```

Enum 도 이 패키지가 제공한다:

```js
import { Enums } from '@timbel-timblo-onpremise/prisma';
Enums.YesNo.YES        // MariaDB
Enums.MongoYesNo.YES   // MongoDB
```

#### 스키마를 읽어야 할 때

리포에 없으므로 `node_modules` 를 직접 본다.

```bash
B=node_modules/@timbel-timblo-onpremise/prisma/dist/libs/prismaService
$EDITOR $B/mariaDB/schema.prisma    # 모델 58개
$EDITOR $B/mongoDB/schema.prisma    # 모델 12개
```

#### 스키마 변경이 배포되는 경로

패키지에 마이그레이션 도구(`dist/db-migrate/`)가 동봉돼 있는데, **diff 생성만 하고 적용하지 않는다.**

```
prisma 패키지 리포에서 스키마 수정
        ↓  npm run package  (generate → build)
   새 버전 배포 (GitLab 레지스트리)
        ↓  이 리포의 package.json 버전 올림
   db-migrate 컨테이너 1회 실행 → *-prisma-diff.sql 생성
        ↓  ★개발자가 검토하고 필요한 DDL 만 직접 적용
   DB 반영
```

자동 마이그레이션이 아니라 **사람이 검토하는 절차**다.
실행 방법과 환경변수는 [LOCAL_SETUP.md 10장](./LOCAL_SETUP.md) 참조.

#### ⚠️ 확인 필요 — PrismaClient 인스턴스 수

`BaseDatabase` 는 **constructor 에서** PrismaClient 를 새로 만든다.
그런데 이를 상속한 모델이 28개이고, 전부 싱글턴으로 인스턴스화된다.

```
28개 모델 × 2 (mariaDB + mongoDB) = 56개 PrismaClient 인스턴스 / 프로세스
PM2 인스턴스 3개면                 = 168개
```

Prisma 는 클라이언트마다 **독립 커넥션 풀**을 가지므로, 일반적으로는 클라이언트 하나를 공유하는 것이 권장 패턴이다.

다만 단정할 근거는 아직 없다:

- Prisma 커넥션은 **지연 생성**이라, 실제로 쿼리를 던지지 않는 모델은 커넥션을 잡지 않는다
- 개발/운영에서 문제없이 돌고 있다면 실질 영향이 없을 수 있다

**미검증 항목이다.** 개발서버 연결 후 실측할 것:

```sql
-- MariaDB
SHOW STATUS LIKE 'Threads_connected';
SHOW VARIABLES LIKE 'max_connections';
```

```js
// MongoDB
db.serverStatus().connections
```

실측치가 `max_connections` 에 근접하면 그때 공유 클라이언트 패턴을 검토한다.
(이 변경은 `BaseDatabase` 소관이므로 **이 리포가 아니라 prisma 패키지 리포**를 고쳐야 한다.)

---

## 3. 미들웨어 체인

`src/app.js` 기준. **순서가 곧 보안 경계**다.

```
요청
  │
  ├─ /api-docs  ─────────────────────────▶ Swagger UI      (인증 없음)
  ├─ /health    ─────────────────────────▶ Consul 헬스체크  (인증 없음)
  │
  ├─ telemetry.traceMiddleware()            분산 트레이싱
  ├─ express.json / urlencoded              limit: 1gb
  ├─ cookieParser
  ├─ morganMiddleware
  ├─ cors({ origin: true, credentials: true })
  │
  ├─ ① streamGrantHandler                   스트리밍 신원 격리
  ├─ ② authenticateRequest                  인증 — 누구인가
  ├─ ③ authorizeMember                      인가 — 멤버·워크스페이스 로드
  │
  ├─ 라우터 10종
  │    /home /user /search /contents /inbox
  │    /bookmark /integrate /queue /notice /chat
  │
  └─ ErrorHandler.exception
```

> `/api-docs` 와 `/health` 가 인증 체인 **앞**에 있다.
> 그래서 DB·인증서버 없이도 이 둘은 동작한다 (로컬 분석에 유용).

---

## 4. 인증 · 인가 플로우

### 4-1. 인증 — 두 갈래

`src/handlers/authenticate.handler.js`

```
authenticateRequest
  │
  ├─ isExternalApiRequest(req) ?
  │    헤더에 x-timblo-auth + authorization 둘 다 있는가
  │    x-timblo-auth === ENCRYPT_SECRET_KEY 검증 (틀리면 401)
  │
  ├── YES ──▶ withExternalApi()          [서버 간 호출 레인]
  │             │
  │             ├─ empno + companyCode  → 사번으로 사용자 조회
  │             │    없으면 AUTH_API_URL/auth/sso/external 로 가입 시도
  │             ├─ email               → 이메일로 조회
  │             ├─ rec_system_*@adotbiz.ai → 채용 계정 자동 생성
  │             │    (AUTH_API_URL/auth/interview/signup)
  │             │
  │             ├─ req.user = { ...user.profile, config.external }
  │             ├─ req.token = null
  │             └─ req.isExternalApiRequest = true   ← 임퍼소네이션 표식
  │
  └── NO ───▶ withTimbloToken()          [일반 사용자 레인]
                │
                ├─ x-timblo-token 헤더에서 JWT 추출
                │    (NODE_ENV=development 면 authorization / query.accessToken 도 허용)
                ├─ jwt.decode()  ← ※ verify 가 아니라 decode
                ├─ payload 에 pid 없으면 401
                └─ req.user = decoded, req.token = token
```

> **주목**: 일반 레인은 `jwt.decode()` 만 하고 **서명 검증(`jwt.verify`)을 하지 않는다.**
> 게이트웨이가 앞단에서 검증하는 구조를 전제한 것으로 보인다.
> master-api 를 게이트웨이 없이 직접 노출하면 안 된다는 뜻이다.

### 4-2. 인가

`src/handlers/authorize.handler.js`

```
authorizeMember
  │
  ├─ verifyTemporaryAccess(req)  게스트 임시접근 확인
  │    Redis `accessTokens:<token>` 조회 → isCert && isGuest 면 통과
  │    ★ req.streamGrant 가 있으면 이 게이트를 스코프 한정 우회
  │
  ├─ memberModel.findMemberByPID(user.pid)
  │    업로드 경로면 workspace.config.asrEndpoint 까지 함께 로드
  │
  ├─ resolveAsrEngine()  워크스페이스 ASR 엔진 해석 → transcribeEngine 별칭 주입
  │
  └─ req.auth = {
        member,                          멤버 + 워크스페이스
        isAuthorized: true,
        config: { ...user.config, isMobile },
        sso: user.sso ?? null,           SSO 진입 컨텍스트
        kms: generate.keyFromString(`${member.id}${member.workspace.id}`)
     }                                   └─ MinIO 파일 경로 암호화 키
```

`auth.kms` 가 이후 **모든 파일 경로의 네임스페이스**가 된다 (`${auth.kms}/${fileKey}`).

### 4-3. 스트리밍 신원 격리 (streamGrant)

이 코드베이스에서 가장 미묘한 부분이라 따로 다룬다.

**문제**: `<audio src="...">` 나 파일 다운로드는 **커스텀 헤더를 실을 수 없다.**
그래서 게이트웨이가 브라우저 세션 토큰을 `x-timblo-token` 으로 주입해 준다.
그런데 한 브라우저에서 여러 계정으로 로그인해 두면, **그 세션 신원이 "지금 이 탭의 계정"이 아닐 수 있다.**

**해결**: 콘텐츠별 grant 쿠키

```
① 클라이언트가 재생/다운로드 전에 호출
   POST /contents/:contentId/stream-grant
        → 현재 탭 계정으로 서명한 grant 발급
        → 쿠키 streamGrant_<contentId> 로 저장

② 이후 다운로드 요청
   GET /contents/download/:contentId
        │
        ├─ streamGrantHandler (authenticate 보다 앞!)
        │    · 경로가 /contents/download 로 시작하는가
        │    · x-timblo-auth 헤더가 없는가 (서버 간 레인은 손대지 않음)
        │    · streamGrant_<contentId> 쿠키 서명·만료·contentId·purpose 검증
        │    → 통과 시 req.headers['x-timblo-token'] = grant  (덮어쓰기)
        │              req.streamGrant = verified
        │
        └─ authenticate 가 grant 의 pid 를 읽어 "그 탭의 계정" 으로 인증
```

**왜 authenticate 앞이어야 하는가**: 하류 authenticate 가 *대체된* 토큰을 읽어야 하기 때문.
뒤에 두면 이미 세션 신원으로 인증이 끝나 버린다 (`src/app.js:60-62` 주석).

**왜 authorize 에 별도 우회가 필요한가**: grant 는 Redis `accessTokens` 에 등록된 토큰이 아니다.
그래서 임시접근 게이트가 "미등록 토큰"으로 보고 401 을 낸다.
`req.streamGrant` 플래그가 있을 때만 예외 처리한다 — 게이트 자체를 완화하면
유출된 grant 가 다운로드 외 전 API 를 타게 되므로 절대 안 된다 (`authorize.handler.js:30-36` 주석).

grant 서명 키는 `STREAM_GRANT_SECRET`, 없으면 `ENCRYPT_SECRET_KEY` 로 폴백한다.

---

## 5. 핵심 플로우 — 콘텐츠 업로드 → STT → 요약

이 서비스의 **심장**이다. 비동기 2단 큐 구조다.

### 5-1. 전체 그림

```
[HTTP 요청]                    [recog 큐]              [llm 큐]
     │                             │                      │
POST /contents/upload              │                      │
     │                             │                      │
     ├─ multer 파일 수신            │                      │
     ├─ wav → flac 변환             │                      │
     ├─ MinIO 업로드                │                      │
     ├─ 미디어 파싱(duration)       │                      │
     ├─ Content · File 행 생성      │                      │
     ├─ TranscribeResult 생성       │                      │
     ├─ recog 큐에 잡 등록 ─────────▶│                      │
     │                             │                      │
     └─ 즉시 응답 (WAITING)         │                      │
        └ 사용자는 기다리지 않음      │                      │
                                   │                      │
                          recogWorker 실행                 │
                                   ├─ MinIO 파일 확보       │
                                   ├─ ASR 엔진 호출         │
                                   │   (진행률 WS 푸시)     │
                                   ├─ 코퍼스 치환           │
                                   ├─ mergedSegments 생성   │
                                   ├─ 수기 메모 적용        │
                                   ├─ llm 큐 등록 ─────────▶│
                                   │   (delay 3초)         │
                                   └─ STT_DONE 저장         │
                                                           │
                                                  llmWorker 실행
                                                           ├─ LLM 엔드포인트 해석
                                                           ├─ 요약 생성
                                                           ├─ 노트 생성
                                                           ├─ SUMMARY_DONE
                                                           ├─ 사용량 기록
                                                           ├─ 완료 메일
                                                           ├─ DONE
                                                           └─ 알림함 캡처
```

### 5-2. 1단계 — 업로드 (동기)

`content.controller.js:23` → `drive.service.js:42`

```
uploadContent(req)
  ├─ 파일 없으면 1000 에러
  ├─ authHandler.isMember(auth)
  ├─ lang === 'none' 이면 사용자 기본 언어로
  ├─ auth.config.transcribeLang / summarySize 세팅
  ├─ .wav 면 flac 로 압축 변환         convert.replaceFileWithFlac
  ├─ 파일명 인코딩 정규화
  └─ driveService.uploadContent(file, auth, user, manualOptions)
       │
       ├─ demo.getDemoContent()          데모 계정 분기
       ├─ new drive(auth).put(file)      MinIO 업로드
       ├─ media.parseMediaFile()         ffprobe 로 duration 추출
       ├─ generate.meetingTime()         파일명에서 회의시각 추론
       ├─ contentModel.createContent()   MariaDB Content
       ├─ contentModel.createFileContent()  MongoDB File
       │
       ├─ duration === 0 이면 throw      ← 오디오 아님
       │
       └─ 분기:
            demoContent 있음      → demo.addTask()
            flac + IS_FLAC_NORMALIZE → normalizeService.addTask()   음량 정규화 선행
            그 외                  → recogService.addTask()
```

**롤백 처리**가 눈여겨볼 만하다 (`drive.service.js:104-116`):

```
실패 시
  ├─ tmpRollbackData 있음 (File 행까지 생성됨)
  │    → MinIO 오브젝트 삭제 + File 행 삭제
  └─ content 만 있음
       → Content 를 ERROR 상태로 + MONGO 실패 캡처 + WS 에러 푸시
```

### 5-3. 2단계 — recog 큐 접수

`recog.service.js:157 addTask`

```
addTask(auth, params, user)
  ├─ getRecogTaskQueue(transcribeEngine)   엔진별 큐 인스턴스 (tag 단위)
  ├─ ticketId 발급
  ├─ 같은 fileId 잡이 이미 돌면 → 1105 거부
  ├─ transcribeResultModel.create()        MongoDB TranscribeResult
  ├─ datasync.onCreate()                   SSO 있으면 원문 캡처 (비차단)
  ├─ recogTaskQueue.addTask(taskParams)
  └─ notify.sttStatus WAITING 푸시
```

#### 엔진별 큐 + 인스턴스 간 채널 배분

PM2 가 프로세스를 N개 띄우므로, **ASR 채널을 인스턴스끼리 나눠 가져야** 엔진이 과부하되지 않는다.

```js
// recog.service.js:137
const getAssignedChannelCount = maxQueue => {
    const totalInstances = Number(process.env.RECOG_WORKER ?? 3);
    const instanceId     = Number(process.env.INSTANCE_ID ?? 0);
    const baseChannels   = Math.floor(maxQueue / totalInstances);
    const extraChannels  = maxQueue % totalInstances;
    return baseChannels + (instanceId < extraChannels ? 1 : 0);
};
```

엔진 채널 10개 · 인스턴스 3개면 → `4, 3, 3` 으로 배분된다.

### 5-4. 3단계 — recogWorker (STT)

`recog.service.js:42`

```
recogWorker(task)
  │
  ├─ checkRecogFilePath()
  │    로컬 tmp 에 있으면 그대로, 없으면 MinIO 에서 재로드
  │
  ├─ new TranscribeUtil(task, auth)
  │    ├─ duration > MAX_DURATION 이면 ERROR 전이 후 throw
  │    └─ RUNNING 전이
  │
  ├─ manager.runner(filePath)              ← ASR 엔진 호출
  │    provider 로 분기: NAVER / HAIV / OPENAI_COMPAT
  │    콜백으로 진행률을 WS 푸시
  │
  ├─ segments 0개면 QueueError(1104)
  ├─ corpusService 로 사용자 사전 치환
  ├─ convert.createMergedSegments()        화자별 발화 병합
  ├─ applyManualMemosFromUpload()          업로드 시 첨부한 수기 메모 매핑
  │
  ├─ llmTaskQueue.addTask(taskParams, 3000)   ★ delay 3초
  │    실패하면 QueueError(1127)
  │
  ├─ manager.transUpdater({ status: 'STT_DONE' })
  │
  └─ ★ 포인트 오브 노 리턴 이후 (실패해도 ERROR 로 안 만듦)
       ├─ 재전사면 파생물 정리 (하이라이트·북마크·메모)
       ├─ usageModel.addUsage(TRANSCRIBE, duration)
       └─ 임시 파일 정리
```

#### ⚠️ delay 3초의 이유 — 실제 레이스 버그의 흔적

```js
// recog.service.js:86-88
// delay 3s: 아래 STT_DONE 저장(실측 0.36s+, 콘텐츠 클수록 김)이 요약 워커의 전사문 콜백보다
// 먼저 끝나도록 여유를 둔다. 기본 300ms 로는 2h 콘텐츠에서 60ms 차로 져서 1114 레이스 실증(2026-08-04)
```

요약 워커가 STT_DONE 저장보다 먼저 전사문을 읽으려 해서 실패하던 버그를 지연으로 막았다.
**이 값을 줄이면 대용량 콘텐츠에서 1114 에러가 재발한다.**

#### 포인트 오브 노 리턴

STT_DONE 이후의 부수 작업(사용량 기록·임시파일 정리 등) 실패는 잡을 ERROR 로 만들지 않는다.
이미 요약이 진행 중이라, ERROR 로 만들면 곧 DONE 이 덮어써서 **화면에 "변환실패"가 잠깐 떴다 사라지는** 혼란만 생긴다 (`recog.service.js:94-95`).

### 5-5. 4단계 — llmWorker (요약)

`llm.service.js:69`

```
llmWorker(task)
  ├─ manager.notify('LLM-RUNNING')
  ├─ 재요약이면 RE_SUMMARY_RUNNING 전이
  │
  ├─ summarize(params)                     ← 요약 엔진 디스패치
  │    resolveLlmEndpoint(workspaceId) 로 provider 결정
  │      SKAX   → skaxCustomProcess
  │      TIMBLO → timbloAgentProcess   (LangGraph 기반)
  │      기타    → skCustomProcess      (OpenAI 호환)
  │
  ├─ postSummaryProcess()   병렬 3건
  │    ├─ 노트 생성
  │    ├─ Content 갱신 (제목 · 키워드 · transcribeStatus=DONE)
  │    └─ TranscribeResult SUMMARY_DONE
  │
  ├─ finalizeSummaryProcess()
  │    ├─ usageModel.addUsage(LLM, totalToken)
  │    ├─ 하이라이트 초기화
  │    ├─ 순수 재요약이면 이력 기록
  │    ├─ 완료 메일 발송
  │    └─ DONE 전이
  │
  └─ 알림함 캡처
       isCreate       → CREATE
       isRetranscribe → RETRANSCRIBE
       그 외           → RESUMMARY
```

---

## 6. 상태 머신

`TranscribeResult.status` / `Content.transcribeStatus` (둘 다 자유 문자열이다. enum 아님)

```
                    ┌─────────┐
                    │ WAITING │  큐 접수 완료
                    └────┬────┘
                         │ recogWorker 시작
                    ┌────▼────┐
              ┌─────│ RUNNING │  ASR 진행 중 (진행률 WS 푸시)
              │     └────┬────┘
              │          │ 전사 완료
              │     ┌────▼─────┐
              │     │ STT_DONE │  llm 큐 등록됨
              │     └────┬─────┘
              │          │ llmWorker 시작
              │   ┌──────▼───────┐
              │   │ LLM-RUNNING  │ (재요약이면 RE_SUMMARY_RUNNING)
              │   └──────┬───────┘
              │          │ 요약 완료
              │   ┌──────▼───────┐
              │   │ SUMMARY_DONE │
              │   └──────┬───────┘
              │          │ 후처리 완료
              │      ┌───▼──┐
              │      │ DONE │ ★ 종결
              │      └──────┘
              │
              └────────▶ ┌───────┐
                         │ ERROR │ ★ 종결
                         └───────┘
```

상태 전이는 전부 `TranscribeUtil.transUpdater()` 를 지난다:

```js
// transcribe.util.js:91
async transUpdater(targetData, err = null) {
    await transcribeResultModel.updateStatus(where, targetData);   // MongoDB
    persisted = true;                    // ← TR 저장 성공 여부를 여기서 확정
    await contentModel.updateTranscribeStatus(...);                // MariaDB
    await this.statusUpdater(targetData, err);                     // 알림
    return persisted;
}
```

`persisted` 를 **TR 저장 직후** 확정하는 게 핵심이다.
호출부(재전사 파생물 정리)가 알고 싶은 건 "새 전사가 실제로 저장됐는가" 하나뿐이고,
Content 갱신·알림 실패와는 구분해야 하기 때문이다.

`statusUpdater` 는 종결 상태(DONE / ERROR)에서 추가 이벤트를 발행한다:

```js
// transcribe.util.js:83
if (['DONE','ERROR'].includes(status)) datasync.onComplete(...)      // Kafka
if (['DONE','ERROR'].includes(status) && this.external)
    await notify.externalEvent(...)                                   // 외부 콜백
return notify.sttStatus(data, this.params, this.member);              // WS 푸시
```

---

## 7. 큐 아키텍처

### 7-1. 이중화 — standalone / cluster

```js
// src/utils/index.js:19
const taskQueue = isRedisCluster() ? queueCluster : queueLegacy;
```

`REDIS_CLUSTER_HOSTS` 환경변수 유무로 **모듈 로드 시점에** 결정된다.
로컬은 standalone(`queue.util.js`), 운영은 cluster 를 쓰는 것으로 보인다.

### 7-2. 큐 종류

| 큐 이름 | 워커 | 동시성 | 생성 위치 |
|---|---|---|---|
| `recog-<engineTag>` | `recogWorker` | 채널 배분값 | 엔진별 지연 생성 |
| `llm` | `llmWorker` | `LLM_WORKER` (기본 100) | 모듈 로드 시 |
| `normalize` | 음량 정규화 | `NORMALIZE_WORKER` | `normalize.service.js` |

### 7-3. jobId 규약 — 중복 방지의 핵심

```
recog 큐 :  jobId = fileId
llm   큐 :  jobId = ticketId
```

`addTask` 는 동일 jobId 잡이 active/waiting/delayed 중 하나면 **`false` 를 반환**한다 (throw 아님).

```js
// queue.util.js:55
this.queue.add(task, {
    delay,
    jobId: taskId,
    removeOnFail: false,      // 실패 잡은 남긴다 (조사용)
    removeOnComplete: true,   // 성공 잡은 즉시 정리
});
```

> `removeOnFail: false` 라 실패 잡이 Redis 에 계속 쌓인다.
> 재전사 시 `removeResidualJob()` 이 종료 상태(completed/failed) 잡만 골라 지우는 이유다.

---

## 8. 재전사 · 재요약

### 재전사 `POST /contents/:contentId/re-transcribe`

`recog.service.js:209 reAddTask`. 일반 업로드와 **다른 점**이 많다.

```
reAddTask
  ├─ 기존 ticket · TranscribeResult 를 유지        ← sso·datasync 행 보존
  ├─ auth.member.workspace.config 에 엔진 주입      ← 재전사 경로엔 인증 심이 엔진을 안 실음
  │
  ├─ ① 잔여 잡 제거 (recog: fileId, llm: ticket)
  │      종료 잡만 제거. active 면 1105 거부
  │
  ├─ ② 잡 접수 먼저                                 ★ 순서 엄수
  │      isCreate: false        생성 메일 억제
  │      isRetranscribe: true   파생물 정리 트리거
  │      실패하면 DB 무변경으로 종료 (WAITING 고착 방지)
  │
  └─ ③ 접수 확정 후에만 상태 커밋
       ├─ 3-a. 조건부 WAITING 리셋  ★ 가장 먼저
       │        종결 상태(DONE/ERROR/CANCEL)일 때만 되돌린다
       │        워커가 이미 전진시킨 RUNNING/STT_DONE 은 절대 안 건드림
       └─ 3-b. 언어·엔진 메타 미러링 (상태와 필드 분리 → 워커와 충돌 없음)
```

주석에 순서를 지켜야 하는 이유가 명시돼 있다:

- **리셋을 가장 먼저**: 앞에 DB 왕복을 끼우면 워커 fast-fail 과의 레이스 창이 넓어진다
- **메타 미러링은 접수 이후**: 앞에 두면 접수 거부(1127) 시 메타만 변이된 채 종료된다

전사 교체로 인덱스가 어긋나므로, STT_DONE 직후 파생물을 정리한다:

```js
// recog.service.js:30
highlightModel.clearHighlightByFileId(...)   // 하이라이트
bookmarkModel.clearBookmarksByFileId(...)    // 북마크
memoModel.clearMemosByFileId(...)            // 메모
```

### 재요약 `POST /contents/:contentId/reSummary`

llm 큐에만 다시 넣는다. STT 는 재실행하지 않는다.
`isCreate: false` · `isRetranscribe: false` 조합으로 들어와서
`reSummaryHistory` 에 이력이 남고 알림함 액션이 `RESUMMARY` 가 된다.

### 세 경로 구분 요약

| 경로 | isCreate | isRetranscribe | 이력 기록 | 알림함 액션 |
|---|---|---|---|---|
| 최초 업로드 | `true` | `false` | — | `CREATE` |
| 재전사 | `false` | `true` | — | `RETRANSCRIBE` |
| 재요약 | `false` | `false` | ✅ | `RESUMMARY` |

---

## 9. 알림 · 알림함(Inbox) 플로우

경로가 **세 갈래**라 헷갈리기 쉽다.

```
① 실시간 푸시 (WebSocket)
   notify.sttStatus() → notify.personal(`member:${id}`, ...)
   진행률 · 상태 변경을 열린 화면에 즉시 반영. fire-and-forget

② 이메일
   notify.contentDoneEmail() — 요약 완료 시 1회

③ 알림함 (Inbox)  ← 가장 복잡
   contentCaptureService.createContentCapture()
     ├─ ContentCapture 행 생성 (MariaDB)
     └─ Kafka 'notification' 토픽으로 봉투 발행
          → notification-api 가 소비해 배달
```

### Inbox 생성 주체 이관 — 진행 중인 마이그레이션

**과거**: master 는 캡처만 만들고, notification-api 가 Inbox 행을 생성했다 (CDC 경유).
**현재(2단계)**: master 가 캡처와 **같은 트랜잭션에서** Inbox 행까지 만든다.

```
createContentCapture()
  │
  ├─ inboxPolicy.isInboxPolicyReady() ?
  │
  ├── 준비됨 ──▶ 수신자 결정 → tx 안에서 캡처 + Inbox 행 함께 INSERT
  │              → Kafka 봉투에 message.created = true 표식
  │              → 소비자는 생성을 건너뛰고 조회·배달만
  │
  └── 미준비 ─▶ 캡처만 생성 → 무표식 봉투 발행
                 → 소비자의 legacy 생성 경로가 대신 만듦  (폴백)
```

**정책 3키**는 notification 서비스의 KV 에만 있어서, master 가 남의 KV 를 봐야 한다:

```
INBOX_SHARE_ACTIONS
INBOX_PERIOD_VISIBLE_ACTIONS
INBOX_NOT_VISIBLE_ACTIONS
```

`fetchEnv.js` 가 부팅 시 `timblo/notification/mutable` 에서 **이 3키만 선별해** 가져온다.
전부 가져오지 않는 이유가 주석에 있다:

```js
// utils/fetchEnv.js
// ★3키 외에는 절대 가져오지 않는다 — 같은 KV 에 FCM_PRIVATE_KEY·EMAIL_PASSWORD 같은 비밀이 있고,
//   개행이 포함된 값이라 .env 파일 자체가 깨진다.
```

파싱 실패 시 `err.message` 를 로그에 찍지 않는 것도 같은 이유다 —
V8 SyntaxError 메시지에 입력 원문 조각이 들어가 **비밀이 부팅 로그로 샌다.**

### 수신자 결정 3종

`inboxPolicy.util.js`

| 라벨 | 수신자 |
|---|---|
| `SHARE_EMAIL` | 공유 대상 이메일 → 멤버 |
| `CONTENT_SHARE_USERS` | 콘텐츠 작성자 + 공유받은 전원 |
| `CREATOR_ONLY` | 캡처 행위자 본인만 (조회 쿼리 자체가 없음) |

정책 판단은 순수 함수(`inboxPolicy.util.js`)가, 실제 DB 조회는 서비스가 한다.
테스트에 DB 모킹이 필요 없게 하려는 분리다.

> **주의**: 이 판정 로직은 notification-api 의 것을 **의도적으로 복제**한 것이다.
> 두 판정이 갈라지면 "같은 액션인데 서버마다 알림이 보였다 안 보였다" 하는 재현 불가 버그가 된다.
> 개선이 필요하면 **두 곳을 같은 커밋에서** 고쳐야 한다.

---

## 10. 엔진 플러그인 구조

ASR 과 LLM 모두 **워크스페이스 단위로 엔진을 갈아끼울 수 있다.**

### ASR (음성인식)

```
InferenceEndpoint (type=ASR)  ← DB 테이블
        │
   resolveAsrEngine()          asrEngine.util.js
        │  워크스페이스 엔드포인트 없으면 → 시스템 기본 ASR(isDefault) 폴백
        │  maxConcurrency → maxQueue 별칭 (채널 배분용)
        ▼
   transcribeEngine  { provider, tag, maxQueue, params }
        │
   TranscribeUtil.runner()     provider 로 분기
        ├─ NAVER          → engines/Naver/naverClova.js
        ├─ HAIV           → engines/Haiv/haiv.js
        ├─ OPENAI_COMPAT  → engines/OpenAICompat/openaiCompat.js
        └─ 그 외           → QueueError(1107)
```

> ASR 은 **하류 런타임 폴백이 없다.** 미할당이면 전사 자체가 불가하므로
> 기본 엔드포인트 폴백을 둔다 (`asrEngine.util.js:20-22`).

### LLM (요약)

```
resolveLlmEndpoint(workspaceId)   llmAdapters/resolver.js
        │
        ├─ SKAX    → summarizer/skaxCustomProcess.js
        ├─ TIMBLO  → summarizer/timbloAgentProcess.js   LangGraph 기반
        └─ 기타     → summarizer/skCustomProcess.js      OpenAI 호환
```

---

## 11. 외부 연동 맵

| 대상 | 방향 | 용도 | 차단성 |
|---|---|---|---|
| **Consul** | ↔ | 설정 KV, 서비스 등록, 런타임 watch | 등록 실패 = 부팅 실패 |
| **Kafka** | → | 알림 봉투, datasync 완료 이벤트 | 연결 실패 = 부팅 실패 |
| **Redis** | ↔ | Bull 큐, 세션 토큰 게이트, 캐시 | 큐 동작 불가 |
| **MinIO** | ↔ | 원본 파일, 썸네일, 공개 이미지 | 파일 API 만 실패 |
| **MariaDB** | ↔ | 관계형 전체 | 대부분 API 실패 |
| **MongoDB** | ↔ | 전사 결과, 노트 | 상세 조회 실패 |
| `AUTH_API_URL` | → | 외부 API 레인 사용자 조회·가입 | 인증 실패 |
| `CORRECTION_URL` | → | 교정 요청 | 교정 기능만 |
| `SKAX_API_URL` | → | SKAX 요약 엔진 | 해당 워크스페이스만 |
| ASR 엔진 | → | 음성인식 | 전사 불가 |

### Kafka 토픽 2종

| 토픽 | 환경변수 | 소비자 | 내용 |
|---|---|---|---|
| `notification` | `KAFKA_NOTIFY_TOPIC` | notification-api | Inbox 캡처 봉투 |
| `content.events` | `DATASYNC_TOPIC` | datasync-api | 콘텐츠 완료 이벤트 |

### datasync — SSO 콘텐츠만 동기화

```
onCreate({ ticketId, auth })
   auth.sso 없으면 no-op          ← self-gate
   있으면 TranscribeResult.sso 에 원문 캡처 (write-once)

onComplete({ contentId, ticketId })
   TR.sso 없으면 no-op            ← self-gate
   있으면 이벤트 조립 → Kafka 발행
```

**provider 무지(provider-agnostic)** 설계다. 캡처는 불투명 블롭으로 저장하고,
조립 시점에만 우리 엔티티 계약으로 변환한다.
본 STT/요약 파이프라인을 절대 차단하지 않는다 (내부 try/catch, 실패는 로그만).

---

## 12. 라이프사이클 배치

`handlers/lifecycle.handler.js`

워크스페이스 정책에 따라 오래된 콘텐츠를 정리하는 배치다.
**큐 두 개를 물려 스스로 매일 재예약하는 구조**라 처음 보면 헷갈린다.

```
큐 ①  'lifecycle'      워커: lifecycleWorker   동시성 1000   ← 실제 정리 작업
큐 ②  'lifecycleInit'  워커: lifecycleInit     동시성 1      ← 스케줄러 역할
```

```
lifecycleInit()                                    ← 큐 ②의 워커
  ├─ workspacePolicyModel.findAll()
  ├─ 워크스페이스마다
  │    ├─ 기존 잡 취소 (jobId = workspaceId)
  │    ├─ 정책 0건이면 skip
  │    └─ 큐 ①에 등록, delay = getDelayUntil(DAY, HOUR)      기본 1일 후 03시
  │
  └─ dailyQueueSetup()
       └─ 큐 ②에 자기 자신을 재등록, delay = getDelayUntil(DAY, HOUR + 1)
                                                    ← 04시. 정리 작업보다 1시간 뒤
```

즉 **매일 03시에 정리가 돌고, 04시에 다음 날 스케줄을 다시 깐다.**
`HOUR + 1` 인 이유가 이것 — 재예약이 당일 정리보다 먼저 돌면 방금 등록한 잡을 취소해 버린다.

```
lifecycleWorker(task)                              ← 큐 ①의 워커
  └─ 정책별로
       ├─ 실행 로그 생성 (LifeCyclePolicyExecutionLog)
       ├─ 마지막 완료 지점 조회 → 이어서 처리 (중단 지점 재개)
       ├─ worker[policyType.toLowerCase()] 실행     utils/lifecycleWorker/
       │    없는 policyType 이면 로그만 남기고 continue
       └─ 실행 로그 갱신 (건수 · 소요시간 · 실패사유)
```

### ⚠️ 알아둘 두 가지

**① 인스턴스 0번만 배치를 돈다**

```js
// lifecycle.handler.js:123
process.on('configChanged', () => {
    const instanceId = process.env.INSTANCE_ID || '0';
    if (instanceId === '0') {
        SYS_LIFE_CYCLE_BATCH_DAY  = Number(process.env.SYS_LIFE_CYCLE_BATCH_DAY)  || 1;
        SYS_LIFE_CYCLE_BATCH_HOUR = Number(process.env.SYS_LIFE_CYCLE_BATCH_HOUR) || 3;
        lifecycleInit();
    }
});
```

PM2 가 인스턴스를 3개 띄워도 **0번만** 스케줄을 만든다. 중복 배치 방지다.

**② 최초 기동만으로는 배치가 깔리지 않는다**

`lifecycleInit` 은 `app.module.js` 에서 export 되지만 **`app.js` 가 호출하지 않는다.**
실제 트리거는 둘뿐이다:

- Consul `configChanged` 이벤트 (KV 변경 시)
- Redis 에 남아 있던 `lifecycleInit` 큐 잡

따라서 **Consul KV 를 한 번도 안 건드린 채 새로 뜬 클러스터에서는 배치가 시작되지 않을 수 있다.**
운영 중에는 Redis 에 잡이 남아 이어지지만, 큐를 비우고 재기동하면 재확인이 필요하다.

### configChanged 이벤트를 공유하지 않는 이유

이 배치 재생성이 `configChanged` 에 걸려 있기 때문에,
notification KV 워처는 **전용 이벤트**(`inboxPolicyChanged`)를 따로 쓴다.
남의 서비스 KV 변경이 master 의 배치 재구성을 끌고 오면 안 되기 때문이다
(`discovery-config.js:88-93`, `inboxPolicy.util.js:56`).

---

## 13. 읽을 때 참고할 관례

### 13-1. 주석이 곧 설계 문서다

이 코드베이스는 **왜 그렇게 했는지**를 주석에 남기는 문화가 강하다.
`★` 로 시작하는 주석은 특히 중요하다 — 대부분 실제 장애나 리뷰 지적의 흔적이다.

```js
// ★포인트 오브 노 리턴: 요약이 이미 진행 중 — 이후 부수 작업 실패는 본 작업을 ERROR로 만들지 않는다
// ★위치 엄수: addTask보다 앞에 두면 수락 거부(1127) 시 메타만 변이된 채 종료된다
// ★3키 외에는 절대 가져오지 않는다 — 같은 KV 에 FCM_PRIVATE_KEY·EMAIL_PASSWORD 같은 비밀이 있고
```

**리팩터링 전에 ★ 주석을 반드시 읽을 것.** 순서·지연·예외 처리에 이유가 있다.

### 13-2. 실패를 삼키는 곳과 던지는 곳이 구분돼 있다

| 성격 | 처리 | 예 |
|---|---|---|
| 본 작업 | throw → 잡 실패 → ERROR 전이 | ASR 실패, 요약 실패 |
| 부수 효과 | 내부 catch, 로그만 | datasync 발행, Inbox 캡처, 사용량 기록 |
| 폴백 있는 것 | null 반환 → 호출측이 폴백 | Inbox 정책 미준비 |

> "Inbox·캡처는 원 요청(제목 변경·공유·휴지통 등)의 **부수 효과지 결과가 아니므로**
> 도메인 API 를 실패시키지 않는다" (`contentCapture.service.js` 주석)

### 13-3. 에러 코드

`HttpError(code)` / `QueueError(code)` 로 4자리 도메인 코드를 쓴다.

| 코드 | HTTP | 정의된 메시지 | 실제 쓰이는 상황 |
|---|---|---|---|
| `1000` | 400 | 필수 파라미터가 부족합니다 | 파일 누락, 잘못된 요청 |
| `1104` | 500 | 음성인식 결과가 없습니다 | segments 0건 |
| `1105` | 500 | 음성인식 진행중인 파일 입니다 | 동일 fileId 잡이 이미 실행 중 |
| `1107` | 500 | 사용 불가능한 엔진 코드입니다 | 미지원 ASR provider |
| `1114` | 422 | 현재 전사 및 AI 처리 중인 컨텐츠 입니다 | STT_DONE 저장 전 전사문 접근 (delay 3초로 방지하는 그 레이스) |
| `1127` | 500 | 요약이 진행 중인 회의록 입니다 | **llm 큐 등록 실패** — 메시지와 실제 용법이 어긋난다 |

전체 매핑은 `src/handlers/error.handler.js:17-51` 참조.

> `1127` 은 정의된 메시지("요약이 진행 중")와 코드에서 던지는 상황(큐 등록 실패)이
> 일치하지 않는다. `recog.service.js:89` 와 `:237` 둘 다 큐 접수 실패에 이 코드를 쓴다.
> 사용자에게는 "요약 진행 중"으로 보이지만 실제로는 접수 자체가 안 된 것이라, 장애 조사 시 혼동 주의.

---

## 14. 더 파볼 만한 곳

이번 분석에서 **깊게 들어가지 않은** 영역이다.

| 영역 | 위치 | 비고 |
|---|---|---|
| 문서 내보내기 | `utils/documator/` | PDF·DOCX·HWP 생성. `docs.composer.js` 492줄 |
| 요약 프롬프트 | `prompts/` | `summaryV2.js` 251줄 |
| 검색 | `services/search.service.js`, `models/search.model.js` | |
| 노트 편집 | `utils/note.paster.util.js` | 붙여넣기 처리 299줄 |
| 화자 관리 | `services/attendee.service.js` | 342줄 |
| 교정 | `services/correction.service.js`, `proofreading.service.js` | 외부 API 연동 |
| 챗봇 | `services/chatbot.service.js` | |
| 사용자·워크스페이스 | `services/user.service.js` | 504줄 |

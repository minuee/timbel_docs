# master-api 로컬 개발 환경 구축

> 작성일: 2026-08-14 · 대상: macOS (Apple Silicon, arm64)
> 인계 직후 최초 구동까지의 전 과정 기록. 실측 기반이며 추정은 별도 표기함.

---

## 1. 스택 개요

| 레이어 | 기술 | 비고 |
|---|---|---|
| 런타임 | Node.js **ESM** (`"type": "module"`) | 검증 버전 v24.16.0 |
| 웹 프레임워크 | Express 4 | |
| 프로세스 관리 | PM2 cluster (`ecosystem.config.cjs`) | 인스턴스 수 = `RECOG_WORKER` (기본 3) |
| DB | **MariaDB + MongoDB** 동시 사용 | `@timbel-timblo-onpremise/prisma` 래퍼 경유 |
| 캐시 / 큐 | Redis + **Bull / BullMQ** | standalone·cluster 자동 분기 |
| 오브젝트 스토리지 | **MinIO** | `@timbel-timblo-onpremise/minio-js` |
| 설정 / 디스커버리 | **Consul** | KV → `.env` 생성, 서비스 등록, 런타임 watch |
| 메시징 | **Kafka** | `@timbel-timblo-onpremise/notify` (kafkajs) |
| AI | OpenAI SDK, LangGraph, tiktoken | 자체 어댑터 `utils/llmAdapters`, `engines/Haiv`, SKAX |
| 문서 / 미디어 | pdfmake, docx, HWP generator(jar), fluent-ffmpeg | |
| APM / 트레이싱 | Pinpoint agent, `@timbel-timblo-onpremise/tracely` | 로컬에선 자동 비활성화 |
| API 문서 | swagger-jsdoc + swagger-ui-express | `/api-docs` |

### Redis 연결 모드 분기

`src/utils/index.js:19` 에서 `REDIS_CLUSTER_HOSTS` 환경변수 유무로 결정된다.

```js
const taskQueue = isRedisCluster() ? queueCluster : queueLegacy;
```

- 설정됨 → `queueCluster.util.js` (ioredis Cluster)
- 미설정 → `queue.util.js` (standalone) ← **로컬은 이쪽**

---

## 2. 구조

```
src/
├── app.js              진입점. 미들웨어 체인 + 라우터 마운트 + listen
├── app.module.js       공통 모듈 배럴 + uncaughtException 핸들러
├── configs/            discovery(Consul), swagger, i18n
├── handlers/           auth · authenticate · authorize · error · lifecycle · streamGrant
├── routes/             라우팅 정의 (10개)
├── controller/         요청·응답 처리 (11개)
├── services/           비즈니스 로직 (28개)
├── models/             Prisma 접근 계층 (28개)
├── utils/              공통 유틸 (40여개)
├── prompts/            LLM 프롬프트
└── docs/               Swagger 정의 (routes/, schemas/)
```

### 요청 처리 흐름

```
요청
 ├─ /health      → discovery.healthChecker          (인증 없음)
 ├─ /api-docs    → swagger-ui                       (인증 없음)
 │
 ├─ telemetry.traceMiddleware
 ├─ express.json / urlencoded  (limit 1gb)
 ├─ cookieParser → morgan → cors
 │
 ├─ streamGrantHandler     스트리밍 신원 격리. grant 쿠키를 세션 토큰으로 대체
 ├─ authenticateRequest    인증 (AUTH_API_URL 외부 호출)
 ├─ authorizeMember        권한 검사
 │
 └─ 라우터 → 컨트롤러 → 서비스 → 모델(Prisma) → MariaDB / MongoDB
      └─ ErrorHandler.exception
```

> `streamGrantHandler` 가 `authenticateRequest` **앞**에 있는 것은 의도적이다.
> 하류 authenticate 가 대체된 `x-timblo-token`(= grant)의 pid 를 읽어야 하기 때문 (`src/app.js:60-62` 주석 참조).

### 등록된 API

Swagger 기준 **경로 63개 / 오퍼레이션 79개**.

| 라우트 | 개수 |
|---|---|
| `/contents` | 40 |
| `/user` | 6 |
| `/queue` | 5 |
| `/search` | 3 |
| `/inbox` | 2 |
| `/chat` | 2 |
| `/bookmark` | 2 |
| `/notice` · `/integrate` · `/home` | 각 1 |

---

## 3. 사전 준비물

| 항목 | 확인 방법 | 비고 |
|---|---|---|
| Node.js | `node -v` | v24.16.0 에서 검증 |
| Homebrew | `brew --version` | 인프라 설치용 |
| 사내 GitLab PAT | — | **필수.** 아래 4-1 참조 |

---

## 4. 설치

### 4-1. 사내 npm 레지스트리 인증 ⚠️ 필수

의존성 중 **4개가 공개 npm 에 없다.** 사내 GitLab 패키지 레지스트리에만 존재한다.

| 패키지 | 필요 버전 | 역할 |
|---|---|---|
| `@timbel-timblo-onpremise/prisma` | `1.3.1` (정확히) | DB 접근 (모델 28개가 의존) |
| `@timbel-timblo-onpremise/notify` | `^0.0.16` | Kafka 알림 발행 |
| `@timbel-timblo-onpremise/minio-js` | `^8.0.6-timbel.0` | 오브젝트 스토리지 |
| `@timbel-timblo-onpremise/tracely` | `^0.3.0` | 분산 트레이싱 |

> `@baronote/logger`, `@baronote/tool` 은 **공개 npm 에 있다.** 인증 불필요.

**레지스트리 위치**

```
https://gitlab.timbel.dev/api/v4/groups/177/-/packages/npm/
```

- 그룹 ID `177` = **`apps/timblo`** (확인 완료)
- 브라우저 확인: <https://gitlab.timbel.dev/groups/apps/timblo/-/packages>
- 이력: 2026-04-09 커밋 `7ac67d4d` 에서 `projects/95` → `groups/177` 로 변경됨.
  **프로젝트 단위가 아니라 그룹 단위이므로 권한도 그룹 177 에 부여해야 한다.**

**PAT 발급**

1. <https://gitlab.timbel.dev/-/user_settings/personal_access_tokens>
2. Scope: **`read_api`** (또는 `read_package_registry`)
3. 생성된 토큰은 **한 번만 표시**되므로 즉시 복사

> 이 인스턴스는 토큰 접두사가 커스텀 설정되어 있어 `glpat-` 이 아니라
> `timbel-gitlab-` 으로 시작한다. 정상이다.
> `glft-` 로 시작하는 것은 **Feed token** 이며 패키지 설치에 쓸 수 없다.

**토큰 저장** (홈 디렉터리 `~/.npmrc`. 리포에 커밋되지 않는다)

```bash
npm config set '//gitlab.timbel.dev/api/v4/groups/177/-/packages/npm/:_authToken' '<발급받은-PAT>'
```

리포의 `.npmrc` 에는 주소만 있고 토큰은 없다:

```
@timbel-timblo-onpremise:registry=https://gitlab.timbel.dev/api/v4/groups/177/-/packages/npm/
//gitlab.timbel.dev/api/v4/groups/177/-/packages/npm/:_authToken=${GITLAB_TOKEN}
```

> 위처럼 `${GITLAB_TOKEN}` 참조가 남아 있으면 `~/.npmrc` 값보다 우선한다.
> 환경변수 방식(`GITLAB_TOKEN=... npm install`)을 쓰지 않을 거라면 두 번째 줄을 지운다.

### 4-2. 의존성 설치

```bash
npm install
```

정상 시 약 1,200여 개 패키지가 설치된다 (실측 1229개 / 60초).
deprecated 경고가 다수 출력되지만 설치 실패는 아니다.

**검증**

```bash
npm run test:unit    # 62개 통과 확인됨
```

### 4-3. Prisma macOS 엔진 확보 ⚠️ 필수

**증상 — 이 단계를 건너뛰면 부팅 즉시 크래시한다.**

```
Prisma Client could not locate the Query Engine for runtime "darwin-arm64".
This happened because Prisma Client was generated for "debian-openssl-3.0.x",
but the actual deployment required "darwin-arm64".
```

**원인**

`@timbel-timblo-onpremise/prisma` 패키지에 동봉된 쿼리 엔진은 리눅스·윈도우용뿐이다.
운영이 Alpine 컨테이너라 `binaryTargets` 에 macOS 가 빠져 있다.

```
libquery_engine-debian-openssl-3.0.x.so.node
libquery_engine-linux-musl-openssl-3.0.x.so.node
query_engine-windows.dll.node
(darwin 없음)
```

**해결**

`npm install` 시 `@prisma/engines` 가 macOS 엔진을 이미 내려받아 둔다.
버전도 일치한다 (양쪽 다 `6.19.3` / 엔진 해시 `c2990dca...`). 복사만 하면 된다.

```bash
SRC=node_modules/@prisma/engines/libquery_engine-darwin-arm64.dylib.node
DST=node_modules/@timbel-timblo-onpremise/prisma/dist/libs/prismaService

cp -f "$SRC" "$DST/mariaDB/libquery_engine-darwin-arm64.dylib.node"
cp -f "$SRC" "$DST/mongoDB/libquery_engine-darwin-arm64.dylib.node"
```

> ⚠️ **`npm install` 을 다시 하면 이 복사본은 사라진다.** 재설치할 때마다 반복해야 한다.
> Intel Mac 이면 파일명의 `darwin-arm64` 를 `darwin` 으로 바꾼다.

---

## 5. 인프라 기동

로컬 부팅에 **반드시 필요한 것은 Redis · Kafka · Consul 3종**이다.
(근거는 아래 8장 실측표)

### Redis

```bash
brew install redis          # 미설치 시
redis-server --daemonize yes
redis-cli ping              # PONG
```

### Kafka

Kafka 4.x 는 KRaft 모드라 Zookeeper 가 필요 없다. Java 의존성은 brew 가 함께 설치한다.

```bash
brew install kafka
brew services start kafka

lsof -nP -iTCP:9092 -sTCP:LISTEN     # 확인
```

> `brew services` 는 로그인 시 자동 시작된다. 원치 않으면
> `brew services stop kafka` 후 필요할 때만 직접 실행:
> `/opt/homebrew/opt/kafka/bin/kafka-server-start /opt/homebrew/etc/kafka/server.properties`

### Consul

Homebrew 코어에 `consul` 포뮬러가 없다 (`brew search consul` 로 나오는 cask 는 동명의 다른 앱).
단일 실행 바이너리를 직접 받는다.

```bash
mkdir -p ~/.local/bin
curl -sSL -o /tmp/consul.zip \
  "https://releases.hashicorp.com/consul/1.22.7/consul_1.22.7_darwin_arm64.zip"
unzip -oq /tmp/consul.zip -d /tmp
mv -f /tmp/consul ~/.local/bin/consul && chmod +x ~/.local/bin/consul

~/.local/bin/consul agent -dev -client=127.0.0.1 -bind=127.0.0.1 &
curl -s http://127.0.0.1:8500/v1/status/leader      # "127.0.0.1:8300"
```

> 1.x 를 쓴 이유: npm `consul@1.2.0` 클라이언트 및 운영 환경과의 호환성.
> 최신은 2.0.3 이지만 검증하지 않았다.
> Consul UI: <http://localhost:8500/ui>

---

## 6. 환경변수

운영은 컨테이너 부팅 시 `src/utils/fetchEnv.js` 가 Consul KV 를 읽어 `.env` 를 생성한다.

| KV 키 | 용도 |
|---|---|
| `timblo/common/env` | 공통 설정 (없으면 부팅 실패) |
| `timblo/master/immutable` | master 전용 설정 (없으면 부팅 실패) |
| `timblo/notification/mutable` | Inbox 정책 3키만 선별 취득 (실패해도 계속) |

런타임 변경은 `src/configs/discovery-config.js` 의 watcher 3개가 따라간다.

**로컬은 이 경로를 쓰지 않고 `.env` 를 직접 작성한다.**
템플릿은 리포 루트 `.env.example` 참조. 복사해서 시작한다.

```bash
cp .env.example .env
```

### 반드시 신경 써야 할 값

| 키 | 로컬 값 | 이유 |
|---|---|---|
| `PORT` | `8000` | 기본값은 9010 (Dockerfile 은 9012) |
| `KAFKA_BROKERS` | `127.0.0.1:9092` | **미설정 시 `baroKafka1:9092` 로 붙으려다 부팅이 멈춘다** |
| `CONSUL_HOST` | `127.0.0.1` | 기본값은 `consul-discovery` |
| `SYS_NAME` | `be-master-service` | 미설정 시 discovery-config 가 throw |
| `CHECK_IP` | `127.0.0.1` | 미설정 시 사설 IP 를 자동 탐지해 Consul 에 등록 |
| `AES_KEY` | 32바이트 문자열 | 길이 안 맞으면 암복호화 실패 |

> `AES_KEY` · `ENCRYPT_SECRET_KEY` · `STREAM_GRANT_SECRET` 은 로컬 더미값이다.
> **운영 DB 의 기존 암호화 데이터를 복호화하려면 실제 키가 필요하다.**

---

## 7. 실행

```bash
node src/app.js      # 또는  npm run dev  (nodemon)
```

### 확인

| URL | 기대 결과 |
|---|---|
| <http://localhost:8000/health> | `ok` |
| <http://localhost:8000/api-docs> | Swagger UI (API 79개) |
| <http://localhost:8500/ui> | Consul 에 `be-master-service-0` 등록됨 |

정상 부팅 로그:

```
info ▷ Listening on 8000
info ▷ 서비스 등록 시도: be-master-service-0 (127.0.0.1:8000)
info ▷ be-master-service가 Consul에 🌐HTTP 체크로 등록 완료
```

> Swagger UI 의 **Servers** 드롭다운 기본값이 `http://localhost:9010` 이다.
> "Try it out" 을 쓰려면 8000 으로 바꾼다 (`src/configs/swagger.js:17`).

---

## 8. 부팅 의존성 실측표

실제로 하나씩 끄고 켜며 확인한 결과다. **추정이 아니다.**

| 의존성 | 없을 때 동작 | 부팅 차단 |
|---|---|---|
| **Prisma macOS 엔진** | 즉시 `uncaughtException` → `exit(1)` | 🔴 차단 |
| **Kafka** | `app.listen` 도달 못 함 (아래 설명) | 🔴 차단 |
| **Consul** | `Listening` 직후 크래시 (아래 설명) | 🔴 차단 |
| Redis | — (로컬에 이미 있어 미검증) | ⚠️ 미검증 |
| MariaDB / MongoDB | Prisma 지연 연결. 부팅은 됨 | 🟢 통과 |
| MinIO | 첫 파일 요청 시에만 필요 | 🟢 통과 |
| 외부 API (AUTH / LLM / SKAX / CORRECTION) | 호출 시점에만 필요 | 🟢 통과 |

### Kafka 가 부팅을 막는 이유

`src/utils/notify.util.js:9` — **파일 최상단의 top-level await**

```js
await notify.connect();
```

ESM 모듈 그래프 로딩 단계에서 실행되므로, 연결될 때까지 `src/app.js` 본문
(= `app.listen`)에 도달하지 못한다. notify 패키지의 재시도 설정이 `retries: 20`
(`node_modules/@timbel-timblo-onpremise/notify/src/config/kafkaConfig.js:26`)
이라 지수 백오프로 사실상 무한정 대기한다.

브로커 기본값은 `baroKafka1:9092` 하드코딩이며 `KAFKA_BROKERS` 로 덮어쓴다.

### Consul 이 부팅을 막는 이유

`src/app.js:55-58`

```js
app.listen(process.env.PORT ?? 9010, '0.0.0.0', async () => {
    log.i(`Listening on ${process.env.PORT}`);
    await discovery.registerService();     // 실패 시 rethrow
});
```

`registerService()` 가 예외를 다시 던지고(`discovery-config.js:224`),
async 콜백의 unhandled rejection 이 `app.module.js` 의 `uncaughtException`
핸들러에 잡혀 `process.exit(1)` 된다.

**즉 "포트는 열렸는데 곧바로 죽는" 형태라 로그를 끝까지 봐야 원인이 보인다.**

한편 Consul **watcher** 실패(`kv.get: connect ECONNREFUSED`)는 로그만 남기고
부팅을 막지 않는다. 등록(register)과 감시(watch)는 별개다.

---

## 9. 오늘 변경된 파일

| 파일 | 상태 | 내용 |
|---|---|---|
| `.npmrc` | 신규 | 사내 레지스트리 주소. **토큰 값 없음** |
| `.gitignore` | 신규 | 기존에 없었음. `node_modules`, `.env`, `dist` 등 제외 |
| `.env` | 신규 | 로컬 설정 (gitignore 대상) |
| `.env.example` | 신규 | 팀 공유용 템플릿 |
| `src/configs/swagger.js` | **수정** | 아래 설명 |
| `docs/LOCAL_SETUP.md` | 신규 | 이 문서 |

### swagger.js 수정 내역

**증상**: 로컬에서 `/api-docs` 는 뜨는데 API 목록이 **0개**.

**원인**: 문서 소스 경로가 `cwd` 기준이었다.

```js
apis: ['./docs/schemas/*.js', './docs/routes/*.js'],
```

운영 컨테이너는 Dockerfile 이 `src/docs/` → `./docs/` 로 복사하고 cwd 가
`/usr/src/app` 이라 맞는다. 로컬은 cwd 가 리포 루트여서 (비어 있는) `docs/` 를
보게 되어 0건이 된다.

**수정**: 파일 위치 기준 절대경로로 변경. 로컬·컨테이너 양쪽에서 동일하게 해석된다.

```js
const docsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../docs');
// ...
apis: [path.join(docsDir, 'schemas/*.js'), path.join(docsDir, 'routes/*.js')],
```

- 로컬: `src/configs/` → `src/docs/` ✅
- 컨테이너: `app/configs/` → `app/docs/` ✅

수정 후 **경로 63개 / API 79개**가 정상 노출됨을 확인했다.

---

## 10. 남은 과제

### 인프라 (미구성)

| 항목 | 영향 | 비고 |
|---|---|---|
| MariaDB | 데이터 조회 API 전부 실패 | 스키마: 모델 58개 |
| MongoDB | 파일·전사 결과 조회 실패 | 스키마: 모델 12개. **replica set 필요** (Prisma 요건) |
| MinIO | 업로드·다운로드·이미지 URL 실패 | 버킷 `PUB_BUCKET_NAME` 사전 생성 필요 |

> 스키마 원본 위치:
> `node_modules/@timbel-timblo-onpremise/prisma/dist/libs/prismaService/{mariaDB,mongoDB}/schema.prisma`
> Prisma 래퍼 구조는 [ARCHITECTURE.md 2장](./ARCHITECTURE.md#데이터-접근-계층--prisma-래퍼) 참조.

#### 스키마 적용 방법 (확인 완료)

패키지에 마이그레이션 도구가 동봉돼 있다.
**단, DDL diff 를 생성만 하고 적용은 하지 않는다.** 자동 마이그레이션이 아니다.

```
node_modules/@timbel-timblo-onpremise/prisma/dist/db-migrate/
├── README.md
├── migrate-diff.sh                범용 — 현재 DB ↔ 동봉 스키마 diff(.sql) 생성
└── dump-transcribe-engine.cjs     전환기 전용 — TranscribeEngine 백업
```

운영 절차는 다음과 같다 (패키지 README 기준):

```sh
# db-migrate 컨테이너에서 실행
node scripts/fetchEnv.js \
  && sh   node_modules/@timbel-timblo-onpremise/prisma/dist/db-migrate/migrate-diff.sh \
  && node node_modules/@timbel-timblo-onpremise/prisma/dist/db-migrate/dump-transcribe-engine.cjs
```

1. 새 SDK 이미지로 1회 실행 → `*-prisma-diff.sql` 생성
2. **개발자가 diff 를 검토하고 필요한 DDL 만 골라 직접 적용**
3. ASR 엔드포인트는 백오피스 GUI 에서 재등록
4. 워크스페이스 미할당은 런타임 폴백(시스템 기본 ASR)으로 처리

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MARIA_DATABASE_URL` | 필수 | 대상 DB |
| `MIGRATION_DIFF_OUTPUT_DIR` | `$APP_DIR/migrations` | 출력 폴더 |
| `PRISMA_SCHEMA_PATH` | SDK 동봉 스키마 | 다른 스키마와 비교할 때만 |

> ⚠️ **빈 DB 를 처음부터 만드는 용도가 아니다.** 기존 DB 와의 차이를 뽑는 도구다.
> 로컬에 백지 상태 DB 를 세우려면 diff 전체를 적용하거나, 개발서버 덤프를 받는 편이 빠르다.

### 외부 연동 (미연결)

`AUTH_API_URL` · `LLM_API_URL` · `CORRECTION_URL` · `SKAX_API_URL` · `SSO_SAML_URL`

특히 **`AUTH_API_URL` 은 `authenticateRequest` 가 매 요청마다 호출**하므로,
이것 없이는 인증이 필요한 API 를 하나도 호출할 수 없다.
`/health` 와 `/api-docs` 는 인증 체인 앞단이라 영향 없다.

### Consul KV 미시딩

현재 dev 모드 Consul 은 KV 가 비어 있다. 그 결과:

- `INBOX_*` 정책 3키 부재 → 로그: `[InboxPolicy] inboxActions 설정 누락`
- `timblo/common/credentials` 부재 → `storageChanged` 이벤트 미발생 →
  **`drive.util.js` 의 `MinioClient` 가 `null` 로 남는다** (`drive.util.js:11-21`)

MinIO 를 붙일 때는 KV 시딩이 함께 필요하다.

---

## 11. ⚠️ 보안 조치 필요

작업 중 아래 두 토큰이 대화창에 노출되었다. **폐기 후 재발급 필요.**

설치는 완료되었고 토큰을 파일에 저장하지 않았으므로 **지금 폐기해도 무방하다.**
재설치가 필요해지면 새 토큰을 4-1 방식으로 `~/.npmrc` 에 넣는다.

---

## 부록 A. 전체 기동 순서 (재현용)

```bash
# 1. 인프라
redis-server --daemonize yes
brew services start kafka
~/.local/bin/consul agent -dev -client=127.0.0.1 -bind=127.0.0.1 &

# 2. 준비 확인
redis-cli ping                                        # PONG
lsof -nP -iTCP:9092 -sTCP:LISTEN                      # kafka
curl -s http://127.0.0.1:8500/v1/status/leader        # consul

# 3. 애플리케이션
cd <repo>
node src/app.js

# 4. 동작 확인
curl http://localhost:8000/health                     # ok
open http://localhost:8000/api-docs
```

## 부록 B. 종료 / 정리

```bash
# 앱
kill $(lsof -nP -iTCP:8000 -sTCP:LISTEN -t)

# 인프라
brew services stop kafka
kill $(lsof -nP -iTCP:8500 -sTCP:LISTEN -t)     # consul
redis-cli shutdown

# 완전 제거
brew uninstall kafka
rm ~/.local/bin/consul
```

## 부록 C. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `404 Not Found @timbel-timblo-onpremise/...` | 레지스트리 인증 없음 | 4-1 |
| `could not locate the Query Engine for "darwin-arm64"` | Prisma 엔진 누락 | 4-3 |
| 로그만 흐르고 `Listening` 이 안 뜸 | Kafka 미기동 | 5장 Kafka |
| `Listening` 직후 `ECONNREFUSED 127.0.0.1:8500` 로 종료 | Consul 미기동 | 5장 Consul |
| `/api-docs` 는 뜨는데 API 0개 | swagger 경로 (수정 완료) | 9장 |
| `PORT 환경변수가 올바르지 않습니다` | `.env` 미로드 또는 PORT 누락 | 6장 |

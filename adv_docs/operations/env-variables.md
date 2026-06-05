# 환경변수 전체 목록

> `asst-service` 의 환경변수는 [src/config/validation.config.ts](../../asst-service/src/config/validation.config.ts) 의 Joi 스키마로 강제됩니다.
> `asst-web` 은 Webpack의 `MODE`에 따라 `.env.{MODE}` 가 빌드 시점에 주입됩니다.

---

## 1. 백엔드 (asst-service)

### 1-1. 기본 / 인프라

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `NODE_ENV` | - | `development` | `local` / `development` / `production` |
| `PROJECT_NAME` | - | - | 로깅/추적용 프로젝트명 |
| `PORT` | - | `3000` | 서버 포트 |
| `HOST` | - | `localhost` | 바인딩 호스트 |
| `API_BASE_PATH` | - | `/api/asst/v1` | 글로벌 prefix |
| `HTTPS_ENABLED` | - | `0` | `1`이면 SSL 활성화 (K8s에선 보통 `0`) |
| `SSL_KEY_PATH` | `HTTPS_ENABLED=1`일 때 | - | SSL 키 경로 |
| `SSL_CERT_PATH` | `HTTPS_ENABLED=1`일 때 | - | SSL 인증서 경로 |
| `SOCKET_SECURE` | - | `1` | `1`이면 WSS 사용 |
| `CORS_ALLOWED_ORIGINS` | - | - | 쉼표 구분 도메인 (게이트웨이가 보통 처리) |

### 1-2. DB 연결

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `DB_DIRECT_CON` | - | `0` | **`1`=정적, `0`=테넌트 동적** ([01-multi-tenant-db.md#4](../architecture/01-multi-tenant-db.md#4-db_direct_con-토글)) |
| `DB_TYPE` | `DB_DIRECT_CON=1`일 때 | - | `postgres` / `mariadb` |
| `DB_HOST` | `DB_DIRECT_CON=1`일 때 | - | DB 호스트 |
| `DB_PORT` | `DB_DIRECT_CON=1`일 때 | - | DB 포트 |
| `DB_USERNAME` | `DB_DIRECT_CON=1`일 때 | - | DB 유저 |
| `DB_PASSWORD` | `DB_DIRECT_CON=1`일 때 | - | DB 비밀번호 |
| `DB_DATABASE` | `DB_DIRECT_CON=1`일 때 | - | DB 이름 |
| `DB_PROXY_HOST` | - | - | SSH 터널 프록시 호스트 (로컬→prod) |
| `DB_PROXY_PORT` | - | - | SSH 터널 프록시 포트 |

### 1-3. Redis

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `REDIS_HOST` | - | `localhost` | Redis 호스트 |
| `REDIS_PORT` | - | `6379` | |
| `REDIS_PASSWORD` | - | - | |
| `REDIS_DB` | - | `0` | DB 번호 |
| `REDIS_TLS` | - | - | `true`/`1`/`false`/`0` |
| `REDIS_HEALTH_CHECK_INTERVAL` | - | `30000` | 헬스체크 주기 ms |

### 1-4. 외부 서비스

| 변수 | 필수 | 설명 |
|------|------|------|
| `USER_HOST` | ✅ | User 서비스 (테넌트 정보 + 토큰 검증) |
| `TENANT_HOST` | ✅ | Tenant 관리 (현재 USER_HOST로 db_config 조회) |
| `TENANT_CONFIG_URL` | - | 별도 테넌트 설정 URL (옵션) |
| `LLM_ORCHESTRATOR_HOST` | - | LLM Orchestrator (요약/todo) |
| `LLM_HOST` | - | LLM Manager fallback |
| `SEARCH_HOST` | - | RAG Search (`/api/v1/rag/assist-stream`) |
| `SEARCH_REPOSITORY_ID` | - | 기본 RAG repository ID |
| `CE_HOST` | - | Call Experience (어드바이저봇) |
| `KNOWLEDGE_API_URL` | - | KMS 프록시 대상 |
| `AUDIO_SERVICE_API_URL` | - | 음성 스트리머 프록시 대상 |
| `QA_API_URL` | - | QA 서비스 프록시 |
| `AUTH_SERVICE_API_URL` | - | Auth 서비스 프록시 |
| `TA_HOST` | - | (현재 코드 주석 처리됨) |

### 1-5. 관측성

| 변수 | 필수 | 설명 |
|------|------|------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | OpenTelemetry 수집기 |
| `OTEL_SERVICE_NAME` | - | 트레이싱 서비스 이름 |
| (그 외 OTEL 표준 env) | - | [@opentelemetry 표준](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/) |

---

## 2. 프론트엔드 (asst-web)

### 2-1. 빌드 모드

| MODE 값 | 명령 | 용도 |
|---------|------|------|
| `development` | `npm run dev` | 개발 서버 |
| `local` | `npm run local` | 로컬 직접 연결 |
| `test` | `npm run test` | 테스트 환경 |
| `dev` | `npm run build:dev` | dev 빌드 |
| `prd` | `npm run build:prd` | 운영 빌드 |
| `aws` | `npm run build:aws` | AWS 빌드 |
| `ncp` | `npm run build:ncp` | NCP 빌드 |

각 MODE 별로 `.env.{MODE}` 파일이 빌드 시점에 주입됩니다.

### 2-2. 주요 변수

| 변수 | 설명 |
|------|------|
| `LANGSA_GATEWAY_URL` | Langsa API 게이트웨이 도메인 (모든 API/소켓 진입점) |
| `VITE_USER_NODE_ENV` | **Redis 채널 prefix** (`dev`/`prod` 등) ⚠️ 채널명 매칭에 결정적 |
| `ASST_API_PREFIX` | asst-service 게이트웨이 경로 (기본 `/aicc/asst-service`) |
| `AUTH_API_PREFIX` | Auth 서비스 경로 (기본 `/api`) |
| `AUDIO_API_PREFIX` | Audio 서비스 경로 (기본 `/api/v1`) |
| `CE_API_PREFIX` | CE 서비스 경로 (기본 `/api/ce/v1`) |

설정 위치: [asst-web/src/api/config/path.ts](../../asst-web/src/api/config/path.ts)

---

## 3. 환경별 권장 조합

### 로컬 개발 (가장 단순)

```bash
# asst-service/.env.local
NODE_ENV=local
DB_DIRECT_CON=1
DB_TYPE=postgres
DB_HOST=localhost
DB_PORT=5432
DB_USERNAME=advisor
DB_PASSWORD=advisor
DB_DATABASE=advisor_local
REDIS_HOST=localhost
USER_HOST=http://localhost:8001
TENANT_HOST=http://localhost:8002
LLM_ORCHESTRATOR_HOST=http://localhost:8010
SEARCH_HOST=http://localhost:8020
HTTPS_ENABLED=0
SOCKET_SECURE=0
```

```bash
# asst-web/.env.local
LANGSA_GATEWAY_URL=http://localhost:3000
VITE_USER_NODE_ENV=dev
ASST_API_PREFIX=/api/asst/v1
```

### 개발 환경 (테넌트 동적 연결)

```bash
# asst-service/.env.development
NODE_ENV=development
DB_DIRECT_CON=0
USER_HOST=https://user.dev.example.com
TENANT_HOST=https://user.dev.example.com
LLM_ORCHESTRATOR_HOST=https://llm-orch.dev.example.com
SEARCH_HOST=https://search.dev.example.com
CE_HOST=https://ce.dev.example.com
REDIS_HOST=redis.dev.internal
REDIS_TLS=true
REDIS_PASSWORD=...
# DB_HOST 등은 USER_HOST 응답으로 동적 결정됨
HTTPS_ENABLED=0  # K8s LB가 처리
SOCKET_SECURE=1
```

### 운영 환경

위 development와 유사하나:
- 호스트가 운영 도메인
- `NODE_ENV=production`
- `SSL_*` 적용 또는 게이트웨이 위임
- 시크릿은 K8s Secrets / Vault

---

## 4. 시크릿 관리 원칙

1. **하드코딩 절대 금지** — 모든 시크릿은 환경변수
2. **`.env.{NODE_ENV}` 파일은 commit 금지** — `.gitignore`에 포함되어 있는지 확인
3. **K8s 환경**: ConfigMap(공개 값) + Secret(민감 값) 분리
4. **로테이션**: DB 비밀번호, Redis 비밀번호, JWT 시크릿은 정기 로테이션
5. **로깅 시 주의**: 토큰/비밀번호가 로그에 남지 않게 — 현재 `AuthMiddleware`는 토큰 일부를 로그에 출력. 운영 환경에서는 마스킹 필요.

---

## 5. env 파일 우선순위

[app.module.ts:16-19](../../asst-service/src/app.module.ts#L16-L19):

```typescript
envFilePath: [
  `.env.${process.env.NODE_ENV || 'local'}`,  // 1순위
  '.env',                                       // 2순위
],
```

→ `.env.local` 의 값이 `.env` 의 값을 override. 둘 다 같은 키가 있으면 환경별 파일이 이김.

`expandVariables: true` 옵션으로 `${VAR}` 형태의 변수 확장 지원.

---

## 6. 변경 시 체크 리스트

- [ ] `validation.config.ts` 의 Joi 스키마 업데이트
- [ ] `.env.example` 파일에 항목 추가 (있다면)
- [ ] 운영팀에 변경 공지 (K8s Secrets/ConfigMap 갱신 필요)
- [ ] 게이트웨이 라우팅 영향 검토 (`API_BASE_PATH`, `ASST_API_PREFIX` 변경 시)
- [ ] 프론트엔드 `.env.{MODE}` 파일도 함께 업데이트 (필요 시)

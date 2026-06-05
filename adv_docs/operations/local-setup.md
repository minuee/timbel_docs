# 로컬 개발 환경 셋업

> 새로 합류한 개발자가 로컬에서 Advisor를 실행하기까지의 단계별 가이드.

---

## 1. 사전 요구사항

| 도구 | 버전 |
|------|------|
| Node.js | 20.x 이상 |
| npm | 10.x 이상 |
| PostgreSQL | 14+ (도커 이미지 추천) |
| Redis | 6+ (도커 이미지 추천) |
| Git | - |

선택사항:
- Docker Desktop (PG/Redis 띄우기 쉬움)
- Postman / Insomnia (API 테스트)
- VS Code (또는 IntelliJ)

---

## 2. 저장소 클론

```bash
git clone <repo-url> advisor
cd advisor
```

모노레포 구조 — 백엔드(`asst-service/`)와 프론트엔드(`asst-web/`)가 같은 저장소.

---

## 3. PostgreSQL + Redis (도커)

### 3-1. 가장 간단한 방법: docker-compose

`asst-service/docker-compose.dev.yml` 또는 별도 인프라용 compose 작성:

```yaml
# infra-compose.yml (예시)
services:
  postgres:
    image: postgres:15
    container_name: advisor-pg
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: advisor
      POSTGRES_PASSWORD: advisor
      POSTGRES_DB: advisor_local
    volumes:
      - pg_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    container_name: advisor-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  pg_data:
  redis_data:
```

실행:

```bash
docker compose -f infra-compose.yml up -d
```

### 3-2. 스키마 생성

```bash
docker exec -it advisor-pg psql -U advisor -d advisor_local -c "CREATE SCHEMA IF NOT EXISTS advisor; CREATE SCHEMA IF NOT EXISTS raw_call;"
```

또는 [asst-service/create-advisor-schema.sql](../../asst-service/create-advisor-schema.sql) 적용:

```bash
docker exec -i advisor-pg psql -U advisor -d advisor_local < asst-service/create-advisor-schema.sql
```

> **Local에서는 `synchronize: true`** 라서 TypeORM이 엔티티 기반으로 테이블을 자동 생성합니다. 다만 마이그레이션 컬럼 일부는 SQL 적용 필요할 수 있음 (SQL 원본: `asst-service/migrations/`, 수동 적용).

---

## 4. 백엔드 (asst-service)

### 4-1. 의존성 설치

```bash
cd asst-service
npm install
```

### 4-2. `.env.local` 작성

```bash
# asst-service/.env.local
NODE_ENV=local
PROJECT_NAME=asst-service
PORT=3000
HOST=localhost
API_BASE_PATH=/api/asst/v1

# DB 정적 연결 (로컬은 1 권장)
DB_DIRECT_CON=1
DB_TYPE=postgres
DB_HOST=localhost
DB_PORT=5432
DB_USERNAME=advisor
DB_PASSWORD=advisor
DB_DATABASE=advisor_local

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# 외부 서비스 (개발 환경 또는 mock)
USER_HOST=https://user-service.dev.example.com
TENANT_HOST=https://user-service.dev.example.com
LLM_ORCHESTRATOR_HOST=https://llm-orch.dev.example.com
SEARCH_HOST=https://search.dev.example.com
CE_HOST=https://ce-service.dev.example.com
KNOWLEDGE_API_URL=https://kms.dev.example.com
AUDIO_SERVICE_API_URL=https://audio.dev.example.com

# HTTPS 비활성화 (로컬)
HTTPS_ENABLED=0
SOCKET_SECURE=0

# 로깅
LOG_LEVEL=debug
FILE_LOG_LEVEL=info
LOG_PRETTY_JSON=true
```

> **외부 서비스가 사내에만 있다면** SSH 터널 + `DB_PROXY_HOST` 사용 또는 사내 dev 환경 토큰 사용.

### 4-3. 실행

```bash
npm run start:dev
```

→ 콘솔에 다음과 같은 로그가 보이면 정상:

```
[NestApplication] Nest application successfully started
서버 설정 완료: { environment: 'local', httpsEnabled: false, socketSecure: false }
```

### 4-4. 동작 확인

```bash
# 헬스 체크 (인증 불필요)
curl http://localhost:3000/api/asst/v1/health/check

# Swagger UI
open http://localhost:3000/api/asst/v1/doc
```

---

## 5. 프론트엔드 (asst-web)

### 5-1. 의존성 설치

```bash
cd asst-web
npm install
```

> 의존성이 매우 많음 (Element Plus + Quasar + DevExtreme + Vue Flow + GoJS 등). 첫 설치 시간이 길 수 있음.

### 5-2. `.env.local` 작성

```bash
# asst-web/.env.local
LANGSA_GATEWAY_URL=http://localhost:3000
VITE_USER_NODE_ENV=dev
ASST_API_PREFIX=/api/asst/v1
AUTH_API_PREFIX=/api
AUDIO_API_PREFIX=/api/v1
CE_API_PREFIX=/api/ce/v1
```

> 로컬에서는 게이트웨이 없이 asst-service 직결. `LANGSA_GATEWAY_URL`을 asst-service URL로 설정.

### 5-3. 실행

```bash
npm run local
```

→ Webpack dev server가 보통 `http://localhost:8080` 같은 포트로 열림. 콘솔 로그 확인.

### 5-4. 동작 확인

브라우저로 dev server 주소 접속 → 상담사 화면 진입 → 콘솔에서 다음 확인:

- `[socket-IO-Plugin] connected: <socket-id>` — Socket.IO 연결 성공
- `[CONSULTANT] 초기화 중 장애가 발생했습니다.` 같은 에러가 없으면 정상
- Network 탭에서 `GET /api/asst/v1/...` 요청이 200 응답

---

## 6. 가장 단순한 로컬 동작 시나리오

외부 서비스 mock 없이 백엔드 자체만 실행하려면:

1. **PG/Redis만 도커로 실행**
2. **`USER_HOST`, `LLM_*` 등은 빈 값** — 다음 기능은 동작 안 함:
   - 멀티테넌트 동적 DB (`DB_DIRECT_CON=1` 로 우회)
   - LLM 요약 (`POST /summary` 호출 시 500 에러)
   - assist-stream (`SEARCH_HOST` 없으면 503)
3. **단순 CRUD만 테스트 가능**:
   - 통화 통계 조회
   - 메모/북마크/공지 CRUD
   - 즐겨찾기

전체 기능 테스트는 dev 환경에 붙거나 외부 서비스를 mock 서버로 띄워야 함.

---

## 7. 첫 실행 체크리스트

- [ ] `docker compose -f infra-compose.yml up -d` — PG + Redis 기동
- [ ] PG 스키마 2개 (`advisor`, `raw_call`) 생성 확인
- [ ] `asst-service/.env.local` 작성
- [ ] `cd asst-service && npm install && npm run start:dev` — 백엔드 기동
- [ ] `curl http://localhost:3000/api/asst/v1/health/check` — 200 응답
- [ ] Swagger UI 접속 확인 (`/api/asst/v1/doc`)
- [ ] `asst-web/.env.local` 작성
- [ ] `cd asst-web && npm install && npm run local` — 프론트 기동
- [ ] 브라우저에서 화면 진입 + Socket.IO 연결 로그 확인
- [ ] (선택) Redis CLI로 메시지 publish 시뮬레이션:
  ```
  redis-cli PUBLISH dev:tenant1:agent01:call:events '{"type":"start","call_id":"test"}'
  ```

---

## 8. 자주 발생하는 셋업 이슈

| 증상 | 원인 | 해결 |
|------|------|------|
| `Joi validation error: USER_HOST is required` | 필수 env 누락 | `.env.local`에 `USER_HOST` 추가 (빈 문자열도 OK 아닌 경우 있음) |
| PG 연결 실패 (ECONNREFUSED) | 도커 미실행 또는 포트 충돌 | `docker ps`로 확인, `lsof -i :5432` |
| Redis 연결 실패 | 동일 | `docker ps`, `lsof -i :6379` |
| TypeORM `entity metadata not found` | 새 엔티티 추가 후 등록 누락 | `database.config.ts` + `dynamic-database.service.ts` 양쪽 확인 |
| 프론트에서 404 | `LANGSA_GATEWAY_URL` 오타 | `.env.local`의 URL 재확인 |
| Webpack `Module not found: host_app/router` | 모듈 페더레이션 host 없음 | 단독 실행 시 정상, 또는 ECP 호스트 같이 실행 |
| Husky pre-commit 에러 | 처음 클론 시 hook 미설치 | `npm install` 다시 실행 (husky install 자동) |

---

## 9. 추가 가이드 (이전 문서 참고)

- [asst-service/setup-database.md](../../asst-service/setup-database.md) (archived) — 상세 DB 셋업
- [asst-service/DYNAMIC_DB_SETUP.md](../../asst-service/DYNAMIC_DB_SETUP.md) (archived) — 동적 DB 설정
- [asst-service/CORS_SETUP.md](../../asst-service/CORS_SETUP.md) (archived) — CORS 설정

위 문서들은 일부 outdated 가능성. 차이가 있으면 본 adv_docs 가 신뢰원.

> ⚠️ **[ARCHIVED] 이 문서는 2026-01-30 작성된 구 인수인계서입니다.**
> **최신 인수인계 문서는 [/adv_docs/](../adv_docs/) 를 참조하세요.**
> 구체적인 매핑:
> - 시스템 아키텍처 → [adv_docs/architecture/00-overview.md](../adv_docs/architecture/00-overview.md)
> - 환경변수 / 배포 → [adv_docs/operations/](../adv_docs/operations/)
> - API 엔드포인트 → [adv_docs/api/conventions.md](../adv_docs/api/conventions.md)
> - 도메인 모듈 → [adv_docs/specs/domains-overview.md](../adv_docs/specs/domains-overview.md)
>
> 이 문서는 historical reference로만 유지합니다. 정보가 다르면 adv_docs/가 신뢰원입니다.

---

# ASST-SERVICE 프로젝트 인수인계서

**작성일**: 2026-01-30
**버전**: 0.0.1
**문서 목적**: 프로젝트 인수인계 (archived)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [기술 스택](#2-기술-스택)
3. [프로젝트 구조](#3-프로젝트-구조)
4. [설치 및 실행](#4-설치-및-실행)
5. [환경 변수 설정](#5-환경-변수-설정)
6. [API 엔드포인트](#6-api-엔드포인트)
7. [데이터베이스 구조](#7-데이터베이스-구조)
8. [인증 및 보안](#8-인증-및-보안)
9. [배포](#9-배포)
10. [모니터링 및 로깅](#10-모니터링-및-로깅)
11. [개발 가이드](#11-개발-가이드)
12. [주의사항 및 알려진 이슈](#12-주의사항-및-알려진-이슈)

---

## 1. 프로젝트 개요

### 1.1 서비스 설명

**asst-service**는 상담사 지원 서비스(Advisor Assistant Service)를 위한 백엔드 API 서버입니다. 콜센터 상담사들의 업무를 지원하기 위한 다양한 기능을 제공합니다.

### 1.2 주요 기능

| 기능 | 설명 |
|------|------|
| **상담사/그룹 관리** | 상담사 정보 및 조직 구조 관리 |
| **통화 통계** | 통화 기록, 턴 데이터, 엔티티, 키워드 분석 |
| **코칭 시스템** | 상담사 간 코칭 요청/응답 관리 |
| **즐겨찾기** | 상담사, 통화, 코칭 즐겨찾기 |
| **북마크/메모** | 스크립트, 지식정보 북마크 및 메모 관리 |
| **공지사항** | 공지사항 CRUD 및 읽음 상태 추적 |
| **할일(Todo)** | 상담사별 할일 관리 및 LLM 자동 생성 |
| **통화 요약** | LLM 기반 통화 요약 및 키워드 추출 |
| **키워드 감지** | 실시간 키워드 감지 설정 |
| **환경 설정** | 사용자별 개인 설정 관리 |

### 1.3 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Vue.js)                         │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTP/WebSocket
┌─────────────────────────────▼───────────────────────────────────┐
│                     asst-service (NestJS)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Controllers │  │  Services   │  │    Gateways (Socket.IO) │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  │
│         │                │                      │                │
│  ┌──────▼────────────────▼──────────────────────▼──────────────┐│
│  │              Dynamic Database Service                        ││
│  │              (Multi-tenant 지원)                             ││
│  └──────────────────────────┬───────────────────────────────────┘│
└─────────────────────────────┼───────────────────────────────────┘
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
    ┌────────────┐    ┌────────────┐    ┌────────────┐
    │ PostgreSQL │    │   Redis    │    │  LLM API   │
    │ (Tenant별) │    │  (Cache)   │    │  (요약)    │
    └────────────┘    └────────────┘    └────────────┘
```

---

## 2. 기술 스택

### 2.1 핵심 기술

| 분류 | 기술 | 버전 |
|------|------|------|
| **Runtime** | Node.js | >= 20.0.0 |
| **Framework** | NestJS | 11.x |
| **Language** | TypeScript | 5.8.x |
| **ORM** | TypeORM | 0.3.x |
| **Database** | PostgreSQL | - |
| **Cache** | Redis | 4.7.x |
| **WebSocket** | Socket.IO | 4.8.x |
| **API Docs** | Swagger/OpenAPI | 11.x |

### 2.2 주요 라이브러리

```
# 핵심
@nestjs/core, @nestjs/common, @nestjs/platform-express
@nestjs/typeorm, @nestjs/config, @nestjs/swagger
@nestjs/websockets, @nestjs/platform-socket.io

# 데이터베이스
typeorm, pg (PostgreSQL driver)

# 캐싱
redis

# 로깅
winston, nest-winston, winston-daily-rotate-file

# 검증
class-validator, class-transformer, joi

# 모니터링
@opentelemetry/sdk-node, @opentelemetry/auto-instrumentations-node

# HTTP 클라이언트
axios

# 유틸리티
uuid, rxjs
```

### 2.3 개발 도구

```
# 빌드
@swc/core, @swc/cli, ts-node

# 테스트
jest, ts-jest, supertest

# 린팅/포매팅
eslint, prettier, typescript-eslint

# Git Hooks
husky, lint-staged, @commitlint/cli
```

---

## 3. 프로젝트 구조

```
asst-service/
├── src/
│   ├── main.ts                    # 애플리케이션 진입점
│   ├── app.module.ts              # 루트 모듈
│   │
│   ├── advisor/                   # 핵심 비즈니스 모듈
│   │   ├── advisor.module.ts
│   │   ├── controllers/           # 21개 API 컨트롤러
│   │   │   ├── agent.controller.ts
│   │   │   ├── coaching.controller.ts
│   │   │   ├── callstat.controller.ts
│   │   │   ├── summary.controller.ts
│   │   │   ├── todo.controller.ts
│   │   │   └── ... (16개 더)
│   │   ├── services/              # 비즈니스 로직 서비스
│   │   ├── entities/              # 26개 데이터베이스 엔티티
│   │   └── dto/                   # 데이터 전송 객체
│   │
│   ├── common/                    # 공통 모듈
│   │   ├── middleware/            # 인증, 추적 미들웨어
│   │   ├── guards/                # 권한 가드
│   │   ├── interceptors/          # DB 정리 인터셉터
│   │   ├── gateways/              # Socket.IO 게이트웨이
│   │   ├── services/              # 공통 서비스 (DB, Redis, Tenant)
│   │   ├── decorators/            # 커스텀 데코레이터
│   │   └── utils/                 # 유틸리티 함수
│   │
│   └── config/                    # 설정 파일
│       ├── database.config.ts     # TypeORM 설정
│       ├── redis.config.ts        # Redis 설정
│       ├── validation.config.ts   # 환경변수 검증 (Joi)
│       └── winston.config.ts      # 로깅 설정
│
├── migrations/                    # SQL 마이그레이션 파일 (16개)
├── public/                        # 정적 파일 (Socket.IO 테스트)
├── logs/                          # 로그 파일 디렉토리
├── dist/                          # 빌드 출력
│
├── Dockerfile                     # 멀티스테이지 빌드
├── docker-compose.yml             # 프로덕션 구성
├── docker-compose.dev.yml         # 개발 구성
│
├── .env                           # 기본 환경변수
├── .env.local                     # 로컬 개발 환경
├── .env.development               # 개발 서버 환경
│
├── package.json
├── tsconfig.json
└── nest-cli.json
```

---

## 4. 설치 및 실행

### 4.1 사전 요구사항

- Node.js >= 20.0.0
- npm 또는 yarn
- PostgreSQL 데이터베이스
- Redis 서버

### 4.2 설치

```bash
# 저장소 클론
git clone <repository-url>
cd asst-service

# 의존성 설치
npm install
```

### 4.3 실행 명령어

```bash
# 개발 모드 (로컬)
npm run start:dev

# 개발 모드 (development 환경)
npm run start:dev:env

# 디버그 모드
npm run start:debug

# 프로덕션 빌드
npm run build

# 프로덕션 실행
npm run start:prod
```

### 4.4 테스트

```bash
# 단위 테스트
npm test

# 테스트 커버리지
npm run test:cov

# E2E 테스트
npm run test:e2e
```

### 4.5 Docker 실행

```bash
# 개발 환경
docker-compose -f docker-compose.dev.yml up --build

# 프로덕션 환경
docker-compose up --build
```

---

## 5. 환경 변수 설정

### 5.1 필수 환경 변수

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `NODE_ENV` | 실행 환경 | `local`, `development`, `production` |
| `PORT` | 서버 포트 | `3000` |
| `API_BASE_PATH` | API 기본 경로 | `/api/asst/v1` |
| `USER_HOST` | 사용자 서비스 호스트 | `http://user-service-svc` |
| `TENANT_HOST` | 테넌트 관리 서비스 호스트 | `http://tenant-mgmt` |
| `LLM_HOST` | LLM 서비스 호스트 | `https://aicc-llm-manager-service` |

### 5.2 Redis 설정

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `REDIS_HOST` | Redis 호스트 | `localhost` |
| `REDIS_PORT` | Redis 포트 | `6379` |
| `REDIS_PASSWORD` | Redis 비밀번호 | - |
| `REDIS_DB` | Redis DB 번호 | `0` |

### 5.3 데이터베이스 설정 (DB_DIRECT_CON=1 일 때)

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `DB_TYPE` | DB 타입 | `postgres` |
| `DB_HOST` | DB 호스트 | `localhost` |
| `DB_PORT` | DB 포트 | `5432` |
| `DB_USERNAME` | DB 사용자명 | `aicc_admin` |
| `DB_PASSWORD` | DB 비밀번호 | - |
| `DB_DATABASE` | DB 이름 | `aicc` |

### 5.4 기타 설정

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `LOG_LEVEL` | 콘솔 로그 레벨 | `debug` |
| `FILE_LOG_LEVEL` | 파일 로그 레벨 | `info` |
| `HTTPS_ENABLED` | HTTPS 활성화 | `0` |
| `SOCKET_SECURE` | Socket.IO 보안 | `1` |
| `CORS_ALLOWED_ORIGINS` | 허용 CORS 도메인 | - |

### 5.5 환경별 설정 파일

- `.env` - 기본 설정 (Kubernetes 배포용)
- `.env.local` - 로컬 개발 (직접 DB 연결)
- `.env.development` - 개발 서버

---

## 6. API 엔드포인트

### 6.1 API 기본 정보

- **Base URL**: `/api/asst/v1`
- **Swagger 문서**: `/api/asst/v1/doc`
- **인증**: Bearer Token (x-auth-token 또는 Authorization 헤더)

### 6.2 주요 엔드포인트 요약

#### 상담사 관리 (`/agents`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/agents` | 상담사 목록 조회 |
| POST | `/agents` | 상담사 생성 |
| GET | `/agents/:id` | 상담사 조회 |
| PUT | `/agents/:id` | 상담사 수정 |
| DELETE | `/agents/:id` | 상담사 삭제 |
| PUT | `/agents/status` | 상담사 상태 변경 (Socket 브로드캐스트) |

#### 그룹 관리 (`/groups`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/groups` | 그룹 목록 조회 |
| POST | `/groups` | 그룹 생성 |
| POST | `/groups/assign-agents` | 그룹에 상담사 배치 |

#### 통화 통계 (`/callstat`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/callstat/calls` | 통화 목록 조회 (Pagination) |
| GET | `/callstat/calls/:id` | 통화 상세 조회 |
| GET | `/callstat/calls/:id/turns` | 통화 턴 목록 |
| GET | `/callstat/agent-summary` | 상담사별 통계 |

#### 코칭 (`/coachings`)
| Method | Path | 설명 |
|--------|------|------|
| POST | `/coachings/requests` | 코칭 요청 생성 |
| POST | `/coachings` | 코칭 생성 |
| GET | `/coachings/call/:callId` | 통화별 코칭 조회 |
| PATCH | `/coachings/:id/read` | 읽음 처리 |

#### 통화 요약 (`/summary`)
| Method | Path | 설명 |
|--------|------|------|
| POST | `/summary` | LLM 통화 요약 생성 |
| GET | `/summary/data/:callstats_id` | 요약 데이터 조회 |

#### 할일 (`/todos`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/todos` | 할일 목록 조회 |
| POST | `/todos` | 할일 생성 |
| POST | `/todos/auto-create` | LLM 자동 할일 생성 |

#### 북마크 (`/bookmarks`, `/bookmark-groups`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/bookmark-groups?user_key=...` | 북마크 그룹 조회 |
| POST | `/bookmarks` | 북마크 생성 |
| PUT | `/bookmarks/:id/move` | 북마크 이동 |

#### 메모 (`/memos`, `/memo-groups`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/memo-groups/user/:userKey` | 사용자별 메모 그룹 |
| POST | `/memos` | 메모 생성 |

#### 공지사항 (`/notices`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/notices` | 공지사항 목록 (Pagination) |
| GET | `/notices/unread/:userKey` | 읽지 않은 공지사항 |

#### 즐겨찾기
| 경로 | 설명 |
|------|------|
| `/favorites` | 일반 즐겨찾기 |
| `/favorite-agents` | 상담사 즐겨찾기 |
| `/favorite-call` | 통화 즐겨찾기 |
| `/favorite-coaching` | 코칭 즐겨찾기 |
| `/favorite-coaching-requests` | 코칭 요청 즐겨찾기 |

#### 헬스 체크
| Method | Path | 설명 |
|--------|------|------|
| GET | `/health/check` | 서비스 상태 확인 (인증 불필요) |
| GET | `/health/db-connections` | DB 연결 상태 |

---

## 7. 데이터베이스 구조

### 7.1 스키마 구성

| 스키마 | 용도 |
|--------|------|
| `advisor` | 메인 비즈니스 로직 테이블 |
| `raw_call` | 통화 원본 데이터 테이블 |

### 7.2 주요 테이블

#### advisor 스키마

| 테이블 | 설명 |
|--------|------|
| `agents` | 상담사 정보 |
| `groups` | 조직/그룹 정보 |
| `notices` / `notices_reads` | 공지사항 및 읽음 기록 |
| `memos` / `memo_groups` | 메모 및 메모 그룹 |
| `bookmarks` / `bookmark_groups` | 북마크 및 북마크 그룹 |
| `coaching_requests` / `coachings` | 코칭 요청 및 코칭 |
| `favorites` | 일반 즐겨찾기 |
| `favorite_agents` | 상담사 즐겨찾기 |
| `favorite_call` | 통화 즐겨찾기 |
| `favorite_coaching` / `favorite_coaching_requests` | 코칭 즐겨찾기 |
| `todos` | 할일 |
| `summary` | 통화 요약 |
| `configs` | 사용자 설정 |
| `keyword_detects` | 키워드 감지 설정 |
| `call_categories` / `call_keywords` | 통화 분류/키워드 |
| `intent_feedback` | Intent 피드백 |

#### raw_call 스키마

| 테이블 | 설명 |
|--------|------|
| `callstats_call` | 통화 통계 메인 |
| `callstats_turn` | 통화 턴(발화) 데이터 |
| `callstats_entity` | 엔티티/슬롯 데이터 |
| `callstats_keyword` | 통화 키워드 |

### 7.3 주요 관계

```
groups ──1:N──> agents
memo_groups ──1:N──> memos
bookmark_groups ──1:N──> bookmarks
notices ──1:N──> notices_reads
coaching_requests ──1:N──> coachings
callstats_turn ──1:N──> intent_feedback
```

### 7.4 마이그레이션

마이그레이션 파일 위치: `/migrations/`

```bash
# 주요 마이그레이션 파일
create_advisor_schema.sql          # 기본 스키마
create_agents_groups_tables.sql    # 상담사/그룹
create_bookmarks_tables.sql        # 북마크
create_coachings_table.sql         # 코칭
create_favorites_table.sql         # 즐겨찾기
create_todos_table.sql             # 할일
create_summary_table.sql           # 요약
```

---

## 8. 인증 및 보안

### 8.1 인증 방식

- **토큰 기반 인증** (Bearer Token)
- 지원 헤더:
  1. `x-auth-token` (우선순위 1)
  2. `Authorization: Bearer <token>` (우선순위 2)

### 8.2 인증 제외 경로

- `GET /health/check`

### 8.3 Multi-tenant 구조

```
1. 요청 수신
2. 토큰에서 테넌트 정보 추출
3. 테넌트별 DB 연결 동적 생성
4. 요청 처리
5. DB 연결 정리 (Interceptor)
```

### 8.4 CORS 설정

**개발 환경**: 모든 origin 허용

**프로덕션 환경**:
- `https://ecplab.etaas.co.kr`
- `http://222.99.52.67:32082`
- `CORS_ALLOWED_ORIGINS` 환경변수로 추가 설정

---

## 9. 배포

### 9.1 Docker 빌드

```bash
# 이미지 빌드
docker build -t asst-service:latest .

# 실행
docker run -p 3000:3000 --env-file .env asst-service:latest
```

### 9.2 Dockerfile 구조

```dockerfile
# Stage 1: 빌드
FROM node:20-alpine AS build
RUN npm ci --ignore-scripts
RUN npm run build

# Stage 2: 프로덕션
FROM node:20-alpine
RUN npm ci --omit=dev
EXPOSE 3000
CMD ["node", "dist/src/main"]
```

### 9.3 Kubernetes 배포

- 설정 참조: `k8s-debug-config.yaml`
- ConfigMap/Secret으로 환경변수 관리
- Service, Deployment 구성 필요

### 9.4 환경별 포트

| 환경 | 내부 포트 | 외부 포트 |
|------|-----------|-----------|
| 개발 | 3000 | 31001 |
| 프로덕션 | 3000 | 32080 |

---

## 10. 모니터링 및 로깅

### 10.1 로깅

**Winston 기반 로깅**:
- 콘솔 출력
- 일일 로테이션 파일 (`logs/asst-service-yyyy-MM-dd.log`)
- 에러 전용 파일 (`logs/error-yyyy-MM-dd.log`)

**로그 레벨**: trace, debug, info, warn, error

### 10.2 요청 추적

- **Trace ID**: 각 요청에 고유 ID 부여
- **헤더**: `x-trace-id`

### 10.3 OpenTelemetry

- 자동 계측 활성화
- HTTP, DB 쿼리 추적
- OTLP Exporter 설정: `OTEL_EXPORTER_OTLP_ENDPOINT`

### 10.4 Health Check

```bash
# 서비스 상태
curl http://localhost:3000/health/check

# DB 연결 상태
curl http://localhost:3000/health/db-connections
```

---

## 11. 개발 가이드

### 11.1 코드 스타일

**ESLint 규칙**:
- 절대 경로 import 사용 (`@app/*`)
- Import 순서: Node.js > 외부 라이브러리 > 내부 모듈
- Prettier 자동 포매팅

### 11.2 커밋 메시지 규칙

**Conventional Commits 형식**:
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type 종류**:
- `feat`: 새로운 기능
- `fix`: 버그 수정
- `docs`: 문서 수정
- `refactor`: 코드 리팩토링
- `test`: 테스트 코드
- `chore`: 기타 변경

### 11.3 새로운 API 추가 방법

1. **Entity 생성** (`src/advisor/entities/`)
2. **DTO 생성** (`src/advisor/dto/`)
3. **Service 생성** (`src/advisor/services/`)
4. **Controller 생성** (`src/advisor/controllers/`)
5. **Module에 등록** (`src/advisor/advisor.module.ts`)
6. **database.config.ts에 Entity 추가**

### 11.4 마이그레이션 추가

1. `/migrations/` 에 SQL 파일 생성
2. DBA에게 실행 요청 또는 직접 실행

---

## 12. 주의사항 및 알려진 이슈

### 12.1 환경별 주의사항

| 환경 | 주의사항 |
|------|----------|
| **local** | `synchronize: true` - 스키마 자동 동기화됨 |
| **development** | `DB_DIRECT_CON=0` - 동적 DB 연결 사용 |
| **production** | SSL 연결 필수, 로깅 최소화 |

### 12.2 DB 연결 관련

- `DB_DIRECT_CON=1`: 정적 DB 연결 (로컬 개발용)
- `DB_DIRECT_CON=0`: 동적 테넌트별 DB 연결 (운영용)

### 12.3 알려진 이슈

1. **CONNECTION_POOL_LIMIT**: 최대 20개 연결 제한
   - 트래픽 급증 시 연결 대기 발생 가능

2. **LLM API 의존성**: 요약/할일 자동생성 시 LLM 서비스 필수
   - LLM 서비스 장애 시 502/503 에러 반환

### 12.4 성능 고려사항

- Pagination 사용 권장 (기본 limit: 10)
- 대용량 통화 데이터 조회 시 날짜 범위 지정 필수
- Redis 캐시 활용 (Agent 상태, 설정 등)

### 12.5 보안 주의사항

- `.env` 파일 커밋 금지
- 민감 정보 환경변수 관리
- CORS 허용 도메인 최소화

---

## 부록

### A. 외부 서비스 의존성

| 서비스 | 용도 | 환경변수 |
|--------|------|----------|
| user-service | 사용자 정보 조회 | `USER_HOST` |
| tenant-mgmt | 테넌트 설정 조회 | `TENANT_HOST` |
| aicc-llm-manager | 통화 요약/키워드 추출 | `LLM_HOST` |
| aicc-ce-service | CE 서비스 연동 | `CE_HOST` |

### B. 담당자 연락처

| 역할 | 담당자 | 연락처 |
|------|--------|--------|
| 개발 | - | - |
| 운영 | - | - |
| DBA | - | - |

### C. 참고 문서

- `README.md` - 프로젝트 기본 안내
- `CORS_SETUP.md` - CORS 설정 가이드
- `DYNAMIC_DB_SETUP.md` - 동적 DB 설정 가이드
- `advisorbot-integration-guide.md` - 어드바이저봇 통합 가이드
- `setup-database.md` - 데이터베이스 셋업 가이드

---

*이 문서는 2026-01-30 기준으로 작성되었습니다.*

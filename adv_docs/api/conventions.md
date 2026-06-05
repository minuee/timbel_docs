# API 규약 및 엔드포인트 인덱스

> asst-service REST API 컨벤션과 도메인별 엔드포인트 요약.
> 정확한 스펙은 Swagger UI(`{API_BASE_PATH}/doc`)를 신뢰원으로 사용하세요.

---

## 1. 기본 정보

| 항목 | 값 |
|------|------|
| Base path | `/api/asst/v1` (env `API_BASE_PATH`) |
| Swagger UI | `/api/asst/v1/doc` |
| 인증 방식 | `x-auth-token` 헤더 (Bearer fallback) |
| Content-Type | `application/json` (기본), `text/event-stream` (assist-stream) |
| 게이트웨이 경로 | `/aicc/asst-service/*` (Langsa 게이트웨이) |

설정 위치: [main.ts:69](../../asst-service/src/main.ts#L69), [app.module.ts:32-40](../../asst-service/src/app.module.ts#L32-L40)

---

## 2. 인증

### 헤더

```http
x-auth-token: <Bearer 토큰>
```

또는 fallback:

```http
Authorization: Bearer <토큰>
```

### 인증 우회 경로

[app.module.ts:35-39](../../asst-service/src/app.module.ts#L35-L39):

```
api/asst/v1/health/check
api/asst/v1/assist-stream
api/asst/v1/proxy/audio/stream/playback
```

이 경로들은 `AuthMiddleware`를 거치지 않습니다. `req.dbConnection`도 부착되지 않으므로 DB 접근이 필요하면 컨트롤러에서 별도 처리.

### 토큰 검증 책임

`AuthMiddleware`는 토큰을 직접 검증하지 않고 **`USER_HOST` 응답(200/4xx)으로 간접 검증**합니다. 자세히는 [01-multi-tenant-db.md#9](../architecture/01-multi-tenant-db.md#9-인증-동작의-진실).

---

## 3. 요청 / 응답 컨벤션

### 요청

- **Body**: JSON, 최대 10MB ([main.ts:54-55](../../asst-service/src/main.ts#L54-L55))
- **ValidationPipe 옵션** ([main.ts:118-124](../../asst-service/src/main.ts#L118-L124)):
  - `transform: true` — DTO 인스턴스 자동 변환
  - `whitelist: true` — DTO에 없는 필드는 제거
  - `forbidNonWhitelisted: true` — DTO에 없는 필드 있으면 400 에러

→ 모든 DTO는 `class-validator` 데코레이터로 검증 필수.

### 응답

**페이지네이션 응답 표준 형식** (예: `GET /callstat/calls`):

```json
{
  "data": [...],
  "total": 123,
  "page": 1,
  "limit": 20,
  "totalPages": 7,
  "hasNext": true,
  "hasPrev": false
}
```

표준 페이지네이션 DTO: [PaginationDto](../../asst-service/src/common/dto/pagination.dto.ts)

### 에러 형식

NestJS 표준 HttpException 형식:

```json
{
  "statusCode": 404,
  "message": "통화 통계를 찾을 수 없습니다: 019913cc-...",
  "error": "Not Found"
}
```

LLM/외부 서비스 에러 상태 코드:

| 상태 | 의미 |
|------|------|
| 502 | 외부 서비스 응답 오류 (Bad Gateway) |
| 503 | 외부 서비스 연결 불가 (Service Unavailable) |

---

## 4. 추적/로깅

### Trace ID

[trace-id.middleware.ts](../../asst-service/src/common/middleware/trace-id.middleware.ts) 가 모든 요청에 `x-trace-id` 헤더를 부착/계승. 로그에 ID가 함께 출력되어 분산 추적 가능.

요청 시 클라이언트가 `x-trace-id`를 보내면 그대로 사용, 없으면 새로 생성.

### OpenTelemetry

[main.ts:1, 19, 23](../../asst-service/src/main.ts) — `@opentelemetry/sdk-node` 자동 트레이싱 활성화. import 시점에 시작.

환경변수로 OTLP 수집기 설정 가능 (`OTEL_EXPORTER_OTLP_ENDPOINT` 등 표준 env).

---

## 5. 도메인별 엔드포인트 인덱스

> 정확한 파라미터와 응답 형식은 Swagger UI를 참조. 여기서는 라우트 구조만 정리.

### 5-1. Health (인증 X)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health/check` | 헬스 체크 |

### 5-2. Agent (`/agents`, `/agent-call-settings`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/agents` | 상담원 목록 |
| GET | `/agents/:id` | 상담원 상세 |
| ... | (`AgentController` 10개 엔드포인트) | |
| GET/PUT | `/agent-call-settings/...` | 통화 개인 설정 |

### 5-3. Call (`/callstat`, `/call-stats`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/callstat/calls` | Pagination 통화 목록 |
| GET | `/callstat/calls/by-call-id/:callId` | call_id 기준 조회 |
| GET | `/callstat/calls/:id` | 통화 상세 |
| GET | `/callstat/turns/:callstatsId` | 발화 턴 목록 |
| ... | (총 12개) | |
| GET | `/call-stats/...` | 집계 (`CallStatsController` 3개) |

### 5-4. Summary (`/summary`)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/summary` | 통화 LLM 요약 + 키워드 추출 |
| POST | `/summary/data` | 요약 데이터 upsert |
| GET | `/summary/...` | 조회 |
| PUT/DELETE | `/summary/:id` | 수정/삭제 |

### 5-5. Coaching (`/coachings`)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/coachings/requests` | 코칭 요청 생성 |
| GET | `/coachings/requests` | 요청 목록 |
| GET | `/coachings/requests/:id` | 요청 상세 |
| PATCH/DELETE | `/coachings/requests/:id` | 수정/삭제 |
| POST | `/coachings` | 코칭 메시지 생성 (Redis publish) |
| GET | `/coachings` | 메시지 목록 |
| ... | (총 14개) | |

### 5-6. Assist Stream (`/assist-stream`, `/assist-snapshot`)

| Method | Path | 설명 | 인증 |
|--------|------|------|------|
| POST | `/assist-stream` | RAG/LLM SSE 스트리밍 | ⚠️ 미들웨어 우회 |
| POST | `/assist-snapshot` | 답변 스냅샷 저장 | O |

### 5-7. Search (`/search`)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/search/...` | 문서 검색 (RAG 위임) |

### 5-8. 보조 도메인

| 도메인 | 경로 | 컨트롤러 수 |
|--------|------|------|
| Bookmark | `/bookmarks`, `/bookmark-groups` | 2 |
| Memo | `/memos`, `/memo-groups` | 2 |
| Notice | `/notices` | 1 |
| Todo | `/todos` | 1 |
| Group | `/groups` | 1 |
| Config | `/config` | 1 |
| Keyword Detect | `/keyword-detect` | 1 |
| Intent Feedback | `/intent-feedback` | 1 |
| Document | `/documents` | 1 |

### 5-9. Favorite (5종)

| Controller | 경로 |
|------------|------|
| `FavoriteController` | `/favorites` |
| `FavoriteCallController` | `/favorites/calls` |
| `FavoriteCoachingController` | `/favorites/coachings` |
| `FavoriteCoachingRequestsController` | `/favorites/coaching-requests` |
| `FavoriteAgentsController` | `/favorites/agents` |

### 5-10. Redis Monitor (운영/디버깅)

[redis-monitor.controller.ts](../../asst-service/src/common/controllers/redis-monitor.controller.ts):

| Method | Path | 설명 |
|--------|------|------|
| GET | `/redis-monitor/debug-auth` | 인증 헤더 디버그 |
| POST | `/redis-monitor/subscribe/:channel` | 채널 구독 시작 |
| DELETE | `/redis-monitor/unsubscribe/:channel` | 구독 해제 |
| DELETE | `/redis-monitor/unsubscribe-all` | 전체 해제 |
| GET | `/redis-monitor/channels` | 구독 중인 채널 목록 |
| GET | `/redis-monitor/status` | 모니터링 상태 |
| GET | `/redis-monitor/debug/rooms` | Socket.IO room 상태 |

→ **이 엔드포인트들은 프론트가 동적으로 호출**해서 백엔드의 Redis 구독을 트리거합니다 ([02-realtime-streaming.md#1-3](../architecture/02-realtime-streaming.md#1-3-백엔드-구독-등록-흐름)).

### 5-11. Proxy 컨트롤러

[src/common/proxy/](../../asst-service/src/common/proxy/) — 외부 서비스로 위임되는 BFF 경로:

| Controller | 경로 prefix | 대상 |
|------------|------|------|
| `CeProxyController` | `/proxy/ce/...` | `CE_HOST` |
| `QaProxyController` | `/proxy/qa/...` | `QA_API_URL` |
| `UserProxyController` | `/proxy/user/...` | `USER_HOST` |
| `KnowledgeProxyController` | `/proxy/knowledge/...` | `KNOWLEDGE_API_URL` |
| `AudioProxyController` | `/proxy/audio/...` | `AUDIO_SERVICE_API_URL` |
| `TaProxyController` | (`TA_HOST` 일시 주석) | - |

자세한 BFF 패턴 배경: [adv_docs/plans/done/2026-04-16-bff-transition-plan.md](../plans/done/2026-04-16-bff-transition-plan.md)

---

## 6. Swagger UI 활용

운영/개발 환경에서 `https://{host}/api/asst/v1/doc` 접속:

```
설정 (main.ts:93-101):
  persistAuthorization: true       # 토큰 입력 후 새로고침해도 유지
  displayRequestDuration: true     # 응답 시간 표시
  docExpansion: 'list'             # 도메인별 접힘
  filter: true                     # 검색
```

**개발 워크플로우**:
1. Swagger UI 접속 → "Authorize" → `x-auth-token` 입력
2. 도메인 펼침 → "Try it out" → 요청 실행
3. 응답 + curl 명령 복사 가능

---

## 7. API 호출 인계 시 체크 포인트

1. **`x-auth-token` 우선** — `Authorization` fallback. 게이트웨이 설정에 따라 다름.
2. **새 엔드포인트 추가 시**:
   - `@ApiTags`, `@ApiBearerAuth('bearer')`, `@ApiOperation`, `@ApiResponse` 빠짐없이
   - DTO에 `class-validator` 데코레이터 + Swagger `@ApiProperty`
3. **에러 응답 일관성**: NestJS `HttpException` 사용. 직접 `res.status(...).json(...)` 금지.
4. **민감 정보 로그 금지**: 토큰 전체나 비밀번호는 로그에 출력 금지. `AuthMiddleware` 의 console.log 다수는 운영 환경에서 줄여야 함.
5. **트래픽 모니터링**: 신규 엔드포인트 추가 시 게이트웨이 라우팅 규칙도 함께 업데이트.
6. **버전닝**: 현재 `v1` 만 존재. Breaking change 시 `v2` 별도 controller 분리.

---

## 8. 프론트엔드에서 호출하는 방법

[asst-web/src/api/config/path.ts](../../asst-web/src/api/config/path.ts) 에 경로 정의:

```typescript
export const path = {
  ADVISOR: {
    PREFIX: `/asst/v1`,
    API_PREFIX: process.env.ASST_API_PREFIX ?? `/aicc/asst-service`,
    API: {
      CENTERS: `/centers`,
      SUMMARY: `/summary`,
      // ...
    },
  },
};
```

`apiPlugin.ts` 의 axios 인스턴스를 통해 호출:

```typescript
import { advisorApi } from '@/api/apiPlugin';
await advisorApi.post(path.ADVISOR.API.SUMMARY, { callstats_id, keyword_count });
```

`x-auth-token`은 axios interceptor에서 자동 부착.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## How to work in this repo (READ FIRST)

Before scanning the codebase for an analysis or task request:
## 대화 지시사항 (항상 준수)
- **언어:** 사용자와 항상 한국어로 대화한다. 친근한 반말 OK(사용자가 편하게 여김).
- **확정 후 작업:** 코드 수정 전 사용자에게 이해한 내용을 정리해 **확정받고** 진행한다. 추측으로 무조건 수정하지 않는다.
- **대화 기록:** 모든 대화는 `CLAUDE-history.md` 에 순차 기록한다. 매 턴 즉시 저장이 아니라 **적당한 시기(대화 2~3턴 진행될 때마다)** 에 이전 마지막 항목에 **이어서** 저장한다(번호 연속, 날짜 헤더 유지). `CLAUDE.md` 에는 사용자가 별도로 지정할 때만 저장한다.
1. **Read this `CLAUDE.md` first** and rely on it as the map of the system (architecture, DB connection flow, schema-migration rules, service locations, deploy branch). Most "where/how does X work" answers are already documented here.
2. **Then open only the minimum set of files** actually needed for the task — start from the specific file/section this doc points to (e.g. `dynamic-database.service.ts` for DB connections, the relevant `src/advisor/{domain}/` module for a feature). Do NOT read the whole repo or broad directory sweeps unless the task genuinely requires it.
3. If `CLAUDE.md` and the code disagree, trust the code, then update this doc.

The goal is fast, targeted answers with minimal file reads — use this doc to decide *which* files to open, not to open everything.

## Project Overview

**asst-service** is a NestJS backend microservice (Advisor Assistant Service) for a call center platform. It provides APIs for agent management, call statistics, coaching, bookmarks, memos, notices, todos, LLM-powered call summaries, and real-time notifications via Socket.IO. The service supports multi-tenant architecture with per-tenant dynamic database connections.

## Commands

```bash
# Development
npm run start:dev          # Local dev with watch (NODE_ENV=local)
npm run start:dev:env      # Dev environment with watch (NODE_ENV=development)
npm run start:debug        # Debug mode with inspector

# Build
npm run build              # Compile TypeScript (nest build)

# Test
npm test                   # Unit tests (Jest)
npm run test:watch         # Watch mode
npm run test:cov           # Coverage report
npm run test:e2e           # E2E tests

# Lint & Format
npm run lint               # ESLint with auto-fix
npm run format             # Prettier formatting
```

## Architecture

### Multi-Tenant Dynamic Database

The core architectural pattern is **multi-tenant isolation via dynamic database connections**:

1. `AuthMiddleware` extracts bearer token from `x-auth-token` header
2. `DynamicDatabaseService` creates/reuses per-tenant `DataSource` (TypeORM) connections by querying the tenant's DB config. **The DB config is fetched from `USER_HOST`** (`GET {USER_HOST}/api/configs/get_configs?filters=db_config`) in `TenantConfigService` — despite the name, it is NOT `TENANT_HOST`.
3. `DbCleanupInterceptor` handles connection lifecycle cleanup after each request
4. Toggle: `DB_DIRECT_CON=1` uses a static connection from `.env` (`DB_HOST`/`DB_PORT`/... — local dev), `DB_DIRECT_CON=0` uses dynamic per-tenant connections (deployed environments)

#### How `DB_DIRECT_CON=0` resolves the target DB

- The bearer token is sent to `USER_HOST`, which returns `configs.db_config` — a connection string `postgresql://user:pass@host:port/database`. `TenantConfigService.parseDbConfig()` parses it, then a new `DataSource` connects to that host. Connections are cached per `tenant_id`.
- **The actual DB server is NOT in any env var** — it comes from the per-tenant `db_config` response. To inspect it: `curl -s '{USER_HOST}/api/configs/get_configs?filters=db_config' -H 'x-auth-token: <token>'`.
- The dev tenant DB is an **AWS Aurora RDS inside a private VPC** (resolves to a private IP like `10.21.x.x`). It is **NOT reachable from a local machine** — running locally with `DB_DIRECT_CON=0` produces a 30s `Connection terminated due to connection timeout`.
- **Local development must use `DB_DIRECT_CON=1` + a local PostgreSQL.** To reach a remote tenant DB from local, open an SSH/SSM tunnel and set `DB_PROXY_HOST`/`DB_PROXY_PORT` — the service then connects through the proxy instead of the `db_config` host (see `dynamic-database.service.ts` proxy handling).

### Deployment / Branches

- **The service is deployed from the `develop` branch only.** The project is still in the development phase; **`main` is unused** — do NOT treat `main` as the source of truth when analyzing what is live. (e.g. `runSchemaMigrations` exists on `develop` but not on `main`; that's expected.)
- Deployed environment runs with `NODE_ENV=development` (see `docker-compose.dev.yml`); `Dockerfile`'s default CMD uses `NODE_ENV=production`, but the actual dev deploy overrides it to `development`.
- Local dev runs with `NODE_ENV=local` (`npm run start:dev`).

### Module Structure

All business logic lives in `src/advisor/` with sub-modules per domain (agent, call, coaching, summary, todo, etc.), each following **Controller → Service → Entity** pattern. Shared infrastructure (auth, guards, interceptors, gateways, dynamic DB) is in `src/common/`.

### Key Services

- **`DynamicDatabaseService`** (`src/common/services/dynamic-database.service.ts`) — Per-tenant DataSource pool management
- **`LlmOrchestratorService`** (`src/common/services/llm-orchestrator.service.ts`) — Proxies LLM calls for summaries and auto-generated todos
- **`SocketGateway`** (`src/common/gateways/socket.gateway.ts`) — Socket.IO gateway for real-time agent status broadcasts
- **`UserInfoService`** (`src/common/services/user-info.service.ts`) — Fetches user/account info from external user service

### External Service Dependencies

| Service | Env Variable | Purpose |
|---------|-------------|---------|
| User Service | `USER_HOST` | User/agent info lookup **and per-tenant DB config** (`/api/configs/get_configs?filters=db_config`) |
| Tenant Mgmt | `TENANT_HOST` | Tenant management (note: per-tenant **DB config is fetched from `USER_HOST`**, not here) |
| LLM Orchestrator | `LLM_ORCHESTRATOR_HOST` | Prompt-based LLM calls (dev host: `dev-ecp-llm-orchestrator-service.langsa.ai`; the old `dev-aicc.langsa.ai` is dead → `ENOTFOUND`/NXDOMAIN) |
| LLM Manager | `LLM_HOST` | Call summarization (fallback) |
| CE Service | `CE_HOST` | Call Experience integration |

### Proxy Controllers (`src/common/proxy/`)

These controllers proxy requests to external services via `HttpClientService` (`{SERVICE}_HOST` + path, forwarding `req.token` as `X-Auth-token`). Active: knowledge, ce, qa, user, audio. `ta-proxy` is **fully commented out (inactive)**.

- **Every proxy controller needs `@ApiBearerAuth('bearer')`** on the class. Without it, **Swagger UI does not attach the Authorize token** to that endpoint's requests → `AuthMiddleware` sees no token → 401 "토큰이 없습니다". (This decorator is Swagger-only; it has no effect on the actual middleware logic. All 6 proxy controllers were missing it and got fixed.)
- **Upstream path prefixes differ per service — verify against the upstream's own Swagger (`{HOST}/docs`).** e.g. AICM/knowledge endpoints live under **`/api/aicm/v1/...`**, NOT `/api/...` (knowledge-proxy calls `${AICM_HOST}/api/aicm/v1/dashboard/popular` etc.). `AICM_HOST` = `KNOWLEDGE_HOST` = `https://dev-ecp-aicm-service.langsa.ai`.

### Gateway routing (404 debugging)

The deployed/web path goes through a gateway (Spring Cloud Gateway, separate repo). Route rule:
```
Path=/aicc/asst-service/**  →  StripPrefix=2 (drops /aicc/asst-service)  →  PrefixPath=/api/asst/v1
# /aicc/asst-service/proxy/knowledge/dashboard/popular  →  /api/asst/v1/proxy/knowledge/dashboard/popular
```
Local gateway profile points `asst-service.uri` at `http://localhost:3000`.

**When a proxy endpoint 404s, isolate the layer:**
1. **Gateway** — does another proxy under the same gateway path work (e.g. `GET /aicc/asst-service/proxy/user/get_user` → 200)? If yes, gateway + routing + asst-service routes are all fine.
2. **asst-service route** — exists if Swagger (`:3000` direct) reaches it (even a 401 means the route exists; 404 = route missing).
3. **Upstream path/host** — the proxy may be calling the wrong upstream path. **`curl` the upstream directly**: 404 on every path incl. `/health` = wrong host/service; 404 on one path but 405/422/409 on the right prefix = path prefix is wrong (the real case here: `/api/...` → `/api/aicm/v1/...`).

A `409 {"detail":"해당 workspace가 존재하지 않습니다"}` from a proxy is the **upstream's** valid response (data issue: workspace_id not in AICM), not a proxy bug.

### Database

- **ORM**: TypeORM 0.3.x with PostgreSQL
- **Schemas**: `advisor` (business tables), `raw_call` (call statistics)
- **Entities**: Must be registered in **4 spots kept in sync**: the `import` + the dynamic `entities` array + the static `entities` array inside `src/common/services/dynamic-database.service.ts`, PLUS the array in `src/config/database.config.ts`.
  - ⚠️ The dynamic and static arrays use **different indentation** (the dynamic one is nested deeper), so a single find-replace will NOT update both — add to each by hand and re-grep to confirm.
  - Missing an entity throws `No metadata for "X" was found` at runtime. Because the **static** array serves `DB_DIRECT_CON=1` (local) and the **dynamic** array serves `DB_DIRECT_CON=0` (deployed), omitting it from just one array breaks **only that environment** (e.g. works in deploy but fails locally). `IntentFeedback` is currently missing from both runtime arrays (only in `database.config.ts`, which is never wired up) so it fails everywhere.
- **Migrations**: SQL files in `migrations/` (kept as change history; applied manually)

### Schema Changes & Migrations (IMPORTANT)

Because of the multi-tenant design, **every tenant has its own database**, and each environment (local / dev) has its own set of tenant DBs. There is no single DB to ALTER. Three mechanisms keep schemas in sync — understand which to use:

| Mechanism | Where | Runs | Scope |
|-----------|-------|------|-------|
| ① `synchronize` | entity classes | on every connection init | **only when `NODE_ENV === 'local'`** (off on deployed envs) |
| ② `runSchemaMigrations` → `addColumnIfNotExists` (and raw `CREATE ... IF NOT EXISTS`) | `dynamic-database.service.ts` (~line 410) | **on every connection creation**, idempotent | all envs/tenants |
| ③ `migrations/*.sql` | `migrations/` folder | manual (someone runs the SQL directly on each DB) | only DBs a human runs it on |

`synchronize` is gated on `process.env.NODE_ENV === 'local'` in all three places (`dynamic-database.service.ts` static & dynamic options, `database.config.ts`). So on deployed environments it is **off** — schema changes there are driven by mechanism ② (and ③), NOT by synchronize. **Mechanism ② is the primary, safe way to evolve deployed schemas** and is already live on the `develop` deployment (it currently provisions the `coachings.coaching_request_id / sender_name / customer_name` columns).

**Recommended workflow to ADD a column (auto-applies to local + deployed + every tenant, no per-env SQL, no RDS access needed):**
1. Add the field to the entity class (keeps code consistent; also drives `synchronize` for local).
2. Add one `addColumnIfNotExists(dataSource, 'advisor', '<table>', '<column>', '<DDL e.g. VARCHAR(100) NULL>')` call inside `runSchemaMigrations()`.
3. Deploy (to `develop`). Each tenant DB gets the column on its next connection. (Optionally also record the change as a `migrations/*.sql` file for history.)

**To add a new TABLE or SCHEMA** — same mechanism, with raw idempotent SQL inside `runSchemaMigrations()`:
```ts
await dataSource.query(`CREATE SCHEMA IF NOT EXISTS advisor`);
await dataSource.query(`CREATE TABLE IF NOT EXISTS advisor.my_table ( id VARCHAR(64) PRIMARY KEY, ... )`);
```
For a new table you ALSO need a TypeORM entity registered in **all 4 entity spots** (see Database section), or `getRepository()` throws `EntityMetadataNotFoundError` / `No metadata for "X" was found`.

**Raw SQL must be PostgreSQL-flavored AND idempotent** (it re-runs on every connection):
- `enum('a','b')` is MySQL/MariaDB syntax — invalid in PG. Use `VARCHAR(n) NOT NULL CHECK (col IN ('a','b'))` (this codebase has zero native PG enums). Use `TIMESTAMPTZ` for timestamps.
- `CREATE TRIGGER` does NOT support `IF NOT EXISTS`, so it is not idempotent and will error on re-run. For `updated_at` auto-update, prefer TypeORM `@UpdateDateColumn` at the app layer (the convention all existing tables follow) instead of a DB trigger.

**After adding an entity or a `runSchemaMigrations` change, fully RESTART the server** (Ctrl+C then `npm run start:dev`). `DataSource`s are cached in the `connections` Map for the process lifetime, so a still-alive connection keeps using the OLD entity list / skips the new migration. Watch-mode auto-restart is not always enough — if you see `No metadata for "X"` right after registering X, a stale cached connection is the cause; restart clears the Map.

A worked example of all this lives in the `emotion` domain (`advisor.emotions` table created via `runSchemaMigrations`, entity in all 4 spots, `EmotionService` reused by `SummaryService`).

**Idempotency / re-deploy behavior:**
- `addColumnIfNotExists` checks `information_schema` first; `CREATE ... IF NOT EXISTS` is a no-op when the object exists. Re-deploying the same source is safe — existing objects are skipped, no error. `runSchemaMigrations` is also wrapped in try/catch (`:438-443`) so a failing migration logs a warning but never crashes the service.
- **Caveat — "exists" is checked by NAME only.** Changing the body of an already-existing object is NOT applied: a `CREATE TABLE IF NOT EXISTS` whose table already exists is skipped entirely, and `addColumnIfNotExists` skips when the column exists (so a `VARCHAR(100)→VARCHAR(200)` type/length change is ignored). Mechanism ② is **add-only**.

**Cautions:**
- Mechanism ② is for additive changes only. **Destructive/structural changes** (column/table drop, type or length change, constraints, data backfill) are NOT handled by it. Do those via `migrations/*.sql`, or via explicit idempotent `ALTER` raw SQL in `runSchemaMigrations()`.
- `migrations/*.sql` is **applied manually** — someone with DB access runs it on each DB. Since deployed tenant DBs are AWS RDS in a private VPC (no direct access for most devs), this means asking a DBA/infra owner to run it per tenant. Prefer mechanism ② whenever the change is additive, so a plain deploy handles it without RDS access.

### API

- Base path: `/api/asst/v1` (configurable via `API_BASE_PATH`)
- Swagger docs: `{basePath}/doc`
- Auth: Bearer token via `x-auth-token` header (except `GET /health/check`)
- Input validation: `class-validator` with global `ValidationPipe` (whitelist + forbidNonWhitelisted)

## Feature: Emotion & Risk Analysis (감정·이슈 분석) — status & roadmap

Ongoing feature work. Captured here so it can be resumed later.

### Implemented (post-call emotion)
- **What**: LLM analyzes customer emotion from a call and stores it.
- **Flow (hybrid)**: write is integrated into post-call summary, read is a separate endpoint.
  - `POST /summary` (`SummaryService.summarizeCall`) → analyzes emotion → auto-upserts to `advisor.emotions` (write failure does not block the summary; wrapped in try/catch).
  - `GET /emotion/data/:callstats_id` → reads stored emotion.
  - `POST /emotion/analyze` (`{ conversation, save?, callstats_id? }`) → **test/debug** endpoint: analyzes emotion straight from a conversation string (no callstats data needed). Remove before prod if undesired.
- **Table** `advisor.emotions`: `callstats_id`(PK), `icon_type`(negative/neutral/positive/etc, VARCHAR+CHECK), `score`(double precision, nullable), `description`, `created_at`, `updated_at`.
- **Mapping**: LLM returns `EmotionDto` (type: calm/neutral/angry/sad/happy + score + summary); `EmotionService.mapEmotionTypeToIconType()` maps the 5 types → 4 `icon_type` values (angry/sad→negative, happy/calm→positive, neutral→neutral, else→etc). **This mapping is intentionally isolated in one method** because it changes as the LLM prompt evolves.
- **Key files**: `src/advisor/emotion/` (entity/service/controller/dto), `SummaryService.analyzeEmotion()` + `classifyEmotion()` (prompt lives here), `summary-response.dto.ts` (`EmotionDto`/`EmotionType`).

### Planned (3-axis emotion & issue analysis)
Goal is to expand from emotion-only to **3 analysis axes**: 고객 감정(emotion) / 민원 위험(complaint risk) / 이탈 징후(churn risk), each with **evidence quotes** from the dialogue and **recommended follow-up actions**. The prompt must go beyond keyword/profanity detection: understand complaint intent **in context** and **propose next actions**. (Draft schema + prompt strategy discussed; not yet built.)

### Architecture decision — two tracks (different timing)
The two needs run at different times and must NOT be forced into one call/table:
- **Track A — post-call** (요약 버튼 / `summarizeCall`): emotion (+ final complaint/churn verdict) computed on the **full** conversation, stored for reporting. Low-latency not required. *Emotion part is already done.*
- **Track B — real-time** (통화 중): complaint/churn **early detection** on partial/streaming dialogue, pushed to agent/supervisor immediately. Latency-sensitive.

### Real-time infra that already exists (for Track B)
- `POST /assist-stream` (`AssistStreamService.stream`, tag "AI 상담 보조"): receives **per-utterance** `query` + `conversationHistory` + `callId`, and **SSE-relays** "근거문서 Top5 + 요약 + LLM 답변" from an external RAG service (`SEARCH_HOST` `/api/v1/rag/assist-stream`). It is a **proxy/relay — asst-service does NOT call the LLM itself here**; the external RAG service does.
- `SocketGateway` (Socket.IO) for real-time push to clients.
- So real-time dialogue already flows through this service — a natural attach point for Track B.

### OPEN DECISIONS (not yet decided — decide before building Track B)
1. **Where to attach real-time complaint/churn analysis**:
   - **Option A** — in `assist-stream.service` itself: call analysis LLM (reuse `LlmOrchestratorService`) in parallel with the RAG relay, emit as extra SSE event or Socket push. Pros: our control, reuse emotion prompt assets. Cons: per-utterance LLM cost/latency (would need triggers/throttling).
   - **Option B** — delegate to the external RAG service (`SEARCH_HOST`): have it include complaint/churn events in the assist-stream response; we just relay. Pros: RAG already holds context/LLM. Cons: external-team dependency, less control.
2. **Storage shape** when axes grow to 3: extend `emotions` table (add score/complaint_*/churn_* columns) **vs** a new `call_risk_analysis` table grouping all axes per call (recommended if axes grow).
3. **Model**: emotion uses `gpt-4o-mini`; contextual complaint understanding + action proposal may need a stronger model.

## Adding a New API

1. Create entity in `src/advisor/{domain}/entities/`
2. Create DTOs in `src/advisor/{domain}/dto/`
3. Create service in `src/advisor/{domain}/services/`
4. Create controller in `src/advisor/{domain}/controllers/`
5. Register all in `src/advisor/advisor.module.ts`
6. Add entity to the entities arrays in **both** `src/config/database.config.ts` and `src/common/services/dynamic-database.service.ts` (dynamic + static) — see Database section

## Commit Message Convention

Commit messages must be in **Korean** (types stay in English). Format:

```
<type>: <한글 제목>

- <변경사항 1>
- <변경사항 2>
```

Types: `feat`, `fix`, `refactor`, `style`, `docs`, `test`, `build`, `chore`

## Code Style

- **Absolute imports** using `@app/*` path alias (enforced by ESLint)
- Husky pre-commit hook runs lint-staged
- Commitlint enforces conventional commit format

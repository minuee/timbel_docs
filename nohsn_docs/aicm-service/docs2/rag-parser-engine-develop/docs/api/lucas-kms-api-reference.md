# Lucas-KMS API Reference

> Lucas-KMS — Knowledge Management System (단독 배포 / standalone)
> 외부 개발자·통합 파트너용 완전 통합 가이드. 본 문서만으로 즉시 호출 가능.

- **버전**: 1.0.0 (KMS-Plus 브랜치 기준)
- **앱 진입점**: `src/api/main_kms.py` (`create_kms_app()` factory)
- **기본 포트**: `5101`
- **OpenAPI**: `/docs` (Swagger UI), `/redoc` (Redoc), `/openapi.json`
- **공식 prefix**: `/api/v1/*` — 통합 솔루션 (Locus) 와 동일. agent / chat / skill / tool / external-agent / scheduler 라우터는 *포함되지 않음*.

> **무인증 모드 기본**: `LUCAS_AUTH_DISABLED=true` 가 default. 키·토큰 없이 즉시 호출 가능. 본 문서의 모든 예시는 *무인증 모드 가정*. 인증 모드는 §1 에 별도 명시.

---

## 0. 시작하기 (Quick Start)

### 0.1 기동

```bash
# Docker Compose 로 일괄 기동 (Postgres / Redis / Qdrant / Elasticsearch / Kafka + API)
docker compose -f docker-compose.lucas-kms.yml up -d

# 단독 기동 (의존 서비스가 이미 떠 있다고 가정)
uvicorn src.api.main_kms:create_kms_app \
  --factory \
  --host 0.0.0.0 \
  --port 5101 \
  --workers 2
```

기동 확인:

```bash
curl -s http://localhost:5101/health
# {"status":"ok"}

curl -s http://localhost:5101/health/live
# {"status":"alive"}

curl -s http://localhost:5101/health/ready | jq .
# {
#   "status": "ready",
#   "checks": {
#     "postgres": {"status": "ok"},
#     "redis": {"status": "ok"},
#     "qdrant": {"status": "ok"},
#     "elasticsearch": {"status": "ok"}
#   }
# }
```

### 0.2 무인증 / 인증 모드 차이

| 항목 | 무인증 (`LUCAS_AUTH_DISABLED=true`) | 인증 (`LUCAS_AUTH_DISABLED=false`) |
|---|---|---|
| 호출 헤더 | (선택) `X-Tenant-Id` | `Authorization: Bearer <jwt>` 필수 |
| Tenant 결정 | `LUCAS_DEFAULT_TENANT_ID` 또는 `X-Tenant-Id` | JWT payload `tenant_id` |
| User 결정 | `LUCAS_DEFAULT_USER_ID` | JWT payload `sub` |
| RBAC | bypass (admin 동등) | role-based (owner/admin/editor/viewer) |
| cross-tenant path | path `{tenant_id}` 자유 진입 | path `{tenant_id}` 와 JWT `tenant_id` 일치 강제 (403 불일치) |

기본값:
- `LUCAS_DEFAULT_TENANT_ID` = `00000000-0000-0000-0000-000000000001`
- `LUCAS_DEFAULT_USER_ID` = `00000000-0000-0000-0000-000000000001`

### 0.3 공통 헤더

| 헤더 | 필요 | 설명 |
|---|---|---|
| `Content-Type` | POST/PATCH 시 | `application/json` 또는 `multipart/form-data` (파일 업로드) |
| `Authorization` | 인증 모드 | `Bearer <access_token>` |
| `X-Tenant-Id` | 선택 | UUID — 인증 모드에서 path 와 JWT 가 불일치하면 403 |
| `X-User-Id` | 선택 | 일부 legacy endpoint (`apply_classification` 등) 의 audit 식별 |
| `Accept` | 선택 | SSE 호출 시 `text/event-stream` 권장 |

### 0.4 ApiResponse 응답 wrapper

거의 모든 응답이 다음 형태로 래핑:

```json
{
  "success": true,
  "data": { /* 실제 payload */ },
  "error": null
}
```

에러 시:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "TENANT_ID_REQUIRED",
    "message": "X-Tenant-Id 헤더가 필요합니다.",
    "details": {}
  }
}
```

> 일부 인증/health/audit 엔드포인트는 wrap 없이 raw payload 반환 (Auth v2 의 `TokenPair`, `/health/*`, `/api/v1/admin/audit/*`). 각 endpoint 명세 참조.

### 0.5 페이지네이션

```json
{
  "success": true,
  "data": {
    "items": [...],
    "next_cursor": null,
    "total_count": 42
  }
}
```

- `offset` / `limit` query param (대부분), 또는 `page` / `page_size` 호환 alias.
- 기본 `limit=50`, 최대 `limit=100~500` (endpoint 별 다름).

### 0.6 에러 코드 표 (AICMError)

| HTTP | code | 의미 | 발생 조건 |
|---|---|---|---|
| 400 | `TENANT_ID_REQUIRED` | tenant ID 누락 | 인증 모드에서 X-Tenant-Id 부재 |
| 400 | `UNSUPPORTED_FORMAT` | 미지원 포맷 | 업로드 파일 확장자 미지원 |
| 401 | `invalid token` / `expired` | JWT 검증 실패 | Auth v2 모든 endpoint |
| 403 | `TENANT_ISOLATION_VIOLATION` | tenant 격리 위반 | cross-tenant 시도 |
| 403 | `path tenant_id ... 와 ... 불일치` | path/JWT mismatch | Repository CRUD 등 |
| 404 | `{RESOURCE}_NOT_FOUND` | 리소스 없음 | get/update/delete 시 |
| 409 | `duplicate_in_flight_upload` | 동일 제목 업로드 중복 | 업로드 시 같은 title processing 중 |
| 409 | `slug 충돌` / `email already registered` | UNIQUE 충돌 | tenant slug / account email |
| 422 | (pydantic ValidationError) | 검증 실패 | body / query param 형식 |
| 429 | `RATE_LIMIT_EXCEEDED` / assist-stream 동시 상한 | 호출 제한 | 테넌트별 동시 SSE 등 |
| 503 | service_unavailable | 외부 서비스 다운 | Qdrant / vLLM / reranker 등 |
| 5xx | `PIPELINE_{STAGE}_ERROR`, `LLM_ROUTING_FAILED` | 내부 처리 실패 | 파이프라인 / LLM 라우팅 |
| 5xx | `LICENSE_LIMIT_EXCEEDED` | 라이선스 초과 | document / repository quota |

---

## 1. 인증 (Authentication)

### 1.1 무인증 모드 — Lucas-KMS 기본

`LUCAS_AUTH_DISABLED=true` 가 환경 변수 default. JWT 없이 모든 endpoint 호출 가능. `get_current_principal` 이 자동으로:

```json
{
  "user_id": "00000000-0000-0000-0000-000000000001",
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "role": "admin",
  "auth_v2": false,
  "auth_disabled": true
}
```

를 주입. RBAC bypass.

`X-Tenant-Id` 헤더를 전달하면 그 값이 우선 — 무인증이지만 *멀티 테넌트 시뮬레이션* 가능.

### 1.2 인증 모드 — JWT (Auth v2)

운영 배포 시 `LUCAS_AUTH_DISABLED=false` 로 켜고, Auth v2 (`/auth/v2/*` 또는 `/api/v1/auth/v2/*`) 를 사용한다.

#### 1.2.1 POST `/auth/v2/signup`

```bash
curl -X POST http://localhost:5101/auth/v2/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "password": "s3cret-pass-1234",
    "name": "Alice",
    "groups": ["personal"]
  }'
```

응답 (`TokenPair`):

```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": "<account-uuid>",
    "email": "alice@example.com",
    "tenant_id": "<personal-tenant-uuid>",
    "role": "owner",
    "name": "Alice",
    "groups": ["personal"]
  }
}
```

- `groups`: `personal` (default) / `sole_proprietor`. `company` / `business` 는 별도 활성화 endpoint.
- `password`: 8-200 자.
- 동일 email 재가입 시 `409`.

#### 1.2.2 POST `/auth/v2/login`

```bash
curl -X POST http://localhost:5101/auth/v2/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "s3cret-pass-1234"}'
```

응답 동일 `TokenPair`. 실패 시 401 (`invalid credentials` / `account disabled` / `no password set`).

#### 1.2.3 POST `/auth/v2/refresh`

```bash
curl -X POST http://localhost:5101/auth/v2/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<eyJhbGc...>"}'
```

응답 (`AccessOnly`):

```json
{ "access_token": "eyJhbGc...", "token_type": "bearer" }
```

> refresh 자체는 회전 (rotation) 하지 않음 — 후속 보안 강화 단계에서 도입.

#### 1.2.4 GET `/auth/v2/me`

```bash
curl http://localhost:5101/auth/v2/me \
  -H "Authorization: Bearer <access_token>"
```

응답 (`MeResponse`):

```json
{
  "user_id": "<uuid>",
  "email": "alice@example.com",
  "tenant_id": "<uuid>",
  "role": "owner",
  "name": "Alice",
  "display_name": null,
  "preferences": {"user_groups": ["personal"]}
}
```

### 1.3 토큰 만료 / refresh 흐름 (Python)

```python
import httpx
from datetime import datetime, timedelta

BASE = "http://localhost:5101"

class LucasClient:
    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._expires_at: datetime | None = None

    def login(self) -> None:
        r = httpx.post(f"{BASE}/auth/v2/login", json={
            "email": self._email, "password": self._password,
        })
        r.raise_for_status()
        body = r.json()
        self.access_token = body["access_token"]
        self.refresh_token = body["refresh_token"]
        # JWT exp 는 별도 디코딩 필요 — 여기선 15분 보수적 추정
        self._expires_at = datetime.utcnow() + timedelta(minutes=15)

    def _ensure(self) -> None:
        if self.access_token is None:
            self.login()
            return
        if self._expires_at and datetime.utcnow() > self._expires_at - timedelta(seconds=30):
            r = httpx.post(f"{BASE}/auth/v2/refresh", json={
                "refresh_token": self.refresh_token,
            })
            if r.status_code == 401:
                self.login()
                return
            self.access_token = r.json()["access_token"]
            self._expires_at = datetime.utcnow() + timedelta(minutes=15)

    def headers(self) -> dict:
        self._ensure()
        return {"Authorization": f"Bearer {self.access_token}"}
```

### 1.4 JS 예시 (fetch)

```javascript
async function login(email, password) {
  const r = await fetch("http://localhost:5101/auth/v2/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({email, password}),
  });
  if (!r.ok) throw new Error(`login failed: ${r.status}`);
  return await r.json();
}

async function me(accessToken) {
  const r = await fetch("http://localhost:5101/auth/v2/me", {
    headers: {"Authorization": `Bearer ${accessToken}`},
  });
  return await r.json();
}
```

---

## 2. Tenant 관리

`/api/v1/tenants` (Auth v2 호환). 무인증 모드에서는 path `{tenant_id}` 자유 진입. 인증 모드는 JWT `tenant_id` 와 path 의 멤버십 일치 강제.

### 2.1 GET `/api/v1/tenants` — 내 tenant 목록

```bash
curl http://localhost:5101/api/v1/tenants \
  -H "Authorization: Bearer <access_token>"
```

응답 (`TenantListOut`):

```json
{
  "items": [
    {
      "id": "<uuid>",
      "name": "Alice 개인",
      "slug": "personal_e_alice",
      "tenant_type": "personal",
      "role": "owner",
      "is_active": true,
      "created_at": "2026-05-19T14:00:00"
    }
  ]
}
```

### 2.2 POST `/api/v1/tenants` — 신규 tenant 생성

권한: `auth_disabled=True` (무인증 모드) **또는** `role=admin`.

**Body** (`TenantCreate`):

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `name` | string (1-200) | yes | tenant 표시명 |
| `slug` | string (≤100) | no | 비어있으면 `name` 에서 자동 슬러그화 |
| `tenant_type` | string | no | default `corporate` |
| `plan` | string | no | default `standard` |
| `description` | string | no | `config.description` 으로 저장 |

```bash
curl -X POST http://localhost:5101/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "공공기관 SaaS 데모", "description": "운영 데모용"}'
```

응답 (`TenantOut`):

```json
{
  "id": "<uuid>",
  "name": "공공기관 SaaS 데모",
  "slug": "tenant-a1b2c3d4",
  "tenant_type": "corporate",
  "role": "admin",
  "is_active": true,
  "created_at": "2026-05-19T14:05:00"
}
```

**에러**:
- 403 — admin 아니고 무인증 모드도 아님
- 409 — `slug 충돌 — 이미 존재` (명시적 slug 지정 권장)
- 422 — name 빈 문자열

### 2.3 GET `/api/v1/tenants/{tenant_id}` — 상세

응답: `TenantOut`. 401/403/404 처리는 §0.6 표.

### 2.4 PATCH `/api/v1/tenants/{tenant_id}` — 수정

owner / admin 만. Body (`TenantPatch`):

```json
{ "name": "...", "config": { /* JSON */ } }
```

null 필드는 기존 값 유지.

### 2.5 POST `/api/v1/tenants/{tenant_id}/switch` — 활성 전환

```bash
curl -X POST http://localhost:5101/api/v1/tenants/<tid>/switch \
  -H "Authorization: Bearer <token>"
```

응답:

```json
{
  "access_token": "eyJ...new...",
  "tenant_id": "<tid>",
  "role": "admin"
}
```

JWT 의 `tenant_id` 클레임만 갱신된 새 토큰.

### 2.6 GET `/api/v1/tenants/{tenant_id}/members` — 멤버 목록

응답:

```json
{
  "items": [
    {
      "account_id": "<uuid>",
      "name": "Alice",
      "email": "alice@example.com",
      "phone": null,
      "role": "owner"
    }
  ]
}
```

### 2.7 다중 테넌트 운영 패턴

- **B2C SaaS**: 가입 시 `tenant_type=personal` 자동 생성. 각 user 가 단독 tenant.
- **B2B 통합**: `POST /tenants` (admin) 로 customer 별 tenant 생성 → 멤버 초대 → 멤버는 `/switch` 로 활성 변경.
- **공공 SaaS 데모**: 무인증 모드 + path `{tenant_id}` 명시. 같은 API 호출자가 여러 tenant 를 자유 전환.

---

## 3. Repository (저장소) 관리

repo 는 tenant 안의 **지식 풀(pool)** 단위. 하나의 repo 안 문서들이 같은 검색 컬렉션·랭킹 정책을 공유한다.

### 3.1 GET `/api/v1/tenants/{tenant_id}/repositories` — 목록

**Path / query**:
- `tenant_id` (UUID, path)
- `is_active` (bool, optional)
- `offset` (int, default 0), `limit` (int, default 50, max 100)

```bash
curl "http://localhost:5101/api/v1/tenants/<tid>/repositories?is_active=true&limit=20"
```

응답 (`ApiResponse[PaginatedResponse[RepositoryResponse]]`):

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "<uuid>",
        "tenant_id": "<tid>",
        "name": "공공 SaaS 가이드",
        "description": "외부 배포용",
        "config": {},
        "is_active": true,
        "created_at": "2026-05-19T14:00:00Z",
        "updated_at": "2026-05-19T14:00:00Z",
        "document_count": 42,
        "chunk_count": 1820,
        "kind_summary": {
          "sop_doc_count": 5,
          "manual_doc_count": 30,
          "faq_doc_count": 4,
          "policy_doc_count": 2,
          "glossary_doc_count": 1
        }
      }
    ],
    "total_count": 1
  }
}
```

### 3.2 POST `/api/v1/tenants/{tenant_id}/repositories` — 생성

**Body** (`RepositoryCreate`):

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `name` | string (1-200) | yes | tenant 내 unique |
| `description` | string | no | 검색 분류기에 도메인 힌트로도 사용 |
| `config` | object | no | 파이프라인 / 검색 오버라이드 |

```bash
curl -X POST http://localhost:5101/api/v1/tenants/<tid>/repositories \
  -H "Content-Type: application/json" \
  -d '{
    "name": "공공 SaaS 가이드",
    "description": "공공기관 도입 매뉴얼 + 운영 FAQ"
  }'
```

응답 (201, `ApiResponse[RepositoryResponse]`):

```json
{
  "data": {
    "id": "<uuid>",
    "tenant_id": "<tid>",
    "name": "공공 SaaS 가이드",
    "description": "공공기관 도입 매뉴얼 + 운영 FAQ",
    "is_active": true,
    "created_at": "2026-05-19T14:10:00Z",
    "document_count": 0,
    "chunk_count": 0,
    "kind_summary": { "sop_doc_count": 0, "manual_doc_count": 0, "faq_doc_count": 0, "policy_doc_count": 0, "glossary_doc_count": 0 }
  }
}
```

**에러**:
- 403 — path tenant 와 인증 tenant 불일치
- 409 — repo name 중복 (UniqueConstraint `tenant_id+name`)
- 422 — name 검증 실패
- 5xx — `LICENSE_LIMIT_EXCEEDED` (repositories quota 초과)

### 3.3 GET `/api/v1/repositories/{repo_id}` — 상세

응답: `ApiResponse[RepositoryResponse]` — §3.1 의 단일 item 과 동일.

### 3.4 PATCH `/api/v1/repositories/{repo_id}` — 수정

**Body** (`RepositoryUpdate`) — 모두 optional:

```json
{
  "name": "공공 SaaS 가이드 v2",
  "description": "...",
  "config": {},
  "is_active": true
}
```

> path 에 `tenant_id` 가 없고 dependency 가 인증된 tenant_id 를 주입한다 (cross-tenant 자동 차단).

### 3.5 DELETE `/api/v1/repositories/{repo_id}` — soft delete

```bash
curl -X DELETE http://localhost:5101/api/v1/repositories/<rid>
```

응답:

```json
{ "success": true, "data": {"deleted": true} }
```

`is_active=false` 로 마킹. 문서/블럭은 보존.

### 3.6 Python 예시

```python
import httpx

BASE = "http://localhost:5101/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

# 생성
r = httpx.post(
    f"{BASE}/tenants/{TENANT}/repositories",
    json={"name": "공공 SaaS 가이드", "description": "..."},
    timeout=15.0,
)
r.raise_for_status()
repo = r.json()["data"]
repo_id = repo["id"]

# 목록
r = httpx.get(f"{BASE}/tenants/{TENANT}/repositories")
for item in r.json()["data"]["items"]:
    print(item["name"], item["document_count"])
```

### 3.7 JS 예시

```javascript
const BASE = "http://localhost:5101/api/v1";
const TENANT = "00000000-0000-0000-0000-000000000001";

const r = await fetch(`${BASE}/tenants/${TENANT}/repositories`, {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({name: "공공 SaaS 가이드", description: "..."}),
});
const {data: repo} = await r.json();
console.log(repo.id);
```

---

## 3a. Repository Groups (저장소 그룹)

tenant 안의 *named subset* — multi-repo 검색 scope 관리.

> 다른 agent 가 진행 중인 KMS-Plus 확장. backend ship 후 본 섹션 endpoint 활성.

### 3a.0 개요

**Use cases**

- 검색 시 *모든 repo* (`tenant_all`) 또는 *지정 repo subset* (`group`) 선택.
- 운영자가 *기본 검색 scope* 로 사용할 default group 지정 (검색 호출 시 `scope: "default"` 만 보내면 자동 group 사용).
- 부서별 / 프로젝트별 repo 묶음 — UI 의 검색창에서 한 번에 선택.

**Constraints**

- name 은 tenant 안에서 unique (`tenant_id + name`).
- `repository_ids` 의 각 UUID 는 *같은 tenant 의 active repo* 여야 한다 — 다른 tenant repo 또는 비활성 repo 포함 시 422.
- `is_default` 는 tenant 당 최대 1 — 새 group 을 default 로 지정하면 기존 default 가 자동 false.

### 3a.1 GET `/api/v1/tenants/{tenant_id}/repository-groups` — 목록

**Path / query**:

- `tenant_id` (UUID, path)
- `offset` (int, default 0), `limit` (int, default 50, max 100)

```bash
curl "http://localhost:5101/api/v1/tenants/<tid>/repository-groups"
```

응답 (`ApiResponse[PaginatedResponse[RepositoryGroupResponse]]`):

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "<uuid>",
        "tenant_id": "<tid>",
        "name": "공공 SaaS 전체",
        "description": "전 부서 공유 자료",
        "repository_ids": ["<rid1>", "<rid2>"],
        "is_default": true,
        "created_at": "2026-05-19T16:00:00Z",
        "updated_at": "2026-05-19T16:00:00Z"
      }
    ],
    "total_count": 1
  }
}
```

### 3a.2 POST `/api/v1/tenants/{tenant_id}/repository-groups` — 생성

**Body** (`RepositoryGroupCreate`):

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `name` | string (1-200) | yes | tenant 내 unique |
| `description` | string | no | 설명 |
| `repository_ids` | UUID[] | yes | 그룹에 속할 repo 들. tenant 소속 active repo 만 허용 |
| `is_default` | bool | no | default 지정 (기존 default 자동 false) |

```bash
curl -X POST http://localhost:5101/api/v1/tenants/<tid>/repository-groups \
  -H "Content-Type: application/json" \
  -d '{
    "name": "공공 SaaS 전체",
    "description": "전 부서 공유 자료",
    "repository_ids": ["<rid1>", "<rid2>"],
    "is_default": true
  }'
```

응답 (201, `ApiResponse[RepositoryGroupResponse]`):

```json
{
  "success": true,
  "data": {
    "id": "<group-uuid>",
    "tenant_id": "<tid>",
    "name": "공공 SaaS 전체",
    "description": "전 부서 공유 자료",
    "repository_ids": ["<rid1>", "<rid2>"],
    "is_default": true,
    "created_at": "2026-05-19T16:05:00Z",
    "updated_at": "2026-05-19T16:05:00Z"
  }
}
```

**에러**:

- 403 — path tenant 와 인증 tenant 불일치
- 409 — group name 중복 (UniqueConstraint `tenant_id+name`)
- 422 — `repository_ids` 안에 다른 tenant repo 또는 비활성 repo 포함

### 3a.3 GET `/api/v1/repository-groups/{group_id}` — 상세

응답: `ApiResponse[RepositoryGroupResponse]` — §3a.1 의 단일 item 과 동일.

### 3a.4 PATCH `/api/v1/repository-groups/{group_id}` — 수정

**Body** (`RepositoryGroupUpdate`) — 모두 optional, None 은 기존 값 유지:

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | string | 새 이름 (tenant unique 재검증) |
| `description` | string | 새 설명 |
| `repository_ids` | UUID[] | 통째 교체 (부분 머지 X). tenant 소속 active 만 |
| `is_default` | bool | true 로 설정 시 기존 default 자동 false |

```bash
curl -X PATCH http://localhost:5101/api/v1/repository-groups/<gid> \
  -H "Content-Type: application/json" \
  -d '{
    "repository_ids": ["<rid1>", "<rid2>", "<rid3>"]
  }'
```

### 3a.5 POST `/api/v1/repository-groups/{group_id}/set-default` — default 지정

지정 group 의 `is_default=true` + 같은 tenant 의 다른 group 의 `is_default=false`.

```bash
curl -X POST http://localhost:5101/api/v1/repository-groups/<gid>/set-default
```

응답 (`ApiResponse[RepositoryGroupResponse]`):

```json
{ "success": true, "data": { "id": "<gid>", "is_default": true, "...": "..." } }
```

### 3a.6 DELETE `/api/v1/repository-groups/{group_id}` — 삭제

```bash
curl -X DELETE http://localhost:5101/api/v1/repository-groups/<gid>
```

응답: `{ "success": true, "data": {"deleted": true} }`.

> default group 삭제 후 남은 group 의 auto-promote 는 backend 정책 — 자동 promote 안 되면 호출자가 `set-default` 로 명시 지정 필요.

### 3a.7 Python 예시

```python
import httpx

BASE = "http://localhost:5101/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

# group 생성
r = httpx.post(
    f"{BASE}/tenants/{TENANT}/repository-groups",
    json={
        "name": "공공 SaaS 전체",
        "description": "전 부서 공유",
        "repository_ids": ["<rid1>", "<rid2>"],
        "is_default": True,
    },
)
r.raise_for_status()
group = r.json()["data"]

# default scope 로 검색 (group 의 repo 만 대상)
s = httpx.post(
    f"{BASE}/search",
    json={"query": "잔고증명서 수수료", "scope": "default", "top_k": 5},
)
print(s.json()["data"]["results"])
```

### 3a.8 JS 예시

```javascript
const BASE = "http://localhost:5101/api/v1";
const TENANT = "00000000-0000-0000-0000-000000000001";

// group 생성
const r = await fetch(`${BASE}/tenants/${TENANT}/repository-groups`, {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    name: "공공 SaaS 전체",
    repository_ids: ["<rid1>", "<rid2>"],
    is_default: true,
  }),
});
const {data: group} = await r.json();

// group scope 로 검색
const s = await fetch(`${BASE}/search`, {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    query: "...",
    scope: "group",
    repository_group_id: group.id,
    top_k: 5,
  }),
});
```

---

## 4. Document (문서) 관리

### 4.1 POST `/api/v1/documents/upload` — 파일 업로드

**Multipart/form-data**:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | binary | yes | PDF / DOCX / XLSX / HTML / MD / TXT |
| `repository_id` | UUID | yes | 대상 repo |
| `title` | string | no | 미지정 시 파일명 |
| `category_ids` | JSON-string | no | `"[\"<uuid>\",\"<uuid>\"]"` |
| `document_type_id` | UUID | no | 문서 유형 (선택) |
| `config_override` | JSON-string | no | 파이프라인 stage 오버라이드 |
| `step_by_step` | bool | no | true 면 각 stage 후 자동 pause |
| `force_new` | bool | no | 동일 title processing 중 문서가 있어도 강제 새 업로드 (기존 archived) |

```bash
curl -X POST http://localhost:5101/api/v1/documents/upload \
  -F "file=@./guide.pdf" \
  -F "repository_id=<rid>" \
  -F 'title=공공기관 가이드 v1' \
  -F 'category_ids=[]'
```

응답 (201):

```json
{
  "success": true,
  "data": {
    "document_id": "<doc-uuid>",
    "status": "processing",
    "step_by_step": false,
    "message": "문서가 업로드되었습니다. 처리가 완료되면 검색 가능합니다."
  }
}
```

**에러**:
- 409 `duplicate_in_flight_upload` — 같은 (repo, title) 의 `processing` / `pending_review` 문서 존재. `force_new=true` 로 우회.
- 400 `UNSUPPORTED_FORMAT` — 미지원 확장자
- 413 — 파일 크기 초과 (기본 ~100MB)
- `LICENSE_LIMIT_EXCEEDED`

대안: `POST /api/v1/repositories/{repo_id}/documents/upload` — path 에 repo 직접 지정 (V2 alias).

### 4.2 처리 라이프사이클

문서 `status` 전이:

```
uploaded
  → parsing       (LLM 기반 PDF/표/이미지 파싱)
  → segmenting    (의미 단위 chunk + block)
  → embedding     (BGE-M3 dense + sparse)
  → pending_review  (step_by_step 모드)
  → active        (검색·RAG 노출)
  ↓
  failed          (어느 stage 든 실패)
  ↓
  archived        (soft delete / 재업로드 시)
```

### 4.3 GET `/api/v1/repositories/{repo_id}/documents` — 목록

**Query**:
- `status` (string) — 필터 (`active`/`processing`/`failed` 등)
- `category_id` (UUID)
- `document_type_id` (UUID)
- `offset` (default 0), `limit` (default 50, max 500)
- `page` / `page_size` (1-based, offset/limit 대체)

응답: `ApiResponse[PaginatedResponse[DocumentResponse]]`. `DocumentResponse` 주요 필드:

| 필드 | 타입 | 의미 |
|---|---|---|
| `id`, `repository_id`, `title`, `description` | | |
| `repository_name` | string | 동봉 (편의) |
| `source_file` | string | 저장 경로 |
| `source_format` | string | pdf / docx / xlsx / md / html / txt / note |
| `version` | int | 버전 (rollback 가능) |
| `status` | string | 라이프사이클 |
| `search_excluded` | bool | true 면 검색/RAG 제외 |
| `folder_id` | UUID? | 라이브러리 폴더 (NULL=root) |
| `is_sop` | bool | SOP 분류 (검색 좁히기) |
| `processing_meta` | object | stage / progress / classification 등 |
| `category_ids` | UUID[] | N:M 카테고리 |

### 4.4 GET `/api/v1/documents/{doc_id}` — 상세

응답: `ApiResponse[DocumentResponse]`. 조회 시 자동 audit log 기록.

### 4.5 GET `/api/v1/pipeline/documents` — 처리중 / 실패 목록

**Query**:
- `status` (`processing` | `failed`) — 기본 `processing`
- `limit` (default 20)

응답: `ApiResponse[list[ProcessingDocumentResponse]]` — 진행 stage / 에러 메시지 포함.

### 4.6 GET `/api/v1/documents/{doc_id}/preview` — 블럭 프리뷰

**Query**: `offset`, `limit` (max 200).

응답: blocks 페이지네이션.

### 4.7 자동 분류

#### 4.7.1 GET `/api/v1/documents/{doc_id}/auto_classification`

처리 중 LLM 이 산출한 분류 제안 (`suggested_repository_name`, `suggested_document_type`).

```json
{
  "success": true,
  "data": {
    "suggested_repository_name": "공공 SaaS 매뉴얼",
    "suggested_document_type": "정책",
    "confidence": 0.87,
    "applied": false
  }
}
```

#### 4.7.2 POST `/api/v1/documents/{doc_id}/apply_classification`

분류 제안을 실제 repo / doc-type 으로 반영. body 가 없으면 suggested_* 사용. repo / doc-type 이 존재하지 않으면 자동 생성.

```bash
curl -X POST http://localhost:5101/api/v1/documents/<did>/apply_classification \
  -H "Content-Type: application/json" \
  -d '{"repository_name": "공공 SaaS 매뉴얼", "document_type": "정책"}'
```

#### 4.7.3 POST `/api/v1/documents/{doc_id}/reject_classification`

`applied=false` 로 soft 마킹. UI 배너 숨김.

### 4.8 DELETE `/api/v1/documents/{doc_id}` — archive

soft delete. blocks / 인덱스는 별도 cleanup worker 가 처리.

### 4.9 멀티파트 업로드 — Python (requests)

```python
import requests

BASE = "http://localhost:5101/api/v1"
REPO = "<rid>"

with open("./guide.pdf", "rb") as f:
    files = {"file": ("guide.pdf", f, "application/pdf")}
    data = {
        "repository_id": REPO,
        "title": "공공기관 가이드 v1",
        "category_ids": "[]",
    }
    r = requests.post(f"{BASE}/documents/upload", files=files, data=data, timeout=120)
    r.raise_for_status()
    doc_id = r.json()["data"]["document_id"]
    print(f"uploaded: {doc_id}")
```

### 4.10 멀티파트 업로드 — JS (FormData)

```javascript
async function uploadDoc(file, repoId, title) {
  const fd = new FormData();
  fd.append("file", file, file.name);
  fd.append("repository_id", repoId);
  fd.append("title", title);
  fd.append("category_ids", "[]");
  const r = await fetch("http://localhost:5101/api/v1/documents/upload", {
    method: "POST",
    body: fd,
  });
  if (!r.ok) {
    const err = await r.json();
    throw new Error(err?.error?.message ?? r.statusText);
  }
  return await r.json();
}
```

### 4.11 처리 진행률 폴링 패턴

```python
import time, httpx

def wait_for_active(doc_id: str, timeout_s: int = 600) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = httpx.get(f"http://localhost:5101/api/v1/documents/{doc_id}")
        doc = r.json()["data"]
        status = doc["status"]
        meta = doc.get("processing_meta") or {}
        print(f"[{status}] {meta.get('current_stage')} {meta.get('progress_percent', 0)}%")
        if status in ("active", "pending_review", "failed"):
            return status
        time.sleep(2)
    raise TimeoutError(f"document {doc_id} did not become active in {timeout_s}s")
```

---

## 5. Block (블럭) 관리 — 노션 스타일

문서 안 의미 단위. PDF → 블럭 (paragraph / heading_1..3 / table / image / code / quote / list 등). 검색·인용은 블럭 단위.

### 5.1 GET `/api/v1/documents/{document_id}/blocks` — 블럭 목록

**Query**:
- `offset` (default 0), `limit` (default 50, max 200)
- `block_type` (string) — `text` / `table` / `image` / `summary` 등 필터
- `include_noise` (bool) — 노이즈로 분류된 블럭 포함 여부

응답: `PaginatedResponse[BlockResponse]` — 주요 필드:

| 필드 | 타입 | 의미 |
|---|---|---|
| `id`, `document_id`, `repository_id` | UUID | |
| `block_type` | string | `paragraph` / `heading_1..3` / `table` / `image` / `code` / `quote` / `callout` / `to_do` / `bulleted_list` / `numbered_list` / `divider` |
| `content` | string | 본문 텍스트 (table 은 markdown) |
| `block_index` | int | 순서 |
| `source_location` | object | `page_number`, `bbox`, `heading_path`, `sheet_name`, ... |
| `metadata` | object | 분류·확신도·확장 |
| `is_indexed` | bool | 벡터화 완료 여부 |
| `is_noise` | bool | true 면 검색 인덱스 제외 |
| `table_headers`, `table_markdown` | | table 전용 |
| `image_description`, `ocr_text` | | image 전용 |
| `confidence_grade` | object | provenance badge |

### 5.2 GET `/api/v1/blocks/{block_id}` — 상세 (벡터 프리뷰 옵션)

**Query**: `include_vector` (bool) — true 면 dense vector 일부 + `vector_id` 포함.

응답: `ApiResponse[BlockDetailResponse]`.

### 5.3 PUT/PATCH `/api/v1/blocks/{block_id}` — 텍스트/타입 편집

권한: `editor` 이상.

**Body** (`BlockUpdateRequest`):

```json
{
  "content": "수정된 본문",
  "block_type": "paragraph",
  "metadata": {"keywords": ["KMS"]}
}
```

- `content` 변경 시 `is_indexed=false` + `vector_id=null` → 백그라운드 재벡터화.
- ES + Qdrant payload 도 즉시 sync (dense vector 는 유지).
- 응답: `ApiResponse[BlockResponse]`.

### 5.4 POST `/api/v1/blocks/{block_id}/re-index` — 단일 재인덱싱

GPU sidecar `/embed` 호출 (≈20ms) → Qdrant + ES upsert.

### 5.5 노이즈 블럭 관리

| Endpoint | 동작 |
|---|---|
| `GET /api/v1/documents/{document_id}/noise-blocks` | 노이즈 목록 |
| `POST /api/v1/blocks/{block_id}/promote` | 노이즈 → 본문 복원 + 재인덱싱 |
| `POST /api/v1/blocks/{block_id}/demote` | 본문 → 노이즈 강등 + 인덱스 제거 |

### 5.6 병합 / 분할

| Endpoint | 동작 |
|---|---|
| `POST /api/v1/blocks/{block_id}/merge-next` | 다음 block 과 병합 (다음 삭제) |
| `POST /api/v1/blocks/{block_id}/merge-prev` | 이전 block 과 병합 (현재 삭제) |
| `POST /api/v1/blocks/{block_id}/split` | `at_offset` 위치에서 분할 (body: `{"at_offset": 120}`) |

`table` / `image` / `divider` 는 분할 불가 (400).

### 5.7 표 markdown 편집 예시

```python
import httpx

BLK = "<block-uuid>"
new_md = """| 항목 | 한도 | 비고 |
|---|---|---|
| 잔고증명서 | 무제한 | 즉시 발급 |
| NXT 매매 | 일 5억 | 사전 등록 |"""

r = httpx.patch(
    f"http://localhost:5101/api/v1/blocks/{BLK}",
    json={"content": new_md, "block_type": "table"},
)
print(r.json())
```

---

## 6. Chunk 조회

`chunk` = 임베딩/검색의 *기본 단위*. block 과 1:1 또는 N:1 (긴 block 은 다중 chunk).

### 6.1 GET `/api/v1/chunks/{chunk_id}`

응답: chunk 본문 + `source_location` + `metadata` + 인덱싱 상태.

> 검색 hits 는 `chunk_id` 를 반환하므로, 인용 [N] 클릭 시 이 endpoint 로 원본 fetch 권장.

### 6.2 block vs chunk

| 측면 | block | chunk |
|---|---|---|
| 단위 | 의미 단위 (UI 표시) | 임베딩 단위 (검색) |
| 편집 | yes (PATCH) | no (재파이프 필요) |
| 인용 | 사용자가 본 단위 | 검색 매칭 단위 |
| 변환 | 1 block → 1+ chunks (긴 paragraph 분할) | |

---

## 7. 검색 (Search)

`POST /api/v1/search` — 하이브리드 (BGE-M3 dense + sparse + keyword) + RRF fusion + (옵션) cross-encoder reranker.

### 7.1 POST `/api/v1/search`

**Body** (`SearchRequest`):

| 필드 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `query` | string (1-1000) | — | 검색어 |
| `repository_id` | UUID | null | 단일 repo (legacy 호환). `scope` 와 함께 쓰지 않음 |
| `repository_ids` | UUID[] | null | 복수 repo (legacy 호환 또는 `scope="specified"`) |
| `scope` | enum | null | `default` / `tenant_all` / `specified` / `group` — 아래 표 참조 |
| `repository_group_id` | UUID | null | `scope="group"` 일 때 대상 group |
| `exclude_repository_ids` | UUID[] | null | `tenant_all` / `default` (group 폴백) 시 제외할 repo |
| `category_ids`, `document_type_ids` | UUID[] | null | 필터 |
| `top_k` | int (1-100) | 10 | |
| `weights` | `{dense,sparse,keyword}` | default | 가중치 오버라이드 |
| `block_types` | string[] | null | e.g. `["paragraph","heading_1","code"]` |
| `enable_rerank` | bool | true | cross-encoder |
| `mode` | `hybrid` / `dense` / `sparse` / `keyword` | hybrid | |
| `min_score` | float | 0.0 | 임계값 |
| `nature_filter` | string[] | null | 성격 필터 |
| `validity_filter` | `all`/`active`/`historical` | all | |
| `use_hyde` | bool | false | HyDE 가상문서 |
| `use_fallback` | bool | true | 폴백 전략 |
| `auto_intent` | bool | false | 의도 자동 분석 |
| `enable_llm_rewrite` | bool | false | LLM 쿼리 리라이팅 (오타·동의어·대화 재구성) |
| `conversation_history` | `[{role,content},...]` | null | 대화 컨텍스트 (대명사 복원) |
| `enable_sufficiency_check` | bool | false | 결과 충분성 평가 |
| `enable_intent_gate` | bool | true | 일상 대화 차단 |

**`scope` resolve 동작** (KMS-Plus 확장):

| scope | resolve 로직 |
| --- | --- |
| `default` | tenant 의 `is_default=true` group 의 `repository_ids`. default group 없으면 `tenant_all` 로 폴백 |
| `tenant_all` | tenant 의 모든 active repo (`exclude_repository_ids` 제외) |
| `specified` | `repository_ids` 만 (미지정 시 빈 결과 + warning log) |
| `group` | `repository_group_id` 가 가리키는 group 의 `repository_ids` (cross-tenant 또는 미존재 시 빈 결과) |

`scope` 미지정 시 기존 동작 유지 (`repository_id` / `repository_ids` 그대로).

**예시** — scope 사용:

```json
{
  "query": "잔고증명서 수수료",
  "scope": "default",
  "top_k": 5,
  "enable_intent_gate": true
}
```

```json
{
  "query": "공공기관 SOP",
  "scope": "group",
  "repository_group_id": "00000000-0000-0000-0000-000000000abc",
  "top_k": 10
}
```

```json
{
  "query": "법인 카드 정책",
  "scope": "tenant_all",
  "exclude_repository_ids": ["00000000-0000-0000-0000-000000000ff1"],
  "top_k": 8
}
```

**응답** (`ApiResponse[SearchResponse]`):

```json
{
  "success": true,
  "data": {
    "query": "잔고증명서 발급 수수료",
    "results": [
      {
        "chunk_id": "<uuid>",
        "document_id": "<uuid>",
        "document_title": "공공기관 가이드 v1",
        "section_title": "수수료 정책",
        "content": "잔고증명서 발급 수수료는 ...",
        "score": 0.8712,
        "source_location": {
          "page_number": 12,
          "heading_path": ["수수료", "잔고증명"]
        },
        "metadata": { "classification_confidence": 0.91 },
        "block_type": "paragraph",
        "block_index": 24,
        "repository_id": "<uuid>",
        "validity": "active",
        "nature": "policy",
        "token_count": 120,
        "fallback_level": 0
      }
    ],
    "total_candidates": 24,
    "latency_ms": 312,
    "decomposed": null,
    "intent": {
      "search": true,
      "reason": "knowledge_query",
      "latency_ms": 180,
      "skipped": false
    },
    "keywords": ["잔고증명서", "발급", "수수료"],
    "rewritten_query": "잔고증명서 발급 수수료"
  }
}
```

### 7.2 시나리오

#### 7.2.1 단일 쿼리

```bash
curl -X POST http://localhost:5101/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "잔고증명서 수수료", "top_k": 5}'
```

#### 7.2.2 multi-turn (대화 컨텍스트)

```python
import httpx

history = [
    {"role": "user", "content": "잔고증명서 말인데요"},
    {"role": "assistant", "content": "네, 어떤 점이 궁금하신가요?"},
]
r = httpx.post(
    "http://localhost:5101/api/v1/search",
    json={
        "query": "수수료 얼마예요?",
        "repository_id": "<rid>",
        "enable_llm_rewrite": True,
        "conversation_history": history,
        "top_k": 5,
    },
    timeout=30,
)
data = r.json()["data"]
print("rewritten:", data["rewritten_query"])  # "잔고증명서 수수료 ..."
```

#### 7.2.3 노이즈 chunk 제외 + 표 우선

```json
{
  "query": "지자체별 메일 수 통계",
  "block_types": ["table"],
  "enable_intent_gate": true,
  "top_k": 3
}
```

---

## 8. RAG (검색 + 답변)

### 8.1 POST `/api/v1/rag/retrieve` — 컨텍스트 검색 (토큰 예산 기반)

LLM 프롬프트 주입용. **외부 LLM** 을 쓸 때 컨텍스트만 가져오는 용도.

**Body** (`RAGRetrieveRequest`):

| 필드 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `query` | string (1-2000) | — | 질의 |
| `repository_id` | UUID? | null | null 이면 tenant 전체 |
| `category_ids` / `document_type_ids` | UUID[] | null | 필터 |
| `top_k` | int (1-10) | 3 | 권장 3-5 |
| `max_context_tokens` | int (200-8000) | 2000 | 예산 |
| `compress` | bool | false | 500 토큰 초과 청크 LLM 요약 |
| `weights` | object? | null | |
| `enable_rerank` | bool | true | |
| `include_linked_tenants` | bool | false | cross-tenant |
| `enable_intent_gate` | bool | true | |

**응답** (`RAGRetrieveResponse`):

```json
{
  "data": {
    "context": "## 출처 [1] (공공기관 가이드 v1, p.12)\n잔고증명서 발급 수수료는 ...",
    "sources": [
      {
        "ref_num": 1,
        "chunk_id": "<uuid>",
        "document_id": "<uuid>",
        "document_title": "공공기관 가이드 v1",
        "section_title": "수수료 정책",
        "content": "...",
        "score": 0.87,
        "token_count": 120,
        "compressed": false,
        "source_location": {...},
        "page_info": "p.12"
      }
    ],
    "token_count": 1320,
    "max_context_tokens": 2000,
    "prompt_template": "다음 참고자료를 기반으로 ... ## 참고자료 ... ## 질문 ...",
    "latency_ms": 612,
    "intent": {"search": true, "reason": "knowledge_query", "latency_ms": 180, "skipped": false}
  }
}
```

> `prompt_template` 은 외부 LLM 호출 시 그대로 user prompt 로 사용 가능.

alias: `POST /api/v1/rag/context` (V2 프론트 호환).

### 8.2 POST `/api/v1/rag/answer` — 검색 + LLM 답변

retrieve + distill + generation 한 번에.

**Body** (`RAGAnswerRequest`) — `RAGRetrieveRequest` + 답변 옵션:

| 필드 | 기본 | 설명 |
|---|---|---|
| `conversation_history` | `[]` | 멀티턴 |
| `llm_model` | auto | `auto` / `claude` / `qwen` / 모델 id |
| `temperature` | 0.3 | 0.0-1.0 |
| `max_answer_tokens` | 500 | 50-2000 |
| `verify_facts` | false | 환각 감지 (추가 LLM 호출) |
| `distill` | true | 후보 정제 단계 |
| `distill_pool_size` | 10 | 3-30 |
| `with_answer` | true | false 면 정제 결과만 |
| `enable_intent_gate` | true | |

**응답** (`RAGAnswerResponse`):

```json
{
  "data": {
    "answer": "잔고증명서 발급 수수료는 무료입니다 [1].",
    "distilled": {
      "selected_refs": [1, 3],
      "summary": "...",
      "rationale": "..."
    },
    "sources": [{ "ref_num": 1, ... }],
    "sources_all": [{ "ref_num": 1, ... }],
    "confidence": 0.87,
    "model_used": "gemma-4-26b-a4b",
    "token_usage": {
      "context_tokens": 1320,
      "prompt_tokens": 1820,
      "completion_tokens": 64,
      "total_tokens": 1884
    },
    "latency_ms": 2980,
    "retrieval_latency_ms": 620,
    "selection_latency_ms": 1100,
    "generation_latency_ms": 1240,
    "fact_check_score": null,
    "verdict": null,
    "unsupported_claims": null,
    "intent": {...}
  }
}
```

### 8.3 POST `/api/v1/rag/generate` — 답변만 생성

미리 가져온 `context` 로 LLM 호출만 (점진 표시 2단계 UI 용).

**Body** (`RAGGenerateRequest`):

```json
{
  "query": "...",
  "context": "...",
  "conversation_history": [],
  "llm_model": "auto",
  "temperature": 0.3,
  "max_answer_tokens": 500
}
```

### 8.4 POST `/api/v1/rag/assist-stream` — SSE 스트리밍 (상담사 보조 전용)

**핵심 endpoint** — KMS 의 *기본 retrieval 파이프라인*. site/agent 가 사용할 표준 진입점.

**Body** (`AssistStreamRequest`):

| 필드 | 필수 | 설명 |
|---|---|---|
| `query` | yes | 현재 발화 (1-1000) |
| `repository_id` | yes | 대상 repo |
| `conversation_history` | no | 서버가 최근 3턴(6메시지)으로 truncate, msg 당 1000 char cap |
| `enable_distill` | no (true) | 정제 단계 on/off |

**SSE 이벤트 순서**:

1. `event: intent` — `{search, reason, latency_ms, skipped}`
2. `event: query_analysis` (검색 진행 시) — `{original_query, rewritten_query, keywords, decomposed}`
3. `event: sources` — `{sources[], confidence, search_latency_ms, total_candidates}`
4. `event: distilled` (옵션) — `{selected_refs, summary, rationale, latency_ms}`
5. `event: token` × N — `{text}` (한 청크씩)
6. `event: done` — `{model_used, confidence, token_usage, latency_ms, stages: {intent, search, distill, generate}}`
7. (에러 시) `event: error` — `{stage, code, message}` 후 종료

intent.search=false (일상 대화) → sources/distilled skip, `token: "일상 대화입니다."` + done.

**제한**:
- 테넌트당 동시 요청 상한 (`ASSIST_MAX_CONCURRENT_PER_TENANT`, default 처리 — 초과 시 429)
- TTFT timeout, total timeout, distill timeout, search timeout 모두 환경 변수

#### 8.4.1 Python (httpx + sseclient)

```python
import json
import httpx
import sseclient  # pip install sseclient-py

BASE = "http://localhost:5101/api/v1/rag"
body = {
    "query": "잔고증명서 발급 수수료 알려줘",
    "repository_id": "<rid>",
    "conversation_history": [],
    "enable_distill": True,
}
with httpx.stream("POST", f"{BASE}/assist-stream", json=body, timeout=120) as r:
    client = sseclient.SSEClient(r.iter_lines())
    for event in client.events():
        data = json.loads(event.data)
        if event.event == "intent":
            print(f"[intent] search={data['search']} ({data['reason']})")
        elif event.event == "sources":
            print(f"[sources] {len(data['sources'])} hits, top score={data['confidence']}")
        elif event.event == "token":
            print(data["text"], end="", flush=True)
        elif event.event == "done":
            print(f"\n[done] total={data['latency_ms']}ms")
            break
        elif event.event == "error":
            print(f"\n[error] {data['stage']} {data['code']} {data['message']}")
            break
```

#### 8.4.2 JS (EventSource — fetch streaming polyfill)

```javascript
async function assistStream(query, repoId, onToken, onSources, onDone) {
  const r = await fetch("http://localhost:5101/api/v1/rag/assist-stream", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Accept": "text/event-stream"},
    body: JSON.stringify({query, repository_id: repoId, enable_distill: true}),
  });
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buf += decoder.decode(value, {stream: true});
    const events = buf.split("\n\n");
    buf = events.pop() ?? "";
    for (const evt of events) {
      const lines = evt.split("\n");
      const eventName = (lines.find(l => l.startsWith("event:")) ?? "").slice(6).trim();
      const dataLine = (lines.find(l => l.startsWith("data:")) ?? "").slice(5).trim();
      if (!dataLine) continue;
      const data = JSON.parse(dataLine);
      if (eventName === "token") onToken(data.text);
      else if (eventName === "sources") onSources(data.sources);
      else if (eventName === "done") { onDone(data); return; }
      else if (eventName === "error") throw new Error(`${data.stage}: ${data.message}`);
    }
  }
}
```

### 8.5 citation 인용 [N] 처리

답변 본문에 `[1]`, `[2]` 마커가 inline 으로 등장한다. 각 마커는 `sources[i].ref_num` 와 1:1 대응. 클릭 시:

```javascript
function handleCitationClick(refNum, sources) {
  const src = sources.find(s => s.ref_num === refNum);
  if (!src) return;
  // popup 또는 detail panel
  showCitation({
    title: src.document_title,
    section: src.section_title,
    page: src.page_info,
    text: src.content,
    docId: src.document_id,
  });
}
```

서버측 citation popup endpoint: `GET /api/v1/citations/...` (Web/Telegram/OpenAI 호환).

### 8.6 GET `/api/v1/rag/models`

사용 가능한 LLM 모델 목록:

```json
{ "data": { "models": [
  { "id": "auto", "name": "Auto (기본)", "provider": "auto" },
  { "id": "gemma-4-26b-a4b", "name": "Gemma 4 26B MoE (AWQ-4bit)", "provider": "vllm" }
]}}
```

---

## 9. Note (노션 스타일 노트)

파일 없이 직접 입력. 문서 라이프사이클 (`status=active` 즉시) + 블럭 배열.

### 9.1 POST `/api/v1/notes` — 생성

권한: `editor` 이상.

**Body** (`NoteCreateRequest`):

```json
{
  "repository_id": "<rid>",
  "title": "운영 메모: 5월 19일",
  "description": "...",
  "blocks": [
    {"block_type": "heading_1", "content": "운영 이슈"},
    {"block_type": "paragraph", "content": "오늘 발견된 ..."},
    {"block_type": "bulleted_list", "content": "항목 A"},
    {"block_type": "bulleted_list", "content": "항목 B"},
    {"block_type": "to_do", "content": "내일 처리", "properties": {"checked": false}},
    {"block_type": "callout", "content": "주의", "properties": {"icon": "warning"}, "children": [
      {"block_type": "paragraph", "content": "중첩 블럭"}
    ]}
  ],
  "category_ids": []
}
```

지원 `block_type`: `paragraph`, `heading_1..3`, `bulleted_list`, `numbered_list`, `code`, `quote`, `callout`, `to_do`, `divider`, `table`, `image`.

**응답** (`NoteResponse`):

```json
{
  "data": {
    "document": { ... },
    "blocks": [ ... ],
    "block_count": 6
  }
}
```

### 9.2 GET `/api/v1/notes/{doc_id}`

에디터 로드용. 블럭 배열 전체 반환.

### 9.3 GET `/api/v1/notes?repository_id=...`

목록 (`NoteListItem` 페이지네이션). `offset`, `limit` (max 200).

### 9.4 PATCH `/api/v1/notes/{doc_id}` — 편집 (블럭 전체 교체)

권한: `editor`.

**Body** (`NoteUpdateRequest`):

```json
{ "title": "...", "description": "...", "blocks": [ /* 새 블럭 배열 */ ] }
```

`blocks=null` 이면 메타만 변경. 제공 시 기존 블럭 모두 삭제 후 재삽입 → 임베딩 큐 재발행.

### 9.5 DELETE `/api/v1/notes/{doc_id}`

문서 + 블럭 hard delete.

---

## 10. 카테고리 / 문서타입 / 라이브러리 폴더

### 10.1 카테고리 (`/api/v1`)

| Method | Path | 동작 |
|---|---|---|
| GET | `/repositories/{repo_id}/categories?parent_id=...` | 목록 (트리 한 단계) |
| GET | `/repositories/{repo_id}/categories/tree` | 전체 트리 |
| GET | `/categories/{category_id}` | 상세 |
| POST | `/repositories/{repo_id}/categories` | 생성 (`CategoryCreate`) |
| PATCH | `/categories/{category_id}` | 수정 (`CategoryUpdate`) |
| PATCH | `/repositories/{repo_id}/categories/{category_id}` | 저장소 스코프 수정 (드래그-앤-드롭) |
| DELETE | `/categories/{category_id}` | soft delete |

`CategoryCreate`: `name` (1-200), `description?`, `parent_id?` (다단계), `sort_order` (기본 0).

### 10.2 문서타입 (`/api/v1`)

| Method | Path | 동작 |
|---|---|---|
| GET | `/tenants/{tenant_id}/document-types?is_system=...` | 목록 |
| GET | `/document-types/{doc_type_id}` | 상세 |
| POST | `/tenants/{tenant_id}/document-types` | 생성 (`DocumentTypeCreate`: name 1-100, description?, icon?) |

### 10.3 라이브러리 폴더 (`/api/v1`)

repo 안 트리 분류 (검색에 영향 X, UI 분류 전용). alembic 067/068.

| Method | Path | 동작 |
|---|---|---|
| GET | `/repos/{repo_id}/folders` | 폴더 트리 |
| POST | `/repos/{repo_id}/folders` | 신규 폴더 |
| PATCH | `/folders/{folder_id}` | 이름/부모/kind 변경 |
| DELETE | `/folders/{folder_id}?cascade=...` | 삭제 (안에 doc/sub 있으면 cascade=false 시 409) |
| PATCH | `/documents/{doc_id}/move` | 문서 1건 이동 |
| POST | `/documents/bulk-move` | 문서 N건 일괄 이동 |

폴더 `kind` 화이트리스트: `sop` / `manual` / `glossary` / `faq` / `policy` (기본 manual).

---

## 11. 감사 (Audit) + Health + 시스템

### 11.1 시스템 endpoint

| Method | Path | 의미 |
|---|---|---|
| GET | `/health` | 항상 200 (간이) |
| GET | `/health/live` | liveness — 프로세스 살아있음 |
| GET | `/health/ready` | readiness — DB / Redis / Qdrant / ES 연결. 하나라도 실패 시 503 |
| GET | `/api/versions` | API version registry |
| GET | `/api/changelog` | 변경 이력 |
| GET | `/docs` | Swagger UI (정책에 따라 비활성/IP 제한 가능) |
| GET | `/redoc` | Redoc |
| GET | `/openapi.json` | OpenAPI spec |
| GET | `/metrics` | Prometheus (ASGI sub-app) |

### 11.2 Audit logs — admin only

`/api/v1/admin/audit/*` — `admin` role 강제 (KMS_RBAC_ENFORCED 무관).

| Method | Path | 동작 |
|---|---|---|
| GET | `/tool_invocations?limit=&status=&skill_id=` | 최근 tool invocation |
| GET | `/freshness_runs?limit=` | 최근 knowledge_freshness_runs |
| GET | `/combined?inv_limit=&fresh_limit=` | 위 두 가지 한 번에 |
| GET | `/logs?limit=&tenant_id=&owner_scope=&owner_agent_id=&include_null_owner=` | audit_logs 합산 |

응답은 wrap 없이 `{"data": {"items": [...], "count": N}}`.

---

## 12. 에러 처리 가이드

### 12.1 응답 모양

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "TENANT_ID_REQUIRED",
    "message": "X-Tenant-Id 헤더가 필요합니다.",
    "details": {}
  }
}
```

### 12.2 HTTP 매핑

| Status | 의미 | 클라이언트 대응 |
|---|---|---|
| 200 | OK | |
| 201 | Created | |
| 400 | 잘못된 요청 (`UNSUPPORTED_FORMAT` 등) | 입력 정정 |
| 401 | 미인증 / 토큰 만료 | `/auth/v2/refresh` 후 retry |
| 403 | 권한 / cross-tenant | path / role 확인 |
| 404 | 리소스 없음 | 존재 확인 |
| 409 | 충돌 (`duplicate_in_flight_upload`, slug, email) | force_new / 다른 slug |
| 422 | Pydantic ValidationError | body schema 정정 |
| 429 | Rate limit / 동시 상한 | exponential backoff |
| 500 | 내부 오류 (`PIPELINE_*_ERROR`, `LLM_ROUTING_FAILED`) | retry / 운영자 |
| 503 | 외부 의존성 다운 (`service_unavailable`) | `/health/ready` 확인 후 retry |

### 12.3 retry / backoff

권장:
- 401 → refresh 1회 → 그래도 401 이면 재로그인.
- 429 / 503 → exponential backoff (0.5s → 1s → 2s → 4s, max 5회).
- 5xx (LLM / search) → 최대 2회 retry. assist-stream 은 client 종료 후 재시작.
- 4xx (400/403/404/409/422) → retry 금지, 입력 정정.

```python
import time
def retry(call, retries=3, base=0.5):
    for i in range(retries):
        try:
            r = call()
            if r.status_code in (429, 502, 503, 504):
                time.sleep(base * (2 ** i))
                continue
            return r
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(base * (2 ** i))
    raise RuntimeError("retries exhausted")
```

---

## 13. Rate Limit / Quota

> 현재 KMS-only 배포는 `RATE_LIMIT_EXCEEDED` 코드 (`RateLimitExceededError`) 와 동시 요청 상한 (assist-stream 의 `ASSIST_MAX_CONCURRENT_PER_TENANT`) 두 메커니즘.

| 자원 | 제한 | 응답 |
|---|---|---|
| `/api/v1/rag/assist-stream` 동시 | tenant 별 (env: `ASSIST_MAX_CONCURRENT_PER_TENANT`) | 429 + `Too many concurrent assist-stream requests` |
| (선택) API key 호출률 | 운영 설정 시 | 429 `RATE_LIMIT_EXCEEDED` (details: `{key_id, limit}`) |
| document / repository 갯수 | 라이선스 (`LicenseLimitExceededError`) | `LICENSE_LIMIT_EXCEEDED` (details: `{resource, current, limit, tier}`) |
| daily searches | (옵션) `increment_daily_counter` | 한도 초과 시 LicenseLimit |

> 헤더 `X-RateLimit-*` 는 현재 표준 미노출 — 운영 단계에서 reverse proxy (nginx) 가 별도 부여 가능.

---

## 14. 통합 예시 시나리오

### 14.1 시나리오 A: PDF 업로드 → 검색 → 인용 (Python end-to-end)

```python
"""
end-to-end 통합 예시 — 공공 SaaS 가이드 업로드 + assist-stream.
무인증 모드 기준 (LUCAS_AUTH_DISABLED=true).
"""
import json
import time
import httpx
import sseclient

BASE = "http://localhost:5101/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

# 1. repository 확보 (기존 있으면 재사용)
r = httpx.get(f"{BASE}/tenants/{TENANT}/repositories")
items = r.json()["data"]["items"]
repo = next((x for x in items if x["name"] == "공공 SaaS 가이드"), None)
if repo is None:
    r = httpx.post(
        f"{BASE}/tenants/{TENANT}/repositories",
        json={"name": "공공 SaaS 가이드", "description": "운영 매뉴얼"},
    )
    repo = r.json()["data"]
repo_id = repo["id"]

# 2. 문서 업로드
with open("./guide.pdf", "rb") as f:
    files = {"file": ("guide.pdf", f, "application/pdf")}
    data = {"repository_id": repo_id, "title": "공공기관 가이드 v1"}
    r = httpx.post(f"{BASE}/documents/upload", files=files, data=data, timeout=120)
    doc_id = r.json()["data"]["document_id"]

# 3. 처리 완료 대기
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    r = httpx.get(f"{BASE}/documents/{doc_id}")
    status = r.json()["data"]["status"]
    if status in ("active", "pending_review", "failed"):
        break
    time.sleep(2)
assert status == "active", f"upload failed: status={status}"

# 4. assist-stream 호출 + 인용 수집
body = {"query": "잔고증명서 발급 수수료", "repository_id": repo_id, "enable_distill": True}
with httpx.stream("POST", f"{BASE}/rag/assist-stream", json=body, timeout=120) as r:
    client = sseclient.SSEClient(r.iter_lines())
    sources = []
    answer = ""
    for event in client.events():
        data = json.loads(event.data)
        if event.event == "sources":
            sources = data["sources"]
        elif event.event == "token":
            answer += data["text"]
        elif event.event == "done":
            break

print("answer:", answer)
for s in sources:
    print(f"  [{s['ref_num']}] {s['document_title']} {s.get('page_info','')}")
```

### 14.2 시나리오 B: 노트 생성 + 검색

```python
# 1. 노트 생성
note = {
    "repository_id": repo_id,
    "title": "운영 이슈 메모",
    "blocks": [
        {"block_type": "heading_1", "content": "5월 19일 운영 이슈"},
        {"block_type": "paragraph", "content": "잔고증명서 발급 시간이 지연됨."},
        {"block_type": "to_do", "content": "내일 회의 안건 등록", "properties": {"checked": False}},
    ],
}
r = httpx.post(f"{BASE}/notes", json=note)
note_doc_id = r.json()["data"]["document"]["id"]

# 2. 임베딩 완료까지 대기 (note 는 빠름 — 보통 수 초)
time.sleep(5)

# 3. 검색
r = httpx.post(
    f"{BASE}/search",
    json={"query": "잔고증명서 지연", "repository_id": repo_id, "top_k": 3},
)
for hit in r.json()["data"]["results"]:
    print(hit["document_title"], hit["score"])
```

### 14.3 시나리오 C: 표 편집 + 재검색

```python
# 1. 문서 블럭 중 표 찾기
r = httpx.get(f"{BASE}/documents/{doc_id}/blocks?block_type=table&limit=5")
tables = r.json()["items"]
table = tables[0]

# 2. 표 markdown 수정
new_md = table["content"].replace("일 5억", "일 10억")
r = httpx.patch(f"{BASE}/blocks/{table['id']}", json={"content": new_md})

# 3. 재인덱싱 (자동이지만 명시적으로)
httpx.post(f"{BASE}/blocks/{table['id']}/re-index")

# 4. 재검색
time.sleep(3)
r = httpx.post(f"{BASE}/search", json={"query": "NXT 매매 일일 한도", "top_k": 3})
print(r.json()["data"]["results"][0]["content"])
```

---

## 15. SDK 패턴 (참고)

> 공식 SDK 는 별도 배포. 본 스켈레톤은 외부 통합 시 참고.

### 15.1 Python SDK 스켈레톤

```python
"""lucas_kms — minimal Python client."""
from __future__ import annotations

from typing import Any, AsyncIterator
from uuid import UUID

import httpx
import sseclient


class LucasKMSClient:
    def __init__(
        self,
        base_url: str = "http://localhost:5101",
        access_token: str | None = None,
        tenant_id: str | None = None,
        timeout: float = 30.0,
    ):
        self.base = base_url.rstrip("/")
        self._token = access_token
        self._tenant = tenant_id
        self._client = httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if self._tenant:
            h["X-Tenant-Id"] = self._tenant
        return h

    # -------- auth -----------------------------------------------------------

    def login(self, email: str, password: str) -> dict[str, Any]:
        r = self._client.post(
            f"{self.base}/auth/v2/login",
            json={"email": email, "password": password},
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._tenant = body["user"]["tenant_id"]
        return body

    # -------- repositories ---------------------------------------------------

    def list_repositories(self, tenant_id: str | UUID) -> list[dict[str, Any]]:
        r = self._client.get(
            f"{self.base}/api/v1/tenants/{tenant_id}/repositories",
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()["data"]["items"]

    def create_repository(
        self, tenant_id: str | UUID, name: str, description: str = ""
    ) -> dict[str, Any]:
        r = self._client.post(
            f"{self.base}/api/v1/tenants/{tenant_id}/repositories",
            json={"name": name, "description": description},
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()["data"]

    # -------- documents ------------------------------------------------------

    def upload_document(
        self,
        repository_id: str | UUID,
        file_path: str,
        title: str | None = None,
    ) -> str:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f)}
            data = {"repository_id": str(repository_id)}
            if title:
                data["title"] = title
            r = self._client.post(
                f"{self.base}/api/v1/documents/upload",
                files=files,
                data=data,
                headers=self._headers(),
                timeout=300.0,
            )
        r.raise_for_status()
        return r.json()["data"]["document_id"]

    def get_document(self, doc_id: str | UUID) -> dict[str, Any]:
        r = self._client.get(
            f"{self.base}/api/v1/documents/{doc_id}",
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()["data"]

    # -------- search ---------------------------------------------------------

    def search(
        self,
        query: str,
        repository_id: str | UUID | None = None,
        top_k: int = 10,
        **kwargs,
    ) -> dict[str, Any]:
        body = {"query": query, "top_k": top_k, **kwargs}
        if repository_id:
            body["repository_id"] = str(repository_id)
        r = self._client.post(
            f"{self.base}/api/v1/search",
            json=body,
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()["data"]

    # -------- assist-stream --------------------------------------------------

    def assist_stream(
        self,
        query: str,
        repository_id: str | UUID,
        conversation_history: list[dict] | None = None,
        enable_distill: bool = True,
    ) -> AsyncIterator[tuple[str, dict]]:
        """generator (event_name, payload)."""
        import json
        body = {
            "query": query,
            "repository_id": str(repository_id),
            "conversation_history": conversation_history or [],
            "enable_distill": enable_distill,
        }
        with self._client.stream(
            "POST",
            f"{self.base}/api/v1/rag/assist-stream",
            json=body,
            headers=self._headers(),
            timeout=180.0,
        ) as r:
            client = sseclient.SSEClient(r.iter_lines())
            for event in client.events():
                yield event.event, json.loads(event.data)
                if event.event in ("done", "error"):
                    return

    def close(self) -> None:
        self._client.close()
```

사용:

```python
c = LucasKMSClient()
repos = c.list_repositories("00000000-0000-0000-0000-000000000001")
doc_id = c.upload_document(repos[0]["id"], "./guide.pdf", title="가이드 v1")
hits = c.search("잔고증명서 수수료", repository_id=repos[0]["id"], top_k=5)
for evt, data in c.assist_stream("잔고증명서 발급 수수료", repos[0]["id"]):
    if evt == "token":
        print(data["text"], end="", flush=True)
```

### 15.2 JS/TS SDK 스켈레톤

```typescript
// lucas-kms.ts — minimal TypeScript client (browser + Node 18+)

export interface LucasOptions {
  baseUrl?: string;
  accessToken?: string;
  tenantId?: string;
}

export class LucasKMSClient {
  baseUrl: string;
  accessToken?: string;
  tenantId?: string;

  constructor(opts: LucasOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? "http://localhost:5101").replace(/\/$/, "");
    this.accessToken = opts.accessToken;
    this.tenantId = opts.tenantId;
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const h: Record<string, string> = {"Accept": "application/json", ...extra};
    if (this.accessToken) h["Authorization"] = `Bearer ${this.accessToken}`;
    if (this.tenantId) h["X-Tenant-Id"] = this.tenantId;
    return h;
  }

  async login(email: string, password: string) {
    const r = await fetch(`${this.baseUrl}/auth/v2/login`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email, password}),
    });
    if (!r.ok) throw new Error(`login failed: ${r.status}`);
    const body = await r.json();
    this.accessToken = body.access_token;
    this.tenantId = body.user.tenant_id;
    return body;
  }

  async listRepositories(tenantId: string) {
    const r = await fetch(
      `${this.baseUrl}/api/v1/tenants/${tenantId}/repositories`,
      {headers: this.headers()},
    );
    const body = await r.json();
    return body.data.items as any[];
  }

  async createRepository(tenantId: string, name: string, description = "") {
    const r = await fetch(
      `${this.baseUrl}/api/v1/tenants/${tenantId}/repositories`,
      {
        method: "POST",
        headers: this.headers({"Content-Type": "application/json"}),
        body: JSON.stringify({name, description}),
      },
    );
    if (!r.ok) throw new Error(`createRepository: ${r.status}`);
    return (await r.json()).data;
  }

  async uploadDocument(file: File | Blob, repositoryId: string, title?: string) {
    const fd = new FormData();
    fd.append("file", file as any);
    fd.append("repository_id", repositoryId);
    if (title) fd.append("title", title);
    const r = await fetch(`${this.baseUrl}/api/v1/documents/upload`, {
      method: "POST",
      headers: this.headers(),  // FormData 는 Content-Type 자동
      body: fd,
    });
    if (!r.ok) throw new Error(`upload: ${r.status}`);
    return (await r.json()).data.document_id as string;
  }

  async search(query: string, repositoryId?: string, topK = 10) {
    const r = await fetch(`${this.baseUrl}/api/v1/search`, {
      method: "POST",
      headers: this.headers({"Content-Type": "application/json"}),
      body: JSON.stringify({query, repository_id: repositoryId, top_k: topK}),
    });
    return (await r.json()).data;
  }

  async *assistStream(
    query: string,
    repositoryId: string,
    options: {conversationHistory?: any[]; enableDistill?: boolean} = {},
  ): AsyncGenerator<{event: string; data: any}, void, void> {
    const body = {
      query,
      repository_id: repositoryId,
      conversation_history: options.conversationHistory ?? [],
      enable_distill: options.enableDistill ?? true,
    };
    const r = await fetch(`${this.baseUrl}/api/v1/rag/assist-stream`, {
      method: "POST",
      headers: this.headers({
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
      }),
      body: JSON.stringify(body),
    });
    const reader = r.body!.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const {value, done} = await reader.read();
      if (done) return;
      buf += decoder.decode(value, {stream: true});
      const events = buf.split("\n\n");
      buf = events.pop() ?? "";
      for (const evt of events) {
        const lines = evt.split("\n");
        const event = (lines.find(l => l.startsWith("event:")) ?? "").slice(6).trim();
        const dataLine = (lines.find(l => l.startsWith("data:")) ?? "").slice(5).trim();
        if (!dataLine) continue;
        yield {event, data: JSON.parse(dataLine)};
        if (event === "done" || event === "error") return;
      }
    }
  }
}
```

사용:

```typescript
const c = new LucasKMSClient();
const repos = await c.listRepositories("00000000-0000-0000-0000-000000000001");
for await (const {event, data} of c.assistStream("잔고증명서 수수료", repos[0].id)) {
  if (event === "token") process.stdout.write(data.text);
  if (event === "done") console.log("\n[done]", data.latency_ms, "ms");
}
```

---

## 부록 A. 환경 변수 빠른 참조

| 변수 | 기본 | 설명 |
|---|---|---|
| `LUCAS_AUTH_DISABLED` | `false` | true 면 무인증 모드 (Lucas-KMS 권장 default) |
| `LUCAS_DEFAULT_TENANT_ID` | `00000000-...-001` | 무인증 모드 기본 tenant |
| `LUCAS_DEFAULT_USER_ID` | `00000000-...-001` | 무인증 모드 기본 user |
| `DATABASE_URL` | — | Postgres DSN |
| `REDIS_URL` | — | Redis (캐시·intent log) |
| `QDRANT_URL` | — | Qdrant (dense vectors) |
| `ELASTICSEARCH_URL` | — | ES (sparse·keyword) |
| `KAFKA_BOOTSTRAP_SERVERS` | — | Kafka (파이프라인 이벤트) |
| `EMBEDDING_PROXY_URL` | — | GPU sidecar `/embed` |
| `RERANKER_URL` | — | cross-encoder |
| `ASSIST_MAX_CONCURRENT_PER_TENANT` | (config) | assist-stream 동시 상한 |
| `ASSIST_INTENT_TIMEOUT_MS` | (config) | intent gate timeout |
| `ASSIST_SEARCH_TIMEOUT_MS` | (config) | hybrid search timeout |
| `ASSIST_DISTILL_TIMEOUT_MS` | (config) | distill timeout |
| `ASSIST_GEN_FIRST_TOKEN_TIMEOUT_MS` | (config) | LLM TTFT |
| `ASSIST_GEN_TOTAL_TIMEOUT_MS` | (config) | LLM total |
| `ENABLE_SWAGGER` | true | false 면 `/docs` 비활성 |
| `SWAGGER_AUTH_MODE` | open | `open` / `basic` / `ip` / `jwt` |
| `SWAGGER_IP_ALLOWLIST` | — | CIDR list |

## 부록 B. 라우터 → endpoint prefix 매핑 (Lucas-KMS 한정)

`src/api/main_kms.py` 의 `_build_kms_specs()` / `_build_shared_specs()` 가 source of truth. 주요 매핑:

| Router | Prefix | Tag |
|---|---|---|
| `health` | `/health` | 시스템 |
| `repositories` | `/api/v1` | 저장소 |
| `categories` | `/api/v1` | 카테고리 |
| `document_types` | `/api/v1` | 문서타입 |
| `documents` | `/api/v1` | 문서 |
| `blocks` | `/api/v1` | 블럭 |
| `notes` | `/api/v1` | 노트 |
| `chunks` | `/api/v1` | 청크 |
| `preview` | `/api/v1` | 문서 |
| `search` | `/api/v1/search` | 검색 |
| `rag` | `/api/v1/rag` | RAG |
| `rag_assist` | `/api/v1/rag` | RAG Assist |
| `search_proxy` | `/api/v1` | Search Proxy |
| `synonyms` | `/api/v1/synonyms` | 동의어 |
| `ab_tests` | `/api/v1/search/ab-tests` | A/B 테스트 |
| `confidentiality` | `/api/v1` | 기밀 등급 |
| `pii` | `/api/v1` | PII |
| `anonymization` | `/api/v1/anonymization` | 익명화 |
| `stats` | `/api/v1/stats` | 통계 |
| `analytics` | `/api/v1/analytics` | 검색 분석 |
| `feedback_stats` | `/api/v1/feedback-stats` | 피드백 통계 |
| `knowledge_gap` | `/api/v1/knowledge-gap` | 지식 갭 |
| `classification_quality` | `/api/v1/quality` | 분류 품질 |
| `llm_metrics` | `/api/v1/metrics` | LLM 메트릭 |
| `playground` | `/api/v1/playground` | Playground |
| `reprocess` | (no prefix) | 재처리 |
| `pipeline_admin` | (no prefix) | 파이프라인 관리 |
| `webhook_inbound` | `/api/v1` | Webhook |
| `mail_accounts` | `/api/v1` | Mail Accounts |
| `library_folders` | `/api/v1` | Library Folders |
| `citations_v1` | `/api/v1` | citation popup |
| `knowledge_v1` | `/api/v1` | knowledge (KMS 표면) |
| `auth_v2` | (root + `/api/v1`) | auth-v2 |
| `account_settings` | `/api/v1` | account |
| `tenants_v1` | (prefix `/api/v1/tenants` 내장) | tenants-v1 |
| `audit` | (prefix `/api/v1/admin/audit` 내장) | 감사 |
| `account_groups` | `/api/v1` | account-groups |

> agent / chat / skill / tool / external-agent / scheduler 라우터는 **포함되지 않음** (KMS-only 정책).

## 부록 C. OpenAPI / Swagger

- Swagger UI: `GET /docs` (운영 정책에 따라 비활성 / IP 제한 / basic auth / JWT 가능)
- Redoc: `GET /redoc`
- OpenAPI JSON: `GET /openapi.json`

`SWAGGER_AUTH_MODE` 환경 변수로 보호 가능 (운영 권장: `ip` allowlist + `basic`).

---

> 문서 끝. 추가 endpoint (재처리, A/B, 동의어, PII, 익명화, webhook, mail 등) 는 `/docs` 의 Swagger 에서 schema 와 함께 참조 가능. 본 가이드는 **외부 통합 시 가장 자주 쓰이는 14 섹션 + 부록 3 종** 을 커버한다.

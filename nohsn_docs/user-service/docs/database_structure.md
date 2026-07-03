# user-service 데이터베이스 구조

> user-service가 접속하는 DB·스키마·테이블·컬럼 정리. SQLAlchemy 모델(`db/models/**`) 기준.
> 작성: 2026-07-03 · 기준 브랜치 `develop`

> ⚠️ 전제: user-service는 이 테이블들의 **생성자가 아니라 조회/일부 수정만** 담당. 스키마·테이블 준비는 `tenant-mgmt-service` 몫.
> `init_db()`는 `mgmt/staging/internal` 스키마만 보장하고 **테이블 생성 안 함, `prod` 스키마는 만들지 않음**(`db/database.py:124`).

---

## 1. 접속 대상 (단일 DB, 스키마 분리)

| 항목 | aicc-dev (docker-compose) | 코드 기본값(core/config.py) |
|---|---|---|
| DBMS | PostgreSQL | PostgreSQL |
| DB명 | `tenant_management` | `tenant_management` |
| 호스트/포트 | `cis-postgres:5432` (timbel_network 내부 DNS) | `localhost:5432` |
| 사용자 | `aicc_admin` | `postgres` |
| 커넥션풀 | pool_size 20 / max_overflow 30 / pool_recycle 1800s / pool_pre_ping | `db/database.py:58-66` |

- DB 분리가 아니라 **하나의 DB 안 여러 schema** 구조.
- import 시점에 `ensure_database_exists()`가 `postgres` DB 접속 후 DB 존재 확인/생성 시도.

## 2. 스키마 구성

```
tenant_management
├── mgmt      # BO/운영 메타데이터 (사용자·조직·전화번호·봇·history)
├── prod      # ★런타임 기준 (company·조직계층·agent·인프라 config)
├── staging   # 외부 동기화/편집 후보 (prod와 동일 구조)
└── internal  # init_db가 스키마만 생성, 테이블 없음(빈 스키마)
```

총 **19개 테이블**: mgmt 7 + prod 6 + staging 6 (internal 비어있음).

---

## 3. 스키마별 테이블

### 🟦 mgmt (7개) — 운영/BO 메타데이터

| 테이블 | 모델 | 주요 컬럼 |
|---|---|---|
| `mgmt.users` | Users | user_id(unique), password_hash, name, email, **role(JSONB)**, is_active, soft_deleted |
| `mgmt.organizations` | Organizations | name, description, **api_metadata(JSONB)**, phone, address, is_active, soft_deleted |
| `mgmt.phone_number_groups` | PhoneNumberGroups | name, provider, base_number, soft_deleted |
| `mgmt.phone_numbers` | PhoneNumbers | full_number, extension_number, workspace_id, expire_at, group_id→groups, org_id→organizations, company_id→**prod.company** |
| `mgmt.callbot` | Callbot | phone_number_id→phone_numbers, bot_id, **direction**, active, description |
| `mgmt.chatbot` | Chatbot | **channel(unique)**, bot_id, org_id→organizations, company_id→**prod.company**, active |
| `mgmt.tenant_history` | MultiTenantsHistory | org_id, tenant_id, action, status, result, error_str, {configs,db,minio,es,milvus,mongo,encrypt}_detail(JSONB), elapsed — 프로비저닝 이력 |

### 🟥 prod (6개) — 런타임 기준 데이터

| 테이블 | 모델 | 주요 컬럼 |
|---|---|---|
| `prod.company` ★ | CompanyProd | company_id, vendor_tenant_id, org_id→organizations, code, name, business_number, is_contract, contract_expire_at, **db_config / minio_config / es_config / milvus_config / mongo_config (JSONB, 암호화)**, available_{chatbot,callbot,advisor}_ch, enable_{ce,aicm,advisor,ta,qa}, expire_at |
| `prod.tenants` | TenantProd | tenant_id, code, name, company_id→company |
| `prod.centers` | CentersProd | center_id, name, company_id, tenant_id |
| `prod.teams` | TeamsProd | team_id, name, cc_team_id, company_id, tenant_id, center_id |
| `prod.parts` | PartsProd | part_id, name, company_id, tenant_id, center_id, team_id |
| `prod.agents` ★ | AgentProd | **ecp_account_id(unique), ecp_account(unique)**, role, password_hash, name, vendor, **advisor / ta / ce / aicm / qa (JSONB 권한)**, internal_role(JSONB), workspace_ids(JSONB), assigned_workspace_id, source, cc_*(cti_id·team_id·login_id·채널수 등), org_id·company_id·tenant_id·center_id·team_id·part_id |

### 🟨 staging (6개) — prod와 동일 이름/구조, 편집 후보

`staging.company` · `staging.tenants` · `staging.centers` · `staging.teams` · `staging.parts` · `staging.agents`

- prod와 **base 클래스 공유**(CompanyBase / TenantsBase / CentersBase / TeamsBase / PartsBase / AgentBase)라 컬럼 대부분 동일.
- 차이점:
  - staging은 `has_updated(Boolean)` 플래그 추가
  - `created_at`/`updated_at`이 nullable (prod는 server_default=now())
  - config성 컬럼(db_config 등)·enable/available 컬럼은 prod.company에만 있음
  - FK가 자기 스키마(`staging.*`)를 가리킴. 단 `org_id`는 공통으로 `mgmt.organizations` 참조

---

## 4. 조직 계층 & 매칭 키

```
prod.company   (company_id  ← JWT.cId)
   └─ prod.tenants
        └─ prod.centers
             └─ prod.teams
                  └─ prod.parts

prod.agents    (ecp_account_id ← JWT.sub,  ecp_account ← JWT.acc)
   → org_id·company_id·tenant_id·center_id·team_id·part_id 로 계층 연결
```

- 조직 계층 6단계: **company → tenant → center → team → part → agent**
- **스키마 교차 FK** 존재: `prod.agents.org_id`, `prod.chatbot.org_id`, `mgmt.phone_numbers.company_id`(→prod.company), `mgmt.chatbot.company_id`(→prod.company) 등 mgmt ↔ prod 상호 참조.

## 5. 운영 시 짚어둘 점

1. **`mgmt.phone_numbers`에 `direction` 컬럼 없음** — `direction`은 `mgmt.callbot`에만 존재. (phone update 로직의 direction 불일치 이슈와 연결)
2. **암호화 인프라 config는 전부 `prod.company`의 JSONB** (`db_config`/`minio_config`/`es_config`/`milvus_config`/`mongo_config`) — 내부 서비스 config 조회 시 CryptManager로 복호화.
3. **권한(permission)은 `prod.agents`의 advisor/ta/ce/aicm/qa JSONB** — 권한 수정 API가 여기를 대상으로 함.
4. **user-service는 생성자가 아님** — 조회 + 일부 컬럼 수정만. 신규 환경은 tenant-mgmt-service 초기화/migration 선행 필요.

---

## 참고
- 계층/모델 상세: 저장소 루트 `db-detail.md`
- 서비스 전반 분석: `docs/operation_check.md`

# user-service 종합 분석 및 운영 점검 (operation_check)

> Claude와 함께 진행하는 코드 분석 기록. 개발 스택 · 아키텍처 · 워크플로우 · 외부 연동 · 문제점을 누적한다.
> 각 항목은 가능한 한 `파일:라인`으로 근거를 남긴다.

작성 시작: 2026-07-03 · 기준 브랜치: `develop` · 분석: Claude와 1차 분석

---

## 1. 개발적 내용 (언어 · 스택 · 구조)

### 1.1 기술 스택
| 구분 | 사용 기술 | 근거 |
|---|---|---|
| 언어 | Python 3.11 | `Dockerfile:1` |
| 웹 프레임워크 | FastAPI 0.116 + uvicorn 0.35 | `main.py`, `requirements.txt` |
| ORM | SQLAlchemy 2.0.41 + psycopg2-binary | `db/database.py` |
| 설정 | pydantic-settings(`BaseSettings`) + python-dotenv | `core/config.py` |
| 인증 | PyJWT`[crypto]`, HMAC-SHA256, passlib(비번 해시) | `utils/auth_utils.py`, `utils/password_util.py` |
| 암복호화 | `cryptography`(RSA, PyJWT[crypto]가 전이 설치) | `managers/crypt_manager.py` |
| 캐시/스트림 | redis (동기 + `redis.asyncio`) | `managers/*redis*` |
| CLI | typer (실제로는 거의 미사용) | `main.py:26` |
| 관측성 | OpenTelemetry (OTLP 로그, 조건부) | `managers/logger_manager.py` |
| 로깅 | loguru(DEBUG) / logging(운영) 이중 스위치 | 전 파일 공통 패턴 |

### 1.2 코드 구조 (레이어드 아키텍처)
```
main.py                # 엔트리, FastAPI 앱 + lifespan
core/config.py         # 환경설정 (pydantic Settings)
api/
  __init__.py          # /api prefix 라우터 조립 (setup_routers)
  endpoints/*.py       # HTTP 계층 (얇음, 490줄)
  schemas/*.py         # Pydantic 요청/응답 스키마
service/*.py           # 비즈니스 로직 (두꺼움, 1,485줄) ★핵심
clients/*.py           # 외부 HTTP 호출 (auth/ecp/tenant-mgmt)
managers/*.py          # 싱글톤 인프라 (crypt/redis/logger)
utils/*.py             # 인증/롤/비번/dict 헬퍼
db/
  models/              # SQLAlchemy 모델 (mgmt / organizations)
  repositories/        # 쿼리 계층
  services/            # 모델별 DB 서비스 (repository 래핑)
  database.py          # 엔진/세션/초기화
```

- 계층 흐름: `endpoint → service(비즈니스) → db/services(모델별) → repositories → models` (4~5단)
- 무게중심은 `service/` : `tenant_service.py`(499줄), `prod_tenant_service.py`(337줄), `agent_service.py`(270줄)

### 1.3 DB 구조 — 하나의 DB, 3개 스키마
```
tenant_management (PostgreSQL)
├── mgmt      # BO 운영자/조직/전화번호/봇/history
├── staging   # 외부 동기화·편집 후보 (organizations/*_staging)
└── prod      # ★런타임 기준 데이터 (company/tenant/center/team/part/agent)
```
- 모델이 `prod`/`staging` 쌍으로 존재 (`company_prod.py` / `company_staging.py` 등)
- 조직 계층: **company → tenant → center → team → part → agent** (6단계)
- 코드에서 `tenant_id`라 부르는 값이 실제로는 `prod.company.id`인 경우가 많음 (함정)

---

## 2. 아키텍처 (역할과 포지션)

이름과 달리 **회원가입 서비스가 아님**. 실제 역할:

> 로그인 이후 런타임 요청에서 **JWT 사용자 ↔ 내부 `prod` 조직/agent를 매칭**하고,
> 해당 company가 쓸 **권한·조직·전화번호·봇·인프라 config를 해석해 내려주는 계층**.

```
client / runtime service (callbot·chatbot·advisor·OB)
      │
      ▼
  user-service ───► auth-service      (JWT 검증 위임)
      │        ───► ECP GW            (agent 보정 정보)
      │        ───► tenant_management (prod 데이터 조회/일부 수정)
      ▼
  조직/권한/workspace/bot/config 해석 응답
```

역할 분담:
- `tenant-mgmt-service` = 테넌트 **생성·프로비저닝** 주체 (write/lifecycle)
- `user-service` = 그 결과인 `prod` 데이터를 **런타임 조회·해석** (read 중심 + 일부 write)
- `auth-service` = 토큰 발급/검증 (user-service는 검증을 **위임**만, 직접 발급 안 함)

인증 이중 구조:
- 외부/사용자 API → `X-auth-token` → auth-service `verify_token` 위임 (`utils/auth_utils.py:19`)
- 내부 서비스 API(`/api/internal/*`) → `X-Internal-Auth` HMAC + 60초 timestamp (`utils/auth_utils.py:40`)

---

## 3. 워크플로우 (핵심 흐름 4가지)

### ① 로그인 (계정 검증은 user-service가 담당)
```
client → auth-service POST /api/auth/login
              → user-service GET /api/user/exist  (인증 없음, username/pw query)
                    → prod.agents.ecp_account 조회 → passlib verify_password
              → auth-service가 JWT 발급
```
코드: `agent_service.get_exist_user()` — `ecp_account`로 조회 후 `password_hash` 검증, 성공 시 sub/acc/cId/role 등 반환.

### ② 런타임 요청 인증·매칭
```
client → user-service /api/user|organization|phone|bots ...
    → X-auth-token을 auth-service로 검증 (payload: cId, sub, acc, role, exp)
    → payload.cId 로 prod.company 조회       (_parse_auth)
    → payload.sub + acc 로 prod.agents 조회  (_get_current_user)
    → 조직/권한/config 처리
```
코드: `base_service._parse_auth()` → `_get_current_user()`.

### ③ ECP 기반 agent 보정 생성 (회원가입이 아닌 "보정")
```
JWT 유효 & prod.company 있음 & prod.agents row 없음
    → ECP contact-center-groups + my-account 호출
    → ECP가 준 company/tenant/center/team/part가 prod에 "전부" 있는지 상위→하위 검증
    → 모두 있으면 source="external", vendor="NICE" agent row 생성
    → unique 충돌 시 재조회로 우회
```
코드: `base_service._fetch_ecp_agent_info()` (76~222줄). **조직 계층이 prod에 미리 다 있어야만 성공**.

### ④ 내부 서비스 config 조회
```
runtime service → GET /api/internal/get_configs
    → X-Internal-* HMAC 검증
    → tenant_id/vendor/phone/cti_id/channel/workspace로 company 역추적
    → prod.company.*_config 를 RSA 개인키로 복호화 (CryptManager)
    → tenant_info / configs / available_ch / bot_info 반환
```
코드: `service/prod_tenant_service.py`(`InternalTenantService`) + `managers/crypt_manager.py`.

---

## 4. 외부 Third-party & 연동

| 대상 | 종류 | 연동 방식 | 코드 |
|---|---|---|---|
| PostgreSQL `tenant_management` | DB | SQLAlchemy + psycopg2 | `db/database.py` |
| Redis (db 1) | 캐시/스트림/락 | 동기 + async | `managers/*redis*`, `utils/redis_helper.py` |
| auth-service | 내부 서비스 | HTTP GET `verify_token` (timeout 5s) | `clients/auth_client.py` |
| tenant-mgmt-service | 내부 서비스 | HTTP | `clients/tenant_mgmt_client.py` |
| ECP GW (`ecplab-gw.etaas.co.kr`) | **외부** SaaS | HTTPS, 3회 재시도 | `clients/ecp_client.py` |
| NICE | 외부 | ECP 경유(vendor 값) | `base_service.py:179` |
| OTLP collector | 관측성 | gRPC(4317), 조건부 | `logger_manager.py` |

주목: ECP만 진짜 외부 인터넷 호출(NICE 상용 컨택센터 플랫폼). 나머지는 `timbel_network` 내부 DNS.

### 4.1 실행/배포 사실표
| 항목 | 값 | 근거 |
|---|---|---|
| 엔트리포인트 | `python main.py` → `uvicorn.run("main:app")` | `Dockerfile:22`, `main.py:74` |
| 라우터 prefix | 실제 `/api` (config `API_V1_STR="/api/v1"`는 미사용) | `api/__init__.py:11` |
| 컨테이너 내부 포트 | `8080` (compose가 `PORT=8080` 주입) | `docker-compose.yml:13` |
| 호스트 노출 포트 | `32031` → 컨테이너 `8080` | `docker-compose.yml:8` |
| health check | `GET /api/health` → `{"status":"ok"}` | `main.py:57-59` |
| DB 초기화 | lifespan 시작 시 `initialize_database()` | `main.py:35` |
| 네트워크 | 외부 도커 네트워크 `timbel_network` | `docker-compose.yml:32-37` |

---

## 5. 문제점 · 리스크 (심각도순)

### 🔴 Critical — 기동 자체를 막을 수 있음
1. **`prompt_toolkit` 미설치 → 앱 전체 다운**
   `service/prod_tenant_service.py:3` `from prompt_toolkit.buffer import indent` (미사용). `requirements.txt`에 없음.
   `main.py → api import → setup_routers → internal_endpoints → prod_tenant_service` 경로로 **기동 시점 import**라, 컨테이너에 미설치면 `ModuleNotFoundError`로 서비스가 안 뜸.
   → **해결: 그 줄 삭제** (미사용이라 삭제가 정답)

2. **import 시점 DB 접속 강제**
   `db/database.py:55` `ensure_database_exists()`가 **모듈 로드 즉시** `postgres` DB 접속 + `CREATE DATABASE` 시도.
   `aicc_admin`이 `postgres` 접속/`CREATEDB` 권한 없거나 `cis-postgres` 미기동이면 즉시 기동 실패.

### 🟠 High — 동작 오류/데이터 위험
3. **`init_db()`가 테이블을 안 만듦**
   `db/database.py:124` — `model_classes` 리스트만 구성하고 `create_table_if_not_exists` 호출이 **없음**.
   `prod` 스키마도 보장 안 함(`mgmt/staging/internal`만). → user-service 단독으로 신규 환경 부팅 불가, `tenant-mgmt-service` 선행 필수.

4. **`BaseService.__init__(db=next(get_db()))` 기본 인자 함정**
   `service/base_service.py:34` — 기본값 `next(get_db())`가 **import 시점 1회만** 평가됨.
   db 미전달 시 모든 인스턴스가 import 때 열린 **단일 세션 공유** + import 시 DB 커넥션 발생. `Depends`로 db 넘기는 경로는 회피되나, 안 넘기면 세션 누수/공유 위험.

### 🟡 Medium — 잠복/견고성
5. **`workers` 패키지 부재**
   `managers/async_redis_manager.py:104,108`이 `from workers.agents_task/add_tenant_task` 참조하나 패키지 없음.
   지연 import라 기동은 안 막지만, 리스너 등록+이벤트 도착 시 실패. 게다가 `main.py`는 `AsyncRedisManager`를 import만 하고 **리스너 등록 안 함** → 현재 완전 미동작(dead code). `celery`도 requirements에 있으나 브로커/워커 부재.

6. **`get_exist_user` None 방어 부재**
   `agent_service.py:20` — 없는 username이면 `exist`가 None → `exist.password_hash`에서 `AttributeError`(500). 401이 맞는 상황에 500 반환.

7. **HMAC이 timestamp만 서명**
   `utils/auth_utils.py:14` — `X-Internal-Timestamp`만 서명 대상. tenant_id/phone 등 헤더 값 무결성 미보증(내부망 전제 가정).

8. **설정 불일치(혼란 유발)**
   - config 기본 PORT `32021` vs 컨테이너 `8080` vs 호스트 `32031`
   - `API_V1_STR="/api/v1"` 정의됐지만 미사용(실제 prefix `/api`)
   - `DEBUG` 기본 `True`(config) vs compose `false`

9. **`phone/update_phone_data`의 `direction`** 처리 흔적 vs `mgmt.phone_numbers` 모델 컬럼 불일치 (문서 기재, 코드 재확인 필요)

---

## 6. 운영 점검 체크리스트 (배포 후)

```bash
# 1) 컨테이너 상태
docker ps --filter name=user-service
docker logs --tail=100 user-service

# 2) 기동 블로커 확인 (문제점 1/2)
docker logs user-service 2>&1 | grep -iE "ModuleNotFoundError|prompt_toolkit|could not connect|authentication failed"

# 3) health (호스트 32031 → 컨테이너 8080)
curl -s http://localhost:32031/api/health        # 기대: {"status":"ok"}
curl -s http://localhost:32031/docs -o /dev/null -w "%{http_code}\n"  # 200

# 4) internal 라우터 등록 여부 (문제점 1이 해결됐다는 방증)
curl -s http://localhost:32031/openapi.json | grep -o "/api/internal[^\"]*" | sort -u
```

---

## 7. 토큰 재발행 / Silent Refresh 분석 (SSE 튕김 이슈)

### 7.1 배경
어드바이저 상담 페이지가 **SSE 장기 연결** 중 access token이 만료되면, 그 세션에서 호출하는 user-service API가 **401을 반환하며 튕김**. 자동 갱신(silent refresh)이 필요한데 이 서버엔 없음.

> 용어: **ECP = ECS Portal** (협력업체 포털). 어드바이저는 이 토큰 체계에 물려 있음.

### 7.2 결론
> **user-service는 토큰을 "검증 위임"만 하는 소비자다. 갱신(refresh) 주체가 아니고, 쿠키를 아예 만지지 않으며, SSE도 여기 없다.** silent refresh가 이 서버에 없는 게 정상이고, 있어야 할 곳도 여기가 아니다.

| 확인 | 결과 |
|---|---|
| 쿠키 처리(`cookie`/`set_cookie`) | **전무** — BFF silent refresh 전제(쿠키 접근) 자체가 없음 |
| SSE(`StreamingResponse`/`text/event-stream`) | **전무** — SSE 연결은 어드바이저 백엔드 쪽 |
| refresh/재발행/`jwt.encode`/PyJWT import | **전무** — 토큰을 만들지 않음 |

### 7.3 "튕기는" 정확한 코드 경로
```
어드바이저 BFF → user-service (헤더: X-auth-token = 만료 JWT)
  ▼ Depends(auth_dependency)                     utils/auth_utils.py:19
     ├─ 'tenant_' 로 시작 → 403 "ECP 토큰으로 교체하세요"   (line 24-26)
     └─ AuthClient.verify_token(token)            auth_utils.py:30
          ▼ GET auth-service /api/auth/verify_token?token=…   auth_client.py:21
            (만료 → auth-service 4xx) → raise_for_status 실패 → HTTPException(401,"token 만료")  auth_client.py:32
  ▼ auth_dependency except가 다시 감쌈 → HTTPException(401,"토큰 인증 실패")   auth_utils.py:34-36
  ▼ SSE 세션이 401 받고 끊김  ← "튕김"
```
user-service는 만료 감지 시 **오직 401만 던짐** — 재시도·갱신·쿠키확인 없음. 순수 pass-through.

### 7.4 ECP 연동 실체 (재발행에 필요한 부품 점검)
| 필요 요소 | 현재 | 근거 |
|---|---|---|
| ECP 클라이언트 | **읽기 전용 2개뿐**: `contact_center_groups`, `my_account` | `clients/ecp_client.py:19,46` |
| ECP 설정 URL | 조직/계정 조회 2개만 | `config.py:34-35` |
| ECP 토큰/OAuth refresh URL | **없음** | grep 0건 |
| refresh token 보관 | **없음** (access token만 되씀) | 전 코드 |
| refresh 클라이언트 메서드 / 엔드포인트 | **없음** | `ecp_client.py`, `api/endpoints/*` |

이 서버는 인증 중계자: ECP 호출 Authorization으로 `auth.get('token')`(=auth-service verify 응답 속 token)을 그대로 되씀(`base_service.py:59,107,196` → `ecp_client.py:23`).
```
ECS Portal ──원본토큰──► auth-service ──verify 응답에 token 포함──► user-service ──► 다시 ECP 호출
```

### 7.5 ⚠️ 설계 함정 — 토큰 형식 경계
user-service는 **원본 ECP 토큰(`tenant_...`)을 직접 거부**(`auth_utils.py:24`)하고 **내부 JWT만** 받음.
→ ECP에 refresh하면 나오는 건 **새 ECP 토큰**인데, user-service는 그걸 거부함.
→ **결국 auth-service가 새 ECP 토큰을 내부 JWT로 재교환**해야 함. **ECP만 때려서는 완결 불가**, 어떤 경로든 auth-service를 반드시 거침.

### 7.6 설계안
**안 A — refresh를 auth-service가 소유 (권장)**
```
BFF(쿠키에 refresh_token) → 401 감지 → auth-service /api/auth/refresh
                                          └─ ECP OAuth refresh → 새 내부 JWT
                              → 새 JWT로 user-service 재시도
```
- 발급·교환·검증·갱신을 auth-service 한 곳에. 이 저장소는 손댈 것 없음.

**안 B — user-service에 refresh 엔드포인트 추가**
- 신규 필요: ①ECP refresh URL ②`ECPClient.refresh()` ③refresh 엔드포인트 ④refresh_token 수신 ⑤**auth-service 재교환 연동(불가피)**.
- 단점: 검증(auth-service)과 갱신(user-service)이 쪼개짐. 함정 때문에 auth-service 의존 못 없앰.

**권고**: 토큰 라이프사이클은 한 서비스(=이미 교환 로직 있는 auth-service)에 모으는 안 A. user-service는 "중계자"로 유지 = 갱신을 소유하지 않는 게 맞음. 단, silent refresh를 **트리거하는 주체는 어드바이저 BFF**(쿠키·401 인터셉트·SSE 재연결).

### 7.7 현재 실제 운영 구조 (개발자 첨언, 2026-07-03)
> 아래는 코드가 아니라 개발자가 확인해준 **현행 실제 동작**이며, 개선 대상.

- 어드바이저는 현재 **프론트엔드가 직접 토큰 만료를 감지**해서 **ECP 인증서버로 바로 재발행 요청**하는 구조.
- 포털사이트가 **sessionStorage**에 토큰 보관 → **XSS 공격 노출 위험** 있음.
- 프론트가 만료를 체크해서 보내야 하는 구조 → **service 계층 + 인터셉터(interceptor)**에서 토큰 만료 확인 후 재발행하고 API 재호출하는 방식.
- 이 방식은 개발자가 직접 만든 적도, 써본 적도 처음인 낯선 구조. → **BFF 기반 silent refresh(쿠키+httpOnly)로 전환**하는 것이 목표.

**개선 방향 요약**: 프론트 주도(sessionStorage, XSS 위험) → **BFF 주도 silent refresh**(httpOnly 쿠키에 refresh_token, BFF가 401 인터셉트/재발행/재시도). 서버측 refresh API는 **안 A(auth-service 소유)** 권장.

---

## 8. ECP 토큰 관리 구조 — 객관적 보안 평가

> 평가 기준: OAuth 2.0 Security BCP(RFC 9700), IETF "OAuth 2.0 for Browser-Based Apps" BCP, OWASP.
> 상황·이해관계 배제하고 표준 일반론으로만 판정. (2026-07-03)

### 9.1 평가 대상 구조 (개발자 확인 사실)
1. SPA가 **access token + refresh token을 함께 sessionStorage**에 저장
2. 프론트가 만료 감지(service 계층 interceptor) → **인증서버(ECP)에 직접 재발행 요청** → API 재호출
3. access token 수명 **20분**
4. refresh token **rotation 없음** — 재발행 시 값 유지, 만료만 함께 연장(sliding)
5. bearer 토큰 (sender-constrained 아님)

### 9.2 두 축 분리 평가
**축 1 — 메커니즘(흐름): 정상 범주**
- "프론트 만료 감지 → 인터셉터 재발행 → 재시도"는 OIDC SPA의 전형적 silent renew 구현. 흐름 자체는 **문제 아님**.

**축 2 — 토큰 저장/수명/회전: 표준 미달**

| 사실 | 방향 | 판정 |
|---|---|---|
| refresh token이 web storage에 | 🔴 가장 치명적 | 장수명 자격증명이 XSS에 노출. 브라우저 refresh token은 rotation 필수(BCP)인데 위반 |
| access token 20분 | 🟢 양호 | 권장 방향이나 아래 이유로 효과 상쇄 |
| rotation 없음 + sliding 연장 | 🔴 치명적 | 도난 탐지·차단 불가. "쓰는 한 안 죽는" 사실상 영구 토큰 |

### 9.3 조합 위험 (핵심)
```
XSS 1건
 → sessionStorage에서 refresh token 탈취        (①)
 → rotation 없어 같은 refresh token 계속 사용     (④)
 → 쓸 때마다 만료 연장(sliding) → 사실상 영구 유효  (④)
 → 20분마다 새 access token 무한 발급 (③ 방어 못함)
 → bearer라 replay → 지속적·은밀한 계정 장악
 → rotation 부재로 도난 탐지/무효화 수단 없음
```
→ **20분 수명의 이점이 refresh token 상태로 인해 무력화됨.** 공격자는 20분마다 갱신만 하면 됨. access token 단명은 refresh token 탈취 앞에서 방어 기여 거의 없음.

### 9.4 심각도 판정
- 이전에 "조건부 High"라 한 조건(refresh token 노출·긴 수명·무회전·XSS 표면)이 **전부 나쁜 쪽으로 확정된 케이스**.
- **등급: High (실질적으로 Critical 근접).** 단일 XSS → 일시적 세션 탈취가 아니라 **지속적·영구적 계정 장악**으로 증폭.
- 유일 완화요소(20분)는 access token 단독 탈취 시나리오에만 유효, refresh token 탈취엔 무력.

### 9.5 표준 요구 최소 개선 (우선순위)
1. **refresh token rotation 도입** (one-time use, 재발급 시 새 값 + 구값 무효화) — 최우선. 도난 탐지·차단의 전제.
2. **refresh token을 web storage에서 제거** — 최소 메모리 보관, 이상적으로 **BFF httpOnly 쿠키**(브라우저에서 완전 제거).
3. **refresh token 절대 만료(하드 리밋)** — sliding 무한 연장 방지 상한.
4. (보강) 엄격한 CSP로 XSS 표면 축소, 가능 시 토큰 바인딩(DPoP/mTLS).

### 9.6 한 줄 결론
> **"짧은 access token(20분)"이라는 유일한 장점을, refresh token의 저장 위치·무회전·sliding 만료가 전부 무력화한다. 단일 XSS → 영구적 계정 장악으로 이어지는 High급 구조이며, 최우선 조치는 refresh token rotation 도입과 web storage 제거다.**

> 주의: 위 평가는 **ECP/어드바이저 프론트 영역**의 문제이며, 본 저장소(user-service)의 코드 결함은 아님. user-service는 검증 위임자로서 만료 시 401만 반환(§7).

---

## 9. 최종 결론 — 어드바이저 SSE 토큰 튕김 (§7·§8 종합)

> 2026-07-03 분석 종합. **회의 일정 미정** — 아래는 회의에서 방향 제안용 정리이며, 결정 시 재논의.

### 9.1 세 줄 결론
1. **SSE 튕김 원인**: user-service는 토큰 검증을 auth-service에 **위임만 하는 중계자**. 만료 시 401만 반환(§7). refresh·쿠키·SSE 로직이 여기 없는 건 정상이며, **이 서버 결함 아님.**
2. **보안 이슈(별개 영역)**: ECP 토큰이 access+refresh 모두 sessionStorage에 저장 + rotation 없음 + sliding 만료 → 단일 XSS로 **지속적 계정 장악 가능한 High(≈Critical)**(§8). 단, **ECP/어드바이저 프론트 영역**의 문제.
3. **해법 방향**: 어드바이저 **BFF가 토큰 커스터디 + 서버측 refresh**를 맡으면 §7(튕김)·§8(XSS)이 **동시 해결**.

### 9.2 해법 구조 (권고)
```
[브라우저]  httpOnly 세션쿠키만 (sessionStorage 토큰 제거)
   ▼
[어드바이저 BFF]  토큰(access+refresh) 서버측 보관 · 만료 시 서버에서 /auth/refresh 호출 · 재시도
   ▼
[user-service]  새 토큰 주입 재호출 (변경 없음)   ← ECP·auth-service도 변경 없음
```
- BFF가 `https://ecplab-gw.etaas.co.kr/auth/refresh`를 **서버측에서 호출** 가능(값 기반 refresh_token, **서버-투-서버라 CORS 무관**).
- 현재 프론트가 ECP-refresh 토큰으로 user-service를 정상 호출 중 → 그 토큰은 이미 user-service가 수용하는 형태 → **auth-service 재교환 불필요**(초기 §7.5 우려 철회).

### 9.3 핵심 제약의 정확한 프레임
- ❌ 오해: "ECP가 토큰 구조를 안 바꿔줘서 불가."
- ✅ 실제: **로그인 핸드오프(프론트→BFF 1회 전달 후 브라우저에서 제거)는 ECP 변경 불필요.** ECP는 현 구조 유지, 타 서비스 영향 0.
- ✅ **진짜 걸림돌 = 어드바이저 프론트가 sessionStorage에 강결합**되어 호출부 다수를 BFF 경유로 바꿔야 하는 **내부 리팩터링 비용/리스크.**
- 즉 "불가능"이 아니라 **"지금은 비용 대비 안 함"의 의사결정.** (미루는 것도 합리적, 단 영구 차단은 아님)

### 9.4 미채택 시 차선 (ECP·BFF 없이 프론트만으로)
- access token은 **메모리 변수만**(sessionStorage 미보관), refresh는 **hidden iframe `prompt=none` silent renew**(ECP 세션 기반), **엄격 CSP + 서드파티 스크립트 최소화.**
- §8 위험을 완전 제거는 못 해도 크게 낮춤. ECP 변경 0. (BFF보다는 열등)

### 9.5 회의 전 확인하면 좋은 사실 (선택)
- ECP `/auth/refresh`가 refresh_token 값만 받나, 브라우저 세션 쿠키/Origin을 추가로 요구하나 (BFF 서버측 호출 가능 여부 확정)
- 어드바이저 SPA ↔ BFF 오리진 동일 여부 (httpOnly 쿠키 전략)
- auth-service의 내부 refresh 엔드포인트 유무 (완성형 경로 §7.6 안 A 성립 여부)

---

## 10. 미해결 / 다음 분석 대상
- [ ] `/api/user/exist` 시그니처·인증 부재 재확인 (auth-service HMAC 수신 검증 여부)
- [ ] `permission` 다중 업데이트에서 이전 agent 값 오염 가능성 코드 검증
- [ ] `phone/update_phone_data`의 `direction` vs `mgmt.phone_numbers` 컬럼 불일치
- [ ] ECP agent 보정 생성의 부분성공/실패 처리
- [ ] `prod.company.*_config` 복호화 경로와 키 관리(`crypt_manager.py`)
- [ ] 실서버 컨테이너에서 문제점 1(prompt_toolkit) 현재 발생 중인지 로그 확인

---

## 변경 이력
| 날짜 | 내용 |
|---|---|
| 2026-07-03 | 1차 분석: 개발 스택·구조·아키텍처·워크플로우·외부연동·문제점 정리 |
| 2026-07-03 | 토큰 재발행/Silent Refresh 분석 추가(§7): SSE 튕김 경로, ECP 연동 실체, tenant_ 형식 함정, 설계안 A/B, 현행 프론트 주도 구조(sessionStorage/XSS)와 BFF 전환 목표 |
| 2026-07-03 | ECP 토큰 관리 객관적 보안 평가 추가(§8): refresh token web storage 저장 + rotation 부재 + sliding 만료 조합 → High(≈Critical) 판정, 최우선 개선안(rotation·web storage 제거·하드 리밋) |
| 2026-07-03 | 최종 결론 추가(§9): 어드바이저 BFF 토큰 커스터디 해법으로 §7·§8 동시 해결, ECP/user-service 불변, 진짜 제약=프론트 sessionStorage 강결합에 따른 내부 리팩터링 비용(불가 아님, 비용 판단). 회의 미정 |

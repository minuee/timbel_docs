# CLAUDE 작업 히스토리 (user-service)

> Claude와 함께한 작업 기록. 다음 세션에서 이어서 진행하기 위한 요약.
> 상세 코드 분석은 `docs/operation_check.md` 참고.

---

## 2026-07-03 — 로컬 개발환경 구축 (맥북)

### 목표
파이썬 프로젝트인 user-service를 **로컬 맥북에서 구동**. (로컬 PostgreSQL/Redis는 이미 기동 중)

### 최종 상태: ✅ 로컬 기동 성공
- `http://localhost:32021/docs`, `/api/health` → `{"status":"ok"}` 확인
- DB 테이블 구조까지 생성 완료 (데이터는 아직 0행)

---

### 1. 환경 구성

| 항목 | 내용 |
|---|---|
| Python | **3.11.15** (Homebrew `python@3.11`, 시스템 3.9.6은 그대로 둠) |
| 가상환경 | 프로젝트 루트 `.venv` (`python3.11 -m venv .venv`) |
| 의존성 | `requirements.txt` 전부 설치 완료 |
| 설정 | `.env` 생성 (계정/비번/RSA 키 — **비밀값은 .env 파일 참조**) |

**로컬 인프라 (native, Docker 아님)**
- PostgreSQL: `/opt/homebrew/opt/postgresql@17` (PG 17.10), 포트 5432, data dir `/opt/homebrew/var/postgresql@17`
- Redis: localhost:6379 (auth 없음)
- 맥에 PostgreSQL은 **이 하나뿐** (Postgres.app/Docker/다른 인스턴스 없음)

**PostgreSQL 계정 / DB**
- role: `aicc_admin` (앱 접속용, CREATEDB 권한 없음 / LOGIN 가능), `seongnamnoh` (mac 계정 = 슈퍼유저)
- localhost TCP는 **trust 인증** (비번 없이도 접속됨)
- DB `tenant_management` — **owner `aicc_admin`** 으로 생성함
  - `aicc_admin`이 CREATEDB 권한이 없어서, 슈퍼유저로 `CREATE DATABASE tenant_management OWNER aicc_admin` 미리 생성 → 앱의 `ensure_database_exists()` CREATE 실패 회피
- 접속: `psql -h 127.0.0.1 -p 5432 -U aicc_admin -d tenant_management`
  - ⚠️ `-d` 안 주면 psql이 DB명을 유저명으로 기본설정 → `database "aicc_admin" does not exist` 에러남 (정상 동작)

---

### 2. 만든 파일 (모두 커밋 대상, gitignore 안 걸림)

| 파일 | 용도 |
|---|---|
| `start.sh` | 실행 스크립트. venv 없으면 자동 생성+설치, `.env` 확인, `python main.py`. 실행 시 `.server.pid` 기록 |
| `stop.sh` | `.server.pid` 기반 종료 (자식 reload 워커까지, 5초 후 SIGKILL) |
| `create_tables.py` | 로컬 테이블 생성 유틸. `MainBase.metadata.create_all()`로 19개 테이블 생성 (idempotent) |
| `.env` | **gitignore 처리됨** (커밋 안 됨). 로컬 계정+RSA 개인키 포함 |

`.gitignore`에 `.venv/`, `__pycache__/`, `.server.pid` 추가함.

**실행 방법**
```bash
cd /Users/seongnamnoh/Documents/WorkSpaces/gitlab/user-service
./start.sh          # → http://localhost:32021/docs
./stop.sh           # 종료
# 또는 수동: source .venv/bin/activate && python main.py
```

---

### 3. DB 테이블 생성 (operation_check.md §5-3 우회)

`init_db()`가 스키마만 만들고 테이블 생성을 안 하는 문제 → `create_tables.py`로 우회.
모든 모델이 단일 `MainBase` 상속이라 `create_all`로 FK 순서까지 자동 정렬.

`tenant_management`에 **총 19개 테이블 생성됨** (owner `aicc_admin`):
```
mgmt    (7)  callbot, chatbot, organizations, phone_number_groups,
             phone_numbers, tenant_history, users
prod    (6)  agents, centers, company, parts, teams, tenants   ← 런타임 기준 데이터
staging (6)  agents, centers, company, parts, teams, tenants
```
- `prod` 스키마는 `init_db`가 원래 빠뜨리는 것 → `create_tables.py`가 함께 생성
- **데이터는 0행** (구조만 있음)

> DBeaver에서 안 보이면: 연결 우클릭 → **Invalidate/Reconnect** (스키마 캐시 때문에 F5로는 안 뜰 수 있음. "Show all databases" 옵션과 별개로 재접속 필요)

---

### 4. 기동 블로커 처리 결과 (operation_check.md §5 대조)

| 블로커 | 상태 |
|---|---|
| §5-1 `prompt_toolkit` 미설치 | ✅ 통과 — celery 의존성(celery→click-repl→prompt-toolkit)으로 자동 설치됨. 단 미사용 import라 fragile → 나중에 `service/prod_tenant_service.py:3` 삭제 권장 |
| §5-2 import 시점 DB 접속/CREATE | ✅ 회피 — DB 미리 생성해서 CREATE 분기 안 탐 |
| §5-3 `init_db()` 테이블 미생성 | ✅ 우회 — `create_tables.py`로 생성 |

---

### 5. 알아둘 한계 (로컬 기준)
- **외부 서비스 부재**: `auth-service` / `tenant-mgmt-service` / `ECP GW`가 로컬에 없음 → 인증·조직조회 API는 실제 호출 실패. 서버 부팅/`/docs`/구조 확인/디버깅까지는 문제없음.
- **데이터 0행**: 조회 API는 빈 결과. 실제 흐름 태우려면 `company→tenant→center→team→part→agent` 순서로 시드 필요.
- **DB 비번 평문 로그**: `DEBUG=True`라 `db/database.py:26`에서 DATABASE_URL(비번 포함) 콘솔 출력됨. 로컬 전용.

---

### 6. 다음에 할 수 있는 것 (TODO)
- [ ] 최소 시드 데이터 삽입 (company 1 + agent 1 등) → 로그인/조직조회 흐름 검증
- [ ] `service/prod_tenant_service.py:3` 미사용 `prompt_toolkit` import 삭제
- [ ] (선택) `init_db()` 자체를 고쳐서 서버 기동 시 테이블 자동 생성되게
- [ ] `create_tables.py` 커밋 여부 결정 (로컬 전용이면 gitignore)
- [ ] operation_check.md §10 미해결 항목들 (§5-6 get_exist_user None 방어 등)

# Docker 배포 가이드 (asst-service / 192 개발기 기준)

> 도커를 처음 다루는 사람을 위한 가이드. **설치 → 핵심개념 → 이 프로젝트 배포 → 자주 쓰는 명령 → 트러블슈팅**을 192 개발기(`192.168.101.192`, API Gateway 없음) 실제 배포 경험으로 정리했다.

---

## 0. 한눈에 보는 배포 흐름

```
git clone → 브랜치 checkout → docker compose up -d --build → 헬스체크 → (스키마/테이블 1회 세팅)
```

192 개발기는 **CI/CD 없이 서버에 직접 git clone 후 docker로 띄우는** 방식이다.

---

## 1. 핵심 개념 5가지 (이것만 알면 됨)

| 개념 | 뜻 | 이 프로젝트 예시 |
|------|-----|------------------|
| **이미지(Image)** | 앱 + 런타임을 통째로 묶은 "템플릿". `Dockerfile`로 빌드 | `node:24-alpine` 기반으로 우리 앱 빌드 |
| **컨테이너(Container)** | 이미지를 실행한 "인스턴스"(격리된 프로세스) | `asst-service-dev` |
| **포트 매핑** | `외부포트:내부포트`. 밖에서 들어오는 포트를 컨테이너 안 포트로 연결 | `32025:3000` (외부 32025 → 안 3000) |
| **네트워크** | 컨테이너끼리 통신하는 가상 망. **같은 네트워크면 컨테이너 이름으로 서로 호출** 가능 | `timbel_network` |
| **환경변수 / env_file** | 컨테이너에 설정값 주입 | `.env.development` |

> **가장 중요한 직관**: 컨테이너는 "작은 독립 컴퓨터"다. 그래서 컨테이너 안의 `127.0.0.1`은 **호스트 서버가 아니라 컨테이너 자기 자신**을 가리킨다. (트러블슈팅 #3 참고 — 이거 때문에 제일 많이 헤맸다)

---

## 2. 설치 vs 사용 (sudo 권한 관계)

| 구분 | sudo 필요? | 설명 |
|------|-----------|------|
| Docker 엔진 **설치** | ✅ 필요 | 보통 **이미 설치돼 있음**(다른 서비스가 도커로 돌고 있으면 확실) |
| Docker **사용**(`docker ...`) | ❌ 불필요* | *내 계정이 `docker` 그룹에 속해 있어야 함 |

확인 명령:
```bash
docker version            # 버전 뜨면 설치+권한 OK
docker ps                 # permission denied 뜨면 → docker 그룹에 넣어달라고 인프라에 요청(sudo 작업)
docker compose version
```

### Node 버전과 도커
- **도커로 띄우면 서버의 Node 버전은 무관하다.** 컨테이너가 자체 Node를 포함하기 때문(`FROM node:24-alpine`).
- 컨테이너 안 Node 버전을 바꾸려면 **서버가 아니라 `Dockerfile`의 `FROM` 한 줄**만 바꾼다. (예: `node:20-alpine` → `node:24-alpine`)

---

## 3. 이 프로젝트의 도커 파일 3종

### `Dockerfile` — 이미지 빌드 레시피
```dockerfile
FROM node:24-alpine        # 베이스 이미지 (= 컨테이너 안 Node 버전)
...
RUN npm ci --ignore-scripts
RUN npm run build
CMD ["sh","-c","NODE_ENV=production node dist/src/main"]   # ⚠️ 기본 NODE_ENV=production 강제
```

### `docker-compose.dev.yml` — 컨테이너 실행 설정
```yaml
services:
  asst-service:
    build: .
    container_name: asst-service-dev
    ports:
      - '32025:3000'              # 외부 32025 → 내부 3000
    env_file:
      - .env.development          # ⚠️ 모든 호스트/DB/redis 설정은 여기서 주입
    environment:
      - NODE_ENV=development
    command: ['sh','-c','NODE_ENV=development node dist/src/main']   # ⚠️ Dockerfile의 production을 override
    networks:
      - timbel_network
networks:
  timbel_network:
    external: true                # 192에 이미 떠 있는 네트워크에 합류
```

**놓치기 쉬운 2가지:**
1. **`env_file`이 있어야** `.env.development`의 값들이 컨테이너에 들어간다. (없으면 USER_HOST/DB/redis 다 주입 안 됨)
2. **`NODE_ENV`는 `command` 안의 값이 진짜로 적용된다.** `Dockerfile`의 CMD가 `production`을 박기 때문에, compose의 `command`로 덮어써야 한다. `environment`만 바꾸면 command가 덮어써서 안 먹힌다.

### `.env.development` — 실제 설정값
호스트 주소, DB, redis 등. 192 환경에 맞춘 값이 들어있다 (아래 4번 참고).

---

## 4. 192 개발기 배포 실전 설정 (이번 케이스)

192 개발기는 **API Gateway가 없어서**, 게이트웨이(`*.langsa.ai`)로 가던 요청을 **각 백엔드 서비스 직접 주소**로 바꿔야 한다.

| 항목 | 값 | 이유 |
|------|-----|------|
| 외부 포트 | **32025** | 32020번대(업무 서비스용)만 방화벽 개방. **32099 등은 막혀 있음** |
| 네트워크 | `timbel_network` (external) | 192에 이미 떠 있는 도커 네트워크에 합류 |
| `USER_HOST` | `http://user-service:8080` | **같은 네트워크라 컨테이너 이름**으로 통신 (코드가 뒤에 `/api/...` 붙임) |
| `CE_HOST` | `http://192.168.101.192:32021` | 192 ce-service (호스트포트). langsa.ai는 VPN 정책으로 192에서 timeout |
| redis | `192.168.101.192:32014`, `REDIS_TLS=false` | 호스트포트 방식. **비TLS** redis라 TLS 끔 |
| DB | `192.168.101.192:32011` (`DB_DIRECT_CON=1`) | 테넌트 DB 미연동이라 **192 postgres 직결**. 테넌트 DB 준비되면 `0`(동적연결)으로 |
| `CORS_ALLOWED_ORIGINS` | `http://192.168.101.192:32026` | 게이트웨이 없는 직접배포라 백엔드가 CORS 직접 처리 (프론트 origin) |

> **호스트 지정 두 방식**:
> - **같은 도커 네트워크**에 있으면 → 컨테이너 이름 (`user-service:8080`) ← 깔끔
> - 네트워크가 다르거나 확실치 않으면 → **호스트IP:포트** (`192.168.101.192:32014`) ← 항상 작동

---

## 5. 자주 쓰는 명령어 모음

```bash
# 빌드 + 실행 (코드가 바뀌었을 때)
docker compose -f docker-compose.dev.yml up -d --build

# 설정(.env/compose)만 바뀌었을 때 — 재빌드 없이 컨테이너만 재생성
docker compose -f docker-compose.dev.yml up -d --force-recreate

# 상태 확인
docker ps | grep asst                  # 떠있나 + 포트 매핑
docker ps | grep -i postgres           # DB 컨테이너 찾기

# 로그
docker compose -f docker-compose.dev.yml logs --tail=80     # 최근 80줄
docker compose -f docker-compose.dev.yml logs -f            # 실시간 (Ctrl+C로 나옴)

# 컨테이너 안으로 들어가기 / 환경변수 확인
docker exec -it asst-service-dev sh
docker exec asst-service-dev env | grep NODE_ENV            # NODE_ENV 확인

# DB 접속 (psql)
docker exec -it <postgres컨테이너> psql -U aicc_admin -d aicc -c "\dt advisor.*"   # 테이블 목록
docker exec -it <postgres컨테이너> psql -U aicc_admin -c "\l"                       # DB 목록

# redis 확인
docker exec <redis컨테이너> redis-cli -a '<비번>' ping       # PONG 이면 OK

# 중지 / 네트워크 확인
docker compose -f docker-compose.dev.yml down
docker network ls | grep timbel

# 헬스체크
curl http://localhost:32025/api/asst/v1/health/check

## docker log 실시간 확인 
docker compose -f docker-compose.dev.yml logs -f
```

---

## 6. 트러블슈팅 — 이번에 실제로 겪은 것들 (제일 중요)

| # | 증상 | 원인 | 해결 |
|---|------|------|------|
| 1 | 빌드가 이미지/npm 단계에서 멈춤 | 폐쇄망이라 Docker Hub/npm 접근 불가 | 사내 레지스트리/프록시 사용 (이번엔 인터넷 됐음) |
| 2 | 브라우저에서 접속 안 됨 (근데 서버 `localhost`에선 200) | **외부 방화벽이 그 포트를 안 열어줌** (32099) | 방화벽 열린 포트 범위로 변경 (→ 32025) |
| 3 | `ECONNREFUSED 127.0.0.1:5432` | **컨테이너 안 `127.0.0.1`은 컨테이너 자기 자신** | host를 `192.168.101.192`(호스트IP)로 |
| 4 | redis `연결 타임아웃` 무한 재시도 | 비TLS redis에 `REDIS_TLS=true`로 붙으려다 핸드셰이크 실패 | `REDIS_TLS=false` |
| 5 | redis `WRONGPASS` | 비밀번호 틀림 | 컨테이너 실행설정에서 진짜 비번 확인 (`docker inspect`) |
| 6 | `NODE_ENV`가 development인데 안 바뀜 | `command:` 안의 `NODE_ENV`를 안 바꿈 (environment만 바꿈) | compose의 **command + environment 둘 다** 변경 |
| 7 | `relation "advisor.notices" does not exist` (42P01) | 스키마(껍데기)만 있고 **테이블이 없음** | 테이블 생성 필요 (아래 7번) |
| 8 | DB 설정 바꿨는데 그대로 | `.env` 바꾼 뒤 컨테이너 재생성 안 함 | `up -d --force-recreate` |
| 9 | 프록시 호출 **502 Bad Gateway** | asst가 업스트림(예: CE) 호스트에 못 닿음 (langsa.ai가 VPN 정책으로 timeout) | 업스트림을 192 주소로 교체 (`CE_HOST=192.168.101.192:32021`) |
| 10 | 브라우저 **CORS / `ERR_NETWORK`** | 게이트웨이+백엔드가 ACAO 헤더 **중복** (또는 백엔드 CORS 미설정) | 한쪽만 CORS 처리 (게이트웨이 경유=게이트웨이, 직접배포=`CORS_ALLOWED_ORIGINS`) |
| 11 | `--build` 중 `npm ci` **ETIMEDOUT** (호스트는 레지스트리에 정상 접속되는데) | `docker compose`가 **buildx bake 경로**로 빌드하면 compose의 `build.network: host`가 **빌드 컨테이너에 적용 안 됨** → 빌드가 bridge로 돌다 timeout | **`COMPOSE_BAKE=false`** 로 classic 빌드 경로 사용 (아래 #6-1 참고) |

**디버깅 황금률**: "브라우저에서 안 된다"면 먼저 **서버에서 `curl localhost`로 확인** → 되면 네트워크/방화벽 문제, 안 되면 앱 문제. 그리고 **항상 `docker compose logs`를 본다.**

### 6-1. `npm ci` ETIMEDOUT — bake가 `network: host`를 무시하는 문제 (asst-web 빌드)

**증상**: `docker compose -f docker-compose.dev.5f.yml up -d --build` 시 빌드의 `RUN npm ci` 단계에서, public npm 패키지는 일부 받아지다가 중간에 `npm error network read ETIMEDOUT` 으로 죽음.

**진단 순서**:
1. 빌드 로그 맨 위에 `=> [internal] load local bake definitions / reading from stdin` 가 보이면 → 지금 **buildx bake** 경로로 빌드 중.
2. **서버 호스트**에서 레지스트리 직접 접속 테스트 (컨테이너가 아니라 호스트 네트워크 확인):
   ```bash
   # GitHub Packages(@timbel-aicc/ecp-ui-kit) 접속 확인 — 200 + 1초 이내면 호스트는 정상
   curl -sw "\nHTTP:%{http_code} time:%{time_total}s\n" -o /dev/null --max-time 20 \
     -H "Authorization: Bearer <.npmrc의 _authToken>" \
     https://npm.pkg.github.com/@timbel-aicc/ecp-ui-kit
   ```
   호스트는 200인데 빌드만 timeout이면 → **빌드 컨테이너의 네트워크 문제**(host 네트워크 미적용)로 확정.

**원인**: compose의 `build.network: host` 는 classic 빌드에선 먹지만, **bake 경로에선 빌드 컨테이너에 제대로 전달되지 않음**. 그래서 빌드가 기본 bridge 네트워크로 돌고, (메타데이터 같은 작은 요청은 되지만 큰 tarball read에서) timeout 난다.

**해결** — bake를 꺼서 classic 빌드 경로로 돌리면 `network: host`가 정상 적용됨:
```bash
COMPOSE_BAKE=false docker compose -f docker-compose.dev.5f.yml up -d --build
```
검증용 1줄 (host 네트워크가 진짜 해결책인지 단독 확인):
```bash
docker build --network=host -f Dockerfile.dev -t test-build .
```

> 참고: `docker-compose.dev.5f.yml` 의 `build.network: host` 는 **호스트의 네트워크/DNS/프록시를 빌드에 그대로 쓰게** 하는 설정이라 빠뜨리면 안 된다. bake만 안 쓰면(`COMPOSE_BAKE=false`) 이 설정이 살아난다.

---

## 7. 스키마 / 테이블 생성 (이 서비스의 특수 규칙)

빈 DB(192처럼 새로 띄운 postgres)는 테이블이 자동으로 다 생기지 않는다. 규칙:

| 대상 | 자동? | 방법 |
|------|-------|------|
| `notices`/`todos`/`memos` 등 기존 핵심 테이블 | ❌ | **최초 1회 수동 생성** (아래 synchronize 방식 권장) |
| `emotion`/`callstat_voc`, coaching 컬럼 등 | ✅ | `runSchemaMigrations`가 연결 시 자동 (`IF NOT EXISTS`) |
| 엔티티 전체 자동생성(`synchronize`) | ⚠️ | **`NODE_ENV=local`에서만** 켜짐 (배포는 development라 OFF) |

### 빈 DB에 전체 테이블 한 번에 까는 법 (권장)
엔티티 기반 `synchronize`를 **일회성**으로 켠다. (빈 DB라 데이터 손실 위험 0)

```bash
# 1) NODE_ENV를 local로 (2곳 다 — command 포함)
sed -i 's/NODE_ENV=development/NODE_ENV=local/g' docker-compose.dev.yml
docker compose -f docker-compose.dev.yml up -d --force-recreate
docker exec asst-service-dev env | grep NODE_ENV          # NODE_ENV=local 확인

# 2) API 한 번 호출(Swagger) → synchronize가 전체 테이블 생성
docker exec -it <postgres컨테이너> psql -U aicc_admin -d aicc -c "\dt advisor.*"   # 테이블 확인

# 3) ⚠️ 반드시 development로 원복 (켜둔 채 운영하면 스키마 자동변경 위험)
sed -i 's/NODE_ENV=local/NODE_ENV=development/g' docker-compose.dev.yml
docker compose -f docker-compose.dev.yml up -d --force-recreate
```

### ⚠️ 하지 말 것
- **`advisor-schema-ddl.sql`은 쓰지 마라** — MySQL/MariaDB 문법(`INT(1)`, `ON UPDATE CURRENT_TIMESTAMP`, 인라인 `COMMENT`)이라 PostgreSQL에서 syntax error 나고, 최근 테이블도 빠져 있는 낡은 문서다.
- **`database.config.ts`의 synchronize를 바꾸지 마라** — 이 파일은 런타임에 wiring되지 않아(never wired up) 아무 효과 없다. 실제 연결은 `dynamic-database.service.ts`가 한다.

---

## 8. 요약 체크리스트 (새 환경에 다시 띄울 때)

1. `docker version` / `docker ps` 로 도커 사용 가능 확인
2. `docker network ls | grep <네트워크>` 로 합류할 네트워크 확인
3. `git clone` → 브랜치 checkout
4. `.env.development` 의 호스트들을 그 환경에 맞게 (게이트웨이 없으면 직접 주소 / 같은 네트워크면 컨테이너명)
5. `docker-compose.dev.yml` 의 포트(방화벽 열린 범위) + 네트워크 확인
6. `docker compose -f docker-compose.dev.yml up -d --build`
7. `curl localhost:<포트>/api/asst/v1/health/check` → 200
8. (빈 DB면) 7번 방식으로 테이블 1회 생성 → development 원복
9. 토큰 넣고 실제 API 호출 → DB 연동 확인

---

## 9. 서버를 원격(로컬 push본)으로 강제 정렬 — `git reset --hard`

서버에 로컬 수정이 쌓여 `git pull`이 충돌나거나 꼬일 때, **로컬을 원격에 올리고 → 서버를 그 원격 버전으로 강제로 덮어쓰는** 방법.

### 1) 로컬(맥)에서 푸시 — 원격에 올바른 버전부터 올리기

서버가 받아갈 게 원격에 있어야 하니까:
```bash
git add -A
git commit -m "chore: 192 dev 직결 설정 (env/docker/node24/npm/host_app/token)"
git push origin develop_nohsn      # 네 브랜치
```

### 2) 서버에서 원격 버전으로 강제 덮어쓰기

```bash
git fetch origin
git reset --hard origin/develop_nohsn   # 서버 로컬수정 다 버리고 원격과 100% 동일
git clean -fd                            # (선택) 추적 안 되는 새 파일/폴더까지 청소 — ⚠️ git에 없는 파일 삭제됨
```

### ⚠️ 주의

- `git reset --hard`는 **서버의 커밋 안 된 수정·작업을 전부 날린다** (되돌릴 수 없음).
- 지금은 *서버 수정 == 로컬 수정*(동일)이고 그걸 1)에서 푸시했으니 → 날아가도 원격에 그대로 있어 **안전**하다.
- 혹시 서버에만 있는 다른 수정이 걱정되면, 날리기 전에 확인/백업:
  ```bash
  git status      # 서버에서 뭐가 바뀌었나 확인
  git stash       # 백업 (나중에 git stash pop 으로 복구 가능)
  ```

### 한 줄 요약

> 로컬 `push` → 서버 `git fetch && git reset --hard origin/<브랜치>` = 서버가 깃 버전으로 깔끔하게 정렬, 충돌 없음.

**참고:**
- 서버 브랜치가 맞는지 `git branch`로 **먼저 확인** (전에 브랜치 함정이 있었으니).
- `.env.development`에 토큰이 들어있어서 push하면 원격에도 올라간다 — 기존에 `.env.local`도 토큰이 커밋돼 있던 레포라 관행상 문제는 없지만, 신경 쓰이면 **나중에 토큰 정리 한 번 권장**.

---

## 10. 브라우저로 실시간 로그 보기 (Dozzle) — Swagger처럼

서버에 SSH 들어가 `docker compose logs -f` 치는 대신, **브라우저 주소만 치면 실시간 로그**가 뜨게 하는 도구. `docker-compose.monitor.yml` 로 컨테이너 1개만 띄우면 된다. (우리 앱/코드는 안 건드림 — 도커 소켓을 read-only로 읽어서 모든 컨테이너 로그를 웹으로 보여줄 뿐)

### 띄우기
```bash
docker compose -f docker-compose.monitor.yml up -d            # 시작
docker compose -f docker-compose.monitor.yml logs --tail=20   # dozzle 자체 로그 확인
docker compose -f docker-compose.monitor.yml down             # 중지
```

### 접속
- 주소: **`http://192.168.101.192:32027`** (방화벽 열린 32020번대)
- 로그인: **ID `admin` / PW `lena47`**
- `docker compose logs -f` 와 동일한 실시간 스트리밍 + 검색/필터 + 여러 컨테이너(asst-service, postgres, redis…) 한 화면

### 계정/비밀번호 바꾸기
계정은 `monitor-data/users.yml` 에 정의돼 있고, 비번은 **bcrypt 해시**로 저장된다.
> ⚠️ Dozzle v8+ 부터 **sha-256 은 보안상 폐기**됐다(`sha256 passwords are no longer supported` fatal 로그). 반드시 bcrypt 를 써야 하며, **Dozzle 자체 `generate` 명령**으로 만드는 게 가장 안전하다.
```bash
# users.yml 통째로 재생성 (ID admin / PW 원하는값)
docker run --rm amir20/dozzle generate admin \
  --password '새비번' --name admin --email admin@timbel.net \
  > monitor-data/users.yml

cat monitor-data/users.yml      # password 가 $2a$... 로 시작하면 bcrypt 정상
docker compose -f docker-compose.monitor.yml up -d --force-recreate
```

### 트러블슈팅
| 증상 | 원인 | 해결 |
|------|------|------|
| 브라우저 접속 안 됨 (서버 `curl localhost:32027`은 됨) | 방화벽이 그 포트 미개방 | 32020번대 열린 포트로 변경 |
| `permission denied ... docker.sock` | 내 계정이 docker 그룹 아님 | 인프라에 docker 그룹 추가 요청 |
| 로그인 안 됨 | users.yml 해시/마운트 문제 | `./monitor-data:/data` 마운트 + 해시 재생성 확인 |
| 로그가 안 보임 | 대상 컨테이너가 stdout으로 로그 안 냄 | asst는 winston 콘솔로 stdout에 나가므로 정상 표시됨 |

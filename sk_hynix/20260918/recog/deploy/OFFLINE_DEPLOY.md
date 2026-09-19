# 망분리 서버 배포 가이드

> recog-backend를 폐쇄망 서버에 올리는 절차. 두 가지 경로를 다룬다.
> 작성 2026-09-19

**어느 경로인지 모르겠으면 A절부터 읽으세요.** 30초짜리 판정 명령이 있습니다.

---

## A. 먼저 — 어느 경로로 갈지 30초 만에 판정하기

배포 방법이 **두 가지**입니다. 서버가 도커 이미지를 받아올 수 있느냐로 갈립니다.

망분리 서버에서 이 명령 하나만 실행해 보세요.

```bash
docker run --rm python:3.11-slim apt-get update
```

| 결과 | 가야 할 경로 |
|---|---|
| 정상적으로 끝남 | **경로 1 — 서버에서 직접 빌드** (아래 B절, 훨씬 간단) |
| 멈추거나 에러 | **경로 2 — 오프라인 번들** (1절부터) |

이 한 줄이 Docker Hub(`python:3.11-slim` 받기)와 Debian 저장소(`apt-get`) 둘 다를
한 번에 확인해 줍니다. 이미지 빌드가 필요로 하는 게 정확히 이 둘입니다.

> `pip install`은 필요 없습니다. recog는 **외부 파이썬 패키지를 하나도 쓰지 않습니다**
> (표준 라이브러리 + ffmpeg). `requirements.txt` 자체가 없습니다.

---

## B. 경로 1 — 서버에서 직접 빌드 (권장, 되면)

소스만 서버에 올리면 됩니다. git clone 후 sftp로 올리든, 압축해서 올리든 상관없습니다.

```bash
# 1) 소스를 서버에 올린 뒤
cd <소스경로>/deploy

# 2) 설정 파일 준비
cp .env.recog.example .env.recog

# 3) 빌드 + 기동 (한 방에)
docker compose -f docker-compose.yml -f docker-compose.build.yml \
    --env-file .env.recog up -d --build
```

**이 경로의 장점:**

- 아키텍처 걱정이 없습니다. 서버에서 빌드하니 서버 아키텍처로 만들어집니다
  (arm64/x86_64 불일치 문제 자체가 발생하지 않습니다)
- 이미지 tar를 옮길 필요가 없습니다 (1.5GB 전송 생략)
- 소스가 서버에 남아 수정·재빌드가 쉽습니다

`docker-compose.build.yml`은 **이미지를 어떻게 얻을지만** 덮어씁니다.
포트·볼륨·네트워크·헬스체크는 `docker-compose.yml` 설정을 그대로 씁니다.

### 확인

```bash
curl http://127.0.0.1:28080/health
docker logs -f aimm-recog-backend
```

### 주의할 점

- **`runtime/` 소유권**: 컨테이너가 uid 10001로 돌기 때문에 권한 오류가 나면
  ```bash
  sudo chown -R 10001:10001 <데이터경로>
  ```
- **데이터 위치**: 아래 C절 참조. 기본값은 `deploy/runtime/`입니다.
- **네트워크**: `timblo-net-package`가 없으면 실패합니다. 5절 참조.

### 재빌드 (코드 수정 후)

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml \
    --env-file .env.recog up -d --build
```

같은 명령을 다시 돌리면 됩니다. `runtime/`은 보존됩니다.

---

## C. 데이터 저장 위치 (`RUNTIME_DIR`)

### 무엇이 저장되나

| 경로 | 내용 | 지워지면 |
|---|---|---|
| `<데이터경로>/sessions/` | 기존 `/sessions` 경로의 세션 데이터 | 해당 세션 유실 |
| `<데이터경로>/merge.db` | **병합 작업 기록 (SQLite, 90일)** | 이력·재작업 대상 유실 |
| `<데이터경로>/merge/` | 병합 중 임시 파일 (작업 끝나면 자동 삭제) | 무해 |
| `<데이터경로>/merge_results/` | 업로드 테스트 경로의 결과 파일 | 테스트 결과만 유실 |

**모두 호스트 디스크에 있습니다.** 컨테이너는 빌려 쓸 뿐이라, 이미지를 다시 만들거나
컨테이너를 지워도 그대로 남습니다.

### 기본값

`docker-compose.yml`이 있는 디렉터리 기준 `./runtime`입니다.

| 방법 | 실제 경로 |
|---|---|
| 경로 1 (서버 빌드) | `<소스경로>/deploy/runtime/` |
| 경로 2 (오프라인 번들) | `<설치경로>/runtime/` |

### 소스 밖으로 빼는 것을 권합니다

경로 1을 쓰면 데이터가 소스 트리 안에 들어갑니다. `.gitignore`에 `runtime/`이
있어서 `git pull`은 안전하지만, **sftp로 디렉터리를 통째로 덮어쓰면 같이 지워질 수 있습니다.**

`.env.recog`에서 절대경로로 바꾸면 됩니다.

```bash
RUNTIME_DIR=/var/lib/recog-runtime
```

```bash
sudo mkdir -p /var/lib/recog-runtime
sudo chown -R 10001:10001 /var/lib/recog-runtime
```

이러면 소스를 몇 번을 갈아엎어도 기록이 남습니다.

### 초기화해도 되는가

**됩니다.** 병합 기록은 감사·통계·재작업용이고, 실제 결과물(병합된 음성)은 이미
오브젝트 스토리지에 올라가 있습니다. 지워도 서비스 동작에는 영향이 없습니다.

```bash
docker compose down
rm -f <데이터경로>/merge.db
docker compose up -d          # 빈 DB로 새로 시작
```

### 백업

SQLite는 파일 하나라 복사만 하면 됩니다.

```bash
# 서버가 돌아가는 중에도 안전
sqlite3 <데이터경로>/merge.db ".backup /tmp/merge-$(date +%Y%m%d).db"
```

### 기록 보기

```bash
sqlite3 <데이터경로>/merge.db "SELECT room_no, status, finished_at FROM merge_jobs ORDER BY accepted_at DESC LIMIT 20"
sqlite3 <데이터경로>/merge.db "SELECT status, COUNT(*) FROM merge_jobs GROUP BY status"
```

API로도 볼 수 있습니다: `GET /v1/merge?limit=50`

> 조회 방법(API·Swagger·콘솔·PC로 가져오기)과 자주 쓰는 쿼리는
> `newDocs/03_병합기록_조회가이드.md`에 정리해 뒀습니다.
> **우분투에 `sqlite3` 명령이 기본 설치되어 있지 않을 수 있습니다.**
> 없으면 `python3`로 조회하면 됩니다(추가 설치 불필요).

---

## 경로 2 — 오프라인 번들 (서버가 이미지를 못 받아올 때)

여기서부터는 A절 판정이 실패했을 때의 절차입니다.


## 0. 왜 별도 절차가 필요한가

현재 이미지는 빌드할 때 **세 군데에서 네트워크를 탑니다.**

| 위치 | 내용 |
|---|---|
| `Dockerfile:17` | `FROM python:3.11-slim` — 베이스 이미지 pull |
| `Dockerfile:51` | `apt-get install ffmpeg curl` — 패키지 다운로드 |
| `docker-compose.yml` | `ghcr.io/...` — 레지스트리 pull |

망분리 서버에서는 셋 다 실패합니다. 그래서 **인터넷 되는 machine에서 이미지를 완성해
파일로 만들어 반입**하는 방식을 씁니다.

```
[인터넷 되는 PC]                      [망분리 서버]
 build_offline_bundle.sh
   docker build                        USB / 사내 파일서버
   docker save | gzip      ──────────►  install_offline.sh
   + compose + env + 문서                 docker load
   → recog-offline-*.tar.gz              docker compose up -d
```

> **좋은 소식**: recog는 pip 의존성이 0개입니다(파이썬 표준 라이브러리 + ffmpeg).
> 휠 파일을 따로 모아 반입할 필요가 없습니다. Swagger UI 자산도 저장소에 내장되어
> 있어 CDN 접근 없이 `/docs`가 뜹니다.

---

## 1. 준비물

**인터넷 되는 PC**
- Docker (데몬 실행 중)
- 이 저장소 소스
- Apple Silicon Mac이라면 `docker buildx` (아래 3절 주의사항 참조)

**망분리 서버**
- Docker + Docker Compose
- `timblo-net-package` 네트워크 (MinIO·master-api가 이미 쓰고 있으면 존재함)
- 디스크 여유 2GB 이상

---

## 2. 번들 만들기 (인터넷 되는 PC)

```bash
cd recog
./scripts/deploy/build_offline_bundle.sh
```

버전과 아키텍처를 지정하려면:

```bash
./scripts/deploy/build_offline_bundle.sh skHynix-v1.0.0 linux/amd64
```

결과물:

```
dist/recog-offline-<version>.tar.gz          ← 이 파일을 반입
dist/recog-offline-<version>.tar.gz.sha256   ← 무결성 확인용
```

번들 안에 들어가는 것:

| 파일 | 용도 |
|---|---|
| `recog-backend-<version>.tar.gz` | 도커 이미지 (ffmpeg 포함, 완성본) |
| `docker-compose.yml` | 배포 정의 |
| `.env.recog.example` | 설정 템플릿 |
| `install_offline.sh` | 설치 스크립트 |
| `OFFLINE_DEPLOY.md` | 이 문서 |
| `bundle.env` | 이미지 태그·플랫폼·빌드시각 기록 |
| `SHA256SUMS` | 전송 손상 검증 |

---

## 3. ⚠️ 아키텍처 — 가장 흔한 실패 원인

**M1/M2/M3 맥에서 그냥 빌드하면 arm64 이미지가 나옵니다.** 망분리 서버가 x86_64면
컨테이너가 기동조차 안 됩니다 (`exec format error`).

빌드 스크립트가 기본으로 `linux/amd64`를 지정하고, 빌드 후 실제 아키텍처를 검사해
경고를 냅니다. 설치 스크립트도 호스트 아키텍처와 비교해 불일치면 **설치 전에 중단**합니다.

서버 아키텍처 확인:

```bash
uname -m        # x86_64 → linux/amd64 , aarch64 → linux/arm64
```

맥에서 amd64로 빌드하려면 buildx가 필요합니다:

```bash
docker buildx create --use --name recog-builder   # 최초 1회
./scripts/deploy/build_offline_bundle.sh skHynix-v1.0.0 linux/amd64
```

---

## 4. 반입 후 설치 (망분리 서버)

```bash
# 1) 무결성 확인
sha256sum -c recog-offline-<version>.tar.gz.sha256

# 2) 풀기
tar xzf recog-offline-<version>.tar.gz
cd recog-offline-<version>

# 3) 설치할 위치를 지정해 실행 (생략하면 현재 디렉터리)
./install_offline.sh /home/jwpark/timblo-hynix/recog-backend
```

스크립트가 하는 일:

1. docker / compose 존재 확인
2. **아키텍처 일치 확인** (불일치면 중단)
3. SHA256 검증
4. `docker load`로 이미지 적재
5. `runtime/` 생성 + 소유권 `10001:10001` 설정
6. `.env.recog` 생성 (이미 있으면 건드리지 않음)
7. `IMAGE_NAME` / `RECOG_VERSION`을 적재한 이미지로 고정
8. `timblo-net-package` 네트워크 존재 확인
9. `docker compose up -d`
10. `/health` 200 확인 (최대 60초)

성공하면 이렇게 나옵니다:

```
  상태 확인 : curl http://127.0.0.1:28080/health
  API 문서  : http://<이 호스트>:28080/docs   (계정은 .env.recog 참조)
  로그      : docker logs -f aimm-recog-backend
```

### 유용한 옵션

```bash
SKIP_START=1 ./install_offline.sh      # 적재·설정만 하고 기동은 나중에
SKIP_CHECKSUM=1 ./install_offline.sh   # 검증 생략 (권장하지 않음)
```

---

## 5. 네트워크 연결

`/v1/merge`는 **두 방향 통신**이 필요합니다.

```
① recog → MinIO        presigned URL 호스트가 timblo-minio:9000 이므로
                       recog가 그 이름을 해석할 수 있어야 한다
② master-api → recog   폴링으로 상태를 조회하므로 recog에 닿아야 한다
```

그래서 compose에 외부 네트워크를 붙여뒀습니다:

```yaml
networks:
  - timblo-net-package
```

네트워크가 없으면 설치 스크립트가 중단하고 안내합니다. MinIO와 master-api가 이미
떠 있으면 존재하므로 보통 그냥 지나갑니다.

확인:

```bash
docker network inspect timblo-net-package --format '{{range .Containers}}{{.Name}} {{end}}'
# timblo-minio ... aimm-recog-backend 가 같이 보여야 정상
```

컨테이너 사이 연결 확인:

```bash
docker exec aimm-recog-backend python -c \
  "import urllib.request;print(urllib.request.urlopen('http://timblo-minio:9000/minio/health/live',timeout=3).status)"
```

> 네트워크명이나 컨테이너명이 환경마다 다르면 `docker-compose.yml`에서 바꾸면 됩니다.

---

## 6. 동작 확인

```bash
# 헬스체크
curl http://127.0.0.1:28080/health

# API 문서 (브라우저) — 계정은 .env.recog 의 SWAGGER_USER/SWAGGER_PASSWORD
http://<서버주소>:28080/docs

# 병합 동작 확인 — 스토리지 없이 파일만으로
curl -X POST http://127.0.0.1:28080/v1/merge/upload \
  -F "files=@p1.flac" -F "files=@p2.flac" \
  -F "align=none"
# → {"jobId":"mrg_...","status":"WAITING",...}

curl http://127.0.0.1:28080/v1/merge/mrg_...
# → {"status":"DONE","output":{...},"downloadUrl":"/v1/merge/mrg_.../download"}

curl -o merged.flac http://127.0.0.1:28080/v1/merge/mrg_.../download
```

---

## 7. 갱신 (새 버전 배포)

### 경로 1 (서버 빌드)

**같은 위치에서** 소스만 갱신하고 다시 빌드합니다.

```bash
cd <기존 소스경로>
git pull                       # 또는 sftp 로 덮어쓰기
cd deploy
docker compose -f docker-compose.yml -f docker-compose.build.yml \
    --env-file .env.recog up -d --build
```

`RUNTIME_DIR`을 건드리지 않으므로 병합 기록이 그대로 이어집니다.

> **새 디렉터리에 clone 하면 기록이 따라오지 않습니다.** 예전 경로에 그대로 남아 있을 뿐입니다.
> 위치를 옮기실 거면 `merge.db`를 같이 복사하거나, 애초에 `RUNTIME_DIR`을 소스 밖
> 절대경로로 잡아두세요 (C절).

### 경로 2 (오프라인 번들)

같은 절차를 반복하면 됩니다. 기존 `.env.recog`는 덮어쓰지 않고,
`IMAGE_NAME`/`RECOG_VERSION`만 새 이미지로 갱신됩니다.

```bash
./install_offline.sh /home/jwpark/timblo-hynix/recog-backend
```

`runtime/` 디렉터리는 그대로 유지되므로 기존 세션 데이터가 보존됩니다.

이전 이미지 정리:

```bash
docker images recog-backend
docker rmi recog-backend:<old-version>
```

---

## 8. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `exec format error` | 아키텍처 불일치 | 3절 참조. 또는 **경로 1(서버 빌드)로 전환하면 문제 자체가 없어짐** |
| 빌드 중 `Could not resolve 'deb.debian.org'` | 서버가 패키지 저장소에 못 감 | 경로 1 불가. 경로 2(오프라인 번들) 사용 |
| 빌드 중 `failed to resolve source metadata for docker.io/library/python` | Docker Hub 차단 | 경로 1 불가. 경로 2 사용 |
| `no such file or directory: Dockerfile` | `deploy/`가 아닌 곳에서 실행 | `cd deploy` 후 실행. context가 `..`로 잡혀 있음 |
| `network timblo-net-package not found` | 외부 네트워크 없음 | `docker network create timblo-net-package` 또는 MinIO 먼저 기동 |
| `Permission denied` (로그) | `runtime/` 소유권 | `sudo chown -R 10001:10001 <설치경로>/runtime` |
| `pull access denied` | `PULL_POLICY`가 never가 아님 | `.env.recog`에서 `PULL_POLICY=never` 확인 |
| 헬스체크 실패 | 포트 충돌 등 | `docker logs aimm-recog-backend` 확인 |
| `/docs`가 빈 화면 | — | 자산이 내장되어 있어 네트워크와 무관. `curl -u $SWAGGER_USER:$SWAGGER_PASSWORD .../docs/swagger-ui-bundle.js`로 200 확인 |
| `/docs` 접속 시 401 | 계정 불일치 | `.env.recog`의 `SWAGGER_USER` / `SWAGGER_PASSWORD` 참조 |
| presigned 다운로드 실패 | DNS 해석 실패 | 5절 네트워크 연결 확인 |
| 재배포 후 이력이 비어 있음 | `RUNTIME_DIR`이 바뀜 | C절. 예전 경로의 `merge.db` 확인 |
| `merge.db` 권한 오류 | 데이터 경로 소유권 | `sudo chown -R 10001:10001 <데이터경로>` |

로그 확인:

```bash
docker logs --tail 100 aimm-recog-backend
docker inspect aimm-recog-backend --format '{{.State.Health.Status}}'
```

---

## 9. 참고 — 호스트 정리 작업

세션 데이터·병합 잔여물을 주기적으로 지우는 systemd 타이머가 별도로 있습니다.

```bash
sudo ./scripts/deploy/install_cleanup_cron.sh
```

병합 작업은 성공·실패와 무관하게 자기 작업 디렉터리를 지우고, 프로세스가 죽어 남은
고아 디렉터리는 서버 기동 시 정리합니다. 이 타이머는 그 위의 추가 안전망입니다.

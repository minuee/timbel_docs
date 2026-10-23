# 서버 설치 — 최소 절차

> 이 문서만 보고 끝낼 수 있게 썼다. 망분리 서버에는 인터넷이 없으니,
> 막히면 맨 아래 **"막혔을 때"** 를 보면 된다.

---

## 0. 반입할 파일 5개

한 디렉터리에 **전부 같이** 두어야 한다. `install.sh` 가 자기 옆에서 tar 를 찾는다.

```
mobile-sync-server_0.0.1_amd64.tar          ← 이미지 (약 160MB)
mobile-sync-server_0.0.1_amd64.tar.sha256   ← 전송 검증용
install.sh
docker-compose.yml
.env.example
```

**예전 버전 tar 가 같은 디렉터리에 있으면 안 된다.** 있으면 설치가 중단된다
(어느 걸 띄울지 모호해지는 걸 막는 안전장치다). 새 버전을 올릴 때는 예전 tar 를 먼저 지울 것.

---

## 1. 서버에 필요한 것

| 항목 | 확인 명령 | 기대 |
|---|---|---|
| 도커 | `docker version` | 응답이 오면 OK |
| compose | `docker compose version` | 없으면 `docker-compose` 도 가능 |
| 아키텍처 | `uname -m` | `x86_64` |
| 계정 | `id aimm` | uid/gid 가 나오면 OK |
| 네트워크 | `docker network ls \| grep timblo-net` | 있어야 함 |
| 디스크 | `df -h /data` | 2GB 이상 여유 |

`timblo-net` 이 없으면 (보통 MinIO·master-api 가 이미 쓰고 있어 존재한다):

```bash
docker network create timblo-net
```

---

## 2. 설치 — 명령 3줄

```bash
cd <반입한 디렉터리>
chmod +x install.sh
./install.sh /data/timblo/mobile-sync-server
```

끝이다. 스크립트가 알아서 한다.

<details>
<summary>스크립트가 하는 일 (펼쳐보기)</summary>

1. 도커 / compose 존재 확인
2. 서버가 `x86_64` 인지 확인 — 아니면 중단
3. `.sha256` 으로 전송 무결성 확인
4. `docker load` 로 이미지 적재
5. `.env` 생성 (**이미 있으면 건드리지 않음**)
6. 적재한 이미지로 `IMAGE_NAME` / `IMAGE_VERSION` 고정
7. `aimm` 계정의 uid/gid 를 읽어 `RUN_UID` / `RUN_GID` 에 기록
8. 데이터 디렉터리 생성 + 그 uid/gid 로 소유권 설정
9. **그 uid 로 실제로 써 보고**, 안 되면 중단 (기동 후 재시작 루프 방지)
10. `timblo-net` 네트워크 확인
11. `docker compose up -d`
12. `/health` 200 확인 (최대 60초)

</details>

성공하면 이렇게 나온다.

```
  상태 확인 : curl http://127.0.0.1:9995/health
  API 문서  : http://<서버주소>:9995/docs   (계정은 .env 참조)
  로그      : docker logs -f mobile-sync-server
  중지      : cd ... && docker compose --env-file .env down
```

---

## 3. 설치 직후 — 비밀번호 변경

`.env` 의 `SWAGGER_PASSWORD` 가 `change-me` 다. 반드시 바꾼다.

```bash
cd /data/timblo/mobile-sync-server
vi .env                                    # SWAGGER_PASSWORD 수정
docker compose --env-file .env up -d       # 반영
```

이 계정은 `/docs` (API 문서 화면) 접근용이다. `/v1/merge` 자체는 인증이 없다
(도커 네트워크 내부에서만 부르는 API 라서).

---

## 4. 동작 확인

```bash
# ① 살아 있나
curl http://127.0.0.1:9995/health
# → {"status": "ok", "service": "recog"}

# ② 컨테이너 상태
docker ps | grep mobile-sync-server
# → Up ... (healthy)  가 보여야 한다

# ③ 네트워크에 붙었나
docker network inspect timblo-net --format '{{range .Containers}}{{.Name}} {{end}}'
# → timblo-minio ... mobile-sync-server 가 같이 보여야 정상
```

### 실제 병합까지 확인하려면

서버에 음성 파일이 없으면 컨테이너 안의 ffmpeg 로 만들면 된다.

```bash
cd /tmp
docker exec mobile-sync-server sh -c \
  'cd /tmp && ffmpeg -y -loglevel error -f lavfi -i "sine=frequency=440:duration=3" -ac 1 a.flac \
             && ffmpeg -y -loglevel error -f lavfi -i "sine=frequency=660:duration=3" -ac 1 b.flac'
docker cp mobile-sync-server:/tmp/a.flac .
docker cp mobile-sync-server:/tmp/b.flac .

curl -X POST http://127.0.0.1:9995/v1/merge/upload \
  -F "files=@a.flac" -F "files=@b.flac" -F "align=none"
# → {"jobId":"mrg_...","status":"WAITING",...}

curl http://127.0.0.1:9995/v1/merge/mrg_...
# → {"status":"DONE",...}

curl -o merged.flac http://127.0.0.1:9995/v1/merge/mrg_.../download
```

---

## 5. 새 버전 올리기 (다음날 이후)

```bash
cd /data/timblo/mobile-sync-server

# ① 예전 tar 를 먼저 지운다 (안 지우면 설치가 중단된다)
rm -f mobile-sync-server_0.0.1_amd64.tar*

# ② 새 tar 2개를 이 디렉터리에 올린다

# ③ 같은 명령을 다시
./install.sh /data/timblo/mobile-sync-server
```

**유지되는 것**

- `.env` — 비밀번호·포트 등 손댄 설정 (이미지 버전만 갱신된다)
- `merge.db` — 병합 이력 전부
- `sessions/` 등 데이터 디렉터리 전체
- 돌고 있던 병합 작업 — 재기동 후 **자동으로 처음부터 다시 돌아 완료된다**

컨테이너는 재시작이 아니라 **재생성(Recreated)** 된다. 다운타임은 몇 초다.

**롤백**

옛 이미지는 디스크에 남아 있으니 `.env` 의 `IMAGE_VERSION` 만 되돌리면 된다.

```bash
docker images mobile-sync-server              # 남아 있는 버전 확인
vi .env                                       # IMAGE_VERSION=0.0.1
docker compose --env-file .env up -d
```

옛 버전으로 내려도 DB 때문에 죽지 않는다. 로그에 경고만 남는다.

---

## 6. 일상 관리

```bash
# 로그
docker logs -f mobile-sync-server
docker logs --tail 100 mobile-sync-server

# 헬스 상태
docker inspect mobile-sync-server --format '{{.State.Health.Status}}'

# 중지 / 시작
cd /data/timblo/mobile-sync-server
docker compose --env-file .env down
docker compose --env-file .env up -d

# 병합 이력 (API 로. sqlite3 명령이 없어도 된다)
curl "http://127.0.0.1:9995/v1/merge?limit=20"
```

로그는 컨테이너당 10MB × 5개로 제한돼 있어 디스크를 채우지 않는다.

---

## 막혔을 때

### 설치 중 중단됐다

| 메시지 | 뜻 | 조치 |
|---|---|---|
| `docker 가 없다` | 도커 미설치/미기동 | `sudo systemctl start docker` |
| `이 서버는 ... 다` | 아키텍처 불일치 | `uname -m` 확인. `x86_64` 가 아니면 빌드 PC 에서 다시 만들어야 한다 |
| `이미지 파일이 여러 개다` | tar 가 2개 이상 | 예전 tar 를 지운다 |
| `체크섬 불일치` | 전송 중 파일 손상 | tar 를 다시 받아온다 |
| `... 에 ... 로 쓸 수 없다` | 데이터 경로 소유권 | 메시지에 나온 `sudo chown -R` 명령을 실행하고 재시도 |
| `network timblo-net not found` | 네트워크 없음 | `docker network create timblo-net` |

### 컨테이너가 재시작을 반복한다

```bash
docker logs --tail 50 mobile-sync-server
```

| 로그에 보이는 것 | 원인 | 조치 |
|---|---|---|
| `PermissionError: ... /var/lib/recog/runtime/...` | 데이터 경로 소유권 | `sudo chown -R aimm:aimm <RUNTIME_DIR>` 후 `docker compose ... up -d` |
| `exec format error` | 아키텍처 불일치 | 빌드 PC 에서 `x86_64` 로 다시 만들어야 한다 |
| `Address already in use` | 9995 포트 충돌 | `.env` 의 `HOST_PORT` 를 바꾸거나 쓰는 쪽을 정리 |

`<RUNTIME_DIR>` 값은 `.env` 에 있다: `grep RUNTIME_DIR .env`

### RHEL / CentOS / Rocky 계열이고 권한이 계속 안 맞는다

소유권을 맞췄는데도 `PermissionError` 가 나면 SELinux 일 수 있다.

```bash
getenforce        # Enforcing 이면 해당
```

`docker-compose.yml` 의 볼륨 줄 끝에 `:z` 를 붙이면 된다.

```yaml
    volumes:
      - ${RUNTIME_DIR:-./runtime}:/var/lib/recog/runtime:z
```

고친 뒤 `docker compose --env-file .env up -d`.

### `/health` 가 안 뜬다

```bash
docker ps -a | grep mobile-sync-server     # 컨테이너가 있긴 한가
docker logs --tail 50 mobile-sync-server   # 왜 죽었나
docker port mobile-sync-server 8080        # 포트 매핑이 맞나
```

### pull 을 시도하다 멈춘다

`.env` 의 `IMAGE_NAME` / `IMAGE_VERSION` 이 적재한 이미지와 다른 경우다.

```bash
docker images mobile-sync-server           # 실제 적재된 태그
grep -E "^IMAGE_(NAME|VERSION)=" .env      # .env 가 가리키는 값
```

두 값을 일치시키고 다시 `up -d`. compose 에 `pull_policy: never` 가 박혀 있어
레지스트리를 보지는 않지만, 이름이 어긋나면 "이미지 없음" 으로 즉시 죽는다.

### MinIO 에서 파일을 못 받아온다

`/v1/merge` 는 presigned URL 의 호스트명(`timblo-minio`)을 해석할 수 있어야 한다.

```bash
docker exec mobile-sync-server python -c \
  "import urllib.request;print(urllib.request.urlopen('http://timblo-minio:9000/minio/health/live',timeout=3).status)"
# → 200 이면 정상
```

실패하면 같은 네트워크에 있는지 확인한다.

```bash
docker network inspect timblo-net --format '{{range .Containers}}{{.Name}} {{end}}'
```

### 전부 다시 하고 싶다

데이터까지 버리고 처음부터:

```bash
cd /data/timblo/mobile-sync-server
docker compose --env-file .env down
sudo rm -rf <RUNTIME_DIR>          # ⚠️ 병합 이력이 사라진다
docker rmi mobile-sync-server:0.0.1
./install.sh /data/timblo/mobile-sync-server
```

병합 결과물은 이미 오브젝트 스토리지에 올라가 있으므로, 이력을 지워도
서비스 동작에는 영향이 없다.

---

## 최후의 수단 — 스크립트 없이 손으로

`install.sh` 가 어떤 이유로든 안 돌면, 하는 일은 결국 이것뿐이다.

```bash
cd <반입 디렉터리>

# ① 이미지 적재
docker load -i mobile-sync-server_0.0.1_amd64.tar
docker images mobile-sync-server                   # 태그 확인

# ② 설치 위치 준비
mkdir -p /data/timblo/mobile-sync-server
cp docker-compose.yml .env.example /data/timblo/mobile-sync-server/
cd /data/timblo/mobile-sync-server
cp .env.example .env

# ③ .env 에서 4줄만 확인/수정
#    IMAGE_NAME=mobile-sync-server
#    IMAGE_VERSION=0.0.1          ← ① 에서 본 태그와 같게
#    RUN_UID=<id -u aimm 값>
#    RUN_GID=<id -g aimm 값>
vi .env

# ④ 데이터 디렉터리 + 소유권
sudo mkdir -p /data/timblo/mobile-sync-server-runtime
sudo chown -R aimm:aimm /data/timblo/mobile-sync-server-runtime

# ⑤ 기동
docker compose --env-file .env up -d
curl http://127.0.0.1:9995/health
```

`install.sh` 는 여기에 검증 단계(체크섬·아키텍처·쓰기 권한·네트워크)를 얹은 것뿐이다.

---

## 한 장 요약

```bash
# 설치
cd <반입 디렉터리>
chmod +x install.sh
./install.sh /data/timblo/mobile-sync-server

# 비밀번호 변경
cd /data/timblo/mobile-sync-server && vi .env
docker compose --env-file .env up -d

# 확인
curl http://127.0.0.1:9995/health

# 새 버전
rm -f mobile-sync-server_<옛버전>_amd64.tar*
# 새 tar 올리고
./install.sh /data/timblo/mobile-sync-server
```

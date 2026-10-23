# mobile-sync-server 망분리 배포

망분리 서버는 **네트워크를 전혀 타지 않는다.** 이미지를 인터넷 되는 PC 에서
완성해 tar 로 반입하고, 서버는 `docker load` 만 한다.

```
[인터넷 되는 PC]                      [망분리 서버]

  ./deploy/build.sh
     └ 빌드 + 검증 + save        반입      ./install.sh
       ↓                      ────────►     └ docker load
  dist/mobile-sync-server_     (업로드/      └ docker compose up -d
      <버전>_amd64.tar          다운로드)
```

서버 쪽에는 네트워크를 타는 지점이 하나도 남지 않는다. 빌드 PC 쪽에서도
`FROM python:3.11-slim` 한 줄과 ffmpeg 바이너리 내려받기 두 군데뿐이다.

ffmpeg 는 apt 가 아니라 **static 빌드 바이너리**를 쓴다. Debian 의 `ffmpeg`
패키지는 `ffplay`(GUI 재생기)까지 들어 있는 풀빌드라 X11·Wayland·Vulkan·SDL2·
Mesa·LLVM 등 250여 개 패키지를 끌고 온다. 우리는 오디오만 쓰므로 전부 불필요하다.
static 으로 바꿔서 이미지가 208MB → 165MB 로 줄었고 ffmpeg 버전도 7.1 → 9.0 이 됐다.

---

## 문서

| 문서 | 언제 보나 |
|---|---|
| **`SERVER_INSTALL.md`** | **서버에서 설치할 때 — 이것만 보면 된다** |
| `README.md` (이 문서) | 빌드부터 배포까지 전체 흐름 |
| `REFERENCE.md` | 왜 이런 선택을 했는지, 무엇을 확인했는지 |
| `../newDocs/03_병합기록_조회가이드.md` | merge.db 조회·스키마·마이그레이션 |

---

## 파일

| 파일 | 어디서 쓰나 |
|---|---|
| `Dockerfile` | 빌드 PC |
| `build.sh` | 빌드 PC — ffmpeg 확보·빌드·검증·tar 생성 |
| `smoke_test.py` | 빌드 PC — build.sh 가 내부적으로 사용 |
| `.ffmpeg/` | 빌드 PC — build.sh 가 받아두는 static 바이너리 (git 제외) |
| `../VERSION` | 빌드 PC — 이미지 버전 (저장소 루트) |
| `install.sh` | **서버** |
| `docker-compose.yml` | **서버** |
| `.env.example` | **서버** — `.env` 로 복사해서 사용 |

---

## 1. 빌드 PC — 이미지 만들기

```bash
cd recog
./deploy/build.sh               # 저장소 루트의 VERSION 파일을 읽는다
./deploy/build.sh 0.0.2         # 태그를 직접 줄 수도 있다
```

### 버전

저장소 루트의 `VERSION` 파일 하나로 관리한다. node 의 `package.json` 버전과 같은 역할이다.

```
VERSION       ← 0.0.1
```

`build.sh` 가 결정하는 순서:

| 순위 | 출처 | 예 |
|---|---|---|
| 1 | 실행 인자 | `./deploy/build.sh 0.0.2` |
| 2 | `VERSION` 파일 | `0.0.1` |
| 3 | 오늘 날짜 (둘 다 없을 때) | `20260921` |

올릴 때는 `VERSION` 파일만 고치면 이미지 태그와 tar 파일명이 같이 따라간다.
변경 내역은 루트의 `BUILD_HISTORY.md` 에 한 줄씩 남긴다.

```
VERSION=0.0.1  →  mobile-sync-server:0.0.1
                  mobile-sync-server_0.0.1_amd64.tar
```

스크립트가 순서대로 한다:

1. ffmpeg static 바이너리 확보 (`deploy/.ffmpeg/` 에 캐시되어 두 번째부터는 건너뛴다)
2. `linux/amd64` 로 빌드
3. 정말 amd64 로 나왔는지 확인 — 아니면 중단
4. **컨테이너를 띄워 실제로 음성 두 개를 병합해 본다** (서버와 같이 비기본 uid 로) — 실패하면 중단
5. `docker save` 로 tar 생성

4번을 통과해야만 tar 가 만들어진다. 서버에 가서야 안 되는 걸 알게 되는 상황을 막는다.

다른 ffmpeg 빌드를 쓰려면:

```bash
FFMPEG_URL=https://.../ffmpeg-xxx-linux64-lgpl.tar.xz ./deploy/build.sh
```

결과물:

```
dist/mobile-sync-server_<버전>_amd64.tar
dist/mobile-sync-server_<버전>_amd64.tar.sha256
```

### Apple Silicon 맥에서 빌드할 때

서버가 x86_64 이므로 크로스 빌드가 된다. `docker buildx` 와 QEMU 가 필요하고
일반 빌드보다 느리다. `build.sh` 가 결과 아키텍처를 직접 검사하므로,
잘못 나오면 tar 가 만들어지지 않고 중단된다.

---

## 2. 반입

서버로 옮길 파일:

```
mobile-sync-server_<버전>_amd64.tar
mobile-sync-server_<버전>_amd64.tar.sha256
install.sh
docker-compose.yml
.env.example
```

전부 한 디렉터리에 같이 두어야 한다. `install.sh` 가 같은 디렉터리에서 tar 를 찾는다.

---

## 3. 서버 — 설치

```bash
chmod +x install.sh
./install.sh /data/timblo/mobile-sync-server
```

스크립트가 하는 일:

1. docker / compose 확인
2. 서버 아키텍처가 amd64 인지 확인
3. `.sha256` 으로 전송 무결성 확인
4. `docker load`
5. `.env` 생성 (이미 있으면 건드리지 않음) + 적재한 이미지로 `IMAGE_NAME`/`IMAGE_VERSION` 고정
6. **서버 계정(`aimm`)의 uid/gid 를 읽어 `RUN_UID`/`RUN_GID` 에 기록**
7. 데이터 디렉터리 생성 + 그 uid/gid 로 소유권 설정
8. `timblo-net` 네트워크 확인
9. `docker compose up -d`
10. `/health` 200 확인 (최대 60초)

적재만 하고 나중에 올리려면:

```bash
SKIP_START=1 ./install.sh /data/timblo/mobile-sync-server
```

### 설치 직후 할 일

`.env` 의 `SWAGGER_PASSWORD` 가 `change-me` 다. 바꾸고 재기동한다.

```bash
cd /data/timblo/mobile-sync-server
vi .env
docker compose --env-file .env up -d
```

---

## 4. 확인

```bash
curl http://127.0.0.1:9995/health
docker logs -f mobile-sync-server
```

스토리지 없이 파일만으로 병합이 되는지:

```bash
curl -X POST http://127.0.0.1:9995/v1/merge/upload \
  -F "files=@p1.flac" -F "files=@p2.flac" -F "align=none"
# → {"jobId":"mrg_...","status":"WAITING",...}

curl http://127.0.0.1:9995/v1/merge/mrg_...
# → {"status":"DONE", ... ,"downloadUrl":"/v1/merge/mrg_.../download"}

curl -o merged.flac http://127.0.0.1:9995/v1/merge/mrg_.../download
```

API 문서: `http://<서버주소>:9995/docs` (계정은 `.env` 의 `SWAGGER_USER` / `SWAGGER_PASSWORD`)

---

## 실행 계정

컨테이너는 `.env` 의 `RUN_UID`:`RUN_GID` 로 돈다. **서버 계정 `aimm` 의 값과 같아야 한다.**

```bash
id -u aimm    # RUN_UID
id -g aimm    # RUN_GID
```

`install.sh` 가 설치할 때 자동으로 읽어서 채운다. 다른 계정으로 돌리려면:

```bash
SERVICE_USER=<계정명> ./install.sh /data/timblo/mobile-sync-server
```

이미지 안의 기본 계정은 uid 10001 이지만 그대로 쓰면 안 된다. `RUNTIME_DIR` 에
쌓이는 세션 파일·`merge.db`·임시 파일이 전부 10001 소유가 되어, `aimm` 계정으로
로그를 지우지도 DB 를 복사하지도 못하게 된다.

이미지는 어떤 uid 로도 돌 수 있게 만들어져 있다 (`/app/src` 는 읽기 허용,
`/var/lib/recog` 는 쓰기 허용). `build.sh` 도 검증할 때 일부러 10001 이 아닌
uid 로 띄워서 확인한다.

---

## 데이터 저장 위치

`.env` 의 `RUNTIME_DIR` 이 가리키는 **호스트 경로**다. 기본값 `/data/timblo/mobile-sync-server-runtime`.

| 경로 | 내용 | 지워지면 |
|---|---|---|
| `<RUNTIME_DIR>/sessions/` | 세션 데이터 | 해당 세션 유실 |
| `<RUNTIME_DIR>/merge.db` | 병합 기록 (SQLite, 기본 90일) | 이력 유실 |
| `<RUNTIME_DIR>/merge/` | 병합 중 임시 파일 (끝나면 자동 삭제) | 무해 |
| `<RUNTIME_DIR>/merge_results/` | 업로드 테스트 경로 결과 | 테스트 결과만 유실 |

호스트에 있으므로 이미지를 갈아끼우거나 컨테이너를 지워도 남는다.

---

## 갱신 (새 버전 반입)

빌드 PC 에서 새 tar 를 만들고, 같은 절차를 반복한다.

```bash
./install.sh /data/timblo/mobile-sync-server
```

기존 `.env` 는 덮어쓰지 않고 이미지 이름만 갱신된다. `RUNTIME_DIR` 을 건드리지
않으므로 병합 기록이 이어진다.

오래된 이미지 정리:

```bash
docker images mobile-sync-server
docker rmi mobile-sync-server:<옛버전>
```

---

## 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `exec format error` | 아키텍처 불일치 | 빌드 PC 에서 `build.sh` 재실행. 2단계 검사를 통과했다면 발생하지 않는다 |
| `pull access denied` / pull 시도 | compose 가 레지스트리를 봄 | `.env` 의 `IMAGE_NAME`/`IMAGE_VERSION` 이 `docker images` 결과와 같은지 확인 |
| `network timblo-net not found` | 외부 네트워크 없음 | `docker network create timblo-net` 또는 MinIO 먼저 기동 |
| `Permission denied` (로그) | 데이터 경로 소유권 | `sudo chown -R aimm:aimm <RUNTIME_DIR>` — `.env` 의 `RUN_UID`/`RUN_GID` 와 같아야 한다 |
| 호스트에서 데이터 파일을 못 지움 | `RUN_UID` 가 `aimm` 이 아님 | `id -u aimm` 값과 `.env` 의 `RUN_UID` 를 맞추고 재기동 |
| `/docs` 401 | 계정 불일치 | `.env` 의 `SWAGGER_USER` / `SWAGGER_PASSWORD` |
| presigned 다운로드 실패 | `timblo-minio` DNS 해석 실패 | 같은 네트워크에 있는지 확인 (`docker network inspect timblo-net`) |
| 재배포 후 이력이 비어 있음 | `RUNTIME_DIR` 이 바뀜 | 예전 경로의 `merge.db` 확인 |

```bash
docker logs --tail 100 mobile-sync-server
docker inspect mobile-sync-server --format '{{.State.Health.Status}}'
```

---

## 이름 체계 (참고)

`mobile-sync-server` 와 `recog` 가 섞여 보이는데, 층이 다르다.

**배포 층 — 전부 `mobile-sync-server`**

| 대상 | 값 | 어디서 바꾸나 |
|---|---|---|
| 이미지 | `mobile-sync-server:<버전>` | `build.sh` 의 `IMAGE_REPO` |
| compose 서비스 | `mobile-sync-server` | `docker-compose.yml` |
| 컨테이너 | `mobile-sync-server` | `docker-compose.yml` 의 `container_name` |
| 반입 파일 | `mobile-sync-server_<버전>_amd64.tar` | `build.sh` 가 생성 |
| 설치 경로 | `/data/timblo/mobile-sync-server` | `install.sh` 인자 |
| 데이터 경로 | `/data/timblo/mobile-sync-server-runtime` | `.env` 의 `RUNTIME_DIR` |
| 이미지 버전 | `IMAGE_VERSION` | `.env` (install.sh 가 자동 기록) |

**코드 층 — `recog` 로 남아 있다**

| 대상 | 값 | 비고 |
|---|---|---|
| 파이썬 패키지 | `src/recog/` | 애플리케이션 모듈명 |
| 진입점 | `python -m recog` | `Dockerfile` 의 `ENTRYPOINT` |
| 바인드 설정 | `RECOG_HOST` / `RECOG_PORT` | **코드가 직접 읽는다.** 이름을 바꾸려면 소스 수정 |
| `/health` 응답 | `{"status":"ok","service":"recog"}` | 소스에 하드코딩 |

배포 층은 이름표라 자유롭게 바꿔도 되지만, 코드 층은 소스를 고쳐야 한다.
서비스 동작에는 영향이 없어서 지금은 그대로 두었다.

---

## 요구사항 (참고)

| 항목 | 요구 | 이미지에 들어간 것 |
|---|---|---|
| Python | 3.11+ | 3.11.16 (`python:3.11-slim`) |
| ffmpeg | 4.4+ | 9.0.2 (BtbN static, LGPL 빌드) |
| pip 패키지 | **없음** | — |

- Python 3.11 이 필요한 이유: 코드가 `from datetime import UTC` 를 쓴다.
- ffmpeg 4.4 가 필요한 이유: 병합이 `amix` 의 `normalize=` 옵션을 쓰는데 4.4 에서 추가됐다.
- recog 는 외부 파이썬 패키지를 하나도 쓰지 않는다. `requirements.txt` 가 없다.
  Swagger UI 자산도 저장소에 내장되어 있어 CDN 없이 `/docs` 가 뜬다.
- LGPL 빌드를 쓰는 이유: 우리가 쓰는 기능(flac/aac/opus/mp3 디코딩, flac 인코딩,
  필터 7종)은 전부 코어라 LGPL 로 충분하고, 고객사에 이미지를 넘기는 상황에서
  GPL 빌드보다 정리하기 쉽다.

`build.sh` 는 이 요구사항을 이미지 안에서 직접 확인한다. 버전이 모자라거나
필요한 필터가 빠진 빌드면 tar 를 만들지 않고 중단한다.

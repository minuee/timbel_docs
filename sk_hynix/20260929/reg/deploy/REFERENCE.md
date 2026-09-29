# 참고 — 왜 이렇게 만들었나

> 작업하며 오간 질문과 결정을 정리한 문서다. 절차는 다른 문서에 있다.
>
> | 문서 | 언제 보나 |
> |---|---|
> | `SERVER_INSTALL.md` | **서버에서 설치할 때** — 이것만 보면 된다 |
> | `README.md` | 빌드부터 배포까지 전체 흐름 |
> | `REFERENCE.md` (이 문서) | 왜 이런 선택을 했는지, 무엇을 확인했는지 |
> | `../newDocs/03_병합기록_조회가이드.md` | merge.db 조회·스키마·마이그레이션 |

---

## 1. 왜 이미지를 tar 로 옮기나

망분리 서버에서는 `docker build` 가 성립하지 않는다. Dockerfile 이 네트워크를
타는 지점이 있기 때문이다.

| 지점 | 무엇을 받아오나 | 망분리에서 |
|---|---|---|
| `FROM python:3.11-slim` | Docker Hub 에서 베이스 이미지 | 실패 |
| ffmpeg 설치 | 패키지 저장소 | 실패 |
| compose 의 `image:` | 레지스트리 pull | 실패 |

그래서 **인터넷 되는 PC 에서 이미지를 완성**해 파일로 만들어 반입한다.
서버는 `docker load` 만 하므로 네트워크를 전혀 타지 않는다.

```
[빌드 PC]                                  [망분리 서버]
  build.sh
    빌드 + 검증 + docker save     반입       install.sh
      ↓                        ────────►      docker load
  mobile-sync-server_                         docker compose up -d
    0.0.1_amd64.tar
```

`ffmpeg` 는 아예 호스트에서 미리 받아 바이너리만 이미지에 복사한다(4절).
그래서 지금 Dockerfile 이 네트워크를 타는 곳은 `FROM` 한 줄뿐이다.

---

## 2. 빌드 PC 와 서버, 각각 뭐가 필요한가

### 빌드 PC

| 항목 | 요건 |
|---|---|
| 인터넷 | 필요 (베이스 이미지 + ffmpeg 최초 1회) |
| 도커 | 필요 |
| buildx | `linux/amd64` 로 만들어야 하므로 사실상 필요 |
| 디스크 | 2GB 이상 |

**Apple Silicon 맥이라면** 서버가 x86_64 이므로 크로스 빌드가 된다. buildx 와
QEMU(또는 Rosetta)가 있어야 한다. `build.sh` 가 결과 아키텍처를 직접 검사해서
잘못 나오면 tar 를 만들지 않고 중단하므로, 모르고 넘어갈 일은 없다.

이번 작업은 colima(Rosetta 가속) 위에서 빌드했다.

```bash
brew install colima docker docker-buildx docker-compose
colima start --cpu 4 --memory 8 --disk 30 --vm-type vz --vz-rosetta
```

### 배포 서버

| 항목 | 요건 |
|---|---|
| 인터넷 | **불필요** |
| 도커 + compose | 필요 |
| 아키텍처 | `x86_64` |
| 계정 | `aimm` (uid/gid 를 컨테이너가 그대로 쓴다) |
| 네트워크 | `timblo-net` (MinIO·master-api 와 공유) |
| 디스크 | 2GB 이상 |

### 파일이 어디서 쓰이나

| 파일 | 서버 | 빌드 PC |
|---|:---:|:---:|
| `install.sh` | **필요** | — |
| `docker-compose.yml` | **필요** | — |
| `.env.example` | **필요** | — |
| `SERVER_INSTALL.md` | 있으면 좋음 | — |
| `Dockerfile` | 불필요 | 필요 |
| `build.sh` | 불필요 | 필요 |
| `smoke_test.py` | 불필요 | 필요 |
| `.ffmpeg/` (282MB) | 불필요 | 필요 |
| `README.md` / `REFERENCE.md` | 참고용 | 참고용 |

`dist/` 의 두 파일은 **둘 다** 가져간다.

- `.tar` — 이미지 본체
- `.tar.sha256` — 104바이트. `install.sh` 가 있으면 검증하고 없으면 경고만 한다.
  USB/파일서버를 거치다 깨지면 `docker load` 가 엉뚱하게 실패하는데, 이게 있으면
  전송 문제인지 이미지 문제인지 바로 갈린다.

---

## 3. src/ 소스는 어디서 오나

`build.sh` 의 빌드 명령 마지막 `.` 이 **빌드 컨텍스트**이고, 스크립트가 먼저
`cd "$REPO_ROOT"` 를 하므로 이 `.` 은 항상 저장소 루트다.

```bash
docker buildx build ... --file deploy/Dockerfile --load .
                                                       ↑ 저장소 루트
```

그래서 Dockerfile 이 `deploy/` 안에 있어도

```dockerfile
COPY src/ ./src/          # deploy/src 가 아니라 저장소 루트의 src/
```

**항상 루트의 `src/`** 를 가져간다. Dockerfile 위치와 빌드 컨텍스트는 별개다.

> **이미지는 그 순간의 스냅샷이다.** `src/` 를 고쳐도 이미 만든 tar 에는
> 반영되지 않는다. 코드를 고치면 `build.sh` 를 다시 돌려야 한다.

---

## 4. ffmpeg — 왜 apt 가 아니라 static 빌드인가

처음에는 `apt-get install ffmpeg` 로 만들었다가 바꿨다.

Debian 의 `ffmpeg` 패키지는 `ffplay`(GUI 재생기)까지 들어 있는 풀빌드라
X11·Wayland·Vulkan·SDL2·Mesa·LLVM·폰트까지 **250여 개 패키지**를 끌고 온다.
우리는 오디오만 쓰므로 전부 불필요하다.

| | apt 패키지 | static 빌드 |
|---|---|---|
| tar 크기 | 208 MB | **160 MB** |
| ffmpeg 버전 | 7.1.5 | **9.0.2** |
| 빌드 시 네트워크 | 베이스 + apt 250개 | 베이스 + 파일 1개 |
| 의존성 | 공유 라이브러리 다수 | 없음 (단일 바이너리) |

**LGPL 변종**을 쓴다. 우리가 쓰는 기능(flac/aac/opus/mp3 디코딩, flac 인코딩,
`amix`·`adelay`·`alimiter`·`apad`·`atrim`·`aresample`·`volume` 필터)은 전부
코어라 LGPL 로 충분하고, 고객사에 이미지를 넘기는 상황에서 GPL 빌드보다 깔끔하다.

다른 빌드를 쓰려면:

```bash
FFMPEG_URL=https://.../ffmpeg-xxx-linux64-lgpl.tar.xz ./deploy/build.sh
```

한 번 받으면 `deploy/.ffmpeg/` 에 캐시되어 다음 빌드부터는 건너뛴다.

### 최소 요구 버전은 4.4 다

코드가 쓰는 필터 중 가장 최신이 `amix` 의 `normalize=` 옵션이고, 그게 4.4 에서
추가됐다. `build.sh` 가 이미지 안에서 버전과 필터 7종의 존재를 직접 확인하므로,
모자란 빌드를 쓰면 tar 가 만들어지지 않는다.

---

## 5. 이미지에 들어 있는 것

| 항목 | 값 |
|---|---|
| 베이스 | `python:3.11-slim` |
| Python | 3.11.16 |
| ffmpeg / ffprobe | 9.0.2 (static, LGPL) |
| pip 패키지 | **0개** |
| 기본 계정 | uid 10001 (compose 의 `user:` 가 덮어씀) |
| 노출 포트 | 8080 (컨테이너 내부) |

Python 3.11 이 필요한 이유는 코드가 `from datetime import UTC` 를 쓰기 때문이다
(3.11+). recog 는 외부 파이썬 패키지를 하나도 쓰지 않아 `requirements.txt` 가
없다. Swagger UI 자산도 저장소에 내장되어 있어 CDN 없이 `/docs` 가 뜬다.

`curl` 은 일부러 설치하지 않았다. 헬스체크는 이미 있는 python 으로 한다.

---

## 6. 포트

| | 값 | 바꿔도 되나 |
|---|---|---|
| `HOST_PORT` | **9995** | `.env` 에서 자유롭게 |
| `CONTAINER_PORT` | 8080 | 바꿀 이유 없음 |

컨테이너 포트는 내부 전용이라 외부와 충돌하지 않는다. 바꾸면 `RECOG_PORT` 까지
같이 맞춰야 해서 이득이 없다.

---

## 7. 실행 계정 — 왜 `aimm` uid 로 도나

이미지 안의 기본 계정은 uid 10001 이지만, 그대로 쓰면 안 된다.

`RUNTIME_DIR` 에 쌓이는 세션 파일·`merge.db`·임시 파일이 전부 10001 소유가 되어
**서버의 `aimm` 계정으로는 로그도 못 지우고 DB 도 복사하지 못한다.**

그래서:

- `docker-compose.yml` 에 `user: "${RUN_UID}:${RUN_GID}"`
- `install.sh` 가 `id -u aimm` / `id -g aimm` 를 읽어 `.env` 에 기록
- 데이터 디렉터리도 같은 uid/gid 로 `chown`
- 이미지는 어떤 uid 로도 돌 수 있게 만들어 뒀다 (`/app/src` 읽기 허용,
  `/var/lib/recog` 쓰기 허용)

다른 계정으로 돌리려면:

```bash
SERVICE_USER=<계정명> ./install.sh /data/timblo/mobile-sync-server
```

소유권이 안 맞으면 컨테이너가 기동 직후 `PermissionError` 로 죽고 재시작만
반복한다. 로그를 뒤져야 원인을 알게 되므로, `install.sh` 가 **기동 전에**
그 uid 로 실제 써 보고 안 되면 중단한다.

---

## 8. 버전 관리

저장소 루트의 `VERSION` 파일 하나로 관리한다. node 의 `package.json` 버전과
같은 역할이다. `build.sh` 가 이 순서로 정한다.

| 순위 | 출처 | 예 |
|---|---|---|
| 1 | 실행 인자 | `./deploy/build.sh 0.0.2` |
| 2 | `VERSION` 파일 | `0.0.1` |
| 3 | 오늘 날짜 | `20260921` |

`VERSION` 만 고치면 이미지 태그와 tar 파일명이 같이 따라간다.

```
0.0.1  →  mobile-sync-server:0.0.1
          mobile-sync-server_0.0.1_amd64.tar
```

변경 내역은 루트의 `BUILD_HISTORY.md` 에 한 줄씩 남긴다.

---

## 9. 새 버전으로 갈아끼울 때 무슨 일이 일어나나

`docker compose up -d` 가 이미지가 바뀐 걸 감지하고 컨테이너를 **재생성
(Recreated)** 한다. 재시작이 아니라 새로 만드는 것이다. 컨테이너 ID 가 바뀐다.

그래도 다음은 전부 유지된다.

| 항목 | 유지 | 이유 |
|---|:---:|---|
| `merge.db` (병합 이력) | O | 호스트 `RUNTIME_DIR` 에 있음 |
| `sessions/` 등 데이터 | O | 같음 |
| `.env` (비밀번호·포트) | O | `install.sh` 가 있으면 안 건드림 |
| 돌고 있던 병합 작업 | O | 재기동 시 자동 재실행 |

**돌고 있던 작업**은 `merge_job.py` 의 `_restore_from_records()` 가 미완료
작업을 다시 큐에 넣어 처음부터 돌린다. 작업이 날아가지 않는다.

다운타임은 컨테이너 재생성하는 몇 초다.

### 롤백

옛 이미지는 디스크에 남아 있으니 `.env` 의 `IMAGE_VERSION` 만 되돌리면 된다.
DB 가 새 스키마여도 죽지 않는다(10절).

### 주의 — 예전 tar 를 치워야 한다

`install.sh` 는 자기 옆에서 tar 를 glob 으로 찾는다. 두 개 이상이면 어느 걸
띄울지 모호해지므로 **중단한다.** 조용히 엉뚱한 버전이 뜨는 것보다 낫다고 봤다.

```
[install] 중단: 이미지 파일이 여러 개다. 하나만 남길 것:
  mobile-sync-server_0.0.1_amd64.tar
  mobile-sync-server_0.0.2_amd64.tar
```

---

## 10. SQLite 는 영향을 받나

**소스만 바뀌는 버전이면 영향 없다.** `merge.db` 는 호스트에 있고, WAL 모드라
쓰기 도중 컨테이너가 죽어도 다음 기동 때 자동 복구된다.

**스키마(컬럼)가 바뀌는 버전**은 마이그레이션이 필요하다. `CREATE TABLE IF NOT
EXISTS` 만으로는 기존 DB 에 새 컬럼이 생기지 않아서, 그 컬럼을 쓰는 저장이 전부
`no such column` 으로 실패하기 때문이다.

그래서 `schema_meta` 에 기록된 버전을 읽어 필요한 `ALTER` 만 순서대로 적용한다.
서버가 뜰 때 자동으로 일어난다.

```
INFO merge_schema_migrated from=1 to=2
```

자세한 내용(현재 버전 확인, 컬럼 추가하는 법, 실패 시 동작, 그냥 다 지우는 법)은
`../newDocs/03_병합기록_조회가이드.md` 5절에 있다.

---

## 11. 이름이 두 가지인 이유

`mobile-sync-server` 와 `recog` 가 섞여 보이는데 층이 다르다.

- **배포 층** — 이미지·컨테이너·파일명·경로. 전부 `mobile-sync-server`. 이름표라
  자유롭게 바꿀 수 있다.
- **코드 층** — 파이썬 패키지 `src/recog/`, `python -m recog`,
  `RECOG_HOST`/`RECOG_PORT`, `/health` 의 `{"service":"recog"}`. **코드가 직접
  읽는 값들이라** 바꾸려면 소스를 고쳐야 한다.

`RECOG_VERSION` 은 코드가 읽지 않아(compose 전용) `IMAGE_VERSION` 으로 바꿨다.

표 전체는 `README.md` 의 "이름 체계" 절에 있다.

---

## 12. build.sh 가 검증하는 것

문서와 스크립트만 만들어 놓고 정작 이미지를 안 만들어 현장에서 막힌 적이 있다.
그래서 **검증을 통과해야만 tar 가 만들어지도록** 했다.

| 단계 | 확인 | 실패하면 |
|---|---|---|
| 1 | ffmpeg static 바이너리 확보 | 중단 |
| 2 | `linux/amd64` 로 빌드 | 중단 |
| 3 | **정말 amd64 로 나왔는가** | 중단 (`exec format error` 예방) |
| 4 | **컨테이너를 띄워 실제로 병합을 한 번 돌린다** | 중단 |
| 5 | `docker save` | — |

4단계는 서버와 같은 조건을 만든다. 이미지 기본 계정(10001)이 아니라 **비기본
uid(1000)** 로 띄워서, 권한 때문에 서버에서만 터지는 일이 없는지 확인한다.

확인 항목: python/ffmpeg/ffprobe 버전, 필터 7종 존재, `/health` 200,
440Hz+660Hz 음성 2개 병합 → `DONE` → 결과를 ffprobe 로 열어 3초짜리 flac 인지까지.

---

## 13. 이번에 실제로 확인한 것

추측으로 넘긴 항목이 없도록 전부 돌려서 확인했다.

| 항목 | 방법 | 결과 |
|---|---|---|
| 이미지가 amd64 인가 | `docker image inspect` | `linux/amd64` |
| tar 가 구버전 도커에서 열리나 | 구조 검사 | 단일 `manifest.v2` (manifest list·attestation 없음) |
| `docker load` 가 되나 | 이미지 삭제 후 복구 | `Loaded image: mobile-sync-server:0.0.1` |
| load 후에도 도나 | 스모크 테스트 재실행 | 병합 `DONE` |
| 비기본 uid 로 도나 | `--user 1000:1000` | 정상 |
| compose 전체 경로 | VM 안 리눅스 경로로 기동 | `healthy`, `timblo-net` 연결 |
| 포트 9995 | 호스트에서 업로드→병합→다운로드 | 76,857 bytes flac 3.00초 |
| 데이터 소유권 | 기동 후 `ls -lan` | `merge.db` 포함 전부 `1000:1000` |
| 소유권 불일치 시 | 일부러 어긋나게 | `PermissionError` 재시작 루프 → 사전 검사 추가 |
| 0.0.1 → 0.0.2 갱신 | 실제 갱신 | `Recreated`, 이력·`.env` 유지 |
| 갱신 중 작업 | `RUNNING` 상태에서 컨테이너 삭제 | 재기동 후 자동 재실행 → `DONE` |
| 스키마 마이그레이션 | 컬럼 추가한 0.0.2 로 갱신 | `from=1 to=2`, 17→18 컬럼, 이력 보존 |
| 롤백 | 0.0.2 DB 에 0.0.1 | 정상 기동 + 새 병합 성공 |

> `--provenance=false --sbom=false` 로 빌드하는 이유가 여기서 나왔다.
> 기본값으로 두면 buildx 가 tar 에 attestation manifest 를 끼워 넣어 manifest
> list 구조로 만드는데, 구버전 도커의 `docker load` 가 이것 때문에 실패할 수 있다.

---

## 14. 알아둘 제약

- **이미지는 스냅샷이다.** 코드를 고치면 재빌드해야 한다.
- **컬럼을 추가하는 버전은 `_MIGRATIONS` 에 `ALTER` 를 같이 넣어야 한다.**
  안 넣으면 새 컬럼이 안 생기고 저장이 실패한다.
- **예전 tar 를 서버에 남겨두면 설치가 중단된다.** 의도된 동작이다.
- 단위 테스트 214개 중 **3개가 에러**로 남아 있다. `mobile_app/` 디렉터리를
  정리하면서 Flutter PoC 스캐폴드 검사 도구가 대상 파일을 못 찾는 것이다.
  병합 API·배포와는 무관하다.

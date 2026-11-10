# 서버 설치 — 최소 절차

> 이 문서만 보고 끝낼 수 있게 썼다. 막히면 맨 아래 **"막혔을 때"** 를 본다.

## 0. 반입할 파일 5개

한 디렉터리에 **전부 같이** 둔다. `install.sh` 가 자기 옆에서 tar 를 찾는다.

```
pcapp-log-server_0.0.1_amd64.tar          ← 이미지
pcapp-log-server_0.0.1_amd64.tar.sha256   ← 전송 검증용
install.sh
docker-compose.yml
.env.example
```

**예전 버전 tar 가 같은 디렉터리에 있으면 설치가 중단된다** (어느 걸 띄울지 모호해지는 걸 막는 안전장치). 새 버전을 올릴 때는 예전 tar 를 먼저 지운다.

## 1. 서버에 필요한 것

| 항목 | 확인 명령 | 기대 |
|---|---|---|
| 도커 | `docker version` | 응답이 오면 OK |
| compose | `docker compose version` | 없으면 `docker-compose` 도 가능 |
| 아키텍처 | `uname -m` | `x86_64` |
| 계정 | `id aimm` | uid/gid 가 나오면 OK (없으면 현재 사용자로 돈다) |
| 포트 | `ss -ltn \| grep 9996` | 아무것도 안 나와야 함 |

## 2. 설치 — 명령 3줄

```bash
cd <반입한 디렉터리>
chmod +x install.sh
./install.sh /data/timblo/pcapp-log-server
```

스크립트가 하는 일:
1. 도커 / compose / 아키텍처 확인
2. `.sha256` 으로 전송 무결성 확인
3. `docker load`
4. `.env` 생성 (이미 있으면 안 건드림) + 적재한 이미지 이름 고정
5. `aimm` 의 uid/gid 를 `.env` 에 기록
6. 로그 폴더(`/data/timblo/pcapp-log-server-logs`) 생성 + 소유권 설정 + **실제로 써 보기**
7. `docker compose up -d`
8. `/health` 200 확인 (최대 60초)

적재만 하고 나중에 올리려면: `SKIP_START=1 ./install.sh /data/timblo/pcapp-log-server`

## 3. 확인

```bash
curl http://127.0.0.1:9996/health
curl -X POST http://127.0.0.1:9996/pcapp/log -H 'content-type: application/json' -d '{"msg":"설치 확인"}'
docker logs --tail 5 pcapp-log-server
ls /data/timblo/pcapp-log-server-logs
```

그다음 nginx 에 `/m/api/pcapp/` 프록시를 추가한다 (`../README.md` 4번).

## 4. 갱신 (새 버전)

```bash
rm pcapp-log-server_<옛버전>_amd64.tar*
./install.sh /data/timblo/pcapp-log-server
```
`.env` 와 로그 폴더는 그대로 유지된다. **Dozzle 에 보이던 이전 로그는 사라지지만 파일은 남는다.**

오래된 이미지 정리: `docker images pcapp-log-server` → `docker rmi pcapp-log-server:<옛버전>`

## 5. 설정 바꾸기

```bash
cd /data/timblo/pcapp-log-server
vi .env                                  # 예: LOG_RETENTION_DAYS=180
docker compose --env-file .env up -d     # 재기동
```

| 값 | 기본 | 설명 |
|---|---|---|
| `HOST_PORT` | 9996 | 서버에서 열리는 포트 |
| `LOG_HOST_DIR` | `/data/timblo/pcapp-log-server-logs` | 로그 파일 위치 |
| `LOG_FILE_ENABLED` | 1 | 0 이면 파일 저장 안 함 (Dozzle 만) |
| `LOG_RETENTION_DAYS` | 90 | 지난 파일은 1시간마다 삭제. 0 이면 영구 보관 |

## 막혔을 때

| 증상 | 원인 | 조치 |
|---|---|---|
| `exec format error` | 아키텍처 불일치 | 빌드 PC 에서 `build.sh` 재실행 |
| `pull access denied` / pull 시도 | compose 가 레지스트리를 봄 | `.env` 의 `IMAGE_NAME`/`IMAGE_VERSION` 이 `docker images` 결과와 같은지 |
| 컨테이너가 재시작을 반복, 로그에 `log_dir_not_writable` | 로그 폴더 소유권 | `sudo chown -R aimm:aimm /data/timblo/pcapp-log-server-logs` |
| `port is already allocated` | 9996 사용 중 | `.env` 의 `HOST_PORT` 변경 (nginx 도 같이) |
| 앱 로그가 안 들어옴 | nginx 경로 | 서버에서 `curl` 은 되는데 앱에서 안 되면 nginx 설정 확인. 앱 로그 파일의 `[logShipper]` 경고 확인 |
| 로그의 `ip` 가 전부 같음 | nginx 가 `X-Forwarded-For` 를 안 넘김 | `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` |

```bash
docker logs --tail 100 pcapp-log-server
docker inspect pcapp-log-server --format '{{.State.Health.Status}}'
```

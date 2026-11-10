# pcapp-log-server — PC 녹음앱 로그 수집 서버

PC 녹음앱(timbloRecApp)이 보내는 로그를 받아서
**Dozzle 로 실시간 조회**하고, **날짜별 파일로 90일 보관**한다.

```
[PC 앱 logger.js] ──(3초마다 100줄씩 POST)──▶ nginx /m/api/pcapp/log ──▶ pcapp-log-server :9996
                                                                         ├─ stdout (JSON 한 줄씩) → docker logs → Dozzle
                                                                         └─ /var/lib/pcapp-log/pcapp-YYYY-MM-DD.log (90일)
```

- 외부 패키지 없음 (node 표준 라이브러리만). `npm install` 이 필요 없다.
- DB 없음. 인증 없음 (사내망 전용 개발 서버 기준. 필요해지면 추가).
- 참고한 구조: `docs/example/deploy` (mobile-sync-server 망분리 배포)

## 왜 stdout 과 파일 둘 다인가

| | Dozzle (docker logs) | 날짜별 파일 |
|---|---|---|
| 용도 | 실시간 조회, 필터 | 장기 보관, grep |
| 보관 | 10MB × 5개 넘으면 오래된 것부터 삭제. **새 이미지로 컨테이너를 교체하면 전부 사라짐** | `LOG_RETENTION_DAYS`(90일) 동안. 컨테이너와 무관 |
| 끄기 | — | `.env` 의 `LOG_FILE_ENABLED=0` |

---

## 문서

| 문서 | 언제 보나 |
|---|---|
| **`deploy/SERVER_INSTALL.md`** | **서버에서 설치할 때 — 이것만 보면 된다** |
| `README.md` (이 문서) | 빌드부터 배포까지 전체 흐름, API |
| `BUILD_HISTORY.md` | 버전별 변경 내역 |

## 파일

| 파일 | 어디서 쓰나 |
|---|---|
| `src/server.js` | 서버 본체 (이미지에 들어감) |
| `VERSION` | 빌드 PC — 이미지 버전 |
| `deploy/Dockerfile` | 빌드 PC |
| `deploy/build.sh` | 빌드 PC — 빌드·검증·tar 생성 |
| `deploy/smoke_test.js` | 빌드 PC — build.sh 가 컨테이너 안에서 실행 |
| `deploy/install.sh` | **서버** |
| `deploy/docker-compose.yml` | **서버** |
| `deploy/.env.example` | **서버** — `.env` 로 복사해서 사용 |

---

## 1. 빌드 PC — 이미지 만들기

Docker Desktop(또는 colima)을 켠 뒤:

```bash
cd docs/logserver
./deploy/build.sh            # VERSION 파일의 버전으로
./deploy/build.sh 0.0.2      # 버전을 직접 지정 (VERSION 파일도 같이 갱신됨)
```

스크립트가 순서대로 한다. **2·3번을 통과해야만 tar 가 만들어진다.**

1. `linux/amd64` 로 빌드 (Apple Silicon 맥이면 크로스 빌드라 조금 느리다)
2. 정말 amd64 로 나왔는지 확인
3. 컨테이너를 **이미지 기본과 다른 uid** 로 띄워 로그를 실제로 보내 보고, 파일 저장·docker logs 출력까지 확인
4. `docker save` → tar + sha256

결과물:
```
dist/pcapp-log-server_<버전>_amd64.tar
dist/pcapp-log-server_<버전>_amd64.tar.sha256
```

버전을 올릴 때는 `VERSION` 파일만 고치고, `BUILD_HISTORY.md` 에 한 줄 남긴다.

## 2. 반입

한 디렉터리에 같이 옮긴다.
```
pcapp-log-server_<버전>_amd64.tar
pcapp-log-server_<버전>_amd64.tar.sha256
install.sh
docker-compose.yml
.env.example
```

## 3. 서버 — 설치

```bash
chmod +x install.sh
./install.sh /data/timblo/pcapp-log-server
```
자세한 절차와 문제 해결은 `deploy/SERVER_INSTALL.md`.

## 4. nginx 연결

앱은 `https://<서버>/m/api/pcapp/log` 로 보낸다 (앱 설정 `LOG_SERVER_URL`).
서버는 **경로 끝이 `/pcapp/log` 면 모두 받으므로**, 아래 둘 중 어느 쪽이든 된다.

```nginx
# /m/api 를 떼고 넘기는 경우 (모바일 서버와 같은 방식)
location /m/api/pcapp/ {
    proxy_pass http://127.0.0.1:9996/pcapp/;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# 그대로 넘기는 경우
location /m/api/pcapp/ {
    proxy_pass http://127.0.0.1:9996;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```
`X-Forwarded-For` 를 넘겨야 로그의 `ip` 에 실제 PC 주소가 찍힌다 (없으면 nginx 주소가 찍힘).

---

## API

### `POST .../pcapp/log`

PC 앱 형식 (여러 줄):
```json
{ "logs": [
  { "level": "info", "process": "main", "message": "recording_start", "empno": "X0000001", "appOs": "WINDOWS", "sessionId": "..." },
  { "level": "error", "process": "main", "message": "server_upload_failed", "empno": "X0000001", "kind": "network" }
] }
```
모바일 형식 (한 줄): `{ "msg": "..." }`

응답: `{ "httpCode": 200, "message": "Success", "received": 2 }`

| 상태 | 원인 |
|---|---|
| 400 | JSON 이 깨졌거나 `logs` / `msg` 가 없음 |
| 413 | 1MB 초과 또는 한 번에 500줄 초과 |

### `GET /health`
`{ "status": "ok", "service": "pcapp-log", "version": "0.0.1" }`

### 출력 한 줄 (stdout 과 파일이 같다)
```json
{"ts":"2026-10-12 21:03:04.313","level":"error","source":"pcapp","empno":"X0165928","message":"server_upload_failed","ip":"10.1.2.3","appOs":"WINDOWS","process":"main","headers":{"Authorization":"***"}}
```
- `ts` 서버 수신 시각(KST), `clientTs` 앱 기록 시각
- `source`: `pcapp`(앱 로그) / `server`(서버 자체 로그)
- 토큰·비밀번호는 **앱이 보내기 전에** `***` 로 가린다

### Dozzle 에서 보기
컨테이너 `pcapp-log-server` 를 고르면 JSON 이 필드별로 펼쳐지고 level 로 색이 입혀진다.
특정 사용자만: 검색창에 사번 입력. 에러만: level 필터.

### 파일에서 찾기
```bash
cd /data/timblo/pcapp-log-server-logs
grep '"empno":"X0165928"' pcapp-2026-10-12.log
grep '"level":"error"' pcapp-2026-10-*.log | wc -l
```

---

## PC 앱 쪽 (보내는 쪽)

`src/main/services/logShipper.js` — `logger.js` 가 파일에 쓰는 로그를 그대로 이어받아 보낸다. 호출부를 고칠 필요가 없다.

| 항목 | 동작 |
|---|---|
| 보내는 레벨 | `LOG_SERVER_MIN_LEVEL`(기본 info) 이상 → info / warn / error. debug 는 안 보냄 |
| 렌더러 console | 양이 많아서 warn 이상만 |
| 주기 | 3초마다, 또는 100줄 쌓이면 즉시. 한 번에 최대 100줄 |
| 실패 시 | 메모리에 보관 후 재시도 (3초 → 6초 → … 최대 60초 간격). 2000줄 넘으면 오래된 것부터 버리고 `log_shipper_dropped` 로 알림. 파일 로그에는 그대로 남음 |
| 모든 줄에 붙는 값 | `empno`(로그인 전이면 빈 값), `deviceId`, `appOs`, `version`, `platform`, `pid` |
| 가리는 값 | 키 이름에 token/password/authorization/secret/cookie 가 들어간 값 → `***`, 문장 속 `Bearer xxx` → `Bearer ***`. 긴 문자열은 2000자에서 자름 |
| 종료 시 | 남은 로그를 최대 2초 동안 한 번 더 보내 봄 (종료를 붙잡지 않음) |
| 설정 | `LOG_SERVER_ENABLED`, `LOG_SERVER_URL`, `LOG_SERVER_MIN_LEVEL` (저장소 루트 `.env.example`) |

로그 형식도 함께 정리했다: 이벤트 이름(`message`)이 상세 정보의 `message` 에 덮여 사라지던 문제를 `logger.js` 에서 고쳤다. 상세 메시지는 이제 `detail` 에 들어간다.

---

## 로컬 개발

```bash
cd docs/logserver
LOG_DIR=./runtime PORT=9996 node src/server.js
BASE=http://127.0.0.1:9996 LOG_DIR=./runtime node deploy/smoke_test.js
```
PC 앱을 여기로 붙이려면 앱 저장소 루트 `.env` 에 `LOG_SERVER_URL=http://127.0.0.1:9996/pcapp/log`.

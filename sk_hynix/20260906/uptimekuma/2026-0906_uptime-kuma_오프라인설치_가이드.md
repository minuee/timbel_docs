# Uptime Kuma 오프라인 설치 가이드 (작성일: 2026-09-06)

인터넷이 차단된 사내 서버에 **Uptime Kuma**(서비스/웹사이트 가동시간 모니터링 도구)를 단독 설치하기 위한 패키지와 절차.

- 대상: `docker pull` 이 불가능한 폐쇄망 서버
- 전제: 서버에 **docker + docker compose 가 이미 설치되어 있을 것** (그 외 의존성 없음)
- 특징: 외부 전송 데이터 없음 (알림 기능 비활성화), GUI 대시보드로 모든 설정 관리
- 백엔드 API(`asst-service-portal`) 소스와 **완전히 분리**된 독립 패키지

---

## 1. Uptime Kuma란

| 항목 | 설명 |
|---|---|
| **용도** | HTTP/HTTPS, TCP, DNS, Ping 등 다양한 프로토콜로 서비스 가동시간 모니터링 |
| **GUI** | 웹 브라우저 기반 대시보드 (Dozzle과 동일한 방식) |
| **데이터 저장** | SQLite 데이터베이스 (로컬, 외부 전송 없음) |
| **알림** | 이메일/Slack/Discord 등 지원하나, 본 패키지는 비활성화 (필요시 추후 활성화 가능) |
| **특징** | 단일 서버에서 독립 운영, 설정이 모두 GUI 에서 가능 |

**외부 전송 데이터:** 알림 비활성화 상태에서는 0% (모든 데이터 로컬 저장)

---

## 2. 패키지 구성

배포물: **`uptime-kuma-offline.tar.gz` (약 50MB)** — 이 파일 하나만 옮기면 된다.

```
uptime-kuma-offline/
├── images/
│   ├── uptime-kuma-latest-amd64.tar.gz   # x86_64 서버용 (30MB)
│   └── uptime-kuma-latest-arm64.tar.gz   # ARM 서버용   (28MB)
├── app-data/                             # 데이터베이스 + 설정 저장 디렉토리
├── docker-compose.yml
├── .env                                  # UPTIME_KUMA_PORT=9998
├── install.sh                            # 이미지 load + 기동
├── uninstall.sh
└── README.md
```

> 이 패키지는 용량(50MB 바이너리) 때문에 `.gitignore` 처리되어 있다. 저장소에 커밋되지 않으므로
> **USB / 메신저 / scp 등으로 압축파일을 직접 전달**해야 한다.

### 이미지 획득 방식

Dozzle과 동일하게 Docker Hub 레지스트리 API로 `louislam/uptime-kuma:latest` 의 레이어를 직접 받아
`docker load` 형식 tar 로 조립했다. 각 레이어의 `diff_id` 를 원본 이미지 config 와 대조 검증했으므로
`docker save` 결과물과 내용이 동일하다.

amd64 / arm64 를 모두 담았고 `install.sh` 가 `uname -m` 으로 자동 판별하므로,
대상 서버 아키텍처를 미리 몰라도 된다.

---

## 3. 설치 절차

### 3-1. 반출 전 (작업 PC에서)

1. **포트 확인** — 대상 서버에서 쓸 포트를 `.env` 의 `UPTIME_KUMA_PORT` 에 맞춰 둔다. 현재 `9998`
2. **외부 전송 설정** — `docker-compose.yml` 에서 알림 기능이 비활성화되어 있는지 확인 (기본값)
3. `uptime-kuma-offline.tar.gz` 를 USB 등으로 복사

### 3-2. 서버에서

```bash
tar xzf uptime-kuma-offline.tar.gz
cd uptime-kuma-offline
./install.sh
```

`install.sh` 가 순서대로 수행하는 것:

| 단계 | 내용 | 실패 시 |
|---|---|---|
| 1 | `docker` / `docker compose` 존재·기동 확인 | 설치 안내 후 중단 |
| 2 | `uname -m` → amd64·arm64 판별, 해당 tar 만 `docker load` | 미지원 아키텍처면 중단 |
| 3 | `UPTIME_KUMA_PORT` 중복 점유 검사 (`ss`/`netstat`) | 포트 변경 안내 후 중단 |
| 4 | `app-data` 디렉토리 생성 (없으면) | — |
| 5 | `docker compose up -d` | — |
| 6 | 3초 후 컨테이너 Running 여부 확인 | 컨테이너 로그 50줄 출력 후 중단 |

이미지가 이미 있으면 `load` 를 건너뛰므로 **재실행해도 안전**하다.

수동으로 하려면:

```bash
docker load -i images/uptime-kuma-latest-amd64.tar.gz
docker compose up -d
```

### 3-3. 접속

```
http://<서버IP>:9998
```

**외부에서 접속할 때 쓰는 포트가 곧 `.env` 의 `UPTIME_KUMA_PORT` 값**이다 (현재 `9998`).

**초기 설정:**
1. 첫 접속 시 관리자 계정 생성 화면 나타남
2. 사용자명, 비밀번호, 이메일 입력 후 계정 생성
3. 로그인 후 대시보드에서 모니터링 대상 추가

---

## 4. 포트 변경

`.env` 한 줄만 고치고 재기동한다.

```bash
echo 'UPTIME_KUMA_PORT=8080' > .env
docker compose up -d --force-recreate
```

현재 기본값은 **9998** 로 잡아두었다.

또한 9998 은 여러 툴이 관례적으로 쓰는 흔한 포트는 아니지만, 충돌 가능성이 있다.
`install.sh` 가 기동 전에 점유 여부를 검사해 걸리면 중단하므로, 실패하면 다른 값으로 바꾸면 된다.

---

## 5. 초기 설정 (GUI)

### 5-1. 관리자 계정 생성

1. 첫 접속 (`http://<서버IP>:9998`)
2. 계정 생성 페이지에서 정보 입력:
   - **Username**: 원하는 사용자명
   - **Password**: 비밀번호
   - **Repeat Password**: 비밀번호 확인
   - **Email**: 이메일 (필수이지만 알림 비활성화 시 미사용)
3. "Create" 클릭

### 5-2. 모니터링 대상 추가

1. 대시보드 상단 "Add Monitor" 클릭
2. 모니터링 설정:
   - **Monitor Type**: HTTP(s), TCP, Ping, DNS 등 선택
   - **Friendly Name**: 서비스명 (예: "메인 API", "데이터베이스")
   - **URL / Hostname**: 모니터링 대상 주소
   - **Interval**: 체크 간격 (기본 60초)
3. "Save" 클릭

예시: 내부 API 서버 모니터링
- Monitor Type: `HTTP`
- URL: `http://192.168.1.100:8080/health`
- Interval: `60` (초)

---

## 6. 외부 전송 차단 설정

본 패키지는 알림 기능이 비활성화되어 있어 **외부 전송 데이터 0%**.

만약 추후 알림을 활성화하려면:

1. **Settings** (좌측 메뉴) → **Notifications**
2. 알림 채널 추가 (Email, Slack, Discord 등)
3. 각 채널별 인증 정보 입력

현재는 이 섹션을 건드리지 않으면 모든 데이터가 로컬에만 저장된다.

> **보안 고려사항:** 알림 활성화 시 해당 서비스(Slack, Email 등)로의 outbound 통신이 필요하다.
> 폐쇄망 정책에 따라 방화벽 승인을 받아야 한다.

---

## 7. 데이터 백업 / 복구

모든 데이터는 `app-data/` 디렉토리 아래 SQLite DB + 설정 파일로 저장된다.

### 백업
```bash
tar czf uptime-kuma-backup-$(date +%Y%m%d).tar.gz app-data/
```

### 복구
```bash
tar xzf uptime-kuma-backup-20260906.tar.gz
docker compose restart
```

---

## 8. 주의사항

| 항목 | 내용 |
|---|---|
| **모니터링 대상** | 폐쇄망 내부 서비스만 가능. 외부 인터넷 서비스는 통신 불가. |
| **포트 범위** | 5F 서버는 62000~62999 대역 정책이 있을 수 있음. 필요시 포트 변경 (→ 4절). |
| **권한** | 도커 데몬에 접근 필요. `sudo ./install.sh` 또는 docker 그룹 가입 필요. |
| **방화벽** | 모니터링 대상 서버들의 방화벽에서 Uptime Kuma 서버로의 inbound 를 허용해야 함. |
| **db 경로** | `app-data/` 가 없으면 설치 중 자동 생성. 해당 디렉토리 권한 확인. |
| **성능** | 모니터링 대상이 많으면(100+) CPU/메모리 사용량 증가. 필요시 interval 조정. |
| **외부 노출** | 대시보드 포트를 인터넷에 직접 열지 말 것. 사내 네트워크 내에서만 접근. |

---

## 9. 운영 명령

```bash
docker ps -f name=uptime-kuma          # 상태 확인
docker logs -f uptime-kuma             # 로그 확인
docker compose down                    # 중지
./uninstall.sh                         # 제거 (데이터 유지)
./uninstall.sh --image                # 이미지까지 삭제
./uninstall.sh --all                  # 이미지 + 데이터 삭제
```

---

## 10. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `./install.sh: Permission denied` | Windows PC 를 경유해 옮기면 실행권한이 날아간다. `chmod +x install.sh uninstall.sh` 후 재실행 |
| 컨테이너는 Running 인데 접속 불가 | 포트 매핑 확인. `docker exec uptime-kuma netstat -ltn` 로 실제 리슨 포트 확인 |
| `port is already allocated` | 다른 서비스가 해당 포트 점유. `.env` 의 `UPTIME_KUMA_PORT` 변경 |
| 모니터링 대상에 접속 불가 | 대상 서비스가 폐쇄망 내부인지 확인. 방화벽 규칙 확인. `docker exec uptime-kuma curl <target>` 로 테스트 |
| `permission denied ... docker.sock` | 컨테이너가 도커 소켓을 못 읽음. 호스트 권한 확인 또는 `sudo` 실행 |
| 대시보드 데이터 손실 | `app-data/` 디렉토리가 삭제되면 복구 불가. 정기 백업 권장 |
| GUI에서 설정 저장이 안 됨 | 브라우저 개발자 도구(F12) → Console 탭에서 에러 확인. 서버 로그도 함께 확인 |

---

## 11. 검증 상태

실제 `docker load` + 기동 리허설은 미수행. 아래까지 확인했다.

- ✅ 이미지 tar 레이어 구조 (amd64 / arm64)
- ✅ `install.sh` / `uninstall.sh` bash 문법 검사 통과
- ✅ `docker-compose.yml` YAML 파싱 정상
- ✅ 압축파일 내 실행권한(`0755`) 보존
- ⬜ **`docker load` → `up -d` → 브라우저 접속** — 도커 있는 환경에서 1회 리허설 권장

---

## 12. 참고 자료

- Uptime Kuma 공식 문서: https://uptime.kuma.pet (외부)
- 폐쇄망 dozzle 가이드: [2026-0902_dozzle_오프라인설치_가이드.md](./2026-0902_dozzle_오프라인설치_가이드.md)

# master-api 문서

| 문서 | 내용 |
|---|---|
| [LOCAL_SETUP.md](./LOCAL_SETUP.md) | 로컬 개발 환경 구축. 설치 · 인프라 기동 · 환경변수 · 트러블슈팅 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 아키텍처와 핵심 플로우. 인증 · 콘텐츠 파이프라인 · 큐 · 알림 · 배치 |
| [CONTENT_DETAIL_LATENCY.md](./CONTENT_DETAIL_LATENCY.md) | 회의록 상세 진입 지연 확인(2026-08-20). 상세 조회 · stream-grant 호출 체인 분석 |

## 빠른 참조

**처음 세팅한다면** → `LOCAL_SETUP.md` 4장(설치)부터 순서대로.
사내 GitLab PAT 가 먼저 필요하다.

**코드를 읽기 시작한다면** → `ARCHITECTURE.md` 5장(콘텐츠 파이프라인).
이 서비스의 핵심이고, 나머지는 대부분 그 주변이다.

**장애를 보고 있다면** → `ARCHITECTURE.md` 6장(상태 머신)과 13-3(에러 코드).

**Prisma 가 이상해 보인다면** → `ARCHITECTURE.md` 2장 "데이터 접근 계층".
스키마가 이 리포에 없는 게 정상이다. 사내 패키지 안에 들어 있다.

## 실행 요약

```bash
redis-server --daemonize yes
brew services start kafka
~/.local/bin/consul agent -dev -client=127.0.0.1 -bind=127.0.0.1 &

node src/app.js
```

| URL | |
|---|---|
| <http://localhost:8000/health> | 헬스체크 |
| <http://localhost:8000/api-docs> | Swagger (API 79개) |
| <http://localhost:8500/ui> | Consul |

> MariaDB · MongoDB · MinIO 는 아직 미구성이다. 서버는 뜨지만 데이터 API 는 실패한다.
> 상세는 `LOCAL_SETUP.md` 10장.

## 문서 작성 원칙

- **실측한 것과 추정한 것을 구분해 표기한다.** 확인 안 된 건 "미확인"이라고 쓴다.
- 코드 인용에는 `파일:라인` 을 붙인다.
- 코드의 `★` 주석은 대부분 실제 장애의 흔적이다. 옮길 때 이유까지 함께 옮긴다.

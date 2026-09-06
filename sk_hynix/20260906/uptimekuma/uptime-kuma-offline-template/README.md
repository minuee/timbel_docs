# Uptime Kuma 오프라인 설치 패키지

폐쇄망 서버에 Uptime Kuma를 설치하기 위한 완전한 패키지입니다.

## 빠른 시작

```bash
tar xzf uptime-kuma-offline.tar.gz
cd uptime-kuma-offline
./install.sh
```

설치가 완료되면 다음 주소로 접속하세요:
```
http://<서버IP>:9998
```

## 패키지 구성

- `install.sh` - 자동 설치 스크립트
- `uninstall.sh` - 제거 스크립트
- `docker-compose.yml` - Docker Compose 설정
- `.env` - 포트 등 환경 설정 (기본값: 9998)
- `images/` - Docker 이미지 (amd64, arm64)
- `app-data/` - 데이터베이스 및 설정 저장 디렉토리 (설치 중 자동 생성)

## 설치 요구사항

- Docker 설치 완료
- Docker Compose 설치 완료
- 포트 9998 사용 가능
- 약 100MB 디스크 여유 공간

## 주요 특징

✅ **외부 전송 없음** - 모든 데이터가 로컬에만 저장됨
✅ **GUI 대시보드** - 웹 브라우저로 모든 설정 관리
✅ **다양한 모니터링** - HTTP, TCP, Ping, DNS 등 지원
✅ **폐쇄망 완전 대응** - 인터넷 연결 없이 독립 운영

## 설치 후 주의사항

1. **첫 접속 시** 관리자 계정을 생성해야 합니다
2. **모니터링 대상**은 폐쇄망 내부 서비스만 가능합니다
3. **알림 기능**은 현재 비활성화되어 있습니다 (필요시 추후 활성화 가능)
4. **데이터는 정기적으로 백업**하세요 (app-data/ 디렉토리)

## 상세 가이드

전체 설치 및 운영 가이드는 다음 문서를 참고하세요:
- [2026-0906_uptime-kuma_오프라인설치_가이드.md](../2026-0906_uptime-kuma_오프라인설치_가이드.md)

## 운영 명령

```bash
# 상태 확인
docker ps -f name=uptime-kuma

# 로그 보기
docker logs -f uptime-kuma

# 중지
docker-compose down

# 시작
docker-compose up -d

# 완전 제거 (데이터 포함)
./uninstall.sh --all
```

## 트러블슈팅

**포트가 이미 사용 중인 경우:**
```bash
echo 'UPTIME_KUMA_PORT=9999' > .env
docker-compose up -d --force-recreate
```

**컨테이너가 시작되지 않는 경우:**
```bash
docker logs uptime-kuma
```

더 자세한 트러블슈팅은 가이드 문서의 10절을 참고하세요.

## 라이선스

Uptime Kuma는 MIT 라이선스입니다.
https://github.com/louislam/uptime-kuma

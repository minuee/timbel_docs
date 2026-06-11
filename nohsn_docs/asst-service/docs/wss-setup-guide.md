# WebSocket Secure (WSS) 설정 가이드

## 개요

이 문서는 ASST Service에서 Socket.IO를 WSS(WebSocket Secure)로 설정하는 방법을 설명합니다.

## 기본 동작

### 기본 WSS 사용

**기본적으로 WSS(WebSocket Secure)가 활성화**됩니다. 다음과 같은 조건입니다:

- **기본값**: `SOCKET_SECURE=1` (WSS 사용)
- **비보안 모드**: `SOCKET_SECURE=0` (WS 사용, 개발용)

### WSS 활성화 조건

다음 조건 중 하나라도 충족되면 **WSS가 활성화**됩니다:

1. **기본 설정**: `SOCKET_SECURE`가 설정되지 않았거나 `1` (기본값: WSS 사용)
2. **HTTPS 직접 활성화**: `HTTPS_ENABLED=1` (기본값은 '0', Load Balancer에서 SSL 처리)

### WebSocket 연결 프로토콜

- **기본값 (K8s/Load Balancer 환경)**: `wss://` (WebSocket Secure, SOCKET_SECURE=1)
- **개발용 비보안 모드** (`SOCKET_SECURE=0`): `ws://` (WebSocket)
- **직접 HTTPS 서버** (`HTTPS_ENABLED=1`): `wss://` with SSL certificates

## 설정 방법

### 1. 기본 WSS 사용 (권장)

별도 설정 없이 기본적으로 WSS를 사용합니다:

```bash
# 기본값이므로 별도 설정 불필요
# SOCKET_SECURE=1 (기본값)
```

이렇게 하면 자동으로:

- Socket.IO에서 `secure: true` 옵션 활성화
- WebSocket 연결이 WSS로 처리됨
- HTTP 요청도 HTTPS로 예상됨

### 1-1. 개발용 비보안 모드

개발 환경에서 HTTP/WS를 사용하려면:

```bash
HTTPS_ENABLED=0
SOCKET_SECURE=0
```

### 2. HTTPS 서버와 함께 WSS 사용

SSL 인증서가 있는 경우 HTTPS 서버를 직접 실행할 수 있습니다:

```bash
# 환경변수 설정
HTTPS_ENABLED=1
SSL_KEY_PATH=/path/to/your/private.key
SSL_CERT_PATH=/path/to/your/certificate.crt
NODE_ENV=production
```

### 3. 리버스 프록시를 통한 WSS (권장)

실제 프로덕션에서는 Nginx나 Apache와 같은 리버스 프록시를 사용하는 것이 권장됩니다:

#### Nginx 설정 예시

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;

    # HTTP API 요청 프록시
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 연결 프록시
    location /socket.io/ {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

이 경우 애플리케이션 설정:

```bash
# 기본값으로 WSS 사용, Nginx에서 SSL 처리하므로 HTTPS 비활성화
HTTPS_ENABLED=0  # Nginx에서 SSL 처리하므로 0
```

## Docker 배포 설정

### 1. 리버스 프록시 사용 (권장)

**docker-compose.prod.yml**

```yaml
environment:
  - NODE_ENV=production
  - HTTPS_ENABLED=0 # Nginx에서 SSL 처리
  - SOCKET_SECURE=1 # 기본값: WSS 사용
  - CORS_ALLOWED_ORIGINS=https://ecplab.etaas.co.kr,https://remote-app.example.com
```

### 2. 직접 HTTPS 서버 실행

**docker-compose.prod.yml**

```yaml
environment:
  - NODE_ENV=production
  - HTTPS_ENABLED=1
  - SOCKET_SECURE=1 # 기본값이지만 명시적 설정
  - SSL_KEY_PATH=/app/ssl/private.key
  - SSL_CERT_PATH=/app/ssl/certificate.crt
  - CORS_ALLOWED_ORIGINS=https://ecplab.etaas.co.kr,https://remote-app.example.com
volumes:
  - ./ssl:/app/ssl:ro # SSL 인증서 마운트
```

## 클라이언트 연결 방법

### JavaScript/Node.js

```javascript
import { io } from 'socket.io-client';

// 프로덕션 환경에서는 자동으로 WSS 사용
const socket = io('https://yourdomain.com', {
  transports: ['websocket', 'polling'],
  secure: true, // WSS 사용
  rejectUnauthorized: true, // SSL 인증서 검증
});

socket.on('connect', () => {
  console.log('WSS 연결 성공:', socket.id);
});
```

### 브라우저에서

```html
<script src="https://cdn.socket.io/4.8.1/socket.io.min.js"></script>
<script>
  const socket = io('https://yourdomain.com', {
    transports: ['websocket', 'polling'],
    secure: true,
  });

  socket.on('connect', () => {
    console.log('WSS 연결 성공');
  });
</script>
```

## 설정 확인

### 1. 서버 로그 확인

애플리케이션 시작 시 다음과 같은 로그가 출력됩니다:

```
서버 설정 완료: {
  environment: 'production',
  httpsEnabled: true,
  socketSecure: true,
  ...
}
```

### 2. 브라우저 개발자 도구 확인

Network 탭에서 WebSocket 연결이 `wss://`로 시작하는지 확인하세요.

### 3. Redis Monitor API로 연결 정보 확인

```bash
GET /api/asst/v1/redis-monitor/start/{channel}
```

응답에서 `endpoint`가 `https://`로 시작하는지 확인하세요.

## 문제 해결

### 1. SSL 인증서 오류

```
SSL 인증서 로드 실패: Error: ENOENT: no such file or directory
```

- SSL 파일 경로가 올바른지 확인
- 파일 권한이 올바른지 확인
- Docker에서는 볼륨 마운트가 올바른지 확인

### 2. WebSocket 연결 실패

```
WebSocket connection failed
```

- 방화벽에서 포트가 열려있는지 확인
- 리버스 프록시 설정이 올바른지 확인
- SSL 인증서가 유효한지 확인

### 3. Mixed Content 오류

HTTPS 페이지에서 HTTP WebSocket 연결 시도 시:

```
Mixed Content: The page at 'https://...' was loaded over HTTPS, but attempted to connect to the insecure WebSocket endpoint 'ws://...'
```

- `NODE_ENV=production` 설정 확인
- 클라이언트에서 `https://` URL 사용 확인

## 보안 고려사항

1. **SSL 인증서**: 신뢰할 수 있는 CA에서 발급받은 인증서 사용
2. **CORS 설정**: 프로덕션에서는 특정 도메인만 허용
3. **방화벽**: 필요한 포트만 열기
4. **인증**: Socket.IO 연결에 적절한 인증 메커니즘 구현

## 성능 최적화

1. **리버스 프록시 사용**: Nginx 등을 통한 SSL 터미네이션
2. **Connection Pooling**: Socket.IO 연결 풀링 활용
3. **Compression**: WebSocket 메시지 압축 활성화

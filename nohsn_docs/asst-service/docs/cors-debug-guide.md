# Socket.IO CORS 차단 문제 해결 가이드

## 🚨 **문제 증상**
```
Blocked message from unauthorized origin: https://ecplab.etaas.co.kr
```

## 🔍 **가능한 원인들**

### 1. **브라우저 정책 (가장 가능성 높음)**
- Mixed Content 정책: HTTPS 페이지에서 HTTP Socket.IO 연결 시도
- 해결책: Socket.IO 서버도 HTTPS/WSS 사용

### 2. **CDN/Proxy 설정**
- AWS CloudFront, Nginx 등에서 WebSocket 차단
- 해결책: Proxy 설정에서 WebSocket 허용

### 3. **Socket.IO CORS 설정**
- Gateway 데코레이터의 CORS 설정
- 해결책: origin 허용 목록에 도메인 추가

### 4. **Network Policy (K8s)**
- Kubernetes NetworkPolicy에서 차단
- 해결책: Ingress/Service 설정 확인

## 🛠️ **단계별 해결 방법**

### Step 1: Socket.IO CORS 설정 확인
현재 설정:
```typescript
@WebSocketGateway({
  cors: {
    origin: true, // 모든 origin 허용 (디버깅용)
    methods: ['GET', 'POST'],
    credentials: true,
    allowedHeaders: ['*'],
  }
})
```

### Step 2: 클라이언트 연결 방식 확인
```javascript
// 문제가 있는 연결 방식
const socket = io('http://your-server.com'); // HTTP 연결

// 올바른 연결 방식
const socket = io('https://your-server.com', {
  secure: true,
  transports: ['websocket', 'polling']
});
```

### Step 3: 브라우저 개발자 도구 확인
1. **Network 탭**: WebSocket 연결 시도 확인
2. **Console 탭**: CORS 오류 메시지 확인
3. **Security 탭**: Mixed Content 경고 확인

### Step 4: 서버 로그 확인
```bash
# Socket.IO 연결 시도 로그 확인
kubectl logs -f deployment/asst-service | grep -E "(NEW CLIENT|CORS CHECK)"

# 예상 로그:
# 🔗 NEW CLIENT CONNECTED: abc123
# 🌐 CLIENT ORIGIN: https://ecplab.etaas.co.kr
# 🔒 CORS CHECK: ✅ ALLOWED - Origin: https://ecplab.etaas.co.kr
```

## 🔧 **임시 해결책**

### 1. **완전 개방 (디버깅용)**
```typescript
@WebSocketGateway({
  cors: true, // 모든 origin 허용
})
```

### 2. **특정 도메인만 허용**
```typescript
@WebSocketGateway({
  cors: {
    origin: ['https://ecplab.etaas.co.kr'],
    credentials: true
  }
})
```

### 3. **클라이언트에서 강제 HTTPS 사용**
```javascript
const socket = io('https://your-server.com', {
  secure: true,
  rejectUnauthorized: false, // 자체 서명 인증서 허용 (테스트용)
  transports: ['polling', 'websocket'] // polling을 먼저 시도
});
```

## 🎯 **권장 해결 순서**

1. **Socket.IO CORS를 완전 개방으로 설정** (현재 적용됨)
2. **클라이언트에서 HTTPS 연결 확인**
3. **브라우저 콘솔에서 실제 오류 메시지 확인**
4. **서버 로그에서 연결 시도 확인**
5. **AWS ALB/Ingress 설정 확인**

## ⚠️ **주의사항**

- `origin: true` 설정은 임시 디버깅용입니다
- 프로덕션에서는 특정 도메인만 허용해야 합니다
- 보안을 위해 디버깅 완료 후 다시 제한적으로 설정하세요

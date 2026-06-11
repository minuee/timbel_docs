# AWS EKS Socket.IO 연결 문제 해결 가이드

## 🚨 **주요 문제점들**

### 1. **Load Balancer Sticky Session 미설정**
가장 흔한 원인입니다. Socket.IO는 연결 유지를 위해 같은 Pod로 요청이 라우팅되어야 합니다.

**해결책:**
```yaml
# Ingress annotations에 추가
alb.ingress.kubernetes.io/target-group-attributes: stickiness.enabled=true,stickiness.lb_cookie.duration_seconds=86400
```

### 2. **HTTPS/WSS 인증서 문제**
현재 설정에서 HTTPS_ENABLED=1이 기본값이므로 SSL 인증서가 없으면 연결 실패합니다.

**임시 해결책 (테스트용):**
```bash
HTTPS_ENABLED=0
SOCKET_SECURE=0
```

### 3. **Health Check 경로 문제**
Load Balancer가 잘못된 경로로 헬스체크하면 Pod가 Unhealthy로 표시됩니다.

**확인사항:**
```yaml
alb.ingress.kubernetes.io/healthcheck-path: /health/check
```

## 🔍 **단계별 진단 방법**

### Step 1: 기본 연결 테스트
```bash
# Pod 직접 접근 테스트
kubectl port-forward deployment/asst-service 3000:3000

# 로컬에서 테스트
curl http://localhost:3000/health/check
```

### Step 2: 로그 확인
```bash
# Socket.IO 초기화 로그 확인
kubectl logs deployment/asst-service | grep "Socket.IO"

# 연결 시도 로그 확인
kubectl logs deployment/asst-service -f | grep "Client connected\|Client disconnected"
```

### Step 3: Load Balancer 설정 확인
```bash
# ALB Target Group 상태 확인
aws elbv2 describe-target-groups --region your-region

# Target Health 확인
aws elbv2 describe-target-health --target-group-arn your-target-group-arn
```

### Step 4: 네트워크 정책 확인
```bash
# Service 확인
kubectl get svc asst-service-svc -o yaml

# Ingress 확인
kubectl get ingress asst-service-ingress -o yaml

# Pod 상태 확인
kubectl get pods -l app=asst-service
```

## 🛠️ **임시 디버깅 설정**

### 1. 비보안 모드로 테스트
```yaml
env:
- name: HTTPS_ENABLED
  value: "0"
- name: SOCKET_SECURE
  value: "0"
- name: DEBUG
  value: "socket.io:*"
- name: LOG_LEVEL
  value: "debug"
```

### 2. CORS 완전 개방 (테스트용)
```yaml
env:
- name: CORS_ALLOWED_ORIGINS
  value: ""  # 모든 origin 허용
```

### 3. Socket.IO 타임아웃 증가
현재 코드에서 이미 적용됨:
- pingTimeout: 60000ms (60초)
- pingInterval: 25000ms (25초)
- upgradeTimeout: 30000ms (30초)

## 🔧 **AWS ALB 권장 설정**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asst-service-ingress
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    
    # 🔥 가장 중요: Sticky Session
    alb.ingress.kubernetes.io/target-group-attributes: |
      stickiness.enabled=true,
      stickiness.lb_cookie.duration_seconds=86400,
      deregistration_delay.timeout_seconds=30
    
    # Health Check 설정
    alb.ingress.kubernetes.io/healthcheck-path: /health/check
    alb.ingress.kubernetes.io/healthcheck-protocol: HTTP
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: "30"
    alb.ingress.kubernetes.io/healthcheck-timeout-seconds: "5"
    alb.ingress.kubernetes.io/healthy-threshold-count: "2"
    alb.ingress.kubernetes.io/unhealthy-threshold-count: "3"
    
    # WebSocket 지원
    alb.ingress.kubernetes.io/load-balancer-attributes: |
      idle_timeout.timeout_seconds=60,
      routing.http2.enabled=true
spec:
  rules:
  - host: your-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: asst-service-svc
            port:
              number: 80
```

## 📊 **모니터링 명령어**

### 실시간 로그 모니터링
```bash
# Socket.IO 관련 로그만 필터링
kubectl logs -f deployment/asst-service | grep -E "(Socket\.IO|Client connected|Client disconnected|WebSocket)"

# 에러 로그만 확인
kubectl logs deployment/asst-service | grep -E "(ERROR|WARN|Failed)"
```

### 연결 상태 확인
```bash
# Pod 내부에서 netstat 확인 (디버깅용)
kubectl exec -it deployment/asst-service -- netstat -tlnp

# Service Endpoints 확인
kubectl get endpoints asst-service-svc
```

## 🚀 **클라이언트 테스트 코드**

### JavaScript 클라이언트 디버깅
```javascript
import { io } from 'socket.io-client';

const socket = io('https://your-domain.com', {
  transports: ['websocket', 'polling'], // polling을 fallback으로 사용
  upgrade: true,
  rememberUpgrade: false,
  timeout: 20000,
  forceNew: true,
  
  // 디버깅용
  debug: true,
});

socket.on('connect', () => {
  console.log('✅ Connected:', socket.id);
  console.log('Transport:', socket.io.engine.transport.name);
});

socket.on('connect_error', (error) => {
  console.error('❌ Connection Error:', error);
  console.log('Error type:', error.type);
  console.log('Error description:', error.description);
});

socket.on('disconnect', (reason) => {
  console.warn('🔌 Disconnected:', reason);
});

// 연결 상태 모니터링
setInterval(() => {
  console.log('Connection status:', socket.connected);
  console.log('Transport:', socket.io.engine?.transport?.name);
}, 5000);
```

## ⚠️ **주의사항**

1. **SSL 인증서**: HTTPS_ENABLED=1 사용 시 유효한 SSL 인증서 필요
2. **도메인 설정**: CORS_ALLOWED_ORIGINS에 실제 클라이언트 도메인 설정
3. **리소스 제한**: K8s에서 메모리/CPU 제한으로 인한 연결 끊김 가능
4. **Pod 재시작**: 배포 시 기존 연결이 끊어질 수 있음

## 🎯 **권장 해결 순서**

1. **임시 비보안 모드로 테스트** (HTTPS_ENABLED=0, SOCKET_SECURE=0)
2. **Sticky Session 설정** (가장 중요!)
3. **Health Check 경로 확인**
4. **로그 레벨을 debug로 설정**
5. **클라이언트에서 polling transport 우선 사용**
6. **연결 성공 후 보안 설정 단계적 적용**

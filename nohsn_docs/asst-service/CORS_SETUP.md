# CORS 설정 가이드

> ⚠️ **[ARCHIVED]** 최신 인수인계 문서는 [/adv_docs/operations/](../adv_docs/operations/) 를 참조하세요.
> 환경변수 (`CORS_ALLOWED_ORIGINS`) 는 [adv_docs/operations/env-variables.md](../adv_docs/operations/env-variables.md) 에 정리되어 있습니다.
> 운영 환경의 CORS는 보통 Langsa 게이트웨이에서 처리합니다.

---

## 개요

이 문서는 ASST Service의 CORS(Cross-Origin Resource Sharing) 설정 방법을 설명합니다.

## 환경별 CORS 설정

### 1. 개발 환경 (NODE_ENV=development 또는 local)

- **기본 동작**: 모든 origin 허용
- **환경변수 설정**: `CORS_ALLOWED_ORIGINS`를 빈 문자열로 설정하거나 특정 origin들만 허용

```bash
# 모든 origin 허용 (기본값)
CORS_ALLOWED_ORIGINS=

# 특정 origin들만 허용
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000
```

### 2. 프로덕션 환경 (NODE_ENV=production)

- **기본 동작**: `CORS_ALLOWED_ORIGINS`가 비어있으면 모든 origin 허용
- **환경변수 설정**: `CORS_ALLOWED_ORIGINS`를 설정하면 해당 origin들만 허용

```bash
# 모든 origin 허용 (기본값)
CORS_ALLOWED_ORIGINS=

# 특정 origin들만 허용
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com,https://admin.yourdomain.com
```

## 허용되는 HTTP 메서드

- GET
- POST
- PUT
- DELETE
- PATCH
- OPTIONS

## 허용되는 헤더

- Origin
- X-Requested-With
- Content-Type
- Accept
- Authorization
- X-API-Key
- x-auth-token (동적 DB 연결용)
- x-trace-id (트레이싱용)

## 노출되는 헤더

- Content-Length
- X-Total-Count
- X-Trace-Id

## Docker 배포 시 설정

### docker-compose.yml (프로덕션)

```yaml
environment:
  - NODE_ENV=production
  - CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

### docker-compose.dev.yml (개발)

```yaml
environment:
  - NODE_ENV=development
  - CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:8080
```

## 문제 해결

### 1. CORS 오류가 발생하는 경우

1. 브라우저 개발자 도구에서 Network 탭 확인
2. 서버 로그에서 CORS 설정 확인
3. `CORS_ALLOWED_ORIGINS` 환경변수 값 확인

### 2. Preflight 요청 실패

- OPTIONS 요청이 실패하는 경우 허용되는 메서드와 헤더 확인
- `x-auth-token` 헤더를 사용하는 경우 `CORS_ALLOWED_HEADERS`에 포함되어 있는지 확인

### 3. 인증 토큰 전송 실패

- `credentials: true` 설정으로 쿠키와 인증 헤더 전송 가능
- `Authorization` 헤더와 `x-auth-token` 헤더 모두 허용됨

## 로깅

서버 시작 시 CORS 설정이 로그에 출력됩니다:

```
CORS 설정 완료: {
  environment: 'production',
  isProduction: true,
  corsOrigin: ['https://yourdomain.com', 'https://app.yourdomain.com'],
  allowedMethods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
  allowedHeaders: ['Origin', 'X-Requested-With', 'Content-Type', 'Accept', 'Authorization', 'X-API-Key', 'x-auth-token', 'x-trace-id']
}
```

## 보안 고려사항

1. 프로덕션 환경에서는 반드시 `CORS_ALLOWED_ORIGINS`를 설정하여 허용할 도메인을 제한하세요
2. 개발 환경에서도 가능한 한 특정 origin들만 허용하도록 설정하세요
3. `credentials: true` 설정으로 인해 민감한 정보가 전송될 수 있으므로 신뢰할 수 있는 origin만 허용하세요

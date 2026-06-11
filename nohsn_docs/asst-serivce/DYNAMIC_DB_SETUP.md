# 동적 DB 연결 설정 가이드

> ⚠️ **[ARCHIVED]** 최신 문서는 [/adv_docs/architecture/01-multi-tenant-db.md](../adv_docs/architecture/01-multi-tenant-db.md) 를 참조하세요.
> 더 상세한 흐름도, 캐시 동작, 자동 마이그레이션 주의사항이 정리되어 있습니다.

---

## 개요

이 프로젝트는 서버 시작 시 정적 DB 연결이 아닌, API 호출 시마다 동적으로 DB 연결 정보를 조회하여 연결하고 해제하는 구조로 변경되었습니다.

## 주요 변경사항

### 1. 새로운 서비스들

- **TenantConfigService**: 테넌트 설정 조회 서비스
- **DynamicDatabaseService**: 동적 DB 연결 관리 서비스
- **DbCleanupInterceptor**: 요청 완료 후 DB 연결 해제 인터셉터

### 2. 인증 헤더 처리

- `x-auth-token` 헤더 우선 처리
- `Authorization` 헤더 fallback 지원
- Bearer 토큰 자동 파싱

### 3. 동적 DB 연결 플로우

1. API 요청 시 `x-auth-token` 헤더에서 토큰 추출
2. 토큰으로 테넌트 설정 조회 (`http://222.99.52.67:32020/api/v1/tenants/get_configs`)
3. DB 연결 정보 파싱 및 동적 연결 생성
4. API 로직 수행
5. 요청 완료 후 DB 연결 자동 해제

## 환경 변수 설정

```bash
# 테넌트 설정 서비스 URL
TENANT_CONFIG_URL=http://222.99.52.67:32020/api/v1/tenants/get_configs
```

## API 사용 예시

### 요청 헤더

```http
x-auth-token: Bearer your_bearer_token_here
Content-Type: application/json
```

### 응답 예시

테넌트 설정 조회 API 응답:

```json
{
  "tenant_id": "tenant_fd73bf8c_b00b_4bbf_8e7b_4d0dae11ed99",
  "configs": {
    "db_config": "postgresql://tenant_8bc6d075:746b925b8c3b407a9c532dcfa70001d4@128.0.0.1:32011/tenant_fd73bf8c_b00b_4bbf_8e7b_4d0dae11ed99",
    "minio_config": {
      "access_key": "lhlPH-rpcEee3ebWqyjngw",
      "secret_key": "N9Kvx3unpcIv-OmvIc1HvLddDHjej_DBYuyD6VjPOH0",
      "bucket_name": "tenant-fd73bf8c-b00b-4bbf-8e7b-4d0dae11ed99",
      "endpoint": "128.0.0.1:9000"
    },
    "es_config": {
      "password": "zIaPx0IaS5YFf2unKQ9RaA",
      "username": "s7kelrsktwu",
      "index_name": "tenant-fd73bf8c-b00b-4bbf-8e7b-4d0dae11ed99",
      "endpoint": "128.0.0.1:9200"
    }
  }
}
```

## 구현된 기능

### ✅ 완료된 작업

1. **TenantConfigService**: 테넌트 설정 조회 및 DB 연결 문자열 파싱
2. **DynamicDatabaseService**: 동적 DB 연결 생성/관리/해제
3. **AuthMiddleware**: x-auth-token 헤더 처리 및 동적 DB 연결 생성
4. **DbCleanupInterceptor**: 요청 완료 후 DB 연결 자동 해제
5. **AdvisorService**: 모든 메서드를 동적 DB 연결로 수정
6. **모든 컨트롤러**: 동적 DB 연결 및 인터셉터 적용
   - UserController
   - NoticeController
   - TeamController
   - CoachingController
   - CenterController
   - ConfigController
   - CsClassificationController
   - FavoriteController
   - KeywordDetectController
   - MajorCategoryController
   - MemoGroupController
   - MemoController
   - MiddleCategoryController
   - MinorCategoryController

### 🎯 구현 완료

- 모든 API 엔드포인트가 동적 DB 연결을 사용합니다
- 모든 컨트롤러에 DB 정리 인터셉터가 적용되었습니다
- 토큰 기반 테넌트별 DB 연결이 완전히 구현되었습니다

## 테스트 방법

### 1. 서버 시작

```bash
npm run start:dev
```

### 2. API 테스트

#### 사용자 목록 조회

```bash
curl -X GET http://localhost:3000/users \
  -H "x-auth-token: Bearer your_token_here" \
  -H "Content-Type: application/json"
```

#### 공지사항 목록 조회

```bash
curl -X GET http://localhost:3000/notices \
  -H "x-auth-token: Bearer your_token_here" \
  -H "Content-Type: application/json"
```

#### 팀 목록 조회

```bash
curl -X GET http://localhost:3000/teams \
  -H "x-auth-token: Bearer your_token_here" \
  -H "Content-Type: application/json"
```

#### 사용자 생성 (ADMIN 권한 필요)

```bash
curl -X POST http://localhost:3000/users \
  -H "x-auth-token: Bearer your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "user_123",
    "user_key": "test_user",
    "email": "test@example.com",
    "name": "Test User",
    "team_id": "team_123",
    "role": "AGENT"
  }'
```

### 3. 자동화된 테스트

테스트 스크립트를 사용하여 모든 API를 자동으로 테스트할 수 있습니다:

```bash
# 테스트 토큰을 설정하고 실행
node test-dynamic-db.js
```

## 주의사항

1. **토큰 유효성**: x-auth-token 헤더의 토큰이 유효해야 테넌트 설정 조회가 가능합니다.
2. **DB 연결 관리**: 각 요청마다 새로운 DB 연결이 생성되므로 연결 수 제한에 주의하세요.
3. **에러 처리**: 테넌트 설정 조회 실패 시 적절한 에러 응답이 반환됩니다.
4. **성능**: 동적 연결 생성으로 인한 약간의 지연이 있을 수 있습니다.

## 로그 확인

서버 로그에서 다음과 같은 메시지들을 확인할 수 있습니다:

- `🔗 동적 DB 연결 생성 시작`
- `✅ 동적 DB 연결 생성 완료`
- `DB 연결 해제 완료`

## 문제 해결

### 테넌트 설정 조회 실패

- x-auth-token 헤더가 올바른지 확인
- 테넌트 설정 서비스 URL이 접근 가능한지 확인
- 네트워크 연결 상태 확인

### DB 연결 실패

- 테넌트 설정의 db_config 문자열이 올바른지 확인
- DB 서버가 접근 가능한지 확인
- DB 인증 정보가 유효한지 확인

# SystemConfig API 스펙

> 참조: [FD-SYS-시스템설정](../../01-requirements/features/FD-SYS-시스템설정.md) · [rules.md](./rules.md) · [data.md](./data.md) · [04-permission-architecture](../../02-architecture/04-permission-architecture.md)

---

## 엔드포인트 요약

| # | 메서드 | 경로 | 설명 | 권한 |
|---|--------|------|------|------|
| 1 | GET | `/admin/system-config` | 카테고리별 그룹핑 설정 조회 | `manage_system` |
| 2 | PATCH | `/admin/system-config/:configKey` | 설정 변경 | `manage_system` |

---

## 1. GET `/admin/system-config`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 전체 시스템 설정을 카테고리별로 그룹핑하여 조회 |
| 권한 | `manage_system` AdminPermission |
| 비즈니스 규칙 | BR-SYS-001 |

### Request

```typescript
// Query
interface GetSystemConfigQuery {
  category?: SystemConfigCategory; // 특정 카테고리만 필터 (생략 시 전체)
}

type SystemConfigCategory =
  | 'system'        // 시스템 전역 — 업로드 제한
  | 'document'      // 문서 관리 — 태그 수, 자동 저장, 드래프트 방치, 블록 상한, 잠금 타임아웃
  | 'approval'      // 승인 — 긴급 발행 사유, 리마인더
  | 'aggregation'   // 집계 — 인기 가중치, 트렌딩 기준값
  | 'audit'         // 감사 로그 — 보관 기간, access log 설정
  | 'export'        // 내보내기 — 워터마크, 비동기 임계치, 파일 TTL, 최대 크기, Job 대기
  | 'embedding'     // 임베딩 — 워커 수, 재시도
  | 'community'     // 커뮤니티 — 댓글 제한, 신고 설정, 북마크/게시글 한도
  | 'monitoring'    // 모니터링 — 수집 주기, 알림 쿨다운, 보관 기간, 용량 예측
  | 'ai'            // AI — 일일 쿼터, 동시 요청, 토큰 한도, 신뢰도 임계값
  | 'notification'; // 알림 — 묶음 시간 창, 보관 기간, 야간 무음, 재시도 횟수
```

### Response

```typescript
// 200 OK
interface SystemConfigGroupResponse {
  category: string;               // 카테고리명
  display_name: string;           // UI 표시명
  configs: SystemConfigResponse[];// 해당 카테고리의 설정 목록
}

interface SystemConfigResponse {
  config_key: string;    // 설정 키
  category: string;      // 카테고리
  value: unknown;        // 설정값 (JSON 원본)
  value_type: 'number' | 'string' | 'boolean' | 'object' | 'array';
  description: string;   // 설정 설명
  updated_by: string;    // 최종 변경자 UUID
  updated_at: string;    // 최종 변경 일시 (ISO 8601)
}

// 최상위 응답
type GetSystemConfigResponse = SystemConfigGroupResponse[];
```

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 403 | `ACL_PERMISSION_DENIED` | `manage_system` 권한 미보유 | BR-SYS-001 |

---

## 2. PATCH `/admin/system-config/:configKey`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 단일 설정 항목 변경 |
| 권한 | `manage_system` AdminPermission |
| 비즈니스 규칙 | BR-SYS-001, BR-SYS-002, BR-SYS-010, BR-SYS-012, BR-SYS-013 |

### Request

```typescript
// Path Params
interface UpdateSystemConfigParams {
  configKey: string; // 변경할 설정 키
}

// Body
interface UpdateSystemConfigRequest {
  value: unknown;    // 변경할 값
}
```

### Response

```typescript
// 200 OK
interface UpdateSystemConfigResponse {
  config_key: string;
  value: unknown;       // 변경 후 값
  updated_by: string;
  updated_at: string;
}
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-SYS-001 | `manage_system` 권한 필수 |
| BR-SYS-010 | 변경 사실을 `system_config.changed` 이벤트로 감사 로그에 비동기 기록 |
| BR-SYS-012 | 값 유효 범위 초과 시 `SYS_INVALID_VALUE` 반환 |
| BR-SYS-013 | 존재하지 않는 config_key 시 `SYS_KEY_NOT_FOUND` 반환 |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 400 | `SYS_INVALID_VALUE` | 설정값 유효 범위 초과 (음수, 상한 초과 등) | BR-SYS-012 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_system` 권한 미보유 | BR-SYS-001 |
| 404 | `SYS_KEY_NOT_FOUND` | 존재하지 않는 config_key | BR-SYS-013 |

---

## 공통 에러 코드

| 에러 코드 | HTTP | 설명 | BR |
|----------|------|------|---|
| `SYS_INVALID_VALUE` | 400 | 설정값이 허용된 범위를 벗어남 — 응답에 허용 범위 포함 | BR-SYS-012 |
| `SYS_KEY_NOT_FOUND` | 404 | 존재하지 않는 config_key 접근 | BR-SYS-013 |
| `ACL_PERMISSION_DENIED` | 403 | `manage_system` AdminPermission 미보유 | BR-SYS-001 |

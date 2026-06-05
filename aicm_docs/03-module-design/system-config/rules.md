# SystemConfig 비즈니스 규칙

> 참조: [FD-SYS-시스템설정](../../01-requirements/features/FD-SYS-시스템설정.md) · [api.md](./api.md) · [04-permission-architecture](../../02-architecture/04-permission-architecture.md)

---

## 1. 엔티티 생명주기

SystemConfig는 엔티티 자체의 상태(status) 필드를 갖지 않는다. 설정 변경 가능 여부는 **`manage_system` 권한(BR-SYS-001)** 및 값 검증 규칙(BR-SYS-012, BR-SYS-013)으로만 제어된다.

---

## 2. 규칙 카탈로그

### 권한

#### BR-SYS-001: 설정 접근 권한

- **트리거**: 모든 SystemConfig API 요청
- **조건**: 요청 사용자가 `manage_system` AdminPermission 보유
- **동작**: 권한 확인 통과 시 API 처리 진행
- **위반 시**: `manage_system` 미보유 → `ACL_PERMISSION_DENIED`(403)

### 변경 전파

#### BR-SYS-002: 이벤트 기반 캐시 무효화

- **트리거**: 설정 변경 DB 커밋 완료 시
- **조건**: 항상
- **동작**: 
  1. DB 커밋 완료 후 `system_config.changed` 이벤트를 EventBus(Best-effort)로 발행
  2. 구독 모듈이 해당 `config_key`의 캐시를 무효화
  3. 다음 설정 조회 시 DB에서 최신값을 읽어 캐시 갱신
- **위반 시**: 이벤트 발행 실패 시 최대 3회 재시도 (지수 백오프, 초기 지연 500ms). 재시도 소진 시 캐시는 TTL 만료(1시간)로 자연 갱신, 운영 모니터링 지표 증가 + 운영 관리자 알림

### 감사 로그

#### BR-SYS-010: 감사 로그 비동기 기록

- **트리거**: 모든 SystemConfig 설정값 변경
- **조건**: 항상
- **동작**: `system_config.changed` 이벤트를 통해 감사 로그에 비동기 기록 — `actor`, `action(system_config.update)`, `config_key`, `before`, `after`, `timestamp`. 감사 로그 기록은 설정 변경 API 응답에 영향을 주지 않음
- **위반 시**: 이벤트 발행 실패 시 BR-SYS-002의 재시도 정책 적용

### DB 시딩

#### BR-SYS-011: DB 시딩 (upsert-if-absent)

- **트리거**: 앱 최초 배포 또는 새 키 추가 후 배포
- **조건**: DB에 해당 `config_key`가 존재하는지 확인
- **동작**:
  - 키 없음 → 기본값으로 INSERT (초기 배포)
  - 키 있음 → UPDATE 하지 않음 (관리자 변경 보존)
  - 시딩 시 `created_at`은 시딩 시점 설정
- **위반 시**: 해당 없음 (배포 시점 자동 처리)

### 값 검증

#### BR-SYS-012: 설정값 유효 범위 검증

- **트리거**: 설정 변경 요청 시
- **조건**: 변경 대상 값의 타입과 범위
- **동작**: 타입별 유효 범위 검증 — 숫자형은 `0 이상` 및 항목별 상한(정의된 경우), 문자열은 최대 길이, 배열은 최대 요소 수
- **위반 시**: `SYS_INVALID_VALUE`(400) — 응답에 허용 범위 포함

#### BR-SYS-013: 존재하지 않는 키 접근 차단

- **트리거**: 조회, 변경 요청 시
- **조건**: 요청된 `config_key`가 DB에 존재하지 않음
- **동작**: 시딩되지 않은 키나 오타를 조기에 차단
- **위반 시**: `SYS_KEY_NOT_FOUND`(404)

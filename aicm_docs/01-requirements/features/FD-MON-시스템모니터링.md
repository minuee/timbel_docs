# 시스템 모니터링 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-MON |
| 버전 | 1.1 |
| 작성일 | 2026-03-31 |
| 기준 문서 | UC-ADM-시스템모니터링 (UC-ADM-18) |

---

## 1. 기능 개요

시스템을 구성하는 애플리케이션 레벨 서비스(API, 검색 엔진, AI 서비스, 큐, 데이터베이스)의 가동 상태와 성능 지표를 수집·표시하여, 장애를 선제적으로 감지하고 운영자가 즉각 대응할 수 있도록 하는 기능이다.

**모니터링 대상 영역**:

| 영역 | 수집 지표 | 단위 |
|------|----------|------|
| 서비스 헬스 | 각 서비스(API, 검색 엔진, AI 서비스, 큐 시스템, DB)의 가동 상태, 응답 시간, 에러율 | ms, % |
| 큐 모니터링 | 큐별 대기/처리중/실패 건수, 평균 처리 시간 | 건, 초 |
| 스토리지 | 파일 스토리지 사용량, DB 용량, AI 검색용 데이터 저장소 용량 | GB, % |
| 동시접속 | 현재 동시접속자 수, 피크 시간대 추이 | 명 |
| AI 서비스 | AI 응답 시간, 토큰 사용량, 일별 비용 추이 | ms, 원/달러 |

**범위 한정**: 인프라 레벨 모니터링(서버 CPU, 메모리, 디스크 등)은 외부 인프라 모니터링 도구가 담당하며, 이 기능정의서의 범위에 포함되지 않는다.

---

## 2. 비즈니스 규칙

### 2.1 서비스 상태 판정

**[BR-MON-001] 3단계 상태 판정**
- 각 지표는 정상(`healthy`) / 경고(`warning`) / 위험(`critical`) 3단계로 판정한다
- 판정 기준은 지표별 두 단계 임계치(경고 임계치, 위험 임계치)로 결정한다
- 시스템이 최초 가동 시 기본 임계치를 제공하며, 관리자가 지표별로 조정할 수 있다

**[BR-MON-002] 복합 서비스 상태 산출**
- 대시보드 상단의 전체 시스템 상태는 개별 서비스 상태 중 가장 심각한 등급으로 표시한다
- 예: 5개 서비스 중 1개가 `critical`이면 전체 상태는 `critical`

### 2.2 알림 규칙

**[BR-MON-003] 임계치 초과 알림**
- 지표가 설정된 임계치를 초과하면 관리자에게 알림을 발송한다
- 알림 채널: 인앱 알림 + 이메일 + 외부 메신저 연동(슬랙, Teams 등)
- 알림 채널은 지표별로 설정할 수 있다 (FD-NTF 모니터링 알림 유형 연동)
- 모니터링 알림은 시스템 운영상 필수이므로, 개인 알림 설정(유형별 켜기/끄기)과 무관하게 항상 발송된다

**[BR-MON-004] 정상 복귀 알림**
- 임계치를 초과했던 지표가 정상 범위로 복귀하면 "정상 복귀" 알림을 발송한다

**[BR-MON-005] 반복 알림 방지 (쿨다운)**
- 동일 지표가 임계치를 반복 초과하는 경우, 설정된 반복 알림 방지 기간(기본 5분) 동안 반복 알림을 억제한다
- 억제 기간 동안 추가 발생한 건은 "N건 추가 발생" 요약 알림으로 묶어 발송한다

**[BR-MON-006] 과다 알림 자동 억제**
- 설정된 시간(기본 10분) 내에 동일 지표에서 알림이 기준 횟수(기본 10건)를 초과하면, 해당 지표의 알림을 일시 억제한다
- "임계치 재검토 필요" 안내 알림을 발송하고, 해당 지표의 최근 추이 데이터를 함께 제공한다
- 관리자가 임계치를 조정하면 알림 억제가 자동 해제된다

### 2.3 에스컬레이션

**[BR-MON-007] 에스컬레이션 규칙**
- 알림 발송 후 설정된 시간 이내에 조치가 이루어지지 않으면, 에스컬레이션 대상에게 재알림을 발송한다
- 지표 영역별로 서로 다른 에스컬레이션 대상(특정 사용자 또는 사용자 그룹)을 설정할 수 있다

**[BR-MON-008] 근무/비근무 시간대 에스컬레이션 분리**
- 관리자가 근무 시간대와 비근무 시간대(야간, 주말, 공휴일)의 에스컬레이션 대상을 각각 설정한다
- 비근무 시간대 에스컬레이션 대상이 미설정이면, 근무 시간대 대상에게 발송하고 "비근무 시간대 에스컬레이션 경로 미설정" 경고를 함께 표시한다

### 2.4 수동 조치

**[BR-MON-009] 수동 조치 종류**
- 캐시 초기화
- 큐 재처리 (실패 건 재시도)
- 작업 처리기 수 현재 값 확인 및 시스템 운영 설정(ADM-15) 바로가기

**[BR-MON-010] 수동 조치 실행 규칙**
- 모든 수동 조치는 확인 대화 상자(confirm dialog)를 거쳐야 실행된다
- 조치 실행 결과(성공/실패/에러 메시지)를 즉시 표시한다
- 조치 실행 전후의 관련 지표 변화를 비교하여 표시한다
- 수동 조치 실행 시 감사 로그에 기록된다 (실행자, 조치 유형, 실행 시각, 결과)

**[BR-MON-011] 동시 조치 충돌 방지**
- 두 명 이상의 관리자가 동일한 수동 조치를 동시에 실행하려 하면, 먼저 실행한 관리자의 조치만 수행한다
- 나머지 관리자에게 "다른 관리자가 이미 해당 조치를 실행 중입니다" 안내를 표시한다

### 2.5 자동 조치 규칙

**[BR-MON-012] 자동 조치 실행 규칙**
- 관리자가 지표별 자동 조치 규칙을 등록한다 (예: "큐 실패 건수 100건 초과 시 → 자동 큐 재처리")
- 임계치를 초과하면 등록된 자동 조치를 실행하고, 실행 결과를 관리자에게 알림으로 통보한다
- 자동 조치가 실패하면 즉시 관리자에게 "자동 조치 실패 — 수동 대응 필요" 알림을 발송한다
- 자동 조치 실행 이력은 감사 로그에 "자동 실행"으로 구분하여 기록된다
- 관리자가 명시적으로 등록한 조치만 실행되며, 시스템이 임의로 조치를 수행하지 않는다

### 2.6 유지보수 모드

**[BR-MON-013] 유지보수 모드 동작**
- 유지보수 모드 활성화 시 알림 발송을 일시 중지한다
- 유지보수 기간 동안 모니터링 데이터 수집은 계속된다
- 임계치 초과 발생 시 알림을 발송하지 않으며, 해당 이벤트는 "유지보수 중 발생"으로 별도 기록한다

**[BR-MON-014] 유지보수 모드 전환 절차**
- 진입: 관리자가 예정 시작 시각, 예정 종료 시각, 점검 사유를 입력한다
- 사전 안내: 시작 N분 전(설정 가능)부터 사용자에게 사전 안내를 표시한다
- 점검 중: 대시보드에 "유지보수 중" 표시, 사용자 화면에 점검 안내 표시
- 해제: 예정 종료 시각에 자동 해제하거나, 관리자가 수동으로 조기 해제할 수 있다
- 사후 요약: 해제 시 유지보수 기간 중 누적된 이상 징후를 요약 알림으로 발송한다

**[BR-MON-015] 유지보수 모드 연동**
- 유지보수 모드 중 승인 SLA 타이머가 자동 일시 정지된다
- AI 검색 데이터 변환 작업 등록도 일시 중지된다
- 해제 시 모두 자동 재개된다

### 2.7 데이터 수집 및 보관

**[BR-MON-016] 수집 주기**
- 모니터링 데이터는 기본 30초 주기로 수집한다
- 수집 주기는 시스템 설정에서 조정할 수 있다
- 대시보드는 수집 주기와 동일한 간격으로 자동 갱신된다

**[BR-MON-017] 시계열 데이터 해상도 및 보관**
- 시계열 데이터 보관 기간: 기본 90일 (시스템 설정에서 조정 가능)
- 조회 기간에 따라 데이터 해상도가 자동 조정된다:
  - 7일 이내: 분 단위
  - 7~30일: 시간 단위
  - 30일 초과: 일 단위

### 2.8 복수 서비스 동시 장애

**[BR-MON-018] 동시 장애 알림**
- 여러 서비스에서 동시에 장애가 발생하면, "복수 서비스 장애 발생" 종합 알림을 먼저 발송한다
- 종합 알림에 장애 서비스 목록과 각 서비스의 심각도(위험/경고)를 포함한다
- 개별 서비스별 상세 알림은 심각도 높은 순서대로 발송한다

### 2.9 장애 사후 분석

**[BR-MON-019] 포스트모템 보고서 자동 채움**
- 장애 복구 후 사후 분석 보고서 작성 시, 시스템이 해당 장애의 타임라인(감지 시각, 알림 시각, 조치 시각, 복구 시각), 영향 범위(영향받은 서비스, 영향받은 사용자 수 추정치), 수행된 조치 이력을 자동으로 채워 넣는다
- 장애 감지 소요 시간(MTTD)과 복구 소요 시간(MTTR)을 자동 산출하여 보고서에 포함한다

**[BR-MON-020] 후속 조치 추적**
- 포스트모템 보고서의 후속 조치 항목에 대해 이행 여부를 추적한다
- 기한이 도래하면 담당자에게 리마인더가 발송되며, 미이행 항목은 관리자에게 알림이 간다

### 2.10 용량 계획

**[BR-MON-021] 용량 예측**
- 파일 스토리지, DB, AI 검색용 데이터 저장소, 동시접속자 수, AI 서비스 비용의 장기 추세(30일/90일/180일)를 분석한다
- 각 지표의 예상 소진 시점 또는 예산 초과 시점을 자동 산출한다
- 예상 소진 시점이 설정된 기간(기본 30일) 이내이면, 사전 알림을 발송한다

### 2.11 대시보드

**[BR-MON-022] 대시보드 개인화**
- 관리자가 관심 지표의 배치·크기·표시 항목을 조정하여 개인별 레이아웃으로 저장한다
- 저장 전 대시보드를 벗어나면 "저장하지 않은 변경이 있습니다" 확인을 표시한다

**[BR-MON-023] 대시보드 공유 및 프리셋**
- 관리자가 개인 레이아웃을 "팀 공유 레이아웃"으로 게시하면, 다른 관리자가 가져와 적용할 수 있다
- 역할별(예: 검색 담당, 보안 담당, 전체 운영) 기본 대시보드 프리셋을 등록할 수 있다
- 신규 관리자가 처음 접근하면 해당 역할의 프리셋이 기본 레이아웃으로 적용된다
- 공유 레이아웃에 포함된 지표 중 접근 권한이 없는 항목은 "권한 없음"으로 표시된다

### 2.12 교대 근무 인수인계

**[BR-MON-024] 인수인계 규칙**
- 퇴근하는 관리자가 인수인계 메모(현재 주의 지표, 진행 중인 조치, 미해결 알림 등)를 작성한다
- 시스템이 최근 근무 시간 동안 발생한 알림·조치·미확인 이벤트를 자동 요약하여 인수인계 메모에 첨부한다
- 인계받는 관리자가 인수 확인을 처리하면 인수인계 기록이 이력으로 보관된다

### 2.13 장애 시 사용자 안내

**[BR-MON-025] 장애 안내 발송**
- 서비스 헬스가 `critical` 상태에 진입하면, 관리자가 사전에 등록한 장애 유형별 사용자 안내 메시지를 자동 또는 수동으로 발송할 수 있다

**[BR-MON-026] 비필수 기능 일시 제한**
- 동시접속자 수가 설정된 임계치를 초과하면, 관리자가 비필수 기능(통계 집계, AI 답변 생성 등)을 일시적으로 제한하여 핵심 기능(문서 조회, 검색)의 응답 성능을 보호할 수 있다

---

## 3. 데이터 모델

### 3.1 HealthCheckResult 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 헬스 체크 결과 고유 식별자 |
| `service_name` | VARCHAR(100) | NOT NULL | 서비스 이름 (API, SearchEngine, AIService, QueueSystem, Database) |
| `status` | VARCHAR + CHECK | NOT NULL | `'healthy'` \| `'warning'` \| `'critical'` \| `'unreachable'` |
| `response_time_ms` | INTEGER | NULL | 응답 시간 (ms) |
| `error_rate` | DECIMAL(5,2) | NULL | 에러율 (%) |
| `details` | JSONB | NULL | 서비스별 상세 지표 (큐 건수, 스토리지 사용량 등) |
| `checked_at` | TIMESTAMP | NOT NULL | 체크 시점 |

### 3.2 AlertRule 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 알림 규칙 고유 식별자 |
| `metric_key` | VARCHAR(100) | NOT NULL | 대상 지표 키 (예: `api.response_time`, `queue.embedding.failed`) |
| `warning_threshold` | DECIMAL | NOT NULL | 경고 임계치 |
| `critical_threshold` | DECIMAL | NOT NULL | 위험 임계치 |
| `comparison_operator` | VARCHAR + CHECK | NOT NULL | `'gt'` (초과) \| `'lt'` (미만) \| `'gte'` \| `'lte'` |
| `cooldown_seconds` | INTEGER | NOT NULL, DEFAULT 300 | 반복 알림 방지 기간 (초) |
| `notification_channels` | JSONB | NOT NULL | 알림 채널 설정 (`{ inApp: true, email: true, messenger: true }`) |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | 활성 여부 |
| `created_by` | UUID | FK(User), NOT NULL | 생성자 |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

### 3.3 AlertHistory 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 알림 이력 고유 식별자 |
| `alert_rule_id` | UUID | FK(AlertRule), NOT NULL | 발생 규칙 |
| `metric_key` | VARCHAR(100) | NOT NULL | 대상 지표 키 |
| `metric_value` | DECIMAL | NOT NULL | 발생 시점 지표 값 |
| `severity` | VARCHAR + CHECK | NOT NULL | `'warning'` \| `'critical'` |
| `status` | VARCHAR + CHECK | NOT NULL | `'triggered'` \| `'acknowledged'` \| `'resolved'` |
| `triggered_at` | TIMESTAMP | NOT NULL | 발생 시각 |
| `acknowledged_at` | TIMESTAMP | NULL | 확인 시각 |
| `acknowledged_by` | UUID | FK(User), NULL | 확인자 |
| `resolved_at` | TIMESTAMP | NULL | 복구 시각 |
| `during_maintenance` | BOOLEAN | NOT NULL, DEFAULT false | 유지보수 중 발생 여부 |

### 3.4 EscalationConfig 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 에스컬레이션 설정 고유 식별자 |
| `metric_area` | VARCHAR(50) | NOT NULL | 지표 영역 (serviceHealth, queue, storage, ai, concurrency) |
| `escalation_timeout_minutes` | INTEGER | NOT NULL, DEFAULT 15 | 미조치 시 에스컬레이션 대기 시간 (분) |
| `working_hours_targets` | JSONB | NOT NULL | 근무 시간대 에스컬레이션 대상 (사용자/그룹 ID 배열) |
| `off_hours_targets` | JSONB | NULL | 비근무 시간대 에스컬레이션 대상 (미설정 시 근무 시간대 대상 사용) |
| `created_by` | UUID | FK(User), NOT NULL | 생성자 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

### 3.5 AutoActionRule 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 자동 조치 규칙 고유 식별자 |
| `alert_rule_id` | UUID | FK(AlertRule), NOT NULL | 연결된 알림 규칙 |
| `action_type` | VARCHAR + CHECK | NOT NULL | `'cache_clear'` \| `'queue_retry'` |
| `action_params` | JSONB | NULL | 조치 파라미터 |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | 활성 여부 |
| `created_by` | UUID | FK(User), NOT NULL | 생성자 |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

### 3.6 MaintenanceWindow 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 유지보수 창 고유 식별자 |
| `scheduled_start` | TIMESTAMP | NOT NULL | 예정 시작 시각 |
| `scheduled_end` | TIMESTAMP | NOT NULL | 예정 종료 시각 |
| `actual_start` | TIMESTAMP | NULL | 실제 시작 시각 |
| `actual_end` | TIMESTAMP | NULL | 실제 종료 시각 |
| `reason` | TEXT | NOT NULL | 점검 사유 |
| `status` | VARCHAR + CHECK | NOT NULL | `'scheduled'` \| `'active'` \| `'completed'` \| `'cancelled'` |
| `pre_notice_minutes` | INTEGER | NOT NULL, DEFAULT 30 | 사전 안내 시작 시점 (시작 N분 전) |
| `user_notice_message` | TEXT | NULL | 사용자에게 표시할 점검 안내 메시지 |
| `post_summary` | JSONB | NULL | 유지보수 중 누적된 이상 징후 요약 |
| `created_by` | UUID | FK(User), NOT NULL | 생성자 |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |

### 3.7 DashboardLayout 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 레이아웃 고유 식별자 |
| `owner_id` | UUID | FK(User), NOT NULL | 소유자 |
| `name` | VARCHAR(200) | NOT NULL | 레이아웃 이름 |
| `layout_config` | JSONB | NOT NULL | 위젯 배치·크기·표시 항목 설정 |
| `is_shared` | BOOLEAN | NOT NULL, DEFAULT false | 팀 공유 여부 |
| `is_preset` | BOOLEAN | NOT NULL, DEFAULT false | 역할별 프리셋 여부 |
| `preset_role` | VARCHAR(50) | NULL | 프리셋 대상 역할 (is_preset=true일 때) |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

### 3.8 PostmortemReport 엔티티

> `incident_id`는 장애 인시던트를 식별하는 값이다. 별도 `Incident` 엔티티를 두지 않고, **`AlertHistory`에서 동일 장애로 그룹핑된 첫 번째 알림의 ID**를 인시던트 식별자로 사용한다. 동시다발 장애(BR-MON-018)의 경우 종합 알림 `AlertHistory.id`가 `incident_id`가 된다. 향후 별도 `Incident` 엔티티가 필요하면 마이그레이션으로 FK를 추가한다.

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 보고서 고유 식별자 |
| `incident_id` | UUID | NOT NULL | 관련 장애 ID — `AlertHistory.id` (동일 장애의 첫 번째 알림 또는 종합 알림) |
| `timeline` | JSONB | NOT NULL | 장애 타임라인 (감지·알림·조치·복구 시각) — 시스템 자동 채움 |
| `affected_services` | VARCHAR[] | NOT NULL | 영향받은 서비스 목록 |
| `estimated_affected_users` | INTEGER | NULL | 영향받은 사용자 수 추정치 |
| `mttd_seconds` | INTEGER | NULL | 장애 감지 소요 시간 (자동 산출) |
| `mttr_seconds` | INTEGER | NULL | 복구 소요 시간 (자동 산출) |
| `summary` | TEXT | NULL | 장애 요약 (관리자 기입) |
| `root_cause` | TEXT | NULL | 근본 원인 (관리자 기입) |
| `response_evaluation` | TEXT | NULL | 대응 과정 평가 (관리자 기입) |
| `prevention_measures` | TEXT | NULL | 재발 방지 대책 (관리자 기입) |
| `follow_up_items` | JSONB | NULL | 후속 조치 항목 (`[{ description, assigneeId, dueDate, status }]`) |
| `created_by` | UUID | FK(User), NOT NULL | 작성자 |
| `created_at` | TIMESTAMP | NOT NULL | 작성일시 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

### 3.9 HandoverRecord 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 인수인계 기록 고유 식별자 |
| `from_user_id` | UUID | FK(User), NOT NULL | 인계자 |
| `to_user_id` | UUID | FK(User), NULL | 인수자 (인수 확인 전 NULL) |
| `memo` | TEXT | NOT NULL | 인수인계 메모 |
| `auto_summary` | JSONB | NOT NULL | 시스템 자동 요약 (최근 알림·조치·미확인 이벤트) |
| `acknowledged_at` | TIMESTAMP | NULL | 인수 확인 시각 |
| `shift_start` | TIMESTAMP | NOT NULL | 근무 시작 시각 |
| `shift_end` | TIMESTAMP | NOT NULL | 근무 종료 시각 |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |

### 3.10 RunbookLink 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 대응 절차서 링크 고유 식별자 |
| `metric_area` | VARCHAR(50) | NOT NULL | 지표 영역 |
| `severity` | VARCHAR + CHECK | NOT NULL | `'warning'` \| `'critical'` \| `'emergency'` |
| `runbook_url` | TEXT | NOT NULL | 대응 절차서 링크 |
| `description` | VARCHAR(500) | NULL | 절차서 설명 |
| `created_by` | UUID | FK(User), NOT NULL | 등록자 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

### 3.11 EmergencyContact 엔티티

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 비상 연락처 고유 식별자 |
| `name` | VARCHAR(100) | NOT NULL | 이름 |
| `contact_info` | VARCHAR(200) | NOT NULL | 연락처 |
| `responsible_area` | VARCHAR(100) | NOT NULL | 담당 영역 |
| `severity_level` | VARCHAR + CHECK | NOT NULL | 대응 장애 등급 (`'warning'` \| `'critical'` \| `'emergency'`) |
| `is_working_hours` | BOOLEAN | NOT NULL | 근무 시간대 담당 여부 |
| `is_off_hours` | BOOLEAN | NOT NULL | 비근무 시간대 담당 여부 |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | 활성 여부 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

---

## 4. 상태 정의

### 4.1 서비스 상태 모델

```
[서비스 가동 상태 (HealthCheckResult.status)]

정상 판정 흐름:
- healthy: 모든 지표가 정상 범위 이내
- warning: 1개 이상 지표가 경고 임계치 초과, 위험 임계치 미만
- critical: 1개 이상 지표가 위험 임계치 초과
- unreachable: 서비스에 연결할 수 없음 (데이터 수집 불가)

상태 전이:
- healthy → warning: 경고 임계치 초과 시
- warning → critical: 위험 임계치 초과 시
- warning → healthy: 지표가 정상 범위로 복귀 시
- critical → warning: 위험 → 경고 범위로 복귀 시
- critical → healthy: 모든 지표 정상 복귀 시
- * → unreachable: 서비스 연결 실패 시
- unreachable → healthy/warning/critical: 연결 복구 후 지표 재판정
```

### 4.2 알림 상태 모델

```
[알림 상태 (AlertHistory.status)]

- triggered: 알림 발생 (임계치 초과 감지)
- acknowledged: 관리자가 알림을 확인함
- resolved: 지표가 정상 복귀하여 장애 해소됨

전이:
- triggered → acknowledged: 관리자가 알림 확인 시
- triggered → resolved: 관리자 확인 없이 자동 복구 시
- acknowledged → resolved: 장애 복구 시
```

### 4.3 유지보수 창 상태 모델

```
[유지보수 상태 (MaintenanceWindow.status)]

- scheduled: 예약됨 (아직 시작 전)
- active: 유지보수 진행 중
- completed: 유지보수 완료
- cancelled: 유지보수 취소됨

전이:
- scheduled → active: 예정 시각 도래 또는 관리자 수동 진입
- scheduled → cancelled: 관리자가 예약 취소
- active → completed: 예정 종료 시각 도래 또는 관리자 수동 해제
```

---

## 5. 설정 가능 항목

> 아래 설정 항목은 FD-SYS 시스템 설정 카테고리에 모니터링 카테고리(`monitoring`)로 등록되어야 한다.

| 설정 항목 | 필드명 | 타입 | 기본값 | 설명 |
|-----------|--------|------|--------|------|
| 데이터 수집 주기 | `pm:monitoring.collection_interval_seconds` | integer | 30 | 모니터링 데이터 수집 간격 (초) |
| 시계열 보관 기간 | `pm:monitoring.timeseries_retention_days` | integer | 90 | 시계열 데이터 보관 기간 (일) |
| 반복 알림 방지 기간 | `pm:monitoring.alert_cooldown_seconds` | integer | 300 | 동일 지표 반복 알림 억제 기간 (초) |
| 과다 알림 판정 시간 | `pm:monitoring.excessive_alert_window_minutes` | integer | 10 | 과다 알림 판정 시간 창 (분) |
| 과다 알림 판정 횟수 | `pm:monitoring.excessive_alert_threshold` | integer | 10 | 과다 알림 판정 기준 횟수 |
| 사전 안내 시작 시점 | `pm:monitoring.maintenance_pre_notice_minutes` | integer | 30 | 유지보수 사전 안내 시작 (시작 N분 전) |
| 이력 조회 최대 기간 | `pm:monitoring.max_history_days` | integer | 90 | 시계열 이력 최대 조회 가능 기간 (일) |
| 알림 보관 기간 | `pm:monitoring.alert_retention_days` | integer | 365 | 알림 이력 보관 기간 (일) |
| 용량 예측 사전 알림 기간 | `pm:monitoring.capacity_warning_days` | integer | 30 | 예상 소진 시점이 N일 이내일 때 사전 알림 (일) |
| 비상 연락 체계 검토 주기 | `pm:monitoring.emergency_contact_review_days` | integer | 90 | 비상 연락 체계 검토 알림 주기 (일, 분기 1회) |

---

## 6. API 개요

> 주요 REST 엔드포인트와 요청/응답 형태를 정의한다. 상세 필드·유효성 규칙은 모듈 스펙에서 확정한다.

| 메서드 | 경로 | 요청/파라미터 | 응답 | 설명 |
|--------|------|--------------|------|------|
| GET | `/api/admin/monitoring/health` | — | `HealthDashboardResponse` | 전체 서비스 헬스 현황 (SSE 스트림 지원) |
| GET | `/api/admin/monitoring/health/{serviceName}` | `from`, `to` | `ServiceHealthDetailResponse` | 개별 서비스 상세 지표·시계열 |
| GET | `/api/admin/monitoring/alert-rules` | `page`, `size`, `metricArea` | `Page<AlertRuleResponse>` | 알림 규칙 목록 조회 |
| POST | `/api/admin/monitoring/alert-rules` | `CreateAlertRuleRequest` | `AlertRuleResponse` | 알림 규칙 생성 |
| PUT | `/api/admin/monitoring/alert-rules/{id}` | `UpdateAlertRuleRequest` | `AlertRuleResponse` | 알림 규칙 수정 |
| DELETE | `/api/admin/monitoring/alert-rules/{id}` | — | 204 | 알림 규칙 삭제 |
| GET | `/api/admin/monitoring/alerts` | `page`, `size`, `severity`, `status` | `Page<AlertHistoryResponse>` | 알림 이력 조회 |
| PATCH | `/api/admin/monitoring/alerts/{id}/acknowledge` | — | `AlertHistoryResponse` | 알림 확인 처리 |
| GET | `/api/admin/monitoring/dashboard-layouts` | — | `DashboardLayoutResponse[]` | 개인/공유 대시보드 레이아웃 목록 |
| PUT | `/api/admin/monitoring/dashboard-layouts/{id}` | `UpdateDashboardLayoutRequest` | `DashboardLayoutResponse` | 대시보드 레이아웃 저장 |
| POST | `/api/admin/monitoring/maintenance-windows` | `CreateMaintenanceRequest` | `MaintenanceWindowResponse` | 유지보수 창 예약 |
| PATCH | `/api/admin/monitoring/maintenance-windows/{id}/end` | — | `MaintenanceWindowResponse` | 유지보수 조기 종료 |
| POST | `/api/admin/monitoring/actions/{actionType}` | `ManualActionRequest` | `ManualActionResultResponse` | 수동 조치 실행 (캐시 초기화, 큐 재처리) |
| GET | `/api/admin/monitoring/postmortem/{id}` | — | `PostmortemReportResponse` | 포스트모템 보고서 조회 |
| GET | `/api/admin/monitoring/capacity` | `metricKey`, `period` | `CapacityForecastResponse` | 용량 예측 조회 |

**자동 조치 규칙 관리 API**:

| 메서드 | 경로 | 요청/파라미터 | 응답 | 설명 |
|--------|------|--------------|------|------|
| GET | `/api/admin/monitoring/auto-action-rules` | `page`, `size`, `is_active` | `Page<AutoActionRuleResponse>` | 자동 조치 규칙 목록 조회 |
| POST | `/api/admin/monitoring/auto-action-rules` | `CreateAutoActionRuleRequest` | `AutoActionRuleResponse` | 자동 조치 규칙 생성 |
| PUT | `/api/admin/monitoring/auto-action-rules/{id}` | `UpdateAutoActionRuleRequest` | `AutoActionRuleResponse` | 자동 조치 규칙 수정 |
| DELETE | `/api/admin/monitoring/auto-action-rules/{id}` | — | 204 | 자동 조치 규칙 삭제 |

```
[CreateAutoActionRuleRequest]
- alertRuleId: UUID — 연결할 알림 규칙 ID
- actionType: ENUM('cache_clear', 'queue_retry') — 조치 유형
- actionParams: JSONB, NULL — 조치 파라미터 (예: { queueName: 'embedding' })
- isActive: BOOLEAN, DEFAULT true — 활성 여부

[AutoActionRuleResponse]
- id: UUID — 규칙 ID
- alertRuleId: UUID — 연결된 알림 규칙 ID
- alertRuleMetricKey: VARCHAR — 연결된 알림 규칙의 지표 키
- actionType: ENUM('cache_clear', 'queue_retry')
- actionParams: JSONB
- isActive: BOOLEAN
- lastExecutedAt: TIMESTAMP, NULL — 마지막 실행 시각
- lastExecutionResult: ENUM('success', 'failed'), NULL — 마지막 실행 결과
- createdBy: UUID
- createdAt: TIMESTAMP
- updatedAt: TIMESTAMP
```

**주요 요청/응답 DTO**:

```
[HealthDashboardResponse]
- overallStatus: ENUM('healthy', 'warning', 'critical', 'unreachable') — 전체 시스템 상태 (BR-MON-002)
- services: ServiceHealthSummary[] — 개별 서비스 상태 목록
- lastCollectedAt: TIMESTAMP — 마지막 수집 시각

[ServiceHealthSummary]
- serviceName: VARCHAR(100) — 서비스 이름
- status: ENUM('healthy', 'warning', 'critical', 'unreachable')
- responseTimeMs: INTEGER, NULL — 응답 시간
- errorRate: DECIMAL(5,2), NULL — 에러율

[CreateMaintenanceRequest]
- scheduledStart: TIMESTAMP — 예정 시작 시각
- scheduledEnd: TIMESTAMP — 예정 종료 시각
- reason: TEXT — 점검 사유
- preNoticeMinutes: INTEGER, DEFAULT 30 — 사전 안내 시작 시점
- userNoticeMessage: TEXT, NULL — 사용자 안내 메시지
```

---

## 7. 에러 코드

| 에러 코드 | HTTP | 트리거 | 사용자 메시지 |
|-----------|------|--------|-------------|
| `MON_FORBIDDEN` | 403 | 시스템 모니터링 권한 미보유 | 시스템 모니터링 권한이 없습니다 |
| `MON_SERVICE_UNREACHABLE` | 503 | 모니터링 대상 서비스 연결 실패 | 모니터링 데이터를 가져올 수 없습니다 |
| `MON_DATA_STALE` | 200 | 수집 주기 초과하여 데이터 미갱신 (경고, 정상 응답) | 데이터 갱신이 지연되고 있습니다. 마지막 수집: {timestamp} |
| `MON_ACTION_CONFLICT` | 409 | 다른 관리자가 동일 조치 실행 중 | 다른 관리자가 이미 해당 조치를 실행 중입니다 |
| `MON_ACTION_FAILED` | 500 | 수동/자동 조치 실행 실패 | 조치 실행에 실패했습니다: {reason} |
| `MON_ALERT_CHANNEL_FAILURE` | 200 | 알림 채널(이메일/메신저) 장애 (경고, 인앱 대체 발송) | 알림 채널 장애 — 인앱 알림으로 대체 발송됨 |
| `MON_ESCALATION_TARGET_MISSING` | 200 | 에스컬레이션 대상 미설정/비활성 (경고, 전체 관리자 발송) | 에스컬레이션 대상이 설정되지 않았습니다 |
| `MON_MAINTENANCE_OVERLAP` | 409 | 기존 유지보수 기간과 겹치는 예약 시도 | 해당 시간대에 이미 유지보수가 예약되어 있습니다 |
| `MON_THRESHOLD_INVALID` | 422 | 경고 임계치가 위험 임계치보다 큰 값 설정 시도 | 경고 임계치는 위험 임계치보다 작아야 합니다 |
| `MON_AUTO_ACTION_FAILED` | 200 | 자동 조치 실행 실패 (경고, 수동 대응 유도) | 자동 조치가 실패했습니다 — 수동 대응이 필요합니다 |

### 7.1 BR↔에러 코드 매핑

| BR-ID | 에러/경고 | HTTP | 코드 | 비고 |
|-------|----------|------|------|------|
| BR-MON-001 | — | — | — | 3단계 판정 — `HealthCheckResult.status` 필드에 반영 |
| BR-MON-002 | — | — | — | 복합 상태 산출 — 응답 `overallStatus`에 반영 |
| BR-MON-003 | — | — | — | 알림 발송 — NTF 모듈 연동, 채널 장애 시 `MON_ALERT_CHANNEL_FAILURE` |
| BR-MON-005 | — | — | — | 쿨다운 — 내부 알림 억제 로직, 별도 에러 없음 |
| BR-MON-006 | 경고 | 200 | — | 과다 알림 시 "임계치 재검토 필요" 안내 발송 |
| BR-MON-009~010 | 에러 | 500 | `MON_ACTION_FAILED` | 수동 조치 실패 |
| BR-MON-011 | 에러 | 409 | `MON_ACTION_CONFLICT` | 동시 조치 충돌 |
| BR-MON-012 | 경고 | 200 | `MON_AUTO_ACTION_FAILED` | 자동 조치 실패 → 수동 대응 유도 |
| BR-MON-013~014 | 에러 | 409 | `MON_MAINTENANCE_OVERLAP` | 유지보수 기간 겹침 |
| BR-MON-016 | 경고 | 200 | `MON_DATA_STALE` | 수집 주기 초과 시 데이터 미갱신 안내 |
| — | 에러 | 403 | `MON_FORBIDDEN` | 모니터링 권한 미보유 |
| — | 에러 | 503 | `MON_SERVICE_UNREACHABLE` | 대상 서비스 연결 실패 |
| — | 에러 | 422 | `MON_THRESHOLD_INVALID` | 경고 임계치 ≥ 위험 임계치 |
| — | 경고 | 200 | `MON_ESCALATION_TARGET_MISSING` | 에스컬레이션 대상 미설정 |

> 감사 로그 기록 실패는 AUD 모듈 에러 코드로 처리한다. 모니터링 모듈은 감사 이벤트를 비동기로 발행만 한다.

---

## 8. 도메인 이벤트

이 모듈이 **발행**하는 도메인 이벤트 목록이다. 이벤트 계약은 발행측(monitoring 모듈)에서 정의한다.

| 이벤트명 | 트리거 | 페이로드 주요 필드 | 소비자 |
|----------|--------|-------------------|--------|
| `monitoring.alert.triggered` | 임계치 초과 알림 발생 | `{ alertRuleId, metricKey, metricValue, severity, triggeredAt }` | NTF, AUD |
| `monitoring.alert.resolved` | 장애 복구 (정상 복귀) | `{ alertHistoryId, metricKey, resolvedAt, mttdSeconds, mttrSeconds }` | NTF, AUD |
| `monitoring.escalation.triggered` | 미조치 에스컬레이션 발생 | `{ alertHistoryId, escalationTargets, timeoutMinutes }` | NTF |
| `monitoring.auto-action.executed` | 자동 조치 실행 | `{ autoActionRuleId, actionType, result, executedAt }` | AUD |
| `monitoring.auto-action.failed` | 자동 조치 실패 | `{ autoActionRuleId, actionType, failureReason, executedAt }` | NTF, AUD |
| `monitoring.maintenance.started` | 유지보수 모드 시작 | `{ maintenanceId, scheduledEnd, reason }` | NTF, APR (SLA 일시정지) |
| `monitoring.maintenance.ended` | 유지보수 모드 종료 | `{ maintenanceId, postSummary }` | NTF, APR (SLA 재개) |
| `monitoring.manual-action.executed` | 수동 조치 실행 | `{ actionType, executedBy, result, executedAt }` | AUD |
| `monitoring.capacity.warning` | 용량 소진 사전 경고 | `{ metricKey, currentUsage, estimatedExhaustionDate }` | NTF |
| `monitoring.service.status-changed` | 서비스 상태 변경 | `{ serviceName, previousStatus, newStatus, changedAt }` | NTF |

**전달 보장**: at-least-once. 소비 모듈(NTF, AUD, APR)은 멱등 처리를 보장해야 한다. 재시도·DLQ 정책은 각 소비 모듈 스펙을 따른다.

---

## 9. 비기능 요구사항

| 항목 | 요구사항 | 근거 |
|------|----------|------|
| 데이터 수집 주기 | 기본 30초 (설정 가능) | UC-ADM-18 제약 사항 |
| 대시보드 갱신 주기 | 수집 주기와 동일 (기본 30초), SSE 기반 실시간 푸시 | T6 설계 결정 (SSE 활용) |
| 대시보드 초기 로딩 | 3초 이내 | 운영자 즉각 대응 요구 |
| 알림 발송 지연 | 임계치 초과 감지 후 5초 이내 | 장애 선제 대응 (MTTD 단축) |
| 수동 조치 응답 | 10초 이내 (캐시 초기화, 큐 재처리) | 운영 조치 즉시성 |
| 시계열 데이터 보관 | 기본 90일 (설정 가능) | 장기 트렌드 분석 지원 |
| 알림 이력 보관 | 기본 1년 (설정 가능) | 감사 요건 |
| 모니터링 서비스 자체 가용성 | 모니터링 대상 서비스 장애 시에도 모니터링 서비스는 독립적으로 동작 | 모니터링 서비스가 모니터링 대상에 의존하지 않도록 설계 |
| 감사 로그 기록 방식 | 비동기 처리 (T3 설계 결정) | 모니터링 대시보드 응답 지연 방지 |
| 설정 변경 반영 | 캐시 + 이벤트 무효화 (T4 설계 결정) | 서비스 재시작 없이 설정 반영 |

---

## 10. 런북 연동

### 10.1 대응 절차서 연동 규칙

- 지표 영역별, 장애 등급별(`warning`/`critical`/`emergency`)로 대응 절차서 링크를 등록한다
- 알림이 발생하면, 시스템이 장애 등급을 자동 판정하고 해당 등급의 대응 절차서 링크를 알림 메시지에 포함한다
- 대응 절차서에 체크리스트가 포함된 경우, 관리자가 각 단계를 체크하며 진행할 수 있고, 체크 이력이 장애 이력에 함께 기록된다
- 절차서 미등록 상태에서 알림이 발생하면, "대응 절차서가 등록되지 않았습니다" 경고를 함께 표시한다

---

## 11. 장기 트렌드 보고서

### 11.1 보고서 생성 규칙

- 관리자가 보고서 기간(주간/월간)과 포함할 지표를 선택한다
- 시스템이 해당 기간의 서비스 가용률, 장애 횟수, 평균 복구 시간(MTTR), 용량 추이, AI 서비스 비용, 동시접속 피크 등을 자동 집계한다
- 직전 기간 대비 변동 추이(개선/악화)를 시각화하여 표시한다
- 보고서를 표 형식 파일(CSV) 또는 문서 형식으로 내보낼 수 있다
- 자동 생성 스케줄을 설정하면, 설정된 주기마다 보고서를 자동 생성하여 지정 수신자에게 전달한다

---

## 결정 사항

| 항목 | 결정 | 근거 |
|------|------|------|
| FD-ADM에서 분리 | FD-MON으로 별도 기능정의서 생성 (B2) | UC-ADM-18의 서비스 헬스/큐/스토리지/AI 등 독립 도메인 성격. FD-ADM 허브 취지와 일관 |
| 감사 로그 기록 방식 | 비동기 처리 (T3) | 모니터링 대시보드 응답 지연 방지. 감사 이벤트는 큐를 통해 비동기 기록 |
| 설정 변경 반영 | 캐시 + 이벤트 무효화 (T4) | 임계치 등 설정 변경 시 관련 캐시를 이벤트로 무효화하여 서비스 재시작 없이 반영 |
| 대시보드 실시간 푸시 | SSE (T6) | 모니터링 대시보드에 서버→클라이언트 실시간 데이터 푸시. WebSocket 대비 구현 단순, 단방향 데이터 흐름에 적합 |
| 이벤트 발행 책임 | 발행측에서 정의 (B5) | monitoring 모듈이 발행하는 이벤트 계약을 이 문서에서 정의. 소비 모듈(NTF, AUD 등)은 구독만 |
| 큐 모니터링 범위 | 시스템 전체 큐 | AI 검색 데이터 변환 큐를 포함한 승인 처리, 알림 발송 등 전체 큐를 모니터링 대상으로 포함 |
| 인프라 모니터링 제외 | 애플리케이션 레벨만 | 서버 CPU, 메모리, 디스크 등 인프라 레벨은 외부 모니터링 도구 담당. 이 모듈은 애플리케이션 서비스 상태에 집중 |

---

## 미결 사항

| # | 사항 | 관련 |
|---|------|------|
| 1 | FD-NTF에 모니터링 알림 유형 등록 필요 (임계치 초과, 서비스 장애, 정상 복귀, 에스컬레이션, 알림 채널 장애, 자동 조치 결과, 용량 예측 사전 알림, 유지보수 모드 시작/종료, 과다 알림 경고) | FD-NTF |
| 2 | FD-SYS에 모니터링 설정 카테고리(`monitoring`) 등록 필요 — 수집 주기, 시계열 보관 기간, 임계치 기본값, 반복 알림 방지 기간, 유지보수 모드, 자동 조치 규칙, 에스컬레이션 시간대, 용량 예측 사전 알림 기간 등 | FD-SYS |
| 3 | 장애 패턴 분석에서 "예방 조치 제안" 기능의 상세 규칙 미정 — 규칙 기반 vs ML 기반 판단 필요 | UC-ADM-18 4e |

---

## 관련 문서

| 문서 | 참조 내용 |
|------|----------|
| [FD-ADM](FD-ADM-관리자.md) | 관리자 기능 목록 — §1.18 시스템 모니터링 (허브 참조) |
| [FD-SYS](FD-SYS-시스템설정.md) | 시스템 운영 파라미터 — 모니터링 관련 설정 항목 |
| [FD-NTF](FD-NTF-알림.md) | 알림 발송 (인앱 + 이메일 + 외부 메신저 연동) |
| [FD-AUD](FD-AUD-감사로그.md) | 수동 조치, 자동 조치, 설정 변경 감사 로그 |
| [FD-EMB](FD-EMB-임베딩파이프라인.md) | 임베딩 큐 모니터링 — §1.8 파이프라인 상태 관리 |
| [UC-ADM-시스템모니터링](../usecases/admin/UC-ADM-시스템모니터링.md) | 대응 유즈케이스 (UC-ADM-18) |
| [UC-ADM-시스템운영](../usecases/admin/UC-ADM-시스템운영.md) | ADM-15 시스템 운영 설정 — 임계치 설정·작업 처리기 수 변경 연계 |

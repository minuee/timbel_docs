# 시스템 설정 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-SYS |
| 버전 | 1.4 |
| 작성일 | 2026-03-31 |
| 기준 문서 | AICM 새 기능정의서 v1 §7, 권한 설계 |

---

## 1. 개요

시스템 설정은 AICM 서비스 전반의 **운영 파라미터**를 관리하는 기능이다. 파일 업로드 제한, 알림 기준일수, 인기 스코어 가중치, 감사 로그 보관 기간 등 운영 중 조정이 필요한 값들을 관리자 화면에서 변경할 수 있다.

AICM의 운영 파라미터는 **SystemConfig**로 통합 관리된다.

| 변경 주체 | 변경 시점 | 저장소 | 대상 |
|----------|----------|--------|------|
| `manage_system` 권한 보유자 | 운영 중 수시 | DB (`system_configs` 테이블) | 수치 제한(`lm:`), 튜닝 파라미터(`pm:`) |

**이 문서는 `manage_system` AdminPermission으로 관리하는 SystemConfig를 정의한다.**

---

## 2. 데이터 모델

### 2.1 SystemConfig 엔티티

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `uuid` (PK) | 시스템설정 ID |
| `config_key` | `string` (UNIQUE) | 설정 키 (`{scope}:{module}.{name}` 형식) |
| `category` | `string` | 카테고리 — UI 그룹핑 및 필터 용도 |
| `config_value` | `jsonb` | 설정값 (숫자, 문자열, 배열, 객체 모두 수용) |
| `value_type` | `enum` | `number` \| `string` \| `boolean` \| `object` \| `array` |
| `description` | `string` (nullable) | 관리자에게 표시되는 설명 |
| `updated_by` | `uuid` (FK → User, nullable) | 최종 변경자 (시딩 시 NULL) |
| `updated_at` | `timestamp` | 최종 변경 일시 |
| `created_at` | `timestamp` | 최초 생성(시딩) 일시 |

### 2.2 config_key 네이밍 규칙

```
{scope}:{module}.{name}
```

| 세그먼트 | 규칙 | 예시 |
|----------|------|------|
| **scope** | `lm` (제한값) 또는 `pm` (파라미터) | `lm:`, `pm:` |
| **module** | 소유 도메인 모듈명 (NestJS 모듈 디렉토리와 대응) | `system`, `document`, `audit` |
| **name** | snake_case, 2~4단어, 수치는 단위 포함 | `max_upload_bytes`, `retention_days` |

- 단위 접미어: `_bytes`, `_days`, `_hours`, `_seconds`, `_count`, `_percent`, `_ratio`, `_weight`

---

## 3. 설정 카테고리 및 항목

### 3.1 시스템 전역 (`system`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:system.max_upload_bytes` | `number` | `104857600` (100MB) | 파일 업로드 최대 크기 (bytes) |
| `lm:system.allowed_mime_types` | `string[]` | (별도 정의) | 허용 MIME 타입 목록 |

### 3.2 문서 (`document`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:document.max_tags` | `number` | `10` | 문서당 최대 태그 수 |
| `lm:document.autosave_interval_seconds` | `number` | `5` | 자동 저장 간격 (초) |
| `lm:document.draft_stale_days` | `number` | `30` | 드래프트 방치 알림 기준 일수 |
| `lm:document.max_blocks` | `number` | `300` | 문서당 최대 블록 수 |
| `lm:document.lock_timeout_minutes` | `number` | `30` | 편집 잠금 자동 해제 시간 (분) |

### 3.3 승인 (`approval`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:approval.bypass_reason_min_length` | `number` | `10` | 긴급 발행 사유 최소 글자수 |
| `lm:approval.stale_reminder_days` | `number` | `7` | 미처리 승인 리마인더 기준 일수 |

### 3.4 집계 (`aggregation`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `pm:aggregation.popular_weights` | `object` | `{view:1, like:3, comment:5}` | 인기 스코어 가중치 |
| `pm:aggregation.trending_threshold_percent` | `number` | `200` | 트렌딩 문서 판정 기준 증가율 (%) |
| `lm:aggregation.trending_min_views` | `number` | `10` | 트렌딩 대상 최소 조회수 |
| `lm:aggregation.trending_window_hours` | `number` | `168` | 트렌딩 시간 윈도우 (시간) — 7일 기본 |

### 3.5 감사 (`audit`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:audit.retention_days` | `number` | `365` | 감사 로그 보관 기간 (일) |
| `lm:audit.access_log_retention_days` | `number` | `180` | Access log ES 보관 기간 (일) |
| `lm:audit.access_log_flush_interval_sec` | `number` | `300` | Redis Stream → ES 플러시 주기 (초) |
| `lm:audit.access_count_flush_interval_sec` | `number` | `600` | Redis → PG 조회수 카운트 플러시 주기 (초) |

> **UC-ADM-15 용어 매핑**: [UC-ADM-15](../usecases/admin/UC-ADM-시스템운영.md#uc-adm-15-시스템-운영-설정-관리) 기본 흐름 표의 「감사 로그 활성 조회 기간」은 `lm:audit.retention_days`와 **동일 개념**이다 — 이 값이 FD-AUD §3.3의 "활성 조회 기간"에 해당하며, 기간 경과 후 아카이브로 이관된다.

### 3.6 내보내기 (`export`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `pm:export.watermark_text` | `string` | `'대외비'` | 워터마크 기본 텍스트 (PDF 전용) |
| `lm:export.async_threshold` | `number` | `100` | 이 블록 수 초과 시 비동기 처리로 전환 |
| `lm:export.file_ttl_hours` | `number` | `24` | 생성된 내보내기 파일의 스토리지 보관 시간 (시간) |
| `lm:export.max_file_size_mb` | `number` | `50` | 내보내기 결과 파일 최대 크기 (MB) |
| `lm:export.job_max_wait_minutes` | `number` | `30` | pending 상태 최대 대기 시간 (분) — 초과 시 자동 failed |


### 3.7 임베딩 파이프라인 (`embedding`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:embedding.worker_count` | `number` | `2` | 동시 처리 워커 수 |
| `lm:embedding.max_retry_count` | `number` | `3` | 실패 최대 재시도 횟수 |

### 3.8 검색 (`search`)

> **검색 튜닝 파라미터는 SystemConfig가 아닌 전용 엔티티(`SearchConfig`)로 관리한다.**
> 변경 주기·소비자·동기화 대상이 범용 Key-Value와 달라 분리되었다 — [FD-SCH](FD-SCH-검색.md) §6 참조.

### 3.9 파싱/청킹 (`parsing`)

> **파싱/청킹 파라미터는 SystemConfig가 아닌 전용 엔티티(`ParsingConfig`)로 관리한다.**
> 청크 사이즈·오버랩 등은 임베딩 파이프라인과 함께 변경되므로 분리되었다 — [FD-SCH](FD-SCH-검색.md) §3 참조.

### 3.10 커뮤니티 (`community`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:community.comment_max_length` | `number` | `2000` | 댓글 내용 최대 길이 |
| `lm:community.comment_edit_window_hours` | `number` | `24` | 등록 후 수정 가능 시간 (시간) |
| `lm:community.comment_rate_limit_seconds` | `number` | `10` | 동일 사용자 연속 댓글 최소 간격 (초) |
| `lm:community.unresolved_comment_reminder_days` | `number` | `7` | 미해결 상태 N일 초과 시 담당자 리마인더 |
| `lm:community.report_auto_hide_threshold` | `number` | `5` | 신고 N건 누적 시 자동 비공개 전환 |
| `lm:community.report_abuse_period_hours` | `number` | `24` | 신고 남용 판단 시간 윈도우 (시간) |
| `lm:community.report_abuse_max_count` | `number` | `20` | 판단 기간 내 최대 신고 건수 |
| `lm:community.bookmark_max_count` | `number` | `500` | 사용자당 최대 북마크 수 |
| `lm:community.bookmark_folder_max_count` | `number` | `20` | 사용자당 최대 북마크 폴더 수 |
| `lm:community.post_max_length` | `number` | `50000` | 자유게시판 게시글 최대 글자 수 |
| `lm:community.pinned_post_max_count` | `number` | `5` | 게시판당 공지 고정 최대 수 |

### 3.11 모니터링 (`monitoring`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `pm:monitoring.collection_interval_seconds` | `number` | `30` | 모니터링 데이터 수집 간격 (초) |
| `pm:monitoring.timeseries_retention_days` | `number` | `90` | 시계열 데이터 보관 기간 (일) |
| `pm:monitoring.alert_cooldown_seconds` | `number` | `300` | 동일 지표 반복 알림 억제 기간 (초) |
| `pm:monitoring.excessive_alert_window_minutes` | `number` | `10` | 과다 알림 판정 시간 창 (분) |
| `pm:monitoring.excessive_alert_threshold` | `number` | `10` | 과다 알림 판정 기준 횟수 |
| `pm:monitoring.maintenance_pre_notice_minutes` | `number` | `30` | 유지보수 사전 안내 시작 (시작 N분 전) |
| `pm:monitoring.max_history_days` | `number` | `90` | 시계열 이력 최대 조회 가능 기간 (일) |
| `pm:monitoring.alert_retention_days` | `number` | `365` | 알림 이력 보관 기간 (일) |
| `pm:monitoring.capacity_warning_days` | `number` | `30` | 예상 소진 시점이 N일 이내일 때 사전 알림 (일) |
| `pm:monitoring.emergency_contact_review_days` | `number` | `90` | 비상 연락 체계 검토 알림 주기 (일) |

### 3.12 AI (`ai`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `lm:ai.daily_quota` | `number` | `1000` | 조직 일일 AI 호출 횟수 제한 |
| `lm:ai.concurrent_requests` | `number` | `10` | 테넌트당 동시 AI 요청 수 제한 |
| `lm:ai.summary_max_input_tokens` | `number` | `32000` | 요약 최대 입력 토큰 |
| `lm:ai.writing_max_input_tokens` | `number` | `8000` | 글쓰기 개선 최대 입력 토큰 |
| `lm:ai.max_regeneration_count` | `number` | `5` | 동일 블록 재생성 최대 횟수 |
| `pm:ai.tag_recommend_min_length` | `number` | `100` | 태그 추천 최소 본문 길이 (자) |
| `pm:ai.summary_max_retries` | `number` | `3` | 자동 요약 재시도 최대 횟수 |
| `pm:ai.confidence_threshold_high` | `number` | `0.8` | 신뢰도 상한 임계값 — 이 이상이면 "높음" |
| `pm:ai.confidence_threshold_low` | `number` | `0.5` | 신뢰도 하한 임계값 — 이 미만이면 "낮음" |
| `pm:ai.usage_log_retention_years` | `number` | `1` | AI 사용 이력 보관 기간 (년, 금융권 5년) |
| `pm:ai.auto_disable_error_rate` | `number` | `0.3` | 오류율 초과 시 해당 AI 기능 자동 비활성화 |


### 3.13 알림 (`notification`)

| config_key | 값 타입 | 기본값 | 설명 |
|------------|---------|--------|------|
| `pm:notification.bundle_window_minutes` | `number` | `10` | 동일 유형 알림 묶음 판정 시간 (분) |
| `lm:notification.retention_days` | `number` | `90` | 인앱 알림 자동 삭제 기간 (일) |
| `pm:notification.quiet_start` | `string` | `'23:00'` | 야간 무음 모드 시작 시간 |
| `pm:notification.quiet_end` | `string` | `'07:00'` | 야간 무음 모드 종료 시간 |
| `lm:notification.email_max_retry` | `number` | `3` | 이메일 발송 실패 시 최대 재시도 횟수 |
| `lm:notification.webpush_max_retry` | `number` | `2` | Web Push 전송 실패 시 최대 재시도 횟수 |
| `lm:notification.webhook_max_retry` | `number` | `5` | 웹훅 전송 실패 시 최대 재시도 횟수 |
| `pm:notification.work_summary_enabled` | `boolean` | `true` | 근무 시작 시 비근무 시간 알림 요약 발송 여부 |

---

## 4. 설정 변경 규칙

### 4.1 필요 권한

> **BR-SYS-001**: `manage_system` AdminPermission 보유자만 설정 변경이 가능하다. (외부 사용자 유형 라벨과 무관)

- 상세: [FD-ACL](FD-ACL-권한체계.md) §4.5 AdminPermission

### 4.2 변경 전파 메커니즘

> **BR-SYS-002**: 설정 변경은 **이벤트 기반 캐시 무효화**를 통해 모든 인스턴스에 즉시 반영된다. 앱 재시작 불필요.

각 모듈은 자주 참조하는 설정값을 **인메모리 캐시**에 보관한다. 설정 변경 시 다음 절차로 전파된다:

1. 관리자가 설정을 변경하면 DB에 저장한다
2. `system_config.changed` 이벤트를 발행한다 (§6 이벤트 계약 참조)
3. 이벤트를 구독하는 각 모듈이 해당 `config_key`의 캐시를 무효화한다
4. 다음 설정 조회 시 DB에서 최신값을 읽어 캐시를 갱신한다

- **이벤트 발행 실패 시 폴백 정책**:
  1. 설정 변경 DB 커밋 후 EventBus로 이벤트 발행을 시도한다
  2. 이벤트 발행 실패 시 최대 3회 재시도 (지수 백오프, 초기 지연 500ms)
  3. 재시도 소진 시: 캐시는 TTL 만료(기본 60초)로 자연 갱신된다 (fallback), 운영 모니터링 지표(`sys.event_publish_failure_count`)를 증가시키고 운영 관리자 알림을 발송한다
  4. 감사 이벤트 역시 동일 경로로 발행되므로, 발행 실패 시 감사 기록이 최대 60초 지연될 수 있다
- 다중 인스턴스 환경에서는 이벤트 버스(Redis pub/sub)를 통해 모든 인스턴스에 전파

### 4.3 설정값 유효 범위 검증

> **BR-SYS-012**: 모든 설정값은 타입별 유효 범위를 검증한다 — 숫자형은 `0 이상` 및 항목별 상한(정의된 경우), 문자열은 최대 길이, 배열은 최대 요소 수. 유효 범위를 벗어나면 `SYS_INVALID_VALUE` 에러를 반환하며, 응답에 허용 범위를 포함한다.

> **BR-SYS-013**: 존재하지 않는 `config_key`에 대한 조회·변경 요청은 `SYS_KEY_NOT_FOUND` 에러를 반환한다 — 시딩되지 않은 키나 오타를 조기에 차단한다.

---

## 5. 에러 코드

| 에러 코드 | HTTP | 상황 | 설명 |
|-----------|------|------|------|
| `SYS_INVALID_VALUE` | 400 | 유효 범위 초과 | 설정값이 허용된 범위를 벗어남 (음수, 상한 초과 등) — 허용 범위를 응답에 포함. BR-SYS-012 |
| `SYS_KEY_NOT_FOUND` | 404 | config_key 없음 | 존재하지 않는 config_key 접근. BR-SYS-013 |

---

## 6. 이벤트 계약

### 6.1 system_config.changed

설정 변경 시 발행되는 도메인 이벤트. 이벤트 발행측(SYS 모듈)에서 스키마를 정의한다.

**페이로드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `config_key` | `string` | 변경된 설정 키 |
| `category` | `string` | 설정 카테고리 |
| `before` | `jsonb` | 변경 전 값 |
| `after` | `jsonb` | 변경 후 값 |
| `changed_by` | `uuid` | 변경한 관리자 |
| `changed_at` | `timestamp` | 변경 일시 |

**소비자 목록**:

| 소비자 모듈 | 소비 목적 |
|------------|----------|
| document | 문서 관련 설정(`max_tags`, `autosave_interval` 등) 캐시 무효화 |
| search | 검색 관련 설정 캐시 무효화 (SystemConfig 범위에 한함) |
| embedding | 임베딩 워커 수, 재시도 설정 캐시 무효화 |
| aggregation | 인기/트렌딩 가중치 설정 캐시 무효화 |
| audit | 감사 로그 비동기 기록 (§7 참조) |

---

## 7. 감사 로그 연동

> **BR-SYS-010**: 모든 SystemConfig 변경은 `system_config.changed` 이벤트를 통해 **비동기적으로** 감사 로그에 기록된다.

| 기록 항목 | 설명 |
|----------|------|
| `actor` | 변경한 관리자 |
| `action` | `system_config.update` |
| `config_key` | 변경된 설정 키 |
| `before` | 변경 전 값 |
| `after` | 변경 후 값 |
| `timestamp` | 변경 일시 |

- 변경 이력 조회: 특정 설정 항목의 이전 변경 이력(변경 전/후 값, 변경자, 변경 일시)을 관리자 UI에서 확인 가능
- 감사 로그 기록은 이벤트 소비자(audit 모듈)가 비동기로 처리한다 — 설정 변경 API 응답에 영향을 주지 않는다
- 상세: [FD-AUD](FD-AUD-감사로그.md) §2.3 관리자 액션 로그

---

## 8. DTO 정의

### 8.1 설정 조회

**SystemConfigResponseDto**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `config_key` | `string` | 설정 키 |
| `category` | `string` | 카테고리 |
| `value` | `jsonb` | 설정값 (JSON 원본) |
| `value_type` | `string` | 값 타입 (`number` \| `string` \| `boolean` \| `object` \| `array`) |
| `description` | `string` | 설정 설명 |
| `updated_by` | `uuid` | 최종 변경자 |
| `updated_at` | `timestamp` | 최종 변경 일시 |

**SystemConfigGroupResponseDto** (카테고리별 그룹핑 조회):

| 필드 | 타입 | 설명 |
|------|------|------|
| `category` | `string` | 카테고리명 |
| `display_name` | `string` | UI 표시명 |
| `configs` | `SystemConfigResponseDto[]` | 해당 카테고리의 설정 목록 |

### 8.2 설정 변경

**UpdateSystemConfigRequestDto**:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `config_key` | `string` | Y | 변경할 설정 키 |
| `value` | `jsonb` | Y | 변경할 값 |

---

## 9. 관리자 UI

### 9.1 카테고리 그룹핑

설정 화면은 `category`별로 그룹핑하여 표시한다.

| UI 카테고리명 | category | 포함 설정 수 |
|-------------|----------|-------------|
| 시스템 전역 | `system` | 1 (업로드 제한) |
| 문서 관리 | `document` | 5 (태그 수, 자동 저장, 드래프트 방치, 블록 상한, 잠금 타임아웃) |
| 승인 | `approval` | 2 (긴급 발행 사유, 리마인더) |
| 집계 | `aggregation` | 4 (인기 가중치, 트렌딩 기준값 등) |
| 감사 로그 | `audit` | 4 (보관 기간, access log 설정 등) |
| 내보내기 | `export` | 5 (워터마크 텍스트, 비동기 임계치, 파일 TTL, 최대 크기, Job 대기 시간) |
| 임베딩 | `embedding` | 2 (워커 수, 재시도) |
| 커뮤니티 | `community` | 11 (댓글 제한, 신고 설정, 북마크 한도, 게시글 한도 등) |
| 모니터링 | `monitoring` | 10 (수집 주기, 알림 쿨다운, 보관 기간, 용량 예측 등) |
| AI | `ai` | 11 (일일 쿼터, 동시 요청, 토큰 한도, 신뢰도 임계값, 재생성 한도 등) |
| 알림 | `notification` | 8 (묶음 시간 창, 보관 기간, 야간 무음, 재시도 횟수 등) |

- 각 설정 항목에 `description`을 표시하여 관리자가 용도를 파악할 수 있도록 한다

---

## 10. 비기능 요구사항

### 10.1 캐싱 전략

- 각 모듈은 자주 참조하는 설정값을 **인메모리 캐시**에 보관한다
- 캐시 TTL: 기본 60초 (이벤트 기반 무효화의 fallback)
- 캐시 무효화: `system_config.changed` 이벤트 수신 시 해당 키의 캐시를 즉시 삭제
- 다중 인스턴스 환경: 이벤트 버스(Redis pub/sub)를 통해 모든 인스턴스에 전파

### 10.2 성능 목표

| 항목 | 목표 |
|------|------|
| 설정 조회 (캐시 hit) | < 5ms |
| 설정 조회 (DB fallback) | < 50ms |
| 설정 변경 API 응답 | < 200ms |
| 이벤트 전파 지연 | < 500ms (이벤트 발행 → 캐시 무효화 완료) |

### 10.3 동시성

- 설정 변경은 Last-Write-Wins(마지막 쓰기 우선) — 변경 빈도가 낮고 관리자 수가 적어 충돌 위험 무시 가능
- 동시 읽기에 대한 제한 없음 — 캐시 계층에서 흡수

---

## 11. DB 시딩

> **BR-SYS-011**: 앱 최초 배포 시 `lm:`/`pm:` 항목을 SystemConfig 테이블에 시딩한다.

### 11.1 시딩 규칙

```
DB에 해당 config_key가 존재하는가?
  ├── 없음 → 기본값으로 INSERT (초기 배포)
  └── 있음 → UPDATE 하지 않음 (관리자 변경 보존)
```

- 관리자가 운영 중 변경한 값을 재배포로 덮어쓰지 않는다
- 새 키가 추가된 경우에만 해당 키를 INSERT한다
- 시딩 시 `created_at`은 시딩 시점으로 설정한다

---

## 결정사항

| 결정 | 근거 |
|------|------|
| 재배포 시 기존 DB 값 미덮어쓰기 | 관리자가 운영 중 튜닝한 값을 보존 |
| 검색/파싱 튜닝 파라미터는 SystemConfig가 아닌 전용 엔티티로 분리 | 변경 주기, 소비자, 동기화 대상이 각각 달라 범용 Key-Value로 관리 부적절 — [ADR-009](../../adr/009-search-config-singleton-merge.md) 참조 |
| 설정 변경 전파: 캐시 + 이벤트 무효화 방식 | 매번 DB 조회는 성능 비용 과다, TTL 기반은 "즉시 적용" 요건 미충족 — 이벤트 기반 무효화가 성능과 실시간성의 균형점 |
| 감사 로그 기록: 비동기 이벤트 처리 | 설정 변경 API 응답 시간에 영향을 주지 않으면서 감사 추적 보장 |
| 동시성 제어: Last-Write-Wins | 설정 변경 빈도가 낮고 관리자 수가 적어 OCC 불필요 |
| 변경 이력: 감사 로그(`audit_logs`)로 조회 | 별도 이력 테이블 불필요 — 감사 로그에 before/after diff가 이미 기록되므로 중복 방지 |
| 이벤트 계약: 발행측(SYS 모듈) 정의 | 이벤트 스키마 소유권을 발행자에게 부여하여 소비자 의존성 역전 방지 |
| 이벤트 발행 실패 시 TTL 폴백 + 알림 | 재시도 3회 소진 후 캐시 TTL(60초)로 자연 갱신, 운영 알림 발송 — 전달은 Best-effort이며 모듈 스펙(BR-SYS-002)의 재시도·모니터링으로 보강 |

---

## 관련 문서

| 문서 | 참조 내용 |
|------|----------|
| [FD-ADM](FD-ADM-관리자.md) | 관리자 기능 목록 (§1.16 시스템 설정) |
| [FD-ACL](FD-ACL-권한체계.md) | `manage_system` AdminPermission (§4.5) |
| [FD-AUD](FD-AUD-감사로그.md) | 시스템 설정 변경 감사 로그 (§2.3) |
| [FD-SCH](FD-SCH-검색.md) | SearchConfig / ParsingConfig 전용 엔티티 (§3, §6) |
| [ADR-009](../../adr/009-search-config-singleton-merge.md) | 검색·파싱 설정을 SystemConfig에서 분리한 근거 |
| [FD-EMB](FD-EMB-임베딩파이프라인.md) | 임베딩 워커/재시도 설정 |
| [FD-AGG](FD-AGG-집계피드.md) | 인기/트렌딩 집계 파라미터 |
| [04-permission-architecture](../../02-architecture/04-permission-architecture.md) | 인프라 floor vs `manage_system` 운영 조정 |
| [UC-ADM](../usecases/admin/UC-ADM-시스템운영.md) | UC-ADM-15 시스템 운영 설정 관리 |

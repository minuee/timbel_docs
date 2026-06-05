# 집계 및 피드 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-AGG |
| 버전 | 1.2 |
| 작성일 | 2026-03-25 |
| 수정일 | 2026-04-13 |
| 기준 문서 | AICM 새 기능정의서 v1 §3 |

---

## 1. 문서 각종 집계 데이터

- **최신 문서**: 전체 / [게시판](FD-DOC-문서관리.md) §7별 최신 등록순
- **인기 문서**: 전체 / 게시판별 — 조회수, 좋아요 수, 댓글 수 기반 랭킹
- **인기 기간 설정**: 일간 / 주간 / 월간 인기
- **사용자 활동 통계**: 문서 등록 수, 댓글 수, 좋아요 수 등 기여도 집계
- **게시판 통계**: 게시판별 문서 수, 활성 사용자 수, 평균 응답 시간
- **게시판 트리 통계**: 게시판별(뎁스별) 문서 수 집계

### 1.1 비즈니스 규칙

**[인기 스코어 산정]**

- **BR-AGG-001**: 인기 스코어 = `(조회수 × W1) + (좋아요 × W2) + (댓글 × W3)` — 가중치는 `pm:aggregation.popular_weights`로 관리 (기본값: `{view:1, like:3, comment:5}`, [FD-SYS](FD-SYS-시스템설정.md) §3.4)
- **BR-AGG-002**: 인기 기간은 일간 / 주간 / 월간으로 분리 집계한다

**[트렌딩 판정]**

- **BR-AGG-003**: 트렌딩 문서 판정 — 다음 3가지 조건을 모두 충족해야 한다:
  1. 시간 윈도우: 최근 7일 (기본값 168시간, `lm:aggregation.trending_window_hours`, [FD-SYS](FD-SYS-시스템설정.md) §3.4, 관리자 설정 가능)
  2. 증가율: 해당 윈도우의 조회수 증가율이 이전 동일 윈도우 대비 임계값 이상 (`pm:aggregation.trending_threshold_percent` = 200%, 관리자 설정 가능)
  3. 최소 조회수: 절대 조회수가 `lm:aggregation.trending_min_views`(기본 10건) 이상 — 우연한 1~2건 조회의 급등 방지

  **증가율 산정 규칙**:
  ```
  increase_rate = (window_view_count - previous_window_view_count) / previous_window_view_count × 100
  ```
  - `previous_window_view_count == 0`인 경우: `window_view_count >= trending_min_views`이면 증가율을 임계값과 동일하게 간주하여 트렌딩 대상에 포함한다 (신규 문서 초기 급등 허용)
  - 윈도우 경계: 배치 실행 시점 기준 `[now - window_hours, now)` / 이전 윈도우는 `[now - 2×window_hours, now - window_hours)`

**[집계 처리]**

- **BR-AGG-004**: 집계 데이터는 실시간이 아닌 **배치/캐시 기반** 처리 (Redis)
  - 갱신 주기: 트렌딩/인기 문서는 1시간 단위, 통계 대시보드는 일 1회 배치
- **BR-AGG-005**: 캐시 무효화 규칙:
  - 관리자가 수동 새로고침 시 즉시 재계산
  - 관리자가 집계 관련 설정(`pm:aggregation.*`, `lm:aggregation.*`)을 변경하면 `system_config.changed` 이벤트를 통해 관련 캐시를 자동 무효화

---

## 2. 피드 및 구독

**[구독]**

- **BR-AGG-006**: 사용자가 관심 게시판을 구독 → 새 문서 등록 시 [FD-NTF](FD-NTF-알림.md) §1 알림
- **BR-AGG-007**: 구독 상한 — 사용자당 구독 가능한 게시판 수는 관리자가 설정한 상한을 초과할 수 없다 (UC-PER-03 §2a)
- **BR-AGG-008**: 구독 알림 빈도 — 게시판별 "즉시 알림" 또는 "일간 요약" 선택 가능 (UC-PER-03 §3c)

**[피드]**

- **BR-AGG-009**: 피드 페이지는 구독 중인 게시판의 최신 문서를 시간순으로 통합 표시 — 개인화된 뉴스피드
- **BR-AGG-010**: 피드에 표시되는 문서는 사용자의 [FD-ACL](FD-ACL-권한체계.md) 게시판 접근 권한에 따라 필터됨 — 열람 권한 없는 문서는 노출하지 않는다
- **BR-AGG-011**: 피드 정렬: 최신순(기본), 미읽은 문서 우선 정렬 옵션
  - 문서 열람 상태는 `document.viewed` 이벤트를 통해 개인별 열람 이력으로 관리한다 — 열람 이력 저장은 document 모듈이 담당하고, aggregation 모듈은 피드 조회 시 해당 데이터를 참조하여 정렬한다

---

## 3. 홈 대시보드 위젯

로그인 후 메인 화면에 위젯 형태로 집계 데이터와 개인 업무 현황을 표시한다.

### 3.1 위젯 목록

| 위젯 | 설명 | 데이터 원천 | 비고 |
|------|------|------------|------|
| 내 드래프트 현황 | 작성 중인 드래프트 문서 N건 표시 | 실시간 (개인 데이터) | |
| 승인 대기 문서 | 내가 승인해야 할 문서 N건 표시 | 실시간 (개인 데이터) | |
| 최근 열람 문서 | 사용자가 최근 열람한 문서 목록 | 실시간 (개인 데이터) | |
| 인기 문서 Top 5 | 전체/게시판별 인기 문서 상위 5건 (BR-AGG-001 기반) | 배치 (Redis 캐시) | |
| 트렌딩 문서 | 최근 급상승 문서 목록 (BR-AGG-003 기반) | 배치 (Redis 캐시) | |
| 구독 게시판 최신 문서 | 구독 중인 게시판의 최신 문서 요약 | 배치 (Redis 캐시) | |
| 자주 찾는 문서 | 최근 2주간 3회 이상 열람한 문서 목록 | 배치 (개인 데이터) | 상담사 기본 프리셋 (UC-PER-05) |
| 내 문서의 미해결 댓글 | 내가 작성한 문서에 달린 미해결 댓글 목록 | 실시간 (개인 데이터) | 지식 관리자 기본 프리셋 (UC-PER-05) |
| 만료 예정 문서 | 유효기간이 임박한 문서 목록 ([FD-DOC](FD-DOC-문서관리.md) §10 유효기간) | 배치 (개인 데이터) | 지식 관리자 기본 프리셋 (UC-PER-05, UC-DOC-10) |
| 온보딩 가이드 | 신규 입사자용 — 필수 열람 문서, 게시판 구독 안내, 알림 설정 안내 | 실시간 (설정 데이터) | 첫 로그인 시 표시, 완료 후 자동 숨김 (UC-PER-05 시나리오 6) |
| 임베딩 상태 현황 | 대기/처리중/완료/실패 건수 요약 ([FD-EMB](FD-EMB-임베딩파이프라인.md) §1) | 실시간 | **관리자 전용** |

### 3.2 위젯 커스터마이징

- **BR-AGG-012**: 사용자가 위젯 배치를 **드래그 앤 드롭**으로 자유롭게 정렬
- **BR-AGG-013**: 위젯별 **on/off 토글** — 불필요한 위젯을 숨기고 필요한 위젯만 표시
- **BR-AGG-014**: 사용자별 위젯 레이아웃 설정은 개인 자원으로 저장 — 브라우저/기기 간 동기화

### 3.3 역할별 기본 위젯 프리셋

역할에 따라 홈 대시보드의 기본 위젯 구성이 다르다. 사용자가 커스터마이징하지 않은 경우 아래 프리셋이 기본 적용된다.

| 역할 | 기본 위젯 |
|------|----------|
| **상담사** (열람 중심) | 최근 열람 문서, 자주 찾는 문서, 인기 문서 Top 5, 트렌딩 문서, 구독 게시판 최신 문서 |
| **지식 관리자** (편집 권한 보유) | 내 드래프트 현황, 승인 대기 문서, 내 문서의 미해결 댓글, 만료 예정 문서, 인기 문서 Top 5 |
| **승인권자** (APPROVE 보유) | 승인 대기 문서, 최근 열람 문서, 인기 문서 Top 5, 구독 게시판 최신 문서 |
| **운영·통계 위젯 프리셋** (임베딩 현황 등 관리용 위젯 기본 포함) | 임베딩 상태 현황, 승인 대기 문서, 내 드래프트 현황, 트렌딩 문서, 인기 문서 Top 5 |
| **신규 사용자** (첫 로그인) | 온보딩 가이드, 인기 문서 Top 5, 트렌딩 문서 |

- **BR-AGG-015**: 프리셋은 최초 로그인 시 자동 적용 — 이후 사용자가 자유롭게 변경 가능
- **BR-AGG-016**: 역할 변경 시 기존 커스텀 레이아웃은 유지 (자동 리셋 없음)
- **BR-AGG-017**: 온보딩 가이드 위젯은 온보딩 완료 후 자동 숨김 처리 (UC-PER-05 시나리오 6)

### 3.4 위젯 데이터 갱신

- **배치 기반 집계 데이터** (인기 문서, 트렌딩, 구독 최신 문서, 자주 찾는 문서, 만료 예정 문서): Redis 캐시에서 조회 — §1의 갱신 주기(트렌딩/인기 1시간, 통계·개인 집계 일 1회)를 따름
- **실시간 개인 데이터** (내 드래프트, 승인 대기, 미해결 댓글): API 직접 조회 — 대시보드 접근 시 최신 데이터 반영
- **관리자 전용 데이터** (임베딩 상태 현황): [FD-EMB](FD-EMB-임베딩파이프라인.md) §1.5 모니터링 데이터에서 요약 조회

### 3.5 위젯 카탈로그 관리

- **BR-AGG-018**: 홈 대시보드에서 제공하는 위젯 목록은 **위젯 카탈로그**로 관리한다.
- **BR-AGG-019**: 위젯 카탈로그는 **관리 자원**이며, `manage_system` AdminPermission 보유자만 변경할 수 있다.
- 카탈로그 관리 항목:
  - 위젯 키(고유 식별자), 이름, 설명, 활성/비활성 상태
  - 노출 대상 역할·프리셋(열람 중심/승인권자/운영 등), 데이터 원천 유형(실시간/배치), 기본 정렬 순서
- **BR-AGG-020**: 카탈로그에서 비활성화된 위젯은 사용자 개인 레이아웃에 기존 설정이 있더라도 화면에 표시하지 않는다.
- **BR-AGG-021**: 카탈로그 변경(생성/수정/활성화/비활성화/정렬 변경)은 감사 대상 이벤트로 기록한다.

---

## 4. 데이터 모델

### 4.1 DocumentStats 엔티티

문서별 집계 통계를 저장하는 materialized 데이터.

- id: UUID, PK
- document_id: UUID, FK(Document), NOT NULL, UNIQUE — 대상 문서
- board_id: UUID, FK(Board), NOT NULL — 소속 게시판 (조회 편의)
- view_count: INTEGER, NOT NULL, DEFAULT 0 — 누적 조회수
- like_count: INTEGER, NOT NULL, DEFAULT 0 — 좋아요 수
- comment_count: INTEGER, NOT NULL, DEFAULT 0 — 댓글 수
- popular_score_daily: DECIMAL, DEFAULT 0 — 일간 인기 스코어 (BR-AGG-001)
- popular_score_weekly: DECIMAL, DEFAULT 0 — 주간 인기 스코어
- popular_score_monthly: DECIMAL, DEFAULT 0 — 월간 인기 스코어
- last_calculated_at: TIMESTAMP, NOT NULL — 마지막 집계 시각
- created_at: TIMESTAMP, NOT NULL
- updated_at: TIMESTAMP, NOT NULL

### 4.2 TrendingScore 엔티티

트렌딩 배치 판정 결과를 저장.

- id: UUID, PK
- document_id: UUID, FK(Document), NOT NULL — 대상 문서
- board_id: UUID, FK(Board), NOT NULL — 소속 게시판
- window_view_count: INTEGER, NOT NULL — 현재 윈도우 기간 내 조회수
- previous_window_view_count: INTEGER, NOT NULL — 이전 동일 윈도우 조회수
- increase_rate: DECIMAL, NOT NULL — 증가율 (%)
- is_trending: BOOLEAN, NOT NULL, DEFAULT false — 트렌딩 여부 (BR-AGG-003)
- calculated_at: TIMESTAMP, NOT NULL — 계산 시각
- expires_at: TIMESTAMP, NOT NULL — 만료 시각 (다음 배치 시 교체)

### 4.3 Subscription 엔티티

게시판 구독 정보.

- id: UUID, PK
- user_id: UUID, FK(User), NOT NULL — 구독자
- board_id: UUID, FK(Board), NOT NULL — 구독 대상 게시판
- notify_frequency: ENUM('immediate', 'daily_digest'), NOT NULL, DEFAULT 'immediate' — 알림 빈도 (BR-AGG-008)
- status: ENUM('active', 'board_inaccessible', 'board_deactivated'), NOT NULL, DEFAULT 'active' — §5 상태 정의 참조
- created_at: TIMESTAMP, NOT NULL
- updated_at: TIMESTAMP, NOT NULL
- UNIQUE(user_id, board_id)

### 4.4 WidgetCatalog 엔티티

시스템이 제공하는 위젯 목록을 관리하는 관리 자원.

- id: UUID, PK
- widget_key: VARCHAR(50), NOT NULL, UNIQUE — 고유 식별자 (예: `my_drafts`, `popular_top5`, `trending`)
- name: VARCHAR(100), NOT NULL — 위젯 표시명
- description: VARCHAR(500), NULL — 위젯 설명
- is_active: BOOLEAN, NOT NULL, DEFAULT true — 활성/비활성 (BR-AGG-020)
- target_roles: VARCHAR[], NOT NULL — 노출 대상 역할 목록
- data_source_type: ENUM('realtime', 'batch'), NOT NULL — 데이터 원천 유형
- sort_order: INTEGER, NOT NULL, DEFAULT 0 — 기본 정렬 순서
- created_at: TIMESTAMP, NOT NULL
- updated_at: TIMESTAMP, NOT NULL

### 4.5 UserWidgetLayout 엔티티

사용자별 위젯 배치 설정. 개인 자원 — 본인만 접근 가능.

- id: UUID, PK
- user_id: UUID, FK(User), NOT NULL — 소유자
- widget_key: VARCHAR(50), FK(WidgetCatalog.widget_key), NOT NULL — 위젯 참조
- position: INTEGER, NOT NULL — 배치 순서
- is_visible: BOOLEAN, NOT NULL, DEFAULT true — 표시 여부 (on/off 토글)
- created_at: TIMESTAMP, NOT NULL
- updated_at: TIMESTAMP, NOT NULL
- UNIQUE(user_id, widget_key)

> `UserWidgetLayout.widget_key`는 UUID FK가 아닌 **안정 문자열 키 FK**를 의도적으로 사용한다. 위젯 카탈로그의 키는 시스템 전체에서 코드 레벨로 참조되므로(역할별 프리셋, 프론트 컴포넌트 매핑) 변경되지 않는 안정 식별자가 필요하며, UUID는 환경마다 달라져 시딩·마이그레이션에 불리하다 — 결정사항 참조.

### 4.6 엔티티 관계

```
User 1──N Subscription N──1 Board
User 1──N UserWidgetLayout N──1 WidgetCatalog
Document 1──1 DocumentStats
Document 1──0..1 TrendingScore
```

---

## 5. 상태 정의

### 5.1 위젯 카탈로그 상태

```
active ←→ inactive
  ↓           ↓
     deleted (논리 삭제)
```

- active → inactive: 관리자가 비활성화 (BR-AGG-020에 의해 사용자 레이아웃에 있어도 숨김)
- inactive → active: 관리자가 재활성화 — 기존 사용자 레이아웃 설정 복원
- active/inactive → deleted: 관리자가 삭제 — 사용자 레이아웃에서 자동 제거

### 5.2 구독 상태

```
active ←→ board_inaccessible
active ←→ board_deactivated
active → (삭제): 사용자 구독 해제
board_inaccessible/board_deactivated → active: 권한 복원 / 게시판 재활성화
```

- **active**: 정상 구독 중 — 알림 발송
- **board_inaccessible**: 게시판 열람 권한 해제됨 — 구독 유지, 알림 중단 (UC-PER-03 §1a)
- **board_deactivated**: 게시판 비활성화됨 — 구독 유지, 알림 중단, 게시판 재활성화 시 자동 복원 (UC-PER-03 §2c)
- 게시판 삭제 시: 구독 자동 해제 + 사용자에게 알림 발송 (UC-PER-03 §2b)
- 접근 불가/비활성화 상태가 30일 이상 지속 시 구독 정리 알림 발송 (UC-PER-03 §2d)

---

## 6. 설정 가능 항목

| 설정 항목 | config_key ([FD-SYS](FD-SYS-시스템설정.md) §3.4) | 타입 | 기본값 | 설명 |
|-----------|------------|------|--------|------|
| 인기 스코어 가중치 | `pm:aggregation.popular_weights` | object | `{view:1, like:3, comment:5}` | BR-AGG-001 가중치 |
| 트렌딩 증가율 임계값 | `pm:aggregation.trending_threshold_percent` | number | 200 | BR-AGG-003 증가율 기준 (%) |
| 트렌딩 최소 조회수 | `lm:aggregation.trending_min_views` | number | 10 | BR-AGG-003 최소 조회수 필터 |
| 트렌딩 시간 윈도우 | `lm:aggregation.trending_window_hours` | number | 168 (7일) | BR-AGG-003 시간 윈도우 |

---

## 7. 이벤트 계약

### 7.1 소비 이벤트

aggregation 모듈이 다른 모듈에서 발행한 이벤트를 소비하여 집계 데이터를 갱신한다. 이벤트 페이로드는 발행측 모듈에서 정의한다 (B5 결정).

> **교차 참조**: 각 소비 이벤트의 페이로드 스키마는 발행 모듈의 FD/모듈 스펙에서 정의한다 — `document.*`는 [FD-DOC](FD-DOC-문서관리.md), `document.liked`/`document.commented`는 [FD-COM](FD-COM-커뮤니티.md), `board.*`는 [FD-DOC](FD-DOC-문서관리.md) §7, `system_config.changed`는 [FD-SYS](FD-SYS-시스템설정.md) §6.1 참조.

**큐 및 운영 정책**:
- 큐명: `aggregation.events` (BullMQ)
- 재시도: 소비 실패 시 최대 3회 재시도 (지수 백오프, 초기 지연 1초)
- DLQ: 재시도 소진 시 `aggregation.events.dlq`로 이동 — 운영 관리자 알림 발송
- 멱등 키: `{eventType}:{resourceId}:{timestamp}` — 동일 이벤트 중복 소비 방지

| 이벤트 | 발행 모듈 | aggregation 처리 |
|--------|----------|-----------------|
| `document.published` | document | 최신 문서 목록 갱신, 구독 게시판 피드 추가 |
| `document.viewed` | document | 조회수 증가 (DocumentStats), 트렌딩 계산 입력 |
| `document.liked` | community | 좋아요 수 증가 (DocumentStats), 인기 스코어 재계산 입력 |
| `document.commented` | community | 댓글 수 증가 (DocumentStats), 인기 스코어 재계산 입력 |
| `document.archived` | document | 집계 대상 제외 — 인기/트렌딩 목록에서 제거 |
| `document.suspended` | document | 집계 대상 제외 — 인기/트렌딩 목록에서 제거 |
| `board.deleted` | board | 해당 게시판 구독 자동 해제 + 사용자 알림 |
| `board.deactivated` | board | 해당 게시판 구독 상태 → `board_deactivated`, 알림 중단 |
| `board.activated` | board | 해당 게시판 구독 상태 → `active`, 알림 재개 |
| `system_config.changed` | system-config | 집계 관련 설정 변경 시 해당 캐시 무효화 (BR-AGG-005) |

### 7.2 발행 이벤트

aggregation 모듈이 발행하는 이벤트.

| 이벤트 | 페이로드 | 소비자 | 설명 |
|--------|---------|--------|------|
| `aggregation.popular_updated` | `{ period: 'daily' \| 'weekly' \| 'monthly', boardId?: UUID, calculatedAt: ISO8601 }` | notification | 인기 문서 배치 갱신 완료 |
| `aggregation.trending_updated` | `{ windowHours: number, documentCount: number, calculatedAt: ISO8601 }` | notification | 트렌딩 배치 갱신 완료 |
| `subscription.created` | `{ userId: UUID, boardId: UUID }` | — | 구독 생성 |
| `subscription.deleted` | `{ userId: UUID, boardId: UUID, reason: 'user_action' \| 'board_deleted' }` | — | 구독 해제 |
| `widget_catalog.changed` | `{ widgetKey: string, action: 'created' \| 'updated' \| 'activated' \| 'deactivated', changedBy: UUID }` | log-event | 위젯 카탈로그 변경 (BR-AGG-021) |

---

## 8. 에러 코드

| 에러 코드 | HTTP | 설명 | 관련 BR |
|-----------|------|------|---------|
| `AGG_SUBSCRIPTION_LIMIT_EXCEEDED` | 409 | 구독 상한 초과 | BR-AGG-007 |
| `AGG_SUBSCRIPTION_NO_ACCESS` | 403 | 열람 권한 없는 게시판 구독 시도 | BR-AGG-006 |
| `AGG_SUBSCRIPTION_DUPLICATE` | 409 | 이미 구독 중인 게시판 재구독 시도 | BR-AGG-006 |
| `AGG_WIDGET_NOT_FOUND` | 404 | 비활성화/삭제된 위젯 참조 | BR-AGG-020 |
| `AGG_WIDGET_CATALOG_UNAUTHORIZED` | 403 | 위젯 카탈로그 관리 권한 없음 | BR-AGG-019 |
| `AGG_FEED_BOARD_INACCESSIBLE` | 403 | 피드에서 접근 불가 게시판 문서 조회 시도 | BR-AGG-010 |
| `AGG_WIDGET_LAYOUT_INVALID` | 400 | 위젯 레이아웃 저장 시 position 중복/범위 초과 등 검증 실패 | BR-AGG-012 |
| `AGG_WIDGET_LAYOUT_CONFLICT` | 409 | 위젯 레이아웃 동시 변경 충돌 | BR-AGG-014 |
| `AGG_CACHE_UNAVAILABLE` | 503 | Redis 캐시 장애 — 이전 캐시 데이터(stale) 또는 빈 응답 반환 | BR-AGG-004 |

---

## 9. 주요 API 및 DTO 개요

> 모듈 스펙에서 본 §4 엔티티 필드명을 준수하여 상세 API를 정의한다. 이 절은 FD 수준의 리소스/DTO 개요이다.

### 9.1 인기 문서 조회

| 항목 | 값 |
|------|---|
| 엔드포인트 | `GET /api/aggregation/popular` |
| 쿼리 파라미터 | `period` (`daily` \| `weekly` \| `monthly`), `boardId?` (UUID), `limit` (기본 5, 최대 20) |
| 응답 DTO | `PopularDocumentsResponseDto` |

**PopularDocumentsResponseDto**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `items` | `PopularDocumentItemDto[]` | 인기 문서 목록 |
| `period` | `string` | 조회 기간 |
| `calculatedAt` | `ISO8601` | 마지막 집계 시각 |

**PopularDocumentItemDto**: `documentId`, `title`, `boardId`, `boardName`, `viewCount`, `likeCount`, `commentCount`, `popularScore`

### 9.2 트렌딩 문서 조회

| 항목 | 값 |
|------|---|
| 엔드포인트 | `GET /api/aggregation/trending` |
| 쿼리 파라미터 | `limit` (기본 10, 최대 20) |
| 응답 DTO | `TrendingDocumentsResponseDto` |

**TrendingDocumentsResponseDto**: `items` (`TrendingDocumentItemDto[]`), `windowHours`, `calculatedAt`

**TrendingDocumentItemDto**: `documentId`, `title`, `boardId`, `boardName`, `windowViewCount`, `increaseRate`

### 9.3 피드 조회

| 항목 | 값 |
|------|---|
| 엔드포인트 | `GET /api/aggregation/feed` |
| 쿼리 파라미터 | `sort` (`latest` \| `unread_first`, 기본 `latest`), `page`, `pageSize` |
| 응답 DTO | `FeedResponseDto` |

**FeedResponseDto**: `items` (`FeedItemDto[]`), `total`, `page`, `pageSize`

**FeedItemDto**: `documentId`, `title`, `boardId`, `boardName`, `createdAt`, `isRead` (boolean)

### 9.4 구독 관리

| 엔드포인트 | 메서드 | 요청 DTO | 응답 DTO | 설명 |
|-----------|--------|---------|---------|------|
| `/api/aggregation/subscriptions` | GET | — | `SubscriptionListResponseDto` | 내 구독 목록 |
| `/api/aggregation/subscriptions` | POST | `CreateSubscriptionRequestDto` | `SubscriptionResponseDto` | 구독 생성 |
| `/api/aggregation/subscriptions/:id` | DELETE | — | — (204) | 구독 해제 |
| `/api/aggregation/subscriptions/:id` | PATCH | `UpdateSubscriptionRequestDto` | `SubscriptionResponseDto` | 알림 빈도 변경 |

**CreateSubscriptionRequestDto**: `boardId` (UUID, 필수)

**UpdateSubscriptionRequestDto**: `notifyFrequency` (`immediate` \| `daily_digest`, 필수)

**SubscriptionResponseDto**: `id`, `boardId`, `boardName`, `notifyFrequency`, `status`, `createdAt`

### 9.5 위젯 레이아웃 관리

| 엔드포인트 | 메서드 | 요청 DTO | 응답 DTO | 설명 |
|-----------|--------|---------|---------|------|
| `/api/aggregation/widgets/layout` | GET | — | `WidgetLayoutResponseDto` | 내 위젯 레이아웃 조회 |
| `/api/aggregation/widgets/layout` | PUT | `SaveWidgetLayoutRequestDto` | `WidgetLayoutResponseDto` | 레이아웃 전체 저장 |

**SaveWidgetLayoutRequestDto**: `widgets` (`WidgetLayoutItemDto[]`)

**WidgetLayoutItemDto**: `widgetKey` (string), `position` (integer), `isVisible` (boolean)

**WidgetLayoutResponseDto**: `widgets` (`WidgetLayoutItemDto[]`), `updatedAt`

### 9.6 위젯 카탈로그 관리 (관리자)

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/admin/widgets/catalog` | GET | 카탈로그 목록 조회 |
| `/api/admin/widgets/catalog` | POST | 위젯 등록 |
| `/api/admin/widgets/catalog/:key` | PATCH | 위젯 수정 |
| `/api/admin/widgets/catalog/:key` | DELETE | 위젯 삭제 (논리) |

> 카탈로그 관리의 상세 DTO는 [FD-ADM](FD-ADM-관리자.md) §1.14.1 및 모듈 스펙에서 정의한다. 관련 UC: [UC-ADM-17](../usecases/admin/UC-ADM-시스템운영.md#uc-adm-17-위젯-카탈로그-관리)

### 9.7 배치 실행 이력 조회

| 항목 | 값 |
|------|---|
| 엔드포인트 | `GET /api/admin/aggregation/batch-history` |
| 쿼리 파라미터 | `batch_type` (`popular` \| `trending` \| `stats`), `from` (ISO8601), `to` (ISO8601), `page`, `pageSize` |
| 응답 DTO | `BatchHistoryResponseDto` |

**BatchHistoryResponseDto**: `items` (`BatchHistoryItemDto[]`), `total`, `page`, `pageSize`

**BatchHistoryItemDto**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `batchId` | UUID | 배치 실행 고유 ID |
| `batchType` | string | 배치 유형 (`popular` \| `trending` \| `stats`) |
| `status` | enum | `'completed'` \| `'failed'` \| `'running'` |
| `startedAt` | ISO8601 | 실행 시작 시각 |
| `completedAt` | ISO8601, NULL | 완료 시각 |
| `durationMs` | integer, NULL | 실행 소요 시간 (ms) |
| `processedCount` | integer | 처리된 문서/레코드 수 |
| `errorMessage` | string, NULL | 실패 시 에러 메시지 |

---

## 10. 비기능 요구사항

### 10.1 성능

- 대시보드 로드 시간: p95 < 3초 (UC-PER OPS-PER-02 참조)
- 위젯별 독립 로딩 — 한 위젯 장애가 전체 대시보드를 차단하지 않는다 (UC-PER-05 §2f)

### 10.2 캐시 전략

| 캐시 대상 | TTL | 갱신 방식 |
|-----------|-----|----------|
| 인기 문서 랭킹 | 1시간 | 배치 스케줄 (1시간 단위) |
| 트렌딩 문서 | 1시간 | 배치 스케줄 (1시간 단위) |
| 통계 대시보드 | 24시간 | 일 1회 배치 |
| 구독 게시판 최신 문서 | 1시간 | 배치 스케줄 |
| 자주 찾는 문서 | 24시간 | 일 1회 배치 |
| 만료 예정 문서 | 24시간 | 일 1회 배치 |

- 설정 변경(`system_config.changed` 이벤트) 시 관련 캐시 즉시 무효화 (BR-AGG-005)
- 관리자 수동 새로고침 시 해당 캐시 즉시 재계산
- Redis 장애 시 이전 캐시 데이터(stale) 반환 또는 빈 응답 + `AGG_CACHE_UNAVAILABLE` 에러

### 10.3 배치 처리

- 배치 실패 시 최대 3회 재시도 (지수 백오프)
- 연속 실패 시 관리자 알림 발송
- 배치 갱신 중 조회 요청은 이전 캐시 데이터로 응답 (eventually consistent)

### 10.4 데이터 보관

- 집계 결과(DocumentStats, TrendingScore): 최신 데이터만 유지, 이력 미보관
- 구독 정보(Subscription): 사용자 탈퇴 시 삭제
- 위젯 레이아웃(UserWidgetLayout): 사용자 탈퇴 시 삭제

---

## 결정 사항

| 항목 | 결정 | 근거 | 날짜 |
|------|------|------|------|
| 트렌딩 윈도우 | 7일 (168시간) | UC-PER-05와 통일, AICC 컨택센터 환경에서 24시간은 짧아 의미 있는 트렌딩 감지 어려움 | 2026-03-31 |
| 추가 위젯 4종 | v1 스코프에 포함 | UC-PER-05에 정의된 역할별 위젯, 위젯 카탈로그 구조이므로 추가 비용 낮음 | 2026-03-31 |
| 설정 변경 캐시 무효화 | `system_config.changed` 이벤트 기반 자동 무효화 | 설정 변경 후 최대 1시간 대기는 운영자 혼선 유발 | 2026-03-31 |
| 이벤트 계약 소유권 | 이벤트 발행측 모듈에서 페이로드 정의 | `document.published` 등은 document 모듈이 원천, aggregation은 소비자 | 2026-03-31 |
| UserWidgetLayout FK | `widget_key`(문자열) FK 사용, UUID FK 미사용 | 위젯 키는 코드·프리셋·시딩에서 안정 식별자로 참조되어 환경 간 일관성 필요 — UUID는 환경마다 상이 | 2026-03-31 |
| 소비 이벤트 큐/재시도 | BullMQ `aggregation.events` 큐, 3회 재시도 + DLQ | 멱등 소비 보장, 운영 알림 연동 | 2026-03-31 |

---

## 관련 문서

| 문서 | 설명 |
|------|------|
| [FD-DOC](FD-DOC-문서관리.md) | 게시판 트리(§7), 문서 상태 관리(§1) — 집계 대상 |
| [FD-NTF](FD-NTF-알림.md) | 구독 게시판 새 문서 알림(§1) |
| [FD-ADM](FD-ADM-관리자.md) | 위젯 카탈로그 관리(§1.14.1), 개인 커스터마이징 운영 경계(§1.14.2) |
| [FD-SYS](FD-SYS-시스템설정.md) | 집계 관련 설정 항목(§3.4) — config_key 정의 |
| [FD-ACL](FD-ACL-권한체계.md) | 피드 접근 권한 필터링, 개인 자원 정의 |
| [FD-COM](FD-COM-커뮤니티.md) | 좋아요/댓글 — 인기 스코어 입력 이벤트 |
| [FD-EMB](FD-EMB-임베딩파이프라인.md) | 임베딩 상태 현황 위젯(§1.5) |
| [UC-PER](../usecases/user/UC-PER-개인영역.md) | 개인 영역 유즈케이스 (UC-PER-03 구독, UC-PER-05 홈 대시보드) |
| [UC-ADM-17](../usecases/admin/UC-ADM-시스템운영.md#uc-adm-17-위젯-카탈로그-관리) | 위젯 카탈로그 관리 — FD-ADM §1.14.1과 동일 주제 |

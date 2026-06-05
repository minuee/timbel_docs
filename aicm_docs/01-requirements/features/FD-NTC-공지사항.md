# 공지사항 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-NTC |
| 버전 | 1.0 |
| 작성일 | 2026-04-02 |
| 기준 문서 | UC-NTC-공지사항 (UC-NTC-01~08), FD-DOC §1·§7, FD-NTF §1, FD-COM §1 |

---

## 1. 공지사항 게시판

### 1.1 게시판 유형 확장

- **[BR-NTC-001]** `Board.board_type` CHECK 제약에 `'notice'`를 추가한다: `CHECK (board_type IN ('knowledge', 'community', 'notice', 'custom'))`
- **[BR-NTC-002]** `notice` 타입 게시판의 문서는 기존 `Document`/`Block` 구조를 그대로 사용한다 — 별도 `Notice` 엔티티를 생성하지 않는다
- **[BR-NTC-003]** `notice` 타입 게시판은 기본적으로 전체 사용자에게 `VIEW` 권한이 부여된다. `BoardPermission`에서 명시적으로 `VIEW`를 제거하지 않는 한 모든 로그인 사용자가 열람 가능하다
- **[BR-NTC-004]** `notice` 타입 게시판도 트리 구조(`parent_id`)로 구성할 수 있다 — "시스템 공지", "정책/규정 변경", "교육 안내" 등 하위 게시판 분류

### 1.2 notice 타입 운영 특성

| 특성 | knowledge | community | notice |
|------|-----------|-----------|--------|
| 임베딩/RAG 대상 | ✅ | ❌ | 관리자 설정(`board_config.notice.include_in_rag`) |
| 승인+버전 관리 | 기본 ON | 기본 OFF | 기본 OFF (승인 필요 시 `approval_required = true` 및 `mandatory_approval_config` / `default_approval_template_id` 설정) |
| 기본 열람 권한 | 게시판별 설정 | 게시판별 설정 | 전체 사용자 VIEW [BR-NTC-003] |
| 읽음 확인 | ❌ | ❌ | ✅ (문서별 선택) |
| 팝업 공지 | ❌ | ❌ | ✅ (문서별 선택) |
| 상단 고정 | ✅ (일반 고정) | ✅ (게시판 공지) | ✅ (공지 고정) |
| 강제 알림 | ❌ | ❌ | ✅ (게시 시 구독 무관 강제 발송) |
| 에디터 프로파일 | 전체 블록 | 기본 블록 | 전체 블록 |
| AI 답변 검색 포함 | ✅ | ❌ | 문서별 선택 [BR-NTC-005] |

- **[BR-NTC-005]** 관리자가 `board_config.notice.include_in_rag = true`로 설정한 경우, 작성자가 공지별로 "AI 답변 검색에 포함" 여부를 선택할 수 있다. 정책 공지처럼 장기 참조가 필요한 경우 포함하고, 일시적 안내(점검 일정 등)는 제외한다

### 1.3 board_config 공지 전용 설정

`Board.board_config`에 공지 관련 설정 키를 추가한다. `notice` 키는 `board_type = 'notice'`인 게시판에서만 유의미하며, 다른 타입에서는 무시한다. `banner` 키는 모든 `board_type`에서 유효하다 — 타 게시판에서 크로스보드 공지 배너를 수신하는 설정이므로 `notice` 키와 분리한다.

```jsonc
{
  "notice": {
    "default_popup": false,
    "default_popup_frequency": "once",
    "default_confirmation_required": false,
    "default_confirmation_deadline_days": null,
    "max_pinned_count": 5,
    "reminder_days_before": [3, 1],
    "overdue_reminder_interval_hours": 24,
    "allowed_notification_channels": ["in_app", "email", "web_push"],
    "include_in_rag": false
  },
  "banner": {
    "show_cross_board_banner": true,
    "max_banner_count": 3
  }
}
```

**`notice` 키** — `board_type = 'notice'` 전용:

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| `default_popup` | boolean | false | 새 공지 작성 시 팝업 기본값 |
| `default_popup_frequency` | string | `"once"` | 기본 팝업 표시 빈도: `"once"` \| `"every_login"` \| `"daily"` |
| `default_confirmation_required` | boolean | false | 새 공지 작성 시 읽음 확인 필수 기본값 |
| `default_confirmation_deadline_days` | integer \| null | null | 기본 확인 기한 일수. null이면 무기한 |
| `max_pinned_count` | integer | 5 | 게시판당 고정 문서 최대 수 [BR-NTC-014] |
| `reminder_days_before` | integer[] | [3, 1] | 확인 기한 전 리마인더 발송 잔여 일수 목록 |
| `overdue_reminder_interval_hours` | integer | 24 | 기한 초과 후 리마인더 반복 간격(시간) |
| `allowed_notification_channels` | string[] | ["in_app", "email", "web_push"] | 허용 알림 채널 목록 |
| `include_in_rag` | boolean | false | AI 답변 검색(RAG) 포함 허용 여부 |

**`banner` 키** — 모든 `board_type`(`knowledge`, `community`, `notice`, `custom`)에서 유효:

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| `show_cross_board_banner` | boolean | true | 이 게시판에서 크로스보드 공지 배너를 표시할지 여부. false이면 해당 게시판에 배너가 노출되지 않는다 |
| `max_banner_count` | integer | 3 | 동시에 표시할 배너 최대 건수. 초과 시 "N건 더보기" 링크로 안내 |

- **[BR-NTC-006]** 키가 누락되면 애플리케이션 레벨의 기본값을 적용한다 (`board_config`의 기존 패턴과 동일, [Board data.md](../../03-module-design/board/data.md) §2.1 참조)

---

## 2. 공지사항 작성/수정/삭제

### 2.1 작성 규칙

- **[BR-NTC-007]** 공지 작성 권한은 해당 공지사항 게시판의 `EDIT` 권한 보유자에게 부여된다 — 일반적으로 운영 관리자, 지식 관리자
- **[BR-NTC-008]** 공지 본문은 기존 블록 에디터(Tiptap)를 그대로 사용한다 ([FD-DOC](FD-DOC-문서관리.md) §2 참조). 에디터 프로파일은 `knowledge`와 동일하다
- **[BR-NTC-009]** 공지 작성 시 `Document.board_id`가 `board_type = 'notice'`인 게시판을 가리킨다. 시스템은 `board_type`을 기준으로 공지 전용 옵션 UI를 활성화한다
- **[BR-NTC-010]** `Board.approval_required = true`인 공지사항 게시판에서는 "게시" 시 승인 요청 흐름을 따른다 ([FD-APR](FD-APR-승인워크플로.md) 참조). 승인 완료 후 자동 게시 + 알림 발송
- 게시판에 문서 양식(템플릿)이 설정되어 있으면 양식을 활용할 수 있다 ([FD-DOC](FD-DOC-문서관리.md) §4 참조)

### 2.2 공지 옵션

공지 문서에 설정하는 옵션은 `Document.notice_options` JSONB 필드에 저장한다.

```jsonc
{
  "requires_confirmation": false,
  "confirmation_target_type": "all",
  "confirmation_target_ids": [],
  "confirmation_deadline_days": null,
  "is_popup": false,
  "popup_frequency": "once",
  "notification_target_type": "all",
  "notification_target_ids": [],
  "send_update_notification": true,
  "require_scroll_to_confirm": false,
  "include_in_rag": false,
  "is_banner": false,
  "banner_target_type": "all",
  "banner_target_board_ids": []
}
```

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| `requires_confirmation` | boolean | `board_config.notice.default_confirmation_required` | 읽음 확인 필수 여부 |
| `confirmation_target_type` | string | `"all"` | 읽음 확인 대상: `"all"` \| `"roles"` \| `"groups"` |
| `confirmation_target_ids` | UUID[] | [] | `"roles"` 또는 `"groups"` 시 대상 ID 목록. `"all"`이면 빈 배열 |
| `confirmation_deadline_days` | integer \| null | `board_config.notice.default_confirmation_deadline_days` | 게시 후 확인 기한 일수. null이면 무기한 |
| `is_popup` | boolean | `board_config.notice.default_popup` | 팝업 공지 여부 |
| `popup_frequency` | string | `board_config.notice.default_popup_frequency` | 팝업 표시 빈도: `"once"` \| `"every_login"` \| `"daily"` |
| `notification_target_type` | string | `"all"` | 알림 대상: `"all"` \| `"roles"` \| `"groups"` |
| `notification_target_ids` | UUID[] | [] | `"roles"` 또는 `"groups"` 시 대상 ID 목록 |
| `send_update_notification` | boolean | true | 수정 게시 시 알림 발송 여부 (경미한 오탈자 수정 시 false 선택) |
| `require_scroll_to_confirm` | boolean | false | 본문 끝까지 스크롤해야 확인 버튼 활성화 |
| `include_in_rag` | boolean | false | AI 답변 검색 포함 여부. `board_config.notice.include_in_rag = true`일 때만 유효 [BR-NTC-005] |
| `is_banner` | boolean | false | 크로스보드 배너 표시 여부. true이면 대상 게시판 상단에 배너로 노출 |
| `banner_target_type` | string | `"all"` | 배너 대상 게시판: `"all"` (배너 수신이 허용된 모든 게시판) \| `"selected"` (특정 게시판만) |
| `banner_target_board_ids` | UUID[] | [] | `"selected"` 시 대상 게시판 ID 목록. `"all"`이면 빈 배열. 대상 게시판의 `board_config.banner.show_cross_board_banner = false`이면 해당 게시판에서는 무시 |

- **[BR-NTC-011]** `notice_options`는 `board_type = 'notice'`인 게시판의 문서에서만 유효하다. 다른 타입 게시판 문서에서는 무시된다
- **[BR-NTC-012]** 공지 게시 시 `notice_options`의 기본값은 `board_config.notice.*` 설정에서 상속한다. 작성자가 개별 공지에서 오버라이드할 수 있다

### 2.3 수정 규칙

- **[BR-NTC-013]** 공지 수정은 기존 문서 수정 흐름을 따른다 — 게시된 공지를 유지한 채 새 `draft` 버전을 생성하고, 승인 설정에 따라 즉시 게시 또는 승인 요청 ([FD-DOC](FD-DOC-문서관리.md) §1.1 참조)
- 수정 시 `notice_options`를 변경할 수 있다 — 읽음 확인 필수 여부, 팝업 설정, 알림 대상 등
- 읽음 확인 재설정: §4.2 [BR-NTC-023] 참조
- 수정 알림: §5.1 `notice_updated` 참조. `notice_options.send_update_notification = false`이면 수정 알림을 발송하지 않는다

### 2.4 삭제 규칙

- 공지 삭제는 기존 문서 삭제 규칙([FD-DOC](FD-DOC-문서관리.md) §1 [BR-DOC-002], [BR-DOC-036])을 따른다 — 소프트 딜리트, 승인 대기 중 삭제 차단
- **[BR-NTC-040]** 읽음 확인이 진행 중인 공지를 삭제하면 `NoticeReadConfirmation` 데이터를 보존한다 — 감사 목적. 삭제된 공지의 확인 현황은 관리자 조회에서 "(삭제됨)" 표시와 함께 조회 가능하다
- 삭제 시 상단 고정은 자동 해제된다 [BR-NTC-019]
- 삭제 시 배너 설정된 공지는 모든 대상 게시판의 배너 영역에서 즉시 제거된다 [BR-NTC-043]

### 2.5 크로스보드 배너 규칙

`notice_options.is_banner = true`인 공지를 공지사항 게시판이 아닌 다른 게시판 상단에 배너 영역으로 표시하는 규칙을 정의한다. 배너는 기존 문서 목록·핀(고정)·검색과 완전히 독립된 채널로 동작한다.

- **[BR-NTC-041]** 배너 표시 조건 — 다음 조건을 **모두** 충족하는 공지만 게시판 상단 배너 영역에 노출한다:
  1. `notice_options.is_banner = true`
  2. `Document.status = 'published'` AND `is_suspended = false` AND `deleted_at IS NULL`
  3. 대상 게시판 매칭: `banner_target_type = 'all'`이면 배너 수신이 허용된(`board_config.banner.show_cross_board_banner = true`) 모든 게시판, `banner_target_type = 'selected'`이면 `banner_target_board_ids`에 포함된 게시판 중 배너 수신이 허용된 게시판
  4. 사용자 타겟 매칭: `notification_target_type/notification_target_ids` 기준으로 현재 사용자가 대상에 포함
  5. 유효기간(`expires_at`)이 미설정이거나 만료 전

- **[BR-NTC-042]** 배너 가시성 판단 기준 — 배너 가시성은 `notification_target_type`/`notification_target_ids`를 기준으로 판단하며, 대상 게시판의 `BoardPermission`과 무관하다. 즉, 게시판 열람 권한이 있더라도 공지의 알림 대상에 포함되지 않으면 배너가 표시되지 않는다.

- **[BR-NTC-043]** 배너 자동 해제 조건 — 다음 중 하나에 해당하면 배너가 모든 대상 게시판에서 즉시 제거된다:
  - 원본 문서가 `published` 외 상태로 전환될 때 (승인 대기 복귀, 아카이브 등)
  - 원본 문서가 삭제(`deleted_at IS NOT NULL`)될 때
  - 유효기간(`expires_at`) 만료 시 — 유효기간 만료 배치([FD-DOC](FD-DOC-문서관리.md) §1.3)에서 처리
  - 공지가 긴급 회수(`is_suspended = true`)될 때
  - 작성자 또는 관리자가 `notice_options.is_banner = false`로 수동 해제할 때

- **[BR-NTC-044]** 배너와 팝업 우선순위 — 동일 공지가 팝업(`is_popup = true`) + 배너(`is_banner = true`)로 설정된 경우:
  - 팝업을 먼저 표시한다 (로그인 시 팝업 표시 규칙에 따라)
  - 팝업 확인/닫기 후에도 대상 게시판의 배너는 유지된다 — 두 채널은 독립적으로 동작
  - 상단 고정(`is_pinned`)과도 독립 — 고정은 소속 게시판 목록 내, 배너는 타 게시판 상단 영역

- **[BR-NTC-045]** 배너 표시 순서 — 게시판당 배너 목록의 표시 순서는 다음 기준을 적용한다:
  1. 읽음 확인 필수(`notice_options.requires_confirmation = true`) 공지 우선
  2. 동일 조건 내에서 게시일 역순(`published_at DESC`, 최신이 위)
  3. `board_config.banner.max_banner_count` 초과 시 우선순위가 낮은 배너부터 "N건 더보기" 링크로 안내 — 더보기 클릭 시 공지사항 게시판 목록으로 이동

---

## 3. 문서 상단 고정 (Pin)

### 3.1 고정 필드

`Document` 엔티티에 다음 필드를 추가한다.

| 필드 | 타입 | 제약 | 기본값 | 설명 |
|------|------|------|--------|------|
| `is_pinned` | BOOLEAN | NOT NULL | false | 상단 고정 여부 |
| `pinned_at` | TIMESTAMPTZ | NULL | null | 고정 시각 |
| `pinned_by` | UUID | NULL | null | 고정 수행자 (외부 UserService, FK 없음) |

- **[BR-NTC-014]** 게시판당 고정 문서 수는 `board_config.notice.max_pinned_count` 이하로 제한한다. 상한 초과 시 고정 요청을 거부한다
- **[BR-NTC-015]** `is_pinned = true`이면 `pinned_at`, `pinned_by`가 NOT NULL이어야 한다 (앱 레벨 검증)
- **[BR-NTC-016]** `is_pinned = true`는 `status = 'published'`인 문서에서만 허용한다. 다른 상태에서 고정 시도 시 거부한다

### 3.2 고정 규칙

- **[BR-NTC-017]** 고정은 게시판 스코프로 동작한다 — 동일 문서가 여러 게시판에 속할 수 없으므로(`Document.board_id`), 고정은 소속 게시판 목록에서만 유효하다
- **[BR-NTC-018]** 고정 권한: 해당 게시판의 `APPROVE` 권한 보유자 또는 운영 관리자(`manage_boards`) — [FD-ACL](FD-ACL-권한체계.md) 참조
- **[BR-NTC-019]** 고정 자동 해제 조건:
  - 문서가 `published` 외 상태로 전환될 때 (`archived`, 긴급 회수 `is_suspended = true`, 삭제)
  - 문서의 유효기간(`expires_at`)이 만료되어 `is_suspended = true`로 전환될 때
  - 자동 해제 시 `is_pinned = false`, `pinned_at = NULL`, `pinned_by = NULL`로 초기화
- **[BR-NTC-020]** 자동 해제된 문서가 다시 `published` 상태로 복원되더라도 고정은 자동 복원되지 않는다 — 필요 시 수동으로 다시 고정해야 한다
- **[BR-NTC-021]** 고정 기간 설정: 작성자가 고정 시 만료 날짜를 설정할 수 있다. 만료 시 자동으로 고정이 해제된다. 만료 날짜가 없으면 수동 해제할 때까지 유지. 구현: 유효기간 만료 배치와 동일한 BullMQ cron job에서 처리

### 3.3 고정 문서 정렬

- **[BR-NTC-022]** 게시판 목록 조회 시 고정 문서가 항상 최상단에 표시된다. 고정 문서 간 정렬은 `pinned_at DESC` (최근 고정이 위). 비고정 문서는 `created_at DESC` (최신순)
- 운영 관리자가 고정 문서 간 표시 순서를 변경할 수 있다 — 2차 릴리스에서 `Document.pin_order` 필드를 추가한다. 1차 릴리스에서는 `pinned_at DESC`(최근 고정이 위)로 정렬한다

---

## 4. 읽음 확인

### 4.1 NoticeReadConfirmation 엔티티

**소속 모듈**: CommunityModule — Document에 대한 사용자 액션을 관리하는 모듈

| 필드 | 타입 | 제약 | 기본값 | 설명 |
|------|------|------|--------|------|
| `id` | UUID | PK | | 고유 식별자 |
| `document_id` | UUID | FK(Document), NOT NULL | | 대상 공지 |
| `user_id` | UUID | NOT NULL | | 확인 대상 사용자 (외부 UserService, FK 없음) |
| `confirmed_at` | TIMESTAMPTZ | NULL | null | 확인 완료 시각. null이면 미확인 |
| `confirmation_deadline` | TIMESTAMPTZ | NULL | null | 개인별 확인 기한 (공지의 `confirmation_deadline_days`에서 산출) |
| `reminder_sent_count` | INTEGER | NOT NULL | 0 | 발송된 리마인더 횟수 |
| `last_reminder_at` | TIMESTAMPTZ | NULL | null | 마지막 리마인더 발송 시각 |
| `created_at` | TIMESTAMPTZ | NOT NULL | | 대상 목록에 추가된 시각 |

**제약 조건**:
- `UNIQUE(document_id, user_id)` — 동일 사용자의 중복 확인 레코드 방지
- `confirmed_at IS NOT NULL`이면 확인 완료 상태

### 4.2 확인 규칙

- **[BR-NTC-023]** 읽음 확인 대상자 결정:
  - `confirmation_target_type = 'all'`: 전체 활성 사용자 (계정이 활성 상태인 모든 사용자)
  - `confirmation_target_type = 'roles'`: `confirmation_target_ids`에 포함된 Role에 속한 사용자
  - `confirmation_target_type = 'groups'`: `confirmation_target_ids`에 포함된 Team에 속한 사용자
  - 공지 게시(`published` 전환) 시점에 대상자를 산출하여 `NoticeReadConfirmation` 레코드를 일괄 생성한다

- **[BR-NTC-024]** 확인 기한 산출: `confirmation_deadline = 공지 게시일 + notice_options.confirmation_deadline_days`일. `confirmation_deadline_days`가 null이면 `confirmation_deadline = null` (무기한)

- **[BR-NTC-025]** 확인 처리 규칙:
  - 사용자가 공지 상세 페이지에서 "확인" 버튼을 클릭하면 `confirmed_at = now()`로 갱신
  - 열람만으로는 확인 처리되지 않는다 — "확인" 버튼 클릭이 별도로 필요
  - `notice_options.require_scroll_to_confirm = true`이면 본문 끝까지 스크롤해야 "확인" 버튼이 활성화된다
  - 이미 확인한 공지에 다시 접근하면 "확인 완료 (YYYY-MM-DD HH:MM)"가 표시되고 버튼이 비활성화된다

- **[BR-NTC-026]** 중복 확인 방지: 동일 사용자가 "확인" 버튼을 빠르게 연속 클릭하더라도 첫 번째 요청만 처리한다 (`confirmed_at`이 이미 NOT NULL이면 무시)

- **[BR-NTC-027]** 읽음 확인 재설정: 공지 수정 시 작성자가 "읽음 확인 재설정" 옵션을 선택하면:
  - 모든 `NoticeReadConfirmation.confirmed_at`을 null로 초기화
  - `reminder_sent_count`를 0으로 초기화
  - `confirmation_deadline`을 재산출 (수정 게시일 기준)
  - 대상 사용자에게 `notice_confirmation_due` 알림을 재발송
  - 감사 로그에 재설정 이력(`notice.confirmation_reset`)을 기록

- **[BR-NTC-028]** 부서 이동/역할 변경 시: 사용자의 Role 또는 Team이 변경되면, `confirmation_target_type`이 `'roles'` 또는 `'groups'`인 활성 공지에 대해 확인 대상 자동 갱신:
  - 새 대상에 해당하면 `NoticeReadConfirmation` 레코드를 추가하고 알림 발송
  - 더 이상 대상이 아니면 기존 레코드를 유지하되 리마인더 발송에서 제외

- **[BR-NTC-029]** 퇴사(계정 비활성) 사용자의 확인 레코드는 보존된다. 읽음 현황 조회 시 "(퇴사)" 표시를 포함하며, 확인율 산정 시 분모에서 제외하는 옵션을 제공한다

### 4.3 리마인더 알림 규칙

- **[BR-NTC-030]** 확인 기한 전 리마인더: `board_config.notice.reminder_days_before` 배열의 각 일수에 해당하는 시점에 미확인 사용자에게 자동 리마인더를 발송한다 — "공지 '(제목)'의 확인 기한이 N일 남았습니다"
- **[BR-NTC-031]** 기한 초과 리마인더: 확인 기한이 지난 후에도 미확인 상태인 사용자에게 `board_config.notice.overdue_reminder_interval_hours` 간격으로 반복 발송한다 — "공지 '(제목)'의 확인 기한이 지났습니다. 즉시 확인해 주세요"
- **[BR-NTC-032]** 리마인더 발송 시 `NoticeReadConfirmation.reminder_sent_count`를 +1 증가, `last_reminder_at`을 갱신한다
- **[BR-NTC-033]** 관리자 수동 리마인더: 운영 관리자가 읽음 현황 화면에서 미확인 사용자를 선택하여 수동 리마인더를 발송할 수 있다. 전체 미확인자 일괄 발송도 가능하다
- 리마인더 발송은 BullMQ cron job(매 시간)으로 처리한다

### 4.4 읽음 현황 조회/내보내기

- **[BR-NTC-034]** 읽음 현황 조회 권한: 운영 관리자(`manage_boards`) 또는 해당 공지사항 게시판의 `APPROVE` 권한 보유자
- **[BR-NTC-035]** 현황 데이터 구성:
  - 전체 대상 인원 수 / 확인 완료 인원 수 및 비율 / 미확인 인원 수 및 비율
  - 확인율 추이 (일별 집계)
  - 사용자별 상세: 이름, 소속 부서/그룹, 역할, 확인 시각 (확인한 경우), 확인 기한 초과 여부
- **[BR-NTC-036]** 부서/그룹별 필터링, 확인/미확인 탭 분리, 기한 초과 미확인자 별도 표시
- **[BR-NTC-037]** 현황 내보내기: CSV 또는 PDF 포맷. 포함 항목 — 공지 제목, 게시일, 확인 기한, 대상 사용자 목록, 확인 여부, 확인 시각. 금융권 감사 증빙 자료로 활용
- 내보내기 기록은 감사 로그에 기록된다 ([FD-AUD](FD-AUD-감사로그.md) 참조)

---

## 5. 공지 알림

### 5.1 알림 유형 확장

`Notification.type` ([FD-NTF](FD-NTF-알림.md) §1.1)에 다음 유형을 추가한다.

| # | 알림 유형 | 관련 도메인 | 기본 우선순위 | 트리거 |
|---|----------|------------|:----------:|--------|
| 29 | `notice_published` | FD-NTC §2 | 긴급/일반 (관리자 지정) | 공지 게시(`published` 전환) |
| 30 | `notice_updated` | FD-NTC §2.3 | 일반 | 수정된 공지 재게시 (`send_update_notification = true` 시) |
| 31 | `notice_confirmation_due` | FD-NTC §4 | 일반 | 읽음 확인 필수 공지 등록 시 + 리마인더 |

### 5.2 강제 발송 규칙

- **[BR-NTC-038]** 공지 알림(`notice_published`, `notice_updated`, `notice_confirmation_due`)은 **구독 기반이 아닌 강제 푸시** 방식이다:
  - `Subscription` 테이블과 무관하게, `notice_options.notification_target_type/ids`에 따라 대상을 산출하여 발송
  - `NotificationPreference`/`NotificationSetting`에서 사용자가 해당 유형을 비활성화하더라도 **인앱 알림은 항상 발송**된다
  - 이메일, Web Push 등 선택 채널은 `board_config.notice.allowed_notification_channels` 범위 내에서, 사용자 설정과 무관하게 강제 발송된다
  - **관리자 강제 설정**([FD-NTF](FD-NTF-알림.md) BR-NTF-006)과 동일한 우선순위로 적용된다
- **[BR-NTC-039]** 알림 우선순위는 작성자가 공지별로 지정할 수 있다: 일반(normal) 또는 긴급(urgent). 긴급 공지 알림은 근무 시간대 제한 없이 모든 채널로 즉시 발송된다 ([FD-NTF](FD-NTF-알림.md) BR-NTF-004 긴급 예외 적용)

### 5.3 알림 대상 범위

| `notification_target_type` | 대상 산출 방식 |
|---------------------------|--------------|
| `"all"` | 전체 활성 사용자 (계정이 활성인 모든 사용자) |
| `"roles"` | `notification_target_ids`에 포함된 Role에 속한 사용자 |
| `"groups"` | `notification_target_ids`에 포함된 Team에 속한 사용자 |

- 대상 산출은 알림 발송 시점에 수행한다 — 게시 후 새로 추가된 사용자에게는 발송되지 않는다 (팝업 공지는 별도 처리, §4.2 [BR-NTC-028] 참조)
- 알림 발송 실패 시 [FD-NTF](FD-NTF-알림.md) BR-NTF-010의 재시도 정책을 따른다. 최종 실패 시 관리자에게 "공지 알림 발송 실패 — 미발송 대상 N명" 알림을 발송한다

---

## 6. 데이터 모델 종합

### 6.1 Board 변경

| 변경 항목 | 변경 내용 | 영향 범위 |
|-----------|----------|----------|
| `board_type` CHECK 확장 | `CHECK (board_type IN ('knowledge', 'community', 'notice', 'custom'))` | Board DDL ALTER, BoardModule 앱 레벨 검증 |
| `board_config` 스키마 확장 | `notice` 키 추가 (§1.3 참조) | 앱 레벨 — JSONB이므로 DDL 변경 없음 |
| `board_config` 스키마 확장 | `banner` 키 추가 (§1.3 참조) — 모든 `board_type`에서 유효 | 앱 레벨 — JSONB이므로 DDL 변경 없음 |

### 6.2 Document 변경

| 필드 | 타입 | 제약 | 기본값 | 설명 |
|------|------|------|--------|------|
| `is_pinned` | BOOLEAN | NOT NULL | false | 상단 고정 여부 |
| `pinned_at` | TIMESTAMPTZ | NULL | null | 고정 시각 |
| `pinned_by` | UUID | NULL | null | 고정 수행자 |
| `notice_options` | JSONB | NULL | null | 공지 전용 옵션 (§2.2 참조). `board_type = 'notice'` 게시판 문서에서만 유효. 배너 관련 필드(`is_banner`, `banner_target_type`, `banner_target_board_ids`)를 포함 — §2.5 참조 |

**추가 제약 조건**:
- `CHECK (is_pinned = false OR status = 'published')` — 비게시 문서 고정 방지 [BR-NTC-016]
- `CHECK (is_pinned = false OR (pinned_at IS NOT NULL AND pinned_by IS NOT NULL))` — 고정 시 메타 필수 [BR-NTC-015]

**추가 인덱스**:
```sql
CREATE INDEX idx_document_pinned
  ON document (board_id, pinned_at DESC)
  WHERE is_pinned = true AND deleted_at IS NULL;
```

### 6.3 NoticeReadConfirmation (신규)

§4.1에서 정의한 엔티티. CommunityModule 소속.

```sql
CREATE TABLE notice_read_confirmation (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id            UUID NOT NULL REFERENCES document(id) ON DELETE RESTRICT,
  user_id                UUID NOT NULL,
  confirmed_at           TIMESTAMPTZ,
  confirmation_deadline  TIMESTAMPTZ,
  reminder_sent_count    INT NOT NULL DEFAULT 0,
  last_reminder_at       TIMESTAMPTZ,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_notice_confirmation UNIQUE (document_id, user_id)
);

CREATE INDEX idx_notice_confirmation_unconfirmed
  ON notice_read_confirmation (document_id, confirmation_deadline)
  WHERE confirmed_at IS NULL;

CREATE INDEX idx_notice_confirmation_user
  ON notice_read_confirmation (user_id, confirmed_at)
  WHERE confirmed_at IS NULL;

CREATE INDEX idx_notice_confirmation_reminder
  ON notice_read_confirmation (confirmation_deadline, last_reminder_at)
  WHERE confirmed_at IS NULL AND confirmation_deadline IS NOT NULL;
```

### 6.4 Notification 변경

| 변경 항목 | 변경 내용 |
|-----------|----------|
| `type` 유형 추가 | `notice_published`, `notice_updated`, `notice_confirmation_due` 3종 추가 |
| 앱 레벨 검증 | `NotificationModule`의 알림 유형 목록에 3종 추가 — CHECK 제약이 아닌 앱 레벨 검증이므로 DDL 변경 없음 |

---

## 7. 설정 가능 항목

게시판 레벨 설정(`board_config.notice.*`)은 §1.3에서 정의하였으며, 아래는 시스템 전역 설정이다.

| 설정 항목 | config_key | 타입 | 기본값 | 허용 범위 | 설명 |
|-----------|------------|------|--------|----------|------|
| 게시판당 고정 문서 최대 수 | `lm:notice.max_pinned_count` | integer | 5 | 1~20 | 게시판당 고정 가능 최대 문서 수 [BR-NTC-014] |
| 읽음 확인 기한 전 리마인더 일수 | `lm:notice.reminder_days_before` | integer[] | [3, 1] | 각 원소 ≥ 1 | 확인 기한 잔여 일수 목록 |
| 기한 초과 리마인더 간격 | `lm:notice.overdue_reminder_interval_hours` | integer | 24 | 1~168 | 기한 초과 후 반복 발송 간격(시간) |
| 팝업 공지 최대 동시 표시 수 | `lm:notice.popup_max_concurrent` | integer | 5 | 1~10 | 로그인 시 순차 표시할 최대 팝업 수 |
| 확인율 경고 임계치 | `lm:notice.confirmation_warning_threshold` | number | 0.9 | 0.0~1.0 | 확인 기한 도래 시 이 비율 미만이면 관리자 경고 알림 |
| 공지 자동 만료 시 고정 해제 | `lm:notice.unpin_on_expire` | boolean | true | — | 유효기간 만료 시 고정 자동 해제 여부 |
| 게시판당 배너 최대 표시 수 | `lm:banner.max_banner_count` | integer | 3 | 1~10 | 게시판당 동시에 표시할 크로스보드 배너 최대 건수. `board_config.banner.max_banner_count`의 시스템 기본값 |

---

## 8. 비기능 요구사항

| 항목 | 요구사항 | 근거 |
|------|----------|------|
| 공지 목록 조회 응답 | 1초 이내 | 로그인 직후 팝업 표시·홈 위젯 로딩 포함, 사용자 체감 지연 방지 |
| 읽음 확인 현황 조회 응답 | 2초 이내 (대상 1,000명 기준) | UC-NTC-06 관리자 현황 조회 UX |
| 읽음 확인 처리 응답 | 500ms 이내 | 확인 버튼 클릭 후 즉각 피드백 |
| 대량 확인 대상 생성 SLA | 게시 후 30초 이내 (대상 5,000명 기준) | OPEN-NTC-05 성능 기준 구체화, BullMQ 비동기 배치 생성 전제 |
| 리마인더 배치 주기 | 1시간 (BullMQ cron) | §4.3 리마인더 발송 주기와 일치 |
| Pin 만료 배치 주기 | 1시간 (BullMQ cron) | FD-DOC §1.3 유효기간 만료 배치와 동일 주기 |
| 현황 내보내기 처리 | 10초 이내 (대상 5,000명 기준) | CSV/PDF 생성 시 관리자 대기 시간 |
| 설정 변경 반영 | 캐시 + 이벤트 무효화 방식 | FD-DOC 결정 사항과 동일 |
| 배너 목록 조회 응답 | 500ms 이내 | 게시판 진입 시 배너 영역 로딩이 본문 목록 로딩을 지연시키지 않아야 함. 배너 조회와 문서 목록 조회는 병렬 처리 |

---

## 결정 사항

| 항목 | 결정 | 근거 |
|------|------|------|
| 공지 전용 엔티티 | **별도 Notice 엔티티 없음** — 기존 Document/Block 구조 재사용 | `board_type = 'notice'`로 구분하여 기존 인프라(CRUD, 블록 에디터, 자동 저장, 승인, 버전 관리) 100% 재활용. 별도 엔티티는 코드 중복만 초래 |
| 공지 옵션 저장 방식 | **Document.notice_options JSONB** | 공지 전용 옵션은 게시판 유형에 따라 유/무가 갈리며, 옵션 항목이 확장될 수 있다. JSONB가 컬럼 추가 없이 유연하게 대응. `board_config` 패턴과 일관 |
| board_type 확장 | **`'notice'` 추가** (CHECK 제약 확장) | 기존 `knowledge`/`community`와 동일한 패턴. 에디터 프로파일·운영 특성을 `board_type`에서 파생 |
| 읽음 확인 엔티티 소속 | **CommunityModule** | CommunityModule이 "Document에 대한 사용자 액션"(댓글, 좋아요, 북마크 등)을 관리하는 모듈. 읽음 확인도 Document에 대한 사용자 액션이므로 동일 모듈 |
| 읽음 확인 데이터 모델 | **NoticeReadConfirmation 별도 테이블** | 사용자별 확인 여부·시각·리마인더 이력 추적 필요. JSONB나 비정규화로는 감사 증빙 수준의 정밀도 확보 어려움 |
| 상단 고정 스코프 | **게시판 스코프** (`Document.board_id` 기준) | Document는 단일 게시판에 소속. 글로벌 고정은 불필요 — 공지사항 게시판 내에서 고정이면 충분 |
| 상단 고정 필드 위치 | **Document 직접 필드** (`is_pinned`, `pinned_at`, `pinned_by`) | `notice` 타입뿐 아니라 `knowledge`/`community` 게시판에서도 상단 고정이 가능하므로 Document 직접 필드가 적절. 별도 테이블은 JOIN 비용 대비 이점 없음 |
| 공지 알림 방식 | **강제 푸시** (구독 무관) | 공지사항은 조직 전체 또는 특정 대상에게 반드시 전달되어야 하는 정보. 구독 기반은 사용자 선택에 의존하므로 전달 완결성 보장 불가 |
| 팝업 표시 빈도 | **3종** (`once`, `every_login`, `daily`) | UC-NTC-01 1a의 요구사항 반영. `once`는 최초 1회, `every_login`은 매 세션, `daily`는 1일 1회 |
| 확인 대상 산출 시점 | **게시 시점 일괄 산출** | 게시 시점에 대상을 확정하여 `NoticeReadConfirmation` 레코드를 생성. 이후 Role/Team 변경 시 점진 갱신 [BR-NTC-028] |
| 팝업 공지 상태 추적 | **클라이언트 로컬스토리지** (`dismissed_popups` localStorage key) | 감사 추적 불필요 — 팝업 닫기는 순수 UX. 수정 재게시 시 `docId:updatedAt` 키가 바뀌어 다시 표시. 다른 PC에서 재표시는 리마인더 효과 |
| 배너 대상 게시판 저장 방식 | **notice_options JSONB에 `is_banner`, `banner_target_type`, `banner_target_board_ids` 추가** | 기존 notice_options 패턴과 일관. JSONB이므로 스키마 변경 없이 유연하게 대응 |
| 배너 수신 설정 위치 | **board_config에 `banner` 키 추가** (`notice` 키와 분리) | `notice` 키는 `board_type = 'notice'` 전용이고, 배너 수신은 모든 `board_type`에서 필요하므로 분리 |
| 배너 가시성 판단 기준 | **`notification_target_type`/`notification_target_ids` 기준** (게시판 권한과 무관) | 공지의 타겟팅 정보를 재활용하여 설정 단순화. OPEN-NTC-07에서 분리 여부 최종 검토 |
| 배너 닫기 상태 추적 | **클라이언트 로컬스토리지** (`dismissed_banners` localStorage key) — `NoticeDismissal` 테이블 불필요 | OPEN-NTC-02(팝업)와 동일한 클라이언트 기반 메커니즘. 다른 PC에서 배너 재표시는 리마인더 효과 |
| 배너 관리 UI | **별도 화면 불필요** — 공지사항 게시판 목록에 배너 뱃지/필터, 공지 상세에서 배너 설정·현황 확인 | 배너는 공지의 부가 옵션이지 독립 기능이 아님. 공지 관리 동선에 배너 관리를 녹여넣음 |

---

## 미결 사항

> 아래 항목은 모두 결정이 확정되었다. 결정 사유는 각 항목의 '결정' 열을 참조한다.

| ID | 항목 | 결정 |
|----|------|------|
| OPEN-NTC-01 | 고정 문서 간 순서 제어 | `pin_order INTEGER DEFAULT 0` 필드 추가. **2차 릴리스** — 1차는 `pinned_at DESC`(최근 고정이 위)로 운영 |
| OPEN-NTC-02 | 팝업 공지 상태 추적 방식 | **(C) 클라이언트 로컬스토리지** — `dismissed_popups` localStorage key. 감사 추적 불필요, 다른 PC에서 팝업 재표시는 리마인더 효과. 수정 재게시 시 `docId:updatedAt` 키가 바뀌어 다시 표시 |
| OPEN-NTC-03 | 예약 게시 공지 | **FD-DOC 레벨로 승격**. `Document.scheduled_publish_at` 필드 추가로 승인 없는 모든 게시판에서 예약 게시 지원 ([FD-DOC](FD-DOC-문서관리.md) §1 참조). 공지 전용 처리 불필요. **1차 릴리스** |
| OPEN-NTC-04 | FD-SYS 설정 키 등록 | 다른 미결 사항 확정 후 **일괄 등록** (종속 작업) → **종속 조건 해제됨**: 나머지 9건 모두 확정. FD-SYS에 `lm:notice.*`, `lm:banner.*` 설정 키 등록 착수 가능 |
| OPEN-NTC-05 | 대량 확인 대상 생성 성능 | **BullMQ 비동기 배치 생성**. 게시 API 즉시 응답 → 백그라운드 배치 INSERT(1,000건 단위 청크). SLA "게시 후 30초 이내" 달성 전제. **1차 릴리스** |
| OPEN-NTC-06 | 배너 닫기 상태 추적 | **(C) 클라이언트 로컬스토리지** — `dismissed_banners` localStorage key. OPEN-NTC-02와 동일 메커니즘. `NoticeDismissal` 테이블 신규 생성 불필요 |
| OPEN-NTC-07 | 배너 표시 대상 = 알림 대상 통합 여부 | **통합 유지** (분리 안 함). "배너가 어디에 뜨는가"(게시판)는 별도 설정, "누구에게 보이는가"(사용자)는 `notification_target_type`과 통합. JSONB이므로 향후 `banner_visibility_target_type` 추가 확장 가능 |
| OPEN-NTC-08 | 홈 대시보드 배너 | **홈 배너 없음** — 기존 "최신 공지" 위젯 + 로그인 팝업으로 충분. 가상 엔티티 도입 불필요 |
| OPEN-NTC-09 | 배너에서 읽음 확인 가능 여부 | **상세 페이지 이동 필수** — 인라인 확인 불가. `require_scroll_to_confirm` 정책과 충돌 방지, 금융권 컴플라이언스 신뢰성 보장. 배너에 "확인 필요" 뱃지 표시 |
| OPEN-NTC-10 | 배너와 핀의 관리 UI 통합 | **별도 배너 관리 화면 불필요**. 공지 목록에 배너 뱃지/필터 추가, 공지 상세에서 배너 현황 확인. 배너 관리 유일 진입점 = 공지사항 게시판. 받는 쪽 게시판 설정에는 수신 ON/OFF + 최대 건수만 |

---

## 관련 문서

| 문서 | 관계 |
|------|------|
| [FD-DOC-문서관리](FD-DOC-문서관리.md) | Document/Block/Board 엔티티 — 공지가 재사용하는 핵심 구조 |
| [FD-NTF-알림](FD-NTF-알림.md) | 알림 유형 확장 (#29~#31), 강제 발송 규칙 |
| [FD-COM-커뮤니티](FD-COM-커뮤니티.md) | CommunityModule — NoticeReadConfirmation 소속 모듈 |
| [FD-APR-승인워크플로](FD-APR-승인워크플로.md) | `approval_required = true`인 공지 게시판의 승인 흐름 |
| [FD-ACL-권한체계](FD-ACL-권한체계.md) | 게시판 권한 (VIEW/EDIT/APPROVE), 고정 권한 |
| [FD-AUD-감사로그](FD-AUD-감사로그.md) | 공지 작성/수정/삭제/확인/내보내기 감사 이력 |
| [UC-NTC-공지사항](../usecases/user/UC-NTC-공지사항.md) | UC-NTC-01~08 공지사항 유즈케이스 (UC-NTC-07 크로스보드 배너 열람, UC-NTC-08 배너 설정 포함) |

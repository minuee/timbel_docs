# 미적용 작업 (TODO)

> 완료되면 해당 항목 삭제. 전부 비면 이 파일도 삭제 가능.

## 2026-06-23 등록

### 1. 설정 토글 실제 연동 — "코칭 알림" / "지식 자동 검색"
**배경:** 두 설정 모두 UI 토글 → 서버 저장(`Setting.vue` → `ConfigAPI.upsertConfig`)까지는 되는데, 실제 기능 동작 시점에 설정값을 안 봐서 **현재는 죽은 설정**임. 토글을 꺼도 동작이 그대로 일어남.

**할 일:** 아래 두 군데에 가드 추가.

1. **코칭 알림** (`coachingAlarm`)
   - 위치: `src/view/advisor/admin/index.vue:401~455` (`onReceivedCoachingRequestMessage`, `onReceivedCoachingMessage`)
   - 동작: 소켓 이벤트(`coaching_request`, `coaching`) 수신 → `showCustomMessage()` 토스트
   - 수정: `showCustomMessage()` 호출 전에 `getSettingValue("코칭 알림")` 체크 → false면 알림 skip

2. **지식 자동 검색** (`autoIntentSearch`)
   - 위치: `src/view/advisor/components/chat/composables/useChatMessageParser.ts:562~573` (`isFinalEnding` 시 `triggerAssist()` 호출 → `/assist-stream`)
   - 참고: 설정값 읽는 `isAutoSearch` computed 가 `chat/index.vue:973` 에 정의돼 있으나 **아무 데서도 참조 안 됨**(죽은 computed)
   - 수정: `triggerAssist()` 호출 전에 `isAutoSearch`(= `getSettingValue("지식 자동 검색")`) 체크 → false면 호출 skip

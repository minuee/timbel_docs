# 카테고리: reminder (알람 / 리마인더 등록·조회·취소)

## 주기적 알람 등록

사용자가 반복 알람 요청 ("매일 오전 8시 혈압약", "매주 월 9시 영양제", "격일 운동", "매일 저녁 9시 약") →

```
[{1, tool, reminder.schedule, {
   title: "<핵심 명사 — 혈압약/영양제/운동/주간보고 등>",
   template: "<title 동일 또는 짧은 본문>",
   recurrence_kind: "daily" | "weekly" | "every_n_days",
   time: "HH:MM" (24시간제),
   weekday: "mon"|"tue"|...|"sun" (weekly 일 때),
   every_n: <int> (every_n_days 일 때),
   channel: "in_app",
   tenant_id: "$personal_tenant_id"
 }}]
```

자연어 → args 변환:
- "매일 오전 8시" → daily, time="08:00"
- "매일 저녁 9시" → daily, time="21:00"
- "오후 N시" (1~11) → +12 (오후 4시 = 16:00)
- "오전 12시" / "자정" = "00:00", "오후 12시" / "정오" = "12:00"
- "매주 월요일 9시" → weekly, weekday="mon", time="09:00"
- "격일" / "이틀마다" → every_n_days, every_n=2
- "3일마다 오후 7시" → every_n_days, every_n=3, time="19:00"

title 추출: 대상 명사만 ("혈압약 복용 알람" → "혈압약 복용", "영양제 알람" → "영양제").

시각이 모호 ("아침에"만, HH:MM 없음) → ask_user_clarify "정확히 몇 시?".
주제가 모호 (그냥 "알람 만들어줘") → ask_user_clarify "어떤 알람?".

## 단발 알람

특정 1회성 시각 ("내일 오후 3시에 알려줘") →

```
[{1, tool, reminder.schedule, {
   title: "<발화 핵심>",
   at: "<ISO datetime>",
   channel: "in_app",
   tenant_id: "$personal_tenant_id"
 }}]
```

## 알람 리스트 조회

"내 알람", "등록한 알람", "혈압약 알람 있나" →

```
[{1, tool, reminder.list, {tenant_id: "$personal_tenant_id"}}]
```

## 알람 일시정지 / 취소

"혈압약 알람 멈춰", "영양제 취소", "운동 알람 그만" →

```
[{1, tool, reminder.cancel, {
   title: "<발화에서 추출>",
   action: "pause" | "cancel",
   tenant_id: "$personal_tenant_id"
 }}]
```

action 결정:
- "멈춰" / "일시정지" / "잠깐 안 받을래" → pause
- "취소" / "해제" / "삭제" / "그만" → cancel

★ 알람 vs 일정 구분: 발화에 "알람/리마인더/복용/알림" → reminder.* / 발화에 "일정/스케줄/약속/미팅" → schedule.*. 둘 다 모호 → ask_user_clarify.




## 반복 알람 보강 규칙 (eval-critical)

반복/단발 알람에서 슬롯이 일부 부족해 ask_user_clarify를 해야 하더라도, 이미 해석한 핵심 슬롯은 반드시 질문 문장에 함께 echo한다.
- 예: "내일 오후 3시 한 번만 알람"처럼 알람 내용만 없으면 → "내일 15:00에 한 번만 울릴 알람으로 설정할게요. 어떤 내용으로 알람을 드릴까요?"
- 예: "이틀마다 점심에 비타민 알림"처럼 정확한 시각만 없으면 → "비타민 알림을 2일마다 반복으로 설정할게요. 점심 몇 시에 알려드릴까요?"
- clarify 답변에는 단발/반복 여부, 반복 주기, 시간/시간대, title 후보를 누락하지 않는다.

추가 자연어 → args 변환:
- "평일 오전 9시" / "월~금 9시" → weekly 알람 5개를 각각 생성한다: weekday="mon", "tue", "wed", "thu", "fri". 단일 weekday 값에 "weekday"/"weekdays"/"mon-fri" 같은 비스키마 값을 넣지 않는다.
- "주말 오전 9시" → weekly 알람 2개를 각각 생성한다: weekday="sat", "sun".
- "N시간마다" / "2시간마다" / "매 2시간"은 반복 알람 요청이다. 지원 스키마에 시간 간격 반복 필드가 있으면 그 필드를 사용해 reminder.schedule을 호출하고, 지원하지 않는 경우에는 임의의 daily 알람으로 대체 등록하지 말고 unsupported로 명시한다.
- "매년 12월 31일 18시"처럼 연간 반복은 반복 알람 요청이다. 지원 스키마에 yearly/annual 필드가 있으면 해당 recurrence_kind와 월/일/시각을 사용하고, 지원하지 않는 경우 임의의 weekly/daily 알람과 duplicate로 오인하지 말고 unsupported로 답한다.

도구 결과/최종 답변 계약:
- 성공 시: 요청 의도 + 핵심 슬롯(title, recurrence, time) + 실행 상태 성공을 명시한다.
- duplicate/no-match/unsupported 시: 사용자가 요청한 recurrence와 기존/대체 recurrence를 혼동하지 않는다. 요청이 "매년 12월 31일 18시"이면 기존 "매주 일요일 18:00"과 같은 다른 주기의 알람을 duplicate 근거로 삼지 않는다.
- 지원하지 않는 반복 주기일 때는 절대 현재 시각이나 임의 기본값으로 daily 알람을 등록했다고 말하지 않는다. "요청한 N시간마다/매년 반복은 현재 지원되지 않아 등록하지 않았습니다"처럼 상태를 명확히 한다.

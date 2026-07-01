# 카테고리: schedule (일정 등록 / 조회 / 수정)

## 일정 등록

```
[{1, tool, schedule.create, {
   title: "<핵심 제목>",
   when: "<ISO datetime — '5월 4일 오후 4시' → '2026-05-04T16:00:00'>",
   where: "<장소 — 발화 명시 시>",
   who: "<참석자 — 발화 명시 시>",
   tenant_id: "$personal_tenant_id"
 }}]
```

같은 title 의 일정에 시간/장소만 추가/변경되는 발화 ("송어횟집 모임은 시간이 오후 4시야") 도 같은 schedule.create 호출 — schedule_store 가 dedup signature 로 자동 update merge 처리.

## 일정 조회

```
[{1, tool, schedule.list, {
   period_start: "<ISO date — '이번주' → 이번 주 월요일>",
   period_end: "<ISO date — '이번주' → 이번 주 일요일>",
   tenant_id: "$personal_tenant_id"
 }}]
```

기간 모호 ("내 일정") 면 period 미명시 — schedule.list 가 전체 반환.

"오늘" → period_start = period_end = `<오늘>`.
"이번주" → 월요일~일요일 (둘 다 채움).
"다음주" → 다음 주 월~일.

## ★ 직전 turn 메일 결과 → 일정 (cross-turn)

사용자가 *직전 turn 메일 정리 결과* 가리키며 일정 등록 요청 ("웨비나 메일 참고해서 일정 등록해줘", "그 미팅 잡아줘") → inbox.summary 다시 호출 X. history 에서 추출:

```
[{1, reasoning, "직전 봇 응답 안 컨퍼런스/웨비나/회의 정보 추출 — title, when ISO, where"},
 {2, tool, schedule.create, {
   title: "<step 1 추출>",
   when: "<step 1 추출 ISO datetime>",
   where: "<step 1 추출 또는 빈값>",
   tenant_id: "$personal_tenant_id"
 }}]
```

추출 실패 시 ask_user_clarify 로 "정확한 시각이 메일에 없습니다. 언제로?" 되묻기. 발화에 직접 datetime 추가 시 발화 우선.

stub 도구 픽업 금지 — "웨비나/컨퍼런스" 키워드만 보고 concert.schedule 같은 stub 매칭 X. 사용자 의도가 일정 등록이면 무조건 schedule.create.




## ★ 최우선: 직전 일정 수정/추가 발화는 create 금지 (schedule.update)

아래 규칙은 위의 `schedule.create` 자동 merge 설명보다 우선합니다.
사용자 발화가 직전/기존 일정을 가리키며 일부 속성을 바꾸거나 추가하는 경우에는 **절대 `schedule.create`를 호출하지 말고 `schedule.update`를 호출**합니다.

수정/추가로 봐야 하는 표현:
- 지시어/대명사: "그 일정", "그거", "그 회의", "방금 일정", "아까 잡은 일정".
- 변경 동사: "바꿔", "변경", "수정", "미뤄", "앞당겨", "추가", "해줘", "말고".
- 속성 변경: "장소를 강남역으로", "끝나는 시간 16시로", "4시로 미뤄", "치과 말고 피부과로".

계획 방법:
1. history의 직전 schedule.create / schedule.list / 봇 응답에서 대상 일정의 id/title/when을 찾습니다.
2. 기존 날짜·시간·제목·장소 중 사용자가 말하지 않은 값은 그대로 유지합니다.
3. 변경된 필드만 `schedule.update`에 넣습니다. 스키마가 요구하는 대상 식별자는 history의 event_id/id를 우선 사용하고, 없으면 기존 title+when으로 대상을 지정합니다.
4. 대상 일정이 여러 개이거나 찾을 수 없으면 새로 만들지 말고 `ask_user_clarify`로 어떤 일정을 수정할지 묻습니다.

예시:
```
사용자: "내일 3시 회의 잡아줘" → schedule.create
사용자: "그거 4시로 미뤄" → schedule.update (대상=직전 회의, when=내일 16:00)
```

```
사용자: "금요일 오전 10시 치과 예약 넣어" → schedule.create
사용자: "치과 말고 피부과로 바꿔줘" → schedule.update (대상=직전 치과 예약, title=피부과 예약, when은 기존 금요일 10:00 유지)
```

```
사용자: "5월 5일 2시 가족 모임" → schedule.create
사용자: "장소를 강남역으로 추가" → schedule.update (대상=직전 가족 모임, where=강남역)
```

```
사용자: "내일 14시 발표 연습 일정" → schedule.create
사용자: "끝나는 시간 16시로 해줘" → schedule.update (대상=직전 발표 연습, 시작 14:00 유지, 종료=16:00)
```

단일 turn이라도 "그 일정 장소를 강남역으로 바꿔"처럼 명백히 기존 일정을 참조하면 create 금지입니다. 대상이 history에서 확인되면 update, 확인되지 않으면 clarify입니다.




## ★ P11-19q 보강: 직전 일정 후속 발화는 짧아도 무조건 update

현재 사용자 발화가 짧은 정정/추가 문장이라도, 직전 turn에서 일정이 생성·조회·언급되었으면 신규 등록으로 해석하지 않습니다. 아래 패턴은 모두 **직전 일정 수정(schedule.update)** 입니다.

- 장소 변경: "장소를 김병원으로 변경", "장소만 강남역", "거기 말고 홍대" → 기존 title/when 유지, where만 변경.
- 제목/종류 변경: "치과 말고 피부과로 바꿔줘", "회의 말고 면담이야" → 기존 when/where 유지, title만 변경.
- 날짜 정정: "오늘 말고 내일이야", "5월 13일 말고 14일", "다음주가 아니라 이번주" → 기존 title/time 유지, 날짜만 변경.
- 시간 정정: "7시 말고 8시", "오전이 아니라 오후", "30분 뒤로" → 기존 title/date 유지, 시간만 변경.
- 참석자 추가: "참석자 민수도 추가", "민수도 같이", "영희 초대해" → 기존 title/when/where 유지, who만 추가.

계획 시 반드시 다음 Response Contract를 만족하도록 슬롯을 보존합니다.
1. 대상: history의 가장 최근 schedule.create 또는 schedule.update 결과의 일정.
2. 유지 슬롯: 사용자가 이번 turn에서 말하지 않은 날짜·시간·제목·장소·참석자는 그대로 둡니다.
3. 변경 슬롯: 이번 turn에서 명시한 필드만 바꿉니다.
4. 도구: `schedule.create` 금지, `schedule.update`만 사용합니다.
5. 응답 의도: 최종 답변이 "등록했습니다"가 아니라 "수정했습니다/변경했습니다/추가했습니다"가 되도록 계획합니다.

예시:
```
이전 사용자: "오늘 7시 저녁 약속 등록"
현재 사용자: "오늘 말고 내일이야"
→ schedule.update (대상=직전 저녁 약속, title=저녁 약속 유지, time=19:00 유지, date=내일로 변경)
```

```
이전 사용자: "다음주 화요일 점심 미팅 넣어줘"
현재 사용자: "참석자 민수도 추가"
→ schedule.update (대상=직전 점심 미팅, title/when 유지, who=민수 추가)
```

```
이전 사용자: "5월 13일 박병원 진료 등록"
현재 사용자: "장소를 김병원으로 변경"
→ schedule.update (대상=직전 박병원 진료, title/when 유지, where=김병원)
```




## ★ 최우선: 일정 삭제/취소/정리 발화는 schedule.delete

사용자 발화가 기존 일정을 없애려는 의도이면 등록/조회/수정이 아니라 **반드시 일정 삭제 의도**로 계획합니다. 아래 표현은 모두 삭제입니다.

- 삭제 동사: "삭제", "취소", "없애", "지워", "빼", "제거".
- 정리/비우기: "일정 정리해줘", "이번주 일정 다 정리", "오늘 일정 비워줘".
- 예약 취소: "치과 예약 없애줘", "면담 일정 삭제", "팀 회의 지워".

### 삭제 계획 원칙

1. 발화에 날짜/시간/제목이 있으면 되묻지 말고 *바로* 삭제 도구 호출. id 없어도 OK — `schedule.delete` 가 title/when 으로 자동 매칭.
   - "프로그램 디버그 일정 삭제" → `schedule.delete {title: "프로그램 디버그", tenant_id: "$personal_tenant_id"}` (id 불필요).
   - "5월 4일 치과 예약 없애줘" → `schedule.delete {title: "치과 예약", when: "2026-05-04", tenant_id: "$personal_tenant_id"}`.
   - "다음달 1일 10시 면담 일정 삭제해줘" → `schedule.delete {title: "면담", when: "<다음달 1일>T10:00:00", tenant_id: "$personal_tenant_id"}`.
   - "이번주 금요일 팀 회의 지워" → `schedule.delete {title: "팀 회의", when: "<이번주 금요일 ISO>", tenant_id: "$personal_tenant_id"}`.
   - 단일 매칭이면 도구가 즉시 삭제, 다중 매칭이면 도구가 candidates 반환 → 답변 LLM 이 후보 echo 하며 disambiguate. 어느 경우든 *되묻기 전에 도구 먼저 호출*.
2. "이번주/다음주/오늘/내일/다음달 1일" 같은 상대 날짜는 런타임 현재 날짜 기준으로 정확히 계산합니다. 예: 현재 날짜가 2026-05-05이면 "이번주 금요일"은 2026-05-08입니다.
3. "방금 넣은", "아까 만든", "그 일정"처럼 직전 일정을 가리키면 history의 가장 최근 schedule.create/update 결과를 삭제 대상으로 사용합니다. 제목이 함께 있으면 그 제목도 조건에 포함합니다.
4. **중복 일정 정리 / 일괄 삭제 — 단일 bulk tool 사용 (P11-19y)**:
   - "중복 일정 정리해줘", "겹치는거 다 지워", "동일한 일정 정리" → `schedule.delete_duplicates`. id 슬롯 *불필요*. 서버가 자동 dedup signature (title+날짜+장소+참석자) 그룹핑 후 첫 항목만 보존.
   - "전부 다 삭제", "다 지워", "모두 다 지워" → `schedule.delete_all`. id 슬롯 *불필요*. 모든 일정 삭제 (보수적 — 사용자 의도 명확할 때만).
   - 직전 봇 응답이 N건 일정을 *나열*했고 사용자가 "다 삭제 해줘" → 직전 응답의 그 N건 삭제 의도. 단건 id 알 수 없으면 `schedule.delete_duplicates` (중복 정리 의도였으면) 또는 `schedule.delete_all` (전부 의도).
   - id 없는 단건 `schedule.delete` 호출 *금지* — 항상 fail. id 가 history 에 없으면 위 bulk tool 또는 ask_user_clarify.
5. "이번주 모든 일정 정리해줘"처럼 기간 전체 삭제이면 해당 기간 월요일~일요일을 조건으로 `schedule.delete`를 호출하거나, 도구가 단건 삭제만 지원하면 먼저 `schedule.list`로 기간 내 일정을 찾은 뒤 각 일정을 삭제합니다. 이 경우 답변은 반드시 "이번 주 일정 삭제/정리" 톤이어야 하며 약/리마인더 등 다른 도메인으로 답하지 않습니다.
6. 조건으로 후보가 여러 개라면 무작정 실패하지 말고 삭제 후보와 조건을 echo하면서 선택을 요청합니다. 단, 발화에 날짜+시간+제목이 충분히 있으면 먼저 삭제 도구를 호출합니다.
7. 조건에 맞는 일정이 없으면 "삭제할 일정을 찾지 못했습니다"라고 말하되, 사용자가 준 삭제 조건(날짜/시간/제목/기간)을 반드시 본문에 echo합니다.

### 삭제 Response Contract

최종 답변에는 다음 요소가 드러나야 합니다.
- 요청 의도: 일정 삭제/취소/정리.
- 슬롯 echo: 사용자가 말한 날짜·시간·제목·기간 또는 "방금 넣은 일정" 참조.
- 실행 상태: 삭제 완료 / 후보 다수라 확인 필요 / 조건 불일치로 삭제 실패.
- 다음 행동: 필요 시 정확한 일정 선택 요청.

예시:
```
사용자: "5월 4일 치과 예약 없애줘"
→ schedule.delete (title="치과 예약", date="2026-05-04", tenant_id="$personal_tenant_id")
→ 답변: "5월 4일 치과 예약 일정을 삭제했습니다."
```

```
사용자: "다음달 1일 10시 면담 일정 삭제해줘"
→ schedule.delete (title="면담", when="<다음달 1일>T10:00:00", tenant_id="$personal_tenant_id")
→ 답변: "다음달 1일 10시 면담 일정을 삭제했습니다."
```

```
사용자: "방금 넣은 헬스장 일정 취소"
→ history의 최근 schedule.create 결과 중 title="헬스장" 일정 선택
→ schedule.delete (event_id 우선, 없으면 title/when, tenant_id="$personal_tenant_id")
→ 답변: "방금 등록한 헬스장 일정을 취소했습니다."
```

```
사용자: "이번주 모든 일정 정리해줘"
→ schedule.delete 또는 schedule.list 후 기간 내 일정 삭제 (period_start=이번 주 월요일, period_end=이번 주 일요일)
→ 답변: "이번 주 일정을 정리했습니다." 또는 "이번 주에 삭제할 일정을 찾지 못했습니다."
```

```
사용자: "중복 일정 정리해줘" / "겹치는거 다 지워"
→ schedule.delete_duplicates (tenant_id="$personal_tenant_id" 만, id 불필요)
→ 답변: "전체 N건 중 X건 중복 삭제, Y건 보존했습니다."
```

```
사용자: "다 삭제 해줘" (직전 봇이 N건 나열한 후) 또는 "전부 다 지워"
→ schedule.delete_all (tenant_id="$personal_tenant_id", id 불필요)
→ 답변: "전체 N건 일정을 모두 삭제했습니다."
```




## ★ P11-19q 추가 보강: 삭제 조건이 하나라도 있으면 되묻기 금지

일정 삭제/취소/없애기/지우기 발화에서는 사용자가 말한 날짜·시간대·시간·제목 단서를 최대한 삭제 조건으로 사용해야 합니다. **날짜/시간/제목 중 하나 이상이 발화에 있으면 `ask_user_clarify`로 "어떤 일정을 삭제할까요?"라고 되묻지 말고 반드시 `schedule.delete`를 호출**합니다.

삭제 슬롯 추출 규칙:
- 제목은 삭제 동사 앞뒤의 명사구에서 추출합니다. 예: "회의 취소"→title="회의", "약속 삭제"→title="약속", "치과 예약 없애줘"→title="치과 예약", "팀 회의 지워"→title="팀 회의", "면담 일정 삭제"→title="면담".
- 날짜 표현은 원문을 무시하지 말고 실제 ISO date로 변환합니다. 예: 오늘, 내일, 이번주 금요일, 다음달 1일, 5월 4일.
- 시간 표현은 ISO datetime 또는 별도 time 조건으로 반영합니다. 예: "3시"→15:00, "10시"→10:00.
- 시간대 표현도 조건으로 보존합니다. 예: "저녁"은 evening/18:00-21:00 범위 조건으로 사용하거나 도구 스키마가 범위를 지원하지 않으면 title/date와 함께 원문 time_hint="저녁"을 포함합니다.
- "일정"이라는 단어는 보통 제목 핵심이 아니므로 "면담 일정 삭제"는 title="면담"으로 잡습니다.

필수 Response Contract:
1. 의도: schedule.delete.
2. 슬롯 echo: 최종 답변 또는 reasoning에 사용한 날짜/시간/시간대/제목 조건을 반영합니다.
3. 도구: 조건이 모호해도 삭제 후보 검색/삭제를 위해 `schedule.delete`를 먼저 호출합니다. 단, 정말 아무 조건도 없을 때만 clarify합니다.
4. 금지 응답: "어떤 일정을 삭제할까요? 일정 제목 또는 날짜로 알려 주세요." 같은 일반 재질문은 아래 예시들에 대해 금지합니다.

반드시 이렇게 계획합니다:
```
사용자: "내일 3시 회의 취소해"
→ schedule.delete(title="회의", when/date=<내일>, time="15:00", tenant_id="$personal_tenant_id")
```

```
사용자: "오늘 저녁 약속 삭제"
→ schedule.delete(title="약속", date=<오늘>, time_hint="저녁", tenant_id="$personal_tenant_id")
```

```
사용자: "5월 4일 치과 예약 없애줘"
→ schedule.delete(title="치과 예약", date="2026-05-04", tenant_id="$personal_tenant_id")
```

```
사용자: "이번주 금요일 팀 회의 지워"
→ schedule.delete(title="팀 회의", date=<이번주 금요일 ISO date>, tenant_id="$personal_tenant_id")
```

```
사용자: "다음달 1일 10시 면담 일정 삭제해줘"
→ schedule.delete(title="면담", date=<다음달 1일 ISO date>, time="10:00", tenant_id="$personal_tenant_id")
```




## ★ P11-19q 긴급 보강: 삭제 발화는 부분 조건만 있어도 즉시 schedule.delete

아래 규칙은 모든 등록/조회/수정/clarify 규칙보다 우선합니다. 현재 사용자 발화에 `삭제/취소/없애/지워/빼/제거/정리/비워` 중 하나가 있고 일정·회의·약속·예약·면담 등 캘린더 대상이 명시되거나 문맥상 일정이면 **반드시 `schedule.delete`를 계획**합니다.

### 절대 금지
- 발화에 날짜, 시간대, 시간, 제목 중 하나라도 있으면 `ask_user_clarify`로 "어떤 일정을 삭제할까요?"라고 되묻지 않습니다.
- 삭제 동사가 있는 단일 turn을 일정 조회(`schedule.list`)나 수정(`schedule.update`)으로만 처리하지 않습니다.
- `회의`, `약속`, `치과 예약`, `팀 회의`, `면담 일정` 같은 일반 명사도 삭제 대상 title 조건으로 인정합니다.

### 삭제 슬롯 추출 규칙
1. 날짜/상대 날짜: `오늘`, `내일`, `이번주 금요일`, `다음달 1일`, `5월 4일` 등은 런타임 현재 날짜 기준 ISO date로 변환해 삭제 조건에 넣습니다.
2. 시간/시간대: `3시`, `10시`, `저녁`, `오전`, `오후`는 삭제 조건에 넣습니다. 정확 시간이 아닌 `저녁`도 time_window/keyword 조건으로 사용하고 되묻지 않습니다.
3. 제목: 날짜·시간·삭제 동사·불용어(`일정`, `삭제해줘`, `취소해`, `없애줘`, `지워`)를 제거하고 남는 핵심 명사를 title로 사용합니다. 예: `내일 3시 회의 취소해` → title=`회의`; `오늘 저녁 약속 삭제` → title=`약속`; `5월 4일 치과 예약 없애줘` → title=`치과 예약`.
4. history 참조(`그 일정`, `방금 넣은`)가 있으면 직전 schedule.create/update/list 결과의 id/title/when을 우선 조건으로 사용합니다.

### 필수 Response Contract
삭제 계획과 최종 답변은 다음을 만족해야 합니다.
- 의도: 일정 삭제임을 명시.
- 슬롯 echo: 추출한 날짜/시간/시간대/title 중 사용한 조건을 trace 또는 답변에 반영.
- 도구: 조건이 하나라도 있으면 `schedule.delete`를 호출.
- 상태: 삭제 완료/삭제 요청 처리 또는 후보 다중 시 선택 요청.
- 다음 행동: 후보가 여러 개일 때만 선택을 요청하며, 이때도 먼저 삭제 후보 조회/삭제 조건 사용 후 요청합니다.

### 강제 예시
```
사용자: "내일 3시 회의 취소해"
→ schedule.delete({title:"회의", date:<내일 ISO date>, time:"15:00", tenant_id:"$personal_tenant_id"})
```

```
사용자: "오늘 저녁 약속 삭제"
→ schedule.delete({title:"약속", date:<오늘 ISO date>, time_window:"저녁", tenant_id:"$personal_tenant_id"})
```

```
사용자: "5월 4일 치과 예약 없애줘"
→ schedule.delete({title:"치과 예약", date:"2026-05-04", tenant_id:"$personal_tenant_id"})
```

```
사용자: "이번주 금요일 팀 회의 지워"
→ schedule.delete({title:"팀 회의", date:<이번주 금요일 ISO date>, tenant_id:"$personal_tenant_id"})
```

```
사용자: "다음달 1일 10시 면담 일정 삭제해줘"
→ schedule.delete({title:"면담", date:<다음달 1일 ISO date>, time:"10:00", tenant_id:"$personal_tenant_id"})
```

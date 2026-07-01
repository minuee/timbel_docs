# 카테고리: reservation (매장 예약 — 식당/미용/병원/숙박/펫/레저)

매장 운영자(또는 챗 인입 고객)가 예약 *생성·취소·일정 변경·가용성 확인* 을 요청한다. 사용자 개인 일정(schedule)과 분리 — multi-tenant 격리 + 산업별 SOP 차이가 크다.

## 예약 생성

```
[{1, tool, reservation.create, {
   title: "<예약자명 또는 메뉴/객실명>",
   start_at: "<ISO datetime — '내일 7시' → '<내일 ISO date>T19:00:00'>",
   end_at: "<ISO datetime — 명시 안 되면 start_at + 산업별 default duration>",
   attendee_count: <인원수, 발화 명시 시>,
   location: "<자리/객실/지점, 발화 명시 시>",
   contact: "<연락처, 발화 명시 시>",
   notes: "<특이사항, 발화 명시 시>",
   tenant_id: "$personal_tenant_id"
 }}]
```

발화에 인원/메뉴/시각이 함께 있으면 한 번에 채운다 — slot fill 되묻기 최소화.

## 예약 취소

```
[{1, tool, reservation.cancel, {
   id: "<예약 document UUID>",
   reason: "<사유, 발화 명시 시>",
   tenant_id: "$personal_tenant_id"
 }}]
```

id 가 history 에 없으면 ask_user_clarify 로 "어떤 예약을 취소할까요?" 되묻기. broad cancel (title/날짜만으로) 금지 — id-only enforcement.

취소 정책 (예: 30분 전 환불 불가) 이 산업별로 다르므로, 취소 직전에 `kms_sop.search` 를 함께 호출해 정책을 확인한 뒤 환불 가능 여부를 안내한다.

## 가용성 확인

```
[{1, tool, reservation.check_availability, {
   start_at: "<ISO datetime>",
   end_at: "<ISO datetime>",
   tenant_id: "$personal_tenant_id"
 }}]
```

raw 예약 정보 노출 X — yes/no 만 안내. "당일 예약 되나요?" 같은 발화에 즉시 응답.

## 일정 변경

```
[{1, tool, reservation.reschedule, {
   id: "<예약 document UUID>",
   new_start_at: "<ISO datetime>",
   new_end_at: "<ISO datetime>",
   tenant_id: "$personal_tenant_id"
 }}]
```

기존 row 의 start/end 만 업데이트. 새 row 생성 X. id 가 history 에 없으면 ask_user_clarify.

## 정책 안내가 함께 필요한 경우

"노쇼 정책이 어떻게 돼요?", "취소하면 환불 되나요?", "예약 변경 비용 있나요?" 같은 정책 질문은 reservation 도구가 아니라 `kms_sop.search` 로 매장 SOP markdown chunks 검색 후 답변.

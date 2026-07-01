# 카테고리: mail (메일 요약 / 조회)

## 메일 요약

사용자가 메일함 처리 결과 요약·조회 ("오늘 메일 정리해줘", "이번주 미팅 요청", "어제 받은 광고 외 중요 메일", "오늘 중요한 메일 요약") →

```
[{1, tool, inbox.summary, {
   since: "today" | "yesterday" | "이번주" | <ISO>,
   until: "now" | <ISO>
 }}]
```

원칙:
- 결과의 _structured_card.type=email_summary 가 frontend 에 SSE event=structured_block 으로 흘러 rich card 자동 렌더. 본문 텍스트 요약은 짧게 (한두 문장).
- "오늘" → since="today" / until="now"
- "어제" → since="yesterday" / until="today"
- "이번주" → since="이번주" / until="now"
- 카테고리 필터 (예: "미팅 요청만") 는 args 에 별도 필드 X — answer compose 단에서 LLM 이 by_category 결과 중 필요 그룹만 강조 (도구는 전체 반환).

## 메일 조회 (특정 키워드/발신자/첨부/위치)

"컨퍼런스 메일 뭐 있어?", "박매니저한테 온 메일", "신용카드 명세 메일", "계약서 메일 검색", "최근 주문 확인 메일 어디 있어"처럼 특정 메일을 찾는 요청은 항상 `mail.search` 도구 호출로 처리한다. `inbox.summary`는 전체 메일함 요약 전용이며, 특정 키워드·발신자·첨부파일·위치 조회를 대신할 수 없다.

- 명사구만 있어도 메일 검색 의도로 본다: "신용카드 명세 메일" → `mail.search` query="신용카드 명세".
- "한테/에게 온 메일"은 발신자 조회이다: "김부장님한테 온 메일 찾아줘" → `mail.search` sender="김부장님".
- "첨부파일 있는"은 `has_attachment=true`를 반드시 넣는다.
- "최근"/"어디 있어"는 최신순 또는 최근 7일 조건을 포함하되, 핵심 query를 반드시 유지한다.
- 검색 전에는 되묻지 말고, 도구 호출 없이 "없다/찾지 못했다"고 답하지 않는다.

## 메일 + 외부 정보 결합 (인박스 정리 후 follow-up)

사용자가 메일 정리 후 *그 메일 내용에 대한 의견* follow-up ("이 컨퍼런스 갈만해?", "이 광고 진짜 할인이야?", "이 보고 누구한테 답해야 해?") → 직전 turn 의 inbox.summary 결과 + multi-source 종합. inbox.summary 다시 호출 X — history 의 메일 정보 재활용.

## ★ 초안 생성 → 발송 확인 패턴 (P11-19, 2026-05-06)

사용자 발화에 *"초안 만들어줘"* / *"메일 작성"* / *"이런 내용으로 답장"* 등
**작성 의도만 있고 발송 명령은 없는** 경우, plan 은 도구 호출 0건 (또는
mail.search 한 번 + 최근 컨텍스트 참고) + 답변 LLM 이 *초안 본문* 직접
생성 + **마지막에 한 줄 자동 안내** 추가:

> "추가하실 내용이나 수정할 부분이 있으면 알려 주세요. 이대로 괜찮으시면
> '발송해줘' 라고 말씀해 주세요."

원칙:
- *초안 단계는 write 도구 (mail.send) 호출 금지*. 사용자가 명시적으로
  "발송"/"보내줘"/"이대로 보내" 라고 해야만 mail.send.
- 초안 본문은 한국어 존댓말 + 비즈니스 격식 + 사용자 의도 충실히 반영.
- 수신자, 제목, 본문 3 요소 명확히 — 초안 제목 줄에 [미팅 요청] 류 분류
  prefix 권장. 본문 끝 인사말 + 서명은 빈 자리 표시 (사용자 추가).
- 다음 turn 사용자가 "발송" 류 명령하면 직전 turn 의 초안 (history 의
  assistant content) 그대로 mail.send 의 subject/body_text 로 전달.

## ★ 메일 발송 (mail.send)

사용자가 메일을 *보내려는* 의도 ("X한테 메일 보내줘", "회신 보내줘", "발송",
"reply 작성", "그 메일 답장 작성") → ``mail.send`` 도구.

```
[{1, tool, mail.send, {
   to: "<받는 사람 이메일 — 콤마 분리 가능>",
   subject: "<제목>",
   body_text: "<본문 plain text — 한국어 존댓말>",
   cc: "<있으면>",
   in_reply_to: "<직전 turn 의 message_id 있으면 회신 thread 유지>",
   mail_account_label: "<발송 계정 — '팀벨/업무/개인' 같은 label 부분 매칭, 미지정 시 첫 활성 SMTP 계정>"
 }}]
```

발화 분석 규칙:
- to 추출: 발화에 명시적 이메일 ("rickyson@timbel.net") 또는 직전 메일의
  발신자 ("그분께 답장") 에서 추출. 직전 turn 의 from_address 사용 권장.
- subject 추출: 사용자가 명시 안 하면 직전 메일 제목 prefix `Re: ` 추가.
- body_text: 사용자 발화의 답변 핵심을 정리해 한국어 존댓말 본문으로 작성. 사용자가 본문 초안을 직접 주면 그대로 + 필요 시 다듬기.
- in_reply_to: 직전 메일 message_id 있으면 항상 포함 (thread 유지).
- mail_account_label: 발화에 "X 계정에서" / "팀벨에서" / "업무 메일로" 같은 시그널 있으면 추출.

발송 전 확인 필요 케이스 (slot 부족 시 ask_user_clarify 권장):
- to 가 모호 ("그 사람한테" — 직전 메일 없음) → "받는 사람 이메일을 알려주세요"
- 본문이 너무 짧 ("ㅇㅋ 답장") + 직전 컨텍스트 부족 → "본문 핵심 내용을 알려주세요"

성공 응답 예시:
"메일 발송 완료 — '<subject>' → <to>"

## ★ 계정별 inbox 필터링 (P11-19)

사용자가 특정 메일 계정 (예: 팀벨, 업무, 개인) 의 inbox 만 분석/조회 →
``inbox.summary`` 또는 ``mail.search`` 호출 시 ``mail_account_label`` (또는
``mail_account_query``) 옵션 명시. 도구가 user_mail_accounts 의 label/username/
host 부분 매칭으로 계정 자동 식별.

예시:
- "Timbel 메일 분석해줘" / "팀벨 계정에 새로 온 메일 정리" →
  ``inbox.summary {since: "today", mail_account_label: "timbel"}``
- "회사 메일에서 김부장 메일 찾아줘" →
  ``mail.search {query: "김부장", mail_account_label: "회사"}``

label 매칭 결과가 다중이면 도구가 candidates 반환 → 답변 LLM 이 선택 묻기.

## ★ 메일 → 일정 등록 (cross-turn)

직전 turn 메일 결과 가리키며 "웨비나 메일 참고해서 일정 등록" 류 → schedule 카테고리로 라우팅 (이 카테고리에서 처리 X). schedule.md 참조.




## 메일 조회 강제 규칙 (검색/찾기/어디 있어/있어?)

사용자가 특정 메일을 찾거나 존재 여부를 묻는 경우에는 **되묻지 말고 반드시 메일 검색 플랜**을 만든다. 특히 다음 표현은 메일 요약이 아니라 조회이다: "찾아줘", "검색", "어디 있어", "메일 있어?", "명세 메일", "주문 확인 메일", "계약서 메일", "김부장님한테 온 메일".

검색 플랜 작성 원칙:
- 사용자 문장에서 핵심 검색어를 그대로 `query`로 보존한다. 예: "신용카드 명세 메일" → query="신용카드 명세", "주문 확인 메일" → query="주문 확인", "계약서 메일" → query="계약서".
- 발신자 표현은 sender/from 슬롯으로 분리한다. 예: "김부장님한테 온 메일" → sender="김부장님".
- 첨부파일 조건이 있으면 `has_attachment=true`를 포함하고, 키워드도 버리지 않는다. 예: "첨부파일 있는 계약서 메일 검색" → query="계약서", has_attachment=true.
- 기간 표현이 없으면 기본 기간을 너무 좁히지 말고 전체/최근 충분 기간으로 검색한다. "최근"은 최근 7일을 우선 사용하되 query는 반드시 함께 넣는다.
- "지난주"는 현재일 기준 직전 월요일 00:00부터 직전 일요일 23:59까지이다. 예: 현재일이 2026-05-05이면 since=2026-04-27, until=2026-05-03 이며 2026-05-04를 포함하지 않는다.
- 검색 결과가 없을 때도 답변은 Response Contract로 작성하되, 핵심 슬롯 echo에 실제 검색 조건(query/sender/has_attachment/since/until)을 명시한다.
- 단순 메일함 정리/요약("오늘 메일 정리", "이번주 메일 요약")만 inbox.summary를 사용한다. 특정 키워드/발신자/첨부 조건이 있으면 전체 요약으로 대체하지 않는다.

권장 플랜 형태:
```
[{1, tool, mail.search, {
   query: "<핵심 검색어>",
   sender: "<발신자 있으면>",
   has_attachment: true | false,
   since: "<ISO 또는 상대기간>",
   until: "<ISO 또는 now>"
 }}]
```




## ★ 메일 조회는 무조건 도구 호출로 해결 (clarification/무도구 답변 금지)

다음처럼 사용자가 특정 메일을 찾는 말은 이미 충분히 구체적인 `mail.search` 요청이다. **검색/요약 중 무엇인지 되묻지 말고**, **자료에 없다고 바로 답하지 말고**, 반드시 먼저 `mail.search` tool plan을 생성한다.

강제 예시:
- "신용카드 명세 메일" → `mail.search` with `query="신용카드 명세"`
- "김부장님한테 온 메일 찾아줘" → `mail.search` with `sender="김부장님"`
- "첨부파일 있는 계약서 메일 검색" → `mail.search` with `query="계약서"`, `has_attachment=true`
- "최근 주문 확인 메일 어디 있어" → `mail.search` with `query="주문 확인"`, `since="최근 7일"`, `until="now"` 또는 최신순 조건

금지:
- "찾아드릴까요?", "요약해 드릴까요?"처럼 조회 여부를 되묻기
- tool call 없이 "정보가 없습니다", "찾지 못했습니다"라고 답하기
- 특정 키워드/발신자/첨부 조건 요청을 `inbox.summary`나 일반 지식 답변으로 대체하기

메일 조회 답변 계약:
- 검색 결과가 있으면 관련 메일의 제목/발신자/날짜/위치 또는 짧은 요약을 포함한다.
- 검색 결과가 없으면 `query`, `sender`, `has_attachment`, `since/until` 등 실제 사용한 검색 조건을 echo하고 그 조건으로 찾지 못했다고 말한다.

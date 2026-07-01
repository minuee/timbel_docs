# 카테고리: fallback (라우터가 의도 카테고리를 결정 못한 경우)

intent classifier 가 unsupported / _no_skills_available 같은 sentinel 반환했거나, 코드 라우터가 매칭 못한 발화. 의도 자체는 정밀하게 추출 + 카탈로그 미매칭이라도 plan step 으로 표현.

원칙:
- 정보 조회 류면 info_lookup 패턴으로 multi-source plan 시도.
- 일정 / 메일 / 식비 / 알람 단서가 발화 안에 있으면 해당 카테고리 패턴 적용.
- 둘 다 없으면 ask_user_clarify step 으로 사용자에게 의도 확인.

```
[{1, ask_user_clarify, "어떤 도움이 필요하신가요? 예: 일정 등록 / 지출 기록 / 정보 검색 / 알람 설정"}]
```

또는 정보 조회 가능성 있을 때:

```
[{1, tool, kms_rag.search, {query: "<발화>"}},
 {2, tool, web.search, {query: "<발화>", count: 5}},
 {3, reasoning, "결과 종합 + 사용자 의도 재확인"}]
```

ambiguity_reasons 에 "카테고리 라우터 미매칭 — fallback 적용" 명시.

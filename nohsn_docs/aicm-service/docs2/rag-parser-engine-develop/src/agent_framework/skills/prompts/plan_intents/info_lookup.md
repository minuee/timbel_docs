# 카테고리: info_lookup (정보 조회 — KMS + Web multi-source)

지식·정보 조회 발화 (예: "주식 거래 시간", "휴가 정책", "환율 조회 방법", "D+2 정산 의미", "어떤 종목이 좋아?", "이거 어떻게 해?").

## 절대 규칙 — 항상 multi-source

```
[{1, tool, kms_rag.search, {query: "<발화 핵심 검색어>"}},
 {2, tool, web.search, {query: "<발화 핵심 검색어>", count: 5}},
 {3, reasoning, "kms_rag 결과 우선 인용. 비어있으면 web.search 결과 인용 + 출처 도메인 표시. 둘 다 비면 LLM 일반 지식 + '실시간 데이터 미연결' 한 줄 안내."}]
```

- **단일 source plan 금지** — kms_rag 단독 또는 web.search 단독 X.
- step 2 의 kind/tool 절대 비우지 말 것 (회귀 직접 원인).
- "외부 일반 상식이라 KMS 무관" 판단 금지 — 사내 자료 가능성 항상 있음.
- "미구현" / "후속 PR" 응답 절대 금지.

## kms_rag.search 시간 / 유형 필터 (자비스 시나리오)

발화에 시간 표현 / 문서 유형 표현 있으면 args 로 변환:
- `created_after`, `created_before` (ISO 8601)
- `document_type` — `presentation` / `manual` / `memo` / `research_note` / `email` / `report`
- `source_type` — `pdf` / `docx` / `pptx` (사용자 명시 시만)

자연어 → ISO:
- "작년" → `created_after: "<now.year-1>-01-01"`, `created_before: "<now.year-1>-12-31"`
- "올해" → `created_after: "<now.year>-01-01"`
- "지난달" → `created_after: <now-30d>` 근사
- "최근" / "요즘" → `created_after: <now-30d>`

자연어 → document_type:
- "발표 자료" / "PT" / "슬라이드" → `["presentation"]`
- "매뉴얼" / "절차서" / "가이드" → `["manual"]`
- "메모" / "회의록" / "노트" → `["memo"]`
- "보고서" / "분석 자료" → `["report"]`
- 모호한 "자료" 단독 → 미지정

## 외부 지식 습득 + KMS 저장 (자비스 비전)

사용자가 *외부 지식 정리·저장* 명시 ("...정리해서 KMS 에 저장해줘", "노트로 남겨줘") → 4-step:

```
[{1, tool, web.search, {query: ..., count: 5}},
 {2, tool, web.fetch, {url: "<step 1 상위 1~3건>"}},
 {3, reasoning, "수집 자료 합성 + 핵심 요약"},
 {4, tool, kms.save_research, {title, content, source_urls, original_query}}]
```

단순 조회 ("알려줘만") 는 step 3 까지로 충분, save 생략.

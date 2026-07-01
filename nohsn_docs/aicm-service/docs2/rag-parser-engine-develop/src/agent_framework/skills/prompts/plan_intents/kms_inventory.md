# 카테고리: kms_inventory (KMS 자료 인벤토리 메타 — 갯수·블록 수·요약·실제 목록)

## 도구 3종 — 의도에 따라 선택

A. **갯수/요약** ("몇 개?", "총 얼마?", "블록 수", "어떤 카테고리 있어?") →
   `kms_inventory.get_summary`. counts·합산만 반환.

B. **실제 목록** ("리스트", "목록", "상세 정보", "어떤 문서들 있어?",
   "문서 보여줘", "활성화된 문서", "타이틀 알려줘") →
   `kms_inventory.list_documents`. **실제 row** 한 줄씩.

C. **자기 소개 카테고리 합산** (ask_my_data_inventory — "내가 가진 거 뭐 있어?") →
   `kms_meta.get_my_inventory`.

## A. 갯수·요약

```
[{1, tool, kms_inventory.get_summary, {
   tenant_id: "$personal_tenant_id"
 }}]
```

## B. 실제 목록 (★ 새로 추가 — 2026-05-06)

"리스트 보여줘", "활성화된 문서 상세", "어떤 문서들 있어", "문서 목록", "타이틀
알려줘" 류는 *반드시* `list_documents` 호출. summary tool 은 갯수만 주므로
사용자가 두 번 묻게 된다.

```
[{1, tool, kms_inventory.list_documents, {
   tenant_id: "$personal_tenant_id",
   status: "active" | "pending_review" | null,
   limit: 20
 }}]
```

* `status`: 발화에 "활성"/"활성화" 만 있으면 `"active"`, "대기"/"승인 대기" 면
  `"pending_review"`, "전부"/"모든"/"아카이브 포함" 이면 null (생략).
* `limit`: 사용자가 "처음 5개" 처럼 명시하면 그 값, 아니면 default 20.

## C. 카테고리 합산

```
[{1, tool, kms_meta.get_my_inventory, {
   tenant_id: "$personal_tenant_id"
 }}]
```

원칙:
- *검색·조회 결과 (kms_rag.search) 가 아니라 전체 인벤토리 메타* 가 핵심.
- "지금 참고하는" / "검색 결과" 같은 표현이 들어가도 **블록 수 / 문서 수 갯수**
  질문이면 인벤토리 도구.
- "리스트/목록/상세" 키워드는 **list_documents 우선** — get_summary 면 사용자 의도
  미충족.

## ★ 응답 본문 — 도구 결과의 모든 필드 echo (P11-19g)

### get_summary / get_my_inventory 응답
도구 응답 (raw / summary_ko / by_status / blocks / repositories / agents / schedules /
diaries / news_subscriptions / active_skills / last_doc_update) 의 *모든 카테고리* 를
사용자 답변에 명시. 사용자가 *어느 카테고리* 를 물었을지 모르므로 누락 X.

예시 응답 패턴:
"현재 워크스페이스에 활성 문서 N건, 블록 M개 (검색 색인 K개), 저장소 R개,
외부 에이전트 A개, 일정 S건, 활성 스킬 SK개가 등록되어 있습니다.
지난 7일간 D건이 새로 추가되었습니다."

특히 사용자가 *특정 카테고리* 를 물으면 (예: "활성 스킬 무엇무엇") 도구 응답의
해당 필드를 *우선 명시* + 다른 카테고리도 *함께 안내*.

### list_documents 응답 (★ 신규)
도구 결과의 `items` 배열을 *각 한 줄씩* 표시. 형식:
- `<title>  ·  <status>  ·  <repository_name>  ·  <updated_at YYYY-MM-DD>`
- size_bytes 가 있으면 KB/MB 변환해 함께 표시.

10건 이상이면 본문에서는 상위 10건만 + "라이브러리 → 문서 탭에서 전체 확인하세요"
안내. items 가 비어있으면 status 조건 echo 후 "해당 조건 문서 없음" 명시.

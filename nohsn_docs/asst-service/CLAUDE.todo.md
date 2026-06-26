# CLAUDE.todo.md — 나중에 실제 적용할 작업

## ☐ 상담 사후처리 4개 서비스를 기존(LLM오케스트레이터) → CE 서비스로 교체

> 배경: 현재 4개 서비스는 LLM 오케스트레이터(또는 코드 하드코딩 프롬프트)로 호출 중.
> 이번에 같은 4개를 CE service(`/ai-apps/advisor-*/runs`) 직접 호출 버전으로 **테스트 엔드포인트(`PostCall-LLM` 그룹, `src/advisor/postcall/`)** 로 미리 만들어 둠.
> 검증이 끝나면 **기존 운영 흐름을 CE 호출로 교체**한다. 그때 아래대로 진행.
>
> ⚠️ 핵심 차이: CE 응답은 전부 **파이프(`|`) 구분 문자열**로 옴(배열 못 줌). 기존 코드가 기대하는 배열/객체 형태로 **split(필요 시 zip) 복원**해야 함.
> 테스트 엔드포인트는 **원본 그대로** 반환(변환 없음) — 변환 로직은 이 교체 작업에서 새로 넣는다.

### 공통 준비
- CE 호출 공통부는 `PostCallLlmService.postToCe()` 패턴 참고(헤더 `x-api-key`+`Authorization`+`X-Tenant-Id`, base=`CE_API_LLM_URL`, 30s 타임아웃, 502 변환).
- 교체는 "기존 메서드 내부의 LLM 오케스트레이터 호출부만 CE 호출 + 파이프 파싱으로 바꾸는" 방식. 컨트롤러/응답 DTO(대외 계약)는 최대한 유지.

---

### ① 할일 자동생성
- **기존**: `todo.service.ts` `callLlmAutoCreateTodos()` → LLM오케스트레이터 `complete('adv-auto-create-todos')` → `{ todos: string[] }`
- **CE**: `POST {CE_API_LLM_URL}/ai-apps/advisor-todolist/runs`, body `{ conversation, maxLength, includeSimple }`
- **응답**: `output.todos` = `"a|b|c"` (파이프 문자열)
- **변환**: `output.todos.split('|')` → `string[]` → 기존 `autoCreateTodos()` 저장 루프(todo.service.ts:394)에 그대로 투입
- 참고 테스트: `runTodolistRawByCe`

### ② 내용요약
- **기존**: `summary.service.ts` `callLlmSummarize()` → LLM오케스트레이터 `complete('adv-conversations-summarize')` → 4필드 객체 → `buildSummaryMarkdown()`로 마크다운 조립
- **CE**: `POST {CE_API_LLM_URL}/ai-apps/advisor-summary/runs`, body `{ conversation }`
- **응답**: `output.{ customerInquiry, handlingResult, followUp, notes }` (필드명 동일)
- **변환**: split 불필요. `output` 4필드를 기존 `buildSummaryMarkdown()`에 그대로 넘기면 됨(마크다운 조립 재사용)
- 참고 테스트: `runSummaryRawByCe`

### ③ 키워드 생성
- **기존**: `summary.service.ts` `callLlmKeywords()` → LLM오케스트레이터 `complete('adv-conversations-summarize-keyword')` → `{ keywords: ... }`
- **CE**: `POST {CE_API_LLM_URL}/ai-apps/advisor-keywords/runs`, body `{ conversation, count }`
- **응답**: `output.keywords` = `"a|b|c|d|e"` (파이프 문자열)
- **변환**: `output.keywords.split('|')` → `string[]` → 기존 응답(`keywords`) 형태로 매핑
- 참고 테스트: `runKeywordsRawByCe`

### ④ 상담유형 추출 (가장 손이 많이 감)
- **기존**: `summary.service.ts` `classifyCounselingType()` → `customComplete(openai/gpt-4o-mini)` + **코드 하드코딩 systemPrompt(카탈로그+규칙+응답형식, :347~471)** → `[{ id, categoryPath }]` 배열
- **CE**: `POST {CE_API_LLM_URL}/ai-apps/advisor-category/runs`, body `{ conversation }` (카탈로그는 **CE 프롬프트가 자체 보유** → 우리는 안 보냄)
- **응답**: `output.{ id: "1|2|3", categoryPath: "A>B>C|D>E>F|..." }` (두 필드 각각 파이프 문자열)
- **변환(★ 2필드 split + zip)**:
  ```
  const ids   = output.id.split('|');
  const paths = output.categoryPath.split('|');
  const result = ids.map((id, i) => ({ id: id.trim(), categoryPath: paths[i]?.trim() }));
  // → 기존 CounselingTypeItemDto[] 형태로 복원
  ```
- **교체 시 정리 대상**: 우리 코드의 하드코딩 systemPrompt 카탈로그(:347~471)는 CE로 책임 이관 → 제거 검토.
- **확인 필요(CE팀)**: CE advisor-category 프롬프트의 카탈로그가 우리 것과 동일한지(다르면 분류 결과가 달라짐).
- **상태**: CE 담당자가 응답 형식(배열 불가 → 파이프 타협) 반영해 **수정·재배포 예정** → 재배포되면 `/postcall/category` 로 먼저 테스트 후 교체.
- 참고 테스트: `runCategoryRawByCe`

---

---

## ☐ 실시간 VOC(감정체크) conversation 전송 방식 개선 — 슬라이딩 윈도우로 전환

> 배경: `/assist-stream` 요청이 올 때마다 그동안의 대화를 **메모리에 전체 누적**해서, CE emotion API의 `conversation`에 **모든 대화**를 실어 보냄(현재 `voc-realtime` 경로).
> 문제: 통화가 길어질수록 메모리/토큰/레이턴시가 계속 커지고, **감정분석 품질도 나빠짐**.

### 왜 전체 누적이 문제인가 (AI 관점)
- 실시간 VOC가 알고 싶은 건 **"지금 이 순간 고객 감정"**인데, 전체를 넣으면 **과거 감정(초반에 화났다 풀린 것)이 현재 판단을 희석** → 뭉뚱그려진 결과.
- 길어질수록 **오래된 맥락이 노이즈**가 되어 최근 1~2턴의 감정 변화(다시 짜증↑)를 놓침 → **감정 변화 감지가 둔해짐**(조기탐지에 치명적).

### 왜 "현재 1턴 / 고객 직전 2턴"도 안 되나
- 너무 짧으면 맥락 부족 — `"네 알겠어요"`가 진심인지 비꼬는 건지 직전 맥락 없이 판단 불가.
- **고객 발화만** 모으면 더 위험: 고객 감정은 보통 **상담사 행동에 대한 반응**이라, 상담사 발화를 빼면 인과가 사라져 LLM이 오판.

### 권장 방향 (적용 시)
1. **슬라이딩 윈도우**: 최근 **6~10 발화**(고객만 2턴 X → 고객 3~4발화 + 사이 상담사 응답 포함, **양쪽 role 유지**)만 전송.
2. **고정 크기 큐(maxlen)로 메모리 보관** → 오래된 건 자동으로 밀려나 **메모리 폭증도 동시 해결**(전체 저장 후 자르기보다 애초에 윈도우만 유지가 깔끔).
3. **통화 극초반**(윈도우보다 짧을 때)은 있는 만큼 그대로 전송.
4. **짧은 윈도우 맥락 보완**: 직전 감정 점수를 상태로 캐싱 → 이번 윈도우 결과와 가중평균(EMA). 윈도우=“지금”, 캐싱=“추세” 담당.
- 윈도우 크기(6~10)는 실제 통화 데이터로 1~2회 튜닝해 적정값 확정.

### 적용 시 손볼 곳 (추정)
- `voc-realtime.service.ts` `handleUtterance`(누적 버퍼/`buildConversation`, 현재 `MAX_BUFFER=40` 슬라이딩 + customer만 누적) — 윈도우 로직 + 양쪽 role 포함으로 변경, 감정 점수 캐싱 상태 추가.
- 적용 전 현재 구조 다시 확인하고 같이 설계할 것.

---

### 진행 메모
- [2026-06-26] 테스트 엔드포인트 4개(`PostCall-LLM`) 신설 완료, ①②③ 스웨거 테스트 정상. ④는 CE 재배포 대기 중.
- emotion(VOC)도 CE path가 `/ai-apps/advisor-emotion/runs`로 변경됨(이미 운영 흐름 반영).
- [2026-06-26] 실시간 VOC conversation 누적 방식 개선안(슬라이딩 윈도우) todo 등록 — 아직 미적용, 의견 단계.

# 콜봇 멀티턴 reformulate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 콜봇 멀티턴 발화(`conversation_history` 있음)에서만 KMS reformulate를 켜 지칭("아까 그거")·부정("X 말고")을 자기완결 검색어로 복원하고, 재오염을 막기 위해 context_weighted는 끈다.

**Architecture:** 변경은 2개 repo·2개 파일. (1) aicm-service 콜봇 internal_search가 KMS 검색 호출 시 `enable_llm_rewrite=bool(conv)`·`context_weighted=False`를 전달. (2) KMS `REFORMULATE_PROMPT`에 제외(부정) 복원 지시 추가. KMS 파이프라인은 reformulate 결과로 `request.query`를 교체(`service.py:926`)하므로 앵커·검색·rerank가 자동으로 재작성 쿼리를 사용 — 추가 배선 없음.

**Tech Stack:** Python, pytest. 두 repo 모두 테스트는 **소스 텍스트 단언("wiring") 방식**(`_read(rel)` 후 `assert "..." in src`) — 기존 `tests/test_internal_search_context.py`, `tests/search/test_context_weighted_wiring.py` 패턴을 그대로 따른다.

## Global Constraints

- repo·브랜치: aicm-service = `feature/colbot-multiturn-reformulate`(스펙 커밋 250e7a8 위), rag-parser-engine = 신규 브랜치 `feature/colbot-multiturn-reformulate`(현재 develop 기준 분기). develop/main 직접 커밋 금지.
- 이모지 금지(코드/주석/커밋). **하드코딩 금지**: 프롬프트 지시는 특정 상품명·키워드가 아닌 일반 지시문이어야 함.
- 커밋 메시지 한국어, 버그/기능은 이슈·원인·수정 포함. 커밋 trailer 2줄 필수:
  - `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  - `Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW`
- 테스트는 소스 텍스트 단언 방식 유지(이 코드베이스 관행). 기능 검증(앵커가 의도 상품으로 가는지)은 **배포 후 게이트웨이 무인증 internal_search API A/B**로 별도 수행 — 배포는 테스트/공지 후.
- 멀티턴 게이팅: `conversation_history` 있을 때만 reformulate ON. 단발은 off(기존 고속 경로).
- 두 태스크는 서로 다른 repo라 독립. 순서 무관.

---

## Task 1: aicm-service — 콜봇 internal_search 플래그 전환

**Files:**
- Modify: `aicm-service/api/endpoints/documents/search_endpoints.py` (`_internal_search_impl`의 `rag_client.search(...)` 호출, 약 L345-362)
- Modify(Test): `aicm-service/tests/test_internal_search_context.py` (`test_internal_search_disables_reformulate_and_uses_context_weighted`)

**Interfaces:**
- Consumes: `rag_client.search(..., enable_llm_rewrite: bool=False, conversation_history, context_weighted: bool=False, w_c, w_p)` (clients/rag_service_client.py — 기존 시그니처 불변).
- Produces: 없음(엔드포인트 내부 동작 변경).

- [ ] **Step 1: 기존 테스트를 새 동작 단언으로 교체(실패하는 테스트)**

`aicm-service/tests/test_internal_search_context.py`에서 아래 함수를 통째로 교체:

```python
def test_internal_search_enables_reformulate_for_multiturn():
    """콜봇 멀티턴(conversation_history 있음)만 reformulate ON, context_weighted는 OFF(재오염 방지).

    지칭/부정 발화('X 말고 아까 그거')를 KMS reformulate가 자기완결 검색어로 복원하도록
    멀티턴에 한해 enable_llm_rewrite 를 켠다. reformulate 가 쿼리를 자기완결화하므로
    context_weighted(직전 턴 dense 융합)는 재오염을 유발해 끈다. 단발은 enable_llm_rewrite=False.
    """
    src = _read("api/endpoints/documents/search_endpoints.py")
    assert "enable_llm_rewrite=bool(conv)" in src
    assert "enable_llm_rewrite=False" not in src
    assert "context_weighted=False" in src
    assert "context_weighted=bool(conv)" not in src
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd aicm-service && python -m pytest tests/test_internal_search_context.py::test_internal_search_enables_reformulate_for_multiturn -v`
Expected: FAIL (현 소스는 `enable_llm_rewrite=False`·`context_weighted=bool(conv)`이므로 단언 불일치).

- [ ] **Step 3: 소스의 search 호출 플래그 변경**

`api/endpoints/documents/search_endpoints.py`의 `rag_client.search(...)` 호출에서 해당 라인들을 교체. 현재:

```python
        enable_rerank=True,
        # [수정 2026-06-09] 콜봇은 "rerank까지 처리한 결과"를 받음(검색 청크만, 답변 X). rerank on.
        # [수정 2026-06-16] reformulate(LLM 재작성) 제거 — 현재 발화 지배 + 이전 맥락 저가중 융합.
        # reformulate는 자기완결 발화를 일반화해 정답을 밀어내고(1→5위), 이력 토픽 오염·비결정·latency(+500ms) 유발.
        # 대신 KMS 가중 컨텍스트 dense 융합 사용(설계: 2026-06-16-context-weighted-colbot-search-design.md).
        enable_llm_rewrite=False,
        conversation_history=conv,
        context_weighted=bool(conv),
        w_c=0.8,
        w_p=0.2,
    )
```

변경 후:

```python
        enable_rerank=True,
        # 콜봇은 rerank까지 처리한 결과를 받음(검색 청크만, 답변 X). rerank on.
        # [수정 2026-06-24] 멀티턴(conversation_history 있음)만 reformulate ON — 지칭/부정 발화
        # ('X 말고 아까 그거')를 KMS가 자기완결 검색어로 복원해 앵커가 제외 상품으로 가는 오답을 막는다.
        # reformulate가 쿼리를 자기완결화하므로 context_weighted(직전 턴 dense 융합)는 재오염을 유발해 끈다.
        # 단발(이력 없음)은 reformulate off = 기존 고속 경로. 과거 reformulate '정답 밀림'은
        # 임베딩/리랭커 컨텍스트 prefix로 이미 해소됨.
        enable_llm_rewrite=bool(conv),
        conversation_history=conv,
        context_weighted=False,
    )
```

(주: `context_weighted=False`라 `w_c`/`w_p`는 무의미해지므로 호출에서 제거 — `rag_client.search` 기본값 0.8/0.2가 있고 KMS가 context_weighted=False면 무시한다.)

- [ ] **Step 4: 테스트 통과 확인 + 회귀 없음 확인**

Run: `cd aicm-service && python -m pytest tests/test_internal_search_context.py -v`
Expected: 3개 테스트 모두 PASS (`test_rag_client_search_supports_context_weighted`, `test_internal_search_enables_reformulate_for_multiturn`, `test_internal_search_enrichment_scopes_by_workspace`).

- [ ] **Step 5: 커밋**

```bash
cd aicm-service
git add api/endpoints/documents/search_endpoints.py tests/test_internal_search_context.py
git commit -m "fix(search): 콜봇 멀티턴만 reformulate ON + context_weighted OFF

- 이슈: 멀티턴 'X 말고 아까 그거 Y'가 제외 상품으로 앵커링돼 오답
- 원인: 콜봇 internal_search가 enable_llm_rewrite=False 고정 → 원문이 앵커 오염
- 수정: enable_llm_rewrite=bool(conv)(멀티턴만), context_weighted=False(재오염 방지). 단발은 기존 경로 유지

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW"
```

---

## Task 2: rag-parser-engine(KMS) — REFORMULATE_PROMPT 부정 처리 보강

**Files:**
- Modify: `rag-parser-engine/src/search/llm_query_rewriter.py` (`REFORMULATE_PROMPT`, 약 L63)
- Create(Test): `rag-parser-engine/tests/search/test_reformulate_prompt.py`

**Interfaces:**
- Consumes: 없음.
- Produces: 없음(프롬프트 문자열 보강만, `reformulate_for_search`의 JSON 출력 스키마 불변).

- [ ] **Step 1: 신규 테스트 작성(실패하는 테스트)**

Create `rag-parser-engine/tests/search/test_reformulate_prompt.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_reformulate_prompt_handles_exclusion():
    """REFORMULATE_PROMPT는 'X 말고' 같은 제외(부정) 표현을 복원하도록 지시해야 한다.

    멀티턴 부정 발화('한국투자 말고 아까 그거')에서 제외 대상을 검색어에서 빼고
    실제 가리키는 대상으로 재작성하게 하는 지시가 프롬프트에 있어야 한다.
    """
    src = _read("src/search/llm_query_rewriter.py")
    assert "REFORMULATE_PROMPT" in src
    assert "말고" in src
    assert "제외" in src
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd rag-parser-engine && python -m pytest tests/search/test_reformulate_prompt.py -v`
Expected: FAIL (현 프롬프트엔 "말고"/"제외" 지시가 없음).

- [ ] **Step 3: REFORMULATE_PROMPT에 제외 지시 추가**

`src/search/llm_query_rewriter.py`의 `REFORMULATE_PROMPT` 선언에서 둘째 줄 뒤에 지시를 추가. 현재:

```python
REFORMULATE_PROMPT = """대화 맥락을 참고하여 마지막 질문을 독립적인 검색 쿼리로 변환하라.
대명사, 생략된 주어/목적어를 대화 기록에서 복원하라.

대화 기록:
```

변경 후:

```python
REFORMULATE_PROMPT = """대화 맥락을 참고하여 마지막 질문을 독립적인 검색 쿼리로 변환하라.
대명사, 생략된 주어/목적어를 대화 기록에서 복원하라.
'X 말고/아니고 ~' 처럼 특정 대상을 제외하는 표현이면, 제외 대상(X)을 검색어에서 빼고
실제 가리키는 대상을 대화 기록에서 복원하라.

대화 기록:
```

(나머지 `{conversation_history}` / `마지막 질문: {query}` / JSON 출력 지시는 불변. 특정 상품명 하드코딩 없이 일반 지시문만 추가.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd rag-parser-engine && python -m pytest tests/search/test_reformulate_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
cd rag-parser-engine
git add src/search/llm_query_rewriter.py tests/search/test_reformulate_prompt.py
git commit -m "fix(search): reformulate 프롬프트에 제외(부정) 표현 복원 지시 추가

- 이슈: 멀티턴 'X 말고 아까 그거'에서 제외 대상 X가 검색어에 남아 오답
- 원인: REFORMULATE_PROMPT가 대명사/생략만 복원, 부정/제외 처리 지시 없음
- 수정: 'X 말고/아니고' 제외 대상을 빼고 실제 지칭 대상으로 재작성하는 일반 지시 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW"
```

---

## 배포 후 기능 검증 (계획 외 — 배포 재개 시 수행)

소스 단언 테스트는 "변경이 소스에 반영됨"만 확인한다. 실제 효과는 배포 후 게이트웨이 무인증 internal_search API로:

- **B'(수정 후)**: POST `https://ecpad.etaas.co.kr/aicc/aicm-service/search/internal/document`
  body: `{"workspace_id":"019eb9a8-33eb-7648-8f75-5130e89a625d","text":"한국 투자 말고 아까 그거 수수료는 어떻게 돼요","conversation_history":[<하나코리아·한국투자 4턴>],"top_k":10}`
  기대: 결과가 **하나코리아(`0ccba376`)** + 환매수수료 청크 상위(수정 전엔 한국투자 `9e4afe1c`/0.50).
- **회귀**: 자기완결 멀티턴 "한국투자테크 총보수"(2턴째) → 한국투자테크 유지. 단발 "하나코리아 환매수수료" → 불변(0.7대).
- UTF-8 body는 파일로(`--data-binary @file`) — 셸 직접 한글은 400(body parse) 발생.

---

## Self-Review

**1. 스펙 커버리지:**
- §접근1 aicm-service 플래그(enable_llm_rewrite=bool(conv)·context_weighted=False) → Task 1.
- §접근2 KMS 프롬프트 부정 보강 → Task 2.
- §게이팅(멀티턴만) → Task 1의 `bool(conv)`.
- §데이터흐름(앵커가 reformulate 결과 사용) → 변경 없음(파이프라인 기존, 스펙에 근거 명시) — 별도 태스크 불필요.
- §검증(단위=소스단언, API 재현) → 각 Task의 테스트 + "배포 후 기능 검증" 절.
- §범위제외(어드바이저·KMS 타소비자·#2·재색인) → 본 계획 미포함(정상).

**2. 플레이스홀더 스캔:** TBD/모호 지시 없음. 모든 코드 스텝에 실제 코드·정확 명령. "배포 후 검증"은 배포 의존이라 계획 실행 범위 밖임을 명시.

**3. 타입/명칭 일관성:** `enable_llm_rewrite`·`context_weighted`·`conversation_history`·`REFORMULATE_PROMPT`가 두 Task·소스·테스트에서 동일. 테스트 단언 문자열("enable_llm_rewrite=bool(conv)", "context_weighted=False", "말고", "제외")이 Step 3 변경 코드와 정확히 일치.

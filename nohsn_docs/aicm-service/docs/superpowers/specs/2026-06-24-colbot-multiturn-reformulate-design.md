# 콜봇 멀티턴 지칭/부정 발화 검색 정확도 — reformulate 설계 (spec)

작성일: 2026-06-24 · 대상: aicm-service(콜봇 internal_search) + rag-parser-engine(KMS reformulate)

## 배경 / 문제 (실측 확정)
콜봇 멀티턴에서 **지칭·부정 발화**가 엉뚱한 상품으로 검색된다.

AWS 대신증권 워크스페이스(`019eb9a8-...`) 실대화:
- 17:18:01 "하나코리아 펀드가 뭐에요" → 콜봇 하나코리아 설명
- 17:18:18 "한국 투자 테크펀드 클래스 C 총 보수" → 1.2731%
- 17:18:32 "**한국 투자 말고 아까 그거** 수수료는 어떻게 돼요" → "하나코리아 판매수수료 정보 없음" **오답**

게이트웨이 internal_search API로 A/B 재현(확정):
- **A** `"하나코리아 환매수수료"`(이력 없는 깨끗한 질의) → 하나코리아 문서(`0ccba376`) **#1·#2·#3 = 0.726/0.713/0.664**. 데이터·임베딩·랭킹 정상.
- **B** `"한국 투자 말고 아까 그거 수수료"`+이력 → 결과 **전부 한국투자(`9e4afe1c`)** = 사용자가 "말고"로 **제외한 상품**, 점수 전부 ~0.50.

**근본 원인:** 콜봇 경로가 `enable_llm_rewrite=False`(2026-06-16 의도적 — 당시 "reformulate가 정답을 밀어냄"으로 판단해 비활성, context_weighted dense 융합으로 대체). 그래서 원문 "한국 투자 말고 아까 그거"가 그대로 앵커링에 들어가 **"한국 투자" 토큰이 한국투자 제목과 매칭 → 제외 상품으로 스코프** → 그 문서만 검색 → 정답 없음.
- 보강: 당시 "정답 밀림"은 reformulate 자체 결함이 아니라 **답 청크(수수료 표)가 펀드명·섹션을 임베딩에 안 가져 개요 청크에 밀리던 랭킹 문제**였고, 이는 임베딩/리랭커 컨텍스트 prefix(이미 배포·A의 0.72가 증명)로 해소됨. 즉 reformulate를 다시 켜도 그 회귀는 재발하지 않는다.

## 목표
콜봇 **멀티턴** 발화에서 지칭("아까 그거")·부정("X 말고")을 **자기완결 검색어로 복원**해, 앵커링·검색·리랭크가 사용자가 실제 의도한 상품으로 동작하게 한다. 단발(이력 없는) 질의는 현 고속 경로를 그대로 유지(추가 latency 0).

## 접근 (승인: 접근 A + 멀티턴 항상)
변경 2곳. 파이프라인은 reformulate 결과로 `request.query`를 교체(KMS `service.py:926`)하므로 앵커(`:1210`)·retrieval·rerank가 **자동으로 재작성된 쿼리를 사용** — 추가 배선 불필요.

### 1. aicm-service — 콜봇 internal_search 플래그 (`api/endpoints/documents/search_endpoints.py`, `_internal_search_impl`)
- 현재: `enable_llm_rewrite=False`, `context_weighted=bool(conv)`
- 변경: `enable_llm_rewrite=bool(conv)`(멀티턴만 ON), `context_weighted=False`
  - 이유: reformulate가 쿼리를 자기완결화하면, context_weighted(직전 턴 dense 융합 w_p=0.2)는 **제외한 상품 신호를 다시 섞어 재오염**시키므로 상충 → 멀티턴 메커니즘을 context_weighting → reformulate로 전환.
- 단발(이력 없음): `bool(conv)=False` → reformulate·context_weighted 모두 off = 현 동작 유지.

### 2. rag-parser-engine(KMS) — REFORMULATE_PROMPT 보강 (`src/search/llm_query_rewriter.py`)
- 현재: "대명사, 생략된 주어/목적어를 대화 기록에서 복원하라."
- 추가: **제외(부정) 표현 복원** — "'X 말고/아니고 ~' 처럼 특정 대상을 제외하는 표현이면, 제외 대상(X)을 검색어에서 빼고 실제 가리키는 대상을 대화 기록에서 복원하라."
- 제약: 특정 상품명·키워드 하드코딩 금지(일반 지시문). 출력은 기존 JSON 스키마(`{"reformulated", "resolved_references"}`) 유지.

### 게이팅 (멀티턴 항상)
- 멀티턴(`conversation_history` 있음)이면 항상 reformulate 적용. 지칭/부정 신호 탐지 게이트는 두지 않는다(신호 탐지=하드코딩 위험, 프롬프트가 자기완결 발화는 거의 원문 유지).
- 자기완결 멀티턴 발화(예 2턴째 "한국투자테크 총보수")의 과일반화 회귀는 **랭킹 prefix 수정으로 완화 + 회귀 테스트로 가드**(아래 검증).

## 데이터 흐름
1. 콜봇 멀티턴 질의 + history → aicm-service internal_search → KMS `/api/v1/search`(`enable_llm_rewrite=True`, `conversation_history`, `context_weighted=False`)
2. KMS Step0-pre `reformulate_for_search(query, history)` → effective_query("하나코리아 환매수수료") → `request.query` 교체(`service.py:926`)
3. 앵커(`_resolve_anchor_doc_ids`, `:1210`)·dense/sparse/keyword·rerank가 교체된 쿼리 사용 → 하나코리아 스코프 → 정답(A가 증명한 0.72 경로)
4. 단발: `enable_llm_rewrite=False` → reformulate 미실행 → 기존 경로

## 에러 / 폴백
- `reformulate_for_search`는 LLM 실패/예외 시 **원문 반환**(기존 try/except) → 최악도 현재 동작과 동일(무회귀).
- reformulate 실패해도 앵커링은 `conversation_history`로 독립 수행되므로 안전망 유지.
- LLM 모델 미가용(현 AWS에 별개 model='' 오설정 이슈 존재 — 본 스펙 범위 밖, 별도 수정) 시 reformulate도 원문 폴백.

## 범위
- **포함:** 콜봇 internal_search 플래그(aicm-service) + KMS REFORMULATE_PROMPT 부정 처리 보강.
- **제외:**
  - 어드바이저(assist-stream) 경로 — 동일 적용은 후속(별도 검토).
  - KMS 타 소비자(agent/RAG) 기본 동작 — 불변(콜봇 요청만 `enable_llm_rewrite=True`로 켬).
  - 쿼리 분해(#2, `QuerySplitter`) — 별도 기능.
  - 임베딩 stale 문서 재색인 backfill — 별개 운영 과제.

## 검증
테스트 러너: KMS·aicm-service 모두 pytest 보유.

### 단위 테스트
- aicm-service: `_internal_search_impl`이 `conversation_history` 유무에 따라 `enable_llm_rewrite=bool(conv)`·`context_weighted=False`를 rag_client.search에 전달하는지(rag_client 모킹).
- KMS: `reformulate_for_search`가 보강 프롬프트로 (LLM 모킹) 부정·지칭 케이스에서 기대 쿼리를 반환하는지. 프롬프트 문자열에 제외 지시 포함 검증.

### API 재현 (배포 후, 게이트웨이 무인증 internal_search)
- **B'(수정 후)**: `"한국 투자 말고 아까 그거 수수료"`+동일 이력 → **하나코리아(`0ccba376`)** 반환 + 환매수수료 청크 상위(A와 유사 0.7대). (수정 전 B = 한국투자 `9e4afe1c`/0.50)

### 회귀 케이스 (멀티턴)
- 지칭: "아까 그거 수수료" → 직전 언급 상품으로 해소.
- 부정: "X 말고 아까 그거 Y" → 비-X 지칭 상품으로 해소.
- **자기완결 멀티턴**: 2턴째 "한국투자테크 총보수" → 한국투자테크 유지(과일반화로 정답 안 밀림 — 2026-06-16 우려 검증).
- 단발(이력 없음): reformulate 미실행, 기존 결과 불변.

## 열린 질문
1. 어드바이저(assist-stream)에도 동일 적용할지 — 본 스펙은 콜봇만. 콜봇 검증 후 별도 결정.
2. reformulate latency(~500ms) 멀티턴 누적 — 단발은 영향 없음. 멀티턴 latency 허용 범위는 배포 후 실측으로 확인(필요 시 캐시는 이미 존재).

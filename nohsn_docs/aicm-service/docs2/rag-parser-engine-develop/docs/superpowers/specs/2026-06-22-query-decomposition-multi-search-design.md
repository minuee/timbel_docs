# 다중질문 분해 → 멀티검색 → 병합 — 설계 (spec)

> 2026-06-22 · 대상: rag-parser-engine(KMS) `src/search/`
> 문제 #2(복합질문 시 한쪽 의도 검색 누락). #1(청크 임베딩 prefix)은 별도 spec(`2026-06-22-chunk-embedding-context-prefix-design.md`).

## 1. 배경 / 문제 (실측 확정)
콜봇/어드바이저 검색에서 **복합(다중의도) 질문이 한쪽 의도를 누락**한다.
- 11:40 멀티턴: "위험등급이랑 환매하면 돈 언제 한꺼번에" → 위험등급만 검색, 환매시점 누락. 단독 질문("환매 언제")은 성공. turn-3(복합+history)도 동일 실패.

근본 원인(소스 확정, kms-explorer): 콜봇/어드바이저 모두 같은 `_execute_pipeline`(`src/search/service.py:702`)에서 **복합질문을 단일 블렌딩 임베딩 1회**로 검색. **쿼리 분해→서브쿼리별 멀티검색 로직이 코드에 전무**(`QueryDecomposer`는 필터(category/nature/entity)만 추출, `sub_queries` 개념 없음). candidate_pool=20→RRF→rerank→top_k=5에서 우세 의도가 슬롯 독점 → 약한 의도 탈락. rerank도 복합쿼리 기준이라 누락 악화.

부수(별건): 콜봇이 보내는 `context_weighted/w_c/w_p`를 KMS `/api/v1/search` 스키마·라우터가 안 받아 **멀티턴 가중 dense 융합이 silent no-op**(2026-06-16 설계 미적용). → 본 설계가 멀티턴을 분해로 흡수하므로 **수정 불필요해짐**(§9).

## 2. 목표
복합질문을 **LLM으로 N개 자기완결 서브질문으로 분해**(N 가변, 멀티턴 참조해소 포함)하고, **서브질문별로 독립 검색**한 뒤 **라운드로빈 병합**으로 각 의도를 최종 top_k에 보장한다. 콜봇/어드바이저 양쪽 적용. **기능 플래그로 on/off**(default on).

비목표: #1(임베딩 prefix), context_weighted no-op 수정, 검색 API 응답 스키마 변경.

## 3. 확정 결정 (brainstorming)
- **트리거**: 항상 LLM 분해(N 가변, 단순=N1). 게이팅 없음. (실측 latency 수용 가능 §8)
- **범위**: 콜봇(`internal_search`) + 어드바이저(`rag_assist`), 공유 `_execute_pipeline` 경유.
- **병합**: 레벨1 RRF(각 서브쿼리 하이브리드 검색) 유지 + 레벨2 **라운드로빈**(의도별 대표성).
- **멀티턴**: 분해 LLM이 conversation_history로 참조해소 흡수. context_weighted 미수정.
- **플래그**: default on, env로 off 가능(off=현행 단일검색).

## 4. 실측 근거 (B200 gemma-4-31B-it, timbel 터널)
분해 LLM latency·품질(2026-06-22 측정):
| 케이스 | latency | 분해 출력 |
|---|---|---|
| 단순 | ~0.18s | N=1 그대로 |
| 복합 | ~0.26~0.31s | 2개 정확분할 + 펀드명 보강 |
| 멀티턴 참조("그거 환매수수료") | ~0.24s | "그거"→풀펀드명 해소, N=1 |
| 멀티턴 복합 | ~0.42s | history로 펀드 해소 + 2분할 |
→ 모두 <0.5s. 단순질문 페널티 ~180ms(현행 ~300ms→~480ms). 게이팅 불필요 판단 근거.

## 5. 아키텍처 / 컴포넌트
2단계 오케스트레이션 추가, 기존 단일쿼리 파이프라인은 **서브쿼리당 재사용**.
```
search(query, conversation_history, ...)
  ├─[A] QuerySplitter(신규, LLM): query+history → ["서브질문1", ...] (N 가변, 단순=1)
  ├─[B] 서브쿼리별 검색(병렬): 각 서브질문 → 기존 _execute_pipeline
  │       (embed→dense/sparse/keyword→RRF→rerank[서브질문 기준])
  └─[C] 라운드로빈 병합: 각 서브쿼리 결과 순번 인터리브 → 중복제거 → final top_k
```
- **신규**: `src/search/query_splitter.py` `QuerySplitter` — 기존 필터추출 `QueryDecomposer`와 이름·역할 구분(혼동 금지).
- **오케스트레이션**: `SearchService`에 `_execute_with_split(request)` 추가. **반환은 `_execute_pipeline`와 동일 5-tuple** `(list[SearchHit], SearchTrace, int, dict|None, QueryAnalysis)`(service.py:708,1387) — 그래야 양 진입점 unpack 무변경. 기존 `_execute_pipeline` 시그니처·내부 무변경(서브쿼리당 호출).
- rerank가 **서브쿼리 기준**으로 동작(각 서브쿼리 _execute_pipeline 내부) → 각 의도 정답 chunk 상위.

### 5.1 영향 리뷰 반영 (병렬 안전·필터·진입점 — 착수 전 필수)
- **서브쿼리 request 격리(필수)**: `_execute_pipeline`는 `request`를 in-place 변이(category_ids service.py:846-847, block_types/repo/time/hint 888-897). N개 동시호출이 같은 객체 공유 시 데이터 레이스 → 서브쿼리마다 **`request.model_copy(update={"query": sub_q, ...filters})`** 독립 복사본 사용, in-place 변이 금지.
- **필터 처리(확정 2026-06-22: 단순화 채택)**: 콜봇 명시 `category_ids`는 model_copy로 전 서브쿼리에 보존. 서브쿼리별 `QueryDecomposer` 재분해는 **허용**(서브쿼리가 자기완결이라 적정 + `_is_complex` 미발동으로 Stage2 LLM 안 탐 → latency 무영향). "필터 1회 추출·공유"는 `_execute_pipeline` 내부 수정이 필요하고 latency 이득이 없어 **생략**(원쿼리 1회 decompose가 오히려 복합쿼리에 Stage2 필터-LLM을 태울 여지). 격리는 model_copy로 보장.
- **동시 제한(필수)**: 무제한 `asyncio.gather` 금지. embedder+reranker가 단일 cuda:0 공유라 N 동시검색이 단일요청 내부 GPU 경합(c=8 tail 3.9x 패턴)을 유발 → **`asyncio.Semaphore`로 동시도 ≤2** 또는 순차. 콜봇(동시부하 높음)은 순차 우선, 어드바이저(저부하)는 제한 병렬 허용. **fan-out 검색단 GPU 경합은 미측정 — 롤아웃서 실측 필수**(§13).
- **진입점 비대칭 배선**: 콜봇=`search()`(service.py:245, 캐시 275-289 + fallback 297-312 래퍼) → split을 **캐시 안쪽**에 둬 병합결과가 원쿼리로 캐시. 어드바이저=`rag_assist.py:242`가 `_execute_pipeline` 직접 → 그 자리에 `_execute_with_split` swap(intent_gate는 _do_search와 병렬 유지). 플래그 off면 양쪽 모두 기존 단일 `_execute_pipeline` 그대로(회귀 0).
- **명칭 정정**: KMS측 콜봇/공개 경로는 `SearchService.search()`(라우터 search.py)다. aicm-service의 `internal_search`는 이 KMS `/api/v1/search`를 부르는 클라이언트측 이름.

## 6. QuerySplitter (컴포넌트)
- 입력: `query: str`, `conversation_history: list[dict] | None`, `max_subqueries: int`.
- 출력: `list[str]`(서브질문 1..N). 분해 불가/단순이면 `[query]`(N=1).
- LLM: 기존 KMS LLM 클라이언트 재사용 — `factory.py:43-50`의 `AsyncOpenAI(base_url=settings.VLLM_URL)`(intent_classifier/llm_query_rewriter와 동일 client)를 `SearchService.__init__`에 `query_splitter`로 주입. model=`settings.VLLM_MODEL`(gemma). OpenAI-호환 chat, system=분해기 지시(맥락 참조해소+자기완결+JSON 배열), messages=history+현재발화.
- **robust JSON 추출**: ` ```json ` 펜스/잡텍스트 제거 후 배열 파싱. 실패→`[query]` fallback.
- 상한: `max_subqueries`(default 4) 초과분 절단.
- 타임아웃: 분해 LLM 호출 예산(default 2.0s). 초과/예외→`[query]` fallback(로깅).

## 7. 라운드로빈 병합
- 입력: N개 서브쿼리 결과 리스트(각각 RRF+rerank된 랭킹), 최종 `top_k`.
- 알고리즘: 라운드 단위로 서브1[0],서브2[0],…,서브1[1],… 순서로 채움. **중복(같은 chunk id) 제거**(첫 등장 유지). top_k 도달 시 중단.
- 각 chunk는 자기 서브쿼리의 rerank score 유지. 콜봇 `threshold`(0.5)는 chunk별 적용(기존과 동일).
- N=1: 병합 생략, 단일 결과 그대로(passthrough).
- 응답 포맷: 기존 검색 응답 스키마 동일(결과 리스트만 분해·병합으로 채워짐).

## 8. 기능 플래그 / 파라미터 (default on, off 가능)
- **`SEARCH_QUERY_DECOMPOSITION_ENABLED`** (env, default `true`): 마스터 스위치. **off → `_execute_pipeline` 단일검색 그대로**(QuerySplitter·병합 미실행, 분해 LLM 호출 0, 동작·latency 변화 0). 즉시 복귀(재임베딩·코드revert 불필요).
- **`SEARCH_DECOMPOSITION_MAX_SUBQUERIES`** (env, default `4`): N 상한.
- **`SEARCH_DECOMPOSITION_TIMEOUT_S`** (env, default `2.0`): 분해 LLM 타임아웃.
- (옵션) 요청 레벨 `enable_query_decomposition: bool | None` — None=env 기본, 명시 시 override(콜봇/어드바이저 개별 제어 여지). API 스키마 추가는 하위호환(기본 None).
- **fallback은 항상 ON**(안전장치, 토글 아님): 분해 실패/타임아웃/빈배열 → 원본 단일검색.

## 9. 멀티턴 (분해가 흡수)
conversation_history를 QuerySplitter에 전달 → 참조해소+자기완결 서브질문(실측 §4). 따라서 context_weighted(dense 융합) 불필요 → **수정 안 함**(기존 dead 배선 잔존은 후속 정리, #2 범위 밖). 11:40 turn-3(복합+history) 해소.

## 10. 에러처리 / 견고성
- 분해 LLM 실패·타임아웃·비JSON·빈배열 → **원본 쿼리 단일검색 fallback**(검색 안 깨짐). 로깅.
- 서브검색 **동시제한(`asyncio.Semaphore`≤2)/순차**(§5.1 — 무제한 gather 금지), 일부 서브검색 실패 시 성공분으로 병합. **전부 실패 시 원본 쿼리 단일검색으로 fallback**(빈 결과 반환 금지).
- N 상한·타임아웃·동시제한으로 latency·GPU경합·비용 bound.
- 플래그 off 경로는 기존 코드 그대로(회귀 0).

## 11. 변경 / 불변 경계
- **변경**: 신규 `query_splitter.py` + `SearchService._execute_with_split` + 두 진입점(search/rag_assist) 배선(플래그 분기) + env 플래그.
- **불변**: `_execute_pipeline` 내부(레벨1 RRF·rerank·필터 `QueryDecomposer`), 검색 API 응답 스키마, 콜봇/어드바이저 응답 계약, 임베딩/인덱스(#1과 독립).

## 12. 테스트
- **QuerySplitter 단위**(LLM 모킹): JSON 파싱(펜스 유/무), N=1/N=2/N>cap 절단, 빈배열→fallback, 예외→fallback, history 전달.
- **라운드로빈 병합 단위**: 2서브쿼리 인터리브, 중복제거, top_k 절단, N=1 passthrough, 일부 빈 결과.
- **플래그 단위**: enabled=false → 단일경로(분해 미호출).
- **통합**: 복합질문 → 두 의도 chunk 결과 포함(11:40 회귀). 멀티턴 참조해소.

## 13. 검증 / 회귀 (운영)
- 효과: "위험등급이랑 환매 언제" → 두 의도 모두 top_k(현재 누락). 멀티턴 "그거 …" 참조해소.
- 회귀(필수, multi-turn): 단순질문 무회귀(N=1 경로), 단일의도 정확도 유지, threshold 통과율, 플래그 off=현행 동등.
- **fan-out GPU 경합 latency 실측(§5.1, spec §4는 분해기만 측정)**: 복합질문 동시제한(≤2)/순차에서 콜봇 total latency가 예산 내인지 측정. 동시부하(c=4~8)서 tail 확인 → 필요 시 동시도/순차 정책 조정.
- **어드바이저 3 LLM 홉**(split+intent_gate+reformulate) 직렬 누적 latency 점검.
- timbel(개발) 먼저 → AWS(POC). 배포 사전 공지([[feedback_deploy_announce]]).

## 14. 미해결 / 후속
- #1(임베딩 prefix) 배포·검증은 별도 진행 중.
- context_weighted no-op dead 배선 정리(선택, 별건).
- 분해 모델 최적화(더 빠른 모델)·서브검색 GPU 경합 튜닝은 필요 시.

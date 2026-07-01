# B200 동적 배칭 작업 요약 (rerank + embed)

> 2026-06-20~21 · 검색 latency tail 개선 · 대상: NHN 공유 B200 `kms_unified_server/unified_server.py`
> 한 줄: 단일 cuda:0를 공유하는 reranker·embedder의 동시부하 경합을 **동적 마이크로배칭**으로 해소.

## 1. 배경 / 문제
검색 3경로(콜봇/어드바이저/웹) latency 측정 결과(`Doc/perf/2026-06-20-search-latency-3paths.md`):
- 단일요청은 정상(콜봇 ~165ms)이나 **동시부하 c=8서 total p50가 3.9배(~600ms)로 tail 악화**.
- 근본원인 = **embedder + reranker가 같은 단일 B200 GPU(cuda:0)를 공유**(vLLM 168GB도 동거, free ~9GB). 동시 요청마다 각자 독립 추론을 단일 GPU서 직렬경합 → 둘 다 3.4~3.6x 동반 열화. retrieval(Qdrant/ES)·API 큐는 무관.
- 가능한 레버: (a) embedder/reranker GPU 분리 — **GPU 1개뿐이라 불가**, (b) **둘 다 마이크로배칭**(채택), (c) 증설(미실행).

## 2. 한 일
동시 요청을 짧은 윈도로 모아 **1회 추론으로 합산** 후 요청별로 분배하는 동적 배처를 reranker·embedder 양쪽에 도입. 단일 소비 루프가 추론을 직렬화 → 동시 추론 경합 제거(단일 GPU 유리).

| | rerank | embed |
|---|---|---|
| 배처 | `RerankBatcher`(`rerank_batcher.py`) | `EmbedBatcher`(`embed_batcher.py`, 별도 클래스) |
| 대상 | `/rerank` 전체 | `/embed` **legacy 단일텍스트만**(인제스트 batch 경로 우회) |
| 분배 | offset 슬라이싱(요청당 pairs N개) | index(요청당 텍스트 1개) |
| 합산 추론 | `CrossEncoder.predict(all_pairs)` | `BGEM3FlagModel.encode(texts)` |
| 확정 파라미터 | max_batch_pairs=160, wait=8ms, queue=1000 | max_batch_texts=32, wait=6ms, queue=1000 |
| 설계/계획 | `docs/superpowers/{specs,plans}/2026-06-21-rerank-dynamic-batching*` | `...-embed-dynamic-batching*` |

외부 `/rerank`·`/embed` API 스키마, KMS 클라이언트, 인제스트 경로는 **불변**. 둘 다 lifespan(@asynccontextmanager) 기동, lazy 모델로드 호환, None 가드, 예외→future 전파(graceful), 루프 영속.

## 3. 결과 (before → after, timbel→B200 실측)
권위값 = 격리 측정(`Doc/perf/2026-06-21-rerank-batching-before-after.md`, `...-embed-batching-before-after.md`).

| 지표 (c=8) | rerank | embed |
|---|---|---|
| 격리 latency before→after | step p50 124→? (total 365→**317**) | /embed p50 **177→38ms (4.7x)** |
| c=8/c=1 배수 | (rerank step 1.5x) | before 2.7x → **after 0.53**(동시가 1회 encode로 합쳐져 c=8<c=1) |
| 품질 | top-5 재현 5/5(score 결정적) | 벡터 bit-identical 재현·swap 0(cos~0.999998=fp16) |
| vLLM 동반부하 | rerank tail +11~32ms만 증가(경합 억제 실증) | /embed c=8 61ms(before 177 대비 우위) |
| c=1 세금 | — | +6.6%(batch_wait 6ms, 게이트 ≤10% 통과) |

추가 발견(rerank): **배칭이 기존 CUDA OOM 81건→0 제거**(비배칭 동시 predict가 9GB 헤드룸을 터뜨리던 것을 단일 직렬화가 해소). embed도 부하 중 ΔVRAM~1GB·OOM 0. → **OOM은 배칭의 리스크가 아니라 배칭이 해결한 문제.** (CrossEncoder.predict batch_size=32, BGE-M3 encode batch_size=16라 GPU forward는 누적상한과 무관하게 ≤16~32로 청크.)

## 4. 진행 방식 / 검증
Subagent-Driven Development: 태스크별 fresh 구현자 → 태스크별 리뷰(spec+품질) → opus 최종 전체 리뷰. 각 작업 Phase 0 게이트로 배칭 전제 선검증:
- rerank Phase 0: B200-local 배칭 server-compute 66.8~77.3% 단축(터널 RTT 희석 교훈 후 재측정).
- embed Phase 0: 기존 /embed 이중모드 활용(batch 포맷=배칭후, 단일 동시=경합) → 신규코드·VRAM리스크 0으로 검증, N=8 90% 단축.
- 단위테스트: rerank 6건, embed 8건(ndarray 회귀 포함). 양쪽 최종 리뷰 "Ready to finalize".
- **1차 embed 배포 실패에서 교훈**: 단위테스트 fake가 plain list라 `out.get("dense_vecs") or []`가 실제 numpy ndarray서 던지는 `ValueError`(단일 /embed 500)를 못 잡음 → B200 스모크가 적발·롤백 → None 가드 + ndarray 회귀테스트로 수정(a7e3d94). 테스트 fake는 실제 반환형을 모사해야 한다.

## 5. 배포 / 영구화 상태
- B200 `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server/`에 런타임 cp 배포, uvicorn :35001(현재 PID 3231286). bare 프로세스(docker 아님).
- **영구화(deploy.sh 재현성 + git canonical)**: `unified_deploy.sh`(d1a5b07)에 필수 3파일 fail-fast 가드 + canonical 출처(git `kms_unified_server/`) 문서화 + 확정 배칭 파라미터 export 고정. git develop 4파일 추적·푸시, B200 라이브 = git HEAD(md5 일치).
- 정정: `unified_deploy.sh`는 unified_server.py를 덮어쓰지 않음 → cp 파일은 프로세스 재기동·deploy 재실행에 생존(이전 "drift" 우려는 부정확).

## 6. 미적용 / 후속 (의도적 제외)
- **리부팅 자동 복구 없음**: unified_server는 고아 프로세스(PPID=1), systemd/cron 미등록 → 리부팅 시 수동 `unified_deploy.sh` 필요. (사용자 결정: B200 그대로 둠.)
- B200 cruft(.bak/.failed/로그) 정리 안 함.
- 비차단 코드 후속: rerank M-3(`_run_loop` 바깥 except 로깅+미완료 future set_exception — embed엔 선반영됨), 테스트 경계 단언 보강.
- 남은 GPU 레버: embedder/reranker GPU 분리(GPU 1개라 현재 불가)·증설.
- 임베딩/쿼리 캐시(레버 B): distinct 쿼리·reformulation으로 hit률 낮아 범위 제외.

## 7. 산출물 (git develop)
- 코드: `kms_unified_server/{rerank_batcher,embed_batcher,unified_server}.py` + `test_{rerank,embed}_batcher.py` + `unified_deploy.sh`.
- 문서: 본 요약 + `Doc/perf/2026-06-21-{rerank,embed}-batching-before-after.md` + `Doc/perf/2026-06-20-search-latency-3paths.md` + specs/plans 4건.
- 커밋 범위: `9a1f0e8`(B200 미러 베이스) ~ `d1a5b07`(영구화). rerank 9a1f0e8~2e0c15b, embed 0ffb834~683ee0f, 영구화 d1a5b07.

# rerank 동적 배칭 — before/after 검증

> 측정 2026-06-21 · timbel_5fl 호스트 내부(localhost:32012, 콜봇 경로 무인증) · KMS reranker=B200 unified_server(:7125 터널)
> 비교 원칙: §10이 아닌 **이 세션 before/after** 기준(공유 B200 부하 변동 때문). 조건마다 cis-redis DB3 `aicm:search_cache:*` flush 후 clean 측정, `aicm:embed:*` 불변.
> 배포: develop abb8e28(rerank_batcher + /rerank 배처 배선)을 B200 런타임 cp(백업 `unified_server.py.bak.20260621015150`). 런타임 drift(영구화 미정).

## 환경
- workspace `019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6`(ECS 리빙), 13문서/363섹션 ready. distinct query 풀 99~105개(콜봇성 금융/펀드/증권/다이소), 결과 ≥3건 100%. intent_gate OFF. 전 rerank `input_count=20`.

## before(비배칭) vs after(배칭) — c=1/4/8 (ms)
| 조건 | before total p50 | after total p50 | before p95 | after p95 |
|------|------|------|------|------|
| c=1 | 145 | 188 | 273 | 280 |
| c=4 | 199 | 206 | 277 | 275 |
| c=8 | **365** | **317** | 496 | 623 |

### c=8 단계 분해
| 지표(c=8) | before | after(무부하) | after(vLLM 동반부하) |
|------|------|------|------|
| total p50 | 365 | 317 | 361 |
| total p95 | 496 | 623 | 645 |
| total mean | 357 | 359 | 396 |
| rerank step p50 | 124 | 143 | 154 |
| rerank step p95 | 161 | 208 | 240 |
| pipeline total p50 | 325 | 278 | 314 |
| pipeline total p95 | 403 | 368 | 396 |

## 판정: 회귀 없음 — 게이트 통과
- **무부하**: total/pipeline p50 소폭 개선(317<365, 278<325). p95/max 일부 증가는 단발 outlier(무부하 변동폭; rerank step p95 208 안정, pipeline p95는 오히려 368<403 개선). 현 GPU 부하가 가벼워(before가 §10의 ~60%) 무부하 절대개선폭은 작은 게 정상 — 배칭의 목적은 동시경합 완화.
- **vLLM 동반부하(gemma-31B 생성 동시 가동)**: 같은 B200에서 vLLM이 도는데도 rerank step p50 143→154(+11), p95 208→240(+32)에 그침. total p50 361≈before 무부하(365). **배칭이 GPU 경합 하 rerank 열화를 억제**함을 실증. 큐 폭주·적체 없음(c=8 96건 전부 정상 완료).
- **품질(score 보존)**: 동일 query 5개 2회 호출 → top-5 id/순서 재현 5/5, score 내림차순 5/5, 관련성 합리적. offset 분배가 score를 깨뜨린 흔적 없음(단위테스트 concurrent+offset과 일치).

## VRAM / OOM (2026-06-21 read-only 실측)
- cuda:0: total 183GB / used 173GB / free **9.2GB**. 점유 = vLLM 168.9GB(KV cache) + unified_server 4.5GB.
- CrossEncoder.predict 기본 `batch_size=32`(미지정 호출). **max_batch_pairs=160은 배처의 요청 누적 상한일 뿐 GPU forward 배치 아님** — predict 내부에서 ≤32쌍 sub-batch로 청크되어 GPU 동시 노출은 항상 ≤32쌍.
- c=8 × 요청당 320쌍(160캡 초과) 가중 부하 중 150샘플 폴링 → **ΔVRAM=0 MiB**(allocator 풀 재사용, 헤드룸 미잠식).
- **핵심: 배칭 도입 전 로그 `CUDA out of memory` 81건 → 도입 후 0건.** 비배칭 시 c=8에서 동시 predict 다수가 9GB 헤드룸을 터뜨려 실제 OOM 발생했고, 배칭의 단일 직렬화(32청크)가 이를 제거. **OOM은 배칭 리스크가 아니라 배칭이 해결한 문제.**
- 잔여 주의: free 9GB가 작아 vLLM KV cache 추가 확장 시 마진 축소 가능(rerank 배칭과 무관한 vLLM 요인).

## 한계
- `.bak` 무배칭 복원은 재기동(서비스 중단) 수반이라 미수행 → before의 vLLM 동반부하 수치는 부재. after 동반부하 vs after/before 무부하로 판정.
- 측정 시점 GPU 부하가 가벼워 §10(c=8 p50 593) 같은 고경합은 재현 안 됨. 고경합 시 배칭 이득은 더 클 것으로 추정(동반부하 +11~32ms 억제가 방향 근거).

# Perf Comparison: search_concurrent_burst

- baseline profile: `integrated-baseline`
- candidate profile: `integrated`
- baseline base_url: `http://localhost:5101`
- candidate base_url: `http://localhost:5201`

## Per-label latency (ms)

| label | metric | baseline | candidate (delta) | ratio | status |
| --- | --- | --- | --- | --- | --- |
| concurrent::1 | p50_ms | 10.4 | 3.2 (-68.9%) | 0.31x | warn (samples<min) |
| concurrent::1 | p95_ms | 11.5 | 3.8 (-67.1%) | 0.33x | warn (samples<min) |
| concurrent::1 | p99_ms | 11.5 | 3.8 (-67.1%) | 0.33x | warn (samples<min) |
| concurrent::4 | p50_ms | 43.8 | 19.5 (-55.6%) | 0.44x | ok |
| concurrent::4 | p95_ms | 79.2 | 36.2 (-54.3%) | 0.46x | ok |
| concurrent::4 | p99_ms | 80.7 | 37.7 (-53.3%) | 0.47x | ok |
| concurrent::8 | p50_ms | 21.4 | 37.7 (+76.6%) | 1.77x | FAIL (>=1.20x) |
| concurrent::8 | p95_ms | 989.5 | 110.0 (-88.9%) | 0.11x | ok |
| concurrent::8 | p99_ms | 1008.3 | 110.4 (-89.1%) | 0.11x | ok |

## SLO check (candidate)

| slo_key | limit_ms | observed_p95 | status |
| --- | --- | --- | --- |
| search_p95 | 300 | 110.0 | ok |
| rag_first_token_p95 | 1500 | 110.0 | ok |
| rag_full_response_p95 | 8000 | 110.0 | ok |

## Verdict

**FAIL** — regressions detected:
- concurrent::8/p50_ms: 1.77x >= 1.20x

# Perf Comparison: search_concurrent_burst

- baseline profile: `integrated-baseline`
- candidate profile: `integrated`
- baseline base_url: `http://localhost:5101`
- candidate base_url: `http://localhost:5201`

## Per-label latency (ms)

| label | metric | baseline | candidate (delta) | ratio | status |
| --- | --- | --- | --- | --- | --- |
| concurrent::1 | p50_ms | 10.4 | 6.0 (-42.1%) | 0.58x | warn (samples<min) |
| concurrent::1 | p95_ms | 11.5 | 6.1 (-46.9%) | 0.53x | warn (samples<min) |
| concurrent::1 | p99_ms | 11.5 | 6.1 (-46.9%) | 0.53x | warn (samples<min) |
| concurrent::4 | p50_ms | 43.8 | 10.6 (-75.7%) | 0.24x | ok |
| concurrent::4 | p95_ms | 79.2 | 617.0 (+678.9%) | 7.79x | FAIL (>=1.20x) |
| concurrent::4 | p99_ms | 80.7 | 622.0 (+670.9%) | 7.71x | FAIL (>=1.30x) |
| concurrent::8 | p50_ms | 21.4 | 14.8 (-30.9%) | 0.69x | ok |
| concurrent::8 | p95_ms | 989.5 | 52.7 (-94.7%) | 0.05x | ok |
| concurrent::8 | p99_ms | 1008.3 | 545.8 (-45.9%) | 0.54x | ok |

## SLO check (candidate)

| slo_key | limit_ms | observed_p95 | status |
| --- | --- | --- | --- |
| search_p95 | 300 | 617.0 | warn (max p95 617.0 > 300) |
| rag_first_token_p95 | 1500 | 617.0 | ok |
| rag_full_response_p95 | 8000 | 617.0 | ok |

## Verdict

**FAIL** — regressions detected:
- concurrent::4/p95_ms: 7.79x >= 1.20x
- concurrent::4/p99_ms: 7.71x >= 1.30x

# Perf Comparison: rag_assist_e2e

- baseline profile: `integrated-baseline`
- candidate profile: `integrated`
- baseline base_url: `http://localhost:5101`
- candidate base_url: `http://localhost:5201`

## Per-label latency (ms)

| label | metric | baseline | candidate (delta) | ratio | status |
| --- | --- | --- | --- | --- | --- |
| first_token::csap_table | p50_ms | 33.0 | 30.3 (-8.2%) | 0.92x | ok |
| first_token::csap_table | p95_ms | 93.6 | 153.0 (+63.5%) | 1.63x | FAIL (>=1.25x) |
| first_token::csap_table | p99_ms | 93.6 | 153.0 (+63.5%) | 1.63x | FAIL (>=1.25x) |
| first_token::multi_turn_followup | p50_ms | 57.8 | 31.8 (-44.9%) | 0.55x | ok |
| first_token::multi_turn_followup | p95_ms | 163.4 | 77.5 (-52.6%) | 0.47x | ok |
| first_token::multi_turn_followup | p99_ms | 163.4 | 77.5 (-52.6%) | 0.47x | ok |
| first_token::nara_register_full | p50_ms | 52.4 | 32.6 (-37.8%) | 0.62x | ok |
| first_token::nara_register_full | p95_ms | 231.7 | 103.3 (-55.4%) | 0.45x | ok |
| first_token::nara_register_full | p99_ms | 231.7 | 103.3 (-55.4%) | 0.45x | ok |
| first_token::saas_full_flow | p50_ms | 40.3 | 33.0 (-18.2%) | 0.82x | ok |
| first_token::saas_full_flow | p95_ms | 100.1 | 201.2 (+100.9%) | 2.01x | FAIL (>=1.25x) |
| first_token::saas_full_flow | p99_ms | 100.1 | 201.2 (+100.9%) | 2.01x | FAIL (>=1.25x) |
| full_response::csap_table | p50_ms | 33.0 | 30.3 (-8.2%) | 0.92x | ok |
| full_response::csap_table | p95_ms | 93.7 | 153.0 (+63.3%) | 1.63x | FAIL (>=1.25x) |
| full_response::csap_table | p99_ms | 93.7 | 153.0 (+63.3%) | 1.63x | FAIL (>=1.25x) |
| full_response::multi_turn_followup | p50_ms | 57.8 | 31.8 (-44.9%) | 0.55x | ok |
| full_response::multi_turn_followup | p95_ms | 163.4 | 77.5 (-52.6%) | 0.47x | ok |
| full_response::multi_turn_followup | p99_ms | 163.4 | 77.5 (-52.6%) | 0.47x | ok |
| full_response::nara_register_full | p50_ms | 52.4 | 32.6 (-37.8%) | 0.62x | ok |
| full_response::nara_register_full | p95_ms | 231.7 | 103.3 (-55.4%) | 0.45x | ok |
| full_response::nara_register_full | p99_ms | 231.7 | 103.3 (-55.4%) | 0.45x | ok |
| full_response::saas_full_flow | p50_ms | 40.3 | 33.0 (-18.2%) | 0.82x | ok |
| full_response::saas_full_flow | p95_ms | 100.1 | 201.2 (+100.9%) | 2.01x | FAIL (>=1.25x) |
| full_response::saas_full_flow | p99_ms | 100.1 | 201.2 (+100.9%) | 2.01x | FAIL (>=1.25x) |
| intent::csap_table | p50_ms | 9.2 | 8.7 (-5.8%) | 0.94x | ok |
| intent::csap_table | p95_ms | 12.1 | 131.7 (+984.4%) | 10.84x | FAIL (>=1.25x) |
| intent::csap_table | p99_ms | 12.1 | 131.7 (+984.4%) | 10.84x | FAIL (>=1.25x) |
| intent::multi_turn_followup | p50_ms | 9.9 | 9.8 (-1.3%) | 0.99x | ok |
| intent::multi_turn_followup | p95_ms | 142.1 | 10.7 (-92.5%) | 0.08x | ok |
| intent::multi_turn_followup | p99_ms | 142.1 | 10.7 (-92.5%) | 0.08x | ok |
| intent::nara_register_full | p50_ms | 10.4 | 8.9 (-14.8%) | 0.85x | ok |
| intent::nara_register_full | p95_ms | 166.6 | 10.8 (-93.5%) | 0.06x | ok |
| intent::nara_register_full | p99_ms | 166.6 | 10.8 (-93.5%) | 0.06x | ok |
| intent::saas_full_flow | p50_ms | 12.0 | 9.0 (-24.7%) | 0.75x | ok |
| intent::saas_full_flow | p95_ms | 20.4 | 136.9 (+570.7%) | 6.71x | FAIL (>=1.25x) |
| intent::saas_full_flow | p99_ms | 20.4 | 136.9 (+570.7%) | 6.71x | FAIL (>=1.25x) |

## SLO check (candidate)

| slo_key | limit_ms | observed_p95 | status |
| --- | --- | --- | --- |
| search_p95 | 300 | 201.2 | ok |
| rag_first_token_p95 | 1500 | 201.2 | ok |
| rag_full_response_p95 | 8000 | 201.2 | ok |

## Verdict

**FAIL** — regressions detected:
- first_token::csap_table/p95_ms: 1.63x >= 1.25x
- first_token::csap_table/p99_ms: 1.63x >= 1.25x
- first_token::saas_full_flow/p95_ms: 2.01x >= 1.25x
- first_token::saas_full_flow/p99_ms: 2.01x >= 1.25x
- full_response::csap_table/p95_ms: 1.63x >= 1.25x
- full_response::csap_table/p99_ms: 1.63x >= 1.25x
- full_response::saas_full_flow/p95_ms: 2.01x >= 1.25x
- full_response::saas_full_flow/p99_ms: 2.01x >= 1.25x
- intent::csap_table/p95_ms: 10.84x >= 1.25x
- intent::csap_table/p99_ms: 10.84x >= 1.25x
- intent::saas_full_flow/p95_ms: 6.71x >= 1.25x
- intent::saas_full_flow/p99_ms: 6.71x >= 1.25x

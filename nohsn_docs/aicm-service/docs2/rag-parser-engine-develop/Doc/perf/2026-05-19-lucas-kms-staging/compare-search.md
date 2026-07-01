# Perf Comparison: search_latency

- baseline profile: `integrated`
- candidate profile: `integrated`
- baseline base_url: `http://localhost:5101`
- candidate base_url: `http://localhost:5201`

## Per-label latency (ms)

| label | metric | baseline | candidate (delta) | ratio | status |
| --- | --- | --- | --- | --- | --- |
| cold::cold_csap_levels | p50_ms | 8.3 | 3.0 (-63.6%) | 0.36x | ok |
| cold::cold_csap_levels | p95_ms | 10.0 | 3.2 (-67.9%) | 0.32x | ok |
| cold::cold_csap_levels | p99_ms | 10.0 | 3.2 (-67.9%) | 0.32x | ok |
| cold::cold_nara_register | p50_ms | 8.1 | 2.9 (-64.4%) | 0.36x | ok |
| cold::cold_nara_register | p95_ms | 8.8 | 3.3 (-62.2%) | 0.38x | ok |
| cold::cold_nara_register | p99_ms | 8.8 | 3.3 (-62.2%) | 0.38x | ok |
| cold::cold_saas_intro | p50_ms | 8.3 | 2.9 (-65.7%) | 0.34x | ok |
| cold::cold_saas_intro | p95_ms | 10.2 | 3.1 (-70.1%) | 0.30x | ok |
| cold::cold_saas_intro | p99_ms | 10.2 | 3.1 (-70.1%) | 0.30x | ok |
| filtered::filter_doc_type | p50_ms | 9.6 | 4.0 (-57.9%) | 0.42x | ok |
| filtered::filter_doc_type | p95_ms | 10.8 | 5.0 (-53.2%) | 0.47x | ok |
| filtered::filter_doc_type | p99_ms | 10.8 | 5.0 (-53.2%) | 0.47x | ok |
| multi_turn::csap_flow::turn1 | p50_ms | 8.1 | 3.0 (-63.4%) | 0.37x | ok |
| multi_turn::csap_flow::turn1 | p95_ms | 10.6 | 3.3 (-68.5%) | 0.31x | ok |
| multi_turn::csap_flow::turn1 | p99_ms | 10.6 | 3.3 (-68.5%) | 0.31x | ok |
| multi_turn::csap_flow::turn2 | p50_ms | 8.0 | 3.0 (-61.8%) | 0.38x | ok |
| multi_turn::csap_flow::turn2 | p95_ms | 9.1 | 3.7 (-59.7%) | 0.40x | ok |
| multi_turn::csap_flow::turn2 | p99_ms | 9.1 | 3.7 (-59.7%) | 0.40x | ok |
| multi_turn::csap_flow::turn3 | p50_ms | 8.4 | 3.2 (-62.5%) | 0.37x | ok |
| multi_turn::csap_flow::turn3 | p95_ms | 10.4 | 4.2 (-59.3%) | 0.41x | ok |
| multi_turn::csap_flow::turn3 | p99_ms | 10.4 | 4.2 (-59.3%) | 0.41x | ok |
| multi_turn::nara_flow::turn1 | p50_ms | 8.3 | 3.0 (-63.4%) | 0.37x | ok |
| multi_turn::nara_flow::turn1 | p95_ms | 9.6 | 3.6 (-62.8%) | 0.37x | ok |
| multi_turn::nara_flow::turn1 | p99_ms | 9.6 | 3.6 (-62.8%) | 0.37x | ok |
| multi_turn::nara_flow::turn2 | p50_ms | 7.6 | 3.0 (-60.6%) | 0.39x | ok |
| multi_turn::nara_flow::turn2 | p95_ms | 9.0 | 3.3 (-63.8%) | 0.36x | ok |
| multi_turn::nara_flow::turn2 | p99_ms | 9.0 | 3.3 (-63.8%) | 0.36x | ok |
| multi_turn::nara_flow::turn3 | p50_ms | 7.8 | 3.0 (-61.2%) | 0.39x | ok |
| multi_turn::nara_flow::turn3 | p95_ms | 9.0 | 3.4 (-61.8%) | 0.38x | ok |
| multi_turn::nara_flow::turn3 | p99_ms | 9.0 | 3.4 (-61.8%) | 0.38x | ok |
| ood::stocks_ood | p50_ms | 7.8 | 3.0 (-62.0%) | 0.38x | ok |
| ood::stocks_ood | p95_ms | 8.6 | 3.6 (-58.1%) | 0.42x | ok |
| ood::stocks_ood | p99_ms | 8.6 | 3.6 (-58.1%) | 0.42x | ok |
| single::csap_levels | p50_ms | 8.1 | 3.3 (-59.7%) | 0.40x | ok |
| single::csap_levels | p95_ms | 9.0 | 4.0 (-56.1%) | 0.44x | ok |
| single::csap_levels | p99_ms | 9.0 | 4.0 (-56.1%) | 0.44x | ok |
| single::nara_register | p50_ms | 8.5 | 2.9 (-66.3%) | 0.34x | ok |
| single::nara_register | p95_ms | 13.5 | 3.1 (-77.0%) | 0.23x | ok |
| single::nara_register | p99_ms | 13.5 | 3.1 (-77.0%) | 0.23x | ok |
| single::noisy_citation | p50_ms | 9.0 | 3.1 (-65.5%) | 0.34x | ok |
| single::noisy_citation | p95_ms | 12.1 | 3.8 (-68.7%) | 0.31x | ok |
| single::noisy_citation | p99_ms | 12.1 | 3.8 (-68.7%) | 0.31x | ok |
| single::saas_intro | p50_ms | 8.2 | 3.0 (-63.5%) | 0.37x | ok |
| single::saas_intro | p95_ms | 9.4 | 5.2 (-44.8%) | 0.55x | ok |
| single::saas_intro | p99_ms | 9.4 | 5.2 (-44.8%) | 0.55x | ok |

## SLO check (candidate)

| slo_key | limit_ms | observed_p95 | status |
| --- | --- | --- | --- |
| search_p95 | 300 | 5.2 | ok |
| rag_first_token_p95 | 1500 | 5.2 | ok |
| rag_full_response_p95 | 8000 | 5.2 | ok |

## Verdict

**PASS** — no regression above configured ratios.

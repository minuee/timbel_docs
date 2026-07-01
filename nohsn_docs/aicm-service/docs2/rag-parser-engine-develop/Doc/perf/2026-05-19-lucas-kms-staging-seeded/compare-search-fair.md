# Perf Comparison: search_latency

- baseline profile: `integrated`
- candidate profile: `integrated`
- baseline base_url: `http://localhost:5101`
- candidate base_url: `http://localhost:5201`

## Per-label latency (ms)

| label | metric | baseline | candidate (delta) | ratio | status |
| --- | --- | --- | --- | --- | --- |
| cold::cold_csap_levels | p50_ms | 8.3 | 6.8 (-18.1%) | 0.82x | ok |
| cold::cold_csap_levels | p95_ms | 10.0 | 8.3 (-17.5%) | 0.82x | ok |
| cold::cold_csap_levels | p99_ms | 10.0 | 8.3 (-17.5%) | 0.82x | ok |
| cold::cold_nara_register | p50_ms | 8.1 | 6.6 (-18.4%) | 0.82x | ok |
| cold::cold_nara_register | p95_ms | 8.8 | 7.2 (-17.4%) | 0.83x | ok |
| cold::cold_nara_register | p99_ms | 8.8 | 7.2 (-17.4%) | 0.83x | ok |
| cold::cold_saas_intro | p50_ms | 8.3 | 6.3 (-24.8%) | 0.75x | ok |
| cold::cold_saas_intro | p95_ms | 10.2 | 7.2 (-29.8%) | 0.70x | ok |
| cold::cold_saas_intro | p99_ms | 10.2 | 7.2 (-29.8%) | 0.70x | ok |
| filtered::filter_doc_type | p50_ms | 9.6 | 6.6 (-31.0%) | 0.69x | ok |
| filtered::filter_doc_type | p95_ms | 10.8 | 7.8 (-27.6%) | 0.72x | ok |
| filtered::filter_doc_type | p99_ms | 10.8 | 7.8 (-27.6%) | 0.72x | ok |
| multi_turn::csap_flow::turn1 | p50_ms | 8.1 | 6.6 (-18.7%) | 0.81x | ok |
| multi_turn::csap_flow::turn1 | p95_ms | 10.6 | 8.0 (-25.0%) | 0.75x | ok |
| multi_turn::csap_flow::turn1 | p99_ms | 10.6 | 8.0 (-25.0%) | 0.75x | ok |
| multi_turn::csap_flow::turn2 | p50_ms | 8.0 | 7.1 (-10.9%) | 0.89x | ok |
| multi_turn::csap_flow::turn2 | p95_ms | 9.1 | 8.9 (-2.6%) | 0.97x | ok |
| multi_turn::csap_flow::turn2 | p99_ms | 9.1 | 8.9 (-2.6%) | 0.97x | ok |
| multi_turn::csap_flow::turn3 | p50_ms | 8.4 | 8.1 (-4.5%) | 0.95x | ok |
| multi_turn::csap_flow::turn3 | p95_ms | 10.4 | 10.6 (+1.7%) | 1.02x | ok |
| multi_turn::csap_flow::turn3 | p99_ms | 10.4 | 10.6 (+1.7%) | 1.02x | ok |
| multi_turn::nara_flow::turn1 | p50_ms | 8.3 | 6.6 (-21.1%) | 0.79x | ok |
| multi_turn::nara_flow::turn1 | p95_ms | 9.6 | 7.7 (-20.5%) | 0.80x | ok |
| multi_turn::nara_flow::turn1 | p99_ms | 9.6 | 7.7 (-20.5%) | 0.80x | ok |
| multi_turn::nara_flow::turn2 | p50_ms | 7.6 | 7.7 (+1.6%) | 1.02x | ok |
| multi_turn::nara_flow::turn2 | p95_ms | 9.0 | 162.7 (+1699.7%) | 18.00x | FAIL (>=1.20x) |
| multi_turn::nara_flow::turn2 | p99_ms | 9.0 | 162.7 (+1699.7%) | 18.00x | FAIL (>=1.30x) |
| multi_turn::nara_flow::turn3 | p50_ms | 7.8 | 6.1 (-22.4%) | 0.78x | ok |
| multi_turn::nara_flow::turn3 | p95_ms | 9.0 | 7.0 (-22.2%) | 0.78x | ok |
| multi_turn::nara_flow::turn3 | p99_ms | 9.0 | 7.0 (-22.2%) | 0.78x | ok |
| ood::stocks_ood | p50_ms | 7.8 | 6.9 (-11.6%) | 0.88x | ok |
| ood::stocks_ood | p95_ms | 8.6 | 9.4 (+9.5%) | 1.10x | ok |
| ood::stocks_ood | p99_ms | 8.6 | 9.4 (+9.5%) | 1.10x | ok |
| single::csap_levels | p50_ms | 8.1 | 6.4 (-20.8%) | 0.79x | ok |
| single::csap_levels | p95_ms | 9.0 | 7.5 (-17.0%) | 0.83x | ok |
| single::csap_levels | p99_ms | 9.0 | 7.5 (-17.0%) | 0.83x | ok |
| single::nara_register | p50_ms | 8.5 | 6.7 (-21.1%) | 0.79x | ok |
| single::nara_register | p95_ms | 13.5 | 7.2 (-46.4%) | 0.54x | ok |
| single::nara_register | p99_ms | 13.5 | 7.2 (-46.4%) | 0.54x | ok |
| single::noisy_citation | p50_ms | 9.0 | 6.5 (-27.3%) | 0.73x | ok |
| single::noisy_citation | p95_ms | 12.1 | 7.2 (-40.4%) | 0.60x | ok |
| single::noisy_citation | p99_ms | 12.1 | 7.2 (-40.4%) | 0.60x | ok |
| single::saas_intro | p50_ms | 8.2 | 6.6 (-19.7%) | 0.80x | ok |
| single::saas_intro | p95_ms | 9.4 | 8.6 (-8.2%) | 0.92x | ok |
| single::saas_intro | p99_ms | 9.4 | 8.6 (-8.2%) | 0.92x | ok |

## SLO check (candidate)

| slo_key | limit_ms | observed_p95 | status |
| --- | --- | --- | --- |
| search_p95 | 300 | 162.7 | ok |
| rag_first_token_p95 | 1500 | 162.7 | ok |
| rag_full_response_p95 | 8000 | 162.7 | ok |

## Verdict

**FAIL** — regressions detected:
- multi_turn::nara_flow::turn2/p95_ms: 18.00x >= 1.20x
- multi_turn::nara_flow::turn2/p99_ms: 18.00x >= 1.30x

"""Performance benchmark suite for Lucas-KMS vs integrated Locus.

See tests/perf/README or scripts/perf/run_benchmark.sh for usage.
All measurements are data-driven via:
- tests/perf/scenarios.yml  (query / multi-turn / OOD / table cases)
- tests/perf/thresholds.yml  (p50/p95/p99 regression gates)
"""

# tools/docker_scan

Phase 0 T0.7 — Lucas-KMS Docker image 의 agent 코드 흔적 multi-layer scan.

## 스크립트

| 스크립트 | 설명 |
|---|---|
| `scan.sh` | docker history / filesystem / pip / import 4-layer scan |

## 사용법

```bash
chmod +x tools/docker_scan/scan.sh
tools/docker_scan/scan.sh lucas-kms:latest
```

## 검사 항목

1. `docker history --no-trunc` 의 모든 layer 에 `lucas_agent | lucas-agent` 흔적
2. 최종 image filesystem 의 디렉토리
3. `pip show lucas-agent` → not found
4. `python -c "import lucas_agent"` → ImportError

모두 PASS 시 종료 코드 0. 하나라도 FAIL 시 비-0.

## Phase 3 활용

T3.6 Dockerfile.lucas-kms 빌드 후 본 scan 을 *반드시 통과* 시켜야 함.
CI 의 docker build → scan → push 파이프라인의 gate.

# Lucas-KMS Docker Image Scan — 2026-05-19

## Image

- Tag: `lucas-kms:0.2`
- Manifest list digest: `sha256:d0271dba05a029ca2cf797875c6f9c18eda82c47bac9493ca127697d68b53ffc`
- Base: `python:3.11-slim`
- Disk usage: 14.6 GB (compressed content size 4.89 GB — torch cu128 + transformers + FlagEmbedding)
- `/app` 디렉토리 크기: 5.6 MB

## Build context filter — `.dockerignore` 신설

Phase 3 packaging 의 핵심 신규 가드. 정적 격리 (LUCAS_PRODUCT=kms dynamic router 차단)
위에 *물리적 격리* 추가 — build context 자체에 agent_framework 가 진입하지 않음.

주요 제외 항목:

- `src/agent_framework/` — 분리 핵심
- `tests/agent_framework/`
- `src/src/` — 재귀적 잔여 디렉토리 (build cache artifact 차단)
- `frontend/`, `frontend-v3/`
- `tests/full/`, `Doc/TestDoc/`, `Doc/eval/`
- `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.venv/`
- `.env*`, `*.pem`, `*.key` (secret 차단 — 별도 안전망)
- `hf_cache/`, `data/`, `uploads/`, `*.log`

## Build 결과

```
PASS — 11 stage build 정상 종료
- COPY src/ src/ : 4.47 MB context (.dockerignore 적용 후, agent_framework 제외)
- COPY alembic/ alembic/
- COPY alembic.ini
- exporting manifest list sha256:d0271dba05a0...
- Pre-flight: pyproject.toml 누락 발견 → AICM-APIs 원본에서 복사 (현 단계 임시 조치).
  Phase 3 정식화 시 Locus-KMS 전용 pyproject.toml 생성 필요 (TODO).
```

## 4-layer scan 결과 (`tools/docker_scan/scan.sh lucas-kms:0.2`)

| Step | 검사 | 결과 |
|---|---|---|
| 1/7 | docker history layer scan (`lucas_agent`/`lucas-agent`) | OK — 0 hit |
| 2/7 | filesystem find (`lucas_agent`/`lucas-agent`) | OK — 0 디렉토리 |
| 3/7 | pip show lucas-agent | OK — not found |
| 4/7 | python -c "import lucas_agent" | OK — ImportError |
| 5/7 | tarball / wheel / archive 흔적 | OK — 0 hit |
| 6/7 | OpenAPI schema scan | SKIP (--with-runtime 미지정 — 추후 staging 검증) |
| 7/7 | SBOM (cyclonedx) | SKIP (cyclonedx tool 미설치 — CI base image 보강 TODO) |

**최종 verdict: `PASS: lucas-agent 0 trace in lucas-kms:0.2`**

## 추가 dynamic 검증 — `agent_framework` 디렉토리 직접 확인

scan.sh 는 `lucas_agent` / `lucas-agent` 명명 규칙을 검사하므로 현재의 디렉토리명
`agent_framework` 에 대한 별도 dynamic 확인 수행:

```
docker run --rm --entrypoint sh lucas-kms:0.2 -c \
    'find /app -type d -name agent_framework 2>/dev/null'
→ (출력 없음)

docker run --rm --entrypoint sh lucas-kms:0.2 -c 'ls /app/src/'
→ __init__.py api common core integration pipeline reranker_service search
```

`agent_framework`, `src/src/` 모두 최종 image 에 부재 — `.dockerignore` 작동 입증.

## 잔여 / TODO

1. **pyproject.toml 임시 복사** — AICM-APIs 원본 사용. Phase 3 정식 closure 시
   Locus-KMS 전용 pyproject (KMS 의존성만 추출) 생성 권장.
2. **scan.sh 명명 보강** — `agent_framework` 패턴도 검사 키워드에 추가하면
   현 디렉토리명 변경 없이 직접 검출 가능 (현재는 `lucas_agent` 명명 기준).
3. **--with-runtime OpenAPI scan** — staging 컨테이너 기동 후 6/7 step PASS 확인.
4. **cyclonedx-py CI 설치** — 7/7 SBOM step 의 SKIP → PASS 격상.

## 결론

`lucas-kms:0.2` image 는 Phase 3 packaging 의 artifact-layer 격리 기준을 통과.
`.dockerignore` 가 정적 격리 보강 — agent_framework / 재귀 src / 캐시 / 시크릿 모두
build context 진입 차단. 4-layer scan PASS (2 SKIP 은 환경 의존, 운영 영향 X).

# Lucas-KMS Docker Image — Artifact Scan Checklist

spec: `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md` Section 12.1

이 checklist 는 `tools/docker_scan/scan.sh` 가 자동 검사한다. Lucas-KMS 분리 이미지가
push 되기 전 **모든 항목 PASS** 가 필수.

## 4-Layer Validation (spec Section 12.1)

| Layer | 검사 항목 | 통과 기준 | scan.sh step |
|---|---|---|---|
| Static | import-linter / grep / grimp | 0 violation | (CI 별도) |
| Dynamic | `sys.modules` 에 `lucas_agent` 0건 | 0 모듈 | (runtime test 별도) |
| Artifact | 본 checklist 의 [1]–[7] | 모두 PASS | scan.sh |
| Repo history | `git log --all --name-only` 에 agent 0건 | 0 hit | (T38, 별도) |

## scan.sh 검사 항목

### [1] docker history layer scan
- 명령: `docker history --no-trunc <img> | grep -E "lucas_agent|lucas-agent"`
- 기준: 0 hit
- 의미: 빌드 단계에서 한 번이라도 agent 파일이 추가된 layer 가 있으면 fail

### [2] filesystem scan
- 명령: 최종 image 내부 `find / -type d -name lucas_agent -o -name lucas-agent`
- 기준: 0 디렉토리
- 의미: 멀티 스테이지 build 후에도 남아있는 디렉토리 잔존 검사

### [3] pip show
- 명령: `pip show lucas-agent`
- 기준: not found
- 의미: pip metadata 에 lucas-agent 패키지 미설치

### [4] import attempt
- 명령: `python -c "import lucas_agent"`
- 기준: ImportError / ModuleNotFoundError
- 의미: 모듈 검색 경로에 lucas_agent 미존재

### [5] tarball / wheel / zip archive scan (Phase 5 신설)
- 명령: image 내부의 `*.tar.gz / *.whl / *.zip / *.tar` 안 내용까지 검사
- 기준: 파일명 + archive 내용 모두 0 hit
- 의미: build cache, source dist, dependency wheel 안에 source code 가 끼어드는 사례 차단

### [6] OpenAPI schema scan (Phase 5 신설, optional)
- 명령: `--with-runtime` 옵션 시 컨테이너 임시 기동 → `curl /api/v1/openapi.json`
  → `paths` 에서 `agent | skill | persona` 키워드 검사
- 기준: 0 hit
- 의미: 의도치 않게 router 에 등록된 agent endpoint 가 *실제 OpenAPI schema 에 노출*
  되는지 final dynamic 검사

### [7] SBOM (cyclonedx) — optional
- 명령: `pip freeze` 결과 + (가용 시) cyclonedx SBOM 의 lucas-agent metadata
- 기준: 0 항목
- 의미: 공급망 보안 — SBOM 의 dependency 그래프에서도 agent 미발견

## 운영자 사용법

### Basic 4-layer scan
```bash
chmod +x tools/docker_scan/scan.sh
tools/docker_scan/scan.sh lucas-kms:latest
```

### Full 7-layer (with OpenAPI runtime check)
```bash
SCAN_RUNTIME_PORT=15101 tools/docker_scan/scan.sh lucas-kms:latest --with-runtime
```

## 통과 기준

| 결과 | 의미 |
|---|---|
| `PASS: lucas-agent 0 trace in <img>` | 모든 layer 통과 — push 가능 |
| `FAIL: ...` (exit 1) | 한 layer 라도 실패 — 빌드 context / `.dockerignore` 재점검 |
| `SKIP` | 환경 의존 항목 — 정보용 (예: cyclonedx 미설치) |

`SKIP` 항목이라도 CI/release pipeline 에서는 추가 도구 설치하여 PASS 까지 달성 권장.

## CI 통합 권장 위치

`Phase 3` 의 Docker build job 에서:

```yaml
- name: Build Lucas-KMS image
  run: docker build -f Dockerfile.lucas-kms -t lucas-kms:ci .
- name: Multi-layer artifact scan
  run: tools/docker_scan/scan.sh lucas-kms:ci
- name: Push (only if scan passed)
  run: docker push ...
```

## 추후 보강 TODO

- [ ] `cyclonedx-py` 를 CI base image 에 사전 설치 → SBOM 항목 SKIP 제거
- [ ] OpenAPI schema 검사를 standalone tool 분리 (lucas-shared 의 endpoint registry 직접 검사)
- [ ] `find /` 의 디렉토리 검사 외 추가로 `find / -name "*.py" -exec grep -l "from lucas_agent" {} \;`
      runtime python source 도 grep — phase 0 import_linter 와 중복이지만 별 image build 변형 시 안전망

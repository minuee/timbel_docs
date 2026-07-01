# Locus-KMS — 핸드오프 (이 폴더만 열면 작업 이어가기)

작성: 2026-05-19
다음 세션 진입 시 가장 먼저 읽을 문서.

---

## 0. 한 줄 현황

**Locus-KMS v1.0.1 release 완료** — gitlab tag `Locus-KMS1.0.1`, github `Locus-KMS` main 동기 직전. 운영 docker-compose self-contained, 검증 4-layer PASS. 후속 작업은 *선택적 보강* (Phase 3 packaging refactor, frontend dockerize 등).

## 1. 마지막 commit

```
f2087be  fix(documents): 동일 내용/제목 문서 중복 적재 차단   ← HEAD (2026-06-08), gitlab/locus-kms-release-1.0
a158121  fix(rag_assist): assist-stream 에 분류 권한 스코프 필터   ┐
4571d24  fix(kms): 서버 운영 working state 통합 (preview OCR on 등) │ 05-26~06-08
cf176dd  fix(pipeline): main 컨슈머 max_poll_interval 재처리 루프 │ 운영/연동 수정 다수
...                                                              ┘ (커밋 ~20건)
885e133  docs(kms-only): 문서 인덱스 + 현재 상태 매뉴얼 + pyproject.toml   ← tag Locus-KMS1.0.1 (v1.0.1 release 시점)
8f6de33  (tag: Locus-KMS1.0) fix(deploy): init_db.py + QUICKSTART + host.docker.internal
```

## 2. Remotes / push 상태

| Remote | URL | 상태 |
|---|---|---|
| `origin` (github) | `https://github.com/RickySonYH/Locus-KMS` | `main` = `e49c590` — **`885e133` (새 commit) 미반영**. 추후 `git push origin main` 필요. |
| `gitlab` | `https://gitlab.timbel.dev/apps/langsa/rag-parser-engine` | `locus-kms-release-1.0` = `f2087be` ✅ (2026-06-08 push, `a158121..f2087be`) |
| Tags (gitlab) | `Locus-KMS1.0` (`8f6de33`), `Locus-KMS1.0.1` (`885e133`) | ✅ 둘 다 push 완료 |

> 참고: `885e133`(v1.0.1) 이후 05-26~06-08 운영/연동 수정 ~20건이 `locus-kms-release-1.0`에 누적됨(dedup·OCR·재처리루프·카테고리권한 등). 본 HANDOFF 의 §3 staging(5201 포트, /home/Ricky-Dev)은 v1.0.1 시점 기준이며, 이후 연동 검증은 새 서버(192.168.101.192) + AICC B200(59.150.35.1:49910)에서 진행됨.

> github origin 은 사용자가 명시 push 요청하기 전까지 *보류*. 이번 세션은 gitlab 만 처리.

## 3. 떠있는 staging 환경 (2026-05-19 기준)

| 컨테이너 | 이미지 | 포트 | 상태 |
|---|---|---|---|
| lucas-kms-api | aicm-apis-api | 5201 → 8000 | healthy (3h) |
| lucas-kms-worker-large | lucas-kms:latest | (internal) | healthy |
| lucas-kms-worker-small | lucas-kms:latest | (internal) | healthy |
| lucas-kms-postgres | postgres:16-alpine | 5210 → 5432 | healthy (5h) |
| lucas-kms-qdrant | qdrant/qdrant:v1.12.1 | 5211/5212 | healthy |
| lucas-kms-elasticsearch | elasticsearch:8.15.0 | 5213 → 9200 | healthy |
| lucas-kms-kafka | apache/kafka:latest | 5214 → 9094 | healthy |
| lucas-kms-redis | redis:7-alpine | 5215 → 6379 | healthy |
| lucas-kms-minio | minio/minio:latest | 5216/5217 | healthy |

healthz: `curl http://localhost:5201/health` → `{"status":"ok"}`

frontend (5252) — docker 컨테이너 미존재. WSL Windows 측 dev server 추정. 본격 정리 미진행.

## 4. 본 release 까지의 검증 결과

| 항목 | 결과 |
|---|---|
| e2e ingest | 14초 / 4p PDF, 9 blocks |
| 공정 perf (실 데이터, integrated vs Locus-KMS) | API −20% / RAG −53% / c=8 tail −89% |
| 분리 정확성 | integrated 315 routes → Locus-KMS 192 routes (agent 0) |
| 4-layer artifact scan | PASS |
| import-linter (KMS → agent) | 0 import |
| 인프라 fix | schema dump + kms_app role + 권한 GRANT |
| GPT-5.5 최종 verification | PASS (`Doc/research/2026-05-19-lucas-kms-phase5-final.gpt55.txt` — AICM-APIs 측) |

원본:
- `Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md`
- `Doc/solution/2026-05-19-locus-kms-deployment-ready.md`
- `Doc/scan/2026-05-19-lucas-kms-image-scan.md`

## 5. 미진행 작업 / 알려진 한계

### 5.1 권장 후속 (우선순위 순)

| 우선도 | 항목 | 영향 | 작업 위치 |
|---|---|---|---|
| 중 | **Phase 3 packaging refactor** — `src/api/routers/` 의 agent 잔존 파일 (`agents_v1.py`, `agent_management.py`, `agent_documents_v1.py` 등) 물리 제거 | 현재 runtime/build 양쪽 격리 OK 라 *기능 영향 X*. KMS-only 순도만 개선. | 본 repo + AICM-APIs Phase 3 동기화 |
| 중 | **lucas-shared vendoring** — staging compose 의 `/home/Ricky-Dev/AICM-APIs/packages/lucas-shared` 절대경로 의존 해소. 본 repo 에 `packages/lucas-shared` 복사. | dev 편의성. 운영은 영향 X (image 자체 내장). | 본 repo |
| 중 | **frontend dockerize** — `frontend/` 를 nginx static container 로 컨테이너화. 5252 port 안정화. | dev / 데모 편의성. | 본 repo |
| 낮음 | **csap_table 시나리오 perf 보강** — 측정 시 +63% latency (data 부족). | 운영 데이터 충분 시드되면 자동 해소. | 추가 시드 + 재측정 |
| 낮음 | **운영 보안 체크리스트 자동화** — .env 검증 스크립트 (`LUCAS_AUTH_DISABLED=false` + `ENABLE_SWAGGER=false` + 비밀번호 강도). | 운영 배포 사고 예방. | `scripts/preflight.sh` 신규 |
| 낮음 | **alembic enum 이중 생성 버그** — 근본 fix (alembic version 격리). | 현재 `init_db.py` (create_all) 우회로 충분. | alembic 측 PR 또는 wrapping |
| 중 | **문서 dedup 동시성 봉쇄** — `f2087be`의 content-hash dedup은 조회→생성 사이 경합(TOCTOU)에 취약(동시 동일 업로드 2건). | 실 시나리오 순차라 영향 낮으나 근본봉쇄 미비. | `documents.processing_meta->>'source_sha256'` 부분 unique 인덱스(마이그레이션) |
| 낮음 | **dedup 시 category 병합** — content-hash hit 시 들어온 `category_ids`를 버림 → "같은 문서 다른 카테고리" 미지원. | UX 한계(현재는 차단). | `upload_document` dedup 분기에서 기존 문서 categories N:M 병합 |

### 5.2 알려진 한계 (대응 적용 중)

| 한계 | 영향 | 현 대응 |
|---|---|---|
| alembic fresh DB enum 이중 생성 | DB init 실패 | migrate 가 `scripts/init_db.py` (create_all) 자동 호출 |
| `host.docker.internal` Linux 미해석 | mode A default endpoint 실패 | `docker-compose.yml` 에 `extra_hosts: ["host.docker.internal:host-gateway"]` 적용됨 |
| `kms_app` role 권한 부족 | API permission denied | `init_db.py` 가 GRANT 수행 |
| agent_framework 코드가 routers/ 에 *물리 존재* | image 사이즈 + 순도 (runtime 영향 X) | `.dockerignore` + `main_kms.py` 격리 / Phase 3 정리 예정 |
| `csap_table` 시나리오 +63% | 특정 query latency | 운영 시드 충분 시 해소 |

## 6. 다음 세션이 작업 시작 전 확인할 것

1. **본 폴더에서 작업 중인지 확인** — `pwd` 가 `/home/Ricky-Dev/Locus-KMS`. AICM-APIs 와 헷갈리지 말 것.
2. **두 product 분리 절칙 확인** — `CLAUDE.md` §1.
3. **현 staging 상태 확인** — `docker ps --filter "name=lucas-kms-"` 가 5h+ healthy 여야 함. 안 떠있으면 `docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d`.
4. **사용자 요청 분류** — KMS 관련 / Locus 본체 관련 / 양쪽 모두인지.
5. **변경 commit 전 확인** — 이모지 X / 하드코딩 X / KMS-only 격리 유지.

## 7. 작업 이어받기 시나리오별 진입점

| 시나리오 | 진입점 |
|---|---|
| API 새 endpoint 추가 | `DEVELOPMENT.md` §3.1 |
| DB schema 변경 | `DEVELOPMENT.md` §3.2 |
| Pipeline worker 추가 | `DEVELOPMENT.md` §3.3 |
| Frontend 수정 | `DEVELOPMENT.md` §3.4 |
| 버그 추적 (traceback) | `DEVELOPMENT.md` §4.6 |
| 성능 측정 | `DEVELOPMENT.md` §6 |
| 운영 배포 | `QUICKSTART.md` + `docs/deployment/lucas-kms-public-saas-deployment.md` |
| 운영자 사용 | `docs/deployment/lucas-kms-operator-manual.md` |
| Tenant 격리 운영 | `docs/deployment/lucas-kms-public-saas-multi-tenant.md` |
| Phase 3 packaging refactor | (AICM-APIs 의 `docs/superpowers/plans/2026-05-19-lucas-kms-separation.md` 참조) |

## 8. AICM-APIs 본체 측 진행 상태 (참고용)

본 repo 와는 *별개* 지만, 일부 분리 작업은 AICM-APIs 에서도 진행 중:
- AICM-APIs branch `KMS-Plus` HEAD `20a7b26` (Lucas-KMS v1.0 배포 준비 완료 종합 보고)
- Phase 1 T1.1-T1.3 완료, T1.4-T1.6 미완료 (`src/api/main_kms.py` 분리 자체는 본 repo 에는 이미 적용됨)
- Phase 2 (Alembic multi-branch + RLS FORCE + multi-store isolation) 완료
- Phase 3 (uv workspace + packages/ 이동) v0.1 진행 중 (storage_tenant / time_utils / agent_hook 만 분리, 나머지는 미진행)
- Phase 4-5 완료

자세한 사항은 AICM-APIs 의 메모리: `/home/rickyson/.claude/projects/-home-Ricky-Dev-AICM-APIs/memory/project_lucas_kms_separation_20260519.md`

---

## 9. 핸드오프 갱신 정책

본 문서는 *시점 의존*. 큰 변경 (release / phase 완료 / breaking change) 후 반드시 갱신.

갱신 시 추가할 것:
- §1 마지막 commit
- §2 push 상태
- §3 staging 환경 변경
- §4 새 검증 결과
- §5 새 후속 또는 해소된 한계

---

> 본 폴더만 열고 작업을 이어가려면: `CLAUDE.md` → 본 문서 → `DEVELOPMENT.md` → 사용자 요청 분류 → 작업.

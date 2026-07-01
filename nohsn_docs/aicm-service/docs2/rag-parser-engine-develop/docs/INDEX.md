# Locus-KMS — 문서 인덱스

작성: 2026-05-19
대상: 운영자 / 통합 파트너 / 신규 합류자

Locus-KMS (KMS-only standalone) 문서 전체 navigation hub. 처음 진입자는 `README.md` → `QUICKSTART.md` → 본 INDEX 순으로 본다.

---

## 1. 시작하기

| 문서 | 위치 | 대상 |
|---|---|---|
| 개요 + 핵심기능 + 빠른 시작 | [`README.md`](../README.md) | 모든 합류자 |
| 단계별 setup + 트러블슈팅 | [`QUICKSTART.md`](../QUICKSTART.md) | 첫 배포 운영자 |
| **본 폴더에서 작업 이어받기 (핸드오프)** | [`HANDOFF.md`](../HANDOFF.md) | 새 세션 진입자 — 마지막 commit / staging 상태 / 미진행 / 진입점 |
| **개발자 가이드 (수정·디버그·테스트)** | [`DEVELOPMENT.md`](../DEVELOPMENT.md) | 코드 수정·디버그·테스트하는 개발자 |
| AI 어시스턴트 컨텍스트 (자동 로드) | [`CLAUDE.md`](../CLAUDE.md) | Claude / Copilot / Codex |

## 2. API 통합

| 문서 | 위치 | 내용 |
|---|---|---|
| **API 사용 가이드** | [`docs/api/lucas-kms-api-reference.md`](api/lucas-kms-api-reference.md) | 14 섹션 + 부록 3. 모든 핵심 endpoint 의 path / body / response schema + curl / Python / JS 예시. 무인증·인증 모드 양쪽. SSE 스트리밍 (RAG assist-stream) 명세. AICMError 표 + retry/backoff. 통합 시나리오 3건. Python/TS SDK 스켈레톤. |
| OpenAPI Schema (live) | `http://<host>:<api-port>/api/v1/openapi.json` | 자동 생성. 클라이언트 SDK 생성용 |
| Swagger UI (live) | `http://<host>:<api-port>/api/v1/docs` | 운영 모드는 JWT + IP allowlist gated |
| Redoc (live) | `http://<host>:<api-port>/api/v1/redoc` | 읽기 전용 reference |

## 3. 배포 / 운영 매뉴얼

| 문서 | 위치 | 대상 |
|---|---|---|
| **공공 SaaS 배포 가이드** | [`docs/deployment/lucas-kms-public-saas-deployment.md`](deployment/lucas-kms-public-saas-deployment.md) | 인프라 담당. 호스트 요구사항 / vLLM endpoint / .env / 보안 / TLS / 모니터링 |
| **Multi-tenant 운영** | [`docs/deployment/lucas-kms-public-saas-multi-tenant.md`](deployment/lucas-kms-public-saas-multi-tenant.md) | Tenant 격리 (Postgres RLS + Qdrant/ES/MinIO/Redis/Kafka tenant scope) 운영 절차 |
| **성능 기준선** | [`docs/deployment/lucas-kms-public-saas-perf-baseline.md`](deployment/lucas-kms-public-saas-perf-baseline.md) | 회귀 임계값 / 측정 절차 / 정상 latency 분포 |
| **운영자 매뉴얼** | [`docs/deployment/lucas-kms-operator-manual.md`](deployment/lucas-kms-operator-manual.md) | Tenant 관리자 / 검토자. Library / Repo / Doc / 검토 큐 / 카테고리 / 폴더 / API 사용법 |

## 4. 현재 상태 / 라이브 환경

| 문서 | 위치 | 내용 |
|---|---|---|
| **현재 상태 매뉴얼 (KMS)** | [`docs/CURRENT_STATE.md`](CURRENT_STATE.md) | 본 시점 staging 환경 구성 / 떠있는 컨테이너 / 포트 / 마운트 구조 / 운영·점검 방법 |

## 5. 디자인 / 분리 spec

| 문서 | 위치 | 내용 |
|---|---|---|
| Lucas-KMS 분리 디자인 | [`docs/design/2026-05-19-lucas-kms-separation-design.md`](design/2026-05-19-lucas-kms-separation-design.md) | Lucas-KMS / Lucas-Agent 분리 아키텍처 spec |
| Lucas-KMS 분리 plan | [`docs/design/2026-05-19-lucas-kms-separation.md`](design/2026-05-19-lucas-kms-separation.md) | Phase 0-5 task 분해 + 검증 |

## 6. 배포 준비 보고 / 성능 결과

| 문서 | 위치 | 내용 |
|---|---|---|
| 배포 준비 완료 종합 보고 | [`Doc/solution/2026-05-19-locus-kms-deployment-ready.md`](../Doc/solution/2026-05-19-locus-kms-deployment-ready.md) | Phase 0-5 종합 / 검증 결과 / 배포 시나리오 3종 / 운영 전 체크리스트 |
| Staging seeded perf (공정) | [`Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md`](../Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md) | 실 데이터 환경 perf 재측정 — API −20% / RAG −53% / c=8 tail −89% |
| Staging perf (1차) | [`Doc/perf/2026-05-19-lucas-kms-staging/report.md`](../Doc/perf/2026-05-19-lucas-kms-staging/report.md) | Locus-KMS staging 배포 + 1차 측정 |
| Image scan | [`Doc/scan/2026-05-19-lucas-kms-image-scan.md`](../Doc/scan/2026-05-19-lucas-kms-image-scan.md) | 4-layer artifact scan 결과 |

## 7. 운영 / 점검 스크립트

```
scripts/perf/          # 성능 측정 (run_benchmark.sh)
scripts/regression/    # Locus 회귀 smoke
scripts/eval/          # GPT-5.5 검증
scripts/init_db.py     # DB schema + default tenant 초기화
```

## 8. 핵심 코드 진입점

| 영역 | 파일 |
|---|---|
| KMS API factory | `src/api/main_kms.py` (`create_kms_app()`) |
| 인증 (JWT v2) | `src/api/auth/`, `src/api/routers/auth_v2.py` |
| Tenant v1 | `src/api/routers/tenants_v1.py` |
| Repository | `src/api/routers/repositories.py` |
| Document | `src/api/routers/documents.py` |
| Search (하이브리드) | `src/api/routers/search.py`, `src/search/` |
| RAG (assist-stream SSE) | `src/api/routers/rag_assist.py`, `src/api/routers/rag.py` |
| Repository Groups | `src/api/routers/repository_groups.py` |
| Health | `src/api/routers/health.py` |
| Pipeline workers | `src/pipeline/` |
| 공통 (config / storage_tenant / time_utils / agent_hook) | `src/common/` |

---

> 본 INDEX 는 정적 navigation hub. 최신 commit 의 코드 자체가 진실의 원천. 문서가 코드와 어긋날 경우 코드 우선.

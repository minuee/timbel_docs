# Locus-KMS — AI Assistant Context

> 본 파일은 Claude / Copilot / Codex 같은 AI 어시스턴트가 본 repo 에서 작업할 때 자동 로드되는 컨텍스트 파일. 사람 개발자는 `README.md` → `QUICKSTART.md` → `DEVELOPMENT.md` → `HANDOFF.md` 순으로 본다.

---

## 0. Repo 정체 — 한 줄

**Locus-KMS = Locus 통합 솔루션 (AICM-APIs / branch `KMS-Plus`) 에서 KMS 기능만 분리한 KMS-only standalone product.** 별도 git repo, 별도 docker stack, 별도 release.

## 1. 두 product 영구 분리 절칙 (사용자 명시 — 2026-05-19)

| Product | 위치 | 정체 | 발전 방향 |
|---|---|---|---|
| **Locus 본체** | `/home/Ricky-Dev/AICM-APIs` (branch `KMS-Plus`) | 통합 솔루션 (KMS + Agent + Chat + Skill + Tool + Scheduler). 76 router mount, V3 frontend 포함. | 마지막 상태 *보존* + 앞으로도 *개선·발전 지속* |
| **Locus-KMS** | `/home/Ricky-Dev/Locus-KMS` (본 폴더) | KMS 만 분리한 독립 product. `main_kms.py` 가 KMS router 만 mount. | 별도 서비스로 *독립 운영* |

**Cross-edit 금지**: 본 repo (`Locus-KMS`) 작업은 AICM-APIs 에 자동 반영되지 *않음*. 두 repo 모두 손대야 할 변경이면 *각 repo 에 별도 commit*.

**판단 기준**:
- 사용자가 *"본체 / Locus / V3"* 표현 → AICM-APIs 작업
- 사용자가 *"KMS / 분리본 / locus-KMS 폴더"* → 본 repo 작업

## 2. 사용자 절대 규칙 (memory 에서 발췌)

| 규칙 | 적용 |
|---|---|
| **이모지 X** | 코드 / 커밋 메시지 / 파일 / 채팅 어디에도 이모지 X (2026-04-28 사용자 명시) |
| **하드코딩 X** | 키워드 리스트 / 사례 enum / 정해진 답변 문자열 금지. LLM 패턴 인식. (제 1 원칙, 2026-04-28) |
| **기존 백엔드 재작성 X** | 통째로 다시 짓기 X. 보안 / grounding / structured_block / verification 보강은 항상. |
| **검증 시 multi-turn** | 단발 정확도만 보지 말 것. 중복요청 / 부정형조회 / 시간slot / 참조해소 / capability 패턴 회귀 케이스. |
| **GPT-5.5 검증 + 사용자 동의** | 모든 변경 단계 (commit / DB / dispatch / restart) 시행 전. 단, *현 세션이 "no clarifying questions"* 모드면 단순 docs commit 은 보류 가능. |
| **KMS / 루카스 분리** | (본 repo 와는 무관 — Locus 본체 측 절칙. 본 repo 는 KMS-only 라 agent 가 KMS 결과 후가공할 일 없음) |

전체 절칙 원본: `/home/rickyson/.claude/projects/-home-Ricky-Dev-AICM-APIs/memory/MEMORY.md`

## 3. 핵심 코드 진입점

| 영역 | 파일 |
|---|---|
| **KMS API factory** | `src/api/main_kms.py` (`create_kms_app()`) — KMS router 만 mount. Locus 본체의 `main.py` 와 *다른 파일*. |
| Auth (JWT v2) | `src/api/auth/`, `src/api/routers/auth_v2.py` |
| Tenant v1 | `src/api/routers/tenants_v1.py` |
| Repository / Document / Block / Chunk | `src/api/routers/{repositories,documents,blocks,chunks}.py` |
| Search (하이브리드) | `src/api/routers/search.py` + `src/search/` |
| RAG (assist-stream SSE) | `src/api/routers/{rag_assist,rag}.py` |
| Repository Groups | `src/api/routers/repository_groups.py` |
| Health | `src/api/routers/health.py` |
| Pipeline workers | `src/pipeline/` |
| 공통 (config / storage_tenant / time_utils / agent_hook) | `src/common/` |
| DB models | `src/core/` |
| Alembic | `alembic/` (KMS branch — `alembic.kms.ini` 사용 가능) |
| 초기화 (default tenant) | `scripts/init_db.py` |

## 4. 격리 (KMS-only 보장)

1. **Static (build)**: `.dockerignore` 가 `src/agent_framework/`, `tests/agent_framework/` 자체 차단 → image 에 agent 코드 안 들어감.
2. **Dynamic (runtime)**: `main_kms.py` 가 KMS router 만 mount. routers/ 안에 agent 관련 파일 (`agents_v1.py` 등) 이 *물리 존재* 해도 import / mount 안 됨.
3. **검증**: import-linter 0 import, 4-layer artifact scan PASS (`Doc/scan/2026-05-19-lucas-kms-image-scan.md`).

수정 시 주의:
- `main_kms.py` 에 *agent / chat / skill / scheduler* router 를 무심코 추가하지 말 것 → KMS-only 정체성 깨짐.
- 새 router 가 `agent_framework` 의 *어떤 함수도 import 하지 않도록* 확인 (import-linter `tools/import_audit/` 에서 검증 가능).

## 5. 환경 / 실행 모드

| 모드 | 파일 | 용도 |
|---|---|---|
| **운영** | `docker-compose.yml` | self-contained — image 내장 코드 사용. 외부 환경에도 그대로 배포 가능. |
| **Staging (dev)** | `docker-compose.staging.yml` | 빠른 코드 iteration 용. `src/`, `alembic/` 등을 host volume mount + `/home/Ricky-Dev/AICM-APIs/packages/lucas-shared` *외부 마운트*. **외부 환경에서는 작동 X** — 본 호스트 전용. |

기본 인증: `LUCAS_AUTH_DISABLED=true` (무인증). 운영 시 `false` 로 전환 + JWT_SECRET 등 강한 값.

기본 tenant: `00000000-0000-0000-0000-000000000001` (alembic 082 자동 시드).

## 6. 작업 / Git workflow

| 흐름 | 명령 |
|---|---|
| Branch | `main` (default) |
| Remote 1 | `origin` = `https://github.com/RickySonYH/Locus-KMS` |
| Remote 2 | `gitlab` = `https://gitlab.timbel.dev/apps/langsa/rag-parser-engine` (branch `locus-kms-release-1.0`, default `main` 은 별도 프로젝트라 *건드리지 않음*) |
| Tags | `Locus-KMS1.0` (8f6de33), `Locus-KMS1.0.1` (885e133) |
| 일반 push | `git push origin main` (github) / `git push gitlab main:locus-kms-release-1.0` (gitlab) |
| 새 release | `git tag -a Locus-KMS<ver> -m "..."` → `git push gitlab Locus-KMS<ver>` |

**Diverged 주의**: `gitlab/main` 은 본 repo 와 다른 흐름의 *별도 프로젝트* (langsa rag-parser-engine 원본). *절대 `gitlab/main` 으로 force push X*. push 대상은 항상 `locus-kms-release-1.0`.

## 7. 진행 중 작업 / 알려진 한계

전체 핸드오프 → [`HANDOFF.md`](HANDOFF.md)
디버그·수정 가이드 → [`DEVELOPMENT.md`](DEVELOPMENT.md)

요약:
- Phase 3 packaging refactor (routers/agents_v1.py 같은 *물리 잔존* 파일 정리) — 미진행. 현재 격리 2-layer 로 충분.
- staging compose 의 AICM-APIs 절대경로 의존 — dev only, 운영 영향 X.
- alembic fresh DB enum 이중 생성 버그 — `scripts/init_db.py` (SQLAlchemy `create_all`) 우회 적용 중.
- frontend (5252) — docker 컨테이너 미존재. WSL Windows 측 dev server 가정.
- csap_table 시나리오 perf +63% — 데이터 부족 시 발생, 운영 시드로 해소.

## 8. 검증된 동작 (2026-05-19 기준)

- e2e ingest: 14초 / 4p PDF, 9 blocks (정상)
- 공정 perf 비교 (실 데이터, integrated vs Locus-KMS): API −20% / RAG −53% / c=8 tail −89%
- 분리 정확성: integrated 315 routes → Locus-KMS 192 routes (agent 0)
- 4-layer artifact scan: PASS

원본: `Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md`, `Doc/solution/2026-05-19-locus-kms-deployment-ready.md`.

## 9. 참고 메모리 (Claude 전용)

- `project_two_product_separation` — 본 절칙의 원본
- `lucas-kms-separation-handoff-20260519` — AICM-APIs 측 분리 작업 phase 진행
- `feedback-kms-lukas-separation` — KMS/agent layer 분리 철칙
- `feedback-no-hardcoding-first-principle` — 하드코딩 금지 제 1원칙
- `feedback-no-emoji` — 이모지 금지

---

> AI 어시스턴트가 본 repo 에서 작업을 시작할 때: 본 파일 → `HANDOFF.md` → `DEVELOPMENT.md` → 작업 요청에 명시된 파일 순으로 컨텍스트 로드.

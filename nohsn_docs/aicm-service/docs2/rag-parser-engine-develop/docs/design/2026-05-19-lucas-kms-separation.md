# Lucas-KMS 분리 배포 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Locus AI 의 KMS 영역을 분리해 Lucas-KMS 단독 배포 product 로 제공한다.

**Architecture:** uv workspace 기반 monorepo (`packages/lucas-shared` / `packages/lucas-kms` / `packages/lucas-agent` / `packages/full-app`). Phase 0 (Inventory) → Phase 1 (Boundary) → Phase 2 (Alembic+RLS) → Phase 3 (Packaging+Docker) → Phase 4 (E2E+V1) → Phase 5 (Release).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 + Alembic, aiokafka, BGE-M3, Qdrant, ES, PostgreSQL (RLS), Redis, MinIO, vLLM (Gemma-4-31B). uv workspace + Docker (multi-stage). frontend-v1 vanilla JS + PDF.js.

**Spec**: `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md` (rev3, GPT-5.5 GO_WITH_CHANGES + blocker 보강).

**메모리 절칙 (모든 task 적용)**:
- 이모지 X (코드/커밋/문서)
- 하드코딩 X — LLM 패턴 인식 우선
- 매 commit 전 GPT-5.5 검증 + 사용자 동의
- KMS / Lucas-agent 두 레이어 분리 — agent 가 KMS 결과 재해석 X
- 기존 백엔드 재작성 X (보강·디버그·신뢰성 강화는 필수)

---

# Phase 0 — Inventory & CI Gates (1-2일)

분리 작업 *착수 전* 현 코드베이스의 정확한 의존성 그래프 확보.
출력: `tools/import_audit/`, `tools/alembic_audit/`, `tools/docker_scan/`.

## Task 0.1: import graph 생성 (grimp)

**Files:**
- Create: `tools/import_audit/build_graph.py`
- Create: `tools/import_audit/graph.json` (출력)
- Create: `tools/import_audit/README.md`

- [ ] **Step 1: pyproject 에 grimp 의존성 추가**
  - 기존 `pyproject.toml` 의 dev 의존성에 `grimp>=3.0`
- [ ] **Step 2: build_graph.py 작성**
  ```python
  """현 src/ 의 import 의존성 그래프를 JSON 으로 출력."""
  import json
  from pathlib import Path
  import grimp

  ROOT = Path(__file__).resolve().parents[2]
  OUT = ROOT / "tools/import_audit/graph.json"

  def main() -> int:
      graph = grimp.build_graph("src", include_external_packages=False)
      modules = sorted(graph.modules)
      edges = [
          {"from": m, "to": list(graph.find_modules_directly_imported_by(m))}
          for m in modules
      ]
      OUT.write_text(json.dumps({"modules": modules, "edges": edges}, indent=2))
      print(f"graph: {len(modules)} modules, {sum(len(e['to']) for e in edges)} edges")
      return 0

  if __name__ == "__main__":
      raise SystemExit(main())
  ```
- [ ] **Step 3: 실행 — graph.json 생성**
  ```bash
  python3 tools/import_audit/build_graph.py
  test -s tools/import_audit/graph.json
  ```
- [ ] **Step 4: 검증 — lucas-kms 후보 → lucas-agent 후보 import 식별**
  ```bash
  python3 -c "
  import json
  g = json.load(open('tools/import_audit/graph.json'))
  agent_keys = ['agent_framework', 'src.api.routers.agents_v1', 'src.api.routers.chat_v1']
  for e in g['edges']:
      for ak in agent_keys:
          if any(ak in t for t in e['to']):
              if not e['from'].startswith(('src.agent_framework', 'src.api.routers.agents')):
                  print(f'CROSS: {e[\"from\"]} -> agent')
  "
  ```
- [ ] **Step 5: README 작성 + commit**
  ```bash
  git add tools/import_audit/
  git commit -m "phase0(import_audit): grimp 기반 의존성 그래프 도구 (T0.1)"
  ```

## Task 0.2: Router / Worker / DB Model Inventory

**Files:**
- Create: `tools/import_audit/inventory.py`
- Create: `tools/import_audit/inventory.json`

- [ ] **Step 1: inventory.py 작성** — `src/api/routers/*.py` 의 prefix + include 식별 + worker `Consumer` 등록 추출 + `Base.metadata.tables` 의 model 식별
- [ ] **Step 2: 실행 + inventory.json 출력**
- [ ] **Step 3: 수동 검토 — KMS / Agent / Shared 분류 확인**
- [ ] **Step 4: commit**

## Task 0.3: Alembic branch audit

**Files:**
- Create: `tools/alembic_audit/check_model_branches.py`

- [ ] **Step 1: 모든 SQLAlchemy model 의 `__tablename__` + 정의 파일 경로 매핑**
- [ ] **Step 2: spec Section 4 의 모델 분류 (KMS/Agent/Shared) 와 비교 — 누락 시 fail**
- [ ] **Step 3: 실행 — 현 모델의 branch 분류 표 출력**
- [ ] **Step 4: commit**

## Task 0.4: Frontend API Call Inventory

**Files:**
- Create: `tools/import_audit/frontend_api_audit.py`

- [ ] **Step 1: V1 (`frontend/`) + v3 (`frontend-v3/src/`) 에서 `fetch("/api/v1/...")` + axios 호출 grep**
- [ ] **Step 2: endpoint list 추출 → router inventory 와 매칭 (cover ratio 측정)**
- [ ] **Step 3: V1 의 KMS-only endpoint coverage 확인 — Phase 4 의 MVP 스코프 기반**
- [ ] **Step 4: commit**

## Task 0.5: Storage Tenant-Scope Audit

**Files:**
- Create: `tools/import_audit/storage_tenant_audit.py`

- [ ] **Step 1: Qdrant collection naming pattern 식별** — 현재 코드의 `qdrant.upsert(collection_name=...)` grep
- [ ] **Step 2: ES index naming pattern** — `es.index(index=...)` grep
- [ ] **Step 3: MinIO bucket pattern**
- [ ] **Step 4: Redis key pattern** — `redis.set/get` 의 key prefix
- [ ] **Step 5: Kafka topic + message tenant_id field 확인**
- [ ] **Step 6: 현재 누락 항목 list → Phase 2 의 T22 입력으로 사용**
- [ ] **Step 7: commit**

## Task 0.6: CI Gate 초안 (import-linter)

**Files:**
- Create: `tools/import_audit/contract.toml`
- Create: `.github/workflows/import_check.yml` (또는 기존 CI 확장)

- [ ] **Step 1: import-linter contract 작성**
  ```toml
  [importlinter]
  root_packages = ["lucas_shared", "lucas_kms", "lucas_agent"]

  [[importlinter.contracts]]
  name = "lucas-kms-zero-agent"
  type = "forbidden"
  source_modules = ["lucas_kms"]
  forbidden_modules = ["lucas_agent"]

  [[importlinter.contracts]]
  name = "lucas-agent-zero-kms"
  type = "forbidden"
  source_modules = ["lucas_agent"]
  forbidden_modules = ["lucas_kms"]

  [[importlinter.contracts]]
  name = "shared-no-product-deps"
  type = "forbidden"
  source_modules = ["lucas_shared"]
  forbidden_modules = ["lucas_kms", "lucas_agent"]
  ```
- [ ] **Step 2: CI workflow 추가** — push/PR 마다 `lint-imports` 실행
- [ ] **Step 3: pyproject 의 dev 의존성에 `import-linter>=2.0`**
- [ ] **Step 4: 현 src/ 상태에서는 패키지 미존재 — Phase 1 후 작동**
- [ ] **Step 5: commit**

## Task 0.7: Docker Scan 도구

**Files:**
- Create: `tools/docker_scan/scan.sh`

- [ ] **Step 1: 스크립트 작성**
  ```bash
  #!/bin/bash
  set -eu
  IMG="${1:-lucas-kms:latest}"
  echo "[1/4] docker history layer scan"
  docker history --no-trunc "$IMG" | grep -E "lucas_agent|lucas-agent" && exit 1
  echo "[2/4] filesystem scan"
  docker run --rm --entrypoint sh "$IMG" -c 'find / -path /proc -prune -o -type d \( -name lucas_agent -o -name lucas-agent \) -print 2>/dev/null' | grep -q . && exit 1
  echo "[3/4] pip show lucas-agent"
  docker run --rm --entrypoint sh "$IMG" -c 'pip show lucas-agent 2>&1' | grep -q "WARNING" && exit 1
  echo "[4/4] import attempt"
  docker run --rm --entrypoint sh "$IMG" -c 'python -c "import lucas_agent" 2>&1' | grep -q "ImportError"
  echo "PASS: lucas-agent 0 trace in $IMG"
  ```
- [ ] **Step 2: 실행 권한 + commit**

## Phase 0 종료 게이트

- [ ] 모든 inventory JSON 파일 생성 완료
- [ ] `tools/import_audit/contract.toml` 작성 (Phase 1 후 작동 대비)
- [ ] `tools/docker_scan/scan.sh` 작성 (Phase 3 에서 사용)
- [ ] GPT-5.5 검증 + 사용자 동의 후 Phase 1 진입

---

# Phase 1 — Boundary Hardening (2-3일)

## Task 1.1: time_context → lucas-shared/time_utils.py 이동

**Files:**
- Modify: `src/agent_framework/runtime/time_context.py` → 신규 위치
- Create: `packages/shared/src/lucas_shared/time_utils.py` (또는 임시 `src/common/time_utils.py`)
- Modify: `src/search/intent_classifier.py:21`
- Test: `tests/common/test_time_utils.py` (신규)

**참고**: Phase 2 에서 packages/shared 디렉토리 도입. 그 전까지는 `src/common/time_utils.py` 임시 위치.

- [ ] **Step 1: 실패 테스트** — `tests/common/test_time_utils.py`
  ```python
  from src.common.time_utils import now_prefix

  def test_now_prefix_kst_format():
      out = now_prefix()
      assert "[현재 시각" in out or len(out) > 0
  ```
- [ ] **Step 2: 테스트 실행 — fail 확인** (`pytest tests/common/test_time_utils.py -v`)
- [ ] **Step 3: 신규 파일 작성** — `src/common/time_utils.py` 에 `now_prefix()` 함수 이동 (기존 `src/agent_framework/runtime/time_context.py` 의 동일 함수)
- [ ] **Step 4: intent_classifier.py:21 import 변경**
  ```python
  from src.common.time_utils import now_prefix
  ```
- [ ] **Step 5: 기존 `src/agent_framework/runtime/time_context.py` 는 호환 shim 으로 변경** — `from src.common.time_utils import *`
- [ ] **Step 6: 테스트 통과 + 통합 시나리오 회귀** (`pytest tests/agent_framework -k time_context -v`)
- [ ] **Step 7: GPT-5.5 검증 + commit**

## Task 1.2: classify_worker env gate

**Files:**
- Modify: `src/pipeline/workers/classify_worker.py`
- Modify: `src/common/config.py`
- Test: `tests/pipeline/workers/test_classify_worker_gate.py`

- [ ] **Step 1: 실패 테스트** — 환경변수 `ENABLE_INTENT_CLASSIFICATION=false` 시 worker 등록 skip
- [ ] **Step 2: settings 에 `ENABLE_INTENT_CLASSIFICATION: bool = True` 추가**
- [ ] **Step 3: classify_worker.py 의 worker entry 에 `if not settings.ENABLE_INTENT_CLASSIFICATION: return` 가드 추가**
- [ ] **Step 4: 테스트 통과 + 회귀**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 1.3: documents.py _activation_shim 명시 + agent hook 인터페이스화

**Files:**
- Modify: `src/api/routers/documents.py:59-96`
- Create: `src/common/agent_hook.py` — abstract hook interface
- Test: `tests/api/routers/test_documents_activation_shim_kms_only.py`

- [ ] **Step 1: 실패 테스트** — agent framework 미설치 (KMS-only mode) 시 documents 의 apply_classification 호출이 *graceful pass*
- [ ] **Step 2: `src/common/agent_hook.py` — interface 정의**
  ```python
  from typing import Protocol
  class AgentClassificationHook(Protocol):
      async def apply_classification(self, doc_id: str, **kwargs) -> None: ...
      async def reject_classification(self, doc_id: str, **kwargs) -> None: ...

  _hook: AgentClassificationHook | None = None
  def register_hook(h: AgentClassificationHook) -> None:
      global _hook
      _hook = h
  def get_hook() -> AgentClassificationHook | None:
      return _hook
  ```
- [ ] **Step 3: documents.py 의 `_activation_shim` 을 hook lookup 으로 변경**
- [ ] **Step 4: agent framework startup 에서 `register_hook(...)` 호출**
- [ ] **Step 5: KMS-only mode 에서 hook=None → 정상 동작 검증**
- [ ] **Step 6: GPT-5.5 검증 + commit**

## Task 1.4: KMS app factory 분리

**Files:**
- Create: `src/api/main_kms.py` — KMS-only app factory
- Modify: `src/api/main.py` — Full app factory (분기)
- Test: `tests/api/test_app_factory.py`

- [ ] **Step 1: 실패 테스트** — `create_kms_app()` import 가능 + KMS-only router 만 포함
- [ ] **Step 2: `src/api/main_kms.py` 신규** — KMS router 만 mount
  ```python
  from fastapi import FastAPI
  def create_kms_app() -> FastAPI:
      app = FastAPI(title="Lucas-KMS API")
      from src.api.routers import repositories, documents, blocks, chunks, search, rag, rag_assist, categories, document_types, library_folders_v1, notes, preview, playground
      for r in [repositories, documents, blocks, chunks, search, rag, rag_assist, categories, document_types, library_folders_v1, notes, preview, playground]:
          app.include_router(r.router, prefix="/api/v1")
      return app
  ```
- [ ] **Step 3: 통합 솔루션의 `create_app()` 은 기존 동작 유지 + agent router 추가**
- [ ] **Step 4: 두 factory 모두 정상 import + smoke 테스트**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 1.5: Worker registry 분리

**Files:**
- Create: `src/pipeline/workers/registry_kms.py` — KMS workers (chunk, embed, block, dlq)
- Create: `src/pipeline/workers/registry_agent.py` — Agent workers (reminder)
- Modify: `src/pipeline/workers/main.py` — env 기반 registry 선택

- [ ] **Step 1: 실패 테스트** — `LUCAS_PRODUCT=kms` 시 KMS registry 만 로드 → agent worker 0개
- [ ] **Step 2: 두 registry 모듈 작성 — 각 worker class 의 list 정의**
- [ ] **Step 3: main.py 가 `settings.LUCAS_PRODUCT` 에 따라 분기**
- [ ] **Step 4: 회귀 — 기본 (LUCAS_PRODUCT=full) 동작 동일**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 1.6: import-linter contract 활성화 (Phase 1 후 첫 검증)

- [ ] **Step 1: 현 src/ 에서 import-linter 실행 시 contract 적용 가능한 부분 확인**
- [ ] **Step 2: 패키지 미존재이므로 contract 는 Phase 2 후 정식 작동 — 현 단계는 *dry-run* 만 검증**
- [ ] **Step 3: CI workflow 의 import-linter step 은 *Phase 2 후 activate* 주석**
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Phase 1 종료 게이트

- [ ] time_context 분리 완료 + 회귀 pass
- [ ] classify_worker env gate
- [ ] agent hook interface 도입 + KMS-only mode 동작
- [ ] KMS / Full app factory 분리
- [ ] Worker registry 분리
- [ ] 통합 솔루션 정상 동작 (regression 0)
- [ ] GPT-5.5 verdict PASS → 사용자 동의 → Phase 2

---

# Phase 2 — Alembic Multi-Branch + RLS + Multi-Store Isolation (2-3일)

## Task 2.1: Alembic multi-branch 셋업

**Files:**
- Modify: `alembic.ini` — version_locations 추가
- Create: `packages/shared/src/lucas_shared/migrations/env.py` (Phase 2 시점에는 임시 위치 `src/migrations/shared/`)
- Create: `packages/lucas-kms/src/lucas_kms/migrations/env.py`
- Create: `packages/lucas-agent/src/lucas_agent/migrations/env.py`

**참고**: Phase 2 에서는 아직 packages/ 디렉토리 도입 전 — 임시로 `src/migrations/{shared,kms,agent}/` 위치 사용. Phase 3 에서 packages/ 이동.

- [ ] **Step 1: 실패 테스트** — 3 branch (`shared`, `kms`, `agent`) 의 head 가 각각 존재
- [ ] **Step 2: 기존 migration history 의 마지막 revision 식별** (`alembic heads`)
- [ ] **Step 3: 신규 migration 생성** — 각 branch 의 첫 revision (`alembic revision -m "shared_root" --branch-label shared`)
- [ ] **Step 4: branch label + depends_on 명시**
- [ ] **Step 5: stamp transition migration 작성** — 기존 단일 history → multi-branch 변환 SQL
- [ ] **Step 6: 검증 — `alembic heads` 가 3개 출력**
- [ ] **Step 7: GPT-5.5 검증 + commit**

## Task 2.2: 모델 → branch 매핑

**Files:**
- Modify: `src/core/models/*.py` — 각 모델의 위치 (KMS/Agent/Shared) 확정
- Test: `tests/alembic/test_branch_completeness.py`

- [ ] **Step 1: 실패 테스트** — `tools/alembic_audit/check_model_branches.py` 통과 (모든 모델이 정확히 1개 branch 에 속함)
- [ ] **Step 2: 모델 파일 헤더에 `__branch__` 메타 또는 module path 기반 자동 분류**
- [ ] **Step 3: 각 branch 의 env.py 가 자기 metadata 만 import**
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Task 2.3: KMS fresh DB migration test

**Files:**
- Create: `tests-integration/lucas_kms/test_fresh_db_migration.py`
- Create: `docker-compose.test-kms.yml`

- [ ] **Step 1: 실패 테스트** — fresh postgres 에 KMS-only env.py 로 upgrade 후 `\dt` 에 agent table *0개*
- [ ] **Step 2: docker-compose.test-kms.yml — postgres only**
- [ ] **Step 3: pytest 가 컨테이너 기동 → upgrade → SELECT pg_tables → assert 검증**
- [ ] **Step 4: 회귀 — Full fresh DB upgrade 도 정상 동작**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 2.4: PostgreSQL RLS FORCE + app role

**Files:**
- Create: `src/migrations/shared/versions/shared_002_rls_force.py`
- Create: `src/common/db_session.py` — session helper 에 SET LOCAL 적용
- Test: `tests/db/test_rls_force_and_app_role.py`

- [ ] **Step 1: 실패 테스트** — app role 로 connection 시 tenant_id 미설정 상태에서 SELECT 0행
- [ ] **Step 2: migration — `lucas_kms_app` role 생성 (NOSUPERUSER NOBYPASSRLS)**
- [ ] **Step 3: migration — 모든 tenant-scoped table 에 `ALTER TABLE ... FORCE ROW LEVEL SECURITY`**
- [ ] **Step 4: session helper — `SET LOCAL app.current_tenant_id = ?` (transaction scope)**
- [ ] **Step 5: write path 테스트 (INSERT/UPDATE/DELETE) — cross-tenant 0 확인**
- [ ] **Step 6: GPT-5.5 검증 + commit**

## Task 2.5: Multi-store tenant isolation — Qdrant

**Files:**
- Modify: `src/search/qdrant_client.py` — wrapper
- Test: `tests-integration/storage/test_qdrant_tenant_isolation.py`

- [ ] **Step 1: 실패 테스트** — tenant A 의 collection 에 upsert + tenant B 검색 시 0 hit
- [ ] **Step 2: collection naming = `lucas_{tenant_id}_{repo_id}`**
- [ ] **Step 3: 검색 시 `must` filter 에 `tenant_id` 추가 (이중 안전망)**
- [ ] **Step 4: raw qdrant_client 직접 호출 금지 — wrapper 강제 import**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 2.6: Multi-store tenant isolation — ES

**Files:**
- Modify: `src/search/es_client.py` — wrapper

- [ ] **Step 1: 실패 테스트 + Step 2-5: index naming + filter + wrapper**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 2.7: Multi-store — MinIO / Redis / Kafka tenant fields

**Files:**
- Modify: `src/common/minio_client.py`, `src/common/redis_client.py`, `src/pipeline/kafka_*.py`

- [ ] **Step 1: 실패 테스트들 (3 store 각각)**
- [ ] **Step 2: MinIO bucket = `lucas-{tenant_id}`**
- [ ] **Step 3: Redis key = `lucas:{tenant_id}:*`**
- [ ] **Step 4: Kafka message body 에 `tenant_id` 필수 — consumer 가 RLS context 설정**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Phase 2 종료 게이트

- [ ] Alembic 3-branch heads 정상
- [ ] KMS fresh DB 에 agent table 0개
- [ ] RLS FORCE + app role 적용 + write path 회귀
- [ ] Qdrant/ES/MinIO/Redis/Kafka 모두 tenant_id 필수 + 격리 회귀
- [ ] 기존 Locus DB upgrade 회귀 (staging)
- [ ] GPT-5.5 verdict PASS → 사용자 동의 → Phase 3

---

# Phase 3 — Packaging + Docker (2-3일)

## Task 3.1: uv workspace 도입

**Files:**
- Modify: `pyproject.toml` — `[tool.uv.workspace]` members
- Create: `packages/shared/pyproject.toml`
- Create: `packages/lucas-kms/pyproject.toml`
- Create: `packages/lucas-agent/pyproject.toml`
- Create: `packages/full-app/pyproject.toml`

- [ ] **Step 1: uv 설치 확인**
- [ ] **Step 2: 루트 pyproject 에 workspace members**
- [ ] **Step 3: 각 패키지 pyproject — dependencies 명시 (shared 는 외부만, kms 는 shared, agent 는 shared, full 은 shared+kms+agent)**
- [ ] **Step 4: `uv sync` 정상 — lockfile 통일**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 3.2: src/ → packages/ 이동 (shared)

**Files:**
- Move: `src/common/` 의 일부 → `packages/shared/src/lucas_shared/`
  - config.py, redis.py, time_utils.py, logging.py
- Move: shared models → `packages/shared/src/lucas_shared/models/`
  - tenant, user, api_key, audit_log, integration, llm_usage, anonymization_log, dlq_message

- [ ] **Step 1: 파일 이동 + import 경로 grep/replace** (`from src.common.config` → `from lucas_shared.config`)
- [ ] **Step 2: `src/common/` 에 deprecation shim 남김** — `from lucas_shared.config import *` (Phase 4 후 제거)
- [ ] **Step 3: 회귀 — 전체 테스트 통과**
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Task 3.3: src/ → packages/lucas-kms 이동

**Files:**
- Move: `src/api/routers/{repositories,documents,blocks,chunks,search,rag,...}` → `packages/lucas-kms/src/lucas_kms/api/routers/`
- Move: `src/pipeline/` (KMS 부분) → `packages/lucas-kms/src/lucas_kms/pipeline/`
- Move: `src/search/` → `packages/lucas-kms/src/lucas_kms/search/`
- Move: KMS models → `packages/lucas-kms/src/lucas_kms/models/`

- [ ] **Step 1-4: 이동 + import 경로 update + 회귀 + commit**
- [ ] **Step 5: GPT-5.5 검증**

## Task 3.4: src/ → packages/lucas-agent 이동

**Files:**
- Move: `src/agent_framework/` → `packages/lucas-agent/src/lucas_agent/`
- Move: agent routers → `packages/lucas-agent/src/lucas_agent/api/routers/`

- [ ] **Step 1-4: 이동 + import 경로 update + 회귀 + commit**

## Task 3.5: full-app 패키지

**Files:**
- Create: `packages/full-app/src/lucas_full/main.py`

- [ ] **Step 1: create_full_app() — lucas-kms + lucas-agent 의 app 을 mount 또는 routers include**
- [ ] **Step 2: 회귀 — 통합 솔루션 정상 동작**
- [ ] **Step 3: GPT-5.5 검증 + commit**

## Task 3.6: Dockerfile.lucas-kms (build context 제한)

**Files:**
- Create: `packages/lucas-kms/Dockerfile`
- Create: `packages/lucas-kms/.dockerignore`
- Create: `docker-compose.lucas-kms.yml`

- [ ] **Step 1: shared wheel build** — `cd packages/shared && uv build`
- [ ] **Step 2: Dockerfile** (build context = `packages/lucas-kms`)
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY ../shared/dist/lucas_shared-*.whl /tmp/
  COPY pyproject.toml ./
  COPY src ./src
  RUN pip install /tmp/lucas_shared-*.whl . && rm -rf /tmp/*.whl
  ENV LUCAS_PRODUCT=kms
  CMD ["uvicorn", "lucas_kms.main:create_kms_app", "--factory", "--host", "0.0.0.0", "--port", "5101"]
  ```
- [ ] **Step 3: .dockerignore — agent, frontend-v3, tests/full 제외**
- [ ] **Step 4: build + scan** (`tools/docker_scan/scan.sh lucas-kms:latest` → PASS)
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 3.7: docker-compose.lucas-kms.yml

- [ ] **Step 1: services — postgres, qdrant, es, redis, minio, kafka, lucas-kms-api, lucas-kms-worker-large, lucas-kms-worker-small**
- [ ] **Step 2: 외부 vLLM endpoint env 노출 (`LUCAS_VLLM_ENDPOINT`)**
- [ ] **Step 3: 1-command 기동 검증** (`docker compose -f docker-compose.lucas-kms.yml up -d` → healthz OK)
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Task 3.8: vLLM 운영 정책 코드 (Phase 4 이전)

**Files:**
- Modify: `packages/shared/src/lucas_shared/llm/client.py`

- [ ] **Step 1: timeout/retry/circuit breaker/health/concurrency 적용**
  - `httpx.AsyncClient(timeout=...)` 
  - `tenacity` 또는 custom retry
  - `circuitbreaker` 또는 custom (5분 50% → 30초 open)
  - asyncio.Semaphore for concurrency
  - 백그라운드 health check task
- [ ] **Step 2: PII redact filter**
- [ ] **Step 3: audit log 통합**
- [ ] **Step 4: 테스트 — failure mode (endpoint down / TLS error / model mismatch)**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Phase 3 종료 게이트

- [ ] uv workspace 정상 — 4 패키지 모두 install 가능
- [ ] Lucas-KMS Docker image 빌드 + scan PASS (agent 0건)
- [ ] docker-compose.lucas-kms.yml 1-command 기동 OK
- [ ] vLLM 운영 정책 코드 통과
- [ ] 통합 솔루션 (Locus) 도 동일 monorepo 에서 빌드 OK
- [ ] GPT-5.5 verdict PASS → 사용자 동의 → Phase 4

---

# Phase 4 — Runtime E2E + V1 Frontend MVP (2-3일)

## Task 4.1: e2e PDF upload → ingest → search → RAG

**Files:**
- Create: `tests-integration/lucas_kms/test_e2e_pdf_pipeline.py`

- [ ] **Step 1: 테스트 PDF (sample 30p) — repo upload → status active 도달 대기 → search hit > 0 → RAG retrieve OK**
- [ ] **Step 2: assertion — citation deep-link 정확**
- [ ] **Step 3: GPT-5.5 검증 + commit**

## Task 4.2: DLQ + retry 회귀

**Files:**
- Create: `tests-integration/lucas_kms/test_dlq_retry.py`

- [ ] **Step 1: parser 실패 강제 → DLQ 적재 → 자동 retry 1회 → 성공**
- [ ] **Step 2: GPT-5.5 검증 + commit**

## Task 4.3: Multi-tenant cross-tenant 0 검증

**Files:**
- Create: `tests-integration/lucas_kms/test_multi_tenant_isolation.py`

- [ ] **Step 1: tenant A 의 doc upload → tenant B 검색 → 0 hit**
- [ ] **Step 2: write path 도 동일 (INSERT 시 tenant_id 자동 적용)**
- [ ] **Step 3: GPT-5.5 검증 + commit**

## Task 4.4: V1 frontend MVP — 텍스트 블럭 + 표 + validity

**Files:**
- Modify: `frontend/knowledge.html` + `frontend/doc-detail.js`
- Create: `frontend/components/block_editor.js`
- Create: `frontend/components/table_editor.js`

- [ ] **Step 1: 블럭 단위 텍스트 편집 (contentEditable)**
- [ ] **Step 2: 표 셀 편집**
- [ ] **Step 3: validity 토글 (active/needs_review/excluded)**
- [ ] **Step 4: playwright E2E 테스트**
- [ ] **Step 5: GPT-5.5 검증 + commit**

## Task 4.5: V1 frontend — citation PDF.js viewer

- [ ] **Step 1: PDF.js 통합** — `frontend/lib/pdfjs/`
- [ ] **Step 2: citation [N] 클릭 → page + bbox 강조**
- [ ] **Step 3: playwright E2E**
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Task 4.6: Swagger auth policy

**Files:**
- Modify: `packages/lucas-kms/src/lucas_kms/main.py`

- [ ] **Step 1: env `ENABLE_SWAGGER` + `SWAGGER_AUTH_MODE` + `SWAGGER_IP_ALLOWLIST` 도입**
- [ ] **Step 2: prod default OFF, dev default ON**
- [ ] **Step 3: 인증 없는 prod 접근 → 401**
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Phase 4 종료 게이트

- [ ] e2e PDF pipeline 전 케이스 통과
- [ ] DLQ retry 정상
- [ ] Multi-tenant cross-tenant 0
- [ ] V1 MVP UI 동작 (블럭 + 표 + validity + citation)
- [ ] Swagger 운영 보안 적용
- [ ] GPT-5.5 verdict PASS → 사용자 동의 → Phase 5

---

# Phase 5 — Release (1-2일)

## Task 5.1: vLLM failure mode tests

- [ ] **Step 1-3: endpoint down / model mismatch / TLS error 시나리오 + commit**

## Task 5.2: 최종 artifact scan

- [ ] **Step 1: tools/docker_scan/scan.sh lucas-kms:latest → PASS**
- [ ] **Step 2: SBOM 검증 (lucas-agent metadata 0건)**
- [ ] **Step 3: OpenAPI schema 에 agent endpoint 0건**
- [ ] **Step 4: GPT-5.5 검증 + commit**

## Task 5.3: Lucas-KMS 운영자 매뉴얼

**Files:**
- Create: `packages/lucas-kms/docs/admin-manual.md`

- [ ] **Step 1: 운영자 매뉴얼 작성** (KMS 관리 / multi-tenant / Swagger / vLLM endpoint / 사고 회복 / FAQ)
- [ ] **Step 2: GPT-5.5 검증 + commit**

## Task 5.4: subtree push to Lucas-KMS repo

- [ ] **Step 1: subtree 스크립트 작성** (`scripts/release/subtree_push_lucas_kms.sh`)
  ```bash
  # packages/shared + packages/lucas-kms + frontend-v1 + docs 를 Lucas-KMS repo 로 push
  git subtree push --prefix=packages/lucas-kms https://github.com/RickySonYH/Lucas-KMS.git main
  # 또는 별도 release branch
  ```
- [ ] **Step 2: subtree push 후 repo history audit** — `git log --all --name-only | grep -E "lucas_agent|frontend-v3"` → empty
- [ ] **Step 3: GPT-5.5 검증 + commit**

## Task 5.5: 통합 솔루션 (Locus) 전체 회귀

- [ ] **Step 1: 모든 기존 시나리오 (agent 위임 / SOP inject / persona) 회귀 통과**
- [ ] **Step 2: GPT-5.5 검증 + commit**

## Task 5.6: 최종 GPT-5.5 verdict + 사용자 동의

- [ ] **Step 1: GPT-5.5 full verification (spec + plan + artifact + tests 모두)**
- [ ] **Step 2: verdict PASS 도달 시 사용자 보고**
- [ ] **Step 3: 사용자 *명시 동의* → 배포 진행**

---

# 종합 종료 게이트

- [ ] Phase 0-5 모두 통과
- [ ] Section 12 (spec) 의 Success Criteria 전 항목 통과
- [ ] Lucas-KMS repo 에 자료 push 완료 + history audit 통과
- [ ] 통합 솔루션 (Locus) regression 0
- [ ] GPT-5.5 최종 PASS + 사용자 동의

---

# Notes

- 각 task 의 commit 메시지 prefix: `phase{N}.{T}({brief})` 예: `phase1.1(time_context): src/common/time_utils.py 분리`
- task 별 GPT-5.5 검증 보고서: `Doc/research/2026-05-XX-phase{N}.{T}.gpt55.txt`
- Phase 종료 시 사용자 보고 필수 — 다음 phase 진입 전 *명시 동의*
- 메모리 절칙 위반 시 즉시 stop + 사용자 보고

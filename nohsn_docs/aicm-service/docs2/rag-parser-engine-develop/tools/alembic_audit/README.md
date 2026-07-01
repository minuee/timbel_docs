# tools/alembic_audit

Phase 0 T0.3 — Alembic multi-branch (shared/kms/agent) 적용 전 모델 분류 audit.

## 스크립트

| 스크립트 | 설명 |
|---|---|
| `check_model_branches.py` | `src/core/models/` 의 `__tablename__` 추출 + branch 분류 (KMS/Agent/Shared) |
| `check_branch_consistency.py` | T2.2 — `alembic/env_kms.py` / `env_agent.py` 의 `target_metadata` 가 자기 branch + shared 만 포함하는지 검증. 다른 branch table 누설 시 비-0 종료. |

## 사용법

```bash
python3 tools/alembic_audit/check_model_branches.py
```

비-0 종료 → unknown table 발견. 분류 보강 (스크립트 상단의 `KMS_TABLES`/`AGENT_TABLES`/`SHARED_TABLES` set 갱신 또는 spec Section 4 보강).

## 출력

`tools/alembic_audit/model_branches.json` — branch 별 모델 list + 파일 경로.

## Phase 2 의 활용

T2.1 Alembic multi-branch 셋업 시 본 audit 결과를 기반으로 각 branch 의
`target_metadata` 를 구성. 누락된 모델은 *반드시 unknown 0개* 인 상태에서
진입.

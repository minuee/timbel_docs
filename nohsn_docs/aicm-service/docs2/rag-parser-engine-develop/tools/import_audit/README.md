# tools/import_audit

Phase 0 (Inventory & Gates) 용 import 그래프 / API call / storage tenant audit 도구.

## 스크립트

| 스크립트 | 설명 | 출력 |
|---|---|---|
| `build_graph.py` | grimp 기반 의존성 그래프 | `graph.json` |
| `inventory.py` | Router / Worker / Model 분류 | `inventory.json` |
| `frontend_api_audit.py` | V1/v3 frontend 의 endpoint 호출 | `frontend_api_calls.json` |
| `storage_tenant_audit.py` | Qdrant/ES/MinIO/Redis/Kafka tenant scope | `storage_tenant.json` |
| `contract.toml` | import-linter contract (Phase 2 후 활성) | — |

## 사용법

```bash
# 의존성
pip install grimp import-linter

# 실행
python3 tools/import_audit/build_graph.py
python3 tools/import_audit/inventory.py
python3 tools/import_audit/frontend_api_audit.py
python3 tools/import_audit/storage_tenant_audit.py

# import-linter (Phase 2 후)
cd packages && lint-imports --config ../tools/import_audit/contract.toml
```

## 출력 해석

- `cross_violations`: lucas-kms 후보 → lucas-agent 후보 import. 0 이 목표.
- `inventory.json` 의 `routers.shared_or_unknown`: 분류 미정 — 수동 검토 후 *_ROUTERS set 에 추가.
- `frontend_api_calls.json` 의 `only_v3`: V1 에 미존재 — Phase 4 V1 MVP 의 backport 후보 (선택).
- `storage_tenant.json`: tenant_id 미포함 naming 식별.

## 메모리 절칙

- 본 도구는 인벤토리/스캔만 수행 — production 코드 미변경
- 결과는 Phase 1+ 의 의사결정 근거로 사용

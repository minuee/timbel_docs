"""Phase 2 T2.2 — env_kms.py / env_agent.py 의 branch metadata 정합성 audit.

각 env file 이 노출하는 ``target_metadata`` 의 table set 이
``model_branches.json`` 의 자기 branch (+ shared) 정확히 일치하는지 검증.

위반 (다른 branch table 누설 또는 자기 branch 누락) 시 비-0 종료.

env 파일은 alembic context 가 없으면 top-level 에서 ``context.is_offline_mode()``
호출이 실패한다. 따라서 직접 import 대신 *python 모듈로 load 하되 alembic
context 부분 실행을 회피* 하기 위해 subprocess + 모듈 일부 추출 패턴 사용.

사용법:
    python3 tools/alembic_audit/check_branch_consistency.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_BRANCHES = ROOT / "tools/alembic_audit/model_branches.json"


def _load_expected() -> dict[str, set[str]]:
    """model_branches.json 에서 branch -> expected tables set 추출."""
    data = json.loads(MODEL_BRANCHES.read_text(encoding="utf-8"))
    by_branch = data["by_branch"]
    return {
        branch: {row["table"] for row in by_branch[branch]}
        for branch in ("kms", "agent", "shared")
    }


def _extract_target_metadata_tables(env_file: str) -> set[str]:
    """env_*.py 의 target_metadata 가 가진 table 명 set 추출 (subprocess).

    env 파일 top-level 에 ``context.run_migrations()`` 호출이 있으므로 그대로
    import 하면 실패. 따라서 env 파일을 *읽어서 ``target_metadata`` 정의 라인
    까지만* 실행하는 stub 을 만든다 — env 파일의 ``if context.is_offline_mode()``
    분기 직전까지 코드를 추출.

    더 단순한 접근: env 파일을 그대로 import 하되 ``alembic.context`` 를
    *mock* 으로 monkeypatch — ``is_offline_mode()`` 가 True 반환 + offline
    실행은 SQL 만 생성 (DB 접속 X) 이지만 ``literal_binds`` 가 driver 필요.
    그래서 본 audit 는 *target_metadata 정의 시점에서 import 를 중단* 한다.
    """
    runner = f"""
import sys
sys.path.insert(0, '{ROOT}')
import importlib.util

# alembic.context.is_offline_mode 를 monkeypatch — env 파일이 import 만 되도록.
import alembic.context as _ctx
_ctx.is_offline_mode = lambda: True

# offline 분기에서 ``context.configure(url=...)`` 도 호출되므로 stub.
_ctx.configure = lambda **kw: None
_ctx.run_migrations = lambda: None
class _Tx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
_ctx.begin_transaction = lambda: _Tx()

# alembic 의 Config 도 — env 파일은 ``context.config`` 를 참조.
class _CfgStub:
    config_file_name = None
    config_ini_section = 'alembic'
    def get_main_option(self, k, default=None): return ''
    def set_main_option(self, k, v): pass
    def get_section(self, *a, **kw): return {{}}
_ctx.config = _CfgStub()

# 이제 env 파일 import.
spec = importlib.util.spec_from_file_location('_envmod', '{ROOT}/alembic/{env_file}')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

import json
tm = mod.target_metadata
print(json.dumps(sorted(tm.tables.keys())))
"""
    res = subprocess.run(
        [sys.executable, "-c", runner],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
    )
    if res.returncode != 0:
        print(f"FAIL: subprocess failed for {env_file}", file=sys.stderr)
        print("STDOUT:", res.stdout, file=sys.stderr)
        print("STDERR:", res.stderr, file=sys.stderr)
        sys.exit(2)
    # 마지막 줄이 JSON
    last_json_line = res.stdout.strip().splitlines()[-1]
    return set(json.loads(last_json_line))


def main() -> int:
    expected = _load_expected()
    shared_tables = expected["shared"]

    # KMS env: shared + kms + document_categories assoc — agent table 누락
    kms_tables = _extract_target_metadata_tables("env_kms.py")
    kms_expected = shared_tables | expected["kms"] | {"document_categories"}
    kms_forbidden = expected["agent"]

    kms_missing = kms_expected - kms_tables
    kms_extra = kms_tables - kms_expected
    kms_leaked = kms_forbidden & kms_tables

    # Agent env: shared + agent — kms table 누락
    agent_tables = _extract_target_metadata_tables("env_agent.py")
    agent_expected = shared_tables | expected["agent"]
    agent_forbidden = expected["kms"] | {"document_categories"}

    agent_missing = agent_expected - agent_tables
    agent_extra = agent_tables - agent_expected
    agent_leaked = agent_forbidden & agent_tables

    print(f"=== KMS env_kms.py ===")
    print(f"  registered tables: {len(kms_tables)}")
    print(f"  expected (shared + kms + assoc): {len(kms_expected)}")
    print(f"  missing: {sorted(kms_missing)}")
    print(f"  unexpected (extra): {sorted(kms_extra)}")
    print(f"  leaked agent tables: {sorted(kms_leaked)}")
    print()
    print(f"=== AGENT env_agent.py ===")
    print(f"  registered tables: {len(agent_tables)}")
    print(f"  expected (shared + agent): {len(agent_expected)}")
    print(f"  missing: {sorted(agent_missing)}")
    print(f"  unexpected (extra): {sorted(agent_extra)}")
    print(f"  leaked kms tables: {sorted(agent_leaked)}")

    failed = bool(
        kms_missing or kms_leaked or kms_extra
        or agent_missing or agent_leaked or agent_extra
    )
    if failed:
        print()
        print("FAIL: branch metadata 정합성 위반 — env_*.py 보강 필요.")
        return 1
    print()
    print("PASS: env_kms.py / env_agent.py 모두 자기 branch + shared 만 등록.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

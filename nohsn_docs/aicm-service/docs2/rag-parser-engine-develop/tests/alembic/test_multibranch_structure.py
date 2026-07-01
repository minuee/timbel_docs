"""Phase 2 T2.1 / T2.2 — Alembic multi-branch 구조 단위 테스트 (DB 불필요).

검증:
- alembic.ini 에 3 head (shared_root, kms_root, agent_root) 존재.
- kms_root / agent_root 가 ``depends_on=("shared",)`` 보유.
- alembic.kms.ini 가 2 head (shared, kms) 만 인식 — agent head 없음.
- alembic.agent.ini 가 2 head (shared, agent) 만 인식 — kms head 없음.
- env_kms.target_metadata 에 agent table 없음 (T2.2 branch metadata isolation).
- env_agent.target_metadata 에 kms table 없음 (T2.2 branch metadata isolation).

CI 회귀 게이트.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Alembic structure
# ---------------------------------------------------------------------------


def _get_script_directory(ini_path: str):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(ini_path)
    return ScriptDirectory.from_config(cfg)


@pytest.fixture(scope="module")
def full_script():
    return _get_script_directory(str(ROOT / "alembic.ini"))


@pytest.fixture(scope="module")
def kms_script():
    return _get_script_directory(str(ROOT / "alembic.kms.ini"))


@pytest.fixture(scope="module")
def agent_script():
    return _get_script_directory(str(ROOT / "alembic.agent.ini"))


def test_full_alembic_has_three_branch_heads(full_script):
    """alembic.ini → 3 head (shared_root, kms_root, agent_root)."""
    heads = set(full_script.get_heads())
    assert heads == {"shared_root", "kms_root", "agent_root"}, (
        f"expected 3 branch heads, got {heads}"
    )


def test_branch_root_revisions_have_correct_labels(full_script):
    """각 branch root revision 의 branch_labels 검증."""
    expected = {
        "shared_root": "shared",
        "kms_root": "kms",
        "agent_root": "agent",
    }
    for rev_id, branch_name in expected.items():
        rev = full_script.get_revision(rev_id)
        assert branch_name in (rev.branch_labels or set()), (
            f"{rev_id} missing branch_label {branch_name!r}, "
            f"got {rev.branch_labels}"
        )


def test_kms_and_agent_depend_on_shared(full_script):
    """kms_root / agent_root 가 shared 에 의존."""
    for rev_id in ("kms_root", "agent_root"):
        rev = full_script.get_revision(rev_id)
        deps = rev.dependencies or []
        if isinstance(deps, str):
            deps = [deps]
        assert "shared" in deps, (
            f"{rev_id} missing depends_on='shared', got {deps}"
        )


def test_branch_roots_revise_legacy_head_081(full_script):
    """3 branch root 모두 ``down_revision='081'`` (기존 linear head)."""
    for rev_id in ("shared_root", "kms_root", "agent_root"):
        rev = full_script.get_revision(rev_id)
        assert rev.down_revision == "081", (
            f"{rev_id} down_revision should be '081', got {rev.down_revision}"
        )


def test_kms_ini_excludes_agent_head(kms_script):
    """alembic.kms.ini → shared_root, kms_root 만 — agent_root 미포함."""
    heads = set(kms_script.get_heads())
    assert heads == {"shared_root", "kms_root"}, (
        f"kms.ini should see only shared+kms heads, got {heads}"
    )


def test_agent_ini_excludes_kms_head(agent_script):
    """alembic.agent.ini → shared_root, agent_root 만 — kms_root 미포함."""
    heads = set(agent_script.get_heads())
    assert heads == {"shared_root", "agent_root"}, (
        f"agent.ini should see only shared+agent heads, got {heads}"
    )


def test_legacy_history_intact(full_script):
    """기존 단일 history (001_* → ... → 081) 보존 확인 (3-digit prefix)."""
    revs = list(full_script.walk_revisions())
    rev_ids = {r.revision for r in revs}
    # 1-77 의 일부는 ``001_initial``, ``002_users_rbac`` 같은 prefix 형식.
    # 78+ 는 ``077``, ``080`` 같은 plain digit.
    # 두 형식 모두 인식.
    def _has_legacy_prefix(prefix: str) -> bool:
        return any(r == prefix or r.startswith(f"{prefix}_") for r in rev_ids)

    for legacy in ("001", "030", "077", "080", "081"):
        assert _has_legacy_prefix(legacy), f"legacy revision {legacy}* 누락"

    # plus the 3 new branch roots
    for new in ("shared_root", "kms_root", "agent_root"):
        assert new in rev_ids


# ---------------------------------------------------------------------------
# env_kms / env_agent target_metadata isolation
# ---------------------------------------------------------------------------


def _extract_target_metadata_tables(env_file: str) -> set[str]:
    """env_*.py 의 target_metadata 를 subprocess 로 추출."""
    runner = f"""
import sys
sys.path.insert(0, '{ROOT}')
import importlib.util
import alembic.context as _ctx
_ctx.is_offline_mode = lambda: True
_ctx.configure = lambda **kw: None
_ctx.run_migrations = lambda: None
class _Tx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
_ctx.begin_transaction = lambda: _Tx()
class _CfgStub:
    config_file_name = None
    config_ini_section = 'alembic'
    def get_main_option(self, k, default=None): return ''
    def set_main_option(self, k, v): pass
    def get_section(self, *a, **kw): return {{}}
_ctx.config = _CfgStub()
spec = importlib.util.spec_from_file_location('_envmod', '{ROOT}/alembic/{env_file}')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
import json
print(json.dumps(sorted(mod.target_metadata.tables.keys())))
"""
    res = subprocess.run(
        [sys.executable, "-c", runner],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    assert res.returncode == 0, (
        f"subprocess failed: stdout={res.stdout!r} stderr={res.stderr!r}"
    )
    return set(json.loads(res.stdout.strip().splitlines()[-1]))


_BRANCH_DATA = json.loads(
    (ROOT / "tools/alembic_audit/model_branches.json").read_text(encoding="utf-8")
)
_KMS_TABLES = {row["table"] for row in _BRANCH_DATA["by_branch"]["kms"]} | {"document_categories"}
_AGENT_TABLES = {row["table"] for row in _BRANCH_DATA["by_branch"]["agent"]}
_SHARED_TABLES = {row["table"] for row in _BRANCH_DATA["by_branch"]["shared"]}


def test_env_kms_target_metadata_excludes_agent_tables():
    """env_kms.target_metadata 에 agent table 0개."""
    tables = _extract_target_metadata_tables("env_kms.py")
    leaked = _AGENT_TABLES & tables
    assert not leaked, f"env_kms.py leaked agent tables: {sorted(leaked)}"


def test_env_kms_target_metadata_has_kms_and_shared():
    """env_kms.target_metadata = shared (12) + kms (10) + document_categories assoc."""
    tables = _extract_target_metadata_tables("env_kms.py")
    expected = _KMS_TABLES | _SHARED_TABLES
    missing = expected - tables
    extra = tables - expected
    assert not missing, f"env_kms missing: {sorted(missing)}"
    assert not extra, f"env_kms unexpected extras: {sorted(extra)}"


def test_env_agent_target_metadata_excludes_kms_tables():
    """env_agent.target_metadata 에 kms table 0개."""
    tables = _extract_target_metadata_tables("env_agent.py")
    leaked = (_KMS_TABLES | {"document_categories"}) & tables
    assert not leaked, f"env_agent.py leaked kms tables: {sorted(leaked)}"


def test_env_agent_target_metadata_has_agent_and_shared():
    """env_agent.target_metadata = shared (12) + agent (8) = 20."""
    tables = _extract_target_metadata_tables("env_agent.py")
    expected = _AGENT_TABLES | _SHARED_TABLES
    missing = expected - tables
    extra = tables - expected
    assert not missing, f"env_agent missing: {sorted(missing)}"
    assert not extra, f"env_agent unexpected extras: {sorted(extra)}"

"""회귀 — fresh 배포 시 테넌트 에러 방지 (2026-05-21).

배경 (DEBUG REPORT 2026-05-21):
- docker-compose 의 migrate 서비스는 alembic 이 아니라 ``scripts/init_db.py`` 를
  호출한다. 따라서 fresh 배포의 schema 생성 + default tenant 시드는 전적으로
  init_db.py + ``Base.metadata.create_all`` 에 의존한다.
- 과거 두 결함:
  1. init_db.py 가 tenant ``...0000`` 을 시드했으나 무인증 모드(``LUCAS_AUTH_DISABLED
     =true``)는 ``LUCAS_DEFAULT_TENANT_ID`` (``...0001``) 를 기대 → 모든 write 가
     FK 위반(테넌트 에러). alembic ``082_seed_default_lucas_tenant`` 만이 ``...0001``
     을 시드하는데 migrate 가 alembic 을 안 탐.
  2. ``models/__init__`` 이 ``AgentDocument`` (FK ``agent_id → agents.id``) 는 import
     하나 ``Agent`` (agents 테이블) 는 import 안 함 → ``create_all`` 이 dangling FK
     (NoReferencedTableError) 로 실패 → seed 단계 도달조차 못 함.

본 테스트는 두 결함의 회귀를 막는다. DB 불필요 — import + metadata 정적 검사만.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_082 = (
    REPO_ROOT / "alembic" / "versions" / "shared" / "082_seed_default_lucas_tenant.py"
)
MIGRATION_081 = (
    REPO_ROOT / "alembic" / "versions" / "081_rls_force_lucas_kms_app.py"
)


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"모듈 로드 실패: {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration_082():
    """082 마이그레이션 모듈을 파일 경로로 로드 (파일명이 숫자 시작이라 직접 import 불가)."""
    spec = importlib.util.spec_from_file_location("_seed_082", MIGRATION_082)
    assert spec and spec.loader, f"082 마이그레이션 로드 실패: {MIGRATION_082}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_tenant_id_synced_with_migration() -> None:
    """결함 1 회귀: config 의 default tenant 와 082 시드 tenant ID 가 일치해야 한다.

    불일치 시 — init_db / 082 / 무인증 모드 fallback 이 서로 다른 tenant 를 가리켜
    fresh 배포에서 FK 위반(테넌트 에러)이 재발한다.
    """
    from src.common.config import settings

    migration = _load_migration_082()

    assert settings.LUCAS_DEFAULT_TENANT_ID == migration.DEFAULT_TENANT_ID, (
        "config.LUCAS_DEFAULT_TENANT_ID 와 082 마이그레이션의 DEFAULT_TENANT_ID 가 "
        f"불일치: config={settings.LUCAS_DEFAULT_TENANT_ID!r} "
        f"vs 082={migration.DEFAULT_TENANT_ID!r}. "
        "둘 중 하나만 바꾸면 fresh 배포에서 테넌트 에러가 재발한다."
    )


def test_model_metadata_has_no_dangling_foreign_keys() -> None:
    """결함 2 회귀: init_db 가 생성하는 metadata 에 dangling FK 가 없어야 한다.

    ``create_all`` 이 참조하는 모든 FK 대상 테이블이 metadata 에 등록되어 있어야
    fresh DB 생성이 NoReferencedTableError 없이 성공한다. 본 import 세트는
    ``scripts/init_db.py`` 의 import 세트를 그대로 반영한다 (변경 시 동기 유지).
    """
    # init_db.py 와 동일한 import 세트 — create_all 이 보는 metadata 를 재현.
    import src.core.models  # noqa: F401
    from src.core.models.user import User, UserRepositoryAccess  # noqa: F401
    from src.core.models.tenant import Tenant  # noqa: F401
    from src.core.models.tenant_link import TenantLink  # noqa: F401
    from src.core.models.audit_log import AuditLog  # noqa: F401
    from src.core.models.lifecycle_feedback import LifecycleFeedback  # noqa: F401
    from src.core.models.scheduled_action import ScheduledAction  # noqa: F401
    from src.core.models.transition import TransitionEvent, LifecyclePolicy  # noqa: F401
    from src.core.models.api_key import APIKey  # noqa: F401

    from src.core.models.base import Base

    registered = set(Base.metadata.tables.keys())
    dangling: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        for fk in table.foreign_keys:
            # "agents.id" → "agents". target_fullname 은 resolution 을 강제하지 않음.
            target_table = fk.target_fullname.rsplit(".", 1)[0]
            # schema-qualified ("schema.table.col") 안전 처리.
            target_table = target_table.split(".")[-1]
            if target_table not in registered:
                dangling.setdefault(table_name, []).append(fk.target_fullname)

    assert not dangling, (
        "create_all 이 실패할 dangling FK (대상 테이블 미등록): "
        f"{dangling}. 해당 대상 모델을 src/core/models/__init__ 에 import 해야 한다."
    )


def test_rls_owner_tables_have_owner_agent_id_column() -> None:
    """결함 3 회귀: init_db 의 RLS 정책이 참조하는 owner_agent_id 가 모델에 존재해야 한다.

    ``_apply_rls_policies`` 는 documents / library_folders / audit_logs 에 대해
    owner_agent_id 기반 정책을 만든다. 모델이 마이그레이션(072 등)과 drift 되어
    해당 컬럼이 누락되면 ``create_all`` 스키마에 컬럼이 없어 RLS 적용이
    'column owner_agent_id does not exist' 로 크래시 → fresh 배포 실패.
    """
    import src.core.models  # noqa: F401
    from src.core.models.document import Document
    from src.core.models.library_folder import LibraryFolder
    from src.core.models.audit_log import AuditLog

    missing = [
        model.__tablename__
        for model in (Document, LibraryFolder, AuditLog)
        if "owner_agent_id" not in model.__table__.columns
    ]
    assert not missing, (
        "RLS 정책이 참조하는 owner_agent_id 컬럼이 다음 모델에 누락: "
        f"{missing}. 해당 모델에 컬럼 추가(마이그레이션과 동기) 필요."
    )

    # documents.owner_agent_id 속성이 마이그레이션 072 와 일치해야 함
    # (UUID / nullable / FK→agents.id / ondelete SET NULL).
    col = Document.__table__.columns["owner_agent_id"]
    assert col.nullable is True, "owner_agent_id 는 nullable 이어야 함 (072)"
    assert "UUID" in type(col.type).__name__.upper(), (
        f"owner_agent_id 타입이 UUID 가 아님: {col.type!r}"
    )
    fks = list(col.foreign_keys)
    assert len(fks) == 1, "owner_agent_id 는 FK 1개(agents.id) 여야 함"
    assert fks[0].column.table.name == "agents", (
        f"owner_agent_id FK 대상이 agents 가 아님: {fks[0].target_fullname}"
    )
    assert fks[0].ondelete == "SET NULL", (
        f"owner_agent_id FK ondelete 가 SET NULL 이 아님: {fks[0].ondelete!r}"
    )


def test_rls_table_classification_matches_schema() -> None:
    """결함 4 회귀: RLS 의 DIRECT/JOIN 분류가 실제 컬럼 스키마와 일치해야 한다.

    alembic 081 의 분류가 권위 — DIRECT_TENANT_TABLES 는 tenant_id 직접 보유,
    JOIN_TENANT_TABLES 는 직접 컬럼 없이 FK(JOIN_FK_COLUMNS)로 부모 격리.
    chunks 처럼 tenant_id 없는 table 을 DIRECT 로 분류하면 RLS 적용이 fresh DB
    에서 'column tenant_id does not exist' 로 크래시. init_db._apply_rls_policies
    의 로컬 분류도 081 과 동일해야 함 (두 곳 동기).
    """
    import src.core.models  # noqa: F401
    from src.core.models.base import Base

    rls = _load_module(MIGRATION_081, "_rls_081")
    tables = Base.metadata.tables

    # DIRECT 는 metadata 에 존재 + tenant_id 직접 보유해야 함 (완화 없음).
    direct_bad = [
        t for t in rls.DIRECT_TENANT_TABLES
        if t not in tables or "tenant_id" not in tables[t].columns
    ]
    assert not direct_bad, (
        "DIRECT_TENANT_TABLES 인데 metadata 부재거나 tenant_id 컬럼 부재 "
        f"(RLS 크래시 유발): {direct_bad}. JOIN_TENANT_TABLES 로 재분류 필요."
    )

    # JOIN 은 metadata 에 존재 + FK 컬럼 보유 + 그 FK 가 parent.id 를 가리켜야 함.
    join_bad: list[str] = []
    for t, fk in rls.JOIN_FK_COLUMNS.items():
        if t not in tables or fk not in tables[t].columns:
            join_bad.append(f"{t}.{fk} (컬럼 부재)")
            continue
        parent = rls.JOIN_TENANT_TABLES.get(t)
        targets = {
            f.column.table.name for f in tables[t].columns[fk].foreign_keys
        }
        if parent not in targets:
            join_bad.append(f"{t}.{fk} FK 대상 {targets} != parent {parent}")
    assert not join_bad, f"JOIN_TENANT_TABLES FK 검증 실패: {join_bad}."

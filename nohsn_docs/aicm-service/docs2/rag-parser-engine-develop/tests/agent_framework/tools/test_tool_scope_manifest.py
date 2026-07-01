"""Phase 2 (#153) + D26 (#201, 2026-05-08) — 도구 manifest default_scope 정합 가드.

spec: docs/superpowers/specs/2026-05-08-d26-default-scope-manifest.md

D26 단일 소스화 후 검증 contract:

1. dependencies.py 의 `_REGISTERED_TOOL_NAMES` 가 ToolRegistry 의 tools dict
   key 와 정확히 동일 (drift 검출).
2. `_REGISTERED_TOOL_NAMES` 가 `scope_resolver._TOOL_DEFAULT_SCOPES` 의 sub-set
   (resolver 에 default 가 없으면 실패).
3. 모든 scope 값이 'tenant'|'user'|'agent'|'session' 4 가지.
4. critical classifications (schedule.* / mail.* / kms_rag.search 등) 회귀 가드.

source-of-truth 통합 후, validator + engine + catalog 모두 *동일한* scope 값을
반환하므로, drift 가 발생할 수 있는 위치는 deps.py 의 `_REGISTERED_TOOL_NAMES`
유지뿐. 본 test 가 그 정합성을 보장.
"""

import ast
from pathlib import Path

from src.agent_framework.api.dependencies import (
    _REGISTERED_TOOL_NAMES,
    _default_scopes_for_registered_tools,
)
from src.agent_framework.tools.scope_resolver import TOOL_DEFAULT_SCOPES as _TOOL_DEFAULT_SCOPES

VALID_SCOPES = {"tenant", "user", "agent", "session"}


def _extract_tool_names_from_source() -> set[str]:
    """dependencies.py 의 ToolRegistry(...) 첫 positional arg dict 의 key 추출.

    runtime import 없이 source-level AST 만으로 — _build_engine() 외부 연결 회피.
    """
    deps_path = (
        Path(__file__).resolve().parents[3]
        / "src/agent_framework/api/dependencies.py"
    )
    src = deps_path.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name != "ToolRegistry":
            continue
        tools_dict = None
        if node.args:
            tools_dict = node.args[0]
        for kw in node.keywords:
            if kw.arg == "tools":
                tools_dict = kw.value
        if not isinstance(tools_dict, ast.Dict):
            continue
        out: set[str] = set()
        for k in tools_dict.keys:
            assert isinstance(k, ast.Constant) and isinstance(k.value, str), (
                f"non-string key in tools dict: {ast.dump(k)}"
            )
            out.add(k.value)
        return out
    raise AssertionError("ToolRegistry(...) call with tools dict not found in dependencies.py")


def test_registered_tool_names_matches_actual_tools_dict():
    """`_REGISTERED_TOOL_NAMES` 와 ToolRegistry 의 tools dict key 가 정확히 동일.

    deps.py 에 새 도구 추가 시 `_REGISTERED_TOOL_NAMES` 도 갱신해야 함을 가드.
    """
    actual = _extract_tool_names_from_source()
    missing = actual - _REGISTERED_TOOL_NAMES
    extra = _REGISTERED_TOOL_NAMES - actual
    assert not missing, (
        f"tools dict 에 등록됐지만 _REGISTERED_TOOL_NAMES 에 없음: {sorted(missing)}"
    )
    assert not extra, (
        f"_REGISTERED_TOOL_NAMES 에 있지만 tools dict 에 등록 안 됨: {sorted(extra)}"
    )


def test_registered_tools_are_subset_of_resolver_defaults():
    """등록된 모든 도구는 resolver._TOOL_DEFAULT_SCOPES 에 명시 등록.

    fallback 'agent' 에 의존 X — 의도 drift 가드.
    """
    missing = _REGISTERED_TOOL_NAMES - set(_TOOL_DEFAULT_SCOPES)
    assert not missing, (
        f"등록 도구인데 scope_resolver._TOOL_DEFAULT_SCOPES 에 없음 (drift): "
        f"{sorted(missing)}\n"
        "D26 spec 에 따라 모든 등록 도구는 resolver 에 명시 default scope 보유."
    )


def test_all_default_scopes_are_valid_4_levels():
    """resolver._TOOL_DEFAULT_SCOPES 의 모든 값이 4 단계 중 하나."""
    invalid = {n: s for n, s in _TOOL_DEFAULT_SCOPES.items() if s not in VALID_SCOPES}
    assert not invalid, (
        f"invalid scope 값: {invalid}\n허용: {sorted(VALID_SCOPES)}"
    )


def test_default_scopes_helper_returns_resolver_subset():
    """`_default_scopes_for_registered_tools()` 반환 dict = resolver sub-set."""
    helper = _default_scopes_for_registered_tools()
    # 모든 등록 도구 포함.
    assert set(helper) == _REGISTERED_TOOL_NAMES
    # 각 값이 resolver 와 일치.
    for name, scope in helper.items():
        assert scope == _TOOL_DEFAULT_SCOPES[name], (
            f"{name}: helper={scope!r} != resolver={_TOOL_DEFAULT_SCOPES[name]!r}"
        )


def test_known_critical_classifications():
    """schedule.* / mail.* / GPT-5 권고 반영 케이스 회귀 가드.

    D26 (2026-05-08) 권고 반영: diary.* / expense.* default = 'agent' 유지
    (SUPPORTS=true → user 전환 시 NULL 버킷 위험).
    """
    s = _default_scopes_for_registered_tools()

    # Phase 1 — schedule.* 는 모두 agent.
    for n in [
        "schedule.create", "schedule.list", "schedule.delete",
        "schedule.delete_duplicates", "schedule.delete_all", "schedule.update",
        "schedule.availability", "schedule.suggest_slots",
    ]:
        assert s[n] == "agent", f"{n} 은 agent scope 여야 함 (Phase 1 ✓)"

    # mail.* + inbox.summary 는 모두 user (사용자 메일함 자산).
    # mail.compose D26: agent → user.
    for n in ["mail.send", "mail.search", "mail.compose", "inbox.summary"]:
        assert s[n] == "user", f"{n} 은 user scope 여야 함"

    # D26 — diary.* / expense.* default 'agent' 유지 (GPT-5 phase0 권고).
    for n in ["diary.save", "diary.search"]:
        assert s[n] == "agent", f"{n} 은 D26 권고 — agent 유지"
    for n in [
        "expense.create", "expense.list", "expense.update", "expense.delete",
        "expense.sum_by_category",
    ]:
        assert s[n] == "agent", f"{n} 은 D26 권고 — agent 유지"

    # kms_meta.get_my_inventory — D26: tenant → user ("my" 의미).
    assert s["kms_meta.get_my_inventory"] == "user"

    # KMS read-only 검색 — tenant.
    assert s["kms_rag.search"] == "tenant"
    assert s["kms_sop.search"] == "tenant"

    # 외부 read-only — tenant.
    for n in ["weather.lookup", "news.search", "web.search", "web.fetch"]:
        assert s[n] == "tenant", f"{n} 은 외부 자료 = tenant"

    # stock 시세 (read-only 시장 데이터) — tenant.
    for n in ["stock.quote", "stock.market_movers", "stock.analyze", "stock.predict"]:
        assert s[n] == "tenant", f"{n} 은 시장 데이터 = tenant"

    # stock watchlist — user.
    for n in ["stock.add_watch", "stock.list_watch", "stock.update_watch", "stock.delete_watch"]:
        assert s[n] == "user", f"{n} 은 개인 투자 자산 = user"


def test_no_orphan_resolver_entries_for_registered_tools():
    """resolver 에 등록 도구와 무관한 ghost entry 없음 (D26 정리 후).

    D26 에서 calendar.cancel/create/list, concert.list, inventory.update,
    kms_inventory.summary, kms_meta.list, movie.detail/list 를 resolver 에서
    삭제. 이전에 deps.py 미등록이었던 도구들이 resolver 에만 있는 잔존 검출.
    """
    ghost_candidates = {
        "calendar.cancel",
        "calendar.create",
        "calendar.list",
        "concert.list",
        "inventory.update",
        "kms_inventory.summary",
        "kms_meta.list",
        "movie.detail",
        "movie.list",
    }
    resolver_keys = set(_TOOL_DEFAULT_SCOPES)
    leftover = ghost_candidates & resolver_keys
    assert not leftover, (
        f"D26 에서 삭제했어야 할 ghost resolver entries 잔존: {sorted(leftover)}"
    )

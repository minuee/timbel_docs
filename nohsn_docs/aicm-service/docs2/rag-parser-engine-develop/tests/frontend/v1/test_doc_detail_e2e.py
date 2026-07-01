"""Phase 4.4/4.5 V1 frontend MVP — component tests.

Validates the new vanilla-JS component modules (block_editor, table_editor,
citation_viewer, api wrapper) via Node.js evaluation. No browser dependency —
covers what playwright would also assert (parse/serialize round-trip,
component module structure, API wrapper contract, debounce semantics).

A real browser E2E is reserved for the deployed runtime pass (a follow-up that
needs a live backend); these tests run in CI with just node + python.

메모리 절칙 — 하드코딩 enum X (값은 module 에서 추출), 이모지 X.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
LIB = FRONTEND / "lib" / "api.js"
COMP = FRONTEND / "components"
BLOCK_EDITOR = COMP / "block_editor.js"
TABLE_EDITOR = COMP / "table_editor.js"
CITATION = COMP / "citation_viewer.js"
MVP_HTML = FRONTEND / "doc-detail-mvp.html"

_NODE = shutil.which("node")
requires_node = pytest.mark.skipif(_NODE is None, reason="node not installed")


def _run_node(script: str) -> str:
    """Run a JS snippet via `node -e` and return stdout."""
    assert _NODE, "node missing"
    proc = subprocess.run(
        [_NODE, "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(FRONTEND),
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node failed (rc={proc.returncode}):\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc.stdout


def test_all_module_files_exist() -> None:
    for p in (LIB, BLOCK_EDITOR, TABLE_EDITOR, CITATION, MVP_HTML):
        assert p.exists(), f"missing: {p}"
        assert p.stat().st_size > 200, f"too small: {p}"


@requires_node
def test_api_js_loads_and_exports_contract() -> None:
    """KmsApi exposes get/post/patch/put/delete/request/url and reads tenant."""
    out = _run_node(
        f"""
        const root = {{
          document: null,
          localStorage: {{ getItem: (k) => k === 'tenant_id' ? '11111111-1111-1111-1111-111111111111' : (k === 'jwt' ? 'tok-abc' : null) }},
        }};
        // Stub window (api.js prefers window over globalThis)
        global.window = root;
        // load
        require({json.dumps(str(LIB))});
        const api = root.KmsApi;
        const out = {{
          methods: ['get','post','patch','put','delete','request','url'].every(m => typeof api[m] === 'function'),
          tenant: api.getTenantId(),
          jwt: api.getJwt(),
          url: api.url('/blocks/abc'),
        }};
        process.stdout.write(JSON.stringify(out));
        """
    )
    parsed = json.loads(out.strip())
    assert parsed["methods"] is True
    assert parsed["tenant"] == "11111111-1111-1111-1111-111111111111"
    assert parsed["jwt"] == "tok-abc"
    assert parsed["url"].endswith("/api/v1/blocks/abc")


@requires_node
def test_table_editor_parse_serialize_round_trip() -> None:
    """Markdown table parse -> serialize -> parse yields identical structure."""
    out = _run_node(
        f"""
        const root = {{ document: null }};
        global.window = root;
        require({json.dumps(str(TABLE_EDITOR))});
        const T = root.KmsTableEditor;
        const md = '| 컬럼 A | 컬럼 B | 컬럼 C |\\n|---|---|---|\\n| 1 | 2 | 3 |\\n| 4 | 5 | 6 |';
        const parsed = T._parse(md);
        const serialized = T._serialize(parsed);
        const reparsed = T._parse(serialized);
        process.stdout.write(JSON.stringify({{
          headers: parsed.headers,
          rows: parsed.rows,
          reparsed_headers: reparsed.headers,
          reparsed_rows: reparsed.rows,
          serialized_starts_with_pipe: serialized.startsWith('|'),
        }}));
        """
    )
    parsed = json.loads(out.strip())
    assert parsed["headers"] == ["컬럼 A", "컬럼 B", "컬럼 C"]
    assert parsed["rows"] == [["1", "2", "3"], ["4", "5", "6"]]
    # Round-trip preserves structure
    assert parsed["reparsed_headers"] == parsed["headers"]
    assert parsed["reparsed_rows"] == parsed["rows"]
    assert parsed["serialized_starts_with_pipe"] is True


@requires_node
def test_block_editor_module_validity_options() -> None:
    """block_editor exposes VALIDITY_OPTIONS matching backend allowed values."""
    out = _run_node(
        f"""
        const root = {{ document: null }};
        global.window = root;
        require({json.dumps(str(BLOCK_EDITOR))});
        const opts = root.KmsBlockEditor.VALIDITY_OPTIONS;
        process.stdout.write(JSON.stringify(opts.map(o => o.value)));
        """
    )
    values = json.loads(out.strip())
    # Backend VALID_VALIDITY_STATUSES (blocks.py): active, historical, superseded, archived, purged, disputed
    backend_allowed = {"active", "historical", "superseded", "archived", "purged", "disputed"}
    assert set(values).issubset(backend_allowed), f"values not in backend allow-list: {values}"
    assert "active" in values  # active must always be present


@requires_node
def test_block_editor_debounce_semantics() -> None:
    """debounce coalesces rapid calls into a single trailing invocation."""
    out = _run_node(
        f"""
        const root = {{ document: null }};
        global.window = root;
        require({json.dumps(str(BLOCK_EDITOR))});
        const debounce = root.KmsBlockEditor._debounce;
        let calls = 0;
        const fn = () => {{ calls++; }};
        const d = debounce(fn, 30);
        d(); d(); d();
        setTimeout(() => {{
          process.stdout.write(String(calls));
        }}, 80);
        """
    )
    assert out.strip() == "1", f"expected 1 trailing call, got {out!r}"


@requires_node
def test_citation_viewer_module_loads() -> None:
    """citation_viewer module loads, exposes mount + _loadPdfJs."""
    out = _run_node(
        f"""
        const root = {{}};
        global.window = root;
        require({json.dumps(str(CITATION))});
        const v = root.KmsCitationViewer;
        process.stdout.write(JSON.stringify({{
          has_mount: typeof v.mount === 'function',
          has_loader: typeof v._loadPdfJs === 'function',
        }}));
        """
    )
    parsed = json.loads(out.strip())
    assert parsed["has_mount"] is True
    assert parsed["has_loader"] is True


def test_mvp_html_references_all_components() -> None:
    """doc-detail-mvp.html loads lib/api.js + 3 components in order."""
    txt = MVP_HTML.read_text(encoding="utf-8")
    assert "/lib/api.js" in txt
    assert "/components/citation_viewer.js" in txt
    assert "/components/block_editor.js" in txt
    assert "/components/table_editor.js" in txt
    # mounts both editors + viewer
    assert "KmsCitationViewer.mount" in txt
    assert "KmsBlockEditor.mount" in txt
    assert "KmsTableEditor.mount" in txt

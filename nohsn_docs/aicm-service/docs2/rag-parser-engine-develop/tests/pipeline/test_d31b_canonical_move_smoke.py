"""D31b §2A — SemanticBlockMerger canonical move smoke test.

old import path (`scripts.seed.semantic_block_merger`) 가 thin re-export 후에도
동작 + new canonical path 와 *동일 객체* 보장.

D31b spec v4 §5.6 case 41-42 + §6.4 (no scripts import) 의 일부.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC_PIPELINE = ROOT / "src" / "pipeline"


def test_semantic_block_merger_old_path_identity() -> None:
    """SemanticBlockMerger — old / new path 가 동일 객체."""
    from scripts.seed.semantic_block_merger import SemanticBlockMerger as Old
    from src.pipeline.processing.semantic_block_merger import (
        SemanticBlockMerger as New,
    )

    assert Old is New, "SemanticBlockMerger old re-export 가 canonical 와 다름"


def test_input_block_old_path_identity() -> None:
    """InputBlock — old / new path 동일 객체."""
    from scripts.seed.semantic_block_merger import InputBlock as Old
    from src.pipeline.models.chunking import InputBlock as New

    assert Old is New, "InputBlock old re-export 가 canonical 와 다름"


def test_merged_chunk_old_path_identity() -> None:
    """MergedChunk — old / new path 동일 객체."""
    from scripts.seed.semantic_block_merger import MergedChunk as Old
    from src.pipeline.models.chunking import MergedChunk as New

    assert Old is New, "MergedChunk old re-export 가 canonical 와 다름"


def test_old_path_module_imports_cleanly() -> None:
    """thin re-export module import smoke (SyntaxError / ImportError 0)."""
    import importlib

    mod = importlib.import_module("scripts.seed.semantic_block_merger")
    assert hasattr(mod, "SemanticBlockMerger")
    assert hasattr(mod, "InputBlock")
    assert hasattr(mod, "MergedChunk")
    assert hasattr(mod, "stats_for")


def test_no_scripts_import_in_src_pipeline() -> None:
    """src/pipeline/**/*.py 가 scripts.* 를 import 하지 않는지 AST 검증.

    D31b spec v4 §6.4 — D31a 의 부분 검사 (merged_chunk_builder + chunking) 를
    src/pipeline 전체로 확장. **예외 없음**.
    """
    bad: list[tuple[str, str]] = []
    for path in sorted(SRC_PIPELINE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        # spec v4 §6.4 — 예외 0. SyntaxError 도 fail (silently continue 금지).
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("scripts"):
                        bad.append((str(path.relative_to(ROOT)), a.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("scripts"):
                    bad.append((str(path.relative_to(ROOT)), node.module))
    assert not bad, f"src/pipeline scripts.* imports: {bad}"


def test_demo_function_reachable_via_old_path() -> None:
    """_demo() — re-export 통해 옛 main wrapper 가 호출 가능."""
    from scripts.seed.semantic_block_merger import _demo

    assert callable(_demo), "_demo must be callable via old path"

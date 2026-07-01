from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_service_imports_and_uses_context_weighting():
    src = _read("src/search/service.py")
    assert "from src.search.context_weighting import" in src
    assert "combine_dense_vectors(" in src
    assert "build_context_text(" in src
    assert "request.context_weighted" in src


def test_service_passes_context_key_to_cache():
    src = _read("src/search/service.py")
    assert "context_fingerprint(" in src
    assert "context_key=" in src


def test_reranker_has_fusion_fallback():
    src = _read("src/search/reranker/cross_encoder.py")
    assert "rerank_failed_fusion_fallback" in src
    assert "candidates[:top_k]" in src

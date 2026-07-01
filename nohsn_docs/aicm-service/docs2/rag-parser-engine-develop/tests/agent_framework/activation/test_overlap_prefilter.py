import numpy as np
from src.agent_framework.activation.overlap_prefilter import SemHashPreFilter, Candidate


def test_stage2a_cosine_filter():
    rng = np.random.default_rng(42)
    dim = 16
    new_emb = rng.normal(size=dim)
    new_emb /= np.linalg.norm(new_emb)

    corpus: list[Candidate] = []
    for i in range(100):
        v = rng.normal(size=dim)
        v /= np.linalg.norm(v)
        corpus.append(Candidate(doc_id=f"d{i}", embedding=v, title=f"t{i}"))
    for i in [5, 30, 77]:
        corpus[i].embedding = (new_emb * 0.95 + corpus[i].embedding * 0.05)
        corpus[i].embedding /= np.linalg.norm(corpus[i].embedding)

    f = SemHashPreFilter(stage2a_threshold=0.55, stage2a_topk=50)
    out = f.stage2a_filter(new_emb, corpus)
    ids = {c.doc_id for c in out}
    assert "d5" in ids and "d30" in ids and "d77" in ids
    assert len(out) <= 50


def test_small_corpus_bypass():
    f = SemHashPreFilter(small_corpus_bypass=30)
    corpus = [Candidate(doc_id=f"d{i}", embedding=np.zeros(4), title="") for i in range(10)]
    out = f.stage2a_filter(np.zeros(4), corpus)
    assert len(out) == 10

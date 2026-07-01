from src.search.context_weighting import build_anchor_query_text, select_anchors


def test_includes_current_query_and_user_turns_excludes_assistant():
    hist = [
        {"role": "user", "content": "하나코리아 펀드 가입했는데요"},
        {"role": "assistant", "content": "네 하나코리아증권자투자신탁 말씀이시군요"},
        {"role": "user", "content": "수수료가 궁금해요"},
    ]
    out = build_anchor_query_text("잠깐 환매하면 수수료 있어요?", hist)
    assert "잠깐 환매하면 수수료 있어요?" in out
    assert "하나코리아" in out          # user turn 포함
    assert "수수료가 궁금해요" in out   # user turn 포함
    assert "말씀이시군요" not in out    # assistant turn 제외


def test_no_history_returns_current_query():
    assert build_anchor_query_text("환매 수수료?", None).strip() == "환매 수수료?"


def test_recency_limit_user_turns():
    hist = [{"role": "user", "content": f"발화{i}"} for i in range(10)]
    out = build_anchor_query_text("현재", hist, max_user_turns=3)
    assert "발화9" in out and "발화8" in out and "발화7" in out
    assert "발화0" not in out


def test_single_strong_anchor():
    assert select_anchors([("docA", 9.0), ("docB", 2.0)], abs_min=3.0, rel_ratio=0.8) == ["docA"]


def test_multi_close_anchors():
    out = select_anchors([("docA", 9.0), ("docB", 8.5)], abs_min=3.0, rel_ratio=0.8)
    assert set(out) == {"docA", "docB"}


def test_no_anchor_below_abs_min():
    assert select_anchors([("docA", 1.0)], abs_min=3.0, rel_ratio=0.8) == []


def test_empty_input():
    assert select_anchors([], abs_min=3.0, rel_ratio=0.8) == []

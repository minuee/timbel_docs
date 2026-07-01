from src.api.routers.rag_assist import _needs_table_slot


def _hit(block_type):
    class H:
        pass
    h = H()
    h.block_type = block_type
    return h


def test_needs_table_slot_true_when_no_table_hit():
    hits = [_hit("paragraph"), _hit("bulleted_list"), _hit("heading_1")]
    assert _needs_table_slot(hits) is True


def test_needs_table_slot_false_when_table_present():
    hits = [_hit("paragraph"), _hit("table")]
    assert _needs_table_slot(hits) is False


def test_needs_table_slot_false_when_empty():
    assert _needs_table_slot([]) is False

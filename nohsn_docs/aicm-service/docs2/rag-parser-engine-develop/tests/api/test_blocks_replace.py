from uuid import uuid4

from src.api.routers.blocks import _deleted_block_ids


def test_deleted_ids_are_existing_not_in_incoming():
    id_keep, id_edit, id_gone = uuid4(), uuid4(), uuid4()
    existing = {id_keep, id_edit, id_gone}
    incoming = [
        {"block_id": id_keep, "content": "same", "block_type": "paragraph"},
        {"block_id": id_edit, "content": "changed", "block_type": "paragraph"},
        {"block_id": None, "content": "brand new", "block_type": "paragraph"},
    ]
    assert _deleted_block_ids(existing, incoming) == {id_gone}


def test_stale_incoming_id_not_protected_from_delete():
    stale = uuid4()
    existing = set()
    incoming = [{"block_id": stale, "content": "x", "block_type": "paragraph"}]
    assert _deleted_block_ids(existing, incoming) == set()

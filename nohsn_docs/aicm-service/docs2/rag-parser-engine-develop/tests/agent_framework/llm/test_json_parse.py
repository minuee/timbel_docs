import json

import pytest

from src.agent_framework.llm.json_parse import extract_json


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json_with_label():
    raw = '```json\n{"a": 1}\n```'
    assert extract_json(raw) == {"a": 1}


def test_fenced_json_no_label():
    raw = '```\n{"a": 1}\n```'
    assert extract_json(raw) == {"a": 1}


def test_fenced_with_whitespace():
    raw = '  \n```json\n{"intents": ["book_appointment"]}\n```  \n'
    assert extract_json(raw) == {"intents": ["book_appointment"]}


def test_prose_around_json():
    raw = '분류 결과: {"intents": ["book_appointment"]} 입니다.'
    assert extract_json(raw) == {"intents": ["book_appointment"]}


def test_bad_input_raises():
    with pytest.raises(json.JSONDecodeError):
        extract_json("totally not json at all")


def test_non_string_input_raises():
    with pytest.raises(TypeError):
        extract_json(None)


def test_array_top_level_parses():
    # Plain JSON parse 가 먼저 실행되므로 최상위 array 도 그대로 반환된다.
    # dict-ness 검증은 호출자 책임 (intent_classifier/slot_filler 는 별도 isinstance 체크).
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_garbage_no_braces_raises():
    # Case 3 (outermost {} 추출) 도 실패하는 완전 garbage 는 JSONDecodeError.
    with pytest.raises(json.JSONDecodeError):
        extract_json("no json here at all")


def test_gemma_typical_fenced_output():
    # Layer 2 live smoke 에서 실제 관찰된 포맷
    raw = '```json\n{\n  "intents": ["book_appointment"]\n}\n```'
    assert extract_json(raw) == {"intents": ["book_appointment"]}

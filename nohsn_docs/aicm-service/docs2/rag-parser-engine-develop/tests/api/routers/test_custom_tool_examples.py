"""Custom tool examples catalog 검증 테스트.

파일 기반 검증 (DB/서버 불필요) — CI 에서 즉시 실행 가능.
"""
import json
from pathlib import Path

import pytest

EXAMPLES_DIR = Path("src/agent_framework/agent_templates/custom_tool_examples")
REQUIRED_KEYS = [
    "id",
    "name",
    "display_name",
    "description",
    "category",
    "vendor",
    "endpoint_url",
    "method",
    "auth_headers",
    "input_schema",
    "risk_metadata",
    "setup_instructions",
]
VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _load_all_examples() -> list[dict]:
    files = sorted(EXAMPLES_DIR.glob("*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def test_15_examples_exist():
    files = list(EXAMPLES_DIR.glob("*.json"))
    assert len(files) == 15, f"expected 15, got {len(files)}: {[f.name for f in files]}"


def test_index_yaml_exists():
    index = EXAMPLES_DIR / "_index.yaml"
    assert index.exists(), "_index.yaml 파일이 없습니다"
    content = index.read_text(encoding="utf-8")
    assert "examples:" in content


def test_each_example_has_required_keys():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        for key in REQUIRED_KEYS:
            assert key in example, f"{name}: '{key}' 필드 누락"


def test_each_example_valid_method():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        assert example["method"] in VALID_METHODS, (
            f"{name}: method='{example['method']}' 는 유효하지 않습니다 "
            f"(허용: {VALID_METHODS})"
        )


def test_each_example_setup_instructions_min_3():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        steps = example.get("setup_instructions", [])
        assert isinstance(steps, list), f"{name}: setup_instructions 가 list 가 아닙니다"
        assert len(steps) >= 3, (
            f"{name}: setup_instructions 최소 3단계 필요 (현재 {len(steps)})"
        )


def test_each_example_input_schema_is_object():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        schema = example.get("input_schema", {})
        assert isinstance(schema, dict), f"{name}: input_schema 가 dict 가 아닙니다"


def test_each_example_risk_metadata_has_side_effect():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        rm = example.get("risk_metadata", {})
        assert "side_effect" in rm, f"{name}: risk_metadata.side_effect 누락"
        assert rm["side_effect"] in ("read", "write"), (
            f"{name}: risk_metadata.side_effect='{rm['side_effect']}' 는 유효하지 않습니다"
        )


def test_ids_match_filenames():
    for f in sorted(EXAMPLES_DIR.glob("*.json")):
        example = json.loads(f.read_text(encoding="utf-8"))
        expected_id = f.stem  # 파일명 (확장자 제외)
        assert example.get("id") == expected_id, (
            f"{f.name}: id='{example.get('id')}' 가 파일명 '{expected_id}' 와 다릅니다"
        )


def test_no_duplicate_ids():
    examples = _load_all_examples()
    ids = [e["id"] for e in examples]
    assert len(ids) == len(set(ids)), f"중복 id 발견: {[i for i in ids if ids.count(i) > 1]}"


def test_categories_cover_all_groups():
    """15개 예시가 4개 주요 카테고리(알림/SMS-메일/정보-검색/협업-CRM/결제-사업) 모두 포함."""
    examples = _load_all_examples()
    categories = {e["category"] for e in examples}
    expected = {"알림", "SMS/메일", "정보/검색", "협업/CRM", "결제/사업"}
    assert expected == categories, (
        f"카테고리 불일치. expected={expected}, got={categories}"
    )


def test_endpoint_urls_are_strings():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        url = example.get("endpoint_url", "")
        assert isinstance(url, str) and len(url) > 0, (
            f"{name}: endpoint_url 이 비어 있거나 string 이 아닙니다"
        )


def test_vendor_urls_are_https_when_present():
    for example in _load_all_examples():
        name = example.get("id", "<unknown>")
        vendor_url = example.get("vendor_url")
        if vendor_url:
            assert vendor_url.startswith("http"), (
                f"{name}: vendor_url='{vendor_url}' 이 http(s) 로 시작하지 않습니다"
            )

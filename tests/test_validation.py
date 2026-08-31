"""추출 결과가 calltree.schema.json 을 만족하는지 확인한다."""

from __future__ import annotations

import copy

import pytest

from calltree.extract import extract
from calltree.model import CallTree, Meta
from calltree.validation import find_schema, load_schema, validate
from conftest import FIXTURE_ROOT, make_commands, requires_libclang

jsonschema = pytest.importorskip("jsonschema")


def test_schema_file_is_found():
    assert find_schema().name == "calltree.schema.json"
    assert load_schema()["title"] == "Static Call Tree Extraction"


@pytest.fixture(scope="module")
def extracted() -> dict:
    tree = CallTree(
        meta=Meta(
            entry_point="c:@F@process_frame",
            compile_commands="build/compile_commands.json",
            clang_version="18.1.1",
            generated_at="2026-08-31T10:00:00+09:00",
            tu_count=3,
        ),
    )
    result = extract(make_commands(), root=FIXTURE_ROOT)
    tree.nodes = result.nodes
    tree.state = result.state
    return tree.to_dict()


@requires_libclang
def test_extraction_output_validates(extracted: dict):
    assert validate(extracted) == []


@requires_libclang
def test_validator_rejects_unknown_field(extracted: dict):
    data = copy.deepcopy(extracted)
    data["nodes"]["c:@F@process_frame"]["contamination_degree"] = 7
    errors = validate(data)
    # 판정 결과는 추출 파일에 들어가면 안 된다. 스키마가 막아준다.
    assert any("contamination_degree" in error for error in errors)


@requires_libclang
def test_validator_rejects_bad_access_value(extracted: dict):
    data = copy.deepcopy(extracted)
    data["nodes"]["c:@F@process_frame"]["state_uses"][0]["access"] = "maybe"
    assert validate(data)


def test_validator_reports_missing_meta():
    errors = validate({"schema_version": 1, "nodes": {}, "state": {}})
    assert any("meta" in error for error in errors)

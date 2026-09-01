"""추출/판정 결과가 각자의 스키마를 만족하는지 확인한다."""

from __future__ import annotations

import copy

import pytest

from calltree.analysis import analyze
from calltree.extract import extract
from calltree.model import CallTree, Meta
from calltree.validation import (
    find_analysis_schema,
    find_schema,
    load_analysis_schema,
    load_schema,
    schema_for,
    validate,
    validate_analysis,
)
from conftest import FIXTURE_ROOT, make_commands

jsonschema = pytest.importorskip("jsonschema")


def test_schema_file_is_found():
    assert find_schema().name == "calltree.schema.json"
    assert load_schema()["title"] == "Static Call Tree Extraction"


def test_analysis_schema_file_is_found():
    assert find_analysis_schema().name == "analysis.schema.json"
    assert load_analysis_schema()["title"] == "Contamination Analysis"


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


def test_extraction_output_validates(extracted: dict):
    assert validate(extracted) == []


def test_validator_rejects_unknown_field(extracted: dict):
    data = copy.deepcopy(extracted)
    data["nodes"]["c:@F@process_frame"]["contamination_degree"] = 7
    errors = validate(data)
    # 판정 결과는 추출 파일에 들어가면 안 된다. 스키마가 막아준다.
    assert any("contamination_degree" in error for error in errors)


def test_validator_rejects_bad_access_value(extracted: dict):
    data = copy.deepcopy(extracted)
    data["nodes"]["c:@F@process_frame"]["state_uses"][0]["access"] = "maybe"
    assert validate(data)


def test_validator_reports_missing_meta():
    errors = validate({"schema_version": 1, "nodes": {}, "state": {}})
    assert any("meta" in error for error in errors)


@pytest.fixture(scope="module")
def analyzed(extracted: dict) -> dict:
    return analyze(CallTree.from_dict(extracted), source="calltree.json").analysis.to_dict()


def test_analysis_output_validates(analyzed: dict):
    assert validate_analysis(analyzed) == []


def test_schema_is_chosen_by_content(extracted: dict, analyzed: dict):
    assert schema_for(extracted)["title"] == "Static Call Tree Extraction"
    assert schema_for(analyzed)["title"] == "Contamination Analysis"


def test_validator_rejects_reasons_without_impurity(analyzed: dict):
    data = copy.deepcopy(analyzed)
    data["nodes"]["c:common.h@F@clamp"]["impurity_reasons"] = ["c:@g_flag"]
    # 오염원이 아니면 사유가 있을 수 없다.
    assert validate_analysis(data)


def test_validator_rejects_impure_clean_subtree_root(analyzed: dict):
    data = copy.deepcopy(analyzed)
    data["nodes"]["c:@F@process_frame"]["is_clean_subtree_root"] = True
    assert validate_analysis(data)


def test_validator_rejects_extraction_fields_in_analysis(analyzed: dict):
    data = copy.deepcopy(analyzed)
    data["nodes"]["c:@F@process_frame"]["state_uses"] = []
    # 사실은 판정 파일에 들어가면 안 된다. 조인은 USR 로 한다.
    assert any("state_uses" in error for error in validate_analysis(data))

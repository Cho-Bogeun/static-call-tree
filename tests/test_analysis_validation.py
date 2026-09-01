"""판정 결과가 analysis.schema.json 을 만족하는지 확인한다.

스키마가 강제하는 것과 분석기가 지키는 것은 다르다. 여기서는 스키마가 막아주는
쪽만 본다 — 사유 없는 오염원, 오염원인 깨끗한 루트, 판정 파일에 섞인 사실.
"""

from __future__ import annotations

import copy

import pytest

from analyze.contamination import analyze
from analyze.validation import (
    find_analysis_schema,
    load_analysis_schema,
    schema_for,
    validate_analysis,
)
from calltree.model import CallTree

jsonschema = pytest.importorskip("jsonschema")


def test_analysis_schema_file_is_found():
    assert find_analysis_schema().name == "analysis.schema.json"
    assert load_analysis_schema()["title"] == "Contamination Analysis"


@pytest.fixture(scope="module")
def analyzed(extracted_tree: CallTree) -> dict:
    return analyze(extracted_tree, source="calltree.json").analysis.to_dict()


def test_analysis_output_validates(analyzed: dict):
    assert validate_analysis(analyzed) == []


def test_schema_is_chosen_by_content(extracted_tree: CallTree, analyzed: dict):
    assert schema_for(extracted_tree.to_dict())["title"] == "Static Call Tree Extraction"
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

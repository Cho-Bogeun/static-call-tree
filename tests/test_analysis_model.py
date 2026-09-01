"""analysis.schema.json 에 대응하는 데이터 모델의 직렬화."""

from __future__ import annotations

from analyze.model import (
    ANALYSIS_SCHEMA_VERSION,
    Analysis,
    Criteria,
    Verdict,
)


def make_analysis() -> Analysis:
    return Analysis(
        source="build/calltree.json",
        criteria=Criteria(),
        nodes={
            "c:@F@process_frame": Verdict(
                usr="c:@F@process_frame",
                is_impure=True,
                impurity_reasons=["c:@g_flag"],
                contamination_degree=12,
            ),
            "c:@F@decode": Verdict(usr="c:@F@decode", is_clean_subtree_root=True),
        },
    )


def test_analysis_to_dict_matches_schema_shape():
    data = make_analysis().to_dict()

    assert data["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert set(data) == {"schema_version", "source", "criteria", "nodes"}

    verdict = data["nodes"]["c:@F@process_frame"]
    assert set(verdict) == {
        "is_impure",
        "impurity_reasons",
        "is_contaminated",
        "contamination_degree",
        "is_clean_subtree_root",
        "scc_id",
    }
    # USR 은 맵의 키다. 값 안에 중복해서 넣지 않는다.
    assert "usr" not in verdict


def test_criteria_defaults_are_the_documented_ones():
    assert Criteria().to_dict() == {
        "exclude_const": True,
        "include_function_static": True,
        "addr_as": "readwrite",
        "const_read": False,
    }


def test_scc_id_is_null_until_we_need_it():
    assert make_analysis().to_dict()["nodes"]["c:@F@decode"]["scc_id"] is None


def test_analysis_nodes_are_sorted_by_usr():
    data = make_analysis().to_dict()
    assert list(data["nodes"]) == sorted(data["nodes"])


def test_analysis_round_trip():
    original = make_analysis()
    restored = Analysis.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.nodes["c:@F@decode"].usr == "c:@F@decode"

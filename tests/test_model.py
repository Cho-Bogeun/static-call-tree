from __future__ import annotations

from calltree.model import (
    SCHEMA_VERSION,
    Call,
    CallTree,
    FunctionNode,
    Loc,
    Meta,
    Param,
    StateUse,
    StateVar,
    UnresolvedCall,
)


def make_tree() -> CallTree:
    node = FunctionNode(
        usr="c:@F@process_frame",
        name="process_frame",
        linkage="external",
        kind="definition",
        loc=Loc("src/proc.c", 42),
        return_type="int",
        params=[Param("buf", "uint8_t *"), Param("len", "size_t")],
        calls=[Call("c:@F@decode", Loc("src/proc.c", 51))],
        state_uses=[StateUse("c:@g_cfg", "read", Loc("src/proc.c", 47))],
        unresolved_calls=[
            UnresolvedCall(Loc("src/proc.c", 88), "handlers[i].fn", "function_pointer")
        ],
    )
    state = StateVar(
        usr="c:@g_cfg",
        name="g_cfg",
        type="const struct config",
        scope="file_global",
        linkage="external",
        is_const=True,
        loc=Loc("src/cfg.c", 10),
    )
    return CallTree(
        meta=Meta(
            entry_point="c:@F@process_frame",
            compile_commands="build/compile_commands.json",
            clang_version="17.0.6",
            generated_at="2026-08-31T10:00:00+09:00",
            tu_count=84,
        ),
        nodes={node.usr: node},
        state={state.usr: state},
    )


def test_to_dict_matches_schema_shape():
    data = make_tree().to_dict()

    assert data["schema_version"] == SCHEMA_VERSION
    assert set(data) == {"schema_version", "meta", "nodes", "state"}

    node = data["nodes"]["c:@F@process_frame"]
    assert node["loc"] == {"file": "src/proc.c", "line": 42}
    assert node["calls"][0]["callee"] == "c:@F@decode"
    assert node["unresolved_calls"][0]["reason"] == "function_pointer"
    # USR 은 맵의 키다. 값 안에 중복해서 넣지 않는다.
    assert "usr" not in node


def test_state_var_omits_absent_owner():
    data = make_tree().to_dict()
    assert "owner" not in data["state"]["c:@g_cfg"]


def test_function_static_keeps_owner_and_hides_merge_metadata():
    var = StateVar(
        usr="c:proc.c@1043@F@process_frame@retry_cnt",
        name="retry_cnt",
        type="int",
        scope="function_static",
        linkage="internal",
        is_const=False,
        loc=Loc("src/proc.c", 44),
        owner="c:@F@process_frame",
        is_definition=True,
    )
    data = var.to_dict()
    assert data["owner"] == "c:@F@process_frame"
    # is_definition 은 병합 전용 메타데이터라 스키마에 없다.
    assert "is_definition" not in data


def test_round_trip():
    original = make_tree()
    restored = CallTree.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.nodes["c:@F@process_frame"].usr == "c:@F@process_frame"


def test_declaration_node_has_no_body_facts():
    node = FunctionNode(
        usr="c:@F@ext_lib",
        name="ext_lib",
        linkage="external",
        kind="declaration",
        loc=Loc("include/common.h", 9),
        return_type="int",
        params=[Param("v", "int")],
    )
    data = node.to_dict()
    assert data["kind"] == "declaration"
    assert data["calls"] == []
    assert data["state_uses"] == []
    assert data["unresolved_calls"] == []
    assert node.is_definition is False


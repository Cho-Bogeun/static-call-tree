from __future__ import annotations

from calltree.merge import merge_node, merge_nodes, merge_state_var
from calltree.model import Call, FunctionNode, Loc, Param, StateVar


def node(kind: str, file: str, calls: int = 0) -> FunctionNode:
    return FunctionNode(
        usr="c:@F@f",
        name="f",
        linkage="external",
        kind=kind,  # type: ignore[arg-type]
        loc=Loc(file, 1),
        return_type="int",
        params=[Param("v", "int")],
        calls=[Call("c:@F@g", Loc(file, 2)) for _ in range(calls)],
    )


def test_definition_overwrites_declaration():
    nodes: dict[str, FunctionNode] = {}
    merge_node(nodes, node("declaration", "include/f.h"))
    merge_node(nodes, node("definition", "src/f.c", calls=1))

    assert nodes["c:@F@f"].kind == "definition"
    assert nodes["c:@F@f"].loc.file == "src/f.c"


def test_declaration_does_not_overwrite_definition():
    nodes: dict[str, FunctionNode] = {}
    merge_node(nodes, node("definition", "src/f.c", calls=1))
    merge_node(nodes, node("declaration", "include/f.h"))

    assert nodes["c:@F@f"].kind == "definition"
    assert len(nodes["c:@F@f"].calls) == 1


def test_duplicate_definition_is_deduped_and_reported():
    """헤더의 static inline 은 TU 마다 등장한다. 두 번째는 버려져야 한다."""
    nodes: dict[str, FunctionNode] = {}
    first = node("definition", "include/f.h", calls=1)
    merge_node(nodes, first)

    second = node("definition", "include/f.h", calls=1)
    winner = merge_node(nodes, second)

    assert winner is first  # 호출자는 이걸 보고 본문 재순회를 건너뛴다
    assert len(nodes["c:@F@f"].calls) == 1


def test_declaration_fills_missing_signature():
    nodes: dict[str, FunctionNode] = {}
    bare = FunctionNode(
        usr="c:@F@f",
        name="f",
        linkage="external",
        kind="declaration",
        loc=Loc("a.h", 1),
    )
    merge_node(nodes, bare)
    merge_node(nodes, node("declaration", "b.h"))

    assert nodes["c:@F@f"].return_type == "int"
    assert nodes["c:@F@f"].params[0].name == "v"


def test_merge_nodes_over_dicts():
    dst = {"c:@F@f": node("declaration", "f.h")}
    merge_nodes(dst, {"c:@F@f": node("definition", "f.c")})
    assert dst["c:@F@f"].kind == "definition"


def state(is_definition: bool, file: str) -> StateVar:
    return StateVar(
        usr="c:@g_flag",
        name="g_flag",
        type="int",
        scope="file_global",
        linkage="external",
        is_const=False,
        loc=Loc(file, 3),
        is_definition=is_definition,
    )


def test_state_definition_wins_over_extern_declaration():
    table: dict[str, StateVar] = {}
    merge_state_var(table, state(False, "include/common.h"))
    merge_state_var(table, state(True, "src/cfg.c"))

    assert table["c:@g_flag"].loc.file == "src/cfg.c"


def test_state_declaration_does_not_clobber_definition():
    table: dict[str, StateVar] = {}
    merge_state_var(table, state(True, "src/cfg.c"))
    merge_state_var(table, state(False, "include/common.h"))

    assert table["c:@g_flag"].loc.file == "src/cfg.c"

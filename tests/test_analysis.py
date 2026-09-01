"""오염 판정. 그래프 논리는 손으로 만든 작은 콜트리로 확인한다.

추출과 달리 이 단계는 libclang 도 소스도 보지 않으므로, 판정에 필요한 최소한의
콜트리를 직접 만들어 경계 사례를 정확히 짚을 수 있다. 픽스처 프로젝트를 실제로
파싱한 결과는 파일 끝에서 한 번 확인한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pytest

from calltree.analysis import EntryNotFound, analyze, reachable_from
from calltree.extract import extract
from calltree.model import (
    ANALYSIS_SCHEMA_VERSION,
    Analysis,
    Call,
    CallTree,
    Criteria,
    FunctionNode,
    Loc,
    Meta,
    StateUse,
    StateVar,
    UnresolvedCall,
)
from conftest import FIXTURE_ROOT, make_commands

LOC = Loc(file="t.c", line=1)


def fn(name: str) -> str:
    return f"c:@F@{name}"


def var(name: str) -> str:
    return f"c:@{name}"


def make_tree(
    calls: Mapping[str, Iterable[str]],
    uses: Mapping[str, Iterable[tuple[str, str]]] | None = None,
    state: Mapping[str, Mapping[str, object]] | None = None,
    entry: str = "main",
    unresolved: Iterable[str] = (),
    declarations: Iterable[str] = (),
) -> CallTree:
    """이름으로 쓰는 콜트리 빌더. USR 은 `c:@F@<이름>` 규칙으로 만든다."""
    uses = uses or {}
    state = state or {}
    unresolved = set(unresolved)
    declarations = set(declarations)

    names = set(calls) | {callee for callees in calls.values() for callee in callees}
    names |= set(uses) | {entry}

    nodes: dict[str, FunctionNode] = {}
    for name in names:
        is_declaration = name in declarations
        nodes[fn(name)] = FunctionNode(
            usr=fn(name),
            name=name,
            linkage="external",
            kind="declaration" if is_declaration else "definition",
            loc=LOC,
            return_type=None if is_declaration else "int",
            calls=[
                Call(callee=fn(callee), loc=LOC) for callee in calls.get(name, ())
            ],
            state_uses=[
                StateUse(target=var(target), access=access, loc=LOC)
                for target, access in uses.get(name, ())
            ],
            unresolved_calls=[],
        )
        if name in unresolved:
            nodes[fn(name)].unresolved_calls = [
                UnresolvedCall(loc=LOC, expr="fn(v)", reason="function_pointer")
            ]

    variables: dict[str, StateVar] = {}
    for name, attrs in state.items():
        scope = attrs.get("scope", "file_global")
        variables[var(name)] = StateVar(
            usr=var(name),
            name=name,
            type="int",
            scope=scope,
            linkage="internal" if scope == "function_static" else "external",
            is_const=bool(attrs.get("is_const", False)),
            loc=LOC,
            owner=fn(str(attrs["owner"])) if "owner" in attrs else None,
        )

    return CallTree(
        meta=Meta(
            entry_point=fn(entry),
            compile_commands="build/compile_commands.json",
            clang_version="18.1.1",
            generated_at="2026-08-31T10:00:00+09:00",
            tu_count=1,
        ),
        nodes=nodes,
        state=variables,
    )


# ------------------------------------------------------------------ 1. 가지치기


def test_prunes_to_entry_reachable_nodes():
    """calltree.json 에는 TU 전체가 들어 있다. 진입점에서 닿는 것만 남긴다."""
    tree = make_tree({"main": ["a"], "a": [], "orphan": ["also_orphan"]})
    result = analyze(tree)

    assert set(result.analysis.nodes) == {fn("main"), fn("a")}
    assert result.total == 4


def test_pruning_terminates_on_cycles():
    tree = make_tree({"main": ["a"], "a": ["b"], "b": ["a", "main"]})
    assert reachable_from(tree, fn("main")) == {fn("main"), fn("a"), fn("b")}


def test_missing_entry_is_an_error():
    tree = make_tree({"main": []})
    tree.meta.entry_point = fn("no_such_function")
    with pytest.raises(EntryNotFound):
        analyze(tree)


def test_callee_missing_from_nodes_is_reported():
    tree = make_tree({"main": ["a"], "a": []})
    tree.nodes[fn("main")].calls.append(Call(callee=fn("ghost"), loc=LOC))
    result = analyze(tree)

    assert result.missing_callees == [fn("ghost")]
    assert fn("ghost") not in result.analysis.nodes


# --------------------------------------------------------------- 2. 오염원 판정


def test_impure_node_lists_deduped_sorted_targets():
    tree = make_tree(
        {"main": []},
        uses={"main": [("g_b", "write"), ("g_a", "read"), ("g_b", "read")]},
        state={"g_a": {}, "g_b": {}},
    )
    verdict = analyze(tree).analysis.nodes[fn("main")]

    assert verdict.is_impure
    assert verdict.impurity_reasons == [var("g_a"), var("g_b")]


def test_impurity_is_local_and_ignores_descendants():
    """후손이 오염되어도 자기 자신은 오염원이 아니다."""
    tree = make_tree(
        {"main": ["dirty"], "dirty": []},
        uses={"dirty": [("g", "write")]},
        state={"g": {}},
    )
    nodes = analyze(tree).analysis.nodes

    assert not nodes[fn("main")].is_impure
    assert nodes[fn("main")].impurity_reasons == []
    assert nodes[fn("dirty")].is_impure


def test_const_is_excluded_by_default():
    tree = make_tree(
        {"main": []},
        uses={"main": [("g_table", "read")]},
        state={"g_table": {"is_const": True}},
    )
    assert not analyze(tree).analysis.nodes[fn("main")].is_impure
    assert analyze(tree, Criteria(exclude_const=False)).analysis.nodes[
        fn("main")
    ].is_impure


def test_function_static_is_included_by_default():
    tree = make_tree(
        {"main": []},
        uses={"main": [("retry_cnt", "readwrite")]},
        state={"retry_cnt": {"scope": "function_static", "owner": "main"}},
    )
    assert analyze(tree).analysis.nodes[fn("main")].is_impure
    assert not analyze(
        tree, Criteria(include_function_static=False)
    ).analysis.nodes[fn("main")].is_impure


def test_unknown_state_target_counts_conservatively():
    """state 에 없으면 기준을 적용할 수 없다. 놓치는 쪽이 더 비싸므로 센다."""
    tree = make_tree({"main": []}, uses={"main": [("g_missing", "read")]})
    result = analyze(tree)

    assert result.analysis.nodes[fn("main")].is_impure
    assert result.unknown_state == [var("g_missing")]


@pytest.mark.parametrize("addr_as", ["read", "write", "readwrite", "manual"])
def test_addr_as_alone_does_not_change_the_verdict(addr_as: str):
    """const_read 가 꺼져 있으면 방향을 보지 않으므로 네 값이 같은 결과를 낸다."""
    tree = make_tree({"main": []}, uses={"main": [("g", "addr")]}, state={"g": {}})
    assert analyze(tree, Criteria(addr_as=addr_as)).analysis.nodes[fn("main")].is_impure


def test_reads_count_until_const_read_is_on():
    tree = make_tree({"main": []}, uses={"main": [("g", "read")]}, state={"g": {}})

    assert analyze(tree).analysis.nodes[fn("main")].is_impure
    assert not analyze(tree, Criteria(const_read=True)).analysis.nodes[
        fn("main")
    ].is_impure


def test_const_read_never_drops_a_write():
    tree = make_tree(
        {"main": []},
        uses={"main": [("g", "write"), ("g_rw", "readwrite")]},
        state={"g": {}, "g_rw": {}},
    )
    verdict = analyze(tree, Criteria(const_read=True)).analysis.nodes[fn("main")]

    assert verdict.impurity_reasons == [var("g"), var("g_rw")]


@pytest.mark.parametrize(
    ("addr_as", "expected"),
    [("read", False), ("write", True), ("readwrite", True), ("manual", True)],
)
def test_const_read_makes_addr_as_meaningful(addr_as: str, expected: bool):
    """§3 표의 순서. read 는 낙관적이라 오염원이 최소로, readwrite 는 보수적으로 나온다."""
    tree = make_tree({"main": []}, uses={"main": [("g", "addr")]}, state={"g": {}})
    verdict = analyze(
        tree, Criteria(addr_as=addr_as, const_read=True)
    ).analysis.nodes[fn("main")]

    assert verdict.is_impure is expected


def test_const_read_applies_to_unknown_targets_too():
    """대상 기준은 못 걸어도 방향은 접근 자체에서 알 수 있다."""
    tree = make_tree({"main": []}, uses={"main": [("g_missing", "read")]})
    assert not analyze(tree, Criteria(const_read=True)).analysis.nodes[
        fn("main")
    ].is_impure


def test_const_read_can_free_a_whole_subtree():
    """읽기만 하는 노드가 풀리면 그 위쪽이 새 테스트 경계가 된다."""
    tree = make_tree(
        {"main": ["mid"], "mid": ["reader"], "reader": []},
        uses={"main": [("g", "write")], "reader": [("g", "read")]},
        state={"g": {}},
    )
    assert [v.usr for v in analyze(tree).clean_subtree_roots] == []
    assert [
        v.usr for v in analyze(tree, Criteria(const_read=True)).clean_subtree_roots
    ] == [fn("mid")]


def test_manual_lists_addr_sites_for_review():
    tree = make_tree(
        {"main": []},
        uses={"main": [("g", "addr"), ("g_ro", "addr"), ("g", "write")]},
        state={"g": {}, "g_ro": {"is_const": True}},
    )
    result = analyze(tree, Criteria(addr_as="manual"))

    # const 로 걸러진 접근은 확인할 것도 없고, addr 이 아닌 접근도 대상이 아니다.
    assert [(site.usr, site.target) for site in result.manual_sites] == [
        (fn("main"), var("g"))
    ]
    assert analyze(tree, Criteria(addr_as="readwrite")).manual_sites == []


# ----------------------------------------------------------------- 3. 오염도


def test_degree_counts_self_and_ancestors():
    tree = make_tree(
        {"main": ["a"], "a": ["dirty"], "dirty": []},
        uses={"dirty": [("g", "write")]},
        state={"g": {}},
    )
    nodes = analyze(tree).analysis.nodes

    assert nodes[fn("dirty")].contamination_degree == 3
    # 오염원이 아닌 노드는 0 이다.
    assert nodes[fn("a")].contamination_degree == 0
    assert nodes[fn("main")].contamination_degree == 0


def test_degree_counts_each_ancestor_once():
    """다이아몬드. 같은 콜리를 여러 경로로 불러도 조상은 집합으로 센다."""
    tree = make_tree(
        {"main": ["left", "right"], "left": ["dirty"], "right": ["dirty"], "dirty": []},
        uses={"dirty": [("g", "write")]},
        state={"g": {}},
    )
    assert analyze(tree).analysis.nodes[fn("dirty")].contamination_degree == 4


def test_degree_counts_repeated_call_once():
    tree = make_tree({"main": ["dirty", "dirty"], "dirty": []},
                     uses={"dirty": [("g", "write")]}, state={"g": {}})
    assert analyze(tree).analysis.nodes[fn("dirty")].contamination_degree == 2


def test_degree_handles_recursion():
    """순환은 visited 집합으로 처리된다. SCC 축약이 필요 없는 이유다."""
    tree = make_tree(
        {"main": ["a"], "a": ["b"], "b": ["a"]},
        uses={"b": [("g", "write")]},
        state={"g": {}},
    )
    nodes = analyze(tree).analysis.nodes

    assert nodes[fn("b")].contamination_degree == 3
    assert nodes[fn("b")].scc_id is None


def test_entry_as_the_only_source_has_degree_one():
    tree = make_tree({"main": ["a"], "a": []}, uses={"main": [("g", "write")]},
                     state={"g": {}})
    assert analyze(tree).analysis.nodes[fn("main")].contamination_degree == 1


def test_priorities_are_sorted_by_degree():
    tree = make_tree(
        {"main": ["mid"], "mid": ["deep"], "deep": []},
        uses={"mid": [("g", "write")], "deep": [("g", "write")]},
        state={"g": {}},
    )
    assert [v.usr for v in analyze(tree).impure] == [fn("deep"), fn("mid")]


# ------------------------------------------------------------------ 4. 오염됨


def test_contaminated_is_an_ancestor_of_a_source():
    tree = make_tree(
        {"main": ["a"], "a": ["dirty"], "dirty": []},
        uses={"dirty": [("g", "write")]},
        state={"g": {}},
    )
    nodes = analyze(tree).analysis.nodes

    assert nodes[fn("main")].is_contaminated
    assert nodes[fn("a")].is_contaminated


def test_source_is_not_also_counted_as_contaminated():
    """규약: 자기 자신이 원인인 노드를 부수 피해로 세지 않는다."""
    tree = make_tree(
        {"main": ["dirty"], "dirty": []},
        uses={"main": [("g", "write")], "dirty": [("g", "write")]},
        state={"g": {}},
    )
    verdict = analyze(tree).analysis.nodes[fn("main")]

    assert verdict.is_impure
    assert not verdict.is_contaminated


def test_siblings_of_a_source_stay_clean():
    tree = make_tree(
        {"main": ["clean", "dirty"], "clean": [], "dirty": []},
        uses={"dirty": [("g", "write")]},
        state={"g": {}},
    )
    verdict = analyze(tree).analysis.nodes[fn("clean")]

    assert not verdict.is_impure
    assert not verdict.is_contaminated


# ------------------------------------------------- 4. 깨끗한 서브트리 루트


def test_clean_root_is_the_top_of_a_clean_region():
    """리프가 아니라 깨끗한 영역의 가장 위쪽이 잡혀야 한다."""
    tree = make_tree(
        {"main": ["mid"], "mid": ["leaf"], "leaf": []},
        uses={"main": [("g", "write")]},
        state={"g": {}},
    )
    roots = [v.usr for v in analyze(tree).clean_subtree_roots]

    assert roots == [fn("mid")]


def test_entry_is_the_only_root_when_nothing_is_impure():
    tree = make_tree({"main": ["a", "b"], "a": ["c"], "b": [], "c": []})
    result = analyze(tree)

    assert [v.usr for v in result.clean_subtree_roots] == [fn("main")]
    assert not any(v.is_contaminated for v in result.analysis.nodes.values())


def test_impure_node_is_never_a_clean_root():
    tree = make_tree({"main": []}, uses={"main": [("g", "write")]}, state={"g": {}})
    verdict = analyze(tree).analysis.nodes[fn("main")]

    assert verdict.is_impure
    assert not verdict.is_clean_subtree_root


def test_unresolved_call_blocks_the_root_and_its_ancestors():
    """함수 포인터 아래를 알 수 없으면 깨끗해 보이는 것이지 깨끗한 것이 아니다."""
    tree = make_tree(
        {"main": ["mid"], "mid": ["leaf"], "leaf": []},
        uses={"main": [("g", "write")]},
        state={"g": {}},
        unresolved=["leaf"],
    )
    result = analyze(tree)

    assert result.unresolved == [fn("leaf")]
    assert [v.usr for v in result.clean_subtree_roots] == []


def test_unresolved_elsewhere_does_not_block_a_clean_sibling():
    tree = make_tree(
        {"main": ["opaque", "clean"], "opaque": [], "clean": []},
        uses={"main": [("g", "write")]},
        state={"g": {}},
        unresolved=["opaque"],
    )
    assert [v.usr for v in analyze(tree).clean_subtree_roots] == [fn("clean")]


def test_declaration_is_a_clean_leaf_and_gets_reported():
    """정의를 보지 못했으므로 낙관적으로 깨끗하다고 본다. 눈으로 확인해야 한다."""
    tree = make_tree(
        {"main": ["strtok"]},
        uses={"main": [("g", "write")]},
        state={"g": {}},
        declarations=["strtok"],
    )
    result = analyze(tree)

    assert result.declarations == [fn("strtok")]
    assert result.analysis.nodes[fn("strtok")].is_clean_subtree_root


# -------------------------------------------------------------------- 직렬화


def test_criteria_are_recorded_in_the_output():
    tree = make_tree({"main": []})
    criteria = Criteria(
        exclude_const=False,
        include_function_static=False,
        addr_as="manual",
        const_read=True,
    )
    data = analyze(tree, criteria, source="build/calltree.json").analysis.to_dict()

    assert data["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert data["source"] == "build/calltree.json"
    assert data["criteria"] == {
        "exclude_const": False,
        "include_function_static": False,
        "addr_as": "manual",
        "const_read": True,
    }


def test_output_is_sorted_by_usr():
    tree = make_tree({"main": ["z", "a"], "z": [], "a": []})
    data = analyze(tree).analysis.to_dict()

    assert list(data["nodes"]) == sorted(data["nodes"])


def test_verdict_round_trips():
    tree = make_tree(
        {"main": ["dirty"], "dirty": []},
        uses={"dirty": [("g", "write")]},
        state={"g": {}},
    )
    data = analyze(tree).analysis.to_dict()

    assert Analysis.from_dict(data).to_dict() == data


# ------------------------------------------------------------------ 픽스처


@pytest.fixture(scope="module")
def fixture_tree() -> CallTree:
    result = extract(make_commands(), root=FIXTURE_ROOT)
    return CallTree(
        meta=Meta(
            entry_point="c:@F@process_frame",
            compile_commands="build/compile_commands.json",
            clang_version="18.1.1",
            generated_at="2026-08-31T10:00:00+09:00",
            tu_count=3,
        ),
        nodes=result.nodes,
        state=result.state,
    )


def test_fixture_analysis(fixture_tree: CallTree):
    result = analyze(fixture_tree)
    nodes = result.analysis.nodes

    # aux.c 쪽은 진입점에서 닿지 않으므로 잘려나간다.
    assert "c:@F@aux_entry" not in nodes
    assert "c:aux.c@F@reset" not in nodes

    # reset 을 고치면 자신과 process_frame 이 함께 풀린다.
    assert [v.usr for v in result.impure] == [
        "c:proc.c@F@reset",
        "c:@F@process_frame",
    ]
    assert nodes["c:proc.c@F@reset"].contamination_degree == 2
    assert nodes["c:@F@process_frame"].contamination_degree == 1

    # const 인 g_cfg 는 기본 기준에서 빠지고, 함수 내 static 인 retry_cnt 는 들어온다.
    assert nodes["c:@F@process_frame"].impurity_reasons == [
        "c:@g_flag",
        "c:proc.c@264@F@process_frame@retry_cnt",
        "c:proc.c@g_buf",
    ]

    # dispatch 는 함수 포인터를 부르므로 서브트리를 알 수 없다.
    assert result.unresolved == ["c:proc.c@F@dispatch"]
    assert not nodes["c:proc.c@F@dispatch"].is_clean_subtree_root

    assert [v.usr for v in result.clean_subtree_roots] == [
        "c:@F@ext_lib",
        "c:@F@sink",
        "c:common.h@F@clamp",
    ]
    assert result.declarations == ["c:@F@ext_lib", "c:@F@sink"]


def test_fixture_const_criterion_changes_the_reasons(fixture_tree: CallTree):
    result = analyze(fixture_tree, Criteria(exclude_const=False))
    assert "c:@g_cfg" in result.analysis.nodes["c:@F@process_frame"].impurity_reasons


def test_fixture_const_read_drops_the_array_that_is_only_read(fixture_tree: CallTree):
    """g_buf 는 process_frame 안에서 sink(g_buf) 감쇠와 g_buf[i] 읽기로만 닿는다.

    감쇠를 읽기로 보면 둘 다 빠지므로 오염원 근거에서 사라진다. reset 쪽은
    g_buf[0] = 0 으로 쓰므로 그대로 남는다.
    """
    nodes = analyze(
        fixture_tree, Criteria(addr_as="read", const_read=True)
    ).analysis.nodes

    assert nodes["c:@F@process_frame"].impurity_reasons == [
        "c:@g_flag",
        "c:proc.c@264@F@process_frame@retry_cnt",
    ]
    assert "c:proc.c@g_buf" in nodes["c:proc.c@F@reset"].impurity_reasons


def test_fixture_summary_mentions_the_priorities(fixture_tree: CallTree):
    summary = analyze(fixture_tree).summary(fixture_tree)

    assert "process_frame" in summary
    assert "exclude_const=true" in summary
    assert "clamp" in summary


def test_fixture_analysis_validates(fixture_tree: CallTree):
    pytest.importorskip("jsonschema")
    from calltree.validation import validate_analysis

    assert validate_analysis(analyze(fixture_tree).analysis.to_dict()) == []

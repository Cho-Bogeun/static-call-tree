"""시각화. 원칙 문서가 요구한 성질을 그대로 확인한다.

그림 자체는 눈으로 봐야 하지만, 원칙 대부분은 그림이 아니라 **페이로드**에 대한
요구다. 깊이가 수직으로 고정되는가(§4), 깨끗한 서브트리가 접힌 채로 나오는가(§5),
상태가 배치에 영향을 주지 않는가(§8) — 전부 여기서 확인할 수 있다.

브라우저가 필요한 부분(호버, 시뮬레이션)은 페이로드가 그 계산에 필요한 것을 다
담고 있는지까지만 본다. 조상 집합은 판정 단계가 이미 확인한 논리를 그대로 쓴다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from analyze import Criteria, analyze
from calltree.model import (
    Call,
    CallTree,
    FunctionNode,
    Loc,
    Meta,
    StateUse,
    StateVar,
    UnresolvedCall,
)
from cstat.cli import main
from visualize.payload import build_payload, common_prefix, spanning_tree
from visualize.render import render

LOC = Loc(file="t.c", line=1)


def fn(name: str) -> str:
    return f"c:@F@{name}"


def make_tree(
    calls: Mapping[str, Iterable[str]],
    uses: Mapping[str, Iterable[str]] | None = None,
    entry: str = "main",
    unresolved: Iterable[str] = (),
    declarations: Iterable[str] = (),
) -> CallTree:
    """이름으로 쓰는 콜트리 빌더.

    상태 접근은 대상 이름만 준다. `state` 에 없는 대상은 기준을 적용할 근거가 없어
    보수적으로 오염원 근거가 되므로(판정 단계의 규칙), 그림 시험에는 이걸로 충분하다.
    """
    uses = dict(uses or {})
    unresolved = set(unresolved)
    declarations = set(declarations)

    names = set(calls) | {callee for group in calls.values() for callee in group}
    names |= set(uses) | {entry}

    nodes = {}
    for name in names:
        nodes[fn(name)] = FunctionNode(
            usr=fn(name),
            name=name,
            linkage="external",
            kind="declaration" if name in declarations else "definition",
            loc=LOC,
            calls=[Call(callee=fn(callee), loc=LOC) for callee in calls.get(name, ())],
            state_uses=[
                StateUse(target=f"c:@{target}", access="write", loc=LOC)
                for target in uses.get(name, ())
            ],
            unresolved_calls=[
                UnresolvedCall(loc=LOC, expr="fn(v)", reason="function_pointer")
            ]
            if name in unresolved
            else [],
        )

    return CallTree(
        meta=Meta(
            entry_point=fn(entry),
            compile_commands="build/compile_commands.json",
            clang_version="18.1.1",
            generated_at="2026-09-01T10:00:00+09:00",
            tu_count=1,
        ),
        nodes=nodes,
    )


def payload_of(tree: CallTree, criteria: Criteria | None = None) -> dict:
    return build_payload(tree, analyze(tree, criteria).analysis)


def by_name(payload: dict) -> dict[str, dict]:
    return {node["name"]: node for node in payload["nodes"]}


# ------------------------------------------------------------------ 라벨 (§9)


def test_common_prefix_cuts_at_a_word_boundary():
    """`hal_uart_` 까지 겹쳐도 자르는 것은 단어 경계까지다."""
    assert common_prefix(["hal_uart_write", "hal_uart_read"]) == "hal_uart_"
    assert common_prefix(["hal_uart_write", "hal_spi_read"]) == "hal_"


def test_common_prefix_gives_up_when_it_would_eat_a_name():
    """이름이 통째로 사라지면 잘라서 얻는 게 없다."""
    assert common_prefix(["hal_", "hal_uart_write"]) == ""
    assert common_prefix(["read", "write"]) == ""
    assert common_prefix(["only_one"]) == ""


def test_payload_shortens_names_with_the_prefix():
    payload = payload_of(make_tree({"app_main": ["app_run"]}, entry="app_main"))
    assert by_name(payload)["app_run"]["short"] == "run"
    assert payload["prefix"] == "app_"


# --------------------------------------------------------- 깊이와 배치 (§4, §8)


def test_depth_is_the_shortest_call_distance():
    """진입점을 맨 위에 두고 깊이를 층으로 내린다. 층은 하나로 정해져야 한다.

    `deep` 은 두 경로로 닿지만 층은 하나다 — 짧은 쪽을 쓴다.
    """
    tree = make_tree({"main": ["mid", "deep"], "mid": ["deep"]})
    nodes = by_name(payload_of(tree))
    assert nodes["main"]["depth"] == 0
    assert nodes["mid"]["depth"] == 1
    assert nodes["deep"]["depth"] == 1


def test_children_are_ordered_by_name_not_by_call_order():
    """정렬 기준을 이름으로 못박아야 수정 전후 그림이 겹쳐 보인다(§8)."""
    tree = make_tree({"main": ["zeta", "alpha", "mid"]})
    payload = payload_of(tree)
    nodes = payload["nodes"]
    entry = nodes[payload["entry"]]
    assert [nodes[i]["name"] for i in entry["children"]] == ["alpha", "mid", "zeta"]


def test_shared_node_gets_one_parent_and_the_rest_become_cross_edges():
    """공유 노드가 여러 부모 밑에 복제되면 서브트리 단위의 뭉침이 안 보인다."""
    tree = make_tree(
        {"main": ["a", "b"], "a": ["shared"], "b": ["shared"]},
        uses={"shared": ["g_flag"]},
    )
    payload = payload_of(tree)
    index = {node["name"]: i for i, node in enumerate(payload["nodes"])}

    parents = [n["name"] for n in payload["nodes"] if index["shared"] in n["children"]]
    assert parents == ["a"]  # 같은 깊이면 이름이 앞선 쪽이 부모다
    # 배치 트리에 못 들어간 호출도 오염이 타고 오르는 길이면 그린다(§10).
    assert payload["cross"] == [[index["b"], index["shared"]]]
    # 호버와 시뮬레이션은 배치 트리가 아니라 전체 역방향 간선을 따라간다.
    assert payload["nodes"][index["shared"]]["callers"] == sorted(
        [index["a"], index["b"]]
    )


def test_spanning_tree_covers_every_reachable_node_once():
    tree = make_tree({"main": ["a", "b"], "a": ["b", "c"], "c": ["main"]})
    reachable = set(analyze(tree).analysis.nodes)
    parent, depth, children = spanning_tree(tree, reachable, fn("main"))
    assert set(parent) == reachable
    assert parent[fn("main")] is None
    # 순환(c -> main)이 있어도 부모는 하나뿐이다.
    assert sum(len(group) for group in children.values()) == len(reachable) - 1


def test_state_does_not_move_anything():
    """§8 의 핵심. 판정이 달라져 색이 바뀌어도 좌표를 정하는 값은 그대로다.

    접힘 기본값(`impure_below`)은 §5 가 판정을 보라고 한 것이라 같이 바뀐다. 다만
    화면 안에서 도는 시뮬레이션은 이 값을 다시 계산하지 않으므로, 고쳤다고 가정하는
    동안 배치는 움직이지 않는다.
    """

    def structure(payload: dict) -> list:
        return [
            (node["usr"], node["depth"], node["children"], node["subtree"])
            for node in payload["nodes"]
        ]

    tree = make_tree({"main": ["a"], "a": ["b"]}, uses={"b": ["counter"]})
    tree.state["c:@counter"] = StateVar(
        usr="c:@counter",
        name="counter",
        type="int",
        scope="function_static",
        linkage="internal",
        is_const=False,
        loc=LOC,
        owner=fn("b"),
    )

    strict = payload_of(tree, Criteria())
    loose = payload_of(tree, Criteria(include_function_static=False))

    assert structure(strict) == structure(loose)
    # 색은 실제로 달라져야 시험이 의미가 있다.
    assert [n["state"] for n in strict["nodes"]] != [n["state"] for n in loose["nodes"]]


# ------------------------------------------------------------------ 접기 (§5)


def test_clean_subtrees_are_marked_by_structure_not_by_colour():
    """접기 기준은 "서브트리 안에 오염원이 없다" 이고, 이건 구조에서 나온 수다."""
    tree = make_tree(
        {"main": ["dirty", "clean_top"], "dirty": ["leaf"], "clean_top": ["helper"]},
        uses={"leaf": ["g_flag"]},
    )
    nodes = by_name(payload_of(tree))
    assert nodes["clean_top"]["impure_below"] == 0
    assert nodes["clean_top"]["subtree"] == 1
    assert nodes["dirty"]["impure_below"] == 1
    # 접힌 노드가 곧 확보된 테스트 경계다.
    assert nodes["clean_top"]["boundary"] is True


def test_subtree_counts_are_the_badge_numbers():
    tree = make_tree({"main": ["a"], "a": ["b", "c"], "b": ["d"]})
    nodes = by_name(payload_of(tree))
    assert nodes["a"]["subtree"] == 3
    assert nodes["b"]["subtree"] == 1
    assert nodes["c"]["subtree"] == 0


# ------------------------------------------------------- 색과 간선 (§3, §10)


def test_three_states_are_distinguished(extracted_tree: CallTree):
    nodes = by_name(payload_of(extracted_tree))
    assert nodes["process_frame"]["state"] == "impure"
    assert nodes["reset"]["state"] == "impure"
    assert nodes["clamp"]["state"] == "clean"
    assert nodes["clamp"]["boundary"] is True
    # 함수 포인터를 부르는 노드는 깨끗해도 경계가 아니다. 그림에서도 갈려야 한다.
    assert nodes["dispatch"]["state"] == "clean"
    assert nodes["dispatch"]["boundary"] is False
    assert nodes["dispatch"]["unresolved"] is True
    assert nodes["ext_lib"]["declaration"] is True


def test_clean_cross_edges_are_dropped_not_drawn():
    """오염 전파와 무관한 간선은 세기만 한다. 다 그리면 선이 엉킨다(§10)."""
    tree = make_tree({"main": ["a", "b"], "a": ["shared"], "b": ["shared"]})
    payload = payload_of(tree)
    assert payload["cross"] == []
    assert payload["omitted_edges"] == 1


def test_degree_and_reasons_ride_along_for_the_ranking(extracted_tree: CallTree):
    """순위표가 쓸 것 — 오염도, 전역 read/write 구분, 함수 내 static 여부(§7)."""
    nodes = by_name(payload_of(extracted_tree))
    assert nodes["reset"]["degree"] == 2
    reasons = {reason["name"]: reason for reason in nodes["process_frame"]["reasons"]}
    assert reasons["g_flag"]["write"] and reasons["g_flag"]["read"]
    assert reasons["g_flag"]["addr"]  # sink(&g_flag)
    assert reasons["retry_cnt"]["static"] is True
    assert reasons["g_buf"]["read"] and not reasons["g_buf"]["write"]


def test_unknown_state_targets_are_marked():
    """state 에 없는 대상은 기준을 적용할 수 없어 남은 것이다. 툴팁에서 갈려야 한다."""
    nodes = by_name(payload_of(make_tree({"main": []}, uses={"main": ["g_ghost"]})))
    assert nodes["main"]["reasons"][0]["unknown"] is True


def test_function_static_scope_comes_from_the_state_table():
    tree = make_tree({"main": []}, uses={"main": ["counter"]})
    tree.state["c:@counter"] = StateVar(
        usr="c:@counter",
        name="counter",
        type="int",
        scope="function_static",
        linkage="internal",
        is_const=False,
        loc=LOC,
        owner=fn("main"),
    )
    nodes = by_name(payload_of(tree))
    assert nodes["main"]["reasons"][0]["static"] is True


# ---------------------------------------------------------------- 렌더링


def test_page_is_self_contained(extracted_tree: CallTree):
    """망이 끊긴 장비에서도 열려야 하고, 며칠 뒤 다시 열어도 같아야 한다."""
    html = render(extracted_tree, analyze(extracted_tree).analysis)
    assert html.startswith("<!doctype html>")
    assert "process_frame" in html
    for placeholder in ("__DATA__", "/*__CSS__*/", "/*__JS__*/", "__TITLE__"):
        assert placeholder not in html
    # 바깥으로 나가는 링크가 하나라도 있으면 그때 깨진다. 네임스페이스만 예외다.
    external = html.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in external and "https://" not in external


def test_rendering_is_reproducible(extracted_tree: CallTree):
    """같은 입력이면 같은 바이트. 두 장을 겹쳐 보려면 이게 먼저다(§8)."""
    analysis = analyze(extracted_tree).analysis
    assert render(extracted_tree, analysis) == render(extracted_tree, analysis)


def test_payload_cannot_close_the_script_tag():
    """경로 문자열은 우리가 만든 것이 아니다."""
    tree = make_tree({"main": []})
    tree.nodes[fn("main")].loc = Loc(file="a</script><script>alert(1)</script>", line=1)
    html = render(tree, analyze(tree).analysis)
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script>" in html


# ------------------------------------------------------------------- 명령


@pytest.fixture
def calltree_file(extracted_tree: CallTree, tmp_path: Path) -> Path:
    path = tmp_path / "calltree.json"
    path.write_text(
        json.dumps(extracted_tree.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_visualize_writes_one_html_file(calltree_file: Path, tmp_path: Path):
    output = tmp_path / "tree.html"
    assert main(["visualize", str(calltree_file), "-o", str(output), "--quiet"]) == 0
    html = output.read_text(encoding="utf-8")
    assert "<title>process_frame" in html
    assert '"entry"' in html


def test_visualize_prints_a_summary(calltree_file: Path, tmp_path: Path, capsys):
    assert main(["visualize", str(calltree_file), "-o", str(tmp_path / "t.html")]) == 0
    summary = capsys.readouterr().err
    assert "오염원 2개" in summary
    assert "깨끗한 경계 3개" in summary


def test_visualize_to_stdout(calltree_file: Path, capsys):
    assert main(["visualize", str(calltree_file), "--quiet"]) == 0
    assert capsys.readouterr().out.startswith("<!doctype html>")


def test_visualize_applies_the_criteria_flags(calltree_file: Path, tmp_path: Path):
    """기준을 바꿔 그림을 여러 장 뽑는 것이 이 단계의 실제 사용법이다."""
    strict = tmp_path / "strict.html"
    loose = tmp_path / "loose.html"
    main(["visualize", str(calltree_file), "-o", str(strict), "--quiet"])
    main(
        [
            "visualize",
            str(calltree_file),
            "-o",
            str(loose),
            "--no-function-static",
            "--quiet",
        ]
    )
    assert "include_function_static=true" in strict.read_text(encoding="utf-8")
    assert "include_function_static=false" in loose.read_text(encoding="utf-8")


def test_visualize_reuses_a_given_analysis(calltree_file: Path, tmp_path: Path):
    """판정을 다시 하지 않는다. 그림에 실린 기준이 그 파일의 것이어야 한다."""
    analysis = tmp_path / "analysis.json"
    main(
        [
            "analyze",
            str(calltree_file),
            "-o",
            str(analysis),
            "--no-function-static",
            "--quiet",
        ]
    )
    output = tmp_path / "tree.html"
    assert (
        main(
            [
                "visualize",
                str(calltree_file),
                "-a",
                str(analysis),
                "-o",
                str(output),
                "--quiet",
            ]
        )
        == 0
    )
    # 플래그를 하나도 주지 않았는데도 파일의 기준이 그대로 나온다.
    assert "include_function_static=false" in output.read_text(encoding="utf-8")


def test_visualize_refuses_criteria_next_to_an_analysis_file(
    calltree_file: Path, tmp_path: Path
):
    """기준이 두 벌이 되면 범례와 파일이 어긋나도 아무도 모른다."""
    analysis = tmp_path / "analysis.json"
    main(["analyze", str(calltree_file), "-o", str(analysis), "--quiet"])
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "visualize",
                str(calltree_file),
                "-a",
                str(analysis),
                "--const-read",
                "--quiet",
            ]
        )
    assert "criteria" in str(exc.value)


def test_visualize_rejects_an_analysis_from_another_calltree(
    calltree_file: Path, tmp_path: Path
):
    """어긋난 짝을 그리면 노드가 조용히 사라진다. 그림에서는 눈에 띄지 않는다."""
    analysis = tmp_path / "analysis.json"
    main(["analyze", str(calltree_file), "-o", str(analysis), "--quiet"])
    data = json.loads(analysis.read_text(encoding="utf-8"))
    data["nodes"]["c:@F@ghost"] = data["nodes"]["c:proc.c@F@reset"]
    analysis.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["visualize", str(calltree_file), "-a", str(analysis), "--quiet"])
    assert "c:@F@ghost" in str(exc.value)


def test_visualize_rejects_an_entry_missing_from_nodes(
    calltree_file: Path, tmp_path: Path
):
    data = json.loads(calltree_file.read_text(encoding="utf-8"))
    data["meta"]["entry_point"] = "c:@F@ghost"
    calltree_file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["visualize", str(calltree_file), "--quiet"])

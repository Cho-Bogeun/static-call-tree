"""판정 결과에서 **그림에 쓸 것만** 남긴 페이로드.

시각화 원칙 §1 은 이 그림의 목적을 하나로 못박는다 — "테스트 경계를 어디에 그을
것인가". 그 판단에 기여하지 않는 정보(LOC, 호출 횟수, 커밋 빈도)는 화면에서 빼는
게 아니라 **애초에 페이로드에 넣지 않는다.** 데이터에 없으면 실수로 그려질 일도
없다.

원칙 §8(재현 시 비교 가능)도 여기서 지켜진다.

- 자식 정렬 기준은 이름 고정이다. 상태가 바뀌어도 순서가 흔들리지 않는다.
- 배치에 쓰이는 값(`depth`, `children`, `subtree`)은 전부 콜 그래프 구조에서만
  나온다. 판정 결과(색)는 어느 것에도 끼어들지 않는다.
- 현재 시각을 보지 않는다. 표시용 시각은 콜트리 메타에서 가져온다. 같은 입력이면
  같은 바이트가 나와야 두 장을 겹쳐 볼 수 있다.

입력은 `CallTree`(사실)와 `Analysis`(판단) 두 개다. 판정이 파일에서 왔든 즉석에서
계산됐든 여기서는 구분되지 않는다.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from analyze.model import Analysis, Verdict
from calltree.model import CallTree, FunctionNode

#: 접두사를 자를 최소 길이. `g_` 두 글자를 자르는 건 이득이 없다.
MIN_PREFIX = 3


# ------------------------------------------------------------------- 라벨 (§9)


def common_prefix(names: list[str]) -> str:
    """잘라낼 공통 접두사. 없으면 빈 문자열.

    C 함수명은 접두사가 겹쳐서 노드가 넓어진다(§9). 다만 단어 중간에서 자르면
    남은 이름이 읽히지 않으므로 `_` 경계까지만 물러선다. 하나라도 이름이
    통째로 사라지는 경우에는 자르지 않는다.
    """
    if len(names) < 2:
        return ""

    first, last = min(names), max(names)
    end = 0
    while end < len(first) and end < len(last) and first[end] == last[end]:
        end += 1

    cut = first.rfind("_", 0, end)
    if cut < 0:
        return ""
    prefix = first[: cut + 1]
    if len(prefix) < MIN_PREFIX or any(len(name) <= len(prefix) for name in names):
        return ""
    return prefix


# ------------------------------------------------------- 배치의 뼈대 (§4, §8)


def callees(node: FunctionNode, reachable: set[str], tree: CallTree) -> list[str]:
    """중복을 없애고 이름으로 정렬한 콜리.

    정렬 기준을 이름으로 못박는 것이 §8 의 요구다. 같은 콜리를 몇 번 부르든
    간선은 하나다 — 호출 횟수는 경계 판단에 쓰이지 않는다(§2).
    """
    unique = {call.callee for call in node.calls if call.callee in reachable}
    return sorted(unique, key=lambda usr: (tree.nodes[usr].name, usr))


def spanning_tree(
    tree: CallTree, reachable: set[str], entry: str
) -> tuple[dict[str, str | None], dict[str, int], dict[str, list[str]]]:
    """진입점에서 BFS 로 뽑은 배치용 트리.

    콜 그래프는 트리가 아니다(공유 노드와 순환이 있다). 깊이를 수직으로 고정하려면
    노드마다 층이 하나로 정해져야 하므로, **최단 호출 거리**를 깊이로 삼고 그
    거리를 처음 준 호출자를 배치상의 부모로 둔다. 나머지 호출 간선은 여기 들어오지
    않고 `cross` 로 빠진다.
    """
    parent: dict[str, str | None] = {entry: None}
    depth = {entry: 0}
    children: dict[str, list[str]] = {usr: [] for usr in reachable}

    queue = deque([entry])
    while queue:
        usr = queue.popleft()
        for callee in callees(tree.nodes[usr], reachable, tree):
            if callee in parent:
                continue
            parent[callee] = usr
            depth[callee] = depth[usr] + 1
            children[usr].append(callee)
            queue.append(callee)

    return parent, depth, children


def _post_order(children: dict[str, list[str]], entry: str) -> list[str]:
    """자식이 부모보다 먼저 오는 순서. 서브트리 집계용이다."""
    order: list[str] = []
    stack = [(entry, False)]
    while stack:
        usr, expanded = stack.pop()
        if expanded:
            order.append(usr)
            continue
        stack.append((usr, True))
        for child in children[usr]:
            stack.append((child, False))
    return order


# ---------------------------------------------------------------- 오염원 근거


def reasons_of(
    node: FunctionNode, verdict: Verdict, tree: CallTree
) -> list[dict[str, Any]]:
    """오염원 근거를 순위표가 쓸 모양으로 정리한다(§7 — 전역 read/write 구분).

    같은 대상을 여러 번 건드리면 접근 방향을 합친다. 지점 하나하나는 경계 판단에
    쓰이지 않으므로 위치는 담지 않는다.
    """
    accesses: dict[str, set[str]] = {usr: set() for usr in verdict.impurity_reasons}
    for use in node.state_uses:
        if use.target in accesses:
            accesses[use.target].add(use.access)

    reasons = []
    for usr in verdict.impurity_reasons:
        var = tree.state.get(usr)
        seen = accesses[usr]
        reasons.append(
            {
                "name": var.name if var else usr,
                # 관측된 방향을 합친다. `readwrite` 는 양쪽으로 편다.
                "read": bool(seen & {"read", "readwrite"}),
                "write": bool(seen & {"write", "readwrite"}),
                "addr": "addr" in seen,
                # 함수 내 static 은 밖에서 리셋할 방법이 없어 성격이 다르다.
                "static": bool(var and var.scope == "function_static"),
                # state 에 없는 대상은 기준을 적용할 수 없어 보수적으로 남은 것이다.
                "unknown": var is None,
            }
        )
    return reasons


# -------------------------------------------------------------------- 페이로드


def build_payload(tree: CallTree, analysis: Analysis) -> dict[str, Any]:
    """그림 한 장에 필요한 전부. 그 이상은 넣지 않는다.

    `analysis.nodes` 가 곧 가지치기 후 살아남은 집합이므로 도달 판정을 다시 하지
    않는다. 진입점과 노드가 서로 맞는지 확인하는 것은 호출하는 쪽(`cli`)의 몫이다.
    """
    entry = tree.meta.entry_point
    reachable = set(analysis.nodes)

    parent, depth, children = spanning_tree(tree, reachable, entry)

    # 전체 역방향 간선. 호버 하이라이트와 시뮬레이션은 배치용 트리가 아니라 이쪽을
    # 따라간다 — 오염은 모든 호출 간선으로 전파되기 때문이다.
    callers: dict[str, set[str]] = {usr: set() for usr in reachable}
    for usr in reachable:
        for callee in callees(tree.nodes[usr], reachable, tree):
            if callee != usr:
                callers[callee].add(usr)

    # 오염원이 서브트리 안에 몇 개 있는지. 접기 기본값(§5)과 "오염 경로만" 필터가
    # 이 값 하나로 결정된다. 판정 결과를 보고 정해지지만 **그리기 전에 확정되고**,
    # 화면 안의 시뮬레이션은 이 값을 다시 계산하지 않는다. 고쳤다고 가정하는 동안
    # 배치가 흔들리지 않는 것이 §8 이 요구한 것이다.
    subtree: dict[str, int] = {}
    impure_below: dict[str, int] = {}
    for usr in _post_order(children, entry):
        subtree[usr] = sum(1 + subtree[child] for child in children[usr])
        impure_below[usr] = sum(impure_below[child] for child in children[usr]) + (
            1 if analysis.nodes[usr].is_impure else 0
        )

    # USR 순 인덱스. 이름이 바뀌어도 순서가 흔들리지 않아 파일 diff 가 안정적이다.
    # 배치 순서는 `children` 이 따로 정하므로 이 순서와 무관하다.
    order = sorted(reachable)
    index = {usr: i for i, usr in enumerate(order)}
    prefix = common_prefix([tree.nodes[usr].name for usr in order])

    nodes = []
    for usr in order:
        node = tree.nodes[usr]
        verdict = analysis.nodes[usr]
        state = (
            "impure"
            if verdict.is_impure
            else "contaminated"
            if verdict.is_contaminated
            else "clean"
        )
        nodes.append(
            {
                "usr": usr,
                "name": node.name,
                "short": node.name[len(prefix) :] if prefix else node.name,
                "file": node.loc.file,
                "line": node.loc.line,
                "depth": depth[usr],
                "state": state,
                # 지금 당장 테스트를 붙일 수 있는 자리. 깨끗함과는 다른 처리를
                # 받아야 한다(§3 의 예외).
                "boundary": verdict.is_clean_subtree_root,
                "degree": verdict.contamination_degree,
                "children": [index[child] for child in children[usr]],
                "callers": sorted(index[caller] for caller in callers[usr]),
                "subtree": subtree[usr],
                "impure_below": impure_below[usr],
                # 아래를 알 수 없는 노드. 깨끗해 보여도 경계로 쓸 수 없다.
                "unresolved": bool(node.unresolved_calls),
                # 정의를 보지 못해 깨끗한 리프로 취급된 노드.
                "declaration": node.kind == "declaration",
                "reasons": reasons_of(node, verdict, tree),
            }
        )

    # 배치용 트리에 들어가지 못한 호출 간선. 전부 그리면 선이 엉켜 오염 경로를
    # 못 따라가므로(§10), 오염이 실제로 타고 올라오는 간선만 남기고 나머지는
    # 개수만 센다.
    cross: list[list[int]] = []
    omitted = 0
    for usr in order:
        for callee in callees(tree.nodes[usr], reachable, tree):
            if parent[callee] == usr or callee == usr:
                continue
            verdict = analysis.nodes[callee]
            if verdict.is_impure or verdict.is_contaminated:
                cross.append([index[usr], index[callee]])
            else:
                omitted += 1

    return {
        "entry": index[entry],
        "prefix": prefix,
        "source": analysis.source,
        "criteria": analysis.criteria.describe(),
        # 현재 시각이 아니라 추출 시각이다. 같은 입력이면 같은 파일이 나와야 한다.
        "generated_at": tree.meta.generated_at,
        "total": len(tree.nodes),
        "nodes": nodes,
        "cross": cross,
        "omitted_edges": omitted,
    }

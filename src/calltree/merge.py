"""USR 키 병합.

TU 마다 파싱한 결과를 합치는 규칙은 하나뿐이다: **정의가 선언을 덮어쓴다**.
헤더에 정의된 `inline` / `static inline` 함수는 TU 마다 중복 등장하지만 USR 이
같으므로 여기서 자연히 dedupe 된다.
"""

from __future__ import annotations

from calltree.model import FunctionNode, StateVar


def merge_node(nodes: dict[str, FunctionNode], node: FunctionNode) -> FunctionNode:
    """`node` 를 병합하고 살아남은 노드를 돌려준다.

    반환값이 `node` 와 다르면 기존 노드가 이겼다는 뜻이다. 호출자는 이걸 보고
    본문을 두 번 훑는 낭비(같은 inline 함수의 중복 전개)를 피할 수 있다.
    """
    existing = nodes.get(node.usr)
    if existing is None:
        nodes[node.usr] = node
        return node

    if existing.is_definition:
        return existing
    if node.is_definition:
        nodes[node.usr] = node
        return node

    # 둘 다 선언이면 먼저 본 쪽을 유지하되, 비어 있는 시그니처는 채워 넣는다.
    if existing.return_type is None and node.return_type is not None:
        existing.return_type = node.return_type
        existing.params = list(node.params)
    return existing


def merge_state_var(state: dict[str, StateVar], var: StateVar) -> StateVar:
    """상태 변수를 병합하고 살아남은 항목을 돌려준다.

    `extern int g_flag;` (헤더의 선언) 과 `int g_flag;` (정의) 는 USR 이 같다.
    정의 쪽 위치를 남겨야 `loc` 이 실제 정의를 가리킨다.
    """
    existing = state.get(var.usr)
    if existing is None:
        state[var.usr] = var
        return var

    if existing.is_definition:
        return existing
    if var.is_definition:
        state[var.usr] = var
        return var
    return existing


def merge_nodes(dst: dict[str, FunctionNode], src: dict[str, FunctionNode]) -> None:
    for node in src.values():
        merge_node(dst, node)


def merge_state(dst: dict[str, StateVar], src: dict[str, StateVar]) -> None:
    for var in src.values():
        merge_state_var(dst, var)

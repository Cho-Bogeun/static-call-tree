"""`calltree.json`(사실)을 입력으로 `analysis.json`(판단)을 만든다.

    소스코드 ──libclang──> calltree.json ──분석──> analysis.json
                            (사실)                  (판단)

판정 기준은 확정된 것이 아니라 분석을 진행하면서 바뀐다. 그래서 이 단계는 추출과
분리되어 있고, libclang 도 소스도 건드리지 않는다. `calltree.json` 하나로 기준별
`analysis.json` 을 여러 벌 만들어 비교하는 것이 목적이다.

처리 순서는 참조 문서 §5 그대로다.

1. 가지치기 — `entry_point` 에서 BFS. `calltree.json` 에는 TU 전체가 들어 있다.
2. 오염원 판정 — 노드 로컬. 그래프를 보지 않으므로 기준만 바꿔 다시 돌릴 수 있다.
3. 오염도 — 엣지를 뒤집고 각 오염원에서 역방향 BFS. 방문 집합의 크기.
4. 오염됨 / 깨끗한 서브트리 루트 — 부모 상태와 대조해 경계를 확정.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from calltree.model import (
    Access,
    Analysis,
    CallTree,
    Criteria,
    FunctionNode,
    StateUse,
    StateVar,
    Verdict,
)


class EntryNotFound(KeyError):
    """`meta.entry_point` 가 `nodes` 에 없다. 가지치기를 시작할 수 없다."""


@dataclass
class ManualSite:
    """`addr_as: "manual"` 에서 눈으로 확인해야 하는 주소 취득 지점."""

    usr: str
    target: str
    file: str
    line: int


@dataclass
class AnalysisResult:
    """판정 결과와, 결과 파일에는 담기지 않는 확인 대상들.

    `analysis.schema.json` 은 `additionalProperties: false` 이므로 노드마다 메모를
    붙일 자리가 없다. 눈으로 확인할 것들은 파일이 아니라 여기로 나온다.
    """

    analysis: Analysis
    entry_point: str
    #: 가지치기 후 남은 USR (정렬)
    reachable: list[str] = field(default_factory=list)
    #: 가지치기 전 노드 수. 얼마나 잘려나갔는지 보기 위한 것이다.
    total: int = 0
    #: 정의를 보지 못한 노드. 깨끗한 리프로 취급했으므로 눈으로 확인한다(§6).
    declarations: list[str] = field(default_factory=list)
    #: `unresolved_calls` 가 있어 그 아래를 알 수 없는 노드
    unresolved: list[str] = field(default_factory=list)
    manual_sites: list[ManualSite] = field(default_factory=list)
    #: `calls` 가 가리키는데 `nodes` 에 없는 USR. 정상적인 추출에서는 비어 있다.
    missing_callees: list[str] = field(default_factory=list)
    #: `state_uses` 가 가리키는데 `state` 에 없는 USR. 기준을 적용할 수 없으므로
    #: 보수적으로 오염원 근거에 넣었다.
    unknown_state: list[str] = field(default_factory=list)

    @property
    def impure(self) -> list[Verdict]:
        """오염원. 오염도 내림차순 — 수정 대상 우선순위 그대로다(§7-1)."""
        return sorted(
            (v for v in self.analysis.nodes.values() if v.is_impure),
            key=lambda v: (-v.contamination_degree, v.usr),
        )

    @property
    def contaminated(self) -> list[Verdict]:
        return sorted(
            (v for v in self.analysis.nodes.values() if v.is_contaminated),
            key=lambda v: v.usr,
        )

    @property
    def clean_subtree_roots(self) -> list[Verdict]:
        """지금 당장 비용 0 으로 테스트를 붙일 수 있는 경계(§7-2)."""
        return sorted(
            (v for v in self.analysis.nodes.values() if v.is_clean_subtree_root),
            key=lambda v: v.usr,
        )

    def summary(self, tree: CallTree) -> str:
        """사람이 읽는 요약. 참조 문서 §7 의 순서를 그대로 따른다."""

        def label(usr: str) -> str:
            node = tree.nodes.get(usr)
            if node is None:
                return usr
            return f"{node.name}  ({node.loc.file}:{node.loc.line})"

        entry = tree.nodes.get(self.entry_point)
        lines = [
            f"진입점   : {entry.name if entry else self.entry_point}",
            f"도달 노드: {len(self.reachable)}개 (전체 {self.total}개 중)",
            f"기준     : {self.analysis.criteria.describe()}",
            "",
        ]

        impure = self.impure
        if impure:
            lines.append(f"오염원 {len(impure)}개 — 오염도 내림차순, 수정 대상 우선순위")
            for verdict in impure:
                reasons = ", ".join(
                    tree.state[usr].name if usr in tree.state else usr
                    for usr in verdict.impurity_reasons
                )
                lines.append(
                    f"  {verdict.contamination_degree:>4}  {label(verdict.usr)}"
                )
                lines.append(f"        {reasons}")
            lines.append(f"오염됨 {len(self.contaminated)}개")
        else:
            lines.append("오염원 없음. 진입점에 바로 테스트를 붙이면 된다.")
        lines.append("")

        roots = self.clean_subtree_roots
        lines.append(f"깨끗한 서브트리 루트 {len(roots)}개 — 지금 붙일 수 있는 테스트 경계")
        for verdict in roots:
            lines.append(f"  {label(verdict.usr)}")

        manual: list[str] = []
        if self.declarations:
            manual.append(
                f"  정의를 보지 못한 노드 {len(self.declarations)}개 "
                f"(깨끗한 리프로 취급): "
                + ", ".join(
                    tree.nodes[usr].name for usr in self.declarations if usr in tree.nodes
                )
            )
        if self.unresolved:
            manual.append(
                f"  서브트리가 불완전한 노드 {len(self.unresolved)}개: "
                + ", ".join(
                    tree.nodes[usr].name for usr in self.unresolved if usr in tree.nodes
                )
            )
        if self.manual_sites:
            manual.append(f"  주소 취득 지점 {len(self.manual_sites)}개:")
            for site in self.manual_sites:
                name = tree.state[site.target].name if site.target in tree.state else site.target
                manual.append(f"    {site.file}:{site.line}  &{name}")
        if self.missing_callees:
            manual.append(f"  nodes 에 없는 콜리 {len(self.missing_callees)}개")
        if self.unknown_state:
            manual.append(
                f"  state 에 없는 접근 대상 {len(self.unknown_state)}개 "
                f"(기준을 적용할 수 없어 오염원 근거로 셈)"
            )
        if manual:
            lines.extend(["", "눈으로 확인할 것"])
            lines.extend(manual)

        return "\n".join(lines)


# ------------------------------------------------------------------ 1. 가지치기


def reachable_from(tree: CallTree, entry: str) -> set[str]:
    """`entry` 에서 콜 엣지로 도달 가능한 노드. 순환은 visited 로 처리된다."""
    if entry not in tree.nodes:
        raise EntryNotFound(f"진입점 USR 이 nodes 에 없다: {entry}")

    seen = {entry}
    queue = deque([entry])
    while queue:
        node = tree.nodes[queue.popleft()]
        for call in node.calls:
            if call.callee in tree.nodes and call.callee not in seen:
                seen.add(call.callee)
                queue.append(call.callee)
    return seen


# --------------------------------------------------------------- 2. 오염원 판정


def effective_access(use: StateUse, criteria: Criteria) -> Access:
    """`addr` 을 기준이 정한 방향으로 바꾼다. 나머지는 관측된 그대로다.

    `&g_state` 를 넘긴 지점에서는 읽기인지 쓰기인지 정적으로 판정할 수 없다.
    `manual` 은 방향을 정하지 않고 보수적으로 두되 확인 대상으로 따로 뽑는 값이므로,
    여기서는 `readwrite` 와 같이 취급한다.
    """
    if use.access != "addr":
        return use.access
    if criteria.addr_as == "manual":
        return "readwrite"
    return criteria.addr_as


def counts_as_impurity(use: StateUse, var: StateVar | None, criteria: Criteria) -> bool:
    """이 접근이 오염원 근거가 되는가. 노드가 아니라 접근 하나에 대한 판단이다.

    참조 문서 §4 의 정의는 "`state_uses` 중 `criteria` 를 통과한 항목"이므로, 통과
    여부를 정하는 것은 `criteria` 뿐이다. 기준은 대상(`exclude_const`,
    `include_function_static`)을 먼저 보고 방향(`const_read`)을 나중에 본다.

    방향을 `addr_as` 로 확정한 뒤 `const_read` 를 적용하는 순서가 중요하다. 이 순서
    덕분에 §3 표의 `read` 는 낙관적(주소만 넘긴 접근이 빠져 오염원이 최소), `readwrite`
    는 보수적이 된다. `const_read` 가 꺼져 있으면 방향을 보지 않으므로
    `read`/`write`/`readwrite` 가 같은 결과를 낸다.
    """
    if var is not None:
        if criteria.exclude_const and var.is_const:
            return False
        if not criteria.include_function_static and var.scope == "function_static":
            return False
    # var 가 None 이면 대상 기준을 적용할 근거가 없다. 놓치는 쪽이 과잉 계상보다
    # 비싸므로 남겨 두고, 방향 기준만 마저 본다.
    if criteria.const_read and effective_access(use, criteria) == "read":
        return False
    return True


def impurity_reasons(
    node: FunctionNode, state: dict[str, StateVar], criteria: Criteria
) -> list[str]:
    """이 노드를 오염원으로 만든 state USR 목록. 중복은 제거하고 정렬한다.

    노드 로컬 판단이며 그래프를 보지 않는다. 후손이 오염되어 있는 것은 여기에 영향을
    주지 않는다.
    """
    reasons = {
        use.target
        for use in node.state_uses
        if counts_as_impurity(use, state.get(use.target), criteria)
    }
    return sorted(reasons)


# ------------------------------------------------------------------- 그래프 유틸


def _reverse(edges: dict[str, set[str]]) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {usr: set() for usr in edges}
    for source, targets in edges.items():
        for target in targets:
            reverse[target].add(source)
    return reverse


def _reach(edges: dict[str, set[str]], starts: Iterable[str]) -> set[str]:
    """`starts` 자신을 포함해 도달 가능한 집합. 순환은 visited 로 처리된다."""
    seen = set(starts)
    queue = deque(seen)
    while queue:
        for neighbour in edges[queue.popleft()]:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


# ---------------------------------------------------------------------- 분석


def analyze(
    tree: CallTree,
    criteria: Criteria | None = None,
    source: str = "calltree.json",
) -> AnalysisResult:
    criteria = criteria or Criteria()
    entry = tree.meta.entry_point
    reachable = reachable_from(tree, entry)

    verdicts = {usr: Verdict(usr=usr) for usr in reachable}
    result = AnalysisResult(
        analysis=Analysis(source=source, criteria=criteria, nodes=verdicts),
        entry_point=entry,
        reachable=sorted(reachable),
        total=len(tree.nodes),
    )

    # 2. 오염원 판정 — 노드 로컬.
    missing_callees: set[str] = set()
    unknown_state: set[str] = set()
    for usr in reachable:
        node = tree.nodes[usr]
        reasons = impurity_reasons(node, tree.state, criteria)
        if reasons:
            verdicts[usr].is_impure = True
            verdicts[usr].impurity_reasons = reasons

        if node.kind == "declaration":
            result.declarations.append(usr)
        if node.unresolved_calls:
            result.unresolved.append(usr)
        for call in node.calls:
            if call.callee not in tree.nodes:
                missing_callees.add(call.callee)
        for use in node.state_uses:
            var = tree.state.get(use.target)
            if var is None:
                unknown_state.add(use.target)
            # 기준에 걸려 떨어진 접근은 확인할 것도 없다. 남은 것만 뽑는다.
            if (
                use.access == "addr"
                and criteria.addr_as == "manual"
                and counts_as_impurity(use, var, criteria)
            ):
                result.manual_sites.append(
                    ManualSite(
                        usr=usr,
                        target=use.target,
                        file=use.loc.file,
                        line=use.loc.line,
                    )
                )

    result.declarations.sort()
    result.unresolved.sort()
    result.manual_sites.sort(key=lambda site: (site.file, site.line, site.target))
    result.missing_callees = sorted(missing_callees)
    result.unknown_state = sorted(unknown_state)

    edges = {
        usr: {
            call.callee for call in tree.nodes[usr].calls if call.callee in reachable
        }
        for usr in reachable
    }
    reverse = _reverse(edges)

    # 3. 오염도 — 각 오염원에서 역방향 BFS. 같은 콜리를 여러 번 호출해도 조상은 한
    #    번만 센다(집합 크기).
    has_impure_descendant: set[str] = set()
    for usr in reachable:
        if not verdicts[usr].is_impure:
            continue
        ancestors = _reach(reverse, [usr])
        verdicts[usr].contamination_degree = len(ancestors)
        # 조상은 이 오염원을 후손으로 가진다. 자기 자신은 후손이 아니므로 뺀다.
        has_impure_descendant |= ancestors - {usr}

    # 4-a. 오염됨. 오염원인 노드는 false 로 둔다 — 자기 자신이 원인인 노드를 부수
    #      피해로 세면 두 집합의 구분이 흐려진다. 스키마가 강제하지 않으므로 여기서
    #      지킨다.
    for usr in reachable:
        verdict = verdicts[usr]
        verdict.is_contaminated = not verdict.is_impure and usr in has_impure_descendant

    # 4-b. 깨끗한 서브트리 루트. 함수 포인터 호출이 서브트리 안에 있으면 그 아래를
    #      알 수 없으므로, unresolved 노드와 그 조상은 모두 제외한다.
    blocked_by_unresolved = _reach(reverse, result.unresolved)
    for usr in reachable:
        verdict = verdicts[usr]
        if verdict.is_impure or usr in has_impure_descendant:
            continue
        if usr in blocked_by_unresolved:
            continue
        # 부모가 오염되어 있다는 것은 거기서 깨끗한 영역의 경계가 끝난다는 뜻이다.
        # 이 조건을 빼면 모든 리프가 루트로 잡힌다.
        if usr == entry or any(
            verdicts[parent].is_impure or verdicts[parent].is_contaminated
            for parent in reverse[usr]
        ):
            verdict.is_clean_subtree_root = True

    return result

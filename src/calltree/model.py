"""`calltree.schema.json` 과 `analysis.schema.json` 에 1:1 대응하는 데이터 모델.

직렬화 규칙은 스키마가 정한다. 두 스키마 모두 `additionalProperties: false` 이므로
`to_dict()` 는 스키마에 없는 필드를 절대 내보내지 않는다.

두 파일은 같은 USR 을 키로 쓰므로 조인이 자명하다. 사실(`CallTree`)과
판단(`Analysis`)은 파일이 갈리는 만큼 타입도 갈라 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 1
#: 2 = `criteria.const_read` 추가. 기준이 하나 늘면 올린다.
ANALYSIS_SCHEMA_VERSION = 2

Linkage = Literal["external", "internal"]
NodeKind = Literal["definition", "declaration"]
Scope = Literal["file_global", "function_static"]
Access = Literal["read", "write", "readwrite", "addr"]
UnresolvedReason = Literal["function_pointer", "inline_asm", "unknown"]
AddrAs = Literal["read", "write", "readwrite", "manual"]


@dataclass(frozen=True)
class Loc:
    file: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Loc:
        return cls(file=data["file"], line=data["line"])


@dataclass(frozen=True)
class Param:
    name: str
    type: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Param:
        return cls(name=data["name"], type=data["type"])


@dataclass(frozen=True)
class Call:
    """해석된 직접 호출. 같은 콜리를 여러 번 부르면 각각 기록된다."""

    callee: str
    loc: Loc

    def to_dict(self) -> dict[str, Any]:
        return {"callee": self.callee, "loc": self.loc.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Call:
        return cls(callee=data["callee"], loc=Loc.from_dict(data["loc"]))


@dataclass(frozen=True)
class StateUse:
    target: str
    access: Access
    loc: Loc

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "access": self.access, "loc": self.loc.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateUse:
        return cls(
            target=data["target"], access=data["access"], loc=Loc.from_dict(data["loc"])
        )


@dataclass(frozen=True)
class UnresolvedCall:
    """콜리를 특정할 수 없는 호출 지점. 비어있지 않으면 콜트리가 불완전하다."""

    loc: Loc
    expr: str
    reason: UnresolvedReason

    def to_dict(self) -> dict[str, Any]:
        return {"loc": self.loc.to_dict(), "expr": self.expr, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnresolvedCall:
        return cls(
            loc=Loc.from_dict(data["loc"]), expr=data["expr"], reason=data["reason"]
        )


@dataclass
class FunctionNode:
    """`nodes` 의 한 항목. `usr` 은 맵의 키이므로 직렬화하지 않는다."""

    usr: str
    name: str
    linkage: Linkage
    kind: NodeKind
    loc: Loc
    return_type: str | None = None
    params: list[Param] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    state_uses: list[StateUse] = field(default_factory=list)
    unresolved_calls: list[UnresolvedCall] = field(default_factory=list)

    @property
    def is_definition(self) -> bool:
        return self.kind == "definition"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "linkage": self.linkage,
            "kind": self.kind,
            "loc": self.loc.to_dict(),
        }
        if self.return_type is not None:
            data["return_type"] = self.return_type
            data["params"] = [p.to_dict() for p in self.params]
        data["calls"] = [c.to_dict() for c in self.calls]
        data["state_uses"] = [s.to_dict() for s in self.state_uses]
        data["unresolved_calls"] = [u.to_dict() for u in self.unresolved_calls]
        return data

    @classmethod
    def from_dict(cls, usr: str, data: dict[str, Any]) -> FunctionNode:
        return cls(
            usr=usr,
            name=data["name"],
            linkage=data["linkage"],
            kind=data["kind"],
            loc=Loc.from_dict(data["loc"]),
            return_type=data.get("return_type"),
            params=[Param.from_dict(p) for p in data.get("params", [])],
            calls=[Call.from_dict(c) for c in data.get("calls", [])],
            state_uses=[StateUse.from_dict(s) for s in data.get("state_uses", [])],
            unresolved_calls=[
                UnresolvedCall.from_dict(u) for u in data.get("unresolved_calls", [])
            ],
        )


@dataclass
class StateVar:
    """`state` 의 한 항목. 전역과 함수 내 static 을 같은 테이블에 담는다."""

    usr: str
    name: str
    type: str
    scope: Scope
    linkage: Linkage
    is_const: bool
    loc: Loc
    owner: str | None = None
    #: 병합 전용 메타데이터. 정의(초기화/tentative definition)를 본 TU 인지 여부이며,
    #: 스키마에 없는 필드이므로 직렬화하지 않는다.
    is_definition: bool = True

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "scope": self.scope,
            "linkage": self.linkage,
            "is_const": self.is_const,
            "loc": self.loc.to_dict(),
        }
        if self.owner is not None:
            data["owner"] = self.owner
        return data

    @classmethod
    def from_dict(cls, usr: str, data: dict[str, Any]) -> StateVar:
        return cls(
            usr=usr,
            name=data["name"],
            type=data["type"],
            scope=data["scope"],
            linkage=data["linkage"],
            is_const=data["is_const"],
            loc=Loc.from_dict(data["loc"]),
            owner=data.get("owner"),
        )


@dataclass
class Meta:
    entry_point: str
    compile_commands: str
    clang_version: str
    generated_at: str
    tu_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_point": self.entry_point,
            "compile_commands": self.compile_commands,
            "clang_version": self.clang_version,
            "generated_at": self.generated_at,
            "tu_count": self.tu_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Meta:
        return cls(
            entry_point=data["entry_point"],
            compile_commands=data["compile_commands"],
            clang_version=data["clang_version"],
            generated_at=data["generated_at"],
            tu_count=data["tu_count"],
        )


@dataclass
class CallTree:
    """추출 결과 전체. 트리가 아니라 USR 을 키로 하는 플랫 맵이다."""

    meta: Meta
    nodes: dict[str, FunctionNode] = field(default_factory=dict)
    state: dict[str, StateVar] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "meta": self.meta.to_dict(),
            # USR 정렬로 스냅샷 diff 를 안정화한다.
            "nodes": {usr: self.nodes[usr].to_dict() for usr in sorted(self.nodes)},
            "state": {usr: self.state[usr].to_dict() for usr in sorted(self.state)},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallTree:
        return cls(
            meta=Meta.from_dict(data["meta"]),
            nodes={
                usr: FunctionNode.from_dict(usr, node)
                for usr, node in data["nodes"].items()
            },
            state={
                usr: StateVar.from_dict(usr, var) for usr, var in data["state"].items()
            },
        )


# --------------------------------------------------------------- analysis.json


@dataclass(frozen=True)
class Criteria:
    """오염 판정 기준. 결과 파일에 반드시 기록한다.

    기준을 바꿔가며 여러 번 돌릴 때 어떤 결과가 어떤 기준에서 나왔는지 구분할 수
    없으면 비교 자체가 무의미해진다.
    """

    #: `const` 상태 접근을 오염원 근거에서 뺀다. const 룩업 테이블이 잡히면 오염도가
    #: 부풀어 우선순위 판단이 왜곡된다.
    exclude_const: bool = True
    #: 함수 내 `static` 을 포함한다. 스코프만 좁을 뿐 성격이 전역과 같고, 외부에서
    #: 리셋할 방법이 없어 테스트 관점에서는 오히려 더 나쁘다.
    include_function_static: bool = True
    #: 주소만 취한 접근(`addr`)을 무엇으로 간주할지. 놓치는 쪽이 과잉 계상보다
    #: 비싸므로 보수적인 `readwrite` 가 기본이다.
    addr_as: AddrAs = "readwrite"
    #: 읽기 전용 접근을 상수 취급해 오염원 근거에서 뺀다. `addr_as` 가 방향을 정한
    #: 뒤에 적용되므로, 꺼 두면 `read`/`write`/`readwrite` 가 같은 결과를 낸다.
    #: 읽기도 숨은 상태에 대한 의존이라 기본값은 세는 쪽(`false`)이다.
    const_read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "exclude_const": self.exclude_const,
            "include_function_static": self.include_function_static,
            "addr_as": self.addr_as,
            "const_read": self.const_read,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Criteria:
        return cls(
            exclude_const=data["exclude_const"],
            include_function_static=data["include_function_static"],
            addr_as=data["addr_as"],
            const_read=data["const_read"],
        )

    def describe(self) -> str:
        return (
            f"exclude_const={str(self.exclude_const).lower()} "
            f"include_function_static={str(self.include_function_static).lower()} "
            f"addr_as={self.addr_as} "
            f"const_read={str(self.const_read).lower()}"
        )


@dataclass
class Verdict:
    """`nodes` 의 한 항목. `usr` 은 맵의 키이므로 직렬화하지 않는다."""

    usr: str
    #: 오염원. 자기 자신이 직접 숨은 상태에 접근하는 노드이며 실제 수정 대상이다.
    is_impure: bool = False
    impurity_reasons: list[str] = field(default_factory=list)
    #: 오염됨. 자신은 오염원이 아니지만 후손 중에 오염원이 있다.
    is_contaminated: bool = False
    contamination_degree: int = 0
    is_clean_subtree_root: bool = False
    #: 역방향 도달성을 visited 집합으로 계산하면 순환은 자동으로 처리되므로 축약할
    #: 일이 없다. 나중에 최적화가 필요해질 때 형식을 바꾸지 않으려고 남겨 둔다.
    scc_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_impure": self.is_impure,
            "impurity_reasons": list(self.impurity_reasons),
            "is_contaminated": self.is_contaminated,
            "contamination_degree": self.contamination_degree,
            "is_clean_subtree_root": self.is_clean_subtree_root,
            "scc_id": self.scc_id,
        }

    @classmethod
    def from_dict(cls, usr: str, data: dict[str, Any]) -> Verdict:
        return cls(
            usr=usr,
            is_impure=data["is_impure"],
            impurity_reasons=list(data["impurity_reasons"]),
            is_contaminated=data["is_contaminated"],
            contamination_degree=data["contamination_degree"],
            is_clean_subtree_root=data["is_clean_subtree_root"],
            scc_id=data["scc_id"],
        )


@dataclass
class Analysis:
    """판정 결과 전체. `CallTree` 와 같은 USR 키를 쓰는 파생 파일이다."""

    source: str
    criteria: Criteria = field(default_factory=Criteria)
    nodes: dict[str, Verdict] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "source": self.source,
            "criteria": self.criteria.to_dict(),
            # USR 정렬로 스냅샷 diff 를 안정화한다.
            "nodes": {usr: self.nodes[usr].to_dict() for usr in sorted(self.nodes)},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Analysis:
        return cls(
            source=data["source"],
            criteria=Criteria.from_dict(data["criteria"]),
            nodes={
                usr: Verdict.from_dict(usr, verdict)
                for usr, verdict in data["nodes"].items()
            },
        )

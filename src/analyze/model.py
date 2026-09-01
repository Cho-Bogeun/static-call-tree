"""analysis.schema.json 에 1:1 대응하는 데이터 모델.

직렬화 규칙은 스키마가 정한다. 스키마가 `additionalProperties: false` 이므로
`to_dict()` 는 스키마에 없는 필드를 절대 내보내지 않는다. 노드마다 메모를 붙일
자리도 없으므로, 눈으로 확인할 것들은 파일이 아니라 `contamination.AnalysisResult`
로 나간다.

추출 결과의 모델은 `calltree.model` 에 있다. 이 모듈은 그쪽을 참조하지 않는다 —
판정 결과는 USR 키만 공유할 뿐 사실을 다시 담지 않기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: 2 = `criteria.const_read` 추가. 기준이 하나 늘면 올린다.
ANALYSIS_SCHEMA_VERSION = 2

AddrAs = Literal["read", "write", "readwrite", "manual"]


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

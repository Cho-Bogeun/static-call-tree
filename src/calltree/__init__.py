"""정적 콜트리 추출기.

`calltree-extraction-schema.md` 의 원칙을 그대로 구현한다. 추출기는 관측 가능한
사실만 기록하고, 오염 판정 같은 해석은 `analyze` 패키지(분석 단계)의 몫이다.
"""

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

__version__ = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "Call",
    "CallTree",
    "FunctionNode",
    "Loc",
    "Meta",
    "Param",
    "StateUse",
    "StateVar",
    "UnresolvedCall",
    "__version__",
]

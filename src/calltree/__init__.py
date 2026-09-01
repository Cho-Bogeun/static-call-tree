"""정적 콜트리 추출기와 오염 분석기.

    소스코드 ──libclang──> calltree.json ──분석──> analysis.json
                            (사실)                  (판단)

`calltree-extraction-schema.md` 의 원칙을 그대로 구현한 추출기는 관측 가능한 사실만
기록한다. 오염 판정은 `contamination-analysis.md` 를 구현한 별도 단계이며, 추출
결과를 입력으로 받을 뿐 소스도 libclang 도 건드리지 않는다. 기준이 바뀌어도 재파싱이
필요 없는 이유가 여기에 있다.
"""

from calltree.model import (
    ANALYSIS_SCHEMA_VERSION,
    SCHEMA_VERSION,
    Analysis,
    Call,
    CallTree,
    Criteria,
    FunctionNode,
    Loc,
    Meta,
    Param,
    StateUse,
    StateVar,
    UnresolvedCall,
    Verdict,
)

__version__ = "0.1.0"

__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "Analysis",
    "Call",
    "CallTree",
    "Criteria",
    "FunctionNode",
    "Loc",
    "Meta",
    "Param",
    "StateUse",
    "StateVar",
    "UnresolvedCall",
    "Verdict",
    "__version__",
]

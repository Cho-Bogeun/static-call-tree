"""오염 분석기.

    소스코드 ──libclang──> calltree.json ──분석──> analysis.json
                            (사실)                  (판단)

`contamination-analysis.md` 를 구현한다. 추출 결과를 입력으로 받을 뿐 소스도
libclang 도 건드리지 않으므로, 판정 기준이 바뀌어도 재파싱이 필요 없다. 기준별
`analysis.json` 을 여러 벌 만들어 비교하는 것이 이 단계의 목적이다.

패키지가 갈린 것도 같은 이유다. `calltree` 는 사실만 기록하고, 판단은 전부 이쪽에
있다. 의존은 한 방향이다 — `analyze` 가 `calltree.model` 을 읽고, 그 반대는 없다.
"""

from analyze.contamination import (
    AnalysisResult,
    EntryNotFound,
    ManualSite,
    analyze,
    counts_as_impurity,
    effective_access,
    impurity_reasons,
    reachable_from,
)
from analyze.model import (
    ANALYSIS_SCHEMA_VERSION,
    AddrAs,
    Analysis,
    Criteria,
    Verdict,
)

__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "AddrAs",
    "Analysis",
    "AnalysisResult",
    "Criteria",
    "EntryNotFound",
    "ManualSite",
    "Verdict",
    "analyze",
    "counts_as_impurity",
    "effective_access",
    "impurity_reasons",
    "reachable_from",
]

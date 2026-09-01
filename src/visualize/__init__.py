"""오염도 시각화.

    calltree.json + analysis.json ──그림──> contamination.html
       (사실)         (판단)                    (읽는 법)

`시각화-원칙.md` 를 구현한다. 그림이 답해야 하는 질문은 하나다 — **테스트 경계를
어디에 그을 것인가.** 진입점을 그대로 쓸지, 한 층 내릴지, 여러 서브트리 루트를
각각 경계로 삼을지. 이 판단에 기여하지 않는 정보는 그리지 않는다.

의존은 여기서도 한 방향이다. `visualize` 가 `calltree.model` 과 `analyze.model` 을
읽고, 그 반대는 없다. 판정 기준을 바꾸든 추출기를 고치든 이 패키지는 조인 키(USR)
하나만 그대로면 된다.

정적인 색칠 그림은 Graphviz 로도 충분하다. HTML 로 내는 값은 §6 하나에 있다 —
*"이 세 개를 고치면 진입점이 깨끗해지는가"* 에 즉답하는 시뮬레이션.
"""

from visualize.payload import build_payload, common_prefix, spanning_tree
from visualize.render import render

__all__ = [
    "build_payload",
    "common_prefix",
    "render",
    "spanning_tree",
]

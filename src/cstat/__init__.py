"""두 단계를 한 명령으로 묶는 진입점.

    소스코드 ──cstat calltree──> calltree.json ──cstat analyze──> analysis.json
                                  (사실)                           (판단)

`calltree` 와 `analyze` 는 서로를 모른다. 각자 인자 정의와 실행만 내놓고, 명령
이름을 붙여 하나의 파서로 조립하는 것은 이쪽 몫이다. 의존이 여기로만 모이므로
두 패키지 사이는 여전히 단방향이다.
"""

#: 배포 버전은 pyproject 와 calltree 가 들고 있다. 여기서 또 적지 않는다.
from calltree import __version__

__all__ = ["__version__"]

"""실행 전 점검.

버전 대조만으로는 부족하다. 바인딩이 바뀌면 같은 코드에서 관측되는 사실이 조용히
달라질 수 있고, 그 결과는 "성공했지만 틀린 콜트리"다. 그래서 작은 C 조각을 실제로
훑어서 우리가 의존하는 관측이 그대로 나오는지 확인한다.

여기서 하나라도 어긋나면 아무 것도 추출하지 않고 즉시 멈춘다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from calltree.libclang_loader import (
    INSTALL_HELP,
    LibclangUnavailable,
    binding_version,
    clang_version,
    require,
)

SMOKE_NAME = "calltree_preflight.c"

#: 추출기가 의존하는 관측을 한 번에 건드리는 최소 코드.
#: static 전역, 함수 내 static, 해석되는 호출, 정의 없는 리프, 토큰 기반 연산자 판정,
#: 그리고 빌트인 헤더가 실제로 닿는지.
#:
#: `#include <stddef.h>` 는 취향이 아니라 관문이다. PyPI `libclang` 휠처럼 clang
#: 리소스 디렉터리(빌트인 헤더)가 없는 파서에서는 `stddef.h` 를 못 찾고, 그러면
#: `NULL` 이 미정의 식별자가 된다. 이때 clang 의 에러 복구는 **그 식별자를 인자로 쓰는
#: 호출식을 AST 에서 통째로 지운다.** 진단은 "헤더를 못 찾았다"인데 실제로 사라지는
#: 것은 콜 엣지다. 아래 `smoke_leaf(v, NULL)` 한 줄 덕에 기존 콜 엣지 검사가 곧
#: "빌트인 헤더가 있는가" 검사가 된다.
#:
#: `stddef.h` 는 프리스탠딩 헤더라 libc 유무와 무관하고, `unsaved_files` 로 파싱하므로
#: 디스크에 파일도 만들지 않는다.
SMOKE_SOURCE = """\
#include <stddef.h>

static int s_flag;

int smoke_leaf(int v, void *p);

int smoke_entry(int v)
{
    static int hits;

    hits++;
    s_flag = v;
    return smoke_leaf(v, NULL) + hits;
}
"""

_EXPECTED_ACCESSES = {("hits", "readwrite"), ("hits", "read"), ("s_flag", "write")}

#: 리소스 디렉터리가 없는 파서에서 나오는 진단. 이게 보이면 원인을 짚어 준다.
_MISSING_BUILTIN_HEADER = "'stddef.h' file not found"


@dataclass
class Report:
    """점검 결과. `problems` 가 비어 있으면 통과다."""

    clang_version: str = "unknown"
    binding: str = "unknown"
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        lines = [
            f"네이티브 libclang : {self.clang_version}",
            f"파이썬 바인딩     : {self.binding}",
        ]
        if self.ok:
            lines.append("스모크 파싱       : 통과")
        else:
            lines.append("스모크 파싱       : 실패")
            lines.extend(f"  - {problem}" for problem in self.problems)
        return "\n".join(lines)


def diagnose(
    library_file: str | None = None, library_path: str | None = None
) -> Report:
    """점검 결과를 보고서로 돌려준다. 로딩 자체가 안 되면 예외를 던진다."""
    require(library_file=library_file, library_path=library_path)
    binding = binding_version()
    report = Report(
        clang_version=clang_version(),
        binding=f"{binding[0]} {binding[1]}" if binding else "unknown",
    )
    report.problems = _smoke_problems()
    return report


def run(library_file: str | None = None, library_path: str | None = None) -> Report:
    """통과하면 보고서를, 아니면 `LibclangUnavailable` 을 던진다."""
    report = diagnose(library_file=library_file, library_path=library_path)
    if not report.ok:
        raise LibclangUnavailable(
            "libclang 은 로드되지만 관측 결과가 기대와 다르다. "
            "이 상태로 추출하면 틀린 콜트리가 나오므로 멈춘다.\n"
            + "\n".join(f"  - {problem}" for problem in report.problems)
            + f"\n\n{report.summary()}\n\n{INSTALL_HELP}"
        )
    return report


def _smoke_problems(extra_args: Sequence[str] = ()) -> list[str]:
    """스모크 조각을 훑고 기대와 다른 점을 모은다.

    `extra_args` 는 테스트가 깨진 파서를 흉내 내려고 쓴다(빌트인 헤더를 빼는
    `-nobuiltininc` 등). 실행 경로에서는 비어 있다.
    """
    from calltree.extract import TUExtractor  # 순환 임포트 회피

    problems: list[str] = []
    extractor = TUExtractor(root=Path.cwd())
    result = extractor.parse(
        SMOKE_NAME,
        args=["-std=c11", *extra_args],
        unsaved_files=[(SMOKE_NAME, SMOKE_SOURCE)],
    )

    if result.has_errors:
        problems.append(f"스모크 조각 파싱에 에러: {result.diagnostics[:3]}")
        if any(_MISSING_BUILTIN_HEADER in text for text in result.diagnostics):
            problems.append(
                "빌트인 헤더를 못 찾았다 — clang 리소스 디렉터리가 없는 파서다. "
                "PyPI `libclang` 휠이 대표적이다(.so 만 담고 헤더는 안 담는다). "
                "이대로 큰 코드베이스를 훑으면 NULL 을 쓰는 호출식이 AST 에서 사라져 "
                "콜트리가 조용히 잘린다."
            )

    entry = result.nodes.get("c:@F@smoke_entry")
    if entry is None:
        problems.append(
            "함수 노드를 못 만들었다 (USR c:@F@smoke_entry 없음). "
            f"관측된 노드: {sorted(result.nodes)}"
        )
        return problems  # 나머지 확인은 의미가 없다

    if entry.kind != "definition":
        problems.append(f"정의를 정의로 못 봤다: kind={entry.kind}")

    callees = [call.callee for call in entry.calls]
    if callees != ["c:@F@smoke_leaf"]:
        problems.append(f"콜 엣지가 기대와 다르다: {callees}")

    leaf = result.nodes.get("c:@F@smoke_leaf")
    if leaf is None or leaf.kind != "declaration":
        problems.append("정의 없는 함수를 declaration 리프로 못 잡았다")

    observed = {
        (result.state[use.target].name, use.access)
        for use in entry.state_uses
        if use.target in result.state
    }
    if observed != _EXPECTED_ACCESSES:
        problems.append(
            f"상태 접근 방향이 기대와 다르다: 기대 {sorted(_EXPECTED_ACCESSES)}, "
            f"관측 {sorted(observed)}"
        )

    hits = next((var for var in result.state.values() if var.name == "hits"), None)
    if hits is None or hits.scope != "function_static":
        problems.append("함수 내 static 을 function_static 으로 못 잡았다")
    elif hits.owner != "c:@F@smoke_entry":
        problems.append(f"함수 내 static 의 owner 가 다르다: {hits.owner}")

    s_flag = next((var for var in result.state.values() if var.name == "s_flag"), None)
    if s_flag is None or s_flag.linkage != "internal":
        problems.append("파일 스코프 static 의 linkage 를 internal 로 못 잡았다")

    return problems

"""`compile_commands.json` 읽기.

각 엔트리가 하나의 TU 다. 컴파일 명령을 그대로 libclang 에 넘기면 안 되고,
드라이버 전용 플래그(`-c`, `-o`, 의존성 생성)와 소스 파일 자체를 걷어내야 한다.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

#: 값을 하나 더 먹는 드라이버 플래그.
_FLAGS_WITH_VALUE = frozenset({"-o", "-MF", "-MT", "-MQ", "-MD", "-MMD"})

#: 값이 없는 드라이버 플래그.
_FLAGS_TO_DROP = frozenset({"-c", "-S", "-M", "-MM", "-MP", "-MG", "-pipe"})

#: `-MD`/`-MMD` 는 값을 안 받는 형태로도 쓰인다. 뒤 인자가 플래그면 값이 없는 것.
_OPTIONAL_VALUE = frozenset({"-MD", "-MMD"})


@dataclass(frozen=True)
class CompileCommand:
    directory: str
    file: str
    arguments: list[str]

    @property
    def abs_file(self) -> Path:
        path = Path(self.file)
        return path if path.is_absolute() else Path(self.directory) / path

    def clang_args(self) -> list[str]:
        """libclang `Index.parse()` 에 넘길 인자.

        상대 include 경로가 깨지지 않도록 `-working-directory` 를 붙인다.
        """
        args: list[str] = []
        source = self.abs_file.resolve()
        rest = list(self.arguments[1:])  # argv[0] = 컴파일러
        index = 0
        while index < len(rest):
            arg = rest[index]
            index += 1
            if arg in _FLAGS_TO_DROP:
                continue
            if arg in _FLAGS_WITH_VALUE:
                takes_value = index < len(rest) and not rest[index].startswith("-")
                if arg in _OPTIONAL_VALUE and not takes_value:
                    continue
                if takes_value:
                    index += 1
                continue
            if arg.startswith("-o"):
                continue
            if _is_source(arg, source, self.directory):
                continue
            args.append(arg)

        args.append(f"-working-directory={self.directory}")
        return args


def _is_source(arg: str, source: Path, directory: str) -> bool:
    if arg.startswith("-"):
        return False
    candidate = Path(arg)
    if not candidate.is_absolute():
        candidate = Path(directory) / candidate
    try:
        return candidate.resolve() == source
    except OSError:  # pragma: no cover - 해석 불가한 경로
        return False


def load_compile_commands(path: str | Path) -> list[CompileCommand]:
    """`compile_commands.json` 을 읽어 엔트리 목록을 돌려준다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("compile_commands.json 의 최상위는 배열이어야 한다")

    commands: list[CompileCommand] = []
    for entry in raw:
        arguments = entry.get("arguments")
        if arguments is None:
            command = entry.get("command")
            if command is None:
                raise ValueError(
                    "엔트리에 arguments 도 command 도 없다: " f"{entry.get('file')!r}"
                )
            arguments = shlex.split(command)
        commands.append(
            CompileCommand(
                directory=entry["directory"],
                file=entry["file"],
                arguments=list(arguments),
            )
        )
    return commands

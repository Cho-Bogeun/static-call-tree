from __future__ import annotations

import json
from pathlib import Path

import pytest

from calltree.compile_db import CompileCommand
from calltree.libclang_loader import is_available

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "proj"
SOURCES = ("src/cfg.c", "src/proc.c", "src/aux.c")

requires_libclang = pytest.mark.skipif(
    not is_available(),
    reason="libclang 을 불러올 수 없다 (pip install libclang)",
)


def make_commands(root: Path = FIXTURE_ROOT) -> list[CompileCommand]:
    """픽스처 프로젝트의 compile_commands 엔트리."""
    return [
        CompileCommand(
            directory=str(root),
            file=source,
            arguments=[
                "cc",
                "-std=c11",
                "-Iinclude",
                "-c",
                source,
                "-o",
                f"{Path(source).stem}.o",
            ],
        )
        for source in SOURCES
    ]


@pytest.fixture
def fixture_root() -> Path:
    return FIXTURE_ROOT


@pytest.fixture
def commands() -> list[CompileCommand]:
    return make_commands()


@pytest.fixture
def compile_commands_file(tmp_path: Path) -> Path:
    """픽스처 프로젝트를 가리키는 compile_commands.json 을 임시 디렉터리에 만든다."""
    path = tmp_path / "compile_commands.json"
    path.write_text(
        json.dumps(
            [
                {
                    "directory": command.directory,
                    "file": command.file,
                    "arguments": command.arguments,
                }
                for command in make_commands()
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return path

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calltree.compile_db import CompileCommand, load_compile_commands


def test_clang_args_drops_driver_flags_and_source():
    command = CompileCommand(
        directory="/proj",
        file="src/proc.c",
        arguments=[
            "cc",
            "-std=c11",
            "-Iinclude",
            "-DDEBUG=1",
            "-c",
            "src/proc.c",
            "-o",
            "obj/proc.o",
            "-MD",
            "-MF",
            "obj/proc.d",
        ],
    )
    args = command.clang_args()

    assert "-std=c11" in args
    assert "-Iinclude" in args
    assert "-DDEBUG=1" in args
    assert "src/proc.c" not in args
    assert "obj/proc.o" not in args
    assert "obj/proc.d" not in args
    assert not {"-c", "-o", "-MD", "-MF"} & set(args)
    # 상대 include 경로가 깨지지 않도록 작업 디렉터리를 넘긴다.
    assert "-working-directory=/proj" in args


def test_clang_args_keeps_flags_that_look_like_values():
    command = CompileCommand(
        directory="/proj",
        file="/proj/src/proc.c",
        arguments=["cc", "-MD", "-Wall", "-c", "/proj/src/proc.c"],
    )
    args = command.clang_args()
    # -MD 뒤가 플래그면 값을 먹지 않는다.
    assert "-Wall" in args


def test_abs_file_resolves_relative_entry():
    command = CompileCommand(directory="/proj", file="src/proc.c", arguments=["cc"])
    assert command.abs_file == Path("/proj/src/proc.c")


def test_load_accepts_command_string(tmp_path: Path):
    db = tmp_path / "compile_commands.json"
    db.write_text(
        json.dumps(
            [
                {
                    "directory": "/proj",
                    "file": "src/proc.c",
                    "command": "cc -std=c11 -Iinclude -c src/proc.c -o proc.o",
                }
            ]
        ),
        encoding="utf-8",
    )
    commands = load_compile_commands(db)

    assert len(commands) == 1
    assert commands[0].arguments[0] == "cc"
    assert "-Iinclude" in commands[0].clang_args()


def test_load_rejects_entry_without_command(tmp_path: Path):
    db = tmp_path / "compile_commands.json"
    db.write_text(
        json.dumps([{"directory": "/proj", "file": "src/proc.c"}]), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_compile_commands(db)


def test_load_rejects_non_array(tmp_path: Path):
    db = tmp_path / "compile_commands.json"
    db.write_text(json.dumps({"file": "a.c"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_compile_commands(db)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calltree.cli import main
from conftest import FIXTURE_ROOT, requires_libclang

pytestmark = requires_libclang


def run_extract(
    compile_commands: Path, output: Path, entry: str = "process_frame", *extra: str
) -> int:
    return main(
        [
            "extract",
            "--compile-commands",
            str(compile_commands),
            "--entry",
            entry,
            "--root",
            str(FIXTURE_ROOT),
            "--output",
            str(output),
            "--quiet",
            *extra,
        ]
    )


def test_extract_writes_schema_shaped_json(compile_commands_file: Path, tmp_path: Path):
    output = tmp_path / "calltree.json"
    assert run_extract(compile_commands_file, output) == 0

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["meta"]["entry_point"] == "c:@F@process_frame"
    assert data["meta"]["tu_count"] == 3
    assert data["meta"]["compile_commands"] == str(compile_commands_file)
    assert data["meta"]["clang_version"]
    assert "c:proc.c@F@reset" in data["nodes"]
    assert "c:@g_cfg" in data["state"]
    # USR 정렬로 스냅샷 diff 가 안정적이어야 한다.
    assert list(data["nodes"]) == sorted(data["nodes"])


def test_extract_accepts_usr_as_entry(compile_commands_file: Path, tmp_path: Path):
    output = tmp_path / "calltree.json"
    assert run_extract(compile_commands_file, output, "c:@F@aux_entry") == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["meta"]["entry_point"] == "c:@F@aux_entry"


def test_extract_rejects_ambiguous_entry(compile_commands_file: Path, tmp_path: Path):
    """reset 은 proc.c 와 aux.c 에 하나씩 있다. 이름만으로는 고를 수 없다."""
    with pytest.raises(SystemExit) as exc:
        run_extract(compile_commands_file, tmp_path / "out.json", "reset")
    assert "모호" in str(exc.value)
    assert "c:proc.c@F@reset" in str(exc.value)


def test_extract_rejects_unknown_entry(compile_commands_file: Path, tmp_path: Path):
    with pytest.raises(SystemExit):
        run_extract(compile_commands_file, tmp_path / "out.json", "no_such_function")


def test_extract_validates_when_asked(compile_commands_file: Path, tmp_path: Path):
    pytest.importorskip("jsonschema")
    output = tmp_path / "calltree.json"
    assert run_extract(compile_commands_file, output, "process_frame", "--validate") == 0


def test_validate_subcommand_round_trip(compile_commands_file: Path, tmp_path: Path):
    pytest.importorskip("jsonschema")
    output = tmp_path / "calltree.json"
    run_extract(compile_commands_file, output)

    assert main(["validate", str(output)]) == 0

    broken = json.loads(output.read_text(encoding="utf-8"))
    broken["meta"].pop("tu_count")
    bad_file = tmp_path / "broken.json"
    bad_file.write_text(json.dumps(broken), encoding="utf-8")

    assert main(["validate", str(bad_file)]) == 1


def test_extract_to_stdout(compile_commands_file: Path, capsys):
    exit_code = main(
        [
            "extract",
            "-c",
            str(compile_commands_file),
            "-e",
            "process_frame",
            "--root",
            str(FIXTURE_ROOT),
            "--quiet",
        ]
    )
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["meta"]["entry_point"] == "c:@F@process_frame"

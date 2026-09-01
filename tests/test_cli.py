from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FIXTURE_ROOT
from cstat.cli import main

# ------------------------------------------------------------------ 명령 구성


def test_subcommands_are_the_two_stages_plus_utilities(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    usage = capsys.readouterr().out
    assert "{calltree,analyze,visualize,validate,doctor}" in usage


def test_version_names_the_command(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("cstat ")


def test_unknown_subcommand_fails(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["extract"])
    assert exc.value.code == 2


def test_doctor_reports_a_usable_libclang(capsys):
    """conftest 가 이미 점검했으므로 여기서는 통과해야 한다."""
    assert main(["doctor"]) == 0
    assert "스모크 파싱" in capsys.readouterr().out


# ---------------------------------------------------------------------- 추출


def run_extract(
    compile_commands: Path, output: Path, entry: str = "process_frame", *extra: str
) -> int:
    return main(
        [
            "calltree",
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


def test_analyze_writes_schema_shaped_json(compile_commands_file: Path, tmp_path: Path):
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)

    analysis = tmp_path / "analysis.json"
    assert main(["analyze", str(calltree), "-o", str(analysis), "--quiet"]) == 0

    data = json.loads(analysis.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["source"] == str(calltree)
    assert data["criteria"] == {
        "exclude_const": True,
        "include_function_static": True,
        "addr_as": "readwrite",
        "const_read": False,
    }
    # 가지치기로 aux.c 쪽은 빠진다.
    assert "c:@F@aux_entry" not in data["nodes"]
    assert data["nodes"]["c:proc.c@F@reset"]["contamination_degree"] == 2
    assert list(data["nodes"]) == sorted(data["nodes"])


def test_analyze_records_the_criteria_it_ran_with(
    compile_commands_file: Path, tmp_path: Path
):
    """기준을 바꿔 여러 벌 만들 때 어떤 결과가 어떤 기준인지 구분되어야 한다."""
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)

    analysis = tmp_path / "loose.json"
    assert (
        main(
            [
                "analyze",
                str(calltree),
                "-o",
                str(analysis),
                "--include-const",
                "--no-function-static",
                "--addr-as",
                "manual",
                "--quiet",
            ]
        )
        == 0
    )

    data = json.loads(analysis.read_text(encoding="utf-8"))
    assert data["criteria"] == {
        "exclude_const": False,
        "include_function_static": False,
        "addr_as": "manual",
        "const_read": False,
    }
    reasons = data["nodes"]["c:@F@process_frame"]["impurity_reasons"]
    assert "c:@g_cfg" in reasons  # const 를 포함시켰다
    assert not any("retry_cnt" in usr for usr in reasons)  # 함수 내 static 은 뺐다


def test_analyze_const_read_narrows_the_reasons(
    compile_commands_file: Path, tmp_path: Path
):
    """읽기 전용 접근을 빼면 addr_as 가 결과를 가른다."""
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)

    def reasons(*extra: str) -> list[str]:
        output = tmp_path / f"a{len(extra)}{extra[-1]}.json"
        assert (
            main(["analyze", str(calltree), "-o", str(output), "--quiet", *extra]) == 0
        )
        data = json.loads(output.read_text(encoding="utf-8"))
        return data["nodes"]["c:@F@process_frame"]["impurity_reasons"]

    # g_buf 는 sink(g_buf) 감쇠와 g_buf[i] 읽기로만 닿는다. 감쇠를 읽기로 보면 빠진다.
    assert "c:proc.c@g_buf" in reasons("--const-read", "--addr-as", "readwrite")
    assert "c:proc.c@g_buf" not in reasons("--const-read", "--addr-as", "read")


def test_analyze_prints_a_summary(compile_commands_file: Path, tmp_path: Path, capsys):
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)
    capsys.readouterr()

    assert main(["analyze", str(calltree), "-o", str(tmp_path / "a.json")]) == 0
    summary = capsys.readouterr().err
    assert "오염원" in summary
    assert "깨끗한 서브트리 루트" in summary
    assert "process_frame" in summary


def test_analyze_to_stdout(compile_commands_file: Path, tmp_path: Path, capsys):
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)
    capsys.readouterr()

    assert main(["analyze", str(calltree), "--quiet"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["nodes"]["c:@F@process_frame"]["is_impure"]


def test_analyze_validates_when_asked(compile_commands_file: Path, tmp_path: Path):
    pytest.importorskip("jsonschema")
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)

    assert (
        main(
            [
                "analyze",
                str(calltree),
                "-o",
                str(tmp_path / "analysis.json"),
                "--validate",
                "--quiet",
            ]
        )
        == 0
    )


def test_validate_picks_the_schema_by_content(
    compile_commands_file: Path, tmp_path: Path
):
    pytest.importorskip("jsonschema")
    calltree = tmp_path / "calltree.json"
    analysis = tmp_path / "analysis.json"
    run_extract(compile_commands_file, calltree)
    main(["analyze", str(calltree), "-o", str(analysis), "--quiet"])

    assert main(["validate", str(calltree)]) == 0
    assert main(["validate", str(analysis)]) == 0

    broken = json.loads(analysis.read_text(encoding="utf-8"))
    # 오염원이 아니면 사유가 있을 수 없다. 스키마가 막아준다.
    broken["nodes"]["c:common.h@F@clamp"]["impurity_reasons"] = ["c:@g_flag"]
    bad_file = tmp_path / "broken.json"
    bad_file.write_text(json.dumps(broken), encoding="utf-8")

    assert main(["validate", str(bad_file)]) == 1


def test_analyze_rejects_entry_missing_from_nodes(
    compile_commands_file: Path, tmp_path: Path
):
    calltree = tmp_path / "calltree.json"
    run_extract(compile_commands_file, calltree)
    data = json.loads(calltree.read_text(encoding="utf-8"))
    data["meta"]["entry_point"] = "c:@F@ghost"
    calltree.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["analyze", str(calltree), "--quiet"])


def test_extract_to_stdout(compile_commands_file: Path, capsys):
    exit_code = main(
        [
            "calltree",
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

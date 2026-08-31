"""libclang 이 어긋났을 때 아무 것도 하지 않고 멈추는지 확인한다."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import calltree.libclang_loader as loader
from calltree.libclang_loader import LibclangUnavailable
from calltree.preflight import diagnose, run as preflight

SRC = Path(__file__).resolve().parents[1] / "src"


def cli(*argv: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(SRC))
    env.pop(loader.ENV_ALLOW_MISMATCH, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "calltree.cli", *argv],
        capture_output=True,
        text=True,
        env=env,
    )


# ------------------------------------------------------------------ 정상 경로


def test_preflight_passes_in_this_environment():
    report = preflight()
    assert report.ok
    assert "clang" in report.clang_version
    assert report.binding != "unknown"


def test_summary_reports_both_versions():
    summary = diagnose().summary()
    assert "네이티브 libclang" in summary
    assert "파이썬 바인딩" in summary
    assert "통과" in summary


def test_doctor_exits_zero():
    result = cli("doctor")
    assert result.returncode == 0, result.stderr
    assert "통과" in result.stdout


# ------------------------------------------------------------------ 실패 경로


def test_missing_library_file_fails_with_install_help(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(loader, "_configured", False)
    with pytest.raises(LibclangUnavailable) as exc:
        loader.configure(library_file="/nonexistent/libclang.so")

    message = str(exc.value)
    assert "지정한 libclang 파일이 없다" in message
    assert "pip install 'libclang" in message  # 설치법이 항상 붙는다
    assert loader.ENV_LIBRARY_FILE in message


def test_major_version_mismatch_is_fatal(monkeypatch: pytest.MonkeyPatch):
    """로드는 되지만 조용히 틀릴 수 있는 조합. 여기서 멈춰야 한다."""
    monkeypatch.delenv(loader.ENV_ALLOW_MISMATCH, raising=False)
    monkeypatch.setattr(loader, "binding_version", lambda *a, **k: ("clang", "21.1.7"))
    monkeypatch.setattr(loader, "clang_version", lambda: "clang version 18.1.1")

    with pytest.raises(LibclangUnavailable) as exc:
        loader.require()

    message = str(exc.value)
    assert "메이저 버전이 다르다" in message
    assert "설치 방법" in message


def test_version_mismatch_override_is_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(loader.ENV_ALLOW_MISMATCH, "1")
    monkeypatch.setattr(loader, "binding_version", lambda *a, **k: ("clang", "21.1.7"))
    monkeypatch.setattr(loader, "clang_version", lambda: "clang version 18.1.1")

    assert loader.require() is not None


def test_two_binding_packages_is_fatal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(loader.ENV_ALLOW_MISMATCH, raising=False)
    monkeypatch.setattr(
        loader, "_installed_bindings", lambda: ["libclang 18.1.1", "clang 21.1.7"]
    )
    with pytest.raises(LibclangUnavailable) as exc:
        loader.require()
    assert "둘 이상 설치" in str(exc.value)


def test_broken_smoke_result_stops_extraction(monkeypatch: pytest.MonkeyPatch):
    """버전이 맞아도 관측이 기대와 다르면 멈춘다."""
    import calltree.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module, "_smoke_problems", lambda: ["콜 엣지가 기대와 다르다: []"]
    )
    with pytest.raises(LibclangUnavailable) as exc:
        preflight_module.run()

    message = str(exc.value)
    assert "틀린 콜트리가 나오므로 멈춘다" in message
    assert "콜 엣지가 기대와 다르다" in message


# ------------------------------------------------------------------ CLI 순서


def test_extract_stops_before_touching_any_input(tmp_path: Path):
    """libclang 이 깨졌으면 compile_commands.json 을 읽기도 전에 멈춘다."""
    missing_db = tmp_path / "compile_commands.json"  # 존재하지 않는다
    result = cli(
        "extract",
        "-c",
        str(missing_db),
        "-e",
        "process_frame",
        CALLTREE_LIBCLANG_LIBRARY="/nonexistent/libclang.so",
    )

    assert result.returncode == 2
    assert "설치 방법" in result.stderr
    # 입력을 읽었다면 FileNotFoundError 로 죽었을 것이다.
    assert "FileNotFoundError" not in result.stderr
    assert result.stdout == ""


def test_doctor_reports_broken_library():
    result = cli("doctor", CALLTREE_LIBCLANG_LIBRARY="/nonexistent/libclang.so")
    assert result.returncode == 2
    assert "지정한 libclang 파일이 없다" in result.stderr


def test_validate_does_not_need_libclang(tmp_path: Path):
    """검증만 할 때는 libclang 이 필요 없다. 여기까지 막지는 않는다."""
    pytest.importorskip("jsonschema")
    bad = tmp_path / "calltree.json"
    bad.write_text('{"schema_version": 1}', encoding="utf-8")

    result = cli(
        "validate", str(bad), CALLTREE_LIBCLANG_LIBRARY="/nonexistent/libclang.so"
    )
    assert result.returncode == 1  # 스키마 위반이지 libclang 문제가 아니다
    assert "스키마 위반" in result.stderr

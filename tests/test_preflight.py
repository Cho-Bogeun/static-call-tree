"""libclang 이 어긋났을 때 아무 것도 하지 않고 멈추는지 확인한다."""

from __future__ import annotations

import os
import re
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
        [sys.executable, "-m", "cstat.cli", *argv],
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


# ---------------------------------------------------------- 네이티브 버전 읽기


def test_clang_version_is_readable():
    """네이티브 버전을 실제로 읽는다.

    `"unknown"` 이면 `_check_versions` 의 메이저 대조가 통째로 꺼진다. 그 상태로는
    바인딩/네이티브 불일치를 막는 코드가 있으나 없으나 같다.
    """
    version = loader.clang_version()
    assert version != "unknown"
    assert re.search(r"clang version (\d+)", version), version


def test_clang_version_survives_a_one_argument_from_result(
    monkeypatch: pytest.MonkeyPatch,
):
    """clang 21.x 바인딩의 `from_result(res)` 시그니처에서도 읽어야 한다.

    ctypes 의 errcheck 규약은 콜러블을 3인자로 부른다. 거기에 1인자 헬퍼를 걸면
    `TypeError` 가 나고, 그걸 삼키면 `"unknown"` 이 되어 버전 관문이 꺼진다.
    18.x 바인딩에서는 `from_result(res, fn=None, args=None)` 라 그냥 돌아가므로,
    21.x 의 시그니처를 흉내 내야 이 회귀가 잡힌다.
    """
    cindex = loader.configure()
    original = cindex._CXString.from_result

    def one_argument_from_result(res):  # clang 21.x 와 같은 시그니처
        return original(res)

    monkeypatch.setattr(
        cindex._CXString, "from_result", staticmethod(one_argument_from_result)
    )
    assert loader.clang_version() != "unknown"


def test_version_mismatch_still_raises_with_the_real_version(
    monkeypatch: pytest.MonkeyPatch,
):
    """대조가 살아 있는지. `clang_version` 은 진짜를 쓰고 바인딩 쪽만 바꾼다.

    위쪽의 불일치 테스트들은 `clang_version` 자체를 몽키패치하므로, 그 함수가
    고장나 있어도 통과한다. 결함이 여기까지 살아온 이유다.
    """
    monkeypatch.delenv(loader.ENV_ALLOW_MISMATCH, raising=False)
    monkeypatch.setattr(loader, "binding_version", lambda *a, **k: ("clang", "9.0.0"))

    with pytest.raises(LibclangUnavailable, match="메이저 버전이 다르다"):
        loader.require()


def test_native_major_ignores_a_distro_prefix():
    """배포판 접두에 숫자가 있어도 clang 의 메이저를 집는다."""
    assert loader._native_major("Ubuntu clang version 21.1.8 (++2025...)") == 21
    assert loader._native_major("Ubuntu 24.04 clang version 18.1.3") == 18
    assert loader._native_major("clang version 16.0.6") == 16


# -------------------------------------------------------------- 빌트인 헤더


def test_smoke_source_carries_the_builtin_header_tripwire():
    """스모크 조각이 빌트인 헤더 없는 파서에 반응할 재료를 갖고 있는지.

    빌트인 헤더가 없으면 `stddef.h` 를 못 찾고, 그러면 `NULL` 이 미정의 식별자가
    되고, clang 의 에러 복구가 그 인자를 쓰는 **호출식을 AST 에서 지운다.** 그래서
    기존의 콜 엣지 검사가 곧 "빌트인 헤더가 있는가" 검사가 된다. 이 두 줄이 빠지면
    그 검사가 무력해지므로 여기 못박아 둔다.
    """
    from calltree.preflight import SMOKE_SOURCE

    assert "#include <stddef.h>" in SMOKE_SOURCE
    assert "smoke_leaf(v, NULL)" in SMOKE_SOURCE


def test_missing_builtin_headers_erase_the_call_edge():
    """빌트인 헤더를 뺏으면 실제로 엣지가 사라지는지 — 실측.

    `-nobuiltininc` 는 clang 리소스 디렉터리만 검색 경로에서 뺀다. PyPI `libclang`
    휠이 만드는 상태(`.so` 는 있고 빌트인 헤더는 없다)와 정확히 같다.
    `-resource-dir` 을 없는 경로로 주는 방법은 배포판이 다른 경로에서 헤더를
    찾아내는 환경이 있어 재현되지 않는다.
    """
    from calltree.extract import TUExtractor
    import calltree.preflight as preflight_module

    result = TUExtractor(root=Path.cwd()).parse(
        preflight_module.SMOKE_NAME,
        args=["-std=c11", "-nobuiltininc"],
        unsaved_files=[(preflight_module.SMOKE_NAME, preflight_module.SMOKE_SOURCE)],
    )

    assert result.has_errors, "빌트인 헤더 없이도 파싱이 성공하면 스모크 조각이 무력하다"
    entry = result.nodes["c:@F@smoke_entry"]
    assert [call.callee for call in entry.calls] == [], (
        "에러 복구가 호출식을 지우지 않았다면 이 조각으로는 절단을 못 잡는다"
    )


def test_preflight_stops_a_parser_without_builtin_headers():
    """그 상태를 preflight 가 실제로 막는지. 이슈의 핵심이다."""
    import calltree.preflight as preflight_module

    problems = preflight_module._smoke_problems(["-nobuiltininc"])

    assert problems, "빌트인 헤더가 없는 파서를 통과시키면 콜트리가 조용히 잘린다"
    joined = "\n".join(problems)
    assert "콜 엣지가 기대와 다르다" in joined  # 기존 검사가 그대로 잡는다
    assert "리소스 디렉터리" in joined  # 원인을 짚어 준다


# ------------------------------------------------------------------ CLI 순서


def test_extract_stops_before_touching_any_input(tmp_path: Path):
    """libclang 이 깨졌으면 compile_commands.json 을 읽기도 전에 멈춘다."""
    missing_db = tmp_path / "compile_commands.json"  # 존재하지 않는다
    result = cli(
        "calltree",
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

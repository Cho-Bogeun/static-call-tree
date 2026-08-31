"""libclang 로딩.

파이썬 바인딩(`clang.cindex`)과 네이티브 `libclang.so` 의 버전이 어긋나면
`Index.create()` 시점에 `undefined symbol` 로 죽는다. 로딩 경로를 한 곳에 모아서
어디서 어긋났는지 바로 알 수 있게 한다.

우선순위:

1. 명시적으로 넘긴 `library_file` / `library_path`
2. 환경변수 `CALLTREE_LIBCLANG_LIBRARY` (.so 파일) / `CALLTREE_LIBCLANG_PATH` (디렉터리)
3. 바인딩 기본 동작 (PyPI ``libclang`` 휠은 자기 안에 .so 를 들고 있다)
"""

from __future__ import annotations

import os
from types import ModuleType

ENV_LIBRARY_FILE = "CALLTREE_LIBCLANG_LIBRARY"
ENV_LIBRARY_PATH = "CALLTREE_LIBCLANG_PATH"

_configured = False


class LibclangUnavailable(RuntimeError):
    """`clang.cindex` 를 못 불러오거나 네이티브 라이브러리를 못 여는 경우."""


def configure(
    library_file: str | None = None, library_path: str | None = None
) -> ModuleType:
    """`clang.cindex` 를 설정하고 모듈을 돌려준다. 여러 번 불러도 안전하다."""
    global _configured

    try:
        import clang.cindex as cindex
    except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 다름
        raise LibclangUnavailable(
            "clang.cindex 를 불러올 수 없다. `pip install libclang` 으로 설치하거나 "
            "시스템 clang 바인딩을 PYTHONPATH 에 올려라."
        ) from exc

    if _configured:
        return cindex

    library_file = library_file or os.environ.get(ENV_LIBRARY_FILE)
    library_path = library_path or os.environ.get(ENV_LIBRARY_PATH)

    try:
        if library_file:
            cindex.Config.set_library_file(library_file)
        elif library_path:
            cindex.Config.set_library_path(library_path)
    except Exception as exc:  # cindex 는 설정 후 상태에서 다양한 예외를 던진다
        raise LibclangUnavailable(f"libclang 경로 설정 실패: {exc}") from exc

    _configured = True
    return cindex


def load() -> ModuleType:
    """설정을 마친 `clang.cindex` 모듈. 네이티브 로딩까지 여기서 확인한다."""
    cindex = configure()
    try:
        cindex.Index.create()
    except Exception as exc:
        raise LibclangUnavailable(
            f"libclang 네이티브 라이브러리를 열 수 없다: {exc}\n"
            f"{ENV_LIBRARY_FILE} 로 libclang.so 경로를 직접 지정할 수 있다."
        ) from exc
    return cindex


def is_available() -> bool:
    try:
        load()
    except LibclangUnavailable:
        return False
    return True


def clang_version() -> str:
    """`meta.clang_version` 에 넣을 문자열.

    `clang_getClangVersion` 은 바인딩 버전에 따라 등록되어 있지 않아서 반환값이
    정수로 잘려 나온다. 그래서 restype 을 직접 지정해 호출한다.
    """
    cindex = load()
    try:
        lib = cindex.conf.lib
        func = lib.clang_getClangVersion
        func.restype = cindex._CXString
        func.errcheck = cindex._CXString.from_result
        version = func()
    except Exception:  # pragma: no cover - 바인딩 내부 사정
        return "unknown"
    return str(version) if version else "unknown"

"""libclang 로딩.

파이썬 바인딩(`clang.cindex`)과 네이티브 `libclang.so` 는 서로 다른 물건이고,
버전이 어긋나면 두 가지로 갈린다.

- 바인딩이 더 최신이면 없는 심볼을 등록하다 `undefined symbol` 로 죽는다.
- 바인딩이 더 구형이면 **아무 소리 없이 로드된다**. 새로 생긴 커서 종류를 못 알아보고
  조용히 다른 분기로 빠지므로, 틀린 콜트리를 뽑고도 성공한 것처럼 끝난다.

두 번째가 훨씬 위험하다. 그래서 여기서는 로딩에 성공했더라도 버전을 대조해
불일치를 실패로 처리한다. 실제 관측 결과까지 확인하는 것은 `preflight` 의 몫이다.
"""

from __future__ import annotations

import os
import re
from importlib import metadata
from pathlib import Path
from types import ModuleType

ENV_LIBRARY_FILE = "CALLTREE_LIBCLANG_LIBRARY"
ENV_LIBRARY_PATH = "CALLTREE_LIBCLANG_PATH"
ENV_ALLOW_MISMATCH = "CALLTREE_ALLOW_VERSION_MISMATCH"

#: 파이썬 바인딩을 제공하는 배포판 이름. 둘 다 `clang/` 패키지에 설치된다.
_BINDING_DISTRIBUTIONS = ("libclang", "clang")

INSTALL_HELP = f"""\
설치 방법
─────────
[1] PyPI 휠 하나로 끝내기 (권장. 바인딩과 .so 가 한 벌로 온다)

      pip uninstall -y clang            # 두 패키지는 같은 clang/ 을 덮어쓴다
      pip install 'libclang==18.1.1'

[2] 시스템 clang 사용

      apt install libclang-18-dev       # Debian/Ubuntu
      dnf install clang-devel           # Fedora/RHEL
      brew install llvm                 # macOS

    .so 경로를 알려준다:

      export {ENV_LIBRARY_FILE}=/usr/lib/llvm-18/lib/libclang.so.1
      export {ENV_LIBRARY_FILE}=$(brew --prefix llvm)/lib/libclang.dylib   # macOS

    바인딩 메이저 버전을 .so 에 맞춘다 (libclang-18 이면 clang 18.x):

      pip uninstall -y libclang && pip install 'clang==18.1.8'

확인:  cstat doctor"""


class LibclangUnavailable(RuntimeError):
    """libclang 을 못 불러오거나, 불러왔지만 믿고 쓸 수 없는 상태."""


def _fail(reason: str) -> LibclangUnavailable:
    return LibclangUnavailable(f"{reason}\n\n{INSTALL_HELP}")


_configured = False


def configure(
    library_file: str | None = None, library_path: str | None = None
) -> ModuleType:
    """`clang.cindex` 를 설정하고 모듈을 돌려준다. 여러 번 불러도 안전하다."""
    global _configured

    try:
        import clang.cindex as cindex
    except ImportError as exc:
        raise _fail(f"파이썬 바인딩 clang.cindex 를 불러올 수 없다: {exc}") from exc

    if _configured:
        return cindex

    library_file = library_file or os.environ.get(ENV_LIBRARY_FILE)
    library_path = library_path or os.environ.get(ENV_LIBRARY_PATH)

    if library_file and not Path(library_file).exists():
        raise _fail(f"지정한 libclang 파일이 없다: {library_file}")

    try:
        if library_file:
            cindex.Config.set_library_file(library_file)
        elif library_path:
            cindex.Config.set_library_path(library_path)
    except Exception as exc:
        raise _fail(f"libclang 경로 설정 실패: {exc}") from exc

    _configured = True
    return cindex


def require(
    library_file: str | None = None, library_path: str | None = None
) -> ModuleType:
    """쓸 수 있는 `clang.cindex` 를 돌려준다. 조금이라도 어긋나면 예외를 던진다."""
    cindex = configure(library_file, library_path)

    try:
        cindex.Index.create()
    except Exception as exc:
        raise _fail(f"네이티브 libclang 을 열 수 없다: {exc}") from exc

    _check_versions(cindex)
    return cindex


def clang_version() -> str:
    """네이티브 라이브러리가 보고하는 버전 문자열.

    `clang_getClangVersion` 은 바인딩에 등록돼 있지 않아 반환값이 정수로 잘린다.
    restype 을 직접 지정해 호출한다.
    """
    cindex = configure()
    try:
        function = cindex.conf.lib.clang_getClangVersion
        function.restype = cindex._CXString
        function.errcheck = cindex._CXString.from_result
        version = function()
    except Exception:  # pragma: no cover - 바인딩 내부 사정
        return "unknown"
    return str(version) if version else "unknown"


def binding_version(cindex: ModuleType | None = None) -> tuple[str, str] | None:
    """(배포판 이름, 버전). 배포판 메타데이터가 없으면 None."""
    cindex = cindex or configure()
    # libclang 휠은 자기 안에 native/ 로 .so 를 들고 온다. 그걸로 어느 쪽인지 가른다.
    bundled = (Path(cindex.__file__).resolve().parent / "native").is_dir()
    preferred = "libclang" if bundled else "clang"
    for name in (preferred, *_BINDING_DISTRIBUTIONS):
        try:
            return name, metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return None


def _installed_bindings() -> list[str]:
    installed = []
    for name in _BINDING_DISTRIBUTIONS:
        try:
            installed.append(f"{name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            continue
    return installed


def _major(version: str) -> int | None:
    match = re.search(r"(\d+)", version)
    return int(match.group(1)) if match else None


def _check_versions(cindex: ModuleType) -> None:
    if os.environ.get(ENV_ALLOW_MISMATCH):
        return

    installed = _installed_bindings()
    if len(installed) > 1:
        raise _fail(
            "파이썬 바인딩 패키지가 둘 이상 설치돼 있다: "
            + ", ".join(installed)
            + "\n둘 다 같은 clang/ 디렉터리에 설치되므로 어느 쪽이 살아 있는지 알 수 없다. "
            "하나만 남겨라."
        )

    binding = binding_version(cindex)
    native = clang_version()
    if binding is None or native == "unknown":
        # 배포판 메타데이터가 없는 환경(배포판 패키지 등)에서는 대조를 건너뛴다.
        # 실제 관측이 맞는지는 preflight 의 스모크 파싱이 본다.
        return

    binding_major = _major(binding[1])
    native_major = _major(native.replace("clang version", "").strip())
    if binding_major is None or native_major is None:
        return

    if binding_major != native_major:
        raise _fail(
            f"파이썬 바인딩({binding[0]} {binding[1]})과 "
            f"네이티브 libclang({native})의 메이저 버전이 다르다.\n"
            f"로드는 되지만 새 커서 종류를 조용히 놓쳐 틀린 콜트리가 나올 수 있어 "
            f"실행을 멈춘다.\n"
            f"검증을 무시하려면 {ENV_ALLOW_MISMATCH}=1 (권장하지 않는다)."
        )

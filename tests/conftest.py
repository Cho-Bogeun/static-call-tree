from __future__ import annotations

import json
from pathlib import Path

import pytest

from calltree.compile_db import CompileCommand
from calltree.libclang_loader import LibclangUnavailable
from calltree.model import CallTree, Meta
from calltree.preflight import run as preflight

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "proj"
SOURCES = ("src/cfg.c", "src/proc.c", "src/aux.c")


def pytest_configure(config: pytest.Config) -> None:
    """libclang 이 어긋나 있으면 테스트를 하나도 돌리지 않는다.

    건너뛰기(skip)로 두면 CI 는 초록불인데 파싱 테스트는 한 개도 안 돈 상태가 된다.
    그게 제일 위험하므로 수집 단계에서 통째로 실패시킨다.
    """
    try:
        preflight()
    except LibclangUnavailable as exc:
        raise pytest.UsageError(f"\n{exc}") from exc


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


@pytest.fixture(scope="session")
def extracted_tree() -> CallTree:
    """픽스처 프로젝트를 한 번만 파싱해 콜트리로 만든다.

    파싱은 이 테스트 묶음에서 제일 비싼 일이고, 판정 쪽 테스트는 전부 같은 결과를
    입력으로 쓴다. 읽기 전용으로만 다뤄야 한다.
    """
    from calltree.extract import extract

    result = extract(make_commands(), root=FIXTURE_ROOT)
    return CallTree(
        meta=Meta(
            entry_point="c:@F@process_frame",
            compile_commands="build/compile_commands.json",
            clang_version="18.1.1",
            generated_at="2026-08-31T10:00:00+09:00",
            tu_count=3,
        ),
        nodes=result.nodes,
        state=result.state,
    )


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

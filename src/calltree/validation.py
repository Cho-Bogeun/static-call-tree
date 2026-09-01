"""추출 결과가 `calltree.schema.json` 을 만족하는지 확인한다.

스키마 파일은 저장소 루트에 있는 한 벌이 유일한 원본이다. 패키지 안에 복사본을
두지 않고 찾아 쓴다. 판정 결과 쪽은 `analyze.validation` 이 같은 방식으로 한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ENV_SCHEMA = "CALLTREE_SCHEMA"
SCHEMA_FILENAME = "calltree.schema.json"


class SchemaNotFound(FileNotFoundError):
    pass


def find_schema_file(filename: str, env: str) -> Path:
    """환경변수 → 패키지 동봉본 → 저장소 루트 → 현재 디렉터리 순으로 찾는다.

    두 스키마가 같은 규칙으로 놓이므로 파일명만 갈아끼워 쓴다.
    """
    override = os.environ.get(env)
    if override:
        return Path(override)

    packaged = Path(__file__).resolve().parent / filename
    if packaged.is_file():
        return packaged

    repo_root = Path(__file__).resolve().parents[2] / filename
    if repo_root.is_file():
        return repo_root

    cwd = Path.cwd() / filename
    if cwd.is_file():
        return cwd

    raise SchemaNotFound(f"{filename} 을 찾을 수 없다. {env} 로 경로를 지정해라.")


def find_schema() -> Path:
    """`calltree.schema.json` 경로."""
    return find_schema_file(SCHEMA_FILENAME, ENV_SCHEMA)


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    schema_path = Path(path) if path is not None else find_schema()
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate(data: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """스키마 위반 목록. 빈 리스트면 통과다."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - 선택 의존성
        raise RuntimeError(
            "jsonschema 가 필요하다: pip install 'cstat[validate]'"
        ) from exc

    validator = jsonschema.Draft202012Validator(schema or load_schema())
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: e.absolute_path)
    ]

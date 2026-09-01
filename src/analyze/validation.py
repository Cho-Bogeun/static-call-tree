"""판정 결과가 `analysis.schema.json` 을 만족하는지 확인한다.

스키마를 찾는 규칙은 추출 쪽과 같으므로 `calltree.validation` 의 탐색기를 그대로
쓴다. 저장소 루트의 한 벌이 유일한 원본이고, 패키지 안에 복사본을 두지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from calltree.validation import find_schema_file, load_schema, validate

ENV_ANALYSIS_SCHEMA = "CALLTREE_ANALYSIS_SCHEMA"
ANALYSIS_SCHEMA_FILENAME = "analysis.schema.json"


def find_analysis_schema() -> Path:
    """`analysis.schema.json` 경로."""
    return find_schema_file(ANALYSIS_SCHEMA_FILENAME, ENV_ANALYSIS_SCHEMA)


def load_analysis_schema(path: str | Path | None = None) -> dict[str, Any]:
    schema_path = Path(path) if path is not None else find_analysis_schema()
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_analysis(
    data: dict[str, Any], schema: dict[str, Any] | None = None
) -> list[str]:
    """스키마 위반 목록. 빈 리스트면 통과다."""
    return validate(data, schema or load_analysis_schema())


def schema_for(data: dict[str, Any]) -> dict[str, Any]:
    """내용을 보고 두 스키마 중 하나를 고른다.

    두 파일은 최상위 키가 갈린다. 추출 결과에는 `meta` 가, 판정 결과에는 `criteria`
    가 있다. 둘 다 아니면 추출 스키마로 검증해 위반을 그대로 보여준다.
    """
    if isinstance(data, dict) and "criteria" in data:
        return load_analysis_schema()
    return load_schema()

"""cstat 명령.

    cstat calltree -c build/compile_commands.json -e process_frame -o calltree.json
    cstat analyze calltree.json -o analysis.json
    cstat validate analysis.json
    cstat doctor

단계마다 명령이 하나씩이다. `calltree` 는 소스를 훑어 사실을 뽑고, `analyze` 는 그
결과만 읽어 판단을 붙인다.

`validate` 가 여기 있는 이유는 두 스키마를 다 아는 곳이 여기뿐이기 때문이다.
`calltree` 도 `analyze` 도 상대의 스키마를 모르고, 알 필요도 없다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from analyze import cli as analyze_cli
from analyze.validation import schema_for
from calltree import cli as calltree_cli
from calltree.validation import load_schema, validate
from cstat import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cstat",
        description="정적 콜트리 추출과 오염 분석",
    )
    parser.add_argument("--version", action="version", version=f"cstat {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    calltree_cli.add_arguments(
        sub.add_parser(
            "calltree",
            help="소스를 훑어 콜트리를 뽑는다 (libclang 필요)",
            description="compile_commands.json 의 각 TU 를 파싱해 calltree.json 을 만든다.",
        )
    )
    analyze_cli.add_arguments(
        sub.add_parser(
            "analyze",
            help="콜트리를 오염 판정한다 (libclang 불필요)",
            description="calltree.json 을 읽어 analysis.json 을 만든다.",
        )
    )

    validate_cmd = sub.add_parser("validate", help="추출/판정 결과를 스키마로 검증")
    validate_cmd.add_argument("file", help="calltree.json 또는 analysis.json 경로")
    validate_cmd.add_argument(
        "--schema", help="스키마 파일 경로. 생략하면 내용을 보고 고른다"
    )

    calltree_cli.add_doctor_arguments(
        sub.add_parser("doctor", help="libclang 이 쓸 만한 상태인지 점검")
    )

    return parser


def run_validate(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    schema = load_schema(args.schema) if args.schema else schema_for(data)
    errors = validate(data, schema)
    if not errors:
        print("OK", file=sys.stderr)
        return 0
    for error in errors:
        print(f"스키마 위반: {error}", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "calltree":
        return calltree_cli.run(args)
    if args.command == "analyze":
        return analyze_cli.run(args)
    if args.command == "doctor":
        return calltree_cli.run_doctor(args)
    return run_validate(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""명령줄 인터페이스.

    calltree extract --compile-commands build/compile_commands.json \
                     --entry process_frame -o calltree.json
    calltree validate calltree.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from calltree import __version__
from calltree.compile_db import load_compile_commands
from calltree.extract import ExtractionResult, extract
from calltree.libclang_loader import LibclangUnavailable
from calltree.model import CallTree, Meta
from calltree.preflight import diagnose, run as preflight
from calltree.validation import load_schema, validate

#: libclang 문제로 아무 것도 하지 못하고 멈췄을 때의 종료 코드.
EXIT_LIBCLANG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calltree", description="정적 콜트리 추출기 (libclang)"
    )
    parser.add_argument("--version", action="version", version=f"calltree {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    extract_cmd = sub.add_parser("extract", help="compile_commands.json 으로 콜트리 추출")
    extract_cmd.add_argument(
        "-c",
        "--compile-commands",
        required=True,
        help="compile_commands.json 경로",
    )
    extract_cmd.add_argument(
        "-e",
        "--entry",
        required=True,
        help="진입점. 함수 이름 또는 USR(c: 로 시작)",
    )
    extract_cmd.add_argument(
        "-o", "--output", help="출력 파일. 생략하면 표준출력"
    )
    extract_cmd.add_argument(
        "--root",
        default=".",
        help="loc.file 을 상대경로로 만들 기준 디렉터리 (기본: 현재 디렉터리)",
    )
    extract_cmd.add_argument(
        "--include-system",
        action="store_true",
        help="시스템 헤더의 선언도 노드로 기록한다",
    )
    extract_cmd.add_argument("--libclang", help="libclang 공유 라이브러리 경로")
    extract_cmd.add_argument(
        "--validate", action="store_true", help="출력을 스키마로 검증한다"
    )
    extract_cmd.add_argument(
        "--strict",
        action="store_true",
        help="파싱 에러가 하나라도 있으면 실패로 처리한다",
    )
    extract_cmd.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨김")

    validate_cmd = sub.add_parser("validate", help="추출 결과를 스키마로 검증")
    validate_cmd.add_argument("file", help="calltree.json 경로")
    validate_cmd.add_argument("--schema", help="스키마 파일 경로")

    doctor_cmd = sub.add_parser("doctor", help="libclang 이 쓸 만한 상태인지 점검")
    doctor_cmd.add_argument("--libclang", help="libclang 공유 라이브러리 경로")

    return parser


def _resolve_entry(entry: str, result: ExtractionResult) -> str:
    """진입점 이름을 USR 로 바꾼다.

    이름으로 키를 잡으면 파일마다 있는 static `init()` 이 뭉치므로, 후보가 여럿이면
    USR 을 직접 지정하게 한다.
    """
    if entry.startswith("c:"):
        if entry not in result.nodes:
            raise SystemExit(f"진입점 USR 을 노드에서 찾을 수 없다: {entry}")
        return entry

    candidates = result.find_by_name(entry)
    definitions = [node for node in candidates if node.is_definition] or candidates
    if not definitions:
        raise SystemExit(f"진입점 함수를 찾을 수 없다: {entry}")
    if len(definitions) > 1:
        lines = "\n".join(
            f"  {node.usr}  ({node.loc.file}:{node.loc.line})" for node in definitions
        )
        raise SystemExit(f"진입점 이름이 모호하다: {entry}\n USR 로 지정해라:\n{lines}")
    return definitions[0].usr


def _run_extract(args: argparse.Namespace) -> int:
    # 무엇보다 먼저 점검한다. libclang 이 조금이라도 어긋나면 파일 하나 읽지 않고 멈춘다.
    try:
        report = preflight(library_file=args.libclang)
    except LibclangUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LIBCLANG
    version = report.clang_version

    commands = load_compile_commands(args.compile_commands)
    if not commands:
        print("compile_commands.json 이 비어 있다", file=sys.stderr)
        return 1

    total = len(commands)
    counter = {"n": 0}

    def progress(command) -> None:
        counter["n"] += 1
        print(f"[{counter['n']}/{total}] {command.file}", file=sys.stderr)

    result = extract(
        commands,
        root=args.root,
        include_system=args.include_system,
        progress=None if args.quiet else progress,
    )

    for failure in result.failed:
        print(f"파싱 실패: {failure}", file=sys.stderr)
    if result.diagnostics and not args.quiet:
        print(
            f"파싱 에러 진단 {len(result.diagnostics)}건 (앞 10건):", file=sys.stderr
        )
        for diagnostic in result.diagnostics[:10]:
            print(f"  {diagnostic}", file=sys.stderr)

    entry_usr = _resolve_entry(args.entry, result)
    tree = CallTree(
        meta=Meta(
            entry_point=entry_usr,
            compile_commands=str(args.compile_commands),
            clang_version=version,
            generated_at=datetime.now(timezone.utc).astimezone().isoformat(
                timespec="seconds"
            ),
            tu_count=result.tu_count,
        ),
        nodes=result.nodes,
        state=result.state,
    )

    data = tree.to_dict()
    exit_code = 0

    if args.validate:
        errors = validate(data)
        for error in errors:
            print(f"스키마 위반: {error}", file=sys.stderr)
        if errors:
            exit_code = 1

    if args.strict and (result.diagnostics or result.failed):
        print("--strict: 파싱 에러가 있어 실패로 처리한다", file=sys.stderr)
        exit_code = 1

    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        if not args.quiet:
            print(
                f"노드 {len(tree.nodes)}개, 상태 {len(tree.state)}개 -> {args.output}",
                file=sys.stderr,
            )
    else:
        sys.stdout.write(text)

    return exit_code


def _run_validate(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    errors = validate(data, load_schema(args.schema))
    if not errors:
        print("OK", file=sys.stderr)
        return 0
    for error in errors:
        print(f"스키마 위반: {error}", file=sys.stderr)
    return 1


def _run_doctor(args: argparse.Namespace) -> int:
    try:
        report = diagnose(library_file=args.libclang)
    except LibclangUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LIBCLANG

    print(report.summary())
    if report.ok:
        return 0
    print("\n이 상태로는 추출을 시작하지 않는다.", file=sys.stderr)
    return EXIT_LIBCLANG


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        return _run_extract(args)
    if args.command == "doctor":
        return _run_doctor(args)
    return _run_validate(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

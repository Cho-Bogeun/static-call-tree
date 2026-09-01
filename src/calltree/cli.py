"""추출 단계의 명령줄 인터페이스.

    cstat calltree -c build/compile_commands.json -e process_frame -o calltree.json
    cstat doctor

인자 정의와 실행만 담고 명령 이름은 정하지 않는다. 이름을 붙이고 서브명령으로 다는
것은 `cstat.cli` 의 몫이다. 판정 쪽은 `analyze.cli` 에 따로 있고, 이 모듈은 그쪽을
참조하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from calltree.compile_db import load_compile_commands
from calltree.extract import ExtractionResult, extract
from calltree.libclang_loader import LibclangUnavailable
from calltree.model import CallTree, Meta
from calltree.preflight import diagnose, run as preflight
from calltree.validation import validate

#: libclang 문제로 아무 것도 하지 못하고 멈췄을 때의 종료 코드.
EXIT_LIBCLANG = 2


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """추출 인자."""
    parser.add_argument(
        "-c",
        "--compile-commands",
        required=True,
        help="compile_commands.json 경로",
    )
    parser.add_argument(
        "-e",
        "--entry",
        required=True,
        help="진입점. 함수 이름 또는 USR(c: 로 시작)",
    )
    parser.add_argument("-o", "--output", help="출력 파일. 생략하면 표준출력")
    parser.add_argument(
        "--root",
        default=".",
        help="loc.file 을 상대경로로 만들 기준 디렉터리 (기본: 현재 디렉터리)",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="시스템 헤더의 선언도 노드로 기록한다",
    )
    parser.add_argument("--libclang", help="libclang 공유 라이브러리 경로")
    parser.add_argument(
        "--validate", action="store_true", help="출력을 스키마로 검증한다"
    )
    parser.add_argument(
        "--allow-parse-errors",
        action="store_true",
        help="파싱 에러가 있어도 종료 코드 0 으로 끝낸다 (기본은 실패)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="(옛 이름) 지금은 기본 동작이라 아무 효과가 없다",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨김")


def add_doctor_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--libclang", help="libclang 공유 라이브러리 경로")


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


def run(args: argparse.Namespace) -> int:
    """소스를 훑어 calltree.json 을 만든다."""
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

    # 파싱 에러는 "덜 뽑혔다"가 아니라 "틀리게 뽑혔다"다. clang 의 에러 복구는 해석에
    # 실패한 식별자를 인자로 쓰는 **호출식을 AST 에서 통째로 지우므로**, 진단이 있는
    # 콜트리는 엣지가 조용히 빠져 있다. 그 위에 세운 오염도와 "깨끗한 서브트리" 는
    # 볼 가치가 없으니 기본을 실패로 둔다.
    parse_errors_are_fatal = bool(result.diagnostics or result.failed) and not (
        args.allow_parse_errors
    )
    # 실패로 끝낼 참이면 -q 여도 이유는 보여준다. -q 는 진행 로그를 줄이는 것이지
    # 실패 사유를 감추는 것이 아니다.
    if result.diagnostics and (not args.quiet or parse_errors_are_fatal):
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

    if parse_errors_are_fatal:
        print(
            "파싱 에러가 있어 실패로 처리한다. 에러 복구가 호출식을 지우므로 이 "
            "콜트리는 엣지가 빠져 있다. 헤더 경로부터 확인해라 "
            "(빌트인 헤더가 없으면 stddef.h 를 못 찾는다). "
            "그래도 내보내려면 --allow-parse-errors 를 준다.",
            file=sys.stderr,
        )
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


def run_doctor(args: argparse.Namespace) -> int:
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

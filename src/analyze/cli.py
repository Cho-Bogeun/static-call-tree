"""판정 단계의 명령줄 인터페이스.

    cstat analyze calltree.json -o analysis.json

인자 정의와 실행만 담고 명령 이름은 정하지 않는다. 이름을 붙이고 서브명령으로 다는
것은 `cstat.cli` 의 몫이다.

libclang 이 필요 없다는 점이 추출 쪽과 다르다. 기준을 바꿔가며 몇 번을 돌려도
소스를 다시 읽지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analyze.contamination import EntryNotFound, analyze
from analyze.model import Criteria
from analyze.validation import validate_analysis
from calltree.model import CallTree


def add_criteria_arguments(parser: argparse.ArgumentParser) -> None:
    """오염 판정 기준 플래그. 전부 기본값에서 벗어나는 쪽으로만 준다.

    판정을 하는 명령이 `analyze` 하나가 아니게 되어(그림도 판정을 딛고 선다) 따로
    떼어 두었다. 기준의 정의가 두 벌이 되면 같은 이름의 플래그가 서로 다른 뜻을
    갖는 사고가 난다.
    """
    parser.add_argument(
        "--include-const",
        action="store_true",
        help="const 상태 접근도 오염원 근거로 센다 (기본: 제외)",
    )
    parser.add_argument(
        "--no-function-static",
        action="store_true",
        help="함수 내 static 을 오염원 근거에서 뺀다 (기본: 포함)",
    )
    parser.add_argument(
        "--addr-as",
        choices=["read", "write", "readwrite", "manual"],
        default="readwrite",
        help="주소만 취한 접근을 무엇으로 볼지 (기본: readwrite)",
    )
    parser.add_argument(
        "--const-read",
        action="store_true",
        help="읽기 전용 접근을 상수 취급해 오염원 근거에서 뺀다 (기본: 센다)",
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """판정 인자."""
    parser.add_argument("file", help="calltree.json 경로")
    parser.add_argument("-o", "--output", help="출력 파일. 생략하면 표준출력")
    add_criteria_arguments(parser)
    parser.add_argument(
        "--validate", action="store_true", help="출력을 스키마로 검증한다"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="요약 숨김")


def criteria_from(args: argparse.Namespace) -> Criteria:
    return Criteria(
        exclude_const=not args.include_const,
        include_function_static=not args.no_function_static,
        addr_as=args.addr_as,
        const_read=args.const_read,
    )


def run(args: argparse.Namespace) -> int:
    """calltree.json 을 읽어 analysis.json 을 만든다."""
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    tree = CallTree.from_dict(data)

    try:
        result = analyze(tree, criteria_from(args), source=str(args.file))
    except EntryNotFound as exc:
        raise SystemExit(str(exc)) from exc

    output = result.analysis.to_dict()
    exit_code = 0

    if args.validate:
        errors = validate_analysis(output)
        for error in errors:
            print(f"스키마 위반: {error}", file=sys.stderr)
        if errors:
            exit_code = 1

    text = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    if not args.quiet:
        print(result.summary(tree), file=sys.stderr)
        if args.output:
            print(f"\n판정 {len(output['nodes'])}개 -> {args.output}", file=sys.stderr)

    return exit_code

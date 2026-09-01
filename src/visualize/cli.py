"""그림 단계의 명령줄 인터페이스.

    cstat visualize calltree.json -o contamination.html

인자 정의와 실행만 담고 명령 이름은 정하지 않는다. 앞의 두 단계와 같은 모양이다.

판정 파일을 따로 주지 않으면 여기서 바로 판정한다. 기준을 바꿔가며 그림을 여러 장
뽑아 비교하는 것이 실제 사용법이고, 그때마다 `analyze` 를 먼저 돌리게 하면 두
파일의 기준이 어긋나 있어도 알 수 없기 때문이다. 이미 만들어 둔 판정을 그대로 쓸
때는 `--analysis` 로 준다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analyze import cli as analyze_cli
from analyze.contamination import EntryNotFound, analyze
from analyze.model import Analysis, Criteria
from calltree.model import CallTree
from visualize.render import render


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", help="calltree.json 경로")
    parser.add_argument("-o", "--output", help="출력 HTML. 생략하면 표준출력")
    parser.add_argument(
        "-a",
        "--analysis",
        help="이미 만든 analysis.json. 생략하면 같은 기준으로 여기서 판정한다",
    )
    analyze_cli.add_criteria_arguments(parser)
    parser.add_argument("-q", "--quiet", action="store_true", help="요약 숨김")


def load_analysis(path: str, tree: CallTree) -> Analysis:
    """판정 파일을 읽고 이 콜트리에서 나온 것인지 확인한다.

    두 파일은 USR 을 키로 조인된다. 어긋난 짝을 그리면 노드가 조용히 사라지거나
    엉뚱한 색이 칠해지는데, 그림에서는 그게 눈에 띄지 않는다. 여기서 막는다.
    """
    analysis = Analysis.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    unknown = sorted(set(analysis.nodes) - set(tree.nodes))
    if unknown:
        raise SystemExit(
            f"판정 파일이 이 콜트리에서 나온 것이 아니다. "
            f"콜트리에 없는 USR {len(unknown)}개: {unknown[0]}"
        )
    if tree.meta.entry_point not in analysis.nodes:
        raise SystemExit(
            f"판정 파일에 진입점이 없다: {tree.meta.entry_point}. "
            f"다른 진입점으로 만든 판정으로 보인다."
        )
    return analysis


def run(args: argparse.Namespace) -> int:
    """calltree.json (+ analysis.json) 을 읽어 HTML 한 장을 만든다."""
    tree = CallTree.from_dict(
        json.loads(Path(args.file).read_text(encoding="utf-8"))
    )
    criteria = analyze_cli.criteria_from(args)

    if args.analysis:
        # 기준은 판정 파일에 이미 들어 있다. 여기서 또 받으면 그림의 범례와 파일의
        # criteria 가 어긋나도 아무도 모른다.
        if criteria != Criteria():
            raise SystemExit(
                "--analysis 와 기준 플래그는 같이 줄 수 없다. "
                "기준은 판정 파일의 criteria 를 쓴다."
            )
        analysis = load_analysis(args.analysis, tree)
    else:
        try:
            analysis = analyze(tree, criteria, source=str(args.file)).analysis
        except EntryNotFound as exc:
            raise SystemExit(str(exc)) from exc

    html = render(tree, analysis)
    if args.output:
        Path(args.output).write_text(html, encoding="utf-8")
    else:
        sys.stdout.write(html)

    if not args.quiet:
        impure = [v for v in analysis.nodes.values() if v.is_impure]
        roots = [v for v in analysis.nodes.values() if v.is_clean_subtree_root]
        entry = tree.nodes[tree.meta.entry_point].name
        print(
            f"진입점 {entry} · 노드 {len(analysis.nodes)}개 · "
            f"오염원 {len(impure)}개 · 깨끗한 경계 {len(roots)}개",
            file=sys.stderr,
        )
        if args.output:
            print(f"그림 -> {args.output}", file=sys.stderr)

    return 0

"""페이로드와 에셋을 합쳐 **파일 하나로 도는 HTML** 을 만든다.

바깥을 참조하지 않는다. CDN 도 없고 이미지도 없다. 이 그림은 보통 빌드 서버나
망이 끊긴 개발 장비에서 열리고, 며칠 뒤 다시 열어 이전 그림과 겹쳐 봐야 하는
물건이다(§8). 링크가 하나라도 살아 있으면 그때 깨진다.

CSS 와 JS 를 파이썬 문자열이 아니라 `assets/` 의 진짜 파일로 둔 이유도 같다.
그림의 규칙(색, 배치, 인터랙션)은 앞으로 계속 손댈 곳이라 편집기가 문법을 아는
채로 두는 편이 낫다. 여기서는 자리를 채워 넣기만 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analyze.model import Analysis
from calltree.model import CallTree
from visualize.payload import build_payload

ASSETS = Path(__file__).parent / "assets"

TEMPLATE = "report.html"
STYLE = "report.css"
SCRIPT = "report.js"


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def embed(payload: dict[str, Any]) -> str:
    """`<script>` 안에 안전하게 넣을 수 있는 JSON.

    `</script>` 가 문자열 안에 있으면 문서가 거기서 끊긴다. C 함수명에 `<` 가
    들어갈 일은 없지만, 파일 경로는 우리가 만든 문자열이 아니다.
    """
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def render(tree: CallTree, analysis: Analysis) -> str:
    """자립 HTML 한 장. 같은 입력이면 같은 문자열이 나온다(§8)."""
    payload = build_payload(tree, analysis)
    entry = payload["nodes"][payload["entry"]]["name"]

    return (
        _asset(TEMPLATE)
        .replace("__TITLE__", _escape(f"{entry} — 오염도"))
        .replace("/*__CSS__*/", _asset(STYLE))
        .replace("/*__JS__*/", _asset(SCRIPT))
        .replace('"__DATA__"', embed(payload))
    )

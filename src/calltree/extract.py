"""libclang AST 순회.

콜 엣지와 상태 접근을 **같은 순회에서 동시에** 얻는다. 기록하는 것은 관측 가능한
사실뿐이고, 오염원 판정 같은 해석은 하지 않는다.

libclang 파이썬 바인딩은 버전마다 `CursorKind` 상수 구성이 달라서, 커서 종류는
`cursor.kind.name` 문자열로 비교한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from calltree.compile_db import CompileCommand
from calltree.libclang_loader import load
from calltree.merge import merge_node, merge_nodes, merge_state, merge_state_var
from calltree.model import (
    Access,
    Call,
    FunctionNode,
    Linkage,
    Loc,
    Param,
    StateUse,
    StateVar,
    UnresolvedCall,
)

#: lvalue 성질을 그대로 위로 전달하는 커서. `(x)`, 암시적 캐스트 따위.
_TRANSPARENT_KINDS = frozenset(
    {
        "UNEXPOSED_EXPR",
        "PAREN_EXPR",
        "CSTYLE_CAST_EXPR",
        "FIRST_EXPR",
    }
)

_ASM_KINDS = frozenset({"ASM_STMT", "GCC_ASM_STMT", "MS_ASM_STMT"})

_ARRAY_TYPE_KINDS = frozenset(
    {"CONSTANTARRAY", "INCOMPLETEARRAY", "VARIABLEARRAY", "DEPENDENTSIZEDARRAY"}
)

_POINTER_LIKE_DECLS = frozenset({"VAR_DECL", "PARM_DECL", "FIELD_DECL"})

#: 선언을 감싸기만 하는 커서. 안쪽을 계속 훑어야 한다.
_DECL_CONTAINER_KINDS = frozenset({"LINKAGE_SPEC", "UNEXPOSED_DECL"})


@dataclass
class TUResult:
    """TU 하나의 추출 결과."""

    path: str
    nodes: dict[str, FunctionNode] = field(default_factory=dict)
    state: dict[str, StateVar] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    has_errors: bool = False


@dataclass
class ExtractionResult:
    """TU 전체를 병합한 결과."""

    nodes: dict[str, FunctionNode] = field(default_factory=dict)
    state: dict[str, StateVar] = field(default_factory=dict)
    tu_count: int = 0
    diagnostics: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def find_by_name(self, name: str) -> list[FunctionNode]:
        """표시용 이름으로 노드를 찾는다. static 함수는 파일마다 있으므로 복수일 수 있다."""
        return [node for node in self.nodes.values() if node.name == name]


class TUExtractor:
    """TU 하나를 파싱해 `TUResult` 로 만든다."""

    def __init__(self, root: str | Path = ".", include_system: bool = False) -> None:
        self.ci = load()
        self.root = Path(root).resolve()
        self.include_system = include_system
        self.index = self.ci.Index.create()
        #: 현재 TU 의 작업 디렉터리. clang 이 돌려주는 상대 경로의 기준이다.
        self._base = self.root

    # ------------------------------------------------------------------ 파싱

    def parse_command(self, command: CompileCommand) -> TUResult:
        return self.parse(
            command.abs_file, command.clang_args(), directory=command.directory
        )

    def parse(
        self,
        path: str | Path,
        args: Sequence[str] | None = None,
        directory: str | Path | None = None,
    ) -> TUResult:
        self._base = Path(directory).resolve() if directory else self.root
        tu = self.index.parse(str(path), args=list(args or []))
        return self.extract(tu, str(path))

    def extract(self, tu: Any, path: str) -> TUResult:
        result = TUResult(path=path)
        error_severity = self.ci.Diagnostic.Error
        for diagnostic in tu.diagnostics:
            if diagnostic.severity >= error_severity:
                result.has_errors = True
                result.diagnostics.append(str(diagnostic))
        for cursor in tu.cursor.get_children():
            self._visit_top_level(cursor, result)
        return result

    # ------------------------------------------------------------- 최상위 선언

    def _visit_top_level(self, cursor: Any, result: TUResult) -> None:
        if not self.include_system and self._is_system(cursor):
            return
        kind = cursor.kind.name
        if kind == "FUNCTION_DECL":
            self._visit_function(cursor, result)
        elif kind == "VAR_DECL":
            self._register_var(cursor, result)
        elif kind in _DECL_CONTAINER_KINDS:
            for child in cursor.get_children():
                self._visit_top_level(child, result)

    def _visit_function(self, cursor: Any, result: TUResult) -> None:
        usr = cursor.get_usr()
        if not usr:
            return
        is_definition = cursor.is_definition()
        node = FunctionNode(
            usr=usr,
            name=cursor.spelling,
            linkage=self._linkage(cursor),
            kind="definition" if is_definition else "declaration",
            loc=self._loc(cursor.location),
            return_type=cursor.result_type.spelling,
            params=[
                Param(name=arg.spelling, type=arg.type.spelling)
                for arg in (cursor.get_arguments() or [])
            ],
        )
        stored = merge_node(result.nodes, node)
        if not is_definition or stored is not node:
            # 이미 정의를 본 함수(헤더 inline 의 중복 전개)는 다시 훑지 않는다.
            return
        for child in cursor.get_children():
            if child.kind.name == "PARM_DECL":
                continue
            self._visit_body(child, node, (), result)

    # ------------------------------------------------------------------ 본문

    def _visit_body(
        self, cursor: Any, node: FunctionNode, parents: tuple[Any, ...], result: TUResult
    ) -> None:
        kind = cursor.kind.name
        if kind == "CALL_EXPR":
            self._record_call(cursor, node, result)
        elif kind == "DECL_REF_EXPR":
            self._record_state_use(cursor, node, parents, result)
        elif kind == "VAR_DECL":
            self._register_var(cursor, result)
        elif kind in _ASM_KINDS:
            node.unresolved_calls.append(
                UnresolvedCall(
                    loc=self._loc(cursor.location),
                    expr=self._text(cursor) or "asm",
                    reason="inline_asm",
                )
            )

        child_parents = parents + (cursor,)
        for child in cursor.get_children():
            self._visit_body(child, node, child_parents, result)

    def _record_call(self, cursor: Any, node: FunctionNode, result: TUResult) -> None:
        loc = self._loc(cursor.location)
        referenced = cursor.referenced
        if referenced is not None and referenced.kind.name == "FUNCTION_DECL":
            callee = referenced.get_usr()
            if callee:
                # 시스템 헤더 선언이라 최상위 순회에서 걸러진 콜리도
                # 노드 테이블에 있어야 `calls` 의 참조가 깨지지 않는다.
                self._ensure_declaration_node(referenced, result)
                node.calls.append(Call(callee=callee, loc=loc))
                return

        node.unresolved_calls.append(
            UnresolvedCall(
                loc=loc,
                expr=self._callee_text(cursor),
                reason=self._unresolved_reason(cursor, referenced),
            )
        )

    def _record_state_use(
        self, cursor: Any, node: FunctionNode, parents: tuple[Any, ...], result: TUResult
    ) -> None:
        referenced = cursor.referenced
        if referenced is None or referenced.kind.name != "VAR_DECL":
            return
        var = self._register_var(referenced, result)
        if var is None:
            return
        node.state_uses.append(
            StateUse(
                target=var.usr,
                access=self._classify_access(cursor, parents, referenced),
                loc=self._loc(cursor.location),
            )
        )

    # ------------------------------------------------------------------ 상태

    def _register_var(self, cursor: Any, result: TUResult) -> StateVar | None:
        """전역 / 함수 내 static 이면 상태 테이블에 넣는다. 지역 자동 변수는 상태가 아니다."""
        if cursor.kind.name != "VAR_DECL":
            return None
        usr = cursor.get_usr()
        if not usr:
            return None

        parent = cursor.semantic_parent
        parent_kind = parent.kind.name if parent is not None else ""
        is_const = cursor.type.is_const_qualified()

        if parent_kind == "TRANSLATION_UNIT":
            # `int g_flag;` 은 tentative definition 이라 is_definition() 이 False 다.
            # 헤더의 `extern int g_flag;` 보다는 이쪽이 정의에 가깝다.
            is_definition = (
                cursor.is_definition() or cursor.storage_class.name != "EXTERN"
            )
            var = StateVar(
                usr=usr,
                name=cursor.spelling,
                type=cursor.type.spelling,
                scope="file_global",
                linkage=self._linkage(cursor),
                is_const=is_const,
                loc=self._loc(cursor.location),
                is_definition=is_definition,
            )
            return merge_state_var(result.state, var)

        if cursor.storage_class.name == "STATIC":
            var = StateVar(
                usr=usr,
                name=cursor.spelling,
                type=cursor.type.spelling,
                scope="function_static",
                linkage="internal",
                is_const=is_const,
                loc=self._loc(cursor.location),
                owner=parent.get_usr() if parent is not None else None,
                is_definition=True,
            )
            return merge_state_var(result.state, var)

        return None

    # --------------------------------------------------------------- access

    def _classify_access(
        self, ref: Any, parents: tuple[Any, ...], referenced: Any
    ) -> Access:
        """참조 지점의 문맥을 위로 훑어 접근 방향을 정한다.

        판정할 수 없는 것(주소를 넘긴 뒤의 사용)은 `addr` 로 남긴다. 배열명이
        포인터로 감쇠하는 경우도 마찬가지다.
        """
        node = ref
        subscripted = False

        for parent in reversed(parents):
            kind = parent.kind.name

            if kind in _TRANSPARENT_KINDS or kind == "MEMBER_REF_EXPR":
                node = parent
                continue

            if kind == "ARRAY_SUBSCRIPT_EXPR":
                children = list(parent.get_children())
                if children and self._contains(children[0], node):
                    subscripted = True
                    node = parent
                    continue
                return "read"  # 첨자 위치의 참조는 읽기다

            if kind == "UNARY_OPERATOR":
                operator = self._unary_operator(parent)
                if operator == "&":
                    return "addr"
                if operator in ("++", "--"):
                    return "readwrite"
                break  # `*p`, `-x` 등: 변수 자체는 읽기

            if kind == "COMPOUND_ASSIGNMENT_OPERATOR":
                return "readwrite" if self._is_lhs(parent, node) else "read"

            if kind == "BINARY_OPERATOR":
                if self._is_lhs(parent, node) and self._binary_operator(parent) == "=":
                    return "write"
                break

            break

        if not subscripted and referenced.type.kind.name in _ARRAY_TYPE_KINDS:
            # 배열명이 포인터로 감쇠했다. 이후 방향은 정적으로 알 수 없다.
            return "addr"
        return "read"

    def _is_lhs(self, parent: Any, node: Any) -> bool:
        children = list(parent.get_children())
        return bool(children) and self._contains(children[0], node)

    @staticmethod
    def _contains(outer: Any, inner: Any) -> bool:
        outer_extent, inner_extent = outer.extent, inner.extent
        return (
            outer_extent.start.offset <= inner_extent.start.offset
            and inner_extent.end.offset <= outer_extent.end.offset
        )

    @staticmethod
    def _binary_operator(cursor: Any) -> str | None:
        """이항 연산자의 철자.

        바인딩에 `cursor.binary_operator` 가 없는 버전이 많아 토큰으로 읽는다.
        좌변의 extent 가 끝난 뒤 처음 나오는 토큰이 연산자다.
        """
        children = list(cursor.get_children())
        if len(children) != 2:
            return None
        lhs_end = children[0].extent.end.offset
        for token in cursor.get_tokens():
            if token.extent.start.offset >= lhs_end:
                return token.spelling
        return None

    @staticmethod
    def _unary_operator(cursor: Any) -> str | None:
        tokens = [token.spelling for token in cursor.get_tokens()]
        if not tokens:
            return None
        if tokens[0] in {"&", "*", "++", "--", "-", "+", "!", "~"}:
            return tokens[0]
        if tokens[-1] in {"++", "--"}:
            return tokens[-1]
        return None

    # ------------------------------------------------------------- 미해석 호출

    def _unresolved_reason(self, cursor: Any, referenced: Any) -> str:
        if referenced is not None and referenced.kind.name in _POINTER_LIKE_DECLS:
            return "function_pointer"
        callee = next(iter(cursor.get_children()), None)
        if callee is not None and self._is_function_pointer(callee.type):
            return "function_pointer"
        return "unknown"

    @staticmethod
    def _is_function_pointer(type_: Any) -> bool:
        try:
            if type_.kind.name == "POINTER":
                return type_.get_pointee().kind.name in {
                    "FUNCTIONPROTO",
                    "FUNCTIONNOPROTO",
                }
        except Exception:  # pragma: no cover - 바인딩이 못 다루는 타입
            return False
        return False

    def _callee_text(self, cursor: Any) -> str:
        callee = next(iter(cursor.get_children()), None)
        text = self._text(callee) if callee is not None else ""
        return text or self._text(cursor) or "<unknown>"

    @staticmethod
    def _text(cursor: Any, limit: int = 120) -> str:
        try:
            tokens = [token.spelling for token in cursor.get_tokens()]
        except Exception:  # pragma: no cover - 매크로 확장 등
            return ""
        text = " ".join(tokens).strip()
        return text[:limit]

    # ------------------------------------------------------------------ 유틸

    def _ensure_declaration_node(self, cursor: Any, result: TUResult) -> None:
        usr = cursor.get_usr()
        if not usr or usr in result.nodes:
            return
        result.nodes[usr] = FunctionNode(
            usr=usr,
            name=cursor.spelling,
            linkage=self._linkage(cursor),
            kind="definition" if cursor.is_definition() else "declaration",
            loc=self._loc(cursor.location),
            return_type=cursor.result_type.spelling,
            params=[
                Param(name=arg.spelling, type=arg.type.spelling)
                for arg in (cursor.get_arguments() or [])
            ],
        )

    @staticmethod
    def _linkage(cursor: Any) -> Linkage:
        return "internal" if cursor.linkage.name != "EXTERNAL" else "external"

    def _loc(self, location: Any) -> Loc:
        file = location.file
        line = location.line or 1
        if file is None:
            return Loc(file="<builtin>", line=line)
        return Loc(file=self._relative(file.name), line=line)

    def _relative(self, path: str) -> str:
        candidate = Path(path)
        if not candidate.is_absolute():
            # clang 은 `-working-directory` 기준의 상대 경로를 돌려준다.
            candidate = self._base / candidate
        try:
            candidate = candidate.resolve()
        except OSError:  # pragma: no cover - 해석 불가한 경로
            pass
        try:
            return candidate.relative_to(self.root).as_posix()
        except ValueError:
            return candidate.as_posix()

    @staticmethod
    def _is_system(cursor: Any) -> bool:
        location = cursor.location
        return location.file is None or location.is_in_system_header


def extract(
    commands: Iterable[CompileCommand],
    root: str | Path = ".",
    include_system: bool = False,
    progress: Callable[[CompileCommand], None] | None = None,
) -> ExtractionResult:
    """TU 목록을 모두 파싱해 USR 로 병합한다."""
    extractor = TUExtractor(root=root, include_system=include_system)
    result = ExtractionResult()

    for command in commands:
        if progress is not None:
            progress(command)
        try:
            tu_result = extractor.parse_command(command)
        except Exception as exc:  # 한 TU 가 죽어도 나머지는 계속 뽑는다
            result.failed.append(f"{command.file}: {exc}")
            continue

        result.tu_count += 1
        result.diagnostics.extend(tu_result.diagnostics)
        merge_nodes(result.nodes, tu_result.nodes)
        merge_state(result.state, tu_result.state)

    return result

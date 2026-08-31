"""실제 libclang 으로 픽스처 C 프로젝트를 훑어 관측 사실을 확인한다."""

from __future__ import annotations

import pytest

from calltree.extract import ExtractionResult, TUExtractor, extract
from calltree.model import FunctionNode

from conftest import FIXTURE_ROOT, make_commands, requires_libclang

pytestmark = requires_libclang


@pytest.fixture(scope="module")
def result() -> ExtractionResult:
    return extract(make_commands(), root=FIXTURE_ROOT)


def node_by_name(result: ExtractionResult, name: str) -> FunctionNode:
    matches = result.find_by_name(name)
    assert len(matches) == 1, f"{name}: {[n.usr for n in matches]}"
    return matches[0]


def accesses(node: FunctionNode, result: ExtractionResult) -> set[tuple[str, str]]:
    return {(result.state[use.target].name, use.access) for use in node.state_uses}


def callee_names(node: FunctionNode, result: ExtractionResult) -> list[str]:
    return sorted(result.nodes[call.callee].name for call in node.calls)


# ------------------------------------------------------------------ 노드


def test_parses_every_tu_without_errors(result: ExtractionResult):
    assert result.tu_count == 3
    assert result.failed == []
    assert result.diagnostics == []


def test_definition_records_signature_and_location(result: ExtractionResult):
    node = result.nodes["c:@F@process_frame"]
    assert node.name == "process_frame"
    assert node.kind == "definition"
    assert node.linkage == "external"
    assert node.return_type == "int"
    assert [(p.name, p.type) for p in node.params] == [("v", "int")]
    assert node.loc.file == "src/proc.c"


def test_static_function_is_internal(result: ExtractionResult):
    assert result.nodes["c:proc.c@F@reset"].linkage == "internal"


def test_same_named_statics_do_not_collide(result: ExtractionResult):
    resets = sorted(node.usr for node in result.find_by_name("reset"))
    assert resets == ["c:aux.c@F@reset", "c:proc.c@F@reset"]
    # USR 에 파일 경로가 들어가므로 두 노드는 별개다.
    assert result.nodes["c:proc.c@F@reset"].loc.file == "src/proc.c"
    assert result.nodes["c:aux.c@F@reset"].loc.file == "src/aux.c"


def test_undefined_function_is_a_declaration_leaf(result: ExtractionResult):
    for usr in ("c:@F@ext_lib", "c:@F@sink"):
        node = result.nodes[usr]
        assert node.kind == "declaration"
        assert node.calls == []
        assert node.state_uses == []
        assert node.unresolved_calls == []
        assert node.loc.file == "include/common.h"


def test_header_inline_is_deduped_across_tus(result: ExtractionResult):
    """common.h 는 3개 TU 에 들어가지만 clamp 노드는 하나여야 한다."""
    clamp = node_by_name(result, "clamp")
    assert clamp.usr == "c:common.h@F@clamp"
    assert clamp.kind == "definition"
    assert clamp.linkage == "internal"


# ------------------------------------------------------------------ 콜 엣지


def test_calls_are_recorded_per_call_site(result: ExtractionResult):
    node = result.nodes["c:@F@process_frame"]
    assert callee_names(node, result) == [
        "clamp",
        "dispatch",
        "ext_lib",
        "reset",
        "sink",
        "sink",  # 호출이 두 번이면 두 번 기록된다
    ]
    # static 함수 호출은 같은 파일의 reset 으로 해석되어야 한다.
    reset_calls = [c for c in node.calls if c.callee.endswith("@F@reset")]
    assert [c.callee for c in reset_calls] == ["c:proc.c@F@reset"]
    assert all(call.loc.file == "src/proc.c" for call in node.calls)


def test_function_pointer_call_is_unresolved(result: ExtractionResult):
    dispatch = result.nodes["c:proc.c@F@dispatch"]
    assert dispatch.calls == []
    assert len(dispatch.unresolved_calls) == 1

    unresolved = dispatch.unresolved_calls[0]
    assert unresolved.reason == "function_pointer"
    assert unresolved.expr == "fn"
    assert unresolved.loc.file == "src/proc.c"


def test_inline_asm_is_recorded_as_unresolved(result: ExtractionResult):
    node = result.nodes["c:@F@aux_barrier"]
    assert node.calls == []
    assert [u.reason for u in node.unresolved_calls] == ["inline_asm"]
    assert node.unresolved_calls[0].expr
    assert node.unresolved_calls[0].loc.file == "src/aux.c"


def test_resolved_call_sites_leave_no_unresolved(result: ExtractionResult):
    assert result.nodes["c:@F@process_frame"].unresolved_calls == []


# ------------------------------------------------------------------ 상태 접근


def test_state_uses_capture_access_direction(result: ExtractionResult):
    node = result.nodes["c:@F@process_frame"]
    assert accesses(node, result) == {
        ("retry_cnt", "readwrite"),  # retry_cnt++
        ("retry_cnt", "read"),  # g_buf[retry_cnt]
        ("g_flag", "readwrite"),  # g_flag += v
        ("g_flag", "addr"),  # sink(&g_flag)
        ("g_buf", "addr"),  # sink(g_buf) — 배열 감쇠
        ("g_buf", "read"),  # g_buf[retry_cnt]
        ("g_cfg", "read"),
    }


def test_plain_assignment_is_write(result: ExtractionResult):
    reset = result.nodes["c:proc.c@F@reset"]
    assert accesses(reset, result) == {("g_buf", "write"), ("g_flag", "write")}
    # g_buf[0] = 0 은 배열 첨자를 거친 쓰기다. addr 로 뭉뚱그리지 않는다.
    g_buf_use = next(
        use for use in reset.state_uses if result.state[use.target].name == "g_buf"
    )
    assert g_buf_use.access == "write"


def test_state_use_targets_point_into_state_table(result: ExtractionResult):
    for node in result.nodes.values():
        for use in node.state_uses:
            assert use.target in result.state
        for call in node.calls:
            assert call.callee in result.nodes


# ------------------------------------------------------------------ 상태 테이블


def test_file_global_records_constness(result: ExtractionResult):
    g_cfg = result.state["c:@g_cfg"]
    assert g_cfg.scope == "file_global"
    assert g_cfg.linkage == "external"
    assert g_cfg.is_const is True
    assert g_cfg.owner is None
    # 헤더의 extern 선언이 아니라 정의 위치를 남긴다.
    assert g_cfg.loc.file == "src/cfg.c"


def test_tentative_definition_beats_extern_declaration(result: ExtractionResult):
    assert result.state["c:@g_flag"].loc.file == "src/cfg.c"
    assert result.state["c:@g_flag"].is_const is False


def test_static_global_is_internal(result: ExtractionResult):
    g_buf = result.state["c:proc.c@g_buf"]
    assert g_buf.linkage == "internal"
    assert g_buf.scope == "file_global"
    assert g_buf.type == "int[4]"


def test_function_static_is_state_with_owner(result: ExtractionResult):
    retry = next(
        var for var in result.state.values() if var.name == "retry_cnt"
    )
    assert retry.scope == "function_static"
    assert retry.linkage == "internal"
    assert retry.owner == "c:@F@process_frame"
    assert retry.loc.file == "src/proc.c"
    # 알려진 한계: 로컬 USR 에 파일 오프셋이 들어간다.
    assert retry.usr.startswith("c:proc.c@")


def test_local_automatic_variables_are_not_state(result: ExtractionResult):
    names = {var.name for var in result.state.values()}
    assert names == {"g_cfg", "g_flag", "g_buf", "reset_count", "retry_cnt"}


# ------------------------------------------------------------------ TU 단위


def test_single_tu_sees_only_its_own_static(tmp_path):
    extractor = TUExtractor(root=FIXTURE_ROOT)
    command = next(c for c in make_commands() if c.file.endswith("proc.c"))
    tu_result = extractor.parse_command(command)

    assert "c:proc.c@F@reset" in tu_result.nodes
    assert "c:aux.c@F@reset" not in tu_result.nodes
    assert not tu_result.has_errors

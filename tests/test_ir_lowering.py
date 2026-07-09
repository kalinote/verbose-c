import pytest

from verbose_c.compiler.ir import format_ir_program, lower_bytecode_unit_to_ir, lower_compiler_output_to_ir
from verbose_c.compiler.ir.model import IRLoweringError
from verbose_c.compiler.opcode import Opcode
from verbose_c.engine.engine import CompilerOutput, run_source_file
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_string import VBCString


def _lower(bytecode, constants=None):
    return lower_bytecode_unit_to_ir(
        name="test",
        bytecode=bytecode,
        constants=constants or [VBCInteger(1), VBCInteger(2), VBCBool(True), VBCString("s")],
        lineno_table=[(0, 10), (2, 12)],
    )


def test_ir_lowering_lowers_constants_arithmetic_and_return():
    function = _lower([
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.ADD,),
        (Opcode.RETURN,),
    ])

    block = function.blocks[0]
    assert [instruction.op for instruction in block.instructions] == ["const", "const", "binary add"]
    assert block.terminator.op == "return"
    assert block.terminator.args[0].kind == "temp"


def test_ir_lowering_tracks_local_load_and_store_def_use():
    function = _lower([
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.STORE_LOCAL_VAR, 0),
        (Opcode.LOAD_LOCAL_VAR, 0),
        (Opcode.RETURN,),
    ])

    ops = [instruction.op for instruction in function.blocks[0].instructions]
    assert ops == ["const", "store_local", "load_local"]
    assert function.blocks[0].instructions[1].args[0].kind == "local"


def test_ir_lowering_lowers_function_call():
    function = _lower([
        (Opcode.LOAD_GLOBAL_VAR, "foo"),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.CALL_FUNCTION, 1),
        (Opcode.RETURN,),
    ])

    call = function.blocks[0].instructions[2]
    assert call.op == "call"
    assert call.attrs["argc"] == 1
    assert call.args[0].kind == "temp"


def test_ir_lowering_builds_if_else_cfg():
    function = _lower([
        (Opcode.LOAD_CONSTANT, 2),
        (Opcode.JUMP_IF_FALSE, 5),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.STORE_LOCAL_VAR, 0),
        (Opcode.JUMP, 7),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.STORE_LOCAL_VAR, 0),
        (Opcode.LOAD_LOCAL_VAR, 0),
        (Opcode.RETURN,),
    ])

    assert len(function.blocks) >= 3
    branch = function.blocks[0].terminator
    assert branch.op == "branch"
    assert len(function.blocks[0].successors) == 2


def test_ir_lowering_builds_loop_back_edge_cfg():
    function = _lower([
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.STORE_LOCAL_VAR, 0),
        (Opcode.LOAD_LOCAL_VAR, 0),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.LESS_THAN,),
        (Opcode.JUMP_IF_FALSE, 11),
        (Opcode.LOAD_LOCAL_VAR, 0),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.ADD,),
        (Opcode.STORE_LOCAL_VAR, 0),
        (Opcode.JUMP, 2),
        (Opcode.LOAD_LOCAL_VAR, 0),
        (Opcode.RETURN,),
    ])

    block_starts = {block.name: block.start_pc for block in function.blocks}
    assert any(
        block_starts[successor] < block.start_pc
        for block in function.blocks
        for successor in block.successors
    )


def test_ir_lowering_simulates_dup_pop_and_swap():
    function = _lower([
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.DUP,),
        (Opcode.POP,),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.SWAP,),
        (Opcode.SUBTRACT,),
        (Opcode.RETURN,),
    ])

    ops = [instruction.op for instruction in function.blocks[0].instructions]
    assert "discard" in ops
    assert ops[-1] == "binary sub"


def test_ir_lowering_reports_invalid_constant_with_context():
    with pytest.raises(IRLoweringError) as exc_info:
        _lower([(Opcode.LOAD_CONSTANT, 99)])

    message = str(exc_info.value)
    assert "LOAD_CONSTANT" in message
    assert "PC 0" in message
    assert "函数 test" in message


def test_ir_lowering_reports_stack_underflow():
    with pytest.raises(IRLoweringError) as exc_info:
        _lower([(Opcode.ADD,)])

    assert "模拟栈为空" in str(exc_info.value)


def test_ir_lowering_uses_phi_for_merge_stack_values():
    function = _lower([
        (Opcode.LOAD_CONSTANT, 2),
        (Opcode.JUMP_IF_FALSE, 4),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.JUMP, 5),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.ADD,),
        (Opcode.RETURN,),
    ])

    assert any(
        instruction.op == "phi"
        for block in function.blocks
        for instruction in block.instructions
    )


def test_ir_lowering_lowers_memory_and_pointer_opcodes():
    function = _lower([
        (Opcode.ALLOC_ARRAY, (3, "INT")),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.LOAD_INDEX, (3, "INT")),
        (Opcode.LOAD_ADDRESS, (0, "INT")),
        (Opcode.STORE_BY_POINTER,),
        (Opcode.LOAD_ADDRESS, (0, "INT")),
        (Opcode.LOAD_BY_POINTER,),
        (Opcode.RETURN,),
    ])

    ops = [instruction.op for block in function.blocks for instruction in block.instructions]
    assert "alloc_array" in ops
    assert "load_index" in ops
    assert "address_of" in ops
    assert "store_pointer" in ops
    assert "load_pointer" in ops


def test_ir_lowering_lowers_struct_field_opcodes():
    function = _lower([
        (Opcode.ALLOC_STRUCT, 0),
        (Opcode.DUP,),
        (Opcode.LOAD_FIELD, (2, 1)),
        (Opcode.SWAP,),
        (Opcode.STORE_FIELD, (2, 0)),
        (Opcode.COPY_STRUCT, 2),
        (Opcode.RETURN,),
    ])

    ops = [instruction.op for block in function.blocks for instruction in block.instructions]
    assert "alloc_struct" in ops
    assert "load_field" in ops
    assert "store_field" in ops
    assert "copy_struct" in ops


def test_ir_lowering_attaches_program_to_compiler_output():
    output = CompilerOutput(
        bytecode=[(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)],
        constant_pool=[VBCInteger(1)],
        function_compilation_results={
            "id": {
                "bytecode": [(Opcode.LOAD_LOCAL_VAR, 0), (Opcode.RETURN,)],
                "constants": [],
                "param_count": 1,
                "local_count": 1,
            }
        },
    )

    program = lower_compiler_output_to_ir(output)

    assert program.module.name == "<module>"
    assert "id" in program.functions


def test_ir_formatter_outputs_blocks_successors_and_lines():
    function = _lower([(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)])
    text = format_ir_program(type("Program", (), {"module": function, "functions": {}})())

    assert "## IR" in text
    assert "bb_0" in text
    assert "后继基本块" in text
    assert "line 10" in text


def test_dump_ir_from_source_file(tmp_path):
    source_path = tmp_path / "ir_source.vbc"
    source_path.write_text("int main() {\n    return 0;\n}\n", encoding="utf-8")
    dump_path = tmp_path / "ir_dump.md"
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"ir"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "ir_source.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "## IR" in dump_text
    assert "bb_" in dump_text
    assert "后继基本块" in dump_text


def test_dump_ir_from_loop_source_file(tmp_path):
    dump_path = tmp_path / "ir_loop_dump.md"
    result = run_source_file(
        "tests/grammar/ir_loop_phi_test.vbc",
        log_modules=set(),
        dump_modules={"ir"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "ir_loop_phi.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "phi" in dump_text
    assert "后继基本块" in dump_text

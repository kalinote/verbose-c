import pytest

from verbose_c.compiler.ir import lower_bytecode_unit_to_ir
from verbose_c.compiler.native import NativeLoweringError, format_machine_program, lower_ir_program_to_machine
from verbose_c.compiler.opcode import Opcode
from verbose_c.engine.engine import CompilerOutput, run_source_file
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.function import VBCFunction
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_string import VBCString


def _program(module_bytecode, module_constants=None, functions=None):
    output = CompilerOutput(
        bytecode=module_bytecode,
        constant_pool=module_constants or [VBCInteger(1), VBCInteger(2), VBCBool(True)],
        function_compilation_results=functions or {},
        lineno_table=[(0, 10), (2, 12)],
    )
    from verbose_c.compiler.ir import lower_compiler_output_to_ir

    return lower_compiler_output_to_ir(output)


def test_native_lowering_lowers_constants_locals_arithmetic_and_return():
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=[
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.STORE_LOCAL_VAR, 0),
            (Opcode.LOAD_LOCAL_VAR, 0),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.ADD,),
            (Opcode.RETURN,),
        ],
        constants=[VBCInteger(40), VBCInteger(2)],
        param_count=0,
        local_count=1,
        lineno_table=[(0, 3)],
    )
    program = lower_ir_program_to_machine(type("IRProgramStub", (), {"module": ir_function, "functions": {}})())

    ops = [instruction.op for block in program.module.blocks for instruction in block.instructions]
    assert "load_imm" in ops
    assert "store_stack" in ops
    assert "load_stack" in ops
    assert "add" in ops
    assert program.module.blocks[-1].terminator.op == "ret"


def test_native_lowering_preserves_branch_and_loop_cfg():
    program = _program([
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

    machine = lower_ir_program_to_machine(program)

    terminators = [block.terminator.op for block in machine.module.blocks]
    assert "br" in terminators
    assert "jmp" in terminators
    assert any(
        int(successor.removeprefix("bb_")) < int(block.name.removeprefix("bb_"))
        for block in machine.module.blocks
        for successor in block.successors
    )


def test_native_lowering_marks_boolean_result_vregs():
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=[
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.LESS_THAN,),
            (Opcode.STORE_LOCAL_VAR, 0),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.LOGICAL_NOT,),
            (Opcode.STORE_LOCAL_VAR, 1),
            (Opcode.LOAD_CONSTANT, 3),
            (Opcode.CAST, VBCObjectType.BOOL),
            (Opcode.RETURN,),
        ],
        constants=[VBCInteger(1), VBCInteger(2), VBCInteger(0), VBCInteger(42)],
        param_count=0,
        local_count=2,
        lineno_table=[(0, 3)],
    )
    program = lower_ir_program_to_machine(type("IRProgramStub", (), {"module": ir_function, "functions": {}})())
    instructions = [instruction for block in program.module.blocks for instruction in block.instructions]

    assert next(instruction for instruction in instructions if instruction.op == "cmp_lt").result.type_hint == "bool64"
    assert next(instruction for instruction in instructions if instruction.op == "not_bool").result.type_hint == "bool64"
    assert next(instruction for instruction in instructions if instruction.op == "cast_int_bool").result.type_hint == "bool64"


def test_native_lowering_preserves_integer_cast_target_type():
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=[
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.CAST, VBCObjectType.CHAR),
            (Opcode.RETURN,),
        ],
        constants=[VBCInteger(40)],
        param_count=0,
        local_count=0,
        lineno_table=[(0, 3)],
    )
    program = lower_ir_program_to_machine(type("IRProgramStub", (), {"module": ir_function, "functions": {}})())
    instructions = [instruction for block in program.module.blocks for instruction in block.instructions]
    cast_instruction = next(instruction for instruction in instructions if instruction.op == "cast_bool_int")

    assert cast_instruction.attrs["target_type"] == "char"


def test_machine_formatter_prints_vreg_type_hints():
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=[
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.LESS_THAN,),
            (Opcode.RETURN,),
        ],
        constants=[VBCInteger(1), VBCInteger(2)],
        param_count=0,
        local_count=0,
        lineno_table=[(0, 3)],
    )
    text = format_machine_program(lower_ir_program_to_machine(type("IRProgramStub", (), {"module": ir_function, "functions": {}})()))

    assert "%v0:int64 = load_imm" in text
    assert ":bool64 = cmp_lt" in text
    assert "ret %v2:bool64" in text


def test_machine_formatter_outputs_stack_slot_table():
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=[
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.STORE_LOCAL_VAR, 0),
            (Opcode.LOAD_LOCAL_VAR, 0),
            (Opcode.RETURN,),
        ],
        constants=[VBCInteger(7)],
        param_count=0,
        local_count=1,
        lineno_table=[(0, 3)],
    )
    text = format_machine_program(lower_ir_program_to_machine(type("IRProgramStub", (), {"module": ir_function, "functions": {}})()))

    assert "#### 栈槽" in text
    assert "| 类型 | 索引 | 大小 |" in text
    assert "| `local` | `0` | `8` |" in text
    assert "| `temp` | `0` | `8` |" in text


def test_native_lowering_lowers_user_function_call_and_argument_locations():
    add_function = VBCFunction(
        "add2",
        bytecode=[(Opcode.LOAD_LOCAL_VAR, 0), (Opcode.LOAD_LOCAL_VAR, 1), (Opcode.ADD,), (Opcode.RETURN,)],
        constants=[],
        param_count=2,
        local_count=2,
    )
    program = _program(
        [
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.STORE_GLOBAL_VAR, "add2"),
            (Opcode.LOAD_GLOBAL_VAR, "add2"),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.CALL_FUNCTION, 2),
            (Opcode.SET_EXIT_CODE,),
            (Opcode.HALT,),
        ],
        module_constants=[add_function, VBCInteger(20), VBCInteger(22)],
        functions={
            "add2": {
                "bytecode": add_function.bytecode,
                "constants": [],
                "param_count": 2,
                "local_count": 2,
            }
        },
    )

    machine = lower_ir_program_to_machine(program)
    calls = [instruction for block in machine.module.blocks for instruction in block.instructions if instruction.op == "call"]

    assert calls
    assert [item["name"] for item in calls[0].attrs["arg_locations"]] == ["RCX", "RDX"]
    assert machine.module.exit_code_value is not None


def test_native_lowering_marks_bool_call_result_type():
    flag_function = VBCFunction(
        "flag",
        bytecode=[(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)],
        constants=[VBCBool(True)],
        param_count=0,
        local_count=0,
    )
    program = _program(
        [
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.STORE_GLOBAL_VAR, "flag"),
            (Opcode.LOAD_GLOBAL_VAR, "flag"),
            (Opcode.CALL_FUNCTION, 0),
            (Opcode.RETURN,),
        ],
        module_constants=[flag_function],
        functions={
            "flag": {
                "bytecode": flag_function.bytecode,
                "constants": flag_function.constants,
                "param_count": 0,
                "local_count": 0,
                "return_type": "bool64",
            }
        },
    )

    machine = lower_ir_program_to_machine(program)
    calls = [instruction for block in machine.module.blocks for instruction in block.instructions if instruction.op == "call"]

    assert calls
    assert calls[0].result.type_hint == "bool64"


def test_native_lowering_marks_bool_phi_result_type():
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=[
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.JUMP_IF_FALSE, 4),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.JUMP, 5),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.RETURN,),
        ],
        constants=[VBCBool(True), VBCBool(True), VBCBool(False)],
        param_count=0,
        local_count=0,
        return_type="bool64",
        lineno_table=[(0, 3)],
    )
    program = lower_ir_program_to_machine(type("IRProgramStub", (), {"module": ir_function, "functions": {}})())
    phis = [instruction for block in program.module.blocks for instruction in block.instructions if instruction.op == "phi"]

    assert phis
    assert phis[0].result.type_hint == "bool64"
    assert [operand.type_hint for operand in phis[0].args] == ["bool64", "bool64"]


def test_native_lowering_reports_unsupported_string_constant_with_context():
    program = _program([(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)], module_constants=[VBCString("bad")])

    with pytest.raises(NativeLoweringError) as exc_info:
        lower_ir_program_to_machine(program)

    message = str(exc_info.value)
    assert "函数 <module>" in message
    assert "IR 指令 const" in message
    assert "String" in message or "STRING" in message
    assert "PC 0" in message


def test_native_lowering_reports_unsupported_builtin_call():
    program = _program([
        (Opcode.LOAD_GLOBAL_VAR, "write"),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.CALL_FUNCTION, 2),
        (Opcode.RETURN,),
    ], module_constants=[VBCInteger(1), VBCInteger(2)])

    with pytest.raises(NativeLoweringError) as exc_info:
        lower_ir_program_to_machine(program)

    assert "builtin_function:write" in str(exc_info.value)


def test_machine_dump_from_source_file(tmp_path):
    source_path = tmp_path / "native_dump.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    dump_path = tmp_path / "native_dump.md"
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "native_dump.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "Machine IR" in dump_text
    assert "windows-x64" in dump_text
    assert "RCX" in dump_text
    assert "RAX" in dump_text
    assert "Shadow space" in dump_text
    assert "bb_" in dump_text


def test_machine_formatter_outputs_abi_summary():
    program = _program([(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)])
    text = format_machine_program(lower_ir_program_to_machine(program))

    assert "Machine IR" in text
    assert "windows-x64" in text

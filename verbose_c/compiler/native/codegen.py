from dataclasses import dataclass
from verbose_c.compiler.native.abi import (
    FLOAT_VALUE_TYPES,
    SCALAR_VALUE_TYPES,
    SUPPORTED_ARGUMENT_REGISTERS,
    SUPPORTED_RETURN_TYPES,
    SUPPORTED_VALUE_TYPES,
    WindowsX64ABI,
    is_argument_type_compatible,
)
from verbose_c.compiler.native.encoder import (
    ConditionCode,
    encode_add_rax_r10,
    encode_add_rsp_imm32,
    encode_call_rel32,
    encode_cmp_rax_r10,
    encode_cqo,
    encode_epilogue,
    encode_idiv_r10,
    encode_imul_rax_r10,
    encode_je_rel32,
    encode_jmp_rel32,
    encode_jne_rel32,
    encode_jns_rel32,
    encode_mov_r10_from_r11_offset,
    encode_mov_r10_from_rbp_offset,
    encode_mov_r10_imm64,
    encode_mov_r11_offset_from_rax,
    encode_mov_r11_rbp,
    encode_mov_rax_from_r11_offset,
    encode_mov_rax_from_rbp_offset,
    encode_mov_rax_from_rbp_positive_offset,
    encode_mov_rax_imm64,
    encode_mov_rax_rdx,
    encode_mov_rbp_offset_from_rax,
    encode_mov_rbp_offset_from_reg,
    encode_mov_rdx_imm64,
    encode_mov_reg_from_rax,
    encode_mov_rsp_offset_from_rax,
    encode_movzx_rax_al,
    encode_neg_rax,
    encode_prologue,
    encode_setcc_al,
    encode_sse_transfer,
    encode_sub_rax_r10,
    encode_sub_rsp_imm32,
    encode_test_rdx_rdx,
    encode_xor_rax_r10,
)
from verbose_c.compiler.native.errors import NativeCodegenError
from verbose_c.compiler.native.listing_formatter import format_native_code_program
from verbose_c.compiler.native.machine_ir import (
    MachineBlock,
    MachineFunction,
    MachineInstruction,
    MachineOperand,
    MachineProgram,
    MachineTerminator,
)
from verbose_c.compiler.native.map_format import (
    native_code_program_map,
    validate_native_code_map_bytes,
    validate_native_code_program_map,
    validate_native_text_section_map_bytes,
)
from verbose_c.compiler.native.model import (
    NativeCallFrameAllocation,
    NativeCodeFunction,
    NativeCodeInstruction,
    NativeCodeProgram,
    NativeExitProbe,
    NativeRegisterAllocation,
    NativeRelocation,
    NativeStackSlotAllocation,
    NativeSymbol,
)
from verbose_c.compiler.native.runtime import (
    RUNTIME_SIGNATURES,
    append_runtime,
)
from verbose_c.compiler.native.target import NativeTarget
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.numeric import (
    INTEGER_KIND_NAMES,
    INTEGER_LIMITS,
    float_bits,
    integer_divmod,
)


@dataclass(frozen=True)
class _PendingJump:
    """等待回填的相对跳转。"""

    offset: int
    instruction_index: int
    target: str
    kind: str


_BINARY_OP_ASM = {
    "add": "add rax, r10",
    "sub": "sub rax, r10",
    "imul": "imul rax, r10",
    "idiv": "idiv r10",
    "imod": "idiv r10; mov rax, rdx",
}


_COMPARE_OPS = {
    "cmp_eq": ConditionCode.EQ,
    "cmp_ne": ConditionCode.NE,
    "cmp_lt": ConditionCode.LT,
    "cmp_le": ConditionCode.LE,
    "cmp_gt": ConditionCode.GT,
    "cmp_ge": ConditionCode.GE,
}


_VALUE_OPERAND_KINDS = {"imm", "slot", "vreg"}


_RESULT_OPERAND_KINDS = {"vreg"}


_BOOL64_RESULT_OPS = {"not_bool", "cast_int_bool", *_COMPARE_OPS}


_INTEGER_CAST_TARGET_TYPES = {
    "char",
    "short",
    "int",
    "long",
    "longlong",
    "long long",
    "int64",
}


_BOOL_CAST_TARGET_TYPES = {"bool", "bool64"}


_NARROW_INTEGER_CAST_RANGES = {
    name: INTEGER_LIMITS[kind] for name, kind in INTEGER_KIND_NAMES.items() if kind in INTEGER_LIMITS
}


_INT64_MIN = -(2**63)


_INT64_MAX = 2**63 - 1


_INT32_MAX = 2**31 - 1


_SUPPORTED_VREG_TYPES = SCALAR_VALUE_TYPES


def _function_param_types(function: MachineFunction) -> list[str]:
    """取得函数形参类型；手工 Machine IR 缺省按 int64 处理。"""
    if function.param_types:
        return list(function.param_types)
    return ["int64"] * len(function.params)


def _encode_rel32_jump(kind: str, displacement: int) -> bytes:
    """按跳转助记符编码 rel32 跳转。"""
    if kind == "je":
        return encode_je_rel32(displacement)
    if kind == "jmp":
        return encode_jmp_rel32(displacement)
    if kind == "jne":
        return encode_jne_rel32(displacement)
    if kind == "jns":
        return encode_jns_rel32(displacement)
    raise NativeCodegenError(f"native 机器码 MVP 暂不支持 rel32 跳转 {kind}")


def generate_native_code(program: MachineProgram, *, aot: bool = False) -> NativeCodeProgram:
    """从 Machine IR 生成 x64 机器码 MVP。"""
    if program.target != NativeTarget.WINDOWS_X64:
        raise NativeCodegenError(f"native 机器码 MVP 暂不支持目标平台 {program.target}")
    _validate_program_abi(program)
    _validate_program_function_table(program)
    main_function = program.functions.get("main")
    if main_function is not None:
        if main_function.params:
            raise NativeCodegenError("native 机器码 MVP 入口 main 暂不支持参数")
        if main_function.return_type not in {"int64", "bool64", "void"}:
            raise NativeCodegenError(f"native 机器码 MVP 入口 main 暂不支持返回类型 {main_function.return_type}")
    code = bytearray()
    function_offsets: dict[str, int] = {}
    pending_calls: list[_PendingJump] = []
    functions: dict[str, NativeCodeFunction] = {}
    has_separate_module = program.module.name not in program.functions
    direct_bool_main_entry = (
        has_separate_module
        and main_function is not None
        and main_function.return_type == "bool64"
        and not program.module.frame.global_slots
        and _module_contains_only_function_registration(program.module)
    )
    if direct_bool_main_entry:
        entry_name = "main"
        entry_function = main_function
    elif has_separate_module:
        entry_name = program.module.name
        entry_function = program.module
    elif "main" in program.functions:
        entry_name = "main"
        entry_function = program.functions[entry_name]
    else:
        entry_name = program.module.name
        entry_function = program.functions[entry_name]
    if entry_function.params:
        raise NativeCodegenError(f"native 机器码 MVP 入口 {entry_name} 暂不支持参数")
    ordered_functions = [entry_function]
    if has_separate_module and not direct_bool_main_entry:
        ordered_functions.extend(program.functions.values())
    else:
        ordered_functions.extend(function for name, function in program.functions.items() if name != entry_name)
    for function in ordered_functions:
        if function.return_type not in SUPPORTED_RETURN_TYPES:
            raise NativeCodegenError(f"native 机器码 MVP 函数 {function.name} 暂不支持返回类型 {function.return_type}")
        param_types = _function_param_types(function)
        if len(param_types) != len(function.params):
            raise NativeCodegenError(
                f"native 机器码 MVP 函数 {function.name} 参数类型数量不匹配: "
                f"标注 {len(param_types)}, 参数 {len(function.params)}"
            )
        for index, param_type in enumerate(param_types):
            if param_type not in SUPPORTED_VALUE_TYPES:
                raise NativeCodegenError(f"native 机器码 MVP 函数 {function.name} 第 {index} 个参数暂不支持类型 {param_type}")
    for function in ordered_functions:
        for index, param in enumerate(function.params):
            expected = program.abi.argument_location(index, _function_param_types(function)[index])
            if param != expected:
                raise NativeCodegenError(
                    f"native 机器码 MVP 函数 {function.name} 第 {index} 个参数位置不符合 ABI: "
                    f"需要 {expected.kind}:{expected.name}:{expected.index}, 实际 {param.kind}:{param.name}:{param.index}"
                )
    non_module_global_users = [function.name for function in ordered_functions if function.name != "<module>" and function.frame.global_slots]
    global_frame_owner_name: str | None = None
    if entry_name != "<module>" and non_module_global_users:
        if not entry_function.frame.global_slots:
            raise NativeCodegenError(
                f"native 机器码 MVP 入口 {entry_name} 调用带全局槽的函数时需要声明全局槽并初始化 R11 global frame"
            )
        entry_global_names = {slot.index for slot in entry_function.frame.global_slots}
        for function in ordered_functions:
            missing_globals = [slot.index for slot in function.frame.global_slots if slot.index not in entry_global_names]
            if missing_globals:
                names = ", ".join(str(name) for name in missing_globals)
                raise NativeCodegenError(f"native 机器码 MVP 函数 {function.name} 使用了入口 {entry_name} 未声明的全局槽: {names}")
        global_frame_owner_name = entry_name
    if entry_name == "<module>" and non_module_global_users:
        if not entry_function.frame.global_slots:
            raise NativeCodegenError("native 机器码 MVP 全局标量需要 <module> 栈帧声明全局槽并初始化 R11 global frame")
        module_global_names = {slot.index for slot in entry_function.frame.global_slots}
        for function in ordered_functions:
            if function.name == "<module>":
                continue
            missing_globals = [slot.index for slot in function.frame.global_slots if slot.index not in module_global_names]
            if missing_globals:
                names = ", ".join(str(name) for name in missing_globals)
                raise NativeCodegenError(f"native 机器码 MVP 函数 {function.name} 使用了 <module> 未声明的全局槽: {names}")
        global_frame_owner_name = "<module>"
    if entry_name == "<module>" and entry_function.frame.global_slots:
        global_frame_owner_name = "<module>"
    function_names = set(program.functions.keys())
    function_return_types = {name: function.return_type for name, function in program.functions.items()}
    function_return_types[entry_function.name] = entry_function.return_type
    function_param_counts = {name: len(function.params) for name, function in program.functions.items()}
    function_param_counts[entry_function.name] = len(entry_function.params)
    function_param_types = {
        name: _function_param_types(function)
        for name, function in program.functions.items()
    }
    function_param_types[entry_function.name] = _function_param_types(entry_function)
    needs_runtime = aot or any(
        instruction.op == "load_string" or (
            instruction.op == "call" and instruction.args
            and instruction.args[0].value in RUNTIME_SIGNATURES
        )
        for function in ordered_functions for block in function.blocks
        for instruction in block.instructions
    )
    if needs_runtime:
        function_names.update(RUNTIME_SIGNATURES)
        for name, (return_type, param_types) in RUNTIME_SIGNATURES.items():
            function_return_types[name] = return_type
            function_param_counts[name] = len(param_types)
            function_param_types[name] = list(param_types)
    for function in ordered_functions:
        _validate_block_structure(function)
        _validate_operand_storage_shapes(function)
        _validate_instruction_shapes(function)
        _validate_terminator_shapes(function)
        _validate_vreg_use_order(function)
        _validate_static_machine_hazards(function)
        _validate_exit_instructions(function)
        _validate_terminator_targets(function)
        _validate_phi_incoming_blocks(function)
        _validate_phi_sources_defined(function)
        _validate_call_argument_types(function, function_param_types)
    for function in ordered_functions:
        generated = _NativeCodegenContext(
            function,
            code,
            function_offsets,
            pending_calls,
            function_names,
            function_return_types,
            function_param_counts,
            function_param_types,
            program.abi,
            function.name == global_frame_owner_name,
        ).generate()
        functions[function.name] = generated
    runtime = {}
    if needs_runtime:
        runtime = append_runtime(code, functions, entry_name, detailed_numeric_errors=aot)
        function_offsets.update({name: function.offset for name, function in functions.items()})
        entry_name = "<native:start>"
    _patch_pending_calls(code, pending_calls, function_offsets, functions)
    program_code = bytes(code)
    for name, function in list(functions.items()):
        end = len(program_code)
        next_offsets = [item.offset for item in functions.values() if item.offset > function.offset]
        if next_offsets:
            end = min(next_offsets)
        functions[name] = NativeCodeFunction(
            name=function.name,
            code=program_code[function.offset:end],
            instructions=function.instructions,
            frame_size=function.frame_size,
            offset=function.offset,
            stack_slots=function.stack_slots,
            call_frames=function.call_frames,
            relocations=function.relocations,
            exit_probes=function.exit_probes,
            register_allocation=function.register_allocation,
            return_type=function.return_type,
            param_types=function.param_types,
        )
    return NativeCodeProgram(
        target=program.target,
        entry=functions[entry_name],
        functions=functions,
        code=program_code,
        entry_offset=functions[entry_name].offset,
        abi=program.abi,
        runtime=runtime,
        aot=aot,
        symbols=[
            NativeSymbol(
                name=function.name,
                offset=function.offset,
                size=len(function.code),
                is_entry=function.name == entry_name,
                return_type=function.return_type,
                param_types=function.param_types,
            )
            for function in sorted(functions.values(), key=lambda item: item.offset)
        ],
    )


def _validate_program_abi(program: MachineProgram) -> None:
    """校验 ABI 能被当前 x64 MVP 编码器支持。"""
    abi = program.abi
    if abi.target != program.target:
        raise NativeCodegenError(f"native 机器码 MVP ABI 目标平台 {abi.target} 与程序目标平台 {program.target} 不一致")
    if not isinstance(abi.word_size, int) or isinstance(abi.word_size, bool):
        raise NativeCodegenError(f"native 机器码 MVP ABI word_size 必须是整数，实际 {type(abi.word_size).__name__}")
    if abi.word_size != 8:
        raise NativeCodegenError(f"native 机器码 MVP ABI word_size 必须为 8，实际 {abi.word_size}")
    if not isinstance(abi.stack_alignment, int) or isinstance(abi.stack_alignment, bool):
        raise NativeCodegenError(f"native 机器码 MVP ABI 栈对齐必须是整数，实际 {type(abi.stack_alignment).__name__}")
    if abi.stack_alignment <= 0:
        raise NativeCodegenError(f"native 机器码 MVP ABI 栈对齐必须为正数，实际 {abi.stack_alignment}")
    if not isinstance(abi.shadow_space_size, int) or isinstance(abi.shadow_space_size, bool):
        raise NativeCodegenError(f"native 机器码 MVP ABI shadow space 必须是整数，实际 {type(abi.shadow_space_size).__name__}")
    if abi.shadow_space_size < 0:
        raise NativeCodegenError(f"native 机器码 MVP ABI shadow space 不能为负数，实际 {abi.shadow_space_size}")
    if not isinstance(abi.registers.return_register, str):
        raise NativeCodegenError(f"native 机器码 MVP ABI 返回寄存器必须是字符串，实际 {type(abi.registers.return_register).__name__}")
    if abi.registers.return_register.upper() != "RAX":
        raise NativeCodegenError(f"native 机器码 MVP ABI 返回寄存器必须为 RAX，实际 {abi.registers.return_register}")
    if not isinstance(abi.registers.frame_pointer, str):
        raise NativeCodegenError(f"native 机器码 MVP ABI 帧指针寄存器必须是字符串，实际 {type(abi.registers.frame_pointer).__name__}")
    if abi.registers.frame_pointer.upper() != "RBP":
        raise NativeCodegenError(f"native 机器码 MVP ABI 帧指针寄存器必须为 RBP，实际 {abi.registers.frame_pointer}")
    if not isinstance(abi.registers.stack_pointer, str):
        raise NativeCodegenError(f"native 机器码 MVP ABI 栈指针寄存器必须是字符串，实际 {type(abi.registers.stack_pointer).__name__}")
    if abi.registers.stack_pointer.upper() != "RSP":
        raise NativeCodegenError(f"native 机器码 MVP ABI 栈指针寄存器必须为 RSP，实际 {abi.registers.stack_pointer}")
    seen_argument_registers = set()
    for register in abi.registers.argument_registers:
        if not isinstance(register, str):
            raise NativeCodegenError(f"native 机器码 MVP ABI 参数寄存器必须是字符串，实际 {type(register).__name__}")
        register_name = register.upper()
        if register_name in seen_argument_registers:
            raise NativeCodegenError(f"native 机器码 MVP ABI 参数寄存器重复: {register}")
        seen_argument_registers.add(register_name)
        if register.upper() not in SUPPORTED_ARGUMENT_REGISTERS:
            raise NativeCodegenError(f"native 机器码 MVP ABI 参数寄存器暂不支持 {register}")


def _module_contains_only_function_registration(function: MachineFunction) -> bool:
    """判断模块入口是否只注册函数且无顶层执行逻辑。"""
    if len(function.blocks) != 1:
        return False
    block = function.blocks[0]
    if any(instruction.op != "mov" or instruction.attrs.get("kind") != "register_function" for instruction in block.instructions):
        return False
    terminator = block.terminator
    return (
        terminator is not None
        and terminator.op == "ret"
        and len(terminator.args) == 1
        and terminator.args[0].kind == "imm"
        and int(terminator.args[0].value) == 0
    )


def _validate_program_function_table(program: MachineProgram) -> None:
    """校验 MachineProgram 函数表与函数名一致。"""
    if not program.module.name:
        raise NativeCodegenError("native 机器码 MVP module 函数名不能为空")
    for name, function in program.functions.items():
        if not function.name:
            raise NativeCodegenError(f"native 机器码 MVP 函数表项 {name} 的函数名不能为空")
        if name != function.name:
            raise NativeCodegenError(
                f"native 机器码 MVP 函数表键与函数名不一致: 键 {name}, 函数 {function.name}"
            )
    table_module = program.functions.get(program.module.name)
    if program.module.name == "<module>" and table_module is not None and table_module is not program.module:
        raise NativeCodegenError(
            f"native 机器码 MVP 函数表中的 {program.module.name} 必须与 program.module 指向同一函数"
        )


def _validate_block_structure(function: MachineFunction) -> None:
    """校验 Machine IR 基本块结构不会让跳转回填产生歧义。"""
    if not function.blocks:
        raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP 函数必须至少包含 1 个基本块")
    seen_blocks = set()
    duplicate_blocks = []
    for block in function.blocks:
        if not block.name:
            raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP 基本块名称不能为空")
        if block.name in seen_blocks:
            duplicate_blocks.append(block.name)
        seen_blocks.add(block.name)
        if block.terminator is None:
            raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP 需要基本块 {block.name} 的终结指令")
    if duplicate_blocks:
        names = ", ".join(duplicate_blocks)
        raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP 基本块名重复: {names}")


def _validate_operand_storage_shapes(function: MachineFunction) -> None:
    """校验栈槽和虚拟寄存器能映射到当前 int64 栈帧。"""
    _validate_frame_slots(function, "global", function.frame.global_slots)
    _validate_frame_slots(function, "local", function.frame.local_slots)
    _validate_frame_slots(function, "temp", function.frame.temp_slots)
    _validate_frame_slots(function, "spill", function.frame.spill_slots)
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.result is not None:
                _validate_operand_storage_shape(function, instruction, instruction.result)
            for operand in instruction.args:
                _validate_operand_storage_shape(function, instruction, operand)
        if block.terminator is not None:
            for operand in block.terminator.args:
                _validate_operand_storage_shape(function, block.terminator, operand)


def _validate_frame_slots(function: MachineFunction, expected_kind: str, slots: list[object]) -> None:
    """校验 frame 中同类栈槽声明不会重复或被忽略。"""
    if expected_kind == "spill" and slots:
        raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP 暂不支持 spill 栈槽")
    seen = set()
    duplicates = []
    for slot in slots:
        _validate_stack_slot_shape(function, slot)
        kind = getattr(slot, "kind", None)
        index = getattr(slot, "index", None)
        if kind != expected_kind:
            raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP {expected_kind} 槽列表中出现 {kind}[{index}]")
        key = (kind, index)
        if key in seen:
            duplicates.append(f"{kind}[{index}]")
        seen.add(key)
    if duplicates:
        names = ", ".join(duplicates)
        raise NativeCodegenError(f"函数 {function.name}: native 机器码 MVP 栈槽重复声明: {names}")


def _validate_operand_storage_shape(function: MachineFunction, node: MachineInstruction | MachineTerminator, operand: MachineOperand) -> None:
    """校验单个操作数的存储形状。"""
    if operand.kind == "imm":
        _validate_value_operand_type(function, node, operand)
        _validate_immediate_shape(function, node, operand)
        return
    if operand.kind == "vreg":
        register_name = getattr(operand.value, "name", None)
        register_type = getattr(operand.value, "type_hint", None)
        if not isinstance(register_name, str):
            raise _machine_node_error(
                function,
                node,
                f"native 机器码 MVP 虚拟寄存器名必须是字符串，实际 {type(register_name).__name__}",
            )
        if not _vreg_index_text(register_name).isdigit():
            raise _machine_node_error(
                function,
                node,
                f"native 机器码 MVP 虚拟寄存器名必须形如 %v0，实际 %{register_name}",
            )
        if register_type not in _SUPPORTED_VREG_TYPES:
            raise _machine_node_error(
                function,
                node,
                f"native 机器码 MVP 虚拟寄存器 %{register_name} 类型暂不支持 {register_type}",
            )
        if operand.type_hint != register_type:
            raise _machine_node_error(
                function,
                node,
                f"native 机器码 MVP 虚拟寄存器 %{register_name} 操作数类型 {operand.type_hint} 与定义类型 {register_type} 不一致",
            )
        return
    if operand.kind == "slot":
        _validate_value_operand_type(function, node, operand)
        _validate_stack_slot_shape(function, operand.value, node)


def _validate_value_operand_type(function: MachineFunction, node: MachineInstruction | MachineTerminator, operand: MachineOperand) -> None:
    """校验值操作数类型属于当前 MVP 标量集合。"""
    if operand.type_hint in SUPPORTED_VALUE_TYPES:
        return
    raise _machine_node_error(
        function,
        node,
        f"native 机器码 MVP {operand.kind} 操作数类型暂不支持 {operand.type_hint}",
    )


def _validate_immediate_shape(function: MachineFunction, node: MachineInstruction | MachineTerminator, operand: MachineOperand) -> None:
    """校验立即数能编码为当前 MVP 使用的 signed imm64。"""
    if not isinstance(operand.value, int):
        raise _machine_node_error(
            function,
            node,
            f"native 机器码 MVP 立即数必须是整数，实际 {type(operand.value).__name__}",
        )
    if not (_INT64_MIN <= int(operand.value) <= _INT64_MAX):
        raise _machine_node_error(
            function,
            node,
            f"native 机器码 MVP 立即数超出 signed int64 范围: {operand.value}",
        )


def _validate_stack_slot_shape(
    function: MachineFunction,
    slot: object,
    node: MachineInstruction | MachineTerminator | None = None,
) -> None:
    """校验单个 Machine IR 栈槽形状。"""
    kind = getattr(slot, "kind", None)
    index = getattr(slot, "index", None)
    size = getattr(slot, "size", None)
    if kind not in {"global", "local", "temp"}:
        message = f"native 机器码 MVP 栈槽类型暂不支持 {kind}"
    elif index is None or index == "":
        message = f"native 机器码 MVP {kind} 栈槽索引不能为空"
    elif size != 8:
        message = f"native 机器码 MVP {kind}[{index}] 栈槽大小必须为 8 字节，实际 {size}"
    else:
        return
    if node is None:
        raise NativeCodegenError(f"函数 {function.name}: {message}")
    raise _machine_node_error(function, node, message)


def _vreg_index_text(name: str) -> str:
    """返回虚拟寄存器名中的数字部分。"""
    return str(name).removeprefix("v")


def _validate_instruction_shapes(function: MachineFunction) -> None:
    """校验 Machine IR 指令参数数量与操作数形状。"""
    for block in function.blocks:
        for instruction in block.instructions:
            op = instruction.op
            if op == "load_string":
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_result_type(function, instruction, "string")
                _require_arg_count(function, instruction, 0)
                if not isinstance(instruction.attrs.get("value"), str):
                    raise _machine_node_error(function, instruction, "字符串常量必须包含文本 value")
                continue
            if op == "load_imm":
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_arg_count(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, {"imm"})
                continue
            if op == "load_stack":
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_arg_count(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, {"slot"})
                continue
            if op == "store_stack":
                _require_no_result(function, instruction)
                _require_arg_count(function, instruction, 2)
                _require_operand_kinds(function, instruction, 0, {"slot"})
                _require_operand_kinds(function, instruction, 1, _VALUE_OPERAND_KINDS)
                continue
            if op == "phi":
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                for index in range(len(instruction.args)):
                    _require_operand_kinds(function, instruction, index, _VALUE_OPERAND_KINDS)
                    if not _is_phi_type_compatible(instruction.result.type_hint, instruction.args[index].type_hint):
                        raise _machine_node_error(
                            function,
                            instruction,
                            f"native 机器码 MVP phi 结果类型 {instruction.result.type_hint} 与第 {index} 个来源类型 {instruction.args[index].type_hint} 不一致",
                        )
                continue
            if op == "mov" and instruction.attrs.get("kind") == "register_function":
                _require_no_result(function, instruction)
                _require_arg_count(function, instruction, 2)
                _require_operand_kinds(function, instruction, 0, {"symbol"})
                _require_operand_kinds(function, instruction, 1, {"symbol"})
                continue
            if op in {"fadd", "fsub", "fimul", "fidiv", "fcmp_eq", "fcmp_ne", "fcmp_lt", "fcmp_le", "fcmp_gt", "fcmp_ge", "fneg", "cast_float"}:
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_arg_count(function, instruction, 1 if op in {"fneg", "cast_float"} else 2)
                for index, operand in enumerate(instruction.args):
                    _require_operand_kinds(function, instruction, index, _VALUE_OPERAND_KINDS)
                    if op != "cast_float" and operand.type_hint not in FLOAT_VALUE_TYPES:
                        raise _machine_node_error(function, instruction, "浮点运算需要浮点操作数")
                if op.startswith("fcmp_"):
                    _require_result_type(function, instruction, "bool64")
                elif op == "cast_float":
                    target = instruction.attrs.get("target_type")
                    expected = {"float": "float32", "double": "float64"}.get(target, "int64")
                    if target not in {"float", "double", *_INTEGER_CAST_TARGET_TYPES}:
                        raise _machine_node_error(function, instruction, "不支持的浮点转换目标")
                    _require_result_type(function, instruction, expected)
                else:
                    _require_result_type(function, instruction, instruction.args[0].type_hint)
                if len(instruction.args) == 2 and instruction.args[0].type_hint != instruction.args[1].type_hint:
                    raise _machine_node_error(function, instruction, "浮点运算的两侧类型必须相同")
                continue
            if op in _BINARY_OP_ASM or op in _COMPARE_OPS:
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_result_type(function, instruction, "bool64" if op in _COMPARE_OPS else "int64")
                _require_arg_count(function, instruction, 2)
                _require_operand_kinds(function, instruction, 0, _VALUE_OPERAND_KINDS)
                _require_operand_kinds(function, instruction, 1, _VALUE_OPERAND_KINDS)
                if any(arg.type_hint not in {"int64", "bool64"} for arg in instruction.args):
                    raise _machine_node_error(function, instruction, "整数运算不能使用浮点或字符串操作数")
                continue
            if op in {"neg", "not_bool", "cast_bool_int", "cast_int_bool"}:
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_result_type(function, instruction, "bool64" if op in _BOOL64_RESULT_OPS else "int64")
                _require_arg_count(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, _VALUE_OPERAND_KINDS)
                if op in {"neg", "cast_bool_int"} and instruction.args[0].type_hint in FLOAT_VALUE_TYPES:
                    raise _machine_node_error(function, instruction, "整数运算不能使用浮点操作数")
                if op == "cast_bool_int":
                    target_type = instruction.attrs.get("target_type")
                    if not isinstance(target_type, str) or not target_type:
                        raise _machine_node_error(function, instruction, "native 机器码 MVP cast_bool_int target_type 必须是非空字符串")
                    if target_type not in _INTEGER_CAST_TARGET_TYPES:
                        raise _machine_node_error(function, instruction, f"native 机器码 MVP cast_bool_int target_type 暂不支持 {target_type}")
                if op == "cast_int_bool":
                    target_type = instruction.attrs.get("target_type")
                    if target_type is not None and not isinstance(target_type, str):
                        raise _machine_node_error(function, instruction, "native 机器码 MVP cast_int_bool target_type 必须是字符串或省略")
                    if target_type is not None and target_type not in _BOOL_CAST_TARGET_TYPES:
                        raise _machine_node_error(function, instruction, f"native 机器码 MVP cast_int_bool target_type 暂不支持 {target_type}")
                continue
            if op == "call":
                _require_arg_at_least(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, {"symbol"})
                _validate_call_metadata_shape(function, instruction)
                if instruction.result is not None:
                    _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                for index in range(1, len(instruction.args)):
                    _require_operand_kinds(function, instruction, index, _VALUE_OPERAND_KINDS)
                continue
            if op == "exit":
                _require_no_result(function, instruction)
                _require_arg_count(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, _VALUE_OPERAND_KINDS)
                continue
            if op == "set_exit_code":
                _require_no_result(function, instruction)
                _require_arg_count(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, _VALUE_OPERAND_KINDS)


def _validate_terminator_shapes(function: MachineFunction) -> None:
    """校验 Machine IR 终结指令参数、目标与操作数形状。"""
    for block in function.blocks:
        terminator = block.terminator
        if terminator is None:
            continue
        if terminator.op == "ret":
            if terminator.targets:
                raise _machine_node_error(function, terminator, "native 机器码 MVP ret 不应携带跳转目标")
            if function.return_type == "void" and terminator.args:
                raise _machine_node_error(function, terminator, "native 机器码 MVP void 函数 ret 不应携带返回值")
            if function.return_type in SCALAR_VALUE_TYPES and len(terminator.args) != 1:
                raise _machine_node_error(function, terminator, f"native 机器码 MVP {function.return_type} 函数 ret 必须携带 1 个返回值")
            if terminator.args:
                _require_operand_kinds(function, terminator, 0, _VALUE_OPERAND_KINDS)
                if not _is_return_type_compatible(function.return_type, terminator.args[0].type_hint):
                    raise _machine_node_error(
                        function,
                        terminator,
                        f"native 机器码 MVP {function.return_type} 函数 ret 返回值类型不能是 {terminator.args[0].type_hint}",
                    )
            continue
        if terminator.op == "jmp":
            if terminator.args:
                raise _machine_node_error(function, terminator, "native 机器码 MVP jmp 不应携带参数")
            if len(terminator.targets) != 1:
                raise _machine_node_error(function, terminator, "native 机器码 MVP 需要 jmp 恰好包含 1 个目标")
            continue
        if terminator.op == "br":
            if len(terminator.args) != 1 or len(terminator.targets) != 2:
                raise _machine_node_error(function, terminator, "native 机器码 MVP 需要 br 包含 1 个条件和 2 个目标")
            _require_operand_kinds(function, terminator, 0, _VALUE_OPERAND_KINDS)


def _validate_call_metadata_shape(function: MachineFunction, instruction: MachineInstruction) -> None:
    """校验 call ABI 元数据形状。"""
    attrs = instruction.attrs
    if "argc" in attrs and (not isinstance(attrs["argc"], int) or isinstance(attrs["argc"], bool)):
        raise _machine_node_error(function, instruction, "native 机器码 MVP call argc 元数据必须是整数")
    if "arg_locations" in attrs:
        arg_locations = attrs["arg_locations"]
        if not isinstance(arg_locations, list):
            raise _machine_node_error(function, instruction, "native 机器码 MVP call arg_locations 元数据必须是列表")
        for index, location in enumerate(arg_locations):
            if not isinstance(location, dict):
                raise _machine_node_error(function, instruction, f"native 机器码 MVP call arg_locations[{index}] 必须是字典")
            if set(location) != {"kind", "name", "index"}:
                raise _machine_node_error(
                    function,
                    instruction,
                    f"native 机器码 MVP call arg_locations[{index}] 字段必须为 kind/name/index",
                )


def _require_no_result(function: MachineFunction, instruction: MachineInstruction) -> None:
    """校验指令不携带结果操作数。"""
    if instruction.result is not None:
        raise _machine_node_error(function, instruction, "native 机器码 MVP 指令不应携带结果操作数")


def _require_result_kind(function: MachineFunction, instruction: MachineInstruction, kinds: set[str]) -> None:
    """校验指令结果操作数类型。"""
    if instruction.result is None:
        raise _machine_node_error(function, instruction, "native 机器码 MVP 指令缺少结果操作数")
    if instruction.result.kind not in kinds:
        expected = " / ".join(sorted(kinds))
        raise _machine_node_error(
            function,
            instruction,
            f"native 机器码 MVP 指令结果操作数类型应为 {expected}，实际 {instruction.result.kind}",
        )


def _require_result_type(function: MachineFunction, instruction: MachineInstruction, expected: str) -> None:
    """校验指令结果虚拟寄存器类型。"""
    actual = getattr(instruction.result, "type_hint", None)
    if actual == expected:
        return
    raise _machine_node_error(
        function,
        instruction,
        f"native 机器码 MVP 指令 {instruction.op} 结果类型必须是 {expected}，实际 {actual}",
    )


def _is_phi_type_compatible(result_type: str, source_type: str) -> bool:
    """判断 phi 来源类型是否可按当前标量 MVP 合流。"""
    return result_type == source_type or (result_type == "int64" and source_type == "bool64")


def _is_return_type_compatible(return_type: str, value_type: str) -> bool:
    """判断 ret 返回值类型是否匹配函数返回类型。"""
    return return_type == value_type or (return_type == "int64" and value_type == "bool64")


def _require_arg_count(function: MachineFunction, instruction: MachineInstruction, expected: int) -> None:
    """校验指令参数数量。"""
    if len(instruction.args) != expected:
        raise _machine_node_error(
            function,
            instruction,
            f"native 机器码 MVP 指令需要 {expected} 个参数，实际 {len(instruction.args)} 个",
        )


def _require_arg_at_least(function: MachineFunction, instruction: MachineInstruction, expected: int) -> None:
    """校验指令参数最小数量。"""
    if len(instruction.args) < expected:
        raise _machine_node_error(
            function,
            instruction,
            f"native 机器码 MVP 指令至少需要 {expected} 个参数，实际 {len(instruction.args)} 个",
        )


def _require_operand_kinds(function: MachineFunction, node: MachineInstruction | MachineTerminator, index: int, kinds: set[str]) -> None:
    """校验节点参数操作数类型。"""
    operand = node.args[index]
    if operand.kind in kinds:
        return
    expected = " / ".join(sorted(kinds))
    raise _machine_node_error(
        function,
        node,
        f"native 机器码 MVP 第 {index} 个参数类型应为 {expected}，实际 {operand.kind}",
    )


def _validate_vreg_use_order(function: MachineFunction) -> None:
    """校验 Machine IR 虚拟寄存器不会在定义前被读取。"""
    defined: set[str] = set()
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.op != "phi":
                for operand in instruction.args:
                    _check_vreg_defined(function, instruction, operand, defined)
            if instruction.result is not None and instruction.result.kind == "vreg":
                _define_vreg(function, instruction, instruction.result, defined)
        if block.terminator is not None:
            for operand in block.terminator.args:
                _check_vreg_defined(function, block.terminator, operand, defined)


def _check_vreg_defined(function: MachineFunction, node: MachineInstruction | MachineTerminator, operand: MachineOperand, defined: set[str]) -> None:
    """校验单个虚拟寄存器操作数已定义。"""
    if operand.kind != "vreg" or operand.value.name in defined:
        return
    raise _machine_node_error(
        function,
        node,
        f"native 机器码 MVP 虚拟寄存器 %{operand.value.name} 在定义前被读取",
    )


def _define_vreg(function: MachineFunction, instruction: MachineInstruction, operand: MachineOperand, defined: set[str]) -> None:
    """登记虚拟寄存器定义并拒绝重复定义。"""
    if operand.value.name in defined:
        raise _machine_node_error(
            function,
            instruction,
            f"native 机器码 MVP 虚拟寄存器 %{operand.value.name} 被重复定义",
        )
    defined.add(operand.value.name)


def _validate_static_machine_hazards(function: MachineFunction) -> None:
    """拒绝静态可判定会触发 x64 机器语义错误的场景。"""
    in_values, in_slots, out_values, out_slots = _compute_static_known_states(function)
    for block in function.blocks:
        _walk_static_known_block(
            function,
            block,
            in_values[block.name],
            in_slots[block.name],
            predecessor_values=out_values,
            predecessor_slots=out_slots,
            raise_idiv_errors=True,
        )


def _compute_static_known_states(
    function: MachineFunction,
) -> tuple[
    dict[str, dict[str, int | None]],
    dict[str, dict[tuple[str, int | str], int | None]],
    dict[str, dict[str, int | None]],
    dict[str, dict[tuple[str, int | str], int | None]],
]:
    """计算每个基本块入口和出口处的静态已知常量状态。"""
    in_values: dict[str, dict[str, int | None]] = {block.name: {} for block in function.blocks}
    in_slots: dict[str, dict[tuple[str, int | str], int | None]] = {block.name: {} for block in function.blocks}
    out_values: dict[str, dict[str, int | None]] = {block.name: {} for block in function.blocks}
    out_slots: dict[str, dict[tuple[str, int | str], int | None]] = {block.name: {} for block in function.blocks}
    predecessors = _cfg_predecessors(function)
    changed = True
    iteration = 0
    max_iterations = max(16, len(function.blocks) * len(function.blocks) * 4)
    while changed:
        iteration += 1
        if iteration > max_iterations:
            raise NativeCodegenError(
                f"函数 {function.name}: native 机器码 MVP 静态常量分析未收敛，"
                f"已迭代 {max_iterations} 次"
            )
        changed = False
        for block in function.blocks:
            values, slots = _static_known_entry_state(block.name, predecessors, out_values, out_slots)
            next_values, next_slots = _walk_static_known_block(
                function,
                block,
                values,
                slots,
                predecessor_values=out_values,
                predecessor_slots=out_slots,
                raise_idiv_errors=False,
            )
            if values != in_values[block.name] or slots != in_slots[block.name]:
                in_values[block.name] = values
                in_slots[block.name] = slots
                changed = True
            if next_values != out_values[block.name] or next_slots != out_slots[block.name]:
                out_values[block.name] = next_values
                out_slots[block.name] = next_slots
                changed = True
    return in_values, in_slots, out_values, out_slots


def _static_known_entry_state(
    block_name: str,
    predecessors: dict[str, set[str]],
    out_values: dict[str, dict[str, int | None]],
    out_slots: dict[str, dict[tuple[str, int | str], int | None]],
) -> tuple[dict[str, int | None], dict[tuple[str, int | str], int | None]]:
    """合并静态常量分析的基本块入口状态。"""
    block_predecessors = sorted(predecessors.get(block_name, set()))
    if not block_predecessors:
        return {}, {}
    return _merge_static_known_maps(block_predecessors, out_values), _merge_static_known_maps(block_predecessors, out_slots)


def _cfg_predecessors(function: MachineFunction) -> dict[str, set[str]]:
    """从终结指令目标反推 CFG 前驱集合。"""
    predecessors: dict[str, set[str]] = {block.name: set() for block in function.blocks}
    for block in function.blocks:
        terminator = block.terminator
        if terminator is None:
            continue
        for target in terminator.targets:
            if target in predecessors:
                predecessors[target].add(block.name)
    return predecessors


def _merge_static_known_maps(
    predecessors: list[str],
    states: dict[str, dict[object, int | None]],
) -> dict[object, int | None]:
    """合并多个前驱的已知常量映射。"""
    merged: dict[object, int | None] = {}
    keys: set[object] = set()
    for predecessor in predecessors:
        keys.update(states.get(predecessor, {}))
    for key in keys:
        values = [states.get(predecessor, {}).get(key) for predecessor in predecessors]
        first = values[0] if values else None
        merged[key] = first if first is not None and all(value == first for value in values) else None
    return merged


def _walk_static_known_block(
    function: MachineFunction,
    block: MachineBlock,
    in_values: dict[str, int | None],
    in_slots: dict[tuple[str, int | str], int | None],
    *,
    predecessor_values: dict[str, dict[str, int | None]],
    predecessor_slots: dict[str, dict[tuple[str, int | str], int | None]],
    raise_idiv_errors: bool,
) -> tuple[dict[str, int | None], dict[tuple[str, int | str], int | None]]:
    """模拟单个基本块内的静态常量状态。"""
    known_values = dict(in_values)
    known_slots = dict(in_slots)
    for instruction in block.instructions:
        reject_static_error = raise_idiv_errors and "numeric_kind" not in instruction.attrs
        if instruction.op in {"idiv", "imod"}:
            dividend = instruction.args[0]
            divisor = instruction.args[1]
            known_dividend = _static_known_value(dividend, known_values, known_slots)
            known_divisor = _static_known_value(divisor, known_values, known_slots)
            if reject_static_error and known_divisor == 0:
                raise _machine_node_error(
                    function,
                    instruction,
                    "native 机器码 MVP 暂不生成除数为 0 的 idiv/imod 机器码",
                )
            if reject_static_error and known_dividend == _INT64_MIN and known_divisor == -1:
                raise _machine_node_error(
                    function,
                    instruction,
                    "native 机器码 MVP 暂不生成会触发 signed int64 溢出的 idiv/imod 机器码",
                )
        _, overflows = _static_wrapping_arithmetic_result(instruction, known_values, known_slots)
        if reject_static_error and overflows:
            raise _machine_node_error(
                function,
                instruction,
                f"native 机器码 MVP 暂不生成静态可判定会超出 signed int64 范围的 {instruction.op} 机器码",
            )
        if instruction.op == "store_stack":
            known_slots[_static_stack_slot_key(instruction.args[0])] = _static_known_value(instruction.args[1], known_values, known_slots)
            continue
        if instruction.result is None or instruction.result.kind != "vreg":
            continue
        if instruction.op == "load_imm":
            known_values[instruction.result.value.name] = int(instruction.args[0].value)
        elif instruction.op == "load_stack":
            known_values[instruction.result.value.name] = known_slots.get(_static_stack_slot_key(instruction.args[0]))
        elif instruction.op == "phi":
            known_values[instruction.result.value.name] = _static_phi_result_value(
                instruction,
                predecessor_values,
                predecessor_slots,
            )
        else:
            known_values[instruction.result.value.name] = _static_instruction_result_value(instruction, known_values, known_slots)
    return known_values, known_slots


def _static_instruction_result_value(
    instruction: MachineInstruction,
    known_values: dict[str, int | None],
    known_slots: dict[tuple[str, int | str], int | None],
) -> int | None:
    """计算静态常量分析可安全保留的指令结果。"""
    arithmetic_value, overflows = _static_wrapping_arithmetic_result(instruction, known_values, known_slots)
    if arithmetic_value is not None or overflows:
        return arithmetic_value
    if instruction.op in {"add", "sub", "imul", "idiv", "imod", "cmp_eq", "cmp_ne", "cmp_lt", "cmp_le", "cmp_gt", "cmp_ge"}:
        left = _static_known_value(instruction.args[0], known_values, known_slots)
        right = _static_known_value(instruction.args[1], known_values, known_slots)
        if left is None or right is None:
            return None
        if instruction.op in {"idiv", "imod"}:
            if right == 0 or (left == _INT64_MIN and right == -1):
                return None
            quotient, remainder = integer_divmod(left, right)
            return _static_int64_value(quotient if instruction.op == "idiv" else remainder)
        if instruction.op == "cmp_eq":
            return 1 if left == right else 0
        if instruction.op == "cmp_ne":
            return 1 if left != right else 0
        if instruction.op == "cmp_lt":
            return 1 if left < right else 0
        if instruction.op == "cmp_le":
            return 1 if left <= right else 0
        if instruction.op == "cmp_gt":
            return 1 if left > right else 0
        if instruction.op == "cmp_ge":
            return 1 if left >= right else 0
    if instruction.op in {"neg", "not_bool", "cast_bool_int", "cast_int_bool"}:
        value = _static_known_value(instruction.args[0], known_values, known_slots)
        if value is None:
            return None
        if instruction.op == "neg":
            return _static_int64_value(-value)
        if instruction.op == "not_bool":
            if instruction.args[0].type_hint in FLOAT_VALUE_TYPES:
                value &= 0x7FFFFFFF if instruction.args[0].type_hint == "float32" else 0x7FFFFFFFFFFFFFFF
            return 0 if value else 1
        if instruction.op == "cast_int_bool":
            if instruction.args[0].type_hint in FLOAT_VALUE_TYPES:
                value &= 0x7FFFFFFF if instruction.args[0].type_hint == "float32" else 0x7FFFFFFFFFFFFFFF
            return 1 if value else 0
        return _static_int64_value(value)
    return None


def _static_phi_result_value(
    instruction: MachineInstruction,
    predecessor_values: dict[str, dict[str, int | None]],
    predecessor_slots: dict[str, dict[tuple[str, int | str], int | None]],
) -> int | None:
    """计算所有 incoming 值一致时的 phi 静态常量。"""
    incoming_blocks = [str(item) for item in instruction.attrs.get("incoming_blocks", [])]
    if len(incoming_blocks) != len(instruction.args) or not incoming_blocks:
        return None
    values: list[int | None] = []
    for incoming, operand in zip(incoming_blocks, instruction.args):
        values.append(_static_known_value(operand, predecessor_values.get(incoming, {}), predecessor_slots.get(incoming, {})))
    first = values[0]
    return first if first is not None and all(value == first for value in values) else None


def _static_wrapping_arithmetic_result(
    instruction: MachineInstruction,
    known_values: dict[str, int | None],
    known_slots: dict[tuple[str, int | str], int | None],
) -> tuple[int | None, bool]:
    """计算会由 x64 机器指令回绕的静态整数运算结果。"""
    if instruction.op in {"add", "sub", "imul"}:
        left = _static_known_value(instruction.args[0], known_values, known_slots)
        right = _static_known_value(instruction.args[1], known_values, known_slots)
        if left is None or right is None:
            return None, False
        if instruction.op == "add":
            return _static_checked_int64(left + right)
        if instruction.op == "sub":
            return _static_checked_int64(left - right)
        return _static_checked_int64(left * right)
    if instruction.op == "neg":
        value = _static_known_value(instruction.args[0], known_values, known_slots)
        if value is None:
            return None, False
        return _static_checked_int64(-value)
    return None, False


def _static_checked_int64(value: int) -> tuple[int | None, bool]:
    """返回 signed int64 结果及是否溢出。"""
    return (value, False) if _INT64_MIN <= value <= _INT64_MAX else (None, True)


def _static_int64_value(value: int) -> int | None:
    """保留 signed int64 范围内的静态整数。"""
    return value if _INT64_MIN <= value <= _INT64_MAX else None


def _static_known_value(
    operand: MachineOperand,
    known_values: dict[str, int | None],
    known_slots: dict[tuple[str, int | str], int | None],
) -> int | None:
    """读取静态风险分析中已知的操作数常量值。"""
    if operand.kind == "imm":
        return int(operand.value)
    if operand.kind == "vreg":
        return known_values.get(operand.value.name)
    if operand.kind == "slot":
        return known_slots.get(_static_stack_slot_key(operand))
    return None


def _static_stack_slot_key(operand: MachineOperand) -> tuple[str, int | str]:
    """生成静态风险分析使用的栈槽键。"""
    return operand.value.kind, operand.value.index


def _validate_exit_instructions(function: MachineFunction) -> None:
    """校验 native exit 指令形状。"""
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.op != "exit":
                continue
            if len(instruction.args) != 1:
                raise _machine_node_error(
                    function,
                    instruction,
                    f"native 机器码 MVP exit 需要 1 个参数，实际 {len(instruction.args)} 个",
                )


def _validate_terminator_targets(function: MachineFunction) -> None:
    """校验跳转终结指令引用的基本块存在。"""
    block_names = {block.name for block in function.blocks}
    for block in function.blocks:
        terminator = block.terminator
        if terminator is None or terminator.op not in {"jmp", "br"}:
            continue
        for target in terminator.targets:
            if target not in block_names:
                raise _machine_node_error(
                    function,
                    terminator,
                    f"native 机器码 MVP 跳转到未知目标 {target}",
                )


def _validate_phi_incoming_blocks(function: MachineFunction) -> None:
    """校验 phi incoming_blocks 与真实 CFG 前驱边一致。"""
    block_names = {block.name for block in function.blocks}
    predecessors = _cfg_predecessors(function)
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.op != "phi":
                continue
            incoming_blocks = [str(item) for item in instruction.attrs.get("incoming_blocks", [])]
            if len(incoming_blocks) != len(instruction.args):
                raise _machine_node_error(function, instruction, "native 机器码 MVP phi incoming_blocks 与参数数量不一致")
            if len(set(incoming_blocks)) != len(incoming_blocks):
                raise _machine_node_error(function, instruction, "native 机器码 MVP phi incoming_blocks 存在重复前驱")
            for incoming in incoming_blocks:
                if incoming not in block_names:
                    raise _machine_node_error(function, instruction, f"native 机器码 MVP phi 引用了未知前驱 {incoming}")
                if incoming not in predecessors.get(block.name, set()):
                    raise _machine_node_error(
                        function,
                        instruction,
                        f"native 机器码 MVP phi 前驱 {incoming} 不会跳转到基本块 {block.name}",
                )


def _validate_phi_sources_defined(function: MachineFunction) -> None:
    """校验 phi 来源虚拟寄存器已在函数内定义。"""
    defined = {
        instruction.result.value.name
        for block in function.blocks
        for instruction in block.instructions
        if instruction.result is not None and instruction.result.kind == "vreg"
    }
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.op != "phi":
                continue
            for operand in instruction.args:
                if operand.kind == "vreg" and operand.value.name not in defined:
                    raise _machine_node_error(
                        function,
                        instruction,
                        f"native 机器码 MVP phi 来源虚拟寄存器 %{operand.value.name} 未定义",
                    )


def _validate_call_argument_types(function: MachineFunction, function_param_types: dict[str, list[str]]) -> None:
    """校验 call 实参类型与 callee 形参类型兼容。"""
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.op != "call" or not instruction.args or instruction.args[0].kind != "symbol":
                continue
            callee = str(instruction.args[0].value)
            param_types = function_param_types.get(callee)
            if param_types is None:
                continue
            call_args = instruction.args[1:]
            if len(call_args) != len(param_types):
                continue
            for index, (operand, param_type) in enumerate(zip(call_args, param_types)):
                if not is_argument_type_compatible(param_type, operand.type_hint):
                    raise _machine_node_error(
                        function,
                        instruction,
                        f"native 机器码 MVP 调用 {callee} 第 {index} 个参数类型不匹配: 需要 {param_type}, 实际 {operand.type_hint}",
                    )


def _machine_node_error(function: MachineFunction, node: MachineInstruction | MachineTerminator, message: str) -> NativeCodegenError:
    """构造 Machine IR 节点级机器码生成错误。"""
    parts = [f"函数 {function.name}", f"Machine IR 指令 {getattr(node, 'op', '<unknown>')}"]
    if node.source_line is not None:
        parts.append(f"行 {node.source_line}")
    if node.source_pc is not None:
        parts.append(f"PC {node.source_pc}")
    return NativeCodegenError(f"{', '.join(parts)}: {message}")


class _NativeCodegenContext:
    def __init__(
        self,
        function: MachineFunction,
        code: bytearray | None = None,
        function_offsets: dict[str, int] | None = None,
        pending_calls: list[_PendingJump] | None = None,
        function_names: set[str] | None = None,
        function_return_types: dict[str, str] | None = None,
        function_param_counts: dict[str, int] | None = None,
        function_param_types: dict[str, list[str]] | None = None,
        abi: WindowsX64ABI | None = None,
        global_frame_owner: bool = False,
    ):
        self.function = function
        self.instructions: list[NativeCodeInstruction] = []
        self.code = code if code is not None else bytearray()
        self.start_offset = len(self.code)
        self.function_offsets = function_offsets if function_offsets is not None else {}
        self.pending_calls = pending_calls if pending_calls is not None else []
        self.function_names = function_names if function_names is not None else {function.name}
        self.function_return_types = function_return_types if function_return_types is not None else {function.name: function.return_type}
        self.function_param_counts = function_param_counts if function_param_counts is not None else {function.name: len(function.params)}
        self.function_param_types = function_param_types if function_param_types is not None else {function.name: list(function.param_types)}
        self.abi = abi
        self.global_frame_owner = global_frame_owner
        self.block_offsets: dict[str, int] = {}
        self.pending_jumps: list[_PendingJump] = []
        self.call_frames: list[NativeCallFrameAllocation] = []
        self.relocations: list[NativeRelocation] = []
        self.exit_probes: list[NativeExitProbe] = []
        self.exit_propagation_labels: list[tuple[str, int | None, int | None]] = []
        self.phi_copies = self._build_phi_copies()
        self.synthetic_label_id = 0
        self.constant_vregs: dict[str, int] = {}
        self.constant_slots: dict[tuple[str, int | str], int | None] = {}
        (
            self.static_entry_values,
            self.static_entry_slots,
            self.static_exit_values,
            self.static_exit_slots,
        ) = _compute_static_known_states(function)
        self.slot_offsets = self._build_slot_offsets()
        self.frame_size = self._build_frame_size()
        if self.frame_size < 0 or self.frame_size > _INT32_MAX:
            raise self._function_error(f"native 机器码 MVP 栈帧大小超出 signed int32 编码范围: {self.frame_size}")
        for (kind, index), offset in self.slot_offsets.items():
            if offset <= 0 or offset > _INT32_MAX:
                raise self._function_error(
                    f"native 机器码 MVP 栈槽 {kind}[{index}] 偏移超出 signed int32 编码范围: {offset}"
                )

    def generate(self) -> NativeCodeFunction:
        """生成单个函数的机器码。"""
        self.function_offsets[self.function.name] = self.start_offset
        self._emit(encode_prologue(self.frame_size), self._prologue_asm(), "prologue", None, None)
        if self.global_frame_owner and self.function.frame.global_slots:
            self._emit(encode_mov_r11_rbp(), "mov r11, rbp ; global frame", "prologue", None, None)
        self._store_register_params()
        for block in self.function.blocks:
            self.block_offsets[block.name] = len(self.code)
            self._emit(b"", f"{block.name}:", "label", None, None)
            self.constant_vregs = {
                name: value
                for name, value in self.static_entry_values.get(block.name, {}).items()
                if value is not None
            }
            self.constant_slots = dict(self.static_entry_slots.get(block.name, {}))
            for instruction in block.instructions:
                self._lower_instruction(instruction)
            if block.terminator is None:
                raise self._function_error(f"native 机器码 MVP 需要基本块 {block.name} 的终结指令")
            self._lower_terminator(block.terminator)
        self._emit_exit_propagation_blocks()
        self._patch_pending_jumps()
        stack_slot_allocations = self._stack_slot_allocations()
        has_global_frame_slots = any(slot.name.startswith("global[") for slot in stack_slot_allocations)
        return NativeCodeFunction(
            name=self.function.name,
            code=bytes(self.code[self.start_offset:]),
            instructions=self.instructions,
            frame_size=self.frame_size,
            offset=self.start_offset,
            stack_slots=stack_slot_allocations,
            call_frames=self.call_frames,
            relocations=self.relocations,
            exit_probes=self.exit_probes,
            register_allocation=NativeRegisterAllocation(
                argument_registers=tuple(param.name for param in self.function.params if param.kind == "register"),
                frame_pointer=self.abi.registers.frame_pointer,
                stack_pointer=self.abi.registers.stack_pointer,
                return_register="XMM0" if self.function.return_type in FLOAT_VALUE_TYPES else self.abi.registers.return_register,
                global_frame_register="R11" if has_global_frame_slots else None,
                global_frame_role="owner" if self.global_frame_owner and has_global_frame_slots else (
                    "borrowed" if has_global_frame_slots else "none"
                ),
            ),
            return_type=self.function.return_type,
            param_types=tuple(_function_param_types(self.function)),
        )

    def _lower_instruction(self, instruction: MachineInstruction) -> None:
        op = instruction.op
        if op == "load_string":
            result = self._result_slot_offset(instruction)
            self._emit(bytes.fromhex("48 8D 05 00 00 00 00"), "lea rax, [rip+字符串常量]", op,
                       instruction.source_pc, instruction.source_line, dict(instruction.attrs))
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", op,
                       instruction.source_pc, instruction.source_line)
            return
        if op == "load_imm":
            result = self._result_slot_offset(instruction)
            if instruction.args[0].kind != "imm":
                self._unsupported(instruction, f"operand:{instruction.args[0].kind}")
            value = int(instruction.args[0].value)
            if instruction.result is not None and instruction.result.kind == "vreg":
                self.constant_vregs[str(instruction.result.value.name)] = value
            self._emit(encode_mov_rax_imm64(value), f"mov rax, {value}", op, instruction.source_pc, instruction.source_line)
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", op, instruction.source_pc, instruction.source_line)
            return
        if op == "load_stack":
            if instruction.result is not None and instruction.result.kind == "vreg":
                known_value = self.constant_slots.get(_static_stack_slot_key(instruction.args[0]))
                if known_value is None:
                    self.constant_vregs.pop(str(instruction.result.value.name), None)
                else:
                    self.constant_vregs[str(instruction.result.value.name)] = known_value
            result = self._result_slot_offset(instruction)
            source = self._slot_offset(instruction.args[0], instruction)
            if self._uses_global_frame(instruction.args[0]):
                self._emit(encode_mov_rax_from_r11_offset(source), f"mov rax, [r11-{source}]", op, instruction.source_pc, instruction.source_line)
            else:
                self._emit(encode_mov_rax_from_rbp_offset(source), f"mov rax, [rbp-{source}]", op, instruction.source_pc, instruction.source_line)
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", op, instruction.source_pc, instruction.source_line)
            return
        if op == "store_stack":
            target = self._slot_offset(instruction.args[0], instruction)
            self._load_operand_to_rax(instruction.args[1], instruction)
            self.constant_slots[_static_stack_slot_key(instruction.args[0])] = _static_known_value(
                instruction.args[1],
                self.constant_vregs,
                self.constant_slots,
            )
            if self._uses_global_frame(instruction.args[0]):
                self._emit(encode_mov_r11_offset_from_rax(target), f"mov [r11-{target}], rax", op, instruction.source_pc, instruction.source_line)
            else:
                self._emit(encode_mov_rbp_offset_from_rax(target), f"mov [rbp-{target}], rax", op, instruction.source_pc, instruction.source_line)
            return
        if op == "phi":
            if instruction.result is not None and instruction.result.kind == "vreg":
                result_name = str(instruction.result.value.name)
                value = _static_phi_result_value(instruction, self.static_exit_values, self.static_exit_slots)
                if value is None:
                    self.constant_vregs.pop(result_name, None)
                else:
                    self.constant_vregs[result_name] = value
            return
        if op == "mov" and instruction.attrs.get("kind") == "register_function":
            return
        if op in {"fadd", "fsub", "fimul", "fidiv", "fcmp_eq", "fcmp_ne", "fcmp_lt", "fcmp_le", "fcmp_gt", "fcmp_ge"}:
            self._lower_float_binary(instruction)
            return
        if op == "cast_float":
            self._lower_float_cast(instruction)
            return
        if op == "fneg":
            self._load_operand_to_rax(instruction.args[0], instruction)
            mask = 1 << 31 if instruction.result.type_hint == "float32" else _INT64_MIN
            self._emit(encode_mov_r10_imm64(mask), f"mov r10, {mask}", op, instruction.source_pc, instruction.source_line)
            self._emit(encode_xor_rax_r10(), "xor rax, r10", op, instruction.source_pc, instruction.source_line)
            result = self._result_slot_offset(instruction)
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", op, instruction.source_pc, instruction.source_line)
            return
        if op in _BINARY_OP_ASM:
            self._lower_binary(instruction)
            return
        if op == "neg":
            self._lower_neg(instruction)
            return
        if op == "not_bool":
            self._lower_not_bool(instruction)
            return
        if op in _COMPARE_OPS:
            self._lower_compare(instruction)
            return
        if op == "cast_bool_int":
            result = self._result_slot_offset(instruction)
            target_type = str(instruction.attrs.get("target_type", "")).lower()
            source = instruction.args[0]
            cast_constant = _static_known_value(source, self.constant_vregs, self.constant_slots)
            if target_type in _NARROW_INTEGER_CAST_RANGES:
                minimum, maximum = _NARROW_INTEGER_CAST_RANGES[target_type]
                if cast_constant is not None and (cast_constant < minimum or cast_constant > maximum):
                    cast_constant = None
            if instruction.result is not None and instruction.result.kind == "vreg":
                if cast_constant is None:
                    self.constant_vregs.pop(str(instruction.result.value.name), None)
                else:
                    self.constant_vregs[str(instruction.result.value.name)] = cast_constant
            cast_note = f" ; cast to {target_type}" if target_type else ""
            self._load_operand_to_rax(instruction.args[0], instruction)
            if cast_constant is None:
                error_code = {"char": 3, "short": 4, "int": 5}.get(target_type, 6)
                self._emit_integer_range_check(target_type, instruction, error_code)
            self._emit(
                encode_mov_rbp_offset_from_rax(result),
                f"mov [rbp-{result}], rax{cast_note}",
                op,
                instruction.source_pc,
                instruction.source_line,
                source_attrs={"target_type": target_type},
            )
            return
        if op == "cast_int_bool":
            result = self._result_slot_offset(instruction)
            self._remember_static_result(instruction)
            self._load_operand_to_rax(instruction.args[0], instruction)
            self._mask_float_sign(instruction.args[0].type_hint, instruction)
            self._emit(encode_mov_r10_imm64(0), "mov r10, 0", op, instruction.source_pc, instruction.source_line)
            self._emit(encode_cmp_rax_r10(), "cmp rax, r10", op, instruction.source_pc, instruction.source_line)
            self._emit(encode_setcc_al(ConditionCode.NE), "setne al", op, instruction.source_pc, instruction.source_line)
            self._emit(encode_movzx_rax_al(), "movzx rax, al", op, instruction.source_pc, instruction.source_line)
            target_type = instruction.attrs.get("target_type")
            cast_note = f" ; cast to {target_type}" if target_type else " ; cast to bool"
            self._emit(
                encode_mov_rbp_offset_from_rax(result),
                f"mov [rbp-{result}], rax{cast_note}",
                op,
                instruction.source_pc,
                instruction.source_line,
                source_attrs={"target_type": target_type or "bool"},
            )
            return
        if op == "call":
            self._lower_call(instruction)
            return
        if op == "exit":
            self._lower_exit(instruction)
            return
        if op == "set_exit_code":
            return
        self._unsupported(instruction, op)

    def _mask_float_sign(self, type_hint: str, node) -> None:
        """标量真值转换忽略浮点符号位，使正负零都为假。"""
        if type_hint == "string":
            self._emit(b"\x48\x8B\x00", "mov rax, [rax] ; 字符串字节长度", node.op,
                       node.source_pc, node.source_line)
            return
        if type_hint not in FLOAT_VALUE_TYPES:
            return
        mask = 0x7FFFFFFF if type_hint == "float32" else 0x7FFFFFFFFFFFFFFF
        self._emit(encode_mov_r10_imm64(mask), f"mov r10, {mask}", "numeric_guard", node.source_pc, node.source_line)
        self._emit(b"\x4C\x21\xD0", "and rax, r10", "numeric_guard", node.source_pc, node.source_line)

    def _emit_float_range_check(self, type_hint: str, node) -> None:
        """检查 XMM0 中的结果有限，并将位模式恢复到 RAX。"""
        single = type_hint == "float32"
        transfer = encode_sse_transfer(0, to_rax=True, single=single)
        transfer_asm = "movd eax, xmm0" if single else "movq rax, xmm0"
        self._emit(transfer, transfer_asm, node.op, node.source_pc, node.source_line)
        mask = 0x7F800000 if single else 0x7FF0000000000000
        self._emit(encode_mov_r10_imm64(mask), f"mov r10, {mask}", "numeric_guard", node.source_pc, node.source_line)
        self._emit(b"\x4C\x21\xD0", "and rax, r10", "numeric_guard", node.source_pc, node.source_line)
        self._emit(encode_cmp_rax_r10(), "cmp rax, r10", "numeric_guard", node.source_pc, node.source_line)
        self._emit_numeric_guard(0x75, 7, node)
        self._emit(transfer, transfer_asm, node.op, node.source_pc, node.source_line)

    def _lower_float_binary(self, instruction: MachineInstruction) -> None:
        """
        使用 SSE 执行同类型浮点运算和比较。

        Args:
            instruction: 已完成共同类型转换的浮点指令。
        """
        single = instruction.args[0].type_hint == "float32"
        for index, operand in enumerate(instruction.args):
            self._load_operand_to_rax(operand, instruction)
            self._emit(encode_sse_transfer(index), f"movq xmm{index}, rax", instruction.op, instruction.source_pc, instruction.source_line)
        if instruction.op == "fidiv":
            self._mask_float_sign(instruction.args[1].type_hint, instruction)
            self._emit(b"\x48\x85\xC0", "test rax, rax", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit_numeric_guard(0x75, 8, instruction)
        if instruction.op.startswith("fcmp_"):
            comparison = (b"" if single else b"\x66") + b"\x0F\x2E\xC1"
            self._emit(comparison, "ucomiss xmm0, xmm1" if single else "ucomisd xmm0, xmm1", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit_numeric_guard(0x7B, 7, instruction)
            opcode = {"fcmp_eq": 0x94, "fcmp_ne": 0x95, "fcmp_lt": 0x92, "fcmp_le": 0x96, "fcmp_gt": 0x97, "fcmp_ge": 0x93}[instruction.op]
            self._emit(bytes([0x0F, opcode, 0xC0]), f"{instruction.op} al", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit(encode_movzx_rax_al(), "movzx rax, al", instruction.op, instruction.source_pc, instruction.source_line)
        else:
            opcode = {"fadd": 0x58, "fsub": 0x5C, "fimul": 0x59, "fidiv": 0x5E}[instruction.op]
            code = bytes([0xF3 if single else 0xF2, 0x0F, opcode, 0xC1])
            self._emit(code, f"{instruction.op} xmm0, xmm1", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit_float_range_check(instruction.result.type_hint, instruction)
        result = self._result_slot_offset(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)

    def _lower_float_cast(self, instruction: MachineInstruction) -> None:
        """
        生成整数与浮点数转换，浮点转整数先检查 64 位转换的有效范围。

        Args:
            instruction: 带目标类型和源操作数类型的转换指令。
        """
        source_type = instruction.args[0].type_hint
        target_type = instruction.result.type_hint
        self._load_operand_to_rax(instruction.args[0], instruction)
        if source_type in FLOAT_VALUE_TYPES:
            self._emit(encode_sse_transfer(0), "movq xmm0, rax", instruction.op, instruction.source_pc, instruction.source_line)
        if target_type in FLOAT_VALUE_TYPES:
            if source_type not in FLOAT_VALUE_TYPES:
                prefix = b"\xF3" if target_type == "float32" else b"\xF2"
                self._emit(prefix + b"\x48\x0F\x2A\xC0", "cvtsi2ss xmm0, rax" if target_type == "float32" else "cvtsi2sd xmm0, rax", instruction.op, instruction.source_pc, instruction.source_line)
            elif source_type != target_type:
                prefix = b"\xF2" if target_type == "float32" else b"\xF3"
                self._emit(prefix + b"\x0F\x5A\xC0", "cvtsd2ss xmm0, xmm0" if target_type == "float32" else "cvtss2sd xmm0, xmm0", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit_float_range_check(target_type, instruction)
        else:
            single = source_type == "float32"
            kind = VBCObjectType.FLOAT if single else VBCObjectType.DOUBLE
            for bound, safe_condition in ((-(2**63), 0x73), (2**63, 0x72)):
                self._emit(encode_mov_rax_imm64(float_bits(float(bound), kind)), f"mov rax, {bound} 的浮点位模式", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit(encode_sse_transfer(1), "movq xmm1, rax", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit((b"" if single else b"\x66") + b"\x0F\x2E\xC1", "ucomiss xmm0, xmm1" if single else "ucomisd xmm0, xmm1", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit_numeric_guard(safe_condition, 9, instruction)
            self._emit(bytes([0xF3 if single else 0xF2, 0x48, 0x0F, 0x2C, 0xC0]), "cvttss2si rax, xmm0" if single else "cvttsd2si rax, xmm0", instruction.op, instruction.source_pc, instruction.source_line)
            target_kind = instruction.attrs["target_type"]
            self._emit_integer_range_check(target_kind, instruction, {"char": 3, "short": 4, "int": 5}.get(target_kind, 6))
        result = self._result_slot_offset(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)

    def _lower_binary(self, instruction: MachineInstruction) -> None:
        result = self._result_slot_offset(instruction)
        self._load_operand_to_rax(instruction.args[0], instruction)
        self._load_operand_to_r10(instruction.args[1], instruction)
        if instruction.op == "add":
            code = encode_add_rax_r10()
        elif instruction.op == "sub":
            code = encode_sub_rax_r10()
        elif instruction.op == "imul":
            code = encode_imul_rax_r10()
        else:
            if "numeric_kind" not in instruction.attrs and instruction.args[1].kind == "imm" and int(instruction.args[1].value) == 0:
                raise self._node_error(instruction, "native 机器码 MVP 暂不生成除数为 0 的 idiv/imod 机器码")
            known_left = _static_known_value(instruction.args[0], self.constant_vregs, self.constant_slots)
            known_right = _static_known_value(instruction.args[1], self.constant_vregs, self.constant_slots)
            if known_right is None or known_right == 0:
                self._emit(b"\x4D\x85\xD2", "test r10, r10", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit_numeric_guard(0x75, 8, instruction)
            numeric_kind = instruction.attrs.get("numeric_kind", "long")
            minimum = _NARROW_INTEGER_CAST_RANGES.get(numeric_kind, (_INT64_MIN, _INT64_MAX))[0]
            if known_left is None or known_right is None or (known_left == minimum and known_right == -1):
                # 临时保存除数，检查 MIN/-1 后恢复，避免 CPU 整数除法异常。
                self._emit(b"\x4C\x89\xD2", "mov rdx, r10", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit(encode_mov_r10_imm64(minimum), f"mov r10, {minimum}", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit(encode_cmp_rax_r10(), "cmp rax, r10", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit(b"\x41\x0F\x94\xC2", "sete r10b", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit(b"\x48\x83\xFA\xFF", "cmp rdx, -1", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit(b"\x0F\x94\xC1\x44\x20\xD1", "sete cl; and cl, r10b", instruction.op, instruction.source_pc, instruction.source_line)
                self._emit_numeric_guard(0x74, 2, instruction)
                self._emit(b"\x49\x89\xD2", "mov r10, rdx", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit(encode_cqo(), "cqo", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit(encode_idiv_r10(), "idiv r10", instruction.op, instruction.source_pc, instruction.source_line)
            if instruction.op == "imod":
                self._emit(encode_mov_rax_rdx(), "mov rax, rdx", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit_integer_range_check(instruction.attrs.get("numeric_kind", "long"), instruction)
            self._remember_static_result(instruction)
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)
            return
        self._emit(code, _BINARY_OP_ASM[instruction.op], instruction.op, instruction.source_pc, instruction.source_line)
        if _static_instruction_result_value(instruction, self.constant_vregs, self.constant_slots) is None:
            self._emit_numeric_guard(0x71, 2, instruction)
        self._emit_integer_range_check(instruction.attrs.get("numeric_kind", "long"), instruction)
        self._remember_static_result(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)

    def _lower_neg(self, instruction: MachineInstruction) -> None:
        """生成整数取负。"""
        result = self._result_slot_offset(instruction)
        self._load_operand_to_rax(instruction.args[0], instruction)
        self._emit(encode_neg_rax(), "neg rax", "neg", instruction.source_pc, instruction.source_line)
        if _static_instruction_result_value(instruction, self.constant_vregs, self.constant_slots) is None:
            self._emit_numeric_guard(0x71, 2, instruction)
        self._emit_integer_range_check(instruction.attrs.get("numeric_kind", "long"), instruction)
        self._remember_static_result(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", "neg", instruction.source_pc, instruction.source_line)

    def _lower_not_bool(self, instruction: MachineInstruction) -> None:
        """生成 C 风格逻辑非。"""
        result = self._result_slot_offset(instruction)
        self._load_operand_to_rax(instruction.args[0], instruction)
        self._mask_float_sign(instruction.args[0].type_hint, instruction)
        self._emit(encode_mov_r10_imm64(0), "mov r10, 0", "not_bool", instruction.source_pc, instruction.source_line)
        self._emit(encode_cmp_rax_r10(), "cmp rax, r10", "not_bool", instruction.source_pc, instruction.source_line)
        self._emit(encode_setcc_al(ConditionCode.EQ), "seteq al", "not_bool", instruction.source_pc, instruction.source_line)
        self._emit(encode_movzx_rax_al(), "movzx rax, al", "not_bool", instruction.source_pc, instruction.source_line)
        self._remember_static_result(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", "not_bool", instruction.source_pc, instruction.source_line)

    def _lower_compare(self, instruction: MachineInstruction) -> None:
        result = self._result_slot_offset(instruction)
        self._load_operand_to_rax(instruction.args[0], instruction)
        self._load_operand_to_r10(instruction.args[1], instruction)
        self._emit(encode_cmp_rax_r10(), "cmp rax, r10", instruction.op, instruction.source_pc, instruction.source_line)
        self._emit(encode_setcc_al(_COMPARE_OPS[instruction.op]), f"set{_COMPARE_OPS[instruction.op].value} al", instruction.op, instruction.source_pc, instruction.source_line)
        self._emit(encode_movzx_rax_al(), "movzx rax, al", instruction.op, instruction.source_pc, instruction.source_line)
        self._remember_static_result(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)

    def _remember_static_result(self, instruction: MachineInstruction) -> None:
        """记录发射阶段仍可证明的静态常量结果。"""
        if instruction.result is None or instruction.result.kind != "vreg":
            return
        result_name = str(instruction.result.value.name)
        value = _static_instruction_result_value(instruction, self.constant_vregs, self.constant_slots)
        if value is None:
            self.constant_vregs.pop(result_name, None)
        else:
            self.constant_vregs[result_name] = value

    def _emit_numeric_guard(self, safe_condition: int, error_code: int, node) -> None:
        """检查失败时通过已有的 RDX 状态通道返回数值错误。"""
        failure = encode_mov_rdx_imm64(error_code) + encode_mov_rax_imm64(node.source_line or -1) + encode_epilogue()
        self._emit(bytes([safe_condition, len(failure)]), f"jcc +{len(failure)} ; 数值检查通过", "numeric_guard", node.source_pc, node.source_line)
        self._emit(failure, f"数值错误 {error_code}; 返回调用者", "numeric_error", node.source_pc, node.source_line, source_attrs={"error_code": error_code})

    def _emit_integer_range_check(self, kind: str, node, error_code: int = 2) -> None:
        """校验保存在 RAX 中的整数符合目标类型的位宽。"""
        limits = _NARROW_INTEGER_CAST_RANGES.get(kind)
        if limits is None or limits == (_INT64_MIN, _INT64_MAX):
            return
        for bound, safe_condition in ((limits[0], 0x7D), (limits[1], 0x7E)):
            self._emit(encode_mov_r10_imm64(bound), f"mov r10, {bound}", "numeric_guard", node.source_pc, node.source_line)
            self._emit(encode_cmp_rax_r10(), "cmp rax, r10", "numeric_guard", node.source_pc, node.source_line)
            self._emit_numeric_guard(safe_condition, error_code, node)

    def _lower_call(self, instruction: MachineInstruction) -> None:
        """生成用户函数调用。"""
        if not instruction.args or instruction.args[0].kind != "symbol":
            self._unsupported(instruction, "dynamic_call")
        callee = str(instruction.args[0].value)
        if callee not in self.function_names:
            self._unsupported(instruction, f"unknown_function:{callee}")
        callee_return_type = self.function_return_types.get(callee)
        if callee_return_type == "void" and instruction.result is not None:
            raise self._node_error(instruction, f"native 机器码 MVP void 调用 {callee} 不应携带结果")
        if callee_return_type in SCALAR_VALUE_TYPES and instruction.result is None:
            raise self._node_error(instruction, f"native 机器码 MVP {callee_return_type} 调用 {callee} 必须携带结果")
        if callee_return_type in SCALAR_VALUE_TYPES and instruction.result is not None and instruction.result.type_hint != callee_return_type:
            raise self._node_error(
                instruction,
                f"native 机器码 MVP {callee_return_type} 调用 {callee} 结果类型必须是 {callee_return_type}，实际 {instruction.result.type_hint}",
            )
        if "callee_return_type" in instruction.attrs and instruction.attrs["callee_return_type"] != callee_return_type:
            raise self._node_error(
                instruction,
                f"native 机器码 MVP call callee_return_type 元数据不匹配: 标注 {instruction.attrs['callee_return_type']}, 实际 {callee_return_type}",
            )
        return_register = instruction.attrs.get("return_register")
        expected_return_register = "XMM0" if callee_return_type in FLOAT_VALUE_TYPES else self.abi.registers.return_register
        if return_register is not None and return_register != expected_return_register:
            raise self._node_error(
                instruction,
                f"native 机器码 MVP call return_register 元数据不匹配: 标注 {return_register}, 实际 {self.abi.registers.return_register}",
            )
        call_args = instruction.args[1:]
        if "argc" in instruction.attrs and int(instruction.attrs["argc"]) != len(call_args):
            raise self._node_error(instruction, f"native 机器码 MVP call argc 元数据不匹配: 标注 {instruction.attrs['argc']}, 实际 {len(call_args)}")
        arg_locations = instruction.attrs.get("arg_locations")
        if arg_locations is not None and len(arg_locations) != len(call_args):
            raise self._node_error(instruction, f"native 机器码 MVP call arg_locations 数量不匹配: 标注 {len(arg_locations)}, 实际 {len(call_args)}")
        if arg_locations is not None and self.abi is not None:
            for index, location in enumerate(arg_locations):
                expected_location = self.abi.argument_location(index, call_args[index].type_hint).__dict__
                if location != expected_location:
                    raise self._node_error(
                        instruction,
                        f"native 机器码 MVP call arg_locations[{index}] 不符合 ABI: 需要 {expected_location}, 实际 {location}",
                    )
        expected_argc = self.function_param_counts.get(callee)
        if expected_argc is not None and len(call_args) != expected_argc:
            raise self._node_error(instruction, f"native 机器码 MVP 调用 {callee} 参数数量不匹配: 需要 {expected_argc}, 实际 {len(call_args)}")
        argument_registers = list(self.abi.registers.argument_registers) if self.abi is not None else ["RCX", "RDX", "R8", "R9"]
        shadow_space_size = self.abi.shadow_space_size if self.abi is not None else 32
        stack_alignment = self.abi.stack_alignment if self.abi is not None else 16
        if shadow_space_size < 0:
            raise self._node_error(instruction, f"native 机器码 MVP call shadow space 不能为负数: {shadow_space_size}")
        if stack_alignment <= 0:
            raise self._node_error(instruction, f"native 机器码 MVP call 栈对齐必须为正数: {stack_alignment}")
        register_args = call_args[:len(argument_registers)]
        stack_args = call_args[len(argument_registers):]
        for index, operand in enumerate(register_args):
            register = argument_registers[index]
            self._load_operand_to_rax(operand, instruction)
            if operand.type_hint in FLOAT_VALUE_TYPES:
                self._emit(encode_sse_transfer(index), f"movq xmm{index}, rax", "call", instruction.source_pc, instruction.source_line)
            else:
                self._emit(encode_mov_reg_from_rax(register), f"mov {register.lower()}, rax", "call", instruction.source_pc, instruction.source_line)
        stack_arg_bytes = len(stack_args) * 8
        call_stack_size = shadow_space_size + stack_arg_bytes
        remainder = call_stack_size % stack_alignment
        if remainder:
            call_stack_size += stack_alignment - remainder
        if call_stack_size > _INT32_MAX:
            raise self._node_error(instruction, f"native 机器码 MVP call 栈窗口大小超出 signed int32 编码范围: {call_stack_size}")
        frame_offset = len(self.code)
        self._emit(encode_sub_rsp_imm32(call_stack_size), f"sub rsp, {call_stack_size}", "call", instruction.source_pc, instruction.source_line)
        for index, operand in enumerate(stack_args):
            self._load_operand_to_rax(operand, instruction)
            stack_offset = shadow_space_size + index * 8
            if stack_offset > _INT32_MAX:
                raise self._node_error(instruction, f"native 机器码 MVP call 第 {index + len(argument_registers)} 个参数栈偏移超出 signed int32 编码范围: {stack_offset}")
            self._emit(encode_mov_rsp_offset_from_rax(stack_offset), f"mov [rsp+{stack_offset}], rax", "call", instruction.source_pc, instruction.source_line)
        call_offset = len(self.code)
        self._emit_pending_call(callee, instruction.source_pc, instruction.source_line)
        call_end_offset = len(self.code)
        add_offset = len(self.code)
        add_code = encode_add_rsp_imm32(call_stack_size)
        self._emit(add_code, f"add rsp, {call_stack_size}", "call", instruction.source_pc, instruction.source_line)
        add_end_offset = len(self.code)
        self.call_frames.append(
            NativeCallFrameAllocation(
                offset=frame_offset,
                target=callee,
                arg_count=len(call_args),
                register_arg_count=len(register_args),
                stack_arg_count=len(stack_args),
                shadow_space_size=shadow_space_size,
                stack_arg_bytes=stack_arg_bytes,
                aligned_size=call_stack_size,
                stack_alignment=stack_alignment,
                source_pc=instruction.source_pc,
                source_line=instruction.source_line,
                call_offset=call_offset,
                call_end_offset=call_end_offset,
                add_offset=add_offset,
                add_end_offset=add_end_offset,
                arg_types=tuple(operand.type_hint for operand in call_args),
                param_types=tuple(self.function_param_types.get(callee, [])),
            )
        )
        test_offset = len(self.code)
        self._emit(encode_test_rdx_rdx(), "test rdx, rdx ; native _exit flag", "call", instruction.source_pc, instruction.source_line)
        exit_label = self._synthetic_label("propagate_exit")
        self.exit_propagation_labels.append((exit_label, instruction.source_pc, instruction.source_line))
        jump_offset = len(self.code)
        self._emit_pending_jump("jne", exit_label, instruction.source_pc, instruction.source_line, source_op="exit_probe")
        self.exit_probes.append(
            NativeExitProbe(
                call_offset=call_offset,
                test_offset=test_offset,
                jump_offset=jump_offset,
                target=callee,
                probe_label=exit_label,
                source_pc=instruction.source_pc,
                source_line=instruction.source_line,
            )
        )
        if instruction.result is not None:
            result = self._result_slot_offset(instruction)
            if callee_return_type in FLOAT_VALUE_TYPES:
                self._emit(encode_sse_transfer(0, to_rax=True, single=callee_return_type == "float32"), "movq rax, xmm0", "call", instruction.source_pc, instruction.source_line)
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", "call", instruction.source_pc, instruction.source_line)

    def _lower_exit(self, instruction: MachineInstruction) -> None:
        """生成受限 native _exit。"""
        self._load_operand_to_rax(instruction.args[0], instruction)
        self._emit(encode_mov_rdx_imm64(1), "mov rdx, 1 ; native _exit flag", "exit", instruction.source_pc, instruction.source_line)
        self._emit(encode_epilogue(), "mov rsp, rbp; pop rbp; ret", "exit", instruction.source_pc, instruction.source_line)

    def _lower_terminator(self, terminator: MachineTerminator) -> None:
        if terminator.op == "ret":
            if self.function.return_type == "void" and terminator.args:
                raise self._node_error(terminator, "native 机器码 MVP void 函数 ret 不应携带返回值")
            if self.function.return_type in SCALAR_VALUE_TYPES and len(terminator.args) != 1:
                raise self._node_error(terminator, f"native 机器码 MVP {self.function.return_type} 函数 ret 必须携带 1 个返回值")
            if terminator.args:
                if not _is_return_type_compatible(self.function.return_type, terminator.args[0].type_hint):
                    raise self._node_error(
                        terminator,
                        f"native 机器码 MVP {self.function.return_type} 函数 ret 返回值类型不能是 {terminator.args[0].type_hint}",
                    )
                self._load_operand_to_rax(terminator.args[0], terminator)
                if self.function.return_type in FLOAT_VALUE_TYPES:
                    self._emit(encode_sse_transfer(0), "movq xmm0, rax", "ret", terminator.source_pc, terminator.source_line)
            else:
                self._emit(encode_mov_rax_imm64(0), "mov rax, 0", "ret", terminator.source_pc, terminator.source_line)
            self._emit(encode_mov_rdx_imm64(0), "mov rdx, 0 ; native normal return", "ret", terminator.source_pc, terminator.source_line)
            self._emit(encode_epilogue(), "mov rsp, rbp; pop rbp; ret", "ret", terminator.source_pc, terminator.source_line)
            return
        if terminator.op == "jmp":
            if len(terminator.targets) != 1:
                raise self._node_error(terminator, "native 机器码 MVP 需要 jmp 恰好包含 1 个目标")
            self._emit_phi_copies(terminator.targets[0], terminator)
            self._emit_pending_jump("jmp", terminator.targets[0], terminator.source_pc, terminator.source_line)
            return
        if terminator.op == "br":
            if len(terminator.args) != 1 or len(terminator.targets) != 2:
                raise self._node_error(terminator, "native 机器码 MVP 需要 br 包含 1 个条件和 2 个目标")
            self._load_operand_to_rax(terminator.args[0], terminator)
            self._mask_float_sign(terminator.args[0].type_hint, terminator)
            self._emit(encode_mov_r10_imm64(0), "mov r10, 0", "br", terminator.source_pc, terminator.source_line)
            self._emit(encode_cmp_rax_r10(), "cmp rax, r10", "br", terminator.source_pc, terminator.source_line)
            current_block = self._current_block_name()
            true_has_phi = bool(self.phi_copies.get(terminator.targets[0], {}).get(current_block))
            false_has_phi = bool(self.phi_copies.get(terminator.targets[1], {}).get(current_block))
            if not true_has_phi and not false_has_phi:
                self._emit_pending_jump("jne", terminator.targets[0], terminator.source_pc, terminator.source_line)
                self._emit_pending_jump("jmp", terminator.targets[1], terminator.source_pc, terminator.source_line)
                return
            true_label = self._synthetic_label("phi_true")
            self._emit_pending_jump("jne", true_label, terminator.source_pc, terminator.source_line)
            self._emit_phi_copies(terminator.targets[1], terminator)
            self._emit_pending_jump("jmp", terminator.targets[1], terminator.source_pc, terminator.source_line)
            self.block_offsets[true_label] = len(self.code)
            self._emit(b"", f"{true_label}:", "label", None, None)
            self._emit_phi_copies(terminator.targets[0], terminator)
            self._emit_pending_jump("jmp", terminator.targets[0], terminator.source_pc, terminator.source_line)
            return
        self._unsupported(terminator, terminator.op)

    def _emit_exit_propagation_blocks(self) -> None:
        """生成 call 后 native _exit 标志向调用者传播的尾声块。"""
        for label, source_pc, source_line in self.exit_propagation_labels:
            self.block_offsets[label] = len(self.code)
            self._emit(b"", f"{label}:", "label", None, None)
            self._emit(encode_epilogue(), "mov rsp, rbp; pop rbp; ret", "exit_propagate", source_pc, source_line)

    def _load_operand_to_rax(self, operand: MachineOperand, node: MachineInstruction | MachineTerminator) -> None:
        """将操作数加载到 RAX。"""
        if operand.kind == "imm":
            value = int(operand.value)
            self._emit(encode_mov_rax_imm64(value), f"mov rax, {value}", getattr(node, "op", "operand"), node.source_pc, node.source_line)
            return
        offset = self._slot_offset(operand, node)
        if self._uses_global_frame(operand):
            self._emit(encode_mov_rax_from_r11_offset(offset), f"mov rax, [r11-{offset}]", getattr(node, "op", "operand"), node.source_pc, node.source_line)
            return
        self._emit(encode_mov_rax_from_rbp_offset(offset), f"mov rax, [rbp-{offset}]", getattr(node, "op", "operand"), node.source_pc, node.source_line)

    def _load_operand_to_r10(self, operand: MachineOperand, node: MachineInstruction | MachineTerminator) -> None:
        """将操作数加载到 R10。"""
        if operand.kind == "imm":
            value = int(operand.value)
            self._emit(encode_mov_r10_imm64(value), f"mov r10, {value}", getattr(node, "op", "operand"), node.source_pc, node.source_line)
            return
        offset = self._slot_offset(operand, node)
        if self._uses_global_frame(operand):
            self._emit(encode_mov_r10_from_r11_offset(offset), f"mov r10, [r11-{offset}]", getattr(node, "op", "operand"), node.source_pc, node.source_line)
            return
        self._emit(encode_mov_r10_from_rbp_offset(offset), f"mov r10, [rbp-{offset}]", getattr(node, "op", "operand"), node.source_pc, node.source_line)

    def _emit(
        self,
        code: bytes,
        asm: str,
        source_op: str,
        source_pc: int | None,
        source_line: int | None,
        source_attrs: dict[str, object] | None = None,
    ) -> None:
        """追加一条机器码清单项。"""
        self.instructions.append(
            NativeCodeInstruction(
                offset=len(self.code),
                code=code,
                asm=asm,
                source_op=source_op,
                source_pc=source_pc,
                source_line=source_line,
                source_attrs=source_attrs or {},
            )
        )
        self.code.extend(code)

    def _emit_pending_jump(self, kind: str, target: str, source_pc: int | None, source_line: int | None, source_op: str | None = None) -> None:
        """追加等待回填的相对跳转。"""
        code = _encode_rel32_jump(kind, 0)
        asm = f"{kind} {target}"
        instruction_index = len(self.instructions)
        offset = len(self.code)
        self._emit(code, asm, source_op or ("br" if kind == "jne" else "jmp"), source_pc, source_line)
        self.pending_jumps.append(_PendingJump(offset, instruction_index, target, kind))

    def _emit_pending_call(self, target: str, source_pc: int | None, source_line: int | None) -> None:
        """追加等待回填的函数调用。"""
        instruction_index = len(self.instructions)
        offset = len(self.code)
        self._emit(encode_call_rel32(0), f"call {target}", "call", source_pc, source_line)
        self.pending_calls.append(_PendingJump(offset, instruction_index, target, "call"))

    def _patch_pending_jumps(self) -> None:
        """回填所有 rel32 跳转位移。"""
        for jump in self.pending_jumps:
            target_offset = self.block_offsets.get(jump.target)
            if target_offset is None:
                raise self._function_error(f"native 机器码 MVP 找不到跳转目标 {jump.target}")
            size = len(_encode_rel32_jump(jump.kind, 0))
            displacement = target_offset - (jump.offset + size)
            old = self.instructions[jump.instruction_index]
            try:
                code = _encode_rel32_jump(jump.kind, displacement)
            except OverflowError as exc:
                raise _native_listing_error(
                    self.function.name,
                    old,
                    f"native 机器码 MVP {jump.kind} rel32 位移超出范围: {displacement}",
                ) from exc
            self.code[jump.offset:jump.offset + size] = code
            self.instructions[jump.instruction_index] = NativeCodeInstruction(
                offset=old.offset,
                code=code,
                asm=f"{old.asm} ; rel32={displacement:+d}",
                source_op=old.source_op,
                source_pc=old.source_pc,
                source_line=old.source_line,
                source_attrs=dict(old.source_attrs),
            )
            patch_offset = jump.offset + (len(code) - 4)
            self.relocations.append(
                NativeRelocation(
                    offset=jump.offset,
                    patch_offset=patch_offset,
                    kind=f"{jump.kind}_rel32",
                    target=jump.target,
                    displacement=displacement,
                    source_pc=old.source_pc,
                    source_line=old.source_line,
                )
            )

    def _emit_phi_copies(self, target: str, node: MachineInstruction | MachineTerminator) -> None:
        """在当前控制流边上执行 phi 输入复制。"""
        for result, source in self.phi_copies.get(target, {}).get(self._current_block_name(), []):
            self._load_operand_to_rax(source, node)
            offset = self._slot_offset(result, node)
            self._emit(encode_mov_rbp_offset_from_rax(offset), f"mov [rbp-{offset}], rax", "phi_copy", node.source_pc, node.source_line)

    def _current_block_name(self) -> str:
        """返回当前生成位置所在基本块名。"""
        for name, offset in reversed(list(self.block_offsets.items())):
            if offset <= len(self.code) and not name.startswith("__"):
                return name
        return ""

    def _synthetic_label(self, prefix: str) -> str:
        """创建函数内合成标签名。"""
        self.synthetic_label_id += 1
        return f"__{prefix}_{self.synthetic_label_id}"

    def _store_register_params(self) -> None:
        """将 ABI 参数保存到 local 栈槽。"""
        for param in self.function.params:
            key = ("local", param.index)
            offset = self.slot_offsets.get(key)
            if offset is None:
                raise self._function_error(f"native 机器码 MVP 找不到参数 local[{param.index}] 栈槽")
            if param.kind == "register":
                register = param.name.upper()
                if register.startswith("XMM"):
                    self._emit(encode_sse_transfer(param.index, to_rax=True, single=_function_param_types(self.function)[param.index] == "float32"), f"movq rax, xmm{param.index}", "param", None, None)
                    self._emit(encode_mov_rbp_offset_from_rax(offset), f"mov [rbp-{offset}], rax", "param", None, None)
                    continue
                self._emit(
                    encode_mov_rbp_offset_from_reg(offset, register),
                    f"mov [rbp-{offset}], {register.lower()}",
                    "param",
                    None,
                    None,
                )
                continue
            stack_offset = 48 + (param.index - 4) * 8
            self._emit(encode_mov_rax_from_rbp_positive_offset(stack_offset), f"mov rax, [rbp+{stack_offset}]", "param", None, None)
            self._emit(encode_mov_rbp_offset_from_rax(offset), f"mov [rbp-{offset}], rax", "param", None, None)

    def _build_slot_offsets(self) -> dict[tuple[str, int | str], int]:
        """生成栈槽到 rbp 负偏移的映射。"""
        offsets: dict[tuple[str, int | str], int] = {}
        next_offset = 8
        global_next_offset = 8
        for slot in self.function.frame.global_slots:
            offsets[(slot.kind, slot.index)] = global_next_offset
            global_next_offset += slot.size
            if self.global_frame_owner:
                next_offset = global_next_offset
        for slot in self.function.frame.local_slots:
            offsets[(slot.kind, slot.index)] = next_offset
            next_offset += slot.size
        for slot in self.function.frame.temp_slots:
            offsets[(slot.kind, slot.index)] = next_offset
            next_offset += slot.size
        for block in self.function.blocks:
            for instruction in block.instructions:
                for operand in [instruction.result, *instruction.args]:
                    next_offset = self._collect_operand_slot(offsets, next_offset, operand)
            if block.terminator:
                for operand in block.terminator.args:
                    next_offset = self._collect_operand_slot(offsets, next_offset, operand)
        return offsets

    def _build_frame_size(self) -> int:
        """计算当前函数实际需要分配的栈帧大小。"""
        owned_offsets = [
            offset
            for (kind, _), offset in self.slot_offsets.items()
            if self.global_frame_owner or kind != "global"
        ]
        max_offset = max(owned_offsets, default=0)
        return ((max_offset + 15) // 16) * 16

    def _stack_slot_allocations(self) -> list[NativeStackSlotAllocation]:
        """生成可 dump 的栈槽分配结果。"""
        items = []
        for (kind, index), offset in sorted(self.slot_offsets.items(), key=lambda item: item[1]):
            name = f"%v{index}" if kind == "temp" else f"{kind}[{index}]"
            items.append(NativeStackSlotAllocation(name=name, offset=offset, size=8))
        return items

    def _build_phi_copies(self) -> dict[str, dict[str, list[tuple[MachineOperand, MachineOperand]]]]:
        """收集每条前驱边需要执行的 phi 复制。"""
        copies: dict[str, dict[str, list[tuple[MachineOperand, MachineOperand]]]] = {}
        for block in self.function.blocks:
            for instruction in block.instructions:
                if instruction.op != "phi":
                    continue
                if instruction.result is None:
                    raise self._node_error(instruction, "native 机器码 MVP phi 缺少结果操作数")
                incoming_blocks = instruction.attrs.get("incoming_blocks", [])
                if len(incoming_blocks) != len(instruction.args):
                    raise self._node_error(instruction, "native 机器码 MVP phi incoming_blocks 与参数数量不一致")
                for predecessor, source in zip(incoming_blocks, instruction.args):
                    copies.setdefault(block.name, {}).setdefault(str(predecessor), []).append((instruction.result, source))
        return copies

    def _collect_operand_slot(self, offsets: dict[tuple[str, int | str], int], next_offset: int, operand: MachineOperand | None) -> int:
        """补齐 Machine IR 实际引用的栈槽。"""
        if operand is None:
            return next_offset
        if operand.kind == "slot":
            key = (operand.value.kind, operand.value.index)
            size = operand.value.size
        elif operand.kind == "vreg":
            key = ("temp", int(_vreg_index_text(operand.value.name)))
            size = 8
        else:
            return next_offset
        if key not in offsets:
            offsets[key] = next_offset
            next_offset += size
        return next_offset

    def _slot_offset(self, operand: MachineOperand, node: MachineInstruction | MachineTerminator) -> int:
        """取得操作数对应的 rbp 负偏移。"""
        if operand.kind == "slot":
            key = (operand.value.kind, operand.value.index)
        elif operand.kind == "vreg":
            key = ("temp", int(_vreg_index_text(operand.value.name)))
        else:
            self._unsupported(node, f"operand:{operand.kind}")
        offset = self.slot_offsets.get(key)
        if offset is None:
            raise self._node_error(node, f"native 机器码 MVP 找不到栈槽 {key[0]}[{key[1]}]")
        return offset

    def _uses_global_frame(self, operand: MachineOperand) -> bool:
        """判断操作数是否需要通过 R11 全局帧访问。"""
        return operand.kind == "slot" and operand.value.kind == "global" and self.function.name != "<module>"

    def _result_slot_offset(self, instruction: MachineInstruction) -> int:
        """取得指令结果对应的 rbp 负偏移。"""
        if instruction.result is None:
            raise self._node_error(instruction, "native 机器码 MVP 指令缺少结果操作数")
        return self._slot_offset(instruction.result, instruction)

    def _unsupported(self, node: MachineInstruction | MachineTerminator, feature: str) -> None:
        """抛出不支持特性的机器码生成错误。"""
        raise self._node_error(node, f"native 机器码 MVP 暂不支持特性 '{feature}'")

    def _node_error(self, node: MachineInstruction | MachineTerminator, message: str) -> NativeCodegenError:
        """构造带源码位置的机器码生成错误。"""
        parts = [f"函数 {self.function.name}", f"Machine IR 指令 {getattr(node, 'op', '<unknown>')}"]
        if node.source_line is not None:
            parts.append(f"行 {node.source_line}")
        if node.source_pc is not None:
            parts.append(f"PC {node.source_pc}")
        return NativeCodegenError(f"{', '.join(parts)}: {message}")

    def _function_error(self, message: str) -> NativeCodegenError:
        """构造函数级机器码生成错误。"""
        return NativeCodegenError(f"函数 {self.function.name}: {message}")

    def _prologue_asm(self) -> str:
        """生成函数序言伪汇编。"""
        if self.frame_size:
            return f"push rbp; mov rbp, rsp; sub rsp, {self.frame_size}"
        return "push rbp; mov rbp, rsp"


def _patch_pending_calls(
    code: bytearray,
    pending_calls: list[_PendingJump],
    function_offsets: dict[str, int],
    functions: dict[str, NativeCodeFunction],
) -> None:
    """回填所有函数调用 rel32 位移。"""
    for call in pending_calls:
        target_offset = function_offsets.get(call.target)
        if target_offset is None:
            raise NativeCodegenError(f"native 机器码 MVP 找不到调用目标 {call.target}")
        displacement = target_offset - (call.offset + 5)
        owner_function = None
        for function in functions.values():
            if function.offset <= call.offset < function.offset + len(function.code):
                owner_function = function
                break
        old = owner_function.instructions[call.instruction_index] if owner_function is not None else None
        try:
            patched = encode_call_rel32(displacement)
        except OverflowError as exc:
            if owner_function is None or old is None:
                raise NativeCodegenError(f"native 机器码 MVP call rel32 位移超出范围: {displacement}") from exc
            raise _native_listing_error(
                owner_function.name,
                old,
                f"native 机器码 MVP call rel32 位移超出范围: {displacement}",
            ) from exc
        code[call.offset:call.offset + 5] = patched
        for function in functions.values():
            if not (function.offset <= call.offset < function.offset + len(function.code)):
                continue
            old = function.instructions[call.instruction_index]
            function.instructions[call.instruction_index] = NativeCodeInstruction(
                offset=old.offset,
                code=patched,
                asm=f"{old.asm} ; rel32={displacement:+d}",
                source_op=old.source_op,
                source_pc=old.source_pc,
                source_line=old.source_line,
                source_attrs=dict(old.source_attrs),
            )
            function.relocations.append(
                NativeRelocation(
                    offset=call.offset,
                    patch_offset=call.offset + 1,
                    kind="call_rel32",
                    target=call.target,
                    displacement=displacement,
                    source_pc=old.source_pc,
                    source_line=old.source_line,
                )
            )
            break


def _native_listing_error(function_name: str, instruction: NativeCodeInstruction, message: str) -> NativeCodegenError:
    """构造已生成清单项对应的机器码生成错误。"""
    parts = [f"函数 {function_name}", f"Machine IR 指令 {instruction.source_op}"]
    if instruction.source_line is not None:
        parts.append(f"行 {instruction.source_line}")
    if instruction.source_pc is not None:
        parts.append(f"PC {instruction.source_pc}")
    return NativeCodegenError(f"{', '.join(parts)}: {message}")

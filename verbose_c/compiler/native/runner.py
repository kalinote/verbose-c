import ctypes
import platform
import sys

from verbose_c.compiler.native.codegen import (
    NativeCodeFunction,
    NativeCodeProgram,
    NativeRegisterAllocation,
    _is_argument_type_compatible,
    _native_program_symbols,
    validate_native_code_map_bytes,
    validate_native_text_section_map_bytes,
)
from verbose_c.compiler.native.errors import NativeCodegenError
from verbose_c.compiler.native.target import NativeTarget


MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40
REL32_JUMP_OPCODES = {
    "je_rel32": b"\x0F\x84",
    "jmp_rel32": b"\xE9",
    "jne_rel32": b"\x0F\x85",
    "jns_rel32": b"\x0F\x89",
}
REL32_JUMP_ASM_PREFIXES = {
    "je_rel32": "je ",
    "jmp_rel32": "jmp ",
    "jne_rel32": "jne ",
    "jns_rel32": "jns ",
}


def can_run_native_memory() -> bool:
    """判断当前进程是否支持 Windows x64 内存执行。"""
    return sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}


def run_native_function_in_memory(function: NativeCodeFunction) -> int:
    """在 Windows x64 可执行内存中运行无参数 native 函数。"""
    if not isinstance(function, NativeCodeFunction):
        raise NativeCodegenError("native 单函数内存执行需要 NativeCodeFunction")
    if not isinstance(function.name, str) or not function.name:
        raise NativeCodegenError("native 单函数内存执行函数名必须是非空字符串")
    if not isinstance(function.return_type, str) or function.return_type not in {"int64", "bool64"}:
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} return_type 暂不支持: {function.return_type!r}")
    if not isinstance(function.param_types, tuple) or any(not isinstance(item, str) for item in function.param_types):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} param_types 必须是字符串元组")
    if function.param_types:
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 必须是无参数函数")
    if not isinstance(function.code, bytes):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} code 必须是 bytes")
    if not isinstance(function.offset, int) or isinstance(function.offset, bool):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} offset 必须是整数")
    if function.offset < 0:
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} offset 不能为负数: {function.offset}")
    if not isinstance(function.frame_size, int) or isinstance(function.frame_size, bool):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} frame_size 必须是整数")
    if function.frame_size < 0 or function.frame_size % 16 != 0:
        raise NativeCodegenError(
            f"native 单函数内存执行函数 {function.name} frame_size 必须是非负 16 字节对齐整数，实际 {function.frame_size}"
        )
    if not isinstance(function.instructions, list):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} instructions 必须是列表")
    instruction_ranges = []
    instructions_by_offset = {}
    function_end = function.offset + len(function.code)
    for instruction in function.instructions:
        _validate_source_location(f"native 单函数内存执行函数 {function.name} 机器码清单", instruction)
        if not isinstance(instruction.offset, int) or isinstance(instruction.offset, bool):
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 机器码清单 offset 必须是整数")
        if not isinstance(instruction.code, bytes):
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 机器码清单 code 必须是 bytes")
        if not isinstance(instruction.asm, str):
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 机器码清单 asm 必须是字符串")
        if not isinstance(instruction.source_op, str) or not instruction.source_op:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 机器码清单 source_op 必须是非空字符串")
        _validate_instruction_source_attrs(
            f"native 单函数内存执行函数 {function.name} 机器码清单",
            instruction.source_attrs,
        )
        if instruction.offset < function.offset or instruction.offset > function_end:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 机器码清单偏移越界: {instruction.offset}")
        if not instruction.code:
            continue
        instructions_by_offset.setdefault(instruction.offset, instruction)
        instruction_end = instruction.offset + len(instruction.code)
        if instruction_end > function_end:
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} 机器码清单范围越界: offset {instruction.offset}, "
                f"长度 {len(instruction.code)}"
            )
        relative_start = instruction.offset - function.offset
        relative_end = instruction_end - function.offset
        if function.code[relative_start:relative_end] != instruction.code:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 机器码清单字节与 function.code 不一致")
        instruction_ranges.append((instruction.offset, instruction_end))
    covered_until = function.offset
    for start, end in sorted(instruction_ranges):
        if start < covered_until:
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} 机器码清单范围重叠: offset {start}, 已覆盖到 {covered_until}"
            )
        if start > covered_until:
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} 机器码清单范围前存在空洞: offset {start}, 已覆盖到 {covered_until}"
            )
        covered_until = end
    if instruction_ranges and covered_until != function_end:
        raise NativeCodegenError(
            f"native 单函数内存执行函数 {function.name} 机器码清单范围未覆盖完整函数: 已覆盖到 {covered_until}, "
            f"函数结束 {function_end}"
        )
    allocation = function.register_allocation
    if not isinstance(allocation, NativeRegisterAllocation):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} register_allocation 必须是 NativeRegisterAllocation")
    if allocation.strategy != "保守栈槽分配":
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} register_allocation.strategy 不一致: {allocation.strategy!r}")
    if allocation.temporary_registers != ("RAX", "R10"):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} register_allocation.temporary_registers 必须是 ('RAX', 'R10')")
    if allocation.argument_registers:
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} 必须是无参数函数")
    if allocation.return_register != "RAX":
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} register_allocation.return_register 必须是 RAX")
    if allocation.frame_pointer != "RBP" or allocation.stack_pointer != "RSP":
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} register_allocation 帧/栈指针不一致")
    if allocation.virtual_register_storage != "全部写入栈槽" or allocation.local_storage != "全部写入栈槽":
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} register_allocation 栈槽保存策略不一致")
    if not isinstance(function.relocations, list):
        raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} relocations 必须是列表")
    seen_relocation_offsets = set()
    for relocation in function.relocations:
        _validate_source_location(f"native 单函数内存执行函数 {function.name} rel32 修补记录", relocation)
        if relocation.kind not in {*REL32_JUMP_OPCODES, "call_rel32"}:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 修补类型暂不支持: {relocation.kind}")
        for field in ("offset", "patch_offset", "displacement", "size"):
            value = getattr(relocation, field)
            if not isinstance(value, int) or isinstance(value, bool):
                raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 {field} 必须是整数")
        if not isinstance(relocation.target, str) or not relocation.target:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 target 必须是非空字符串")
        if relocation.size != 4:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 修补字段大小必须为 4，实际 {relocation.size}")
        opcode_size = len(REL32_JUMP_OPCODES[relocation.kind]) if relocation.kind in REL32_JUMP_OPCODES else 1
        expected_patch_offset = relocation.offset + opcode_size
        if relocation.offset in seen_relocation_offsets:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 修补记录重复: {relocation.offset}")
        seen_relocation_offsets.add(relocation.offset)
        if relocation.patch_offset != expected_patch_offset:
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} rel32 修补字段偏移不一致: "
                f"记录 {relocation.patch_offset}, 期望 {expected_patch_offset}"
            )
        instruction_size = opcode_size + relocation.size
        if relocation.offset < function.offset or relocation.offset + instruction_size > function_end:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 范围越界: {relocation.offset}")
        relative_offset = relocation.offset - function.offset
        opcode = function.code[relative_offset:relative_offset + opcode_size]
        if relocation.kind == "call_rel32" and opcode != b"\xE8":
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} call_rel32 opcode 不一致")
        if relocation.kind in REL32_JUMP_OPCODES and opcode != REL32_JUMP_OPCODES[relocation.kind]:
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} {relocation.kind} opcode 不一致")
        relocation_instruction = instructions_by_offset.get(relocation.offset)
        actual_displacement = int.from_bytes(
            function.code[relative_offset + opcode_size:relative_offset + instruction_size],
            "little",
            signed=True,
        )
        if actual_displacement != relocation.displacement:
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} {relocation.kind} 位移与机器码不一致: "
                f"记录 {relocation.displacement}, 机器码 {actual_displacement}"
            )
        target_offset = relocation.offset + instruction_size + relocation.displacement
        if relocation.kind == "call_rel32" and (target_offset < function.offset or target_offset >= function_end):
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} call_rel32 目标不在函数切片内: {relocation.target}"
            )
        if relocation.kind in REL32_JUMP_OPCODES:
            label_offset = _function_label_offset(function, relocation.target)
            if label_offset is None:
                raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 修补目标未知: {relocation.target}")
            if target_offset != label_offset:
                raise NativeCodegenError(
                    f"native 单函数内存执行函数 {function.name} rel32 目标与标签偏移不一致: "
                    f"记录 {relocation.target}@{label_offset}, 位移目标 {target_offset}"
                )
        if relocation_instruction is None:
            raise NativeCodegenError(
                f"native 单函数内存执行函数 {function.name} rel32 修补指令清单缺失: {relocation.offset}"
            )
        if (
            relocation_instruction.source_pc != relocation.source_pc
            or relocation_instruction.source_line != relocation.source_line
        ):
            raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 来源位置与清单不一致")
        if relocation_instruction is not None:
            expected_prefix = {**REL32_JUMP_ASM_PREFIXES, "call_rel32": "call "}[relocation.kind]
            if not relocation_instruction.asm.startswith(expected_prefix):
                raise NativeCodegenError(f"native 单函数内存执行函数 {function.name} rel32 修补指令清单类型不一致")
            instruction_target = relocation_instruction.asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if instruction_target != relocation.target:
                raise NativeCodegenError(
                    f"native 单函数内存执行函数 {function.name} rel32 目标与清单不一致: "
                    f"记录 {relocation.target}, 指令 {instruction_target}"
                )
    return _run_code_in_memory(function.code, 0)


def run_native_program_in_memory(program: NativeCodeProgram) -> int:
    """在 Windows x64 可执行内存中运行 native 程序入口。"""
    if program.target != NativeTarget.WINDOWS_X64:
        raise NativeCodegenError(f"native 内存执行暂不支持目标平台 {program.target}")
    if not isinstance(program.code, bytes):
        raise NativeCodegenError("native 内存执行 program.code 必须是 bytes")
    if not isinstance(program.entry_offset, int) or isinstance(program.entry_offset, bool):
        raise NativeCodegenError("native 内存执行 entry_offset 必须是整数")
    if not isinstance(program.entry, NativeCodeFunction):
        raise NativeCodegenError("native 内存执行 entry 必须是 NativeCodeFunction")
    if not isinstance(program.functions, dict):
        raise NativeCodegenError("native 内存执行 functions 必须是函数表 dict")
    if not isinstance(program.entry.name, str) or not program.entry.name:
        raise NativeCodegenError("native 内存执行 entry 函数名必须是非空字符串")
    if program.entry.name not in program.functions:
        raise NativeCodegenError(f"native 内存执行入口函数不在函数表中: {program.entry.name}")
    if program.functions[program.entry.name] is not program.entry:
        raise NativeCodegenError(f"native 内存执行入口函数表项与 entry 不一致: {program.entry.name}")
    for table_name, function in program.functions.items():
        if not isinstance(table_name, str) or not table_name:
            raise NativeCodegenError("native 内存执行函数表 key 必须是非空字符串")
        if not isinstance(function, NativeCodeFunction):
            raise NativeCodegenError(f"native 内存执行函数表项 {table_name} 必须是 NativeCodeFunction")
        if not isinstance(function.name, str) or not function.name:
            raise NativeCodegenError(f"native 内存执行函数表项 {table_name} 的函数名必须是非空字符串")
        if function.name != table_name:
            raise NativeCodegenError(
                f"native 内存执行函数表 key 与函数名不一致: key {table_name}, 函数 {function.name}"
            )
        if not isinstance(function.return_type, str) or function.return_type not in {"int64", "bool64", "void"}:
            raise NativeCodegenError(f"native 内存执行函数 {table_name} return_type 暂不支持: {function.return_type!r}")
        if not isinstance(function.param_types, tuple) or any(not isinstance(item, str) for item in function.param_types):
            raise NativeCodegenError(f"native 内存执行函数 {table_name} param_types 必须是字符串元组")
        for index, param_type in enumerate(function.param_types):
            if param_type not in {"int64", "bool64"}:
                raise NativeCodegenError(f"native 内存执行函数 {table_name} 第 {index} 个参数暂不支持类型: {param_type!r}")
    if program.entry_offset < 0:
        raise NativeCodegenError(f"native 内存执行入口偏移不能为负数: {program.entry_offset}")
    if program.entry_offset >= len(program.code):
        raise NativeCodegenError(f"native 内存执行入口偏移越界: {program.entry_offset}, 机器码长度 {len(program.code)}")
    if program.entry_offset != program.entry.offset:
        raise NativeCodegenError(
            f"native 内存执行入口偏移与函数偏移不一致: entry_offset {program.entry_offset}, "
            f"函数 {program.entry.name} offset {program.entry.offset}"
        )
    ranges = []
    for name, function in program.functions.items():
        if not isinstance(function.offset, int) or isinstance(function.offset, bool):
            raise NativeCodegenError(f"native 内存执行函数 {name} offset 必须是整数")
        if not isinstance(function.code, bytes):
            raise NativeCodegenError(f"native 内存执行函数 {name} code 必须是 bytes")
        if function.offset < 0:
            raise NativeCodegenError(f"native 内存执行函数 {name} offset 不能为负数: {function.offset}")
        end = function.offset + len(function.code)
        if end > len(program.code):
            raise NativeCodegenError(
                f"native 内存执行函数 {name} 机器码范围越界: offset {function.offset}, "
                f"长度 {len(function.code)}, 程序长度 {len(program.code)}"
            )
        if program.code[function.offset:end] != function.code:
            raise NativeCodegenError(f"native 内存执行函数 {name} 机器码与 program.code 切片不一致")
        ranges.append((function.offset, end, name))
    covered_until = 0
    for offset, end, name in sorted(ranges):
        if offset < covered_until:
            raise NativeCodegenError(f"native 内存执行函数 {name} 范围与前序函数重叠: offset {offset}, 已覆盖到 {covered_until}")
        if offset > covered_until:
            raise NativeCodegenError(f"native 内存执行函数 {name} 范围前存在空洞: offset {offset}, 已覆盖到 {covered_until}")
        covered_until = end
    if covered_until != len(program.code):
        raise NativeCodegenError(f"native 内存执行函数范围未覆盖完整机器码: 已覆盖到 {covered_until}, 机器码长度 {len(program.code)}")
    _validate_instruction_listing(program)
    _validate_stack_frame_layout(program)
    _validate_symbols(program)
    _validate_call_frames(program)
    _validate_register_allocation(program)
    _validate_relocations(program)
    _validate_exit_propagation(program)
    return _run_code_in_memory(program.code, program.entry_offset)


def run_native_bytes_in_memory(code: bytes, metadata: dict[str, object]) -> int:
    """按 map 校验 raw native bytes 后在可执行内存中运行入口。"""
    validate_native_code_map_bytes(code, metadata)
    entry_offset = metadata["entry_offset"]
    if not isinstance(entry_offset, int) or isinstance(entry_offset, bool):
        raise NativeCodegenError(f"native raw bin 内存执行 entry_offset 必须是整数，实际 {type(entry_offset).__name__}")
    return _run_code_in_memory(code, entry_offset)


def run_native_text_section_bytes_in_memory(text_raw: bytes, metadata: dict[str, object]) -> int:
    """按 map 校验补零后的 PE .text raw section 后运行入口。"""
    validate_native_text_section_map_bytes(text_raw, metadata)
    code_size = metadata["code_size"]
    entry_offset = metadata["entry_offset"]
    if not isinstance(code_size, int) or isinstance(code_size, bool):
        raise NativeCodegenError(f"native .text 内存执行 code_size 必须是整数，实际 {type(code_size).__name__}")
    if code_size < 0 or code_size > len(text_raw):
        raise NativeCodegenError(f"native .text 内存执行 code_size 越界: {code_size}, .text 长度 {len(text_raw)}")
    if not isinstance(entry_offset, int) or isinstance(entry_offset, bool):
        raise NativeCodegenError(f"native .text 内存执行 entry_offset 必须是整数，实际 {type(entry_offset).__name__}")
    return _run_code_in_memory(text_raw[:code_size], entry_offset)


def _validate_symbols(program: NativeCodeProgram) -> None:
    """校验 native program 符号表与函数表一致。"""
    seen = set()
    for symbol in _native_program_symbols(program):
        if not isinstance(symbol.name, str) or not symbol.name:
            raise NativeCodegenError("native 内存执行符号 name 必须是非空字符串")
        if not isinstance(symbol.offset, int) or isinstance(symbol.offset, bool):
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} offset 必须是整数")
        if not isinstance(symbol.size, int) or isinstance(symbol.size, bool):
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} size 必须是整数")
        if symbol.offset < 0:
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} offset 不能为负数: {symbol.offset}")
        if symbol.size < 0:
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} size 不能为负数: {symbol.size}")
        if not isinstance(symbol.is_entry, bool):
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} is_entry 必须是布尔值")
        if symbol.name in seen:
            raise NativeCodegenError(f"native 内存执行符号表重复定义: {symbol.name}")
        seen.add(symbol.name)
        function = program.functions.get(symbol.name)
        if function is None:
            raise NativeCodegenError(f"native 内存执行符号表引用未知函数: {symbol.name}")
        if symbol.kind != "function":
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} 类型暂不支持: {symbol.kind}")
        if symbol.offset != function.offset:
            raise NativeCodegenError(
                f"native 内存执行符号 {symbol.name} 偏移与函数不一致: 符号 {symbol.offset}, 函数 {function.offset}"
            )
        if symbol.size != len(function.code):
            raise NativeCodegenError(
                f"native 内存执行符号 {symbol.name} 大小与函数不一致: 符号 {symbol.size}, 函数 {len(function.code)}"
            )
        if not isinstance(symbol.return_type, str) or symbol.return_type not in {"int64", "bool64", "void"}:
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} return_type 暂不支持: {symbol.return_type!r}")
        if not isinstance(symbol.param_types, tuple) or any(not isinstance(item, str) for item in symbol.param_types):
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} param_types 必须是字符串元组")
        for index, param_type in enumerate(symbol.param_types):
            if param_type not in {"int64", "bool64"}:
                raise NativeCodegenError(f"native 内存执行符号 {symbol.name} 第 {index} 个参数暂不支持类型: {param_type!r}")
        if symbol.return_type != function.return_type:
            raise NativeCodegenError(
                f"native 内存执行符号 {symbol.name} return_type 与函数签名不一致: "
                f"符号 {symbol.return_type!r}, 函数 {function.return_type!r}"
            )
        if symbol.param_types != function.param_types:
            raise NativeCodegenError(
                f"native 内存执行符号 {symbol.name} param_types 与函数签名不一致: "
                f"符号 {list(symbol.param_types)}, 函数 {list(function.param_types)}"
            )
        if symbol.is_entry != (symbol.name == program.entry.name):
            raise NativeCodegenError(f"native 内存执行符号 {symbol.name} 入口标记与 entry 不一致")
    missing = sorted(set(program.functions) - seen)
    if missing:
        raise NativeCodegenError(f"native 内存执行符号表缺少函数: {', '.join(missing)}")


def _validate_instruction_listing(program: NativeCodeProgram) -> None:
    """校验 native 机器码清单与程序机器码一致。"""
    for name, function in program.functions.items():
        function_end = function.offset + len(function.code)
        instruction_ranges = []
        for instruction in function.instructions:
            _validate_source_location(f"native 内存执行函数 {name} 机器码清单", instruction)
            if not isinstance(instruction.offset, int) or isinstance(instruction.offset, bool):
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单 offset 必须是整数")
            if not isinstance(instruction.code, bytes):
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单 code 必须是 bytes")
            if not isinstance(instruction.asm, str):
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单 asm 必须是字符串")
            if not isinstance(instruction.source_op, str) or not instruction.source_op:
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单 source_op 必须是非空字符串")
            _validate_instruction_source_attrs(
                f"native 内存执行函数 {name} 机器码清单",
                instruction.source_attrs,
            )
            if instruction.offset < function.offset or instruction.offset > function_end:
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单偏移越界: {instruction.offset}")
            if not instruction.code:
                continue
            instruction_end = instruction.offset + len(instruction.code)
            if instruction_end > function_end:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 机器码清单范围越界: offset {instruction.offset}, 长度 {len(instruction.code)}"
                )
            if program.code[instruction.offset:instruction_end] != instruction.code:
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单字节与 program.code 不一致")
            instruction_ranges.append((instruction.offset, instruction_end))
        covered_until = function.offset
        for start, end in sorted(instruction_ranges):
            if start < covered_until:
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单范围重叠: offset {start}, 已覆盖到 {covered_until}")
            if start > covered_until:
                raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单范围前存在空洞: offset {start}, 已覆盖到 {covered_until}")
            covered_until = end
        if instruction_ranges and covered_until != function_end:
            raise NativeCodegenError(f"native 内存执行函数 {name} 机器码清单范围未覆盖完整函数: 已覆盖到 {covered_until}, 函数结束 {function_end}")


def _validate_instruction_source_attrs(prefix: str, source_attrs: object) -> None:
    """校验 native 指令来源元数据形状。"""
    if not isinstance(source_attrs, dict):
        raise NativeCodegenError(f"{prefix} source_attrs 必须是对象")
    for attr_key, attr_value in source_attrs.items():
        if not isinstance(attr_key, str) or not attr_key:
            raise NativeCodegenError(f"{prefix} source_attrs key 必须是非空字符串")
        if not isinstance(attr_value, (str, int, bool)) and attr_value is not None:
            raise NativeCodegenError(f"{prefix} source_attrs.{attr_key} 必须是字符串、整数、布尔值或 null")


def _validate_stack_frame_layout(program: NativeCodeProgram) -> None:
    """校验 native 函数栈帧与栈槽布局。"""
    global_frame_owners = set()
    for name, function in program.functions.items():
        for instruction in function.instructions:
            if instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame":
                if instruction.code != b"\x49\x89\xEB":
                    raise NativeCodegenError(f"native 内存执行函数 {name} global-frame 初始化指令 bytes 不一致")
                global_frame_owners.add(name)
    if len(global_frame_owners) > 1:
        raise NativeCodegenError(f"native 内存执行 global-frame owner 不能超过 1 个: {', '.join(sorted(global_frame_owners))}")
    global_owner_slots = {}
    for name, function in program.functions.items():
        if not isinstance(function.frame_size, int) or isinstance(function.frame_size, bool):
            raise NativeCodegenError(f"native 内存执行函数 {name} frame_size 必须是整数")
        if function.frame_size < 0 or function.frame_size % 16 != 0:
            raise NativeCodegenError(
                f"native 内存执行函数 {name} frame_size 必须是非负 16 字节对齐整数，实际 {function.frame_size}"
            )
        seen_slot_names = set()
        global_slot_offsets = set()
        frame_slot_offsets = set()
        max_frame_slot_offset = 0
        owns_global_frame = name in global_frame_owners
        for slot in function.stack_slots:
            if not isinstance(slot.name, str) or not slot.name:
                raise NativeCodegenError(f"native 内存执行函数 {name} 栈槽 name 必须是非空字符串")
            if slot.name in seen_slot_names:
                raise NativeCodegenError(f"native 内存执行函数 {name} 栈槽重复: {slot.name}")
            seen_slot_names.add(slot.name)
            for field in ("offset", "size"):
                value = getattr(slot, field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 内存执行函数 {name} 栈槽 {slot.name} {field} 必须是整数")
            if slot.offset <= 0:
                raise NativeCodegenError(f"native 内存执行函数 {name} 栈槽 {slot.name} offset 必须为正数")
            if slot.size != 8:
                raise NativeCodegenError(f"native 内存执行函数 {name} 栈槽 {slot.name} size 必须为 8，实际 {slot.size}")
            if slot.name.startswith("global[") and not owns_global_frame:
                if slot.offset in global_slot_offsets:
                    raise NativeCodegenError(f"native 内存执行函数 {name} 全局栈槽偏移重复: {slot.offset}")
                global_slot_offsets.add(slot.offset)
            else:
                if slot.offset in frame_slot_offsets:
                    raise NativeCodegenError(f"native 内存执行函数 {name} 栈帧槽偏移重复: {slot.offset}")
                frame_slot_offsets.add(slot.offset)
                max_frame_slot_offset = max(max_frame_slot_offset, slot.offset)
                if slot.name.startswith("global["):
                    global_owner_slots[slot.name] = (slot.offset, slot.size)
        if max_frame_slot_offset > function.frame_size:
            raise NativeCodegenError(
                f"native 内存执行函数 {name} 栈槽超出栈帧: 最大偏移 {max_frame_slot_offset}, frame_size {function.frame_size}"
            )
    if global_frame_owners and not global_owner_slots:
        owner = next(iter(global_frame_owners))
        raise NativeCodegenError(f"native 内存执行函数 {owner} 初始化 R11 global frame 但没有声明全局栈槽")
    for name, function in program.functions.items():
        if name in global_frame_owners:
            continue
        for slot in function.stack_slots:
            if not slot.name.startswith("global["):
                continue
            owner_slot = global_owner_slots.get(slot.name)
            if owner_slot is None:
                raise NativeCodegenError(f"native 内存执行函数 {name} 全局栈槽缺少 global-frame owner 声明: {slot.name}")
            if owner_slot != (slot.offset, slot.size):
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 全局栈槽 {slot.name} 与 global-frame owner 布局不一致"
                )


def _validate_register_allocation(program: NativeCodeProgram) -> None:
    """校验 native 函数寄存器分配摘要与 ABI/栈槽一致。"""
    registers = getattr(getattr(program, "abi", None), "registers", None)
    argument_registers = getattr(registers, "argument_registers", None)
    if not isinstance(argument_registers, tuple) or any(not isinstance(register, str) for register in argument_registers):
        raise NativeCodegenError("native 内存执行 ABI 参数寄存器必须是字符串元组")
    return_register = getattr(registers, "return_register", None)
    frame_pointer = getattr(registers, "frame_pointer", None)
    stack_pointer = getattr(registers, "stack_pointer", None)
    global_frame_owners = {
        name
        for name, function in program.functions.items()
        if any(
            instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
            for instruction in function.instructions
        )
    }
    for name, function in program.functions.items():
        allocation = function.register_allocation
        if not isinstance(allocation, NativeRegisterAllocation):
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation 必须是 NativeRegisterAllocation")
        if allocation.strategy != "保守栈槽分配":
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.strategy 不一致: {allocation.strategy!r}")
        if allocation.temporary_registers != ("RAX", "R10"):
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.temporary_registers 必须是 ('RAX', 'R10')")
        if not isinstance(allocation.argument_registers, tuple) or any(not isinstance(register, str) for register in allocation.argument_registers):
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.argument_registers 必须是字符串元组")
        if len(set(allocation.argument_registers)) != len(allocation.argument_registers):
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.argument_registers 不能重复")
        expected_argument_prefix = argument_registers[:len(allocation.argument_registers)]
        if allocation.argument_registers != expected_argument_prefix:
            raise NativeCodegenError(
                f"native 内存执行函数 {name} register_allocation.argument_registers 与 ABI 前缀不一致: "
                f"记录 {list(allocation.argument_registers)}, 期望 {list(expected_argument_prefix)}"
            )
        if allocation.return_register != return_register:
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.return_register 与 ABI 不一致")
        if allocation.frame_pointer != frame_pointer:
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.frame_pointer 与 ABI 不一致")
        if allocation.stack_pointer != stack_pointer:
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.stack_pointer 与 ABI 不一致")
        if allocation.virtual_register_storage != "全部写入栈槽":
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.virtual_register_storage 必须是全部写入栈槽")
        if allocation.local_storage != "全部写入栈槽":
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.local_storage 必须是全部写入栈槽")
        if allocation.global_frame_register not in {None, "R11"}:
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.global_frame_register 必须是 R11 或 None")
        if allocation.global_frame_role not in {"none", "owner", "borrowed"}:
            raise NativeCodegenError(f"native 内存执行函数 {name} register_allocation.global_frame_role 暂不支持")
        has_global_slots = any(slot.name.startswith("global[") for slot in function.stack_slots)
        expected_global_register = "R11" if has_global_slots else None
        if allocation.global_frame_register != expected_global_register:
            raise NativeCodegenError(
                f"native 内存执行函数 {name} register_allocation.global_frame_register 不一致: "
                f"记录 {allocation.global_frame_register!r}, 期望 {expected_global_register!r}"
            )
        expected_global_role = "owner" if name in global_frame_owners and has_global_slots else ("borrowed" if has_global_slots else "none")
        if allocation.global_frame_role != expected_global_role:
            raise NativeCodegenError(
                f"native 内存执行函数 {name} register_allocation.global_frame_role 不一致: "
                f"记录 {allocation.global_frame_role!r}, 期望 {expected_global_role!r}"
            )


def _validate_relocations(program: NativeCodeProgram) -> None:
    """校验 native program rel32 修补记录与机器码一致。"""
    known_targets = set(program.functions)
    for name, function in program.functions.items():
        expected_relocations = {}
        instructions_by_offset = {}
        exit_probe_jump_targets = {
            probe.jump_offset: probe.probe_label
            for probe in function.exit_probes
            if isinstance(probe.jump_offset, int)
            and not isinstance(probe.jump_offset, bool)
            and isinstance(probe.probe_label, str)
            and probe.probe_label
        }
        for instruction in function.instructions:
            instructions_by_offset[instruction.offset] = instruction
            if instruction.code[:1] == b"\xE8":
                expected_relocations[instruction.offset] = "call_rel32"
            else:
                for relocation_kind, opcode in REL32_JUMP_OPCODES.items():
                    if instruction.code.startswith(opcode):
                        expected_relocations[instruction.offset] = relocation_kind
                        break
        seen_relocation_offsets = set()
        for relocation in function.relocations:
            _validate_source_location(f"native 内存执行函数 {name} rel32 修补记录", relocation)
            for field in ("offset", "patch_offset", "displacement", "size"):
                value = getattr(relocation, field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 内存执行函数 {name} rel32 {field} 必须是整数")
            if relocation.kind not in {*REL32_JUMP_OPCODES, "call_rel32"}:
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补类型暂不支持: {relocation.kind}")
            if not isinstance(relocation.target, str) or not relocation.target:
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 target 必须是非空字符串")
            if relocation.size != 4:
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补字段大小必须为 4，实际 {relocation.size}")
            if relocation.target not in known_targets and not _function_contains_label(function, relocation.target):
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补目标未知: {relocation.target}")
            expected_exit_probe_target = exit_probe_jump_targets.get(relocation.offset)
            if expected_exit_probe_target is not None and (
                relocation.kind != "jne_rel32" or relocation.target != expected_exit_probe_target
            ):
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} _exit 传播探针 jump 修补目标不一致: "
                    f"探针 {expected_exit_probe_target}, 修补记录 {relocation.target}"
                )
            expected_patch_offset = relocation.offset + (len(REL32_JUMP_OPCODES[relocation.kind]) if relocation.kind in REL32_JUMP_OPCODES else 1)
            if relocation.offset in seen_relocation_offsets:
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补记录重复: {relocation.offset}")
            seen_relocation_offsets.add(relocation.offset)
            relocation_instruction = instructions_by_offset.get(relocation.offset)
            if relocation_instruction is not None and (
                relocation_instruction.source_pc != relocation.source_pc
                or relocation_instruction.source_line != relocation.source_line
            ):
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 来源位置与清单不一致")
            if relocation.patch_offset != expected_patch_offset:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} rel32 修补字段偏移不一致: "
                    f"记录 {relocation.patch_offset}, 期望 {expected_patch_offset}"
                )
            if relocation.patch_offset < function.offset or relocation.patch_offset + relocation.size > function.offset + len(function.code):
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补字段越界: {relocation.patch_offset}")
            opcode = program.code[relocation.offset:relocation.patch_offset]
            if relocation.kind in REL32_JUMP_OPCODES and opcode != REL32_JUMP_OPCODES[relocation.kind]:
                raise NativeCodegenError(f"native 内存执行函数 {name} {relocation.kind} opcode 不一致")
            if relocation.kind == "call_rel32" and opcode != b"\xE8":
                raise NativeCodegenError(f"native 内存执行函数 {name} call_rel32 opcode 不一致")
            actual = int.from_bytes(
                program.code[relocation.patch_offset:relocation.patch_offset + relocation.size],
                byteorder="little",
                signed=True,
            )
            if actual != relocation.displacement:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} rel32 位移与机器码不一致: 记录 {relocation.displacement}, 机器码 {actual}"
                )
            if relocation_instruction is None:
                raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补指令清单缺失: {relocation.offset}")
            if relocation_instruction is not None:
                expected_asm_prefix = {**REL32_JUMP_ASM_PREFIXES, "call_rel32": "call "}[relocation.kind]
                if not relocation_instruction.asm.startswith(expected_asm_prefix):
                    raise NativeCodegenError(f"native 内存执行函数 {name} rel32 修补指令清单类型不一致")
                instruction_target = relocation_instruction.asm.split(" ", 1)[1].split(";", 1)[0].strip()
                if instruction_target != relocation.target:
                    raise NativeCodegenError(
                        f"native 内存执行函数 {name} rel32 目标与清单不一致: 记录 {relocation.target}, 指令 {instruction_target}"
                    )
        for relocation_offset, expected_kind in expected_relocations.items():
            if relocation_offset not in seen_relocation_offsets:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} rel32 指令缺少修补记录: offset {relocation_offset}, 类型 {expected_kind}"
                )


def _function_contains_label(function: NativeCodeFunction, target: str) -> bool:
    """判断函数清单中是否包含指定标签。"""
    return _function_label_offset(function, target) is not None


def _function_label_offset(function: NativeCodeFunction, target: str) -> int | None:
    """查找函数清单中的标签偏移。"""
    for instruction in function.instructions:
        if instruction.source_op == "label" and instruction.asm == f"{target}:":
            return instruction.offset
    return None


def _validate_exit_propagation(program: NativeCodeProgram) -> None:
    """校验 call 后的 native _exit 标志传播探针。"""
    for name, function in program.functions.items():
        labels = {instruction.asm[:-1] for instruction in function.instructions if instruction.source_op == "label" and instruction.asm.endswith(":")}
        instructions_by_offset = {instruction.offset: instruction for instruction in function.instructions}
        relocations_by_offset = {relocation.offset: relocation for relocation in function.relocations}
        probe_call_offsets = set()
        probe_jump_offsets = set()
        for probe in function.exit_probes:
            _validate_source_location(f"native 内存执行函数 {name} _exit 传播探针", probe)
            for field in ("call_offset", "test_offset", "jump_offset"):
                value = getattr(probe, field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 {field} 必须是整数")
            if not isinstance(probe.target, str) or not probe.target:
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 target 必须是非空字符串")
            if not isinstance(probe.probe_label, str) or not probe.probe_label:
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 probe_label 必须是非空字符串")
            if probe.call_offset < function.offset or probe.call_offset >= function.offset + len(function.code):
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 call_offset 越界: {probe.call_offset}")
            if probe.test_offset < function.offset or probe.test_offset >= function.offset + len(function.code):
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 test_offset 越界: {probe.test_offset}")
            if probe.jump_offset < function.offset or probe.jump_offset >= function.offset + len(function.code):
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 jump_offset 越界: {probe.jump_offset}")
            if probe.target not in program.functions:
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针目标未知: {probe.target}")
            if probe.probe_label not in labels:
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针标签未知: {probe.probe_label}")
            if program.code[probe.call_offset:probe.call_offset + 1] != b"\xE8":
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 call opcode 不一致")
            if program.code[probe.test_offset:probe.test_offset + 3] != b"\x48\x85\xD2":
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 test opcode 不一致")
            if program.code[probe.jump_offset:probe.jump_offset + 2] != b"\x0F\x85":
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 jump opcode 不一致")
            call_instruction = instructions_by_offset.get(probe.call_offset)
            if call_instruction is None or call_instruction.source_op != "call":
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 call 清单不一致")
            call_relocation = relocations_by_offset.get(probe.call_offset)
            if call_relocation is not None and call_relocation.target != probe.target:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} _exit 传播探针 call 修补目标不一致: "
                    f"探针 {probe.target}, 修补记录 {call_relocation.target}"
                )
            if not call_instruction.asm.startswith(f"call {probe.target}"):
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 call 清单不一致")
            test_instruction = instructions_by_offset.get(probe.test_offset)
            if (
                test_instruction is None
                or test_instruction.source_op != "call"
                or test_instruction.asm != "test rdx, rdx ; native _exit flag"
            ):
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 test 清单不一致")
            jump_instruction = instructions_by_offset.get(probe.jump_offset)
            if (
                jump_instruction is None
                or jump_instruction.source_op != "exit_probe"
                or not jump_instruction.asm.startswith(f"jne {probe.probe_label}")
            ):
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 jump 清单不一致")
            for instruction in (call_instruction, test_instruction, jump_instruction):
                if instruction.source_pc != probe.source_pc or instruction.source_line != probe.source_line:
                    raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针来源位置与清单不一致")
            jump_relocation = relocations_by_offset.get(probe.jump_offset)
            if (
                jump_relocation is None
                or jump_relocation.kind != "jne_rel32"
                or jump_relocation.target != probe.probe_label
            ):
                relocation_target = None if jump_relocation is None else jump_relocation.target
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} _exit 传播探针 jump 修补记录不一致: "
                    f"探针 {probe.probe_label}, 修补记录 {relocation_target}"
                )
            if probe.call_offset in probe_call_offsets:
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 call_offset 重复: {probe.call_offset}")
            probe_call_offsets.add(probe.call_offset)
            if probe.jump_offset in probe_jump_offsets:
                raise NativeCodegenError(f"native 内存执行函数 {name} _exit 传播探针 jump_offset 重复: {probe.jump_offset}")
            probe_jump_offsets.add(probe.jump_offset)
        for index, instruction in enumerate(function.instructions):
            if instruction.source_op != "call" or not instruction.asm.startswith("call "):
                continue
            if instruction.offset not in probe_call_offsets:
                raise NativeCodegenError(f"native 内存执行函数 {name} call 缺少 _exit 传播探针记录: {instruction.asm}")
            if index + 3 >= len(function.instructions):
                raise NativeCodegenError(f"native 内存执行函数 {name} call 缺少 _exit 传播探针: {instruction.asm}")
            add_rsp = function.instructions[index + 1]
            test_rdx = function.instructions[index + 2]
            jump = function.instructions[index + 3]
            if add_rsp.source_op != "call" or not add_rsp.asm.startswith("add rsp, ") or add_rsp.code[:3] != b"\x48\x81\xC4":
                raise NativeCodegenError(f"native 内存执行函数 {name} call 后缺少 add rsp 恢复栈窗口")
            if test_rdx.source_op != "call" or test_rdx.asm != "test rdx, rdx ; native _exit flag" or test_rdx.code != b"\x48\x85\xD2":
                raise NativeCodegenError(f"native 内存执行函数 {name} call 后缺少 native _exit 标志检查")
            if jump.source_op != "exit_probe" or not jump.asm.startswith("jne __propagate_exit_") or jump.code[:2] != b"\x0F\x85":
                raise NativeCodegenError(f"native 内存执行函数 {name} call 后缺少 native _exit 传播跳转")
            target = jump.asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if target not in labels:
                raise NativeCodegenError(f"native 内存执行函数 {name} native _exit 传播目标未知: {target}")


def _validate_call_frames(program: NativeCodeProgram) -> None:
    """校验 native 调用栈窗口记录与机器码一致。"""
    abi = getattr(program, "abi", None)
    abi_target = getattr(abi, "target", None)
    if abi_target != program.target:
        raise NativeCodegenError(f"native 内存执行 ABI 目标平台与 program.target 不一致: ABI {abi_target}, program {program.target}")
    registers = getattr(abi, "registers", None)
    argument_registers = getattr(registers, "argument_registers", None)
    if not isinstance(argument_registers, tuple) or any(not isinstance(register, str) for register in argument_registers):
        raise NativeCodegenError("native 内存执行 ABI 参数寄存器必须是字符串元组")
    word_size = getattr(abi, "word_size", None)
    if not isinstance(word_size, int) or isinstance(word_size, bool):
        raise NativeCodegenError(f"native 内存执行 ABI word_size 必须是整数，实际 {type(word_size).__name__}")
    if word_size != 8:
        raise NativeCodegenError(f"native 内存执行 ABI word_size 必须为 8，实际 {word_size}")
    shadow_space_size = getattr(abi, "shadow_space_size", None)
    if not isinstance(shadow_space_size, int) or isinstance(shadow_space_size, bool):
        raise NativeCodegenError(f"native 内存执行 ABI shadow_space_size 必须是整数，实际 {type(shadow_space_size).__name__}")
    if shadow_space_size < 0:
        raise NativeCodegenError(f"native 内存执行 ABI shadow_space_size 不能为负数，实际 {shadow_space_size}")
    stack_alignment = getattr(abi, "stack_alignment", None)
    if not isinstance(stack_alignment, int) or isinstance(stack_alignment, bool):
        raise NativeCodegenError(f"native 内存执行 ABI stack_alignment 必须是整数，实际 {type(stack_alignment).__name__}")
    if stack_alignment <= 0:
        raise NativeCodegenError(f"native 内存执行 ABI stack_alignment 必须为正数，实际 {stack_alignment}")
    return_register = getattr(registers, "return_register", None)
    if not isinstance(return_register, str) or return_register.upper() != "RAX":
        raise NativeCodegenError(f"native 内存执行 ABI 返回寄存器必须为 RAX，实际 {return_register}")
    frame_pointer = getattr(registers, "frame_pointer", None)
    if not isinstance(frame_pointer, str) or frame_pointer.upper() != "RBP":
        raise NativeCodegenError(f"native 内存执行 ABI 帧指针寄存器必须为 RBP，实际 {frame_pointer}")
    stack_pointer = getattr(registers, "stack_pointer", None)
    if not isinstance(stack_pointer, str) or stack_pointer.upper() != "RSP":
        raise NativeCodegenError(f"native 内存执行 ABI 栈指针寄存器必须为 RSP，实际 {stack_pointer}")
    seen_argument_registers = set()
    supported_argument_registers = {"RCX", "RDX", "R8", "R9"}
    for register in argument_registers:
        register_name = register.upper()
        if register_name in seen_argument_registers:
            raise NativeCodegenError(f"native 内存执行 ABI 参数寄存器重复: {register}")
        seen_argument_registers.add(register_name)
        if register_name not in supported_argument_registers:
            raise NativeCodegenError(f"native 内存执行 ABI 参数寄存器暂不支持 {register}")
    supported_value_types = getattr(abi, "supported_value_types", None)
    if not isinstance(supported_value_types, tuple) or any(not isinstance(item, str) for item in supported_value_types):
        raise NativeCodegenError("native 内存执行 ABI supported_value_types 必须是字符串元组")
    if set(supported_value_types) != {"int64", "bool64", "void"}:
        raise NativeCodegenError(f"native 内存执行 ABI supported_value_types 不一致: {supported_value_types}")
    for name, function in program.functions.items():
        expected_frame_offsets = {
            instruction.offset
            for instruction in function.instructions
            if instruction.source_op == "call" and instruction.asm.startswith("sub rsp, ")
        }
        instructions_by_offset = {instruction.offset: instruction for instruction in function.instructions}
        seen_frame_offsets = set()
        for frame in function.call_frames:
            _validate_source_location(f"native 内存执行函数 {name} 调用栈窗口", frame)
            if not isinstance(frame.target, str) or not frame.target:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 target 必须是非空字符串")
            for field in (
                "offset",
                "arg_count",
                "register_arg_count",
                "stack_arg_count",
                "shadow_space_size",
                "stack_arg_bytes",
                "aligned_size",
                "stack_alignment",
            ):
                value = getattr(frame, field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 {field} 必须是整数")
            for field in ("call_offset", "call_end_offset", "add_offset", "add_end_offset"):
                value = getattr(frame, field)
                if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                    raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 {field} 必须是整数或 None")
            for field in (
                "arg_count",
                "register_arg_count",
                "stack_arg_count",
                "shadow_space_size",
                "stack_arg_bytes",
                "aligned_size",
            ):
                value = getattr(frame, field)
                if value < 0:
                    raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 {field} 不能为负数")
            if frame.target not in program.functions:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口目标未知: {frame.target}")
            if frame.arg_count != frame.register_arg_count + frame.stack_arg_count:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口参数数量不一致")
            if not isinstance(frame.arg_types, tuple) or any(not isinstance(item, str) for item in frame.arg_types):
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 arg_types 必须是字符串元组")
            if len(frame.arg_types) != frame.arg_count:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 arg_types 数量不一致: "
                    f"记录 {len(frame.arg_types)}, 参数 {frame.arg_count}"
                )
            if not isinstance(frame.param_types, tuple) or any(not isinstance(item, str) for item in frame.param_types):
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 param_types 必须是字符串元组")
            if len(frame.param_types) != frame.arg_count:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 param_types 数量不一致: "
                    f"记录 {len(frame.param_types)}, 参数 {frame.arg_count}"
                )
            target_param_types = program.functions[frame.target].param_types
            if frame.param_types != target_param_types:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口形参类型与目标函数 {frame.target} 签名不一致: "
                    f"记录 {list(frame.param_types)}, 签名 {list(target_param_types)}"
                )
            for type_index, (arg_type, param_type) in enumerate(zip(frame.arg_types, frame.param_types)):
                if not _is_argument_type_compatible(param_type, arg_type):
                    raise NativeCodegenError(
                        f"native 内存执行函数 {name} 调用栈窗口第 {type_index} 个参数类型不兼容: "
                        f"形参 {param_type}, 实参 {arg_type}"
                    )
            expected_register_arg_count = min(frame.arg_count, len(argument_registers))
            if frame.register_arg_count != expected_register_arg_count:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口寄存器参数数量与 ABI 不一致: "
                    f"记录 {frame.register_arg_count}, 期望 {expected_register_arg_count}"
                )
            expected_stack_arg_count = max(0, frame.arg_count - len(argument_registers))
            if frame.stack_arg_count != expected_stack_arg_count:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口栈参数数量与 ABI 不一致: "
                    f"记录 {frame.stack_arg_count}, 期望 {expected_stack_arg_count}"
                )
            if frame.stack_arg_bytes != frame.stack_arg_count * word_size:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口栈实参字节不一致")
            if frame.shadow_space_size != shadow_space_size:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 shadow space 与 ABI 不一致: "
                    f"记录 {frame.shadow_space_size}, 期望 {shadow_space_size}"
                )
            if frame.stack_alignment <= 0:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口对齐必须为正数")
            if frame.stack_alignment != stack_alignment:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口对齐与 ABI 不一致: "
                    f"记录 {frame.stack_alignment}, 期望 {stack_alignment}"
                )
            expected_size = frame.shadow_space_size + frame.stack_arg_bytes
            remainder = expected_size % frame.stack_alignment
            if remainder:
                expected_size += frame.stack_alignment - remainder
            if frame.aligned_size != expected_size:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口大小不一致: 记录 {frame.aligned_size}, 期望 {expected_size}"
                )
            if frame.offset < function.offset or frame.offset + 7 > function.offset + len(function.code):
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 sub rsp 越界: {frame.offset}")
            if frame.offset in seen_frame_offsets:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口记录重复: {frame.offset}")
            seen_frame_offsets.add(frame.offset)
            code = program.code[frame.offset:frame.offset + 7]
            if code[:3] != b"\x48\x81\xEC":
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 sub rsp opcode 不一致")
            actual_size = int.from_bytes(code[3:7], byteorder="little", signed=True)
            if actual_size != frame.aligned_size:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 sub rsp 大小不一致: 记录 {frame.aligned_size}, 机器码 {actual_size}"
                )
            frame_instruction = instructions_by_offset.get(frame.offset)
            if (
                frame_instruction is None
                or frame_instruction.source_op != "call"
                or not frame_instruction.asm.startswith("sub rsp, ")
            ):
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口清单缺失")
            if frame_instruction.code != code:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 sub rsp 清单 bytes 与机器码不一致")
            if frame_instruction.source_pc != frame.source_pc or frame_instruction.source_line != frame.source_line:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口来源位置与清单不一致")
            frame_instruction_index = function.instructions.index(frame_instruction)
            call_instruction = None
            call_instruction_index = None
            for candidate_index, candidate in enumerate(function.instructions[frame_instruction_index + 1:], start=frame_instruction_index + 1):
                if candidate.source_op == "call" and candidate.asm.startswith("call "):
                    call_instruction = candidate
                    call_instruction_index = candidate_index
                    break
            if call_instruction is None:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 call 清单缺失")
            call_target = call_instruction.asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if call_target != frame.target:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口目标与 call 清单不一致: 记录 {frame.target}, 指令 {call_target}"
                )
            if call_instruction.source_pc != frame.source_pc or call_instruction.source_line != frame.source_line:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 call 来源位置与清单不一致")
            if frame.call_offset is not None and frame.call_offset != call_instruction.offset:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 call_offset 与清单不一致: "
                    f"记录 {frame.call_offset}, 清单 {call_instruction.offset}"
                )
            if frame.call_end_offset is not None and frame.call_end_offset != call_instruction.offset + len(call_instruction.code):
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 call_end_offset 与清单不一致: "
                    f"记录 {frame.call_end_offset}, 清单 {call_instruction.offset + len(call_instruction.code)}"
                )
            call_code = program.code[call_instruction.offset:call_instruction.offset + len(call_instruction.code)]
            if call_instruction.code != call_code:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 call 清单 bytes 与机器码不一致")
            if call_code[:1] != b"\xE8":
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 call opcode 不一致")
            if call_instruction_index is None or call_instruction_index + 1 >= len(function.instructions):
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 add rsp 清单缺失")
            add_instruction = function.instructions[call_instruction_index + 1]
            add_code = program.code[add_instruction.offset:add_instruction.offset + len(add_instruction.code)]
            if add_instruction.code != add_code:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 add rsp 清单 bytes 与机器码不一致")
            if (
                add_instruction.source_op != "call"
                or add_instruction.asm != f"add rsp, {frame.aligned_size}"
                or add_instruction.code[:3] != b"\x48\x81\xC4"
            ):
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 add rsp 清单不一致")
            add_size = int.from_bytes(add_code[3:7], byteorder="little", signed=True)
            if add_size != frame.aligned_size:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 add rsp 大小不一致: 记录 {frame.aligned_size}, 机器码 {add_size}"
                )
            if add_instruction.source_pc != frame.source_pc or add_instruction.source_line != frame.source_line:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口 add rsp 来源位置与清单不一致")
            if frame.add_offset is not None and frame.add_offset != add_instruction.offset:
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 add_offset 与清单不一致: "
                    f"记录 {frame.add_offset}, 清单 {add_instruction.offset}"
                )
            if frame.add_end_offset is not None and frame.add_end_offset != add_instruction.offset + len(add_instruction.code):
                raise NativeCodegenError(
                    f"native 内存执行函数 {name} 调用栈窗口 add_end_offset 与清单不一致: "
                    f"记录 {frame.add_end_offset}, 清单 {add_instruction.offset + len(add_instruction.code)}"
                )
        for frame_offset in expected_frame_offsets:
            if frame_offset not in seen_frame_offsets:
                raise NativeCodegenError(f"native 内存执行函数 {name} 调用栈窗口缺少记录: {frame_offset}")


def _validate_source_location(owner: str, item: object) -> None:
    """校验 native 调试来源位置字段。"""
    for field in ("source_pc", "source_line"):
        value = getattr(item, field)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"{owner}.{field} 必须是非负整数或 None，实际 {type(value).__name__}")
        if value < 0:
            raise NativeCodegenError(f"{owner}.{field} 必须是非负整数或 None，实际 {value}")


def _run_code_in_memory(code: bytes, entry_offset: int) -> int:
    """复制机器码到可执行内存并调用入口。"""
    if not isinstance(code, bytes):
        raise NativeCodegenError("native 内存执行 code 必须是 bytes")
    if not isinstance(entry_offset, int) or isinstance(entry_offset, bool):
        raise NativeCodegenError("native 内存执行入口偏移必须是整数")
    if not code:
        raise NativeCodegenError("native 内存执行需要非空机器码")
    if entry_offset < 0:
        raise NativeCodegenError(f"native 内存执行入口偏移不能为负数: {entry_offset}")
    if entry_offset >= len(code):
        raise NativeCodegenError(f"native 内存执行入口偏移越界: {entry_offset}, 机器码长度 {len(code)}")
    if not can_run_native_memory():
        raise NativeCodegenError("native 内存执行仅支持 Windows x64")
    kernel32 = ctypes.windll.kernel32
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    kernel32.VirtualFree.restype = ctypes.c_bool
    kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.FlushInstructionCache.restype = ctypes.c_bool
    kernel32.FlushInstructionCache.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    size = len(code)
    address = kernel32.VirtualAlloc(None, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not address:
        raise NativeCodegenError("VirtualAlloc 分配可执行内存失败")
    try:
        ctypes.memmove(address, code, size)
        current_process = kernel32.GetCurrentProcess()
        if not kernel32.FlushInstructionCache(current_process, address, size):
            raise NativeCodegenError("FlushInstructionCache 刷新指令缓存失败")
        return int(ctypes.CFUNCTYPE(ctypes.c_int64)(address + entry_offset)())
    finally:
        kernel32.VirtualFree(address, 0, MEM_RELEASE)

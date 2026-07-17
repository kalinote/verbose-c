import hashlib
import json
from dataclasses import dataclass, field

from verbose_c.compiler.native.abi import WINDOWS_X64_ABI, WindowsX64ABI
from verbose_c.compiler.native.encoder import (
    ConditionCode,
    encode_add_rax_r10,
    encode_add_rdx_r10,
    encode_add_rsp_imm32,
    encode_call_rel32,
    encode_cmp_rax_r10,
    encode_cqo,
    encode_epilogue,
    encode_idiv_r10,
    encode_imul_rax_r10,
    encode_je_rel32,
    encode_jmp_rel32,
    encode_jns_rel32,
    encode_jne_rel32,
    encode_mov_rax_rdx,
    encode_mov_r10_from_rbp_offset,
    encode_mov_r10_imm64,
    encode_mov_rax_from_rbp_positive_offset,
    encode_mov_rax_from_rbp_offset,
    encode_mov_rax_from_r11_offset,
    encode_mov_rax_imm64,
    encode_mov_rbp_offset_from_rax,
    encode_mov_rbp_offset_from_reg,
    encode_mov_reg_from_rax,
    encode_mov_r10_from_r11_offset,
    encode_mov_rdx_imm64,
    encode_mov_rsp_offset_from_rax,
    encode_mov_r11_offset_from_rax,
    encode_mov_r11_rbp,
    encode_movzx_rax_al,
    encode_neg_rax,
    encode_prologue,
    encode_setcc_al,
    encode_sub_rsp_imm32,
    encode_sub_rax_r10,
    encode_test_rdx_rdx,
    encode_xor_rax_r10,
)
from verbose_c.compiler.native.errors import NativeCodegenError
from verbose_c.compiler.native.machine_ir import MachineBlock, MachineFunction, MachineInstruction, MachineOperand, MachineProgram, MachineTerminator
from verbose_c.compiler.native.target import NativeTarget


@dataclass(frozen=True)
class NativeCodeInstruction:
    """x64 机器码清单项。"""

    offset: int
    code: bytes
    asm: str
    source_op: str
    source_pc: int | None = None
    source_line: int | None = None
    source_attrs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeStackSlotAllocation:
    """native 栈槽分配项。"""

    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class NativeCallFrameAllocation:
    """native 调用栈窗口分配项。"""

    offset: int
    target: str
    arg_count: int
    register_arg_count: int
    stack_arg_count: int
    shadow_space_size: int
    stack_arg_bytes: int
    aligned_size: int
    stack_alignment: int
    source_pc: int | None = None
    source_line: int | None = None
    call_offset: int | None = None
    call_end_offset: int | None = None
    add_offset: int | None = None
    add_end_offset: int | None = None
    arg_types: tuple[str, ...] = ()
    param_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeRelocation:
    """native rel32 修补记录。"""

    offset: int
    patch_offset: int
    kind: str
    target: str
    displacement: int
    size: int = 4
    source_pc: int | None = None
    source_line: int | None = None


@dataclass(frozen=True)
class NativeExitProbe:
    """native _exit 传播探针。"""

    call_offset: int
    test_offset: int
    jump_offset: int
    target: str
    probe_label: str
    source_pc: int | None = None
    source_line: int | None = None


@dataclass(frozen=True)
class NativeSymbol:
    """native 机器码符号表项。"""

    name: str
    offset: int
    size: int
    kind: str = "function"
    is_entry: bool = False
    return_type: str = "int64"
    param_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeRegisterAllocation:
    """native 函数的寄存器分配摘要。"""

    strategy: str = "保守栈槽分配"
    temporary_registers: tuple[str, ...] = ("RAX", "R10")
    argument_registers: tuple[str, ...] = ()
    return_register: str = "RAX"
    frame_pointer: str = "RBP"
    stack_pointer: str = "RSP"
    virtual_register_storage: str = "全部写入栈槽"
    local_storage: str = "全部写入栈槽"
    global_frame_register: str | None = None
    global_frame_role: str = "none"


@dataclass
class NativeCodeFunction:
    """x64 机器码函数。"""

    name: str
    code: bytes
    instructions: list[NativeCodeInstruction]
    frame_size: int
    offset: int = 0
    stack_slots: list[NativeStackSlotAllocation] = field(default_factory=list)
    call_frames: list[NativeCallFrameAllocation] = field(default_factory=list)
    relocations: list[NativeRelocation] = field(default_factory=list)
    exit_probes: list[NativeExitProbe] = field(default_factory=list)
    register_allocation: NativeRegisterAllocation = field(default_factory=NativeRegisterAllocation)
    return_type: str = "int64"
    param_types: tuple[str, ...] = ()


@dataclass
class NativeCodeProgram:
    """x64 机器码程序。"""

    target: NativeTarget
    entry: NativeCodeFunction
    functions: dict[str, NativeCodeFunction] = field(default_factory=dict)
    code: bytes = b""
    entry_offset: int = 0
    abi: WindowsX64ABI = WINDOWS_X64_ABI
    symbols: list[NativeSymbol] = field(default_factory=list)


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

_SUPPORTED_RETURN_TYPES = {"int64", "bool64", "void"}
_SUPPORTED_VALUE_TYPES = {"int64", "bool64"}
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
    "nlint",
    "unlimited int",
    "int64",
}
_BOOL_CAST_TARGET_TYPES = {"bool", "bool64"}
_NARROW_INTEGER_CAST_RANGES = {
    "char": (-128, 127),
    "short": (-32768, 32767),
}
_PE_DOS_HEADER_SIZE = 64
_PE_LFANEW = 0x80
_PE_SIGNATURE_SIZE = 4
_PE_COFF_HEADER_SIZE = 20
_PE_OPTIONAL_HEADER_SIZE = 240
_PE_SECTION_HEADER_SIZE = 40
_PE_FILE_ALIGNMENT = 512
_PE_SECTION_ALIGNMENT = 4096
_PE_TEXT_RVA = 4096
_PE_IMAGE_BASE = 0x140000000
_MAP_TOP_LEVEL_FIELDS = {
    "schema_version",
    "target",
    "pe_machine",
    "pe_machine_value",
    "pe_coff_header",
    "pe_optional_header_magic",
    "pe_optional_header_magic_value",
    "pe_optional_header",
    "pe_subsystem",
    "pe_subsystem_value",
    "pe_number_of_sections",
    "pe_dos_header_size",
    "pe_lfanew",
    "pe_signature_offset",
    "pe_signature_size",
    "pe_coff_header_offset",
    "pe_coff_header_size",
    "pe_optional_header_offset",
    "pe_optional_header_size",
    "pe_section_table_offset",
    "pe_section_header_size",
    "pe_section_table_size",
    "pe_size_of_headers",
    "pe_file_layout",
    "pe_base_of_code",
    "pe_address_of_entry_point",
    "pe_size_of_code",
    "pe_size_of_initialized_data",
    "pe_size_of_uninitialized_data",
    "pe_size_of_image",
    "pe_file_alignment",
    "pe_section_alignment",
    "image_base",
    "abi",
    "entry",
    "entry_offset",
    "entry_rva",
    "entry_va",
    "global_frame_owner",
    "code_size",
    "code_sha256",
    "sections",
    "symbols",
    "functions",
}
_MAP_PE_FILE_LAYOUT_FIELDS = {
    "dos_header",
    "dos_stub_padding",
    "pe_signature",
    "coff_header",
    "optional_header",
    "section_table",
    "headers_padding",
    "text_raw",
    "file_size",
}
_MAP_PE_FILE_LAYOUT_RANGE_FIELDS = {
    "offset",
    "size",
    "end_offset",
}
_MAP_PE_COFF_HEADER_FIELDS = {
    "Machine",
    "NumberOfSections",
    "TimeDateStamp",
    "PointerToSymbolTable",
    "NumberOfSymbols",
    "SizeOfOptionalHeader",
    "Characteristics",
}
_MAP_PE_OPTIONAL_HEADER_FIELDS = {
    "Magic",
    "SizeOfCode",
    "SizeOfInitializedData",
    "SizeOfUninitializedData",
    "AddressOfEntryPoint",
    "BaseOfCode",
    "ImageBase",
    "SectionAlignment",
    "FileAlignment",
    "SizeOfImage",
    "SizeOfHeaders",
    "Subsystem",
    "NumberOfRvaAndSizes",
}
_MAP_ABI_FIELDS = {
    "name",
    "target",
    "word_size",
    "stack_alignment",
    "shadow_space_size",
    "argument_registers",
    "return_register",
    "frame_pointer",
    "stack_pointer",
    "supported_value_types",
}
_MAP_TEXT_SECTION_FIELDS = {
    "name",
    "name_bytes",
    "offset",
    "size",
    "end_offset",
    "virtual_size",
    "raw_size_aligned",
    "raw_padding_size",
    "raw_padded_sha256",
    "virtual_size_aligned",
    "rva",
    "end_rva",
    "va",
    "end_va",
    "entry_offset",
    "pe_raw_pointer",
    "pe_raw_end_pointer",
    "pe_section_header",
    "sha256",
    "alignment",
    "file_alignment",
    "section_alignment",
    "permissions",
    "characteristics",
    "pe_characteristics",
}
_MAP_PE_SECTION_HEADER_FIELDS = {
    "Name",
    "NameBytes",
    "VirtualSize",
    "VirtualAddress",
    "SizeOfRawData",
    "PointerToRawData",
    "PointerToRelocations",
    "PointerToLinenumbers",
    "NumberOfRelocations",
    "NumberOfLinenumbers",
    "Characteristics",
}
_MAP_FUNCTION_FIELDS = {
    "name",
    "offset",
    "rva",
    "va",
    "size",
    "end_offset",
    "end_rva",
    "end_va",
    "code_sha256",
    "frame_size",
    "return_type",
    "param_types",
    "register_allocation",
    "stack_slots",
    "value_locations",
    "labels",
    "call_frames",
    "relocations",
    "exit_probes",
    "instructions",
}
_MAP_SYMBOL_FIELDS = {
    "name",
    "kind",
    "offset",
    "rva",
    "va",
    "size",
    "end_offset",
    "end_rva",
    "end_va",
    "code_sha256",
    "is_entry",
    "return_type",
    "param_types",
}
_MAP_STACK_SLOT_FIELDS = {
    "name",
    "offset",
    "size",
}
_MAP_VALUE_LOCATION_FIELDS = {
    "name",
    "kind",
    "index",
    "storage",
    "base_register",
    "offset",
    "size",
}
_MAP_REGISTER_ALLOCATION_FIELDS = {
    "strategy",
    "temporary_registers",
    "argument_registers",
    "return_register",
    "frame_pointer",
    "stack_pointer",
    "virtual_register_storage",
    "local_storage",
    "global_frame_register",
    "global_frame_role",
}
_MAP_LABEL_FIELDS = {
    "name",
    "offset",
    "rva",
    "va",
    "source_pc",
    "source_line",
}
_MAP_INSTRUCTION_FIELDS = {
    "offset",
    "rva",
    "va",
    "size",
    "end_offset",
    "end_rva",
    "end_va",
    "bytes",
    "code_sha256",
    "asm",
    "source_op",
    "source_attrs",
    "source_pc",
    "source_line",
}
_MAP_CALL_FRAME_FIELDS = {
    "offset",
    "end_offset",
    "sub_code_sha256",
    "rva",
    "end_rva",
    "va",
    "end_va",
    "call_offset",
    "call_end_offset",
    "call_code_sha256",
    "call_rva",
    "call_end_rva",
    "call_va",
    "call_end_va",
    "add_offset",
    "add_end_offset",
    "add_code_sha256",
    "add_rva",
    "add_end_rva",
    "add_va",
    "add_end_va",
    "target",
    "arg_count",
    "arg_types",
    "param_types",
    "register_arg_count",
    "stack_arg_count",
    "shadow_space_size",
    "stack_arg_bytes",
    "aligned_size",
    "stack_alignment",
    "source_pc",
    "source_line",
}
_MAP_RELOCATION_FIELDS = {
    "offset",
    "rva",
    "va",
    "patch_offset",
    "patch_rva",
    "patch_va",
    "patch_end_offset",
    "patch_end_rva",
    "patch_end_va",
    "instruction_code_sha256",
    "patch_code_sha256",
    "kind",
    "target",
    "target_rva",
    "target_va",
    "displacement",
    "size",
    "source_pc",
    "source_line",
}
_MAP_EXIT_PROBE_FIELDS = {
    "call_offset",
    "call_end_offset",
    "call_code_sha256",
    "call_rva",
    "call_end_rva",
    "call_va",
    "call_end_va",
    "test_offset",
    "test_end_offset",
    "test_code_sha256",
    "test_rva",
    "test_end_rva",
    "test_va",
    "test_end_va",
    "jump_offset",
    "jump_end_offset",
    "jump_code_sha256",
    "jump_rva",
    "jump_end_rva",
    "jump_va",
    "jump_end_va",
    "target",
    "probe_label",
    "source_pc",
    "source_line",
}
_CALL_REL32_SIZE = len(encode_call_rel32(0))
_TEST_RDX_RDX_SIZE = len(encode_test_rdx_rdx())
_JNE_REL32_SIZE = len(encode_jne_rel32(0))
_REL32_JUMP_OPCODES = {
    "je_rel32": b"\x0F\x84",
    "jmp_rel32": b"\xE9",
    "jne_rel32": b"\x0F\x85",
    "jns_rel32": b"\x0F\x89",
}
_REL32_JUMP_ASM_PREFIXES = {
    "je_rel32": "je ",
    "jmp_rel32": "jmp ",
    "jne_rel32": "jne ",
    "jns_rel32": "jns ",
}
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_INT32_MAX = 2**31 - 1
_SUPPORTED_ARGUMENT_REGISTERS = {"RCX", "RDX", "R8", "R9"}
_SUPPORTED_VREG_TYPES = {"int64", "bool64"}


def _function_param_types(function: MachineFunction) -> list[str]:
    """取得函数形参类型；手工 Machine IR 缺省按 int64 处理。"""
    if function.param_types:
        return list(function.param_types)
    return ["int64"] * len(function.params)


def _native_program_symbols(program: NativeCodeProgram) -> list[NativeSymbol]:
    """返回 native program 符号表，缺省时按函数表合成。"""
    if not isinstance(program.symbols, list):
        raise NativeCodegenError(f"native 机器码符号表必须是列表，实际 {type(program.symbols).__name__}")
    if program.symbols:
        for index, symbol in enumerate(program.symbols):
            if not isinstance(symbol, NativeSymbol):
                raise NativeCodegenError(f"native 机器码符号表第 {index} 项必须是 NativeSymbol")
        return program.symbols
    return [
        NativeSymbol(
            name=function.name,
            offset=function.offset,
            size=len(function.code),
            is_entry=function.name == program.entry.name,
            return_type=function.return_type,
            param_types=function.param_types,
        )
        for function in sorted(program.functions.values(), key=lambda item: item.offset)
    ]


def _native_symbol_function(program: NativeCodeProgram, symbol: NativeSymbol) -> NativeCodeFunction:
    """取得 native 符号对应函数。"""
    function = program.functions.get(symbol.name)
    if function is None:
        raise NativeCodegenError(f"native 机器码符号表引用未知函数: {symbol.name}")
    return function


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


def generate_native_code(program: MachineProgram) -> NativeCodeProgram:
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
        if function.return_type not in _SUPPORTED_RETURN_TYPES:
            raise NativeCodegenError(f"native 机器码 MVP 函数 {function.name} 暂不支持返回类型 {function.return_type}")
        param_types = _function_param_types(function)
        if len(param_types) != len(function.params):
            raise NativeCodegenError(
                f"native 机器码 MVP 函数 {function.name} 参数类型数量不匹配: "
                f"标注 {len(param_types)}, 参数 {len(function.params)}"
            )
        for index, param_type in enumerate(param_types):
            if param_type not in _SUPPORTED_VALUE_TYPES:
                raise NativeCodegenError(f"native 机器码 MVP 函数 {function.name} 第 {index} 个参数暂不支持类型 {param_type}")
    for function in ordered_functions:
        for index, param in enumerate(function.params):
            expected = program.abi.argument_location(index)
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
        if register.upper() not in _SUPPORTED_ARGUMENT_REGISTERS:
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
    if operand.type_hint in _SUPPORTED_VALUE_TYPES:
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
            if op in _BINARY_OP_ASM or op in _COMPARE_OPS:
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_result_type(function, instruction, "bool64" if op in _COMPARE_OPS else "int64")
                _require_arg_count(function, instruction, 2)
                _require_operand_kinds(function, instruction, 0, _VALUE_OPERAND_KINDS)
                _require_operand_kinds(function, instruction, 1, _VALUE_OPERAND_KINDS)
                continue
            if op in {"neg", "not_bool", "cast_bool_int", "cast_int_bool"}:
                _require_result_kind(function, instruction, _RESULT_OPERAND_KINDS)
                _require_result_type(function, instruction, "bool64" if op in _BOOL64_RESULT_OPS else "int64")
                _require_arg_count(function, instruction, 1)
                _require_operand_kinds(function, instruction, 0, _VALUE_OPERAND_KINDS)
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
            if function.return_type in {"int64", "bool64"} and len(terminator.args) != 1:
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


def _is_argument_type_compatible(param_type: str, value_type: str) -> bool:
    """判断 call 实参类型是否匹配形参类型。"""
    return param_type == value_type or (param_type == "int64" and value_type == "bool64")


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
        if instruction.op in {"idiv", "imod"}:
            dividend = instruction.args[0]
            divisor = instruction.args[1]
            known_dividend = _static_known_value(dividend, known_values, known_slots)
            known_divisor = _static_known_value(divisor, known_values, known_slots)
            if raise_idiv_errors and known_divisor == 0:
                raise _machine_node_error(
                    function,
                    instruction,
                    "native 机器码 MVP 暂不生成除数为 0 的 idiv/imod 机器码",
                )
            if raise_idiv_errors and known_dividend == _INT64_MIN and known_divisor == -1:
                raise _machine_node_error(
                    function,
                    instruction,
                    "native 机器码 MVP 暂不生成会触发 signed int64 溢出的 idiv/imod 机器码",
                )
        _, overflows = _static_wrapping_arithmetic_result(instruction, known_values, known_slots)
        if raise_idiv_errors and overflows:
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
            quotient = abs(left) // abs(right)
            quotient = quotient if left * right >= 0 else -quotient
            return _static_int64_value(quotient if instruction.op == "idiv" else left % right)
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
            return 0 if value else 1
        if instruction.op == "cast_int_bool":
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
                if not _is_argument_type_compatible(param_type, operand.type_hint):
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


def format_native_code_program(program: NativeCodeProgram) -> str:
    """生成 x64 机器码 dump 文本。"""
    text_rva = _PE_TEXT_RVA
    image_base = _PE_IMAGE_BASE
    code_size = len(program.code)
    raw_size_aligned = ((code_size + _PE_FILE_ALIGNMENT - 1) // _PE_FILE_ALIGNMENT) * _PE_FILE_ALIGNMENT
    raw_padding_size = raw_size_aligned - code_size
    raw_padded_sha256 = hashlib.sha256(program.code + bytes(raw_padding_size)).hexdigest()
    virtual_size_aligned = ((code_size + _PE_SECTION_ALIGNMENT - 1) // _PE_SECTION_ALIGNMENT) * _PE_SECTION_ALIGNMENT
    section_table_offset = _PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE + _PE_OPTIONAL_HEADER_SIZE
    section_table_size = _PE_SECTION_HEADER_SIZE
    pe_size_of_headers = ((section_table_offset + section_table_size + _PE_FILE_ALIGNMENT - 1) // _PE_FILE_ALIGNMENT) * _PE_FILE_ALIGNMENT
    entry_rva = text_rva + program.entry_offset
    entry_va = image_base + entry_rva
    code_sha256 = hashlib.sha256(program.code).hexdigest()
    symbols = _native_program_symbols(program)
    global_frame_owners = [
        function.name
        for function in program.functions.values()
        if any(
            instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
            for instruction in function.instructions
        )
    ]
    global_frame_owner = global_frame_owners[0] if global_frame_owners else "-"
    lines = [
        "## x64 机器码\n\n",
        f"- 目标平台: `{program.target.value}`\n",
        f"- 入口函数: `{program.entry.name}`\n\n",
        f"- Global-frame owner: `{global_frame_owner}`\n",
        f"- 入口偏移: `{program.entry_offset:04X}`\n",
        f"- 入口 RVA: `0x{entry_rva:08X}`\n",
        f"- 入口 VA: `0x{entry_va:016X}`\n",
        f"- 程序机器码大小: `{code_size}` bytes\n",
        f"- 程序 SHA-256: `{code_sha256}`\n\n",
        "### PE/COFF 过渡摘要\n\n",
        "| Machine | Machine 值 | OptionalHeader | OptionalHeader 值 | Subsystem | Subsystem 值 | Sections | e_lfanew | PE sig offset | COFF offset | Optional offset | Section table | SizeOfHeaders | Image base | BaseOfCode | AddressOfEntryPoint | SizeOfCode | SizeOfImage | Initialized data | Uninitialized data | File alignment | Section alignment |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        f"| `AMD64` | `0x8664` | `PE32+` | `0x020B` | `console` | `3` | `1` | "
        f"`0x{_PE_LFANEW:08X}` | `0x{_PE_LFANEW:08X}` | `0x{_PE_LFANEW + _PE_SIGNATURE_SIZE:08X}` | "
        f"`0x{_PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE:08X}` | `0x{section_table_offset:08X}` | "
        f"`{pe_size_of_headers}` | "
        f"`0x{image_base:016X}` | `0x{text_rva:08X}` | `0x{entry_rva:08X}` | "
        f"`{raw_size_aligned}` | `{text_rva + virtual_size_aligned}` | `0` | `0` | "
        f"`{_PE_FILE_ALIGNMENT}` | `{_PE_SECTION_ALIGNMENT}` |\n\n",
        "### PE 文件布局\n\n",
        "| 段 | Offset | Size | End offset | 说明 |\n",
        "| --- | --- | --- | --- | --- |\n",
        f"| `dos_header` | `0` | `{_PE_DOS_HEADER_SIZE}` | `{_PE_DOS_HEADER_SIZE}` | `MZ header` |\n",
        f"| `dos_stub_padding` | `{_PE_DOS_HEADER_SIZE}` | `{_PE_LFANEW - _PE_DOS_HEADER_SIZE}` | `{_PE_LFANEW}` | `padding before PE signature` |\n",
        f"| `pe_signature` | `{_PE_LFANEW}` | `{_PE_SIGNATURE_SIZE}` | `{_PE_LFANEW + _PE_SIGNATURE_SIZE}` | `PE signature` |\n",
        f"| `coff_header` | `{_PE_LFANEW + _PE_SIGNATURE_SIZE}` | `{_PE_COFF_HEADER_SIZE}` | `{_PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE}` | `IMAGE_FILE_HEADER` |\n",
        f"| `optional_header` | `{_PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE}` | `{_PE_OPTIONAL_HEADER_SIZE}` | `{section_table_offset}` | `IMAGE_OPTIONAL_HEADER64` |\n",
        f"| `section_table` | `{section_table_offset}` | `{section_table_size}` | `{section_table_offset + section_table_size}` | `.text section header` |\n",
        f"| `headers_padding` | `{section_table_offset + section_table_size}` | `{pe_size_of_headers - section_table_offset - section_table_size}` | `{pe_size_of_headers}` | `align headers to FileAlignment` |\n",
        f"| `text_raw` | `{pe_size_of_headers}` | `{raw_size_aligned}` | `{pe_size_of_headers + raw_size_aligned}` | `.text raw data` |\n",
        f"| `file_size` | `0` | `{pe_size_of_headers + raw_size_aligned}` | `{pe_size_of_headers + raw_size_aligned}` | `headers + .text raw` |\n\n",
        "### .text 代码节\n\n",
        "| 名称 | Name bytes | Raw offset | Raw size | End offset | PE raw pointer | PE raw end | Raw aligned | Raw padding | Raw padded SHA-256 | Virtual size | Virtual aligned | Code alignment | RVA | End RVA | VA | End VA | Entry offset | SHA-256 | File alignment | Section alignment | 权限 | Characteristics | PE Characteristics |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        f"| `.text` | `2E 74 65 78 74 00 00 00` | `0` | `{code_size}` | `{code_size}` | "
        f"`{pe_size_of_headers}` | `{pe_size_of_headers + raw_size_aligned}` | `{raw_size_aligned}` | `{raw_padding_size}` | `{raw_padded_sha256}` | `{code_size}` | "
        f"`{virtual_size_aligned}` | `16` | "
        f"`0x{text_rva:08X}` | `0x{text_rva + code_size:08X}` | `0x{image_base + text_rva:016X}` | "
        f"`0x{image_base + text_rva + code_size:016X}` | `{program.entry_offset:04X}` | `{code_sha256}` | "
        f"`{_PE_FILE_ALIGNMENT}` | `{_PE_SECTION_ALIGNMENT}` | `read, execute` | `CNT_CODE, MEM_EXECUTE, MEM_READ` | `0x60000020` |\n\n",
        "### ABI\n\n",
        f"- 名称: `{program.abi.name}`\n",
        f"- ABI 目标: `{program.abi.target.value}`\n",
        f"- Word size: `{program.abi.word_size}` bytes\n",
        f"- 参数寄存器: `{', '.join(program.abi.registers.argument_registers)}`\n",
        f"- 返回寄存器: `{program.abi.registers.return_register}`\n",
        f"- 帧指针 / 栈指针: `{program.abi.registers.frame_pointer}` / `{program.abi.registers.stack_pointer}`\n",
        f"- Shadow space: `{program.abi.shadow_space_size}` bytes\n",
        f"- 栈对齐: `{program.abi.stack_alignment}` bytes\n",
        f"- 支持值类型: `{', '.join(program.abi.supported_value_types)}`\n\n",
        "### 函数符号表\n\n",
        "| 名称 | 类型 | 返回类型 | 形参类型 | 偏移 | End offset | RVA | VA | 大小 | End RVA | End VA | SHA-256 | 入口 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    if symbols:
        for symbol in symbols:
            function = _native_symbol_function(program, symbol)
            symbol_code = function.code
            param_types = ", ".join(symbol.param_types) if symbol.param_types else "-"
            symbol_rva = text_rva + symbol.offset
            symbol_end_rva = symbol_rva + symbol.size
            symbol_va = image_base + symbol_rva
            symbol_end_va = image_base + symbol_end_rva
            lines.append(
                f"| `{symbol.name}` | `{symbol.kind}` | `{symbol.return_type}` | `{param_types}` | "
                f"`{symbol.offset:04X}` | `{symbol.offset + symbol.size:04X}` | "
                f"`0x{symbol_rva:08X}` | `0x{symbol_va:016X}` | `{symbol.size}` | `0x{symbol_end_rva:08X}` | "
                f"`0x{symbol_end_va:016X}` | `{hashlib.sha256(symbol_code).hexdigest()}` | "
                f"`{'yes' if symbol.is_entry else 'no'}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `0000` | `0000` | `0x00000000` | `0x0000000000000000` | `0` | `0x00000000` | `0x0000000000000000` | `-` | `no` |\n")
    lines.append("\n")
    for function in program.functions.values():
        lines.extend(_format_function(function, program.functions))
    return "".join(lines)


def native_code_program_map(program: NativeCodeProgram) -> dict[str, object]:
    """生成 native 机器码结构化 map。"""
    code_size = len(program.code)
    code_sha256 = hashlib.sha256(program.code).hexdigest()
    raw_size_aligned = ((code_size + _PE_FILE_ALIGNMENT - 1) // _PE_FILE_ALIGNMENT) * _PE_FILE_ALIGNMENT
    raw_padding_size = raw_size_aligned - code_size
    raw_padded_sha256 = hashlib.sha256(program.code + bytes(raw_padding_size)).hexdigest()
    virtual_size_aligned = ((code_size + _PE_SECTION_ALIGNMENT - 1) // _PE_SECTION_ALIGNMENT) * _PE_SECTION_ALIGNMENT
    section_table_offset = _PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE + _PE_OPTIONAL_HEADER_SIZE
    section_table_size = _PE_SECTION_HEADER_SIZE
    pe_size_of_headers = ((section_table_offset + section_table_size + _PE_FILE_ALIGNMENT - 1) // _PE_FILE_ALIGNMENT) * _PE_FILE_ALIGNMENT
    text_rva = _PE_TEXT_RVA
    image_base = _PE_IMAGE_BASE
    label_records_by_function = {
        function.name: {
            instruction.asm[:-1]: {
                "name": instruction.asm[:-1],
                "offset": instruction.offset,
                "rva": text_rva + instruction.offset,
                "va": image_base + text_rva + instruction.offset,
                "source_pc": instruction.source_pc,
                "source_line": instruction.source_line,
            }
            for instruction in function.instructions
            if instruction.source_op == "label" and instruction.asm.endswith(":")
        }
        for function in program.functions.values()
    }
    global_frame_owners = [
        function.name
        for function in program.functions.values()
        if any(
            instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
            for instruction in function.instructions
        )
    ]
    return {
        "schema_version": 1,
        "target": program.target.value,
        "pe_machine": "AMD64",
        "pe_machine_value": 0x8664,
        "pe_coff_header": {
            "Machine": 0x8664,
            "NumberOfSections": 1,
            "TimeDateStamp": 0,
            "PointerToSymbolTable": 0,
            "NumberOfSymbols": 0,
            "SizeOfOptionalHeader": _PE_OPTIONAL_HEADER_SIZE,
            "Characteristics": 0x22,
        },
        "pe_optional_header_magic": "PE32+",
        "pe_optional_header_magic_value": 0x20B,
        "pe_optional_header": {
            "Magic": 0x20B,
            "SizeOfCode": raw_size_aligned,
            "SizeOfInitializedData": 0,
            "SizeOfUninitializedData": 0,
            "AddressOfEntryPoint": text_rva + program.entry_offset,
            "BaseOfCode": text_rva,
            "ImageBase": image_base,
            "SectionAlignment": _PE_SECTION_ALIGNMENT,
            "FileAlignment": _PE_FILE_ALIGNMENT,
            "SizeOfImage": text_rva + virtual_size_aligned,
            "SizeOfHeaders": pe_size_of_headers,
            "Subsystem": 3,
            "NumberOfRvaAndSizes": 16,
        },
        "pe_subsystem": "console",
        "pe_subsystem_value": 3,
        "pe_number_of_sections": 1,
        "pe_dos_header_size": _PE_DOS_HEADER_SIZE,
        "pe_lfanew": _PE_LFANEW,
        "pe_signature_offset": _PE_LFANEW,
        "pe_signature_size": _PE_SIGNATURE_SIZE,
        "pe_coff_header_offset": _PE_LFANEW + _PE_SIGNATURE_SIZE,
        "pe_coff_header_size": _PE_COFF_HEADER_SIZE,
        "pe_optional_header_offset": _PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE,
        "pe_optional_header_size": _PE_OPTIONAL_HEADER_SIZE,
        "pe_section_table_offset": section_table_offset,
        "pe_section_header_size": _PE_SECTION_HEADER_SIZE,
        "pe_section_table_size": section_table_size,
        "pe_size_of_headers": pe_size_of_headers,
        "pe_file_layout": {
            "dos_header": {
                "offset": 0,
                "size": _PE_DOS_HEADER_SIZE,
                "end_offset": _PE_DOS_HEADER_SIZE,
            },
            "dos_stub_padding": {
                "offset": _PE_DOS_HEADER_SIZE,
                "size": _PE_LFANEW - _PE_DOS_HEADER_SIZE,
                "end_offset": _PE_LFANEW,
            },
            "pe_signature": {
                "offset": _PE_LFANEW,
                "size": _PE_SIGNATURE_SIZE,
                "end_offset": _PE_LFANEW + _PE_SIGNATURE_SIZE,
            },
            "coff_header": {
                "offset": _PE_LFANEW + _PE_SIGNATURE_SIZE,
                "size": _PE_COFF_HEADER_SIZE,
                "end_offset": _PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE,
            },
            "optional_header": {
                "offset": _PE_LFANEW + _PE_SIGNATURE_SIZE + _PE_COFF_HEADER_SIZE,
                "size": _PE_OPTIONAL_HEADER_SIZE,
                "end_offset": section_table_offset,
            },
            "section_table": {
                "offset": section_table_offset,
                "size": section_table_size,
                "end_offset": section_table_offset + section_table_size,
            },
            "headers_padding": {
                "offset": section_table_offset + section_table_size,
                "size": pe_size_of_headers - section_table_offset - section_table_size,
                "end_offset": pe_size_of_headers,
            },
            "text_raw": {
                "offset": pe_size_of_headers,
                "size": raw_size_aligned,
                "end_offset": pe_size_of_headers + raw_size_aligned,
            },
            "file_size": pe_size_of_headers + raw_size_aligned,
        },
        "pe_base_of_code": text_rva,
        "pe_address_of_entry_point": text_rva + program.entry_offset,
        "pe_size_of_code": raw_size_aligned,
        "pe_size_of_initialized_data": 0,
        "pe_size_of_uninitialized_data": 0,
        "pe_size_of_image": text_rva + virtual_size_aligned,
        "pe_file_alignment": 512,
        "pe_section_alignment": 4096,
        "image_base": image_base,
        "abi": {
            "name": program.abi.name,
            "target": program.abi.target.value,
            "word_size": program.abi.word_size,
            "stack_alignment": program.abi.stack_alignment,
            "shadow_space_size": program.abi.shadow_space_size,
            "argument_registers": list(program.abi.registers.argument_registers),
            "return_register": program.abi.registers.return_register,
            "frame_pointer": program.abi.registers.frame_pointer,
            "stack_pointer": program.abi.registers.stack_pointer,
            "supported_value_types": list(program.abi.supported_value_types),
        },
        "entry": program.entry.name,
        "entry_offset": program.entry_offset,
        "entry_rva": text_rva + program.entry_offset,
        "entry_va": image_base + text_rva + program.entry_offset,
        "global_frame_owner": global_frame_owners[0] if global_frame_owners else None,
        "code_size": code_size,
        "code_sha256": code_sha256,
        "sections": [
            {
                "name": ".text",
                "name_bytes": "2E 74 65 78 74 00 00 00",
                "offset": 0,
                "size": code_size,
                "end_offset": code_size,
                "virtual_size": code_size,
                "raw_size_aligned": raw_size_aligned,
                "raw_padding_size": raw_padding_size,
                "raw_padded_sha256": raw_padded_sha256,
                "virtual_size_aligned": virtual_size_aligned,
                "rva": text_rva,
                "end_rva": text_rva + code_size,
                "va": image_base + text_rva,
                "end_va": image_base + text_rva + code_size,
                "entry_offset": program.entry_offset,
                "pe_raw_pointer": pe_size_of_headers,
                "pe_raw_end_pointer": pe_size_of_headers + raw_size_aligned,
                "pe_section_header": {
                    "Name": ".text",
                    "NameBytes": "2E 74 65 78 74 00 00 00",
                    "VirtualSize": code_size,
                    "VirtualAddress": text_rva,
                    "SizeOfRawData": raw_size_aligned,
                    "PointerToRawData": pe_size_of_headers,
                    "PointerToRelocations": 0,
                    "PointerToLinenumbers": 0,
                    "NumberOfRelocations": 0,
                    "NumberOfLinenumbers": 0,
                    "Characteristics": 0x60000020,
                },
                "sha256": code_sha256,
                "alignment": 16,
                "file_alignment": _PE_FILE_ALIGNMENT,
                "section_alignment": _PE_SECTION_ALIGNMENT,
                "permissions": ["read", "execute"],
                "characteristics": ["CNT_CODE", "MEM_EXECUTE", "MEM_READ"],
                "pe_characteristics": 0x60000020,
            }
        ],
        "symbols": [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "offset": symbol.offset,
                "rva": text_rva + symbol.offset,
                "va": image_base + text_rva + symbol.offset,
                "size": symbol.size,
                "end_offset": symbol.offset + symbol.size,
                "end_rva": text_rva + symbol.offset + symbol.size,
                "end_va": image_base + text_rva + symbol.offset + symbol.size,
                "code_sha256": hashlib.sha256(_native_symbol_function(program, symbol).code).hexdigest(),
                "is_entry": symbol.is_entry,
                "return_type": symbol.return_type,
                "param_types": list(symbol.param_types),
            }
            for symbol in _native_program_symbols(program)
        ],
        "functions": [
            {
                "name": function.name,
                "offset": function.offset,
                "rva": text_rva + function.offset,
                "va": image_base + text_rva + function.offset,
                "size": len(function.code),
                "end_offset": function.offset + len(function.code),
                "end_rva": text_rva + function.offset + len(function.code),
                "end_va": image_base + text_rva + function.offset + len(function.code),
                "code_sha256": hashlib.sha256(function.code).hexdigest(),
                "frame_size": function.frame_size,
                "return_type": function.return_type,
                "param_types": list(function.param_types),
                "register_allocation": {
                    "strategy": function.register_allocation.strategy,
                    "temporary_registers": list(function.register_allocation.temporary_registers),
                    "argument_registers": list(function.register_allocation.argument_registers),
                    "return_register": function.register_allocation.return_register,
                    "frame_pointer": function.register_allocation.frame_pointer,
                    "stack_pointer": function.register_allocation.stack_pointer,
                    "virtual_register_storage": function.register_allocation.virtual_register_storage,
                    "local_storage": function.register_allocation.local_storage,
                    "global_frame_register": function.register_allocation.global_frame_register,
                    "global_frame_role": function.register_allocation.global_frame_role,
                },
                "stack_slots": [
                    {"name": slot.name, "offset": slot.offset, "size": slot.size}
                    for slot in function.stack_slots
                ],
                "value_locations": [
                    _native_value_location(function.name, slot)
                    for slot in function.stack_slots
                ],
                "labels": [
                    dict(label_record)
                    for label_record in label_records_by_function[function.name].values()
                ],
                "call_frames": [
                    {
                        "offset": frame.offset,
                        "end_offset": frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size)),
                        "sub_code_sha256": hashlib.sha256(
                            program.code[frame.offset:frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size))]
                        ).hexdigest(),
                        "rva": text_rva + frame.offset,
                        "end_rva": text_rva + frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size)),
                        "va": image_base + text_rva + frame.offset,
                        "end_va": image_base + text_rva + frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size)),
                        "call_offset": frame.call_offset,
                        "call_end_offset": frame.call_end_offset,
                        "call_code_sha256": (
                            hashlib.sha256(program.code[frame.call_offset:frame.call_end_offset]).hexdigest()
                            if frame.call_offset is not None and frame.call_end_offset is not None
                            else None
                        ),
                        "call_rva": text_rva + frame.call_offset if frame.call_offset is not None else None,
                        "call_end_rva": text_rva + frame.call_end_offset if frame.call_end_offset is not None else None,
                        "call_va": image_base + text_rva + frame.call_offset if frame.call_offset is not None else None,
                        "call_end_va": image_base + text_rva + frame.call_end_offset if frame.call_end_offset is not None else None,
                        "add_offset": frame.add_offset,
                        "add_end_offset": frame.add_end_offset,
                        "add_code_sha256": (
                            hashlib.sha256(program.code[frame.add_offset:frame.add_end_offset]).hexdigest()
                            if frame.add_offset is not None and frame.add_end_offset is not None
                            else None
                        ),
                        "add_rva": text_rva + frame.add_offset if frame.add_offset is not None else None,
                        "add_end_rva": text_rva + frame.add_end_offset if frame.add_end_offset is not None else None,
                        "add_va": image_base + text_rva + frame.add_offset if frame.add_offset is not None else None,
                        "add_end_va": image_base + text_rva + frame.add_end_offset if frame.add_end_offset is not None else None,
                        "target": frame.target,
                        "arg_count": frame.arg_count,
                        "arg_types": list(frame.arg_types),
                        "param_types": list(frame.param_types),
                        "register_arg_count": frame.register_arg_count,
                        "stack_arg_count": frame.stack_arg_count,
                        "shadow_space_size": frame.shadow_space_size,
                        "stack_arg_bytes": frame.stack_arg_bytes,
                        "aligned_size": frame.aligned_size,
                        "stack_alignment": frame.stack_alignment,
                        "source_pc": frame.source_pc,
                        "source_line": frame.source_line,
                    }
                    for frame in function.call_frames
                ],
                "relocations": [
                    {
                        "offset": relocation.offset,
                        "rva": text_rva + relocation.offset,
                        "va": image_base + text_rva + relocation.offset,
                        "patch_offset": relocation.patch_offset,
                        "patch_rva": text_rva + relocation.patch_offset,
                        "patch_va": image_base + text_rva + relocation.patch_offset,
                        "patch_end_offset": relocation.patch_offset + relocation.size,
                        "patch_end_rva": text_rva + relocation.patch_offset + relocation.size,
                        "patch_end_va": image_base + text_rva + relocation.patch_offset + relocation.size,
                        "instruction_code_sha256": hashlib.sha256(
                            program.code[relocation.offset:relocation.patch_offset + relocation.size]
                        ).hexdigest(),
                        "patch_code_sha256": hashlib.sha256(
                            program.code[relocation.patch_offset:relocation.patch_offset + relocation.size]
                        ).hexdigest(),
                        "kind": relocation.kind,
                        "target": relocation.target,
                        "target_rva": text_rva + (
                            program.functions[relocation.target].offset
                            if relocation.target in program.functions
                            else label_records_by_function[function.name][relocation.target]["offset"]
                        ),
                        "target_va": image_base + text_rva + (
                            program.functions[relocation.target].offset
                            if relocation.target in program.functions
                            else label_records_by_function[function.name][relocation.target]["offset"]
                        ),
                        "displacement": relocation.displacement,
                        "size": relocation.size,
                        "source_pc": relocation.source_pc,
                        "source_line": relocation.source_line,
                    }
                    for relocation in function.relocations
                ],
                "exit_probes": [
                    {
                        "call_offset": probe.call_offset,
                        "call_end_offset": probe.call_offset + _CALL_REL32_SIZE,
                        "call_code_sha256": hashlib.sha256(
                            program.code[probe.call_offset:probe.call_offset + _CALL_REL32_SIZE]
                        ).hexdigest(),
                        "call_rva": text_rva + probe.call_offset,
                        "call_end_rva": text_rva + probe.call_offset + _CALL_REL32_SIZE,
                        "call_va": image_base + text_rva + probe.call_offset,
                        "call_end_va": image_base + text_rva + probe.call_offset + _CALL_REL32_SIZE,
                        "test_offset": probe.test_offset,
                        "test_end_offset": probe.test_offset + _TEST_RDX_RDX_SIZE,
                        "test_code_sha256": hashlib.sha256(
                            program.code[probe.test_offset:probe.test_offset + _TEST_RDX_RDX_SIZE]
                        ).hexdigest(),
                        "test_rva": text_rva + probe.test_offset,
                        "test_end_rva": text_rva + probe.test_offset + _TEST_RDX_RDX_SIZE,
                        "test_va": image_base + text_rva + probe.test_offset,
                        "test_end_va": image_base + text_rva + probe.test_offset + _TEST_RDX_RDX_SIZE,
                        "jump_offset": probe.jump_offset,
                        "jump_end_offset": probe.jump_offset + _JNE_REL32_SIZE,
                        "jump_code_sha256": hashlib.sha256(
                            program.code[probe.jump_offset:probe.jump_offset + _JNE_REL32_SIZE]
                        ).hexdigest(),
                        "jump_rva": text_rva + probe.jump_offset,
                        "jump_end_rva": text_rva + probe.jump_offset + _JNE_REL32_SIZE,
                        "jump_va": image_base + text_rva + probe.jump_offset,
                        "jump_end_va": image_base + text_rva + probe.jump_offset + _JNE_REL32_SIZE,
                        "target": probe.target,
                        "probe_label": probe.probe_label,
                        "source_pc": probe.source_pc,
                        "source_line": probe.source_line,
                    }
                    for probe in function.exit_probes
                ],
                "instructions": [
                    {
                        "offset": instruction.offset,
                        "rva": text_rva + instruction.offset,
                        "va": image_base + text_rva + instruction.offset,
                        "size": len(instruction.code),
                        "end_offset": instruction.offset + len(instruction.code),
                        "end_rva": text_rva + instruction.offset + len(instruction.code),
                        "end_va": image_base + text_rva + instruction.offset + len(instruction.code),
                        "bytes": instruction.code.hex(" ").upper(),
                        "code_sha256": hashlib.sha256(instruction.code).hexdigest(),
                        "asm": instruction.asm,
                        "source_op": instruction.source_op,
                        "source_attrs": dict(instruction.source_attrs),
                        "source_pc": instruction.source_pc,
                        "source_line": instruction.source_line,
                    }
                    for instruction in function.instructions
                ],
            }
            for function in program.functions.values()
        ],
    }


def validate_native_code_program_map(program: NativeCodeProgram, metadata: dict[str, object]) -> None:
    """校验 native 机器码结构化 map 与程序一致。"""
    if not isinstance(metadata, dict):
        raise NativeCodegenError(f"native 机器码 map 必须是对象，实际 {type(metadata).__name__}")
    expected = native_code_program_map(program)
    validate_native_code_map_bytes(program.code, metadata)
    for key in (
        "schema_version",
        "target",
        "pe_machine",
        "pe_machine_value",
        "pe_optional_header_magic",
        "pe_optional_header_magic_value",
        "pe_subsystem",
        "pe_subsystem_value",
        "pe_number_of_sections",
        "pe_base_of_code",
        "pe_address_of_entry_point",
        "pe_size_of_code",
        "pe_size_of_initialized_data",
        "pe_size_of_uninitialized_data",
        "pe_size_of_image",
        "pe_file_alignment",
        "pe_section_alignment",
        "image_base",
        "abi",
        "entry",
        "entry_offset",
        "entry_rva",
        "entry_va",
        "global_frame_owner",
        "code_size",
        "code_sha256",
    ):
        if metadata.get(key) != expected[key]:
            raise NativeCodegenError(
                f"native 机器码 map 字段 {key} 不一致: 期望 {expected[key]!r}, 实际 {metadata.get(key)!r}"
            )
    for key in ("sections", "symbols", "functions"):
        if metadata.get(key) != expected[key]:
            detail = _describe_map_list_mismatch(key, expected[key], metadata.get(key))
            raise NativeCodegenError(f"native 机器码 map 字段 {key} 不一致: {detail}")


def _describe_map_list_mismatch(key: str, expected: object, actual: object) -> str:
    """描述结构化 map 列表字段的首个差异。"""
    return _describe_map_value_mismatch(key, expected, actual)


def _describe_map_value_mismatch(path: str, expected: object, actual: object) -> str:
    """递归描述结构化 map 字段的首个差异。"""
    if not isinstance(expected, list) or not isinstance(actual, list):
        if isinstance(expected, list) != isinstance(actual, list):
            return f"期望 {type(expected).__name__}, 实际 {type(actual).__name__}"
        if isinstance(expected, dict) and isinstance(actual, dict):
            expected_keys = set(expected)
            actual_keys = set(actual)
            if expected_keys != actual_keys:
                missing = sorted(expected_keys - actual_keys)
                extra = sorted(actual_keys - expected_keys)
                parts = []
                if missing:
                    parts.append(f"缺少字段 {', '.join(missing)}")
                if extra:
                    parts.append(f"多余字段 {', '.join(extra)}")
                return f"{path} " + "，".join(parts)
            for field in expected:
                if expected[field] != actual[field]:
                    return _describe_map_value_mismatch(f"{path} 字段 {field}", expected[field], actual[field])
            return f"{path} 内容不一致"
        if expected != actual:
            return f"{path} 不一致: 期望 {expected!r}, 实际 {actual!r}"
        return f"期望 {type(expected).__name__}, 实际 {type(actual).__name__}"
    if len(expected) != len(actual):
        return f"长度不一致: 期望 {len(expected)}, 实际 {len(actual)}"
    for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
        name = _map_item_name(expected_item, index)
        if expected_item == actual_item:
            continue
        return _describe_map_value_mismatch(f"{path}[{index}] {name}", expected_item, actual_item)
    return "内容不一致"


def _map_item_name(item: object, index: int) -> str:
    """取得 map 列表项的可读名称。"""
    if isinstance(item, dict) and isinstance(item.get("name"), str):
        return f"`{item['name']}`"
    return f"#{index}"


def _native_value_location(function_name: str, slot: NativeStackSlotAllocation) -> dict[str, object]:
    """把栈槽转换为保守寄存器分配的值位置记录。"""
    if slot.name.startswith("%v"):
        kind = "vreg"
        index: object = slot.name[2:]
    elif slot.name.startswith("local[") and slot.name.endswith("]"):
        kind = "local"
        index = slot.name[6:-1]
    elif slot.name.startswith("global[") and slot.name.endswith("]"):
        kind = "global"
        index = slot.name[7:-1]
    else:
        kind = "stack"
        index = slot.name
    base_register = "R11" if function_name != "<module>" and kind == "global" else "RBP"
    return {
        "name": slot.name,
        "kind": kind,
        "index": index,
        "storage": "stack",
        "base_register": base_register,
        "offset": slot.offset,
        "size": slot.size,
    }


def validate_native_code_map_bytes(code: bytes, metadata: dict[str, object]) -> None:
    """校验 raw native 机器码字节与 map 摘要一致。"""
    if not isinstance(code, bytes):
        raise NativeCodegenError(f"native 机器码 raw bytes 必须是 bytes，实际 {type(code).__name__}")
    if not isinstance(metadata, dict):
        raise NativeCodegenError(f"native 机器码 map 必须是对象，实际 {type(metadata).__name__}")
    extra_top_level_fields = sorted(set(metadata) - _MAP_TOP_LEVEL_FIELDS)
    if extra_top_level_fields:
        raise NativeCodegenError(f"native 机器码 map 存在未知顶层字段: {', '.join(extra_top_level_fields)}")
    schema_version = metadata.get("schema_version")
    if schema_version != 1:
        raise NativeCodegenError(f"native 机器码 map 字段 schema_version 必须为 1，实际 {schema_version!r}")
    target = metadata.get("target")
    if target != NativeTarget.WINDOWS_X64.value:
        raise NativeCodegenError(f"native 机器码 map 字段 target 必须为 {NativeTarget.WINDOWS_X64.value!r}，实际 {target!r}")
    abi = metadata.get("abi")
    if not isinstance(abi, dict):
        raise NativeCodegenError(f"native 机器码 map 字段 abi 必须是对象，实际 {type(abi).__name__}")
    extra_abi_fields = sorted(set(abi) - _MAP_ABI_FIELDS)
    if extra_abi_fields:
        raise NativeCodegenError(f"native 机器码 map abi 存在未知字段: {', '.join(extra_abi_fields)}")
    abi_name = abi.get("name")
    if not isinstance(abi_name, str) or not abi_name:
        raise NativeCodegenError("native 机器码 map abi.name 必须是非空字符串")
    if abi.get("target") != target:
        raise NativeCodegenError(f"native 机器码 map abi.target 与 target 不一致: abi {abi.get('target')!r}, target {target!r}")
    abi_word_size = abi.get("word_size")
    if not isinstance(abi_word_size, int) or isinstance(abi_word_size, bool):
        raise NativeCodegenError(f"native 机器码 map abi.word_size 必须是整数，实际 {type(abi_word_size).__name__}")
    if abi_word_size != 8:
        raise NativeCodegenError(f"native 机器码 map abi.word_size 必须为 8，实际 {abi_word_size}")
    abi_stack_alignment = abi.get("stack_alignment")
    if not isinstance(abi_stack_alignment, int) or isinstance(abi_stack_alignment, bool):
        raise NativeCodegenError(f"native 机器码 map abi.stack_alignment 必须是整数，实际 {type(abi_stack_alignment).__name__}")
    if abi_stack_alignment <= 0:
        raise NativeCodegenError(f"native 机器码 map abi.stack_alignment 必须为正数，实际 {abi_stack_alignment}")
    abi_shadow_space = abi.get("shadow_space_size")
    if not isinstance(abi_shadow_space, int) or isinstance(abi_shadow_space, bool):
        raise NativeCodegenError(f"native 机器码 map abi.shadow_space_size 必须是整数，实际 {type(abi_shadow_space).__name__}")
    if abi_shadow_space < 0:
        raise NativeCodegenError(f"native 机器码 map abi.shadow_space_size 不能为负数，实际 {abi_shadow_space}")
    argument_registers = abi.get("argument_registers")
    if not isinstance(argument_registers, list):
        raise NativeCodegenError(f"native 机器码 map abi.argument_registers 必须是列表，实际 {type(argument_registers).__name__}")
    seen_argument_registers = set()
    for index, register in enumerate(argument_registers):
        if not isinstance(register, str) or not register:
            raise NativeCodegenError(f"native 机器码 map abi.argument_registers[{index}] 必须是非空字符串")
        register_name = register.upper()
        if register_name in seen_argument_registers:
            raise NativeCodegenError(f"native 机器码 map abi.argument_registers 重复: {register}")
        seen_argument_registers.add(register_name)
        if register_name not in _SUPPORTED_ARGUMENT_REGISTERS:
            raise NativeCodegenError(f"native 机器码 map abi.argument_registers 暂不支持 {register}")
    if abi.get("return_register") != "RAX":
        raise NativeCodegenError(f"native 机器码 map abi.return_register 必须为 'RAX'，实际 {abi.get('return_register')!r}")
    if abi.get("frame_pointer") != "RBP":
        raise NativeCodegenError(f"native 机器码 map abi.frame_pointer 必须为 'RBP'，实际 {abi.get('frame_pointer')!r}")
    if abi.get("stack_pointer") != "RSP":
        raise NativeCodegenError(f"native 机器码 map abi.stack_pointer 必须为 'RSP'，实际 {abi.get('stack_pointer')!r}")
    supported_value_types = abi.get("supported_value_types")
    if not isinstance(supported_value_types, list) or any(not isinstance(item, str) for item in supported_value_types):
        raise NativeCodegenError("native 机器码 map abi.supported_value_types 必须是字符串列表")
    if set(supported_value_types) != _SUPPORTED_RETURN_TYPES:
        raise NativeCodegenError(
            f"native 机器码 map abi.supported_value_types 必须为 {_SUPPORTED_RETURN_TYPES}，实际 {supported_value_types!r}"
        )
    pe_machine = metadata.get("pe_machine")
    if pe_machine != "AMD64":
        raise NativeCodegenError(f"native 机器码 map 字段 pe_machine 必须为 'AMD64'，实际 {pe_machine!r}")
    pe_machine_value = metadata.get("pe_machine_value")
    if pe_machine_value != 0x8664:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_machine_value 必须为 0x8664，实际 {pe_machine_value!r}")
    pe_coff_header = metadata.get("pe_coff_header")
    if not isinstance(pe_coff_header, dict):
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header 必须是对象")
    extra_pe_coff_header_fields = sorted(set(pe_coff_header) - _MAP_PE_COFF_HEADER_FIELDS)
    if extra_pe_coff_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_coff_header 存在未知字段: "
            f"{', '.join(extra_pe_coff_header_fields)}"
        )
    missing_pe_coff_header_fields = sorted(_MAP_PE_COFF_HEADER_FIELDS - set(pe_coff_header))
    if missing_pe_coff_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_coff_header 缺少字段: "
            f"{', '.join(missing_pe_coff_header_fields)}"
        )
    for field in _MAP_PE_COFF_HEADER_FIELDS:
        value = pe_coff_header.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map 字段 pe_coff_header.{field} 必须是整数")
    if pe_coff_header["Machine"] != pe_machine_value:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header.Machine 与 pe_machine_value 不一致: "
            f"期望 {pe_machine_value}, 实际 {pe_coff_header['Machine']}"
        )
    pe_magic = metadata.get("pe_optional_header_magic")
    if pe_magic != "PE32+":
        raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header_magic 必须为 'PE32+'，实际 {pe_magic!r}")
    pe_magic_value = metadata.get("pe_optional_header_magic_value")
    if pe_magic_value != 0x20B:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header_magic_value 必须为 0x020B，实际 {pe_magic_value!r}")
    pe_optional_header = metadata.get("pe_optional_header")
    if not isinstance(pe_optional_header, dict):
        raise NativeCodegenError("native 机器码 map 字段 pe_optional_header 必须是对象")
    extra_pe_optional_header_fields = sorted(set(pe_optional_header) - _MAP_PE_OPTIONAL_HEADER_FIELDS)
    if extra_pe_optional_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header 存在未知字段: "
            f"{', '.join(extra_pe_optional_header_fields)}"
        )
    missing_pe_optional_header_fields = sorted(_MAP_PE_OPTIONAL_HEADER_FIELDS - set(pe_optional_header))
    if missing_pe_optional_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header 缺少字段: "
            f"{', '.join(missing_pe_optional_header_fields)}"
        )
    for field in _MAP_PE_OPTIONAL_HEADER_FIELDS:
        value = pe_optional_header.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header.{field} 必须是整数")
    if pe_optional_header["Magic"] != pe_magic_value:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.Magic 与 pe_optional_header_magic_value 不一致: "
            f"期望 {pe_magic_value}, 实际 {pe_optional_header['Magic']}"
        )
    pe_subsystem = metadata.get("pe_subsystem")
    if pe_subsystem != "console":
        raise NativeCodegenError(f"native 机器码 map 字段 pe_subsystem 必须为 'console'，实际 {pe_subsystem!r}")
    pe_subsystem_value = metadata.get("pe_subsystem_value")
    if pe_subsystem_value != 3:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_subsystem_value 必须为 3，实际 {pe_subsystem_value!r}")
    if pe_optional_header["Subsystem"] != pe_subsystem_value:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.Subsystem 与 pe_subsystem_value 不一致: "
            f"期望 {pe_subsystem_value}, 实际 {pe_optional_header['Subsystem']}"
        )
    if pe_optional_header["NumberOfRvaAndSizes"] != 16:
        raise NativeCodegenError("native 机器码 map 字段 pe_optional_header.NumberOfRvaAndSizes 必须为 16")
    pe_number_of_sections = metadata.get("pe_number_of_sections")
    if pe_number_of_sections != 1:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_number_of_sections 必须为 1，实际 {pe_number_of_sections!r}")
    if pe_coff_header["NumberOfSections"] != pe_number_of_sections:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header.NumberOfSections 与 pe_number_of_sections 不一致: "
            f"期望 {pe_number_of_sections}, 实际 {pe_coff_header['NumberOfSections']}"
        )
    if pe_coff_header["TimeDateStamp"] != 0:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.TimeDateStamp 必须为 0")
    if pe_coff_header["PointerToSymbolTable"] != 0:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.PointerToSymbolTable 必须为 0")
    if pe_coff_header["NumberOfSymbols"] != 0:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.NumberOfSymbols 必须为 0")
    if pe_coff_header["SizeOfOptionalHeader"] != _PE_OPTIONAL_HEADER_SIZE:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header.SizeOfOptionalHeader 必须为 {_PE_OPTIONAL_HEADER_SIZE}"
        )
    if pe_coff_header["Characteristics"] != 0x22:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.Characteristics 必须为 0x0022")
    for field in (
        "pe_dos_header_size",
        "pe_lfanew",
        "pe_signature_offset",
        "pe_signature_size",
        "pe_coff_header_offset",
        "pe_coff_header_size",
        "pe_optional_header_offset",
        "pe_optional_header_size",
        "pe_section_table_offset",
        "pe_section_header_size",
        "pe_section_table_size",
        "pe_size_of_headers",
    ):
        value = metadata.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map 字段 {field} 必须是整数，实际 {type(value).__name__}")
    if metadata["pe_dos_header_size"] != _PE_DOS_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_dos_header_size 必须为 {_PE_DOS_HEADER_SIZE}")
    if metadata["pe_lfanew"] != _PE_LFANEW:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_lfanew 必须为 0x{_PE_LFANEW:08X}")
    if metadata["pe_signature_offset"] != metadata["pe_lfanew"]:
        raise NativeCodegenError("native 机器码 map 字段 pe_signature_offset 必须等于 pe_lfanew")
    if metadata["pe_signature_size"] != _PE_SIGNATURE_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_signature_size 必须为 {_PE_SIGNATURE_SIZE}")
    expected_coff_offset = metadata["pe_signature_offset"] + metadata["pe_signature_size"]
    if metadata["pe_coff_header_offset"] != expected_coff_offset:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header_offset 不一致: 期望 {expected_coff_offset}, 实际 {metadata['pe_coff_header_offset']}"
        )
    if metadata["pe_coff_header_size"] != _PE_COFF_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_coff_header_size 必须为 {_PE_COFF_HEADER_SIZE}")
    expected_optional_offset = metadata["pe_coff_header_offset"] + metadata["pe_coff_header_size"]
    if metadata["pe_optional_header_offset"] != expected_optional_offset:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header_offset 不一致: 期望 {expected_optional_offset}, 实际 {metadata['pe_optional_header_offset']}"
        )
    if metadata["pe_optional_header_size"] != _PE_OPTIONAL_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header_size 必须为 {_PE_OPTIONAL_HEADER_SIZE}")
    expected_section_table_offset = metadata["pe_optional_header_offset"] + metadata["pe_optional_header_size"]
    if metadata["pe_section_table_offset"] != expected_section_table_offset:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_section_table_offset 不一致: 期望 {expected_section_table_offset}, 实际 {metadata['pe_section_table_offset']}"
        )
    if metadata["pe_section_header_size"] != _PE_SECTION_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_section_header_size 必须为 {_PE_SECTION_HEADER_SIZE}")
    expected_section_table_size = pe_number_of_sections * metadata["pe_section_header_size"]
    if metadata["pe_section_table_size"] != expected_section_table_size:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_section_table_size 不一致: 期望 {expected_section_table_size}, 实际 {metadata['pe_section_table_size']}"
        )
    pe_file_alignment = metadata.get("pe_file_alignment")
    if pe_file_alignment != _PE_FILE_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_file_alignment 必须为 {_PE_FILE_ALIGNMENT}，实际 {pe_file_alignment!r}")
    if pe_optional_header["FileAlignment"] != pe_file_alignment:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.FileAlignment 与 pe_file_alignment 不一致: "
            f"期望 {pe_file_alignment}, 实际 {pe_optional_header['FileAlignment']}"
        )
    pe_section_alignment = metadata.get("pe_section_alignment")
    if pe_section_alignment != _PE_SECTION_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_section_alignment 必须为 {_PE_SECTION_ALIGNMENT}，实际 {pe_section_alignment!r}")
    if pe_optional_header["SectionAlignment"] != pe_section_alignment:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SectionAlignment 与 pe_section_alignment 不一致: "
            f"期望 {pe_section_alignment}, 实际 {pe_optional_header['SectionAlignment']}"
        )
    expected_size_of_headers = (
        (metadata["pe_section_table_offset"] + metadata["pe_section_table_size"] + pe_file_alignment - 1)
        // pe_file_alignment
    ) * pe_file_alignment
    if metadata["pe_size_of_headers"] != expected_size_of_headers:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_headers 不一致: 期望 {expected_size_of_headers}, 实际 {metadata['pe_size_of_headers']}"
        )
    if pe_optional_header["SizeOfHeaders"] != metadata["pe_size_of_headers"]:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SizeOfHeaders 与 pe_size_of_headers 不一致: "
            f"期望 {metadata['pe_size_of_headers']}, 实际 {pe_optional_header['SizeOfHeaders']}"
        )
    pe_file_layout = metadata.get("pe_file_layout")
    if not isinstance(pe_file_layout, dict):
        raise NativeCodegenError("native 机器码 map 字段 pe_file_layout 必须是对象")
    extra_pe_file_layout_fields = sorted(set(pe_file_layout) - _MAP_PE_FILE_LAYOUT_FIELDS)
    if extra_pe_file_layout_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_file_layout 存在未知字段: "
            f"{', '.join(extra_pe_file_layout_fields)}"
        )
    missing_pe_file_layout_fields = sorted(_MAP_PE_FILE_LAYOUT_FIELDS - set(pe_file_layout))
    if missing_pe_file_layout_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_file_layout 缺少字段: "
            f"{', '.join(missing_pe_file_layout_fields)}"
        )
    for range_name in (
        "dos_header",
        "dos_stub_padding",
        "pe_signature",
        "coff_header",
        "optional_header",
        "section_table",
        "headers_padding",
        "text_raw",
    ):
        range_item = pe_file_layout.get(range_name)
        if not isinstance(range_item, dict):
            raise NativeCodegenError(f"native 机器码 map 字段 pe_file_layout.{range_name} 必须是对象")
        extra_range_fields = sorted(set(range_item) - _MAP_PE_FILE_LAYOUT_RANGE_FIELDS)
        if extra_range_fields:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name} 存在未知字段: "
                f"{', '.join(extra_range_fields)}"
            )
        missing_range_fields = sorted(_MAP_PE_FILE_LAYOUT_RANGE_FIELDS - set(range_item))
        if missing_range_fields:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name} 缺少字段: "
                f"{', '.join(missing_range_fields)}"
            )
        for field in _MAP_PE_FILE_LAYOUT_RANGE_FIELDS:
            value = range_item.get(field)
            if not isinstance(value, int) or isinstance(value, bool):
                raise NativeCodegenError(f"native 机器码 map 字段 pe_file_layout.{range_name}.{field} 必须是整数")
        if range_item["size"] < 0:
            raise NativeCodegenError(f"native 机器码 map 字段 pe_file_layout.{range_name}.size 必须是非负整数")
        expected_range_end = range_item["offset"] + range_item["size"]
        if range_item["end_offset"] != expected_range_end:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.end_offset 不一致: "
                f"期望 {expected_range_end}, 实际 {range_item['end_offset']}"
            )
    if not isinstance(pe_file_layout["file_size"], int) or isinstance(pe_file_layout["file_size"], bool):
        raise NativeCodegenError("native 机器码 map 字段 pe_file_layout.file_size 必须是整数")
    image_base = metadata.get("image_base")
    if not isinstance(image_base, int) or isinstance(image_base, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 image_base 必须是整数，实际 {type(image_base).__name__}")
    if image_base < 0:
        raise NativeCodegenError(f"native 机器码 map 字段 image_base 必须是非负整数，实际 {image_base}")
    if pe_optional_header["ImageBase"] != image_base:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.ImageBase 与 image_base 不一致: "
            f"期望 {image_base}, 实际 {pe_optional_header['ImageBase']}"
        )
    actual_size = len(code)
    code_size = metadata.get("code_size")
    if not isinstance(code_size, int) or isinstance(code_size, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 code_size 必须是整数，实际 {type(code_size).__name__}")
    if code_size < 0:
        raise NativeCodegenError(f"native 机器码 map 字段 code_size 必须是非负整数，实际 {code_size}")
    if code_size != actual_size:
        raise NativeCodegenError(
            f"native 机器码 map 字段 code_size 不一致: 期望 {actual_size!r}, 实际 {code_size!r}"
        )
    actual_hash = hashlib.sha256(code).hexdigest()
    code_sha256 = metadata.get("code_sha256")
    if not isinstance(code_sha256, str):
        raise NativeCodegenError(f"native 机器码 map 字段 code_sha256 必须是字符串，实际 {type(code_sha256).__name__}")
    if len(code_sha256) != 64:
        raise NativeCodegenError(f"native 机器码 map 字段 code_sha256 必须是 64 位十六进制字符串，实际长度 {len(code_sha256)}")
    try:
        bytes.fromhex(code_sha256)
    except ValueError as error:
        raise NativeCodegenError(f"native 机器码 map 字段 code_sha256 不是合法十六进制: {error}") from error
    if code_sha256 != actual_hash:
        raise NativeCodegenError(
            f"native 机器码 map 字段 code_sha256 不一致: 期望 {actual_hash!r}, 实际 {code_sha256!r}"
        )
    sections = metadata.get("sections")
    if not isinstance(sections, list) or not sections:
        raise NativeCodegenError("native 机器码 map 字段 sections 必须是非空列表")
    if len(sections) != pe_number_of_sections:
        raise NativeCodegenError(
            f"native 机器码 map 字段 sections 数量不一致: 期望 {pe_number_of_sections}, 实际 {len(sections)}"
        )
    text_sections = [section for section in sections if isinstance(section, dict) and section.get("name") == ".text"]
    if len(text_sections) != 1:
        raise NativeCodegenError(f"native 机器码 map .text section 数量必须为 1，实际 {len(text_sections)}")
    text_section = text_sections[0]
    extra_text_section_fields = sorted(set(text_section) - _MAP_TEXT_SECTION_FIELDS)
    if extra_text_section_fields:
        raise NativeCodegenError(f"native 机器码 map .text section 存在未知字段: {', '.join(extra_text_section_fields)}")
    for field in (
        "offset",
        "size",
        "end_offset",
        "virtual_size",
        "raw_size_aligned",
        "raw_padding_size",
        "virtual_size_aligned",
        "rva",
        "end_rva",
        "va",
        "end_va",
        "entry_offset",
        "pe_raw_pointer",
        "pe_raw_end_pointer",
        "alignment",
        "file_alignment",
        "section_alignment",
        "pe_characteristics",
    ):
        value = text_section.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map .text section {field} 必须是整数")
    name_bytes = text_section.get("name_bytes")
    if name_bytes != "2E 74 65 78 74 00 00 00":
        raise NativeCodegenError(
            f"native 机器码 map .text section name_bytes 必须为 '2E 74 65 78 74 00 00 00'，实际 {name_bytes!r}"
        )
    section_hash = text_section.get("sha256")
    if not isinstance(section_hash, str):
        raise NativeCodegenError(f"native 机器码 map .text section sha256 必须是字符串，实际 {type(section_hash).__name__}")
    raw_padded_hash = text_section.get("raw_padded_sha256")
    if not isinstance(raw_padded_hash, str):
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 必须是字符串，实际 {type(raw_padded_hash).__name__}"
        )
    if len(raw_padded_hash) != 64:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 必须是 64 位十六进制字符串，实际长度 {len(raw_padded_hash)}"
        )
    try:
        bytes.fromhex(raw_padded_hash)
    except ValueError as error:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 不是合法十六进制: {error}"
        ) from error
    permissions = text_section.get("permissions")
    if permissions != ["read", "execute"]:
        raise NativeCodegenError(
            f"native 机器码 map .text section permissions 必须为 ['read', 'execute']，实际 {permissions!r}"
        )
    characteristics = text_section.get("characteristics")
    if characteristics != ["CNT_CODE", "MEM_EXECUTE", "MEM_READ"]:
        raise NativeCodegenError(
            "native 机器码 map .text section characteristics 必须为 "
            f"['CNT_CODE', 'MEM_EXECUTE', 'MEM_READ']，实际 {characteristics!r}"
        )
    if text_section["pe_characteristics"] != 0x60000020:
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_characteristics 必须为 0x60000020，实际 0x{text_section['pe_characteristics']:08X}"
        )
    pe_section_header = text_section.get("pe_section_header")
    if not isinstance(pe_section_header, dict):
        raise NativeCodegenError("native 机器码 map .text section pe_section_header 必须是对象")
    extra_pe_section_header_fields = sorted(set(pe_section_header) - _MAP_PE_SECTION_HEADER_FIELDS)
    if extra_pe_section_header_fields:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header 存在未知字段: "
            f"{', '.join(extra_pe_section_header_fields)}"
        )
    missing_pe_section_header_fields = sorted(_MAP_PE_SECTION_HEADER_FIELDS - set(pe_section_header))
    if missing_pe_section_header_fields:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header 缺少字段: "
            f"{', '.join(missing_pe_section_header_fields)}"
        )
    for field in (
        "VirtualSize",
        "VirtualAddress",
        "SizeOfRawData",
        "PointerToRawData",
        "PointerToRelocations",
        "PointerToLinenumbers",
        "NumberOfRelocations",
        "NumberOfLinenumbers",
        "Characteristics",
    ):
        value = pe_section_header.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map .text section pe_section_header.{field} 必须是整数")
    if pe_section_header["Name"] != ".text":
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_section_header.Name 必须为 '.text'，实际 {pe_section_header['Name']!r}"
        )
    if pe_section_header["NameBytes"] != name_bytes:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.NameBytes 与 name_bytes 不一致: "
            f"期望 {name_bytes!r}, 实际 {pe_section_header['NameBytes']!r}"
        )
    if pe_section_header["PointerToRelocations"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.PointerToRelocations 必须为 0")
    if pe_section_header["PointerToLinenumbers"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.PointerToLinenumbers 必须为 0")
    if pe_section_header["NumberOfRelocations"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.NumberOfRelocations 必须为 0")
    if pe_section_header["NumberOfLinenumbers"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.NumberOfLinenumbers 必须为 0")
    if text_section["offset"] != 0:
        raise NativeCodegenError(f"native 机器码 map .text section offset 必须为 0，实际 {text_section['offset']}")
    if text_section["alignment"] <= 0:
        raise NativeCodegenError(f"native 机器码 map .text section alignment 必须为正数，实际 {text_section['alignment']}")
    if text_section["file_alignment"] != _PE_FILE_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map .text section file_alignment 必须为 {_PE_FILE_ALIGNMENT}，实际 {text_section['file_alignment']}")
    if text_section["file_alignment"] != pe_file_alignment:
        raise NativeCodegenError(
            f"native 机器码 map .text section file_alignment 与 pe_file_alignment 不一致: "
            f"期望 {pe_file_alignment}, 实际 {text_section['file_alignment']}"
        )
    if text_section["section_alignment"] != _PE_SECTION_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map .text section section_alignment 必须为 {_PE_SECTION_ALIGNMENT}，实际 {text_section['section_alignment']}")
    if text_section["section_alignment"] != pe_section_alignment:
        raise NativeCodegenError(
            f"native 机器码 map .text section section_alignment 与 pe_section_alignment 不一致: "
            f"期望 {pe_section_alignment}, 实际 {text_section['section_alignment']}"
        )
    if text_section["size"] != actual_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section size 不一致: 期望 {actual_size!r}, 实际 {text_section['size']!r}"
        )
    expected_end_offset = text_section["offset"] + text_section["size"]
    if text_section["end_offset"] != expected_end_offset:
        raise NativeCodegenError(
            f"native 机器码 map .text section end_offset 不一致: 期望 {expected_end_offset}, 实际 {text_section['end_offset']}"
        )
    if text_section["virtual_size"] != actual_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section virtual_size 不一致: 期望 {actual_size!r}, 实际 {text_section['virtual_size']!r}"
        )
    expected_raw_size = ((actual_size + _PE_FILE_ALIGNMENT - 1) // _PE_FILE_ALIGNMENT) * _PE_FILE_ALIGNMENT
    if text_section["raw_size_aligned"] != expected_raw_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_size_aligned 不一致: 期望 {expected_raw_size}, 实际 {text_section['raw_size_aligned']}"
        )
    expected_raw_padding_size = expected_raw_size - actual_size
    if text_section["raw_padding_size"] != expected_raw_padding_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padding_size 不一致: "
            f"期望 {expected_raw_padding_size}, 实际 {text_section['raw_padding_size']}"
        )
    if text_section["pe_raw_pointer"] != metadata["pe_size_of_headers"]:
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_raw_pointer 不一致: "
            f"期望 {metadata['pe_size_of_headers']}, 实际 {text_section['pe_raw_pointer']}"
        )
    if pe_section_header["PointerToRawData"] != text_section["pe_raw_pointer"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.PointerToRawData 与 pe_raw_pointer 不一致: "
            f"期望 {text_section['pe_raw_pointer']}, 实际 {pe_section_header['PointerToRawData']}"
        )
    expected_pe_raw_end_pointer = text_section["pe_raw_pointer"] + text_section["raw_size_aligned"]
    if text_section["pe_raw_end_pointer"] != expected_pe_raw_end_pointer:
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_raw_end_pointer 不一致: "
            f"期望 {expected_pe_raw_end_pointer}, 实际 {text_section['pe_raw_end_pointer']}"
        )
    expected_file_layout_ranges = {
        "dos_header": (0, metadata["pe_dos_header_size"], metadata["pe_dos_header_size"]),
        "dos_stub_padding": (
            metadata["pe_dos_header_size"],
            metadata["pe_lfanew"] - metadata["pe_dos_header_size"],
            metadata["pe_lfanew"],
        ),
        "pe_signature": (
            metadata["pe_signature_offset"],
            metadata["pe_signature_size"],
            metadata["pe_signature_offset"] + metadata["pe_signature_size"],
        ),
        "coff_header": (
            metadata["pe_coff_header_offset"],
            metadata["pe_coff_header_size"],
            metadata["pe_coff_header_offset"] + metadata["pe_coff_header_size"],
        ),
        "optional_header": (
            metadata["pe_optional_header_offset"],
            metadata["pe_optional_header_size"],
            metadata["pe_optional_header_offset"] + metadata["pe_optional_header_size"],
        ),
        "section_table": (
            metadata["pe_section_table_offset"],
            metadata["pe_section_table_size"],
            metadata["pe_section_table_offset"] + metadata["pe_section_table_size"],
        ),
        "headers_padding": (
            metadata["pe_section_table_offset"] + metadata["pe_section_table_size"],
            metadata["pe_size_of_headers"] - metadata["pe_section_table_offset"] - metadata["pe_section_table_size"],
            metadata["pe_size_of_headers"],
        ),
        "text_raw": (
            text_section["pe_raw_pointer"],
            text_section["raw_size_aligned"],
            text_section["pe_raw_end_pointer"],
        ),
    }
    previous_layout_end = 0
    for range_name, (expected_offset, expected_size, expected_end_offset) in expected_file_layout_ranges.items():
        range_item = pe_file_layout[range_name]
        if range_item["offset"] != expected_offset:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.offset 不一致: "
                f"期望 {expected_offset}, 实际 {range_item['offset']}"
            )
        if range_item["size"] != expected_size:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.size 不一致: "
                f"期望 {expected_size}, 实际 {range_item['size']}"
            )
        if range_item["end_offset"] != expected_end_offset:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.end_offset 不一致: "
                f"期望 {expected_end_offset}, 实际 {range_item['end_offset']}"
            )
        if range_item["offset"] != previous_layout_end:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.offset 与上一段不连续: "
                f"期望 {previous_layout_end}, 实际 {range_item['offset']}"
            )
        previous_layout_end = range_item["end_offset"]
    if pe_file_layout["file_size"] != text_section["pe_raw_end_pointer"]:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_file_layout.file_size 不一致: "
            f"期望 {text_section['pe_raw_end_pointer']}, 实际 {pe_file_layout['file_size']}"
        )
    if pe_section_header["SizeOfRawData"] != text_section["raw_size_aligned"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.SizeOfRawData 与 raw_size_aligned 不一致: "
            f"期望 {text_section['raw_size_aligned']}, 实际 {pe_section_header['SizeOfRawData']}"
        )
    pe_size_of_code = metadata.get("pe_size_of_code")
    if not isinstance(pe_size_of_code, int) or isinstance(pe_size_of_code, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 pe_size_of_code 必须是整数，实际 {type(pe_size_of_code).__name__}")
    if pe_size_of_code != expected_raw_size:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_code 不一致: 期望 {expected_raw_size}, 实际 {pe_size_of_code}"
        )
    if pe_optional_header["SizeOfCode"] != pe_size_of_code:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SizeOfCode 与 pe_size_of_code 不一致: "
            f"期望 {pe_size_of_code}, 实际 {pe_optional_header['SizeOfCode']}"
        )
    pe_size_of_initialized_data = metadata.get("pe_size_of_initialized_data")
    if pe_size_of_initialized_data != 0:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_initialized_data 必须为 0，实际 {pe_size_of_initialized_data!r}"
        )
    if pe_optional_header["SizeOfInitializedData"] != pe_size_of_initialized_data:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header.SizeOfInitializedData 与 pe_size_of_initialized_data 不一致: "
            f"期望 {pe_size_of_initialized_data}, 实际 {pe_optional_header['SizeOfInitializedData']}"
        )
    pe_size_of_uninitialized_data = metadata.get("pe_size_of_uninitialized_data")
    if pe_size_of_uninitialized_data != 0:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_uninitialized_data 必须为 0，实际 {pe_size_of_uninitialized_data!r}"
        )
    if pe_optional_header["SizeOfUninitializedData"] != pe_size_of_uninitialized_data:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header.SizeOfUninitializedData 与 pe_size_of_uninitialized_data 不一致: "
            f"期望 {pe_size_of_uninitialized_data}, 实际 {pe_optional_header['SizeOfUninitializedData']}"
        )
    expected_virtual_size = ((actual_size + _PE_SECTION_ALIGNMENT - 1) // _PE_SECTION_ALIGNMENT) * _PE_SECTION_ALIGNMENT
    if text_section["virtual_size_aligned"] != expected_virtual_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section virtual_size_aligned 不一致: 期望 {expected_virtual_size}, 实际 {text_section['virtual_size_aligned']}"
        )
    if text_section["rva"] != _PE_TEXT_RVA:
        raise NativeCodegenError(f"native 机器码 map .text section rva 必须为 {_PE_TEXT_RVA}，实际 {text_section['rva']}")
    if pe_section_header["VirtualAddress"] != text_section["rva"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.VirtualAddress 与 rva 不一致: "
            f"期望 {text_section['rva']}, 实际 {pe_section_header['VirtualAddress']}"
        )
    if pe_section_header["VirtualSize"] != text_section["virtual_size"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.VirtualSize 与 virtual_size 不一致: "
            f"期望 {text_section['virtual_size']}, 实际 {pe_section_header['VirtualSize']}"
        )
    if pe_section_header["Characteristics"] != text_section["pe_characteristics"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.Characteristics 与 pe_characteristics 不一致: "
            f"期望 0x{text_section['pe_characteristics']:08X}, 实际 0x{pe_section_header['Characteristics']:08X}"
        )
    pe_size_of_image = metadata.get("pe_size_of_image")
    if not isinstance(pe_size_of_image, int) or isinstance(pe_size_of_image, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 pe_size_of_image 必须是整数，实际 {type(pe_size_of_image).__name__}")
    expected_size_of_image = text_section["rva"] + expected_virtual_size
    if pe_size_of_image != expected_size_of_image:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_image 不一致: 期望 {expected_size_of_image}, 实际 {pe_size_of_image}"
        )
    if pe_optional_header["SizeOfImage"] != pe_size_of_image:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SizeOfImage 与 pe_size_of_image 不一致: "
            f"期望 {pe_size_of_image}, 实际 {pe_optional_header['SizeOfImage']}"
        )
    pe_base_of_code = metadata.get("pe_base_of_code")
    if not isinstance(pe_base_of_code, int) or isinstance(pe_base_of_code, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 pe_base_of_code 必须是整数，实际 {type(pe_base_of_code).__name__}")
    if pe_base_of_code != text_section["rva"]:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_base_of_code 不一致: 期望 {text_section['rva']}, 实际 {pe_base_of_code}"
        )
    if pe_optional_header["BaseOfCode"] != pe_base_of_code:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.BaseOfCode 与 pe_base_of_code 不一致: "
            f"期望 {pe_base_of_code}, 实际 {pe_optional_header['BaseOfCode']}"
        )
    expected_section_end_rva = text_section["rva"] + text_section["virtual_size"]
    if text_section["end_rva"] != expected_section_end_rva:
        raise NativeCodegenError(
            f"native 机器码 map .text section end_rva 不一致: 期望 {expected_section_end_rva}, 实际 {text_section['end_rva']}"
        )
    expected_section_va = image_base + text_section["rva"]
    if text_section["va"] != expected_section_va:
        raise NativeCodegenError(
            f"native 机器码 map .text section va 不一致: 期望 {expected_section_va}, 实际 {text_section['va']}"
        )
    expected_section_end_va = image_base + text_section["end_rva"]
    if text_section["end_va"] != expected_section_end_va:
        raise NativeCodegenError(
            f"native 机器码 map .text section end_va 不一致: 期望 {expected_section_end_va}, 实际 {text_section['end_va']}"
        )
    if section_hash != actual_hash:
        raise NativeCodegenError(
            f"native 机器码 map .text section sha256 不一致: 期望 {actual_hash!r}, 实际 {section_hash!r}"
        )
    expected_raw_padded_hash = hashlib.sha256(code + bytes(expected_raw_padding_size)).hexdigest()
    if raw_padded_hash != expected_raw_padded_hash:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 不一致: "
            f"期望 {expected_raw_padded_hash!r}, 实际 {raw_padded_hash!r}"
        )
    entry = metadata.get("entry")
    if not isinstance(entry, str) or not entry:
        raise NativeCodegenError("native 机器码 map 字段 entry 必须是非空字符串")
    entry_offset = metadata.get("entry_offset")
    if not isinstance(entry_offset, int) or isinstance(entry_offset, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 entry_offset 必须是整数，实际 {type(entry_offset).__name__}")
    if entry_offset < 0 or entry_offset >= actual_size:
        raise NativeCodegenError(f"native 机器码 map 入口偏移越界: {entry_offset}, 机器码长度 {actual_size}")
    if text_section["entry_offset"] != entry_offset:
        raise NativeCodegenError(
            f"native 机器码 map .text section entry_offset 与入口偏移不一致: section {text_section['entry_offset']}, entry_offset {entry_offset}"
        )
    entry_rva = metadata.get("entry_rva")
    if not isinstance(entry_rva, int) or isinstance(entry_rva, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 entry_rva 必须是整数，实际 {type(entry_rva).__name__}")
    expected_entry_rva = text_section["rva"] + entry_offset
    if entry_rva != expected_entry_rva:
        raise NativeCodegenError(
            f"native 机器码 map 入口 RVA 不一致: 记录 {entry_rva}, 期望 {expected_entry_rva}"
        )
    pe_entry_point = metadata.get("pe_address_of_entry_point")
    if not isinstance(pe_entry_point, int) or isinstance(pe_entry_point, bool):
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_address_of_entry_point 必须是整数，实际 {type(pe_entry_point).__name__}"
        )
    if pe_entry_point != entry_rva:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_address_of_entry_point 不一致: 期望 {entry_rva}, 实际 {pe_entry_point}"
        )
    if pe_optional_header["AddressOfEntryPoint"] != pe_entry_point:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.AddressOfEntryPoint 与 pe_address_of_entry_point 不一致: "
            f"期望 {pe_entry_point}, 实际 {pe_optional_header['AddressOfEntryPoint']}"
        )
    entry_va = metadata.get("entry_va")
    if not isinstance(entry_va, int) or isinstance(entry_va, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 entry_va 必须是整数，实际 {type(entry_va).__name__}")
    expected_entry_va = image_base + entry_rva
    if entry_va != expected_entry_va:
        raise NativeCodegenError(
            f"native 机器码 map 入口 VA 不一致: 记录 {entry_va}, 期望 {expected_entry_va}"
        )
    functions = metadata.get("functions")
    if not isinstance(functions, list) or not functions:
        raise NativeCodegenError("native 机器码 map 字段 functions 必须是非空列表")
    function_ranges: dict[str, tuple[int, int]] = {}
    function_signatures: dict[str, tuple[str, list[str]]] = {}
    for index, function in enumerate(functions):
        if not isinstance(function, dict):
            raise NativeCodegenError(f"native 机器码 map functions[{index}] 必须是对象")
        extra_function_fields = sorted(set(function) - _MAP_FUNCTION_FIELDS)
        if extra_function_fields:
            raise NativeCodegenError(
                f"native 机器码 map functions[{index}] 存在未知字段: {', '.join(extra_function_fields)}"
            )
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise NativeCodegenError(f"native 机器码 map functions[{index}].name 必须是非空字符串")
        if name in function_ranges:
            raise NativeCodegenError(f"native 机器码 map 函数重复: {name}")
        offset = function.get("offset")
        size = function.get("size")
        end_offset = function.get("end_offset")
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} offset 必须是整数")
        if not isinstance(size, int) or isinstance(size, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} size 必须是整数")
        if not isinstance(end_offset, int) or isinstance(end_offset, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_offset 必须是整数")
        if offset < 0 or size < 0 or offset + size > actual_size:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 范围越界: offset {offset}, size {size}, 机器码长度 {actual_size}")
        expected_end_offset = offset + size
        if end_offset != expected_end_offset:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_offset 不一致: 记录 {end_offset}, 期望 {expected_end_offset}")
        rva = function.get("rva")
        end_rva = function.get("end_rva")
        va = function.get("va")
        end_va = function.get("end_va")
        if not isinstance(rva, int) or isinstance(rva, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} rva 必须是整数")
        if not isinstance(end_rva, int) or isinstance(end_rva, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_rva 必须是整数")
        if not isinstance(va, int) or isinstance(va, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} va 必须是整数")
        if not isinstance(end_va, int) or isinstance(end_va, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_va 必须是整数")
        expected_rva = text_section["rva"] + offset
        expected_end_rva = expected_rva + size
        expected_va = text_section["va"] + offset
        expected_end_va = expected_va + size
        if rva != expected_rva:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} RVA 不一致: 记录 {rva}, 期望 {expected_rva}")
        if end_rva != expected_end_rva:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_rva 不一致: 记录 {end_rva}, 期望 {expected_end_rva}")
        if va != expected_va:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} VA 不一致: 记录 {va}, 期望 {expected_va}")
        if end_va != expected_end_va:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_va 不一致: 记录 {end_va}, 期望 {expected_end_va}")
        function_hash = function.get("code_sha256")
        if not isinstance(function_hash, str):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} code_sha256 必须是字符串")
        if len(function_hash) != 64:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} code_sha256 必须是 64 位十六进制字符串，实际长度 {len(function_hash)}")
        try:
            bytes.fromhex(function_hash)
        except ValueError as error:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} code_sha256 不是合法十六进制: {error}") from error
        actual_function_hash = hashlib.sha256(code[offset:offset + size]).hexdigest()
        if function_hash != actual_function_hash:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} code_sha256 不一致: 期望 {actual_function_hash!r}, 实际 {function_hash!r}"
            )
        return_type = function.get("return_type")
        if not isinstance(return_type, str) or return_type not in _SUPPORTED_RETURN_TYPES:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} return_type 暂不支持: {return_type!r}")
        param_types = function.get("param_types")
        if not isinstance(param_types, list) or any(not isinstance(item, str) for item in param_types):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} param_types 必须是字符串列表")
        for param_index, param_type in enumerate(param_types):
            if param_type not in _SUPPORTED_VALUE_TYPES:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 第 {param_index} 个参数暂不支持类型: {param_type!r}"
                )
        function_ranges[name] = (offset, size)
        function_signatures[name] = (return_type, list(param_types))
    covered_until = 0
    for name, (offset, size) in sorted(function_ranges.items(), key=lambda item: item[1][0]):
        if offset < covered_until:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 范围与前序函数重叠: offset {offset}, 已覆盖到 {covered_until}")
        if offset > covered_until:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 范围前存在空洞: offset {offset}, 已覆盖到 {covered_until}")
        covered_until = offset + size
    if covered_until != actual_size:
        raise NativeCodegenError(f"native 机器码 map 函数范围未覆盖完整 raw bin: 已覆盖到 {covered_until}, 机器码长度 {actual_size}")
    function_labels: dict[str, dict[str, dict[str, int | None]]] = {}
    expected_relocations_by_function: dict[str, dict[int, str]] = {}
    exit_probe_jump_targets_by_function: dict[str, dict[int, str]] = {}
    global_frame_owners = {
        str(function.get("name"))
        for function in functions
        if isinstance(function.get("instructions"), list)
        and any(
            isinstance(instruction, dict)
            and instruction.get("source_op") == "prologue"
            and instruction.get("asm") == "mov r11, rbp ; global frame"
            for instruction in function.get("instructions", [])
        )
    }
    if len(global_frame_owners) > 1:
        raise NativeCodegenError(f"native 机器码 map global-frame owner 不能超过 1 个: {', '.join(sorted(global_frame_owners))}")
    if "global_frame_owner" not in metadata:
        raise NativeCodegenError("native 机器码 map 缺少顶层字段 global_frame_owner")
    global_frame_owner = metadata.get("global_frame_owner")
    expected_global_frame_owner = next(iter(global_frame_owners)) if global_frame_owners else None
    if global_frame_owner is not None and not isinstance(global_frame_owner, str):
        raise NativeCodegenError(
            f"native 机器码 map 字段 global_frame_owner 必须是字符串或 None，实际 {type(global_frame_owner).__name__}"
        )
    if global_frame_owner != expected_global_frame_owner:
        raise NativeCodegenError(
            f"native 机器码 map 字段 global_frame_owner 不一致: 记录 {global_frame_owner!r}, "
            f"指令清单推导 {expected_global_frame_owner!r}"
        )
    global_owner_slots: dict[str, tuple[int, int]] = {}
    non_owner_global_slots: dict[str, list[tuple[str, int, int]]] = {}
    for function in functions:
        name = function["name"]
        function_offset, function_size = function_ranges[name]
        function_end = function_offset + function_size
        frame_size = function.get("frame_size")
        if not isinstance(frame_size, int) or isinstance(frame_size, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} frame_size 必须是整数")
        if frame_size < 0 or frame_size % 16 != 0:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} frame_size 必须是非负 16 字节对齐整数，实际 {frame_size}")
        register_allocation = function.get("register_allocation")
        if not isinstance(register_allocation, dict):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation 必须是对象")
        extra_register_fields = sorted(set(register_allocation) - _MAP_REGISTER_ALLOCATION_FIELDS)
        if extra_register_fields:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation 存在未知字段: {', '.join(extra_register_fields)}"
            )
        missing_register_fields = sorted(_MAP_REGISTER_ALLOCATION_FIELDS - set(register_allocation))
        if missing_register_fields:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation 缺少字段: {', '.join(missing_register_fields)}"
            )
        if register_allocation["strategy"] != "保守栈槽分配":
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.strategy 不一致: {register_allocation['strategy']!r}"
            )
        temporary_registers = register_allocation["temporary_registers"]
        if temporary_registers != ["RAX", "R10"]:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.temporary_registers 必须是 ['RAX', 'R10']"
            )
        allocation_argument_registers = register_allocation["argument_registers"]
        if not isinstance(allocation_argument_registers, list) or any(not isinstance(register, str) for register in allocation_argument_registers):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.argument_registers 必须是字符串列表")
        if len(set(allocation_argument_registers)) != len(allocation_argument_registers):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.argument_registers 不能重复")
        expected_argument_prefix = list(abi["argument_registers"][:len(allocation_argument_registers)])
        if allocation_argument_registers != expected_argument_prefix:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.argument_registers 与 ABI 前缀不一致: "
                f"记录 {allocation_argument_registers}, 期望 {expected_argument_prefix}"
            )
        if register_allocation["return_register"] != abi["return_register"]:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.return_register 与 ABI 不一致")
        if register_allocation["frame_pointer"] != abi["frame_pointer"]:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.frame_pointer 与 ABI 不一致")
        if register_allocation["stack_pointer"] != abi["stack_pointer"]:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.stack_pointer 与 ABI 不一致")
        if register_allocation["virtual_register_storage"] != "全部写入栈槽":
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.virtual_register_storage 必须是全部写入栈槽")
        if register_allocation["local_storage"] != "全部写入栈槽":
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.local_storage 必须是全部写入栈槽")
        if register_allocation["global_frame_register"] not in {None, "R11"}:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.global_frame_register 必须是 R11 或 None")
        if register_allocation["global_frame_role"] not in {"none", "owner", "borrowed"}:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.global_frame_role 暂不支持")
        stack_slots = function.get("stack_slots", [])
        if not isinstance(stack_slots, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} stack_slots 必须是列表")
        seen_slot_names: set[str] = set()
        global_slot_offsets: set[int] = set()
        frame_slot_offsets: set[int] = set()
        max_frame_slot_offset = 0
        owns_global_frame = name in global_frame_owners
        has_global_slots = False
        for slot_index, slot in enumerate(stack_slots):
            if not isinstance(slot, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} stack_slots[{slot_index}] 必须是对象")
            extra_slot_fields = sorted(set(slot) - _MAP_STACK_SLOT_FIELDS)
            if extra_slot_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} stack_slots[{slot_index}] 存在未知字段: {', '.join(extra_slot_fields)}"
                )
            slot_name = slot.get("name")
            slot_offset = slot.get("offset")
            slot_size = slot.get("size")
            if not isinstance(slot_name, str) or not slot_name:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 name 必须是非空字符串")
            if slot_name in seen_slot_names:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽重复: {slot_name}")
            seen_slot_names.add(slot_name)
            if not isinstance(slot_offset, int) or isinstance(slot_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} offset 必须是整数")
            if not isinstance(slot_size, int) or isinstance(slot_size, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} size 必须是整数")
            if slot_offset <= 0:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} offset 必须为正数")
            if slot_size != 8:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} size 必须为 8，实际 {slot_size}")
            if slot_name.startswith("global[") and not owns_global_frame:
                has_global_slots = True
                if slot_offset in global_slot_offsets:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 全局栈槽偏移重复: {slot_offset}")
                global_slot_offsets.add(slot_offset)
                non_owner_global_slots.setdefault(name, []).append((slot_name, slot_offset, slot_size))
            else:
                if slot_offset in frame_slot_offsets:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈帧槽偏移重复: {slot_offset}")
                frame_slot_offsets.add(slot_offset)
                max_frame_slot_offset = max(max_frame_slot_offset, slot_offset)
                if slot_name.startswith("global["):
                    has_global_slots = True
                    global_owner_slots[slot_name] = (slot_offset, slot_size)
        expected_global_register = "R11" if has_global_slots else None
        if register_allocation["global_frame_register"] != expected_global_register:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.global_frame_register 不一致: "
                f"记录 {register_allocation['global_frame_register']!r}, 期望 {expected_global_register!r}"
            )
        expected_global_role = "owner" if owns_global_frame and has_global_slots else ("borrowed" if has_global_slots else "none")
        if register_allocation["global_frame_role"] != expected_global_role:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.global_frame_role 不一致: "
                f"记录 {register_allocation['global_frame_role']!r}, 期望 {expected_global_role!r}"
            )
        if max_frame_slot_offset > frame_size:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} 栈槽超出栈帧: 最大偏移 {max_frame_slot_offset}, frame_size {frame_size}"
            )
        labels: dict[str, dict[str, int | None]] = {}
        instructions = function.get("instructions", [])
        if not isinstance(instructions, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} instructions 必须是列表")
        instruction_ranges: list[tuple[int, int]] = []
        expected_relocations: dict[int, str] = {}
        for instruction_index, instruction in enumerate(instructions):
            if not isinstance(instruction, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} instructions[{instruction_index}] 必须是对象")
            extra_instruction_fields = sorted(set(instruction) - _MAP_INSTRUCTION_FIELDS)
            if extra_instruction_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} instructions[{instruction_index}] 存在未知字段: {', '.join(extra_instruction_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} instructions[{instruction_index}]", instruction)
            instruction_offset = instruction.get("offset")
            instruction_rva = instruction.get("rva")
            instruction_va = instruction.get("va")
            instruction_size = instruction.get("size")
            instruction_end_offset = instruction.get("end_offset")
            instruction_end_rva = instruction.get("end_rva")
            instruction_end_va = instruction.get("end_va")
            instruction_bytes = instruction.get("bytes")
            instruction_hash = instruction.get("code_sha256")
            instruction_asm = instruction.get("asm")
            instruction_source_op = instruction.get("source_op")
            instruction_source_attrs = instruction.get("source_attrs")
            if not isinstance(instruction_offset, int) or isinstance(instruction_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 offset 必须是整数")
            if not isinstance(instruction_rva, int) or isinstance(instruction_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 rva 必须是整数")
            if not isinstance(instruction_va, int) or isinstance(instruction_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 va 必须是整数")
            if not isinstance(instruction_size, int) or isinstance(instruction_size, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 size 必须是整数")
            if not isinstance(instruction_end_offset, int) or isinstance(instruction_end_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 end_offset 必须是整数")
            if not isinstance(instruction_end_rva, int) or isinstance(instruction_end_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 end_rva 必须是整数")
            if not isinstance(instruction_end_va, int) or isinstance(instruction_end_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 end_va 必须是整数")
            if not isinstance(instruction_bytes, str):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 bytes 必须是字符串")
            if not isinstance(instruction_hash, str):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 code_sha256 必须是字符串")
            if len(instruction_hash) != 64:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 code_sha256 必须是 64 位十六进制字符串，实际长度 {len(instruction_hash)}"
                )
            try:
                bytes.fromhex(instruction_hash)
            except ValueError as error:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 code_sha256 不是合法十六进制: {error}") from error
            if not isinstance(instruction_asm, str):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 asm 必须是字符串")
            if not isinstance(instruction_source_op, str) or not instruction_source_op:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 source_op 必须是非空字符串")
            if not isinstance(instruction_source_attrs, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 source_attrs 必须是对象")
            for attr_key, attr_value in instruction_source_attrs.items():
                if not isinstance(attr_key, str) or not attr_key:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 source_attrs key 必须是非空字符串")
                if not isinstance(attr_value, (str, int, bool)) and attr_value is not None:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 指令 source_attrs.{attr_key} 必须是字符串、整数、布尔值或 null"
                    )
            if (
                instruction_size < 0
                or instruction_offset < function_offset
                or instruction_offset > function_end
                or instruction_offset + instruction_size > function_end
            ):
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令范围越界: offset {instruction_offset}, size {instruction_size}"
                )
            expected_instruction_rva = text_section["rva"] + instruction_offset
            expected_instruction_end_offset = instruction_offset + instruction_size
            expected_instruction_end_rva = expected_instruction_rva + instruction_size
            expected_instruction_va = text_section["va"] + instruction_offset
            expected_instruction_end_va = expected_instruction_va + instruction_size
            if instruction_end_offset != expected_instruction_end_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 end_offset 不一致: 记录 {instruction_end_offset}, 期望 {expected_instruction_end_offset}"
                )
            if instruction_rva != expected_instruction_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 RVA 不一致: 记录 {instruction_rva}, 期望 {expected_instruction_rva}"
                )
            if instruction_end_rva != expected_instruction_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 end_rva 不一致: 记录 {instruction_end_rva}, 期望 {expected_instruction_end_rva}"
                )
            if instruction_va != expected_instruction_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 VA 不一致: 记录 {instruction_va}, 期望 {expected_instruction_va}"
                )
            if instruction_end_va != expected_instruction_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 end_va 不一致: 记录 {instruction_end_va}, 期望 {expected_instruction_end_va}"
                )
            try:
                parsed_instruction_bytes = bytes.fromhex(instruction_bytes)
            except ValueError as error:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 bytes 不是合法十六进制: {error}") from error
            if len(parsed_instruction_bytes) != instruction_size:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 bytes 长度与 size 不一致: "
                    f"长度 {len(parsed_instruction_bytes)}, size {instruction_size}"
                )
            actual_instruction_hash = hashlib.sha256(parsed_instruction_bytes).hexdigest()
            if instruction_hash != actual_instruction_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 code_sha256 不一致: 期望 {actual_instruction_hash!r}, 实际 {instruction_hash!r}"
                )
            if parsed_instruction_bytes != code[instruction_offset:instruction_offset + instruction_size]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令字节与 raw bin 不一致")
            if instruction_source_op == "prologue" and instruction_asm == "mov r11, rbp ; global frame":
                if parsed_instruction_bytes != b"\x49\x89\xEB":
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} global-frame 初始化指令 bytes 不一致")
            if instruction_size:
                instruction_ranges.append((instruction_offset, instruction_offset + instruction_size))
                if parsed_instruction_bytes[:1] == b"\xE8":
                    expected_relocations[instruction_offset] = "call_rel32"
                else:
                    for relocation_kind, opcode in _REL32_JUMP_OPCODES.items():
                        if parsed_instruction_bytes.startswith(opcode):
                            expected_relocations[instruction_offset] = relocation_kind
                            break
            if instruction.get("source_op") == "label":
                asm = instruction.get("asm")
                if isinstance(asm, str) and asm.endswith(":"):
                    labels[asm[:-1]] = {
                        "offset": instruction_offset,
                        "source_pc": instruction.get("source_pc"),
                        "source_line": instruction.get("source_line"),
                    }
        label_records = function.get("labels", [])
        if not isinstance(label_records, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} labels 必须是列表")
        seen_label_records: dict[str, int] = {}
        for label_index, label_record in enumerate(label_records):
            if not isinstance(label_record, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} labels[{label_index}] 必须是对象")
            extra_label_fields = sorted(set(label_record) - _MAP_LABEL_FIELDS)
            if extra_label_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} labels[{label_index}] 存在未知字段: {', '.join(extra_label_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} labels[{label_index}]", label_record)
            label_name = label_record.get("name")
            label_offset = label_record.get("offset")
            label_rva = label_record.get("rva")
            label_va = label_record.get("va")
            if not isinstance(label_name, str) or not label_name:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} labels[{label_index}].name 必须是非空字符串")
            if label_name in seen_label_records:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label 重复: {label_name}")
            if not isinstance(label_offset, int) or isinstance(label_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} offset 必须是整数")
            if not isinstance(label_rva, int) or isinstance(label_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} rva 必须是整数")
            if not isinstance(label_va, int) or isinstance(label_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} va 必须是整数")
            if label_offset < function_offset or label_offset > function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} offset 越界: {label_offset}")
            expected_label_rva = text_section["rva"] + label_offset
            if label_rva != expected_label_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} label {label_name} rva 不一致: 记录 {label_rva}, 期望 {expected_label_rva}"
                )
            expected_label_va = text_section["va"] + label_offset
            if label_va != expected_label_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} label {label_name} va 不一致: 记录 {label_va}, 期望 {expected_label_va}"
                )
            seen_label_records[label_name] = label_offset
        missing_labels = sorted(set(labels) - set(seen_label_records))
        if missing_labels:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} labels 缺少指令标签: {', '.join(missing_labels)}")
        extra_labels = sorted(set(seen_label_records) - set(labels))
        if extra_labels:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} labels 包含未知标签: {', '.join(extra_labels)}")
        for label_name, label_info in labels.items():
            label_offset = label_info["offset"]
            if seen_label_records[label_name] != label_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} label {label_name} offset 不一致: "
                    f"记录 {seen_label_records[label_name]}, 指令 {label_offset}"
                )
            label_record = next(item for item in label_records if item.get("name") == label_name)
            if label_record.get("source_pc") != label_info["source_pc"] or label_record.get("source_line") != label_info["source_line"]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} 来源位置与指令不一致")
        expected_relocations_by_function[name] = expected_relocations
        covered_until = function_offset
        for start, end in sorted(instruction_ranges):
            if start < covered_until:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令范围重叠: offset {start}, 已覆盖到 {covered_until}")
            if start > covered_until:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令范围前存在空洞: offset {start}, 已覆盖到 {covered_until}")
            covered_until = end
        if covered_until != function_end:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令范围未覆盖完整函数: 已覆盖到 {covered_until}, 函数结束 {function_end}")
        for instruction_index, instruction in enumerate(instructions):
            if instruction.get("source_op") != "call":
                continue
            asm = instruction.get("asm")
            if not isinstance(asm, str) or not asm.startswith("call "):
                continue
            if instruction_index + 3 >= len(instructions):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 缺少 _exit 传播探针: {asm}")
            add_rsp = instructions[instruction_index + 1]
            test_rdx = instructions[instruction_index + 2]
            jump = instructions[instruction_index + 3]
            if (
                add_rsp.get("source_op") != "call"
                or not isinstance(add_rsp.get("asm"), str)
                or not add_rsp["asm"].startswith("add rsp, ")
                or bytes.fromhex(add_rsp["bytes"])[:3] != b"\x48\x81\xC4"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 后缺少 add rsp 恢复栈窗口")
            if (
                test_rdx.get("source_op") != "call"
                or test_rdx.get("asm") != "test rdx, rdx ; native _exit flag"
                or bytes.fromhex(test_rdx["bytes"]) != b"\x48\x85\xD2"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 后缺少 native _exit 标志检查")
            jump_asm = jump.get("asm")
            if (
                jump.get("source_op") != "exit_probe"
                or not isinstance(jump_asm, str)
                or not jump_asm.startswith("jne __propagate_exit_")
                or bytes.fromhex(jump["bytes"])[:2] != b"\x0F\x85"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 后缺少 native _exit 传播跳转")
            target = jump_asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if target not in labels:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} native _exit 传播目标未知: {target}")
        instructions_by_offset = {
            instruction.get("offset"): instruction
            for instruction in instructions
            if isinstance(instruction.get("offset"), int) and not isinstance(instruction.get("offset"), bool)
        }
        if "exit_probes" not in function:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 缺少 exit_probes 字段")
        exit_probes = function["exit_probes"]
        if not isinstance(exit_probes, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} exit_probes 必须是列表")
        relocations_for_probe = function.get("relocations", [])
        relocation_targets_by_offset = {
            relocation.get("offset"): relocation.get("target")
            for relocation in relocations_for_probe
            if isinstance(relocation, dict)
            and isinstance(relocation.get("offset"), int)
            and not isinstance(relocation.get("offset"), bool)
        } if isinstance(relocations_for_probe, list) else {}
        probe_call_offsets: set[int] = set()
        exit_probe_jump_targets: dict[int, str] = {}
        for probe_index, probe in enumerate(exit_probes):
            if not isinstance(probe, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} exit_probes[{probe_index}] 必须是对象")
            extra_probe_fields = sorted(set(probe) - _MAP_EXIT_PROBE_FIELDS)
            if extra_probe_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} exit_probes[{probe_index}] 存在未知字段: {', '.join(extra_probe_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} exit_probes[{probe_index}]", probe)
            for field, end_field, rva_field, end_rva_field, va_field, end_va_field, instruction_size in (
                ("call_offset", "call_end_offset", "call_rva", "call_end_rva", "call_va", "call_end_va", _CALL_REL32_SIZE),
                ("test_offset", "test_end_offset", "test_rva", "test_end_rva", "test_va", "test_end_va", _TEST_RDX_RDX_SIZE),
                ("jump_offset", "jump_end_offset", "jump_rva", "jump_end_rva", "jump_va", "jump_end_va", _JNE_REL32_SIZE),
            ):
                value = probe.get(field)
                end_value = probe.get(end_field)
                rva_value = probe.get(rva_field)
                end_rva_value = probe.get(end_rva_field)
                va_value = probe.get(va_field)
                end_va_value = probe.get(end_va_field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {field} 必须是整数")
                if not isinstance(end_value, int) or isinstance(end_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {end_field} 必须是整数")
                if not isinstance(rva_value, int) or isinstance(rva_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {rva_field} 必须是整数")
                if not isinstance(end_rva_value, int) or isinstance(end_rva_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {end_rva_field} 必须是整数")
                if not isinstance(va_value, int) or isinstance(va_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {va_field} 必须是整数")
                if not isinstance(end_va_value, int) or isinstance(end_va_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {end_va_field} 必须是整数")
                expected_end_value = value + instruction_size
                if end_value != expected_end_value:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {end_field} 不一致: "
                        f"记录 {end_value}, 期望 {expected_end_value}"
                    )
                if value < function_offset or expected_end_value > function_end:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {field} 越界: {value}")
                expected_rva = text_section["rva"] + value
                if rva_value != expected_rva:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {rva_field} 不一致: 记录 {rva_value}, 期望 {expected_rva}"
                    )
                expected_end_rva = text_section["rva"] + expected_end_value
                if end_rva_value != expected_end_rva:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {end_rva_field} 不一致: "
                        f"记录 {end_rva_value}, 期望 {expected_end_rva}"
                    )
                expected_va = text_section["va"] + value
                if va_value != expected_va:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {va_field} 不一致: 记录 {va_value}, 期望 {expected_va}"
                    )
                expected_end_va = text_section["va"] + expected_end_value
                if end_va_value != expected_end_va:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {end_va_field} 不一致: "
                        f"记录 {end_va_value}, 期望 {expected_end_va}"
                    )
            for hash_field in ("call_code_sha256", "test_code_sha256", "jump_code_sha256"):
                hash_value = probe.get(hash_field)
                if not isinstance(hash_value, str):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 必须是字符串")
                if len(hash_value) != 64:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 必须是 64 位十六进制字符串，"
                        f"实际长度 {len(hash_value)}"
                    )
                try:
                    bytes.fromhex(hash_value)
                except ValueError as error:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 不是合法十六进制: {error}"
                    ) from error
            target = probe.get("target")
            if not isinstance(target, str) or not target:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 target 必须是非空字符串")
            if target not in function_ranges:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针目标未知: {target}")
            probe_label = probe.get("probe_label")
            if not isinstance(probe_label, str) or not probe_label:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 probe_label 必须是非空字符串")
            if probe_label not in labels:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针标签未知: {probe_label}")
            call_offset = probe["call_offset"]
            test_offset = probe["test_offset"]
            jump_offset = probe["jump_offset"]
            if call_offset in probe_call_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call_offset 重复: {call_offset}")
            probe_call_offsets.add(call_offset)
            if code[call_offset:call_offset + 1] != b"\xE8":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call opcode 不一致")
            if code[test_offset:test_offset + 3] != b"\x48\x85\xD2":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 test opcode 不一致")
            if code[jump_offset:jump_offset + 2] != b"\x0F\x85":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 jump opcode 不一致")
            for prefix, offset, end_offset in (
                ("call", call_offset, probe["call_end_offset"]),
                ("test", test_offset, probe["test_end_offset"]),
                ("jump", jump_offset, probe["jump_end_offset"]),
            ):
                actual_hash = hashlib.sha256(code[offset:end_offset]).hexdigest()
                hash_field = f"{prefix}_code_sha256"
                if probe[hash_field] != actual_hash:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 不一致: "
                        f"期望 {actual_hash!r}, 实际 {probe[hash_field]!r}"
                    )
            if jump_offset in exit_probe_jump_targets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 jump_offset 重复: {jump_offset}")
            exit_probe_jump_targets[jump_offset] = probe_label
            call_instruction = instructions_by_offset.get(call_offset)
            test_instruction = instructions_by_offset.get(test_offset)
            jump_instruction = instructions_by_offset.get(jump_offset)
            if call_instruction is None or call_instruction.get("source_op") != "call":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call 清单缺失")
            call_asm = call_instruction.get("asm")
            call_relocation_target = relocation_targets_by_offset.get(call_offset)
            if isinstance(call_relocation_target, str) and isinstance(call_asm, str):
                call_asm_target = call_asm.split(" ", 1)[1].split(";", 1)[0].strip() if call_asm.startswith("call ") else None
                if call_asm_target == call_relocation_target and call_relocation_target != target:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 call 修补目标不一致: "
                        f"探针 {target}, 修补记录 {call_relocation_target}"
                    )
            if not isinstance(call_asm, str) or not call_asm.startswith(f"call {target}"):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call 目标不一致")
            if (
                test_instruction is None
                or test_instruction.get("source_op") != "call"
                or test_instruction.get("asm") != "test rdx, rdx ; native _exit flag"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 test 清单不一致")
            jump_asm = jump_instruction.get("asm") if jump_instruction is not None else None
            if (
                jump_instruction is None
                or jump_instruction.get("source_op") != "exit_probe"
                or not isinstance(jump_asm, str)
                or not jump_asm.startswith(f"jne {probe_label}")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 jump 清单不一致")
            for instruction in (call_instruction, test_instruction, jump_instruction):
                if (
                    instruction.get("source_pc") != probe.get("source_pc")
                    or instruction.get("source_line") != probe.get("source_line")
                ):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针来源位置与清单不一致")
            for instruction, prefix in (
                (call_instruction, "call"),
                (test_instruction, "test"),
                (jump_instruction, "jump"),
            ):
                for instruction_field, probe_field in (
                    ("end_offset", f"{prefix}_end_offset"),
                    ("end_rva", f"{prefix}_end_rva"),
                    ("end_va", f"{prefix}_end_va"),
                ):
                    if instruction.get(instruction_field) != probe[probe_field]:
                        raise NativeCodegenError(
                            f"native 机器码 map 函数 {name} _exit 传播探针 {prefix} 清单范围不一致: "
                            f"{instruction_field} 记录 {instruction.get(instruction_field)}, 探针 {probe[probe_field]}"
                        )
        for instruction in instructions:
            if instruction.get("source_op") != "call":
                continue
            asm = instruction.get("asm")
            if not isinstance(asm, str) or not asm.startswith("call "):
                continue
            call_offset = instruction.get("offset")
            if call_offset not in probe_call_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 缺少 _exit 传播探针记录: {asm}")
        function_labels[name] = labels
        exit_probe_jump_targets_by_function[name] = exit_probe_jump_targets
        call_frames = function.get("call_frames", [])
        if not isinstance(call_frames, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} call_frames 必须是列表")
        expected_call_frame_offsets = {
            instruction["offset"]
            for instruction in instructions
            if (
                instruction.get("source_op") == "call"
                and isinstance(instruction.get("asm"), str)
                and instruction["asm"].startswith("sub rsp, ")
                and isinstance(instruction.get("offset"), int)
                and not isinstance(instruction.get("offset"), bool)
            )
        }
        seen_call_frame_offsets: set[int] = set()
        for frame_index, frame in enumerate(call_frames):
            if not isinstance(frame, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call_frames[{frame_index}] 必须是对象")
            extra_frame_fields = sorted(set(frame) - _MAP_CALL_FRAME_FIELDS)
            if extra_frame_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} call_frames[{frame_index}] 存在未知字段: {', '.join(extra_frame_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} call_frames[{frame_index}]", frame)
            target = frame.get("target")
            if not isinstance(target, str) or not target:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 target 必须是非空字符串")
            if target not in function_ranges:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口目标未知: {target}")
            for field in (
                "offset",
                "end_offset",
                "rva",
                "end_rva",
                "va",
                "end_va",
                "call_offset",
                "call_end_offset",
                "call_rva",
                "call_end_rva",
                "call_va",
                "call_end_va",
                "add_offset",
                "add_end_offset",
                "add_rva",
                "add_end_rva",
                "add_va",
                "add_end_va",
                "arg_count",
                "register_arg_count",
                "stack_arg_count",
                "shadow_space_size",
                "stack_arg_bytes",
                "aligned_size",
                "stack_alignment",
            ):
                value = frame.get(field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 {field} 必须是整数")
            for hash_field in ("sub_code_sha256", "call_code_sha256", "add_code_sha256"):
                hash_value = frame.get(hash_field)
                if not isinstance(hash_value, str):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 {hash_field} 必须是字符串")
                if len(hash_value) != 64:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口 {hash_field} 必须是 64 位十六进制字符串，"
                        f"实际长度 {len(hash_value)}"
                    )
                try:
                    bytes.fromhex(hash_value)
                except ValueError as error:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口 {hash_field} 不是合法十六进制: {error}"
                    ) from error
            expected_frame_rva = text_section["rva"] + frame["offset"]
            if frame["rva"] != expected_frame_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 rva 不一致: 记录 {frame['rva']}, 期望 {expected_frame_rva}"
                )
            expected_frame_va = text_section["va"] + frame["offset"]
            if frame["va"] != expected_frame_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 va 不一致: 记录 {frame['va']}, 期望 {expected_frame_va}"
                )
            if frame["arg_count"] != frame["register_arg_count"] + frame["stack_arg_count"]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口参数数量不一致")
            arg_types = frame.get("arg_types")
            if not isinstance(arg_types, list) or any(not isinstance(item, str) for item in arg_types):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 arg_types 必须是字符串列表")
            if len(arg_types) != frame["arg_count"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 arg_types 数量不一致: "
                    f"记录 {len(arg_types)}, 参数 {frame['arg_count']}"
                )
            param_types = frame.get("param_types")
            if not isinstance(param_types, list) or any(not isinstance(item, str) for item in param_types):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 param_types 必须是字符串列表")
            if len(param_types) != frame["arg_count"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 param_types 数量不一致: "
                    f"记录 {len(param_types)}, 参数 {frame['arg_count']}"
                )
            target_param_types = function_signatures[target][1]
            if param_types != target_param_types:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口形参类型与目标函数 {target} 签名不一致: "
                    f"记录 {param_types}, 签名 {target_param_types}"
                )
            for type_index, (arg_type, param_type) in enumerate(zip(arg_types, param_types)):
                if not _is_argument_type_compatible(param_type, arg_type):
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口第 {type_index} 个参数类型不兼容: "
                        f"形参 {param_type}, 实参 {arg_type}"
                    )
            expected_register_arg_count = min(frame["arg_count"], len(argument_registers))
            if frame["register_arg_count"] != expected_register_arg_count:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口寄存器参数数量与 ABI 不一致: "
                    f"记录 {frame['register_arg_count']}, 期望 {expected_register_arg_count}"
                )
            expected_stack_arg_count = max(0, frame["arg_count"] - len(argument_registers))
            if frame["stack_arg_count"] != expected_stack_arg_count:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口栈参数数量与 ABI 不一致: "
                    f"记录 {frame['stack_arg_count']}, 期望 {expected_stack_arg_count}"
                )
            if frame["stack_arg_bytes"] != frame["stack_arg_count"] * abi_word_size:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口栈实参字节不一致")
            if frame["shadow_space_size"] < 0:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 shadow space 不能为负数")
            if frame["shadow_space_size"] != abi_shadow_space:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 shadow space 与 ABI 不一致: "
                    f"记录 {frame['shadow_space_size']}, 期望 {abi_shadow_space}"
                )
            if frame["stack_alignment"] <= 0:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口对齐必须为正数")
            if frame["stack_alignment"] != abi_stack_alignment:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口对齐与 ABI 不一致: "
                    f"记录 {frame['stack_alignment']}, 期望 {abi_stack_alignment}"
                )
            expected_size = frame["shadow_space_size"] + frame["stack_arg_bytes"]
            remainder = expected_size % frame["stack_alignment"]
            if remainder:
                expected_size += frame["stack_alignment"] - remainder
            if frame["aligned_size"] != expected_size:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口大小不一致: 记录 {frame['aligned_size']}, 期望 {expected_size}"
                )
            sub_rsp_size = len(encode_sub_rsp_imm32(frame["aligned_size"]))
            expected_frame_end_offset = frame["offset"] + sub_rsp_size
            if frame["end_offset"] != expected_frame_end_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 end_offset 不一致: "
                    f"记录 {frame['end_offset']}, 期望 {expected_frame_end_offset}"
                )
            expected_frame_end_rva = text_section["rva"] + expected_frame_end_offset
            if frame["end_rva"] != expected_frame_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 end_rva 不一致: "
                    f"记录 {frame['end_rva']}, 期望 {expected_frame_end_rva}"
                )
            expected_frame_end_va = text_section["va"] + expected_frame_end_offset
            if frame["end_va"] != expected_frame_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 end_va 不一致: "
                    f"记录 {frame['end_va']}, 期望 {expected_frame_end_va}"
                )
            if frame["offset"] < function_offset or frame["offset"] + sub_rsp_size > function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 sub rsp 越界: {frame['offset']}")
            if frame["offset"] in seen_call_frame_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口记录重复: {frame['offset']}")
            seen_call_frame_offsets.add(frame["offset"])
            sub_rsp_code = code[frame["offset"]:frame["offset"] + sub_rsp_size]
            if sub_rsp_code[:3] != b"\x48\x81\xEC":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 sub rsp opcode 不一致")
            actual_sub_hash = hashlib.sha256(sub_rsp_code).hexdigest()
            if frame["sub_code_sha256"] != actual_sub_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 sub_code_sha256 不一致: "
                    f"期望 {actual_sub_hash!r}, 实际 {frame['sub_code_sha256']!r}"
                )
            actual_size = int.from_bytes(sub_rsp_code[3:7], byteorder="little", signed=True)
            if actual_size != frame["aligned_size"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 sub rsp 大小不一致: 记录 {frame['aligned_size']}, 机器码 {actual_size}"
                )
            frame_instruction = instructions_by_offset.get(frame["offset"])
            if (
                frame_instruction is None
                or frame_instruction.get("source_op") != "call"
                or not isinstance(frame_instruction.get("asm"), str)
                or not frame_instruction["asm"].startswith("sub rsp, ")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口清单缺失")
            for instruction_field, frame_field in (
                ("end_offset", "end_offset"),
                ("end_rva", "end_rva"),
                ("end_va", "end_va"),
            ):
                if frame_instruction.get(instruction_field) != frame[frame_field]:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口清单范围不一致: "
                        f"{instruction_field} 记录 {frame_instruction.get(instruction_field)}, 栈窗口 {frame[frame_field]}"
                    )
            if (
                frame_instruction.get("source_pc") != frame.get("source_pc")
                or frame_instruction.get("source_line") != frame.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口来源位置与清单不一致")
            frame_instruction_index = instructions.index(frame_instruction)
            call_instruction = None
            call_instruction_index = None
            for candidate_index, candidate in enumerate(instructions[frame_instruction_index + 1:], start=frame_instruction_index + 1):
                asm = candidate.get("asm")
                if candidate.get("source_op") == "call" and isinstance(asm, str) and asm.startswith("call "):
                    call_instruction = candidate
                    call_instruction_index = candidate_index
                    break
            if call_instruction is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 call 清单缺失")
            call_asm = call_instruction["asm"]
            call_target = call_asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if call_target != target:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口目标与 call 清单不一致: 记录 {target}, 指令 {call_target}"
                )
            if (
                call_instruction.get("source_pc") != frame.get("source_pc")
                or call_instruction.get("source_line") != frame.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 call 来源位置与清单不一致")
            if frame["call_offset"] != call_instruction["offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_offset 与清单不一致: "
                    f"记录 {frame['call_offset']}, 清单 {call_instruction['offset']}"
                )
            if frame["call_end_offset"] != call_instruction["end_offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_end_offset 与清单不一致: "
                    f"记录 {frame['call_end_offset']}, 清单 {call_instruction['end_offset']}"
                )
            actual_call_hash = hashlib.sha256(code[frame["call_offset"]:frame["call_end_offset"]]).hexdigest()
            if frame["call_code_sha256"] != actual_call_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_code_sha256 不一致: "
                    f"期望 {actual_call_hash!r}, 实际 {frame['call_code_sha256']!r}"
                )
            expected_call_rva = text_section["rva"] + frame["call_offset"]
            if frame["call_rva"] != expected_call_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_rva 不一致: "
                    f"记录 {frame['call_rva']}, 期望 {expected_call_rva}"
                )
            expected_call_end_rva = text_section["rva"] + frame["call_end_offset"]
            if frame["call_end_rva"] != expected_call_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_end_rva 不一致: "
                    f"记录 {frame['call_end_rva']}, 期望 {expected_call_end_rva}"
                )
            expected_call_va = text_section["va"] + frame["call_offset"]
            if frame["call_va"] != expected_call_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_va 不一致: "
                    f"记录 {frame['call_va']}, 期望 {expected_call_va}"
                )
            expected_call_end_va = text_section["va"] + frame["call_end_offset"]
            if frame["call_end_va"] != expected_call_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_end_va 不一致: "
                    f"记录 {frame['call_end_va']}, 期望 {expected_call_end_va}"
                )
            if call_instruction_index is None or call_instruction_index + 1 >= len(instructions):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 清单缺失")
            add_instruction = instructions[call_instruction_index + 1]
            add_asm = add_instruction.get("asm")
            add_bytes = add_instruction.get("bytes")
            try:
                add_code = bytes.fromhex(add_bytes) if isinstance(add_bytes, str) else b""
            except ValueError as error:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp bytes 不是合法十六进制: {error}") from error
            if add_instruction.get("source_op") != "call" or add_asm != f"add rsp, {frame['aligned_size']}" or add_code[:3] != b"\x48\x81\xC4":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 清单不一致")
            add_size = int.from_bytes(add_code[3:7], byteorder="little", signed=True)
            if add_size != frame["aligned_size"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 大小不一致: 记录 {frame['aligned_size']}, 机器码 {add_size}"
                )
            if (
                add_instruction.get("source_pc") != frame.get("source_pc")
                or add_instruction.get("source_line") != frame.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 来源位置与清单不一致")
            if frame["add_offset"] != add_instruction["offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_offset 与清单不一致: "
                    f"记录 {frame['add_offset']}, 清单 {add_instruction['offset']}"
                )
            if frame["add_end_offset"] != add_instruction["end_offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_end_offset 与清单不一致: "
                    f"记录 {frame['add_end_offset']}, 清单 {add_instruction['end_offset']}"
                )
            actual_add_hash = hashlib.sha256(code[frame["add_offset"]:frame["add_end_offset"]]).hexdigest()
            if frame["add_code_sha256"] != actual_add_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_code_sha256 不一致: "
                    f"期望 {actual_add_hash!r}, 实际 {frame['add_code_sha256']!r}"
                )
            expected_add_rva = text_section["rva"] + frame["add_offset"]
            if frame["add_rva"] != expected_add_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_rva 不一致: "
                    f"记录 {frame['add_rva']}, 期望 {expected_add_rva}"
                )
            expected_add_end_rva = text_section["rva"] + frame["add_end_offset"]
            if frame["add_end_rva"] != expected_add_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_end_rva 不一致: "
                    f"记录 {frame['add_end_rva']}, 期望 {expected_add_end_rva}"
                )
            expected_add_va = text_section["va"] + frame["add_offset"]
            if frame["add_va"] != expected_add_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_va 不一致: "
                    f"记录 {frame['add_va']}, 期望 {expected_add_va}"
                )
            expected_add_end_va = text_section["va"] + frame["add_end_offset"]
            if frame["add_end_va"] != expected_add_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_end_va 不一致: "
                    f"记录 {frame['add_end_va']}, 期望 {expected_add_end_va}"
                )
        for frame_offset in expected_call_frame_offsets:
            if frame_offset not in seen_call_frame_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口缺少记录: {frame_offset}")
    for function in functions:
        name = function["name"]
        function_offset, function_size = function_ranges[name]
        function_end = function_offset + function_size
        relocations = function.get("relocations", [])
        if not isinstance(relocations, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} relocations 必须是列表")
        instructions = function.get("instructions", [])
        instructions_by_offset = {
            instruction.get("offset"): instruction
            for instruction in instructions
            if isinstance(instruction, dict)
            and isinstance(instruction.get("offset"), int)
            and not isinstance(instruction.get("offset"), bool)
        }
        seen_relocation_offsets: set[int] = set()
        for relocation_index, relocation in enumerate(relocations):
            if not isinstance(relocation, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} relocations[{relocation_index}] 必须是对象")
            extra_relocation_fields = sorted(set(relocation) - _MAP_RELOCATION_FIELDS)
            if extra_relocation_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} relocations[{relocation_index}] 存在未知字段: {', '.join(extra_relocation_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} relocations[{relocation_index}]", relocation)
            relocation_offset = relocation.get("offset")
            relocation_rva = relocation.get("rva")
            relocation_va = relocation.get("va")
            patch_offset = relocation.get("patch_offset")
            patch_rva = relocation.get("patch_rva")
            patch_va = relocation.get("patch_va")
            patch_end_offset = relocation.get("patch_end_offset")
            patch_end_rva = relocation.get("patch_end_rva")
            patch_end_va = relocation.get("patch_end_va")
            instruction_code_sha256 = relocation.get("instruction_code_sha256")
            patch_code_sha256 = relocation.get("patch_code_sha256")
            displacement = relocation.get("displacement")
            size = relocation.get("size")
            kind = relocation.get("kind")
            target = relocation.get("target")
            target_rva = relocation.get("target_rva")
            target_va = relocation.get("target_va")
            if not isinstance(relocation_offset, int) or isinstance(relocation_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 offset 必须是整数")
            if not isinstance(relocation_rva, int) or isinstance(relocation_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 rva 必须是整数")
            if not isinstance(relocation_va, int) or isinstance(relocation_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 va 必须是整数")
            if not isinstance(patch_offset, int) or isinstance(patch_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_offset 必须是整数")
            if not isinstance(patch_rva, int) or isinstance(patch_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_rva 必须是整数")
            if not isinstance(patch_va, int) or isinstance(patch_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_va 必须是整数")
            if not isinstance(patch_end_offset, int) or isinstance(patch_end_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_end_offset 必须是整数")
            if not isinstance(patch_end_rva, int) or isinstance(patch_end_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_end_rva 必须是整数")
            if not isinstance(patch_end_va, int) or isinstance(patch_end_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_end_va 必须是整数")
            if not isinstance(displacement, int) or isinstance(displacement, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 displacement 必须是整数")
            if not isinstance(size, int) or isinstance(size, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 size 必须是整数")
            if not isinstance(target_rva, int) or isinstance(target_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 target_rva 必须是整数")
            if not isinstance(target_va, int) or isinstance(target_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 target_va 必须是整数")
            for hash_field, hash_value in (
                ("instruction_code_sha256", instruction_code_sha256),
                ("patch_code_sha256", patch_code_sha256),
            ):
                if not isinstance(hash_value, str):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 {hash_field} 必须是字符串")
                if len(hash_value) != 64:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} rel32 {hash_field} 必须是 64 位十六进制字符串，"
                        f"实际长度 {len(hash_value)}"
                    )
                try:
                    bytes.fromhex(hash_value)
                except ValueError as error:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} rel32 {hash_field} 不是合法十六进制: {error}"
                    ) from error
            if kind not in {*_REL32_JUMP_OPCODES, "call_rel32"}:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补类型暂不支持: {kind!r}")
            if relocation_offset in seen_relocation_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补记录重复: {relocation_offset}")
            seen_relocation_offsets.add(relocation_offset)
            relocation_instruction = instructions_by_offset.get(relocation_offset)
            if relocation_instruction is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补指令清单缺失: {relocation_offset}")
            if (
                relocation_instruction.get("source_pc") != relocation.get("source_pc")
                or relocation_instruction.get("source_line") != relocation.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 来源位置与清单不一致")
            if not isinstance(target, str) or not target:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 target 必须是非空字符串")
            if target not in function_ranges and target not in function_labels[name]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补目标未知: {target}")
            expected_exit_probe_target = exit_probe_jump_targets_by_function.get(name, {}).get(relocation_offset)
            if expected_exit_probe_target is not None and (kind != "jne_rel32" or target != expected_exit_probe_target):
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} _exit 传播探针 jump 修补目标不一致: "
                    f"探针 {expected_exit_probe_target}, 修补记录 {target}"
                )
            if size != 4:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补字段大小必须为 4，实际 {size}")
            expected_relocation_rva = text_section["rva"] + relocation_offset
            if relocation_rva != expected_relocation_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 RVA 不一致: 记录 {relocation_rva}, 期望 {expected_relocation_rva}"
                )
            expected_relocation_va = text_section["va"] + relocation_offset
            if relocation_va != expected_relocation_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 VA 不一致: 记录 {relocation_va}, 期望 {expected_relocation_va}"
                )
            expected_patch_offset = relocation_offset + (len(_REL32_JUMP_OPCODES[kind]) if kind in _REL32_JUMP_OPCODES else 1)
            if patch_offset != expected_patch_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 修补字段偏移不一致: 记录 {patch_offset}, 期望 {expected_patch_offset}"
                )
            expected_patch_end_offset = patch_offset + size
            if patch_end_offset != expected_patch_end_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_end_offset 不一致: 记录 {patch_end_offset}, 期望 {expected_patch_end_offset}"
                )
            expected_patch_rva = text_section["rva"] + patch_offset
            if patch_rva != expected_patch_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_rva 不一致: 记录 {patch_rva}, 期望 {expected_patch_rva}"
                )
            expected_patch_end_rva = expected_patch_rva + size
            if patch_end_rva != expected_patch_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_end_rva 不一致: 记录 {patch_end_rva}, 期望 {expected_patch_end_rva}"
                )
            expected_patch_va = text_section["va"] + patch_offset
            if patch_va != expected_patch_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_va 不一致: 记录 {patch_va}, 期望 {expected_patch_va}"
                )
            expected_patch_end_va = expected_patch_va + size
            if patch_end_va != expected_patch_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_end_va 不一致: 记录 {patch_end_va}, 期望 {expected_patch_end_va}"
                )
            target_offset = function_ranges[target][0] if target in function_ranges else function_labels[name][target]["offset"]
            expected_target_rva = text_section["rva"] + target_offset
            if target_rva != expected_target_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 target_rva 不一致: 记录 {target_rva}, 期望 {expected_target_rva}"
                )
            expected_target_va = text_section["va"] + target_offset
            if target_va != expected_target_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 target_va 不一致: 记录 {target_va}, 期望 {expected_target_va}"
                )
            if relocation_offset < function_offset or relocation_offset >= function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 指令偏移越界: {relocation_offset}")
            if patch_offset < function_offset or patch_offset + size > function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补字段越界: {patch_offset}")
            opcode = code[relocation_offset:patch_offset]
            if kind in _REL32_JUMP_OPCODES and opcode != _REL32_JUMP_OPCODES[kind]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} {kind} opcode 不一致")
            if kind == "call_rel32" and opcode != b"\xE8":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call_rel32 opcode 不一致")
            actual_instruction_hash = hashlib.sha256(code[relocation_offset:patch_end_offset]).hexdigest()
            if instruction_code_sha256 != actual_instruction_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 instruction_code_sha256 不一致: "
                    f"期望 {actual_instruction_hash!r}, 实际 {instruction_code_sha256!r}"
                )
            actual_patch_hash = hashlib.sha256(code[patch_offset:patch_end_offset]).hexdigest()
            if patch_code_sha256 != actual_patch_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_code_sha256 不一致: "
                    f"期望 {actual_patch_hash!r}, 实际 {patch_code_sha256!r}"
                )
            actual_displacement = int.from_bytes(code[patch_offset:patch_offset + size], byteorder="little", signed=True)
            if actual_displacement != displacement:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 位移与机器码不一致: 记录 {displacement}, 机器码 {actual_displacement}"
                )
            expected_target_from_displacement = patch_offset + size + displacement
            if expected_target_from_displacement != target_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 目标与位移不一致: 记录目标 {target_offset}, 位移目标 {expected_target_from_displacement}"
                )
            relocation_asm = relocation_instruction.get("asm")
            expected_asm_prefix = {**_REL32_JUMP_ASM_PREFIXES, "call_rel32": "call "}[kind]
            if not isinstance(relocation_asm, str) or not relocation_asm.startswith(expected_asm_prefix):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补指令清单类型不一致")
            instruction_target = relocation_asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if instruction_target != target:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 目标与清单不一致: 记录 {target}, 指令 {instruction_target}"
                )
        for relocation_offset, expected_kind in expected_relocations_by_function[name].items():
            if relocation_offset not in seen_relocation_offsets:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 指令缺少修补记录: offset {relocation_offset}, 类型 {expected_kind}"
                )
    if global_frame_owners and not global_owner_slots:
        owner = next(iter(global_frame_owners))
        raise NativeCodegenError(f"native 机器码 map 函数 {owner} 初始化 R11 global frame 但没有声明全局栈槽")
    for function_name, slots in non_owner_global_slots.items():
        for slot_name, slot_offset, slot_size in slots:
            owner_slot = global_owner_slots.get(slot_name)
            if owner_slot is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {function_name} 全局栈槽缺少 global-frame owner 声明: {slot_name}")
            if owner_slot != (slot_offset, slot_size):
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {function_name} 全局栈槽 {slot_name} 与 global-frame owner 布局不一致"
                )
    for function in functions:
        name = function["name"]
        stack_slots = function.get("stack_slots", [])
        expected_value_locations = [
            _native_value_location(
                name,
                NativeStackSlotAllocation(
                    name=str(slot["name"]),
                    offset=int(slot["offset"]),
                    size=int(slot["size"]),
                ),
            )
            for slot in stack_slots
        ]
        if "value_locations" not in function:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 缺少 value_locations 字段")
        value_locations = function["value_locations"]
        if not isinstance(value_locations, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations 必须是列表")
        if len(value_locations) != len(expected_value_locations):
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} value_locations 数量不一致: "
                f"记录 {len(value_locations)}, 期望 {len(expected_value_locations)}"
            )
        seen_value_locations: set[str] = set()
        for location_index, (location, expected_location) in enumerate(zip(value_locations, expected_value_locations)):
            if not isinstance(location, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations[{location_index}] 必须是对象")
            extra_location_fields = sorted(set(location) - _MAP_VALUE_LOCATION_FIELDS)
            if extra_location_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} value_locations[{location_index}] 存在未知字段: "
                    f"{', '.join(extra_location_fields)}"
                )
            missing_location_fields = sorted(_MAP_VALUE_LOCATION_FIELDS - set(location))
            if missing_location_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} value_locations[{location_index}] 缺少字段: "
                    f"{', '.join(missing_location_fields)}"
                )
            location_name = location["name"]
            if not isinstance(location_name, str) or not location_name:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations[{location_index}].name 必须是非空字符串")
            if location_name in seen_value_locations:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations 重复: {location_name}")
            seen_value_locations.add(location_name)
            for field in ("kind", "index", "storage", "base_register"):
                if not isinstance(location[field], str) or not location[field]:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} value_locations[{location_index}].{field} 必须是非空字符串"
                    )
            for field in ("offset", "size"):
                if not isinstance(location[field], int) or isinstance(location[field], bool):
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} value_locations[{location_index}].{field} 必须是整数"
                    )
            if location != expected_location:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} value_locations[{location_index}] 与 stack_slots 不一致: "
                    f"记录 {location!r}, 期望 {expected_location!r}"
                )
    if entry not in function_ranges:
        raise NativeCodegenError(f"native 机器码 map 入口函数不在 functions 中: {entry}")
    if function_ranges[entry][0] != entry_offset:
        raise NativeCodegenError(
            f"native 机器码 map 入口偏移与函数偏移不一致: entry_offset {entry_offset}, 函数偏移 {function_ranges[entry][0]}"
        )
    symbols = metadata.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise NativeCodegenError("native 机器码 map 字段 symbols 必须是非空列表")
    seen_symbols: set[str] = set()
    entry_symbol_count = 0
    for index, symbol in enumerate(symbols):
        if not isinstance(symbol, dict):
            raise NativeCodegenError(f"native 机器码 map symbols[{index}] 必须是对象")
        extra_symbol_fields = sorted(set(symbol) - _MAP_SYMBOL_FIELDS)
        if extra_symbol_fields:
            raise NativeCodegenError(
                f"native 机器码 map symbols[{index}] 存在未知字段: {', '.join(extra_symbol_fields)}"
            )
        name = symbol.get("name")
        if not isinstance(name, str) or not name:
            raise NativeCodegenError(f"native 机器码 map symbols[{index}].name 必须是非空字符串")
        if name in seen_symbols:
            raise NativeCodegenError(f"native 机器码 map 符号重复: {name}")
        seen_symbols.add(name)
        if symbol.get("kind") != "function":
            raise NativeCodegenError(f"native 机器码 map 符号 {name} 类型暂不支持: {symbol.get('kind')!r}")
        if name not in function_ranges:
            raise NativeCodegenError(f"native 机器码 map 符号引用未知函数: {name}")
        return_type = symbol.get("return_type")
        if not isinstance(return_type, str) or return_type not in _SUPPORTED_RETURN_TYPES:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} return_type 暂不支持: {return_type!r}")
        param_types = symbol.get("param_types")
        if not isinstance(param_types, list) or any(not isinstance(item, str) for item in param_types):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} param_types 必须是字符串列表")
        for param_index, param_type in enumerate(param_types):
            if param_type not in _SUPPORTED_VALUE_TYPES:
                raise NativeCodegenError(
                    f"native 机器码 map 符号 {name} 第 {param_index} 个参数暂不支持类型: {param_type!r}"
                )
        expected_return_type, expected_param_types = function_signatures[name]
        if return_type != expected_return_type:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} return_type 与函数签名不一致: "
                f"符号 {return_type!r}, 函数 {expected_return_type!r}"
            )
        if param_types != expected_param_types:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} param_types 与函数签名不一致: "
                f"符号 {param_types}, 函数 {expected_param_types}"
            )
        offset = symbol.get("offset")
        size = symbol.get("size")
        end_offset = symbol.get("end_offset")
        rva = symbol.get("rva")
        end_rva = symbol.get("end_rva")
        va = symbol.get("va")
        end_va = symbol.get("end_va")
        symbol_hash = symbol.get("code_sha256")
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} offset 必须是整数")
        if not isinstance(size, int) or isinstance(size, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} size 必须是整数")
        if not isinstance(end_offset, int) or isinstance(end_offset, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} end_offset 必须是整数")
        if not isinstance(rva, int) or isinstance(rva, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} rva 必须是整数")
        if not isinstance(end_rva, int) or isinstance(end_rva, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} end_rva 必须是整数")
        if not isinstance(va, int) or isinstance(va, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} va 必须是整数")
        if not isinstance(end_va, int) or isinstance(end_va, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} end_va 必须是整数")
        if not isinstance(symbol_hash, str):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} code_sha256 必须是字符串")
        if (offset, size) != function_ranges[name]:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} 范围与函数不一致")
        expected_symbol_end_offset = offset + size
        if end_offset != expected_symbol_end_offset:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} end_offset 不一致: 记录 {end_offset}, 期望 {expected_symbol_end_offset}"
            )
        expected_symbol_rva = text_section["rva"] + offset
        if rva != expected_symbol_rva:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} RVA 不一致: 记录 {rva}, 期望 {expected_symbol_rva}"
            )
        expected_symbol_end_rva = expected_symbol_rva + size
        if end_rva != expected_symbol_end_rva:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} end_rva 不一致: 记录 {end_rva}, 期望 {expected_symbol_end_rva}"
            )
        expected_symbol_va = text_section["va"] + offset
        if va != expected_symbol_va:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} VA 不一致: 记录 {va}, 期望 {expected_symbol_va}"
            )
        expected_symbol_end_va = expected_symbol_va + size
        if end_va != expected_symbol_end_va:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} end_va 不一致: 记录 {end_va}, 期望 {expected_symbol_end_va}"
            )
        if len(symbol_hash) != 64:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} code_sha256 必须是 64 位十六进制字符串，实际长度 {len(symbol_hash)}")
        try:
            bytes.fromhex(symbol_hash)
        except ValueError as error:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} code_sha256 不是合法十六进制: {error}") from error
        actual_symbol_hash = hashlib.sha256(code[offset:offset + size]).hexdigest()
        if symbol_hash != actual_symbol_hash:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} code_sha256 不一致: 期望 {actual_symbol_hash!r}, 实际 {symbol_hash!r}"
            )
        is_entry = symbol.get("is_entry")
        if not isinstance(is_entry, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} is_entry 必须是布尔值")
        if is_entry:
            entry_symbol_count += 1
            if name != entry:
                raise NativeCodegenError(f"native 机器码 map 符号 {name} 入口标记与 entry 不一致")
    if entry_symbol_count != 1:
        raise NativeCodegenError(f"native 机器码 map 入口符号数量必须为 1，实际 {entry_symbol_count}")
    missing_symbols = sorted(set(function_ranges) - seen_symbols)
    if missing_symbols:
        raise NativeCodegenError(f"native 机器码 map 符号表缺少函数: {', '.join(missing_symbols)}")


def validate_native_text_section_map_bytes(text_raw: bytes, metadata: dict[str, object]) -> None:
    """校验补零后的 PE .text raw section 与结构化 map 一致。"""
    if not isinstance(text_raw, bytes):
        raise NativeCodegenError(f"native .text raw section 必须是 bytes，实际 {type(text_raw).__name__}")
    if not isinstance(metadata, dict):
        raise NativeCodegenError(f"native .text raw section map 必须是对象，实际 {type(metadata).__name__}")
    sections = metadata.get("sections")
    if not isinstance(sections, list) or not sections:
        raise NativeCodegenError("native .text raw section map 字段 sections 必须是非空列表")
    text_sections = [section for section in sections if isinstance(section, dict) and section.get("name") == ".text"]
    if len(text_sections) != 1:
        raise NativeCodegenError(f"native .text raw section map .text section 数量必须为 1，实际 {len(text_sections)}")
    text_section = text_sections[0]
    code_size = metadata.get("code_size")
    raw_size_aligned = text_section.get("raw_size_aligned")
    raw_padding_size = text_section.get("raw_padding_size")
    raw_padded_sha256 = text_section.get("raw_padded_sha256")
    if not isinstance(code_size, int) or isinstance(code_size, bool):
        raise NativeCodegenError("native .text raw section map 字段 code_size 必须是整数")
    if not isinstance(raw_size_aligned, int) or isinstance(raw_size_aligned, bool):
        raise NativeCodegenError("native .text raw section map .text section raw_size_aligned 必须是整数")
    if not isinstance(raw_padding_size, int) or isinstance(raw_padding_size, bool):
        raise NativeCodegenError("native .text raw section map .text section raw_padding_size 必须是整数")
    if not isinstance(raw_padded_sha256, str):
        raise NativeCodegenError("native .text raw section map .text section raw_padded_sha256 必须是字符串")
    if code_size < 0:
        raise NativeCodegenError(f"native .text raw section map 字段 code_size 必须是非负整数，实际 {code_size}")
    if raw_size_aligned < code_size:
        raise NativeCodegenError(
            f"native .text raw section map .text section raw_size_aligned 小于 code_size: "
            f"{raw_size_aligned} < {code_size}"
        )
    expected_padding_size = raw_size_aligned - code_size
    if raw_padding_size != expected_padding_size:
        raise NativeCodegenError(
            f"native .text raw section map .text section raw_padding_size 不一致: "
            f"期望 {expected_padding_size}, 实际 {raw_padding_size}"
        )
    if len(text_raw) != raw_size_aligned:
        raise NativeCodegenError(
            f"native .text raw section 大小不一致: 期望 {raw_size_aligned}, 实际 {len(text_raw)}"
        )
    if text_raw[code_size:] != bytes(raw_padding_size):
        raise NativeCodegenError("native .text raw section 尾部补零区域不一致")
    actual_padded_hash = hashlib.sha256(text_raw).hexdigest()
    if raw_padded_sha256 != actual_padded_hash:
        raise NativeCodegenError(
            f"native .text raw section raw_padded_sha256 不一致: "
            f"期望 {raw_padded_sha256!r}, 实际 {actual_padded_hash!r}"
        )
    validate_native_code_map_bytes(text_raw[:code_size], metadata)


def _validate_source_location_fields(owner: str, item: dict[str, object]) -> None:
    """校验 map 来源位置字段。"""
    for field in ("source_pc", "source_line"):
        if field not in item:
            raise NativeCodegenError(f"{owner}.{field} 缺失")
        value = item[field]
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"{owner}.{field} 必须是非负整数或 null，实际 {type(value).__name__}")
        if value < 0:
            raise NativeCodegenError(f"{owner}.{field} 必须是非负整数或 null，实际 {value}")


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
                argument_registers=tuple(self.abi.registers.argument_registers[:self.function_param_counts.get(self.function.name, len(self.function.params))]),
                frame_pointer=self.abi.registers.frame_pointer,
                stack_pointer=self.abi.registers.stack_pointer,
                return_register=self.abi.registers.return_register,
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
                if cast_constant is None:
                    raise self._node_error(instruction, f"native 机器码 MVP 暂不支持动态窄化整数 cast 到 {target_type}")
                if cast_constant < minimum or cast_constant > maximum:
                    raise self._node_error(
                        instruction,
                        f"native 机器码 MVP cast 到 {target_type} 的立即数超出范围: {cast_constant}，允许 {minimum}..{maximum}",
                    )
            if instruction.result is not None and instruction.result.kind == "vreg":
                if cast_constant is None:
                    self.constant_vregs.pop(str(instruction.result.value.name), None)
                else:
                    self.constant_vregs[str(instruction.result.value.name)] = cast_constant
            cast_note = f" ; cast to {target_type}" if target_type else ""
            self._load_operand_to_rax(instruction.args[0], instruction)
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
            if instruction.args[1].kind == "imm" and int(instruction.args[1].value) == 0:
                raise self._node_error(instruction, "native 机器码 MVP 暂不生成除数为 0 的 idiv/imod 机器码")
            self._emit(encode_cqo(), "cqo", instruction.op, instruction.source_pc, instruction.source_line)
            self._emit(encode_idiv_r10(), "idiv r10", instruction.op, instruction.source_pc, instruction.source_line)
            if instruction.op == "imod":
                self._emit_python_modulo_adjustment(instruction)
            self._remember_static_result(instruction)
            self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)
            return
        self._emit(code, _BINARY_OP_ASM[instruction.op], instruction.op, instruction.source_pc, instruction.source_line)
        self._remember_static_result(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", instruction.op, instruction.source_pc, instruction.source_line)

    def _lower_neg(self, instruction: MachineInstruction) -> None:
        """生成整数取负。"""
        result = self._result_slot_offset(instruction)
        self._load_operand_to_rax(instruction.args[0], instruction)
        self._emit(encode_neg_rax(), "neg rax", "neg", instruction.source_pc, instruction.source_line)
        self._remember_static_result(instruction)
        self._emit(encode_mov_rbp_offset_from_rax(result), f"mov [rbp-{result}], rax", "neg", instruction.source_pc, instruction.source_line)

    def _lower_not_bool(self, instruction: MachineInstruction) -> None:
        """生成 C 风格逻辑非。"""
        result = self._result_slot_offset(instruction)
        self._load_operand_to_rax(instruction.args[0], instruction)
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

    def _emit_python_modulo_adjustment(self, instruction: MachineInstruction) -> None:
        """生成与 VM/Python 余数语义一致的 imod 调整。"""
        done_label = self._synthetic_label("imod_done")
        self._emit(encode_test_rdx_rdx(), "test rdx, rdx ; imod remainder", "imod", instruction.source_pc, instruction.source_line)
        self._emit_pending_jump("je", done_label, instruction.source_pc, instruction.source_line, source_op="imod")
        self._emit(encode_mov_rax_rdx(), "mov rax, rdx", "imod", instruction.source_pc, instruction.source_line)
        self._emit(encode_xor_rax_r10(), "xor rax, r10 ; imod sign check", "imod", instruction.source_pc, instruction.source_line)
        self._emit_pending_jump("jns", done_label, instruction.source_pc, instruction.source_line, source_op="imod")
        self._emit(encode_add_rdx_r10(), "add rdx, r10 ; imod VM remainder", "imod", instruction.source_pc, instruction.source_line)
        self.block_offsets[done_label] = len(self.code)
        self._emit(b"", f"{done_label}:", "label", instruction.source_pc, instruction.source_line)
        self._emit(encode_mov_rax_rdx(), "mov rax, rdx", "imod", instruction.source_pc, instruction.source_line)

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
        if callee_return_type in {"int64", "bool64"} and instruction.result is None:
            raise self._node_error(instruction, f"native 机器码 MVP {callee_return_type} 调用 {callee} 必须携带结果")
        if callee_return_type in {"int64", "bool64"} and instruction.result is not None and instruction.result.type_hint != callee_return_type:
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
        if return_register is not None and self.abi is not None and return_register != self.abi.registers.return_register:
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
                expected_location = self.abi.argument_location(index).__dict__
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
            if self.function.return_type in {"int64", "bool64"} and len(terminator.args) != 1:
                raise self._node_error(terminator, f"native 机器码 MVP {self.function.return_type} 函数 ret 必须携带 1 个返回值")
            if terminator.args:
                if not _is_return_type_compatible(self.function.return_type, terminator.args[0].type_hint):
                    raise self._node_error(
                        terminator,
                        f"native 机器码 MVP {self.function.return_type} 函数 ret 返回值类型不能是 {terminator.args[0].type_hint}",
                    )
                self._load_operand_to_rax(terminator.args[0], terminator)
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


def _format_function(function: NativeCodeFunction, functions: dict[str, NativeCodeFunction]) -> list[str]:
    """生成单个机器码函数的 dump 文本。"""
    text_rva = 4096
    image_base = 0x140000000
    function_rva = text_rva + function.offset
    function_va = image_base + function_rva
    function_end_rva = function_rva + len(function.code)
    function_end_va = image_base + function_end_rva
    param_types = ", ".join(function.param_types) if function.param_types else "-"
    has_global_slots = any(slot.name.startswith("global[") for slot in function.stack_slots)
    initializes_global_frame = any(
        instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
        for instruction in function.instructions
    )
    lines = [
        f"### `{function.name}`\n\n",
        f"- 函数偏移: `{function.offset:04X}`\n",
        f"- 函数范围: `[{function.offset:04X}, {function.offset + len(function.code):04X})`\n",
        f"- 函数 RVA 范围: `[0x{function_rva:08X}, 0x{function_end_rva:08X})`\n",
        f"- 函数 VA 范围: `[0x{function_va:016X}, 0x{function_end_va:016X})`\n",
        f"- 返回类型: `{function.return_type}`\n",
        f"- 形参类型: `{param_types}`\n",
        f"- 栈帧大小: `{function.frame_size}` bytes\n",
        f"- 机器码大小: `{len(function.code)}` bytes\n\n",
        "#### 寄存器分配\n\n",
        f"- 策略: `{function.register_allocation.strategy}`\n",
        f"- 临时寄存器: `{ '`, `'.join(function.register_allocation.temporary_registers) }`\n",
        f"- 参数寄存器: `{ '`, `'.join(function.register_allocation.argument_registers) if function.register_allocation.argument_registers else '-' }`\n",
        f"- 返回寄存器: `{function.register_allocation.return_register}`\n",
        f"- 帧指针: `{function.register_allocation.frame_pointer}`\n",
        f"- 栈指针: `{function.register_allocation.stack_pointer}`\n",
        f"- 虚拟寄存器保存: `{function.register_allocation.virtual_register_storage}`\n",
        f"- 局部变量保存: `{function.register_allocation.local_storage}`\n\n",
    ]
    if has_global_slots:
        if initializes_global_frame and function.name == "<module>":
            owner_text = "当前函数初始化，当前函数内 `global[...]` 使用 `[rbp-offset]`，被调用户函数使用 `[r11-offset]`"
        elif initializes_global_frame:
            owner_text = "当前函数初始化，`global[...]` 通过 `[r11-offset]` 访问"
        else:
            owner_text = "由 global-frame owner 初始化，`global[...]` 通过 `[r11-offset]` 访问"
        lines.append(f"- 全局帧寄存器: `{function.register_allocation.global_frame_register}` ({owner_text})\n")
    lines.extend([
        "\n",
        "#### 栈槽分配\n\n",
        "| 名称 | 位置 | 大小 |\n",
        "| --- | --- | --- |\n",
    ])
    if function.stack_slots:
        for slot in function.stack_slots:
            base = "r11" if function.name != "<module>" and slot.name.startswith("global[") else "rbp"
            lines.append(f"| `{slot.name}` | `[{base}-{slot.offset}]` | `{slot.size}` |\n")
    else:
        lines.append("| `-` | `-` | `0` |\n")
    lines.extend([
        "\n",
        "#### 值位置摘要\n\n",
        "| 名称 | 种类 | 索引 | 保存位置 | 基址寄存器 | 偏移 | 大小 |\n",
        "| --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.stack_slots:
        for slot in function.stack_slots:
            location = _native_value_location(function.name, slot)
            lines.append(
                f"| `{location['name']}` | `{location['kind']}` | `{location['index']}` | "
                f"`{location['storage']}` | `{location['base_register']}` | `{location['offset']}` | "
                f"`{location['size']}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` | `-` | `0` |\n")
    label_instructions = [
        instruction
        for instruction in function.instructions
        if instruction.source_op == "label" and instruction.asm.endswith(":")
    ]
    label_offsets = {instruction.asm[:-1]: instruction.offset for instruction in label_instructions}
    lines.extend([
        "\n",
        "#### 标签摘要\n\n",
        "| 名称 | 偏移 | RVA | VA | 来源 |\n",
        "| --- | --- | --- | --- | --- |\n",
    ])
    if label_instructions:
        for instruction in label_instructions:
            label_rva = text_rva + instruction.offset
            label_va = image_base + label_rva
            details = []
            if instruction.source_pc is not None:
                details.append(f"pc {instruction.source_pc}")
            if instruction.source_line is not None:
                details.append(f"line {instruction.source_line}")
            source = ", ".join(details) if details else "-"
            lines.append(
                f"| `{instruction.asm[:-1]}` | `{instruction.offset:04X}` | `0x{label_rva:08X}` | "
                f"`0x{label_va:016X}` | `{source}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` |\n")
    lines.extend([
        "\n",
        "#### 调用栈窗口\n\n",
        "| 偏移 | 结束偏移 | Sub SHA-256 | Call 偏移 | Call 结束 | Call SHA-256 | Add 偏移 | Add 结束 | Add SHA-256 | RVA | End RVA | VA | End VA | Call RVA 范围 | Call VA 范围 | Add RVA 范围 | Add VA 范围 | 目标 | 参数 | 实参类型 | 形参类型 | 寄存器参数 | 栈参数 | Shadow space | 栈实参字节 | 对齐后大小 | 对齐 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.call_frames:
        for item in function.call_frames:
            item_end_offset = item.offset + len(encode_sub_rsp_imm32(item.aligned_size))
            item_local_offset = item.offset - function.offset
            item_local_end_offset = item_end_offset - function.offset
            sub_code_sha256 = hashlib.sha256(function.code[item_local_offset:item_local_end_offset]).hexdigest()
            item_rva = text_rva + item.offset
            item_end_rva = text_rva + item_end_offset
            item_va = image_base + item_rva
            item_end_va = image_base + item_end_rva
            call_offset = f"{item.call_offset:04X}" if item.call_offset is not None else "-"
            call_end_offset = f"{item.call_end_offset:04X}" if item.call_end_offset is not None else "-"
            add_offset = f"{item.add_offset:04X}" if item.add_offset is not None else "-"
            add_end_offset = f"{item.add_end_offset:04X}" if item.add_end_offset is not None else "-"
            if item.call_offset is None or item.call_end_offset is None:
                call_rva_range = "-"
                call_va_range = "-"
                call_code_sha256 = "-"
            else:
                call_local_offset = item.call_offset - function.offset
                call_local_end_offset = item.call_end_offset - function.offset
                call_code_sha256 = hashlib.sha256(function.code[call_local_offset:call_local_end_offset]).hexdigest()
                call_rva = text_rva + item.call_offset
                call_end_rva = text_rva + item.call_end_offset
                call_rva_range = f"0x{call_rva:08X}-0x{call_end_rva:08X}"
                call_va_range = f"0x{image_base + call_rva:016X}-0x{image_base + call_end_rva:016X}"
            if item.add_offset is None or item.add_end_offset is None:
                add_rva_range = "-"
                add_va_range = "-"
                add_code_sha256 = "-"
            else:
                add_local_offset = item.add_offset - function.offset
                add_local_end_offset = item.add_end_offset - function.offset
                add_code_sha256 = hashlib.sha256(function.code[add_local_offset:add_local_end_offset]).hexdigest()
                add_rva = text_rva + item.add_offset
                add_end_rva = text_rva + item.add_end_offset
                add_rva_range = f"0x{add_rva:08X}-0x{add_end_rva:08X}"
                add_va_range = f"0x{image_base + add_rva:016X}-0x{image_base + add_end_rva:016X}"
            details = []
            if item.source_pc is not None:
                details.append(f"pc {item.source_pc}")
            if item.source_line is not None:
                details.append(f"line {item.source_line}")
            target = item.target if not details else f"{item.target} ({', '.join(details)})"
            arg_types = ", ".join(item.arg_types) if item.arg_types else "-"
            param_types = ", ".join(item.param_types) if item.param_types else "-"
            lines.append(
                f"| `{item.offset:04X}` | `{item_end_offset:04X}` | `{sub_code_sha256}` | "
                f"`{call_offset}` | `{call_end_offset}` | `{call_code_sha256}` | "
                f"`{add_offset}` | `{add_end_offset}` | `{add_code_sha256}` | `0x{item_rva:08X}` | "
                f"`0x{item_end_rva:08X}` | `0x{item_va:016X}` | `0x{item_end_va:016X}` | "
                f"`{call_rva_range}` | `{call_va_range}` | `{add_rva_range}` | `{add_va_range}` | `{target}` | "
                f"`{item.arg_count}` | `{arg_types}` | `{param_types}` | `{item.register_arg_count}` | `{item.stack_arg_count}` | "
                f"`{item.shadow_space_size}` | `{item.stack_arg_bytes}` | "
                f"`{item.aligned_size}` | `{item.stack_alignment}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `0` | `-` | `-` | `0` | `0` | `0` | `0` | `0` | `0` |\n")
    lines.extend([
        "\n",
        "#### rel32 修补记录\n\n",
        "| 指令偏移 | 指令 RVA | 指令 VA | 指令 SHA-256 | 字段偏移 | 字段结束 | 字段 RVA | 字段结束 RVA | 字段 VA | 字段结束 VA | Patch SHA-256 | 类型 | 目标 | 目标 RVA | 目标 VA | 位移 | 字段大小 | 来源 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.relocations:
        for item in function.relocations:
            item_rva = text_rva + item.offset
            item_va = image_base + item_rva
            patch_rva = text_rva + item.patch_offset
            patch_va = image_base + patch_rva
            patch_end_offset = item.patch_offset + item.size
            patch_end_rva = patch_rva + item.size
            patch_end_va = patch_va + item.size
            local_offset = item.offset - function.offset
            local_patch_offset = item.patch_offset - function.offset
            local_patch_end_offset = patch_end_offset - function.offset
            instruction_code_sha256 = hashlib.sha256(function.code[local_offset:local_patch_end_offset]).hexdigest()
            patch_code_sha256 = hashlib.sha256(function.code[local_patch_offset:local_patch_end_offset]).hexdigest()
            target_function = functions.get(item.target)
            target_offset = target_function.offset if target_function is not None else label_offsets.get(item.target)
            target_rva = "-" if target_offset is None else f"0x{text_rva + target_offset:08X}"
            target_va = "-" if target_offset is None else f"0x{image_base + text_rva + target_offset:016X}"
            details = []
            if item.source_pc is not None:
                details.append(f"pc {item.source_pc}")
            if item.source_line is not None:
                details.append(f"line {item.source_line}")
            source = ", ".join(details) if details else "-"
            lines.append(
                f"| `{item.offset:04X}` | `0x{item_rva:08X}` | `0x{item_va:016X}` | `{instruction_code_sha256}` | "
                f"`{item.patch_offset:04X}` | "
                f"`{patch_end_offset:04X}` | `0x{patch_rva:08X}` | `0x{patch_end_rva:08X}` | "
                f"`0x{patch_va:016X}` | `0x{patch_end_va:016X}` | `{patch_code_sha256}` | `{item.kind}` | `{item.target}` | "
                f"`{target_rva}` | `{target_va}` | `{item.displacement:+d}` | `{item.size}` | `{source}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `0` | `0` | `-` |\n")
    lines.extend([
        "\n",
        "#### _exit 传播探针\n\n",
        "| Call 偏移 | Call 结束 | Call SHA-256 | Call RVA | Call End RVA | Call VA | Call End VA | Test 偏移 | Test 结束 | Test SHA-256 | Test RVA | Test End RVA | Test VA | Test End VA | Jump 偏移 | Jump 结束 | Jump SHA-256 | Jump RVA | Jump End RVA | Jump VA | Jump End VA | 目标 | 传播标签 | 来源 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.exit_probes:
        for item in function.exit_probes:
            call_end_offset = item.call_offset + _CALL_REL32_SIZE
            call_local_offset = item.call_offset - function.offset
            call_local_end_offset = call_end_offset - function.offset
            call_code_sha256 = hashlib.sha256(function.code[call_local_offset:call_local_end_offset]).hexdigest()
            call_rva = text_rva + item.call_offset
            call_end_rva = text_rva + call_end_offset
            call_va = image_base + call_rva
            call_end_va = image_base + call_end_rva
            test_end_offset = item.test_offset + _TEST_RDX_RDX_SIZE
            test_local_offset = item.test_offset - function.offset
            test_local_end_offset = test_end_offset - function.offset
            test_code_sha256 = hashlib.sha256(function.code[test_local_offset:test_local_end_offset]).hexdigest()
            test_rva = text_rva + item.test_offset
            test_end_rva = text_rva + test_end_offset
            test_va = image_base + test_rva
            test_end_va = image_base + test_end_rva
            jump_end_offset = item.jump_offset + _JNE_REL32_SIZE
            jump_local_offset = item.jump_offset - function.offset
            jump_local_end_offset = jump_end_offset - function.offset
            jump_code_sha256 = hashlib.sha256(function.code[jump_local_offset:jump_local_end_offset]).hexdigest()
            jump_rva = text_rva + item.jump_offset
            jump_end_rva = text_rva + jump_end_offset
            jump_va = image_base + jump_rva
            jump_end_va = image_base + jump_end_rva
            details = []
            if item.source_pc is not None:
                details.append(f"pc {item.source_pc}")
            if item.source_line is not None:
                details.append(f"line {item.source_line}")
            source = ", ".join(details) if details else "-"
            lines.append(
                f"| `{item.call_offset:04X}` | `{call_end_offset:04X}` | `{call_code_sha256}` | "
                f"`0x{call_rva:08X}` | `0x{call_end_rva:08X}` | `0x{call_va:016X}` | `0x{call_end_va:016X}` | "
                f"`{item.test_offset:04X}` | `{test_end_offset:04X}` | `{test_code_sha256}` | "
                f"`0x{test_rva:08X}` | `0x{test_end_rva:08X}` | `0x{test_va:016X}` | `0x{test_end_va:016X}` | "
                f"`{item.jump_offset:04X}` | `{jump_end_offset:04X}` | `{jump_code_sha256}` | "
                f"`0x{jump_rva:08X}` | `0x{jump_end_rva:08X}` | `0x{jump_va:016X}` | `0x{jump_end_va:016X}` | "
                f"`{item.target}` | `{item.probe_label}` | `{source}` |\n"
            )
    else:
        lines.append(
            "| `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | "
            "`-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` |\n"
        )
    lines.extend([
        "\n",
        "#### 机器码清单\n\n",
        "| 偏移 | End offset | RVA | VA | End RVA | End VA | 字节 | SHA-256 | 伪汇编 | 来源 | 来源属性 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    for instruction in function.instructions:
        instruction_rva = text_rva + instruction.offset
        instruction_va = image_base + instruction_rva
        instruction_end_rva = instruction_rva + len(instruction.code)
        instruction_end_va = image_base + instruction_end_rva
        byte_text = " ".join(f"{item:02X}" for item in instruction.code)
        source = instruction.source_op
        details = []
        if instruction.source_pc is not None:
            details.append(f"pc {instruction.source_pc}")
        if instruction.source_line is not None:
            details.append(f"line {instruction.source_line}")
        if details:
            source += " (" + ", ".join(details) + ")"
        source_attrs = "-"
        if instruction.source_attrs:
            source_attrs = json.dumps(
                instruction.source_attrs,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        lines.append(
            f"| `{instruction.offset:04X}` | `{instruction.offset + len(instruction.code):04X}` | "
            f"`0x{instruction_rva:08X}` | `0x{instruction_va:016X}` | "
            f"`0x{instruction_end_rva:08X}` | `0x{instruction_end_va:016X}` | `{byte_text}` | "
            f"`{hashlib.sha256(instruction.code).hexdigest()}` | `{instruction.asm}` | `{source}` | `{source_attrs}` |\n"
        )
    lines.append("\n")
    return lines


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

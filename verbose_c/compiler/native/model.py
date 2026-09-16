"""Native 机器码数据模型与符号、栈槽描述。"""

from dataclasses import (
    dataclass,
    field,
)
from verbose_c.compiler.native.abi import (
    WINDOWS_X64_ABI,
    WindowsX64ABI,
)
from verbose_c.compiler.native.errors import NativeCodegenError
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
    runtime: dict[str, object] = field(default_factory=dict)
    aot: bool = False


def native_program_symbols(program: NativeCodeProgram) -> list[NativeSymbol]:
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


def native_symbol_function(program: NativeCodeProgram, symbol: NativeSymbol) -> NativeCodeFunction:
    """取得 native 符号对应函数。"""
    function = program.functions.get(symbol.name)
    if function is None:
        raise NativeCodegenError(f"native 机器码符号表引用未知函数: {symbol.name}")
    return function


def native_value_location(function_name: str, slot: NativeStackSlotAllocation) -> dict[str, object]:
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

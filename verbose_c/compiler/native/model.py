"""Native 机器码数据模型与符号、栈槽描述。"""

from dataclasses import (
    dataclass,
    field,
)
from verbose_c.compiler.native.abi import (
    ARRAY_ELEMENT_TYPES,
    MAX_ARRAY_FRAME_SIZE,
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
    array_length: int | None = None
    element_type: str | None = None


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
    elif slot.name.startswith("array[") and slot.name.endswith("]"):
        kind = "array"
        index = slot.name[6:-1]
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


def native_stack_slot_map(slot: NativeStackSlotAllocation) -> dict[str, object]:
    """将栈槽及可选的数组来源信息写入产物元数据。"""
    result = {"name": slot.name, "offset": slot.offset, "size": slot.size}
    if slot.array_length is not None or slot.element_type is not None:
        result.update(array_length=slot.array_length, element_type=slot.element_type)
    return result


def validate_native_array_layout(name: str, slots: list[dict], instructions: list[dict], frame_size: int) -> None:
    """验证产物的数组布局、来源元数据与实际寻址字节一致。

    Args:
        name: 当前函数名称。
        slots: 已经过基本结构验证的栈槽记录。
        instructions: 包含机器码十六进制文本和来源属性的清单。
        frame_size: 函数分配的栈帧大小。
    """
    from verbose_c.compiler.native.encoder import encode_mov_rax_imm64, encode_mov_rdx_imm64, encode_mov_rbp_offset_from_rax, encode_mov_r11_offset_from_rax, encode_prologue, encode_epilogue

    arrays = {}
    ranges = []
    owns_global_frame = any(item["source_op"] == "prologue" and bytes.fromhex(item["bytes"]) == b"\x49\x89\xEB"
                            for item in instructions)
    for slot in slots:
        slot_name = slot["name"]
        if slot_name.startswith("array[") or (slot_name.startswith("global[") and slot.get("array_length") is not None):
            length = slot.get("array_length")
            if (not slot_name.endswith("]") or (slot_name.startswith("array[") and not slot_name[6:-1].isdigit()) or type(length) is not int
                    or length <= 0 or slot["size"] not in {length * 8, (length + 1) * 8} or not isinstance(slot.get("element_type"), str)
                    or slot["element_type"] not in ARRAY_ELEMENT_TYPES):
                raise NativeCodegenError(f"函数 {name}: 数组栈槽 {slot_name} 的长度或元素类型无效")
            arrays[slot_name] = slot
        elif slot.get("array_length") is not None or slot.get("element_type") is not None:
            raise NativeCodegenError(f"函数 {name}: 普通栈槽不能携带数组来源信息")
        if not slot_name.startswith("global[") or owns_global_frame:
            ranges.append((slot["offset"] - slot["size"], slot["offset"], slot_name))
    reference_checks = {
        "array_ref_lower_bound": b"\x48\x89\xC2\x4D\x85\xD2",
        "array_ref_upper_bound": b"\x4C\x3B\x52\xF8",
        "array_ref_load": b"\x4A\x8B\x04\xD2",
        "array_ref_store": b"\x4A\x89\x04\xD2",
    }
    reference_state = None
    for index, item in enumerate(instructions):
        op = item["source_op"]
        if op not in reference_checks:
            continue
        element_type = item["source_attrs"].get("element_type")
        if not isinstance(element_type, str) or element_type not in ARRAY_ELEMENT_TYPES or bytes.fromhex(item["bytes"]) != reference_checks[op]:
            raise NativeCodegenError(f"函数 {name}: 数组引用类型或寻址字节无效")
        if op in {"array_ref_lower_bound", "array_ref_upper_bound"}:
            if index + 2 >= len(instructions):
                raise NativeCodegenError(f"函数 {name}: 数组引用缺少越界错误分支")
            guard, failure = instructions[index + 1:index + 3]
            failure_bytes = bytes.fromhex(failure["bytes"])
            condition = 0x79 if op == "array_ref_lower_bound" else 0x7C
            if (len(failure_bytes) != 20 + len(encode_epilogue())
                    or guard["source_op"] != "numeric_guard" or bytes.fromhex(guard["bytes"]) != bytes([condition, len(failure_bytes)])
                    or failure["source_op"] != "numeric_error" or failure["source_attrs"].get("error_code") != 10
                    or not failure_bytes.startswith(encode_mov_rdx_imm64(10)) or not failure_bytes.endswith(encode_epilogue())):
                raise NativeCodegenError(f"函数 {name}: 数组引用越界检查与错误分支不一致")
            if op == "array_ref_lower_bound":
                if reference_state is not None:
                    raise NativeCodegenError(f"函数 {name}: 数组引用边界检查未闭合")
                reference_state = (element_type, "lower")
            else:
                if reference_state != (element_type, "lower"):
                    raise NativeCodegenError(f"函数 {name}: 数组引用缺少负下标检查")
                reference_state = (element_type, "upper")
        else:
            if reference_state != (element_type, "upper"):
                raise NativeCodegenError(f"函数 {name}: 数组引用读写前缺少完整边界检查")
            reference_state = None
    if reference_state is not None:
        raise NativeCodegenError(f"函数 {name}: 数组引用边界检查缺少对应读写")
    array_instructions = [item for item in instructions if item["source_op"] in {"array_init", "array_load", "array_store", "array_bounds", "array_address"}]
    if not arrays and not array_instructions:
        return
    owned_arrays = {slot_name for slot_name in arrays if not slot_name.startswith("global[") or owns_global_frame}
    if owned_arrays and frame_size + 32 > MAX_ARRAY_FRAME_SIZE:
        raise NativeCodegenError(f"函数 {name}: 数组栈帧超过上限")
    previous_end = 0
    for start, end, slot_name in sorted(ranges):
        if start < previous_end or start % 8 or end % 8 or end > frame_size:
            raise NativeCodegenError(f"函数 {name}: 数组与栈槽 {slot_name} 重叠、未对齐或超出栈帧")
        previous_end = end
    prologues = [item for item in instructions if item["source_op"] == "prologue" and bytes.fromhex(item["bytes"]) != b"\x49\x89\xEB"]
    if len(prologues) != 1 or bytes.fromhex(prologues[0]["bytes"]) != encode_prologue(frame_size):
        raise NativeCodegenError(f"函数 {name}: 数组栈帧大小与函数序言不一致")
    initialized = set()
    for item in array_instructions:
        attrs = item["source_attrs"]
        slot = arrays.get(attrs.get("array_slot"))
        if slot is None or any(attrs.get(key) != slot[field] for key, field in (("offset", "offset"), ("length", "array_length"), ("element_type", "element_type"))):
            raise NativeCodegenError(f"函数 {name}: 数组指令来源与栈槽声明不一致")
        offset = slot["offset"]
        global_array = slot["name"].startswith("global[")
        has_header = slot["size"] == (slot["array_length"] + 1) * 8
        data_offset = offset - 8 if has_header else offset
        if item["source_op"] == "array_init":
            if slot["name"] not in owned_arrays:
                raise NativeCodegenError(f"函数 {name}: 不能重新分配借用的全局数组")
            if slot["name"] in initialized:
                raise NativeCodegenError(f"函数 {name}: 数组存在重复分配指令")
            initialized.add(slot["name"])
            store = encode_mov_r11_offset_from_rax if global_array else encode_mov_rbp_offset_from_rax
            expected = (encode_mov_rax_imm64(slot["array_length"]) + store(offset)) if has_header else b""
            expected += encode_mov_rax_imm64(0) + b"".join(store(data_offset - index * 8) for index in range(slot["array_length"]))
        elif item["source_op"] in {"array_load", "array_store"}:
            expected = bytes([0x4B if global_array else 0x4A, 0x89 if item["source_op"] == "array_store" else 0x8B,
                              0x84, 0xD3 if global_array else 0xD5]) + (-data_offset).to_bytes(4, "little", signed=True)
        elif item["source_op"] == "array_address":
            if not has_header:
                raise NativeCodegenError(f"函数 {name}: 可传参的数组必须包含长度头")
            expected = (b"\x49\x8D\x83" if global_array else b"\x48\x8D\x85") + (-data_offset).to_bytes(4, "little", signed=True)
        else:
            continue
        if bytes.fromhex(item["bytes"]) != expected:
            raise NativeCodegenError(f"函数 {name}: 数组寻址字节与栈槽偏移不一致")
    if initialized != owned_arrays:
        raise NativeCodegenError(f"函数 {name}: 数组存储缺少初始化来源")

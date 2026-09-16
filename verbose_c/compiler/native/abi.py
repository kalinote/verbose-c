from dataclasses import dataclass, field

from verbose_c.compiler.native.target import NativeTarget, WINDOWS_X64_REGISTERS, RegisterSet

FLOAT_VALUE_TYPES = {"float32", "float64"}
SCALAR_VALUE_TYPES = {"int64", "bool64", "string", *FLOAT_VALUE_TYPES}
SUPPORTED_RETURN_TYPES = SCALAR_VALUE_TYPES | {"void"}
SUPPORTED_VALUE_TYPES = SCALAR_VALUE_TYPES
SUPPORTED_ARGUMENT_REGISTERS = {"RCX", "RDX", "R8", "R9"}

@dataclass(frozen=True)
class ArgumentLocation:
    """描述函数参数在 ABI 中的位置。"""

    kind: str
    name: str
    index: int


@dataclass(frozen=True)
class WindowsX64ABI:
    """Windows x64 MVP ABI 描述。"""

    name: str = "windows-x64-msvc-mvp"
    target: NativeTarget = NativeTarget.WINDOWS_X64
    word_size: int = 8
    stack_alignment: int = 16
    shadow_space_size: int = 32
    registers: RegisterSet = WINDOWS_X64_REGISTERS
    supported_value_types: tuple[str, ...] = ("int64", "bool64", "float32", "float64", "string", "void")

    def argument_location(self, index: int, type_hint: str = "int64") -> ArgumentLocation:
        """返回第 index 个参数的 ABI 位置。"""
        if index < len(self.registers.argument_registers):
            if type_hint in FLOAT_VALUE_TYPES:
                return ArgumentLocation("register", f"XMM{index}", index)
            return ArgumentLocation("register", self.registers.argument_registers[index], index)
        stack_offset = self.shadow_space_size + (index - len(self.registers.argument_registers)) * self.word_size
        return ArgumentLocation("stack", f"[rsp+{stack_offset}]", index)


@dataclass
class StackFrameLayout:
    """Machine IR 阶段的保守栈帧布局。"""

    word_size: int = 8
    global_slots: list[object] = field(default_factory=list)
    local_slots: list[object] = field(default_factory=list)
    temp_slots: list[object] = field(default_factory=list)
    spill_slots: list[object] = field(default_factory=list)

    @property
    def frame_size(self) -> int:
        """返回栈帧大小。"""
        return (len(self.global_slots) + len(self.local_slots) + len(self.temp_slots) + len(self.spill_slots)) * self.word_size


WINDOWS_X64_ABI = WindowsX64ABI()


def is_argument_type_compatible(param_type: str, value_type: str) -> bool:
    """判断 call 实参类型是否匹配形参类型。"""
    return param_type == value_type or (param_type == "int64" and value_type == "bool64")

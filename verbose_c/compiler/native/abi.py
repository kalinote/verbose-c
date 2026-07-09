from dataclasses import dataclass, field

from verbose_c.compiler.native.target import NativeTarget, WINDOWS_X64_REGISTERS, RegisterSet


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
    supported_value_types: tuple[str, ...] = ("int64", "bool64", "void")

    def argument_location(self, index: int) -> ArgumentLocation:
        """返回第 index 个参数的 ABI 位置。"""
        if index < len(self.registers.argument_registers):
            return ArgumentLocation("register", self.registers.argument_registers[index], index)
        stack_offset = self.shadow_space_size + (index - len(self.registers.argument_registers)) * self.word_size
        return ArgumentLocation("stack", f"[rsp+{stack_offset}]", index)


@dataclass
class StackFrameLayout:
    """Machine IR 阶段的保守栈帧布局。"""

    word_size: int = 8
    local_slots: list[object] = field(default_factory=list)
    temp_slots: list[object] = field(default_factory=list)
    spill_slots: list[object] = field(default_factory=list)

    @property
    def frame_size(self) -> int:
        """返回栈帧大小。"""
        return (len(self.local_slots) + len(self.temp_slots) + len(self.spill_slots)) * self.word_size


WINDOWS_X64_ABI = WindowsX64ABI()


from dataclasses import dataclass, field
from typing import Any

from verbose_c.compiler.native.abi import ArgumentLocation, StackFrameLayout, WindowsX64ABI
from verbose_c.compiler.native.target import NativeTarget


@dataclass(frozen=True)
class VirtualRegister:
    """Machine IR 虚拟寄存器。"""

    name: str
    type_hint: str = "int64"


@dataclass(frozen=True)
class StackSlot:
    """Machine IR 栈槽。"""

    kind: str
    index: int
    size: int = 8


@dataclass(frozen=True)
class MachineOperand:
    """Machine IR 操作数。"""

    kind: str
    value: Any
    type_hint: str = "int64"

    @classmethod
    def vreg(cls, value: VirtualRegister) -> "MachineOperand":
        """创建虚拟寄存器操作数。"""
        return cls("vreg", value, value.type_hint)

    @classmethod
    def slot(cls, value: StackSlot) -> "MachineOperand":
        """创建栈槽操作数。"""
        return cls("slot", value)

    @classmethod
    def imm(cls, value: int) -> "MachineOperand":
        """创建立即数操作数。"""
        return cls("imm", value)

    @classmethod
    def symbol(cls, value: str) -> "MachineOperand":
        """创建符号操作数。"""
        return cls("symbol", value, "function")

    @classmethod
    def reg(cls, value: str) -> "MachineOperand":
        """创建物理寄存器操作数。"""
        return cls("reg", value)


@dataclass
class MachineInstruction:
    op: str
    result: MachineOperand | None = None
    args: list[MachineOperand] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
    source_pc: int | None = None
    source_line: int | None = None


@dataclass
class MachineTerminator:
    op: str
    targets: list[str] = field(default_factory=list)
    args: list[MachineOperand] = field(default_factory=list)
    source_pc: int | None = None
    source_line: int | None = None


@dataclass
class MachineBlock:
    name: str
    instructions: list[MachineInstruction] = field(default_factory=list)
    terminator: MachineTerminator | None = None
    predecessors: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)


@dataclass
class MachineFunction:
    name: str
    params: list[ArgumentLocation]
    return_type: str
    frame: StackFrameLayout
    blocks: list[MachineBlock]
    source_path: str | None = None
    virtual_register_count: int = 0
    exit_code_value: MachineOperand | None = None


@dataclass
class MachineProgram:
    target: NativeTarget
    abi: WindowsX64ABI
    module: MachineFunction
    functions: dict[str, MachineFunction] = field(default_factory=dict)


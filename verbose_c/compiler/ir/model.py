from dataclasses import dataclass, field
from typing import Any

from verbose_c.error import VBCCompileError


class IRLoweringError(VBCCompileError):
    """操作码 lowering 到 IR 失败。"""


@dataclass(frozen=True)
class IRValue:
    kind: str
    name: str | int
    type_hint: str | None = None
    value_repr: str | None = None

    @classmethod
    def temp(cls, name: str, type_hint: str | None = None) -> "IRValue":
        """创建临时值。"""
        return cls("temp", name, type_hint=type_hint)

    @classmethod
    def local(cls, slot: int) -> "IRValue":
        """创建局部变量槽引用。"""
        return cls("local", slot)

    @classmethod
    def global_(cls, name: str) -> "IRValue":
        """创建全局变量引用。"""
        return cls("global", name)

    @classmethod
    def constant(cls, index: int, value: Any) -> "IRValue":
        """创建常量池引用。"""
        type_hint = _type_name_for_constant(value)
        return cls("constant", index, type_hint=type_hint, value_repr=repr(value))


@dataclass
class IRInstruction:
    op: str
    result: IRValue | None = None
    args: list[IRValue] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
    source_pc: int | None = None
    source_line: int | None = None


@dataclass
class IRTerminator:
    op: str
    targets: list[str] = field(default_factory=list)
    args: list[IRValue] = field(default_factory=list)
    source_pc: int | None = None
    source_line: int | None = None


@dataclass
class IRBasicBlock:
    name: str
    start_pc: int
    end_pc: int
    instructions: list[IRInstruction] = field(default_factory=list)
    terminator: IRTerminator | None = None
    predecessors: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)
    entry_stack: tuple[IRValue, ...] = field(default_factory=tuple)
    exit_stack: tuple[IRValue, ...] = field(default_factory=tuple)


@dataclass
class IRFunction:
    name: str
    blocks: list[IRBasicBlock]
    constants: list[Any] = field(default_factory=list)
    param_count: int = 0
    local_count: int = 0
    source_path: str | None = None
    lineno_table: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class IRProgram:
    module: IRFunction
    functions: dict[str, IRFunction] = field(default_factory=dict)


def _type_name_for_constant(value: Any) -> str:
    object_type = getattr(value, "_object_type", None)
    if object_type is not None:
        return getattr(object_type, "name", str(object_type))
    return type(value).__name__

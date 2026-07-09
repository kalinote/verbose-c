from dataclasses import dataclass
from enum import Enum


class NativeTarget(str, Enum):
    """Native 后端目标平台。"""

    WINDOWS_X64 = "windows-x64"


@dataclass(frozen=True)
class RegisterSet:
    """描述目标平台寄存器集合。"""

    argument_registers: tuple[str, ...]
    return_register: str
    frame_pointer: str
    stack_pointer: str
    caller_saved: tuple[str, ...]
    callee_saved: tuple[str, ...]


WINDOWS_X64_REGISTERS = RegisterSet(
    argument_registers=("RCX", "RDX", "R8", "R9"),
    return_register="RAX",
    frame_pointer="RBP",
    stack_pointer="RSP",
    caller_saved=("RAX", "RCX", "RDX", "R8", "R9", "R10", "R11"),
    callee_saved=("RBX", "RBP", "RSI", "RDI", "R12", "R13", "R14", "R15"),
)


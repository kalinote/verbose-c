from dataclasses import dataclass, field
from typing import Any

@dataclass
class TracebackFrame:
    """
    用于存储单层调用栈信息的数据类
    """
    filepath: str
    line: int
    scope_name: str
    source_line_context: list[str] | None = None

class VBCError(Exception):
    """所有 VBC 解释器错误的基类"""
    def __init__(self, message, line: int | None = None, filepath: str | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.filepath = filepath

class VBCCompileError(VBCError):
    """编译时错误"""
    def __init__(self, message, line: int | None = None, filepath: str | None = None):
        super().__init__(message, line, filepath)

class VBCRuntimeError(VBCError):
    """
    运行时错误
    
    Attributes:
        message (str): 错误的核心信息.
        traceback (list[TracebackFrame]): 结构化的调用栈轨迹.
    """
    def __init__(self, message: str, traceback: list[TracebackFrame] = field(default_factory=list)):
        super().__init__(message)
        self.message = message
        self.traceback = traceback


class VBCIOError(VBCRuntimeError):
    """I/O 相关异常"""
    pass

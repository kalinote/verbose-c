from dataclasses import dataclass

from .report import DiagnosticEntry, DiagnosticReport

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
    category = "错误"

    def __init__(self, message, line: int | None = None, filepath: str | None = None, *, report: DiagnosticReport | None = None):
        """保留原异常字段，并为没有专用报告的错误建立默认条目。"""
        super().__init__(message)
        self.message = message
        self.line = line
        self.filepath = filepath
        self.report = report if report is not None else DiagnosticReport(
            self.category, [DiagnosticEntry(str(message), filepath=filepath, line=line)]
        )

class VBCCompileError(VBCError):
    """编译时错误"""
    category = "编译错误"

    def __init__(self, message, line: int | None = None, filepath: str | None = None, warnings: list[str] | None = None, *, report: DiagnosticReport | None = None):
        """兼容原有编译异常参数，允许附带结构化诊断。"""
        super().__init__(message, line, filepath, report=report)
        self.warnings = warnings or []


class VBCBytecodeError(VBCCompileError):
    """字节码产物格式错误"""
    category = "字节码错误"


class VBCRuntimeError(VBCError):
    """
    运行时错误
    
    Attributes:
        message (str): 错误的核心信息.
        traceback (list[TracebackFrame]): 结构化的调用栈轨迹.
    """
    category = "运行时错误"

    def __init__(self, message: str, traceback: list[TracebackFrame] | None = None, *, report: DiagnosticReport | None = None):
        """为每个异常创建独立调用栈，并让报告复用同一份栈信息。"""
        super().__init__(message, report=report)
        self.traceback = traceback if traceback is not None else self.report.traceback
        self.report.traceback = self.traceback


class VBCIOError(VBCRuntimeError):
    """I/O 相关异常"""
    category = "I/O 错误"

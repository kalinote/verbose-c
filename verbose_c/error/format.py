"""统一诊断的纯文本渲染；终端和文件输出由调用方负责。"""

import traceback
import unicodedata

from .exceptions import VBCCompileError, VBCError
from .report import DiagnosticEntry, DiagnosticReport


def _display_width(text: str) -> int:
    """计算中文、组合字符及制表符在源码区的显示宽度。"""
    width = 0
    for char in text:
        if char == "\t":
            width += 4 - width % 4
        elif not unicodedata.combining(char):
            width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def format_report(report: DiagnosticReport) -> str:
    """按原顺序将结构化报告渲染为树形正文。

    Args:
        report: 编译、解析、类型或运行时诊断报告。

    Returns:
        不带末尾换行的纯文本，不读取文件也不执行打印。
    """
    sections = []
    for entry in report.entries:
        chunks = []
        location = []
        if entry.filepath:
            location.append(f"文件 {entry.filepath}")
        if entry.line is not None and entry.line > 0:
            location.append(f"第 {entry.line} 行")
        if entry.column is not None and entry.column >= 0:
            location.append(f"第 {entry.column + 1} 列")
        if location:
            chunks.append(["错误位置: " + "，".join(location)])
        chunks.append(f"{report.category}: {entry.message}".splitlines())
        if entry.source_context:
            context = ["错误上下文:"]
            number_width = max(len(str(number)) for number, _ in entry.source_context)
            for number, source in entry.source_context:
                expanded = ""
                width = 0
                for char in source:
                    size = 4 - width % 4 if char == "\t" else _display_width(char)
                    expanded += " " * size if char == "\t" else char
                    width += size
                context.append(f"{number:>{number_width}} | {expanded}")
                if number == entry.line and entry.column is not None and entry.column >= 0:
                    column = min(entry.column, len(source))
                    start = _display_width(source[:column])
                    end = _display_width(source[:column + max(1, entry.highlight_length)])
                    context.append(" " * (number_width + 3 + start) + "^" * max(1, end - start))
            chunks.append(context)
        if entry.rule_stack:
            chunks.append(["语法解析规则调用栈:", " -> ".join(entry.rule_stack)])
        if len(report.entries) > 1:
            sections.append([line for chunk in chunks for line in chunk])
        else:
            sections.extend(chunks)
    if report.traceback:
        frames = ["错误跟踪:"]
        for frame in report.traceback:
            location = f'文件 "{frame.filepath}"，' if frame.filepath else ""
            if frame.line is not None and frame.line > 0:
                location += f"第 {frame.line} 行，"
            frames.append(f"  在{location}{frame.scope_name} 中:")
            frames.extend(f"    {source}" for source in frame.source_line_context or [])
        sections.append(frames)
    lines = []
    for index, section in enumerate(sections):
        last = index == len(sections) - 1
        lines.append((" └─ " if last else " ├─ ") + section[0])
        lines.extend(("    " if last else " │  ") + line for line in section[1:])
    return "\n".join(lines)


def format_error(error: Exception) -> str:
    """生成终端和 dump 共用的完整诊断，保留内部异常的 Python 跟踪。

    Args:
        error: 原始流水线异常，允许缺少位置或专用报告。

    Returns:
        不带末尾换行的诊断；报告损坏时仍保留原始错误原因。
    """
    if not isinstance(error, VBCError):
        details = "".join(traceback.format_exception(type(error), error, error.__traceback__)).rstrip()
        return f"发生了一个意外的内部错误: {error}\n{details}"
    heading = "编译错误" if isinstance(error, VBCCompileError) else error.category
    if error.filepath:
        heading += f": 文件 {error.filepath}"
    else:
        heading += ":"
    try:
        report = error.report or DiagnosticReport(error.category, [
            DiagnosticEntry(str(error), filepath=error.filepath, line=error.line)
        ])
        return heading + "\n" + (format_report(report) or str(error))
    except Exception:
        # 诊断附加信息不应覆盖最初的错误。
        return f"{heading}\n{error}"

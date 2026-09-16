from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .exceptions import TracebackFrame


@dataclass
class DiagnosticEntry:
    """一条诊断；行号从 1 开始，列号沿用词法分析器的零起点。"""

    message: str
    filepath: str | None = None
    line: int | None = None
    column: int | None = None
    source_context: list[tuple[int, str]] = field(default_factory=list)
    highlight_length: int = 1
    expected_tokens: list[str] = field(default_factory=list)
    actual_token: str | None = None
    rule_stack: list[str] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    """与输出介质无关的诊断报告，保留条目和调用栈的原始顺序。"""

    category: str
    entries: list[DiagnosticEntry] = field(default_factory=list)
    traceback: list[TracebackFrame] = field(default_factory=list)

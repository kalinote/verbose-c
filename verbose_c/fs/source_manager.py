import os


class SourceManager:
    """会话级源码管理器，按绝对路径缓存文件内容。"""

    def __init__(self, include_paths: list[str] | None = None, system_include_paths: list[str] | None = None) -> None:
        self._lines: dict[str, list[str]] = {}
        self.include_paths = list(dict.fromkeys(os.path.abspath(path) for path in include_paths or []))
        self.system_include_paths = list(dict.fromkeys(os.path.abspath(path) for path in system_include_paths or []))

    def normalize_path(self, path: str) -> str:
        """将路径规范为绝对路径。"""
        return os.path.abspath(path) if path else ""

    def read(self, path: str) -> str:
        """读取文件并缓存，已缓存则直接返回全文。"""
        abs_path = self.normalize_path(path)
        if abs_path in self._lines:
            return "\n".join(self._lines[abs_path])

        with open(abs_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        self._lines[abs_path] = content.splitlines()
        return content

    def get_line(self, path: str, line: int) -> str:
        """获取指定文件 1-based 行内容，无则返回空字符串。"""
        abs_path = self.normalize_path(path)
        if abs_path not in self._lines:
            if not abs_path or not os.path.exists(abs_path):
                return ""
            self.read(abs_path)

        lines = self._lines.get(abs_path, [])
        if 1 <= line <= len(lines):
            return lines[line - 1]
        return ""

    def line_count(self, path: str) -> int:
        """返回文件总行数，未加载则尝试读取。"""
        abs_path = self.normalize_path(path)
        if abs_path not in self._lines:
            if not abs_path or not os.path.exists(abs_path):
                return 0
            self.read(abs_path)
        return len(self._lines.get(abs_path, []))

    def exists(self, path: str) -> bool:
        """检查文件是否存在。"""
        return os.path.exists(self.normalize_path(path))

    def get_context(self, path: str, line: int | None, radius: int = 2) -> list[tuple[int, str]]:
        """读取诊断上下文；源码缺失或不可读时保留错误本身。

        Args:
            path: 已知的源码路径。
            line: 从 1 开始的错误行号，未知时允许为空。
            radius: 错误行前后的上下文行数。

        Returns:
            带原始行号的源码行，无法读取时返回空列表。
        """
        if line is None or line < 1:
            return []
        try:
            count = self.line_count(path)
            return [(number, self.get_line(path, number))
                    for number in range(max(1, line - radius), min(count, line + radius) + 1)]
        except (OSError, UnicodeError):
            return []

    def resolve_include(self, include_name: str, from_path: str, angled: bool = False) -> str:
        """依照引号或尖括号规则搜索头文件。

        Args:
            include_name: 指令指定的文件名。
            from_path: 发出 include 的文件路径。
            angled: 尖括号形式跳过发出指令文件的目录。

        Returns:
            首个可用文件的绝对路径。

        Raises:
            FileNotFoundError: 文件不存在，消息列出实际搜索过的路径。
        """
        directories = ([] if angled else [os.path.dirname(self.normalize_path(from_path))])
        directories += self.include_paths + self.system_include_paths
        candidates = ([os.path.abspath(include_name)] if os.path.isabs(include_name) else
                      list(dict.fromkeys(os.path.abspath(os.path.join(path, include_name)) for path in directories)))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        searched = "、".join(candidates) or "未配置 include 搜索目录"
        raise FileNotFoundError(f"#include 文件未找到 '{include_name}'；搜索路径: {searched}")

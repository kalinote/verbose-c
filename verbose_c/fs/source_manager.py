import os


class SourceManager:
    """会话级源码管理器，按绝对路径缓存文件内容。"""

    def __init__(self) -> None:
        self._lines: dict[str, list[str]] = {}

    def normalize_path(self, path: str) -> str:
        """将路径规范为绝对路径。"""
        return os.path.abspath(path) if path else ""

    def read(self, path: str) -> str:
        """读取文件并缓存，已缓存则直接返回全文。"""
        abs_path = self.normalize_path(path)
        if abs_path in self._lines:
            return "\n".join(self._lines[abs_path])

        with open(abs_path, "r", encoding="utf-8") as f:
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

    def resolve_include(self, include_name: str, from_path: str) -> str:
        """将 #include 相对路径解析为绝对路径。"""
        base_dir = os.path.dirname(self.normalize_path(from_path))
        return os.path.normpath(os.path.join(base_dir, include_name))

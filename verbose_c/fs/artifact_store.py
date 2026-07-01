from typing import Any


class ArtifactStore:
    """编译产物持久化"""

    def save_bytecode(self, output_path: str, bytecode: list, metadata: dict[str, Any] | None = None) -> None:
        """TODO: 将编译字节码持久化到磁盘"""
        raise NotImplementedError("暂不支持")

    def load_bytecode(self, output_path: str) -> tuple[list, dict[str, Any]]:
        """TODO: 从磁盘读取已保存的字节码"""
        raise NotImplementedError("暂不支持")

    def artifact_path_for_source(self, source_path: str) -> str:
        """TODO: 由源文件路径推导产物路径"""
        raise NotImplementedError("暂不支持")

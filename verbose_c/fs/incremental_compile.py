
class IncrementalCompiler:
    """增量编译与依赖追踪"""

    def needs_recompile(self, entry_path: str) -> bool:
        """TODO: 判断入口文件及其依赖是否需要重新编译"""
        raise NotImplementedError("暂不支持")

    def record_dependency(self, from_path: str, included_path: str) -> None:
        """TODO: 记录 #include 依赖边"""
        raise NotImplementedError("暂不支持")

    def get_transitive_dependencies(self, entry_path: str) -> list[str]:
        """TODO: 获取入口文件的传递闭包依赖"""
        raise NotImplementedError("暂不支持")

    def invalidate(self, path: str) -> None:
        """TODO: 使指定路径的编译缓存失效"""
        raise NotImplementedError("暂不支持")

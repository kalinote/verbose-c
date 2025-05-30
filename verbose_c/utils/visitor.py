class VisitorBase:
    """
    访问者基类
    """
    def visit(self, node):
        method_name = f'visit_{type(node).__name__}'
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        """默认访问方法"""
        raise NotImplementedError(f"未实现节点类型 {node.__class__.__name__} 的访问方法")
                
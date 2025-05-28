
from verbose_c.parser.parser.ast.node import ASTNode


class Complier:
    """
    编译器
    """
    def __init__(self):
        self._objects = []

    def compile_module(self, ast: ASTNode):
        """
        编译模块
        """
        raise NotImplementedError


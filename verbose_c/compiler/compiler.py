
from ast import List
from verbose_c.compiler.opcode import Opcode
from verbose_c.parser.parser.ast.node import ASTNode


class Compiler:
    """
    编译器
    """
    def __init__(self, target_ast: ASTNode):
        self._target_ast = target_ast
        self._opcodes: List[tuple(Opcode)] = []




from typing import List
from verbose_c.compiler.enum import ScopeType
from verbose_c.compiler.opcode import Opcode
from verbose_c.compiler.opcode_generator import OpcodeGenerator
from verbose_c.compiler.symbol import SymbolTable
from verbose_c.parser.parser.ast.node import ASTNode


class Compiler:
    """
    编译器
    """
    def __init__(self, target_ast: ASTNode, optimize_level: int=0):
        self._target_ast = target_ast
        
        # 编译优化等级，数字越大等级越高，设置成100万直接所有代码给优化成O(1)
        self._optimize_level = optimize_level
        
        # 全局符号表
        self._symbol_table = SymbolTable(ScopeType.GLOBAL)
        
        # TODO 完善操作码生成、符号表管理等
        self._opcode_generator = OpcodeGenerator(self._symbol_table)

        self._bytecode = []
        self._constant_pool = []
        self._errors = []

    @property
    def bytecode(self):
        return self._bytecode
    
    @property
    def constant_pool(self):
        return self._constant_pool

    def compile(self):
        """
        执行编译
        
        - TODO 编译完成后的字节码优化
        """
        self._opcode_generator.visit(self._target_ast)

        self._bytecode = self._opcode_generator.bytecode
        self._constant_pool = self._opcode_generator.constant_pool

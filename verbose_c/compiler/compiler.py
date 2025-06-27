from verbose_c.compiler.enum import CompilerPass, ScopeType
from verbose_c.compiler.opcode_generator_visitor import OpcodeGenerator
from verbose_c.compiler.symbol import SymbolTable
from verbose_c.compiler.type_checker_visitor import TypeChecker
from verbose_c.parser.parser.ast.node import ASTNode


class Compiler:
    """
    编译器
    """
    def __init__(self, target_ast: ASTNode, optimize_level: int=0, scope_type: ScopeType=ScopeType.GLOBAL, symbol_table: SymbolTable | None = None, source_path: str | None = None, passes_to_run: list[CompilerPass] | None = None):
        self._target_ast = target_ast
        self._optimize_level = optimize_level   # 编译优化等级
        self._scope_type=scope_type
        self._source_path = source_path
        self._passes_to_run = passes_to_run
        
        # 符号表
        self._symbol_table = symbol_table or SymbolTable(scope_type=self._scope_type)
        
        # 类型检查
        self._type_checker = TypeChecker(self._symbol_table, source_path=self._source_path)
        # 操作码生成器
        self._opcode_generator = OpcodeGenerator(self._symbol_table, source_path=self._source_path)

        self._bytecode = []
        self._constant_pool = []
        self._errors = []

    @property
    def bytecode(self):
        return self._bytecode
    
    @property
    def constant_pool(self):
        return self._constant_pool
    
    @property
    def opcode_generator(self):
        return self._opcode_generator

    def compile(self):
        """
        执行编译
        
        - TODO 编译完成后的字节码优化
        """
        passes = self._passes_to_run
        if passes is None or CompilerPass.ALL in passes:
            run_all = True
        else:
            run_all = False

        if run_all or CompilerPass.TYPE_CHECK in passes:
            # 类型检查
            self._type_checker.visit(self._target_ast)
            if self._type_checker.errors:
                # 错误类型直接返回
                self._errors.extend(self._type_checker.errors)
                return
        
        if run_all or CompilerPass.GENERATE_CODE in passes:
            # 代码生成
            self._opcode_generator.visit(self._target_ast)
            self._bytecode = self._opcode_generator.bytecode
            self._constant_pool = self._opcode_generator.constant_pool

    def get_errors(self) -> list[str]:
        return self._errors

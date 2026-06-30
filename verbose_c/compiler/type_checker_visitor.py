from verbose_c.compiler.enum import ScopeType
from verbose_c.object.t_float import VBCFloat
from verbose_c.object.t_integer import VBCInteger
from verbose_c.utils.visitor import VisitorBase
from verbose_c.parser.parser.ast.node import *
from verbose_c.compiler.symbol import SymbolTable, SymbolKind
from verbose_c.typing.types import (
    Type, VoidType, NullType, IntegerType, FloatType, StringType, BoolType,
    PointerType, FunctionType, ClassType, AnyType, ErrorType
)
from verbose_c.object.enum import VBCObjectType


# 将字符串类型名映射到编译时Type对象
BUILTIN_TYPE_MAP: dict[str, Type] = {
    "void": VoidType(),
    "char": IntegerType(VBCObjectType.CHAR),
    "int": IntegerType(VBCObjectType.INT),
    "long": IntegerType(VBCObjectType.LONG),
    "long long": IntegerType(VBCObjectType.LONGLONG),
    "unlimited int": IntegerType(VBCObjectType.NLINT),
    "float": FloatType(VBCObjectType.FLOAT),
    "double": FloatType(VBCObjectType.DOUBLE),
    "unlimited float": FloatType(VBCObjectType.NLFLOAT),
    "string": StringType(),
    "bool": BoolType(),
}

def _build_type_promotion_priority() -> dict[VBCObjectType, int]:
    """
    动态构建类型提升优先级字典，确保与运行时行为一致。
    """
    priority_map = {}
    for type_enum, (_, priority) in VBCInteger.bit_width.items():
        priority_map[type_enum] = priority
    for type_enum, (_, priority) in VBCFloat.bit_width.items():
        priority_map[type_enum] = priority
    return priority_map

TYPE_PROMOTION_PRIORITY = _build_type_promotion_priority()


class TypeChecker(VisitorBase):
    """
    类型检查器，遍历AST并验证类型规则。
    """
    def __init__(self, symbol_table: SymbolTable, source_path: str | None = None):
        self.symbol_table = symbol_table
        self.source_path = source_path
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.loop_level = 0
        self.current_function_return_type: Type | None = None   # 跟踪当前函数返回类型
        self.current_class_type: ClassType | None = None # 跟踪当前类上下文
        self._register_builtin_types()

    def _register_builtin_types(self):
        """
        将内置类型注册到类型命名空间。
        TODO: 后续接入 typedef 或自定义类型系统时，统一通过类型命名空间解析。
        """
        for type_name, type_obj in BUILTIN_TYPE_MAP.items():
            try:
                self.symbol_table.add_type_symbol(type_name, type_obj)
            except NameError:
                # 多次初始化同一作用域时允许幂等。
                continue

    def visit(self, node: ASTNode) -> Type:
        """重写 visit 方法以提供更精确的类型提示"""
        return super().visit(node)

    def resolve_type_node(self, type_node: TypeNode, report_error: bool = True) -> Type:
        """
        将 AST 中的 TypeNode 转换为 Type 对象，支持指针。
        """
        type_name = type_node.type_name.name
        base_type: Type | None = self.symbol_table.lookup_type(type_name)
        
        if not base_type:
            if report_error:
                self.errors.append(f"未知类型 '{type_name}', 在 {type_node.start_line} 行")
            return ErrorType()

        # 根据指针级别，递归创建 PointerType
        final_type = base_type
        for _ in range(type_node.pointer_level):
            final_type = PointerType(final_type)
        
        return final_type

    def _is_assignable(self, target_type: Type, source_type: Type) -> bool:
        """
        检查 source_type 是否能安全地赋值给 target_type。
        """
        # 规则1: null 可以赋值给任何指针类型或对象类型
        # 其他类型的暂时还是不允许赋值null了
        if isinstance(source_type, NullType):
            if isinstance(target_type, (PointerType, ClassType)):
                return True
            return False

        # 规则2: 类型完全相同
        if target_type == source_type:
            return True
        
        # 规则3: 允许任何类型赋值给 AnyType
        if isinstance(target_type, AnyType):
            return True

        # 规则4: C 标准下，算术类型之间允许隐式赋值
        if isinstance(target_type, (IntegerType, FloatType, BoolType)) and isinstance(source_type, (IntegerType, FloatType, BoolType)):
            return True
            
        # 规则5: 允许 void* 和其他指针类型互相赋值
        if isinstance(target_type, PointerType) and isinstance(source_type, PointerType):
            if isinstance(target_type.base_type, VoidType) or isinstance(source_type.base_type, VoidType):
                return True

        return False

    def _numeric_rank(self, type_: Type) -> int:
        """返回数值类型的隐式转换优先级，用于判断是否窄化。"""
        if isinstance(type_, BoolType):
            return 0
        if isinstance(type_, IntegerType):
            return int(TYPE_PROMOTION_PRIORITY.get(type_.kind, 0))
        if isinstance(type_, FloatType):
            return int(TYPE_PROMOTION_PRIORITY.get(type_.kind, 0))
        return -1

    def _warn_implicit_conversion_if_needed(self, target_type: Type, source_type: Type, line: int | None, context: str):
        """在发生可能丢失信息的隐式转换时记录编译告警。"""
        if target_type == source_type:
            return

        if isinstance(target_type, IntegerType) and isinstance(source_type, FloatType):
            self.warnings.append(
                f"类型警告: {context} 发生隐式转换 '{source_type}' -> '{target_type}'，可能丢失小数部分, 在 {line} 行"
            )
            return

        if isinstance(target_type, (IntegerType, FloatType, BoolType)) and isinstance(source_type, (IntegerType, FloatType, BoolType)):
            target_rank = self._numeric_rank(target_type)
            source_rank = self._numeric_rank(source_type)
            if target_rank < source_rank:
                self.warnings.append(
                    f"类型警告: {context} 发生隐式窄化转换 '{source_type}' -> '{target_type}'，可能丢失精度, 在 {line} 行"
                )

    def _mark_implicit_cast_if_needed(self, expr_node: ASTNode, target_type: Type, source_type: Type):
        """给表达式打标记，提示代码生成阶段插入隐式 CAST。"""
        if target_type == source_type:
            return
        if isinstance(target_type, (IntegerType, FloatType, BoolType)) and isinstance(source_type, (IntegerType, FloatType, BoolType)):
            setattr(expr_node, "_implicit_cast_target", target_type)

    def _is_castable(self, target_type: Type, source_type: Type) -> bool:
        """
        检查 source_type 是否能显式地转换为 target_type。
        这个方法的规则比 is_assignable 更宽松，因为它处理的是用户明确要求的强制类型转换。
        """
        # 规则 1: 类型完全相同
        if target_type == source_type:
            return True

        # 规则 2: 任何类型可以转换成 void 类型，同时 void 类型可以转换成任何类型。
        if isinstance(target_type, VoidType) or isinstance(source_type, VoidType):
            return True

        # 规则 3: 任何数字类型之间都可以互相转换。
        # 这包括了安全的拓宽转换 (int -> float) 和可能不安全的收窄转换 (float -> int, long -> int)。
        # 程序员使用显式转换，就表示他们接受了可能的信息丢失风险。
        is_target_numeric = isinstance(target_type, (IntegerType, FloatType))
        is_source_numeric = isinstance(source_type, (IntegerType, FloatType))
        if is_target_numeric and is_source_numeric:
            return True

        # 规则 4: 允许数字和布尔值转换为字符串。
        is_target_string = isinstance(target_type, StringType)
        is_source_numeric_or_bool = isinstance(source_type, (IntegerType, FloatType, BoolType))
        if is_target_string and is_source_numeric_or_bool:
            # 在运行时，这会调用类似 str(value) 的逻辑。
            return True

        # 规则 5: 允许字符串转换为数字类型。
        # 这需要运行时支持，例如尝试解析字符串。如果解析失败，可能会在运行时抛出错误。
        if is_target_numeric and isinstance(source_type, StringType):
            return True
            
        # 规则 6: 字符串和数字转换布尔值
        if isinstance(target_type, BoolType) and (isinstance(source_type, StringType) or is_source_numeric):
            return True
            
        # TODO 规则 7: 允许对象类型之间的向上和向下转型。
        if isinstance(target_type, ClassType) and isinstance(source_type, ClassType):
            # 向上转型总是安全的
            if source_type.is_subclass_of(target_type):
                return True
            # 向下转型是允许的，但实际可能有问题，需要进一步分析
            if target_type.is_subclass_of(source_type):
                return True

        return False

    def visit_RootNode(self, node: RootNode) -> Type:
        for module in node.modules:
            self.visit(module)
        return VoidType()

    def visit_ModuleNode(self, node: ModuleNode) -> Type:
        for statement in node.body:
            self.visit(statement)
        return VoidType()

    # 表达式类型推断
    def visit_NumberNode(self, node: NumberNode) -> Type:
        if isinstance(node.value, int):
            return IntegerType(VBCObjectType.INT)
        elif isinstance(node.value, float):
            return FloatType(VBCObjectType.FLOAT)
        else:
            self.errors.append(f"内部错误：意外的数字值类型 {type(node.value)}, 在 {node.start_line} 行")
            return ErrorType()

    def visit_StringNode(self, node: StringNode) -> Type:
        return StringType()

    def visit_BoolNode(self, node: BoolNode) -> Type:
        return BoolType()

    def visit_NullNode(self, node: NullNode) -> Type:
        return NullType()

    def visit_NameNode(self, node: NameNode) -> Type:
        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is None:
            self.errors.append(f"命名错误: '{node.name}' 未定义, 在 {node.start_line} 行")
            return ErrorType()
        return symbol.type_

    def visit_UnaryOpNode(self, node: UnaryOpNode) -> Type:
        if node.op == Operator.DEREFERENCE:
            operand_type = self.visit(node.expr)
            if isinstance(operand_type, ErrorType):
                return ErrorType()
            if not isinstance(operand_type, PointerType):
                self.errors.append(f"类型错误: 解引用操作符 '*' 只能用于指针类型, 而不是 '{operand_type}', 在 {node.start_line} 行")
                return ErrorType()
            # 解引用的结果是其基础类型
            return operand_type.base_type

        if node.op == Operator.ADDRESS_OF:
            # 取地址操作符只能用于变量名
            if not isinstance(node.expr, NameNode):
                self.errors.append(f"语法错误: 取地址操作符 '&' 只能用于变量, 在 {node.start_line} 行")
                return ErrorType()
            
            operand_type = self.visit(node.expr)
            if isinstance(operand_type, ErrorType):
                return ErrorType()
            
            return PointerType(operand_type)

        operand_type = self.visit(node.expr)
        if isinstance(operand_type, ErrorType):
            return ErrorType()

        if node.op in (Operator.SUBTRACT, Operator.ADD):
            if not isinstance(operand_type, (IntegerType, FloatType)):
                self.errors.append(f"类型错误: 操作符 '{node.op.value}' 不能用于类型 '{operand_type}', 在 {node.start_line} 行")
                return ErrorType()
            return operand_type

        if node.op == Operator.NOT:
            # 注意：C语言允许对指针和整数进行逻辑非操作，这里我们先保持严格，只允许布尔
            if not isinstance(operand_type, BoolType):
                self.errors.append(f"类型错误: 操作符 '!' 只能用于布尔类型, 而不是 '{operand_type}', 在 {node.start_line} 行")
                return ErrorType()
            return BoolType()

        self.errors.append(f"内部错误: 未知的一元操作符 '{node.op.value}', 在 {node.start_line} 行")
        return ErrorType()


    def visit_BinaryOpNode(self, node: BinaryOpNode) -> Type:
        """检查二元表达式类型并推导结果类型。"""
        left_type = self.visit(node.left)
        right_type = self.visit(node.right)

        if isinstance(left_type, ErrorType) or isinstance(right_type, ErrorType):
            return ErrorType()

        op = node.op

        # 算术运算
        if op in (Operator.ADD, Operator.SUBTRACT, Operator.MULTIPLY, Operator.DIVIDE):
            # 规则 1: 字符串拼接
            if op == Operator.ADD and isinstance(left_type, StringType) and isinstance(right_type, StringType):
                return StringType()

            # 规则 2: 数字运算 (整数/浮点数)
            if isinstance(left_type, (IntegerType, FloatType)) and isinstance(right_type, (IntegerType, FloatType)):
                left_priority = TYPE_PROMOTION_PRIORITY[left_type.kind]
                right_priority = TYPE_PROMOTION_PRIORITY[right_type.kind]
                
                # 结果类型遵循优先级更高的操作数
                result_type = left_type if left_priority >= right_priority else right_type
                
                # 特殊规则：整数除法的结果是浮点数
                if op == Operator.DIVIDE and isinstance(result_type, IntegerType):
                    return FloatType(VBCObjectType.DOUBLE)
                
                return result_type

            # 如果以上规则都不匹配，则是类型错误
            self.errors.append(f"类型错误: 操作符 '{op.value}' 不能用于类型 '{left_type}' 和 '{right_type}', 在 {node.start_line} 行")
            return ErrorType()

        # 比较运算
        if op in (Operator.GREATER_THAN, Operator.GREATER_EQUAL, Operator.LESS_THAN, Operator.LESS_EQUAL, Operator.EQUAL, Operator.NOT_EQUAL):
            # C 语义: 指针与 null 允许做相等/不等比较
            if op in (Operator.EQUAL, Operator.NOT_EQUAL):
                pointer_null_compare = (
                    (isinstance(left_type, PointerType) and isinstance(right_type, NullType)) or
                    (isinstance(left_type, NullType) and isinstance(right_type, PointerType))
                )
                if pointer_null_compare:
                    return BoolType()

            # 允许数字之间，或相同类型之间比较
            is_numeric = isinstance(left_type, (IntegerType, FloatType)) and isinstance(right_type, (IntegerType, FloatType))
            is_same_type = type(left_type) is type(right_type)

            if not (is_numeric or is_same_type):
                self.errors.append(f"类型错误: 无法比较不兼容的类型 '{left_type}' 和 '{right_type}', 在 {node.start_line} 行")
                return ErrorType()
            return BoolType()

        # 逻辑运算
        if op in (Operator.LOGICAL_AND, Operator.LOGICAL_OR):
            if not (isinstance(left_type, BoolType) and isinstance(right_type, BoolType)):
                self.errors.append(f"类型错误: 逻辑操作符 '{op.value}' 的操作数必须是布尔类型, 而不是 '{left_type}' 和 '{right_type}', 在 {node.start_line} 行")
                return ErrorType()
            return BoolType()

        self.errors.append(f"内部错误: 未知的二元操作符 '{op.value}', 在 {node.start_line} 行")
        return ErrorType()

    # 语句的类型检查
    def visit_VarDeclNode(self, node: VarDeclNode) -> Type:
        """检查变量声明初始化的类型兼容，并记录必要的隐式转换信息。"""
        declared_type = self.resolve_type_node(node.var_type)
        
        if node.init_exp:
            init_type = self.visit(node.init_exp)
            if isinstance(init_type, ErrorType):
                return ErrorType()

            if not self._is_assignable(declared_type, init_type):
                self.errors.append(f"类型错误: 不能将类型 '{init_type}' 的值赋给类型为 '{declared_type}' 的变量 '{node.name.name}', 在 {node.start_line} 行")
            else:
                self._warn_implicit_conversion_if_needed(declared_type, init_type, node.start_line, f"变量 '{node.name.name}' 初始化")
                self._mark_implicit_cast_if_needed(node.init_exp, declared_type, init_type)

        try:
            self.symbol_table.add_symbol(node.name.name, declared_type, kind=SymbolKind.VARIABLE)
        except NameError:
            self.errors.append(f"命名错误: 变量 '{node.name.name}' 在当前作用域已存在, 在 {node.start_line} 行")

        return VoidType()

    def visit_AssignmentNode(self, node: AssignmentNode) -> Type:
        """检查赋值语句类型兼容，并记录赋值边界的隐式转换信息。"""
        if isinstance(node.target, UnaryOpNode) and node.target.op == Operator.DEREFERENCE:
            pointer_type = self.visit(node.target.expr)
            if not isinstance(pointer_type, PointerType):
                self.errors.append(f"类型错误: 赋值目标不是一个指针，无法解引用, 在 {node.start_line} 行")
                return ErrorType()
            
            target_type = pointer_type.base_type
            value_type = self.visit(node.value)

            if not self._is_assignable(target_type, value_type):
                self.errors.append(f"类型错误: 不能将类型 '{value_type}' 的值赋给类型为 '{target_type}' 的指针目标, 在 {node.start_line} 行")
                return ErrorType()
            self._warn_implicit_conversion_if_needed(target_type, value_type, node.start_line, "指针解引用赋值")
            self._mark_implicit_cast_if_needed(node.value, target_type, value_type)
            return target_type
        
        target_type = self.visit(node.target)
        if isinstance(target_type, ErrorType):
            return ErrorType()

        value_type = self.visit(node.value)
        if isinstance(value_type, ErrorType):
            return ErrorType()

        if not self._is_assignable(target_type, value_type):
            self.errors.append(f"类型错误: 不能将类型 '{value_type}' 的值赋给类型为 '{target_type}' 的目标, 在 {node.start_line} 行")
            return ErrorType()
        self._warn_implicit_conversion_if_needed(target_type, value_type, node.start_line, "赋值")
        self._mark_implicit_cast_if_needed(node.value, target_type, value_type)
        return target_type

    def visit_BlockNode(self, node: BlockNode) -> Type:
        original_table = self.symbol_table
        block_table = SymbolTable(scope_type=ScopeType.BLOCK, parent=original_table)
        original_table.add_nested_scope(block_table)
        self.symbol_table = block_table

        for statement in node.statements:
            self.visit(statement)

        self.symbol_table = original_table
        
        return VoidType()

    def visit_IfNode(self, node: IfNode) -> Type:
        condition_type = self.visit(node.condition)
        if not isinstance(condition_type, BoolType):
            self.errors.append(f"类型错误: 'if' 语句的条件必须是布尔类型, 而不是 '{condition_type}', 在 {node.condition.start_line} 行")

        self.visit(node.then_branch)

        if node.else_branch:
            self.visit(node.else_branch)
        
        return VoidType()

    def visit_ExprStmtNode(self, node: ExprStmtNode) -> Type:
        self.visit(node.expr)
        return VoidType()

    def visit_WhileNode(self, node: WhileNode) -> Type:
        condition_type = self.visit(node.condition)
        if not isinstance(condition_type, BoolType):
            self.errors.append(f"类型错误: 'while' 语句的条件必须是布尔类型, 而不是 '{condition_type}', 在 {node.condition.start_line} 行")

        self.loop_level += 1
        self.visit(node.body)
        self.loop_level -= 1

        return VoidType()

    def visit_DoWhileNode(self, node: DoWhileNode) -> Type:
        self.loop_level += 1
        self.visit(node.body)
        self.loop_level -= 1

        condition_type = self.visit(node.condition)
        if not isinstance(condition_type, BoolType):
            self.errors.append(f"类型错误: 'do-while' 语句的条件必须是布尔类型, 而不是 '{condition_type}', 在 {node.condition.start_line} 行")

        return VoidType()

    def visit_ForNode(self, node: ForNode) -> Type:
        original_table = self.symbol_table
        for_table = SymbolTable(scope_type=ScopeType.BLOCK, parent=original_table)
        original_table.add_nested_scope(for_table)
        self.symbol_table = for_table

        if node.init:
            self.visit(node.init)
        
        if node.condition:
            condition_type = self.visit(node.condition)
            if not isinstance(condition_type, BoolType):
                self.errors.append(f"类型错误: 'for' 语句的条件必须是布尔类型, 而不是 '{condition_type}', 在 {node.condition.start_line} 行")

        if node.update:
            self.visit(node.update)

        self.loop_level += 1
        self.visit(node.body)
        self.loop_level -= 1

        self.symbol_table = original_table
        return VoidType()

    def visit_BreakNode(self, node: BreakNode) -> Type:
        if self.loop_level == 0:
            self.errors.append(f"语法错误: 'break' 语句未在循环内, 在 {node.start_line} 行")
        return VoidType()

    def visit_ContinueNode(self, node: ContinueNode) -> Type:
        if self.loop_level == 0:
            self.errors.append(f"语法错误: 'continue' 语句未在循环内, 在 {node.start_line} 行")
        return VoidType()

    def visit_FunctionNode(self, node: FunctionNode) -> Type:
        param_types = [self.resolve_type_node(p.var_type) for p in node.args]
        return_type = self.resolve_type_node(node.return_type)

        func_type = FunctionType(param_types, return_type)
        func_symbol = None
        try:
            func_symbol = self.symbol_table.add_symbol(node.name.name, func_type, kind=SymbolKind.FUNCTION)
        except NameError:
            self.errors.append(f"命名错误: 符号 '{node.name.name}' 在当前作用域已存在, 在 {node.start_line} 行")
        
        # 检查函数体
        original_table = self.symbol_table
        func_table = SymbolTable(scope_type=ScopeType.FUNCTION, parent=original_table)
        if func_symbol:
            func_symbol.scope = func_table
        self.symbol_table = func_table

        for i, param_node in enumerate(node.args):
            self.symbol_table.add_symbol(param_node.name.name, param_types[i], kind=SymbolKind.PARAMETER)

        original_return_type = self.current_function_return_type
        self.current_function_return_type = return_type

        # 直接访问函数体 BlockNode，利用 visit_BlockNode 的逻辑来创建和链接作用域
        self.visit(node.body)

        self.current_function_return_type = original_return_type
        self.symbol_table = original_table

        return VoidType()

    def visit_ReturnNode(self, node: ReturnNode) -> Type:
        """检查 return 返回值是否符合函数签名，并记录隐式返回转换。"""
        if self.current_function_return_type is None:
            self.errors.append(f"语法错误: 'return' 语句未在函数内, 在 {node.start_line} 行")
            return VoidType()

        # 检查 void 函数的 return
        if isinstance(self.current_function_return_type, VoidType):
            if node.value:
                self.errors.append(f"类型错误: 'void' 函数不应有返回值, 在 {node.start_line} 行")
            return VoidType()

        # 检查带返回值的函数的 return
        if not node.value:
            self.errors.append(f"类型错误: 函数需要一个 '{self.current_function_return_type}' 类型的返回值, 但 'return' 语句为空, 在 {node.start_line} 行")
            return VoidType()
        
        actual_return_type = self.visit(node.value)
        if not self._is_assignable(self.current_function_return_type, actual_return_type):
            self.errors.append(f"类型错误: 函数应返回 '{self.current_function_return_type}' 类型, 但返回了 '{actual_return_type}' 类型, 在 {node.start_line} 行")
        else:
            self._warn_implicit_conversion_if_needed(self.current_function_return_type, actual_return_type, node.start_line, "返回值")
            self._mark_implicit_cast_if_needed(node.value, self.current_function_return_type, actual_return_type)

        return VoidType()

    def visit_CallNode(self, node: CallNode) -> Type:
        """检查函数调用参数类型，并记录参数边界的隐式转换。"""
        # 检查被调用者是否是函数
        callee_type = self.visit(node.name)
        if not isinstance(callee_type, FunctionType):
            self.errors.append(f"类型错误: 目标不是一个函数，无法调用, 在 {node.start_line} 行")
            return ErrorType()

        # 检查参数数量
        expected_count = len(callee_type.param_types)
        actual_count = len(node.args)
        if expected_count != actual_count:
            self.errors.append(f"参数数量错误: 函数期望 {expected_count} 个参数, 但提供了 {actual_count} 个, 在 {node.start_line} 行")
            return callee_type.return_type # 即使参数数量错误，也返回预期的返回类型，以减少连锁错误

        # 逐一检查参数类型
        for i, arg_node in enumerate(node.args):
            actual_arg_type = self.visit(arg_node)
            expected_arg_type = callee_type.param_types[i]
            if not self._is_assignable(expected_arg_type, actual_arg_type):
                self.errors.append(f"类型错误: 函数参数 {i+1} 期望类型为 '{expected_arg_type}', 但提供了 '{actual_arg_type}' 类型, 在 {arg_node.start_line} 行")
            else:
                self._warn_implicit_conversion_if_needed(expected_arg_type, actual_arg_type, arg_node.start_line, f"函数参数 {i+1}")
                self._mark_implicit_cast_if_needed(arg_node, expected_arg_type, actual_arg_type)

        return callee_type.return_type

    def visit_ClassNode(self, node: ClassNode) -> Type:
        class_name = node.name.name
        
        # 先解析父类
        super_class: list[ClassType] = []
        if node.base_classes: # 假设 AST 节点有 super_classes 列表
            for super_class_node in node.base_classes:
                super_class_name = super_class_node.name
                super_class_type = self.symbol_table.lookup_type(super_class_name)

                # 验证父类是否存在且为类类型
                if not isinstance(super_class_type, ClassType):
                    self.errors.append(f"类型错误: '{super_class_name}' 不是一个有效的基类, 在 {super_class_node.start_line} 行")
                    continue # 跳过无效的父类

                # 检查是否重复继承
                if super_class_type in super_class:
                    self.errors.append(f"语法错误: 重复的基类 '{super_class_name}', 在 {super_class_node.start_line} 行")
                    continue

                super_class.append(super_class_type)
        
        class_type = ClassType(class_name, super_class=super_class)
        class_symbol = None
        try:
            class_symbol = self.symbol_table.add_symbol(class_name, class_type, kind=SymbolKind.CLASS)
        except NameError:
            self.errors.append(f"命名错误: 符号 '{class_name}' 在当前作用域已存在, 在 {node.start_line} 行")
            class_type = ErrorType()

        # 检查类的内部
        original_table = self.symbol_table
        class_table = SymbolTable(scope_type=ScopeType.CLASS, parent=original_table)
        if class_symbol:
            class_symbol.scope = class_table
        self.symbol_table = class_table

        original_class_type = self.current_class_type
        self.current_class_type = class_type if isinstance(class_type, ClassType) else None

        if isinstance(class_type, ClassType):
            # 先处理父类成员
            for base_class in reversed(class_type.mro):
                if base_class is class_type: # 跳过自身
                    continue
                
                # 合并字段
                for field_name, field_type in base_class.fields.items():
                    class_type.fields[field_name] = field_type
                    
                # 合并方法
                for method_name, method_type in base_class.methods.items():
                    class_type.methods[method_name] = method_type
            
            for member in node.body.statements:
                if isinstance(member, VarDeclNode): # 字段
                    field_type = self.resolve_type_node(member.var_type)
                    class_type.fields[member.name.name] = field_type
                    self.symbol_table.add_symbol(member.name.name, field_type, kind=SymbolKind.VARIABLE)
                elif isinstance(member, FunctionNode): # 方法
                    param_types = [self.resolve_type_node(p.var_type) for p in member.args]
                    return_type = self.resolve_type_node(member.return_type)
                    method_type = FunctionType(param_types, return_type)
                    class_type.methods[member.name.name] = method_type
                    self.symbol_table.add_symbol(member.name.name, method_type, kind=SymbolKind.FUNCTION)
            
            has_user_defined_init = any(
                isinstance(member, FunctionNode) and member.name.name == "__init__"
                for member in node.body.statements
            )

            # 如果当前类没有显式定义 __init__，则在当前类作用域补一个默认构造函数。
            # 不能仅依赖 class_type.methods，因为它可能已合并到父类的 __init__。
            if not has_user_defined_init:
                default_init_type = FunctionType(param_types=[], return_type=VoidType())
                class_type.methods["__init__"] = default_init_type
                # 为默认构造函数创建符号和作用域
                init_symbol = self.symbol_table.add_symbol("__init__", default_init_type, kind=SymbolKind.FUNCTION)
                func_table = SymbolTable(scope_type=ScopeType.FUNCTION, parent=self.symbol_table)
                init_symbol.scope = func_table
                func_table.add_symbol('this', class_type, kind=SymbolKind.VARIABLE)
                # 为空的 body 创建一个空的 block scope，以保持与用户定义函数的一致性
                empty_block_scope = SymbolTable(scope_type=ScopeType.BLOCK, parent=func_table)
                func_table.add_nested_scope(empty_block_scope)


        for member in node.body.statements:
            if isinstance(member, FunctionNode):
                # 检查方法体
                method_name = member.name.name
                method_type = self.current_class_type.methods[method_name]

                method_symbol = self.symbol_table.lookup_value(method_name, current_scope_only=True)

                original_method_scope_parent_table = self.symbol_table # 当前是 class_table
                func_table = SymbolTable(scope_type=ScopeType.FUNCTION, parent=original_method_scope_parent_table)
                
                if method_symbol:
                    method_symbol.scope = func_table
                else:
                    self.errors.append(f"内部错误: 无法在类 '{class_name}' 中找到方法 '{method_name}' 的符号")
                    continue

                self.symbol_table = func_table
                self.symbol_table.add_symbol('this', self.current_class_type, kind=SymbolKind.VARIABLE)

                for i, param_node in enumerate(member.args):
                    self.symbol_table.add_symbol(param_node.name.name, method_type.param_types[i], kind=SymbolKind.PARAMETER)

                original_return_type = self.current_function_return_type
                self.current_function_return_type = method_type.return_type

                # 直接访问方法体 BlockNode，利用 visit_BlockNode 的逻辑来创建和链接作用域
                self.visit(member.body)

                self.current_function_return_type = original_return_type
                self.symbol_table = original_method_scope_parent_table

        self.current_class_type = original_class_type
        self.symbol_table = original_table

        return VoidType()

    def visit_GetPropertyNode(self, node: GetPropertyNode) -> Type:
        # 检查super节点的获取属性
        if isinstance(node.obj, SuperNode):
            super_class_type = self.visit(node.obj)
            if not isinstance(super_class_type, ClassType):
                return ErrorType()

            prop_name = node.property_name.name
            if prop_name in super_class_type.methods:
                return super_class_type.methods[prop_name]
            
            if prop_name in super_class_type.fields:
                return super_class_type.fields[prop_name]

            self.errors.append(f"属性错误: 父类 '{super_class_type.name}' 没有名为 '{prop_name}' 的属性, 在 {node.start_line} 行")
            return ErrorType()
        
        obj_type = self.visit(node.obj)
        if not isinstance(obj_type, ClassType):
            self.errors.append(f"类型错误: 只有类的实例才能访问属性, 而不是 '{obj_type}', 在 {node.start_line} 行")
            return ErrorType()

        prop_name = node.property_name.name
        if prop_name in obj_type.fields:
            return obj_type.fields[prop_name]
        if prop_name in obj_type.methods:
            return obj_type.methods[prop_name]

        self.errors.append(f"属性错误: 类型 '{obj_type.name}' 没有名为 '{prop_name}' 的属性, 在 {node.start_line} 行")
        return ErrorType()

    def visit_NewInstanceNode(self, node: NewInstanceNode) -> Type:
        """检查构造函数调用参数类型，并记录构造参数边界的隐式转换。"""
        class_call = node.class_call
        
        class_type = self.visit(class_call.name)
        if not isinstance(class_type, ClassType):
            self.errors.append(f"类型错误: 'new' 关键字只能用于类, 而不是 '{class_type}', 在 {node.start_line} 行")
            return ErrorType()

        constructor_type = class_type.methods.get("__init__")
        
        if constructor_type:
            expected_count = len(constructor_type.param_types)
            actual_count = len(class_call.args)
            if expected_count != actual_count:
                self.errors.append(f"构造函数参数数量错误: '{class_type.name}' 的构造函数期望 {expected_count} 个参数, 但提供了 {actual_count} 个, 在 {node.start_line} 行")
            
            for i, arg_node in enumerate(class_call.args):
                actual_arg_type = self.visit(arg_node)
                expected_arg_type = constructor_type.param_types[i]
                if not self._is_assignable(expected_arg_type, actual_arg_type):
                    self.errors.append(f"类型错误: 构造函数参数 {i+1} 期望类型为 '{expected_arg_type}', 但提供了 '{actual_arg_type}' 类型, 在 {arg_node.start_line} 行")
                else:
                    self._warn_implicit_conversion_if_needed(expected_arg_type, actual_arg_type, arg_node.start_line, f"构造函数参数 {i+1}")
                    self._mark_implicit_cast_if_needed(arg_node, expected_arg_type, actual_arg_type)
        elif len(class_call.args) > 0:
            self.errors.append(f"构造函数参数错误: 类 '{class_type.name}' 没有定义构造函数, 不能接受参数, 在 {node.start_line} 行")

        return class_type

    def visit_ParenOrCastNode(self, node: ParenOrCastNode) -> Type:
        target_type = self.resolve_type_node(node.target_type, report_error=False)
        if not isinstance(target_type, ErrorType):
            cast_node = CastNode(
                node.target_type,
                node.expression,
                start_line=node.start_line,
                start_column=node.start_column,
                end_line=node.end_line,
                end_column=node.end_column
            )
            node.resolved_node = cast_node
            source_type = self.visit(node.expression)
            if isinstance(source_type, ErrorType):
                return ErrorType()
            if not self._is_castable(target_type, source_type):
                self.errors.append(f"类型错误: 无法将类型 '{source_type}' 强制转换为 '{target_type}', 在 {node.start_line} 行")
                return ErrorType()
            return target_type

        expr_node = None
        if node.target_type.pointer_level == 0:
            left_name = node.target_type.type_name.name
            if self.symbol_table.lookup_value(left_name) is not None and isinstance(node.expression, UnaryOpNode):
                op_map = {
                    Operator.ADD: Operator.ADD,
                    Operator.SUBTRACT: Operator.SUBTRACT,
                    Operator.DEREFERENCE: Operator.MULTIPLY,
                }
                mapped_op = op_map.get(node.expression.op)
                if mapped_op is not None:
                    left = NameNode(
                        left_name,
                        start_line=node.start_line,
                        start_column=node.start_column,
                        end_line=node.end_line,
                        end_column=node.end_column
                    )
                    expr_node = BinaryOpNode(
                        left,
                        mapped_op,
                        node.expression.expr,
                        start_line=node.start_line,
                        start_column=node.start_column,
                        end_line=node.end_line,
                        end_column=node.end_column
                    )

        if expr_node is not None:
            node.resolved_node = expr_node
            return self.visit(expr_node)

        self.resolve_type_node(node.target_type, report_error=True)
        return ErrorType()

    def visit_CastNode(self, node: CastNode) -> Type:
        target_type = self.resolve_type_node(node.target_type)
        source_type = self.visit(node.expression)
        if isinstance(target_type, ErrorType) or isinstance(source_type, ErrorType):
            return ErrorType()
        if not self._is_castable(target_type, source_type):
            self.errors.append(f"类型错误: 无法将类型 '{source_type}' 强制转换为 '{target_type}', 在 {node.start_line} 行")
            return ErrorType()
        return target_type

    def visit_SuperNode(self, node: SuperNode) -> Type:
        if self.current_class_type is None:
            self.errors.append(f"语法错误: 'super' 只能在类的方法内部使用, 在 {node.start_line} 行")
            return ErrorType()

        if not self.current_class_type.super_class:
            self.errors.append(f"类型错误: 类 '{self.current_class_type.name}' 没有父类，无法使用 'super', 在 {node.start_line} 行")
            return ErrorType()

        super_class_type = self.current_class_type.super_class[0]
        
        setattr(node, 'type_', super_class_type)
        return super_class_type

from verbose_c.compiler.enum import ScopeType
from verbose_c.object.t_float import VBCFloat
from verbose_c.object.t_integer import VBCInteger
from verbose_c.utils.visitor import VisitorBase
from verbose_c.parser.parser.ast.node import *
from verbose_c.compiler.symbol import SymbolTable, SymbolKind
from verbose_c.typing.types import (
    Type, VoidType, NullType, IntegerType, FloatType, StringType, BoolType,
    FunctionType, ClassType, AnyType, ErrorType
)
from verbose_c.object.enum import VBCObjectType


# 将字符串类型名映射到编译时Type对象
BUILTIN_TYPE_MAP: dict[str, Type] = {
    "void": VoidType(),
    "char": IntegerType(VBCObjectType.CHAR),
    "int": IntegerType(VBCObjectType.INT),
    "long": IntegerType(VBCObjectType.LONG),
    "long long": IntegerType(VBCObjectType.LONGLONG),
    "super int": IntegerType(VBCObjectType.NLINT),
    "float": FloatType(VBCObjectType.FLOAT),
    "double": FloatType(VBCObjectType.DOUBLE),
    "super float": FloatType(VBCObjectType.NLFLOAT),
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
    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
        self.errors: list[str] = []
        self.loop_level = 0
        self.current_function_return_type: Type | None = None   # 跟踪当前函数返回类型
        self.current_class_type: ClassType | None = None # 跟踪当前类上下文

    def visit(self, node: ASTNode) -> Type:
        """重写 visit 方法以提供更精确的类型提示"""
        return super().visit(node)

    def resolve_type_node(self, type_node: TypeNode) -> Type:
        """
        将 AST 中的 TypeNode 转换为 Type 对象。
        """
        type_name = type_node.type_name.name
        builtin_type = BUILTIN_TYPE_MAP.get(type_name)
        if builtin_type:
            return builtin_type
        symbol = self.symbol_table.lookup(type_name)
        if symbol and isinstance(symbol.type_, ClassType):
            return symbol.type_
        self.errors.append(f"未知类型 '{type_name}', 在 {type_node.start_line} 行")
        return ErrorType()

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
        symbol = self.symbol_table.lookup(node.name)
        if symbol is None:
            self.errors.append(f"命名错误: '{node.name}' 未定义, 在 {node.start_line} 行")
            return ErrorType()
        return symbol.type_

    def visit_UnaryOpNode(self, node: UnaryOpNode) -> Type:
        operand_type = self.visit(node.expr)
        if isinstance(operand_type, ErrorType):
            return ErrorType()

        if node.op in (Operator.SUBTRACT, Operator.ADD):
            if not isinstance(operand_type, (IntegerType, FloatType)):
                self.errors.append(f"类型错误: 操作符 '{node.op.value}' 不能用于类型 '{operand_type}', 在 {node.start_line} 行")
                return ErrorType()
            return operand_type

        if node.op == Operator.NOT:
            if not isinstance(operand_type, BoolType):
                self.errors.append(f"类型错误: 操作符 '!' 只能用于布尔类型, 而不是 '{operand_type}', 在 {node.start_line} 行")
                return ErrorType()
            return BoolType()

        self.errors.append(f"内部错误: 未知的一元操作符 '{node.op.value}', 在 {node.start_line} 行")
        return ErrorType()

    def visit_BinaryOpNode(self, node: BinaryOpNode) -> Type:
        left_type = self.visit(node.left)
        right_type = self.visit(node.right)

        if isinstance(left_type, ErrorType) or isinstance(right_type, ErrorType):
            return ErrorType()

        op = node.op

        # --- 算术运算 ---
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

        # --- 比较运算 ---
        if op in (Operator.GREATER_THAN, Operator.GREATER_EQUAL, Operator.LESS_THAN, Operator.LESS_EQUAL, Operator.EQUAL, Operator.NOT_EQUAL):
            # 允许数字之间，或相同类型之间比较
            is_numeric = isinstance(left_type, (IntegerType, FloatType)) and isinstance(right_type, (IntegerType, FloatType))
            is_same_type = type(left_type) is type(right_type)

            if not (is_numeric or is_same_type):
                 self.errors.append(f"类型错误: 无法比较不兼容的类型 '{left_type}' 和 '{right_type}', 在 {node.start_line} 行")
                 return ErrorType()
            return BoolType()

        # --- 逻辑运算 ---
        if op in (Operator.LOGICAL_AND, Operator.LOGICAL_OR):
            if not (isinstance(left_type, BoolType) and isinstance(right_type, BoolType)):
                self.errors.append(f"类型错误: 逻辑操作符 '{op.value}' 的操作数必须是布尔类型, 而不是 '{left_type}' 和 '{right_type}', 在 {node.start_line} 行")
                return ErrorType()
            return BoolType()

        self.errors.append(f"内部错误: 未知的二元操作符 '{op.value}', 在 {node.start_line} 行")
        return ErrorType()

    # 语句的类型检查
    def visit_VarDeclNode(self, node: VarDeclNode) -> Type:
        declared_type = self.resolve_type_node(node.var_type)
        
        if node.init_exp:
            init_type = self.visit(node.init_exp)
            if isinstance(init_type, ErrorType):
                return ErrorType()

            if not self.is_assignable(declared_type, init_type):
                self.errors.append(f"类型错误: 不能将类型 '{init_type}' 的值赋给类型为 '{declared_type}' 的变量 '{node.name.name}', 在 {node.start_line} 行")

        try:
            self.symbol_table.add_symbol(node.name.name, declared_type, kind=SymbolKind.VARIABLE)
        except NameError:
            self.errors.append(f"命名错误: 变量 '{node.name.name}' 在当前作用域已存在, 在 {node.start_line} 行")

        return VoidType()

    def visit_AssignmentNode(self, node: AssignmentNode) -> Type:
        target_type = self.visit(node.target)
        if isinstance(target_type, ErrorType):
            return ErrorType()

        value_type = self.visit(node.value)
        if isinstance(value_type, ErrorType):
            return ErrorType()

        if not self.is_assignable(target_type, value_type):
            self.errors.append(f"类型错误: 不能将类型 '{value_type}' 的值赋给类型为 '{target_type}' 的目标, 在 {node.start_line} 行")
            return ErrorType()

        return value_type

    def is_assignable(self, target_type: Type, source_type: Type) -> bool:
        """
        检查 source_type 是否能安全地赋值给 target_type。
        """
        # 规则1: 类型完全相同
        if target_type == source_type:
            return True
        
        # 规则2: 允许任何类型赋值给 AnyType (如果未来支持)
        if isinstance(target_type, AnyType):
            return True

        # 规则3: 允许整数赋值给浮点数 (提升)
        if isinstance(target_type, FloatType) and isinstance(source_type, IntegerType):
            return True
            
        # 规则4: 允许低精度数字赋值给高精度数字
        if isinstance(target_type, (IntegerType, FloatType)) and isinstance(source_type, (IntegerType, FloatType)):
            target_priority = TYPE_PROMOTION_PRIORITY.get(target_type.kind, -1)
            source_priority = TYPE_PROMOTION_PRIORITY.get(source_type.kind, -1)
            return target_priority >= source_priority

        return False

    def visit_BlockNode(self, node: BlockNode) -> Type:
        original_table = self.symbol_table
        block_table = SymbolTable(scope_type=ScopeType.BLOCK, parent=original_table)
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

        self.visit(node.body)

        self.current_function_return_type = original_return_type
        self.symbol_table = original_table

        return VoidType()

    def visit_ReturnNode(self, node: ReturnNode) -> Type:
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
        if not self.is_assignable(self.current_function_return_type, actual_return_type):
            self.errors.append(f"类型错误: 函数应返回 '{self.current_function_return_type}' 类型, 但返回了 '{actual_return_type}' 类型, 在 {node.start_line} 行")

        return VoidType()

    def visit_CallNode(self, node: CallNode) -> Type:
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
            if not self.is_assignable(expected_arg_type, actual_arg_type):
                self.errors.append(f"类型错误: 函数参数 {i+1} 期望类型为 '{expected_arg_type}', 但提供了 '{actual_arg_type}' 类型, 在 {arg_node.start_line} 行")

        return callee_type.return_type

    def visit_ClassNode(self, node: ClassNode) -> Type:
        class_name = node.name.name
        
        class_type = ClassType(class_name)
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
            
            # 如果用户没有定义 __init__，则添加一个默认的
            if "__init__" not in class_type.methods:
                default_init_type = FunctionType(param_types=[], return_type=VoidType())
                class_type.methods["__init__"] = default_init_type


        for member in node.body.statements:
            if isinstance(member, FunctionNode):
                # 检查方法体
                method_name = member.name.name
                method_type = self.current_class_type.methods[method_name]

                method_symbol = self.symbol_table.lookup(method_name, current_scope_only=True)

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

                self.visit(member.body)

                self.current_function_return_type = original_return_type
                self.symbol_table = original_method_scope_parent_table

        self.current_class_type = original_class_type
        self.symbol_table = original_table

        return VoidType()

    def visit_GetPropertyNode(self, node: GetPropertyNode) -> Type:
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
                if not self.is_assignable(expected_arg_type, actual_arg_type):
                    self.errors.append(f"类型错误: 构造函数参数 {i+1} 期望类型为 '{expected_arg_type}', 但提供了 '{actual_arg_type}' 类型, 在 {arg_node.start_line} 行")
        elif len(class_call.args) > 0:
            self.errors.append(f"构造函数参数错误: 类 '{class_type.name}' 没有定义构造函数, 不能接受参数, 在 {node.start_line} 行")

        return class_type

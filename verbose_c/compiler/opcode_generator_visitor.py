from verbose_c.compiler.enum import LoopType, ScopeType, SymbolKind
from verbose_c.compiler.opcode import Opcode
from verbose_c.compiler.symbol import SymbolTable
from verbose_c.object.class_ import VBCClass
from verbose_c.object.function import VBCFunction
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_float import VBCFloat
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_null import VBCNull
from verbose_c.object.t_string import VBCString
from verbose_c.object.struct import VBCStruct
from verbose_c.object.enum import VBCObjectType
from verbose_c.utils.visitor import VisitorBase
from verbose_c.parser.parser.ast.node import *
from verbose_c.typing.types import *

class LoopContext:
    """
    循环上下文类，管理循环的控制标签
    """
    def __init__(self, loop_type: LoopType, continue_label: str, break_label: str):
        self.loop_type = loop_type           # 循环类型：'for', 'while' 等
        self.continue_label = continue_label # continue语句跳转的标签
        self.break_label = break_label       # break语句跳转的标签
    
    def __repr__(self):
        return f"LoopContext(type={self.loop_type}, continue={self.continue_label}, break={self.break_label})"
    
    def get_break_target(self, levels: int = 1) -> str:
        """
        TODO 获取break跳转目标标签
        高级功能，后续添加，现在不做实现
        """
        if levels != 1:
            raise NotImplementedError(f"暂不支持多层跳出，levels={levels}")
        return self.break_label
    
    def get_continue_target(self, levels: int = 1) -> str:
        """
        TODO 获取continue跳转目标标签
        高级功能，后续添加，现在不做实现
        """
        if levels != 1:
            raise NotImplementedError(f"暂不支持多层跳转，levels={levels}")
        return self.continue_label

class OpcodeGenerator(VisitorBase):
    """
    根据AST生成机器码的访问者类
    """
    def __init__(self, symbol_table: SymbolTable, source_path: str | None = None, function_name: str | None = None, optimize_level: int = 0):
        self.symbol_table: SymbolTable = symbol_table
        self.source_path = source_path
        self.current_function_name: str | None = function_name
        self.optimize_level = optimize_level
        self.bytecode: list[tuple] = []
        self.labels = {}
        self.constant_pool = []
        self.lineno_table: list[tuple[int, int]] = [] # (字节码偏移, 行号)
        self.optimization_result = None
        self.current_line = -1
        self.next_label_id = 0
        self.loop_stack: list[LoopContext] = []  # 循环标签栈，后续支持嵌套循环和多层跳出
        self.switch_stack: list[str] = []  # switch 结束标签栈
        self.function_compilation_results = {} # 存储函数编译结果
        self._nested_scope_indices: dict[SymbolTable, int] = {} # 跟踪每个父作用域下嵌套作用域的访问索引

    def visit(self, node: ASTNode):
        if node.start_line is not None:
            self.current_line = node.start_line
        return super().visit(node)

    # 工具方法
    def _emit(self, opcode: Opcode, operand=None):
        """
        添加操作码到字节码流中, 并记录行号信息
        
        Args:
            opcode (Opcode): 操作码
            operand (_type_, optional): 操作数. Defaults to None.
        """
        # 记录行号映射：当前字节码的偏移量 -> 当前行号
        # 只有当行号变化时才记录，以节省空间
        if self.current_line is not None and (
            not self.lineno_table or self.lineno_table[-1][1] != self.current_line
        ):
            self.lineno_table.append((len(self.bytecode), self.current_line))

        if operand is not None:
            self.bytecode.append((opcode, operand))
        else:
            self.bytecode.append((opcode,))

    def _add_constant(self, value) -> int:
        """
        添加常量到常量池，确保类型和值都匹配时才复用。

        Args:
            value (any): 要添加的常量对象
        """
        for i, constant in enumerate(self.constant_pool):
            if type(constant) is type(value) and constant == value:
                return i
        
        self.constant_pool.append(value)
        return len(self.constant_pool) - 1

    def _generate_label(self, lebel_name="unnamed"):
        """
        生成唯一标签

        Returns:
            label (str): 标签
        """
        label = f"L{self.next_label_id}_{lebel_name}"
        self.next_label_id += 1
        return label

    def _mark_label(self, label):
        """标记标签位置"""
        self.labels[label] = len(self.bytecode)

    def resolve_labels(self):
        for i, instruction in enumerate(self.bytecode):
            if len(instruction) != 2:
                continue
            opcode, operand = instruction
            if isinstance(operand, str) and operand in self.labels:
                self.bytecode[i] = (opcode, self.labels[operand])

    def optimize_bytecode(self):
        from verbose_c.compiler.bytecode_optimizer import optimize_bytecode

        if self.optimize_level <= 0:
            return None
        if self.optimize_level != 1:
            raise RuntimeError(f"Unsupported optimize level: {self.optimize_level}")

        result = optimize_bytecode(self.bytecode, self.lineno_table, self.labels)
        self.bytecode = result.optimized_bytecode
        self.lineno_table = result.optimized_lineno_table
        self.labels = result.optimized_labels
        self.optimization_result = result
        return result

    def _runtime_type_enum_from_type(self, type_obj: Type | None):
        """把编译期 Type 映射为运行时 CAST 所需的对象类型枚举。"""
        if isinstance(type_obj, IntegerType):
            return type_obj.kind
        if isinstance(type_obj, FloatType):
            return type_obj.kind
        if isinstance(type_obj, BoolType):
            return VBCObjectType.BOOL
        if isinstance(type_obj, StringType):
            return VBCObjectType.STRING
        if isinstance(type_obj, PointerType):
            return VBCObjectType.POINTER
        if isinstance(type_obj, ClassType):
            return VBCObjectType.INSTANCE
        if isinstance(type_obj, StructType):
            return VBCObjectType.STRUCT
        return None

    def _element_type_enum_from_type(self, type_obj: Type | None):
        """数组元素类型映射为运行时枚举"""
        return self._runtime_type_enum_from_type(type_obj)

    def _emit_array_decay_if_needed(self, expr_node: ASTNode) -> None:
        if not getattr(expr_node, "_needs_array_decay", False):
            return
        if isinstance(expr_node, NameNode):
            symbol = self.symbol_table.lookup_value(expr_node.name)
            if symbol is None or not isinstance(symbol.type_, ArrayType):
                raise RuntimeError(f"内部错误: 数组衰变目标无效 '{expr_node.name}'")
            elem_enum = self._element_type_enum_from_type(symbol.type_.element_type)
            if elem_enum is None:
                raise RuntimeError("内部错误: 不支持的数组元素类型衰变")
            self._emit(Opcode.ARRAY_DECAY, elem_enum)

    def _emit_load_array_base(self, symbol) -> None:
        if symbol.address is not None:
            self._emit(Opcode.LOAD_LOCAL_VAR, symbol.address)
        else:
            self._emit(Opcode.LOAD_GLOBAL_VAR, symbol.name)

    def _emit_subscript_base(self, base: ASTNode) -> None:
        if isinstance(base, NameNode):
            symbol = self.symbol_table.lookup_value(base.name)
            if symbol is None:
                raise RuntimeError(f"未定义的标识符: {base.name}")
            self._emit_load_array_base(symbol)
        else:
            raise RuntimeError(f"不支持的数组下标基址: {type(base).__name__}")

    def _subscript_operand(self, node: SubscriptNode) -> tuple[int, VBCObjectType] | None:
        array_type = getattr(node, "_array_type", None)
        if array_type is None:
            return None
        if not isinstance(array_type, ArrayType):
            raise RuntimeError("内部错误: SubscriptNode 缺少有效的 _array_type")
        elem_enum = self._element_type_enum_from_type(array_type.element_type)
        if elem_enum is None:
            raise RuntimeError("内部错误: 不支持的数组元素类型")
        return array_type.size, elem_enum

    def _pointer_target_enum(self, pointer_type: PointerType | None) -> VBCObjectType:
        if not isinstance(pointer_type, PointerType):
            raise RuntimeError("内部错误: 缺少有效的指针目标类型")
        target_enum = self._element_type_enum_from_type(pointer_type.base_type)
        if target_enum is None:
            raise RuntimeError("内部错误: 不支持的指针目标类型")
        return target_enum

    def _get_or_add_struct_constant(self, struct_type: StructType) -> int:
        """将结构体布局注册进当前常量池，依赖 _add_constant 的按值去重实现"一个类型一份描述对象"。"""
        fields = [(name, self._element_type_enum_from_type(field_type)) for name, field_type in struct_type.fields]
        layout = VBCStruct(struct_type.name, fields)
        return self._add_constant(layout)

    def _struct_field_operand(self, node: GetPropertyNode, struct_type: StructType) -> tuple[int, int]:
        offset = struct_type.field_offset(node.property_name.name)
        if offset is None:
            raise RuntimeError(f"内部错误: 结构体 '{struct_type.name}' 缺少字段 '{node.property_name.name}'")
        return struct_type.slot_count, offset

    def _emit_struct_base(self, obj_node: ASTNode, via_pointer: bool) -> None:
        """压入结构体基址：'.' 直接读取变量槽中的基址，'->' 先取出指针对象再还原基址"""
        if via_pointer:
            self.visit(obj_node)
            self._emit(Opcode.POINTER_ADDRESS)
            return
        if isinstance(obj_node, NameNode):
            symbol = self.symbol_table.lookup_value(obj_node.name)
            if symbol is None:
                raise RuntimeError(f"未定义的标识符: {obj_node.name}")
            self._emit_load_array_base(symbol)
            return
        raise RuntimeError(f"不支持的结构体字段基址来源: {type(obj_node).__name__}")

    def _emit_implicit_cast_if_needed(self, expr_node: ASTNode):
        """根据类型检查阶段标记，为表达式补发隐式 CAST 指令。"""
        target_type = getattr(expr_node, "_implicit_cast_target", None)
        target_enum = self._runtime_type_enum_from_type(target_type)
        if target_enum is not None:
            self._emit(Opcode.CAST, target_enum)

    def _emit_expr_with_array_decay(self, expr_node: ASTNode) -> None:
        self.visit(expr_node)
        self._emit_array_decay_if_needed(expr_node)

    def _emit_pointer_index_address(self, base: ASTNode, index: ASTNode) -> None:
        self._emit_expr_with_array_decay(base)
        self.visit(index)
        self._emit(Opcode.POINTER_ADD)

    def _emit_lvalue_address(self, target: ASTNode) -> None:
        """生成左值地址，栈顶结果为 VBCPointer。"""
        if isinstance(target, NameNode):
            symbol = self.symbol_table.lookup_value(target.name)
            if symbol is None:
                raise RuntimeError(f"未定义的标识符: {target.name}")
            if isinstance(symbol.type_, ArrayType):
                raise RuntimeError(f"内部错误: 数组变量 '{target.name}' 不能直接取地址")
            target_enum = self._element_type_enum_from_type(symbol.type_)
            if target_enum is None:
                raise RuntimeError(f"内部错误: 不支持取地址的类型 '{symbol.type_}'")
            identifier = symbol.address if symbol.address is not None else symbol.name
            self._emit(Opcode.LOAD_ADDRESS, (identifier, target_enum))
            return

        if isinstance(target, UnaryOpNode) and target.op == Operator.DEREFERENCE:
            self._emit_expr_with_array_decay(target.expr)
            return

        if isinstance(target, SubscriptNode):
            pointer_type = getattr(target, "_subscript_base_type", None)
            if not isinstance(pointer_type, PointerType):
                raise RuntimeError("内部错误: 下标表达式缺少指针基址类型")
            operand = self._subscript_operand(target)
            if operand is not None:
                _size, elem_enum = operand
                self._emit_subscript_base(target.base)
                self.visit(target.index)
                self._emit(Opcode.ADD)
                self._emit(Opcode.ARRAY_DECAY, elem_enum)
            else:
                self._emit_pointer_index_address(target.base, target.index)
            return

        if isinstance(target, GetPropertyNode):
            struct_type = getattr(target, "_struct_type", None)
            if not isinstance(struct_type, StructType):
                raise RuntimeError("内部错误: 当前仅支持结构体字段取地址")
            field_type = struct_type.field_type(target.property_name.name)
            target_enum = self._element_type_enum_from_type(field_type)
            if target_enum is None:
                raise RuntimeError(f"内部错误: 不支持字段 '{target.property_name.name}' 的取地址类型")
            _slot_count, offset = self._struct_field_operand(target, struct_type)
            self._emit_struct_base(target.obj, target.via_pointer)
            if offset:
                offset_index = self._add_constant(VBCInteger(offset, VBCObjectType.INT))
                self._emit(Opcode.LOAD_CONSTANT, offset_index)
                self._emit(Opcode.ADD)
            self._emit(Opcode.ARRAY_DECAY, target_enum)
            return

        raise RuntimeError(f"不支持取地址的左值: {type(target).__name__}")

    def _emit_load_lvalue(self, target: ASTNode) -> None:
        """将左值当前值压栈：NameNode / *p / obj.field"""
        if isinstance(target, NameNode):
            symbol = self.symbol_table.lookup_value(target.name)
            if symbol is None:
                raise RuntimeError(f"未定义的标识符: {target.name}")
            if symbol.address is not None:
                self._emit(Opcode.LOAD_LOCAL_VAR, symbol.address)
            else:
                self._emit(Opcode.LOAD_GLOBAL_VAR, target.name)
        elif isinstance(target, UnaryOpNode) and target.op == Operator.DEREFERENCE:
            self.visit(target.expr)
            self._emit(Opcode.LOAD_BY_POINTER)
        elif isinstance(target, GetPropertyNode):
            struct_type = getattr(target, "_struct_type", None)
            if struct_type is not None:
                slot_count, offset = self._struct_field_operand(target, struct_type)
                self._emit_struct_base(target.obj, target.via_pointer)
                self._emit(Opcode.LOAD_FIELD, (slot_count, offset))
            else:
                self.visit(target.obj)
                property_name = self._add_constant(VBCString(target.property_name.name))
                self._emit(Opcode.LOAD_CONSTANT, property_name)
                self._emit(Opcode.GET_PROPERTY)
        elif isinstance(target, SubscriptNode):
            operand = self._subscript_operand(target)
            if operand is not None:
                size, elem_enum = operand
                self._emit_subscript_base(target.base)
                self.visit(target.index)
                self._emit(Opcode.LOAD_INDEX, (size, elem_enum))
            else:
                self._emit_lvalue_address(target)
                self._emit(Opcode.LOAD_BY_POINTER)
        else:
            raise RuntimeError(f"不支持的左值读取目标: {type(target).__name__}")

    def _emit_store_lvalue(self, target: ASTNode) -> None:
        """弹出栈顶值写入左值，不保留表达式结果。"""
        if isinstance(target, NameNode):
            symbol = self.symbol_table.lookup_value(target.name)
            if symbol is None:
                raise RuntimeError(f"未定义的变量: {target.name}")
            if symbol.address is not None:
                self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
            else:
                self._emit(Opcode.STORE_GLOBAL_VAR, target.name)
        elif isinstance(target, UnaryOpNode) and target.op == Operator.DEREFERENCE:
            self.visit(target.expr)
            self._emit(Opcode.STORE_BY_POINTER)
            self._emit(Opcode.POP)
        elif isinstance(target, GetPropertyNode):
            struct_type = getattr(target, "_struct_type", None)
            if struct_type is not None:
                slot_count, offset = self._struct_field_operand(target, struct_type)
                self._emit_struct_base(target.obj, target.via_pointer)
                self._emit(Opcode.STORE_FIELD, (slot_count, offset))
                self._emit(Opcode.POP)
            else:
                self.visit(target.obj)
                property_name = self._add_constant(VBCString(target.property_name.name))
                self._emit(Opcode.LOAD_CONSTANT, property_name)
                self._emit(Opcode.SET_PROPERTY)
                self._emit(Opcode.POP)
        elif isinstance(target, SubscriptNode):
            operand = self._subscript_operand(target)
            if operand is not None:
                size, elem_enum = operand
                self._emit_subscript_base(target.base)
                self.visit(target.index)
                self._emit(Opcode.STORE_INDEX, (size, elem_enum))
                self._emit(Opcode.POP)
            else:
                self._emit_lvalue_address(target)
                self._emit(Opcode.STORE_BY_POINTER)
                self._emit(Opcode.POP)
        else:
            raise RuntimeError(f"不支持的左值写入目标: {type(target).__name__}")

    def _emit_store_lvalue_keep(self, target: ASTNode) -> None:
        """写入左值并保留刚写入的值在栈顶。"""
        if isinstance(target, NameNode):
            self._emit(Opcode.DUP)
            symbol = self.symbol_table.lookup_value(target.name)
            if symbol is None:
                raise RuntimeError(f"未定义的变量: {target.name}")
            if symbol.address is not None:
                self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
            else:
                self._emit(Opcode.STORE_GLOBAL_VAR, target.name)
        elif isinstance(target, UnaryOpNode) and target.op == Operator.DEREFERENCE:
            self.visit(target.expr)
            self._emit(Opcode.STORE_BY_POINTER)
        elif isinstance(target, GetPropertyNode):
            struct_type = getattr(target, "_struct_type", None)
            self._emit(Opcode.DUP)
            if struct_type is not None:
                slot_count, offset = self._struct_field_operand(target, struct_type)
                self._emit_struct_base(target.obj, target.via_pointer)
                self._emit(Opcode.STORE_FIELD, (slot_count, offset))
            else:
                self.visit(target.obj)
                property_name = self._add_constant(VBCString(target.property_name.name))
                self._emit(Opcode.LOAD_CONSTANT, property_name)
                self._emit(Opcode.SET_PROPERTY)
        elif isinstance(target, SubscriptNode):
            operand = self._subscript_operand(target)
            self._emit(Opcode.DUP)
            if operand is not None:
                size, elem_enum = operand
                self._emit_subscript_base(target.base)
                self.visit(target.index)
                self._emit(Opcode.STORE_INDEX, (size, elem_enum))
            else:
                self._emit_lvalue_address(target)
                self._emit(Opcode.STORE_BY_POINTER)
        else:
            raise RuntimeError(f"不支持的左值写入目标: {type(target).__name__}")

    # 基本数据类型
    def visit_NameNode(self, node: NameNode):
        if node.name == "__func__":
            if self.current_function_name is None:
                raise Exception(f"'__func__' 只能在函数体内使用, 在行: {node.start_line}, 列: {node.start_column}")
            vbc_str = VBCString(self.current_function_name)
            const_index = self._add_constant(vbc_str)
            self._emit(Opcode.LOAD_CONSTANT, const_index)
            return

        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is None:
            raise Exception(f"未定义的标识符: {node.name}, 在行: {node.start_line}, 列: {node.start_column}")

        # enum 成员是编译期常量，直接折叠为 LOAD_CONSTANT，不占用变量槽
        if symbol.const_value is not None:
            const_index = self._add_constant(VBCInteger(symbol.const_value, VBCObjectType.INT))
            self._emit(Opcode.LOAD_CONSTANT, const_index)
            return

        if symbol.address is not None:
            self._emit(Opcode.LOAD_LOCAL_VAR, symbol.address)
        else:
            self._emit(Opcode.LOAD_GLOBAL_VAR, node.name)
    
    def visit_NumberNode(self, node: NumberNode):
        target_type = getattr(node, "inferred_type", None)
        if target_type is None:
            # 如果没有推断类型，使用默认类型
            if isinstance(node.value, int):
                target_type = VBCObjectType.INT
            elif isinstance(node.value, float):
                target_type = VBCObjectType.FLOAT
            else:
                raise TypeError(f"未知的 NumberNode 值类型: {type(node.value).__name__}")

        # 生成对应的VBC对象
        if target_type in VBCInteger.bit_width.keys():
            vbc_int = VBCInteger(node.value, target_type)
            const_index = self._add_constant(vbc_int)
            self._emit(Opcode.LOAD_CONSTANT, const_index)
        elif target_type in VBCFloat.bit_width.keys():
            vbc_float = VBCFloat(node.value, target_type)
            const_index = self._add_constant(vbc_float)
            self._emit(Opcode.LOAD_CONSTANT, const_index)
        else:
            raise ValueError(f"不支持的目标数据类型: {target_type}")

    def visit_BoolNode(self, node: BoolNode):
        vbc_bool = VBCBool(node.value)
        const_index = self._add_constant(vbc_bool)
        self._emit(Opcode.LOAD_CONSTANT, const_index)
    
    def visit_StringNode(self, node: StringNode):
        # 去掉首尾的引号，得到原始内容
        raw_content = node.value[1:-1]
        vbc_str = VBCString(raw_content)
        const_index = self._add_constant(vbc_str)
        self._emit(Opcode.LOAD_CONSTANT, const_index)
    
    def visit_NullNode(self, node: NullNode): 
        const_index = self._add_constant(VBCNull())
        self._emit(Opcode.LOAD_CONSTANT, const_index)

    def visit_ConstantValueNode(self, node: ConstantValueNode):
        const_index = self._add_constant(node.value)
        self._emit(Opcode.LOAD_CONSTANT, const_index)

    def visit_TypeNode(self, node: TypeNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_RootNode(self, node: RootNode):
        # TODO 暂时遍历执行所有模块，后续进一步完善
        for module in node.modules:
            self.visit(module)
            
        # 执行完停机
        self._emit(Opcode.HALT)

    def visit_ModuleNode(self, node: ModuleNode):
        
        # TODO 暂时遍历执行所有语句，后续进一步完善
        for statement in node.body:
            self.visit(statement)

        main_symbol = self.symbol_table.lookup_value("main")
        main_type = main_symbol.type_ if main_symbol else None
        has_explicit_main_call = any(
            isinstance(statement, ExprStmtNode)
            and isinstance(statement.expr, CallNode)
            and isinstance(statement.expr.name, NameNode)
            and statement.expr.name.name == "main"
            and not statement.expr.args
            and not statement.expr.kwargs
            for statement in node.body
        )
        if (
            main_symbol is not None
            and main_symbol.kind == SymbolKind.FUNCTION
            and main_symbol.is_defined
            and isinstance(main_type, FunctionType)
            and not main_type.param_types
            and isinstance(main_type.return_type, (IntegerType, VoidType))
            and not has_explicit_main_call
        ):
            self._emit(Opcode.LOAD_GLOBAL_VAR, "main")
            self._emit(Opcode.CALL_FUNCTION, 0)
            self._emit(Opcode.SET_EXIT_CODE)
        
        # 解析标签
        for i, instruction in enumerate(self.bytecode):
            if len(instruction) == 2:
                opcode, operand = instruction
                if isinstance(operand, str) and operand in self.labels:
                    self.bytecode[i] = (opcode, self.labels[operand])
        
    def visit_LabelNode(self, node: LabelNode):
        lebel = self._generate_label(node.name.name)
        self._mark_label(lebel)
        
    # 表达式
    def visit_UnaryOpNode(self, node: UnaryOpNode):
        if node.op == Operator.ADDRESS_OF:
            self._emit_lvalue_address(node.expr)
            return
        
        self._emit_expr_with_array_decay(node.expr)
        if node.op == Operator.DEREFERENCE:
            self._emit(Opcode.LOAD_BY_POINTER)
        elif node.op == Operator.SUBTRACT:
            self._emit(Opcode.UNARY_MINUS)
        elif node.op == Operator.ADD:
            # TODO 检查这条分支是否有必要？ (+a 就是 a)
            pass
        elif node.op == Operator.NOT:
            self._emit(Opcode.LOGICAL_NOT)  
        else:
            raise ValueError(f"未知的单目运算符: {node.op}")

    def visit_BinaryOpNode(self, node: BinaryOpNode):
        
        # 优先判断短路操作
        if node.op == Operator.LOGICAL_AND:
            self.visit(node.left)
            
            end_label = self._generate_label("binary_end")
            self._emit(Opcode.DUP)
            self._emit(Opcode.JUMP_IF_FALSE, end_label)
            
            self._emit(Opcode.POP)
            self.visit(node.right)
            
            self._mark_label(end_label)
            
        elif node.op == Operator.LOGICAL_OR:
            self.visit(node.left)
            
            next_instr_label = self._generate_label("logical_or_next")
            end_label = self._generate_label("logical_or_end")
            
            self._emit(Opcode.DUP)
            # 如果左操作数为假，则跳转到下一指令，计算右操作数
            self._emit(Opcode.JUMP_IF_FALSE, next_instr_label)
            
            # 如果左操作数为真，则直接跳转到结尾，结果就是左操作数
            self._emit(Opcode.JUMP, end_label)
            
            self._mark_label(next_instr_label)
            # 弹出为假的左操作数，并计算右操作数
            self._emit(Opcode.POP)
            self.visit(node.right)
            
            self._mark_label(end_label)
        else:
            self._emit_expr_with_array_decay(node.left)
            self._emit_expr_with_array_decay(node.right)

            pointer_arithmetic = getattr(node, "_pointer_arithmetic", None)
            if pointer_arithmetic == "add":
                self._emit(Opcode.POINTER_ADD)
                return
            if pointer_arithmetic == "add_reversed":
                self._emit(Opcode.SWAP)
                self._emit(Opcode.POINTER_ADD)
                return
            if pointer_arithmetic == "sub":
                self._emit(Opcode.POINTER_SUB)
                return
            if pointer_arithmetic == "diff":
                self._emit(Opcode.POINTER_DIFF)
                return

            match node.op:
                case Operator.ADD:
                    self._emit(Opcode.ADD)
                case Operator.SUBTRACT:
                    self._emit(Opcode.SUBTRACT)
                case Operator.MULTIPLY:
                    self._emit(Opcode.MULTIPLY)
                case Operator.DIVIDE:
                    self._emit(Opcode.DIVIDE)
                case Operator.EQUAL:
                    self._emit(Opcode.EQUAL)
                case Operator.NOT_EQUAL:
                    self._emit(Opcode.NOT_EQUAL)
                case Operator.LESS_THAN:
                    self._emit(Opcode.LESS_THAN)
                case Operator.GREATER_THAN:
                    self._emit(Opcode.GREATER_THAN)
                case Operator.LESS_EQUAL:
                    self._emit(Opcode.LESS_EQUAL)
                case Operator.GREATER_EQUAL:
                    self._emit(Opcode.GREATER_EQUAL)
                case Operator.MODULO:
                    self._emit(Opcode.MODULO)
                case _:
                    raise ValueError(f"未知的二元运算符: {node.op}")


    def visit_RangeNode(self, node: RangeNode):
        # TODO 增加Range类型
        # 高级功能，后续添加，现在不做实现
        raise NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_BlockNode(self, node: BlockNode):
        original_symbol_table = self.symbol_table
        explicit_symbol_table = getattr(node, "_optimized_symbol_table", None)
        if explicit_symbol_table is not None:
            parent_table = getattr(node, "_optimized_parent_symbol_table", None)
            parent_scope_index_after = getattr(node, "_optimized_parent_scope_index_after", None)
            if parent_table is original_symbol_table and parent_scope_index_after is not None:
                current_index = self._nested_scope_indices.get(original_symbol_table, 0)
                self._nested_scope_indices[original_symbol_table] = max(current_index, parent_scope_index_after)

            emit_runtime_scope = getattr(node, "_optimized_emit_runtime_scope", False)
            self.symbol_table = explicit_symbol_table
            if emit_runtime_scope:
                self._emit(Opcode.ENTER_SCOPE)
            for statement in node.statements:
                self.visit(statement)
            if emit_runtime_scope:
                self._emit(Opcode.EXIT_SCOPE)
            self.symbol_table = original_symbol_table
            return

        current_index = self._nested_scope_indices.get(original_symbol_table, 0)

        if current_index >= original_symbol_table.get_nested_scope_length():
            raise RuntimeError(f"内部错误: OpcodeGenerator在BlockNode中找不到对应的嵌套作用域。父作用域: {original_symbol_table._scope_type}, 当前索引: {current_index}, 可用作用域数量: {len(original_symbol_table._nested_scopes)}")

        block_symbol_table = original_symbol_table.get_nested_scope(current_index)
        self.symbol_table = block_symbol_table

        self._nested_scope_indices[original_symbol_table] = current_index + 1

        for statement in node.statements:
            self.visit(statement)

        self.symbol_table = original_symbol_table

    def visit_TypedefNode(self, node: TypedefNode):
        """typedef 纯编译期类型别名，不产生任何指令。"""
        pass

    def visit_EnumNode(self, node: EnumNode):
        """enum 成员已在类型检查阶段确定常量值，不产生任何指令。"""
        pass

    def visit_StructNode(self, node: StructNode):
        """struct 定义不产生指令，其 VBCStructLayout 由使用处（ALLOC_STRUCT）按需注册进常量池。"""
        pass

    def visit_VarDeclNode(self, node: VarDeclNode):
        """生成变量声明字节码，并在初始化边界执行隐式转换。"""
        symbol = self.symbol_table.lookup_value(node.name.name)
        if symbol is None:
            raise RuntimeError(f"内部错误: 无法找到已由类型检查器验证的符号 '{node.name.name}'")

        if isinstance(symbol.type_, StructType):
            layout_index = self._get_or_add_struct_constant(symbol.type_)
            self._emit(Opcode.ALLOC_STRUCT, layout_index)
            if symbol.address is not None:
                self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
            else:
                self._emit(Opcode.STORE_GLOBAL_VAR, symbol.name)
            if node.init_exp is not None:
                self.visit(node.init_exp)
                self._emit(Opcode.COPY_STRUCT, symbol.type_.slot_count)
                if symbol.address is not None:
                    self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
                else:
                    self._emit(Opcode.STORE_GLOBAL_VAR, symbol.name)
            return

        if isinstance(symbol.type_, ArrayType):
            elem_enum = self._element_type_enum_from_type(symbol.type_.element_type)
            if elem_enum is None:
                raise RuntimeError(f"内部错误: 不支持的数组元素类型 '{symbol.type_.element_type}'")
            self._emit(Opcode.ALLOC_ARRAY, (symbol.type_.size, elem_enum))
            if symbol.address is not None:
                self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
            else:
                self._emit(Opcode.STORE_GLOBAL_VAR, symbol.name)
            if isinstance(node.init_exp, InitListNode):
                for i, elem in enumerate(node.init_exp.elements):
                    if isinstance(symbol.type_.element_type, (IntegerType, FloatType)):
                        setattr(elem, "inferred_type", symbol.type_.element_type.kind)
                    self.visit(elem)
                    self._emit_implicit_cast_if_needed(elem)
                    self._emit_load_array_base(symbol)
                    idx_const = self._add_constant(VBCInteger(i, VBCObjectType.INT))
                    self._emit(Opcode.LOAD_CONSTANT, idx_const)
                    self._emit(Opcode.STORE_INDEX, (symbol.type_.size, elem_enum))
            return

        if node.init_exp:
            # 仍然需要向初始化表达式传递类型信息，以处理数字字面量
            if isinstance(symbol.type_, (IntegerType, FloatType)):
                setattr(node.init_exp, "inferred_type", symbol.type_.kind)
            self.visit(node.init_exp)
            self._emit_implicit_cast_if_needed(node.init_exp)
            self._emit_array_decay_if_needed(node.init_exp)
        else:
            # 没有初始化，将默认值null压入栈
            const_index = self._add_constant(VBCNull())
            self._emit(Opcode.LOAD_CONSTANT, const_index)

        # 根据符号是否有地址来决定是存为局部变量还是全局变量
        if symbol.address is not None:
            self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
        else:
            self._emit(Opcode.STORE_GLOBAL_VAR, symbol.name)

    def visit_SubscriptNode(self, node: SubscriptNode):
        self._emit_load_lvalue(node)

    def visit_AssignmentNode(self, node: AssignmentNode):
        """生成赋值字节码，并在赋值边界执行隐式转换。"""
        if isinstance(node.target, UnaryOpNode) and node.target.op == Operator.DEREFERENCE:
            self.visit(node.value)
            self._emit_implicit_cast_if_needed(node.value)
            self._emit_array_decay_if_needed(node.value)
            self.visit(node.target.expr)
            self._emit(Opcode.STORE_BY_POINTER)
            return

        if isinstance(node.target, SubscriptNode):
            self.visit(node.value)
            self._emit_implicit_cast_if_needed(node.value)
            self._emit_store_lvalue_keep(node.target)
            return

        if isinstance(node.target, (NameNode, GetPropertyNode)):
            self.visit(node.value)
            self._emit_implicit_cast_if_needed(node.value)
            self._emit_array_decay_if_needed(node.value)
            if isinstance(node.target, NameNode):
                target_symbol = self.symbol_table.lookup_value(node.target.name)
                if target_symbol is not None and isinstance(target_symbol.type_, StructType):
                    self._emit(Opcode.COPY_STRUCT, target_symbol.type_.slot_count)
            self._emit_store_lvalue_keep(node.target)
            return

        raise RuntimeError(f"不支持的赋值目标类型: {type(node.target).__name__}")

    def visit_CompoundAssignmentNode(self, node: CompoundAssignmentNode):
        op_to_opcode = {
            Operator.PLUS_ASSIGN: Opcode.ADD,
            Operator.MINUS_ASSIGN: Opcode.SUBTRACT,
            Operator.STAR_ASSIGN: Opcode.MULTIPLY,
            Operator.SLASH_ASSIGN: Opcode.DIVIDE,
            Operator.PERCENT_ASSIGN: Opcode.MODULO,
        }
        if node.op not in op_to_opcode:
            raise RuntimeError(f"不支持的复合赋值运算符: {node.op}")

        self._emit_load_lvalue(node.left)
        self.visit(node.right)
        self._emit_implicit_cast_if_needed(node.right)
        pointer_arithmetic = getattr(node, "_pointer_arithmetic", None)
        if pointer_arithmetic == "add":
            self._emit(Opcode.POINTER_ADD)
        elif pointer_arithmetic == "sub":
            self._emit(Opcode.POINTER_SUB)
        else:
            self._emit(op_to_opcode[node.op])
        self._emit_implicit_cast_if_needed(node)
        self._emit_store_lvalue_keep(node.left)

    def visit_UpdateExprNode(self, node: UpdateExprNode):
        base = node.base
        step_index = self._add_constant(VBCInteger(1, VBCObjectType.INT))
        base_type = getattr(base, "_subscript_base_type", None)
        if isinstance(base, NameNode):
            symbol = self.symbol_table.lookup_value(base.name)
            base_type = symbol.type_ if symbol is not None else None
        arith_op = Opcode.POINTER_ADD if isinstance(base_type, PointerType) and node.op == Operator.INCREMENT else (
            Opcode.POINTER_SUB if isinstance(base_type, PointerType) else (
                Opcode.ADD if node.op == Operator.INCREMENT else Opcode.SUBTRACT
            )
        )

        if node.is_prefix:
            self._emit_load_lvalue(base)
            self._emit(Opcode.LOAD_CONSTANT, step_index)
            self._emit(arith_op)
            self._emit_store_lvalue_keep(base)
            return

        self._emit_load_lvalue(base)
        self._emit(Opcode.DUP)
        self._emit(Opcode.LOAD_CONSTANT, step_index)
        self._emit(arith_op)
        self._emit_store_lvalue(base)

    def visit_ExprStmtNode(self, node: ExprStmtNode):
        self.visit(node.expr)
        
        # TODO 完善逻辑，部分数据可能(?)不需要将数据弹出栈顶
        self._emit(Opcode.POP)

    def visit_IfNode(self, node: IfNode):
        self.visit(node.condition)
        
        endif_label = self._generate_label("if_end")
        if node.else_branch:
            else_label = self._generate_label("else_branch")
            
            # 条件为假时跳转到else分支
            self._emit(Opcode.JUMP_IF_FALSE, else_label)
            
            # 条件为真时执行then分支
            self._emit(Opcode.ENTER_SCOPE)
            self.visit(node.then_branch)
            self._emit(Opcode.EXIT_SCOPE)
            self._emit(Opcode.JUMP, endif_label)

            self._mark_label(else_label)
            self._emit(Opcode.ENTER_SCOPE)
            self.visit(node.else_branch)
            self._emit(Opcode.EXIT_SCOPE)
            
        else:
            # 条件为假时跳转到语句结束
            self._emit(Opcode.JUMP_IF_FALSE, endif_label)
            
            self._emit(Opcode.ENTER_SCOPE)
            self.visit(node.then_branch)
            self._emit(Opcode.EXIT_SCOPE)
            
        # 标记语句结束位置
        self._mark_label(endif_label)

    def _eval_case_constant_value(self, expr: ASTNode) -> int:
        """从已类型检查的 case 标签提取整型常量值，支持整数字面量与 enum 成员等编译期常量标识符"""
        if isinstance(expr, NumberNode) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
            return expr.value
        if isinstance(expr, NameNode):
            symbol = self.symbol_table.lookup_value(expr.name)
            if symbol is not None and symbol.const_value is not None:
                return symbol.const_value
        if isinstance(expr, ConstantValueNode) and isinstance(expr.value, VBCInteger):
            return expr.value.value
        raise RuntimeError(f"内部错误: 无效的 case 常量节点 {expr!r}")

    def visit_SwitchNode(self, node: SwitchNode):
        switch_end_label = self._generate_label("switch_end")
        label_map: dict[int, str] = {}
        cases: list[tuple[int, str]] = []
        default_label: str | None = None

        for item in node.body.statements:
            if isinstance(item, SwitchLabelNode):
                label_name = "default" if item.value is None else "case"
                label = self._generate_label(label_name)
                label_map[id(item)] = label
                if item.value is None:
                    default_label = label
                else:
                    cases.append((self._eval_case_constant_value(item.value), label))

        self.visit(node.condition)

        original_symbol_table = self.symbol_table
        current_index = self._nested_scope_indices.get(original_symbol_table, 0)
        if current_index >= original_symbol_table.get_nested_scope_length():
            raise RuntimeError("内部错误: OpcodeGenerator 在 SwitchNode 中找不到对应的嵌套作用域。")
        block_table = original_symbol_table.get_nested_scope(current_index)
        self.symbol_table = block_table
        self._nested_scope_indices[original_symbol_table] = current_index + 1

        self._emit(Opcode.ENTER_SCOPE)
        self.switch_stack.append(switch_end_label)

        temp_symbol = self.symbol_table.add_symbol(
            f"__switch_disc_{self.next_label_id}",
            IntegerType(VBCObjectType.INT),
        )
        self._emit(Opcode.DUP)
        self._emit(Opcode.STORE_LOCAL_VAR, temp_symbol.address)
        self._emit(Opcode.POP)

        for value, case_label in cases:
            next_cmp_label = self._generate_label("switch_cmp_next")
            self._emit(Opcode.LOAD_LOCAL_VAR, temp_symbol.address)
            const_index = self._add_constant(VBCInteger(value, VBCObjectType.INT))
            self._emit(Opcode.LOAD_CONSTANT, const_index)
            self._emit(Opcode.EQUAL)
            self._emit(Opcode.JUMP_IF_FALSE, next_cmp_label)
            self._emit(Opcode.JUMP, case_label)
            self._mark_label(next_cmp_label)

        if default_label is not None:
            self._emit(Opcode.JUMP, default_label)
        else:
            self._emit(Opcode.JUMP, switch_end_label)

        for item in node.body.statements:
            if isinstance(item, SwitchLabelNode):
                self._mark_label(label_map[id(item)])
            else:
                self.visit(item)

        self._mark_label(switch_end_label)
        self.switch_stack.pop()
        self._emit(Opcode.EXIT_SCOPE)
        self.symbol_table = original_symbol_table

    def visit_SwitchLabelNode(self, node: SwitchLabelNode):
        pass

    def visit_WhileNode(self, node: WhileNode):
        loop_start_label = self._generate_label("while_start")
        loop_end_label = self._generate_label("while_end")
        
        # 创建循环上下文并推入栈
        loop_context = LoopContext(
            loop_type=LoopType.WHILE,
            continue_label=loop_start_label,  # continue跳转到循环开始（条件检查）
            break_label=loop_end_label        # break跳转到循环结束
        )
        self.loop_stack.append(loop_context)

        self._mark_label(loop_start_label)
        self.visit(node.condition)
        
        # 条件不满足则跳出循环
        self._emit(Opcode.JUMP_IF_FALSE, loop_end_label)

        self.visit(node.body)
        
        self._emit(Opcode.JUMP, loop_start_label)
        self._mark_label(loop_end_label)
        
        # 退出循环时弹出标签栈
        self.loop_stack.pop()

    def visit_DoWhileNode(self, node: DoWhileNode):
        loop_start_label = self._generate_label("do_while_start")
        loop_end_label = self._generate_label("do_while_end")
        continue_label = self._generate_label("do_while_continue")

        loop_context = LoopContext(
            loop_type=LoopType.DO_WHILE,
            continue_label=continue_label,
            break_label=loop_end_label
        )
        self.loop_stack.append(loop_context)

        self._mark_label(loop_start_label)
        self.visit(node.body)
        self._mark_label(continue_label)
        self.visit(node.condition)
        self._emit(Opcode.JUMP_IF_FALSE, loop_end_label)
        self._emit(Opcode.JUMP, loop_start_label)
        self._mark_label(loop_end_label)
        
        self.loop_stack.pop()

    def visit_ForNode(self, node: ForNode):
        # --- 作用域切换逻辑 ---
        original_symbol_table = self.symbol_table
        
        # 获取 for 循环对应的作用域
        current_index = self._nested_scope_indices.get(original_symbol_table, 0)
        if current_index >= len(original_symbol_table._nested_scopes):
            raise RuntimeError(f"内部错误: OpcodeGenerator在ForNode中找不到对应的嵌套作用域。")
        
        for_table = original_symbol_table._nested_scopes[current_index]
        self.symbol_table = for_table
        self._nested_scope_indices[original_symbol_table] = current_index + 1
        # --- 作用域切换逻辑结束 ---

        loop_condition_label = self._generate_label("for_condition")
        loop_update_label = self._generate_label("for_update")
        loop_end_label = self._generate_label("for_end")
        
        # 创建循环上下文并推入栈
        loop_context = LoopContext(
            loop_type=LoopType.FOR,
            continue_label=loop_update_label,  # continue跳转到更新部分
            break_label=loop_end_label         # break跳转到循环结束
        )
        self.loop_stack.append(loop_context)
        
        # 执行初始化表达式
        if node.init:
            self.visit(node.init)
            # 如果初始化是表达式语句，需要弹出结果（避免栈积累）
            if not isinstance(node.init, VarDeclNode):
                self._emit(Opcode.POP)
        
        # 条件检查标签
        self._mark_label(loop_condition_label)
        
        # 检查循环条件
        if node.condition:
            self.visit(node.condition)
            self._emit(Opcode.JUMP_IF_FALSE, loop_end_label)
        
        self.visit(node.body)
    
        self._mark_label(loop_update_label)
        
        # 更新表达式
        if node.update:
            self.visit(node.update)
            # 如果更新是表达式，需要弹出结果（避免栈积累）
            if not isinstance(node.update, VarDeclNode):
                self._emit(Opcode.POP)
        
        # 跳转回条件检查
        self._emit(Opcode.JUMP, loop_condition_label)
        
        # 循环结束标签
        self._mark_label(loop_end_label)
        
        # 退出循环时弹出标签栈
        self.loop_stack.pop()

        # --- 恢复作用域 ---
        self.symbol_table = original_symbol_table

    def visit_ReturnNode(self, node: ReturnNode):
        """生成 return 字节码，并在返回边界执行隐式转换。"""
        if node.value:
            self.visit(node.value)  # 计算返回值并将其放在栈顶
            self._emit_implicit_cast_if_needed(node.value)
        else:
            # 如果没有显示的返回值，则返回null
            const_index = self._add_constant(VBCNull())
            self._emit(Opcode.LOAD_CONSTANT, const_index)
        
        self._emit(Opcode.RETURN)    # 发出返回指令

    def visit_ContinueNode(self, node: ContinueNode):
        if not self.loop_stack:
            raise Exception(f"continue语句只能在循环内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到continue标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_continue_target()
        self._emit(Opcode.JUMP, target_label)

    def visit_BreakNode(self, node: BreakNode):
        if self.switch_stack:
            self._emit(Opcode.JUMP, self.switch_stack[-1])
            return
        if not self.loop_stack:
            raise Exception(f"break语句只能在循环或switch内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到break标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_break_target()
        self._emit(Opcode.JUMP, target_label)

    def visit_ParamNode(self, node: ParamNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_FunctionDeclNode(self, node: FunctionDeclNode):
        pass

    def visit_FunctionNode(self, node: FunctionNode):
        from verbose_c.compiler.compiler import Compiler
        from verbose_c.compiler.enum import CompilerPass
        
        func_symbol = self.symbol_table.lookup_value(node.name.name)
        if func_symbol is None:
            raise RuntimeError(f"内部错误: 未找到函数 '{node.name.name}' 的符号")
        if not func_symbol.is_defined:
            raise RuntimeError(f"内部错误: 函数 '{node.name.name}' 仅有声明，不应进入代码生成")
        if not isinstance(func_symbol.type_, FunctionType):
            raise RuntimeError(f"内部错误: 期望找到函数类型，但找到了 {func_symbol.type_}")
        
        function_symbol_table = func_symbol.scope
        if function_symbol_table is None:
            raise RuntimeError(f"内部错误: 未找到 '{node.name.name}' 的符号表")
            
        function_compiler = Compiler(
            target_ast=node.body,
            optimize_level=self.optimize_level,
            symbol_table=function_symbol_table,
            scope_type=ScopeType.FUNCTION,
            source_path=self.source_path,
            passes_to_run=[CompilerPass.GENERATE_CODE],
            function_name=node.name.name,
        )
        
        function_compiler.compile()
        function_op_generator = function_compiler.opcode_generator

        # 检查一下编译后的操作码，如果最后没有显式的return，则添加一个return null;
        if not function_op_generator.bytecode or function_op_generator.bytecode[-1][0] != Opcode.RETURN:
            const_index = function_op_generator._add_constant(VBCNull())
            function_op_generator._emit(Opcode.LOAD_CONSTANT, const_index)
            function_op_generator._emit(Opcode.RETURN)

        # 将跳转标签解析为地址
        for i, instruction in enumerate(function_op_generator.bytecode):
            if len(instruction) == 2:
                opcode, operand = instruction
                if isinstance(operand, str) and operand in function_op_generator.labels:
                    function_op_generator.bytecode[i] = (opcode, function_op_generator.labels[operand])
        
        # 收集函数编译结果
        self.function_compilation_results[node.name.name] = {
            'bytecode': function_op_generator.bytecode,
            'constants': function_op_generator.constant_pool,
            'labels': function_op_generator.labels,
            'optimization_result': function_op_generator.optimization_result,
            'ast_optimization_result': function_compiler.ast_optimization_result,
        }

        function_bytecode = function_op_generator.bytecode
        function_constants = function_op_generator.constant_pool
        
        param_count = len(node.args)
        local_count = function_symbol_table._next_local_address

        vbc_function = VBCFunction(
            name=node.name.name,
            bytecode=function_bytecode,
            constants=function_constants,
            param_count=param_count,
            local_count=local_count,
            source_path=self.source_path,
            lineno_table=function_op_generator.lineno_table
        )
        
        const_index = self._add_constant(vbc_function)
        self._emit(Opcode.LOAD_CONSTANT, const_index)
        self._emit(Opcode.STORE_GLOBAL_VAR, node.name.name)

    def visit_CallNode(self, node: CallNode):
        """生成函数调用字节码，并在实参边界执行隐式转换。"""
        if node.kwargs:
            # TODO 实现关键词参数
            # 高级功能，后续添加，现在不做实现
            raise NotImplementedError(f"关键字参数在函数调用中暂未实现, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 先加载函数对象，再加载参数
        self.visit(node.name)
        
        for arg_expr in node.args:
            self.visit(arg_expr)
            self._emit_implicit_cast_if_needed(arg_expr)
            self._emit_array_decay_if_needed(arg_expr)
        
        num_args = len(node.args)
        self._emit(Opcode.CALL_FUNCTION, num_args)

    def visit_ClassNode(self, node: ClassNode):
        from verbose_c.compiler.compiler import Compiler
        from verbose_c.compiler.enum import CompilerPass
        class_name = node.name.name
        
        original_table = self.symbol_table
        class_symbol = self.symbol_table.lookup_value(class_name)
        if not (class_symbol and class_symbol.scope):
            raise RuntimeError(f"内部错误: TypeChecker未能正确创建或链接类 '{class_name}' 的作用域")
        
        class_type_info = class_symbol.type_
        super_class_objects = []
        if isinstance(class_type_info, ClassType):
            for super_type in class_type_info.super_class:
                super_symbol = self.symbol_table.lookup_value(super_type.name)
                if super_symbol and isinstance(super_symbol.type_, ClassType):
                    pass
        
        self.symbol_table = class_symbol.scope

        class_name = node.name.name
        class_symbol = self.symbol_table.lookup_value(class_name)
        class_type_info = class_symbol.type_
        
        super_class_objects = []
        if isinstance(class_type_info, ClassType):
            for super_type in class_type_info.super_class:
                # 遍历常量池，找到匹配的 VBCClass 对象
                found_super = None
                for const in self.constant_pool:
                    if isinstance(const, VBCClass) and const._name == super_type.name:
                        found_super = const
                        break
                if found_super:
                    super_class_objects.append(found_super)
                else:
                    raise RuntimeError(f"编译错误: 未找到父类 '{super_type.name}' 的定义。请确保父类在子类之前定义。")

        vbc_class = VBCClass(name=class_name, super_class=super_class_objects)
        
        user_init_node: FunctionNode | None = None
        for statement in node.body.statements:
            if isinstance(statement, FunctionNode) and statement.name.name == "__init__":
                user_init_node = statement
                break

        field_init_statements = []
        
        for statement in node.body.statements:
            if isinstance(statement, FunctionNode):
                method_name = statement.name.name
                
                if method_name == "__init__":
                    continue
                
                original_method_table = self.symbol_table
                method_symbol = self.symbol_table.lookup_value(method_name)
                if not (method_symbol and method_symbol.scope):
                    raise RuntimeError(f"内部错误: TypeChecker未能正确创建或链接方法 '{method_name}' 的作用域")
                
                method_symbol_table = method_symbol.scope

                # 从符号中获取类型信息
                class_type = original_method_table.lookup_value(class_name).type_
                method_type = method_symbol.type_
                if not isinstance(method_type, FunctionType):
                    raise RuntimeError(f"内部错误: 无法找到方法 '{method_name}' 的类型")

                # 编译方法
                # 传递已经由TypeChecker填充好的符号表
                method_compiler = Compiler(
                    target_ast=statement.body,
                    optimize_level=self.optimize_level,
                    symbol_table=method_symbol_table,
                    scope_type=ScopeType.FUNCTION,
                    source_path=self.source_path,
                    passes_to_run=[CompilerPass.GENERATE_CODE],
                    function_name=method_name,
                )
                
                method_compiler.compile()
                method_op_generator = method_compiler.opcode_generator

                # 检查一下编译后的操作码，如果最后没有显式的return，则添加一个return null;
                if not method_op_generator.bytecode or method_op_generator.bytecode[-1][0] != Opcode.RETURN:
                    const_index = method_op_generator._add_constant(VBCNull())
                    method_op_generator._emit(Opcode.LOAD_CONSTANT, const_index)
                    method_op_generator._emit(Opcode.RETURN)

                # 将跳转标签解析为地址
                for i, instruction in enumerate(method_op_generator.bytecode):
                    if len(instruction) == 2:
                        opcode, operand = instruction
                        if isinstance(operand, str) and operand in method_op_generator.labels:
                            method_op_generator.bytecode[i] = (opcode, method_op_generator.labels[operand])
                
                # 收集函数编译结果
                self.function_compilation_results[f"{class_name}.{method_name}"] = {
                    'bytecode': method_op_generator.bytecode,
                    'constants': method_op_generator.constant_pool,
                    'labels': method_op_generator.labels,
                    'optimization_result': method_op_generator.optimization_result,
                    'ast_optimization_result': method_compiler.ast_optimization_result,
                }

                function_bytecode = method_op_generator.bytecode
                function_constants = method_op_generator.constant_pool
                
                param_count = len(statement.args)
                local_count = method_compiler.opcode_generator.symbol_table._next_local_address

                vbc_method = VBCFunction(
                    name=method_name,
                    bytecode=function_bytecode,
                    constants=function_constants,
                    param_count=param_count,
                    local_count=local_count,
                    source_path=self.source_path,
                    lineno_table=method_op_generator.lineno_table
                )
                
                vbc_class._methods[method_name] = vbc_method
                # 恢复到类作用域
                self.symbol_table = original_method_table
                
            elif isinstance(statement, VarDeclNode):
                # 重构：字段信息已在TypeChecker中处理，这里只处理带初始化的字段
                field_name = statement.name.name
                vbc_class._fields[field_name] = VBCNull()
                if statement.init_exp:
                    line = statement.start_line
                    column = statement.start_column
                    this_node = NameNode("this", start_line=line, start_column=column)
                    assignment_node = AssignmentNode(
                        target=GetPropertyNode(
                            obj=this_node,
                            property_name=statement.name,
                            start_line=line,
                            start_column=column,
                        ),
                        value=statement.init_exp,
                        start_line=line,
                        start_column=column,
                    )
                    field_init_statements.append(assignment_node)

        final_init_body_statements = []
        final_init_args = []
        
        if user_init_node:
            final_init_args = user_init_node.args
            final_init_body_statements = field_init_statements + user_init_node.body.statements
        else:
            final_init_args = []
            final_init_body_statements = field_init_statements

        final_init_method_node = FunctionNode(
            return_type=TypeNode(NameNode("void", start_line=node.start_line, start_column=node.start_column)),
            name=NameNode("__init__", start_line=node.start_line, start_column=node.start_column),
            args=final_init_args,
            kwargs={},
            body=BlockNode(
                final_init_body_statements,
                start_line=node.start_line,
                start_column=node.start_column,
            ),
            start_line=node.start_line,
            start_column=node.start_column,
        )

        original_init_table = self.symbol_table
        init_symbol = self.symbol_table.lookup_value("__init__")
        
        # 如果用户定义了__init__，则其符号有关联的作用域，否则为默认构造函数创建一个临时的空作用域
        if not (init_symbol and init_symbol.scope):
            raise RuntimeError(f"内部错误: TypeChecker未能正确创建或链接构造函数 '__init__' 的作用域")
        
        init_symbol_table = init_symbol.scope

        # 在父作用域（original_init_table）中查找类符号
        class_symbol = original_init_table.lookup_value(class_name)
        if not class_symbol or not isinstance(class_symbol.type_, ClassType):
            raise RuntimeError(f"内部错误: 无法在类作用域的父作用域中找到类本身的类型符号")
        class_type = class_symbol.type_
        init_method_type = class_type.methods.get("__init__")
        if not isinstance(init_method_type, FunctionType):
            raise RuntimeError(f"内部错误: 无法找到构造函数 '__init__' 的类型")

        # TypeChecker已经填充了'this'和参数，这里直接编译
        init_compiler = Compiler(
            target_ast=final_init_method_node.body,
            optimize_level=self.optimize_level,
            symbol_table=init_symbol_table,
            scope_type=ScopeType.FUNCTION,
            source_path=self.source_path,
            passes_to_run=[CompilerPass.GENERATE_CODE],
            function_name="__init__",
        )
        init_compiler.compile()
        init_op_generator = init_compiler.opcode_generator

        if not init_op_generator.bytecode or init_op_generator.bytecode[-1][0] != Opcode.RETURN:
            const_index = init_op_generator._add_constant(VBCNull())
            init_op_generator._emit(Opcode.LOAD_CONSTANT, const_index)
            init_op_generator._emit(Opcode.RETURN)

        for i, instruction in enumerate(init_op_generator.bytecode):
            if len(instruction) == 2:
                opcode, operand = instruction
                if isinstance(operand, str) and operand in init_op_generator.labels:
                    init_op_generator.bytecode[i] = (opcode, init_op_generator.labels[operand])

        init_local_count = init_compiler.opcode_generator.symbol_table._next_local_address
        if init_local_count == 0:
            init_local_count = 1

        self.function_compilation_results[f"{class_name}.__init__"] = {
            'bytecode': init_op_generator.bytecode,
            'constants': init_op_generator.constant_pool,
            'labels': init_op_generator.labels,
            'optimization_result': init_op_generator.optimization_result,
            'ast_optimization_result': init_compiler.ast_optimization_result,
        }

        vbc_init_method = VBCFunction(
            name="__init__",
            bytecode=init_op_generator.bytecode,
            constants=init_op_generator.constant_pool,
            param_count=len(final_init_args),
            local_count=init_local_count,
            source_path=self.source_path,
            lineno_table=init_op_generator.lineno_table
        )
        
        vbc_class._methods["__init__"] = vbc_init_method
        self.symbol_table = original_table
        
        # 将 VBCClass 对象存入常量池
        class_index = self._add_constant(vbc_class)
        self._emit(Opcode.LOAD_CONSTANT, class_index)
        
        # 将类本身存储在全局变量中
        self._emit(Opcode.STORE_GLOBAL_VAR, class_name)

    # def visit_AttributeNode(self, node: AttributeNode):
    #     raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_NewInstanceNode(self, node: NewInstanceNode):
        """生成实例化调用字节码，并在构造参数边界执行隐式转换。"""
        call_node = node.class_call
        
        if not isinstance(call_node, CallNode):
            raise TypeError(f"期望类调用, 得到 {type(call_node).__name__}")

        if call_node.kwargs:
            # 高级功能，后续添加，现在不做实现
            raise NotImplementedError(f"关键字参数在构造函数调用中暂未实现, 在行: {node.start_line}, 列: {node.start_column}")

        self.visit(call_node.name)
        
        for arg_expr in call_node.args:
            self.visit(arg_expr)
            self._emit_implicit_cast_if_needed(arg_expr)
        
        num_args = len(call_node.args)
        self._emit(Opcode.NEW_INSTANCE, num_args)

    def visit_GetPropertyNode(self, node: GetPropertyNode):
        # 单独处理super
        if isinstance(node.obj, SuperNode):
            self.visit(node.obj)
            
            property_name = self._add_constant(VBCString(node.property_name.name))
            self._emit(Opcode.LOAD_CONSTANT, property_name)
            
            self._emit(Opcode.SUPER_GET)
            return

        struct_type = getattr(node, "_struct_type", None)
        if struct_type is not None:
            slot_count, offset = self._struct_field_operand(node, struct_type)
            self._emit_struct_base(node.obj, node.via_pointer)
            self._emit(Opcode.LOAD_FIELD, (slot_count, offset))
            return

        self.visit(node.obj)
        
        property_name = self._add_constant(VBCString(node.property_name.name))
        self._emit(Opcode.LOAD_CONSTANT, property_name)
        
        self._emit(Opcode.GET_PROPERTY)

    def visit_SetPropertyNode(self, node: SetPropertyNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_CastNode(self, node: CastNode):
        """生成显式类型转换字节码（含指针目标类型）。"""
        self.visit(node.expression)
        
        if node.target_type.pointer_level > 0:
            target_enum = VBCObjectType.POINTER
        else:
            type_name = node.target_type.type_name.name
            # TODO 增加自定义数据类型和类的转换
            RUNTIME_TYPE_MAP = {
                "void": VBCObjectType.VOID,
                "char": VBCObjectType.CHAR,
                "int": VBCObjectType.INT,
                "long": VBCObjectType.LONG,
                "long long": VBCObjectType.LONGLONG,
                "unlimited int": VBCObjectType.NLINT,
                "float": VBCObjectType.FLOAT,
                "double": VBCObjectType.DOUBLE,
                "unlimited float": VBCObjectType.NLFLOAT,
                "string": VBCObjectType.STRING,
                "bool": VBCObjectType.BOOL,
            }
            target_enum = RUNTIME_TYPE_MAP.get(type_name, VBCObjectType.VOID)
        self._emit(Opcode.CAST, target_enum)

    def visit_ParenOrCastNode(self, node: ParenOrCastNode):
        if node.resolved_node is None:
            raise RuntimeError(f"内部错误: ParenOrCastNode 在代码生成前未完成语义消歧, 在 {node.start_line} 行")
        self.visit(node.resolved_node)

    def visit_SuperNode(self, node: SuperNode):
        this_symbol = self.symbol_table.lookup_value('this')
        if this_symbol is None or this_symbol.address != 0:
            raise RuntimeError("内部错误: 在处理 'super' 时无法找到 'this' 实例")
        self._emit(Opcode.LOAD_LOCAL_VAR, 0)

        class_scope = self.symbol_table
        while class_scope is not None and class_scope._scope_type != ScopeType.CLASS:
            class_scope = class_scope._parent
        
        if class_scope is None:
            raise RuntimeError("内部错误: 在处理 'super' 时无法找到类作用域")

        class_symbol_scope = class_scope._parent
        if class_symbol_scope is None:
            raise RuntimeError("内部错误: 类作用域没有父作用域")

        class_name = None
        for sym in class_symbol_scope._symbols.values():
            if sym.scope is class_scope:
                class_name = sym.name
                break
        
        if class_name is None:
            raise RuntimeError("内部错误: 无法反向解析当前类的名称")

        self._emit(Opcode.LOAD_GLOBAL_VAR, class_name)

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
    def __init__(self, symbol_table: SymbolTable, source_path: str | None = None):
        self.symbol_table: SymbolTable = symbol_table
        self.source_path = source_path
        self.bytecode: list[tuple] = []
        self.labels = {}
        self.constant_pool = []
        self.lineno_table: list[tuple[int, int]] = [] # (字节码偏移, 行号)
        self.current_line = -1
        self.next_label_id = 0
        self.loop_stack: list[LoopContext] = []  # 循环标签栈，后续支持嵌套循环和多层跳出
        self.function_compilation_results = {} # 存储函数编译结果
        self._nested_scope_indices: dict[SymbolTable, int] = {} # 跟踪每个父作用域下嵌套作用域的访问索引

    def visit(self, node: ASTNode):
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
        if not self.lineno_table or self.lineno_table[-1][1] != self.current_line:
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

    # 基本数据类型
    def visit_NameNode(self, node: NameNode): 
        symbol = self.symbol_table.lookup(node.name)
        if symbol is None:
            raise Exception(f"未定义的标识符: {node.name}, 在行: {node.start_line}, 列: {node.start_column}")

        if symbol.address is not None:
            self._emit(Opcode.LOAD_LOCAL_VAR, symbol.address)
        else:
            self._emit(Opcode.LOAD_GLOBAL_VAR, node.name)
    
    def visit_NumberNode(self, node: NumberNode):
        target_type = getattr(node, "inferred_type", None)
        if target_type is None:
            # TODO 自动类型推断可能需要进一步完善？
            if isinstance(node.value, int):
                target_type = VBCObjectType.INT
            elif isinstance(node.value, float):
                target_type = VBCObjectType.FLOAT
            else:
                raise TypeError(f"未知的 NumberNode 值类型: {type(node.value).__name__}")

        if not ((isinstance(node.value, int) and target_type in VBCInteger.bit_width.keys()) or \
            (isinstance(node.value, float) and target_type in VBCFloat.bit_width.keys())):
            raise TypeError(f"NumberNode 的值类型({type(node.value).__name__})与预期类型({target_type})不匹配, 在行: {node.start_line}, 列: {node.start_column}")

        # TODO 处理float和double类型
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
        self.visit(node.expr)
        
        if node.op == Operator.SUBTRACT:
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
            self.visit(node.left)
            self.visit(node.right)

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
                case _:
                    raise ValueError(f"未知的二元运算符: {node.op}")


    def visit_RangeNode(self, node: RangeNode):
        # TODO 增加Range类型
        # 高级功能，后续添加，现在不做实现
        raise NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_BlockNode(self, node: BlockNode):
        original_symbol_table = self.symbol_table

        current_index = self._nested_scope_indices.get(original_symbol_table, 0)

        if current_index >= original_symbol_table.get_nested_scope_length():
            raise RuntimeError(f"内部错误: OpcodeGenerator在BlockNode中找不到对应的嵌套作用域。父作用域: {original_symbol_table._scope_type}, 当前索引: {current_index}, 可用作用域数量: {len(original_symbol_table._nested_scopes)}")

        block_symbol_table = original_symbol_table.get_nested_scope(current_index)
        self.symbol_table = block_symbol_table

        self._nested_scope_indices[original_symbol_table] = current_index + 1

        for statement in node.statements:
            self.visit(statement)

        self.symbol_table = original_symbol_table

    def visit_VarDeclNode(self, node: VarDeclNode):
        symbol = self.symbol_table.lookup(node.name.name)
        if symbol is None:
            raise RuntimeError(f"内部错误: 无法找到已由类型检查器验证的符号 '{node.name.name}'")

        if node.init_exp:
            # 仍然需要向初始化表达式传递类型信息，以处理数字字面量
            if isinstance(symbol.type_, (IntegerType, FloatType)):
                 setattr(node.init_exp, 'inferred_type', symbol.type_.kind)
            self.visit(node.init_exp)
        else:
            # 没有初始化，将默认值null压入栈
            const_index = self._add_constant(VBCNull())
            self._emit(Opcode.LOAD_CONSTANT, const_index)

        # 根据符号是否有地址来决定是存为局部变量还是全局变量
        if symbol.address is not None:
            self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
        else:
            self._emit(Opcode.STORE_GLOBAL_VAR, symbol.name)

    def visit_AssignmentNode(self, node: AssignmentNode):
        if isinstance(node.target, NameNode):
            self.visit(node.value)

            symbol = self.symbol_table.lookup(node.target.name)
            if symbol is None:
                raise ValueError(f"未定义的变量: {node.target.name}")

            if symbol.address is not None:
                self._emit(Opcode.STORE_LOCAL_VAR, symbol.address)
            else:
                # TODO 这里的逻辑应该还需要进一步确认
                self._emit(Opcode.STORE_GLOBAL_VAR, node.target.name)
        
        elif isinstance(node.target, GetPropertyNode):
            # 处理对象属性赋值，比如 obj.prop = value 的语法
            self.visit(node.value)
            self.visit(node.target.obj)

            property_name = self._add_constant(VBCString(node.target.property_name.name))
            self._emit(Opcode.LOAD_CONSTANT, property_name)

            self._emit(Opcode.SET_PROPERTY)
        else:
            raise RuntimeError(f"不支持的赋值目标类型: {type(node.target).__name__}")

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
            if not isinstance(node.init, (VarDeclNode, AssignmentNode)):
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
            if not isinstance(node.update, AssignmentNode):
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
        if node.value:
            self.visit(node.value)  # 计算返回值并将其放在栈顶
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
        if not self.loop_stack:
            raise Exception(f"break语句只能在循环内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到break标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_break_target()
        self._emit(Opcode.JUMP, target_label)

    def visit_ParamNode(self, node: ParamNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_FunctionNode(self, node: FunctionNode):
        from verbose_c.compiler.compiler import Compiler
        from verbose_c.compiler.enum import CompilerPass
        
        func_symbol = self.symbol_table.lookup(node.name.name)
        if not isinstance(func_symbol.type_, FunctionType):
            raise RuntimeError(f"内部错误: 期望找到函数类型，但找到了 {func_symbol.type_}")
        
        function_symbol_table = func_symbol.scope
        if function_symbol_table is None:
            raise RuntimeError(f"内部错误: 未找到 '{node.name.name}' 的符号表")
            
        function_compiler = Compiler(
            target_ast=node.body,
            optimize_level=0,
            symbol_table=function_symbol_table,
            scope_type=ScopeType.FUNCTION,
            source_path=self.source_path,
            passes_to_run=[CompilerPass.GENERATE_CODE]
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
            'labels': function_op_generator.labels
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
        if node.kwargs:
            # TODO 实现关键词参数
            # 高级功能，后续添加，现在不做实现
            raise NotImplementedError(f"关键字参数在函数调用中暂未实现, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 先加载函数对象，再加载参数
        self.visit(node.name)
        
        for arg_expr in node.args:
            self.visit(arg_expr)
        
        num_args = len(node.args)
        self._emit(Opcode.CALL_FUNCTION, num_args)

    def visit_ClassNode(self, node: ClassNode):
        from verbose_c.compiler.compiler import Compiler
        from verbose_c.compiler.enum import CompilerPass
        class_name = node.name.name
        
        original_table = self.symbol_table
        class_symbol = self.symbol_table.lookup(class_name)
        if not (class_symbol and class_symbol.scope):
            raise RuntimeError(f"内部错误: TypeChecker未能正确创建或链接类 '{class_name}' 的作用域")
        
        class_type_info = class_symbol.type_
        super_class_objects = []
        if isinstance(class_type_info, ClassType):
            for super_type in class_type_info.super_class:
                super_symbol = self.symbol_table.lookup(super_type.name)
                if super_symbol and isinstance(super_symbol.type_, ClassType):
                    pass
        
        self.symbol_table = class_symbol.scope

        class_name = node.name.name
        class_symbol = self.symbol_table.lookup(class_name)
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
                method_symbol = self.symbol_table.lookup(method_name)
                if not (method_symbol and method_symbol.scope):
                    raise RuntimeError(f"内部错误: TypeChecker未能正确创建或链接方法 '{method_name}' 的作用域")
                
                method_symbol_table = method_symbol.scope

                # 从符号中获取类型信息
                class_type = original_method_table.lookup(class_name).type_
                method_type = method_symbol.type_
                if not isinstance(method_type, FunctionType):
                    raise RuntimeError(f"内部错误: 无法找到方法 '{method_name}' 的类型")

                # 编译方法
                # 传递已经由TypeChecker填充好的符号表
                method_compiler = Compiler(
                    target_ast=statement.body,
                    optimize_level=0,
                    symbol_table=method_symbol_table,
                    scope_type=ScopeType.FUNCTION,
                    source_path=self.source_path,
                    passes_to_run=[CompilerPass.GENERATE_CODE],
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
                    'labels': method_op_generator.labels
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
                    this_node = NameNode("this")
                    assignment_node = AssignmentNode(
                        target=GetPropertyNode(obj=this_node, property_name=statement.name),
                        value=statement.init_exp
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
            return_type=TypeNode(NameNode("void")),
            name=NameNode("__init__"),
            args=final_init_args,
            kwargs={},
            body=BlockNode(final_init_body_statements)
        )

        original_init_table = self.symbol_table
        init_symbol = self.symbol_table.lookup("__init__")
        
        # 如果用户定义了__init__，则其符号有关联的作用域，否则为默认构造函数创建一个临时的空作用域
        if not (init_symbol and init_symbol.scope):
            raise RuntimeError(f"内部错误: TypeChecker未能正确创建或链接构造函数 '__init__' 的作用域")
        
        init_symbol_table = init_symbol.scope

        # 在父作用域（original_init_table）中查找类符号
        class_symbol = original_init_table.lookup(class_name)
        if not class_symbol or not isinstance(class_symbol.type_, ClassType):
            raise RuntimeError(f"内部错误: 无法在类作用域的父作用域中找到类本身的类型符号")
        class_type = class_symbol.type_
        init_method_type = class_type.methods.get("__init__")
        if not isinstance(init_method_type, FunctionType):
            raise RuntimeError(f"内部错误: 无法找到构造函数 '__init__' 的类型")

        # TypeChecker已经填充了'this'和参数，这里直接编译
        init_compiler = Compiler(
            target_ast=final_init_method_node.body,
            optimize_level=0,
            symbol_table=init_symbol_table,
            scope_type=ScopeType.FUNCTION,
            source_path=self.source_path,
            passes_to_run=[CompilerPass.GENERATE_CODE],
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
        call_node = node.class_call
        
        if not isinstance(call_node, CallNode):
            raise TypeError(f"期望类调用, 得到 {type(call_node).__name__}")

        if call_node.kwargs:
            # 高级功能，后续添加，现在不做实现
            raise NotImplementedError(f"关键字参数在构造函数调用中暂未实现, 在行: {node.start_line}, 列: {node.start_column}")

        self.visit(call_node.name)
        
        for arg_expr in call_node.args:
            self.visit(arg_expr)
        
        num_args = len(call_node.args)
        self._emit(Opcode.NEW_INSTANCE, num_args)

    def visit_GetPropertyNode(self, node: GetPropertyNode):
        self.visit(node.obj)
        
        property_name = self._add_constant(VBCString(node.property_name.name))
        self._emit(Opcode.LOAD_CONSTANT, property_name)
        
        self._emit(Opcode.GET_PROPERTY)

    def visit_SetPropertyNode(self, node: SetPropertyNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_CastNode(self, node: CastNode):
        self.visit(node.expression)
        
        type_name = node.target_type.type_name.name
        
        # TODO 增加自定义数据类型和类的转换
        RUNTIME_TYPE_MAP = {
            "void": VBCObjectType.VOID,
            "char": VBCObjectType.CHAR,
            "int": VBCObjectType.INT,
            "long": VBCObjectType.LONG,
            "long long": VBCObjectType.LONGLONG,
            "super int": VBCObjectType.NLINT,
            "float": VBCObjectType.FLOAT,
            "double": VBCObjectType.DOUBLE,
            "super float": VBCObjectType.NLFLOAT,
            "string": VBCObjectType.STRING,
            "bool": VBCObjectType.BOOL,
        }
        
        target_enum = RUNTIME_TYPE_MAP.get(type_name, VBCObjectType.VOID)
        self._emit(Opcode.CAST, target_enum)

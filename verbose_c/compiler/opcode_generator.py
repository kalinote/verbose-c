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
        """
        if levels != 1:
            raise NotImplementedError(f"暂不支持多层跳出，levels={levels}")
        return self.break_label
    
    def get_continue_target(self, levels: int = 1) -> str:
        """
        TODO 获取continue跳转目标标签
        """
        if levels != 1:
            raise NotImplementedError(f"暂不支持多层跳转，levels={levels}")
        return self.continue_label

class OpcodeGenerator(VisitorBase):
    """
    根据AST生成机器码的访问者类
    
    TODO 暂定设计方案
    """
    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table: SymbolTable = symbol_table
        self.bytecode: list[tuple] = []
        self.labels = {}
        self.constant_pool = []
        self.next_label_id = 0
        self.loop_stack: list[LoopContext] = []  # 循环标签栈，后续支持嵌套循环和多层跳出
        self.function_compilation_results = {} # 存储函数编译结果

    # 工具方法
    def emit(self, opcode: Opcode, operand=None):
        """
        添加操作码到字节码流中
        
        Args:
            opcode (Opcode): 操作码
            operand (_type_, optional): 操作数. Defaults to None.
        """
        if operand is not None:
            self.bytecode.append((opcode, operand))
        else:
            self.bytecode.append((opcode,))

    def add_constant(self, value) -> int:
        """
        添加常量到常量池

        Args:
            value (int): 索引值
        """
        if value not in self.constant_pool:
            self.constant_pool.append(value)
        return self.constant_pool.index(value)

    def generate_label(self, lebel_name="unnamed"):
        """
        生成唯一标签

        Returns:
            label (str): 标签
        """
        label = f"L{self.next_label_id}_{lebel_name}"
        self.next_label_id += 1
        return label

    def mark_label(self, label):
        """标记标签位置"""
        self.labels[label] = len(self.bytecode)

    # 基本数据类型
    def visit_NameNode(self, node: NameNode): 
        symbol = self.symbol_table.lookup(node.name)
        if symbol is None:
            raise Exception(f"未定义的标识符: {node.name}, 在行: {node.start_line}, 列: {node.start_column}")

        if symbol.address is not None:
            self.emit(Opcode.LOAD_LOCAL_VAR, symbol.address)
        else:
            self.emit(Opcode.LOAD_GLOBAL_VAR, node.name)
    
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
            const_index = self.add_constant(vbc_int)
            self.emit(Opcode.LOAD_CONSTANT, const_index)
        elif target_type in VBCFloat.bit_width.keys():
            vbc_float = VBCFloat(node.value, target_type)
            const_index = self.add_constant(vbc_float)
            self.emit(Opcode.LOAD_CONSTANT, const_index)
        else:
            raise ValueError(f"不支持的目标数据类型: {target_type}")

    def visit_BoolNode(self, node: BoolNode):
        vbc_bool = VBCBool(node.value)
        const_index = self.add_constant(vbc_bool)
        self.emit(Opcode.LOAD_CONSTANT, const_index)
    
    def visit_StringNode(self, node: StringNode):
        vbc_str = VBCString(node.value)
        const_index = self.add_constant(vbc_str)
        self.emit(Opcode.LOAD_CONSTANT, const_index)
    
    def visit_NullNode(self, node: NullNode): 
        const_index = self.add_constant(VBCNull())
        self.emit(Opcode.LOAD_CONSTANT, const_index)

    def visit_TypeNode(self, node: TypeNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_RootNode(self, node: RootNode):
        # TODO 暂时遍历执行所有模块，后续进一步完善
        for module in node.modules:
            self.visit(module)
            
        # 执行完停机
        self.emit(Opcode.HALT)

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
        lebel = self.generate_label(node.name.name)
        self.mark_label(lebel)
        
    # 表达式
    def visit_UnaryOpNode(self, node: UnaryOpNode):
        self.visit(node.expr)
        
        if node.op == Operator.SUBTRACT:
            self.emit(Opcode.UNARY_MINUS)
        elif node.op == Operator.ADD:
            # TODO 检查这条分支是否有必要？ (+a 就是 a)
            pass
        elif node.op == Operator.NOT:
            self.emit(Opcode.LOGICAL_NOT)  
        else:
            raise ValueError(f"未知的单目运算符: {node.op}")

    def visit_BinaryOpNode(self, node: BinaryOpNode):
        
        # 优先判断短路操作
        if node.op == Operator.LOGICAL_AND:
            self.visit(node.left)
            
            end_label = self.generate_label("binary_end")
            self.emit(Opcode.DUP)
            self.emit(Opcode.JUMP_IF_FALSE, end_label)
            
            self.emit(Opcode.POP)
            self.visit(node.right)
            
            self.mark_label(end_label)
            
        elif node.op == Operator.LOGICAL_OR:
            self.visit(node.left)
            
            next_instr_label = self.generate_label("logical_or_next")
            end_label = self.generate_label("logical_or_end")
            
            self.emit(Opcode.DUP)
            # 如果左操作数为假，则跳转到下一指令，计算右操作数
            self.emit(Opcode.JUMP_IF_FALSE, next_instr_label)
            
            # 如果左操作数为真，则直接跳转到结尾，结果就是左操作数
            self.emit(Opcode.JUMP, end_label)
            
            self.mark_label(next_instr_label)
            # 弹出为假的左操作数，并计算右操作数
            self.emit(Opcode.POP)
            self.visit(node.right)
            
            self.mark_label(end_label)
        else:
            self.visit(node.left)
            self.visit(node.right)

            match node.op:
                case Operator.ADD:
                    self.emit(Opcode.ADD)
                case Operator.SUBTRACT:
                    self.emit(Opcode.SUBTRACT)
                case Operator.MULTIPLY:
                    self.emit(Opcode.MULTIPLY)
                case Operator.DIVIDE:
                    self.emit(Opcode.DIVIDE)
                case Operator.EQUAL:
                    self.emit(Opcode.EQUAL)
                case Operator.NOT_EQUAL:
                    self.emit(Opcode.NOT_EQUAL)
                case Operator.LESS_THAN:
                    self.emit(Opcode.LESS_THAN)
                case Operator.GREATER_THAN:
                    self.emit(Opcode.GREATER_THAN)
                case Operator.LESS_EQUAL:
                    self.emit(Opcode.LESS_EQUAL)
                case Operator.GREATER_EQUAL:
                    self.emit(Opcode.GREATER_EQUAL)
                case _:
                    raise ValueError(f"未知的二元运算符: {node.op}")


    def visit_RangeNode(self, node: RangeNode):
        # 高级功能，后续添加，现在不做实现
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_BlockNode(self, node: BlockNode):
        original_symbol_table = self.symbol_table
        block_symbol_table = SymbolTable(scope_type=ScopeType.BLOCK, parent=original_symbol_table)
        block_symbol_table._next_local_address = original_symbol_table._next_local_address
        self.symbol_table = block_symbol_table
        
        self.emit(Opcode.ENTER_SCOPE)
        
        for statement in node.statements:
            self.visit(statement)

        self.emit(Opcode.EXIT_SCOPE)
        
        original_symbol_table._next_local_address = self.symbol_table._next_local_address
        self.symbol_table = original_symbol_table

    def visit_VarDeclNode(self, node: VarDeclNode):
        declared_type: VBCObjectType | None = None
        type_name_str = node.var_type.type_name.name
        
        # TODO 优化这里的实现，可能使用dict会好一些?
        match type_name_str:
            case "char":
                declared_type = VBCObjectType.CHAR
            case "int":
                declared_type = VBCObjectType.INT
            case "long":
                declared_type = VBCObjectType.LONG
            case "long long":
                declared_type = VBCObjectType.LONGLONG
            case "super int":
                declared_type = VBCObjectType.NLINT
            case "float":
                declared_type = VBCObjectType.FLOAT
            case "double":
                declared_type = VBCObjectType.DOUBLE
            case "super float":
                declared_type = VBCObjectType.NLFLOAT
            case "string":
                declared_type = VBCObjectType.STRING
            case _:
                # TODO 完善对自定义类型的处理
                declared_type = VBCObjectType.CUSTOM

        if node.init_exp and declared_type is not None:
            setattr(node.init_exp, 'inferred_type', declared_type)
        
        symbol = self.symbol_table.add_symbol(
            node.name.name,
            node.var_type,
            SymbolKind.VARIABLE
        )
        
        if node.init_exp:
            self.visit(node.init_exp)
            self.emit(Opcode.STORE_LOCAL_VAR, symbol.address)  # 存储初始化值到变量
        else:
            # 没有初始化，设置默认值null
            const_index = self.add_constant(VBCNull())
            self.emit(Opcode.LOAD_CONSTANT, const_index)
            self.emit(Opcode.STORE_LOCAL_VAR, symbol.address)

    def visit_AssignmentNode(self, node: AssignmentNode):
        if isinstance(node.target, NameNode):
            self.visit(node.value)

            symbol = self.symbol_table.lookup(node.target.name)
            if symbol is None:
                raise ValueError(f"未定义的变量: {node.target.name}")

            if symbol.address is not None:
                self.emit(Opcode.STORE_LOCAL_VAR, symbol.address)
            else:
                # TODO 这里的逻辑应该还需要进一步确认
                self.emit(Opcode.STORE_GLOBAL_VAR, node.target.name)
        
        elif isinstance(node.target, GetPropertyNode):
            # 处理对象属性赋值，比如 obj.prop = value 的语法
            self.visit(node.value)
            self.visit(node.target.obj)

            property_name = self.add_constant(VBCString(node.target.property_name.name))
            self.emit(Opcode.LOAD_CONSTANT, property_name)

            self.emit(Opcode.SET_PROPERTY)
        else:
            raise RuntimeError(f"不支持的赋值目标类型: {type(node.target).__name__}")

    def visit_ExprStmtNode(self, node: ExprStmtNode):
        self.visit(node.expr)
        
        # TODO 完善逻辑，部分数据可能(?)不需要将数据弹出栈顶
        self.emit(Opcode.POP)

    def visit_IfNode(self, node: IfNode):
        self.visit(node.condition)
        
        endif_label = self.generate_label("if_end")
        if node.else_branch:
            else_label = self.generate_label("else_branch")
            
            # 条件为假时跳转到else分支
            self.emit(Opcode.JUMP_IF_FALSE, else_label)
            
            # 条件为真时执行then分支            
            self.visit(node.then_branch)
            self.emit(Opcode.JUMP, endif_label)

            self.mark_label(else_label)
            self.visit(node.else_branch)
            
        else:
            # 条件为假时跳转到语句结束
            self.emit(Opcode.JUMP_IF_FALSE, endif_label)
            
            self.visit(node.then_branch)
            
        # 标记语句结束位置
        self.mark_label(endif_label)

    def visit_WhileNode(self, node: WhileNode):
        loop_start_label = self.generate_label("while_start")
        loop_end_label = self.generate_label("while_end")
        
        # 创建循环上下文并推入栈
        loop_context = LoopContext(
            loop_type=LoopType.WHILE,
            continue_label=loop_start_label,  # continue跳转到循环开始（条件检查）
            break_label=loop_end_label        # break跳转到循环结束
        )
        self.loop_stack.append(loop_context)

        self.mark_label(loop_start_label)
        self.visit(node.condition)
        
        # 条件不满足则跳出循环
        self.emit(Opcode.JUMP_IF_FALSE, loop_end_label)

        self.visit(node.body)
        
        self.emit(Opcode.JUMP, loop_start_label)
        self.mark_label(loop_end_label)
        
        # 退出循环时弹出标签栈
        self.loop_stack.pop()

    def visit_ForNode(self, node: ForNode):
        loop_condition_label = self.generate_label("for_condition")
        loop_update_label = self.generate_label("for_update")
        loop_end_label = self.generate_label("for_end")
        
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
                self.emit(Opcode.POP)
        
        # 条件检查标签
        self.mark_label(loop_condition_label)
        
        # 检查循环条件
        if node.condition:
            self.visit(node.condition)
            self.emit(Opcode.JUMP_IF_FALSE, loop_end_label)
        
        self.visit(node.body)
    
        self.mark_label(loop_update_label)
        
        # 更新表达式
        if node.update:
            self.visit(node.update)
            # 如果更新是表达式，需要弹出结果（避免栈积累）
            if not isinstance(node.update, AssignmentNode):
                self.emit(Opcode.POP)
        
        # 跳转回条件检查
        self.emit(Opcode.JUMP, loop_condition_label)
        
        # 循环结束标签
        self.mark_label(loop_end_label)
        
        # 退出循环时弹出标签栈
        self.loop_stack.pop()

    def visit_ReturnNode(self, node: ReturnNode):
        if node.value:
            self.visit(node.value)  # 计算返回值并将其放在栈顶
        else:
            # 如果没有显示的返回值，则返回null
            const_index = self.add_constant(VBCNull())
            self.emit(Opcode.LOAD_CONSTANT, const_index)
        
        self.emit(Opcode.RETURN)    # 发出返回指令

    def visit_ContinueNode(self, node: ContinueNode):
        if not self.loop_stack:
            raise Exception(f"continue语句只能在循环内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到continue标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_continue_target()
        self.emit(Opcode.JUMP, target_label)

    def visit_BreakNode(self, node: BreakNode):
        if not self.loop_stack:
            raise Exception(f"break语句只能在循环内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到break标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_break_target()
        self.emit(Opcode.JUMP, target_label)

    def visit_ParamNode(self, node: ParamNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_FunctionNode(self, node: FunctionNode):
        from verbose_c.compiler.compiler import Compiler
        self.symbol_table.add_symbol(
            name=node.name.name,
            type_node=node.return_type,
            kind=SymbolKind.FUNCTION
        )
        
        function_symbol_table = SymbolTable(scope_type=ScopeType.FUNCTION, parent=self.symbol_table)
        
        # 将参数作为变量注册到函数的符号表中
        for param_node in node.args:
            function_symbol_table.add_symbol(
                name=param_node.name.name,
                type_node=param_node.var_type,
                kind=SymbolKind.PARAMETER
            )
            
        # 创建单独的编译环境
        function_compiler = Compiler(
            target_ast=node.body,
            # TODO 根据主编译器优化等级进行优化
            optimize_level=0,
            symbol_table=function_symbol_table,
            scope_type=ScopeType.FUNCTION,
        )
        
        function_compiler.compile()
        function_op_generator = function_compiler.opcode_generator

        # 检查一下编译后的操作码，如果最后没有显式的return，则添加一个return null;
        if not function_op_generator.bytecode or function_op_generator.bytecode[-1][0] != Opcode.RETURN:
            const_index = function_op_generator.add_constant(VBCNull())
            function_op_generator.emit(Opcode.LOAD_CONSTANT, const_index)
            function_op_generator.emit(Opcode.RETURN)

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
            local_count=local_count
        )
        
        const_index = self.add_constant(vbc_function)
        self.emit(Opcode.LOAD_CONSTANT, const_index)
        self.emit(Opcode.STORE_GLOBAL_VAR, node.name.name)

    def visit_CallNode(self, node: CallNode):
        if node.kwargs:
            raise NotImplementedError(f"关键字参数在函数调用中暂未实现, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 约定：先加载函数对象，再加载参数
        self.visit(node.name)
        
        for arg_expr in node.args:
            self.visit(arg_expr)
        
        num_args = len(node.args)
        self.emit(Opcode.CALL_FUNCTION, num_args)

    def visit_ClassNode(self, node: ClassNode):
        from verbose_c.compiler.compiler import Compiler
        class_name = node.name.name
        
        # TODO 类继承处理
        super_classes = []
        class_symbol_table = SymbolTable(scope_type=ScopeType.CLASS, parent=self.symbol_table)
        vbc_class = VBCClass(name=class_name, super_class=[])
        
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
                
                class_symbol_table.add_symbol(
                    name=method_name,
                    type_node=statement.return_type,
                    kind=SymbolKind.FUNCTION
                )
                
                method_symbol_table = SymbolTable(scope_type=ScopeType.FUNCTION, parent=class_symbol_table)
                method_symbol_table.add_symbol(
                    name="this",
                    type_node=TypeNode(type_name=NameNode(class_name)),
                    kind=SymbolKind.PARAMETER
                )

                for param_node in statement.args:
                    method_symbol_table.add_symbol(
                        name=param_node.name.name,
                        type_node=param_node.var_type,
                        kind=SymbolKind.PARAMETER
                    )
                
                # 编译方法
                method_compiler = Compiler(
                    target_ast=statement.body,
                    # TODO 根据主编译器的优化等级进行设置
                    optimize_level=0,
                    symbol_table=method_symbol_table,
                    scope_type=ScopeType.FUNCTION,
                )
                
                method_compiler.compile()
                method_op_generator = method_compiler.opcode_generator

                # 检查一下编译后的操作码，如果最后没有显式的return，则添加一个return null;
                if not method_op_generator.bytecode or method_op_generator.bytecode[-1][0] != Opcode.RETURN:
                    const_index = method_op_generator.add_constant(VBCNull())
                    method_op_generator.emit(Opcode.LOAD_CONSTANT, const_index)
                    method_op_generator.emit(Opcode.RETURN)

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
                local_count = method_symbol_table._next_local_address

                vbc_method = VBCFunction(
                    name=method_name,
                    bytecode=function_bytecode,
                    constants=function_constants,
                    param_count=param_count,
                    local_count=local_count
                )
                
                vbc_class._methods[method_name] = vbc_method
                
            elif isinstance(statement, VarDeclNode):
                field_name = statement.name.name
                class_symbol_table.add_symbol(
                    name=field_name,
                    type_node=statement.var_type,
                    kind=SymbolKind.VARIABLE
                )

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

        init_method_symbol_table = SymbolTable(scope_type=ScopeType.FUNCTION, parent=class_symbol_table)
        init_method_symbol_table.add_symbol(
            name="this",
            type_node=TypeNode(type_name=NameNode(class_name)),
            kind=SymbolKind.PARAMETER
        )
        for param_node in final_init_args:
            init_method_symbol_table.add_symbol(
                name=param_node.name.name,
                type_node=param_node.var_type,
                kind=SymbolKind.PARAMETER
            )
        
        init_compiler = Compiler(
            target_ast=final_init_method_node.body,
            optimize_level=0,
            symbol_table=init_method_symbol_table,
            scope_type=ScopeType.FUNCTION,
        )
        init_compiler.compile()
        init_op_generator = init_compiler.opcode_generator

        if not init_op_generator.bytecode or init_op_generator.bytecode[-1][0] != Opcode.RETURN:
            const_index = init_op_generator.add_constant(VBCNull())
            init_op_generator.emit(Opcode.LOAD_CONSTANT, const_index)
            init_op_generator.emit(Opcode.RETURN)

        for i, instruction in enumerate(init_op_generator.bytecode):
            if len(instruction) == 2:
                opcode, operand = instruction
                if isinstance(operand, str) and operand in init_op_generator.labels:
                    init_op_generator.bytecode[i] = (opcode, init_op_generator.labels[operand])

        vbc_init_method = VBCFunction(
            name="__init__",
            bytecode=init_op_generator.bytecode,
            constants=init_op_generator.constant_pool,
            param_count=len(final_init_args),
            local_count=init_method_symbol_table._next_local_address
        )
        
        vbc_class._methods["__init__"] = vbc_init_method

        class_index = self.add_constant(vbc_class)
        self.emit(Opcode.LOAD_CONSTANT, class_index)
        
        self.symbol_table.add_symbol(
            name=class_name,
            type_node=None,
            kind=SymbolKind.CLASS
        )
        
        self.emit(Opcode.STORE_GLOBAL_VAR, class_name)

    def visit_AttributeNode(self, node: AttributeNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_NewInstanceNode(self, node: NewInstanceNode):
        call_node = node.class_call
        
        if not isinstance(call_node, CallNode):
            raise TypeError(f"期望类调用, 得到 {type(call_node).__name__}")

        if call_node.kwargs:
            raise NotImplementedError(f"关键字参数在构造函数调用中暂未实现, 在行: {node.start_line}, 列: {node.start_column}")

        self.visit(call_node.name)
        
        for arg_expr in call_node.args:
            self.visit(arg_expr)
        
        num_args = len(call_node.args)
        self.emit(Opcode.NEW_INSTANCE, num_args)

    def visit_GetPropertyNode(self, node: GetPropertyNode):
        self.visit(node.obj)
        
        property_name = self.add_constant(VBCString(node.property_name.name))
        self.emit(Opcode.LOAD_CONSTANT, property_name)
        
        self.emit(Opcode.GET_PROPERTY)

    def visit_SetPropertyNode(self, node: SetPropertyNode):
        raise RuntimeError(f"{node.__class__.__name__} 节点不应该被 visit")

    def visit_IncludeNode(self, node: IncludeNode):
        # TODO 后续实现，暂时不要影响语法解析
        pass

    def visit_DefineNode(self, node: DefineNode):
        # TODO 后续实现，暂时不要影响语法解析
        pass
    
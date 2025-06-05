from verbose_c.compiler.enum import LoopType, SymbolKind
from verbose_c.compiler.opcode import Opcode
from verbose_c.compiler.symbol import SymbolTable
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
        self.loop_stack = []  # 循环标签栈，支持嵌套循环和将来的多层跳出

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
        const_index = self.add_constant(node.value)
        self.emit(Opcode.LOAD_CONSTANT, const_index)

    def visit_BoolNode(self, node: BoolNode):
        const_index = self.add_constant(node.value)
        self.emit(Opcode.LOAD_CONSTANT, const_index)
    
    def visit_StringNode(self, node: StringNode):
        const_index = self.add_constant(node.value)
        self.emit(Opcode.LOAD_CONSTANT, const_index)
    
    def visit_NullNode(self, node: NullNode): 
        const_index = self.add_constant(None)
        self.emit(Opcode.LOAD_CONSTANT, const_index)

    def visit_TypeNode(self, node: TypeNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_ModuleNode(self, node: ModuleNode):
        
        # TODO 暂时遍历执行所有语句，后续进一步完善
        for statement in node.body:
            self.visit(statement)
            
        # 执行完停机
        self.emit(Opcode.HALT)
        
        # 解析标签
        for i, instruction in enumerate(self.bytecode):
            if len(instruction) == 2:
                opcode, operand = instruction
                if isinstance(operand, str) and operand in self.labels:
                    self.bytecode[i] = (opcode, self.labels[operand])

    def visit_PackImportNode(self, node: PackImportNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")
        
    def visit_LabelNode(self, node: LabelNode):
        lebel = self.generate_label(node.name.name)
        self.mark_label(lebel)
        
    # 表达式
    def visit_UnaryOpNode(self, node: UnaryOpNode):
        self.visit(node.expr)
        
        if node.op == Operator.SUBTRACT:
            self.emit(Opcode.UNARY_MINUS)
        elif node.op == Operator.ADD:
            self.emit(Opcode.UNARY_PLUS)
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
            
            end_label = self.generate_label("binary_end")
            self.emit(Opcode.DUP)
            self.emit(Opcode.JUMP_IF_TRUE, end_label)
            
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
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_BlockNode(self, node: BlockNode):
        # TODO 作用域切换
        # TODO 进一步完善和优化
        
        for statement in node.statements:
            self.visit(statement)


    def visit_VarDeclNode(self, node: VarDeclNode):
        symbol = self.symbol_table.add_symbol(
            node.name.name,
            node.var_type,
            SymbolKind.VARIABLE
        )
        
        if node.init_exp:
            self.visit(node.init_exp)
            self.emit(Opcode.STORE_LOCAL_VAR, symbol.address)  # 存储初始化值到变量
        else:
            # 没有初始化，设置默认值None
            const_index = self.add_constant(None)
            self.emit(Opcode.LOAD_CONSTANT, const_index)
            self.emit(Opcode.STORE_LOCAL_VAR, symbol.address)

    def visit_VariableNode(self, node: VariableNode):
        """暂未使用"""
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_AssignmentNode(self, node: AssignmentNode):
        self.visit(node.value)

        symbol = self.symbol_table.lookup(node.name.name)
        if symbol is None:
            raise ValueError(f"未定义的变量: {node.name.name}")

        if symbol.address is not None:
            self.emit(Opcode.STORE_LOCAL_VAR, symbol.address)
        else:
            # TODO 这里的逻辑应该还需要进一步确认
            self.emit(Opcode.STORE_GLOBAL_VAR, node.name.name)


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
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_ContinueNode(self, node: ContinueNode):
        """
        实现continue语句：跳转到当前循环的continue标签
        
        对于while循环：跳转到循环开始（条件检查）
        对于for循环：跳转到更新表达式
        """
        if not self.loop_stack:
            raise Exception(f"continue语句只能在循环内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到continue标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_continue_target()
        self.emit(Opcode.JUMP, target_label)

    def visit_BreakNode(self, node: BreakNode):
        """
        实现break语句：跳转到当前循环的结束标签
        
        对于所有类型的循环：跳转到循环结束位置
        """
        if not self.loop_stack:
            raise Exception(f"break语句只能在循环内使用, 在行: {node.start_line}, 列: {node.start_column}")
        
        # 获取当前循环上下文并跳转到break标签
        current_loop = self.loop_stack[-1]
        target_label = current_loop.get_break_target()
        self.emit(Opcode.JUMP, target_label)

    def visit_ParamNode(self, node: ParamNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_FunctionNode(self, node: FunctionNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_CallNode(self, node: CallNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_ClassNode(self, node: ClassNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

    def visit_AttributeNode(self, node: AttributeNode):
        NotImplementedError(f"{node.__class__.__name__} visit 尚未实现")

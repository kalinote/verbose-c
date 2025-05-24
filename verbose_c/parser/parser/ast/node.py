from typing import Dict, List, Optional

from verbose_c.parser.parser.ast.enum import AttributeType
from verbose_c.parser.tokenizer.enum import Operator


class ASTNode:
    """
    抽象语法树节点基类
    """
    
    def __init__(self, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        self.type: str = self.__class__.__name__
        self.start_line: Optional[int] = start_line
        self.start_column: Optional[int] = start_column
        self.end_line: Optional[int] = end_line
        self.end_column: Optional[int] = end_column

    def __repr__(self) -> str:
        return f"{self.type}({self.__dict__})"
    
# 基本类型

class NameNode(ASTNode):
    """
    标识符节点
    """
    def __init__(self, name: str, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: str = name

class NumberNode(ASTNode):
    """
    数字节点
    """
    def __init__(self, value: str | int, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: int | float = float(value) if '.' in str(value) or 'e' in str(value).lower() else int(value)
        
class BoolNode(ASTNode):
    """
    布尔节点
    """
    def __init__(self, value: bool, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: bool = bool(value)
        
class StringNode(ASTNode):
    """
    字符串节点
    """
    def __init__(self, value: str, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: str = value
        
class NullNode(ASTNode):
    """
    空值节点
    """
    def __init__(self, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
    
class TypeNode(ASTNode):
    """
    类型节点
    """
    def __init__(self, type_name: NameNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.type_name: NameNode = type_name
    
# 结构和运算

class PackImportNode(ASTNode):
    """
    包导入节点
    """
    def __init__(self, name: NameNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name

class UnaryOpNode(ASTNode):
    """
    一元运算符节点
    """
    def __init__(self, op: Operator, expr: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.op: Operator = op
        self.expr: ASTNode = expr

class BinaryOpNode(ASTNode):
    """
    二元运算符节点
    """
    def __init__(self, left: ASTNode, op: Operator, right: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.left: ASTNode = left
        self.op: Operator = op
        self.right: ASTNode = right

class BlockNode(ASTNode):
    """
    语句块节点
    """
    def __init__(self, statements: List[ASTNode], start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.statements: List[ASTNode] = statements

class VarDeclNode(ASTNode):
    """
    变量声明节点
    """
    def __init__(self, var_type: NameNode, name: NameNode, init_exp: Optional[ASTNode] = None, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.var_type: NameNode = var_type
        self.name: NameNode = name
        self.init_exp: Optional[ASTNode] = init_exp

class VariableNode(ASTNode):
    """
    [暂未使用]变量节点
    """
    def __init__(self, name: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: ASTNode = name

class AssignmentNode(ASTNode):
    """
    赋值节点
    """
    def __init__(self, name: NameNode, value: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name
        self.value: ASTNode = value
        
class ExprStmtNode(ASTNode):
    """
    表达式语句节点
    """
    def __init__(self, expr: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.expr: ASTNode = expr


# 控制结构

class IfNode(ASTNode):
    """
    条件语句节点
    """
    def __init__(self, condition: ASTNode, then_branch: ASTNode, else_branch: Optional[ASTNode] = None, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.condition: ASTNode = condition
        self.then_branch: ASTNode = then_branch
        self.else_branch: Optional[ASTNode] = else_branch

class WhileNode(ASTNode):
    """
    无限循环循环语句节点
    """
    def __init__(self, condition: ASTNode, body: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.condition: ASTNode = condition
        self.body: ASTNode = body

class ForNode(ASTNode):
    """
    遍历循环语句节点
    """
    def __init__(self, init: ASTNode, condition: ASTNode, update: ASTNode, body: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.init: ASTNode = init
        self.condition: ASTNode = condition
        self.update: ASTNode = update
        self.body: ASTNode = body

class ReturnNode(ASTNode):
    """
    返回语句节点
    """
    def __init__(self, value: Optional[ASTNode] = None, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: Optional[ASTNode] = value


class ContinueNode(ASTNode):
    """
    继续语句节点
    """
    def __init__(self, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)

class BreakNode(ASTNode):
    """
    跳出循环语句节点
    """
    def __init__(self, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)

# 函数结构

class ParamNode(ASTNode):
    """
    参数节点
    """
    def __init__(self, var_type: ASTNode, name: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.var_type: ASTNode = var_type
        self.name: ASTNode = name

class FunctionNode(ASTNode):
    """
    函数定义节点
    """
    def __init__(self, return_type: ASTNode, name: ASTNode, args: List[ASTNode], kwargs: Dict[str, ASTNode], body: ASTNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.return_type: ASTNode = return_type
        self.name: ASTNode = name
        self.args: List[ASTNode] = args
        self.kwargs: Dict[str, ASTNode] = kwargs        # TODO 暂未使用
        self.body: ASTNode = body

class CallNode(ASTNode):
    """
    函数调用节点
    """
    def __init__(self, name: ASTNode, args: List[ASTNode], kwargs: Dict[str, ASTNode] = None, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: ASTNode = name
        self.args: List[ASTNode] = args
        self.kwargs: Dict[str, ASTNode] = kwargs        # TODO 暂未使用

# 类与对象
class ClassNode(ASTNode):
    """
    类节点

    Args:
        name (NameNode): 类名称
        base_classes (List[NameNode]): 父类名称
        body (BlockNode): 类主体，包括类属性和类方法
    """
    def __init__(self, name: NameNode, base_classes: List["ClassNode"], body: BlockNode, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name
        self.base_classes: List[ClassNode] = base_classes
        self.body: BlockNode = body

class AttributeNode(ASTNode):
    """
    TODO 属性节点
    
    Args:
        name (NameNode): 属性名
        type str: 属性类型
    """
    def __init__(self, name: NameNode, type: str, start_line: Optional[int] = None, start_column: Optional[int] = None, end_line: Optional[int] = None, end_column: Optional[int] = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name
        self.type: AttributeType = type

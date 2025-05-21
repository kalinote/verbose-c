from typing import Dict, List, Optional, Union


class ASTNode:
    """
    抽象语法树节点基类
    """
    
    def __init__(self, type_: str, line: Optional[int] = None, column: Optional[int] = None) -> None:
        self.type: str = type_
        self.line: Optional[int] = line
        self.column: Optional[int] = column

    def __repr__(self) -> str:
        return f"{self.type}({self.__dict__})"
    
# 基本结构

class NameNode(ASTNode):
    """
    标识符节点
    """
    def __init__(self, name: str, is_keyword: bool = False, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.name: str = name
        self.is_keyword: bool = is_keyword

class NumberNode(ASTNode):
    """
    数字节点
    """
    def __init__(self, value: str, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.value: Union[int, float] = float(value) if '.' in value or 'e' in value.lower() else int(value)
        
class BoolNode(ASTNode):
    """
    布尔节点
    """
    def __init__(self, value: bool, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.value: bool = bool(value)
        
class StringNode(ASTNode):
    """
    字符串节点
    """
    def __init__(self, value: str, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.value: str = value
        
class OpreatorNode(ASTNode):
    """
    操作符节点
    """
    def __init__(self, op: str, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.op: str = op
        
class NullNode(ASTNode):
    """
    空值节点
    """
    def __init__(self, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
    
class UnaryOpNode(ASTNode):
    """
    一元运算符节点
    """
    def __init__(self, op: str, expr: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.op: str = op
        self.expr: ASTNode = expr

class BinaryOpNode(ASTNode):
    """
    二元运算符节点
    """
    def __init__(self, left: ASTNode, op: str, right: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.left: ASTNode = left
        self.op: str = op
        self.right: ASTNode = right
    

class BlockNode(ASTNode):
    """
    语句块节点
    """
    def __init__(self, statements: List[ASTNode], line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.statements: List[ASTNode] = statements

class VarDeclNode(ASTNode):
    """
    变量声明节点
    """
    def __init__(self, var_type: str, name: str, value: Optional[ASTNode] = None, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.var_type: str = var_type
        self.name: str = name
        self.value: Optional[ASTNode] = value

class VariableNode(ASTNode):
    """
    变量节点
    """
    def __init__(self, name: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.name: ASTNode = name

class AssignmentNode(ASTNode):
    """
    赋值节点
    """
    def __init__(self, var_type: ASTNode, name: ASTNode, value: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.var_type: ASTNode = var_type
        self.name: ASTNode = name
        self.value: ASTNode = value
        
class ExprStmtNode(ASTNode):
    """
    表达式语句节点
    """
    def __init__(self, expr: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.expr: ASTNode = expr


# 控制结构

class IfNode(ASTNode):
    """
    条件语句节点
    """
    def __init__(self, condition: ASTNode, then_branch: ASTNode, else_branch: Optional[ASTNode] = None, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.condition: ASTNode = condition
        self.then_branch: ASTNode = then_branch
        self.else_branch: Optional[ASTNode] = else_branch

class WhileNode(ASTNode):
    """
    无限循环循环语句节点
    """
    def __init__(self, condition: ASTNode, body: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.condition: ASTNode = condition
        self.body: ASTNode = body

class ForNode(ASTNode):
    """
    遍历循环语句节点
    """
    def __init__(self, init: ASTNode, condition: ASTNode, update: ASTNode, body: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.init: ASTNode = init
        self.condition: ASTNode = condition
        self.update: ASTNode = update
        self.body: ASTNode = body

class ReturnNode(ASTNode):
    """
    返回语句节点
    """
    def __init__(self, value: Optional[ASTNode] = None, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.value: Optional[ASTNode] = value


class ContinueNode(ASTNode):
    """
    继续语句节点
    """
    def __init__(self, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)

class BreakNode(ASTNode):
    """
    跳出循环语句节点
    """
    def __init__(self, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)

# 函数结构

class ParamNode(ASTNode):
    """
    参数节点
    """
    def __init__(self, var_type: ASTNode, name: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.var_type: ASTNode = var_type
        self.name: ASTNode = name

class FunctionNode(ASTNode):
    """
    函数定义节点
    """
    def __init__(self, return_type: ASTNode, name: ASTNode, args: List[ASTNode], kwargs: Dict[str, ASTNode], body: ASTNode, line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.return_type: ASTNode = return_type
        self.name: ASTNode = name
        self.args: List[ASTNode] = args
        self.kwargs: Dict[str, ASTNode] = kwargs        # TODO 暂未使用
        self.body: ASTNode = body

class CallNode(ASTNode):
    """
    函数调用节点
    """
    def __init__(self, name: ASTNode, args: List[ASTNode], kwargs: Dict[str, ASTNode], line: Optional[int] = None, column: Optional[int] = None) -> None:
        super().__init__(self.__class__.__name__, line, column)
        self.name: ASTNode = name
        self.args: List[ASTNode] = args
        self.kwargs: Dict[str, ASTNode] = kwargs

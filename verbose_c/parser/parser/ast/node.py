from verbose_c.object.enum import VBCObjectType
from verbose_c.parser.parser.ast.enum import AttributeType
from verbose_c.parser.lexer.enum import Operator
from verbose_c.utils.visitor import VisitorBase


class ASTNode:
    """
    抽象语法树节点基类
    """
    
    def __init__(self, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        self._type: str = self.__class__.__name__
        self.start_line: int | None = start_line
        self.start_column: int | None = start_column
        self.end_line: int | None = end_line
        self.end_column: int | None = end_column

    def __repr__(self) -> str:
        return f"{self._type}({self.__dict__})"
    
    def accept(self, visitor: VisitorBase):
        method_name = f"visit_{self._type}"
        visitor_method = getattr(visitor, method_name, visitor.generic_visit)
        return visitor_method(self)

    
# 基本类型

class NameNode(ASTNode):
    """
    标识符节点
    
    Args:
        name (str): 标识符名称
    """
    def __init__(self, name: str, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: str = name

class NumberNode(ASTNode):
    """
    数字节点
    
    Args:
        value (str | int): 数字值，可以是整数或浮点数字符串或整数类型。如果字符串包含小数点或科学计数法，则解析为浮点数，否则解析为整数。
    """
    def __init__(self, value: str | int, inferred_type: VBCObjectType | None = None, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: int | float = float(value) if '.' in str(value) or 'e' in str(value).lower() else int(value)
        self.inferred_type: VBCObjectType | None = inferred_type
        
class BoolNode(ASTNode):
    """
    布尔节点
    
    Args:
        value (bool): 布尔值
    """
    def __init__(self, value: str, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: bool = False
        # TODO 暂定，后续使用专用token
        if value in ["true", "True"]:
            self.value = True
        
class StringNode(ASTNode):
    """
    字符串节点
    
    Args:
        value (str): 字符串值
    """
    def __init__(self, value: str, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: str = value
        
class NullNode(ASTNode):
    """
    空值节点
    """
    def __init__(self, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
    
class TypeNode(ASTNode):
    """
    类型节点
    
    Args:
        type_name (NameNode): 类型名称节点
    """
    def __init__(self, type_name: NameNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.type_name: NameNode = type_name
    
# 结构和运算
class RootNode(ASTNode):
    """
    根节点，作为整个AST的根节点

    Args:
        modules (list[ModuleNode]): 模块列表
    """
    def __init__(self, modules: list["ModuleNode"], start_line = None, start_column = None, end_line = None, end_column = None):
        super().__init__(start_line, start_column, end_line, end_column)
        self.modules: list[ModuleNode] = modules

class ModuleNode(ASTNode):
    """
    包节点，作为每个包的根节点
    
    Args:
        body (list[ASTNode]): 模块内容节点列表
    """
    def __init__(self, body: list[ASTNode], start_line = None, start_column = None, end_line = None, end_column = None):
        super().__init__(start_line, start_column, end_line, end_column)
        self.body: list[ASTNode] = body

class LabelNode(ASTNode):
    """
    标签节点
    
    Args:
        name (NameNode): 标签名
    """
    def __init__(self, name: NameNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name

class UnaryOpNode(ASTNode):
    """
    一元运算符节点
    
    Args:
        op (Operator): 运算符
        expr (ASTNode): 表达式
    """
    def __init__(self, op: Operator, expr: ASTNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.op: Operator = op
        self.expr: ASTNode = expr

class BinaryOpNode(ASTNode):
    """
    二元运算符节点
    
    Args:
        left (ASTNode): 左操作数
        op (Operator): 运算符
        right (ASTNode): 右操作数
    """
    def __init__(self, left: ASTNode, op: Operator, right: ASTNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.left: ASTNode = left
        self.op: Operator = op
        self.right: ASTNode = right

class RangeNode(ASTNode):
    """
    范围节点

    Args:
        start (NumberNode): 起始值
        end (NumberNode): 结束值
        step (NumberNode): 步长值
    """
    def __init__(self, start: NumberNode | None, end: NumberNode | None, step: NumberNode | None, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.start: NumberNode | None = start
        self.end: NumberNode | None = end
        self.step: NumberNode | None = step

class BlockNode(ASTNode):
    """
    语句块节点
    
    Args:
        statements (list[ASTNode]): 语句列表
    """
    def __init__(self, statements: list[ASTNode], start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.statements: list[ASTNode] = statements or []

class VarDeclNode(ASTNode):
    """
    变量声明节点
    
    Args:
        var_type (NameNode): 变量类型
        name (NameNode): 变量名
        init_exp (ASTNode| None): 初始化表达式，默认为None
    """
    def __init__(self, var_type: TypeNode, name: NameNode, init_exp: ASTNode| None = None, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.var_type: TypeNode = var_type
        self.name: NameNode = name
        self.init_exp: ASTNode| None = init_exp

class AssignmentNode(ASTNode):
    """
    赋值节点
    
    Args:
        target (ASTNode): 赋值的目标，可以是 NameNode 或 GetPropertyNode
        value (ASTNode): 赋值表达式节点
    """
    def __init__(self, target: ASTNode, value: ASTNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.target: ASTNode = target
        self.value: ASTNode = value
        
class ExprStmtNode(ASTNode):
    """
    单表达式语句节点
    
    Args:
        expr (ASTNode): 表达式节点
    """
    def __init__(self, expr: ASTNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.expr: ASTNode = expr


# 控制结构

class IfNode(ASTNode):
    """
    条件语句节点
    
    Args:
        condition (ASTNode): 条件表达式
        then_branch (ASTNode): 条件为真时执行的分支
        else_branch (ASTNode| None, optional): 条件为假时执行的分支。默认为 None。
    """
    def __init__(self, condition: ASTNode, then_branch: ASTNode| None, else_branch: ASTNode| None = None, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.condition: ASTNode = condition
        self.then_branch: ASTNode| None = then_branch
        self.else_branch: ASTNode| None = else_branch

class WhileNode(ASTNode):
    """
    无限循环循环语句节点
    
    Args:
        condition (ASTNode): 循环条件
        body (BlockNode): 循环体
    """
    def __init__(self, condition: ASTNode, body: BlockNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.condition: ASTNode = condition
        self.body: BlockNode = body

class ForNode(ASTNode):
    """
    遍历循环语句节点
    
    Args:
        init (ASTNode): 初始化表达式
        condition (ASTNode): 循环条件
        update (ASTNode): 更新表达式
        body (BlockNode): 循环体
    """
    def __init__(self, init: ASTNode, condition: ASTNode, update: ASTNode, body: BlockNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.init: ASTNode = init
        self.condition: ASTNode = condition
        self.update: ASTNode = update
        self.body: BlockNode = body

class ReturnNode(ASTNode):
    """
    返回语句节点
    
    Args:
        value (ASTNode| None): 返回的值节点，可以为空。默认为 None。
    """
    def __init__(self, value: ASTNode| None = None, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.value: ASTNode| None = value


class ContinueNode(ASTNode):
    """
    继续语句节点
    """
    def __init__(self, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)

class BreakNode(ASTNode):
    """
    跳出循环语句节点
    """
    def __init__(self, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)

# 函数结构

class ParamNode(ASTNode):
    """
    参数节点
    
    Args:
        var_type (ASTNode): 参数类型节点
        name (ASTNode): 参数名节点
    """
    def __init__(self, var_type: TypeNode, name: NameNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.var_type: TypeNode = var_type
        self.name: NameNode = name

class FunctionNode(ASTNode):
    """
    函数定义节点
    
    Args:
        return_type (TypeNode): 返回类型节点
        name (NameNode): 函数名节点
        args (list[ASTNode]): 参数列表节点
        kwargs (Optional[dict[str, ASTNode]]): 关键字参数字典节点
        body (BlockNode): 函数体节点
    """
    def __init__(self, return_type: TypeNode, name: NameNode, args: list[ParamNode], kwargs: dict[str, ParamNode], body: BlockNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.return_type: TypeNode = return_type
        self.name: NameNode = name
        self.args: list[ParamNode] = args or []
        self.kwargs: dict[str, ParamNode] = kwargs or {}        # TODO 暂未使用
        self.body: BlockNode = body

class CallNode(ASTNode):
    """
    函数调用节点
    
    Args:
        name (ASTNode): 函数名
        args (list[ASTNode]): 位置参数列表
        kwargs (dict[str, ASTNode], optional): 关键字参数字典。默认为 None。
    """
    def __init__(self, name: ASTNode, args: list[ASTNode], kwargs: dict[str, ASTNode], start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: ASTNode = name
        self.args: list[ASTNode] = args or []
        self.kwargs: dict[str, ASTNode] = kwargs or {}        # TODO 暂未使用

# 类与对象
class ClassNode(ASTNode):
    """
    类节点

    Args:
        name (NameNode): 类名称
        base_classes (str): 父类名称
        body (BlockNode): 类主体，包括类属性和类方法
    """
    def __init__(self, name: NameNode, body: BlockNode, base_classes: str, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name
        self.base_classes: str = base_classes or []
        self.body: BlockNode = body

class AttributeNode(ASTNode):
    """
    TODO 属性节点
    
    Args:
        name (NameNode): 属性名
        attr_type (str): 属性类型
    """
    def __init__(self, name: NameNode, attr_type: AttributeType, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: NameNode = name
        self.attr_type: AttributeType = attr_type

class NewInstanceNode(ASTNode):
    """
    创建新实例节点
    
    Args:
        class_call (CallNode): 对类构造函数的调用节点
    """
    def __init__(self, class_call: CallNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.class_call: CallNode = class_call

class GetPropertyNode(ASTNode):
    """
    属性获取节点, 表示 '.' 操作

    Args:
        obj (ASTNode): 属性所属的对象表达式
        property_name (NameNode): 要获取的属性的名称
    """
    def __init__(self, obj: ASTNode, property_name: NameNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.obj: ASTNode = obj
        self.property_name: NameNode = property_name

class SetPropertyNode(ASTNode):
    """
    属性设置/赋值节点

    Args:
        obj (ASTNode): 属性所属的对象表达式
        property_name (NameNode): 要设置的属性的名称
        value (ASTNode): 要赋给属性的值表达式
    """
    def __init__(self, obj: ASTNode, property_name: NameNode, value: ASTNode, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None) -> None:
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.obj: ASTNode = obj
        self.property_name: NameNode = property_name
        self.value: ASTNode = value

# 宏操作相关
class IncludeNode(ASTNode):
    """
    #include 宏指令
    """
    def __init__(self, path: str, start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.path: str = path

class DefineNode(ASTNode):
    """
    #define 宏指令
    
    支持两种形式:
    1. 值宏: #define PI 3.14
    2. 函数宏: #define MAX(a, b) ((a) > (b) ? (a) : (b))
    
    Args:
        name (str): 宏名称
        body (str): 宏内容
        function (bool): 是否为函数宏
        params (list[str]): 如果是函数宏，则为参数列表，否则为空列表
    """
    def __init__(self, name: str, body: str, function: bool = False, params: list[str] = [], start_line: int | None = None, start_column: int | None = None, end_line: int | None = None, end_column: int | None = None):
        super().__init__(start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column)
        self.name: str = name
        self.body: str = body
        self.function: bool = function
        self.params: list[str] | None = params

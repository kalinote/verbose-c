from enum import Enum, auto

class FunctionSignatureType(Enum):
    """
    方法签名类型
    
    METHOD: 普通方法
    CONSTRUCT: 构造方法
    GETTER: 获取器方法
    SETTER: 设置器方法
    """
    METHOD = auto()
    CONSTRUCT = auto()
    GETTER = auto()
    SETTER = auto()

class ScopeType(Enum):
    """
    作用域类型
    
    GLOBAL: 全局作用域
    LOCAL: 局部作用域（作用于一个模块）
    CLASS: 类作用域
    FUNCTION: 函数作用域
    BLOCK: 块级作用域（如 if, for, while 等）
    """
    GLOBAL = auto()
    LOCAL = auto()
    CLASS = auto()
    FUNCTION = auto()
    BLOCK = auto()

class SymbolKind(Enum):
    """
    符号种类
    
    VARIABLE: 变量
    FUNCTION: 函数
    CLASS: 类
    PARAMETER: 参数
    """
    VARIABLE = auto()
    FUNCTION = auto()
    CLASS = auto()
    PARAMETER = auto()

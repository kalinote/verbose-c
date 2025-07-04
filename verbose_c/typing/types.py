from abc import ABC, abstractmethod
from typing import Sequence
from verbose_c.object.enum import VBCObjectType

# --- 基础类型 ---

class Type(ABC):
    """
    所有编译时类型的基类。
    """
    @abstractmethod
    def __repr__(self) -> str:
        pass

    def __eq__(self, other):
        return isinstance(other, type(self))

    def __hash__(self):
        return hash(repr(self))

class VoidType(Type):
    """代表 'void' 类型，用于没有返回值的函数。"""
    def __repr__(self) -> str:
        return "Void"

class NullType(Type):
    """代表 'null' 字面量的类型。"""
    def __repr__(self) -> str:
        return "Null"

class IntegerType(Type):
    """代表整数类型，并区分具体的整数种类。"""
    def __init__(self, kind: VBCObjectType):
        # char在C语言体系中也被当作一种整数类型
        if kind not in {VBCObjectType.INT, VBCObjectType.LONG, VBCObjectType.LONGLONG, VBCObjectType.NLINT, VBCObjectType.CHAR}:
            raise ValueError(f"'{kind}' is not a valid integer type kind.")
        self.kind = kind

    def __repr__(self) -> str:
        return f"Integer({self.kind.name})"

    def __eq__(self, other):
        if not isinstance(other, IntegerType):
            return False
        return self.kind == other.kind

class FloatType(Type):
    """代表浮点数类型，并区分具体的浮点数种类。"""
    def __init__(self, kind: VBCObjectType):
        if kind not in {VBCObjectType.FLOAT, VBCObjectType.DOUBLE, VBCObjectType.NLFLOAT}:
            raise ValueError(f"'{kind}' is not a valid float type kind.")
        self.kind = kind

    def __repr__(self) -> str:
        return f"Float({self.kind.name})"

    def __eq__(self, other):
        if not isinstance(other, FloatType):
            return False
        return self.kind == other.kind

class StringType(Type):
    """代表字符串类型。"""
    def __repr__(self) -> str:
        return "String"

class BoolType(Type):
    """代表布尔类型。"""
    def __repr__(self) -> str:
        return "Bool"

class PointerType(Type):
    """
    代表指针类型，例如 int*
    """
    def __init__(self, base_type: 'Type'):
        self.base_type = base_type  # 指针指向的基础类型

    def __repr__(self) -> str:
        return f"Pointer({repr(self.base_type)})"

    def __eq__(self, other):
        if not isinstance(other, PointerType):
            return False
        return self.base_type == other.base_type

# --- 复合类型 ---

class FunctionType(Type):
    """
    代表函数类型，包含参数类型和返回类型。
    """
    def __init__(self, param_types: list['Type'], return_type: 'Type'):
        self.param_types = param_types
        self.return_type = return_type

    def __repr__(self) -> str:
        params = ", ".join(repr(p) for p in self.param_types)
        return f"Function({params}) -> {repr(self.return_type)}"

    def __eq__(self, other):
        if not isinstance(other, FunctionType):
            return False
        return self.param_types == other.param_types and self.return_type == other.return_type

class ClassType(Type):
    """
    代表类类型，包含其名称、字段和方法。
    """
    def __init__(
                self,
                name: str,
                # fields: dict[str, 'Type'] | None = None,
                # methods: dict[str, 'FunctionType'] | None = None,
                super_class: Sequence['ClassType'] = []
            ):
        self.name = name
        self.super_class: Sequence['ClassType'] = super_class   # 父类列表
        self.mro: Sequence['ClassType'] = []                    # 方法解析顺序列表
        self.fields = {}
        self.methods = {}
        
        self._compute_mro()

    def _compute_mro(self):
        """
        计算方法解析顺序
        """
        mro = [self]
        visited_names = {self.name}

        temp_mro = []
        if self.super_class:
            for sc in self.super_class:
                for base_class in sc.mro:
                    if base_class.name not in visited_names:
                        visited_names.add(base_class.name)
                        temp_mro.append(base_class)
        
        mro.extend(temp_mro)
        self.mro = mro

    def is_subclass_of(self, other: 'ClassType') -> bool:
        return other in self.mro

    def __repr__(self) -> str:
        return f"Class({self.name})"

    def __eq__(self, other):
        # 类类型通过名称来判断是否相等（名义类型系统 Nominal Typing）
        if not isinstance(other, ClassType):
            return False
        return self.name == other.name

# --- 特殊类型 ---

class AnyType(Type):
    """
    一个特殊的类型，可以匹配任何其他类型。
    可用于尚未完全实现的特性或内置函数。
    """
    def __repr__(self) -> str:
        return "Any"

class ErrorType(Type):
    """
    一个特殊的类型，代表在类型检查中遇到了错误。
    这可以防止一个错误引发连锁的、无关的错误报告。
    """
    def __repr__(self) -> str:
        return "Error"

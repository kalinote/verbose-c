from typing import Optional

from verbose_c.compiler.enum import ScopeType, SymbolKind
from verbose_c.typing.types import Type, ClassType


class Symbol:
    """
    标识符类
    
    Args:
        name (str): 标识符名称
        type_ (Type): 符号的编译时类型
        kind (SymbolKind): 标识符种类
        address (Optional[int]): 栈帧中的索引
        scope (Optional['SymbolTable']): 如果符号定义了一个新的作用域（如函数、类），此字段会指向该作用域的符号表
        is_defined (bool): FUNCTION 专用，变量/参数始终 True
    """
    def __init__(self,
                name: str,
                type_: Type,
                kind: SymbolKind = SymbolKind.VARIABLE,
                address: int | None = None,
                scope: Optional['SymbolTable'] = None,
                is_defined: bool = True):
        self.name: str = name
        self.type_: Type = type_
        self.kind: SymbolKind = kind
        self.address: int | None = address
        self.scope: 'SymbolTable' | None = scope
        self.is_defined: bool = is_defined

    def __repr__(self) -> str:
        return f"Symbol(name='{self.name}', type={repr(self.type_)}, kind={self.kind.name}, address={self.address})"


class SymbolTable:
    """
    符号表
    
    每个作用域都应该有单独的符号表
    """
    def __init__(self, scope_type: ScopeType, parent: Optional['SymbolTable'] = None):
        self._scope_type: ScopeType = scope_type
        self._symbols: dict[str, Symbol] = {}
        self._types: dict[str, Type] = {}
        self._parent: 'SymbolTable' | None = parent
        self._next_local_address: int = 0 # 用于分配局部变量的栈帧索引
        self._nested_scopes: list['SymbolTable'] = [] # 存储直接嵌套的子作用域

        if parent:
            # 继承父作用域的地址计数器，确保地址连续分配
            self._next_local_address = parent._next_local_address

    def add_nested_scope(self, scope: 'SymbolTable'):
        """添加一个嵌套的子作用域"""
        self._nested_scopes.append(scope)

    def get_nested_scope(self, index: int):
        return self._nested_scopes[index] if index < self.get_nested_scope_length() else None
    
    def get_nested_scope_length(self):
        return len(self._nested_scopes)

    def add_symbol(self, name: str, type_: Type, kind: SymbolKind = SymbolKind.VARIABLE, is_defined: bool = True) -> Symbol:
        """
        添加新符号到当前作用域
        """
        if name in self._symbols:
            raise NameError(f"符号 '{name}' 在当前作用域已存在")

        address: int | None = None
        # 只有函数或块作用域内的变量/参数才分配局部地址
        if self._scope_type in (ScopeType.FUNCTION, ScopeType.BLOCK) and kind in (SymbolKind.VARIABLE, SymbolKind.PARAMETER):
            address = self._next_local_address
            self._next_local_address += 1
        
        symbol = Symbol(name=name, type_=type_, kind=kind, address=address, is_defined=is_defined)
        self._symbols[name] = symbol

        # 类名同步注册到类型命名空间，便于在类型位置与值位置分离查找。
        if kind == SymbolKind.CLASS and isinstance(type_, ClassType):
            self._types[name] = type_

        return symbol

    def add_type_symbol(self, name: str, type_: Type):
        """
        添加新类型到当前作用域。
        TODO: 类型命名空间独立于值命名空间，允许后续按语言规则决定是否允许同名。
        """
        if name in self._types:
            raise NameError(f"类型 '{name}' 在当前作用域已存在")
        self._types[name] = type_

    def add_type_alias(self, alias_name: str, target_type: Type):
        """
        为 typedef 语义预留的类型别名入口。
        当前行为与 add_type_symbol 一致
        TODO: 后续可在此增加别名冲突策略。
        """
        self.add_type_symbol(alias_name, target_type)

    def lookup(self, name: str, current_scope_only: bool = False) -> Symbol | None:
        """
        查找符号。

        Args:
            name (str): 要查找的符号名称。
            current_scope_only (bool): 如果为 True，则仅在当前作用域中查找，不向上递归。
        """
        symbol = self._symbols.get(name)
        if symbol:
            return symbol
        
        if self._parent and not current_scope_only:
            return self._parent.lookup(name)
        
        return None

    def lookup_value(self, name: str, current_scope_only: bool = False) -> Symbol | None:
        """
        按值命名空间查找（变量、函数、类对象等）。
        """
        return self.lookup(name, current_scope_only=current_scope_only)

    def lookup_type(self, name: str, current_scope_only: bool = False) -> Type | None:
        """
        按类型命名空间查找（类、类型别名等）。
        """
        target = self._types.get(name)
        if target is not None:
            return target

        if self._parent and not current_scope_only:
            return self._parent.lookup_type(name)

        return None

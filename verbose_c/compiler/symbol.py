from typing import Optional

from verbose_c.compiler.enum import ScopeType, SymbolKind
from verbose_c.typing.types import Type


class Symbol:
    """
    标识符类
    
    Args:
        name (str): 标识符名称
        type_ (Type): 符号的编译时类型
        kind (SymbolKind): 标识符种类
        address (Optional[int]): 栈帧中的索引
        scope (Optional['SymbolTable']): 如果符号定义了一个新的作用域（如函数、类），此字段会指向该作用域的符号表
    """
    def __init__(self,
                name: str,
                type_: Type,
                kind: SymbolKind = SymbolKind.VARIABLE,
                address: int | None = None,
                scope: Optional['SymbolTable'] = None):
        self.name: str = name
        self.type_: Type = type_
        self.kind: SymbolKind = kind
        self.address: int | None = address
        self.scope: 'SymbolTable' | None = scope # 链接到子作用域

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
        self._parent: 'SymbolTable' | None = parent
        self._next_local_address: int = 0 # 用于分配局部变量的栈帧索引

        if parent:
            # 继承父作用域的地址计数器，确保地址连续分配
            self._next_local_address = parent._next_local_address

    def add_symbol(self, name: str, type_: Type, kind: SymbolKind = SymbolKind.VARIABLE) -> Symbol:
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
        
        symbol = Symbol(name=name, type_=type_, kind=kind, address=address)
        self._symbols[name] = symbol
        return symbol

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

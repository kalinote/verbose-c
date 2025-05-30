from typing import Optional

from verbose_c.compiler.enum import ScopeType, SymbolKind
from verbose_c.parser.parser.ast.node import TypeNode


class Symbol:
    """
    标识符类
    
    Args:
        name (str): 标识符名称
        type_node (Optional[TypeNode]: 类型节点
        kind (SymbolKind): 标识符种类
        address (Optional[int]): 栈帧中的索引
        is_initialized (bool): 是否已初始化
    """
    def __init__(self,
                 name: str,
                 type_node: Optional[TypeNode] = None,
                 kind: SymbolKind = SymbolKind.VARIABLE,
                 address: Optional[int] = None,
                 is_initialized: bool = False):
        self._name: str = name
        self._type_node: Optional[TypeNode] = type_node
        self._kind: SymbolKind = kind
        self._address: Optional[int] = address
        self._is_initialized: bool = is_initialized

    def __repr__(self) -> str:
        return f"Symbol(name='{self._name}', type={self._type_node.type_name.name if self._type_node else 'None'}, kind='{self._kind}', addr={self._address}, init={self._is_initialized})"

    @property
    def name(self) -> str:
        return self._name
    
    @property
    def type_node(self) -> Optional[TypeNode]:
        return self._type_node

    @property
    def kind(self) -> SymbolKind:
        return self._kind

    @property
    def address(self) -> Optional[int]:
        return self._address

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized


class SymbolTable:
    """
    符号表
    
    每个作用域都应该有单独的符号表
    
    Args:
        scope_type (ScopeType): 作用域类型
        parent (Optional[SymbolTable]): 父作用域的符号表，用于支持嵌套作用域查找
    """
    def __init__(self, scope_type: ScopeType, parent: Optional['SymbolTable'] = None):
        self._scope_type: ScopeType = scope_type
        self._symbols: dict[str, Symbol] = {}
        self._parent: Optional['SymbolTable'] = parent
        self._next_local_address: int = 0 # 用于分配局部变量的栈帧索引

    def add_symbol(self, name: str, type_node: Optional[TypeNode] = None, kind: SymbolKind = SymbolKind.VARIABLE) -> Symbol:
        """
        向当前作用域添加一个符号。
        如果符号已存在于当前作用域，则抛出错误（重复定义）。
        """
        if name in self._symbols:
            raise Exception(f"重复定义标识符: {name} 在 {self._scope_type.name} 作用域")
        
        # 为局部变量和参数分配地址
        address = None
        if kind in [SymbolKind.VARIABLE, SymbolKind.PARAMETER]:
            address = self._next_local_address
            self._next_local_address += 1

        symbol = Symbol(name, type_node, kind, address)
        self._symbols[name] = symbol
        return symbol

    def lookup_current_scope(self, name: str) -> Optional[Symbol]:
        """
        在当前作用域中查找符号。
        """
        return self._symbols.get(name)

    def lookup(self, name: str) -> Optional[Symbol]:
        """
        在当前作用域及其所有父作用域中查找符号。
        """
        current_table: Optional[SymbolTable] = self
        while current_table:
            symbol = current_table.lookup_current_scope(name)
            if symbol:
                return symbol
            current_table = current_table._parent
        return None

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
    """
    def __init__(self, scope_type: ScopeType, parent: Optional['SymbolTable'] = None):
        self._scope_type: ScopeType = scope_type
        self._symbols: dict[str, Symbol] = {}
        self._parent: Optional['SymbolTable'] = parent
        self._next_local_address: int = 0 # 用于分配局部变量的栈帧索引

    def _get_function_scope(self) -> Optional['SymbolTable']:
        """
        向上查找并返回最近的函数作用域符号表。
        """
        current = self
        while current:
            if current._scope_type == ScopeType.FUNCTION:
                return current
            current = current._parent
        return None

    def add_symbol(self, name: str, type_node: Optional[TypeNode] = None, kind: SymbolKind = SymbolKind.VARIABLE) -> Symbol:
        """
        向当前作用域添加一个符号。
        如果符号已存在于当前作用域，则抛出错误（重复定义）。
        """
        if name in self._symbols:
            raise Exception(f"重复定义标识符: {name} 在 {self._scope_type.name} 作用域")
        
        address = None
        # 查找最近的函数作用域
        function_scope = self._get_function_scope()
        
        if function_scope and kind in [SymbolKind.VARIABLE, SymbolKind.PARAMETER]:
            # 如果在函数作用域内（包括其子块作用域），则分配局部变量地址
            address = function_scope._next_local_address
            function_scope._next_local_address += 1

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

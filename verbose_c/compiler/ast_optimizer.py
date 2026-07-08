import copy
from dataclasses import dataclass, field
from typing import Any

from verbose_c.compiler.enum import ScopeType, SymbolKind
from verbose_c.compiler.symbol import Symbol, SymbolTable
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_float import VBCFloat
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_null import VBCNull
from verbose_c.object.t_string import VBCString
from verbose_c.parser.lexer.enum import Operator
from verbose_c.parser.parser.ast.node import *
from verbose_c.typing.types import (
    ArrayType,
    BoolType,
    ClassType,
    FloatType,
    FunctionType,
    IntegerType,
    NullType,
    PointerType,
    StringType,
    StructType,
    Type,
)


@dataclass
class ASTOptimizationStats:
    folded_constants: int = 0
    propagated_constants: int = 0
    propagated_copies: int = 0
    optimized_branches: int = 0
    eliminated_common_subexpressions: int = 0
    inlined_functions: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        """记录一次保守跳过原因。"""
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


@dataclass
class ASTOptimizationResult:
    ast_node: ASTNode
    stats: ASTOptimizationStats = field(default_factory=ASTOptimizationStats)

    @property
    def changed(self) -> bool:
        return (
            self.stats.folded_constants > 0
            or self.stats.propagated_constants > 0
            or self.stats.propagated_copies > 0
            or self.stats.optimized_branches > 0
            or self.stats.eliminated_common_subexpressions > 0
            or self.stats.inlined_functions > 0
        )


@dataclass
class _InlineCandidate:
    param_names: list[str]
    return_expr: ASTNode
    return_cast_target: Type | None


class _OptimizationEnv:
    """保存当前作用域内可证明的常量值和拷贝关系。"""

    def __init__(self, constants: dict[Any, Any] | None = None, copies: dict[Any, Any] | None = None) -> None:
        self.constants = dict(constants or {})
        self.copies = dict(copies or {})

    def copy(self) -> "_OptimizationEnv":
        return _OptimizationEnv(self.constants, self.copies)

    def get_constant(self, key: Any):
        return self.constants.get(key)

    def set_constant(self, key: Any, value: Any) -> None:
        self.constants[key] = value

    def kill_constant(self, key: Any) -> None:
        self.constants.pop(key, None)

    def clear_globals(self) -> None:
        for key in list(self.constants):
            if isinstance(key, str):
                self.constants.pop(key, None)
        for target, source in list(self.copies.items()):
            if isinstance(target, str) or isinstance(source, str):
                self.copies.pop(target, None)

    def clear_all(self) -> None:
        self.constants.clear()
        self.copies.clear()


class _ASTConstantOptimizer:
    def __init__(self, symbol_table: SymbolTable) -> None:
        self.symbol_table = symbol_table
        self.stats = ASTOptimizationStats()
        self._nested_scope_indices: dict[SymbolTable, int] = {}
        self._cse_temp_index = 0

    def optimize(self, node: ASTNode) -> ASTOptimizationResult:
        env = _OptimizationEnv()
        self._optimize_node(node, env)
        return ASTOptimizationResult(ast_node=node, stats=self.stats)

    def _optimize_node(self, node: ASTNode | None, env: _OptimizationEnv):
        if node is None:
            return None
        method = getattr(self, f"_optimize_{node.__class__.__name__}", self._optimize_generic)
        return method(node, env)

    def _optimize_generic(self, node: ASTNode, env: _OptimizationEnv):
        return node

    def _optimize_RootNode(self, node: RootNode, env: _OptimizationEnv):
        for module in node.modules:
            self._optimize_node(module, env)
        return node

    def _optimize_ModuleNode(self, node: ModuleNode, env: _OptimizationEnv):
        self._register_inline_candidates(node)
        self._optimize_statement_list(node.body, env)
        return node

    def _optimize_BlockNode(self, node: BlockNode, env: _OptimizationEnv):
        original_table = self.symbol_table
        block_table = self._next_nested_scope(original_table)
        if block_table is None:
            self.stats.skip("缺少块级符号表")
            block_env = env.copy()
            self._optimize_statement_list(node.statements, block_env)
            env.clear_all()
            return node

        self.symbol_table = block_table
        block_env = env.copy()
        self._optimize_statement_list(node.statements, block_env)
        self.symbol_table = original_table
        env.clear_all()
        return node

    def _optimize_statement_list(self, statements: list[ASTNode], env: _OptimizationEnv) -> None:
        optimized_statements: list[ASTNode] = []
        for index, statement in enumerate(statements):
            optimized = self._optimize_node(statement, env)
            if optimized is not None:
                statement = optimized
            prefix = self._extract_cse_prefix(statement)
            optimized_statements.extend(prefix)
            optimized_statements.append(statement)
        statements[:] = optimized_statements

    def _optimize_FunctionNode(self, node: FunctionNode, env: _OptimizationEnv):
        return node

    def _optimize_FunctionDeclNode(self, node: FunctionDeclNode, env: _OptimizationEnv):
        return node

    def _optimize_ClassNode(self, node: ClassNode, env: _OptimizationEnv):
        return node

    def _optimize_EnumNode(self, node: EnumNode, env: _OptimizationEnv):
        return node

    def _optimize_StructNode(self, node: StructNode, env: _OptimizationEnv):
        return node

    def _optimize_TypedefNode(self, node: TypedefNode, env: _OptimizationEnv):
        return node

    def _optimize_VarDeclNode(self, node: VarDeclNode, env: _OptimizationEnv):
        if node.array_dims:
            for index, dim in enumerate(node.array_dims):
                if dim is not None:
                    node.array_dims[index] = self._optimize_expr(dim, env)

        if node.init_exp is not None:
            if isinstance(node.init_exp, InitListNode):
                self._optimize_InitListNode(node.init_exp, env)
                self._kill_name(node.name, env)
                return node

            node.init_exp = self._optimize_expr(node.init_exp, env)
            value = self._constant_value(node.init_exp)
            if value is not None:
                self._set_name(node.name, value, env)
            else:
                source_key = self._copy_source(node.init_exp, env)
                if source_key is not None:
                    self._set_copy(node.name, source_key, env)
                    return node
                self._kill_name(node.name, env)
        else:
            self._kill_name(node.name, env)
        return node

    def _optimize_InitListNode(self, node: InitListNode, env: _OptimizationEnv):
        for index, elem in enumerate(node.elements):
            node.elements[index] = self._optimize_expr(elem, env)
        return node

    def _optimize_AssignmentNode(self, node: AssignmentNode, env: _OptimizationEnv):
        node.value = self._optimize_expr(node.value, env)

        if isinstance(node.target, NameNode):
            value = self._constant_value(node.value)
            if value is not None:
                self._set_name(node.target, value, env)
            else:
                source_key = self._copy_source(node.value, env)
                if source_key is not None:
                    self._set_copy(node.target, source_key, env)
                else:
                    self._kill_name(node.target, env)
            return node

        self._optimize_assignment_target(node.target, env)
        self._invalidate_indirect_write(env)
        return node

    def _optimize_CompoundAssignmentNode(self, node: CompoundAssignmentNode, env: _OptimizationEnv):
        self._optimize_assignment_target(node.left, env)
        node.right = self._optimize_expr(node.right, env)
        if isinstance(node.left, NameNode):
            self._kill_name(node.left, env)
        else:
            self._invalidate_indirect_write(env)
        return node

    def _optimize_UpdateExprNode(self, node: UpdateExprNode, env: _OptimizationEnv):
        self._optimize_assignment_target(node.base, env)
        if isinstance(node.base, NameNode):
            self._kill_name(node.base, env)
        else:
            self._invalidate_indirect_write(env)
        return node

    def _optimize_ExprStmtNode(self, node: ExprStmtNode, env: _OptimizationEnv):
        node.expr = self._optimize_expr(node.expr, env)
        return node

    def _optimize_ReturnNode(self, node: ReturnNode, env: _OptimizationEnv):
        if node.value is not None:
            node.value = self._optimize_expr(node.value, env)
        return node

    def _optimize_IfNode(self, node: IfNode, env: _OptimizationEnv):
        node.condition = self._optimize_expr(node.condition, env)
        condition = self._constant_value(node.condition)
        parent_table = self.symbol_table
        start_index = self._nested_scope_indices.get(parent_table, 0)
        if condition is not None:
            selected = node.then_branch if bool(condition) else node.else_branch
            branch_blocks = [branch for branch in (node.then_branch, node.else_branch) if isinstance(branch, BlockNode)]
            selected_table = None
            if isinstance(selected, BlockNode):
                selected_offset = branch_blocks.index(selected)
                selected_table = parent_table.get_nested_scope(start_index + selected_offset)
            self._nested_scope_indices[parent_table] = start_index + len(branch_blocks)
            env.clear_all()
            self.stats.optimized_branches += 1
            if selected is None:
                empty_block = self._empty_block_like(node)
                if branch_blocks:
                    self._attach_explicit_block_scope(
                        empty_block,
                        parent_table.get_nested_scope(start_index),
                        parent_table,
                        start_index + len(branch_blocks),
                    )
                return empty_block
            if selected_table is not None:
                self._optimize_block_with_table(selected, selected_table, _OptimizationEnv())
                self._attach_explicit_block_scope(
                    selected,
                    selected_table,
                    parent_table,
                    start_index + len(branch_blocks),
                    emit_runtime_scope=True,
                )
                return selected
            return self._optimize_node(selected, _OptimizationEnv()) or selected

        if node.then_branch is not None:
            self._optimize_node(node.then_branch, env.copy())
        if node.else_branch is not None:
            self._optimize_node(node.else_branch, env.copy())
        if (
            isinstance(node.then_branch, BlockNode)
            and isinstance(node.else_branch, BlockNode)
            and self._is_side_effect_free_expr(node.condition)
            and self._nodes_equivalent(node.then_branch, node.else_branch)
        ):
            self._attach_explicit_block_scope(
                node.then_branch,
                parent_table.get_nested_scope(start_index),
                parent_table,
                self._nested_scope_indices.get(parent_table, start_index),
                emit_runtime_scope=True,
            )
            env.clear_all()
            self.stats.optimized_branches += 1
            return node.then_branch
        env.clear_all()
        return node

    def _optimize_WhileNode(self, node: WhileNode, env: _OptimizationEnv):
        node.condition = self._optimize_expr(node.condition, _OptimizationEnv())
        condition = self._constant_value(node.condition)
        if condition is not None and not bool(condition):
            self._skip_block_scope_if_present(node.body)
            env.clear_all()
            self.stats.optimized_branches += 1
            return self._empty_block_like(node)
        self._optimize_node(node.body, _OptimizationEnv())
        env.clear_all()
        return node

    def _optimize_DoWhileNode(self, node: DoWhileNode, env: _OptimizationEnv):
        self._optimize_node(node.body, _OptimizationEnv())
        node.condition = self._optimize_expr(node.condition, _OptimizationEnv())
        env.clear_all()
        return node

    def _optimize_ForNode(self, node: ForNode, env: _OptimizationEnv):
        original_table = self.symbol_table
        start_index = self._nested_scope_indices.get(original_table, 0)
        for_table = self._next_nested_scope(original_table)
        if for_table is not None:
            self.symbol_table = for_table

        loop_env = env.copy()
        if node.init:
            node.init = self._optimize_node(node.init, loop_env)
        if node.condition:
            node.condition = self._optimize_expr(node.condition, _OptimizationEnv())
            condition = self._constant_value(node.condition)
            if condition is not None and not bool(condition):
                replacement = self._empty_block_like(node)
                if node.init is not None:
                    replacement.statements.append(node.init)
                self.symbol_table = original_table
                env.clear_all()
                self.stats.optimized_branches += 1
                if for_table is not None:
                    self._attach_explicit_block_scope(
                        replacement,
                        for_table,
                        original_table,
                        start_index + 1,
                    )
                return replacement
        if node.body:
            self._optimize_node(node.body, _OptimizationEnv())
        if node.update:
            node.update = self._optimize_node(node.update, _OptimizationEnv())

        self.symbol_table = original_table
        env.clear_all()
        return node

    def _optimize_SwitchNode(self, node: SwitchNode, env: _OptimizationEnv):
        node.condition = self._optimize_expr(node.condition, env)
        self._optimize_node(node.body, env.copy())
        env.clear_all()
        return node

    def _optimize_SwitchLabelNode(self, node: SwitchLabelNode, env: _OptimizationEnv):
        if node.value is not None:
            node.value = self._optimize_expr(node.value, env)
        return node

    def _optimize_expr(self, node: ASTNode, env: _OptimizationEnv) -> ASTNode:
        if isinstance(node, ConstantValueNode):
            return node
        method = getattr(self, f"_optimize_expr_{node.__class__.__name__}", None)
        if method is not None:
            return method(node, env)
        return self._optimize_node(node, env) or node

    def _optimize_expr_NameNode(self, node: NameNode, env: _OptimizationEnv) -> ASTNode:
        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is None:
            return node

        if symbol.const_value is not None:
            replacement = ConstantValueNode(
                VBCInteger(symbol.const_value),
                start_line=node.start_line,
                start_column=node.start_column,
                end_line=node.end_line,
                end_column=node.end_column,
            )
            self._copy_optimizer_attrs(node, replacement)
            self.stats.folded_constants += 1
            return replacement

        if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.CLASS):
            return node

        key = self._symbol_key(symbol)
        value = env.get_constant(key)
        if value is None:
            copy_key = self._canonical_copy_source(key, env)
            if copy_key == key:
                return node
            replacement = self._copy_target_node(copy_key, node)
            if replacement is None:
                return node
            self.stats.propagated_copies += 1
            return replacement

        replacement = ConstantValueNode(
            value,
            start_line=node.start_line,
            start_column=node.start_column,
            end_line=node.end_line,
            end_column=node.end_column,
        )
        self._copy_optimizer_attrs(node, replacement)
        self.stats.propagated_constants += 1
        return replacement

    def _optimize_expr_NumberNode(self, node: NumberNode, env: _OptimizationEnv) -> ASTNode:
        return node

    def _optimize_expr_StringNode(self, node: StringNode, env: _OptimizationEnv) -> ASTNode:
        return node

    def _optimize_expr_BoolNode(self, node: BoolNode, env: _OptimizationEnv) -> ASTNode:
        return node

    def _optimize_expr_NullNode(self, node: NullNode, env: _OptimizationEnv) -> ASTNode:
        return node

    def _optimize_expr_UnaryOpNode(self, node: UnaryOpNode, env: _OptimizationEnv) -> ASTNode:
        if node.op in (Operator.ADDRESS_OF, Operator.DEREFERENCE):
            self.stats.skip("一元指针操作")
            return node

        node.expr = self._optimize_expr(node.expr, env)
        value = self._constant_value(node.expr)
        if value is None:
            return node

        try:
            if node.op == Operator.SUBTRACT:
                folded = -value
            elif node.op == Operator.ADD:
                folded = +value
            elif node.op == Operator.NOT:
                folded = VBCInteger(0 if bool(value) else 1)
            else:
                return node
        except Exception:
            self.stats.skip("一元常量求值失败")
            return node

        return self._folded_node(node, folded)

    def _optimize_expr_BinaryOpNode(self, node: BinaryOpNode, env: _OptimizationEnv) -> ASTNode:
        if node.op in (Operator.LOGICAL_AND, Operator.LOGICAL_OR):
            return self._optimize_logical_binary(node, env)

        node.left = self._optimize_expr(node.left, env)
        node.right = self._optimize_expr(node.right, env)
        left = self._constant_value(node.left)
        right = self._constant_value(node.right)
        if left is None or right is None:
            return node

        folded = self._eval_binary(node.op, left, right)
        if folded is None:
            return node
        return self._folded_node(node, folded)

    def _optimize_logical_binary(self, node: BinaryOpNode, env: _OptimizationEnv) -> ASTNode:
        node.left = self._optimize_expr(node.left, env)
        left = self._constant_value(node.left)

        if left is not None:
            left_truthy = bool(left)
            if node.op == Operator.LOGICAL_AND and not left_truthy:
                return self._folded_node(node, VBCBool(False))
            if node.op == Operator.LOGICAL_OR and left_truthy:
                return self._folded_node(node, VBCBool(True))

        node.right = self._optimize_expr(node.right, env)
        right = self._constant_value(node.right)
        if left is None or right is None:
            return node

        if node.op == Operator.LOGICAL_AND:
            return self._folded_node(node, VBCBool(bool(left) and bool(right)))
        if node.op == Operator.LOGICAL_OR:
            return self._folded_node(node, VBCBool(bool(left) or bool(right)))
        return node

    def _optimize_expr_CastNode(self, node: CastNode, env: _OptimizationEnv) -> ASTNode:
        node.expression = self._optimize_expr(node.expression, env)
        self.stats.skip("显式类型转换")
        return node

    def _optimize_expr_ParenOrCastNode(self, node: ParenOrCastNode, env: _OptimizationEnv) -> ASTNode:
        if node.resolved_node is not None:
            node.resolved_node = self._optimize_expr(node.resolved_node, env)
        else:
            node.expression = self._optimize_expr(node.expression, env)
        return node

    def _optimize_expr_CallNode(self, node: CallNode, env: _OptimizationEnv) -> ASTNode:
        for index, arg in enumerate(node.args):
            node.args[index] = self._optimize_expr(arg, env)
        for key, arg in list(node.kwargs.items()):
            node.kwargs[key] = self._optimize_expr(arg, env)

        inlined = self._try_inline_call(node)
        if inlined is not None:
            self.stats.inlined_functions += 1
            return self._optimize_expr(inlined, env)

        if self._contains_address_of(node):
            env.clear_all()
        else:
            env.clear_globals()
        self.stats.skip("函数调用")
        return node

    def _optimize_expr_SubscriptNode(self, node: SubscriptNode, env: _OptimizationEnv) -> ASTNode:
        node.base = self._optimize_expr(node.base, env)
        node.index = self._optimize_expr(node.index, env)
        self.stats.skip("数组下标")
        return node

    def _optimize_expr_GetPropertyNode(self, node: GetPropertyNode, env: _OptimizationEnv) -> ASTNode:
        node.obj = self._optimize_expr(node.obj, env)
        self.stats.skip("属性访问")
        return node

    def _optimize_expr_NewInstanceNode(self, node: NewInstanceNode, env: _OptimizationEnv) -> ASTNode:
        node.class_call = self._optimize_expr_CallNode(node.class_call, env)
        self.stats.skip("对象创建")
        return node

    def _optimize_assignment_target(self, node: ASTNode, env: _OptimizationEnv) -> None:
        if isinstance(node, NameNode):
            return
        if isinstance(node, UnaryOpNode) and node.op == Operator.DEREFERENCE:
            node.expr = self._optimize_expr(node.expr, env)
            return
        if isinstance(node, SubscriptNode):
            node.base = self._optimize_expr(node.base, env)
            node.index = self._optimize_expr(node.index, env)
            return
        if isinstance(node, GetPropertyNode):
            node.obj = self._optimize_expr(node.obj, env)

    def _eval_binary(self, op: Operator, left, right):
        try:
            if op == Operator.ADD:
                return self._normalize_constant(left + right)
            if op == Operator.SUBTRACT:
                return self._normalize_constant(left - right)
            if op == Operator.MULTIPLY:
                return self._normalize_constant(left * right)
            if op == Operator.DIVIDE:
                return self._normalize_constant(left / right)
            if op == Operator.MODULO:
                return self._normalize_constant(left % right)
            if op == Operator.EQUAL:
                return self._normalize_constant(left == right)
            if op == Operator.NOT_EQUAL:
                return self._normalize_constant(left != right)
            if op == Operator.LESS_THAN:
                return self._normalize_constant(left < right)
            if op == Operator.GREATER_THAN:
                return self._normalize_constant(left > right)
            if op == Operator.LESS_EQUAL:
                return self._normalize_constant(left <= right)
            if op == Operator.GREATER_EQUAL:
                return self._normalize_constant(left >= right)
        except Exception:
            self.stats.skip("二元常量求值失败")
            return None
        return None

    def _normalize_constant(self, value):
        if isinstance(value, bool):
            return VBCBool(value)
        return value

    def _constant_value(self, node: ASTNode):
        if isinstance(node, ConstantValueNode):
            return node.value
        if isinstance(node, NumberNode):
            target_type = getattr(node, "inferred_type", None)
            try:
                if isinstance(node.value, int):
                    return VBCInteger(node.value, target_type) if target_type is not None else VBCInteger(node.value)
                if isinstance(node.value, float):
                    return VBCFloat(node.value, target_type) if target_type is not None else VBCFloat(node.value)
            except Exception:
                self.stats.skip("数字常量构造失败")
                return None
        if isinstance(node, StringNode):
            return VBCString(node.value[1:-1])
        if isinstance(node, BoolNode):
            return VBCBool(node.value)
        if isinstance(node, NullNode):
            return VBCNull()
        return None

    def _folded_node(self, original: ASTNode, value) -> ConstantValueNode:
        replacement = ConstantValueNode(
            value,
            start_line=original.start_line,
            start_column=original.start_column,
            end_line=original.end_line,
            end_column=original.end_column,
        )
        self._copy_optimizer_attrs(original, replacement)
        self.stats.folded_constants += 1
        return replacement

    def _optimize_block_with_table(self, node: BlockNode, block_table: SymbolTable, env: _OptimizationEnv) -> None:
        """使用指定符号表优化已知块。"""
        original_table = self.symbol_table
        self.symbol_table = block_table
        self._optimize_statement_list(node.statements, env.copy())
        self.symbol_table = original_table

    def _empty_block_like(self, original: ASTNode) -> BlockNode:
        """构造与原节点位置一致的空语句块。"""
        return BlockNode(
            [],
            start_line=original.start_line,
            start_column=original.start_column,
            end_line=original.end_line,
            end_column=original.end_column,
        )

    def _attach_explicit_block_scope(
        self,
        node: BlockNode,
        block_table: SymbolTable,
        parent_table: SymbolTable,
        parent_scope_index_after: int,
        emit_runtime_scope: bool = False,
    ) -> None:
        """记录裁剪分支原本对应的块级符号表。"""
        setattr(node, "_optimized_symbol_table", block_table)
        setattr(node, "_optimized_parent_symbol_table", parent_table)
        setattr(node, "_optimized_parent_scope_index_after", parent_scope_index_after)
        setattr(node, "_optimized_emit_runtime_scope", emit_runtime_scope)

    def _skip_block_scope_if_present(self, node: ASTNode | None) -> None:
        """跳过被删除块对应的块级符号表。"""
        if isinstance(node, BlockNode):
            current_index = self._nested_scope_indices.get(self.symbol_table, 0)
            if current_index < self.symbol_table.get_nested_scope_length():
                self._nested_scope_indices[self.symbol_table] = current_index + 1

    def _copy_optimizer_attrs(self, source: ASTNode, target: ASTNode) -> None:
        for key, value in source.__dict__.items():
            if key.startswith("_") and key != "_type":
                setattr(target, key, value)

    def _copy_source(self, node: ASTNode, env: _OptimizationEnv):
        if not isinstance(node, NameNode):
            return None
        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is None or not self._is_copyable_symbol(symbol):
            return None
        return self._canonical_copy_source(self._symbol_key(symbol), env)

    def _set_copy(self, target: NameNode, source_key, env: _OptimizationEnv) -> None:
        symbol = self.symbol_table.lookup_value(target.name)
        if symbol is None or not self._is_copyable_symbol(symbol):
            return
        target_key = self._symbol_key(symbol)
        if target_key == source_key:
            self._kill_symbol_dependencies(target_key, env)
            return
        self._kill_symbol_dependencies(target_key, env)
        env.copies[target_key] = source_key

    def _canonical_copy_source(self, key, env: _OptimizationEnv):
        seen = set()
        current = key
        while current in env.copies and current not in seen:
            seen.add(current)
            current = env.copies[current]
        return current

    def _copy_target_node(self, source_key, original_node: NameNode) -> NameNode | None:
        name = source_key if isinstance(source_key, str) else getattr(source_key, "name", None)
        if not isinstance(name, str):
            return None
        replacement = NameNode(
            name,
            start_line=original_node.start_line,
            start_column=original_node.start_column,
            end_line=original_node.end_line,
            end_column=original_node.end_column,
        )
        self._copy_optimizer_attrs(original_node, replacement)
        return replacement

    def _is_copyable_symbol(self, symbol: Symbol) -> bool:
        if symbol.kind != SymbolKind.VARIABLE or symbol.const_value is not None:
            return False
        return not isinstance(symbol.type_, (ArrayType, StructType, ClassType, FunctionType))

    def _kill_symbol_dependencies(self, key, env: _OptimizationEnv) -> None:
        env.kill_constant(key)
        env.copies.pop(key, None)
        for target, source in list(env.copies.items()):
            if source == key:
                env.copies.pop(target, None)

    def _set_name(self, node: NameNode, value, env: _OptimizationEnv) -> None:
        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is not None and symbol.kind == SymbolKind.VARIABLE and symbol.const_value is None:
            key = self._symbol_key(symbol)
            self._kill_symbol_dependencies(key, env)
            env.set_constant(key, value)

    def _kill_name(self, node: NameNode, env: _OptimizationEnv) -> None:
        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is not None:
            self._kill_symbol_dependencies(self._symbol_key(symbol), env)

    def _symbol_key(self, symbol: Symbol):
        if symbol.address is None:
            return symbol.name
        return symbol

    def _invalidate_indirect_write(self, env: _OptimizationEnv) -> None:
        env.clear_all()
        self.stats.skip("间接写入")

    def _next_nested_scope(self, table: SymbolTable) -> SymbolTable | None:
        current_index = self._nested_scope_indices.get(table, 0)
        if current_index >= table.get_nested_scope_length():
            return None
        self._nested_scope_indices[table] = current_index + 1
        return table.get_nested_scope(current_index)

    def _contains_address_of(self, node: ASTNode) -> bool:
        if isinstance(node, UnaryOpNode) and node.op == Operator.ADDRESS_OF:
            return True
        for value in node.__dict__.values():
            if isinstance(value, ASTNode) and self._contains_address_of(value):
                return True
            if isinstance(value, list):
                if any(isinstance(item, ASTNode) and self._contains_address_of(item) for item in value):
                    return True
            if isinstance(value, dict):
                if any(isinstance(item, ASTNode) and self._contains_address_of(item) for item in value.values()):
                    return True
        return False

    def _is_side_effect_free_expr(self, node: ASTNode) -> bool:
        """判断表达式能否在分支合并时安全删除。"""
        if isinstance(node, (ConstantValueNode, NumberNode, StringNode, BoolNode, NullNode, NameNode)):
            return True
        if isinstance(node, UnaryOpNode):
            return node.op in (Operator.ADD, Operator.SUBTRACT, Operator.NOT) and self._is_side_effect_free_expr(node.expr)
        if isinstance(node, BinaryOpNode):
            return self._is_side_effect_free_expr(node.left) and self._is_side_effect_free_expr(node.right)
        if isinstance(node, ParenOrCastNode):
            expr = node.resolved_node if node.resolved_node is not None else node.expression
            return self._is_side_effect_free_expr(expr)
        if isinstance(node, CastNode):
            return self._is_side_effect_free_expr(node.expression)
        return False

    def _nodes_equivalent(self, left, right) -> bool:
        """按 AST 结构判断两个分支是否完全一致。"""
        if type(left) is not type(right):
            return False
        if isinstance(left, ASTNode):
            left_items = self._semantic_items(left)
            right_items = self._semantic_items(right)
            if left_items.keys() != right_items.keys():
                return False
            return all(self._nodes_equivalent(left_items[key], right_items[key]) for key in left_items)
        if isinstance(left, list):
            return len(left) == len(right) and all(self._nodes_equivalent(l_item, r_item) for l_item, r_item in zip(left, right))
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(self._nodes_equivalent(left[key], right[key]) for key in left)
        if isinstance(left, (VBCInteger, VBCFloat, VBCBool, VBCString, VBCNull)):
            return type(left) is type(right) and getattr(left, "value", None) == getattr(right, "value", None)
        return left == right

    def _semantic_items(self, node: ASTNode) -> dict[str, Any]:
        """提取不含位置和优化器内部字段的 AST 语义属性。"""
        ignored = {"start_line", "start_column", "end_line", "end_column"}
        return {
            key: value
            for key, value in node.__dict__.items()
            if key not in ignored and not key.startswith("_")
        }

    def _extract_cse_prefix(self, statement: ASTNode) -> list[VarDeclNode]:
        """
        对单条语句执行保守 CSE。

        Args:
            statement: 已完成常量/传播/分支优化后的语句节点。

        Returns:
            需要插入到该语句前的编译器临时变量声明列表。
        """
        if self.symbol_table._scope_type not in (ScopeType.FUNCTION, ScopeType.BLOCK):
            return []
        if self._statement_has_write_read_overlap(statement):
            return []

        counts: dict[tuple, int] = {}
        nodes_by_sig: dict[tuple, ASTNode] = {}
        self._collect_cse_candidates(statement, counts, nodes_by_sig)
        chosen = [
            (signature, nodes_by_sig[signature])
            for signature, count in counts.items()
            if count > 1 and self._cse_candidate_type(nodes_by_sig[signature]) is not None
        ]
        if not chosen:
            return []

        chosen.sort(key=lambda item: len(repr(item[0])), reverse=True)
        replacements: dict[tuple, NameNode] = {}
        declarations: list[VarDeclNode] = []
        for signature, expr in chosen:
            if self._signature_contains_replaced(signature, replacements):
                continue
            expr_type = self._cse_candidate_type(expr)
            if expr_type is None:
                continue
            temp_name = self._new_cse_temp_name()
            self._add_cse_temp_symbol(temp_name, expr_type)
            init_expr = copy.deepcopy(expr)
            temp_decl = VarDeclNode(
                self._type_node_for_type(expr_type),
                NameNode(temp_name, start_line=expr.start_line, start_column=expr.start_column),
                init_expr,
                start_line=expr.start_line,
                start_column=expr.start_column,
                end_line=expr.end_line,
                end_column=expr.end_column,
            )
            replacement = NameNode(
                temp_name,
                start_line=expr.start_line,
                start_column=expr.start_column,
                end_line=expr.end_line,
                end_column=expr.end_column,
            )
            replacements[signature] = replacement
            declarations.append(temp_decl)

        if not declarations:
            return []

        self._replace_cse_candidates(statement, replacements)
        self.stats.eliminated_common_subexpressions += len(declarations)
        return declarations

    def _collect_cse_candidates(self, node: ASTNode, counts: dict[tuple, int], nodes_by_sig: dict[tuple, ASTNode]) -> None:
        signature = self._cse_signature(node)
        if signature is not None and self._is_cse_composite_candidate(node):
            counts[signature] = counts.get(signature, 0) + 1
            nodes_by_sig.setdefault(signature, node)

        for child in self._cse_child_nodes(node):
            self._collect_cse_candidates(child, counts, nodes_by_sig)

    def _replace_cse_candidates(self, node: ASTNode, replacements: dict[tuple, NameNode]) -> ASTNode:
        signature = self._cse_signature(node)
        if signature in replacements:
            return copy.deepcopy(replacements[signature])

        for key, value in list(node.__dict__.items()):
            if key.startswith("_"):
                continue
            if isinstance(value, ASTNode):
                setattr(node, key, self._replace_cse_candidates(value, replacements))
            elif isinstance(value, list):
                setattr(
                    node,
                    key,
                    [
                        self._replace_cse_candidates(item, replacements) if isinstance(item, ASTNode) else item
                        for item in value
                    ],
                )
            elif isinstance(value, dict):
                setattr(
                    node,
                    key,
                    {
                        item_key: self._replace_cse_candidates(item, replacements) if isinstance(item, ASTNode) else item
                        for item_key, item in value.items()
                    },
                )
        return node

    def _cse_signature(self, node: ASTNode):
        if isinstance(node, ConstantValueNode):
            return ("constant", type(node.value).__name__, getattr(node.value, "value", None), repr(getattr(node.value, "_object_type", None)))
        if isinstance(node, NumberNode):
            return ("number", node.value, repr(getattr(node, "inferred_type", None)))
        if isinstance(node, StringNode):
            return ("string", node.value)
        if isinstance(node, BoolNode):
            return ("bool", node.value)
        if isinstance(node, NullNode):
            return ("null",)
        if isinstance(node, NameNode):
            symbol = self.symbol_table.lookup_value(node.name)
            if symbol is None or symbol.kind in (SymbolKind.FUNCTION, SymbolKind.CLASS):
                return None
            return ("name", self._symbol_key(symbol))
        if isinstance(node, UnaryOpNode):
            if node.op not in (Operator.ADD, Operator.SUBTRACT, Operator.NOT):
                return None
            expr_sig = self._cse_signature(node.expr)
            if expr_sig is None:
                return None
            return ("unary", node.op, expr_sig)
        if isinstance(node, BinaryOpNode):
            if node.op in (Operator.LOGICAL_AND, Operator.LOGICAL_OR):
                return None
            left_sig = self._cse_signature(node.left)
            right_sig = self._cse_signature(node.right)
            if left_sig is None or right_sig is None:
                return None
            return ("binary", node.op, left_sig, right_sig)
        return None

    def _is_cse_composite_candidate(self, node: ASTNode) -> bool:
        return isinstance(node, (BinaryOpNode, UnaryOpNode))

    def _cse_child_nodes(self, node: ASTNode) -> list[ASTNode]:
        if isinstance(node, VarDeclNode):
            return [node.init_exp] if node.init_exp is not None else []
        if isinstance(node, AssignmentNode):
            return [node.value]
        if isinstance(node, ReturnNode):
            return [node.value] if node.value is not None else []
        if isinstance(node, ExprStmtNode):
            return [node.expr]
        if isinstance(node, BinaryOpNode):
            return [node.left, node.right]
        if isinstance(node, UnaryOpNode):
            return [node.expr]
        return []

    def _statement_has_write_read_overlap(self, statement: ASTNode) -> bool:
        written = self._written_symbol_keys(statement)
        if not written:
            return False
        read: set[Any] = set()
        for expr in self._cse_child_nodes(statement):
            self._collect_read_symbol_keys(expr, read)
        return bool(written & read)

    def _written_symbol_keys(self, node: ASTNode) -> set[Any]:
        if isinstance(node, VarDeclNode):
            return {self._name_symbol_key(node.name)}
        if isinstance(node, AssignmentNode) and isinstance(node.target, NameNode):
            return {self._name_symbol_key(node.target)}
        if isinstance(node, CompoundAssignmentNode) and isinstance(node.left, NameNode):
            return {self._name_symbol_key(node.left)}
        if isinstance(node, UpdateExprNode) and isinstance(node.base, NameNode):
            return {self._name_symbol_key(node.base)}
        result: set[Any] = set()
        for child in self._cse_child_nodes(node):
            result.update(self._written_symbol_keys(child))
        return {item for item in result if item is not None}

    def _collect_read_symbol_keys(self, node: ASTNode | None, result: set[Any]) -> None:
        if node is None:
            return
        if isinstance(node, NameNode):
            key = self._name_symbol_key(node)
            if key is not None:
                result.add(key)
            return
        if isinstance(node, AssignmentNode):
            self._collect_read_symbol_keys(node.value, result)
            return
        if isinstance(node, (CompoundAssignmentNode, UpdateExprNode)):
            return
        for child in self._cse_child_nodes(node):
            self._collect_read_symbol_keys(child, result)

    def _name_symbol_key(self, node: NameNode):
        symbol = self.symbol_table.lookup_value(node.name)
        if symbol is None:
            return None
        return self._symbol_key(symbol)

    def _signature_contains_replaced(self, signature: tuple, replacements: dict[tuple, NameNode]) -> bool:
        for existing in replacements:
            if self._signature_contains(existing, signature):
                return True
        return False

    def _signature_contains(self, outer, inner) -> bool:
        if outer == inner:
            return True
        if isinstance(outer, tuple):
            return any(self._signature_contains(item, inner) for item in outer)
        return False

    def _cse_candidate_type(self, node: ASTNode) -> Type | None:
        type_ = self._infer_cse_type(node)
        if isinstance(type_, (IntegerType, FloatType, BoolType, StringType)):
            return type_
        return None

    def _infer_cse_type(self, node: ASTNode) -> Type | None:
        if isinstance(node, ConstantValueNode):
            value = node.value
            if isinstance(value, VBCInteger):
                return IntegerType(value._object_type)
            if isinstance(value, VBCFloat):
                return FloatType(value._object_type)
            if isinstance(value, VBCBool):
                return BoolType()
            if isinstance(value, VBCString):
                return StringType()
            if isinstance(value, VBCNull):
                return NullType()
        if isinstance(node, NumberNode):
            if isinstance(node.value, int):
                return IntegerType(getattr(node, "inferred_type", None) or VBCObjectType.INT)
            if isinstance(node.value, float):
                return FloatType(getattr(node, "inferred_type", None) or VBCObjectType.DOUBLE)
        if isinstance(node, StringNode):
            return StringType()
        if isinstance(node, BoolNode):
            return BoolType()
        if isinstance(node, NullNode):
            return NullType()
        if isinstance(node, NameNode):
            symbol = self.symbol_table.lookup_value(node.name)
            if symbol is None:
                return None
            return symbol.type_
        if isinstance(node, UnaryOpNode):
            operand_type = self._infer_cse_type(node.expr)
            if node.op in (Operator.ADD, Operator.SUBTRACT) and isinstance(operand_type, (IntegerType, FloatType)):
                return operand_type
            if node.op == Operator.NOT and isinstance(operand_type, (IntegerType, FloatType, BoolType, PointerType)):
                return IntegerType(VBCObjectType.INT)
            return None
        if isinstance(node, BinaryOpNode):
            return self._infer_binary_cse_type(node)
        return None

    def _infer_binary_cse_type(self, node: BinaryOpNode) -> Type | None:
        left_type = self._infer_cse_type(node.left)
        right_type = self._infer_cse_type(node.right)
        if left_type is None or right_type is None:
            return None
        if isinstance(left_type, (ArrayType, StructType, ClassType, FunctionType)) or isinstance(right_type, (ArrayType, StructType, ClassType, FunctionType)):
            return None

        if node.op == Operator.MODULO:
            if isinstance(left_type, IntegerType) and isinstance(right_type, IntegerType):
                return IntegerType(VBCObjectType.INT)
            return None

        if node.op in (Operator.ADD, Operator.SUBTRACT, Operator.MULTIPLY, Operator.DIVIDE):
            if node.op == Operator.ADD and isinstance(left_type, StringType) and isinstance(right_type, StringType):
                return StringType()
            if isinstance(left_type, (IntegerType, FloatType)) and isinstance(right_type, (IntegerType, FloatType)):
                if isinstance(left_type, FloatType) or isinstance(right_type, FloatType):
                    return left_type if self._numeric_priority(left_type) >= self._numeric_priority(right_type) else right_type
                int_priority = self._object_type_priority(VBCObjectType.INT)
                left_p = IntegerType(VBCObjectType.INT) if self._numeric_priority(left_type) < int_priority else left_type
                right_p = IntegerType(VBCObjectType.INT) if self._numeric_priority(right_type) < int_priority else right_type
                return left_p if self._numeric_priority(left_p) >= self._numeric_priority(right_p) else right_p
            return None

        if node.op in (
            Operator.GREATER_THAN,
            Operator.GREATER_EQUAL,
            Operator.LESS_THAN,
            Operator.LESS_EQUAL,
            Operator.EQUAL,
            Operator.NOT_EQUAL,
        ):
            numeric = isinstance(left_type, (IntegerType, FloatType)) and isinstance(right_type, (IntegerType, FloatType))
            same_type = type(left_type) is type(right_type)
            pointer_null = node.op in (Operator.EQUAL, Operator.NOT_EQUAL) and (
                (isinstance(left_type, PointerType) and isinstance(right_type, NullType))
                or (isinstance(left_type, NullType) and isinstance(right_type, PointerType))
            )
            if numeric or same_type or pointer_null:
                return BoolType()
        return None

    def _numeric_priority(self, type_: IntegerType | FloatType) -> int:
        return self._object_type_priority(type_.kind)

    def _object_type_priority(self, kind: VBCObjectType) -> int:
        if kind in VBCInteger.bit_width:
            return VBCInteger.bit_width[kind][1]
        if kind in VBCFloat.bit_width:
            return VBCFloat.bit_width[kind][1]
        return 0

    def _type_node_for_type(self, type_: Type) -> TypeNode:
        if isinstance(type_, IntegerType):
            return TypeNode(NameNode(self._type_name_for_object_type(type_.kind)))
        if isinstance(type_, FloatType):
            return TypeNode(NameNode(self._type_name_for_object_type(type_.kind)))
        if isinstance(type_, BoolType):
            return TypeNode(NameNode("bool"))
        if isinstance(type_, StringType):
            return TypeNode(NameNode("string"))
        return TypeNode(NameNode("int"))

    def _type_name_for_object_type(self, kind: VBCObjectType) -> str:
        mapping = {
            VBCObjectType.CHAR: "char",
            VBCObjectType.INT: "int",
            VBCObjectType.LONG: "long",
            VBCObjectType.LONGLONG: "long long",
            VBCObjectType.NLINT: "unlimited int",
            VBCObjectType.FLOAT: "float",
            VBCObjectType.DOUBLE: "double",
            VBCObjectType.NLFLOAT: "unlimited float",
        }
        return mapping.get(kind, "int")

    def _new_cse_temp_name(self) -> str:
        while True:
            name = f"__vbc_cse_{self._cse_temp_index}"
            self._cse_temp_index += 1
            if self.symbol_table.lookup_value(name, current_scope_only=True) is None:
                return name

    def _add_cse_temp_symbol(self, name: str, type_: Type) -> None:
        max_address = self._max_local_address(self.symbol_table)
        if max_address is not None:
            self.symbol_table._next_local_address = max(self.symbol_table._next_local_address, max_address + 1)
        self.symbol_table.add_symbol(name, type_)

    def _max_local_address(self, table: SymbolTable) -> int | None:
        max_address: int | None = None
        for symbol in table._symbols.values():
            if symbol.address is not None:
                max_address = symbol.address if max_address is None else max(max_address, symbol.address)
        for nested in table._nested_scopes:
            nested_max = self._max_local_address(nested)
            if nested_max is not None:
                max_address = nested_max if max_address is None else max(max_address, nested_max)
        return max_address

    def _register_inline_candidates(self, node: ModuleNode) -> None:
        """
        登记当前模块中可供函数体优化阶段使用的内联候选。

        候选以快照形式保存，避免函数体后续被 CSE 或常量优化改写后污染调用点内联。
        """
        candidates = getattr(self.symbol_table, "_vbc_inline_candidates", {})
        for statement in node.body:
            if not isinstance(statement, FunctionNode):
                continue
            symbol = self.symbol_table.lookup_value(statement.name.name)
            if symbol is None or symbol.scope is None or not isinstance(symbol.type_, FunctionType):
                continue
            setattr(symbol.scope, "_vbc_function_name", statement.name.name)
            if self._is_inline_candidate(statement):
                return_node = statement.body.statements[0]
                candidates[statement.name.name] = _InlineCandidate(
                    [param.name.name for param in statement.args if param.name is not None],
                    copy.deepcopy(return_node.value),
                    getattr(return_node.value, "_implicit_cast_target", None),
                )
        setattr(self.symbol_table, "_vbc_inline_candidates", candidates)

    def _is_inline_candidate(self, node: FunctionNode) -> bool:
        if node.kwargs or len(node.body.statements) != 1:
            return False
        statement = node.body.statements[0]
        if not isinstance(statement, ReturnNode) or statement.value is None:
            return False
        if self._contains_call_to(statement.value, node.name.name):
            return False
        param_names = {param.name.name for param in node.args if param.name is not None}
        if len(param_names) != len(node.args):
            return False
        if not self._is_inline_expr_safe(statement.value, param_names):
            return False
        return self._expr_node_count(statement.value) <= 12

    def _try_inline_call(self, node: CallNode) -> ASTNode | None:
        """
        尝试把函数调用替换为可证明安全的内联表达式。

        只处理单 return 纯函数，保留实参和返回值边界上的隐式转换；遇到副作用、
        递归、关键字参数或复杂函数体时返回 None。
        """
        if node.kwargs or not isinstance(node.name, NameNode):
            return None
        candidates = self._lookup_inline_candidates()
        candidate = candidates.get(node.name.name)
        if candidate is None or len(candidate.param_names) != len(node.args):
            return None
        if self._current_function_name() == node.name.name:
            return None
        if not all(self._is_side_effect_free_expr(arg) for arg in node.args):
            return None

        replacements = {
            param_name: self._inline_argument_node(arg)
            for param_name, arg in zip(candidate.param_names, node.args)
        }
        inlined = self._replace_inline_params(copy.deepcopy(candidate.return_expr), replacements)
        if candidate.return_cast_target is not None:
            inlined = CastNode(
                self._type_node_for_type(candidate.return_cast_target),
                inlined,
                start_line=node.start_line,
                start_column=node.start_column,
                end_line=node.end_line,
                end_column=node.end_column,
            )
        self._copy_optimizer_attrs(node, inlined)
        return inlined

    def _lookup_inline_candidates(self) -> dict[str, _InlineCandidate]:
        table = self.symbol_table
        while table is not None:
            candidates = getattr(table, "_vbc_inline_candidates", None)
            if candidates is not None:
                return candidates
            table = table._parent
        return {}

    def _current_function_name(self) -> str | None:
        table = self.symbol_table
        while table is not None:
            name = getattr(table, "_vbc_function_name", None)
            if name is not None:
                return name
            table = table._parent
        return None

    def _inline_argument_node(self, arg: ASTNode) -> ASTNode:
        arg_copy = copy.deepcopy(arg)
        cast_target = getattr(arg, "_implicit_cast_target", None)
        if cast_target is None:
            return arg_copy
        return CastNode(
            self._type_node_for_type(cast_target),
            arg_copy,
            start_line=arg.start_line,
            start_column=arg.start_column,
            end_line=arg.end_line,
            end_column=arg.end_column,
        )

    def _replace_inline_params(self, node: ASTNode, replacements: dict[str, ASTNode]) -> ASTNode:
        if isinstance(node, NameNode) and node.name in replacements:
            replacement = copy.deepcopy(replacements[node.name])
            replacement.start_line = node.start_line
            replacement.start_column = node.start_column
            replacement.end_line = node.end_line
            replacement.end_column = node.end_column
            return replacement

        for key, value in list(node.__dict__.items()):
            if key.startswith("_"):
                continue
            if isinstance(value, ASTNode):
                setattr(node, key, self._replace_inline_params(value, replacements))
            elif isinstance(value, list):
                setattr(
                    node,
                    key,
                    [
                        self._replace_inline_params(item, replacements) if isinstance(item, ASTNode) else item
                        for item in value
                    ],
                )
            elif isinstance(value, dict):
                setattr(
                    node,
                    key,
                    {
                        item_key: self._replace_inline_params(item, replacements) if isinstance(item, ASTNode) else item
                        for item_key, item in value.items()
                    },
                )
        return node

    def _is_inline_expr_safe(self, node: ASTNode, param_names: set[str]) -> bool:
        if isinstance(node, (ConstantValueNode, NumberNode, StringNode, BoolNode, NullNode)):
            return True
        if isinstance(node, NameNode):
            if node.name in param_names:
                return True
            symbol = self.symbol_table.lookup_value(node.name)
            return symbol is not None and symbol.const_value is not None
        if isinstance(node, UnaryOpNode):
            return node.op in (Operator.ADD, Operator.SUBTRACT, Operator.NOT) and self._is_inline_expr_safe(node.expr, param_names)
        if isinstance(node, BinaryOpNode):
            return (
                node.op not in (Operator.LOGICAL_AND, Operator.LOGICAL_OR)
                and self._is_inline_expr_safe(node.left, param_names)
                and self._is_inline_expr_safe(node.right, param_names)
            )
        if isinstance(node, ParenOrCastNode):
            expr = node.resolved_node if node.resolved_node is not None else node.expression
            return self._is_inline_expr_safe(expr, param_names)
        if isinstance(node, CastNode):
            return self._is_inline_expr_safe(node.expression, param_names)
        return False

    def _contains_call_to(self, node: ASTNode, name: str) -> bool:
        if isinstance(node, CallNode) and isinstance(node.name, NameNode) and node.name.name == name:
            return True
        for value in node.__dict__.values():
            if isinstance(value, ASTNode) and self._contains_call_to(value, name):
                return True
            if isinstance(value, list):
                if any(isinstance(item, ASTNode) and self._contains_call_to(item, name) for item in value):
                    return True
            if isinstance(value, dict):
                if any(isinstance(item, ASTNode) and self._contains_call_to(item, name) for item in value.values()):
                    return True
        return False

    def _expr_node_count(self, node: ASTNode) -> int:
        count = 1
        for value in node.__dict__.values():
            if isinstance(value, ASTNode):
                count += self._expr_node_count(value)
            elif isinstance(value, list):
                count += sum(self._expr_node_count(item) for item in value if isinstance(item, ASTNode))
            elif isinstance(value, dict):
                count += sum(self._expr_node_count(item) for item in value.values() if isinstance(item, ASTNode))
        return count


def optimize_typed_ast(ast: ASTNode, symbol_table: SymbolTable, optimize_level: int) -> ASTOptimizationResult:
    """按优化等级对已类型检查 AST 执行保守常量优化。"""
    if optimize_level <= 0:
        return ASTOptimizationResult(ast_node=ast)
    if optimize_level != 1:
        raise RuntimeError(f"Unsupported optimize level: {optimize_level}")
    return _ASTConstantOptimizer(symbol_table).optimize(ast)

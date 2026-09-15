"""编译期常量求值复用运行时数值规则。"""

from verbose_c.object.enum import VBCObjectType
from verbose_c.object.numeric import cast_numeric, numeric_binary, numeric_compare, numeric_literal, numeric_unary
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_integer import VBCInteger
from verbose_c.parser.lexer.enum import Operator
from verbose_c.parser.parser.ast.node import (
    ASTNode, BinaryOpNode, BoolNode, CastNode, ConstantValueNode,
    NameNode, NumberNode, UnaryOpNode,
)
from verbose_c.typing.types import BoolType, FloatType, IntegerType


def evaluate_numeric_constant(node: ASTNode, symbol_table=None):
    """
    计算不含运行时状态的数值表达式，保留每个转换边界和短路规则。

    Args:
        node: 已完成类型检查的数值表达式。
        symbol_table: 可选符号表，仅读取 enum 等编译期常量。

    Returns:
        数值对象；需要运行时求值时返回 None。

    Raises:
        ArithmeticError: 定宽溢出或除零。
        ValueError: 数值转换越界。
    """
    if getattr(node, "resolved_node", None) is not None:
        value = evaluate_numeric_constant(node.resolved_node, symbol_table)
    elif isinstance(node, ConstantValueNode):
        value = node.value
    elif isinstance(node, NumberNode):
        value = numeric_literal(node.value, node.inferred_type)
    elif isinstance(node, BoolNode):
        value = VBCBool(node.value)
    elif isinstance(node, NameNode) and symbol_table is not None:
        symbol = symbol_table.lookup_value(node.name)
        if symbol is None or symbol.const_value is None:
            return None
        value = numeric_literal(symbol.const_value)
    elif isinstance(node, CastNode):
        target = getattr(node, "_cast_target_type", None)
        if not isinstance(target, (IntegerType, FloatType, BoolType)):
            return None
        value = evaluate_numeric_constant(node.expression, symbol_table)
        if value is not None:
            value = cast_numeric(value, VBCObjectType.BOOL if isinstance(target, BoolType) else target.kind)
    elif isinstance(node, UnaryOpNode) and node.op in (Operator.ADD, Operator.SUBTRACT, Operator.NOT):
        value = evaluate_numeric_constant(node.expr, symbol_table)
        if value is not None:
            value = VBCInteger(int(not bool(value))) if node.op == Operator.NOT else numeric_unary(node.op.value, value)
    elif isinstance(node, BinaryOpNode):
        left = evaluate_numeric_constant(node.left, symbol_table)
        if left is None:
            return None
        if node.op == Operator.LOGICAL_AND and not bool(left):
            value = VBCBool(False)
        elif node.op == Operator.LOGICAL_OR and bool(left):
            value = VBCBool(True)
        else:
            right = evaluate_numeric_constant(node.right, symbol_table)
            if right is None:
                return None
            if node.op in (Operator.LOGICAL_AND, Operator.LOGICAL_OR):
                value = VBCBool(bool(right))
            elif node.op in (Operator.ADD, Operator.SUBTRACT, Operator.MULTIPLY, Operator.DIVIDE, Operator.MODULO):
                value = numeric_binary(node.op.value, left, right)
            else:
                value = numeric_compare(node.op.value, left, right)
    else:
        return None
    target = getattr(node, "_implicit_cast_target", None)
    if value is not None and isinstance(target, (IntegerType, FloatType, BoolType)):
        value = cast_numeric(value, VBCObjectType.BOOL if isinstance(target, BoolType) else target.kind)
    return value

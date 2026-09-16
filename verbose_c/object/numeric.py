"""编译期、VM 和 native 共享的数值类型与算术约定。"""

import math
import operator
import struct

from verbose_c.object.enum import VBCObjectType

INTEGER_LAYOUT = {
    VBCObjectType.CHAR: (8, 1),
    VBCObjectType.SHORT: (16, 1.5),
    VBCObjectType.INT: (32, 2),
    VBCObjectType.LONG: (64, 3),
    VBCObjectType.LONGLONG: (64, 4),
    VBCObjectType.NLINT: (float("inf"), 5),
}
FLOAT_LAYOUT = {
    VBCObjectType.FLOAT: ((8, 23), 6),
    VBCObjectType.DOUBLE: ((11, 52), 7),
    VBCObjectType.NLFLOAT: ((float("inf"), float("inf")), 8),
}
INTEGER_LIMITS = {
    kind: (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
    for kind, (bits, _) in INTEGER_LAYOUT.items() if kind != VBCObjectType.NLINT
}
NUMERIC_RANKS = {kind: spec[1] for kind, spec in (INTEGER_LAYOUT | FLOAT_LAYOUT).items()}
INTEGER_KIND_NAMES = {name: kind for kind in INTEGER_LAYOUT for name in (kind.name.lower(), kind.value)}
INTEGER_KIND_NAMES["int64"] = VBCObjectType.LONG
NATIVE_NUMERIC_ERRORS = {
    2: "整数溢出",
    3: "数值转换失败: 转换为 CHAR 时超出范围",
    4: "数值转换失败: 转换为 SHORT 时超出范围",
    5: "数值转换失败: 转换为 INT 时超出范围",
    6: "数值转换失败: 转换为 LONG 时超出范围",
    7: "浮点溢出",
    8: "除零错误",
    9: "数值转换失败: 浮点数不能表示为目标整数",
    10: "数组下标越界",
}
_BINARY_OPERATORS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}
_COMPARISONS = {
    "==": operator.eq, "!=": operator.ne, "<": operator.lt,
    "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}


def check_integer(value: int, kind: VBCObjectType) -> int:
    """校验定宽有符号整数的范围；无限整数保留任意精度。"""
    limits = INTEGER_LIMITS.get(kind)
    if limits is not None and not limits[0] <= value <= limits[1]:
        raise OverflowError(f"整数溢出: {kind.name} 的值 {value} 超出范围 {limits[0]}..{limits[1]}")
    return value


def round_float(value: int | float, kind: VBCObjectType) -> float:
    """
    按目标格式进行一次就近偶数舍入，允许次正规数与下溢。

    Args:
        value: 原始整数或浮点值，整数转 binary32 时保留舍入所需的低位。
        kind: 目标浮点类型。

    Returns:
        精确表示目标格式结果的 Python 浮点数。

    Raises:
        OverflowError: 定宽浮点不能表示该数值。
    """
    try:
        if kind == VBCObjectType.FLOAT and isinstance(value, int):
            # 直接舍入到 24 位有效数字，避免 int64 -> double -> float 的双重舍入。
            magnitude = abs(value)
            shift = max(0, magnitude.bit_length() - 24)
            if shift:
                significand, remainder = divmod(magnitude, 1 << shift)
                halfway = 1 << (shift - 1)
                if remainder > halfway or (remainder == halfway and significand & 1):
                    significand += 1
                magnitude = significand << shift
            value = -magnitude if value < 0 else magnitude
        result = float(value)
        if kind == VBCObjectType.FLOAT:
            result = struct.unpack("<f", struct.pack("<f", result))[0]
        if kind != VBCObjectType.NLFLOAT and not math.isfinite(result):
            raise OverflowError
    except (ValueError, OverflowError) as exc:
        raise OverflowError(f"浮点溢出: {kind.name} 不能表示该数值") from exc
    return result


def float_bits(value: float, kind: VBCObjectType) -> int:
    """取得浮点数的 IEEE 位模式，用于 native 立即数和范围检查。"""
    if kind == VBCObjectType.FLOAT:
        return struct.unpack("<I", struct.pack("<f", value))[0]
    return struct.unpack("<q", struct.pack("<d", value))[0]


def integer_divmod(left: int, right: int) -> tuple[int, int]:
    """计算向零截断的整数商及与被除数同号的余数。"""
    if right == 0:
        raise ZeroDivisionError("除零错误")
    quotient = abs(left) // abs(right)
    if (left < 0) != (right < 0):
        quotient = -quotient
    return quotient, left - quotient * right


def common_numeric_kind(left: VBCObjectType, right: VBCObjectType) -> VBCObjectType:
    """先将布尔值和小整数提升为 int，再选择共同的算术类型。"""
    promoted = {VBCObjectType.BOOL, VBCObjectType.CHAR, VBCObjectType.SHORT}
    left = VBCObjectType.INT if left in promoted else left
    right = VBCObjectType.INT if right in promoted else right
    if left not in NUMERIC_RANKS or right not in NUMERIC_RANKS:
        raise TypeError(f"类型 '{left.name}' 和 '{right.name}' 不能参与数值运算")
    return left if NUMERIC_RANKS[left] >= NUMERIC_RANKS[right] else right


def numeric_literal(value: int | float, target: VBCObjectType | None = None):
    """按字面量值选择可容纳它的数值类型，或保留已推导的类型。"""
    from verbose_c.object.t_float import VBCFloat
    from verbose_c.object.t_integer import VBCInteger

    if isinstance(value, int):
        if target is not None:
            return VBCInteger(value, target)
        kind = next((kind for kind in (VBCObjectType.INT, VBCObjectType.LONG) if INTEGER_LIMITS[kind][0] <= value <= INTEGER_LIMITS[kind][1]), VBCObjectType.NLINT)
        return VBCInteger(value, kind)
    if target is not None:
        return VBCFloat(value, target)
    return VBCFloat(value, VBCObjectType.DOUBLE)


def cast_numeric(source, target: VBCObjectType):
    """
    转换数值对象，保留整数之间转换的完整精度。

    Args:
        source: 整数、浮点或布尔对象。
        target: 目标数值类型。

    Returns:
        已检查范围并完成舍入或截断的数值对象。

    Raises:
        ValueError: 数值不能表示为目标类型。
        TypeError: 源类型或目标类型不支持数值转换。
    """
    from verbose_c.object.t_bool import VBCBool
    from verbose_c.object.t_float import VBCFloat
    from verbose_c.object.t_integer import VBCInteger

    if not isinstance(source, (VBCInteger, VBCFloat, VBCBool)):
        raise TypeError(f"不支持从类型 '{source._object_type.name}' 到 '{target.name}' 的数值转换")
    if target == VBCObjectType.BOOL:
        return VBCBool(bool(source))
    try:
        if target in VBCInteger.bit_width:
            return VBCInteger(int(source.value), target)
        if target in VBCFloat.bit_width:
            return VBCFloat(source.value, target)
    except (ValueError, OverflowError) as exc:
        raise ValueError(
            f"数值转换失败: '{source._object_type.name}' -> '{target.name}'，值 {source.value} 超出范围或不能表示"
        ) from exc
    raise TypeError(f"不支持的数值转换目标: {target.name}")


def numeric_binary(op: str, left, right):
    """
    按共同类型计算数值运算，结果不能因溢出自动扩宽。

    Args:
        op: 算术运算符。
        left: 左数值对象。
        right: 右数值对象。

    Returns:
        保留共同算术类型的运行时数值对象。
    """
    from verbose_c.object.t_float import VBCFloat
    from verbose_c.object.t_integer import VBCInteger

    kind = common_numeric_kind(left._object_type, right._object_type)
    left_value = cast_numeric(left, kind).value
    right_value = cast_numeric(right, kind).value
    if op in ("/", "%") and kind in INTEGER_LAYOUT:
        quotient, remainder = integer_divmod(left_value, right_value)
        check_integer(quotient, kind)
        return VBCInteger(quotient if op == "/" else remainder, kind)
    if op == "%":
        raise TypeError("取模运算的操作数必须是整数类型")
    if op == "/" and right_value == 0:
        raise ZeroDivisionError("除零错误")
    value = _BINARY_OPERATORS[op](left_value, right_value)
    return VBCInteger(value, kind) if kind in INTEGER_LAYOUT else VBCFloat(value, kind)


def numeric_unary(op: str, value):
    """提升一元运算的操作数，并按提升后的类型校验结果。"""
    from verbose_c.object.t_float import VBCFloat
    from verbose_c.object.t_integer import VBCInteger

    kind = common_numeric_kind(value._object_type, value._object_type)
    converted = cast_numeric(value, kind)
    result = -converted.value if op == "-" else converted.value
    return VBCInteger(result, kind) if kind in INTEGER_LAYOUT else VBCFloat(result, kind)


def numeric_compare(op: str, left, right):
    """数值比较先执行与算术运算相同的类型转换。"""
    from verbose_c.object.t_bool import VBCBool

    if getattr(right, "_object_type", None) not in {*NUMERIC_RANKS, VBCObjectType.BOOL}:
        if op in ("==", "!="):
            return VBCBool(op == "!=")
        raise TypeError(f"类型 '{type(right).__name__}' 不能参与数值比较")
    kind = common_numeric_kind(left._object_type, right._object_type)
    return VBCBool(_COMPARISONS[op](cast_numeric(left, kind).value, cast_numeric(right, kind).value))

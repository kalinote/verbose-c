import os
import operator
import re

from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.lexer import Lexer
from verbose_c.parser.lexer.token import Token
from verbose_c.preprocessor.builtin_macros import DYNAMIC_PREDEFINED, make_number_token

_INSIGNIFICANT = frozenset({TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE})
_MASK = (1 << 64) - 1
_SIGNED_MAX = (1 << 63) - 1
_PRECEDENCE = {
    ",": 1, "||": 3, "&&": 4, "|": 5, "^": 6, "&": 7,
    "==": 8, "!=": 8, "<": 9, "<=": 9, ">": 9, ">=": 9,
    "<<": 10, ">>": 10, "+": 11, "-": 11, "*": 12, "/": 12, "%": 12,
}
_OPERATIONS = {
    "+": operator.add, "-": operator.sub, "*": operator.mul,
    "&": operator.and_, "|": operator.or_, "^": operator.xor,
    "==": operator.eq, "!=": operator.ne, "<": operator.lt,
    "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}


def _integer_value(value: int, unsigned: bool) -> tuple[int, bool]:
    """规范为 64 位预处理整数，无符号回绕，有符号越界报错。"""
    if unsigned:
        return value & _MASK, True
    if not -_SIGNED_MAX - 1 <= value <= _SIGNED_MAX:
        raise ValueError("预处理有符号整数溢出（64 位）")
    return value, False


def _character_value(text: str) -> tuple[int, bool]:
    """解释 C 字符常量及转义，使用 UTF-8 执行字符集。

    Args:
        text: 普通字符常量或 L/u/U 前缀字符常量。

    Returns:
        数值与无符号标记；普通多字符常量按大端字节组合为有符号 32 位值。
    """
    prefix = text[0] if text[0] != "'" else ""
    body = text[len(prefix) + 1:-1]
    values = []
    pos = 0
    escapes = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11,
               "\\": 92, "'": 39, '"': 34, "?": 63}
    while pos < len(body):
        char = body[pos]
        pos += 1
        if char != "\\":
            values.extend([ord(char)] if prefix else char.encode("utf-8"))
            continue
        if pos >= len(body):
            raise ValueError("字符常量转义不完整")
        char = body[pos]
        pos += 1
        if char in escapes:
            values.append(escapes[char])
        elif char in "01234567":
            digits = char
            while pos < len(body) and len(digits) < 3 and body[pos] in "01234567":
                digits += body[pos]
                pos += 1
            values.append(int(digits, 8))
        elif char in "xuU":
            start = pos
            limit = {"u": 4, "U": 8}.get(char)
            while pos < len(body) and body[pos] in "0123456789abcdefABCDEF" and (limit is None or pos - start < limit):
                pos += 1
            if start == pos or (limit is not None and pos - start != limit):
                raise ValueError("字符常量中的十六进制或 Unicode 转义不完整")
            value = int(body[start:pos], 16)
            if char in "uU":
                if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF or value < 0xA0 and value not in (0x24, 0x40, 0x60):
                    raise ValueError("字符常量中的 Unicode 码点无效")
                values.extend([value] if prefix else chr(value).encode("utf-8"))
            else:
                values.append(value)
        else:
            raise ValueError(f"字符常量包含非法转义 \\{char}")
    if not values:
        raise ValueError("空字符常量")
    if prefix:
        if len(values) != 1 or values[0] > {"u": 0xFFFF, "U": 0xFFFFFFFF, "L": 0x7FFFFFFF}[prefix]:
            raise ValueError("宽字符常量必须包含一个有效字符")
        return values[0], prefix in "uU"
    if len(values) > 4 or any(value > 255 for value in values):
        raise ValueError("普通字符常量超出 32 位或包含非字节转义")
    value = 0
    for byte in values:
        value = (value << 8) | byte
    if len(values) == 1 and value >= 128:
        value -= 256
    elif value >= 1 << 31:
        value -= 1 << 32
    return value, False


def _substitute_defined(tokens: list[Token], macro_register: dict, site: Token) -> list[Token]:
    """将 defined(MACRO) / defined MACRO 替换为 0/1 数字 token。"""
    output: list[Token] = []
    index = 0
    while index < len(tokens):
        tok = tokens[index]
        if tok.type == TokenType.END:
            break
        if tok.type in _INSIGNIFICANT:
            index += 1
            continue
        if tok.type == TokenType.NAME and tok.value == "defined":
            index += 1
            while index < len(tokens) and tokens[index].type in _INSIGNIFICANT:
                index += 1
            if index >= len(tokens):
                raise ValueError("defined 后缺少宏名")
            macro_name: str | None = None
            if tokens[index].type == TokenType.LPAREN:
                index += 1
                while index < len(tokens) and tokens[index].type in _INSIGNIFICANT:
                    index += 1
                if index >= len(tokens) or tokens[index].type != TokenType.NAME:
                    raise ValueError("defined() 中缺少宏名")
                macro_name = tokens[index].value
                index += 1
                while index < len(tokens) and tokens[index].type in _INSIGNIFICANT:
                    index += 1
                if index >= len(tokens) or tokens[index].type != TokenType.RPAREN:
                    raise ValueError("defined() 缺少右括号")
                index += 1
            elif tokens[index].type == TokenType.NAME:
                macro_name = tokens[index].value
                index += 1
            else:
                raise ValueError("defined 后缺少宏名")
            value = "1" if macro_name in macro_register or macro_name in DYNAMIC_PREDEFINED else "0"
            output.append(make_number_token(value, site))
            continue
        output.append(tok)
        index += 1
    return output


def _evaluate_expr_tokens(tokens: list[Token]) -> bool:
    """按 C 优先级解析整数条件表达式，短路仅跳过求值而不跳过语法检查。"""
    significant = [t for t in tokens if t.type not in _INSIGNIFICANT and t.type != TokenType.END]
    if not significant:
        raise ValueError("空条件表达式")
    pos = 0

    def parse_unary(evaluate: bool) -> tuple[int, bool]:
        """解析前缀运算、括号、整数和字符常量，保留未求值分支的类型。"""
        nonlocal pos
        if pos >= len(significant):
            raise ValueError("条件表达式不完整")
        tok = significant[pos]
        pos += 1
        if tok.value in ("+", "-", "!", "~"):
            value, unsigned = parse_unary(evaluate)
            if tok.value == "!":
                return int(not value) if evaluate else 0, False
            if not evaluate:
                return 0, unsigned
            value = value if tok.value == "+" else -value if tok.value == "-" else ~value
            return _integer_value(value, unsigned)
        if tok.type == TokenType.LPAREN:
            value = parse_expression(1, evaluate)
            if pos >= len(significant) or significant[pos].type != TokenType.RPAREN:
                raise ValueError("条件表达式缺少右括号")
            pos += 1
            return value
        if tok.type == TokenType.NUMBER:
            match = re.fullmatch(r"(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)([uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?", tok.value)
            if not match:
                raise ValueError(f"无效的预处理整数字面量: {tok.value}")
            digits, suffix = match.groups()
            base = 16 if digits.lower().startswith("0x") else 8 if digits.startswith("0") else 10
            value = int(digits, base)
            unsigned = "u" in (suffix or "").lower() or (base != 10 and value > _SIGNED_MAX)
            if value > _MASK or (value > _SIGNED_MAX and not unsigned):
                raise ValueError(f"整数字面量超出 64 位范围: {tok.value}")
            return value, unsigned
        if tok.type == TokenType.STRING and (tok.value.startswith("'") or tok.value[:2] in ("L'", "u'", "U'")):
            return _character_value(tok.value)
        if tok.type == TokenType.NAME:
            return 0, False
        raise ValueError(f"无法求值: {tok.value}")

    def parse_expression(minimum: int, evaluate: bool) -> tuple[int, bool]:
        """按优先级递归求值，逻辑和条件运算只执行选中的分支。

        Args:
            minimum: 当前层允许的最低运算符优先级。
            evaluate: 是否执行运算；关闭时仍解析全部语法和结果符号性。

        Returns:
            当前表达式的整数值和无符号标记。
        """
        nonlocal pos
        left, unsigned = parse_unary(evaluate)
        while pos < len(significant):
            op = significant[pos].value
            if op == "?" and minimum <= 2:
                pos += 1
                yes, yes_unsigned = parse_expression(1, evaluate and left != 0)
                if pos >= len(significant) or significant[pos].value != ":":
                    raise ValueError("条件运算符缺少 ':'")
                pos += 1
                no, no_unsigned = parse_expression(2, evaluate and left == 0)
                left = yes if left else no
                unsigned = yes_unsigned or no_unsigned
                left, unsigned = _integer_value(left if evaluate else 0, unsigned)
                continue
            precedence = _PRECEDENCE.get(op, 0)
            if precedence < minimum:
                break
            pos += 1
            active = evaluate and not (op == "&&" and left == 0 or op == "||" and left != 0)
            right, right_unsigned = parse_expression(precedence + 1, active)
            if op in ("&&", "||"):
                left = int(bool(left) and bool(right)) if op == "&&" else int(bool(left) or bool(right))
                unsigned = False
                continue
            if op == ",":
                if evaluate:
                    raise ValueError("预处理常量表达式不能求值逗号运算符")
                left, unsigned = 0, right_unsigned
                continue
            result_unsigned = unsigned if op in ("<<", ">>") else unsigned or right_unsigned
            if result_unsigned and op not in ("<<", ">>"):
                left, right = left & _MASK, right & _MASK
            comparison = op in ("==", "!=", "<", "<=", ">", ">=")
            if not evaluate:
                left, unsigned = 0, False if comparison else result_unsigned
                continue
            if op in ("/", "%"):
                if right == 0:
                    raise ValueError("预处理条件表达式除零")
                quotient = abs(left) // abs(right)
                if (left < 0) != (right < 0):
                    quotient = -quotient
                _integer_value(quotient, result_unsigned)
                value = quotient if op == "/" else left - quotient * right
            elif op in ("<<", ">>"):
                if not 0 <= right < 64:
                    raise ValueError("预处理移位数量必须在 0 到 63 之间")
                if op == "<<" and left < 0 and not unsigned:
                    raise ValueError("预处理有符号负数不能左移")
                value = left << right if op == "<<" else left >> right
            else:
                value = int(_OPERATIONS[op](left, right))
            left, unsigned = _integer_value(value, False if comparison else result_unsigned)
        return left, unsigned

    result, _ = parse_expression(2, True)
    if pos < len(significant):
        raise ValueError(f"无法解析的 token: {significant[pos].value}")
    return result != 0


def eval_preprocessor_expr(preprocessor, expr_text: str, site: Token) -> bool:
    """求值 #if / #elif 条件表达式。"""
    path = os.path.abspath(site.path) if site.path else ""
    try:
        raw_tokens = [
            tok for tok in Lexer(path, expr_text, preprocessor_mode=True).tokenize()
            if tok.type != TokenType.END
        ]
        for token in raw_tokens:
            token.line = (site.line or 1) + (token.line or 1) - 1
        defined_tokens = _substitute_defined(raw_tokens, preprocessor.macro_register, site)
        expanded = preprocessor._rescan(defined_tokens, set())
        return _evaluate_expr_tokens(expanded)
    except (ValueError, SyntaxError, RecursionError) as exc:
        preprocessor._error(f"预处理错误：#if 表达式求值失败: {exc}", site)

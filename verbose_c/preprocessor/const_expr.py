import os

from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.lexer import Lexer
from verbose_c.parser.lexer.token import Token
from verbose_c.preprocessor.builtin_macros import make_number_token

_INSIGNIFICANT = frozenset({TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE})


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
            value = "1" if macro_name in macro_register else "0"
            output.append(make_number_token(value, site))
            continue
        output.append(tok)
        index += 1
    return output


def _evaluate_expr_tokens(tokens: list[Token]) -> bool:
    """MVP 预处理常量表达式求值：!、&&、||、括号、整数。"""
    significant = [t for t in tokens if t.type not in _INSIGNIFICANT and t.type != TokenType.END]
    if not significant:
        raise ValueError("空条件表达式")
    pos = 0

    def parse_or() -> bool:
        nonlocal pos
        value = parse_and()
        while pos < len(significant) and significant[pos].type == TokenType.OR:
            pos += 1
            value = value or parse_and()
        return value

    def parse_and() -> bool:
        nonlocal pos
        value = parse_unary()
        while pos < len(significant) and significant[pos].type == TokenType.AND:
            pos += 1
            value = value and parse_unary()
        return value

    def parse_unary() -> bool:
        nonlocal pos
        if pos < len(significant) and significant[pos].type == TokenType.NOT:
            pos += 1
            return not parse_unary()
        return parse_primary()

    def parse_primary() -> bool:
        nonlocal pos
        if pos >= len(significant):
            raise ValueError("条件表达式不完整")
        tok = significant[pos]
        if tok.type == TokenType.LPAREN:
            pos += 1
            value = parse_or()
            if pos >= len(significant) or significant[pos].type != TokenType.RPAREN:
                raise ValueError("条件表达式缺少右括号")
            pos += 1
            return value
        if tok.type == TokenType.NUMBER:
            pos += 1
            return int(tok.value, 0) != 0
        raise ValueError(f"无法求值: {tok.value}")

    result = parse_or()
    if pos < len(significant):
        raise ValueError(f"无法解析的 token: {significant[pos].value}")
    return result


def eval_preprocessor_expr(preprocessor, expr_text: str, site: Token) -> bool:
    """求值 #if / #elif 条件表达式。"""
    path = os.path.abspath(site.path) if site.path else ""
    try:
        raw_tokens = [
            tok for tok in Lexer(path, expr_text).tokenize()
            if tok.type != TokenType.END
        ]
        defined_tokens = _substitute_defined(raw_tokens, preprocessor.macro_register, site)
        expanded = preprocessor._rescan(defined_tokens, set())
        return _evaluate_expr_tokens(expanded)
    except ValueError as exc:
        preprocessor._error(f"预处理错误：#if 表达式求值失败: {exc}", site)

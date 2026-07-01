import os
from datetime import datetime

from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.token import Token

DYNAMIC_PREDEFINED = frozenset({"__FILE__", "__LINE__"})

STATIC_PREDEFINED_BASE: dict[str, str] = {
    "__STDC__": "1",
    "__STDC_VERSION__": "201710",
    "__STDC_HOSTED__": "1",
    "__STDC_UTF_16__": "1",
    "__STDC_UTF_32__": "1",
}

RESERVED_PREDEFINED = frozenset({"__STDC__", "__STDC_HOSTED__", "__STDC_VERSION__"})


def format_c_date(dt: datetime) -> str:
    """生成 C __DATE__ 格式，如 Jul  1 2026。"""
    return f'{dt.strftime("%b")} {dt.day:2d} {dt.year}'


def format_c_time(dt: datetime) -> str:
    """生成 C __TIME__ 格式，如 09:30:45。"""
    return dt.strftime("%H:%M:%S")


def build_static_predefined(compile_time: datetime) -> dict[str, str]:
    """根据编译时刻生成含 __DATE__/__TIME__ 的静态预定义宏表。"""
    macros = dict(STATIC_PREDEFINED_BASE)
    macros["__DATE__"] = f'"{format_c_date(compile_time)}"'
    macros["__TIME__"] = f'"{format_c_time(compile_time)}"'
    return macros


def escape_c_string(value: str) -> str:
    """转义 C 字符串字面量中的反斜杠与双引号。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def make_string_token(literal: str, site: Token) -> Token:
    """构造 STRING token，位置信息继承自 site。"""
    path = os.path.abspath(site.path) if site.path else site.path
    return Token(
        TokenType.STRING, literal,
        column=site.column, line=site.line, path=path,
        is_keyword=False,
    )


def make_number_token(value: str, site: Token) -> Token:
    """构造 NUMBER token，位置信息继承自 site。"""
    path = os.path.abspath(site.path) if site.path else site.path
    return Token(
        TokenType.NUMBER, value,
        column=site.column, line=site.line, path=path,
        is_keyword=False,
    )


def expand_predefined(name: str, site: Token) -> Token:
    """展开动态预定义宏 __FILE__ / __LINE__。"""
    if name == "__FILE__":
        path = os.path.abspath(site.path) if site.path else ""
        return make_string_token(f'"{escape_c_string(path)}"', site)
    if name == "__LINE__":
        line = site.line if site.line is not None else 0
        return make_number_token(str(line), site)
    raise ValueError(f"未知动态预定义宏: {name}")

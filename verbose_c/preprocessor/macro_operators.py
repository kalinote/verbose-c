from enum import Enum

from verbose_c.error import VBCCompileError
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.lexer import Lexer
from verbose_c.parser.lexer.token import Token
from verbose_c.preprocessor.builtin_macros import escape_c_string, make_string_token
from verbose_c.preprocessor.macro_definition import MacroDefinitionType

_INSIGNIFICANT = frozenset({TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE})


class ParamUsage(Enum):
    NORMAL = "normal"
    STRINGIFY = "stringify"
    CONCAT = "concat"


def _clone_token(token: Token) -> Token:
    return Token(
        token.type, token.value,
        column=token.column, line=token.line, path=token.path,
        is_keyword=token.is_keyword,
    )


def _strip_insignificant(tokens: list[Token]) -> list[Token]:
    start = 0
    end = len(tokens)
    while start < end and tokens[start].type in _INSIGNIFICANT:
        start += 1
    while end > start and tokens[end - 1].type in _INSIGNIFICANT:
        end -= 1
    return [_clone_token(t) for t in tokens[start:end]]


def _significant_indices(tokens: list[Token]) -> list[int]:
    return [i for i, tok in enumerate(tokens) if tok.type not in _INSIGNIFICANT]


def _raise_define_error(message: str, token: Token) -> None:
    raise VBCCompileError(message, line=token.line, filepath=token.path)


def validate_macro_body(
    macro_type: MacroDefinitionType,
    parameters: list[str],
    body_tokens: list[Token],
    site: Token,
) -> None:
    """校验宏体中 # / ## 的合法性。"""
    param_set = set(parameters)
    has_pp_op = any(
        tok.type in (TokenType.PP_STRINGIFY, TokenType.PP_CONCAT)
        for tok in body_tokens
    )
    if macro_type == MacroDefinitionType.OBJECT and has_pp_op:
        _raise_define_error("预处理错误：对象宏不能使用 # 或 ## 运算符", site)

    if macro_type != MacroDefinitionType.FUNCTION:
        return

    sig = _significant_indices(body_tokens)
    for pos, index in enumerate(sig):
        tok = body_tokens[index]
        if tok.type == TokenType.PP_STRINGIFY:
            if pos + 1 >= len(sig):
                _raise_define_error("预处理错误：# 后缺少形参名", tok)
            next_tok = body_tokens[sig[pos + 1]]
            if next_tok.type != TokenType.NAME or next_tok.value not in param_set:
                _raise_define_error("预处理错误：# 后必须是宏形参名", tok)
        elif tok.type == TokenType.PP_CONCAT:
            if pos == 0 or pos + 1 >= len(sig):
                _raise_define_error("预处理错误：## 两侧必须有预处理 token", tok)


def classify_parameter_usage(
    replacement: list[Token],
    parameters: list[str],
) -> dict[str, ParamUsage]:
    """分析宏体中各形参的用法类别。"""
    param_set = set(parameters)
    usage: dict[str, ParamUsage] = {p: ParamUsage.NORMAL for p in parameters}
    sig = _significant_indices(replacement)

    for pos, index in enumerate(sig):
        tok = replacement[index]
        if tok.type == TokenType.PP_STRINGIFY and pos + 1 < len(sig):
            name = replacement[sig[pos + 1]].value
            if name in param_set:
                usage[name] = ParamUsage.STRINGIFY
        elif tok.type == TokenType.NAME and tok.value in param_set:
            if usage[tok.value] == ParamUsage.STRINGIFY:
                continue
            prev_tok = replacement[sig[pos - 1]] if pos > 0 else None
            next_tok = replacement[sig[pos + 1]] if pos + 1 < len(sig) else None
            if (
                (prev_tok is not None and prev_tok.type == TokenType.PP_CONCAT)
                or (next_tok is not None and next_tok.type == TokenType.PP_CONCAT)
            ):
                usage[tok.value] = ParamUsage.CONCAT

    return usage


def prepare_macro_arguments(
    param_map: dict[str, list[Token]],
    usage: dict[str, ParamUsage],
    preprocessor,
    hiding: set[str],
    depth: int,
) -> dict[str, list[Token]]:
    """按形参用法决定是否预展开实参。"""
    prepared: dict[str, list[Token]] = {}
    for param, raw_tokens in param_map.items():
        if usage.get(param, ParamUsage.NORMAL) in (ParamUsage.STRINGIFY, ParamUsage.CONCAT):
            prepared[param] = _strip_insignificant(raw_tokens)
        else:
            prepared[param] = preprocessor._rescan(raw_tokens, hiding, depth)
    return prepared


def token_spelling(tokens: list[Token]) -> str:
    """将 token 序列转为预处理拼写字符串。"""
    significant = [t for t in tokens if t.type not in _INSIGNIFICANT and t.type != TokenType.END]
    if not significant:
        return ""
    parts: list[str] = []
    for tok in significant:
        if tok.type in (TokenType.STRING, TokenType.NAME, TokenType.NUMBER):
            parts.append(tok.value)
        else:
            parts.append(tok.type.literal)
    return " ".join(parts)


def stringify_tokens(tokens: list[Token], site: Token) -> Token:
    """将实参 token 序列字符串化为 STRING token。"""
    stripped = _strip_insignificant(tokens)
    if not stripped:
        return make_string_token('""', site)
    return make_string_token(f'"{escape_c_string(token_spelling(stripped))}"', site)


def _collect_concat_operand(
    tokens: list[Token], concat_index: int, *, left: bool,
) -> tuple[list[Token], list[int]]:
    """从 ## 一侧收集拼接操作数。"""
    operand: list[Token] = []
    consumed: list[int] = []
    step = -1 if left else 1
    pos = concat_index + step
    while 0 <= pos < len(tokens):
        tok = tokens[pos]
        if tok.type in _INSIGNIFICANT:
            consumed.append(pos)
            pos += step
            continue
        if tok.type == TokenType.PP_CONCAT:
            break
        if left:
            operand.insert(0, tok)
        else:
            operand.append(tok)
        consumed.append(pos)
        pos += step
    return operand, consumed


def substitute_function_macro(
    replacement: list[Token],
    parameters: list[str],
    prepared_args: dict[str, list[Token]],
    site: Token,
) -> list[Token]:
    """替换函数宏体中的形参并处理 # / ##。"""
    param_set = set(parameters)
    out: list[Token] = []
    index = 0
    while index < len(replacement):
        tok = replacement[index]
        if tok.type == TokenType.PP_STRINGIFY:
            next_index = index + 1
            while next_index < len(replacement) and replacement[next_index].type in _INSIGNIFICANT:
                next_index += 1
            if next_index >= len(replacement):
                _raise_define_error("预处理错误：# 后缺少形参名", tok)
            param_tok = replacement[next_index]
            if param_tok.type != TokenType.NAME or param_tok.value not in param_set:
                _raise_define_error("预处理错误：# 后必须是宏形参名", tok)
            out.append(stringify_tokens(prepared_args[param_tok.value], site))
            index = next_index + 1
            continue
        if tok.type == TokenType.NAME and tok.value in param_set:
            out.extend(_clone_token(t) for t in prepared_args[tok.value])
            index += 1
            continue
        out.append(_clone_token(tok))
        index += 1

    current = out
    while True:
        concat_index = next(
            (i for i, tok in enumerate(current) if tok.type == TokenType.PP_CONCAT),
            None,
        )
        if concat_index is None:
            break
        left, left_consumed = _collect_concat_operand(current, concat_index, left=True)
        right, right_consumed = _collect_concat_operand(current, concat_index, left=False)
        spelling = token_spelling(left) + token_spelling(right)
        if spelling:
            try:
                raw = [
                    t for t in Lexer("<paste>", spelling, macro_body=True).tokenize()
                    if t.type not in _INSIGNIFICANT and t.type != TokenType.END
                ]
            except SyntaxError as exc:
                raise VBCCompileError(
                    f"预处理错误：## 粘贴结果无法构成合法预处理 token: {exc}",
                    line=site.line,
                    filepath=site.path,
                ) from exc
            if not raw:
                raise VBCCompileError(
                    "预处理错误：## 粘贴结果无法构成合法预处理 token",
                    line=site.line,
                    filepath=site.path,
                )
            pasted = [
                Token(t.type, t.value, column=site.column, line=site.line, path=site.path, is_keyword=t.is_keyword)
                for t in raw
            ]
        else:
            pasted = []
        remove_indices = set(left_consumed + right_consumed + [concat_index])
        current = [tok for i, tok in enumerate(current) if i not in remove_indices]
        insert_at = min(left_consumed) if left_consumed else concat_index
        for offset, tok in enumerate(pasted):
            current.insert(insert_at + offset, tok)

    leaked = [t for t in current if t.type in (TokenType.PP_STRINGIFY, TokenType.PP_CONCAT)]
    if leaked:
        _raise_define_error("预处理错误：宏展开后残留未处理的 # 或 ## 运算符", leaked[0])
    return current

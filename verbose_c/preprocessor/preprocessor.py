import os
import re

from verbose_c.fs.source_manager import SourceManager
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.lexer import Lexer
from verbose_c.parser.lexer.token import Token
from verbose_c.preprocessor.macro_definition import MacroDefinition, MacroDefinitionType

DEFINE_PATTERN = re.compile(
    r'^\s*#define\s+([a-zA-Z_][a-zA-Z0-9_]*)(\([^\)]*\))?\s+(.*)',
    re.DOTALL,
)
INCLUDE_QUOTED_PATTERN = re.compile(r'^\s*#include\s+"([^"]+)"')
INCLUDE_ANGLE_PATTERN = re.compile(r'^\s*#include\s+<([^>]+)>')

_INSIGNIFICANT = frozenset({TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE})


class Preprocessor:
    """源代码预处理器，负责处理宏指令，如 #include 和 #define。"""

    MAX_EXPANSION_DEPTH = 20

    def __init__(self, source_manager: SourceManager, show_warnings: bool = True):
        self.source_manager = source_manager
        self.show_warnings = show_warnings
        self.macro_register: dict[str, MacroDefinition] = {}
        self._included_files = set()

    def _token_location(self, token: Token) -> str:
        """格式化 token 所在源文件与行号。"""
        path = os.path.abspath(token.path) if token.path else ""
        parts: list[str] = []
        if token.line is not None:
            parts.append(f"位于 {token.line} 行")
        if path:
            parts.append(f"在 {path} 文件")
        return "，".join(parts)

    def _warn(self, message: str, token: Token | None = None) -> None:
        """输出带可选位置信息的预处理警告。"""
        if not self.show_warnings:
            return
        location = self._token_location(token) if token else ""
        if location:
            print(f"警告: {message}，{location}")
        else:
            print(f"警告: {message}")

    def _clone_token(self, token: Token) -> Token:
        """浅拷贝单个 Token。"""
        path = os.path.abspath(token.path) if token.path else token.path
        return Token(
            token.type, token.value,
            column=token.column, line=token.line, path=path,
            is_keyword=token.is_keyword,
        )

    def _parse_function_args(self, tokens: list[Token], lparen_index: int) -> tuple[list[list[Token]], int]:
        """从 LPAREN 起解析函数宏实参，返回实参 token 列表及消费长度。"""
        args: list[list[Token]] = []
        current_arg: list[Token] = []
        paren_level = 0
        index = lparen_index
        while index < len(tokens):
            tok = tokens[index]
            if tok.type == TokenType.LPAREN:
                paren_level += 1
                if paren_level > 1:
                    current_arg.append(tok)
            elif tok.type == TokenType.RPAREN:
                paren_level -= 1
                if paren_level == 0:
                    args.append(current_arg)
                    return args, index - lparen_index + 1
                current_arg.append(tok)
            elif tok.type == TokenType.COMMA and paren_level == 1:
                args.append(current_arg)
                current_arg = []
            else:
                current_arg.append(tok)
            index += 1
        return args, index - lparen_index

    def _expand_at(
        self,
        tokens: list[Token],
        index: int,
        hiding: set[str],
        depth: int = 0,
    ) -> tuple[list[Token], int]:
        """在 index 处展开宏，返回展开 token 及从 index 起消费的长度。"""
        if depth > self.MAX_EXPANSION_DEPTH:
            self._warn(f"宏展开超过最大深度 {self.MAX_EXPANSION_DEPTH}", tokens[index])
            return [self._clone_token(tokens[index])], 1

        name = tokens[index].value
        macro = self.macro_register[name]
        new_hiding = hiding | {name}

        if macro.type == MacroDefinitionType.FUNCTION:
            next_index = index + 1
            while next_index < len(tokens) and tokens[next_index].type in _INSIGNIFICANT:
                next_index += 1
            if next_index >= len(tokens) or tokens[next_index].type != TokenType.LPAREN:
                return [self._clone_token(tokens[index])], 1

            args, arg_span = self._parse_function_args(tokens, next_index)
            if len(args) != len(macro.parameters):
                return [self._clone_token(tokens[index])], 1

            param_map = dict(zip(macro.parameters, args))
            substituted: list[Token] = []
            for tok in macro.replacement:
                if tok.type == TokenType.NAME and tok.value in param_map:
                    substituted.extend(self._clone_token(t) for t in param_map[tok.value])
                else:
                    substituted.append(self._clone_token(tok))

            consumed = next_index - index + arg_span
            return self._rescan(substituted, new_hiding, depth + 1), consumed

        replacement = [self._clone_token(t) for t in macro.replacement]
        return self._rescan(replacement, new_hiding, depth + 1), 1

    def _consume_token(
        self,
        tokens: list[Token],
        index: int,
        hiding: set[str],
        depth: int = 0,
    ) -> tuple[list[Token], int]:
        """处理单个 token：尝试宏展开，否则原样输出。"""
        tok = tokens[index]
        if (
            tok.type == TokenType.NAME
            and tok.value in self.macro_register
            and tok.value not in hiding
        ):
            return self._expand_at(tokens, index, hiding, depth)
        return [self._clone_token(tok)], 1

    def _rescan(self, tokens: list[Token], hiding: set[str], depth: int = 0) -> list[Token]:
        """对 token 序列 rescan 并展开其中的宏。"""
        output: list[Token] = []
        index = 0
        while index < len(tokens):
            if tokens[index].type == TokenType.END:
                break
            expanded, consumed = self._consume_token(tokens, index, hiding, depth)
            output.extend(expanded)
            index += consumed
        return output

    def _handle_define(self, token: Token) -> None:
        """解析 #define 并注册到 macro_register。"""
        define_match = DEFINE_PATTERN.match(token.value)
        if not define_match:
            return

        name = define_match.group(1)
        params_str = define_match.group(2)
        raw_body = define_match.group(3).strip()

        lines = raw_body.splitlines()
        body_parts: list[str] = []
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index].strip()
            while line.endswith('\\') and line_index + 1 < len(lines):
                line = line[:-1].rstrip() + lines[line_index + 1].strip()
                line_index += 1
            if line:
                body_parts.append(line)
            line_index += 1
        body = ' '.join(body_parts)

        if name in self.macro_register:
            existing = self.macro_register[name]
            prev_parts: list[str] = []
            if existing.line is not None:
                prev_parts.append(f"位于 {existing.line} 行")
            if existing.source_file:
                prev_parts.append(f"在 {existing.source_file} 文件")
            prev_loc = "，".join(prev_parts)
            cur_loc = self._token_location(token)
            if prev_loc and cur_loc:
                self._warn(f"宏定义 {name} 已存在，{prev_loc}；当前定义{cur_loc}")
            elif prev_loc:
                self._warn(f"宏定义 {name} 已存在，{prev_loc}")
            else:
                self._warn(f"宏定义 {name} 已存在", token)

        macro_type = MacroDefinitionType.FUNCTION if params_str else MacroDefinitionType.OBJECT
        params = [p.strip() for p in params_str.strip()[1:-1].split(",") if p.strip()] if params_str else []
        body_tokens = [
            tok for tok in Lexer(os.path.abspath(token.path or ""), body).tokenize()
            if tok.type != TokenType.END
        ]
        self.macro_register[name] = MacroDefinition(
            macro_type,
            params,
            body_tokens,
            source_file=os.path.abspath(token.path or ""),
            line=token.line,
            column=token.column,
        )

    def _handle_include(self, token: Token) -> list[Token]:
        """处理 #include "..." 并返回展开后的 token 列表。"""
        quoted_match = INCLUDE_QUOTED_PATTERN.match(token.value)
        if not quoted_match:
            if INCLUDE_ANGLE_PATTERN.match(token.value):
                self._warn("暂不支持 #include <...> 形式", token)
            return []

        filename = quoted_match.group(1)
        abs_path = self.source_manager.resolve_include(filename, token.path or "")

        if abs_path in self._included_files:
            self._warn(f"检测到循环包含 '{abs_path}'，已跳过", token)
            return []

        if not self.source_manager.exists(abs_path):
            self._warn(f"#include 文件未找到 '{abs_path}'", token)
            return []

        self._included_files.add(abs_path)
        try:
            content = self.source_manager.read(abs_path)
            included_tokens = Lexer(abs_path, content).tokenize()
            processed = self.process_tokens(included_tokens)
            return [t for t in processed if t.type != TokenType.END]
        finally:
            self._included_files.discard(abs_path)

    def process_tokens(self, tokens: list[Token]) -> list[Token]:
        """处理 token 序列：注册 define、展开 include 与宏。"""
        output: list[Token] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]

            if token.type == TokenType.END:
                output.append(token)
                break

            if token.type == TokenType.MACRO_CODE:
                if DEFINE_PATTERN.match(token.value):
                    self._handle_define(token)
                elif INCLUDE_QUOTED_PATTERN.match(token.value) or INCLUDE_ANGLE_PATTERN.match(token.value):
                    output.extend(self._handle_include(token))
                elif self.show_warnings:
                    self._warn(f"未识别的预处理指令: {token.value}", token)
                index += 1
                continue

            expanded, consumed = self._consume_token(tokens, index, set())
            output.extend(expanded)
            index += consumed

        return output

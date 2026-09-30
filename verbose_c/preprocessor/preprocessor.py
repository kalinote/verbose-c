import os
import re
from dataclasses import dataclass
from datetime import datetime

from verbose_c.error import DiagnosticEntry, DiagnosticReport, VBCCompileError
from verbose_c.fs.source_manager import SourceManager
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.lexer import Lexer
from verbose_c.parser.lexer.token import Token
from verbose_c.preprocessor.builtin_macros import (
    DYNAMIC_PREDEFINED,
    RESERVED_PREDEFINED,
    build_static_predefined,
    expand_predefined,
)
from verbose_c.preprocessor.const_expr import eval_preprocessor_expr
from verbose_c.preprocessor.macro_definition import MacroDefinition, MacroDefinitionType
from verbose_c.preprocessor.macro_operators import (
    classify_parameter_usage,
    prepare_macro_arguments,
    substitute_function_macro,
    validate_macro_body,
)

DEFINE_PATTERN = re.compile(
    r'^\s*#define\s+([a-zA-Z_][a-zA-Z0-9_]*)(\([^\)]*\))?(?:\s+(.*))?$',
    re.DOTALL,
)
IF_PATTERN = re.compile(r'^\s*#if\b(.*)', re.DOTALL)
ELIF_PATTERN = re.compile(r'^\s*#elif\b(.*)', re.DOTALL)
IFDEF_PATTERN = re.compile(r'^\s*#ifdef\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$')
IFNDEF_PATTERN = re.compile(r'^\s*#ifndef\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$')
ELSE_PATTERN = re.compile(r'^\s*#else\s*$')
ENDIF_PATTERN = re.compile(r'^\s*#endif\s*$')

_INSIGNIFICANT = frozenset({TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE})


@dataclass
class _CondFrame:
    opening_token: Token
    parent_active: bool
    branch_taken: bool
    self_active: bool
    seen_else: bool = False


class Preprocessor:
    """源代码预处理器，负责处理宏指令，如 #include 和 #define。"""

    MAX_EXPANSION_DEPTH = 20
    MAX_INCLUDE_DEPTH = 64

    def __init__(
        self,
        source_manager: SourceManager,
        show_warnings: bool = True,
        compile_time: datetime | None = None,
    ):
        self.source_manager = source_manager
        self.show_warnings = show_warnings
        self.macro_register: dict[str, MacroDefinition] = {}
        self._include_stack: list[str] = []
        self._once_files: set[str] = set()
        self.include_requests: list[dict] = []
        self.diagnostics: list[DiagnosticEntry] = []
        self.dependencies: set[str] = set()
        self._compile_time = compile_time or datetime.now()
        self._cond_stack: list[_CondFrame] = []
        self._register_static_predefined_macros()

    def _register_static_predefined_macros(self) -> None:
        """注册 __DATE__、__STDC__ 等编译期固定的预定义宏。"""
        for name, body in build_static_predefined(self._compile_time).items():
            body_tokens = [
                tok for tok in Lexer("", body).tokenize()
                if tok.type != TokenType.END
            ]
            self.macro_register[name] = MacroDefinition(
                MacroDefinitionType.OBJECT,
                [],
                body_tokens,
                source_file="<builtin>",
                line=None,
                column=None,
            )

    def _is_active(self) -> bool:
        return not self._cond_stack or self._cond_stack[-1].self_active

    def _error(self, message: str, token: Token, code: str = "PP001") -> None:
        """抛出带真实指令位置、稳定错误码和已有警告的编译异常。"""
        entry = DiagnosticEntry(
            message, filepath=token.path, line=token.line, column=token.column,
            source_context=self.source_manager.get_context(token.path or "", token.line), code=code,
        )
        error = VBCCompileError(message, line=token.line, filepath=token.path,
                                report=DiagnosticReport("预处理错误", [entry]))
        error.warning_diagnostics = list(self.diagnostics)
        error.warnings = [item.message for item in self.diagnostics]
        raise error

    def _push_cond_frame(self, token: Token, condition: bool) -> None:
        parent_active = self._is_active()
        self_active = parent_active and condition
        self._cond_stack.append(
            _CondFrame(
                opening_token=token,
                parent_active=parent_active,
                branch_taken=self_active,
                self_active=self_active,
            )
        )

    def _eval_cond_expr(self, expr_raw: str, token: Token) -> bool:
        expr = self._join_directive_continuation(expr_raw.strip())
        return eval_preprocessor_expr(self, expr, token)

    def _handle_conditional_directive(self, token: Token) -> bool:
        """解析条件编译指令并更新条件栈，返回是否已处理。"""
        value = token.value

        ifdef_match = IFDEF_PATTERN.match(value)
        ifndef_match = IFNDEF_PATTERN.match(value)
        if ifdef_match or ifndef_match:
            name = (ifdef_match or ifndef_match).group(1)
            defined = name in self.macro_register or name in DYNAMIC_PREDEFINED
            self._push_cond_frame(token, defined if ifdef_match else not defined)
            return True

        if_match = IF_PATTERN.match(value)
        if if_match:
            self._push_cond_frame(token, self._is_active() and self._eval_cond_expr(if_match.group(1), token))
            return True

        elif_match = ELIF_PATTERN.match(value)
        if elif_match:
            if not self._cond_stack:
                self._error("预处理错误：#elif 缺少匹配的 #if", token)
            frame = self._cond_stack[-1]
            if frame.seen_else:
                self._error("预处理错误：#else 之后不能有 #elif", token)
            if frame.branch_taken or not frame.parent_active:
                frame.self_active = False
            elif self._eval_cond_expr(elif_match.group(1), token):
                frame.branch_taken = True
                frame.self_active = frame.parent_active
            else:
                frame.self_active = False
            return True

        if ELSE_PATTERN.match(value):
            if not self._cond_stack:
                self._error("预处理错误：#else 缺少匹配的 #if", token)
            frame = self._cond_stack[-1]
            if frame.seen_else:
                self._error("预处理错误：重复的 #else", token)
            frame.seen_else = True
            if frame.branch_taken:
                frame.self_active = False
            else:
                frame.branch_taken = True
                frame.self_active = frame.parent_active
            return True

        if ENDIF_PATTERN.match(value):
            if not self._cond_stack:
                self._error("预处理错误：#endif 缺少匹配的 #if", token)
            self._cond_stack.pop()
            return True

        return False

    @staticmethod
    def _join_directive_continuation(text: str) -> str:
        """移除反斜杠续行，保留两侧空白以维持 token 边界。"""
        return re.sub(r"\\\r?\n", "", text)

    def _token_location(self, token: Token) -> str:
        """格式化 token 所在源文件与行号。"""
        path = os.path.abspath(token.path) if token.path else ""
        parts: list[str] = []
        if token.line is not None:
            parts.append(f"位于 {token.line} 行")
        if path:
            parts.append(f"在 {path} 文件")
        return "，".join(parts)

    def _warn(self, message: str, token: Token | None = None, code: str = "PP_WARNING") -> None:
        """只收集结构化警告，显示开关和输出交由编译编排层负责。"""
        self.diagnostics.append(DiagnosticEntry(
            message, filepath=token.path if token else None,
            line=token.line if token else None, column=token.column if token else None,
            source_context=self.source_manager.get_context(token.path or "", token.line) if token else [],
            severity="warning", code=code,
        ))

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
                    if current_arg or args:
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
        site: Token | None = None,
    ) -> tuple[list[Token], int]:
        """在 index 处展开宏，返回展开 token 及从 index 起消费的长度。"""
        if depth > self.MAX_EXPANSION_DEPTH:
            self._warn(f"宏展开超过最大深度 {self.MAX_EXPANSION_DEPTH}", tokens[index])
            return [self._clone_token(tokens[index])], 1

        invocation_site = site or tokens[index]
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
            usage = classify_parameter_usage(macro.replacement, macro.parameters)
            prepared = prepare_macro_arguments(
                param_map, usage, self, hiding, depth,
            )
            substituted = substitute_function_macro(
                macro.replacement,
                macro.parameters,
                prepared,
                invocation_site,
            )

            consumed = next_index - index + arg_span
            return self._rescan(substituted, new_hiding, depth + 1, site=invocation_site), consumed

        replacement = [self._clone_token(t) for t in macro.replacement]
        return self._rescan(replacement, new_hiding, depth + 1, site=invocation_site), 1

    def _consume_token(
        self,
        tokens: list[Token],
        index: int,
        hiding: set[str],
        depth: int = 0,
        site: Token | None = None,
    ) -> tuple[list[Token], int]:
        """处理单个 token：尝试宏展开，否则原样输出。"""
        tok = tokens[index]
        if (
            tok.type == TokenType.NAME
            and tok.value in DYNAMIC_PREDEFINED
            and tok.value not in self.macro_register
            and tok.value not in hiding
        ):
            return [expand_predefined(tok.value, site or tok)], 1
        if (
            tok.type == TokenType.NAME
            and tok.value in self.macro_register
            and tok.value not in hiding
        ):
            return self._expand_at(tokens, index, hiding, depth, site=site)
        return [self._clone_token(tok)], 1

    def _rescan(
        self,
        tokens: list[Token],
        hiding: set[str],
        depth: int = 0,
        site: Token | None = None,
    ) -> list[Token]:
        """对 token 序列 rescan 并展开其中的宏。"""
        output: list[Token] = []
        index = 0
        while index < len(tokens):
            if tokens[index].type == TokenType.END:
                break
            expanded, consumed = self._consume_token(tokens, index, hiding, depth, site=site)
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
        raw_body = define_match.group(3)
        raw_body = raw_body.strip() if raw_body else ""

        body = self._join_directive_continuation(raw_body)

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
                self._warn(f"宏定义 {name} 已存在，{prev_loc}", token, "PP_MACRO_REDEFINED")
            elif prev_loc:
                self._warn(f"宏定义 {name} 已存在，{prev_loc}", token, "PP_MACRO_REDEFINED")
            else:
                self._warn(f"宏定义 {name} 已存在", token, "PP_MACRO_REDEFINED")
            if name in RESERVED_PREDEFINED:
                self._warn(f"不建议重定义标准预定义宏 {name}", token)

        macro_type = MacroDefinitionType.FUNCTION if params_str else MacroDefinitionType.OBJECT
        params = [p.strip() for p in params_str.strip()[1:-1].split(",") if p.strip()] if params_str else []
        try:
            body_tokens = [
                tok for tok in Lexer(os.path.abspath(token.path or ""), body, macro_body=True, preprocessor_mode=True).tokenize()
                if tok.type != TokenType.END
            ]
        except SyntaxError as error:
            self._error(f"宏定义词法错误: {error.msg}", token)
        validate_macro_body(macro_type, params, body_tokens, token)
        self.macro_register[name] = MacroDefinition(
            macro_type,
            params,
            body_tokens,
            source_file=os.path.abspath(token.path or ""),
            line=token.line,
            column=token.column,
        )

    def _handle_include(self, token: Token) -> list[Token]:
        """展开头文件宏并按搜索配置包含文件，保留每次实际解析结果。"""
        argument = re.sub(r"^\s*#include\b", "", token.value).strip()
        try:
            literal = re.fullmatch(r'(?:"([^"\n]+)"|<([^>\n]+)>)\s*(?:(?:/\*.*?\*/|//[^\n]*)\s*)*', argument, re.DOTALL)
            if literal:
                filename = literal.group(1) or literal.group(2)
                angled = literal.group(2) is not None
            else:
                header_tokens = Lexer(token.path, argument, preprocessor_mode=True).tokenize()
                significant = [item for item in self._rescan(header_tokens[:-1], set()) if item.type not in _INSIGNIFICANT]
                if len(significant) == 1 and significant[0].type == TokenType.STRING and significant[0].value.startswith('"'):
                    filename, angled = significant[0].value[1:-1], False
                elif len(significant) >= 3 and significant[0].value == "<" and significant[-1].value == ">":
                    filename, angled = "".join(item.value for item in significant[1:-1]), True
                    if any(item.value in ("<", ">") for item in significant[1:-1]):
                        raise ValueError("头文件名包含多余的尖括号")
                else:
                    raise ValueError("#include 必须指定一个双引号或尖括号头文件名")
            if not filename:
                raise ValueError("#include 头文件名不能为空")
            abs_path = self.source_manager.resolve_include(filename, token.path or "", angled)
        except FileNotFoundError as error:
            self._error(str(error), token, "PP_INCLUDE_NOT_FOUND")
        except (ValueError, SyntaxError) as error:
            self._error(str(error), token, "PP_INCLUDE_SYNTAX")
        self.include_requests.append({"name": filename, "from_path": token.path or "", "angled": angled, "resolved_path": abs_path})
        identity = os.path.normcase(os.path.realpath(abs_path))
        if identity in self._once_files:
            return []
        if len(self._include_stack) >= self.MAX_INCLUDE_DEPTH:
            self._error("include 嵌套过深，可能存在无保护的循环包含: " + " -> ".join([*self._include_stack, abs_path]), token, "PP_INCLUDE_DEPTH")
        self.dependencies.add(os.path.abspath(abs_path))
        self._include_stack.append(abs_path)
        parent_conditions = self._cond_stack
        self._cond_stack = []
        try:
            content = self.source_manager.read(abs_path)
            included_tokens = Lexer(abs_path, content).tokenize(compile_errors=True)
            processed = self.process_tokens(included_tokens)
            return [t for t in processed if t.type != TokenType.END]
        except (OSError, UnicodeError) as error:
            self._error(f"无法读取头文件 '{abs_path}': {error}", token, "PP_INCLUDE_IO")
        finally:
            self._include_stack.pop()
            self._cond_stack = parent_conditions

    def process_tokens(self, tokens: list[Token]) -> list[Token]:
        """处理 token 序列：注册 define、展开 include 与宏。"""
        cond_depth_at_start = len(self._cond_stack)
        output: list[Token] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]

            if token.type == TokenType.END:
                if len(self._cond_stack) > cond_depth_at_start:
                    self._error(
                        "预处理错误：缺少匹配的 #endif",
                        self._cond_stack[cond_depth_at_start].opening_token,
                    )
                output.append(token)
                break

            if token.type == TokenType.MACRO_CODE:
                token = self._clone_token(token)
                token.value = re.sub(r"^\s*#\s*", "#", self._join_directive_continuation(token.value))
                directive = re.match(r"^#([A-Za-z_][A-Za-z_0-9]*)\b", token.value)
                name = directive.group(1) if directive else ""
                if name in ("ifdef", "ifndef", "else", "endif", "undef", "pragma"):
                    token.value = re.sub(r"/\*.*?\*/|//[^\n]*", " ", token.value, flags=re.DOTALL)
                if name in ("if", "ifdef", "ifndef") and not self._is_active():
                    self._push_cond_frame(token, False)
                    index += 1
                    continue
                if not self._handle_conditional_directive(token) and self._is_active():
                    if DEFINE_PATTERN.match(token.value):
                        self._handle_define(token)
                    elif name == "include":
                        output.extend(self._handle_include(token))
                    elif re.fullmatch(r"#pragma\s+once\s*", token.value):
                        self._once_files.add(os.path.normcase(os.path.realpath(token.path)))
                    elif name == "undef":
                        macro_name = token.value[len("#undef"):].strip()
                        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", macro_name):
                            self._error("#undef 后需要一个宏名", token, "PP_DIRECTIVE")
                        if macro_name in RESERVED_PREDEFINED or macro_name in DYNAMIC_PREDEFINED:
                            self._error("不能取消标准预定义宏", token, "PP_DIRECTIVE")
                        self.macro_register.pop(macro_name, None)
                    elif name == "error":
                        self._error(token.value[len("#error"):].strip() or "#error 指令", token, "PP_ERROR")
                    elif name in ("if", "ifdef", "ifndef", "elif", "else", "endif"):
                        self._error("条件编译指令格式无效", token, "PP_CONDITION_SYNTAX")
                    else:
                        self._warn(f"未识别的预处理指令: {token.value}", token)
                index += 1
                continue

            if self._is_active():
                expanded, consumed = self._consume_token(tokens, index, set())
                output.extend(expanded)
                index += consumed
            else:
                index += 1

        return output

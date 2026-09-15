import re
from collections.abc import Iterator
from verbose_c.parser.lexer.token import Token
from verbose_c.parser.lexer.enum import TokenType
import os


class Lexer:
    """将文本转换为 Token 序列，可选启用 PEG 语法文件模式。"""
    KEYWORDS = {
        # 基本C语言关键字
        'auto', 'break', 'case', 'char', 'const', 'continue', 'default',
        'do', 'double', 'else', 'enum', 'extern', 'float', 'for', 'goto',
        'if', 'int', 'long', 'register', 'return', 'short', 'signed',
        'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
        'unsigned', 'void', 'volatile', 'while',

        # 面向对象功能扩展
        'new', 'class', 'public', 'private', 'protected', 'virtual', 'override',
        'final', 'extends', 'implements', 'interface', 'abstract',
    }

    # 语法文件中的动作使用 Python 表达式，需要独立的注释和字面量规则。
    GRAMMAR_PATTERNS = {
        TokenType.WHITESPACE: r"[ \t\f]+|\\\r?\n",
        TokenType.COMMENT: r"#[^\r\n]*",
        TokenType.NEWLINE: TokenType.NEWLINE.pattern,
        TokenType.STRING: (
            r"(?i:r|u|b|f|br|rb|fr|rf)?(?:'''(?:\\[\s\S]|(?!''')[^\\])*'''|"
            r'"""(?:\\[\s\S]|(?!""")[^\\])*"""|'
            r"'(?:\\[\s\S]|[^'\\\r\n])*'|\"(?:\\[\s\S]|[^\"\\\r\n])*\")"
        ),
        TokenType.NUMBER: (
            r"(?:0[xX](?:_?[0-9a-fA-F])+|0[oO](?:_?[0-7])+|0[bB](?:_?[01])+|"
            r"(?:(?:[0-9](?:_?[0-9])*)?\.[0-9](?:_?[0-9])*|[0-9](?:_?[0-9])*\.)"
            r"(?:[eE][+-]?[0-9](?:_?[0-9])*)?[jJ]?|"
            r"[0-9](?:_?[0-9])*(?:[eE][+-]?[0-9](?:_?[0-9])*)?[jJ]?)"
        ),
        TokenType.NAME: TokenType.NAME.pattern,
        TokenType.OP: (
            r"\*\*=?|//=?|<<=?|>>=?|:=|!=|==|<=|>=|->|\.\.\.|"
            r"[+\-*/%@&|^]=?|[~<>=()\[\]{},:.;!?$]"
        ),
        TokenType.UNKNOWN: TokenType.UNKNOWN.pattern,
    }

    def __init__(self, filename, source, *, macro_body: bool = False, grammar_mode: bool = False):
        self.filename = os.path.abspath(filename) if filename else filename
        self.source = source
        self.grammar_mode = grammar_mode
        self.pos = 0
        self.line = 1
        self.column = 0
        self.tokens = []

        token_types = TokenType
        if macro_body:
            token_types = [t for t in TokenType if t != TokenType.MACRO_CODE]
        patterns = [f"(?P<{t.name}>{t.pattern})" for t in token_types]
        if grammar_mode:
            patterns = [f"(?P<{t.name}>{pattern})" for t, pattern in self.GRAMMAR_PATTERNS.items()]
        self.master_pattern = re.compile("|".join(patterns), re.UNICODE)

    def tokenize(self):
        tokens = self._tokenize()
        self.tokens = list(self._apply_grammar_layout(tokens) if self.grammar_mode else tokens)
        return self.tokens

    def _tokenize(self):
        for m in self.master_pattern.finditer(self.source):
            kind = m.lastgroup
            if not kind:
                continue

            value = m.group(kind)

            # 保存当前词法单元的起始位置
            token_start_line = self.line
            token_start_column = self.column

            # 更新行列号，为下一个词法单元的起始位置做准备
            self._update_position(value)

            # 未知字符时报错，使用起始位置
            if kind == 'UNKNOWN':
                if self.grammar_mode:
                    raise SyntaxError(
                        f"语法文件中存在非法字符 {value!r}",
                        (self.filename, token_start_line, token_start_column + 1,
                         self.source.splitlines(keepends=True)[token_start_line - 1]),
                    )
                raise SyntaxError(
                    f"非法字符 {value!r} 在行 {token_start_line}, 列 {token_start_column}")

            tok_type = TokenType[kind]

            # 如果是标识符，检查是否是关键字
            if not self.grammar_mode and tok_type == TokenType.NAME and value in self.KEYWORDS:
                # 将关键字作为特殊的标识符处理
                yield Token(tok_type, value, column=token_start_column, line=token_start_line, path=self.filename, is_keyword=True)
            else:
                # 其他所有类型的词法单元
                yield Token(tok_type, value, column=token_start_column, line=token_start_line, path=self.filename)

        # 扫描结束后，附加 END token
        # END token 的起始位置是文件内容的末尾
        # self.column += 1 # 不再需要这个调整
        yield Token(TokenType.END, TokenType.END.literal, column=self.column, line=self.line, path=self.filename)

    def _apply_grammar_layout(self, tokens: Iterator[Token]) -> Iterator[Token]:
        """为语法文件保留逻辑换行并生成缩进标记。

        Args:
            tokens: 由共享扫描器生成的原始词法单元。

        Yields:
            去除空白和注释、补齐 INDENT、DEDENT 和末尾换行的词法单元。

        Raises:
            SyntaxError: 括号、续行或缩进不合法。
        """
        # 分别按制表符宽度 8 和 1 记录缩进，用于检测制表符与空格混用。
        indents = [(0, 0)]
        delimiters = []
        closing = {')': '(', ']': '[', '}': '{'}
        line_start = True
        indentation = ""
        has_code = False
        continuation = None
        lines = self.source.splitlines(keepends=True)

        for tok in tokens:
            if tok.type == TokenType.WHITESPACE:
                if tok.string.startswith('\\'):
                    continuation = tok
                    line_start = False
                elif line_start:
                    indentation += tok.string
                continue
            if tok.type == TokenType.COMMENT:
                continue
            if tok.type == TokenType.NEWLINE:
                if not delimiters and has_code:
                    yield tok
                    has_code = False
                line_start = True
                indentation = ""
                continuation = None
                continue
            if tok.type == TokenType.END:
                if delimiters or continuation is not None:
                    start = delimiters[-1] if delimiters else continuation
                    raise SyntaxError(
                        "语法文件的括号或续行未结束",
                        (self.filename, start.line, start.column + 1, lines[start.line - 1]),
                    )
                if has_code:
                    yield Token(TokenType.NEWLINE, "", tok.column, tok.line, tok.path)
                while len(indents) > 1:
                    indents.pop()
                    yield Token(TokenType.DEDENT, "", tok.column, tok.line, tok.path)
                yield tok
                return

            continuation = None
            if line_start and not delimiters:
                column = alternate_column = 0
                for char in indentation:
                    if char == '\t':
                        column = (column // 8 + 1) * 8
                        alternate_column += 1
                    elif char == '\f':
                        column = alternate_column = 0
                    else:
                        column += 1
                        alternate_column += 1
                location = (self.filename, tok.line, tok.column + 1, lines[tok.line - 1])
                if column > indents[-1][0]:
                    if alternate_column <= indents[-1][1]:
                        raise TabError("语法文件混用了不一致的制表符和空格缩进", location)
                    indents.append((column, alternate_column))
                    yield Token(TokenType.INDENT, indentation, 0, tok.line, tok.path)
                else:
                    while column < indents[-1][0]:
                        indents.pop()
                        yield Token(TokenType.DEDENT, "", tok.column, tok.line, tok.path)
                    if column != indents[-1][0]:
                        raise IndentationError("语法文件的缩进层级不匹配", location)
                    if alternate_column != indents[-1][1]:
                        raise TabError("语法文件混用了不一致的制表符和空格缩进", location)

            if tok.type == TokenType.OP:
                if tok.string in ('(', '[', '{'):
                    delimiters.append(tok)
                elif tok.string in closing:
                    if not delimiters or delimiters[-1].string != closing[tok.string]:
                        raise SyntaxError(
                            f"语法文件的括号 {tok.string!r} 不匹配",
                            (self.filename, tok.line, tok.column + 1, lines[tok.line - 1]),
                        )
                    delimiters.pop()
            line_start = False
            has_code = True
            yield tok

    def _update_position(self, text):
        """
        根据文本内容更新行号和列号
        """
        lines = text.split('\n')
        if len(lines) > 1:
            self.line += len(lines) - 1
            self.column = len(lines[-1])
        else:
            self.column += len(text)

    def __repr__(self) -> str:
        return f"Lexer(filename={self.filename})"

import re
from verbose_c.parser.tokenizer.token import Token
from verbose_c.parser.tokenizer.enum import TokenType


class Lexer:
    """
    词法分析器，将文本转换为 Token 序列
    """
    KEYWORDS = {
        # 基本C语言关键字
        'auto', 'break', 'case', 'char', 'const', 'continue', 'default',
        'do', 'double', 'else', 'enum', 'extern', 'float', 'for', 'goto',
        'if', 'int', 'long', 'register', 'return', 'short', 'signed',
        'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
        'unsigned', 'void', 'volatile', 'while',

        # 面向对象功能扩展
        'class', 'public', 'private', 'protected', 'virtual', 'override',
        'final', 'extends', 'implements', 'interface', 'abstract',
    }

    def __init__(self, filename, source):
        self.filename = filename
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 0
        self.tokens = []

        # 基于 TokenType 构造 master_pattern
        patterns = [f"(?P<{t.name}>{t.pattern})"
                    for t in TokenType]
        self.master_pattern = re.compile("|".join(patterns))

    def tokenize(self):
        self.tokens = list(self._tokenize())
        return self.tokens

    def _tokenize(self):
        for m in self.master_pattern.finditer(self.source):
            kind = m.lastgroup
            value = m.group(kind)

            # 保存当前词法单元的起始位置
            token_start_line = self.line
            token_start_column = self.column

            # 更新行列号，为下一个词法单元的起始位置做准备
            self._update_position(value)

            # 未知字符时报错，使用起始位置
            if kind == 'UNKNOWN':
                raise SyntaxError(
                    f"非法字符 {value!r} 在行 {token_start_line}, 列 {token_start_column}")

            tok_type = TokenType[kind]

            # 如果是标识符，检查是否是关键字
            if tok_type == TokenType.IDENTIFIER and value in self.KEYWORDS:
                # 将关键字作为特殊的标识符处理
                yield Token(tok_type, value, column=token_start_column, line=token_start_line, is_keyword=True)
            else:
                # 其他所有类型的词法单元
                yield Token(tok_type, value, column=token_start_column, line=token_start_line)

        # 扫描结束后，附加 END token
        # END token 的起始位置是文件内容的末尾
        # self.column += 1 # 不再需要这个调整
        yield Token(TokenType.END, TokenType.END.literal, column=self.column, line=self.line)

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

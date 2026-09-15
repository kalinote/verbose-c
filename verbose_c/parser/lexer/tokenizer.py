from typing import List

from verbose_c.fs.source_manager import SourceManager
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.token import Token
from verbose_c.parser.lexer.lexer import Lexer

Mark = int

class Tokenizer:
    """为源码或 PEG 语法文件提供可回退的 Token 流。"""

    def __init__(self, filename: str, source_manager: SourceManager, *, grammar_mode: bool = False) -> None:
        self.source_manager = source_manager
        self.grammar_mode = grammar_mode
        self._ignored_types = {TokenType.COMMENT, TokenType.WHITESPACE}
        if not grammar_mode:
            self._ignored_types.add(TokenType.NEWLINE)
        abs_path = source_manager.normalize_path(filename)
        source = source_manager.read(abs_path)
        self.lexer: Lexer = Lexer(abs_path, source, grammar_mode=grammar_mode)
        self.tokens: List[Token] = self.lexer.tokenize()
        self._total_tokens: int = len(self.tokens)
        self._index: int = 0
        self._marks: List[int] = []
        self._furthest_index = 0

    def getnext(self) -> Token:
        """
        获取下一个有效token，并推进索引
        """
        while self._index < self._total_tokens:
            tok = self.tokens[self._index]
            self._index += 1
            if tok.type in self._ignored_types:
                continue
            if self.grammar_mode:
                self._furthest_index = max(self._furthest_index, self._index - 1)
            return tok
        return self.tokens[-1]
            

    def peek(self) -> Token:
        """
        预览下一个有效token，不推进索引
        """
        peek_index = self._index
        while peek_index < self._total_tokens:
            tok = self.tokens[peek_index]
            if tok.type in self._ignored_types:
                peek_index += 1
                continue
            if self.grammar_mode:
                self._furthest_index = max(self._furthest_index, peek_index)
            return tok
        return self.tokens[-1]

    def mark(self) -> Mark:
        self._marks.append(self._index)
        return self._index

    def reset(self, index: int) -> None:
        self._index = index

    def diagnose(self) -> Token:
        if self.grammar_mode:
            return self.tokens[self._furthest_index]
        return self.peek()

    def get_last_non_whitespace_token(self) -> Token:
        """
        返回当前索引之前最后一个非WHITESPACE、非COMMENT、非NEWLINE的token
        """
        for tok in reversed(self.tokens[:self._index]):
            if self.grammar_mode and tok.type in (TokenType.END, TokenType.INDENT, TokenType.DEDENT):
                continue
            if tok.type not in (TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE):
                return tok
        return self.tokens[-1]

    def get_line_source(self, path: str, line: int) -> str:
        resolved_path = path or self.lexer.filename
        return self.source_manager.get_line(resolved_path, line)

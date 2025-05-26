from typing import List

from verbose_c.parser.tokenizer.enum import TokenType
from verbose_c.parser.tokenizer.token import Token
from verbose_c.parser.tokenizer.lexer import Lexer

Mark = int

class Tokenizer:
    def __init__(self, filename: str, source: str, verbose: bool = False) -> None:
        self.lexer: Lexer = Lexer(filename, source)
        self.tokens: List[Token] = self.lexer.tokenize()
        self._total_tokens: int = len(self.tokens)
        self._index: int = 0
        self._marks: List[int] = []
        self._verbose: bool = verbose

    def getnext(self) -> Token:
        """
        获取下一个有效token，并推进索引
        """
        while self._index < self._total_tokens:
            tok = self.tokens[self._index]
            self._index += 1
            if tok.type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.WHITESPACE):
                continue
            return tok
        return self.tokens[-1]
            

    def peek(self) -> Token:
        """
        预览下一个有效token，不推进索引
        """
        peek_index = self._index
        while peek_index < self._total_tokens:
            tok = self.tokens[peek_index]
            if tok.type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.WHITESPACE):
                peek_index += 1
                continue
            return tok
        return self.tokens[-1]

    def mark(self) -> Mark:
        self._marks.append(self._index)
        return self._index

    def reset(self, index: int) -> None:
        self._index = index

    def diagnose(self) -> Token:
        return self.peek()

    def get_last_non_whitespace_token(self) -> Token:
        """
        返回当前索引之前最后一个非WHITESPACE、非COMMENT、非NEWLINE的token
        """
        for tok in reversed(self.tokens[:self._index]):
            if tok.type not in (TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE):
                return tok
        return self.tokens[-1]

    def is_end(self) -> bool:
        return self._index >= len(self.tokens)

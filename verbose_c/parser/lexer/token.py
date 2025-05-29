from verbose_c.parser.lexer.enum import TokenType


class Token:
    def __init__(self, type: TokenType, value, column=None, line=None, is_keyword=False):
        self.type: TokenType = type
        self.value = value
        self.line: int | None = line
        self.column: int | None = column
        self.is_keyword: bool = is_keyword
    
    def __repr__(self):
        keyword_mark = " (keyword)" if self.is_keyword else ""
        return f'Token({self.type}, {repr(self.value)}{keyword_mark}, at {self.column} line {self.line})'
    
    @property
    def string(self):
        return str(self.value)
    
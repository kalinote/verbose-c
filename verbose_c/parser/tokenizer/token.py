from verbose_c.parser.tokenizer.enum import TokenType


class Token:
    def __init__(self, type: TokenType, value, column=None, line=None, is_keyword=False):
        self.type = type
        self.value = value
        self.line = line
        self.column = column
        self.is_keyword = is_keyword
    
    def __repr__(self):
        keyword_mark = " (keyword)" if self.is_keyword else ""
        return f'Token({self.type}, {repr(self.value)}{keyword_mark}, at {self.column} line {self.line})'

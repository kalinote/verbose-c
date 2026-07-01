from enum import Enum

from verbose_c.parser.lexer.token import Token


class MacroDefinitionType(Enum):
    """宏定义类型"""
    FUNCTION = "function"
    OBJECT = "object"


class MacroDefinition:
    """宏定义结构"""
    def __init__(
        self,
        type_: MacroDefinitionType,
        parameters: list[str],
        replacement: list[Token],
        source_file: str = "",
        line: int | None = None,
        column: int | None = None,
    ):
        self.type = type_
        self.parameters = parameters
        self.replacement = replacement
        self.source_file = source_file
        self.line = line
        self.column = column

    def __eq__(self, other: "MacroDefinition"):
        if not isinstance(other, MacroDefinition):
            return False
        if self.type != other.type or self.parameters != other.parameters:
            return False
        if len(self.replacement) != len(other.replacement):
            return False
        for left, right in zip(self.replacement, other.replacement):
            if left.type != right.type or left.value != right.value or left.is_keyword != right.is_keyword:
                return False
        return True

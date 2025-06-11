from enum import Enum, auto

class VBCObjectType(Enum):
    """
    类与对象类型
    """
    CUSTOM = auto()
    CLASS = auto()
    CHAR = auto()
    INT = auto()
    LONG = auto()
    LONGLONG = auto()
    NLINT = auto()
    FLOAT = auto()
    DOUBLE = auto()
    NLFLOAT = auto()
    BOOL = auto()
    NULL = auto()
    LIST = auto()
    MAP = auto()
    MODULE = auto()
    STRING = auto()
    FUNCTION = auto()
    INSTANCE = auto()
    RANGE = auto()

    
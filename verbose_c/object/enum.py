from enum import Enum, auto

class VBCObjectType(Enum):
    """
    类与对象类型
    """
    CLASS = auto()
    INT = auto()
    LONG = auto()
    LONGLONG = auto()
    NLINT = auto()
    LIST = auto()
    MAP = auto()
    MODULE = auto()
    STRING = auto()
    FUNCTION = auto()
    INSTANCE = auto()
    RANGE = auto()

    
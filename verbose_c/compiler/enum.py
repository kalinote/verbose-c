from enum import Enum, auto

class FunctionSignatureType(Enum):
    """
    方法签名类型
    """
    METHOD = auto()
    CONSTRUCT = auto()
    GETTER = auto()
    SETTER = auto()

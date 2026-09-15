from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject
from verbose_c.object.numeric import numeric_compare, numeric_unary
from verbose_c.utils.algorithm import hash_

class VBCBool(VBCObject):
    """
    布尔对象类
    """
    def __init__(self, value: bool):
        super().__init__(VBCObjectType.BOOL)
        self.value: bool = bool(value)

    def __repr__(self):
        return super().__repr__() + f"(value={self.value})"

    def __str__(self):
        return str("true" if self.value else "false")

    def __hash__(self):
        return hash_(self.value)

    def __eq__(self, other):
        return numeric_compare("==", self, other)

    def __bool__(self):
        return self.value

    def __neg__(self):
        return numeric_unary("-", self)

    def __pos__(self):
        return numeric_unary("+", self)

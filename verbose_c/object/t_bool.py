from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject
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
        return str(self.value)

    def __hash__(self):
        return hash_(self.value)

    def __eq__(self, other):
        from verbose_c.object.t_float import VBCFloat
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, VBCBool):
            return VBCBool(self.value == other.value)
        elif isinstance(other, VBCInteger) or isinstance(other, VBCFloat):
            return VBCBool(self.value == bool(other.value))

        return VBCBool(False)

    def __bool__(self):
        return self.value

    def __neg__(self):
        return VBCBool(not self.value)

    def __pos__(self):
        return self

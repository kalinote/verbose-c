from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject

class VBCBool(VBCObject):
    """
    布尔对象类
    """
    def __init__(self, value: bool):
        super().__init__(VBCObjectType.BOOL)
        self.value: bool = bool(value)

    def __str__(self):
        return super().__str__() + f"(value={self.value})"


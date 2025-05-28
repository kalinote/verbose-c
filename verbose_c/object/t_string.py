
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCString(VBCObject):
    """
    字符串对象类
    """
    def __init__(self, value: str):
        super().__init__(VBCObjectType.STRING)
        self._value: str = value
        self._hash = hash(value)

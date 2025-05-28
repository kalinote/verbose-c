
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCFunction(VBCObject):
    """
    TODO 函数对象类
    """
    def __init__(self):
        super().__init__(VBCObjectType.FUNCTION)

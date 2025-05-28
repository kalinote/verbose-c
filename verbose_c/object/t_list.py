
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCList(VBCObject):
    """
    列表对象类
    """
    def __init__(self, elements=None):
        super().__init__(VBCObjectType.LIST)
        self._elements = elements if elements is not None else []



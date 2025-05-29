
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCMap(VBCObject):
    """
    map对象类
    """
    def __init__(self, map_: dict = {}):
        super().__init__(VBCObjectType.MAP)
        self._map = map_ or {}


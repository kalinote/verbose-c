
from ast import List
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCClass(VBCObject):
    """
    verbose-c 类类
    """
    def __init__(self, name: str, super_class: List[str]=None):
        super().__init__(VBCObjectType.CLASS)
        self._name: str = name                           # 类名
        self._super_class: List[str] = super_class       # 父类名列表
        self._methods: dict[str, VBCObject] = {}         # 方法字典
        self._fields: dict[str, VBCObject] = {}          # 字段字典



from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCModule(VBCObject):
    """
    模块对象类
    """
    def __init__(self, name: str):
        super().__init__(VBCObjectType.MODULE)
        self._name = name        # 模块名
        self._functions = {}     # 模块中的方法
        self._variables = {}     # 模块中的变量
        
    
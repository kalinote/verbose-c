
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCRange(VBCObject):
    """
    范围对象类
    
    [待完善]相当于python中的range()，语法为 start...end 或 start...end:step
    """
    def __init__(self, start: int, end: int, step: int = 1):
        super().__init__(VBCObjectType.RANGE)
        self._start = start
        self._end = end
        self._step = step



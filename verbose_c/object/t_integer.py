from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCInteger(VBCObject):
    """
    整数对象类
    """
    bit_width = {
        VBCObjectType.INT: 32,
        VBCObjectType.LONG: 64,
        VBCObjectType.LONGLONG: 64,
        VBCObjectType.NLINT: float('inf')
    }
    
    def __init__(self, value: int, type_: VBCObjectType = VBCObjectType.INT):
        if not type_ in [VBCObjectType.INT, VBCObjectType.LONG, VBCObjectType.LONG, VBCObjectType.NLINT]:
            raise ValueError(f"类型必须是 {VBCObjectType.INT}, {VBCObjectType.LONG}, {VBCObjectType.LONGLONG}, {VBCObjectType.NLINT} 之一")
        
        super().__init__(type_)
        if not isinstance(value, int):
            raise TypeError("VBCInteger 值必须是整数")

        MIN_BIT = -2 ** (VBCInteger.bit_width[type_] - 1)
        MAX_BIT = 2 ** (VBCInteger.bit_width[type_] - 1) - 1
        
        if value < MIN_BIT or value > MAX_BIT:
            print(f"警告: VBCInteger 值超出 {type_} 类型整数范围")

        self.value: int = value

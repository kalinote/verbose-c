from verbose_c.object.numeric import INTEGER_LAYOUT, check_integer, numeric_binary, numeric_compare, numeric_unary
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject
from verbose_c.utils.algorithm import hash_


class VBCInteger(VBCObject):
    """
    整数对象类
    """
    # 各数据类型位宽, 值为(位宽, 类型提升优先级), 不同数据类型的运算结果采用更高的优先级
    bit_width = INTEGER_LAYOUT
    
    def __init__(self, value: int, type_: VBCObjectType = VBCObjectType.INT):
        if type_ not in self.bit_width:
            raise ValueError(f"不支持的数值类型: {type_}")
        if not isinstance(value, int):
            raise TypeError("数值必须是整数")
        super().__init__(type_)
        self.value = check_integer(value, type_)
        self.type_priority = self.bit_width[type_][1]

    def __repr__(self):
        return super().__repr__() + f"(value={self.value})"
    
    def __str__(self):
        return str(self.value)

    def __eq__(self, other):
        return numeric_compare("==", self, other)

    def __ne__(self, other):
        return numeric_compare("!=", self, other)

    def __lt__(self, other):
        return numeric_compare("<", self, other)

    def __le__(self, other):
        return numeric_compare("<=", self, other)

    def __gt__(self, other):
        return numeric_compare(">", self, other)

    def __ge__(self, other):
        return numeric_compare(">=", self, other)

    def __bool__(self):
        return self.value != 0
        
    def __hash__(self):
        return hash_(str(self._object_type.value) + str(self.value))

    def __neg__(self):
        return numeric_unary("-", self)

    def __pos__(self):
        return numeric_unary("+", self)


    def __add__(self, other: VBCObject):
        return numeric_binary("+", self, other)

    def __sub__(self, other: VBCObject):
        return numeric_binary("-", self, other)

    def __mul__(self, other: VBCObject):
        return numeric_binary("*", self, other)

    def __truediv__(self, other: VBCObject):
        return numeric_binary("/", self, other)

    def __mod__(self, other: VBCObject):
        return numeric_binary("%", self, other)
    
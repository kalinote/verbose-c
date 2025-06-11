from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject
from verbose_c.utils.algorithm import hash_


class VBCInteger(VBCObject):
    """
    整数对象类
    """
    # 各数据类型位宽, 值为(位宽, 类型提升优先级), 不同数据类型的运算结果采用更高的优先级
    bit_width = {
        VBCObjectType.CHAR: (8, 1),
        VBCObjectType.INT: (32, 2),
        VBCObjectType.LONG: (64, 3),
        VBCObjectType.LONGLONG: (64, 4),
        VBCObjectType.NLINT: (float('inf'), 5)
    }
    
    def __init__(self, value: int, type_: VBCObjectType = VBCObjectType.INT):
        if not type_ in VBCInteger.bit_width.keys():
            raise ValueError(f"类型必须是 <{', '.join(VBCInteger.bit_width.keys())}> 之一")
        
        super().__init__(type_)
        if not isinstance(value, int):
            raise TypeError("VBCInteger 值必须是整数")

        bits, type_priority = VBCInteger.bit_width[type_]
        MIN_BIT = -2 ** (bits - 1)
        MAX_BIT = 2 ** (bits - 1) - 1
        
        if value < MIN_BIT or value > MAX_BIT:
            raise ValueError(f"VBCInteger 值超出 {type_} 类型整数范围")

        self.value: int = value
        self.type_priority = type_priority

    def __str__(self):
        return super().__str__() + f"(value={self.value})"

    def __eq__(self, other):
        from verbose_c.object.t_float import VBCFloat
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, VBCInteger) or isinstance(other, VBCFloat):
            return VBCBool(self.value == other.value)
        
        return VBCBool(False)

    def __ne__(self, other):
        from verbose_c.object.t_bool import VBCBool
        eq_result = self.__eq__(other)
        return VBCBool(not eq_result.value)

    def __lt__(self, other):
        from verbose_c.object.t_float import VBCFloat
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, (VBCInteger, VBCFloat)):
            return VBCBool(self.value < other.value)
        raise TypeError(f"无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 '<' 运算符")

    def __le__(self, other):
        from verbose_c.object.t_float import VBCFloat
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, (VBCInteger, VBCFloat)):
            return VBCBool(self.value <= other.value)
        raise TypeError(f"无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 '<=' 运算符")

    def __gt__(self, other):
        from verbose_c.object.t_float import VBCFloat
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, (VBCInteger, VBCFloat)):
            return VBCBool(self.value > other.value)
        raise TypeError(f"无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 '>' 运算符")

    def __ge__(self, other):
        from verbose_c.object.t_float import VBCFloat
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, (VBCInteger, VBCFloat)):
            return VBCBool(self.value >= other.value)
        raise TypeError(f"无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 '>=' 运算符")

    def __bool__(self):
        return self.value != 0
        
    def __hash__(self):
        return hash_(str(self._object_type.value) + str(self.value))

    @staticmethod
    def _create_with_promotion(value: int, initial_type: VBCObjectType):
        sorted_types = sorted(
            VBCInteger.bit_width.items(), 
            key=lambda item: item[1][1]
        )
        
        start_index = 0
        for i, (t, _) in enumerate(sorted_types):
            if t == initial_type:
                start_index = i
                break
            
        for type_, (bits, _) in sorted_types[start_index:]:
            if type_ == VBCObjectType.NLINT:
                return VBCInteger(value, VBCObjectType.NLINT)
            
            min_val = -2**(bits - 1)
            max_val = 2**(bits - 1) - 1
            
            if min_val <= value <= max_val:
                return VBCInteger(value, type_)
            
        return VBCInteger(value, VBCObjectType.NLINT)

    def __add__(self, other: VBCObject):
        from verbose_c.object.t_float import VBCFloat
        if isinstance(other, VBCInteger):
            new_value = self.value + other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            return VBCInteger._create_with_promotion(new_value, base_type)

        if isinstance(other, VBCFloat):
            new_value = float(self.value) + other.value
            return VBCFloat._create_with_promotion(new_value, other._object_type)
        
        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "+" 运算符')

    def __sub__(self, other: VBCObject):
        from verbose_c.object.t_float import VBCFloat
        if isinstance(other, VBCInteger):
            new_value = self.value - other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            return VBCInteger._create_with_promotion(new_value, base_type)

        if isinstance(other, VBCFloat):
            new_value = float(self.value) - other.value
            return VBCFloat._create_with_promotion(new_value, other._object_type)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "-" 运算符')

    def __mul__(self, other: VBCObject):
        from verbose_c.object.t_float import VBCFloat
        if isinstance(other, VBCInteger):
            new_value = self.value * other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            return VBCInteger._create_with_promotion(new_value, base_type)

        if isinstance(other, VBCFloat):
            new_value = float(self.value) * other.value
            return VBCFloat._create_with_promotion(new_value, other._object_type)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "*" 运算符')

    def __truediv__(self, other: VBCObject):
        from verbose_c.object.t_float import VBCFloat
        if isinstance(other, (VBCInteger, VBCFloat)):
            if other.value == 0:
                raise ZeroDivisionError("division by zero")
            new_value = self.value / other.value
            
            return VBCFloat._create_with_promotion(new_value, VBCObjectType.DOUBLE)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "/" 运算符')

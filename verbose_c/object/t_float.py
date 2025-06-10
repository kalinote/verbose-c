from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCFloat(VBCObject):
    """
    浮点数对象类
    """
    # 各数据类型位宽, 值为((指数位宽, 尾数位宽), 类型提升优先级), 不同数据类型的运算结果采用更高的优先级
    bit_width = {
        VBCObjectType.FLOAT: ((8, 23), 6),
        VBCObjectType.DOUBLE: ((11, 52), 7),
        VBCObjectType.NLFLOAT: ((float("inf"), float("inf")), 8)
    }
    
    def __init__(self, value: float, type_: VBCObjectType = VBCObjectType.FLOAT):
        if type_ not in VBCFloat.bit_width:
            raise ValueError(f"类型必须是 <{', '.join(t.name for t in VBCFloat.bit_width)}> 之一")

        super().__init__(type_)

        if not isinstance(value, (float, int)):
            raise TypeError("VBCFloat 值必须是浮点数或整数")
        
        value = float(value)

        if type_ != VBCObjectType.NLFLOAT:
            (exp_bits, frac_bits), type_priority = VBCFloat.bit_width[type_]

            bias = 2**(exp_bits - 1) - 1
            max_exp = bias
            min_exp = 1 - bias

            max_val = (2 - 2**-frac_bits) * 2**max_exp
            min_val = 1 * 2**min_exp

            if not (-(max_val) <= value <= max_val) or (0 < abs(value) < min_val):
                raise ValueError(f"VBCFloat 值超出 {type_.name} 类型的浮点数表示范围")
        else:
            _, type_priority = VBCFloat.bit_width[type_]

        self.value: float = value
        self.type_priority = type_priority

    def __str__(self):
        return super().__str__() + f"(value={self.value})"

    def __eq__(self, other):
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, VBCFloat) or isinstance(other, VBCInteger):
            return self.value == other.value
        elif isinstance(other, (int, float)):
            return self.value == other
        return TypeError(f"无法比较 {self.__class__.__name__} 和 {type(other).__name__}")

    def __hash__(self):
        return hash(str(self._object_type.value) + str(self.value))

    @staticmethod
    def _create_with_promotion(value: float, initial_type: VBCObjectType):
        sorted_types = sorted(
            VBCFloat.bit_width.items(),
            key=lambda item: item[1][1]
        )

        start_index = 0
        for i, (t, _) in enumerate(sorted_types):
            if t == initial_type:
                start_index = i
                break
        
        for type_, ((exp_bits, frac_bits), _) in sorted_types[start_index:]:
            if type_ == VBCObjectType.NLFLOAT:
                return VBCFloat(value, VBCObjectType.NLFLOAT)

            bias = 2**(exp_bits - 1) - 1
            max_exp = bias
            min_exp = 1 - bias
            max_val = (2 - 2**-frac_bits) * 2**max_exp
            min_val = 1 * 2**min_exp

            if (-(max_val) <= value <= max_val) and not (0 < abs(value) < min_val):
                return VBCFloat(value, type_)

        return VBCFloat(value, VBCObjectType.NLFLOAT)

    def __add__(self, other: VBCObject):
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, (VBCFloat, VBCInteger)):
            new_value = self.value + other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            if isinstance(other, VBCInteger):
                base_type = self._object_type # 整数和浮点数运算，结果类型应为浮点数
            return VBCFloat._create_with_promotion(new_value, base_type)
        
        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "+" 运算符')

    def __sub__(self, other: VBCObject):
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, (VBCFloat, VBCInteger)):
            new_value = self.value - other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            if isinstance(other, VBCInteger):
                base_type = self._object_type
            return VBCFloat._create_with_promotion(new_value, base_type)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "-" 运算符')

    def __mul__(self, other: VBCObject):
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, (VBCFloat, VBCInteger)):
            new_value = self.value * other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            if isinstance(other, VBCInteger):
                base_type = self._object_type
            return VBCFloat._create_with_promotion(new_value, base_type)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "*" 运算符')

    def __truediv__(self, other: VBCObject):
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, (VBCFloat, VBCInteger)):
            if other.value == 0:
                raise ZeroDivisionError("division by zero")
            new_value = self.value / other.value
            base_type = other._object_type if self.type_priority < other.type_priority else self._object_type
            if isinstance(other, VBCInteger):
                base_type = self._object_type
            return VBCFloat._create_with_promotion(new_value, base_type)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "/" 运算符')


from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject

class VBCString(VBCObject):
    def __init__(self, value: str):
        super().__init__(VBCObjectType.STRING)
        self.value = str(value)

    def __str__(self):
        return super().__str__() + f"(value={self.value})"

    def __eq__(self, other):
        if isinstance(other, VBCString):
            return self.value == other.value
        
        raise TypeError(f'无法比较 {self.__class__.__name__} 和 {other.__class__.__name__}')

    def __hash__(self):
        return hash(self.value)

    def __add__(self, other):
        if isinstance(other, VBCString):
            return VBCString(self.value + other.value)

        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "+" 运算符')

    def __sub__(self, other):
        if isinstance(other, VBCString):
            return VBCString(self.value.replace(other.value, ""))
        
        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "-" 运算符')

    def __mul__(self, other):
        from verbose_c.object.t_integer import VBCInteger
        if isinstance(other, VBCInteger):
            return VBCString(self.value * other.value)
        
        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "*" 运算符')

    def __truediv__(self, other):
        raise TypeError(f'无法对 {self.__class__.__name__} 和 {other.__class__.__name__} 使用 "/" 运算符')
    
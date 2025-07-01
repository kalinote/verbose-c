
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject
from verbose_c.utils.algorithm import hash_

class VBCString(VBCObject):
    def __init__(self, raw_value: str):
        super().__init__(VBCObjectType.STRING)
        self.value = self._unescape(raw_value)

    def _unescape(self, s: str) -> str:
        """
        解析字符串的转义序列。
        """
        res = []
        i = 0
        while i < len(s):
            if s[i] == '\\':
                if i + 1 < len(s):
                    char = s[i+1]
                    if char == 'n':
                        res.append('\n')
                    elif char == 't':
                        res.append('\t')
                    elif char == '\\':
                        res.append('\\')
                    elif char == '"':
                        res.append('"')
                    else:
                        # 如果是未知的转义，则保留原始字符
                        res.append('\\' + char)
                    i += 2
                else: # 字符串以'\'结尾
                    res.append('\\')
                    i += 1
            else:
                res.append(s[i])
                i += 1
        return "".join(res)

    def __repr__(self):
        return super().__repr__() + f"(value={self.value})"
    
    def __str__(self):
        return self.value

    def __eq__(self, other):
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, VBCString):
            return VBCBool(self.value == other.value)
        
        return VBCBool(False)

    def __hash__(self):
        return hash_(self.value)

    def __bool__(self):
        return bool(self.value)

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

    def __neg__(self):
        return VBCString(self.value[::-1])

    def __pos__(self):
        return self

    def __len__(self):
        return len(self.value)


class VBCValueObjBase:
    """我们虚拟机语言中所有值的基类。"""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"<{self.__class__.__name__}: {repr(self.value)}>"

    def __eq__(self, other):
        if isinstance(other, VBCValueObjBase):
            return self.value == other.value
        return NotImplemented

    def __ne__(self, other):
        return not self.__eq__(other)

    # 比较运算符
    def __lt__(self, other):
        if isinstance(other, VBCValueObjBase):
            return self.value < other.value
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, VBCValueObjBase):
            return self.value <= other.value
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, VBCValueObjBase):
            return self.value > other.value
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, VBCValueObjBase):
            return self.value >= other.value
        return NotImplemented

    # 算术运算符
    def __add__(self, other):
        if isinstance(other, VBCValueObjBase):
            return VBCValueObjBase(self.value + other.value)
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, VBCValueObjBase):
            return VBCValueObjBase(self.value - other.value)
        return NotImplemented

    def __mul__(self, other):
        if isinstance(other, VBCValueObjBase):
            return VBCValueObjBase(self.value * other.value)
        return NotImplemented

    def __floordiv__(self, other):
        if isinstance(other, VBCValueObjBase):
            if other.value == 0:
                raise ZeroDivisionError("除数不能为零")
            return VBCValueObjBase(self.value // other.value)
        return NotImplemented

    def __neg__(self):
        return VBCValueObjBase(-self.value)

    def __pos__(self):
        return VBCValueObjBase(+self.value)

    def __bool__(self):
        return bool(self.value)

class VBCIntegerObj(VBCValueObjBase):
    def __init__(self, value):
        verify_instance_type = int
        if not isinstance(value, verify_instance_type):
            raise TypeError(f"{__class__.__name__} 必须用 {verify_instance_type} 初始化")
        super().__init__(value)

class VBCStringObj(VBCValueObjBase):
    def __init__(self, value):
        verify_instance_type = str
        if not isinstance(value, verify_instance_type):
            raise TypeError(f"{__class__.__name__} 必须用 {verify_instance_type} 初始化")
        super().__init__(value)

class VBCListObj(VBCValueObjBase):
    def __init__(self, value=None):
        if value is None:
            value = []
        verify_instance_type = str
        if not isinstance(value, verify_instance_type):
            raise TypeError(f"{__class__.__name__} 必须用 {verify_instance_type} 初始化")
        super().__init__(value)

    def __getitem__(self, key):
        if isinstance(key, VBCIntegerObj):
            return self.value[key.value]
        raise TypeError(f"列表索引必须是整数，而不应该是 {type(key)}")

    def __setitem__(self, key, value):
        if isinstance(key, VBCIntegerObj):
            self.value[key.value] = value
        else:
            raise TypeError(f"列表索引必须是整数，而不应该是 {type(key)}")

class VBCMapObj(VBCValueObjBase):
    def __init__(self, value=None):
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise TypeError("VMMap 必须用字典初始化")
        super().__init__(value)

    def __getitem__(self, key):
        # 对于映射查找，键可以是任何可哈希的 VBCValueObjBase
        if isinstance(key, VBCValueObjBase):
            # 需要确保键的值是可哈希的
            try:
                return self.value[key.value]
            except TypeError:
                raise TypeError(f"映射键 {key} 不可哈希")
        raise TypeError(f"映射键必须是 VBCValueObjBase 类型，而不应该是 {type(key)}")

    def __setitem__(self, key, value):
        # 对于映射赋值，键可以是任何可哈希的 VBCValueObjBase
        if isinstance(key, VBCValueObjBase):
            try:
                self.value[key.value] = value
            except TypeError:
                raise TypeError(f"映射键 {key} 不可哈希")
        else:
            raise TypeError(f"映射键必须是 VBCValueObjBase 类型，而不应该是 {type(key)}")

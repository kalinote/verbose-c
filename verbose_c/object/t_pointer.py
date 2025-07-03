from verbose_c.object.object import VBCObject
from verbose_c.object.enum import VBCObjectType
from verbose_c.utils.algorithm import hash_

class VBCPointer(VBCObject):
    """
    指针对象类
    """
    def __init__(self, address: int, target_type: VBCObjectType):
        """
        Args:
            address (int): 指针指向的内存地址。
            target_type (VBCObjectType): 指针的目标类型枚举。
        """
        # 指针本身的类型是 POINTER
        super().__init__(VBCObjectType.POINTER)
        
        if not isinstance(address, int):
            raise TypeError("VBCPointer 的地址必须是整数")
        if not isinstance(target_type, VBCObjectType):
            raise TypeError("VBCPointer 的目标类型必须是 VBCObjectType 枚举成员")

        self.address = address
        self.target_type = target_type

    def __repr__(self):
        return super().__repr__() + f"({self.target_type.name}* -> 0x{self.address:08x})"

    def __str__(self):
        return f"0x{self.address:08x}"

    def __hash__(self):
        return hash_(str(self.address))

    def __eq__(self, other):
        from verbose_c.object.t_bool import VBCBool
        if isinstance(other, VBCPointer):
            return VBCBool(self.address == other.address and self.target_type == other.target_type)
        return VBCBool(False)

    def __bool__(self):
        return self.address != 0

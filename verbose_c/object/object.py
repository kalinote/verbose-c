
from verbose_c.object.enum import VBCObjectType
        
class VBCObject:
    """
    对象基类
    """
    def __init__(self, object_type: VBCObjectType):
        if not isinstance(object_type, VBCObjectType):
            raise TypeError(f"对象类型必须是 {VBCObjectType}")
        self._object_type = object_type

    def __str__(self):
        return f"{self.__class__.__name__}->{self._object_type}"

    def __eq__(self, value):
        NotImplementedError("子类必须实现此方法")

    def __hash__(self):
        NotImplementedError("子类必须实现此方法")

    def __bool__(self):
        return True

    def __repr__(self):
        return self.__str__()

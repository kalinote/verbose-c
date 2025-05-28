
from verbose_c.object.enum import VBCObjectType

class VBCObjectHeader:
    """
    对象头类
    """
    def __init__(self, object_type: VBCObjectType):
        self._object_type: VBCObjectType = object_type
        
class VBCObject:
    """
    对象基类
    """
    def __init__(self, object_type: VBCObjectType):
        if not isinstance(object_type, VBCObjectType):
            raise TypeError(f"对象类型必须是 {VBCObjectType}")
        self._object_header = VBCObjectHeader(object_type)

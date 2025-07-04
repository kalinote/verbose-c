
from verbose_c.object.enum import VBCObjectType
        
class VBCObject:
    """
    对象基类
    """
    def __init__(self, object_type: VBCObjectType):
        if not isinstance(object_type, VBCObjectType):
            raise TypeError(f"对象类型必须是 {VBCObjectType}")
        self._object_type = object_type

    def __repr__(self):
        return f"{self._object_type}"

    def __eq__(self, value):
        NotImplementedError("子类必须实现此方法")

    def __hash__(self):
        NotImplementedError("子类必须实现此方法")

    def __bool__(self):
        return True

    def __str__(self):
        return f"<VBCObject at {id(self):#x}>"

class VBCObjectWithGC(VBCObject):
    def __init__(self, object_type: VBCObjectType):
        super().__init__(object_type)
        self._gc_marked = False
    
    def _gc_walk(self):
        yield self

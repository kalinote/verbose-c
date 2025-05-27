
from verbose_c.object.enum import ObjectType

class ObjectHeader:
    def __init__(self, object_type: ObjectType):
        self.object_type: ObjectType = object_type
        
class VBCObject:
    def __init__(self, object_type: ObjectType):
        if not isinstance(object_type, ObjectType):
            raise TypeError(f"对象类型必须是 {ObjectType}")
        self.object_header = ObjectHeader(object_type)


from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject
from verbose_c.utils.algorithm import hash_


class VBCNull(VBCObject):
    def __init__(self):
        super().__init__(VBCObjectType.NULL)
    
    def __str__(self):
        return super().__str__() + f"(value=null)"
    
    def __hash__(self):
        return hash_(None)

    def __eq__(self, other):
        from verbose_c.object.t_bool import VBCBool
        return VBCBool(isinstance(other, VBCNull))

    def __bool__(self):
        return False

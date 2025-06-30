
from verbose_c.object.object import VBCObject
from verbose_c.typing.types import AnyType


def native_typeof(obj: AnyType):
    """
    内置的 typeof 函数实现
    """
    if not isinstance(obj, VBCObject):
        raise TypeError(f"{obj} 不是一个有效的 verbose-c 对象")
    
    return obj._object_type.value

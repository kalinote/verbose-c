
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject

class VBCString(VBCObject):
    def __init__(self, value: str):
        super().__init__(VBCObjectType.STRING)
        self.value = str(value)
        self.length = len(self.value)
        self.hash = hash(self.value)

    def __str__(self):
        return super().__str__() + f"(value={self.value})"

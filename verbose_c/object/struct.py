from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCStruct(VBCObject):
    """
    结构体布局描述对象，保存字段名、字段运行时类型枚举与槽位数。
    纯数据、不含方法、不持有其它 VBCObject 引用，不需要 GC 遍历。
    面向未来 AOT/JIT：是结构体的"翻译单元"，可在其上继续挂真实字节偏移/大小/对齐信息。

    Args:
        name (str): 结构体标签名称
        fields (list[tuple[str, VBCObjectType | None]]): 按声明顺序排列的 (字段名, 运行时类型枚举)
    """
    def __init__(self, name: str, fields: list[tuple[str, VBCObjectType | None]]):
        super().__init__(VBCObjectType.STRUCT)
        self.name: str = name
        self.fields: list[tuple[str, VBCObjectType | None]] = fields

    @property
    def slot_count(self) -> int:
        return len(self.fields)

    def __repr__(self):
        return super().__repr__() + f"(name={self.name}, fields={[n for n, _ in self.fields]})"

    def __str__(self):
        return f"<struct {self.name}>"

    def __eq__(self, other):
        if not isinstance(other, VBCStruct):
            return False
        return self.name == other.name and self.fields == other.fields

    def __hash__(self):
        return hash((self.name, tuple(self.fields)))

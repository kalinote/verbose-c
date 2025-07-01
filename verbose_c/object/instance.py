from verbose_c.object.object import VBCObject
from verbose_c.object.enum import VBCObjectType


class VBCInstance(VBCObject):
    """
    verbose-c 类的实例对象
    """
    def __init__(self, class_):
        from verbose_c.object.class_ import VBCClass
        super().__init__(VBCObjectType.INSTANCE)
        # 所属类
        self.class_: VBCClass = class_
        # 实例字段和值
        self.fields: dict[str, VBCObject] = {}

    def __str__(self) -> str:
        return f"<Instance of {self.class_._name}>"

    def __repr__(self):
        return super().__repr__() + f"(instance of {self.class_._name})"

    def _gc_walk(self):
        yield self.class_
        yield from self.fields.values()

    def get_attribute(self, name: str) -> 'VBCObject | None':
        """
        获取实例属性
        """
        if name in self.fields:
            return self.fields[name]

        method = self.class_.lookup_method(name)
        if method:
            return method

        return None

    def set_attribute(self, name: str, value: 'VBCObject'):
        """设置实例的属性"""
        self.fields[name] = value

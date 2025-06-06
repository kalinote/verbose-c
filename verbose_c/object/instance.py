from verbose_c.object.object import VBCObject
from verbose_c.object.enum import VBCObjectType


class VBCInstance(VBCObject):
    """
    verbose-c 类的实例对象
    """
    def __init__(self, klass):
        super().__init__(VBCObjectType.INSTANCE)
        # 所属类
        self.klass = klass
        # 实例字段和值
        self.fields: dict[str, VBCObject] = {}

    def __repr__(self) -> str:
        return f"<instance of {self.klass._name}>" # _name 假设是 VBCClass 的类名属性

    def get_attribute(self, name: str) -> 'VBCObject | None':
        """
        TODO 获取实例属性
        """
        pass

    def set_attribute(self, name: str, value: 'VBCObject'):
        """设置实例的属性"""
        self.fields[name] = value

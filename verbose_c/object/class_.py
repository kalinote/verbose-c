from verbose_c.object.enum import VBCObjectType
from verbose_c.object.instance import VBCInstance
from verbose_c.object.object import VBCObject


class VBCClass(VBCObject):
    """
    verbose-c 类类
    """
    def __init__(self, name: str, super_class: list["VBCClass"] = []):
        super().__init__(VBCObjectType.CLASS)
        self._name: str = name                                  # 类名
        self._super_class: list["VBCClass"] = super_class       # 父类名列表
        self._methods: dict[str, VBCObject] = {}                # 方法字典
        self._fields: dict[str, VBCObject] = {}                 # 字段字典

    def __str__(self):
        return super().__str__() + f"(name={self._name})"

    def create_instance(self) -> VBCInstance:
        """
        实例化类
        """
        return VBCInstance(class_=self)

    def lookup_method(self, name: str) -> VBCObject | None:
        """
        查找方法
        """
        method = self._methods.get(name)
        if method:
            return method

        for sclass in self._super_class:
            method = sclass.lookup_method(name)
            if method:
                return method

        return None
    
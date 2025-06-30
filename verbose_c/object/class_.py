from verbose_c.object.enum import VBCObjectType
from verbose_c.object.instance import VBCInstance
from verbose_c.object.object import VBCObject


class VBCClass(VBCObject):
    """
    verbose-c 类类
    """
    def __init__(self, name: str, super_class: list["VBCClass"] = [], methods: dict[str, VBCObject] = {}, fields: dict[str, VBCObject] = {}):
        super().__init__(VBCObjectType.CLASS)
        self._name: str = name                                  # 类名
        self._super_class: list["VBCClass"] = super_class       # 父类名列表
        self._methods: dict[str, VBCObject] = {}                # 方法字典
        self._fields: dict[str, VBCObject] = {}                 # 字段字典

    def __repr__(self):
        return super().__repr__() + f"(name={self._name})"
    
    def __str__(self):
        return f"<Class {self._name}>"

    def create_instance(self) -> VBCInstance:
        """
        实例化类
        """
        instance = VBCInstance(class_=self)
        # 将类的字段定义复制到实例中，初始化为默认值
        for field_name, default_value in self._fields.items():
            instance.fields[field_name] = default_value
        return instance

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

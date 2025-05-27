
from ast import Module


class VBCVirtualMachine:
    """
    verbose-c 虚拟机核心功能
    """
    def __init__(self):
        self.modules = {}

    def import_module(self):
        """
        导入模块
        """
        raise NotImplementedError

    def build_core(self):
        """
        编译核心模块
        """
        core_module_name = "_core_"
        self.modules[core_module_name] = Module(core_module_name)


global_vm = VBCVirtualMachine()

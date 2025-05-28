from verbose_c.utils.stack import Stack


class VBCVirtualMachine:
    """
    verbose-c 虚拟机核心功能
    """
    def __init__(self):
        self._stack: Stack = Stack()
        self._modules = {}

    @property
    def modules(self):
        return self._modules
    
    
    def get_module(self, module_name: str):
        """
        获取模块
        """
        return self._modules.get(module_name, None)


global_vm = VBCVirtualMachine()

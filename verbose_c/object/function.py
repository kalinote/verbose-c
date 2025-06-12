
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCFunction(VBCObject):
    """
    函数对象类
    """
    def __init__(self, name: str, bytecode: list = None, constants: list = [], param_count: int = 0, 
                    local_count: int = 0):
        super().__init__(VBCObjectType.FUNCTION)
        self.name = name                # 函数名
        self.bytecode = bytecode or []  # 函数字节码
        self.constants = constants      # 函数域的常量池
        self.param_count = param_count  # 参数数量
        self.local_count = local_count  # 局部变量数量
    
    def __repr__(self):
        return f"VBCFunction(name='{self.name}', params={self.param_count}, locals={self.local_count})"

    def __str__(self):
        return super().__str__() + f"(name={self.name})"

class CallFrame:
    """
    调用栈帧，保存函数调用的执行上下文
    """
    def __init__(self, return_pc: int, local_vars: list, function_name: str = None, bytecode: list = [], constants: list = []):
        self.return_pc = return_pc              # 返回地址
        self.local_vars = local_vars            # 调用者的局部变量
        self.function_name = function_name      # 函数名
        self.bytecode = bytecode                # 调用者的字节码
        self.constants = constants              # 调用者的常量池
    
    def __repr__(self):
        return f"CallFrame(func='{self.function_name}', return_pc={self.return_pc}, local_vars_count={len(self.local_vars)})"

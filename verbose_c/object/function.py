
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCFunction(VBCObject):
    """
    函数对象类
    """
    def __init__(self, name: str, bytecode: list = None, param_count: int = 0, 
                 local_count: int = 0, start_pc: int = 0):
        super().__init__(VBCObjectType.FUNCTION)
        # 函数名
        self.name = name
        
        # 函数字节码
        self.bytecode = bytecode or []
        
        # 参数数量
        self.param_count = param_count
        
        # 局部变量数量
        self.local_count = local_count
        
        # 起始地址
        self.start_pc = start_pc
    
    def __repr__(self):
        return f"VBCFunction(name='{self.name}', params={self.param_count}, start_pc={self.start_pc})"

    def __str__(self):
        return super().__str__() + f"(name={self.name})"

class CallFrame:
    """
    调用栈帧，保存函数调用的执行上下文
    """
    def __init__(self, return_pc: int, local_vars: list, function_name: str = None):
        # 返回地址
        self.return_pc = return_pc
        
        # 调用者的局部变量
        self.local_vars = local_vars
        
        # 函数名
        self.function_name = function_name
    
    def __repr__(self):
        return f"CallFrame(func='{self.function_name}', return_pc={self.return_pc}, local_vars_count={len(self.local_vars)})"


from verbose_c.object.enum import VBCObjectType
from verbose_c.object.object import VBCObject


class VBCFunction(VBCObject):
    """
    函数对象类
    """
    def __init__(self, name: str, bytecode: list = None, constants: list = [], param_count: int = 0, 
                    local_count: int = 0, source_path: str | None = None, lineno_table: list | None = None):
        super().__init__(VBCObjectType.FUNCTION)
        self.name = name                # 函数名
        self.bytecode = bytecode or []  # 函数字节码
        self.constants = constants      # 函数域的常量池
        self.param_count = param_count  # 参数数量
        self.local_count = local_count  # 局部变量数量
        self.source_path = source_path  # 函数定义的源文件路径
        self.lineno_table = lineno_table or [] # 字节码行号映射表
    
    def __repr__(self):
        return f"VBCFunction(name='{self.name}', params={self.param_count}, locals={self.local_count})"

    def __str__(self):
        return super().__str__() + f"(name={self.name})"

class VBCBoundMethod(VBCObject):
    """
    绑定方法对象，将一个实例和该实例的一个方法绑定在一起。
    """
    def __init__(self, instance, method):
        from verbose_c.object.instance import VBCInstance
        super().__init__(VBCObjectType.FUNCTION)
        if not isinstance(instance, VBCInstance):
            raise TypeError("VBCBoundMethod 的 instance 必须是 VBCInstance 类型")
        if not isinstance(method, VBCFunction):
            raise TypeError("VBCBoundMethod 的 method 必须是 VBCFunction 类型")
            
        self.instance = instance
        self.method = method

    def __repr__(self):
        return f"<BoundMethod {self.method.name} of {self.instance}>"

class CallFrame:
    """
    调用栈帧，保存函数调用的执行上下文
    """
    def __init__(self, function: 'VBCFunction | VBCBoundMethod', return_pc: int, local_vars: list, bytecode: list = [], constants: list = []):
        self.function = function                # 正在执行的函数或方法对象
        self.return_pc = return_pc              # 返回地址
        self.local_vars = local_vars            # 调用者的局部变量
        self.bytecode = bytecode                # 调用者的字节码
        self.constants = constants              # 调用者的常量池
    
    def __repr__(self):
        func_name = self.function.name if isinstance(self.function, VBCFunction) else self.function.method.name
        return f"CallFrame(func='{func_name}', return_pc={self.return_pc}, local_vars_count={len(self.local_vars)})"

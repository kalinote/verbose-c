
class Module:
    """
    模块类
    """
    def __init__(self, name: str):
        self.name = name        # 模块名
        self.functions = {}     # 模块中的方法
        self.variables = {}     # 模块中的变量
        
    
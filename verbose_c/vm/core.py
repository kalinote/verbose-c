from verbose_c.compiler.opcode import Opcode
from verbose_c.utils.stack import Stack


class VBCVirtualMachine:
    """
    verbose-c 虚拟机核心功能
    """
    def __init__(self):
        self._stack: Stack = Stack()            # 栈
        self._pc = 0                            # 程序计数器
        self._local_variables = {}              # 局部变量
        self._global_variables = {}             # 全局变量
        self._call_stack = []                   # 调用栈
        self._running = False                    # 是否正在运行
        self._handlers = {}                    # 指令处理器

    
    def _fetch_instruction(self):
        """
        获取指令
        """
        pass
        
    def _execute_instruction(self, instruction: tuple):
        """
        执行单条指令
        """
        if len(instruction) == 1:
            opcode = instruction[0]
            operand = None
        elif len(instruction) == 2:
            opcode, operand = instruction
        else:
            raise ValueError(f"错误的指令格式: {instruction}, 要求: (opcode,) 或 (opcode, operand)")
        
    def excute(self, bytecode, constants):
        """
        虚拟机指令执行循环
        """
        self._bytecode = bytecode
        self._constants = constants
        self._pc = 0
        self._running = True
        
        while self._running and self._pc < len(bytecode):
            # 取码、译码、执行
            
            instruction = self._fetch_instruction()
            self._execute_instruction(instruction)
            self._pc += 1

    # 指令注册和执行
    def register_instruction(self, opcode):
        def decorator(func):
            self._handlers[opcode] = func
            return func
        return decorator

    @register_instruction(Opcode.LOAD_CONSTANT)
    def __handle_load_constant(self):
        pass

    @register_instruction(Opcode.POP)
    def __handle_pop(self):
        pass

    @register_instruction(Opcode.DUP)
    def __handle_dup(self):
        pass

    @register_instruction(Opcode.SWAP)
    def __handle_swap(self):
        pass

    @register_instruction(Opcode.STORE_LOCAL_VAR)
    def __handle_store_local_var(self):
        pass

    @register_instruction(Opcode.LOAD_LOCAL_VAR)
    def __handle_load_local_var(self):
        pass

    @register_instruction(Opcode.LOAD_GLOBAL_VAR)
    def __handle_load_global_var(self):
        pass

    @register_instruction(Opcode.STORE_GLOBAL_VAR)
    def __handle_store_global_var(self):
        pass
    
    @register_instruction(Opcode.DECLARE_VAR)
    def __handle_declare_var(self):
        pass

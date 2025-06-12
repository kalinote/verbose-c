from verbose_c.compiler.opcode import Instruction, Opcode
from verbose_c.utils.stack import Stack
from verbose_c.object.function import VBCFunction, CallFrame
from verbose_c.object.t_bool import VBCBool

# 全局的指令处理器映射
_vm_handlers = {}

def register_instruction(opcode: Opcode):
    """指令注册装饰器"""
    def decorator(func):
        _vm_handlers[opcode] = func
        return func
    return decorator

class VBCVirtualMachine:
    """
    verbose-c 虚拟机核心功能
    """
    
    def __init__(self, debug_log_collector: list = None):
        self._stack: Stack = Stack()            # 栈
        self._pc = 0                            # 程序计数器
        self._local_variables = []              # 局部变量（使用列表按索引访问）
        self._global_variables = {}             # 全局变量 # TODO 考虑一下这里要不要和局部变量保持一致
        self._call_stack = []                   # 调用栈
        self._scope_stack = []                  # 作用域栈，用于嵌套作用域管理
        self._running = False                   # 是否正在运行
        self._handlers = _vm_handlers           # 使用全局的处理器映射
        self._debug_log_collector = debug_log_collector # 调试日志收集器

    
    def _fetch_instruction(self) -> Instruction:
        """
        获取指令
        """
        if self._pc >= len(self._bytecode):
            raise RuntimeError("程序计数器越界")
        return self._bytecode[self._pc]
        
    def _execute_instruction(self, instruction: Instruction):
        """
        执行单条指令
        """
        if len(instruction) == 1:
            opcode = instruction[0]
            operand = None
        else:
            opcode, operand = instruction
        
        if opcode in self._handlers:
            handler = self._handlers[opcode]
            try:
                if operand is not None:
                    handler(self, operand)
                else:
                    handler(self)
            except Exception as e:
                stack_info = []
                temp_stack = []
                while not self._stack.is_empty():
                    val = self._stack.pop()
                    stack_info.append(f"{type(val).__name__}: {repr(val)}")
                    temp_stack.append(val)

                for val in reversed(temp_stack):
                    self._stack.push(val)
                
                stack_str = "\n        " + ",\n        ".join(reversed(stack_info)) + "\n    " if stack_info else "空栈"
                
                context_start = max(0, self._pc - 3)
                context_end = min(len(self._bytecode), self._pc + 4)
                context_instructions = []
                for i in range(context_start, context_end):
                    marker = ">>> " if i == self._pc else "    "
                    instr = self._bytecode[i]
                    if len(instr) == 1:
                        context_instructions.append(f"{marker}{i}: {instr[0].name}")
                    else:
                        context_instructions.append(f"{marker}{i}: {instr[0].name} {instr[1]}")
                
                context_str = "\n".join(context_instructions)
                
                error_msg = f"""
虚拟机执行错误详情:
    错误: {e}
    指令位置: {self._pc}
    当前指令: {opcode.name}{f' {operand}' if operand is not None else ''}
    栈状态: [{stack_str}]
    局部变量: {[str(item) for item in self._local_variables]}
    指令上下文:
{context_str}
                """.strip()
                raise RuntimeError(error_msg) from e
        else:
            raise RuntimeError(f"未知操作码: {opcode}")
        
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

            if self._debug_log_collector is not None:
                # 记录执行日志
                stack_str = " -> ".join(str(item) for item in self._stack._items)
                log_entry = f"PC: {self._pc:04d} | OP: {instruction[0].name:<15}"
                if len(instruction) > 1:
                    log_entry += f" {instruction[1]:<5}"
                else:
                    log_entry += "      "
                log_entry += f"| STACK: [{stack_str}]"
                self._debug_log_collector.append(log_entry)

            self._execute_instruction(instruction)
            self._pc += 1

    ## 栈操作类
    @register_instruction(Opcode.LOAD_CONSTANT)
    def __handle_load_constant(self, operand):
        if operand is None:
            raise RuntimeError("LOAD_CONSTANT 指令缺少操作数")
        
        if operand < 0 or operand >= len(self._constants):
            raise RuntimeError(f"常量池索引越界: {operand}, 常量池大小: {len(self._constants)}")
        
        # 从常量池获取值并压入栈
        constant_value = self._constants[operand]
        self._stack.push(constant_value)

    @register_instruction(Opcode.POP)
    def __handle_pop(self):
        self._stack.pop()

    @register_instruction(Opcode.DUP)
    def __handle_dup(self):
        self._stack.push(self._stack.peek())

    @register_instruction(Opcode.SWAP)
    def __handle_swap(self):
        a = self._stack.pop()
        b = self._stack.pop()
        self._stack.push(a)
        self._stack.push(b)

    ## 变量操作类
    @register_instruction(Opcode.STORE_LOCAL_VAR)
    def __handle_store_local_var(self, operand):
        """存储栈顶值到局部变量"""
        if operand is None:
            raise RuntimeError("STORE_LOCAL_VAR 指令缺少地址操作数")
        
        if self._stack.is_empty():
            raise RuntimeError("栈为空，无法存储到局部变量")
        
        value = self._stack.pop()
        
        while len(self._local_variables) <= operand:
            self._local_variables.append(None)
        
        self._local_variables[operand] = value

    @register_instruction(Opcode.LOAD_LOCAL_VAR)
    def __handle_load_local_var(self, operand):
        """加载局部变量值到栈顶"""
        if operand is None:
            raise RuntimeError("LOAD_LOCAL_VAR 指令缺少地址操作数")
        
        if operand < 0:
            raise RuntimeError(f"局部变量地址无效: {operand}")
        
        # 如果地址超出已分配范围，则视为未初始化
        if operand >= len(self._local_variables):
            raise RuntimeError(f"访问未初始化的局部变量: 地址 {operand}")
        
        value = self._local_variables[operand]
        if value is None:
            raise RuntimeError(f"访问未初始化的局部变量: 地址 {operand}")
        
        self._stack.push(value)

    @register_instruction(Opcode.LOAD_GLOBAL_VAR)
    def __handle_load_global_var(self, operand):
        """加载全局变量值到栈顶"""
        if operand is None:
            raise RuntimeError("LOAD_GLOBAL_VAR 指令缺少变量名操作数")
        
        if operand not in self._global_variables:
            raise RuntimeError(f"未定义的全局变量: {operand}")
        
        value = self._global_variables[operand]
        self._stack.push(value)

    @register_instruction(Opcode.STORE_GLOBAL_VAR)
    def __handle_store_global_var(self, operand):
        """存储栈顶值到全局变量"""
        if operand is None:
            raise RuntimeError("STORE_GLOBAL_VAR 指令缺少变量名操作数")
        
        if self._stack.is_empty():
            raise RuntimeError("栈为空，无法存储到全局变量")
        
        value = self._stack.pop()
        
        self._global_variables[operand] = value
    

    ## 算术运算类指令
    @register_instruction(Opcode.ADD)
    def __handle_add(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand + r_operand)

    @register_instruction(Opcode.SUBTRACT)
    def __handle_subtract(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand - r_operand)

    @register_instruction(Opcode.MULTIPLY)
    def __handle_multiply(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand * r_operand)

    @register_instruction(Opcode.DIVIDE)
    def __handle_divide(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand / r_operand)

    @register_instruction(Opcode.MODULO)
    def __handle_modulo(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand % r_operand)

    @register_instruction(Opcode.UNARY_MINUS)
    def __handle_unary_minus(self):
        n = self._stack.pop()
        self._stack.push(-n)

    ## 比较运算类指令
    @register_instruction(Opcode.EQUAL)
    def __handle_equal(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand == r_operand)

    @register_instruction(Opcode.NOT_EQUAL)
    def __handle_not_equal(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand != r_operand)

    @register_instruction(Opcode.LESS_THAN)
    def __handle_less_than(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand < r_operand)

    @register_instruction(Opcode.LESS_EQUAL)
    def __handle_less_equal(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand <= r_operand)

    @register_instruction(Opcode.GREATER_THAN)
    def __handle_greater_than(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand > r_operand)

    @register_instruction(Opcode.GREATER_EQUAL)
    def __handle_greater_equal(self):
        r_operand = self._stack.pop()
        l_operand = self._stack.pop()
        self._stack.push(l_operand >= r_operand)

    ## 逻辑运算类指令
    @register_instruction(Opcode.LOGICAL_NOT)
    def __handle_logical_not(self):
        operand = self._stack.pop()
        py_result = not operand
        self._stack.push(VBCBool(py_result))

    ## 控制流类指令
    @register_instruction(Opcode.JUMP)
    def __handle_jump(self, operand):
        if operand is None:
            raise RuntimeError("JUMP 指令缺少目标地址")
        self._pc = operand - 1

    @register_instruction(Opcode.JUMP_IF_FALSE)
    def __handle_jump_if_false(self, operand):
        if operand is None:
            raise RuntimeError("JUMP 指令缺少目标地址")
        
        condition = self._stack.pop()
        if not bool(condition):
            self._pc = operand - 1

    @register_instruction(Opcode.RETURN)
    def __handle_return(self):
        if self._stack.is_empty():
            raise RuntimeError("RETURN 指令缺少返回值")

        return_value = self._stack.pop()
        
        if not self._call_stack:
            # 主函数返回，最后栈里面为返回值，程序结束
            self._running = False
            self._stack.push(return_value)
            return

        # 恢复调用前的上下文
        call_frame: CallFrame = self._call_stack.pop()
        self._pc = call_frame.return_pc
        self._local_variables = call_frame.local_vars
        self._bytecode = call_frame.bytecode
        self._constants = call_frame.constants
        
        # 返回值入栈
        self._stack.push(return_value)

    ## 函数调用类指令
    @register_instruction(Opcode.CALL_FUNCTION)
    def __handle_call_function(self, operand):
        if operand is None:
            raise ValueError("CALL_FUNCTION 指令缺少参数数量")
        
        # 参数数量 + 函数对象
        if self._stack.size() < operand + 1:
            raise RuntimeError(f"栈层数错误, 需要 {operand + 2} 个元素, 实际只有 {self._stack.size}")

        # 从栈顶向下数第 operand 个位置是函数对象，在此之前都是参数
        function_obj = self._stack.peek(operand)
        
        if not isinstance(function_obj, VBCFunction):
            raise RuntimeError(f"调用的对象不是一个函数: {type(function_obj)}")
        
        if operand != function_obj.param_count:
            raise RuntimeError(f"函数 '{function_obj.name}' 期望 {function_obj.param_count} 个参数，但提供了 {operand} 个")
        
        # 保存现场
        call_frame = CallFrame(
            return_pc=self._pc,
            local_vars=self._local_variables,
            bytecode=self._bytecode,
            constants=self._constants,
            function_name=function_obj.name
        )
        self._call_stack.append(call_frame)

        # 切换到函数的执行上下文
        self._bytecode = function_obj.bytecode
        self._constants = function_obj.constants

        self._local_variables = [None] * function_obj.local_count
        
        # 处理参数以及弹出函数对象
        for i in range(operand):
            self._local_variables[operand - 1 - i] = self._stack.pop()
        self._stack.pop()
        
        # 执行完这个命令pc会在循环内+1
        self._pc = -1

    @register_instruction(Opcode.LOAD_FUNCTION)
    def __handle_load_function(self):
        pass

    @register_instruction(Opcode.ENTER_SCOPE)
    def __handle_enter_scope(self):
        """进入新作用域"""
        # 保存当前局部变量状态到作用域栈
        self._scope_stack.append({
            'local_vars': self._local_variables.copy(),
            'local_count': len(self._local_variables)
        })

    @register_instruction(Opcode.EXIT_SCOPE)
    def __handle_exit_scope(self):
        """退出当前作用域"""
        if not self._scope_stack:
            raise RuntimeError("没有可退出的作用域")
        
        # 恢复上一层作用域的局部变量状态
        scope_info = self._scope_stack.pop()
        self._local_variables = scope_info['local_vars']

    ## 类型转换类指令
    @register_instruction(Opcode.CAST)
    def __handle_cast_to_int(self):
        pass

    ## 内存管理类指令
    @register_instruction(Opcode.ALLOC_OBJECT)
    def __handle_alloc_object(self):
        pass

    @register_instruction(Opcode.FREE_OBJECT)
    def __handle_free_object(self):
        pass

    ## 扩展指令类
    @register_instruction(Opcode.NOP)
    def __handle_nop(self):
        pass

    @register_instruction(Opcode.HALT)
    def __handle_halt(self):
        """停机指令，结束虚拟机执行"""
        self._running = False

    @register_instruction(Opcode.DEBUG_PRINT)
    def __handle_debug_print(self):
        if not self._stack.is_empty():
            print(f"DEBUG: 栈顶值 = {self._stack.peek()}")
        else:
            print("DEBUG: 栈为空")

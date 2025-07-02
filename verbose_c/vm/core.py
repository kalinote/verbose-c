import bisect
from verbose_c.compiler.opcode import Instruction, Opcode
from verbose_c.error import VBCRuntimeError, TracebackFrame
from verbose_c.object.class_ import VBCClass
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.instance import VBCInstance
from verbose_c.object.object import VBCObject
from verbose_c.object.t_float import VBCFloat
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_string import VBCString
from verbose_c.utils.stack import Stack
from verbose_c.object.function import VBCBoundMethod, VBCFunction, CallFrame, VBCNativeFunction
from verbose_c.object.t_bool import VBCBool
from verbose_c.vm.gc import GarbageCollector
from verbose_c.vm.builtins_functions import BUILTIN_FUNCTIONS, BUILTIN_CONSTANTS

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
        self._global_variables = {}             # 全局变量
        self._call_stack: list[CallFrame] = []  # 调用栈
        self._scope_stack = []                  # 作用域栈，用于嵌套作用域管理
        self._running = False                   # 是否正在运行
        self._handlers = _vm_handlers           # 使用全局的处理器映射
        self._debug_log_collector = debug_log_collector # 调试日志收集器
        
        # 运行时上下文
        self._bytecode: list = []
        self._constants: list = []
        self._current_function: VBCFunction | None = None # 当前正在执行的函数

        self.gc = GarbageCollector(self)

        self._register_builtins()
    
    def _allocate(self, obj):
        """将对象注册到GC，然后返回该对象。"""
        if isinstance(obj, VBCObject):
            self.gc.allocate(obj)
        return obj

    def _register_builtins(self):
        """注册所有内置函数到全局变量中"""
        for name, py_func in BUILTIN_FUNCTIONS.items():
            self._global_variables[name] = self._allocate(VBCNativeFunction(name, py_func))
        for name, vbc_obj in BUILTIN_CONSTANTS.items():
            self._global_variables[name] = self._allocate(vbc_obj)
    
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
            opcode, operand = instruction[0], None
        else:
            opcode, operand = instruction

        handler = self._handlers.get(opcode)
        if handler is None:
            raise RuntimeError(f"未知操作码: {opcode}")

        try:
            if operand is not None:
                handler(self, operand)
            else:
                handler(self)
        except Exception as e:
            # 捕获到任何指令执行期间的异常，生成并抛出结构化的 VBCRuntimeError
            vbc_error = self._generate_runtime_error(e)
            raise vbc_error from e

    def _find_line_from_pc(self, function: VBCFunction, pc: int) -> int:
        """根据程序计数器(PC)在行号表中查找对应的行号"""
        if not function.lineno_table:
            return -1
        
        pc_offsets = [item[0] for item in function.lineno_table]
        index = bisect.bisect_right(pc_offsets, pc)
        
        if index > 0:
            return function.lineno_table[index - 1][1]
        
        return -1

    def _generate_runtime_error(self, e: Exception) -> VBCRuntimeError:
        """生成一个包含完整调用栈的 VBCRuntimeError"""
        traceback_frames = []

        if self._current_function:
            line = self._find_line_from_pc(self._current_function, self._pc)
            traceback_frames.append(
                TracebackFrame(
                    filepath=self._current_function.source_path or "<unknown>",
                    line=line,
                    scope_name=self._current_function.name,
                    # TODO 完善源代码显示
                    source_line_context=[self._source_code[line - 1].strip()],
                )
            )

        for frame in reversed(self._call_stack):
            func = frame.function
            pc = frame.return_pc
            
            if isinstance(func, VBCBoundMethod):
                func = func.method

            if isinstance(func, VBCFunction):
                line = self._find_line_from_pc(func, pc)
                traceback_frames.append(
                    TracebackFrame(
                        filepath=func.source_path or "<unknown>",
                        line=line,
                        scope_name=func.name,
                        # TODO 完善源代码显示
                        source_line_context=[self._source_code[line - 1].strip()]
                    )
                )
        
        # Python 的 traceback 是从调用者到被调用者，所以我们需要反转列表
        traceback_frames.reverse()
        
        # 获取原始异常的类型和消息
        error_type_name = type(e).__name__
        error_message = str(e)
        full_message = f"{error_type_name}: {error_message}"

        return VBCRuntimeError(full_message, traceback_frames)

    def get_roots(self) -> list:
        """
        收集并返回所有根对象，供GC进行标记。
        """
        roots = []
        
        # 1. 全局变量
        roots.extend(self._global_variables.values())
        
        # 2. 当前常量池
        roots.extend(self._constants)
        
        # 3. 操作数栈
        roots.extend(self._stack._items)
        
        # 4. 当前局部变量
        roots.extend(self._local_variables)
        
        # 5. 当前正在执行的函数
        if self._current_function:
            roots.append(self._current_function)
            
        # 6. 调用栈中的所有帧
        for frame in self._call_stack:
            roots.append(frame.function)
            roots.extend(frame.local_vars)
            roots.extend(frame.constants)
            
        return roots

    def excute(
            self,
            bytecode,
            constants,
            source_path: str | None = None,
            lineno_table: list[tuple[int, int]] | None = None,
            source_code: list[str] = []
        ):
        """
        虚拟机指令执行循环
        """
        self._bytecode = bytecode
        self._constants = constants
        self._pc = 0
        self._running = True
        self._source_code = source_code

        # 为顶层模块创建一个伪函数对象，作为调用栈的根
        module_func = VBCFunction(
            name="<module:entry>",
            bytecode=bytecode,
            constants=constants,
            source_path=source_path,
            lineno_table=lineno_table
        )
        self._current_function = module_func
        
        while self._running and self._pc < len(self._bytecode):
            # 取码、译码、执行
            instruction = self._fetch_instruction()

            if self._debug_log_collector is not None:
                # 记录执行日志
                stack_str = " -> ".join(repr(item) for item in self._stack._items)
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
        
        # 构造函数调用的特殊处理：返回实例 `this` 而不是构造函数的返回值
        if getattr(call_frame, 'is_constructor_call', False):
            instance = self._local_variables[0] # 'this' 存储在局部变量0
            self._stack.push(instance)
        else:
            self._stack.push(return_value)

        self._pc = call_frame.return_pc
        self._local_variables = call_frame.local_vars
        self._bytecode = call_frame.bytecode
        self._constants = call_frame.constants
        # 恢复当前函数
        if isinstance(call_frame.function, VBCBoundMethod):
            self._current_function = call_frame.function.method
        else:
            self._current_function = call_frame.function

    ## 函数调用类指令
    @register_instruction(Opcode.CALL_FUNCTION)
    def __handle_call_function(self, num_args):
        if num_args is None:
            raise ValueError("CALL_FUNCTION 指令缺少参数数量")
        
        if self._stack.size() < num_args + 1:
            raise RuntimeError(f"栈层数错误, 需要 {num_args + 1} 个元素, 实际只有 {self._stack.size()}")

        callable_obj = self._stack.peek(num_args)

        if isinstance(callable_obj, VBCFunction):
            if num_args != callable_obj.param_count:
                raise RuntimeError(f"函数 '{callable_obj.name}' 期望 {callable_obj.param_count} 个参数，但提供了 {num_args} 个")
            
            args = [self._stack.pop() for _ in range(num_args)]
            args.reverse()
            self._stack.pop() # 弹出函数对象

            call_frame = CallFrame(
                function=self._current_function, 
                return_pc=self._pc, 
                local_vars=self._local_variables, 
                bytecode=self._bytecode, 
                constants=self._constants
            )
            self._call_stack.append(call_frame)

            # 切换到新函数的上下文
            self._current_function = callable_obj
            self._bytecode = callable_obj.bytecode
            self._constants = callable_obj.constants
            self._local_variables = [None] * callable_obj.local_count
            for i, arg in enumerate(args):
                self._local_variables[i] = arg
            
            # 将PC设置为-1，因为循环会自动+1，从而从0开始执行新函数
            self._pc = -1

        elif isinstance(callable_obj, VBCNativeFunction):
            args = [self._stack.pop() for _ in range(num_args)]
            args.reverse()
            self._stack.pop() # 弹出内置函数对象

            result = callable_obj(*args)
            self._stack.push(result)

        elif isinstance(callable_obj, VBCBoundMethod):
            method = callable_obj.method
            instance = callable_obj.instance

            if num_args != method.param_count:
                raise RuntimeError(f"方法 '{method.name}' 期望 {method.param_count} 个参数，但提供了 {num_args} 个")

            args = [self._stack.pop() for _ in range(num_args)]
            args.reverse()
            self._stack.pop() # 弹出绑定方法对象

            call_frame = CallFrame(
                function=self._current_function, 
                return_pc=self._pc, 
                local_vars=self._local_variables, 
                bytecode=self._bytecode, 
                constants=self._constants
            )
            self._call_stack.append(call_frame)

            # 切换到新方法的上下文
            self._current_function = method
            self._bytecode = method.bytecode
            self._constants = method.constants
            self._local_variables = [None] * method.local_count
            
            self._local_variables[0] = instance
            for i, arg in enumerate(args):
                self._local_variables[i + 1] = arg
            
            # 将PC设置为-1，因为循环会自动+1，从而从0开始执行新函数
            self._pc = -1
        
        else:
            raise RuntimeError(f"调用的对象不是一个函数或方法: {type(callable_obj)}")

    @register_instruction(Opcode.LOAD_FUNCTION)
    def __handle_load_function(self):
        pass

    @register_instruction(Opcode.ENTER_SCOPE)
    def __handle_enter_scope(self):
        """进入新作用域"""
        self._scope_stack.append(len(self._local_variables))

    @register_instruction(Opcode.EXIT_SCOPE)
    def __handle_exit_scope(self):
        """退出当前作用域"""
        if not self._scope_stack:
            raise RuntimeError("没有可退出的作用域")
        
        previous_count = self._scope_stack.pop()
        num_to_pop = len(self._local_variables) - previous_count
        if num_to_pop > 0:
            del self._local_variables[previous_count:]

    ## 类型转换类指令
    @register_instruction(Opcode.CAST)
    def __handle_cast(self, target_type_enum):
        if target_type_enum is None:
            raise RuntimeError("CAST 指令缺少目标类型操作数")

        source_obj = self._stack.pop()
        new_obj = None

        # TODO 完善转换规则
        # 规则 1: 转换为数字类型
        if target_type_enum in VBCInteger.bit_width or target_type_enum in VBCFloat.bit_width:
            if isinstance(source_obj, (VBCInteger, VBCFloat)):
                value_as_float = float(source_obj.value)
                if target_type_enum in VBCInteger.bit_width:
                    new_obj = VBCInteger(int(value_as_float), target_type_enum)
                else:
                    new_obj = VBCFloat(value_as_float, target_type_enum)
        
        # 规则 2: 转换为字符串类型
        elif target_type_enum == VBCObjectType.STRING:
            new_obj = self._allocate(VBCString(str(source_obj)))

        # 规则 3: 转换为布尔类型
        elif target_type_enum == VBCObjectType.BOOL:
            new_obj = VBCBool(bool(source_obj))

        if new_obj is None:
            source_type_name = source_obj._object_type.name
            raise TypeError(f"不支持从类型 '{source_type_name}' 到 '{target_type_enum.name}' 的强制类型转换")

        self._stack.push(new_obj)

    ## 内存管理类指令
    @register_instruction(Opcode.ALLOC_OBJECT)
    def __handle_alloc_object(self):
        pass

    @register_instruction(Opcode.FREE_OBJECT)
    def __handle_free_object(self):
        pass

    ## 对象与类操作类
    @register_instruction(Opcode.GET_PROPERTY)
    def __handle_get_property(self):
        property_name_obj = self._stack.pop()
        instance_obj = self._stack.pop()

        if not isinstance(property_name_obj, VBCString):
            raise TypeError(f"GET_PROPERTY 指令: 属性名期望 {type(VBCString)} 得到 {type(property_name_obj).__name__}")
        
        property_name = property_name_obj.value

        if not isinstance(instance_obj, VBCInstance):
            raise TypeError(f"GET_PROPERTY 指令: 实例期望 {type(VBCInstance).__name__} 得到 {type(instance_obj).__name__}")

        # 使用实例的 get_attribute 方法查找属性或方法
        attribute = instance_obj.get_attribute(property_name)
        
        if attribute is None:
            raise AttributeError(f"对象 '{instance_obj.class_._name}' 没有属性 '{property_name}'")

        # 如果获取到的是一个方法，则创建一个绑定方法对象
        if isinstance(attribute, VBCFunction):
            bound_method = self._allocate(VBCBoundMethod(instance_obj, attribute))
            self._stack.push(bound_method)
        else:
            self._stack.push(attribute)
    
    @register_instruction(Opcode.SET_PROPERTY)
    def __handle_set_property(self):
        property_name = self._stack.pop()
        instance = self._stack.pop()
        value = self._stack.pop()

        if not isinstance(property_name, VBCString):
            raise TypeError(f"SET_PROPERTY 指令: 属性名期望 {type(VBCString)} 得到 {type(property_name).__name__}")       
        property_name_str = property_name.value
        
        if not isinstance(instance, VBCInstance):
            raise TypeError(f"SET_PROPERTY 指令: 实例期望 {type(VBCInstance).__name__} 得到 {type(instance).__name__}")

        instance.set_attribute(property_name_str, value)
        # 结果入栈
        self._stack.push(value)

    @register_instruction(Opcode.NEW_INSTANCE)
    def __handle_new_instance(self, num_args):
        """处理对象实例化和构造函数调用"""
        if num_args is None:
            raise ValueError("NEW_INSTANCE 指令缺少参数数量")

        if self._stack.size() < num_args + 1:
            raise RuntimeError(f"栈层数错误, 需要 {num_args + 1} 个元素, 实际只有 {self._stack.size()}")

        class_obj = self._stack.peek(num_args)
        if not isinstance(class_obj, VBCClass):
            raise TypeError(f"new 操作的目标不是一个类: {type(class_obj).__name__}")

        instance = self._allocate(class_obj.create_instance())
        init_method = class_obj.lookup_method("__init__")
        
        args = [self._stack.pop() for _ in range(num_args)]
        args.reverse()
        self._stack.pop()

        if not init_method or not isinstance(init_method, VBCFunction):
            if num_args > 0:
                raise RuntimeError(f"类 '{class_obj._name}' 的默认构造函数不接受参数")
            self._stack.push(instance)
            return

        if num_args != init_method.param_count:
            raise RuntimeError(f"构造函数 '{class_obj._name}.__init__' 期望 {init_method.param_count} 个参数，但提供了 {num_args} 个")

        call_frame = CallFrame(
            function=self._current_function,
            return_pc=self._pc,
            local_vars=self._local_variables,
            bytecode=self._bytecode,
            constants=self._constants
        )
        
        setattr(call_frame, 'is_constructor_call', True)
        self._call_stack.append(call_frame)

        # 切换到构造函数的上下文
        self._current_function = init_method
        self._bytecode = init_method.bytecode
        self._constants = init_method.constants
        self._local_variables = [None] * init_method.local_count

        self._local_variables[0] = instance
        for i, arg in enumerate(args):
            self._local_variables[i + 1] = arg

        self._pc = -1

    @register_instruction(Opcode.SUPER_GET)
    def __handle_super_get(self):
        """
        处理 super.method() 调用。
        从栈上获取 this 实例、当前类和属性名，
        然后从当前类的父类开始查找方法。
        """
        property_name_obj = self._stack.pop()
        current_class = self._stack.pop()
        instance_obj = self._stack.pop()

        if not isinstance(property_name_obj, VBCString):
            raise TypeError(f"SUPER_GET 指令: 属性名期望 {type(VBCString)} 得到 {type(property_name_obj).__name__}")
        
        if not isinstance(current_class, VBCClass):
            raise TypeError(f"SUPER_GET 指令: 当前类期望 {type(VBCClass)} 得到 {type(current_class).__name__}")

        if not isinstance(instance_obj, VBCInstance):
            raise TypeError(f"SUPER_GET 指令: 实例期望 {type(VBCInstance)} 得到 {type(instance_obj).__name__}")

        property_name = property_name_obj.value

        # 检查当前类是否有父类
        if not current_class._super_class:
            raise AttributeError(f"类 '{current_class._name}' 没有父类，无法执行 super 调用")

        # 从父类开始查找方法 (目前只支持单继承)
        super_class = current_class._super_class[0]
        method = super_class.lookup_method(property_name)

        if method is None:
            raise AttributeError(f"父类 '{super_class._name}' 中没有名为 '{property_name}' 的方法")

        # 如果获取到的是一个方法，则创建一个绑定方法对象
        if isinstance(method, VBCFunction):
            bound_method = self._allocate(VBCBoundMethod(instance_obj, method))
            self._stack.push(bound_method)
        else:
            # super 理论上只能用于调用方法，但为了健壮性，我们也可以处理字段访问
            self._stack.push(method)

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

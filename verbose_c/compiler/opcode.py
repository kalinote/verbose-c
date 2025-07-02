from enum import Enum

class Opcode(Enum):
    """
    虚拟机操作码定义
    按功能分类组织，尽量支持完整的C语言特性
    """
    
    # === 栈操作类 (0x00-0x0F) ===
    LOAD_CONSTANT       = 0x01  # 加载常量到栈顶
    POP                 = 0x02  # 弹出栈顶元素
    DUP                 = 0x03  # 复制栈顶元素
    SWAP                = 0x04  # 交换栈顶两个元素
    
    # === 变量操作类 (0x10-0x1F) ===
    STORE_LOCAL_VAR     = 0x10  # 存储到局部变量
    LOAD_LOCAL_VAR      = 0x11  # 加载局部变量到栈顶
    LOAD_GLOBAL_VAR     = 0x12  # 加载全局变量
    STORE_GLOBAL_VAR    = 0x13  # 存储到全局变量
    
    # === 算术运算类 (0x20-0x2F) ===
    ADD                 = 0x20  # 加法运算
    SUBTRACT            = 0x21  # 减法运算
    MULTIPLY            = 0x22  # 乘法运算
    DIVIDE              = 0x23  # 除法运算
    MODULO              = 0x24  # 取模运算
    UNARY_MINUS         = 0x25  # 一元负号
    
    # === 比较运算类 (0x30-0x3F) ===
    EQUAL               = 0x30  # 等于比较
    NOT_EQUAL           = 0x31  # 不等于比较
    LESS_THAN           = 0x32  # 小于比较
    LESS_EQUAL          = 0x33  # 小于等于比较
    GREATER_THAN        = 0x34  # 大于比较
    GREATER_EQUAL       = 0x35  # 大于等于比较
    
    # === 逻辑运算类 (0x40-0x4F) ===
    LOGICAL_NOT         = 0x40  # 逻辑非运算
    
    # === 控制流类 (0x50-0x5F) ===
    JUMP                = 0x50  # 无条件跳转
    JUMP_IF_FALSE       = 0x51  # 条件跳转（假时跳转）
    RETURN              = 0x52  # 函数返回
    
    # === 函数调用类 (0x60-0x6F) ===
    CALL_FUNCTION       = 0x60  # 调用函数
    LOAD_FUNCTION       = 0x61  # 加载函数对象
    ENTER_SCOPE         = 0x62  # 进入新作用域
    EXIT_SCOPE          = 0x63  # 退出当前作用域
    
    # === 类型转换类 (0x70-0x7F) ===
    CAST                = 0x70  # 类型转换
    
    # === 内存管理类 (0x80-0x8F) ===
    ALLOC_OBJECT        = 0x80  # 分配对象内存
    FREE_OBJECT         = 0x81  # 释放对象内存
    
    # === 对象与类操作类 (0x90-0x9F) ===
    GET_PROPERTY        = 0x90  # 获取对象属性
    SET_PROPERTY        = 0x91  # 设置对象属性
    NEW_INSTANCE        = 0x92  # 创建新实例
    SUPER_GET           = 0x93  # super属性调用
    
    # === 扩展指令类 (0xA0-0xFF) ===
    NOP                 = 0xA0  # 空操作
    HALT                = 0xA1  # 停机指令
    DEBUG_PRINT         = 0xA2  # 调试输出
    
    def __str__(self):
        """返回操作码的字符串表示"""
        return f"{self.name}(0x{self.value:02X})"
    
    @classmethod
    def get_opcode_name(cls, value: int) -> str:
        """根据操作码值获取名称"""
        for opcode in cls:
            if opcode.value == value:
                return opcode.name
        return f"UNKNOWN(0x{value:02X})"

Instruction = tuple[Opcode, ...]

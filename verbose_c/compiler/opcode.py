from enum import Enum

class Opcode(Enum):
    """
    虚拟机操作码定义
    按功能分类组织，支持完整的C语言特性
    
    TODO 可能需要进一步调整优化
    """
    
    # === 栈操作类 (0x00-0x0F) ===
    LOAD_CONSTANT       = 0x00  # 加载常量到栈顶
    LOAD_LOCAL_VAR      = 0x01  # 加载局部变量到栈顶
    PUSH_NULL           = 0x02  # 推送null值到栈顶
    PUSH_TRUE           = 0x03  # 推送true值到栈顶
    PUSH_FALSE          = 0x04  # 推送false值到栈顶
    POP                 = 0x05  # 弹出栈顶元素
    DUP                 = 0x06  # 复制栈顶元素
    SWAP                = 0x07  # 交换栈顶两个元素
    
    # === 变量操作类 (0x10-0x1F) ===
    STORE_LOCAL_VAR     = 0x10  # 存储到局部变量
    LOAD_GLOBAL_VAR     = 0x11  # 加载全局变量
    STORE_GLOBAL_VAR    = 0x12  # 存储到全局变量
    DECLARE_VAR         = 0x13  # 声明变量
    
    # === 算术运算类 (0x20-0x2F) ===
    ADD                 = 0x20  # 加法运算
    SUBTRACT            = 0x21  # 减法运算
    MULTIPLY            = 0x22  # 乘法运算
    DIVIDE              = 0x23  # 除法运算
    MODULO              = 0x24  # 取模运算
    UNARY_MINUS         = 0x25  # 一元负号
    UNARY_PLUS          = 0x26  # 一元正号
    
    # === 比较运算类 (0x30-0x3F) ===
    EQUAL               = 0x30  # 等于比较
    NOT_EQUAL           = 0x31  # 不等于比较
    LESS_THAN           = 0x32  # 小于比较
    LESS_EQUAL          = 0x33  # 小于等于比较
    GREATER_THAN        = 0x34  # 大于比较
    GREATER_EQUAL       = 0x35  # 大于等于比较
    
    # === 逻辑运算类 (0x40-0x4F) ===
    LOGICAL_AND         = 0x40  # 逻辑与运算
    LOGICAL_OR          = 0x41  # 逻辑或运算
    LOGICAL_NOT         = 0x42  # 逻辑非运算
    
    # === 控制流类 (0x50-0x5F) ===
    JUMP                = 0x50  # 无条件跳转
    JUMP_IF_FALSE       = 0x51  # 条件跳转（假时跳转）
    JUMP_IF_TRUE        = 0x52  # 条件跳转（真时跳转）
    RETURN              = 0x53  # 函数返回
    RETURN_VOID         = 0x54  # 无返回值的函数返回
    BREAK               = 0x55  # 跳出循环
    CONTINUE            = 0x56  # 继续循环
    
    # === 函数调用类 (0x60-0x6F) ===
    CALL_FUNCTION       = 0x60  # 调用函数
    LOAD_FUNCTION       = 0x61  # 加载函数对象
    ENTER_SCOPE         = 0x62  # 进入新作用域
    EXIT_SCOPE          = 0x63  # 退出当前作用域
    
    # === 类型转换类 (0x70-0x7F) ===
    CAST_TO_INT         = 0x70  # 转换为整数
    CAST_TO_FLOAT       = 0x71  # 转换为浮点数
    CAST_TO_BOOL        = 0x72  # 转换为布尔值
    CAST_TO_STRING      = 0x73  # 转换为字符串
    
    # === 内存管理类 (0x80-0x8F) ===
    ALLOC_OBJECT        = 0x80  # 分配对象内存
    FREE_OBJECT         = 0x81  # 释放对象内存
    
    # === 扩展指令类 (0x90-0xFF) ===
    NOP                 = 0x90  # 空操作
    HALT                = 0x91  # 停机指令
    DEBUG_PRINT         = 0x92  # 调试输出
    
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

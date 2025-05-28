from enum import Enum

class Opcode(Enum):
    """
    TODO 虚拟机操作码定义
    """
    LOAD_CONSTANT       = 0x00
    LOAD_LOCAL_VAR      = 0x01
    PUSH_NULL           = 0x02
    PUSH_TRUE           = 0x03
    PUSH_FALSE          = 0x04

from verbose_c.object.enum import VBCObjectType
from verbose_c.vm.builtins_functions.typeof import native_typeof
from verbose_c.vm.builtins_functions.len import native_len
from verbose_c.vm.builtins_functions.io import (
    native_open,
    native_read,
    native_write,
    native_close,
    native_lseek,
    IO_CONSTANTS
)
from verbose_c.typing.types import FunctionType, IntegerType, StringType, VoidType, AnyType

# 将所有内置函数收集到一个字典中，方便注册
BUILTIN_FUNCTIONS = {
    "typeof": native_typeof,
    "len": native_len,
    
    # I/O
    'open': native_open,
    'read': native_read,
    'write': native_write,
    'close': native_close,
    'lseek': native_lseek,
}

# 内置函数的类型签名，用于编译时类型检查
# TODO: 所有 AnyType 后续可以完善为更精确的类型
BUILTIN_FUNCTION_SIGNATURES = {
    "typeof": FunctionType(param_types=[AnyType()], return_type=StringType()),
    "len": FunctionType(param_types=[AnyType()], return_type=IntegerType(VBCObjectType.NLINT)),
    
    # I/O
    'open': FunctionType(
        param_types=[StringType(), IntegerType(VBCObjectType.INT), IntegerType(VBCObjectType.INT)],
        return_type=IntegerType(VBCObjectType.INT)
    ),
    'read': FunctionType(
        param_types=[IntegerType(VBCObjectType.INT), IntegerType(VBCObjectType.INT)],
        return_type=StringType()
    ),
    'write': FunctionType(
        param_types=[IntegerType(VBCObjectType.INT), StringType()],
        return_type=IntegerType(VBCObjectType.INT)
    ),
    'close': FunctionType(
        param_types=[IntegerType(VBCObjectType.INT)],
        return_type=IntegerType(VBCObjectType.INT)
    ),
    'lseek': FunctionType(
        param_types=[IntegerType(VBCObjectType.INT), IntegerType(VBCObjectType.INT), IntegerType(VBCObjectType.INT)],
        return_type=IntegerType(VBCObjectType.INT)
    ),
}

BUILTIN_CONSTANTS = IO_CONSTANTS

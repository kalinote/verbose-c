from verbose_c.object.enum import VBCObjectType
from verbose_c.vm.builtins_functions.typeof import native_typeof
from verbose_c.vm.builtins_functions.print import native_print, native_println
from verbose_c.vm.builtins_functions.input import native_input
from verbose_c.vm.builtins_functions.len import native_len
from verbose_c.typing.types import FunctionType, IntegerType, StringType, VoidType, AnyType

# 将所有内置函数收集到一个字典中，方便注册
BUILTIN_FUNCTIONS = {
    "builtin_print": native_print,
    "builtin_println": native_println,
    "builtin_input": native_input,
    "typeof": native_typeof,
    "len": native_len
}

# 内置函数的类型签名，用于编译时类型检查
# TODO: 所有 AnyType 后续可以完善为更精确的类型
BUILTIN_FUNCTION_SIGNATURES = {
    "builtin_print": FunctionType(param_types=[AnyType()], return_type=VoidType()),
    "builtin_println": FunctionType(param_types=[AnyType()], return_type=VoidType()),
    "builtin_input": FunctionType(param_types=[StringType()], return_type=StringType()),
    "typeof": FunctionType(param_types=[AnyType()], return_type=StringType()),
    "len": FunctionType(param_types=[AnyType()], return_type=IntegerType(VBCObjectType.NLINT))
}

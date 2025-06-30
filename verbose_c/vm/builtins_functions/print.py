from verbose_c.object.t_null import VBCNull

def native_print(*args):
    """
    内置的 print 函数实现
    """
    py_args = [str(arg) for arg in args]
    print(*py_args, end="")
    return VBCNull()

def native_println(*args):
    """
    内置的 println 函数实现
    """
    py_args = [str(arg) for arg in args]
    print(*py_args)
    return VBCNull()

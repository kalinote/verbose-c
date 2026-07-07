from verbose_c.object.t_integer import VBCInteger
from verbose_c.vm.builtins_functions.system_runtime import SystemRuntime


class NativeExitSignal(Exception):
    """_exit 用于通知 VM 正常停止执行的内部信号。"""

    def __init__(self, exit_code: int):
        super().__init__(exit_code)
        self.exit_code = exit_code


def native__exit(status: VBCInteger):
    """终止当前程序并使用 status 作为退出码。"""
    if not isinstance(status, VBCInteger):
        raise TypeError("_exit 的参数必须是整数")

    raise NativeExitSignal(SystemRuntime.instance().exit_status(status.value))

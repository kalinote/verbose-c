from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_string import VBCString
from verbose_c.error.exceptions import VBCIOError
from verbose_c.vm.builtins_functions.system_runtime import SystemRuntime, SystemRuntimeError

def native_open(path_obj: VBCString, flags_obj: VBCInteger, mode_obj: VBCInteger = VBCInteger(0o777)):
    try:
        fd = SystemRuntime.instance().open(path_obj.value, flags_obj.value, mode_obj.value)
        return VBCInteger(fd)
    except SystemRuntimeError as e:
        raise VBCIOError(f"无法打开文件 '{path_obj.value}': {e}")

def native_read(fd_obj: VBCInteger, count_obj: VBCInteger):
    try:
        read_bytes = SystemRuntime.instance().read(fd_obj.value, count_obj.value)
        return VBCString(read_bytes.decode('utf-8', errors='replace'))
    except SystemRuntimeError as e:
        raise VBCIOError(f"读取文件描述符 {fd_obj.value} 失败: {e}")

def native_write(fd_obj: VBCInteger, data_obj: VBCString):
    try:
        string_to_write = str(data_obj)
        write_bytes = string_to_write.encode('utf-8')
        bytes_written = SystemRuntime.instance().write(fd_obj.value, write_bytes)
        return VBCInteger(bytes_written)
    except SystemRuntimeError as e:
        raise VBCIOError(f"写入文件描述符 {fd_obj.value} 失败: {e}")

def native_close(fd_obj: VBCInteger):
    try:
        SystemRuntime.instance().close(fd_obj.value)
        return VBCInteger(0) # C语言中，成功返回0
    except SystemRuntimeError as e:
        raise VBCIOError(f"关闭文件描述符 {fd_obj.value} 失败: {e}")

def native_lseek(fd_obj: VBCInteger, offset_obj: VBCInteger, whence_obj: VBCInteger):
    try:
        new_offset = SystemRuntime.instance().lseek(fd_obj.value, offset_obj.value, whence_obj.value)
        return VBCInteger(new_offset)
    except SystemRuntimeError as e:
        raise VBCIOError(f"移动文件描述符 {fd_obj.value} 指针失败: {e}")

IO_CONSTANTS = {
    name: VBCInteger(value)
    for name, value in SystemRuntime.instance().constants().items()
}

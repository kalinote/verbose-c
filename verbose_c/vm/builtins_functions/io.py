# verbose_c/vm/builtins_functions/io.py
import os
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_string import VBCString
from verbose_c.error.exceptions import VBCIOError

def native_open(path_obj: VBCString, flags_obj: VBCInteger, mode_obj: VBCInteger = VBCInteger(0o777)):
    try:
        fd = os.open(path_obj.value, flags_obj.value, mode_obj.value)
        return VBCInteger(fd)
    except OSError as e:
        raise VBCIOError(f"无法打开文件 '{path_obj.value}': {e.strerror}")

def native_read(fd_obj: VBCInteger, count_obj: VBCInteger):
    try:
        read_bytes = os.read(fd_obj.value, count_obj.value)
        # 将读取到的原始字节解码为字符串返回
        return VBCString(read_bytes.decode('utf-8', errors='replace'))
    except OSError as e:
        raise VBCIOError(f"读取文件描述符 {fd_obj.value} 失败: {e.strerror}")

def native_write(fd_obj: VBCInteger, data_obj: VBCString):
    try:
        # 将字符串编码为字节进行写入
        write_bytes = data_obj.value.encode('utf-8')
        bytes_written = os.write(fd_obj.value, write_bytes)
        return VBCInteger(bytes_written)
    except OSError as e:
        raise VBCIOError(f"写入文件描述符 {fd_obj.value} 失败: {e.strerror}")

def native_close(fd_obj: VBCInteger):
    try:
        os.close(fd_obj.value)
        return VBCInteger(0) # C语言中，成功返回0
    except OSError as e:
        raise VBCIOError(f"关闭文件描述符 {fd_obj.value} 失败: {e.strerror}")

def native_lseek(fd_obj: VBCInteger, offset_obj: VBCInteger, whence_obj: VBCInteger):
    try:
        new_offset = os.lseek(fd_obj.value, offset_obj.value, whence_obj.value)
        return VBCInteger(new_offset)
    except OSError as e:
        raise VBCIOError(f"移动文件描述符 {fd_obj.value} 指针失败: {e.strerror}")

# 导出所有 I/O 相关的常量
IO_CONSTANTS = {
    'O_RDONLY': VBCInteger(os.O_RDONLY),
    'O_WRONLY': VBCInteger(os.O_WRONLY),
    'O_RDWR': VBCInteger(os.O_RDWR),
    'O_CREAT': VBCInteger(os.O_CREAT),
    'O_APPEND': VBCInteger(os.O_APPEND),
    'O_TRUNC': VBCInteger(os.O_TRUNC),
    'SEEK_SET': VBCInteger(os.SEEK_SET),
    'SEEK_CUR': VBCInteger(os.SEEK_CUR),
    'SEEK_END': VBCInteger(os.SEEK_END),
}

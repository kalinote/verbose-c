"""VM 与 native 共享的标准流约定，以及 Windows VM 的系统接口适配。"""

import ctypes


MAX_READ_BYTES = 16 * 1024 * 1024
IO_ERRORS = {
    20: "读取失败：read 仅支持 STDIN（0）。",
    21: "写入失败：write 仅支持 STDOUT（1）或 STDERR（2）。",
    22: f"读取失败：长度必须介于 0 与 {MAX_READ_BYTES} 字节。",
    23: "内存分配失败。",
    24: "读取失败：Windows 输入接口返回错误。",
    25: "写入失败：Windows 输出接口返回错误。",
    26: "UTF-8 编码转换失败。",
    27: "标准流句柄无效。",
}


class WindowsStandardIO:
    """以宽字符控制台和二进制重定向实现 VM 标准流。

    控制台先按行读取 UTF-16，再缓存 UTF-8 字节；count 始终按字节计数。
    文件和管道保留换行及 NUL，已关闭管道视为 EOF。
    """

    def __init__(self):
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p
        dword = ctypes.c_ulong
        signatures = {
            "GetStdHandle": (pointer, [dword]),
            "GetConsoleMode": (ctypes.c_int, [pointer, ctypes.POINTER(dword)]),
            "ReadFile": (ctypes.c_int, [pointer, pointer, dword, ctypes.POINTER(dword), pointer]),
            "WriteFile": (ctypes.c_int, [pointer, pointer, dword, ctypes.POINTER(dword), pointer]),
            "ReadConsoleW": (ctypes.c_int, [pointer, pointer, dword, ctypes.POINTER(dword), pointer]),
            "WriteConsoleW": (ctypes.c_int, [pointer, pointer, dword, ctypes.POINTER(dword), pointer]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.kernel32, name)
            function.restype = result
            function.argtypes = arguments
        self.reset_input()

    def reset_input(self):
        """在一次 VM 执行开始时清空本次运行拥有的控制台缓冲。"""
        self.pending = b""
        self.input_handle = None
        self.console_eof = False

    def handle(self, fd):
        """读取并校验一个当前标准流句柄。"""
        handle = self.kernel32.GetStdHandle(-10 - fd)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError(IO_ERRORS[27])
        return handle

    def read(self, fd, count):
        """读取至多 count 字节，保留控制台行中尚未交付的数据。"""
        if fd != 0:
            raise OSError(IO_ERRORS[20])
        if not 0 <= count <= MAX_READ_BYTES:
            raise OSError(IO_ERRORS[22])
        handle = self.handle(fd)
        if count == 0:
            return b""
        mode = ctypes.c_ulong()
        size = ctypes.c_ulong()
        if self.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            if handle != self.input_handle:
                self.pending = b""
                self.input_handle = handle
                self.console_eof = False
            if not self.pending:
                if self.console_eof:
                    return b""
                buffer = ctypes.create_unicode_buffer(16384)
                if not self.kernel32.ReadConsoleW(handle, buffer, 16384, ctypes.byref(size), None):
                    raise OSError(ctypes.get_last_error(), IO_ERRORS[24])
                if size.value and buffer[0] == "\x1a":
                    self.console_eof = True
                    return b""
                text = buffer[:size.value].encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")
                self.pending = text.encode("utf-8")
            data, self.pending = self.pending[:count], self.pending[count:]
            return data
        buffer = ctypes.create_string_buffer(count)
        if not self.kernel32.ReadFile(handle, buffer, count, ctypes.byref(size), None):
            error = ctypes.get_last_error()
            if error not in (38, 109):
                raise OSError(error, IO_ERRORS[24])
        return buffer.raw[:size.value]

    def write(self, fd, data):
        """完整写入 UTF-8 数据；返回 UTF-8 字节数，短写继续重试。"""
        if fd not in (1, 2):
            raise OSError(IO_ERRORS[21])
        handle = self.handle(fd)
        mode = ctypes.c_ulong()
        console = bool(self.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
        payload = data.decode("utf-8", errors="replace").encode("utf-16-le") if console else data
        buffer = ctypes.create_string_buffer(payload)
        stride = 2 if console else 1
        position = 0
        while position < len(payload):
            count = min((len(payload) - position) // stride, 16384)
            written = ctypes.c_ulong()
            function = self.kernel32.WriteConsoleW if console else self.kernel32.WriteFile
            if not function(handle, ctypes.byref(buffer, position), count, ctypes.byref(written), None):
                raise OSError(ctypes.get_last_error(), IO_ERRORS[25])
            if not 0 < written.value <= count:
                raise OSError(IO_ERRORS[25])
            position += written.value * stride
        return len(data)

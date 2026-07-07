import ctypes
import ctypes.util
import errno
import platform


class SystemRuntimeError(RuntimeError):
    """底层平台适配层错误。"""


class SystemRuntime:
    """加载并封装当前平台的 libc/CRT 底层运行时入口。"""

    _instance = None

    @classmethod
    def instance(cls):
        """返回缓存的底层运行时适配实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.platform_name = platform.system().lower()
        self._libc = self._load_library()
        self._symbols = self._register_symbols()
        self._constants = self._build_constants()

    def constants(self) -> dict[str, int]:
        """返回当前平台的底层 I/O 常量表。"""
        return dict(self._constants)

    def open(self, path: str, flags: int, mode: int) -> int:
        """打开文件并返回底层文件描述符。"""
        if not isinstance(path, str):
            raise SystemRuntimeError("open 的路径参数必须是字符串")

        encoded_path = path.encode("utf-8")
        return self._call_with_errno(
            self._symbols["open"],
            ctypes.c_char_p(encoded_path),
            int(flags),
            int(mode),
            operation="打开文件",
        )

    def read(self, fd: int, count: int) -> bytes:
        """从底层文件描述符读取字节。"""
        self._validate_fd(fd)
        if count < 0:
            raise SystemRuntimeError("read 的读取长度不能为负数")
        if count == 0:
            return b""

        buffer = ctypes.create_string_buffer(count)
        bytes_read = self._call_with_errno(
            self._symbols["read"],
            int(fd),
            buffer,
            count,
            operation="读取文件描述符",
        )
        return buffer.raw[:bytes_read]

    def write(self, fd: int, data: bytes) -> int:
        """向底层文件描述符写入字节。"""
        self._validate_fd(fd)
        if not isinstance(data, bytes):
            raise SystemRuntimeError("write 的数据参数必须是字节")
        if not data:
            return 0

        buffer = ctypes.create_string_buffer(data, len(data))
        return self._call_with_errno(
            self._symbols["write"],
            int(fd),
            buffer,
            len(data),
            operation="写入文件描述符",
        )

    def close(self, fd: int) -> int:
        """关闭底层文件描述符。"""
        self._validate_fd(fd)
        return self._call_with_errno(
            self._symbols["close"],
            int(fd),
            operation="关闭文件描述符",
        )

    def lseek(self, fd: int, offset: int, whence: int) -> int:
        """移动底层文件描述符偏移。"""
        self._validate_fd(fd)
        return self._call_with_errno(
            self._symbols["lseek"],
            int(fd),
            int(offset),
            int(whence),
            operation="移动文件描述符指针",
        )

    def exit_status(self, status: int) -> int:
        """按 C int 语义归一化退出码。"""
        return ctypes.c_int(int(status)).value

    def _validate_fd(self, fd: int):
        """校验文件描述符可传入底层 CRT/libc。"""
        if int(fd) < 0:
            raise SystemRuntimeError(f"非法文件描述符: {fd}")

    def _load_library(self):
        """按平台加载 libc/CRT 动态库。"""
        candidates = self._library_candidates()
        last_error = None

        for candidate in candidates:
            try:
                return ctypes.CDLL(candidate, use_errno=True)
            except OSError as exc:
                last_error = exc

        searched = ", ".join(str(candidate) for candidate in candidates)
        raise SystemRuntimeError(f"无法加载底层运行时动态库，已尝试: {searched}; 最后错误: {last_error}")

    def _library_candidates(self) -> list[str]:
        """返回当前平台的 libc/CRT 候选库名。"""
        if self._is_windows:
            return ["ucrtbase", "msvcrt"]
        if self._is_macos:
            found = ctypes.util.find_library("c")
            return [candidate for candidate in ["libc.dylib", found] if candidate]
        if self._is_linux:
            found = ctypes.util.find_library("c")
            return [candidate for candidate in ["libc.so.6", found] if candidate]
        found = ctypes.util.find_library("c")
        if found:
            return [found]
        raise SystemRuntimeError(f"暂不支持的平台: {platform.system()}")

    def _register_symbols(self):
        """注册底层函数签名并返回符号表。"""
        symbol_names = self._symbol_names()
        symbols = {}

        for public_name, native_name in symbol_names.items():
            try:
                symbols[public_name] = getattr(self._libc, native_name)
            except AttributeError as exc:
                raise SystemRuntimeError(f"底层运行时缺少函数符号: {native_name}") from exc

        self._configure_signatures(symbols)
        return symbols

    def _symbol_names(self) -> dict[str, str]:
        """返回公开原语到平台符号名的映射。"""
        if self._is_windows:
            return {
                "open": "_open",
                "read": "_read",
                "write": "_write",
                "close": "_close",
                "lseek": "_lseek",
                "exit": "_exit",
            }
        return {
            "open": "open",
            "read": "read",
            "write": "write",
            "close": "close",
            "lseek": "lseek",
            "exit": "_exit",
        }

    def _configure_signatures(self, symbols: dict):
        """集中声明底层函数参数和返回类型。"""
        if self._is_windows:
            symbols["open"].argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
            symbols["read"].argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
            symbols["write"].argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
            symbols["lseek"].argtypes = [ctypes.c_int, ctypes.c_long, ctypes.c_int]
            symbols["open"].restype = ctypes.c_int
            symbols["read"].restype = ctypes.c_int
            symbols["write"].restype = ctypes.c_int
            symbols["lseek"].restype = ctypes.c_long
        else:
            symbols["open"].argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
            symbols["read"].argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
            symbols["write"].argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
            symbols["lseek"].argtypes = [ctypes.c_int, ctypes.c_long, ctypes.c_int]
            symbols["open"].restype = ctypes.c_int
            symbols["read"].restype = ctypes.c_ssize_t
            symbols["write"].restype = ctypes.c_ssize_t
            symbols["lseek"].restype = ctypes.c_long

        symbols["close"].argtypes = [ctypes.c_int]
        symbols["close"].restype = ctypes.c_int
        symbols["exit"].argtypes = [ctypes.c_int]
        symbols["exit"].restype = None

    def _build_constants(self) -> dict[str, int]:
        """返回当前平台可暴露给 VM 的底层常量。"""
        constants = {
            "STDIN": 0,
            "STDOUT": 1,
            "STDERR": 2,
            "O_RDONLY": 0,
            "O_WRONLY": 1,
            "O_RDWR": 2,
            "SEEK_SET": 0,
            "SEEK_CUR": 1,
            "SEEK_END": 2,
        }

        if self._is_windows:
            constants.update({
                "O_APPEND": 0x0008,
                "O_CREAT": 0x0100,
                "O_TRUNC": 0x0200,
            })
        elif self._is_macos:
            constants.update({
                "O_APPEND": 0x0008,
                "O_CREAT": 0x0200,
                "O_TRUNC": 0x0400,
            })
        else:
            constants.update({
                "O_CREAT": 0o100,
                "O_TRUNC": 0o1000,
                "O_APPEND": 0o2000,
            })

        return constants

    def _call_with_errno(self, func, *args, operation: str) -> int:
        """调用底层函数，并把 -1 返回值转换为中文错误。"""
        ctypes.set_errno(0)
        result = func(*args)
        if result == -1:
            error_code = ctypes.get_errno()
            raise SystemRuntimeError(f"{operation}失败: {self._format_errno(error_code)}")
        return result

    def _format_errno(self, error_code: int) -> str:
        """格式化 errno 错误码。"""
        if error_code == 0:
            return "未知底层运行时错误"
        error_name = errno.errorcode.get(error_code, "UNKNOWN")
        return f"errno {error_code} ({error_name})"

    @property
    def _is_windows(self) -> bool:
        return self.platform_name == "windows"

    @property
    def _is_linux(self) -> bool:
        return self.platform_name == "linux"

    @property
    def _is_macos(self) -> bool:
        return self.platform_name == "darwin"

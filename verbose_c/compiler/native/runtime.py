"""直接生成 Windows I/O 运行时；目标程序仅导入操作系统的 KERNEL32。"""

import struct
from dataclasses import replace

from verbose_c.standard_io import MAX_READ_BYTES, IO_ERRORS


RUNTIME_SIGNATURES = {
    "<native:read>": ("string", ("int64", "int64")),
    "<native:write>": ("int64", ("int64", "string")),
    "<native:equal>": ("bool64", ("string", "string")),
}
IMPORTS = (
    "GetStdHandle", "GetConsoleMode", "ReadFile", "WriteFile",
    "ReadConsoleW", "WriteConsoleW", "MultiByteToWideChar", "WideCharToMultiByte",
    "HeapCreate", "HeapAlloc", "HeapFree", "HeapDestroy", "GetLastError", "ExitProcess",
)
_REGISTERS = {name: index for index, name in enumerate(
    ("rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
     "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15")
)}


class RuntimeAssembler:
    """生成位置无关的 x64 代码，记录代码、常量和 IAT 的相对引用。

    所有函数使用 192 字节栈帧，前 64 字节留给 Windows 参数窗口。
    R12 指向本次执行的堆和控制台缓冲状态；R11 保存语言的全局帧指针。
    """

    def __init__(self, code, functions):
        self.code = code
        self.functions = functions
        self.labels = {name: function.offset for name, function in functions.items()}
        self.references = []
        self.rodata = bytearray()
        self.constants = {}
        self.function_start = 0
        self.function_name = ""

    def emit(self, hex_code):
        """追加一组固定指令字节。"""
        self.code.extend(bytes.fromhex(hex_code))

    def mov(self, destination, source):
        """将立即数、寄存器或内存值装入寄存器。"""
        target = _REGISTERS[destination]
        if isinstance(source, tuple):
            self.mem("8b", destination, *source)
        elif isinstance(source, int):
            self.code.extend(bytes((0x48 | (target >> 3), 0xB8 | (target & 7))))
            self.code.extend(struct.pack("<Q", source & ((1 << 64) - 1)))
        else:
            value = _REGISTERS[source]
            self.code.extend(bytes((0x48 | ((value >> 3) << 2) | (target >> 3),
                                    0x89, 0xC0 | ((value & 7) << 3) | (target & 7))))

    def mem(self, opcode, register, base, offset=0):
        """编码带 disp32 的内存读取、写入或取址。"""
        value, address = _REGISTERS[register], _REGISTERS[base]
        self.code.extend(bytes((0x48 | ((value >> 3) << 2) | (address >> 3), int(opcode, 16),
                                0x80 | ((value & 7) << 3) | (address & 7))))
        if address & 7 == 4:
            self.code.append(0x24)
        self.code.extend(struct.pack("<i", offset))

    def branch(self, target, condition=None):
        """记录直接或条件跳转，链接时回填 rel32。"""
        prefix = b"\xe9" if condition is None else bytes((0x0F, condition))
        self.code.extend(prefix)
        self.references.append((len(self.code), "code", target))
        self.code.extend(bytes(4))

    def call(self, name):
        """生成内部函数调用。"""
        self.code.append(0xE8)
        self.references.append((len(self.code), "code", name))
        self.code.extend(bytes(4))

    def api(self, name, arguments):
        """按 Windows x64 ABI 放置参数并通过 IAT 调用系统接口。"""
        for index, value in enumerate(arguments):
            if index < 4:
                self.mov(("rcx", "rdx", "r8", "r9")[index], value)
            else:
                self.mov("rax", value)
                self.mem("89", "rax", "rsp", 32 + (index - 4) * 8)
        self.emit("ff 15")
        self.references.append((len(self.code), "import", name))
        self.code.extend(bytes(4))
        if name not in {"GetStdHandle", "HeapCreate", "HeapAlloc", "ExitProcess"}:
            self.emit("89 c0")

    def address(self, register, value, *, wide=False):
        """装入带字节长度的 UTF-8 常量或 UTF-16 诊断文本的地址。"""
        key = (value, wide)
        if key not in self.constants:
            self.rodata.extend(bytes((-len(self.rodata)) % 8))
            self.constants[key] = len(self.rodata)
            payload = value.encode("utf-16-le" if wide else "utf-8")
            self.rodata.extend(payload if wide else struct.pack("<Q", len(payload)) + payload)
        reg = _REGISTERS[register]
        self.code.extend(bytes((0x48 | ((reg >> 3) << 2), 0x8D, 0x05 | ((reg & 7) << 3))))
        self.references.append((len(self.code), "constant", self.constants[key]))
        self.code.extend(bytes(4))

    def begin(self, name):
        """开始一个保存全局帧指针的运行时函数。"""
        self.function_name = name
        self.function_start = len(self.code)
        self.labels[name] = len(self.code)
        self.emit("55 48 89 e5 48 81 ec c0 00 00 00")
        self.mem("89", "r11", "rbp", -8)

    def end(self):
        """结束函数并登记供清单、调用和符号校验使用的元数据。"""
        from verbose_c.compiler.native.codegen import NativeCodeFunction, NativeCodeInstruction, NativeRegisterAllocation

        self.labels[self.function_name + ":return"] = len(self.code)
        self.mem("8b", "r11", "rbp", -8)
        self.emit("48 89 ec 5d c3")
        return_type, param_types = RUNTIME_SIGNATURES.get(self.function_name, ("int64", ()))
        payload = bytes(self.code[self.function_start:])
        self.functions[self.function_name] = NativeCodeFunction(
            name=self.function_name, code=payload, offset=self.function_start, frame_size=192,
            instructions=[NativeCodeInstruction(self.function_start, payload, self.function_name, "runtime")],
            register_allocation=NativeRegisterAllocation(argument_registers=("RCX", "RDX", "R8", "R9")[:len(param_types)]),
            return_type=return_type, param_types=param_types,
        )

    def fail(self, code):
        """返回可传播的运行时错误，并保存 Windows 错误码。"""
        self.labels[self.function_name + f":error{code}"] = len(self.code)
        self.api("GetLastError", [])
        self.mem("89", "rax", "r12", 32)
        self.mov("rax", 1)
        self.mov("rdx", code)
        self.branch(self.function_name + ":return")

    def check(self, code):
        """把空指针或 FALSE 结果转为指定运行时错误。"""
        self.emit("48 85 c0")
        self.branch(self.function_name + f":error{code}", 0x84)


def append_runtime(code, functions, entry_name):
    """追加运行时并链接系统接口和常量引用。

    输入字符串在私有堆中存活至本次程序结束，退出时统一销毁，允许跨函数别名。

    Args:
        code: 已有用户函数机器码，原地追加运行时。
        functions: 待更新的函数表。
        entry_name: 用户程序的入口函数名。

    Returns:
        只读数据、导入布局、PE 入口及相对地址修补记录。
    """
    a = RuntimeAssembler(code, functions)
    for function in list(functions.values()):
        for instruction in function.instructions:
            if instruction.source_op == "load_string" and "value" in instruction.source_attrs:
                value = instruction.source_attrs["value"]
                key = (value, False)
                if key not in a.constants:
                    a.rodata.extend(bytes((-len(a.rodata)) % 8))
                    a.constants[key] = len(a.rodata)
                    payload = value.encode("utf-8")
                    a.rodata.extend(struct.pack("<Q", len(payload)) + payload)
                a.references.append((instruction.offset + 3, "constant", a.constants[key]))

    # UTF-16 转为带长度的 UTF-8 字符串。
    a.begin("<native:utf8>")
    a.mem("89", "rcx", "rbp", -16)
    a.mem("89", "rdx", "rbp", -24)
    a.emit("48 85 d2")
    a.branch("utf8:empty", 0x84)
    a.api("WideCharToMultiByte", [65001, 0, ("rbp", -16), ("rbp", -24), 0, 0, 0, 0])
    a.check(26)
    a.mem("89", "rax", "rbp", -32)
    a.emit("48 83 c0 08")
    a.mov("r8", "rax")
    a.api("HeapAlloc", [("r12", 0), 0, "r8"])
    a.check(23)
    a.mem("89", "rax", "rbp", -40)
    a.mov("r10", ("rbp", -32))
    a.mem("89", "r10", "rax")
    a.emit("48 83 c0 08")
    a.mem("89", "rax", "rbp", -48)
    a.api("WideCharToMultiByte", [65001, 0, ("rbp", -16), ("rbp", -24), ("rbp", -48), ("rbp", -32), 0, 0])
    a.check(26)
    a.mov("rax", ("rbp", -40))
    a.emit("31 d2")
    a.branch("<native:utf8>:return")
    a.labels["utf8:empty"] = len(code)
    a.address("rax", "")
    a.emit("31 d2")
    a.branch("<native:utf8>:return")
    a.fail(23)
    a.fail(26)
    a.end()

    # 每次读取独立解码，非法或被 count 截断的 UTF-8 使用 U+FFFD。
    a.begin("<native:decode>")
    a.mem("89", "rcx", "rbp", -16)
    a.mem("89", "rdx", "rbp", -24)
    a.emit("48 85 d2")
    a.branch("decode:empty", 0x84)
    a.mov("rax", "rdx")
    a.emit("48 6b c0 03 48 83 c0 08")
    a.mov("r8", "rax")
    a.api("HeapAlloc", [("r12", 0), 0, "r8"])
    a.check(23)
    a.mem("89", "rax", "rbp", -32)
    a.mov("r9", "rax")
    a.emit("49 83 c1 08")
    a.mov("r10", ("rbp", -16))
    a.mov("r8", ("rbp", -24))
    a.labels["decode:loop"] = len(code)
    a.emit("4d 85 c0")
    a.branch("decode:done", 0x84)
    a.emit("41 0f b6 02 3c 80")
    a.branch("decode:ascii", 0x82)
    a.emit("3c c2")
    a.branch("decode:invalid", 0x82)
    a.emit("3c f4")
    a.branch("decode:invalid", 0x87)
    a.mov("r11", 2)
    a.emit("3c e0")
    a.branch("decode:second", 0x82)
    a.mov("r11", 3)
    a.emit("3c f0")
    a.branch("decode:second", 0x82)
    a.mov("r11", 4)
    a.labels["decode:second"] = len(code)
    a.emit("49 83 f8 02")
    a.branch("decode:invalid", 0x82)
    a.emit("41 0f b6 52 01 80 fa 80")
    a.branch("decode:invalid", 0x82)
    a.emit("80 fa bf")
    a.branch("decode:invalid", 0x87)
    # 拒绝过长编码、代理码点和超出 U+10FFFF 的编码；仅消耗首字节。
    for leading, bound, condition in ((0xE0, 0xA0, 0x82), (0xED, 0x9F, 0x87),
                                       (0xF0, 0x90, 0x82), (0xF4, 0x8F, 0x87)):
        a.emit(f"3c {leading:02x}")
        a.branch(f"decode:range{leading}", 0x85)
        a.emit(f"80 fa {bound:02x}")
        a.branch("decode:invalid", condition)
        a.labels[f"decode:range{leading}"] = len(code)
    a.mov("rcx", 2)
    a.labels["decode:continuation"] = len(code)
    a.emit("4c 39 d9")
    a.branch("decode:valid", 0x84)
    a.emit("4c 39 c1")
    a.branch("decode:replace", 0x83)
    a.emit("41 0f b6 14 0a 80 fa 80")
    a.branch("decode:replace", 0x82)
    a.emit("80 fa bf")
    a.branch("decode:replace", 0x87)
    a.emit("48 ff c1")
    a.branch("decode:continuation")
    a.labels["decode:valid"] = len(code)
    a.mov("rdx", "rcx")
    a.labels["decode:copy"] = len(code)
    a.emit("41 8a 02 41 88 01 49 ff c1 49 ff c2 49 ff c8 48 ff ca")
    a.branch("decode:copy", 0x85)
    a.branch("decode:loop")
    a.labels["decode:ascii"] = len(code)
    a.emit("41 88 01 49 ff c1 49 ff c2 49 ff c8")
    a.branch("decode:loop")
    a.labels["decode:invalid"] = len(code)
    a.mov("rcx", 1)
    a.labels["decode:replace"] = len(code)
    a.emit("66 41 c7 01 ef bf 41 c6 41 02 bd 49 83 c1 03 49 01 ca 49 29 c8")
    a.branch("decode:loop")
    a.labels["decode:done"] = len(code)
    a.mov("rax", ("rbp", -32))
    a.mov("rcx", "r9")
    a.emit("48 29 c1 48 83 e9 08")
    a.mem("89", "rcx", "rax")
    a.emit("31 d2")
    a.branch("<native:decode>:return")
    a.labels["decode:empty"] = len(code)
    a.address("rax", "")
    a.emit("31 d2")
    a.branch("<native:decode>:return")
    a.fail(23)
    a.end()

    a.begin("<native:read>")
    a.mem("89", "rdx", "rbp", -16)
    a.emit("48 85 c9")
    a.branch("<native:read>:error20", 0x85)
    a.mov("rax", MAX_READ_BYTES)
    a.emit("48 39 c2")
    a.branch("<native:read>:error22", 0x87)
    a.api("GetStdHandle", [-10])
    a.check(27)
    a.emit("48 83 f8 ff")
    a.branch("<native:read>:error27", 0x84)
    a.mem("89", "rax", "rbp", -24)
    a.mov("rax", ("rbp", -16))
    a.emit("48 85 c0")
    a.branch("read:empty", 0x84)
    a.mem("8d", "rdx", "rbp", -32)
    a.api("GetConsoleMode", [("rbp", -24), "rdx"])
    a.emit("85 c0")
    a.branch("read:file", 0x84)
    a.mov("rax", ("r12", 40))
    a.emit("48 85 c0")
    a.branch("read:empty", 0x85)
    a.mov("rax", ("r12", 24))
    a.mov("r10", ("r12", 16))
    a.emit("4c 39 d0")
    a.branch("read:pending", 0x82)
    a.mov("rax", ("r12", 8))
    a.emit("48 85 c0")
    a.branch("read:console", 0x84)
    a.api("HeapFree", [("r12", 0), 0, ("r12", 8)])
    a.mov("rax", 0)
    a.mem("89", "rax", "r12", 8)
    a.labels["read:console"] = len(code)
    a.api("HeapAlloc", [("r12", 0), 0, 32768])
    a.check(23)
    a.mem("89", "rax", "rbp", -40)
    a.mov("rax", 0)
    a.mem("89", "rax", "rbp", -48)
    a.mem("8d", "r9", "rbp", -48)
    a.api("ReadConsoleW", [("rbp", -24), ("rbp", -40), 16384, "r9", 0])
    a.check(24)
    a.mov("rax", ("rbp", -48))
    a.emit("48 85 c0")
    a.branch("read:console_convert", 0x84)
    a.mov("rax", ("rbp", -40))
    a.emit("66 83 38 1a")
    a.branch("read:console_convert", 0x85)
    a.mov("rax", 1)
    a.mem("89", "rax", "r12", 40)
    a.api("HeapFree", [("r12", 0), 0, ("rbp", -40)])
    a.branch("read:empty")
    a.labels["read:console_convert"] = len(code)
    a.mov("rcx", ("rbp", -40))
    a.mov("rdx", ("rbp", -48))
    a.call("<native:utf8>")
    a.mem("89", "rax", "rbp", -56)
    a.mem("89", "rdx", "rbp", -64)
    a.api("HeapFree", [("r12", 0), 0, ("rbp", -40)])
    a.mov("rax", ("rbp", -56))
    a.mov("rdx", ("rbp", -64))
    a.emit("48 85 d2")
    a.branch("<native:read>:return", 0x85)
    a.mov("r10", ("rax", 0))
    a.emit("4d 85 d2")
    a.branch("read:empty", 0x84)
    a.mem("89", "rax", "r12", 8)
    a.mem("89", "r10", "r12", 16)
    a.mov("rax", 0)
    a.mem("89", "rax", "r12", 24)
    a.labels["read:pending"] = len(code)
    a.mov("rcx", ("r12", 8))
    a.mov("rax", ("r12", 24))
    a.emit("48 01 c1 48 83 c1 08")
    a.mov("rdx", ("r12", 16))
    a.emit("48 29 c2")
    a.mov("r10", ("rbp", -16))
    a.emit("4c 39 d2 49 0f 47 d2 48 01 d0")
    a.mem("89", "rax", "r12", 24)
    a.call("<native:decode>")
    a.branch("<native:read>:return")
    a.labels["read:file"] = len(code)
    a.api("HeapAlloc", [("r12", 0), 0, ("rbp", -16)])
    a.check(23)
    a.mem("89", "rax", "rbp", -40)
    a.mov("rax", 0)
    a.mem("89", "rax", "rbp", -48)
    a.mem("8d", "r9", "rbp", -48)
    a.api("ReadFile", [("rbp", -24), ("rbp", -40), ("rbp", -16), "r9", 0])
    a.emit("85 c0")
    a.branch("read:decode", 0x85)
    a.api("GetLastError", [])
    a.emit("83 f8 6d")
    a.branch("read:decode", 0x84)
    a.emit("83 f8 26")
    a.branch("<native:read>:error24", 0x85)
    a.labels["read:decode"] = len(code)
    a.mov("rcx", ("rbp", -40))
    a.mov("rdx", ("rbp", -48))
    a.call("<native:decode>")
    a.mem("89", "rax", "rbp", -56)
    a.mem("89", "rdx", "rbp", -64)
    a.api("HeapFree", [("r12", 0), 0, ("rbp", -40)])
    a.mov("rax", ("rbp", -56))
    a.mov("rdx", ("rbp", -64))
    a.branch("<native:read>:return")
    a.labels["read:empty"] = len(code)
    a.address("rax", "")
    a.emit("31 d2")
    a.branch("<native:read>:return")
    for error in (20, 22, 23, 24, 27):
        a.fail(error)
    a.end()

    a.begin("<native:write>")
    a.mem("89", "rdx", "rbp", -16)
    a.emit("48 ff c9 48 83 f9 01")
    a.branch("<native:write>:error21", 0x87)
    a.emit("48 f7 d9 48 83 e9 0b")
    a.api("GetStdHandle", ["rcx"])
    a.check(27)
    a.emit("48 83 f8 ff")
    a.branch("<native:write>:error27", 0x84)
    a.mem("89", "rax", "rbp", -24)
    a.mov("rax", ("rbp", -16))
    a.mov("r10", ("rax", 0))
    a.mem("89", "r10", "rbp", -32)
    a.mem("89", "r10", "rbp", -40)
    a.emit("48 83 c0 08")
    a.mem("89", "rax", "rbp", -48)
    a.mov("rax", 0)
    a.mem("89", "rax", "rbp", -56)
    a.emit("4d 85 d2")
    a.branch("write:success", 0x84)
    a.mem("8d", "rdx", "rbp", -64)
    a.api("GetConsoleMode", [("rbp", -24), "rdx"])
    a.mem("89", "rax", "rbp", -72)
    a.emit("85 c0")
    a.branch("write:loop", 0x84)
    a.mov("rax", ("rbp", -32))
    a.emit("48 d1 e0 48 83 c0 02")
    a.mov("r8", "rax")
    a.api("HeapAlloc", [("r12", 0), 0, "r8"])
    a.check(23)
    a.mem("89", "rax", "rbp", -56)
    a.api("MultiByteToWideChar", [65001, 0, ("rbp", -48), ("rbp", -32), ("rbp", -56), ("rbp", -32)])
    a.check(26)
    a.mem("89", "rax", "rbp", -40)
    a.mov("rax", ("rbp", -56))
    a.mem("89", "rax", "rbp", -48)
    a.labels["write:loop"] = len(code)
    a.mov("rax", 0)
    a.mem("89", "rax", "rbp", -80)
    a.mov("r8", ("rbp", -40))
    a.mov("rax", 16384)
    a.emit("49 39 c0 4c 0f 47 c0")
    a.mem("8d", "r9", "rbp", -80)
    a.mov("rax", ("rbp", -72))
    a.emit("85 c0")
    a.branch("write:file", 0x84)
    a.api("WriteConsoleW", [("rbp", -24), ("rbp", -48), "r8", "r9", 0])
    a.branch("write:check")
    a.labels["write:file"] = len(code)
    a.api("WriteFile", [("rbp", -24), ("rbp", -48), "r8", "r9", 0])
    a.labels["write:check"] = len(code)
    a.check(25)
    a.mov("rax", ("rbp", -80))
    a.check(25)
    a.mov("r10", ("rbp", -40))
    a.emit("49 29 c2")
    a.mem("89", "r10", "rbp", -40)
    a.mov("r10", ("rbp", -72))
    a.emit("4d 85 d2")
    a.branch("write:advance", 0x84)
    a.emit("48 d1 e0")
    a.labels["write:advance"] = len(code)
    a.mov("r10", ("rbp", -48))
    a.emit("49 01 c2")
    a.mem("89", "r10", "rbp", -48)
    a.mov("rax", ("rbp", -40))
    a.emit("48 85 c0")
    a.branch("write:loop", 0x85)
    a.mov("rax", ("rbp", -56))
    a.emit("48 85 c0")
    a.branch("write:success", 0x84)
    a.api("HeapFree", [("r12", 0), 0, ("rbp", -56)])
    a.labels["write:success"] = len(code)
    a.mov("rax", ("rbp", -32))
    a.emit("31 d2")
    a.branch("<native:write>:return")
    for error in (21, 23, 25, 26, 27):
        a.fail(error)
    a.end()

    a.begin("<native:equal>")
    a.mov("r8", ("rcx", 0))
    a.mov("r9", ("rdx", 0))
    a.emit("31 c0 4d 39 c8")
    a.branch("equal:done", 0x85)
    a.emit("48 83 c1 08 48 83 c2 08")
    a.labels["equal:loop"] = len(code)
    a.emit("4d 85 c0")
    a.branch("equal:true", 0x84)
    a.emit("44 8a 09 44 3a 0a")
    a.branch("equal:done", 0x85)
    a.emit("48 ff c1 48 ff c2 49 ff c8")
    a.branch("equal:loop")
    a.labels["equal:true"] = len(code)
    a.mov("rax", 1)
    a.labels["equal:done"] = len(code)
    a.emit("31 d2")
    a.end()

    a.begin("<native:diagnostic>")
    a.mem("89", "rcx", "rbp", -64)
    for status in (2, *IO_ERRORS):
        a.mov("rax", status)
        a.emit("48 39 c1")
        a.branch(f"diagnostic:{status}", 0x84)
    a.branch("diagnostic:2")
    for status, message in {2: "数值运算失败。", **IO_ERRORS}.items():
        a.labels[f"diagnostic:{status}"] = len(code)
        a.address("rax", message + "\n")
        a.mem("89", "rax", "rbp", -16)
        a.address("rax", message + "\n", wide=True)
        a.mem("89", "rax", "rbp", -24)
        a.mov("rax", len(message) + 1)
        a.mem("89", "rax", "rbp", -32)
        a.branch("diagnostic:print")
    a.labels["diagnostic:print"] = len(code)
    a.api("GetStdHandle", [-12])
    a.mem("89", "rax", "rbp", -40)
    a.mem("8d", "rdx", "rbp", -48)
    a.api("GetConsoleMode", [("rbp", -40), "rdx"])
    a.emit("85 c0")
    a.branch("diagnostic:file", 0x84)
    a.mem("8d", "r9", "rbp", -56)
    a.api("WriteConsoleW", [("rbp", -40), ("rbp", -24), ("rbp", -32), "r9", 0])
    a.branch("diagnostic:system_error")
    a.labels["diagnostic:file"] = len(code)
    a.mov("rax", ("rbp", -16))
    a.mov("r8", ("rax", 0))
    a.emit("48 83 c0 08")
    a.mem("89", "rax", "rbp", -24)
    a.mem("8d", "r9", "rbp", -56)
    a.api("WriteFile", [("rbp", -40), ("rbp", -24), "r8", "r9", 0])
    a.labels["diagnostic:system_error"] = len(code)
    a.mov("rax", ("rbp", -64))
    a.emit("48 83 f8 18")
    a.branch("<native:diagnostic>:return", 0x82)
    a.mov("rax", int.from_bytes(b"Win32=0x", "little"))
    a.mem("89", "rax", "rbp", -112)
    a.mem("8d", "r9", "rbp", -104)
    a.mov("r10", ("r12", 32))
    a.address("rdx", "0123456789ABCDEF")
    a.emit("48 83 c2 08")
    a.mov("rcx", 28)
    a.labels["diagnostic:hex"] = len(code)
    a.mov("rax", "r10")
    a.emit("48 d3 e8 48 83 e0 0f 8a 04 02 41 88 01 49 ff c1 48 83 e9 04")
    a.branch("diagnostic:hex", 0x89)
    a.emit("41 c6 01 0a")
    a.mem("8d", "rdx", "rbp", -112)
    a.mem("8d", "r9", "rbp", -56)
    a.api("WriteFile", [("rbp", -40), "rdx", 17, "r9", 0])
    a.end()

    a.begin("<native:start>")
    a.mem("89", "r12", "rbp", -16)
    a.mem("8d", "r12", "rbp", -112)
    a.mov("rax", 0)
    for offset in range(0, 48, 8):
        a.mem("89", "rax", "r12", offset)
    a.api("HeapCreate", [0, 0, 0])
    a.check(23)
    a.mem("89", "rax", "r12", 0)
    a.call(entry_name)
    a.branch("start:cleanup")
    a.labels["<native:start>:error23"] = len(code)
    a.mov("rax", 1)
    a.mov("rdx", 23)
    a.labels["start:cleanup"] = len(code)
    a.mem("89", "rax", "rbp", -24)
    a.mem("89", "rdx", "rbp", -32)
    a.emit("48 83 fa 02")
    a.branch("start:destroy", 0x82)
    a.mov("rcx", "rdx")
    a.call("<native:diagnostic>")
    a.labels["start:destroy"] = len(code)
    a.mov("rax", ("r12", 0))
    a.emit("48 85 c0")
    a.branch("start:restore", 0x84)
    a.api("HeapDestroy", [("r12", 0)])
    a.labels["start:restore"] = len(code)
    a.mov("rax", ("rbp", -24))
    a.mov("rdx", ("rbp", -32))
    a.mov("r12", ("rbp", -16))
    a.end()

    a.begin("<native:pe_start>")
    a.call("<native:start>")
    a.mov("rcx", "rax")
    a.emit("48 83 fa 02")
    a.branch("pe:exit", 0x82)
    a.mov("rcx", 1)
    a.labels["pe:exit"] = len(code)
    a.api("ExitProcess", ["rcx"])
    a.emit("0f 0b")
    a.end()

    rdata_rva = 4096 + ((len(code) + 4095) // 4096) * 4096
    idata_rva = rdata_rva + max(4096, ((len(a.rodata) + 4095) // 4096) * 4096)
    idata, iat_offsets = build_import_table(idata_rva)
    references = []
    for patch, kind, target in a.references:
        destination = (a.labels[target] + 4096 if kind == "code" else
                       rdata_rva + target if kind == "constant" else
                       idata_rva + iat_offsets[target])
        struct.pack_into("<i", code, patch, destination - (4096 + patch + 4))
        references.append((patch, kind, destination))
    for function in functions.values():
        function.code = bytes(code[function.offset:function.offset + len(function.code)])
        function.instructions = [replace(item, code=bytes(code[item.offset:item.offset + len(item.code)]))
                                 for item in function.instructions]
    return {"rodata": bytes(a.rodata), "idata": idata, "rdata_rva": rdata_rva,
            "idata_rva": idata_rva, "iat_offsets": iat_offsets,
            "pe_entry_offset": a.labels["<native:pe_start>"],
            "references": references}


def build_import_table(rva):
    """构造 KERNEL32 的描述符、ILT、IAT 和按名称导入表。"""
    lookup = 40
    iat = lookup + (len(IMPORTS) + 1) * 8
    data = bytearray(iat + (len(IMPORTS) + 1) * 8)
    dll_name = len(data)
    data.extend(b"KERNEL32.dll\0")
    offsets = {}
    for index, name in enumerate(IMPORTS):
        data.extend(bytes((-len(data)) % 2))
        name_rva = rva + len(data)
        data.extend(b"\0\0" + name.encode("ascii") + b"\0")
        struct.pack_into("<Q", data, lookup + index * 8, name_rva)
        struct.pack_into("<Q", data, iat + index * 8, name_rva)
        offsets[name] = iat + index * 8
    struct.pack_into("<IIIII", data, 0, rva + lookup, 0, 0, rva + dll_name, rva + iat)
    return bytes(data), offsets

import os
import subprocess
import sys
import json
import copy
import struct
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from verbose_c.compiler.native import NativeCodegenError, validate_native_code_map_bytes, validate_native_pe_image_bytes
from verbose_c.compiler.native.runner import run_native_bytes_in_memory
from verbose_c.engine.engine import run_source_file
from verbose_c.engine.native_exporter import NativeExportKind, NativeExportRequest


GREETING = '''int main() {
    write(STDOUT, "请输入你的名字：");
    string name = read(STDIN, 1024);
    write(STDOUT, "你好，");
    write(STDOUT, name);
    return 0;
}
'''


def compile_io(tmp_path, source, optimization_level=0):
    """编译 I/O 验收代码并返回独立 PE 路径。"""
    path = tmp_path / f"io_O{optimization_level}.vbc"
    output = path.with_suffix(".exe")
    path.write_text(source, encoding="utf-8")
    result = run_source_file(
        str(path), log_modules=set(), dump_modules=set(), execute=False,
        optimize_level=optimization_level,
        native_export_request=NativeExportRequest(outputs={
            NativeExportKind.PE_IMAGE: str(output),
            NativeExportKind.MAP: str(output.with_suffix(".json")),
            NativeExportKind.RAW_BINARY: str(output.with_suffix(".bin")),
        }),
    )
    assert result.success, result.error
    return output


@pytest.mark.skipif(os.name != "nt", reason="独立 PE 执行需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
def test_native_chinese_greeting(tmp_path, optimization_level):
    """中文提示、UTF-8 重定向和优化级别保持一致。"""
    output = compile_io(tmp_path, GREETING, optimization_level)
    completed = subprocess.run([str(output)], input="小明\n".encode("utf-8"), capture_output=True, timeout=10)
    assert completed.returncode == 0
    assert completed.stdout.decode("utf-8") == "请输入你的名字：你好，小明\n"
    assert completed.stderr == b""


@pytest.mark.skipif(os.name != "nt", reason="标准流对照需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
@pytest.mark.parametrize(("source", "data", "expected", "status"), [
    (GREETING, b"", "请输入你的名字：你好，", 0),
    ('int main() { string s = read(STDIN, 100); write(STDOUT, s); return 0; }',
     "中文😀\r\n反斜杠\\n\\t".encode("utf-8") + b"\0\xff\xe4", "中文😀\r\n反斜杠\\n\\t\0��", 0),
    ('int main() { write(STDOUT, read(STDIN, 1)); write(STDOUT, read(STDIN, 2)); return 0; }',
     "中".encode("utf-8"), "���", 0),
    ('int main() { string s = read(STDIN, 0); if (s == "") { return 7; } return 1; }',
     b"abc", "", 7),
    ('string input() { return read(STDIN, 10); } string same(string s) { return s; } '
     'int main() { string a = input(); string b = a; a = "覆盖"; write(STDOUT, same(b)); return 0; }',
     "别名".encode("utf-8"), "别名", 0),
    ('string prefix = "全局"; int suffix = 3; int main() { write(STDOUT, prefix); '
     'string s = read(STDIN, 10); write(STDOUT, s); return suffix; }',
     b"ok", "全局ok", 3),
    ('void stop() { write(STDOUT, "退出"); exit(9); } int main() { stop(); write(STDOUT, "错误"); return 0; }',
     b"", "退出", 9),
    ('int main() { return write(STDOUT, "中文😀"); }', b"", "中文😀", 10),
    ('int main() { string s = read(STDIN, 10); if (s != "") { write(STDOUT, s); } return 0; }',
     b"", "", 0),
    ('string fifth(int a, int b, int c, int d, string text) { return text; } '
     'int main() { string s = read(STDIN, 100); write(STDOUT, fifth(1, 2, 3, 4, s)); return 0; }',
     "栈参数".encode("utf-8"), "栈参数", 0),
])
def test_vm_native_standard_streams(tmp_path, optimization_level, source, data, expected, status):
    """独立进程对照 VM 和 PE 的字节内容、EOF、别名及退出语义。"""
    output = compile_io(tmp_path, source, optimization_level)
    commands = ([str(output)], [sys.executable, "-m", "verbose_c.cli", str(output.with_suffix(".vbc")), f"-O{optimization_level}"])
    for command in commands:
        completed = subprocess.run(command, input=data, capture_output=True, timeout=10)
        assert completed.returncode == status, completed.stderr.decode("utf-8", errors="replace")
        assert completed.stdout == expected.encode("utf-8")
        assert completed.stderr == b""


@pytest.mark.skipif(os.name != "nt", reason="PE 执行需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
@pytest.mark.parametrize(("expression", "message"), [
    ('read(STDOUT, 1)', "读取失败"),
    ('read(STDIN, -1)', "读取失败"),
    ('read(STDIN, 16777217)', "读取失败"),
    ('write(STDIN, "失败")', "写入失败"),
])
def test_vm_native_io_errors(tmp_path, optimization_level, expression, message):
    """I/O 失败进入标准错误流并停止执行，进程退出码为 1。"""
    source = f'int main() {{ {expression}; write(STDOUT, "不应执行"); return 0; }}'
    output = compile_io(tmp_path, source, optimization_level)
    for command in ([str(output)], [sys.executable, "-m", "verbose_c.cli", str(output.with_suffix(".vbc")), f"-O{optimization_level}"]):
        completed = subprocess.run(command, input=b"", capture_output=True, timeout=10)
        assert completed.returncode == 1
        assert completed.stdout == b""
        assert message in completed.stderr.decode("utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PE 执行需要 Windows")
def test_native_large_redirect_and_stderr(tmp_path):
    """大块输出完整写入，STDERR 与 STDOUT 可独立重定向。"""
    text = "中文😀" * 10000
    output = compile_io(tmp_path, f'int main() {{ write(STDERR, "诊断"); return write(STDOUT, "{text}"); }}', 1)
    completed = subprocess.run([str(output)], capture_output=True, timeout=10)
    assert completed.returncode == len(text.encode("utf-8"))
    assert completed.stdout == text.encode("utf-8")
    assert completed.stderr.decode("utf-8") == "诊断"


def test_native_imports_and_image_integrity(tmp_path):
    """PE 含独立只读数据和 IAT，损坏数据、导入或地址时校验失败。"""
    output = compile_io(tmp_path, GREETING)
    metadata = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    image = output.read_bytes()
    code = output.with_suffix(".bin").read_bytes()
    assert metadata["schema_version"] == 2
    assert [section["name"] for section in metadata["sections"]] == [".text", ".rdata", ".idata"]
    assert all(section["pe_section_header"]["Characteristics"] & 0xA0000000 != 0xA0000000 for section in metadata["sections"])
    idata = metadata["sections"][2]
    offset = idata["pe_raw_pointer"]
    descriptor = struct.unpack_from("<IIIII", image, offset)
    dll_offset = offset + descriptor[3] - idata["rva"]
    assert image[dll_offset:dll_offset + 13] == b"KERNEL32.dll\0"
    assert set(metadata["runtime"]["iat_offsets"]) >= {"ReadConsoleW", "WriteConsoleW", "ReadFile", "WriteFile", "HeapDestroy", "ExitProcess"}
    validate_native_pe_image_bytes(image, metadata)
    for section in metadata["sections"]:
        damaged = bytearray(image)
        damaged[section["pe_raw_pointer"]] ^= 1
        with pytest.raises(NativeCodegenError):
            validate_native_pe_image_bytes(bytes(damaged), metadata)
    damaged_map = copy.deepcopy(metadata)
    damaged_map["runtime"]["idata_rva"] += 4096
    with pytest.raises(NativeCodegenError):
        validate_native_code_map_bytes(code, damaged_map)


@pytest.mark.skipif(os.name != "nt", reason="内存执行需要 Windows")
@pytest.mark.parametrize("mode", ["--run-native-memory", "--run-native-bin-memory"])
def test_runtime_memory_loader(tmp_path, mode):
    """进程内执行解析同一份 IAT 和常量，不依赖 PE loader。"""
    output = compile_io(tmp_path, GREETING)
    source = output.with_suffix(".vbc") if mode == "--run-native-memory" else output.with_suffix(".bin")
    command = [sys.executable, "-m", "verbose_c.cli", str(source), mode]
    if mode == "--run-native-bin-memory":
        command.append(str(output.with_suffix(".json")))
    completed = subprocess.run(command, input="内存\n".encode("utf-8"), capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stdout.decode("utf-8", errors="replace")
    assert completed.stdout.startswith("请输入你的名字：你好，内存\n".encode("utf-8"))
    assert completed.stderr == b""


@pytest.mark.skipif(os.name != "nt", reason="句柄测试需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_windows_wrong_access_handles(tmp_path, optimization_level, operation):
    """继承方向错误的有效句柄时，Windows 实际读写失败应被报告。"""
    source = ('int main() { read(STDIN, 10); return 0; }' if operation == "read" else
              'int main() { write(STDOUT, "中文"); return 0; }')
    output = compile_io(tmp_path, source, optimization_level)
    data = tmp_path / "错误方向.txt"
    data.write_bytes(b"test")
    for command in ([str(output)], [sys.executable, "-m", "verbose_c.cli", str(output.with_suffix(".vbc")), f"-O{optimization_level}"]):
        with data.open("wb" if operation == "read" else "rb") as wrong_stream:
            streams = {"stdin" if operation == "read" else "stdout": wrong_stream}
            completed = subprocess.run(command, stderr=subprocess.PIPE, timeout=10, **streams)
        assert completed.returncode == 1
        assert ("读取失败" if operation == "read" else "写入失败") in completed.stderr.decode("utf-8")


@pytest.mark.skipif(os.name != "nt", reason="管道测试需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
def test_broken_output_pipe(tmp_path, optimization_level):
    """输出管道读端提前关闭时不能静默成功。"""
    output = compile_io(tmp_path, 'int main() { write(STDOUT, "已断开的管道"); return 0; }', optimization_level)
    for command in ([str(output)], [sys.executable, "-m", "verbose_c.cli", str(output.with_suffix(".vbc")), f"-O{optimization_level}"]):
        reader, writer = os.pipe()
        os.close(reader)
        with os.fdopen(writer, "wb") as pipe:
            completed = subprocess.run(command, stdout=pipe, stderr=subprocess.PIPE, timeout=10)
        assert completed.returncode == 1
        assert "写入失败" in completed.stderr.decode("utf-8")


@pytest.mark.skipif(os.name != "nt", reason="文件重定向需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
def test_file_redirection(tmp_path, optimization_level):
    """真实文件重定向保留 UTF-8、CRLF 和文件 EOF。"""
    source = ('int main() { string a = read(STDIN, 100); string b = read(STDIN, 100); '
              'write(STDOUT, a); if (b == "") { return 0; } return 1; }')
    output = compile_io(tmp_path, source, optimization_level)
    input_path, result_path = tmp_path / "输入.txt", tmp_path / "输出.txt"
    input_path.write_bytes("中文重定向😀\r\n".encode("utf-8"))
    for command in ([str(output)], [sys.executable, "-m", "verbose_c.cli", str(output.with_suffix(".vbc")), f"-O{optimization_level}"]):
        with input_path.open("rb") as source_file, result_path.open("wb") as result_file:
            completed = subprocess.run(command, stdin=source_file, stdout=result_file, stderr=subprocess.PIPE, timeout=10)
        assert completed.returncode == 0
        assert completed.stderr == b""
        assert result_path.read_bytes() == input_path.read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="故障注入需要 Windows x64")
@pytest.mark.parametrize("failure", ["none", "allocation", "zero_write"])
def test_native_short_writes_and_heap_cleanup(tmp_path, monkeypatch, failure):
    """注入短写、零进展和分配失败，检查错误传播及私有堆销毁。"""
    output = compile_io(tmp_path, 'int main() { string s = read(STDIN, 10); write(STDOUT, s); return 0; }')
    metadata = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    kernel = ctypes.WinDLL("kernel32")
    pointer, dword = ctypes.c_void_p, ctypes.c_ulong
    kernel.HeapCreate.argtypes, kernel.HeapCreate.restype = [dword, ctypes.c_size_t, ctypes.c_size_t], pointer
    kernel.HeapDestroy.argtypes, kernel.HeapDestroy.restype = [pointer], ctypes.c_int
    kernel.HeapAlloc.argtypes, kernel.HeapAlloc.restype = [pointer, dword, ctypes.c_size_t], pointer
    imports = {name: getattr(kernel, name) for name in metadata["runtime"]["iat_offsets"]}
    heaps, destroyed, written = [], [], bytearray()
    callbacks = []

    def create_heap(flags, initial, maximum):
        """记录运行时创建的真实 Windows 堆。"""
        heap = kernel.HeapCreate(flags, initial, maximum)
        heaps.append(heap)
        return heap

    def destroy_heap(heap):
        """记录并销毁真实堆，验证正常和失败路径均执行清理。"""
        destroyed.append(heap)
        return kernel.HeapDestroy(heap)

    def allocate(heap, flags, size):
        """按用例注入内存不足，其他分配使用真实堆。"""
        return 0 if failure == "allocation" else kernel.HeapAlloc(heap, flags, size)

    def read_file(handle, buffer, size, count, overlapped):
        """为多次运行提供确定的输入字节。"""
        data = "中文".encode("utf-8")
        ctypes.memmove(buffer, data, len(data))
        count[0] = len(data)
        return 1

    def write_file(handle, buffer, size, count, overlapped):
        """模拟系统短写或零进展，累积实际写出的字节。"""
        count[0] = 0 if failure == "zero_write" else min(size, 3)
        written.extend(ctypes.string_at(buffer, count[0]))
        return 1

    specifications = {
        "GetStdHandle": (pointer, [dword], lambda fd: 123),
        "GetConsoleMode": (ctypes.c_int, [pointer, ctypes.POINTER(dword)], lambda handle, mode: 0),
        "GetLastError": (dword, [], lambda: 5),
        "HeapCreate": (pointer, [dword, ctypes.c_size_t, ctypes.c_size_t], create_heap),
        "HeapDestroy": (ctypes.c_int, [pointer], destroy_heap),
        "HeapAlloc": (pointer, [pointer, dword, ctypes.c_size_t], allocate),
        "ReadFile": (ctypes.c_int, [pointer, pointer, dword, ctypes.POINTER(dword), pointer], read_file),
        "WriteFile": (ctypes.c_int, [pointer, pointer, dword, ctypes.POINTER(dword), pointer], write_file),
    }
    for name, (result, arguments, implementation) in specifications.items():
        callback = ctypes.WINFUNCTYPE(result, *arguments)(implementation)
        callbacks.append(callback)
        imports[name] = callback
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=SimpleNamespace(**imports)))
    for iteration in range(2):
        if failure == "none":
            assert run_native_bytes_in_memory(output.with_suffix(".bin").read_bytes(), metadata) == 0
        else:
            with pytest.raises(NativeCodegenError, match="内存分配失败|写入失败"):
                run_native_bytes_in_memory(output.with_suffix(".bin").read_bytes(), metadata)
        assert heaps == destroyed
        assert len(heaps) == iteration + 1
    if failure == "none":
        assert written == "中文中文".encode("utf-8")


@pytest.mark.skipif(os.name != "nt", reason="UTF-8 系统接口对照需要 Windows")
@pytest.mark.parametrize("optimization_level", [0, 1])
def test_invalid_utf8_corpus(tmp_path, optimization_level):
    """覆盖过长编码、代理码点、截断序列和完整字节表的替换规则。"""
    data = bytes(range(256)) + b"\xed\xa0\x80\xf0\x80\x80\x80\xf4\x90\x80\x80\xe1\x80A\xe2\x82"
    output = compile_io(tmp_path, 'int main() { write(STDOUT, read(STDIN, 1024)); return 0; }', optimization_level)
    completed = subprocess.run([str(output)], input=data, capture_output=True, timeout=10)
    assert completed.returncode == 0
    assert completed.stdout == data.decode("utf-8", errors="replace").encode("utf-8")


@pytest.mark.skipif(os.name != "nt", reason="字节码到 PE 需要 Windows")
def test_string_bytecode_round_trip(tmp_path):
    """从已有字节码导出 PE 时保留字符串函数的参数和返回类型。"""
    source = tmp_path / "字符串函数.vbc"
    bytecode = tmp_path / "字符串函数.vbb"
    source.write_text('string echo(string s) { return s; } int main() { write(STDOUT, echo(read(STDIN, 100))); return 0; }', encoding="utf-8")
    compiled = run_source_file(str(source), log_modules=set(), dump_modules=set(), execute=False, output_path=str(bytecode), optimize_level=1)
    assert compiled.success
    completed = subprocess.run(
        [sys.executable, "-m", "verbose_c.cli", str(bytecode), "--emit", "native-pe", "--emit-dir", str(tmp_path)],
        input=b"", capture_output=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stdout.decode("utf-8", errors="replace")
    # CLI 规范化产物文件名，按 manifest 获取实际路径。
    manifests = list(tmp_path.glob("*.native.manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    output = tmp_path / manifest["artifacts"][0]["path"]
    executed = subprocess.run([str(output)], input="字节码\n".encode("utf-8"), capture_output=True, timeout=10)
    assert executed.returncode == 0
    assert executed.stdout.decode("utf-8") == "字节码\n"

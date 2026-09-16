import copy
import ctypes
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from verbose_c.compiler.native import (
    NativeCodegenError, build_native_pe_image, native_code_program_map,
    validate_native_code_map_bytes, validate_native_pe_image_bytes,
)
from verbose_c.compiler.native.relocations import build_base_relocations
from verbose_c.compiler.native.runner import can_run_native_memory
from verbose_c.engine.engine import compile_module


@pytest.fixture
def aot_program(tmp_path):
    """编译带标准输出的 AOT 程序，供布局、损坏和 loader 测试复用。"""
    source = tmp_path / "image.vbc"
    source.write_text('int main() { write(STDOUT, "独立运行"); return 42; }', encoding="utf-8")
    program = compile_module(str(source), native_aot=True).native_code_program
    metadata = native_code_program_map(program)
    image = build_native_pe_image(program.code, metadata)
    return program, metadata, image


def test_aot_pe_headers_sections_and_relocation_directory(aot_program):
    """直接解码 PE 头和 DIR64 表，核对入口、页对齐、权限和有效修补地址。"""
    program, metadata, image = aot_program
    validate_native_pe_image_bytes(image, metadata)
    optional = struct.unpack_from("<I", image, 0x3C)[0] + 24
    assert struct.unpack_from("<H", image, optional)[0] == 0x20B
    assert struct.unpack_from("<H", image, optional - 18)[0] == 5
    assert struct.unpack_from("<H", image, optional + 70)[0] == 0x160
    assert struct.unpack_from("<H", image, optional - 2)[0] & 1 == 0
    assert metadata["schema_version"] == 3
    assert metadata["pe_size_of_headers"] == 1024
    assert metadata["sections"][0]["rva"] == 4096
    assert [s["name"] for s in metadata["sections"]] == [".text", ".rdata", ".idata", ".aot", ".reloc"]
    for section in metadata["sections"]:
        flags = section["pe_section_header"]["Characteristics"]
        assert not (flags & 0x80000000 and flags & 0x20000000)
    stub, reloc = metadata["sections"][-2:]
    assert struct.unpack_from("<I", image, optional + 16)[0] == stub["rva"]
    directory_rva, directory_size = struct.unpack_from("<II", image, optional + 152)
    assert directory_rva == reloc["rva"]
    assert directory_size == 12
    page, size, entry, padding = struct.unpack_from("<IIHH", image, reloc["pe_raw_pointer"])
    assert page == stub["rva"] and size == 12 and entry == 0xA002 and padding == 0
    target = struct.unpack_from("<Q", image, stub["pe_raw_pointer"] + 2)[0]
    assert target == metadata["image_base"] + 4096 + program.runtime["pe_entry_offset"]


def test_base_relocations_group_multiple_pages_and_pad_blocks():
    """跨页绝对引用应分组，奇数项通过 ABSOLUTE 项补齐四字节边界。"""
    payload = build_base_relocations([0x3050, 0x1FF8, 0x1002])
    assert struct.unpack_from("<IIHH", payload, 0) == (0x1000, 12, 0xA002, 0xAFF8)
    assert struct.unpack_from("<IIHH", payload, 12) == (0x3000, 12, 0xA050, 0)


@pytest.mark.parametrize("rvas", [[-1], [True], [0xFFFFFFF9], [0x1000, 0x1000], [0x1000, 0x1004]])
def test_base_relocations_reject_invalid_or_overlapping_fields(rvas):
    """无效或重叠的绝对地址不能进入 loader 的重定位表。"""
    with pytest.raises(NativeCodegenError):
        build_base_relocations(rvas)


@pytest.mark.parametrize("damage", ["stub", "relocation", "directory", "flags", "padding", "imports"])
def test_aot_rejects_corrupted_pe(aot_program, damage):
    """拒绝启动地址、重定位、导入和头部被篡改的 exe。"""
    _, metadata, image = aot_program
    changed = bytearray(image)
    positions = {
        "stub": metadata["sections"][-2]["pe_raw_pointer"] + 2,
        "relocation": metadata["sections"][-1]["pe_raw_pointer"] + 8,
        "directory": metadata["pe_optional_header_offset"] + 152,
        "flags": metadata["pe_optional_header_offset"] + 70,
        "padding": metadata["pe_size_of_headers"] - 1,
        "imports": metadata["sections"][2]["pe_raw_pointer"],
    }
    changed[positions[damage]] ^= 1
    with pytest.raises(NativeCodegenError):
        validate_native_pe_image_bytes(bytes(changed), metadata)


@pytest.mark.parametrize("damage", ["missing", "rva", "version", "type", "section", "size", "unknown"])
def test_aot_rejects_corrupted_map(aot_program, damage):
    """AOT 扩展字段同样执行严格 schema 与布局校验。"""
    program, metadata, _ = aot_program
    changed = copy.deepcopy(metadata)
    if damage == "missing":
        del changed["aot"]
    elif damage == "rva":
        changed["aot"]["base_relocations"][0]["rva"] += 8
    elif damage == "version":
        changed["aot"]["runtime_abi_version"] = True
    elif damage == "type":
        changed["aot"]["base_relocations"][0]["type"] = "ABSOLUTE"
    elif damage == "section":
        changed["sections"].pop()
    elif damage == "size":
        changed["pe_size_of_code"] += 1
    else:
        changed["aot"]["unknown"] = 0
    with pytest.raises(NativeCodegenError):
        validate_native_code_map_bytes(program.code, changed)


@pytest.mark.skipif(not can_run_native_memory(), reason="需要 Windows x64 loader")
def test_windows_loader_relocates_real_entry_address(aot_program, tmp_path):
    """占用首选地址后检查 Windows loader 修补了实际执行使用的入口指针。"""
    _, metadata, image = aot_program
    executable = tmp_path / "relocated.exe"
    executable.write_bytes(image)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
    kernel32.LoadLibraryW.restype = ctypes.c_void_p
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
    reserved = kernel32.VirtualAlloc(metadata["image_base"], metadata["pe_size_of_image"], 0x2000, 1)
    loaded = None
    try:
        loaded = kernel32.LoadLibraryW(str(executable.resolve()))
        assert loaded, ctypes.get_last_error()
        assert loaded != metadata["image_base"]
        patch = metadata["aot"]["base_relocations"][0]["rva"]
        pointer = ctypes.c_uint64.from_address(loaded + patch).value
        assert pointer == loaded + 4096 + metadata["runtime"]["pe_entry_offset"]
    finally:
        if loaded:
            kernel32.FreeLibrary(loaded)
        if reserved:
            kernel32.VirtualFree(reserved, 0, 0x8000)


@pytest.mark.skipif(not can_run_native_memory(), reason="需要 Windows x64 独立进程")
@pytest.mark.parametrize("optimization_level", [0, 1])
@pytest.mark.parametrize("input_kind", ["source", "bytecode"])
@pytest.mark.parametrize("source,data,expected,status", [
    ("int main() { return 42; }", b"", "", 42),
    ('int main() { string s = read(STDIN, 64); write(STDOUT, "回显："); write(STDOUT, s); return 3; }',
     "中文😀".encode("utf-8"), "回显：中文😀", 3),
    ('void stop() { write(STDOUT, "退出"); exit(7); } int main() { stop(); return 0; }', b"", "退出", 7),
])
def test_cli_aot_runs_as_standalone_exe(tmp_path, optimization_level, input_kind, source, data, expected, status):
    """O0/O1 源码及字节码正式编译后，仅复制 exe 即可独立运行。"""
    source_path = tmp_path / "program.vbc"
    source_path.write_text(source, encoding="utf-8")
    env = {**os.environ, "PYTHONUTF8": "1"}
    vm = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(source_path), f"-O{optimization_level}"],
                        input=data, capture_output=True, timeout=20, env=env)
    input_path = source_path if input_kind == "source" else tmp_path / "__vbccache__" / "program.vbb"
    if input_kind == "bytecode":
        source_path.unlink()
    executable = tmp_path / "独立程序.exe"
    compiled = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(input_path), "--emit-exe", str(executable),
                               f"-O{optimization_level}", "--emit", "native-bundle", "--emit-dir", str(tmp_path / "bundle")],
                              capture_output=True, timeout=20, env=env)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    assert "已生成" in compiled.stdout.decode("utf-8")
    assert compiled.stderr == b""
    assert not compiled.stdout.startswith(expected.encode("utf-8")) or not expected
    metadata = json.loads((tmp_path / "bundle" / "program.native.map.json").read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 3
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    copied = isolated / "program.exe"
    copied.write_bytes(executable.read_bytes())
    completed = subprocess.run([str(copied)], cwd=isolated, input=data, capture_output=True, timeout=10)
    assert completed.returncode == vm.returncode == status
    assert completed.stdout == vm.stdout == expected.encode("utf-8")
    assert completed.stderr == vm.stderr == b""
    assert list(isolated.iterdir()) == [copied]


@pytest.mark.skipif(not can_run_native_memory(), reason="需要 Windows x64 独立进程")
@pytest.mark.parametrize("optimization_level", [0, 1])
@pytest.mark.parametrize("source,diagnostic", [
    ('int main() { return write(STDIN, "错误"); }', "写入失败"),
    ('int main() { string s = read(STDIN, -1); return 0; }', "读取失败"),
    ('int compute(int x) { return x + 1; } int main() { return compute(2147483647); }', "溢出"),
    ('int compute(int x) { return 5 / x; } int main() { return compute(0); }', "除零"),
])
def test_aot_runtime_errors_use_stderr_and_nonzero_exit(tmp_path, optimization_level, source, diagnostic):
    """标量及 I/O 错误在正式 exe 中均停止执行并向 STDERR 输出中文原因。"""
    source_path = tmp_path / "error.vbc"
    source_path.write_text(source, encoding="utf-8")
    program = compile_module(str(source_path), optimize_level=optimization_level, native_aot=True).native_code_program
    image = tmp_path / "error.exe"
    image.write_bytes(build_native_pe_image(program.code, native_code_program_map(program)))
    completed = subprocess.run([str(image)], input=b"", capture_output=True, timeout=10)
    assert completed.returncode == 1
    assert completed.stdout == b""
    assert diagnostic in completed.stderr.decode("utf-8")


@pytest.mark.parametrize("options,reason", [
    (["--run-native-memory"], "不能与"), (["--compile-parser"], "不能与"),
    (["--check-native-map", "missing.json"], "不能与"), (["--native-result", "result.txt"], "不能与"),
])
def test_cli_aot_rejects_conflicting_modes(tmp_path, options, reason):
    """正式编译不能同时进入调试执行或其他输入模式。"""
    source = tmp_path / "input.vbc"
    source.write_text("int main() { return 0; }", encoding="utf-8")
    output = tmp_path / "output.exe"
    completed = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(source), "--emit-exe", str(output), *options],
                               capture_output=True, timeout=20, env={**os.environ, "PYTHONUTF8": "1"})
    assert completed.returncode == 1
    assert reason in completed.stdout.decode("utf-8")
    assert not output.exists()


def test_cli_aot_rejects_unsupported_native_feature(tmp_path):
    """不支持的数组应产生含源码位置的编译诊断，并保留已有 exe。"""
    source = tmp_path / "array.vbc"
    source.write_text("int main() { int values[2] = {1, 2}; return values[0]; }", encoding="utf-8")
    output = tmp_path / "array.exe"
    output.write_bytes(b"existing executable")
    completed = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(source), "--emit-exe", str(output)],
                               capture_output=True, timeout=20, env={**os.environ, "PYTHONUTF8": "1"})
    text = completed.stdout.decode("utf-8")
    assert completed.returncode == 1
    assert str(source) in text and "行 1" in text and "不支持" in text
    assert output.read_bytes() == b"existing executable"

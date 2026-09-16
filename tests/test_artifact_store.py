import hashlib
import struct

import pytest

from verbose_c.engine.engine import compile_module
from verbose_c.error.exceptions import VBCBytecodeError
from verbose_c.fs.artifact_store import ArtifactStore
from verbose_c.vm.core import VBCVirtualMachine


@pytest.fixture
def stored_program(tmp_path):
    """保存包含函数和各类常量的程序，供往返和损坏校验复用。"""
    source = tmp_path / "roundtrip.vbc"
    source.write_text(
        'int add(int a, int b) { return a + b; } '
        'int main() { string s = "中文"; double d = 1.5; bool b = true; '
        'if (s == "中文" && d == 1.5 && b) { return add(20, 22); } return 1; }',
        encoding="utf-8",
    )
    output = compile_module(str(source))
    metadata = {"constant_pool": output.constant_pool, "lineno_table": output.lineno_table,
                "source_path": str(source), "labels": output.labels,
                "function_compilation_results": output.function_compilation_results}
    artifact = tmp_path / "roundtrip.vbb"
    store = ArtifactStore()
    store.save_bytecode(str(artifact), output.bytecode, metadata)
    return store, artifact, output


def test_artifact_roundtrip_preserves_execution_and_serialization(stored_program, tmp_path):
    """验证字节码、元数据和数值/字符串/函数常量往返后仍可独立执行。"""
    store, artifact, output = stored_program
    bytecode, metadata = store.load_bytecode(str(artifact))
    assert bytecode == output.bytecode
    assert metadata["lineno_table"] == output.lineno_table
    assert VBCVirtualMachine().excute(bytecode, metadata["constant_pool"]) == 42
    copied = tmp_path / "copied.vbb"
    store.save_bytecode(str(copied), bytecode, metadata)
    assert copied.read_bytes() == artifact.read_bytes()


@pytest.mark.parametrize("damage,reason", [
    ("magic", "魔数"), ("version", "版本"), ("header", "文件头"),
    ("truncate_header", "截断"), ("truncate_payload", "大小"),
    ("directory", "目录"), ("section_range", "范围"),
    ("duplicate", "重复 section"), ("missing", "缺少必要 section"),
    ("checksum", "checksum"), ("hash", "SHA-256"),
])
def test_artifact_corruption_reports_path_and_cause(stored_program, damage, reason):
    """拒绝损坏的文件头、目录和载荷，保留文件位置及具体原因。"""
    store, artifact, _ = stored_program
    data = bytearray(artifact.read_bytes())
    header = store._HEADER_STRUCT
    section = store._SECTION_STRUCT
    if damage == "magic":
        data[:4] = b"BAD!"
    elif damage == "version":
        struct.pack_into("<H", data, 4, store.FORMAT_VERSION + 1)
    elif damage == "header":
        struct.pack_into("<I", data, 8, 0)
    elif damage == "truncate_header":
        data = data[:8]
    elif damage == "truncate_payload":
        data = data[:-1]
    elif damage == "directory":
        struct.pack_into("<Q", data, 16, len(data))
    elif damage == "section_range":
        struct.pack_into("<Q", data, header.size + 4, 0)
    elif damage == "duplicate":
        data[header.size + section.size:header.size + section.size + 2] = data[header.size:header.size + 2]
    elif damage == "missing":
        struct.pack_into("<H", data, header.size, 99)
    elif damage == "checksum":
        data[-1] ^= 1
    else:
        data[32:64] = hashlib.sha256("错误摘要".encode("utf-8")).digest()
    artifact.write_bytes(data)
    with pytest.raises(VBCBytecodeError, match=reason) as raised:
        store.load_bytecode(str(artifact))
    assert raised.value.filepath == str(artifact.resolve())

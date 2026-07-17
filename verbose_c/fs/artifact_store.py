import hashlib
import os
import struct
import zlib
from typing import Any

from verbose_c.compiler.opcode import Opcode
from verbose_c.error import VBCBytecodeError
from verbose_c.object.class_ import VBCClass
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.function import VBCFunction, VBCNativeFunction
from verbose_c.object.instance import VBCInstance
from verbose_c.object.object import VBCObject
from verbose_c.object.struct import VBCStruct
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_float import VBCFloat
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_null import VBCNull
from verbose_c.object.t_pointer import VBCPointer
from verbose_c.object.t_string import VBCString


class _BinaryWriter:
    """二进制写入辅助类。"""

    def __init__(self):
        self.data = bytearray()

    def write_u8(self, value: int) -> None:
        self.data.append(value & 0xFF)

    def write_u16(self, value: int) -> None:
        self.data.extend(struct.pack("<H", value))

    def write_u32(self, value: int) -> None:
        self.data.extend(struct.pack("<I", value))

    def write_u64(self, value: int) -> None:
        self.data.extend(struct.pack("<Q", value))

    def write_f64(self, value: float) -> None:
        self.data.extend(struct.pack("<d", value))

    def write_varuint(self, value: int) -> None:
        if value < 0:
            raise ValueError("varuint 不能写入负数")
        while value >= 0x80:
            self.write_u8((value & 0x7F) | 0x80)
            value >>= 7
        self.write_u8(value)

    def write_varint(self, value: int) -> None:
        encoded = value * 2 if value >= 0 else -value * 2 - 1
        self.write_varuint(encoded)

    def write_bytes(self, value: bytes) -> None:
        self.write_varuint(len(value))
        self.data.extend(value)

    def to_bytes(self) -> bytes:
        return bytes(self.data)


class _BinaryReader:
    """二进制读取辅助类。"""

    def __init__(self, data: bytes, filepath: str):
        self.data = data
        self.filepath = filepath
        self.pos = 0

    def read_u8(self) -> int:
        if self.pos + 1 > len(self.data):
            raise self._error("读取 u8 时遇到截断数据")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def read_u16(self) -> int:
        return self._unpack("<H", 2)

    def read_u32(self) -> int:
        return self._unpack("<I", 4)

    def read_u64(self) -> int:
        return self._unpack("<Q", 8)

    def read_f64(self) -> float:
        return self._unpack("<d", 8)

    def read_varuint(self) -> int:
        shift = 0
        value = 0
        while True:
            if shift > 63:
                raise self._error("varuint 过长")
            byte = self.read_u8()
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value
            shift += 7

    def read_varint(self) -> int:
        value = self.read_varuint()
        return (value >> 1) ^ -(value & 1)

    def read_bytes(self) -> bytes:
        length = self.read_varuint()
        if self.pos + length > len(self.data):
            raise self._error("读取 bytes 时遇到截断数据")
        value = self.data[self.pos:self.pos + length]
        self.pos += length
        return value

    def ensure_done(self, section_name: str) -> None:
        if self.pos != len(self.data):
            raise self._error(f"{section_name} section 存在未读取数据")

    def _unpack(self, fmt: str, size: int):
        if self.pos + size > len(self.data):
            raise self._error("读取固定长度字段时遇到截断数据")
        value = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def _error(self, message: str) -> VBCBytecodeError:
        return VBCBytecodeError(message, filepath=self.filepath)


class _ArtifactGraph:
    """把运行时对象图收集为紧凑二进制表。"""

    def __init__(self, store: "ArtifactStore", bytecode: list, metadata: dict[str, Any]):
        self.store = store
        self.metadata = metadata
        self.strings: list[str] = []
        self.string_ids: dict[str, int] = {}
        self.bytecode_blocks: list[list] = []
        self.line_tables: list[list[tuple[int, int]]] = []
        self.constant_entries: list[tuple[int, Any]] = []
        self.constant_pool_blocks: list[list[int]] = []
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.structs: list[dict[str, Any]] = []
        self.function_ids: dict[int, int] = {}
        self.class_ids: dict[int, int] = {}
        self.struct_ids: dict[int, int] = {}
        self.constant_object_ids: dict[int, int] = {}
        self.module_bytecode_id = self.add_bytecode_block(bytecode)
        self.module_constant_pool_id = self.add_constant_pool(metadata.get("constant_pool", []))
        self.module_line_table_id = self.add_line_table(metadata.get("lineno_table", []))
        self.source_path_id = self.add_optional_string(metadata.get("source_path"))
        self.target_abi_id = self.add_string(store.TARGET_ABI)
        self.debug_labels = metadata.get("labels", {})
        self.collect_value(self.debug_labels)
        self.debug_function_results = self._collect_function_results(
            metadata.get("function_compilation_results", {})
        )

    def add_string(self, value: str) -> int:
        if value not in self.string_ids:
            self.string_ids[value] = len(self.strings)
            self.strings.append(value)
        return self.string_ids[value]

    def add_optional_string(self, value: str | None) -> int:
        if value is None:
            return 0
        return self.add_string(value) + 1

    def add_bytecode_block(self, bytecode: list) -> int:
        block_id = len(self.bytecode_blocks)
        for instruction in bytecode:
            if not isinstance(instruction, tuple) or not instruction:
                raise VBCBytecodeError(f"非法指令格式: {instruction!r}")
            if not isinstance(instruction[0], Opcode):
                raise VBCBytecodeError(f"非法操作码: {instruction[0]!r}")
            if len(instruction) not in (1, 2):
                raise VBCBytecodeError(f"非法指令长度: {instruction!r}")
            if len(instruction) == 2:
                self.collect_value(instruction[1])
        self.bytecode_blocks.append(bytecode)
        return block_id

    def add_line_table(self, table: list | None) -> int:
        table_id = len(self.line_tables)
        self.line_tables.append([(int(pc), int(line)) for pc, line in (table or [])])
        return table_id

    def add_constant_pool(self, constants: list) -> int:
        if not isinstance(constants, list):
            raise VBCBytecodeError("constant_pool 必须是列表")
        pool_id = len(self.constant_pool_blocks)
        self.constant_pool_blocks.append([])
        self.constant_pool_blocks[pool_id] = [self.add_constant(value) for value in constants]
        return pool_id

    def add_constant(self, value: Any) -> int:
        if isinstance(value, (VBCFunction, VBCClass, VBCStruct)):
            object_id = id(value)
            if object_id in self.constant_object_ids:
                return self.constant_object_ids[object_id]
            if isinstance(value, VBCFunction):
                function_id = self.add_function(value)
                self.constant_entries.append((self.store.CONST_FUNCTION, function_id))
            elif isinstance(value, VBCClass):
                class_id = self.add_class(value)
                self.constant_entries.append((self.store.CONST_CLASS, class_id))
            else:
                struct_id = self.add_struct(value)
                self.constant_entries.append((self.store.CONST_STRUCT, struct_id))
            constant_id = len(self.constant_entries) - 1
            self.constant_object_ids[object_id] = constant_id
            return constant_id

        constant_id = len(self.constant_entries)
        if isinstance(value, VBCInteger):
            self.constant_entries.append((self.store.CONST_INTEGER, (self.store.object_type_id(value._object_type), value.value)))
        elif isinstance(value, VBCFloat):
            self.constant_entries.append((self.store.CONST_FLOAT, (self.store.object_type_id(value._object_type), value.value)))
        elif isinstance(value, VBCBool):
            self.constant_entries.append((self.store.CONST_BOOL, value.value))
        elif isinstance(value, VBCString):
            self.constant_entries.append((self.store.CONST_STRING, self.add_string(value.value)))
        elif isinstance(value, VBCNull):
            self.constant_entries.append((self.store.CONST_NULL, None))
        elif isinstance(value, (VBCPointer, VBCInstance, VBCNativeFunction)):
            raise VBCBytecodeError(f"暂不支持序列化运行时对象: {type(value).__name__}")
        else:
            raise VBCBytecodeError(f"不支持的常量类型: {type(value).__name__}")
        return constant_id

    def add_function(self, value: VBCFunction) -> int:
        object_id = id(value)
        if object_id in self.function_ids:
            return self.function_ids[object_id]
        function_id = len(self.functions)
        self.function_ids[object_id] = function_id
        self.functions.append({})
        self.functions[function_id] = {
            "name": self.add_string(value.name),
            "bytecode": self.add_bytecode_block(value.bytecode),
            "constants": self.add_constant_pool(value.constants),
            "param_count": int(value.param_count),
            "local_count": int(value.local_count),
            "source_path": self.add_optional_string(value.source_path),
            "lineno_table": self.add_line_table(value.lineno_table),
        }
        return function_id

    def add_class(self, value: VBCClass) -> int:
        object_id = id(value)
        if object_id in self.class_ids:
            return self.class_ids[object_id]
        class_id = len(self.classes)
        self.class_ids[object_id] = class_id
        self.classes.append({})
        self.classes[class_id] = {
            "name": self.add_string(value._name),
            "super_class": [self.add_class(item) for item in value._super_class],
            "methods": [(self.add_string(name), self.add_function(method)) for name, method in value._methods.items()],
            "fields": [(self.add_string(name), self.add_constant(field)) for name, field in value._fields.items()],
        }
        return class_id

    def add_struct(self, value: VBCStruct) -> int:
        object_id = id(value)
        if object_id in self.struct_ids:
            return self.struct_ids[object_id]
        struct_id = len(self.structs)
        self.struct_ids[object_id] = struct_id
        self.structs.append({
            "name": self.add_string(value.name),
            "fields": [
                (self.add_string(name), self.store.object_type_id(type_) if type_ else 0)
                for name, type_ in value.fields
            ],
        })
        return struct_id

    def collect_value(self, value: Any) -> None:
        if value is None or isinstance(value, (bool, int, float)):
            return
        if isinstance(value, str):
            self.add_string(value)
            return
        if isinstance(value, VBCObjectType):
            return
        if isinstance(value, tuple) or isinstance(value, list):
            for item in value:
                self.collect_value(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                self.collect_value(key)
                self.collect_value(item)
            return
        raise VBCBytecodeError(f"不支持的操作数或元数据类型: {type(value).__name__}")

    def _collect_function_results(self, results: dict[str, Any]) -> list[dict[str, Any]]:
        collected = []
        if not isinstance(results, dict):
            return collected
        for name, result in results.items():
            if not isinstance(result, dict):
                continue
            labels = result.get("labels", {})
            debug_labels = {
                "__verbose_c_labels__": labels,
                "__verbose_c_metadata__": {
                    "param_count": result.get("param_count", 0),
                    "param_types": result.get("param_types", []),
                    "local_count": result.get("local_count", 0),
                    "return_type": result.get("return_type", "int64"),
                    "lineno_table": result.get("lineno_table", []),
                },
            }
            self.collect_value(debug_labels)
            collected.append({
                "name": self.add_string(name),
                "bytecode": self.add_bytecode_block(result.get("bytecode", [])),
                "constants": self.add_constant_pool(result.get("constants", [])),
                "labels": debug_labels,
            })
        return collected


class ArtifactStore:
    """编译产物持久化"""

    MAGIC = b"VBB\0"
    FORMAT_VERSION = 1
    TARGET_ABI = "verbose-c-vm"
    SECTION_STRINGS = 1
    SECTION_MODULE = 2
    SECTION_CONSTANTS = 3
    SECTION_BYTECODE = 4
    SECTION_FUNCTIONS = 5
    SECTION_CLASSES = 6
    SECTION_STRUCTS = 7
    SECTION_LINE_TABLES = 8
    SECTION_DEBUG = 9
    REQUIRED_SECTIONS = {
        SECTION_STRINGS,
        SECTION_MODULE,
        SECTION_CONSTANTS,
        SECTION_BYTECODE,
        SECTION_FUNCTIONS,
        SECTION_CLASSES,
        SECTION_STRUCTS,
        SECTION_LINE_TABLES,
        SECTION_DEBUG,
    }
    CONST_INTEGER = 1
    CONST_FLOAT = 2
    CONST_BOOL = 3
    CONST_STRING = 4
    CONST_NULL = 5
    CONST_FUNCTION = 16
    CONST_CLASS = 17
    CONST_STRUCT = 18
    VALUE_NONE = 0
    VALUE_INT = 1
    VALUE_FLOAT = 2
    VALUE_BOOL = 3
    VALUE_STRING = 4
    VALUE_TUPLE = 5
    VALUE_LIST = 6
    VALUE_DICT = 7
    VALUE_OBJECT_TYPE = 8
    VALUE_NULL = 9
    _HEADER_STRUCT = struct.Struct("<4sHHIHHQQ32s")
    _SECTION_STRUCT = struct.Struct("<HHQQI")
    _OBJECT_TYPE_IDS = {
        VBCObjectType.CUSTOM: 1,
        VBCObjectType.VOID: 2,
        VBCObjectType.CLASS: 3,
        VBCObjectType.CHAR: 4,
        VBCObjectType.SHORT: 5,
        VBCObjectType.INT: 6,
        VBCObjectType.LONG: 7,
        VBCObjectType.LONGLONG: 8,
        VBCObjectType.NLINT: 9,
        VBCObjectType.FLOAT: 10,
        VBCObjectType.DOUBLE: 11,
        VBCObjectType.NLFLOAT: 12,
        VBCObjectType.BOOL: 13,
        VBCObjectType.NULL: 14,
        VBCObjectType.POINTER: 15,
        VBCObjectType.LIST: 16,
        VBCObjectType.MAP: 17,
        VBCObjectType.MODULE: 18,
        VBCObjectType.STRING: 19,
        VBCObjectType.FUNCTION: 20,
        VBCObjectType.NATIVE_FUNCTION: 21,
        VBCObjectType.INSTANCE: 22,
        VBCObjectType.RANGE: 23,
        VBCObjectType.STRUCT: 24,
    }
    _OBJECT_TYPES_BY_ID = {value: key for key, value in _OBJECT_TYPE_IDS.items()}

    def save_bytecode(self, output_path: str, bytecode: list, metadata: dict[str, Any] | None = None) -> None:
        """将编译字节码持久化到磁盘。"""
        metadata = metadata or {}
        output_path = os.path.abspath(output_path)
        graph = _ArtifactGraph(self, bytecode, metadata)
        sections = self._build_sections(graph)
        data = self._build_file(sections)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as file:
            file.write(data)

    def load_bytecode(self, output_path: str) -> tuple[list, dict[str, Any]]:
        """从磁盘读取已保存的字节码。"""
        output_path = os.path.abspath(output_path)
        try:
            with open(output_path, "rb") as file:
                data = file.read()
        except OSError as exc:
            raise VBCBytecodeError(f"无法读取字节码文件: {exc}", filepath=output_path) from exc

        sections = self._read_sections(data, output_path)
        strings = self._decode_strings(sections[self.SECTION_STRINGS], output_path)
        bytecode_blocks = self._decode_bytecode_blocks(sections[self.SECTION_BYTECODE], strings, output_path)
        line_tables = self._decode_line_tables(sections[self.SECTION_LINE_TABLES], output_path)
        constant_entries, constant_pools = self._decode_constants(sections[self.SECTION_CONSTANTS], strings, output_path)
        structs = self._decode_structs(sections[self.SECTION_STRUCTS], strings, output_path)
        function_defs = self._decode_function_defs(sections[self.SECTION_FUNCTIONS], output_path)
        class_defs = self._decode_class_defs(sections[self.SECTION_CLASSES], output_path)
        functions = [VBCFunction(name=self._string_at(strings, item["name"], output_path)) for item in function_defs]
        classes = [VBCClass(name=self._string_at(strings, item["name"], output_path)) for item in class_defs]

        def restore_constant_pool(pool_id: int) -> list:
            return [restore_constant(constant_id) for constant_id in self._item_at(constant_pools, pool_id, "常量池", output_path)]

        def restore_constant(constant_id: int) -> Any:
            tag, value = self._item_at(constant_entries, constant_id, "常量", output_path)
            if tag == self.CONST_INTEGER:
                type_id, int_value = value
                return VBCInteger(int_value, self.object_type_from_id(type_id, output_path))
            if tag == self.CONST_FLOAT:
                type_id, float_value = value
                return VBCFloat(float_value, self.object_type_from_id(type_id, output_path))
            if tag == self.CONST_BOOL:
                return VBCBool(value)
            if tag == self.CONST_STRING:
                return self._create_string_from_value(self._string_at(strings, value, output_path))
            if tag == self.CONST_NULL:
                return VBCNull()
            if tag == self.CONST_FUNCTION:
                return self._item_at(functions, value, "函数", output_path)
            if tag == self.CONST_CLASS:
                return self._item_at(classes, value, "类", output_path)
            if tag == self.CONST_STRUCT:
                return self._item_at(structs, value, "结构体", output_path)
            raise self._error(output_path, f"未知常量标签: {tag}")

        for function, definition in zip(functions, function_defs):
            function.bytecode = self._item_at(bytecode_blocks, definition["bytecode"], "字节码块", output_path)
            function.constants = restore_constant_pool(definition["constants"])
            function.param_count = definition["param_count"]
            function.local_count = definition["local_count"]
            function.source_path = self._optional_string(strings, definition["source_path"], output_path)
            function.lineno_table = self._item_at(line_tables, definition["lineno_table"], "行号表", output_path)

        for vbc_class, definition in zip(classes, class_defs):
            vbc_class._super_class = [
                self._item_at(classes, class_id, "父类", output_path)
                for class_id in definition["super_class"]
            ]
            vbc_class._methods = {
                self._string_at(strings, name_id, output_path): self._item_at(functions, function_id, "方法", output_path)
                for name_id, function_id in definition["methods"]
            }
            vbc_class._fields = {
                self._string_at(strings, name_id, output_path): restore_constant(constant_id)
                for name_id, constant_id in definition["fields"]
            }

        module = self._decode_module(sections[self.SECTION_MODULE], output_path)
        debug = self._decode_debug(sections[self.SECTION_DEBUG], strings, bytecode_blocks, constant_pools, restore_constant, output_path)
        metadata = {
            "constant_pool": restore_constant_pool(module["constant_pool"]),
            "lineno_table": self._item_at(line_tables, module["lineno_table"], "模块行号表", output_path),
            "source_path": self._optional_string(strings, module["source_path"], output_path),
            "target_abi": self._string_at(strings, module["target_abi"], output_path),
            "labels": debug["labels"],
            "function_compilation_results": debug["function_compilation_results"],
        }
        return self._item_at(bytecode_blocks, module["bytecode"], "模块字节码", output_path), metadata

    def artifact_path_for_source(self, source_path: str) -> str:
        """由源文件路径推导默认产物路径。"""
        source_path = os.path.abspath(source_path)
        source_dir = os.path.dirname(source_path)
        stem, _ = os.path.splitext(os.path.basename(source_path))
        return os.path.join(source_dir, "__vbccache__", f"{stem}.vbb")

    def object_type_id(self, object_type: VBCObjectType) -> int:
        """获取对象类型稳定 ID。"""
        try:
            return self._OBJECT_TYPE_IDS[object_type]
        except KeyError as exc:
            raise VBCBytecodeError(f"未知对象类型: {object_type!r}") from exc

    def object_type_from_id(self, type_id: int, filepath: str) -> VBCObjectType:
        """根据稳定 ID 恢复对象类型。"""
        try:
            return self._OBJECT_TYPES_BY_ID[type_id]
        except KeyError as exc:
            raise self._error(filepath, f"未知对象类型 ID: {type_id}") from exc

    def _build_sections(self, graph: _ArtifactGraph) -> dict[int, bytes]:
        """编码全部 section。"""
        self._active_string_ids = graph.string_ids
        try:
            return {
                self.SECTION_STRINGS: self._encode_strings(graph.strings),
                self.SECTION_MODULE: self._encode_module(graph),
                self.SECTION_CONSTANTS: self._encode_constants(graph),
                self.SECTION_BYTECODE: self._encode_bytecode_blocks(graph.bytecode_blocks),
                self.SECTION_FUNCTIONS: self._encode_function_defs(graph.functions),
                self.SECTION_CLASSES: self._encode_class_defs(graph.classes),
                self.SECTION_STRUCTS: self._encode_structs(graph.structs),
                self.SECTION_LINE_TABLES: self._encode_line_tables(graph.line_tables),
                self.SECTION_DEBUG: self._encode_debug(graph.debug_labels, graph.debug_function_results),
            }
        finally:
            self._active_string_ids = {}

    def _build_file(self, sections: dict[int, bytes]) -> bytes:
        """组合文件头、section 目录和载荷。"""
        section_items = sorted(sections.items())
        header_size = self._HEADER_STRUCT.size
        directory_offset = header_size
        directory_size = self._SECTION_STRUCT.size * len(section_items)
        offset = header_size + directory_size
        directory = bytearray()
        payload_parts = []

        for section_id, payload in section_items:
            checksum = zlib.crc32(payload) & 0xFFFFFFFF
            directory.extend(self._SECTION_STRUCT.pack(section_id, 0, offset, len(payload), checksum))
            payload_parts.append(payload)
            offset += len(payload)

        payload_bytes = b"".join(payload_parts)
        file_size = offset
        header = self._HEADER_STRUCT.pack(
            self.MAGIC,
            self.FORMAT_VERSION,
            0,
            header_size,
            len(section_items),
            0,
            directory_offset,
            file_size,
            hashlib.sha256(payload_bytes).digest(),
        )
        return header + bytes(directory) + payload_bytes

    def _read_sections(self, data: bytes, filepath: str) -> dict[int, bytes]:
        """校验文件并读取 section。"""
        header_size = self._HEADER_STRUCT.size
        if len(data) < header_size:
            raise self._error(filepath, "字节码文件已截断，无法读取文件头")
        magic, version, _flags, recorded_header_size, section_count, _reserved, directory_offset, file_size, expected_hash = (
            self._HEADER_STRUCT.unpack(data[:header_size])
        )
        if magic != self.MAGIC:
            raise self._error(filepath, f"字节码魔数不匹配，期望 {self.MAGIC!r}，实际 {magic!r}")
        if version != self.FORMAT_VERSION:
            raise self._error(filepath, f"字节码版本不匹配，期望 {self.FORMAT_VERSION}，实际 {version}")
        if recorded_header_size != header_size:
            raise self._error(filepath, "字节码文件头长度不一致")
        if file_size != len(data):
            raise self._error(filepath, f"字节码文件大小不匹配，期望 {file_size}，实际 {len(data)}")

        directory_size = self._SECTION_STRUCT.size * section_count
        if directory_offset < header_size or directory_offset + directory_size > len(data):
            raise self._error(filepath, "section 目录范围非法")

        sections: dict[int, bytes] = {}
        ranges = []
        payload_parts = []
        pos = directory_offset
        for _ in range(section_count):
            section_id, _flags, offset, length, checksum = self._SECTION_STRUCT.unpack(data[pos:pos + self._SECTION_STRUCT.size])
            pos += self._SECTION_STRUCT.size
            if section_id in sections:
                raise self._error(filepath, f"重复 section: {section_id}")
            if offset < directory_offset + directory_size or offset + length > len(data):
                raise self._error(filepath, f"section {section_id} 范围非法")
            ranges.append((offset, offset + length, section_id))
            payload = data[offset:offset + length]
            if (zlib.crc32(payload) & 0xFFFFFFFF) != checksum:
                raise self._error(filepath, f"section {section_id} checksum 校验失败")
            sections[section_id] = payload
            payload_parts.append(payload)

        ranges.sort()
        for index in range(1, len(ranges)):
            if ranges[index][0] < ranges[index - 1][1]:
                raise self._error(filepath, "section 范围重叠")
        missing = self.REQUIRED_SECTIONS - set(sections)
        if missing:
            raise self._error(filepath, f"缺少必要 section: {sorted(missing)}")
        if hashlib.sha256(b"".join(payload_parts)).digest() != expected_hash:
            raise self._error(filepath, "字节码载荷 SHA-256 校验失败")
        return sections

    def _encode_strings(self, strings: list[str]) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(strings))
        for value in strings:
            writer.write_bytes(value.encode("utf-8"))
        return writer.to_bytes()

    def _decode_strings(self, data: bytes, filepath: str) -> list[str]:
        reader = _BinaryReader(data, filepath)
        strings = []
        for _ in range(reader.read_varuint()):
            try:
                strings.append(reader.read_bytes().decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise self._error(filepath, "字符串表包含非法 UTF-8") from exc
        reader.ensure_done("STRINGS")
        return strings

    def _encode_module(self, graph: _ArtifactGraph) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(graph.source_path_id)
        writer.write_varuint(graph.target_abi_id)
        writer.write_varuint(graph.module_bytecode_id)
        writer.write_varuint(graph.module_constant_pool_id)
        writer.write_varuint(graph.module_line_table_id)
        return writer.to_bytes()

    def _decode_module(self, data: bytes, filepath: str) -> dict[str, int]:
        reader = _BinaryReader(data, filepath)
        module = {
            "source_path": reader.read_varuint(),
            "target_abi": reader.read_varuint(),
            "bytecode": reader.read_varuint(),
            "constant_pool": reader.read_varuint(),
            "lineno_table": reader.read_varuint(),
        }
        reader.ensure_done("MODULE")
        return module

    def _encode_bytecode_blocks(self, blocks: list[list]) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(blocks))
        for block in blocks:
            writer.write_varuint(len(block))
            for instruction in block:
                writer.write_u16(instruction[0].value)
                if len(instruction) == 1:
                    writer.write_u8(self.VALUE_NONE)
                else:
                    self._write_value(writer, instruction[1])
        return writer.to_bytes()

    def _decode_bytecode_blocks(self, data: bytes, strings: list[str], filepath: str) -> list[list]:
        reader = _BinaryReader(data, filepath)
        blocks = []
        for _ in range(reader.read_varuint()):
            block = []
            for _ in range(reader.read_varuint()):
                opcode_value = reader.read_u16()
                try:
                    opcode = Opcode(opcode_value)
                except ValueError as exc:
                    raise self._error(filepath, f"未知操作码: {opcode_value}") from exc
                operand = self._read_value(reader, strings, filepath)
                block.append((opcode,) if operand is _NO_OPERAND else (opcode, operand))
            blocks.append(block)
        reader.ensure_done("BYTECODE")
        return blocks

    def _encode_constants(self, graph: _ArtifactGraph) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(graph.constant_entries))
        for tag, value in graph.constant_entries:
            writer.write_u8(tag)
            if tag == self.CONST_INTEGER:
                type_id, int_value = value
                writer.write_varuint(type_id)
                writer.write_varint(int_value)
            elif tag == self.CONST_FLOAT:
                type_id, float_value = value
                writer.write_varuint(type_id)
                writer.write_f64(float_value)
            elif tag == self.CONST_BOOL:
                writer.write_u8(1 if value else 0)
            elif tag == self.CONST_STRING:
                writer.write_varuint(value)
            elif tag == self.CONST_NULL:
                pass
            elif tag in (self.CONST_FUNCTION, self.CONST_CLASS, self.CONST_STRUCT):
                writer.write_varuint(value)
            else:
                raise VBCBytecodeError(f"未知常量标签: {tag}")

        writer.write_varuint(len(graph.constant_pool_blocks))
        for pool in graph.constant_pool_blocks:
            writer.write_varuint(len(pool))
            for constant_id in pool:
                writer.write_varuint(constant_id)
        return writer.to_bytes()

    def _decode_constants(self, data: bytes, strings: list[str], filepath: str) -> tuple[list[tuple[int, Any]], list[list[int]]]:
        reader = _BinaryReader(data, filepath)
        entries = []
        for _ in range(reader.read_varuint()):
            tag = reader.read_u8()
            if tag == self.CONST_INTEGER:
                entries.append((tag, (reader.read_varuint(), reader.read_varint())))
            elif tag == self.CONST_FLOAT:
                entries.append((tag, (reader.read_varuint(), reader.read_f64())))
            elif tag == self.CONST_BOOL:
                entries.append((tag, bool(reader.read_u8())))
            elif tag == self.CONST_STRING:
                string_id = reader.read_varuint()
                self._string_at(strings, string_id, filepath)
                entries.append((tag, string_id))
            elif tag == self.CONST_NULL:
                entries.append((tag, None))
            elif tag in (self.CONST_FUNCTION, self.CONST_CLASS, self.CONST_STRUCT):
                entries.append((tag, reader.read_varuint()))
            else:
                raise self._error(filepath, f"未知常量标签: {tag}")

        pools = []
        for _ in range(reader.read_varuint()):
            pools.append([reader.read_varuint() for _ in range(reader.read_varuint())])
        reader.ensure_done("CONSTANTS")
        return entries, pools

    def _encode_function_defs(self, functions: list[dict[str, Any]]) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(functions))
        for function in functions:
            writer.write_varuint(function["name"])
            writer.write_varuint(function["bytecode"])
            writer.write_varuint(function["constants"])
            writer.write_varuint(function["param_count"])
            writer.write_varuint(function["local_count"])
            writer.write_varuint(function["source_path"])
            writer.write_varuint(function["lineno_table"])
        return writer.to_bytes()

    def _decode_function_defs(self, data: bytes, filepath: str) -> list[dict[str, int]]:
        reader = _BinaryReader(data, filepath)
        functions = []
        for _ in range(reader.read_varuint()):
            functions.append({
                "name": reader.read_varuint(),
                "bytecode": reader.read_varuint(),
                "constants": reader.read_varuint(),
                "param_count": reader.read_varuint(),
                "local_count": reader.read_varuint(),
                "source_path": reader.read_varuint(),
                "lineno_table": reader.read_varuint(),
            })
        reader.ensure_done("FUNCTIONS")
        return functions

    def _encode_class_defs(self, classes: list[dict[str, Any]]) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(classes))
        for class_ in classes:
            writer.write_varuint(class_["name"])
            writer.write_varuint(len(class_["super_class"]))
            for class_id in class_["super_class"]:
                writer.write_varuint(class_id)
            writer.write_varuint(len(class_["methods"]))
            for name_id, function_id in class_["methods"]:
                writer.write_varuint(name_id)
                writer.write_varuint(function_id)
            writer.write_varuint(len(class_["fields"]))
            for name_id, constant_id in class_["fields"]:
                writer.write_varuint(name_id)
                writer.write_varuint(constant_id)
        return writer.to_bytes()

    def _decode_class_defs(self, data: bytes, filepath: str) -> list[dict[str, Any]]:
        reader = _BinaryReader(data, filepath)
        classes = []
        for _ in range(reader.read_varuint()):
            classes.append({
                "name": reader.read_varuint(),
                "super_class": [reader.read_varuint() for _ in range(reader.read_varuint())],
                "methods": [(reader.read_varuint(), reader.read_varuint()) for _ in range(reader.read_varuint())],
                "fields": [(reader.read_varuint(), reader.read_varuint()) for _ in range(reader.read_varuint())],
            })
        reader.ensure_done("CLASSES")
        return classes

    def _encode_structs(self, structs: list[dict[str, Any]]) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(structs))
        for struct_ in structs:
            writer.write_varuint(struct_["name"])
            writer.write_varuint(len(struct_["fields"]))
            for name_id, type_id in struct_["fields"]:
                writer.write_varuint(name_id)
                writer.write_varuint(type_id)
        return writer.to_bytes()

    def _decode_structs(self, data: bytes, strings: list[str], filepath: str) -> list[VBCStruct]:
        reader = _BinaryReader(data, filepath)
        structs = []
        for _ in range(reader.read_varuint()):
            name = self._string_at(strings, reader.read_varuint(), filepath)
            fields = []
            for _ in range(reader.read_varuint()):
                field_name = self._string_at(strings, reader.read_varuint(), filepath)
                type_id = reader.read_varuint()
                fields.append((field_name, self.object_type_from_id(type_id, filepath) if type_id else None))
            structs.append(VBCStruct(name, fields))
        reader.ensure_done("STRUCTS")
        return structs

    def _encode_line_tables(self, tables: list[list[tuple[int, int]]]) -> bytes:
        writer = _BinaryWriter()
        writer.write_varuint(len(tables))
        for table in tables:
            writer.write_varuint(len(table))
            for pc, line in table:
                writer.write_varuint(pc)
                writer.write_varint(line)
        return writer.to_bytes()

    def _decode_line_tables(self, data: bytes, filepath: str) -> list[list[tuple[int, int]]]:
        reader = _BinaryReader(data, filepath)
        tables = []
        for _ in range(reader.read_varuint()):
            tables.append([(reader.read_varuint(), reader.read_varint()) for _ in range(reader.read_varuint())])
        reader.ensure_done("LINE_TABLES")
        return tables

    def _encode_debug(self, labels: dict[str, Any], function_results: list[dict[str, Any]]) -> bytes:
        writer = _BinaryWriter()
        self._write_value(writer, labels if isinstance(labels, dict) else {})
        writer.write_varuint(len(function_results))
        for result in function_results:
            writer.write_varuint(result["name"])
            writer.write_varuint(result["bytecode"])
            writer.write_varuint(result["constants"])
            self._write_value(writer, result["labels"] if isinstance(result["labels"], dict) else {})
        return writer.to_bytes()

    def _decode_debug(
        self,
        data: bytes,
        strings: list[str],
        bytecode_blocks: list[list],
        constant_pools: list[list[int]],
        restore_constant,
        filepath: str,
    ) -> dict[str, Any]:
        reader = _BinaryReader(data, filepath)
        labels = self._read_value(reader, strings, filepath)
        function_results = {}
        for _ in range(reader.read_varuint()):
            name = self._string_at(strings, reader.read_varuint(), filepath)
            bytecode_id = reader.read_varuint()
            constants_id = reader.read_varuint()
            result_labels = self._read_value(reader, strings, filepath)
            metadata = {}
            if isinstance(result_labels, dict) and "__verbose_c_metadata__" in result_labels:
                metadata = result_labels.get("__verbose_c_metadata__", {})
                result_labels = result_labels.get("__verbose_c_labels__", {})
            function_results[name] = {
                "bytecode": self._item_at(bytecode_blocks, bytecode_id, "调试字节码块", filepath),
                "constants": [
                    restore_constant(constant_id)
                    for constant_id in self._item_at(constant_pools, constants_id, "调试常量池", filepath)
                ],
                "labels": result_labels,
            }
            if isinstance(metadata, dict):
                function_results[name].update(metadata)
        reader.ensure_done("DEBUG")
        return {"labels": labels, "function_compilation_results": function_results}

    def _write_value(self, writer: _BinaryWriter, value: Any) -> None:
        """写入操作数或调试值。"""
        if value is None:
            writer.write_u8(self.VALUE_NULL)
        elif isinstance(value, bool):
            writer.write_u8(self.VALUE_BOOL)
            writer.write_u8(1 if value else 0)
        elif isinstance(value, int):
            writer.write_u8(self.VALUE_INT)
            writer.write_varint(value)
        elif isinstance(value, float):
            writer.write_u8(self.VALUE_FLOAT)
            writer.write_f64(value)
        elif isinstance(value, str):
            writer.write_u8(self.VALUE_STRING)
            try:
                writer.write_varuint(self._active_string_ids[value])
            except (AttributeError, KeyError) as exc:
                raise VBCBytecodeError(f"字符串未写入字符串表: {value!r}") from exc
        elif isinstance(value, VBCObjectType):
            writer.write_u8(self.VALUE_OBJECT_TYPE)
            writer.write_varuint(self.object_type_id(value))
        elif isinstance(value, tuple):
            writer.write_u8(self.VALUE_TUPLE)
            writer.write_varuint(len(value))
            for item in value:
                self._write_value(writer, item)
        elif isinstance(value, list):
            writer.write_u8(self.VALUE_LIST)
            writer.write_varuint(len(value))
            for item in value:
                self._write_value(writer, item)
        elif isinstance(value, dict):
            writer.write_u8(self.VALUE_DICT)
            writer.write_varuint(len(value))
            for key, item in value.items():
                self._write_value(writer, key)
                self._write_value(writer, item)
        else:
            raise VBCBytecodeError(f"不支持的操作数或元数据类型: {type(value).__name__}")

    def _read_value(self, reader: _BinaryReader, strings: list[str], filepath: str) -> Any:
        """读取操作数或调试值。"""
        tag = reader.read_u8()
        if tag == self.VALUE_NONE:
            return _NO_OPERAND
        if tag == self.VALUE_NULL:
            return None
        if tag == self.VALUE_BOOL:
            return bool(reader.read_u8())
        if tag == self.VALUE_INT:
            return reader.read_varint()
        if tag == self.VALUE_FLOAT:
            return reader.read_f64()
        if tag == self.VALUE_STRING:
            return self._string_at(strings, reader.read_varuint(), filepath)
        if tag == self.VALUE_OBJECT_TYPE:
            return self.object_type_from_id(reader.read_varuint(), filepath)
        if tag == self.VALUE_TUPLE:
            return tuple(self._read_value(reader, strings, filepath) for _ in range(reader.read_varuint()))
        if tag == self.VALUE_LIST:
            return [self._read_value(reader, strings, filepath) for _ in range(reader.read_varuint())]
        if tag == self.VALUE_DICT:
            return {
                self._read_value(reader, strings, filepath): self._read_value(reader, strings, filepath)
                for _ in range(reader.read_varuint())
            }
        raise self._error(filepath, f"未知值标签: {tag}")

    def _string_at(self, strings: list[str], index: int, filepath: str) -> str:
        """读取字符串表项。"""
        return self._item_at(strings, index, "字符串", filepath)

    def _optional_string(self, strings: list[str], index: int, filepath: str) -> str | None:
        """读取可空字符串表项。"""
        if index == 0:
            return None
        return self._string_at(strings, index - 1, filepath)

    def _item_at(self, values: list, index: int, name: str, filepath: str):
        """读取带越界检查的列表项。"""
        if index < 0 or index >= len(values):
            raise self._error(filepath, f"{name}索引越界: {index}")
        return values[index]

    def _create_string_from_value(self, value: str) -> VBCString:
        """按已解析字符串值创建 VBCString。"""
        obj = VBCString.__new__(VBCString)
        VBCObject.__init__(obj, VBCObjectType.STRING)
        obj.value = value
        return obj

    def _error(self, filepath: str, message: str) -> VBCBytecodeError:
        """创建带文件路径的字节码错误。"""
        return VBCBytecodeError(message, filepath=filepath)


class _NoOperand:
    pass


_NO_OPERAND = _NoOperand()

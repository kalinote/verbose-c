import struct

from verbose_c.compiler.native.codegen import validate_native_text_section_map_bytes
from verbose_c.compiler.native.errors import NativeCodegenError


_PE_LINKER_MAJOR_VERSION = 14
_PE_LINKER_MINOR_VERSION = 0
_PE_OS_MAJOR_VERSION = 6
_PE_OS_MINOR_VERSION = 0
_PE_IMAGE_MAJOR_VERSION = 0
_PE_IMAGE_MINOR_VERSION = 0
_PE_SUBSYSTEM_MAJOR_VERSION = 6
_PE_SUBSYSTEM_MINOR_VERSION = 0
_PE_WIN32_VERSION_VALUE = 0
_PE_CHECKSUM = 0
_PE_DLL_CHARACTERISTICS = 0
_PE_STACK_RESERVE = 0x100000
_PE_STACK_COMMIT = 0x1000
_PE_HEAP_RESERVE = 0x100000
_PE_HEAP_COMMIT = 0x1000
_PE_LOADER_FLAGS = 0


def build_native_pe_image(code: bytes, metadata: dict[str, object]) -> bytes:
    """根据 native map 写出最小 PE32+ image。"""
    text_raw = _build_text_raw(code, metadata)
    validate_native_text_section_map_bytes(text_raw, metadata)
    coff_header = _require_mapping(metadata, "pe_coff_header")
    optional_header = _require_mapping(metadata, "pe_optional_header")
    file_layout = _require_mapping(metadata, "pe_file_layout")
    text_section = _single_text_section(metadata)
    section_header = _require_mapping(text_section, "pe_section_header")
    file_size = _require_int(file_layout, "file_size")
    image = bytearray(file_size)
    _write_dos_header(image, metadata)
    _write_pe_signature(image, metadata)
    _write_coff_header(image, metadata, coff_header)
    _write_optional_header(image, metadata, optional_header)
    _write_section_header(image, metadata, section_header)
    text_layout = _require_mapping(file_layout, "text_raw")
    text_offset = _require_int(text_layout, "offset")
    image[text_offset:text_offset + len(text_raw)] = text_raw
    validate_native_pe_image_bytes(bytes(image), metadata)
    return bytes(image)


def validate_native_pe_image_bytes(pe_image: bytes, metadata: dict[str, object]) -> None:
    """校验最小 PE32+ image 与 native map 一致。"""
    if not isinstance(pe_image, bytes):
        raise NativeCodegenError(f"native PE image 必须是 bytes，实际 {type(pe_image).__name__}")
    file_layout = _require_mapping(metadata, "pe_file_layout")
    expected_file_size = _require_int(file_layout, "file_size")
    if len(pe_image) != expected_file_size:
        raise NativeCodegenError(f"native PE image 大小不一致: 期望 {expected_file_size}, 实际 {len(pe_image)}")
    layout_ranges = {
        "dos_header": _validate_pe_range(pe_image, metadata, "dos_header"),
        "dos_stub_padding": _validate_pe_range(pe_image, metadata, "dos_stub_padding"),
        "pe_signature": _validate_pe_range(pe_image, metadata, "pe_signature"),
        "coff_header": _validate_pe_range(pe_image, metadata, "coff_header"),
        "optional_header": _validate_pe_range(pe_image, metadata, "optional_header"),
        "section_table": _validate_pe_range(pe_image, metadata, "section_table"),
        "headers_padding": _validate_pe_range(pe_image, metadata, "headers_padding"),
        "text_raw": _validate_pe_range(pe_image, metadata, "text_raw"),
    }
    text_section = _single_text_section(metadata)
    expected_layout_ranges = {
        "dos_header": (0, _require_int(metadata, "pe_dos_header_size"), _require_int(metadata, "pe_dos_header_size")),
        "dos_stub_padding": (
            _require_int(metadata, "pe_dos_header_size"),
            _require_int(metadata, "pe_lfanew") - _require_int(metadata, "pe_dos_header_size"),
            _require_int(metadata, "pe_lfanew"),
        ),
        "pe_signature": (
            _require_int(metadata, "pe_signature_offset"),
            _require_int(metadata, "pe_signature_size"),
            _require_int(metadata, "pe_signature_offset") + _require_int(metadata, "pe_signature_size"),
        ),
        "coff_header": (
            _require_int(metadata, "pe_coff_header_offset"),
            _require_int(metadata, "pe_coff_header_size"),
            _require_int(metadata, "pe_coff_header_offset") + _require_int(metadata, "pe_coff_header_size"),
        ),
        "optional_header": (
            _require_int(metadata, "pe_optional_header_offset"),
            _require_int(metadata, "pe_optional_header_size"),
            _require_int(metadata, "pe_optional_header_offset") + _require_int(metadata, "pe_optional_header_size"),
        ),
        "section_table": (
            _require_int(metadata, "pe_section_table_offset"),
            _require_int(metadata, "pe_section_table_size"),
            _require_int(metadata, "pe_section_table_offset") + _require_int(metadata, "pe_section_table_size"),
        ),
        "headers_padding": (
            _require_int(metadata, "pe_section_table_offset") + _require_int(metadata, "pe_section_table_size"),
            _require_int(metadata, "pe_size_of_headers") - _require_int(metadata, "pe_section_table_offset") - _require_int(metadata, "pe_section_table_size"),
            _require_int(metadata, "pe_size_of_headers"),
        ),
        "text_raw": (
            _require_int(text_section, "pe_raw_pointer"),
            _require_int(text_section, "raw_size_aligned"),
            _require_int(text_section, "pe_raw_end_pointer"),
        ),
    }
    previous_end = 0
    for name, expected_range in expected_layout_ranges.items():
        actual_range = layout_ranges[name]
        if actual_range != expected_range:
            raise NativeCodegenError(
                f"native PE image layout {name} 不一致: 期望 offset/size/end={expected_range}, 实际 {actual_range}"
            )
        if actual_range[0] != previous_end:
            raise NativeCodegenError(
                f"native PE image layout {name} 与上一段不连续: 期望 offset {previous_end}, 实际 {actual_range[0]}"
            )
        previous_end = actual_range[2]
    if previous_end != expected_file_size:
        raise NativeCodegenError(f"native PE image layout file_size 不一致: 期望 {previous_end}, 实际 {expected_file_size}")
    if pe_image[:2] != b"MZ":
        raise NativeCodegenError("native PE image DOS magic 必须为 MZ")
    pe_lfanew = _require_int(metadata, "pe_lfanew")
    if _u32(pe_image, 0x3C) != pe_lfanew:
        raise NativeCodegenError("native PE image DOS e_lfanew 与 map 不一致")
    dos_header = _require_mapping(file_layout, "dos_header")
    dos_header_offset = _require_int(dos_header, "offset")
    dos_header_size = _require_int(dos_header, "size")
    if dos_header_offset != 0 or dos_header_size < 64:
        raise NativeCodegenError("native PE image DOS header 布局必须从 0 开始且至少 64 字节")
    dos_header_payload = bytearray(pe_image[dos_header_offset:dos_header_offset + dos_header_size])
    dos_header_payload[0:2] = b"\0\0"
    dos_header_payload[0x3C:0x40] = b"\0\0\0\0"
    if dos_header_payload != bytes(dos_header_size):
        raise NativeCodegenError("native PE image DOS header 保留字段必须全部为 0")
    dos_stub_padding = _require_mapping(file_layout, "dos_stub_padding")
    stub_offset = _require_int(dos_stub_padding, "offset")
    stub_size = _require_int(dos_stub_padding, "size")
    if pe_image[stub_offset:stub_offset + stub_size] != bytes(stub_size):
        raise NativeCodegenError("native PE image DOS stub padding 必须全部为 0")
    signature_offset = _require_int(metadata, "pe_signature_offset")
    if pe_image[signature_offset:signature_offset + 4] != b"PE\0\0":
        raise NativeCodegenError("native PE image PE signature 不一致")
    _validate_coff_header(pe_image, metadata)
    _validate_optional_header(pe_image, metadata)
    _validate_section_header(pe_image, metadata)
    text_layout = _require_mapping(file_layout, "text_raw")
    text_offset = _require_int(text_layout, "offset")
    text_size = _require_int(text_layout, "size")
    validate_native_text_section_map_bytes(pe_image[text_offset:text_offset + text_size], metadata)
    headers_padding = _require_mapping(file_layout, "headers_padding")
    padding_offset = _require_int(headers_padding, "offset")
    padding_size = _require_int(headers_padding, "size")
    if pe_image[padding_offset:padding_offset + padding_size] != bytes(padding_size):
        raise NativeCodegenError("native PE image headers padding 必须全部为 0")


def _build_text_raw(code: bytes, metadata: dict[str, object]) -> bytes:
    """构造补零后的 .text raw section。"""
    if not isinstance(code, bytes):
        raise NativeCodegenError(f"native PE image code 必须是 bytes，实际 {type(code).__name__}")
    text_section = _single_text_section(metadata)
    code_size = _require_int(metadata, "code_size")
    if len(code) != code_size:
        raise NativeCodegenError(f"native PE image code_size 不一致: 期望 {code_size}, 实际 {len(code)}")
    padding_size = _require_int(text_section, "raw_padding_size")
    return code + bytes(padding_size)


def _write_dos_header(image: bytearray, metadata: dict[str, object]) -> None:
    """写入 DOS header 和 e_lfanew。"""
    dos_header_size = _require_int(metadata, "pe_dos_header_size")
    if dos_header_size < 64:
        raise NativeCodegenError("native PE image DOS header 至少需要 64 字节")
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, _require_int(metadata, "pe_lfanew"))


def _write_pe_signature(image: bytearray, metadata: dict[str, object]) -> None:
    """写入 PE signature。"""
    offset = _require_int(metadata, "pe_signature_offset")
    image[offset:offset + 4] = b"PE\0\0"


def _write_coff_header(image: bytearray, metadata: dict[str, object], coff_header: dict[str, object]) -> None:
    """写入 COFF file header。"""
    offset = _require_int(metadata, "pe_coff_header_offset")
    struct.pack_into(
        "<HHIIIHH",
        image,
        offset,
        _require_int(coff_header, "Machine"),
        _require_int(coff_header, "NumberOfSections"),
        _require_int(coff_header, "TimeDateStamp"),
        _require_int(coff_header, "PointerToSymbolTable"),
        _require_int(coff_header, "NumberOfSymbols"),
        _require_int(coff_header, "SizeOfOptionalHeader"),
        _require_int(coff_header, "Characteristics"),
    )


def _write_optional_header(image: bytearray, metadata: dict[str, object], optional_header: dict[str, object]) -> None:
    """写入 PE32+ optional header。"""
    offset = _require_int(metadata, "pe_optional_header_offset")
    struct.pack_into(
        "<HBBIIIIIQIIHHHHHHIIIIHHQQQQII",
        image,
        offset,
        _require_int(optional_header, "Magic"),
        _PE_LINKER_MAJOR_VERSION,
        _PE_LINKER_MINOR_VERSION,
        _require_int(optional_header, "SizeOfCode"),
        _require_int(optional_header, "SizeOfInitializedData"),
        _require_int(optional_header, "SizeOfUninitializedData"),
        _require_int(optional_header, "AddressOfEntryPoint"),
        _require_int(optional_header, "BaseOfCode"),
        _require_int(optional_header, "ImageBase"),
        _require_int(optional_header, "SectionAlignment"),
        _require_int(optional_header, "FileAlignment"),
        _PE_OS_MAJOR_VERSION,
        _PE_OS_MINOR_VERSION,
        _PE_IMAGE_MAJOR_VERSION,
        _PE_IMAGE_MINOR_VERSION,
        _PE_SUBSYSTEM_MAJOR_VERSION,
        _PE_SUBSYSTEM_MINOR_VERSION,
        _PE_WIN32_VERSION_VALUE,
        _require_int(optional_header, "SizeOfImage"),
        _require_int(optional_header, "SizeOfHeaders"),
        _PE_CHECKSUM,
        _require_int(optional_header, "Subsystem"),
        _PE_DLL_CHARACTERISTICS,
        _PE_STACK_RESERVE,
        _PE_STACK_COMMIT,
        _PE_HEAP_RESERVE,
        _PE_HEAP_COMMIT,
        _PE_LOADER_FLAGS,
        _require_int(optional_header, "NumberOfRvaAndSizes"),
    )


def _write_section_header(image: bytearray, metadata: dict[str, object], section_header: dict[str, object]) -> None:
    """写入 .text section header。"""
    offset = _require_int(metadata, "pe_section_table_offset")
    name_bytes = bytes.fromhex(_require_str(section_header, "NameBytes"))
    if len(name_bytes) != 8:
        raise NativeCodegenError("native PE image .text section name 必须为 8 字节")
    struct.pack_into(
        "<8sIIIIIIHHI",
        image,
        offset,
        name_bytes,
        _require_int(section_header, "VirtualSize"),
        _require_int(section_header, "VirtualAddress"),
        _require_int(section_header, "SizeOfRawData"),
        _require_int(section_header, "PointerToRawData"),
        _require_int(section_header, "PointerToRelocations"),
        _require_int(section_header, "PointerToLinenumbers"),
        _require_int(section_header, "NumberOfRelocations"),
        _require_int(section_header, "NumberOfLinenumbers"),
        _require_int(section_header, "Characteristics"),
    )


def _validate_coff_header(pe_image: bytes, metadata: dict[str, object]) -> None:
    """校验 COFF file header。"""
    coff_header = _require_mapping(metadata, "pe_coff_header")
    offset = _require_int(metadata, "pe_coff_header_offset")
    fields = struct.unpack_from("<HHIIIHH", pe_image, offset)
    names = (
        "Machine",
        "NumberOfSections",
        "TimeDateStamp",
        "PointerToSymbolTable",
        "NumberOfSymbols",
        "SizeOfOptionalHeader",
        "Characteristics",
    )
    for name, value in zip(names, fields, strict=True):
        if value != _require_int(coff_header, name):
            raise NativeCodegenError(f"native PE image COFF {name} 不一致: 期望 {coff_header[name]}, 实际 {value}")


def _validate_optional_header(pe_image: bytes, metadata: dict[str, object]) -> None:
    """校验 PE32+ optional header 关键字段。"""
    optional_header = _require_mapping(metadata, "pe_optional_header")
    offset = _require_int(metadata, "pe_optional_header_offset")
    fixed_defaults = {
        "MajorLinkerVersion": pe_image[offset + 2],
        "MinorLinkerVersion": pe_image[offset + 3],
        "MajorOperatingSystemVersion": _u16(pe_image, offset + 40),
        "MinorOperatingSystemVersion": _u16(pe_image, offset + 42),
        "MajorImageVersion": _u16(pe_image, offset + 44),
        "MinorImageVersion": _u16(pe_image, offset + 46),
        "MajorSubsystemVersion": _u16(pe_image, offset + 48),
        "MinorSubsystemVersion": _u16(pe_image, offset + 50),
        "Win32VersionValue": _u32(pe_image, offset + 52),
        "CheckSum": _u32(pe_image, offset + 64),
        "DllCharacteristics": _u16(pe_image, offset + 70),
        "SizeOfStackReserve": _u64(pe_image, offset + 72),
        "SizeOfStackCommit": _u64(pe_image, offset + 80),
        "SizeOfHeapReserve": _u64(pe_image, offset + 88),
        "SizeOfHeapCommit": _u64(pe_image, offset + 96),
        "LoaderFlags": _u32(pe_image, offset + 104),
    }
    expected_defaults = {
        "MajorLinkerVersion": _PE_LINKER_MAJOR_VERSION,
        "MinorLinkerVersion": _PE_LINKER_MINOR_VERSION,
        "MajorOperatingSystemVersion": _PE_OS_MAJOR_VERSION,
        "MinorOperatingSystemVersion": _PE_OS_MINOR_VERSION,
        "MajorImageVersion": _PE_IMAGE_MAJOR_VERSION,
        "MinorImageVersion": _PE_IMAGE_MINOR_VERSION,
        "MajorSubsystemVersion": _PE_SUBSYSTEM_MAJOR_VERSION,
        "MinorSubsystemVersion": _PE_SUBSYSTEM_MINOR_VERSION,
        "Win32VersionValue": _PE_WIN32_VERSION_VALUE,
        "CheckSum": _PE_CHECKSUM,
        "DllCharacteristics": _PE_DLL_CHARACTERISTICS,
        "SizeOfStackReserve": _PE_STACK_RESERVE,
        "SizeOfStackCommit": _PE_STACK_COMMIT,
        "SizeOfHeapReserve": _PE_HEAP_RESERVE,
        "SizeOfHeapCommit": _PE_HEAP_COMMIT,
        "LoaderFlags": _PE_LOADER_FLAGS,
    }
    for name, value in fixed_defaults.items():
        expected = expected_defaults[name]
        if value != expected:
            raise NativeCodegenError(f"native PE image OptionalHeader {name} 默认值不一致: 期望 {expected}, 实际 {value}")
    fixed_values = {
        "Magic": _u16(pe_image, offset),
        "SizeOfCode": _u32(pe_image, offset + 4),
        "SizeOfInitializedData": _u32(pe_image, offset + 8),
        "SizeOfUninitializedData": _u32(pe_image, offset + 12),
        "AddressOfEntryPoint": _u32(pe_image, offset + 16),
        "BaseOfCode": _u32(pe_image, offset + 20),
        "ImageBase": _u64(pe_image, offset + 24),
        "SectionAlignment": _u32(pe_image, offset + 32),
        "FileAlignment": _u32(pe_image, offset + 36),
        "SizeOfImage": _u32(pe_image, offset + 56),
        "SizeOfHeaders": _u32(pe_image, offset + 60),
        "Subsystem": _u16(pe_image, offset + 68),
        "NumberOfRvaAndSizes": _u32(pe_image, offset + 108),
    }
    for name, value in fixed_values.items():
        if value != _require_int(optional_header, name):
            raise NativeCodegenError(f"native PE image OptionalHeader {name} 不一致: 期望 {optional_header[name]}, 实际 {value}")
    data_directory_offset = offset + 112
    data_directory_size = _require_int(optional_header, "NumberOfRvaAndSizes") * 8
    if pe_image[data_directory_offset:data_directory_offset + data_directory_size] != bytes(data_directory_size):
        raise NativeCodegenError("native PE image data directory 必须全部为空")


def _validate_section_header(pe_image: bytes, metadata: dict[str, object]) -> None:
    """校验 .text section header。"""
    text_section = _single_text_section(metadata)
    section_header = _require_mapping(text_section, "pe_section_header")
    offset = _require_int(metadata, "pe_section_table_offset")
    names = (
        "NameBytes",
        "VirtualSize",
        "VirtualAddress",
        "SizeOfRawData",
        "PointerToRawData",
        "PointerToRelocations",
        "PointerToLinenumbers",
        "NumberOfRelocations",
        "NumberOfLinenumbers",
        "Characteristics",
    )
    fields = struct.unpack_from("<8sIIIIIIHHI", pe_image, offset)
    values = (fields[0].hex(" ").upper(), *fields[1:])
    for name, value in zip(names, values, strict=True):
        expected = _require_str(section_header, name) if name == "NameBytes" else _require_int(section_header, name)
        if value != expected:
            raise NativeCodegenError(f"native PE image .text section header {name} 不一致: 期望 {expected!r}, 实际 {value!r}")


def _validate_pe_range(pe_image: bytes, metadata: dict[str, object], name: str) -> tuple[int, int, int]:
    """校验 PE 文件布局段范围。"""
    file_layout = _require_mapping(metadata, "pe_file_layout")
    item = _require_mapping(file_layout, name)
    offset = _require_int(item, "offset")
    size = _require_int(item, "size")
    end_offset = _require_int(item, "end_offset")
    if end_offset != offset + size:
        raise NativeCodegenError(f"native PE image layout {name}.end_offset 不一致")
    if offset < 0 or size < 0 or end_offset > len(pe_image):
        raise NativeCodegenError(f"native PE image layout {name} 越界")
    return offset, size, end_offset


def _single_text_section(metadata: dict[str, object]) -> dict[str, object]:
    """读取唯一 .text section map。"""
    sections = metadata.get("sections")
    if not isinstance(sections, list):
        raise NativeCodegenError("native PE image map 字段 sections 必须是列表")
    text_sections = [section for section in sections if isinstance(section, dict) and section.get("name") == ".text"]
    if len(text_sections) != 1:
        raise NativeCodegenError(f"native PE image map .text section 数量必须为 1，实际 {len(text_sections)}")
    return text_sections[0]


def _require_mapping(owner: dict[str, object], field: str) -> dict[str, object]:
    """读取必需对象字段。"""
    value = owner.get(field)
    if not isinstance(value, dict):
        raise NativeCodegenError(f"native PE image 字段 {field} 必须是对象")
    return value


def _require_int(owner: dict[str, object], field: str) -> int:
    """读取必需整数字段。"""
    value = owner.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise NativeCodegenError(f"native PE image 字段 {field} 必须是整数")
    return value


def _require_str(owner: dict[str, object], field: str) -> str:
    """读取必需字符串字段。"""
    value = owner.get(field)
    if not isinstance(value, str):
        raise NativeCodegenError(f"native PE image 字段 {field} 必须是字符串")
    return value


def _u16(data: bytes, offset: int) -> int:
    """读取 little-endian uint16。"""
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    """读取 little-endian uint32。"""
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    """读取 little-endian uint64。"""
    return struct.unpack_from("<Q", data, offset)[0]

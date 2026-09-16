"""稳定 Windows AOT 映像：独立启动、基址重定位与严格 map 校验。"""

import copy
import hashlib
import json
import struct

from verbose_c.compiler.native.errors import NativeCodegenError
from verbose_c.compiler.native.pe_layout import PE_FILE_ALIGNMENT, PE_SECTION_ALIGNMENT
from verbose_c.compiler.native.relocations import build_base_relocations
from verbose_c.compiler.native.runtime_image import runtime_base_map, runtime_image_map, validate_runtime_map


def aot_image_map(base: dict[str, object]) -> dict[str, object]:
    """为完整运行时 map 增加可重定位启动节与 .reloc 节。

    Args:
        base: 使用 schema 2 的运行时 map，代码、常量和 IAT 均已链接。

    Returns:
        schema 3 map；保留原代码 RVA，重新计算文件偏移和 PE 头。
    """
    if base.get("schema_version") != 2:
        raise NativeCodegenError("正式 AOT 编译需要完整的 Windows 运行时")
    metadata = copy.deepcopy(base)
    stub_rva = base["pe_size_of_image"]
    target_va = base["image_base"] + base["pe_address_of_entry_point"]
    # 启动跳转实际使用这个绝对地址，验证 loader 的 DIR64 修补闭环。
    stub = b"\x48\xB8" + struct.pack("<Q", target_va) + b"\xFF\xE0"
    relocations = build_base_relocations([stub_rva + 2])
    reloc_rva = stub_rva + PE_SECTION_ALIGNMENT
    metadata["schema_version"] = 3
    metadata["aot"] = {
        "runtime_abi_version": 1,
        "entry_stub": stub.hex(),
        "base_relocations": [{"rva": stub_rva + 2, "type": "DIR64"}],
        "relocations": relocations.hex(),
        "relocation_directory": {"rva": reloc_rva, "size": len(relocations)},
    }
    for name, payload, rva, flags, permissions in (
        (".aot", stub, stub_rva, 0x60000020, ["read", "execute"]),
        (".reloc", relocations, reloc_rva, 0x42000040, ["read", "discardable"]),
    ):
        metadata["sections"].append({
            "name": name, "rva": rva, "virtual_size": len(payload),
            "raw_size_aligned": PE_FILE_ALIGNMENT, "sha256": hashlib.sha256(payload).hexdigest(),
            "permissions": permissions,
            "pe_section_header": {
                "NameBytes": name.encode("ascii").ljust(8, b"\0").hex(" ").upper(),
                "VirtualSize": len(payload), "VirtualAddress": rva, "SizeOfRawData": PE_FILE_ALIGNMENT,
                "PointerToRelocations": 0, "PointerToLinenumbers": 0,
                "NumberOfRelocations": 0, "NumberOfLinenumbers": 0, "Characteristics": flags,
            },
        })
    section_count = len(metadata["sections"])
    metadata["pe_number_of_sections"] = section_count
    metadata["pe_coff_header"].update(NumberOfSections=section_count, Characteristics=0x22)
    metadata["pe_section_table_size"] = section_count * metadata["pe_section_header_size"]
    layout = metadata["pe_file_layout"]
    table = layout["section_table"]
    table["size"] = metadata["pe_section_table_size"]
    table["end_offset"] = table["offset"] + table["size"]
    headers = (table["end_offset"] + PE_FILE_ALIGNMENT - 1) // PE_FILE_ALIGNMENT * PE_FILE_ALIGNMENT
    metadata["pe_size_of_headers"] = headers
    layout["headers_padding"] = {"offset": table["end_offset"], "size": headers - table["end_offset"], "end_offset": headers}
    pointer = headers
    for section in metadata["sections"]:
        size = section["raw_size_aligned"]
        section["pe_raw_pointer"] = pointer
        section["pe_raw_end_pointer"] = pointer + size
        section["pe_section_header"]["PointerToRawData"] = pointer
        layout[section["name"][1:] + "_raw"] = {"offset": pointer, "size": size, "end_offset": pointer + size}
        pointer += size
    layout["file_size"] = pointer
    metadata["pe_size_of_code"] += PE_FILE_ALIGNMENT
    metadata["pe_size_of_initialized_data"] += PE_FILE_ALIGNMENT
    metadata["pe_size_of_image"] = reloc_rva + PE_SECTION_ALIGNMENT
    metadata["pe_address_of_entry_point"] = stub_rva
    metadata["pe_optional_header"].update(
        SizeOfCode=metadata["pe_size_of_code"], SizeOfInitializedData=metadata["pe_size_of_initialized_data"],
        SizeOfImage=metadata["pe_size_of_image"], SizeOfHeaders=headers, AddressOfEntryPoint=stub_rva,
        DllCharacteristics=0x160,
    )
    return metadata


def aot_base_map(metadata: dict[str, object]) -> dict[str, object]:
    """还原 schema 2 map，供独立校验和内存执行复用原运行时。"""
    base = copy.deepcopy(metadata)
    base.pop("aot")
    base["pe_coff_header"]["Characteristics"] = 0x22
    base["pe_optional_header"].pop("DllCharacteristics")
    base["pe_size_of_code"] = base["sections"][0]["raw_size_aligned"]
    base["pe_optional_header"]["SizeOfCode"] = base["pe_size_of_code"]
    base["pe_file_layout"].pop("aot_raw")
    base["pe_file_layout"].pop("reloc_raw")
    raw = base["runtime"]
    runtime = {**raw, "rodata": bytes.fromhex(raw["rodata"]), "idata": bytes.fromhex(raw["idata"])}
    return runtime_image_map(runtime_base_map(base), runtime)


def validate_aot_map(code: bytes, metadata: dict[str, object]) -> None:
    """验证 AOT 的代码、运行时、启动地址、重定位项和完整文件布局。"""
    try:
        base = aot_base_map(metadata)
        validate_runtime_map(code, base)
        expected = aot_image_map(base)
        if json.dumps(expected, sort_keys=True) != json.dumps(metadata, sort_keys=True):
            raise NativeCodegenError("AOT map 启动地址、基址重定位或 PE 布局不一致")
    except (KeyError, TypeError, ValueError, IndexError, struct.error) as error:
        raise NativeCodegenError(f"AOT map 无效：{error}") from error


def build_aot_pe(code: bytes, metadata: dict[str, object]) -> bytes:
    """由已校验的 AOT map 构造带 ASLR、DEP 和 DIR64 重定位的 PE32+。

    Args:
        code: 已链接的用户代码及 Windows 运行时机器码。
        metadata: 对应的 schema 3 map。

    Returns:
        不依赖 Python、CRT 或额外 DLL 的完整 exe 字节。
    """
    from verbose_c.compiler.native.runtime_image import build_runtime_pe

    validate_aot_map(code, metadata)
    base = aot_base_map(metadata)
    original = build_runtime_pe(code, base)
    image = bytearray(metadata["pe_file_layout"]["file_size"])
    header_end = metadata["pe_section_table_offset"]
    image[:header_end] = original[:header_end]
    coff = metadata["pe_coff_header_offset"]
    optional = metadata["pe_optional_header_offset"]
    struct.pack_into("<H", image, coff + 2, metadata["pe_number_of_sections"])
    struct.pack_into("<H", image, coff + 18, metadata["pe_coff_header"]["Characteristics"])
    for offset, field in ((4, "pe_size_of_code"), (8, "pe_size_of_initialized_data"),
                          (16, "pe_address_of_entry_point"), (56, "pe_size_of_image"), (60, "pe_size_of_headers")):
        struct.pack_into("<I", image, optional + offset, metadata[field])
    struct.pack_into("<H", image, optional + 70, metadata["pe_optional_header"]["DllCharacteristics"])
    directory = metadata["aot"]["relocation_directory"]
    struct.pack_into("<II", image, optional + 112 + 5 * 8, directory["rva"], directory["size"])
    payloads = [code, bytes.fromhex(metadata["runtime"]["rodata"]), bytes.fromhex(metadata["runtime"]["idata"]),
                bytes.fromhex(metadata["aot"]["entry_stub"]), bytes.fromhex(metadata["aot"]["relocations"])]
    for index, (section, payload) in enumerate(zip(metadata["sections"], payloads)):
        header = section["pe_section_header"]
        struct.pack_into("<8sIIIIIIHHI", image, header_end + index * 40,
                         bytes.fromhex(header["NameBytes"]), header["VirtualSize"], header["VirtualAddress"],
                         header["SizeOfRawData"], header["PointerToRawData"], 0, 0, 0, 0, header["Characteristics"])
        pointer = header["PointerToRawData"]
        image[pointer:pointer + len(payload)] = payload
    return bytes(image)

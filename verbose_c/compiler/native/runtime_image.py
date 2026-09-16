"""带 I/O 运行时的 PE 布局及 map 校验。"""

import copy
import hashlib
import struct

from verbose_c.compiler.native.errors import NativeCodegenError
from verbose_c.compiler.native.runtime import IMPORTS, build_import_table


def runtime_image_map(base, runtime):
    """在已有代码 map 上补上只读数据和可写 IAT。

    保留原代码 map 的严格校验信息，新增 schema 2 描述两个数据节、
    系统导入及 RIP 相对地址修补；所有节均不同时拥有写入和执行权限。

    Args:
        base: 原代码节的 schema 1 map。
        runtime: 已链接的运行时代码对应的数据节和地址信息。

    Returns:
        包含完整 PE 布局的 schema 2 map。
    """
    metadata = copy.deepcopy(base)
    metadata["schema_version"] = 2
    metadata["runtime"] = {
        "rodata": runtime["rodata"].hex(), "idata": runtime["idata"].hex(),
        "rdata_rva": runtime["rdata_rva"], "idata_rva": runtime["idata_rva"],
        "iat_offsets": dict(runtime["iat_offsets"]), "pe_entry_offset": runtime["pe_entry_offset"],
        "references": [list(item) for item in runtime["references"]],
    }
    metadata["pe_number_of_sections"] = 3
    metadata["pe_coff_header"]["NumberOfSections"] = 3
    metadata["pe_section_table_size"] = 3 * metadata["pe_section_header_size"]
    layout = metadata["pe_file_layout"]
    table = layout["section_table"]
    table["size"] = metadata["pe_section_table_size"]
    table["end_offset"] = table["offset"] + table["size"]
    headers = (table["end_offset"] + 511) // 512 * 512
    metadata["pe_size_of_headers"] = headers
    layout["headers_padding"] = {"offset": table["end_offset"], "size": headers - table["end_offset"], "end_offset": headers}
    pointer = headers
    for section in metadata["sections"]:
        section["pe_raw_pointer"] = pointer
        section["pe_raw_end_pointer"] = pointer + section["raw_size_aligned"]
        section["pe_section_header"]["PointerToRawData"] = pointer
        layout["text_raw"] = {"offset": pointer, "size": section["raw_size_aligned"], "end_offset": section["pe_raw_end_pointer"]}
        pointer = section["pe_raw_end_pointer"]
    data_size = 0
    for name, payload, rva, flags in (
        (".rdata", runtime["rodata"], runtime["rdata_rva"], 0x40000040),
        (".idata", runtime["idata"], runtime["idata_rva"], 0xC0000040),
    ):
        raw_size = (len(payload) + 511) // 512 * 512
        metadata["sections"].append({
            "name": name, "rva": rva, "virtual_size": len(payload),
            "raw_size_aligned": raw_size, "pe_raw_pointer": pointer,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "permissions": ["read", "write"] if name == ".idata" else ["read"],
            "pe_section_header": {
                "NameBytes": name.encode("ascii").ljust(8, b"\0").hex(" ").upper(),
                "VirtualSize": len(payload), "VirtualAddress": rva, "SizeOfRawData": raw_size,
                "PointerToRawData": pointer, "PointerToRelocations": 0, "PointerToLinenumbers": 0,
                "NumberOfRelocations": 0, "NumberOfLinenumbers": 0, "Characteristics": flags,
            },
        })
        layout[name[1:] + "_raw"] = {"offset": pointer, "size": raw_size, "end_offset": pointer + raw_size}
        pointer += raw_size
        data_size += raw_size
    layout["file_size"] = pointer
    metadata["pe_size_of_initialized_data"] = data_size
    metadata["pe_size_of_image"] = runtime["idata_rva"] + (len(runtime["idata"]) + 4095) // 4096 * 4096
    metadata["pe_address_of_entry_point"] = 4096 + runtime["pe_entry_offset"]
    optional = metadata["pe_optional_header"]
    optional.update(SizeOfInitializedData=data_size, SizeOfImage=metadata["pe_size_of_image"],
                    SizeOfHeaders=headers, AddressOfEntryPoint=metadata["pe_address_of_entry_point"])
    return metadata


def runtime_base_map(metadata):
    """还原代码节 map，复用既有的机器码和元数据完整性校验。"""
    base = copy.deepcopy(metadata)
    base.pop("runtime")
    base["schema_version"] = 1
    base["pe_number_of_sections"] = 1
    base["pe_coff_header"]["NumberOfSections"] = 1
    base["pe_section_table_size"] = base["pe_section_header_size"]
    layout = base["pe_file_layout"]
    table = layout["section_table"]
    table["size"] = base["pe_section_table_size"]
    table["end_offset"] = table["offset"] + table["size"]
    headers = (table["end_offset"] + 511) // 512 * 512
    base["pe_size_of_headers"] = headers
    layout["headers_padding"] = {"offset": table["end_offset"], "size": headers - table["end_offset"], "end_offset": headers}
    base["sections"] = base["sections"][:1]
    section = base["sections"][0]
    section["pe_raw_pointer"] = headers
    section["pe_raw_end_pointer"] = headers + section["raw_size_aligned"]
    section["pe_section_header"]["PointerToRawData"] = headers
    layout["text_raw"] = {"offset": headers, "size": section["raw_size_aligned"], "end_offset": section["pe_raw_end_pointer"]}
    layout.pop("rdata_raw")
    layout.pop("idata_raw")
    layout["file_size"] = section["pe_raw_end_pointer"]
    base["pe_size_of_initialized_data"] = 0
    base["pe_size_of_image"] = 4096 + (base["code_size"] + 4095) // 4096 * 4096
    base["pe_address_of_entry_point"] = base["entry_rva"]
    base["pe_optional_header"].update(SizeOfInitializedData=0, SizeOfImage=base["pe_size_of_image"],
                                       SizeOfHeaders=headers, AddressOfEntryPoint=base["entry_rva"])
    return base


def validate_runtime_map(code, metadata):
    """校验数据节、导入内容、RIP 引用以及原有代码 map。"""
    from verbose_c.compiler.native.map_format import validate_native_code_map_bytes

    try:
        raw = metadata["runtime"]
        runtime = {**raw, "rodata": bytes.fromhex(raw["rodata"]), "idata": bytes.fromhex(raw["idata"])}
        expected_rdata = 4096 + (len(code) + 4095) // 4096 * 4096
        expected_idata = expected_rdata + max(4096, (len(runtime["rodata"]) + 4095) // 4096 * 4096)
        if runtime["rdata_rva"] != expected_rdata or runtime["idata_rva"] != expected_idata:
            raise NativeCodegenError("native 运行时数据节 RVA 不一致")
        idata, offsets = build_import_table(expected_idata)
        if runtime["idata"] != idata or runtime["iat_offsets"] != offsets:
            raise NativeCodegenError("native KERNEL32 导入表不一致")
        if not 0 <= runtime["pe_entry_offset"] < len(code):
            raise NativeCodegenError("native PE 运行时入口越界")
        entries = [item for item in metadata["functions"] if item["name"] == "<native:pe_start>"]
        if len(entries) != 1 or entries[0]["offset"] != runtime["pe_entry_offset"]:
            raise NativeCodegenError("native PE 入口与运行时函数不一致")
        patches = set()
        for patch, kind, rva in runtime["references"]:
            if patch in patches or not 0 <= patch <= len(code) - 4:
                raise NativeCodegenError("native 运行时引用重复或越界")
            patches.add(patch)
            if kind == "import":
                valid = rva in {expected_idata + offset for offset in offsets.values()}
            elif kind == "constant":
                valid = expected_rdata <= rva < expected_rdata + len(runtime["rodata"])
            elif kind == "code":
                valid = 4096 <= rva < 4096 + len(code)
            else:
                valid = False
            if not valid or struct.unpack_from("<i", code, patch)[0] != rva - (4096 + patch + 4):
                raise NativeCodegenError("native 运行时相对地址不一致")
        base = runtime_base_map(metadata)
        validate_native_code_map_bytes(code, base)
        if runtime_image_map(base, runtime) != metadata:
            raise NativeCodegenError("native 运行时 map 布局或数据摘要不一致")
    except (KeyError, TypeError, ValueError, IndexError, struct.error) as error:
        raise NativeCodegenError(f"native 运行时 map 无效：{error}") from error


def build_runtime_pe(code, metadata):
    """由已校验的代码及数据节构建完整 PE32+，仅依赖系统 DLL。"""
    from verbose_c.compiler.native.pe_writer import build_native_pe_image

    validate_runtime_map(code, metadata)
    base = runtime_base_map(metadata)
    image = bytearray(build_native_pe_image(code, base))
    image.extend(bytes(metadata["pe_file_layout"]["file_size"] - len(image)))
    coff = metadata["pe_coff_header_offset"]
    optional = metadata["pe_optional_header_offset"]
    struct.pack_into("<H", image, coff + 2, 3)
    struct.pack_into("<I", image, optional + 8, metadata["pe_size_of_initialized_data"])
    struct.pack_into("<I", image, optional + 16, metadata["pe_address_of_entry_point"])
    struct.pack_into("<I", image, optional + 56, metadata["pe_size_of_image"])
    struct.pack_into("<I", image, optional + 60, metadata["pe_size_of_headers"])
    # 代码使用 RIP 相对寻址；没有绝对地址重定位，也无需 CRT 初始化。
    struct.pack_into("<H", image, optional + 70, 0x100)
    runtime = metadata["runtime"]
    struct.pack_into("<II", image, optional + 120, runtime["idata_rva"], 40)
    struct.pack_into("<II", image, optional + 112 + 12 * 8,
                     runtime["idata_rva"] + min(runtime["iat_offsets"].values()), (len(IMPORTS) + 1) * 8)
    for index, section in enumerate(metadata["sections"]):
        header = section["pe_section_header"]
        struct.pack_into("<8sIIIIIIHHI", image, metadata["pe_section_table_offset"] + index * 40,
                         bytes.fromhex(header["NameBytes"]), header["VirtualSize"], header["VirtualAddress"],
                         header["SizeOfRawData"], header["PointerToRawData"], 0, 0, 0, 0, header["Characteristics"])
        payload = code if index == 0 else bytes.fromhex(runtime["rodata" if index == 1 else "idata"])
        offset = header["PointerToRawData"]
        image[offset:offset + len(payload)] = payload
    return bytes(image)

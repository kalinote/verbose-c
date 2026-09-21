"""Native map 构建与结构、字节一致性校验。"""

import hashlib
from verbose_c.compiler.native.abi import (
    FLOAT_VALUE_TYPES,
    SUPPORTED_ARGUMENT_REGISTERS,
    SUPPORTED_RETURN_TYPES,
    SUPPORTED_VALUE_TYPES,
    is_argument_type_compatible,
)
from verbose_c.compiler.native.encoder import encode_sub_rsp_imm32
from verbose_c.compiler.native.errors import NativeCodegenError
from verbose_c.compiler.native.model import (
    NativeCodeProgram,
    NativeStackSlotAllocation,
    native_program_symbols,
    native_symbol_function,
    native_value_location,
    native_stack_slot_map,
    validate_native_array_layout,
)
from verbose_c.compiler.native.pe_layout import (
    PE_COFF_HEADER_SIZE,
    PE_DOS_HEADER_SIZE,
    PE_FILE_ALIGNMENT,
    PE_IMAGE_BASE,
    PE_LFANEW,
    PE_OPTIONAL_HEADER_SIZE,
    PE_SECTION_ALIGNMENT,
    PE_SECTION_HEADER_SIZE,
    PE_SIGNATURE_SIZE,
    PE_TEXT_RVA,
)
from verbose_c.compiler.native.relocations import (
    CALL_REL32_SIZE,
    JNE_REL32_SIZE,
    REL32_JUMP_ASM_PREFIXES,
    REL32_JUMP_OPCODES,
    TEST_RDX_RDX_SIZE,
)
from verbose_c.compiler.native.target import NativeTarget


_MAP_TOP_LEVEL_FIELDS = {
    "schema_version",
    "target",
    "pe_machine",
    "pe_machine_value",
    "pe_coff_header",
    "pe_optional_header_magic",
    "pe_optional_header_magic_value",
    "pe_optional_header",
    "pe_subsystem",
    "pe_subsystem_value",
    "pe_number_of_sections",
    "pe_dos_header_size",
    "pe_lfanew",
    "pe_signature_offset",
    "pe_signature_size",
    "pe_coff_header_offset",
    "pe_coff_header_size",
    "pe_optional_header_offset",
    "pe_optional_header_size",
    "pe_section_table_offset",
    "pe_section_header_size",
    "pe_section_table_size",
    "pe_size_of_headers",
    "pe_file_layout",
    "pe_base_of_code",
    "pe_address_of_entry_point",
    "pe_size_of_code",
    "pe_size_of_initialized_data",
    "pe_size_of_uninitialized_data",
    "pe_size_of_image",
    "pe_file_alignment",
    "pe_section_alignment",
    "image_base",
    "abi",
    "entry",
    "entry_offset",
    "entry_rva",
    "entry_va",
    "global_frame_owner",
    "code_size",
    "code_sha256",
    "sections",
    "symbols",
    "functions",
}


_MAP_PE_FILE_LAYOUT_FIELDS = {
    "dos_header",
    "dos_stub_padding",
    "pe_signature",
    "coff_header",
    "optional_header",
    "section_table",
    "headers_padding",
    "text_raw",
    "file_size",
}


_MAP_PE_FILE_LAYOUT_RANGE_FIELDS = {
    "offset",
    "size",
    "end_offset",
}


_MAP_PE_COFF_HEADER_FIELDS = {
    "Machine",
    "NumberOfSections",
    "TimeDateStamp",
    "PointerToSymbolTable",
    "NumberOfSymbols",
    "SizeOfOptionalHeader",
    "Characteristics",
}


_MAP_PE_OPTIONAL_HEADER_FIELDS = {
    "Magic",
    "SizeOfCode",
    "SizeOfInitializedData",
    "SizeOfUninitializedData",
    "AddressOfEntryPoint",
    "BaseOfCode",
    "ImageBase",
    "SectionAlignment",
    "FileAlignment",
    "SizeOfImage",
    "SizeOfHeaders",
    "Subsystem",
    "NumberOfRvaAndSizes",
}


_MAP_ABI_FIELDS = {
    "name",
    "target",
    "word_size",
    "stack_alignment",
    "shadow_space_size",
    "argument_registers",
    "return_register",
    "frame_pointer",
    "stack_pointer",
    "supported_value_types",
}


_MAP_TEXT_SECTION_FIELDS = {
    "name",
    "name_bytes",
    "offset",
    "size",
    "end_offset",
    "virtual_size",
    "raw_size_aligned",
    "raw_padding_size",
    "raw_padded_sha256",
    "virtual_size_aligned",
    "rva",
    "end_rva",
    "va",
    "end_va",
    "entry_offset",
    "pe_raw_pointer",
    "pe_raw_end_pointer",
    "pe_section_header",
    "sha256",
    "alignment",
    "file_alignment",
    "section_alignment",
    "permissions",
    "characteristics",
    "pe_characteristics",
}


_MAP_PE_SECTION_HEADER_FIELDS = {
    "Name",
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
}


_MAP_FUNCTION_FIELDS = {
    "name",
    "offset",
    "rva",
    "va",
    "size",
    "end_offset",
    "end_rva",
    "end_va",
    "code_sha256",
    "frame_size",
    "return_type",
    "param_types",
    "register_allocation",
    "stack_slots",
    "value_locations",
    "labels",
    "call_frames",
    "relocations",
    "exit_probes",
    "instructions",
}


_MAP_SYMBOL_FIELDS = {
    "name",
    "kind",
    "offset",
    "rva",
    "va",
    "size",
    "end_offset",
    "end_rva",
    "end_va",
    "code_sha256",
    "is_entry",
    "return_type",
    "param_types",
}


_MAP_STACK_SLOT_FIELDS = {
    "name",
    "offset",
    "size",
    "array_length",
    "element_type",
}


_MAP_VALUE_LOCATION_FIELDS = {
    "name",
    "kind",
    "index",
    "storage",
    "base_register",
    "offset",
    "size",
}


_MAP_REGISTER_ALLOCATION_FIELDS = {
    "strategy",
    "temporary_registers",
    "argument_registers",
    "return_register",
    "frame_pointer",
    "stack_pointer",
    "virtual_register_storage",
    "local_storage",
    "global_frame_register",
    "global_frame_role",
}


_MAP_LABEL_FIELDS = {
    "name",
    "offset",
    "rva",
    "va",
    "source_pc",
    "source_line",
}


_MAP_INSTRUCTION_FIELDS = {
    "offset",
    "rva",
    "va",
    "size",
    "end_offset",
    "end_rva",
    "end_va",
    "bytes",
    "code_sha256",
    "asm",
    "source_op",
    "source_attrs",
    "source_pc",
    "source_line",
}


_MAP_CALL_FRAME_FIELDS = {
    "offset",
    "end_offset",
    "sub_code_sha256",
    "rva",
    "end_rva",
    "va",
    "end_va",
    "call_offset",
    "call_end_offset",
    "call_code_sha256",
    "call_rva",
    "call_end_rva",
    "call_va",
    "call_end_va",
    "add_offset",
    "add_end_offset",
    "add_code_sha256",
    "add_rva",
    "add_end_rva",
    "add_va",
    "add_end_va",
    "target",
    "arg_count",
    "arg_types",
    "param_types",
    "register_arg_count",
    "stack_arg_count",
    "shadow_space_size",
    "stack_arg_bytes",
    "aligned_size",
    "stack_alignment",
    "source_pc",
    "source_line",
}


_MAP_RELOCATION_FIELDS = {
    "offset",
    "rva",
    "va",
    "patch_offset",
    "patch_rva",
    "patch_va",
    "patch_end_offset",
    "patch_end_rva",
    "patch_end_va",
    "instruction_code_sha256",
    "patch_code_sha256",
    "kind",
    "target",
    "target_rva",
    "target_va",
    "displacement",
    "size",
    "source_pc",
    "source_line",
}


_MAP_EXIT_PROBE_FIELDS = {
    "call_offset",
    "call_end_offset",
    "call_code_sha256",
    "call_rva",
    "call_end_rva",
    "call_va",
    "call_end_va",
    "test_offset",
    "test_end_offset",
    "test_code_sha256",
    "test_rva",
    "test_end_rva",
    "test_va",
    "test_end_va",
    "jump_offset",
    "jump_end_offset",
    "jump_code_sha256",
    "jump_rva",
    "jump_end_rva",
    "jump_va",
    "jump_end_va",
    "target",
    "probe_label",
    "source_pc",
    "source_line",
}


def native_code_program_map(program: NativeCodeProgram) -> dict[str, object]:
    """生成代码 map，并按需补上 Windows I/O 运行时节。"""
    metadata = _native_code_program_map(program)
    if program.runtime:
        from verbose_c.compiler.native.runtime_image import runtime_image_map
        metadata = runtime_image_map(metadata, program.runtime)
    if program.aot:
        from verbose_c.compiler.native.aot_image import aot_image_map
        metadata = aot_image_map(metadata)
    return metadata


def _native_code_program_map(program: NativeCodeProgram) -> dict[str, object]:
    """生成 native 机器码结构化 map。"""
    code_size = len(program.code)
    code_sha256 = hashlib.sha256(program.code).hexdigest()
    raw_size_aligned = ((code_size + PE_FILE_ALIGNMENT - 1) // PE_FILE_ALIGNMENT) * PE_FILE_ALIGNMENT
    raw_padding_size = raw_size_aligned - code_size
    raw_padded_sha256 = hashlib.sha256(program.code + bytes(raw_padding_size)).hexdigest()
    virtual_size_aligned = ((code_size + PE_SECTION_ALIGNMENT - 1) // PE_SECTION_ALIGNMENT) * PE_SECTION_ALIGNMENT
    section_table_offset = PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE + PE_OPTIONAL_HEADER_SIZE
    section_table_size = PE_SECTION_HEADER_SIZE
    pe_size_of_headers = ((section_table_offset + section_table_size + PE_FILE_ALIGNMENT - 1) // PE_FILE_ALIGNMENT) * PE_FILE_ALIGNMENT
    text_rva = PE_TEXT_RVA
    image_base = PE_IMAGE_BASE
    label_records_by_function = {
        function.name: {
            instruction.asm[:-1]: {
                "name": instruction.asm[:-1],
                "offset": instruction.offset,
                "rva": text_rva + instruction.offset,
                "va": image_base + text_rva + instruction.offset,
                "source_pc": instruction.source_pc,
                "source_line": instruction.source_line,
            }
            for instruction in function.instructions
            if instruction.source_op == "label" and instruction.asm.endswith(":")
        }
        for function in program.functions.values()
    }
    global_frame_owners = [
        function.name
        for function in program.functions.values()
        if any(
            instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
            for instruction in function.instructions
        )
    ]
    return {
        "schema_version": 1,
        "target": program.target.value,
        "pe_machine": "AMD64",
        "pe_machine_value": 0x8664,
        "pe_coff_header": {
            "Machine": 0x8664,
            "NumberOfSections": 1,
            "TimeDateStamp": 0,
            "PointerToSymbolTable": 0,
            "NumberOfSymbols": 0,
            "SizeOfOptionalHeader": PE_OPTIONAL_HEADER_SIZE,
            "Characteristics": 0x22,
        },
        "pe_optional_header_magic": "PE32+",
        "pe_optional_header_magic_value": 0x20B,
        "pe_optional_header": {
            "Magic": 0x20B,
            "SizeOfCode": raw_size_aligned,
            "SizeOfInitializedData": 0,
            "SizeOfUninitializedData": 0,
            "AddressOfEntryPoint": text_rva + program.entry_offset,
            "BaseOfCode": text_rva,
            "ImageBase": image_base,
            "SectionAlignment": PE_SECTION_ALIGNMENT,
            "FileAlignment": PE_FILE_ALIGNMENT,
            "SizeOfImage": text_rva + virtual_size_aligned,
            "SizeOfHeaders": pe_size_of_headers,
            "Subsystem": 3,
            "NumberOfRvaAndSizes": 16,
        },
        "pe_subsystem": "console",
        "pe_subsystem_value": 3,
        "pe_number_of_sections": 1,
        "pe_dos_header_size": PE_DOS_HEADER_SIZE,
        "pe_lfanew": PE_LFANEW,
        "pe_signature_offset": PE_LFANEW,
        "pe_signature_size": PE_SIGNATURE_SIZE,
        "pe_coff_header_offset": PE_LFANEW + PE_SIGNATURE_SIZE,
        "pe_coff_header_size": PE_COFF_HEADER_SIZE,
        "pe_optional_header_offset": PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE,
        "pe_optional_header_size": PE_OPTIONAL_HEADER_SIZE,
        "pe_section_table_offset": section_table_offset,
        "pe_section_header_size": PE_SECTION_HEADER_SIZE,
        "pe_section_table_size": section_table_size,
        "pe_size_of_headers": pe_size_of_headers,
        "pe_file_layout": {
            "dos_header": {
                "offset": 0,
                "size": PE_DOS_HEADER_SIZE,
                "end_offset": PE_DOS_HEADER_SIZE,
            },
            "dos_stub_padding": {
                "offset": PE_DOS_HEADER_SIZE,
                "size": PE_LFANEW - PE_DOS_HEADER_SIZE,
                "end_offset": PE_LFANEW,
            },
            "pe_signature": {
                "offset": PE_LFANEW,
                "size": PE_SIGNATURE_SIZE,
                "end_offset": PE_LFANEW + PE_SIGNATURE_SIZE,
            },
            "coff_header": {
                "offset": PE_LFANEW + PE_SIGNATURE_SIZE,
                "size": PE_COFF_HEADER_SIZE,
                "end_offset": PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE,
            },
            "optional_header": {
                "offset": PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE,
                "size": PE_OPTIONAL_HEADER_SIZE,
                "end_offset": section_table_offset,
            },
            "section_table": {
                "offset": section_table_offset,
                "size": section_table_size,
                "end_offset": section_table_offset + section_table_size,
            },
            "headers_padding": {
                "offset": section_table_offset + section_table_size,
                "size": pe_size_of_headers - section_table_offset - section_table_size,
                "end_offset": pe_size_of_headers,
            },
            "text_raw": {
                "offset": pe_size_of_headers,
                "size": raw_size_aligned,
                "end_offset": pe_size_of_headers + raw_size_aligned,
            },
            "file_size": pe_size_of_headers + raw_size_aligned,
        },
        "pe_base_of_code": text_rva,
        "pe_address_of_entry_point": text_rva + program.entry_offset,
        "pe_size_of_code": raw_size_aligned,
        "pe_size_of_initialized_data": 0,
        "pe_size_of_uninitialized_data": 0,
        "pe_size_of_image": text_rva + virtual_size_aligned,
        "pe_file_alignment": 512,
        "pe_section_alignment": 4096,
        "image_base": image_base,
        "abi": {
            "name": program.abi.name,
            "target": program.abi.target.value,
            "word_size": program.abi.word_size,
            "stack_alignment": program.abi.stack_alignment,
            "shadow_space_size": program.abi.shadow_space_size,
            "argument_registers": list(program.abi.registers.argument_registers),
            "return_register": program.abi.registers.return_register,
            "frame_pointer": program.abi.registers.frame_pointer,
            "stack_pointer": program.abi.registers.stack_pointer,
            "supported_value_types": list(program.abi.supported_value_types),
        },
        "entry": program.entry.name,
        "entry_offset": program.entry_offset,
        "entry_rva": text_rva + program.entry_offset,
        "entry_va": image_base + text_rva + program.entry_offset,
        "global_frame_owner": global_frame_owners[0] if global_frame_owners else None,
        "code_size": code_size,
        "code_sha256": code_sha256,
        "sections": [
            {
                "name": ".text",
                "name_bytes": "2E 74 65 78 74 00 00 00",
                "offset": 0,
                "size": code_size,
                "end_offset": code_size,
                "virtual_size": code_size,
                "raw_size_aligned": raw_size_aligned,
                "raw_padding_size": raw_padding_size,
                "raw_padded_sha256": raw_padded_sha256,
                "virtual_size_aligned": virtual_size_aligned,
                "rva": text_rva,
                "end_rva": text_rva + code_size,
                "va": image_base + text_rva,
                "end_va": image_base + text_rva + code_size,
                "entry_offset": program.entry_offset,
                "pe_raw_pointer": pe_size_of_headers,
                "pe_raw_end_pointer": pe_size_of_headers + raw_size_aligned,
                "pe_section_header": {
                    "Name": ".text",
                    "NameBytes": "2E 74 65 78 74 00 00 00",
                    "VirtualSize": code_size,
                    "VirtualAddress": text_rva,
                    "SizeOfRawData": raw_size_aligned,
                    "PointerToRawData": pe_size_of_headers,
                    "PointerToRelocations": 0,
                    "PointerToLinenumbers": 0,
                    "NumberOfRelocations": 0,
                    "NumberOfLinenumbers": 0,
                    "Characteristics": 0x60000020,
                },
                "sha256": code_sha256,
                "alignment": 16,
                "file_alignment": PE_FILE_ALIGNMENT,
                "section_alignment": PE_SECTION_ALIGNMENT,
                "permissions": ["read", "execute"],
                "characteristics": ["CNT_CODE", "MEM_EXECUTE", "MEM_READ"],
                "pe_characteristics": 0x60000020,
            }
        ],
        "symbols": [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "offset": symbol.offset,
                "rva": text_rva + symbol.offset,
                "va": image_base + text_rva + symbol.offset,
                "size": symbol.size,
                "end_offset": symbol.offset + symbol.size,
                "end_rva": text_rva + symbol.offset + symbol.size,
                "end_va": image_base + text_rva + symbol.offset + symbol.size,
                "code_sha256": hashlib.sha256(native_symbol_function(program, symbol).code).hexdigest(),
                "is_entry": symbol.is_entry,
                "return_type": symbol.return_type,
                "param_types": list(symbol.param_types),
            }
            for symbol in native_program_symbols(program)
        ],
        "functions": [
            {
                "name": function.name,
                "offset": function.offset,
                "rva": text_rva + function.offset,
                "va": image_base + text_rva + function.offset,
                "size": len(function.code),
                "end_offset": function.offset + len(function.code),
                "end_rva": text_rva + function.offset + len(function.code),
                "end_va": image_base + text_rva + function.offset + len(function.code),
                "code_sha256": hashlib.sha256(function.code).hexdigest(),
                "frame_size": function.frame_size,
                "return_type": function.return_type,
                "param_types": list(function.param_types),
                "register_allocation": {
                    "strategy": function.register_allocation.strategy,
                    "temporary_registers": list(function.register_allocation.temporary_registers),
                    "argument_registers": list(function.register_allocation.argument_registers),
                    "return_register": function.register_allocation.return_register,
                    "frame_pointer": function.register_allocation.frame_pointer,
                    "stack_pointer": function.register_allocation.stack_pointer,
                    "virtual_register_storage": function.register_allocation.virtual_register_storage,
                    "local_storage": function.register_allocation.local_storage,
                    "global_frame_register": function.register_allocation.global_frame_register,
                    "global_frame_role": function.register_allocation.global_frame_role,
                },
                "stack_slots": [
                    native_stack_slot_map(slot)
                    for slot in function.stack_slots
                ],
                "value_locations": [
                    native_value_location(function.name, slot)
                    for slot in function.stack_slots
                ],
                "labels": [
                    dict(label_record)
                    for label_record in label_records_by_function[function.name].values()
                ],
                "call_frames": [
                    {
                        "offset": frame.offset,
                        "end_offset": frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size)),
                        "sub_code_sha256": hashlib.sha256(
                            program.code[frame.offset:frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size))]
                        ).hexdigest(),
                        "rva": text_rva + frame.offset,
                        "end_rva": text_rva + frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size)),
                        "va": image_base + text_rva + frame.offset,
                        "end_va": image_base + text_rva + frame.offset + len(encode_sub_rsp_imm32(frame.aligned_size)),
                        "call_offset": frame.call_offset,
                        "call_end_offset": frame.call_end_offset,
                        "call_code_sha256": (
                            hashlib.sha256(program.code[frame.call_offset:frame.call_end_offset]).hexdigest()
                            if frame.call_offset is not None and frame.call_end_offset is not None
                            else None
                        ),
                        "call_rva": text_rva + frame.call_offset if frame.call_offset is not None else None,
                        "call_end_rva": text_rva + frame.call_end_offset if frame.call_end_offset is not None else None,
                        "call_va": image_base + text_rva + frame.call_offset if frame.call_offset is not None else None,
                        "call_end_va": image_base + text_rva + frame.call_end_offset if frame.call_end_offset is not None else None,
                        "add_offset": frame.add_offset,
                        "add_end_offset": frame.add_end_offset,
                        "add_code_sha256": (
                            hashlib.sha256(program.code[frame.add_offset:frame.add_end_offset]).hexdigest()
                            if frame.add_offset is not None and frame.add_end_offset is not None
                            else None
                        ),
                        "add_rva": text_rva + frame.add_offset if frame.add_offset is not None else None,
                        "add_end_rva": text_rva + frame.add_end_offset if frame.add_end_offset is not None else None,
                        "add_va": image_base + text_rva + frame.add_offset if frame.add_offset is not None else None,
                        "add_end_va": image_base + text_rva + frame.add_end_offset if frame.add_end_offset is not None else None,
                        "target": frame.target,
                        "arg_count": frame.arg_count,
                        "arg_types": list(frame.arg_types),
                        "param_types": list(frame.param_types),
                        "register_arg_count": frame.register_arg_count,
                        "stack_arg_count": frame.stack_arg_count,
                        "shadow_space_size": frame.shadow_space_size,
                        "stack_arg_bytes": frame.stack_arg_bytes,
                        "aligned_size": frame.aligned_size,
                        "stack_alignment": frame.stack_alignment,
                        "source_pc": frame.source_pc,
                        "source_line": frame.source_line,
                    }
                    for frame in function.call_frames
                ],
                "relocations": [
                    {
                        "offset": relocation.offset,
                        "rva": text_rva + relocation.offset,
                        "va": image_base + text_rva + relocation.offset,
                        "patch_offset": relocation.patch_offset,
                        "patch_rva": text_rva + relocation.patch_offset,
                        "patch_va": image_base + text_rva + relocation.patch_offset,
                        "patch_end_offset": relocation.patch_offset + relocation.size,
                        "patch_end_rva": text_rva + relocation.patch_offset + relocation.size,
                        "patch_end_va": image_base + text_rva + relocation.patch_offset + relocation.size,
                        "instruction_code_sha256": hashlib.sha256(
                            program.code[relocation.offset:relocation.patch_offset + relocation.size]
                        ).hexdigest(),
                        "patch_code_sha256": hashlib.sha256(
                            program.code[relocation.patch_offset:relocation.patch_offset + relocation.size]
                        ).hexdigest(),
                        "kind": relocation.kind,
                        "target": relocation.target,
                        "target_rva": text_rva + (
                            program.functions[relocation.target].offset
                            if relocation.target in program.functions
                            else label_records_by_function[function.name][relocation.target]["offset"]
                        ),
                        "target_va": image_base + text_rva + (
                            program.functions[relocation.target].offset
                            if relocation.target in program.functions
                            else label_records_by_function[function.name][relocation.target]["offset"]
                        ),
                        "displacement": relocation.displacement,
                        "size": relocation.size,
                        "source_pc": relocation.source_pc,
                        "source_line": relocation.source_line,
                    }
                    for relocation in function.relocations
                ],
                "exit_probes": [
                    {
                        "call_offset": probe.call_offset,
                        "call_end_offset": probe.call_offset + CALL_REL32_SIZE,
                        "call_code_sha256": hashlib.sha256(
                            program.code[probe.call_offset:probe.call_offset + CALL_REL32_SIZE]
                        ).hexdigest(),
                        "call_rva": text_rva + probe.call_offset,
                        "call_end_rva": text_rva + probe.call_offset + CALL_REL32_SIZE,
                        "call_va": image_base + text_rva + probe.call_offset,
                        "call_end_va": image_base + text_rva + probe.call_offset + CALL_REL32_SIZE,
                        "test_offset": probe.test_offset,
                        "test_end_offset": probe.test_offset + TEST_RDX_RDX_SIZE,
                        "test_code_sha256": hashlib.sha256(
                            program.code[probe.test_offset:probe.test_offset + TEST_RDX_RDX_SIZE]
                        ).hexdigest(),
                        "test_rva": text_rva + probe.test_offset,
                        "test_end_rva": text_rva + probe.test_offset + TEST_RDX_RDX_SIZE,
                        "test_va": image_base + text_rva + probe.test_offset,
                        "test_end_va": image_base + text_rva + probe.test_offset + TEST_RDX_RDX_SIZE,
                        "jump_offset": probe.jump_offset,
                        "jump_end_offset": probe.jump_offset + JNE_REL32_SIZE,
                        "jump_code_sha256": hashlib.sha256(
                            program.code[probe.jump_offset:probe.jump_offset + JNE_REL32_SIZE]
                        ).hexdigest(),
                        "jump_rva": text_rva + probe.jump_offset,
                        "jump_end_rva": text_rva + probe.jump_offset + JNE_REL32_SIZE,
                        "jump_va": image_base + text_rva + probe.jump_offset,
                        "jump_end_va": image_base + text_rva + probe.jump_offset + JNE_REL32_SIZE,
                        "target": probe.target,
                        "probe_label": probe.probe_label,
                        "source_pc": probe.source_pc,
                        "source_line": probe.source_line,
                    }
                    for probe in function.exit_probes
                ],
                "instructions": [
                    {
                        "offset": instruction.offset,
                        "rva": text_rva + instruction.offset,
                        "va": image_base + text_rva + instruction.offset,
                        "size": len(instruction.code),
                        "end_offset": instruction.offset + len(instruction.code),
                        "end_rva": text_rva + instruction.offset + len(instruction.code),
                        "end_va": image_base + text_rva + instruction.offset + len(instruction.code),
                        "bytes": instruction.code.hex(" ").upper(),
                        "code_sha256": hashlib.sha256(instruction.code).hexdigest(),
                        "asm": instruction.asm,
                        "source_op": instruction.source_op,
                        "source_attrs": dict(instruction.source_attrs),
                        "source_pc": instruction.source_pc,
                        "source_line": instruction.source_line,
                    }
                    for instruction in function.instructions
                ],
            }
            for function in program.functions.values()
        ],
    }


def validate_native_code_program_map(program: NativeCodeProgram, metadata: dict[str, object]) -> None:
    """校验 native 机器码结构化 map 与程序一致。"""
    if not isinstance(metadata, dict):
        raise NativeCodegenError(f"native 机器码 map 必须是对象，实际 {type(metadata).__name__}")
    expected = native_code_program_map(program)
    validate_native_code_map_bytes(program.code, metadata)
    for key in (
        "schema_version",
        "target",
        "pe_machine",
        "pe_machine_value",
        "pe_optional_header_magic",
        "pe_optional_header_magic_value",
        "pe_subsystem",
        "pe_subsystem_value",
        "pe_number_of_sections",
        "pe_base_of_code",
        "pe_address_of_entry_point",
        "pe_size_of_code",
        "pe_size_of_initialized_data",
        "pe_size_of_uninitialized_data",
        "pe_size_of_image",
        "pe_file_alignment",
        "pe_section_alignment",
        "image_base",
        "abi",
        "entry",
        "entry_offset",
        "entry_rva",
        "entry_va",
        "global_frame_owner",
        "code_size",
        "code_sha256",
    ):
        if metadata.get(key) != expected[key]:
            raise NativeCodegenError(
                f"native 机器码 map 字段 {key} 不一致: 期望 {expected[key]!r}, 实际 {metadata.get(key)!r}"
            )
    for key in ("sections", "symbols", "functions"):
        if metadata.get(key) != expected[key]:
            detail = _describe_map_list_mismatch(key, expected[key], metadata.get(key))
            raise NativeCodegenError(f"native 机器码 map 字段 {key} 不一致: {detail}")


def _describe_map_list_mismatch(key: str, expected: object, actual: object) -> str:
    """描述结构化 map 列表字段的首个差异。"""
    return _describe_map_value_mismatch(key, expected, actual)


def _describe_map_value_mismatch(path: str, expected: object, actual: object) -> str:
    """递归描述结构化 map 字段的首个差异。"""
    if not isinstance(expected, list) or not isinstance(actual, list):
        if isinstance(expected, list) != isinstance(actual, list):
            return f"期望 {type(expected).__name__}, 实际 {type(actual).__name__}"
        if isinstance(expected, dict) and isinstance(actual, dict):
            expected_keys = set(expected)
            actual_keys = set(actual)
            if expected_keys != actual_keys:
                missing = sorted(expected_keys - actual_keys)
                extra = sorted(actual_keys - expected_keys)
                parts = []
                if missing:
                    parts.append(f"缺少字段 {', '.join(missing)}")
                if extra:
                    parts.append(f"多余字段 {', '.join(extra)}")
                return f"{path} " + "，".join(parts)
            for field in expected:
                if expected[field] != actual[field]:
                    return _describe_map_value_mismatch(f"{path} 字段 {field}", expected[field], actual[field])
            return f"{path} 内容不一致"
        if expected != actual:
            return f"{path} 不一致: 期望 {expected!r}, 实际 {actual!r}"
        return f"期望 {type(expected).__name__}, 实际 {type(actual).__name__}"
    if len(expected) != len(actual):
        return f"长度不一致: 期望 {len(expected)}, 实际 {len(actual)}"
    for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
        name = _map_item_name(expected_item, index)
        if expected_item == actual_item:
            continue
        return _describe_map_value_mismatch(f"{path}[{index}] {name}", expected_item, actual_item)
    return "内容不一致"


def _map_item_name(item: object, index: int) -> str:
    """取得 map 列表项的可读名称。"""
    if isinstance(item, dict) and isinstance(item.get("name"), str):
        return f"`{item['name']}`"
    return f"#{index}"


def validate_native_code_map_bytes(code: bytes, metadata: dict[str, object]) -> None:
    """校验 raw native 机器码字节与 map 摘要一致。"""
    if isinstance(metadata, dict) and metadata.get("schema_version") == 3:
        from verbose_c.compiler.native.aot_image import validate_aot_map
        validate_aot_map(code, metadata)
        return
    if isinstance(metadata, dict) and metadata.get("schema_version") == 2 and "runtime" in metadata:
        from verbose_c.compiler.native.runtime_image import validate_runtime_map
        validate_runtime_map(code, metadata)
        return
    if not isinstance(code, bytes):
        raise NativeCodegenError(f"native 机器码 raw bytes 必须是 bytes，实际 {type(code).__name__}")
    if not isinstance(metadata, dict):
        raise NativeCodegenError(f"native 机器码 map 必须是对象，实际 {type(metadata).__name__}")
    extra_top_level_fields = sorted(set(metadata) - _MAP_TOP_LEVEL_FIELDS)
    if extra_top_level_fields:
        raise NativeCodegenError(f"native 机器码 map 存在未知顶层字段: {', '.join(extra_top_level_fields)}")
    schema_version = metadata.get("schema_version")
    if schema_version != 1:
        raise NativeCodegenError(f"native 机器码 map 字段 schema_version 必须为 1，实际 {schema_version!r}")
    target = metadata.get("target")
    if target != NativeTarget.WINDOWS_X64.value:
        raise NativeCodegenError(f"native 机器码 map 字段 target 必须为 {NativeTarget.WINDOWS_X64.value!r}，实际 {target!r}")
    abi = metadata.get("abi")
    if not isinstance(abi, dict):
        raise NativeCodegenError(f"native 机器码 map 字段 abi 必须是对象，实际 {type(abi).__name__}")
    extra_abi_fields = sorted(set(abi) - _MAP_ABI_FIELDS)
    if extra_abi_fields:
        raise NativeCodegenError(f"native 机器码 map abi 存在未知字段: {', '.join(extra_abi_fields)}")
    abi_name = abi.get("name")
    if not isinstance(abi_name, str) or not abi_name:
        raise NativeCodegenError("native 机器码 map abi.name 必须是非空字符串")
    if abi.get("target") != target:
        raise NativeCodegenError(f"native 机器码 map abi.target 与 target 不一致: abi {abi.get('target')!r}, target {target!r}")
    abi_word_size = abi.get("word_size")
    if not isinstance(abi_word_size, int) or isinstance(abi_word_size, bool):
        raise NativeCodegenError(f"native 机器码 map abi.word_size 必须是整数，实际 {type(abi_word_size).__name__}")
    if abi_word_size != 8:
        raise NativeCodegenError(f"native 机器码 map abi.word_size 必须为 8，实际 {abi_word_size}")
    abi_stack_alignment = abi.get("stack_alignment")
    if not isinstance(abi_stack_alignment, int) or isinstance(abi_stack_alignment, bool):
        raise NativeCodegenError(f"native 机器码 map abi.stack_alignment 必须是整数，实际 {type(abi_stack_alignment).__name__}")
    if abi_stack_alignment <= 0:
        raise NativeCodegenError(f"native 机器码 map abi.stack_alignment 必须为正数，实际 {abi_stack_alignment}")
    abi_shadow_space = abi.get("shadow_space_size")
    if not isinstance(abi_shadow_space, int) or isinstance(abi_shadow_space, bool):
        raise NativeCodegenError(f"native 机器码 map abi.shadow_space_size 必须是整数，实际 {type(abi_shadow_space).__name__}")
    if abi_shadow_space < 0:
        raise NativeCodegenError(f"native 机器码 map abi.shadow_space_size 不能为负数，实际 {abi_shadow_space}")
    argument_registers = abi.get("argument_registers")
    if not isinstance(argument_registers, list):
        raise NativeCodegenError(f"native 机器码 map abi.argument_registers 必须是列表，实际 {type(argument_registers).__name__}")
    seen_argument_registers = set()
    for index, register in enumerate(argument_registers):
        if not isinstance(register, str) or not register:
            raise NativeCodegenError(f"native 机器码 map abi.argument_registers[{index}] 必须是非空字符串")
        register_name = register.upper()
        if register_name in seen_argument_registers:
            raise NativeCodegenError(f"native 机器码 map abi.argument_registers 重复: {register}")
        seen_argument_registers.add(register_name)
        if register_name not in SUPPORTED_ARGUMENT_REGISTERS:
            raise NativeCodegenError(f"native 机器码 map abi.argument_registers 暂不支持 {register}")
    if abi.get("return_register") != "RAX":
        raise NativeCodegenError(f"native 机器码 map abi.return_register 必须为 'RAX'，实际 {abi.get('return_register')!r}")
    if abi.get("frame_pointer") != "RBP":
        raise NativeCodegenError(f"native 机器码 map abi.frame_pointer 必须为 'RBP'，实际 {abi.get('frame_pointer')!r}")
    if abi.get("stack_pointer") != "RSP":
        raise NativeCodegenError(f"native 机器码 map abi.stack_pointer 必须为 'RSP'，实际 {abi.get('stack_pointer')!r}")
    supported_value_types = abi.get("supported_value_types")
    if not isinstance(supported_value_types, list) or any(not isinstance(item, str) for item in supported_value_types):
        raise NativeCodegenError("native 机器码 map abi.supported_value_types 必须是字符串列表")
    if set(supported_value_types) not in (SUPPORTED_RETURN_TYPES, SUPPORTED_RETURN_TYPES - {"string"}):
        raise NativeCodegenError(
            f"native 机器码 map abi.supported_value_types 必须为 {SUPPORTED_RETURN_TYPES}，实际 {supported_value_types!r}"
        )
    pe_machine = metadata.get("pe_machine")
    if pe_machine != "AMD64":
        raise NativeCodegenError(f"native 机器码 map 字段 pe_machine 必须为 'AMD64'，实际 {pe_machine!r}")
    pe_machine_value = metadata.get("pe_machine_value")
    if pe_machine_value != 0x8664:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_machine_value 必须为 0x8664，实际 {pe_machine_value!r}")
    pe_coff_header = metadata.get("pe_coff_header")
    if not isinstance(pe_coff_header, dict):
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header 必须是对象")
    extra_pe_coff_header_fields = sorted(set(pe_coff_header) - _MAP_PE_COFF_HEADER_FIELDS)
    if extra_pe_coff_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_coff_header 存在未知字段: "
            f"{', '.join(extra_pe_coff_header_fields)}"
        )
    missing_pe_coff_header_fields = sorted(_MAP_PE_COFF_HEADER_FIELDS - set(pe_coff_header))
    if missing_pe_coff_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_coff_header 缺少字段: "
            f"{', '.join(missing_pe_coff_header_fields)}"
        )
    for field in _MAP_PE_COFF_HEADER_FIELDS:
        value = pe_coff_header.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map 字段 pe_coff_header.{field} 必须是整数")
    if pe_coff_header["Machine"] != pe_machine_value:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header.Machine 与 pe_machine_value 不一致: "
            f"期望 {pe_machine_value}, 实际 {pe_coff_header['Machine']}"
        )
    pe_magic = metadata.get("pe_optional_header_magic")
    if pe_magic != "PE32+":
        raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header_magic 必须为 'PE32+'，实际 {pe_magic!r}")
    pe_magic_value = metadata.get("pe_optional_header_magic_value")
    if pe_magic_value != 0x20B:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header_magic_value 必须为 0x020B，实际 {pe_magic_value!r}")
    pe_optional_header = metadata.get("pe_optional_header")
    if not isinstance(pe_optional_header, dict):
        raise NativeCodegenError("native 机器码 map 字段 pe_optional_header 必须是对象")
    extra_pe_optional_header_fields = sorted(set(pe_optional_header) - _MAP_PE_OPTIONAL_HEADER_FIELDS)
    if extra_pe_optional_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header 存在未知字段: "
            f"{', '.join(extra_pe_optional_header_fields)}"
        )
    missing_pe_optional_header_fields = sorted(_MAP_PE_OPTIONAL_HEADER_FIELDS - set(pe_optional_header))
    if missing_pe_optional_header_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header 缺少字段: "
            f"{', '.join(missing_pe_optional_header_fields)}"
        )
    for field in _MAP_PE_OPTIONAL_HEADER_FIELDS:
        value = pe_optional_header.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header.{field} 必须是整数")
    if pe_optional_header["Magic"] != pe_magic_value:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.Magic 与 pe_optional_header_magic_value 不一致: "
            f"期望 {pe_magic_value}, 实际 {pe_optional_header['Magic']}"
        )
    pe_subsystem = metadata.get("pe_subsystem")
    if pe_subsystem != "console":
        raise NativeCodegenError(f"native 机器码 map 字段 pe_subsystem 必须为 'console'，实际 {pe_subsystem!r}")
    pe_subsystem_value = metadata.get("pe_subsystem_value")
    if pe_subsystem_value != 3:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_subsystem_value 必须为 3，实际 {pe_subsystem_value!r}")
    if pe_optional_header["Subsystem"] != pe_subsystem_value:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.Subsystem 与 pe_subsystem_value 不一致: "
            f"期望 {pe_subsystem_value}, 实际 {pe_optional_header['Subsystem']}"
        )
    if pe_optional_header["NumberOfRvaAndSizes"] != 16:
        raise NativeCodegenError("native 机器码 map 字段 pe_optional_header.NumberOfRvaAndSizes 必须为 16")
    pe_number_of_sections = metadata.get("pe_number_of_sections")
    if pe_number_of_sections != 1:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_number_of_sections 必须为 1，实际 {pe_number_of_sections!r}")
    if pe_coff_header["NumberOfSections"] != pe_number_of_sections:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header.NumberOfSections 与 pe_number_of_sections 不一致: "
            f"期望 {pe_number_of_sections}, 实际 {pe_coff_header['NumberOfSections']}"
        )
    if pe_coff_header["TimeDateStamp"] != 0:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.TimeDateStamp 必须为 0")
    if pe_coff_header["PointerToSymbolTable"] != 0:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.PointerToSymbolTable 必须为 0")
    if pe_coff_header["NumberOfSymbols"] != 0:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.NumberOfSymbols 必须为 0")
    if pe_coff_header["SizeOfOptionalHeader"] != PE_OPTIONAL_HEADER_SIZE:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header.SizeOfOptionalHeader 必须为 {PE_OPTIONAL_HEADER_SIZE}"
        )
    if pe_coff_header["Characteristics"] != 0x22:
        raise NativeCodegenError("native 机器码 map 字段 pe_coff_header.Characteristics 必须为 0x0022")
    for field in (
        "pe_dos_header_size",
        "pe_lfanew",
        "pe_signature_offset",
        "pe_signature_size",
        "pe_coff_header_offset",
        "pe_coff_header_size",
        "pe_optional_header_offset",
        "pe_optional_header_size",
        "pe_section_table_offset",
        "pe_section_header_size",
        "pe_section_table_size",
        "pe_size_of_headers",
    ):
        value = metadata.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map 字段 {field} 必须是整数，实际 {type(value).__name__}")
    if metadata["pe_dos_header_size"] != PE_DOS_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_dos_header_size 必须为 {PE_DOS_HEADER_SIZE}")
    if metadata["pe_lfanew"] != PE_LFANEW:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_lfanew 必须为 0x{PE_LFANEW:08X}")
    if metadata["pe_signature_offset"] != metadata["pe_lfanew"]:
        raise NativeCodegenError("native 机器码 map 字段 pe_signature_offset 必须等于 pe_lfanew")
    if metadata["pe_signature_size"] != PE_SIGNATURE_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_signature_size 必须为 {PE_SIGNATURE_SIZE}")
    expected_coff_offset = metadata["pe_signature_offset"] + metadata["pe_signature_size"]
    if metadata["pe_coff_header_offset"] != expected_coff_offset:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_coff_header_offset 不一致: 期望 {expected_coff_offset}, 实际 {metadata['pe_coff_header_offset']}"
        )
    if metadata["pe_coff_header_size"] != PE_COFF_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_coff_header_size 必须为 {PE_COFF_HEADER_SIZE}")
    expected_optional_offset = metadata["pe_coff_header_offset"] + metadata["pe_coff_header_size"]
    if metadata["pe_optional_header_offset"] != expected_optional_offset:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header_offset 不一致: 期望 {expected_optional_offset}, 实际 {metadata['pe_optional_header_offset']}"
        )
    if metadata["pe_optional_header_size"] != PE_OPTIONAL_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_optional_header_size 必须为 {PE_OPTIONAL_HEADER_SIZE}")
    expected_section_table_offset = metadata["pe_optional_header_offset"] + metadata["pe_optional_header_size"]
    if metadata["pe_section_table_offset"] != expected_section_table_offset:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_section_table_offset 不一致: 期望 {expected_section_table_offset}, 实际 {metadata['pe_section_table_offset']}"
        )
    if metadata["pe_section_header_size"] != PE_SECTION_HEADER_SIZE:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_section_header_size 必须为 {PE_SECTION_HEADER_SIZE}")
    expected_section_table_size = pe_number_of_sections * metadata["pe_section_header_size"]
    if metadata["pe_section_table_size"] != expected_section_table_size:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_section_table_size 不一致: 期望 {expected_section_table_size}, 实际 {metadata['pe_section_table_size']}"
        )
    pe_file_alignment = metadata.get("pe_file_alignment")
    if pe_file_alignment != PE_FILE_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_file_alignment 必须为 {PE_FILE_ALIGNMENT}，实际 {pe_file_alignment!r}")
    if pe_optional_header["FileAlignment"] != pe_file_alignment:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.FileAlignment 与 pe_file_alignment 不一致: "
            f"期望 {pe_file_alignment}, 实际 {pe_optional_header['FileAlignment']}"
        )
    pe_section_alignment = metadata.get("pe_section_alignment")
    if pe_section_alignment != PE_SECTION_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map 字段 pe_section_alignment 必须为 {PE_SECTION_ALIGNMENT}，实际 {pe_section_alignment!r}")
    if pe_optional_header["SectionAlignment"] != pe_section_alignment:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SectionAlignment 与 pe_section_alignment 不一致: "
            f"期望 {pe_section_alignment}, 实际 {pe_optional_header['SectionAlignment']}"
        )
    expected_size_of_headers = (
        (metadata["pe_section_table_offset"] + metadata["pe_section_table_size"] + pe_file_alignment - 1)
        // pe_file_alignment
    ) * pe_file_alignment
    if metadata["pe_size_of_headers"] != expected_size_of_headers:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_headers 不一致: 期望 {expected_size_of_headers}, 实际 {metadata['pe_size_of_headers']}"
        )
    if pe_optional_header["SizeOfHeaders"] != metadata["pe_size_of_headers"]:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SizeOfHeaders 与 pe_size_of_headers 不一致: "
            f"期望 {metadata['pe_size_of_headers']}, 实际 {pe_optional_header['SizeOfHeaders']}"
        )
    pe_file_layout = metadata.get("pe_file_layout")
    if not isinstance(pe_file_layout, dict):
        raise NativeCodegenError("native 机器码 map 字段 pe_file_layout 必须是对象")
    extra_pe_file_layout_fields = sorted(set(pe_file_layout) - _MAP_PE_FILE_LAYOUT_FIELDS)
    if extra_pe_file_layout_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_file_layout 存在未知字段: "
            f"{', '.join(extra_pe_file_layout_fields)}"
        )
    missing_pe_file_layout_fields = sorted(_MAP_PE_FILE_LAYOUT_FIELDS - set(pe_file_layout))
    if missing_pe_file_layout_fields:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_file_layout 缺少字段: "
            f"{', '.join(missing_pe_file_layout_fields)}"
        )
    for range_name in (
        "dos_header",
        "dos_stub_padding",
        "pe_signature",
        "coff_header",
        "optional_header",
        "section_table",
        "headers_padding",
        "text_raw",
    ):
        range_item = pe_file_layout.get(range_name)
        if not isinstance(range_item, dict):
            raise NativeCodegenError(f"native 机器码 map 字段 pe_file_layout.{range_name} 必须是对象")
        extra_range_fields = sorted(set(range_item) - _MAP_PE_FILE_LAYOUT_RANGE_FIELDS)
        if extra_range_fields:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name} 存在未知字段: "
                f"{', '.join(extra_range_fields)}"
            )
        missing_range_fields = sorted(_MAP_PE_FILE_LAYOUT_RANGE_FIELDS - set(range_item))
        if missing_range_fields:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name} 缺少字段: "
                f"{', '.join(missing_range_fields)}"
            )
        for field in _MAP_PE_FILE_LAYOUT_RANGE_FIELDS:
            value = range_item.get(field)
            if not isinstance(value, int) or isinstance(value, bool):
                raise NativeCodegenError(f"native 机器码 map 字段 pe_file_layout.{range_name}.{field} 必须是整数")
        if range_item["size"] < 0:
            raise NativeCodegenError(f"native 机器码 map 字段 pe_file_layout.{range_name}.size 必须是非负整数")
        expected_range_end = range_item["offset"] + range_item["size"]
        if range_item["end_offset"] != expected_range_end:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.end_offset 不一致: "
                f"期望 {expected_range_end}, 实际 {range_item['end_offset']}"
            )
    if not isinstance(pe_file_layout["file_size"], int) or isinstance(pe_file_layout["file_size"], bool):
        raise NativeCodegenError("native 机器码 map 字段 pe_file_layout.file_size 必须是整数")
    image_base = metadata.get("image_base")
    if not isinstance(image_base, int) or isinstance(image_base, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 image_base 必须是整数，实际 {type(image_base).__name__}")
    if image_base < 0:
        raise NativeCodegenError(f"native 机器码 map 字段 image_base 必须是非负整数，实际 {image_base}")
    if pe_optional_header["ImageBase"] != image_base:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.ImageBase 与 image_base 不一致: "
            f"期望 {image_base}, 实际 {pe_optional_header['ImageBase']}"
        )
    actual_size = len(code)
    code_size = metadata.get("code_size")
    if not isinstance(code_size, int) or isinstance(code_size, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 code_size 必须是整数，实际 {type(code_size).__name__}")
    if code_size < 0:
        raise NativeCodegenError(f"native 机器码 map 字段 code_size 必须是非负整数，实际 {code_size}")
    if code_size != actual_size:
        raise NativeCodegenError(
            f"native 机器码 map 字段 code_size 不一致: 期望 {actual_size!r}, 实际 {code_size!r}"
        )
    actual_hash = hashlib.sha256(code).hexdigest()
    code_sha256 = metadata.get("code_sha256")
    if not isinstance(code_sha256, str):
        raise NativeCodegenError(f"native 机器码 map 字段 code_sha256 必须是字符串，实际 {type(code_sha256).__name__}")
    if len(code_sha256) != 64:
        raise NativeCodegenError(f"native 机器码 map 字段 code_sha256 必须是 64 位十六进制字符串，实际长度 {len(code_sha256)}")
    try:
        bytes.fromhex(code_sha256)
    except ValueError as error:
        raise NativeCodegenError(f"native 机器码 map 字段 code_sha256 不是合法十六进制: {error}") from error
    if code_sha256 != actual_hash:
        raise NativeCodegenError(
            f"native 机器码 map 字段 code_sha256 不一致: 期望 {actual_hash!r}, 实际 {code_sha256!r}"
        )
    sections = metadata.get("sections")
    if not isinstance(sections, list) or not sections:
        raise NativeCodegenError("native 机器码 map 字段 sections 必须是非空列表")
    if len(sections) != pe_number_of_sections:
        raise NativeCodegenError(
            f"native 机器码 map 字段 sections 数量不一致: 期望 {pe_number_of_sections}, 实际 {len(sections)}"
        )
    text_sections = [section for section in sections if isinstance(section, dict) and section.get("name") == ".text"]
    if len(text_sections) != 1:
        raise NativeCodegenError(f"native 机器码 map .text section 数量必须为 1，实际 {len(text_sections)}")
    text_section = text_sections[0]
    extra_text_section_fields = sorted(set(text_section) - _MAP_TEXT_SECTION_FIELDS)
    if extra_text_section_fields:
        raise NativeCodegenError(f"native 机器码 map .text section 存在未知字段: {', '.join(extra_text_section_fields)}")
    for field in (
        "offset",
        "size",
        "end_offset",
        "virtual_size",
        "raw_size_aligned",
        "raw_padding_size",
        "virtual_size_aligned",
        "rva",
        "end_rva",
        "va",
        "end_va",
        "entry_offset",
        "pe_raw_pointer",
        "pe_raw_end_pointer",
        "alignment",
        "file_alignment",
        "section_alignment",
        "pe_characteristics",
    ):
        value = text_section.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map .text section {field} 必须是整数")
    name_bytes = text_section.get("name_bytes")
    if name_bytes != "2E 74 65 78 74 00 00 00":
        raise NativeCodegenError(
            f"native 机器码 map .text section name_bytes 必须为 '2E 74 65 78 74 00 00 00'，实际 {name_bytes!r}"
        )
    section_hash = text_section.get("sha256")
    if not isinstance(section_hash, str):
        raise NativeCodegenError(f"native 机器码 map .text section sha256 必须是字符串，实际 {type(section_hash).__name__}")
    raw_padded_hash = text_section.get("raw_padded_sha256")
    if not isinstance(raw_padded_hash, str):
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 必须是字符串，实际 {type(raw_padded_hash).__name__}"
        )
    if len(raw_padded_hash) != 64:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 必须是 64 位十六进制字符串，实际长度 {len(raw_padded_hash)}"
        )
    try:
        bytes.fromhex(raw_padded_hash)
    except ValueError as error:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 不是合法十六进制: {error}"
        ) from error
    permissions = text_section.get("permissions")
    if permissions != ["read", "execute"]:
        raise NativeCodegenError(
            f"native 机器码 map .text section permissions 必须为 ['read', 'execute']，实际 {permissions!r}"
        )
    characteristics = text_section.get("characteristics")
    if characteristics != ["CNT_CODE", "MEM_EXECUTE", "MEM_READ"]:
        raise NativeCodegenError(
            "native 机器码 map .text section characteristics 必须为 "
            f"['CNT_CODE', 'MEM_EXECUTE', 'MEM_READ']，实际 {characteristics!r}"
        )
    if text_section["pe_characteristics"] != 0x60000020:
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_characteristics 必须为 0x60000020，实际 0x{text_section['pe_characteristics']:08X}"
        )
    pe_section_header = text_section.get("pe_section_header")
    if not isinstance(pe_section_header, dict):
        raise NativeCodegenError("native 机器码 map .text section pe_section_header 必须是对象")
    extra_pe_section_header_fields = sorted(set(pe_section_header) - _MAP_PE_SECTION_HEADER_FIELDS)
    if extra_pe_section_header_fields:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header 存在未知字段: "
            f"{', '.join(extra_pe_section_header_fields)}"
        )
    missing_pe_section_header_fields = sorted(_MAP_PE_SECTION_HEADER_FIELDS - set(pe_section_header))
    if missing_pe_section_header_fields:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header 缺少字段: "
            f"{', '.join(missing_pe_section_header_fields)}"
        )
    for field in (
        "VirtualSize",
        "VirtualAddress",
        "SizeOfRawData",
        "PointerToRawData",
        "PointerToRelocations",
        "PointerToLinenumbers",
        "NumberOfRelocations",
        "NumberOfLinenumbers",
        "Characteristics",
    ):
        value = pe_section_header.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"native 机器码 map .text section pe_section_header.{field} 必须是整数")
    if pe_section_header["Name"] != ".text":
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_section_header.Name 必须为 '.text'，实际 {pe_section_header['Name']!r}"
        )
    if pe_section_header["NameBytes"] != name_bytes:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.NameBytes 与 name_bytes 不一致: "
            f"期望 {name_bytes!r}, 实际 {pe_section_header['NameBytes']!r}"
        )
    if pe_section_header["PointerToRelocations"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.PointerToRelocations 必须为 0")
    if pe_section_header["PointerToLinenumbers"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.PointerToLinenumbers 必须为 0")
    if pe_section_header["NumberOfRelocations"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.NumberOfRelocations 必须为 0")
    if pe_section_header["NumberOfLinenumbers"] != 0:
        raise NativeCodegenError("native 机器码 map .text section pe_section_header.NumberOfLinenumbers 必须为 0")
    if text_section["offset"] != 0:
        raise NativeCodegenError(f"native 机器码 map .text section offset 必须为 0，实际 {text_section['offset']}")
    if text_section["alignment"] <= 0:
        raise NativeCodegenError(f"native 机器码 map .text section alignment 必须为正数，实际 {text_section['alignment']}")
    if text_section["file_alignment"] != PE_FILE_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map .text section file_alignment 必须为 {PE_FILE_ALIGNMENT}，实际 {text_section['file_alignment']}")
    if text_section["file_alignment"] != pe_file_alignment:
        raise NativeCodegenError(
            f"native 机器码 map .text section file_alignment 与 pe_file_alignment 不一致: "
            f"期望 {pe_file_alignment}, 实际 {text_section['file_alignment']}"
        )
    if text_section["section_alignment"] != PE_SECTION_ALIGNMENT:
        raise NativeCodegenError(f"native 机器码 map .text section section_alignment 必须为 {PE_SECTION_ALIGNMENT}，实际 {text_section['section_alignment']}")
    if text_section["section_alignment"] != pe_section_alignment:
        raise NativeCodegenError(
            f"native 机器码 map .text section section_alignment 与 pe_section_alignment 不一致: "
            f"期望 {pe_section_alignment}, 实际 {text_section['section_alignment']}"
        )
    if text_section["size"] != actual_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section size 不一致: 期望 {actual_size!r}, 实际 {text_section['size']!r}"
        )
    expected_end_offset = text_section["offset"] + text_section["size"]
    if text_section["end_offset"] != expected_end_offset:
        raise NativeCodegenError(
            f"native 机器码 map .text section end_offset 不一致: 期望 {expected_end_offset}, 实际 {text_section['end_offset']}"
        )
    if text_section["virtual_size"] != actual_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section virtual_size 不一致: 期望 {actual_size!r}, 实际 {text_section['virtual_size']!r}"
        )
    expected_raw_size = ((actual_size + PE_FILE_ALIGNMENT - 1) // PE_FILE_ALIGNMENT) * PE_FILE_ALIGNMENT
    if text_section["raw_size_aligned"] != expected_raw_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_size_aligned 不一致: 期望 {expected_raw_size}, 实际 {text_section['raw_size_aligned']}"
        )
    expected_raw_padding_size = expected_raw_size - actual_size
    if text_section["raw_padding_size"] != expected_raw_padding_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padding_size 不一致: "
            f"期望 {expected_raw_padding_size}, 实际 {text_section['raw_padding_size']}"
        )
    if text_section["pe_raw_pointer"] != metadata["pe_size_of_headers"]:
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_raw_pointer 不一致: "
            f"期望 {metadata['pe_size_of_headers']}, 实际 {text_section['pe_raw_pointer']}"
        )
    if pe_section_header["PointerToRawData"] != text_section["pe_raw_pointer"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.PointerToRawData 与 pe_raw_pointer 不一致: "
            f"期望 {text_section['pe_raw_pointer']}, 实际 {pe_section_header['PointerToRawData']}"
        )
    expected_pe_raw_end_pointer = text_section["pe_raw_pointer"] + text_section["raw_size_aligned"]
    if text_section["pe_raw_end_pointer"] != expected_pe_raw_end_pointer:
        raise NativeCodegenError(
            f"native 机器码 map .text section pe_raw_end_pointer 不一致: "
            f"期望 {expected_pe_raw_end_pointer}, 实际 {text_section['pe_raw_end_pointer']}"
        )
    expected_file_layout_ranges = {
        "dos_header": (0, metadata["pe_dos_header_size"], metadata["pe_dos_header_size"]),
        "dos_stub_padding": (
            metadata["pe_dos_header_size"],
            metadata["pe_lfanew"] - metadata["pe_dos_header_size"],
            metadata["pe_lfanew"],
        ),
        "pe_signature": (
            metadata["pe_signature_offset"],
            metadata["pe_signature_size"],
            metadata["pe_signature_offset"] + metadata["pe_signature_size"],
        ),
        "coff_header": (
            metadata["pe_coff_header_offset"],
            metadata["pe_coff_header_size"],
            metadata["pe_coff_header_offset"] + metadata["pe_coff_header_size"],
        ),
        "optional_header": (
            metadata["pe_optional_header_offset"],
            metadata["pe_optional_header_size"],
            metadata["pe_optional_header_offset"] + metadata["pe_optional_header_size"],
        ),
        "section_table": (
            metadata["pe_section_table_offset"],
            metadata["pe_section_table_size"],
            metadata["pe_section_table_offset"] + metadata["pe_section_table_size"],
        ),
        "headers_padding": (
            metadata["pe_section_table_offset"] + metadata["pe_section_table_size"],
            metadata["pe_size_of_headers"] - metadata["pe_section_table_offset"] - metadata["pe_section_table_size"],
            metadata["pe_size_of_headers"],
        ),
        "text_raw": (
            text_section["pe_raw_pointer"],
            text_section["raw_size_aligned"],
            text_section["pe_raw_end_pointer"],
        ),
    }
    previous_layout_end = 0
    for range_name, (expected_offset, expected_size, expected_end_offset) in expected_file_layout_ranges.items():
        range_item = pe_file_layout[range_name]
        if range_item["offset"] != expected_offset:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.offset 不一致: "
                f"期望 {expected_offset}, 实际 {range_item['offset']}"
            )
        if range_item["size"] != expected_size:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.size 不一致: "
                f"期望 {expected_size}, 实际 {range_item['size']}"
            )
        if range_item["end_offset"] != expected_end_offset:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.end_offset 不一致: "
                f"期望 {expected_end_offset}, 实际 {range_item['end_offset']}"
            )
        if range_item["offset"] != previous_layout_end:
            raise NativeCodegenError(
                f"native 机器码 map 字段 pe_file_layout.{range_name}.offset 与上一段不连续: "
                f"期望 {previous_layout_end}, 实际 {range_item['offset']}"
            )
        previous_layout_end = range_item["end_offset"]
    if pe_file_layout["file_size"] != text_section["pe_raw_end_pointer"]:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_file_layout.file_size 不一致: "
            f"期望 {text_section['pe_raw_end_pointer']}, 实际 {pe_file_layout['file_size']}"
        )
    if pe_section_header["SizeOfRawData"] != text_section["raw_size_aligned"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.SizeOfRawData 与 raw_size_aligned 不一致: "
            f"期望 {text_section['raw_size_aligned']}, 实际 {pe_section_header['SizeOfRawData']}"
        )
    pe_size_of_code = metadata.get("pe_size_of_code")
    if not isinstance(pe_size_of_code, int) or isinstance(pe_size_of_code, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 pe_size_of_code 必须是整数，实际 {type(pe_size_of_code).__name__}")
    if pe_size_of_code != expected_raw_size:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_code 不一致: 期望 {expected_raw_size}, 实际 {pe_size_of_code}"
        )
    if pe_optional_header["SizeOfCode"] != pe_size_of_code:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SizeOfCode 与 pe_size_of_code 不一致: "
            f"期望 {pe_size_of_code}, 实际 {pe_optional_header['SizeOfCode']}"
        )
    pe_size_of_initialized_data = metadata.get("pe_size_of_initialized_data")
    if pe_size_of_initialized_data != 0:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_initialized_data 必须为 0，实际 {pe_size_of_initialized_data!r}"
        )
    if pe_optional_header["SizeOfInitializedData"] != pe_size_of_initialized_data:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header.SizeOfInitializedData 与 pe_size_of_initialized_data 不一致: "
            f"期望 {pe_size_of_initialized_data}, 实际 {pe_optional_header['SizeOfInitializedData']}"
        )
    pe_size_of_uninitialized_data = metadata.get("pe_size_of_uninitialized_data")
    if pe_size_of_uninitialized_data != 0:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_uninitialized_data 必须为 0，实际 {pe_size_of_uninitialized_data!r}"
        )
    if pe_optional_header["SizeOfUninitializedData"] != pe_size_of_uninitialized_data:
        raise NativeCodegenError(
            "native 机器码 map 字段 pe_optional_header.SizeOfUninitializedData 与 pe_size_of_uninitialized_data 不一致: "
            f"期望 {pe_size_of_uninitialized_data}, 实际 {pe_optional_header['SizeOfUninitializedData']}"
        )
    expected_virtual_size = ((actual_size + PE_SECTION_ALIGNMENT - 1) // PE_SECTION_ALIGNMENT) * PE_SECTION_ALIGNMENT
    if text_section["virtual_size_aligned"] != expected_virtual_size:
        raise NativeCodegenError(
            f"native 机器码 map .text section virtual_size_aligned 不一致: 期望 {expected_virtual_size}, 实际 {text_section['virtual_size_aligned']}"
        )
    if text_section["rva"] != PE_TEXT_RVA:
        raise NativeCodegenError(f"native 机器码 map .text section rva 必须为 {PE_TEXT_RVA}，实际 {text_section['rva']}")
    if pe_section_header["VirtualAddress"] != text_section["rva"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.VirtualAddress 与 rva 不一致: "
            f"期望 {text_section['rva']}, 实际 {pe_section_header['VirtualAddress']}"
        )
    if pe_section_header["VirtualSize"] != text_section["virtual_size"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.VirtualSize 与 virtual_size 不一致: "
            f"期望 {text_section['virtual_size']}, 实际 {pe_section_header['VirtualSize']}"
        )
    if pe_section_header["Characteristics"] != text_section["pe_characteristics"]:
        raise NativeCodegenError(
            "native 机器码 map .text section pe_section_header.Characteristics 与 pe_characteristics 不一致: "
            f"期望 0x{text_section['pe_characteristics']:08X}, 实际 0x{pe_section_header['Characteristics']:08X}"
        )
    pe_size_of_image = metadata.get("pe_size_of_image")
    if not isinstance(pe_size_of_image, int) or isinstance(pe_size_of_image, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 pe_size_of_image 必须是整数，实际 {type(pe_size_of_image).__name__}")
    expected_size_of_image = text_section["rva"] + expected_virtual_size
    if pe_size_of_image != expected_size_of_image:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_size_of_image 不一致: 期望 {expected_size_of_image}, 实际 {pe_size_of_image}"
        )
    if pe_optional_header["SizeOfImage"] != pe_size_of_image:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.SizeOfImage 与 pe_size_of_image 不一致: "
            f"期望 {pe_size_of_image}, 实际 {pe_optional_header['SizeOfImage']}"
        )
    pe_base_of_code = metadata.get("pe_base_of_code")
    if not isinstance(pe_base_of_code, int) or isinstance(pe_base_of_code, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 pe_base_of_code 必须是整数，实际 {type(pe_base_of_code).__name__}")
    if pe_base_of_code != text_section["rva"]:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_base_of_code 不一致: 期望 {text_section['rva']}, 实际 {pe_base_of_code}"
        )
    if pe_optional_header["BaseOfCode"] != pe_base_of_code:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.BaseOfCode 与 pe_base_of_code 不一致: "
            f"期望 {pe_base_of_code}, 实际 {pe_optional_header['BaseOfCode']}"
        )
    expected_section_end_rva = text_section["rva"] + text_section["virtual_size"]
    if text_section["end_rva"] != expected_section_end_rva:
        raise NativeCodegenError(
            f"native 机器码 map .text section end_rva 不一致: 期望 {expected_section_end_rva}, 实际 {text_section['end_rva']}"
        )
    expected_section_va = image_base + text_section["rva"]
    if text_section["va"] != expected_section_va:
        raise NativeCodegenError(
            f"native 机器码 map .text section va 不一致: 期望 {expected_section_va}, 实际 {text_section['va']}"
        )
    expected_section_end_va = image_base + text_section["end_rva"]
    if text_section["end_va"] != expected_section_end_va:
        raise NativeCodegenError(
            f"native 机器码 map .text section end_va 不一致: 期望 {expected_section_end_va}, 实际 {text_section['end_va']}"
        )
    if section_hash != actual_hash:
        raise NativeCodegenError(
            f"native 机器码 map .text section sha256 不一致: 期望 {actual_hash!r}, 实际 {section_hash!r}"
        )
    expected_raw_padded_hash = hashlib.sha256(code + bytes(expected_raw_padding_size)).hexdigest()
    if raw_padded_hash != expected_raw_padded_hash:
        raise NativeCodegenError(
            f"native 机器码 map .text section raw_padded_sha256 不一致: "
            f"期望 {expected_raw_padded_hash!r}, 实际 {raw_padded_hash!r}"
        )
    entry = metadata.get("entry")
    if not isinstance(entry, str) or not entry:
        raise NativeCodegenError("native 机器码 map 字段 entry 必须是非空字符串")
    entry_offset = metadata.get("entry_offset")
    if not isinstance(entry_offset, int) or isinstance(entry_offset, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 entry_offset 必须是整数，实际 {type(entry_offset).__name__}")
    if entry_offset < 0 or entry_offset >= actual_size:
        raise NativeCodegenError(f"native 机器码 map 入口偏移越界: {entry_offset}, 机器码长度 {actual_size}")
    if text_section["entry_offset"] != entry_offset:
        raise NativeCodegenError(
            f"native 机器码 map .text section entry_offset 与入口偏移不一致: section {text_section['entry_offset']}, entry_offset {entry_offset}"
        )
    entry_rva = metadata.get("entry_rva")
    if not isinstance(entry_rva, int) or isinstance(entry_rva, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 entry_rva 必须是整数，实际 {type(entry_rva).__name__}")
    expected_entry_rva = text_section["rva"] + entry_offset
    if entry_rva != expected_entry_rva:
        raise NativeCodegenError(
            f"native 机器码 map 入口 RVA 不一致: 记录 {entry_rva}, 期望 {expected_entry_rva}"
        )
    pe_entry_point = metadata.get("pe_address_of_entry_point")
    if not isinstance(pe_entry_point, int) or isinstance(pe_entry_point, bool):
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_address_of_entry_point 必须是整数，实际 {type(pe_entry_point).__name__}"
        )
    if pe_entry_point != entry_rva:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_address_of_entry_point 不一致: 期望 {entry_rva}, 实际 {pe_entry_point}"
        )
    if pe_optional_header["AddressOfEntryPoint"] != pe_entry_point:
        raise NativeCodegenError(
            f"native 机器码 map 字段 pe_optional_header.AddressOfEntryPoint 与 pe_address_of_entry_point 不一致: "
            f"期望 {pe_entry_point}, 实际 {pe_optional_header['AddressOfEntryPoint']}"
        )
    entry_va = metadata.get("entry_va")
    if not isinstance(entry_va, int) or isinstance(entry_va, bool):
        raise NativeCodegenError(f"native 机器码 map 字段 entry_va 必须是整数，实际 {type(entry_va).__name__}")
    expected_entry_va = image_base + entry_rva
    if entry_va != expected_entry_va:
        raise NativeCodegenError(
            f"native 机器码 map 入口 VA 不一致: 记录 {entry_va}, 期望 {expected_entry_va}"
        )
    functions = metadata.get("functions")
    if not isinstance(functions, list) or not functions:
        raise NativeCodegenError("native 机器码 map 字段 functions 必须是非空列表")
    function_ranges: dict[str, tuple[int, int]] = {}
    function_signatures: dict[str, tuple[str, list[str]]] = {}
    for index, function in enumerate(functions):
        if not isinstance(function, dict):
            raise NativeCodegenError(f"native 机器码 map functions[{index}] 必须是对象")
        extra_function_fields = sorted(set(function) - _MAP_FUNCTION_FIELDS)
        if extra_function_fields:
            raise NativeCodegenError(
                f"native 机器码 map functions[{index}] 存在未知字段: {', '.join(extra_function_fields)}"
            )
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise NativeCodegenError(f"native 机器码 map functions[{index}].name 必须是非空字符串")
        if name in function_ranges:
            raise NativeCodegenError(f"native 机器码 map 函数重复: {name}")
        offset = function.get("offset")
        size = function.get("size")
        end_offset = function.get("end_offset")
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} offset 必须是整数")
        if not isinstance(size, int) or isinstance(size, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} size 必须是整数")
        if not isinstance(end_offset, int) or isinstance(end_offset, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_offset 必须是整数")
        if offset < 0 or size < 0 or offset + size > actual_size:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 范围越界: offset {offset}, size {size}, 机器码长度 {actual_size}")
        expected_end_offset = offset + size
        if end_offset != expected_end_offset:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_offset 不一致: 记录 {end_offset}, 期望 {expected_end_offset}")
        rva = function.get("rva")
        end_rva = function.get("end_rva")
        va = function.get("va")
        end_va = function.get("end_va")
        if not isinstance(rva, int) or isinstance(rva, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} rva 必须是整数")
        if not isinstance(end_rva, int) or isinstance(end_rva, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_rva 必须是整数")
        if not isinstance(va, int) or isinstance(va, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} va 必须是整数")
        if not isinstance(end_va, int) or isinstance(end_va, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_va 必须是整数")
        expected_rva = text_section["rva"] + offset
        expected_end_rva = expected_rva + size
        expected_va = text_section["va"] + offset
        expected_end_va = expected_va + size
        if rva != expected_rva:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} RVA 不一致: 记录 {rva}, 期望 {expected_rva}")
        if end_rva != expected_end_rva:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_rva 不一致: 记录 {end_rva}, 期望 {expected_end_rva}")
        if va != expected_va:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} VA 不一致: 记录 {va}, 期望 {expected_va}")
        if end_va != expected_end_va:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} end_va 不一致: 记录 {end_va}, 期望 {expected_end_va}")
        function_hash = function.get("code_sha256")
        if not isinstance(function_hash, str):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} code_sha256 必须是字符串")
        if len(function_hash) != 64:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} code_sha256 必须是 64 位十六进制字符串，实际长度 {len(function_hash)}")
        try:
            bytes.fromhex(function_hash)
        except ValueError as error:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} code_sha256 不是合法十六进制: {error}") from error
        actual_function_hash = hashlib.sha256(code[offset:offset + size]).hexdigest()
        if function_hash != actual_function_hash:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} code_sha256 不一致: 期望 {actual_function_hash!r}, 实际 {function_hash!r}"
            )
        return_type = function.get("return_type")
        if not isinstance(return_type, str) or return_type not in SUPPORTED_RETURN_TYPES:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} return_type 暂不支持: {return_type!r}")
        param_types = function.get("param_types")
        if not isinstance(param_types, list) or any(not isinstance(item, str) for item in param_types):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} param_types 必须是字符串列表")
        for param_index, param_type in enumerate(param_types):
            if param_type not in SUPPORTED_VALUE_TYPES:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 第 {param_index} 个参数暂不支持类型: {param_type!r}"
                )
        function_ranges[name] = (offset, size)
        function_signatures[name] = (return_type, list(param_types))
    covered_until = 0
    for name, (offset, size) in sorted(function_ranges.items(), key=lambda item: item[1][0]):
        if offset < covered_until:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 范围与前序函数重叠: offset {offset}, 已覆盖到 {covered_until}")
        if offset > covered_until:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 范围前存在空洞: offset {offset}, 已覆盖到 {covered_until}")
        covered_until = offset + size
    if covered_until != actual_size:
        raise NativeCodegenError(f"native 机器码 map 函数范围未覆盖完整 raw bin: 已覆盖到 {covered_until}, 机器码长度 {actual_size}")
    function_labels: dict[str, dict[str, dict[str, int | None]]] = {}
    expected_relocations_by_function: dict[str, dict[int, str]] = {}
    exit_probe_jump_targets_by_function: dict[str, dict[int, str]] = {}
    global_frame_owners = {
        str(function.get("name"))
        for function in functions
        if isinstance(function.get("instructions"), list)
        and any(
            isinstance(instruction, dict)
            and instruction.get("source_op") == "prologue"
            and instruction.get("asm") == "mov r11, rbp ; global frame"
            for instruction in function.get("instructions", [])
        )
    }
    if len(global_frame_owners) > 1:
        raise NativeCodegenError(f"native 机器码 map global-frame owner 不能超过 1 个: {', '.join(sorted(global_frame_owners))}")
    if "global_frame_owner" not in metadata:
        raise NativeCodegenError("native 机器码 map 缺少顶层字段 global_frame_owner")
    global_frame_owner = metadata.get("global_frame_owner")
    expected_global_frame_owner = next(iter(global_frame_owners)) if global_frame_owners else None
    if global_frame_owner is not None and not isinstance(global_frame_owner, str):
        raise NativeCodegenError(
            f"native 机器码 map 字段 global_frame_owner 必须是字符串或 None，实际 {type(global_frame_owner).__name__}"
        )
    if global_frame_owner != expected_global_frame_owner:
        raise NativeCodegenError(
            f"native 机器码 map 字段 global_frame_owner 不一致: 记录 {global_frame_owner!r}, "
            f"指令清单推导 {expected_global_frame_owner!r}"
        )
    global_owner_slots: dict[str, tuple[int, int]] = {}
    non_owner_global_slots: dict[str, list[tuple[str, int, int]]] = {}
    for function in functions:
        name = function["name"]
        function_offset, function_size = function_ranges[name]
        function_end = function_offset + function_size
        frame_size = function.get("frame_size")
        if not isinstance(frame_size, int) or isinstance(frame_size, bool):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} frame_size 必须是整数")
        if frame_size < 0 or frame_size % 16 != 0:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} frame_size 必须是非负 16 字节对齐整数，实际 {frame_size}")
        register_allocation = function.get("register_allocation")
        if not isinstance(register_allocation, dict):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation 必须是对象")
        extra_register_fields = sorted(set(register_allocation) - _MAP_REGISTER_ALLOCATION_FIELDS)
        if extra_register_fields:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation 存在未知字段: {', '.join(extra_register_fields)}"
            )
        missing_register_fields = sorted(_MAP_REGISTER_ALLOCATION_FIELDS - set(register_allocation))
        if missing_register_fields:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation 缺少字段: {', '.join(missing_register_fields)}"
            )
        if register_allocation["strategy"] != "保守栈槽分配":
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.strategy 不一致: {register_allocation['strategy']!r}"
            )
        temporary_registers = register_allocation["temporary_registers"]
        if temporary_registers != ["RAX", "R10"]:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.temporary_registers 必须是 ['RAX', 'R10']"
            )
        allocation_argument_registers = register_allocation["argument_registers"]
        if not isinstance(allocation_argument_registers, list) or any(not isinstance(register, str) for register in allocation_argument_registers):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.argument_registers 必须是字符串列表")
        if len(set(allocation_argument_registers)) != len(allocation_argument_registers):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.argument_registers 不能重复")
        return_type, param_types = function_signatures[name]
        expected_argument_prefix = [f"XMM{index}" if index < len(param_types) and param_types[index] in FLOAT_VALUE_TYPES else register
                                    for index, register in enumerate(abi["argument_registers"][:len(allocation_argument_registers)])]
        if allocation_argument_registers != expected_argument_prefix:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.argument_registers 与 ABI 前缀不一致: "
                f"记录 {allocation_argument_registers}, 期望 {expected_argument_prefix}"
            )
        if register_allocation["return_register"] != ("XMM0" if return_type in FLOAT_VALUE_TYPES else abi["return_register"]):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.return_register 与 ABI 不一致")
        if register_allocation["frame_pointer"] != abi["frame_pointer"]:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.frame_pointer 与 ABI 不一致")
        if register_allocation["stack_pointer"] != abi["stack_pointer"]:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.stack_pointer 与 ABI 不一致")
        if register_allocation["virtual_register_storage"] != "全部写入栈槽":
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.virtual_register_storage 必须是全部写入栈槽")
        if register_allocation["local_storage"] != "全部写入栈槽":
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.local_storage 必须是全部写入栈槽")
        if register_allocation["global_frame_register"] not in {None, "R11"}:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.global_frame_register 必须是 R11 或 None")
        if register_allocation["global_frame_role"] not in {"none", "owner", "borrowed"}:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} register_allocation.global_frame_role 暂不支持")
        stack_slots = function.get("stack_slots", [])
        if not isinstance(stack_slots, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} stack_slots 必须是列表")
        seen_slot_names: set[str] = set()
        global_slot_offsets: set[int] = set()
        frame_slot_offsets: set[int] = set()
        max_frame_slot_offset = 0
        owns_global_frame = name in global_frame_owners
        has_global_slots = False
        for slot_index, slot in enumerate(stack_slots):
            if not isinstance(slot, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} stack_slots[{slot_index}] 必须是对象")
            extra_slot_fields = sorted(set(slot) - _MAP_STACK_SLOT_FIELDS)
            if extra_slot_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} stack_slots[{slot_index}] 存在未知字段: {', '.join(extra_slot_fields)}"
                )
            slot_name = slot.get("name")
            slot_offset = slot.get("offset")
            slot_size = slot.get("size")
            if not isinstance(slot_name, str) or not slot_name:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 name 必须是非空字符串")
            if slot_name in seen_slot_names:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽重复: {slot_name}")
            seen_slot_names.add(slot_name)
            if not isinstance(slot_offset, int) or isinstance(slot_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} offset 必须是整数")
            if not isinstance(slot_size, int) or isinstance(slot_size, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} size 必须是整数")
            if slot_offset <= 0:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} offset 必须为正数")
            if slot_size != 8 and not slot_name.startswith("array[") and slot.get("array_length") is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈槽 {slot_name} size 必须为 8，实际 {slot_size}")
            if slot_name.startswith("global[") and not owns_global_frame:
                has_global_slots = True
                if slot_offset in global_slot_offsets:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 全局栈槽偏移重复: {slot_offset}")
                global_slot_offsets.add(slot_offset)
                non_owner_global_slots.setdefault(name, []).append((slot_name, slot_offset, slot_size))
            else:
                if slot_offset in frame_slot_offsets:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 栈帧槽偏移重复: {slot_offset}")
                frame_slot_offsets.add(slot_offset)
                max_frame_slot_offset = max(max_frame_slot_offset, slot_offset)
                if slot_name.startswith("global["):
                    has_global_slots = True
                    global_owner_slots[slot_name] = (slot_offset, slot_size)
        expected_global_register = "R11" if has_global_slots else None
        if register_allocation["global_frame_register"] != expected_global_register:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.global_frame_register 不一致: "
                f"记录 {register_allocation['global_frame_register']!r}, 期望 {expected_global_register!r}"
            )
        expected_global_role = "owner" if owns_global_frame and has_global_slots else ("borrowed" if has_global_slots else "none")
        if register_allocation["global_frame_role"] != expected_global_role:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} register_allocation.global_frame_role 不一致: "
                f"记录 {register_allocation['global_frame_role']!r}, 期望 {expected_global_role!r}"
            )
        if max_frame_slot_offset > frame_size:
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} 栈槽超出栈帧: 最大偏移 {max_frame_slot_offset}, frame_size {frame_size}"
            )
        labels: dict[str, dict[str, int | None]] = {}
        instructions = function.get("instructions", [])
        if not isinstance(instructions, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} instructions 必须是列表")
        instruction_ranges: list[tuple[int, int]] = []
        expected_relocations: dict[int, str] = {}
        for instruction_index, instruction in enumerate(instructions):
            if not isinstance(instruction, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} instructions[{instruction_index}] 必须是对象")
            extra_instruction_fields = sorted(set(instruction) - _MAP_INSTRUCTION_FIELDS)
            if extra_instruction_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} instructions[{instruction_index}] 存在未知字段: {', '.join(extra_instruction_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} instructions[{instruction_index}]", instruction)
            instruction_offset = instruction.get("offset")
            instruction_rva = instruction.get("rva")
            instruction_va = instruction.get("va")
            instruction_size = instruction.get("size")
            instruction_end_offset = instruction.get("end_offset")
            instruction_end_rva = instruction.get("end_rva")
            instruction_end_va = instruction.get("end_va")
            instruction_bytes = instruction.get("bytes")
            instruction_hash = instruction.get("code_sha256")
            instruction_asm = instruction.get("asm")
            instruction_source_op = instruction.get("source_op")
            instruction_source_attrs = instruction.get("source_attrs")
            if not isinstance(instruction_offset, int) or isinstance(instruction_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 offset 必须是整数")
            if not isinstance(instruction_rva, int) or isinstance(instruction_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 rva 必须是整数")
            if not isinstance(instruction_va, int) or isinstance(instruction_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 va 必须是整数")
            if not isinstance(instruction_size, int) or isinstance(instruction_size, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 size 必须是整数")
            if not isinstance(instruction_end_offset, int) or isinstance(instruction_end_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 end_offset 必须是整数")
            if not isinstance(instruction_end_rva, int) or isinstance(instruction_end_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 end_rva 必须是整数")
            if not isinstance(instruction_end_va, int) or isinstance(instruction_end_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 end_va 必须是整数")
            if not isinstance(instruction_bytes, str):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 bytes 必须是字符串")
            if not isinstance(instruction_hash, str):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 code_sha256 必须是字符串")
            if len(instruction_hash) != 64:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 code_sha256 必须是 64 位十六进制字符串，实际长度 {len(instruction_hash)}"
                )
            try:
                bytes.fromhex(instruction_hash)
            except ValueError as error:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 code_sha256 不是合法十六进制: {error}") from error
            if not isinstance(instruction_asm, str):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 asm 必须是字符串")
            if not isinstance(instruction_source_op, str) or not instruction_source_op:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 source_op 必须是非空字符串")
            if not isinstance(instruction_source_attrs, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 source_attrs 必须是对象")
            for attr_key, attr_value in instruction_source_attrs.items():
                if not isinstance(attr_key, str) or not attr_key:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 source_attrs key 必须是非空字符串")
                if not isinstance(attr_value, (str, int, bool)) and attr_value is not None:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 指令 source_attrs.{attr_key} 必须是字符串、整数、布尔值或 null"
                    )
            if (
                instruction_size < 0
                or instruction_offset < function_offset
                or instruction_offset > function_end
                or instruction_offset + instruction_size > function_end
            ):
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令范围越界: offset {instruction_offset}, size {instruction_size}"
                )
            expected_instruction_rva = text_section["rva"] + instruction_offset
            expected_instruction_end_offset = instruction_offset + instruction_size
            expected_instruction_end_rva = expected_instruction_rva + instruction_size
            expected_instruction_va = text_section["va"] + instruction_offset
            expected_instruction_end_va = expected_instruction_va + instruction_size
            if instruction_end_offset != expected_instruction_end_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 end_offset 不一致: 记录 {instruction_end_offset}, 期望 {expected_instruction_end_offset}"
                )
            if instruction_rva != expected_instruction_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 RVA 不一致: 记录 {instruction_rva}, 期望 {expected_instruction_rva}"
                )
            if instruction_end_rva != expected_instruction_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 end_rva 不一致: 记录 {instruction_end_rva}, 期望 {expected_instruction_end_rva}"
                )
            if instruction_va != expected_instruction_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 VA 不一致: 记录 {instruction_va}, 期望 {expected_instruction_va}"
                )
            if instruction_end_va != expected_instruction_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 end_va 不一致: 记录 {instruction_end_va}, 期望 {expected_instruction_end_va}"
                )
            try:
                parsed_instruction_bytes = bytes.fromhex(instruction_bytes)
            except ValueError as error:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令 bytes 不是合法十六进制: {error}") from error
            if len(parsed_instruction_bytes) != instruction_size:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 bytes 长度与 size 不一致: "
                    f"长度 {len(parsed_instruction_bytes)}, size {instruction_size}"
                )
            actual_instruction_hash = hashlib.sha256(parsed_instruction_bytes).hexdigest()
            if instruction_hash != actual_instruction_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 指令 code_sha256 不一致: 期望 {actual_instruction_hash!r}, 实际 {instruction_hash!r}"
                )
            if parsed_instruction_bytes != code[instruction_offset:instruction_offset + instruction_size]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令字节与 raw bin 不一致")
            if instruction_source_op == "prologue" and instruction_asm == "mov r11, rbp ; global frame":
                if parsed_instruction_bytes != b"\x49\x89\xEB":
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} global-frame 初始化指令 bytes 不一致")
            if instruction_size:
                instruction_ranges.append((instruction_offset, instruction_offset + instruction_size))
                if parsed_instruction_bytes[:1] == b"\xE8":
                    expected_relocations[instruction_offset] = "call_rel32"
                else:
                    for relocation_kind, opcode in REL32_JUMP_OPCODES.items():
                        if parsed_instruction_bytes.startswith(opcode):
                            expected_relocations[instruction_offset] = relocation_kind
                            break
            if instruction.get("source_op") == "label":
                asm = instruction.get("asm")
                if isinstance(asm, str) and asm.endswith(":"):
                    labels[asm[:-1]] = {
                        "offset": instruction_offset,
                        "source_pc": instruction.get("source_pc"),
                        "source_line": instruction.get("source_line"),
                    }
        label_records = function.get("labels", [])
        if not isinstance(label_records, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} labels 必须是列表")
        seen_label_records: dict[str, int] = {}
        for label_index, label_record in enumerate(label_records):
            if not isinstance(label_record, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} labels[{label_index}] 必须是对象")
            extra_label_fields = sorted(set(label_record) - _MAP_LABEL_FIELDS)
            if extra_label_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} labels[{label_index}] 存在未知字段: {', '.join(extra_label_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} labels[{label_index}]", label_record)
            label_name = label_record.get("name")
            label_offset = label_record.get("offset")
            label_rva = label_record.get("rva")
            label_va = label_record.get("va")
            if not isinstance(label_name, str) or not label_name:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} labels[{label_index}].name 必须是非空字符串")
            if label_name in seen_label_records:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label 重复: {label_name}")
            if not isinstance(label_offset, int) or isinstance(label_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} offset 必须是整数")
            if not isinstance(label_rva, int) or isinstance(label_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} rva 必须是整数")
            if not isinstance(label_va, int) or isinstance(label_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} va 必须是整数")
            if label_offset < function_offset or label_offset > function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} offset 越界: {label_offset}")
            expected_label_rva = text_section["rva"] + label_offset
            if label_rva != expected_label_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} label {label_name} rva 不一致: 记录 {label_rva}, 期望 {expected_label_rva}"
                )
            expected_label_va = text_section["va"] + label_offset
            if label_va != expected_label_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} label {label_name} va 不一致: 记录 {label_va}, 期望 {expected_label_va}"
                )
            seen_label_records[label_name] = label_offset
        missing_labels = sorted(set(labels) - set(seen_label_records))
        if missing_labels:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} labels 缺少指令标签: {', '.join(missing_labels)}")
        extra_labels = sorted(set(seen_label_records) - set(labels))
        if extra_labels:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} labels 包含未知标签: {', '.join(extra_labels)}")
        for label_name, label_info in labels.items():
            label_offset = label_info["offset"]
            if seen_label_records[label_name] != label_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} label {label_name} offset 不一致: "
                    f"记录 {seen_label_records[label_name]}, 指令 {label_offset}"
                )
            label_record = next(item for item in label_records if item.get("name") == label_name)
            if label_record.get("source_pc") != label_info["source_pc"] or label_record.get("source_line") != label_info["source_line"]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} label {label_name} 来源位置与指令不一致")
        expected_relocations_by_function[name] = expected_relocations
        covered_until = function_offset
        for start, end in sorted(instruction_ranges):
            if start < covered_until:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令范围重叠: offset {start}, 已覆盖到 {covered_until}")
            if start > covered_until:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令范围前存在空洞: offset {start}, 已覆盖到 {covered_until}")
            covered_until = end
        if covered_until != function_end:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 指令范围未覆盖完整函数: 已覆盖到 {covered_until}, 函数结束 {function_end}")
        for instruction_index, instruction in enumerate(instructions):
            if instruction.get("source_op") != "call":
                continue
            asm = instruction.get("asm")
            if not isinstance(asm, str) or not asm.startswith("call "):
                continue
            if instruction_index + 3 >= len(instructions):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 缺少 _exit 传播探针: {asm}")
            add_rsp = instructions[instruction_index + 1]
            test_rdx = instructions[instruction_index + 2]
            jump = instructions[instruction_index + 3]
            if (
                add_rsp.get("source_op") != "call"
                or not isinstance(add_rsp.get("asm"), str)
                or not add_rsp["asm"].startswith("add rsp, ")
                or bytes.fromhex(add_rsp["bytes"])[:3] != b"\x48\x81\xC4"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 后缺少 add rsp 恢复栈窗口")
            if (
                test_rdx.get("source_op") != "call"
                or test_rdx.get("asm") != "test rdx, rdx ; native _exit flag"
                or bytes.fromhex(test_rdx["bytes"]) != b"\x48\x85\xD2"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 后缺少 native _exit 标志检查")
            jump_asm = jump.get("asm")
            if (
                jump.get("source_op") != "exit_probe"
                or not isinstance(jump_asm, str)
                or not jump_asm.startswith("jne __propagate_exit_")
                or bytes.fromhex(jump["bytes"])[:2] != b"\x0F\x85"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 后缺少 native _exit 传播跳转")
            target = jump_asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if target not in labels:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} native _exit 传播目标未知: {target}")
        instructions_by_offset = {
            instruction.get("offset"): instruction
            for instruction in instructions
            if isinstance(instruction.get("offset"), int) and not isinstance(instruction.get("offset"), bool)
        }
        if "exit_probes" not in function:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 缺少 exit_probes 字段")
        exit_probes = function["exit_probes"]
        if not isinstance(exit_probes, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} exit_probes 必须是列表")
        relocations_for_probe = function.get("relocations", [])
        relocation_targets_by_offset = {
            relocation.get("offset"): relocation.get("target")
            for relocation in relocations_for_probe
            if isinstance(relocation, dict)
            and isinstance(relocation.get("offset"), int)
            and not isinstance(relocation.get("offset"), bool)
        } if isinstance(relocations_for_probe, list) else {}
        probe_call_offsets: set[int] = set()
        exit_probe_jump_targets: dict[int, str] = {}
        for probe_index, probe in enumerate(exit_probes):
            if not isinstance(probe, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} exit_probes[{probe_index}] 必须是对象")
            extra_probe_fields = sorted(set(probe) - _MAP_EXIT_PROBE_FIELDS)
            if extra_probe_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} exit_probes[{probe_index}] 存在未知字段: {', '.join(extra_probe_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} exit_probes[{probe_index}]", probe)
            for field, end_field, rva_field, end_rva_field, va_field, end_va_field, instruction_size in (
                ("call_offset", "call_end_offset", "call_rva", "call_end_rva", "call_va", "call_end_va", CALL_REL32_SIZE),
                ("test_offset", "test_end_offset", "test_rva", "test_end_rva", "test_va", "test_end_va", TEST_RDX_RDX_SIZE),
                ("jump_offset", "jump_end_offset", "jump_rva", "jump_end_rva", "jump_va", "jump_end_va", JNE_REL32_SIZE),
            ):
                value = probe.get(field)
                end_value = probe.get(end_field)
                rva_value = probe.get(rva_field)
                end_rva_value = probe.get(end_rva_field)
                va_value = probe.get(va_field)
                end_va_value = probe.get(end_va_field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {field} 必须是整数")
                if not isinstance(end_value, int) or isinstance(end_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {end_field} 必须是整数")
                if not isinstance(rva_value, int) or isinstance(rva_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {rva_field} 必须是整数")
                if not isinstance(end_rva_value, int) or isinstance(end_rva_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {end_rva_field} 必须是整数")
                if not isinstance(va_value, int) or isinstance(va_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {va_field} 必须是整数")
                if not isinstance(end_va_value, int) or isinstance(end_va_value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {end_va_field} 必须是整数")
                expected_end_value = value + instruction_size
                if end_value != expected_end_value:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {end_field} 不一致: "
                        f"记录 {end_value}, 期望 {expected_end_value}"
                    )
                if value < function_offset or expected_end_value > function_end:
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {field} 越界: {value}")
                expected_rva = text_section["rva"] + value
                if rva_value != expected_rva:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {rva_field} 不一致: 记录 {rva_value}, 期望 {expected_rva}"
                    )
                expected_end_rva = text_section["rva"] + expected_end_value
                if end_rva_value != expected_end_rva:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {end_rva_field} 不一致: "
                        f"记录 {end_rva_value}, 期望 {expected_end_rva}"
                    )
                expected_va = text_section["va"] + value
                if va_value != expected_va:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {va_field} 不一致: 记录 {va_value}, 期望 {expected_va}"
                    )
                expected_end_va = text_section["va"] + expected_end_value
                if end_va_value != expected_end_va:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {end_va_field} 不一致: "
                        f"记录 {end_va_value}, 期望 {expected_end_va}"
                    )
            for hash_field in ("call_code_sha256", "test_code_sha256", "jump_code_sha256"):
                hash_value = probe.get(hash_field)
                if not isinstance(hash_value, str):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 必须是字符串")
                if len(hash_value) != 64:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 必须是 64 位十六进制字符串，"
                        f"实际长度 {len(hash_value)}"
                    )
                try:
                    bytes.fromhex(hash_value)
                except ValueError as error:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 不是合法十六进制: {error}"
                    ) from error
            target = probe.get("target")
            if not isinstance(target, str) or not target:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 target 必须是非空字符串")
            if target not in function_ranges:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针目标未知: {target}")
            probe_label = probe.get("probe_label")
            if not isinstance(probe_label, str) or not probe_label:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 probe_label 必须是非空字符串")
            if probe_label not in labels:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针标签未知: {probe_label}")
            call_offset = probe["call_offset"]
            test_offset = probe["test_offset"]
            jump_offset = probe["jump_offset"]
            if call_offset in probe_call_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call_offset 重复: {call_offset}")
            probe_call_offsets.add(call_offset)
            if code[call_offset:call_offset + 1] != b"\xE8":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call opcode 不一致")
            if code[test_offset:test_offset + 3] != b"\x48\x85\xD2":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 test opcode 不一致")
            if code[jump_offset:jump_offset + 2] != b"\x0F\x85":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 jump opcode 不一致")
            for prefix, offset, end_offset in (
                ("call", call_offset, probe["call_end_offset"]),
                ("test", test_offset, probe["test_end_offset"]),
                ("jump", jump_offset, probe["jump_end_offset"]),
            ):
                actual_hash = hashlib.sha256(code[offset:end_offset]).hexdigest()
                hash_field = f"{prefix}_code_sha256"
                if probe[hash_field] != actual_hash:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 {hash_field} 不一致: "
                        f"期望 {actual_hash!r}, 实际 {probe[hash_field]!r}"
                    )
            if jump_offset in exit_probe_jump_targets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 jump_offset 重复: {jump_offset}")
            exit_probe_jump_targets[jump_offset] = probe_label
            call_instruction = instructions_by_offset.get(call_offset)
            test_instruction = instructions_by_offset.get(test_offset)
            jump_instruction = instructions_by_offset.get(jump_offset)
            if call_instruction is None or call_instruction.get("source_op") != "call":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call 清单缺失")
            call_asm = call_instruction.get("asm")
            call_relocation_target = relocation_targets_by_offset.get(call_offset)
            if isinstance(call_relocation_target, str) and isinstance(call_asm, str):
                call_asm_target = call_asm.split(" ", 1)[1].split(";", 1)[0].strip() if call_asm.startswith("call ") else None
                if call_asm_target == call_relocation_target and call_relocation_target != target:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} _exit 传播探针 call 修补目标不一致: "
                        f"探针 {target}, 修补记录 {call_relocation_target}"
                    )
            if not isinstance(call_asm, str) or not call_asm.startswith(f"call {target}"):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 call 目标不一致")
            if (
                test_instruction is None
                or test_instruction.get("source_op") != "call"
                or test_instruction.get("asm") != "test rdx, rdx ; native _exit flag"
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 test 清单不一致")
            jump_asm = jump_instruction.get("asm") if jump_instruction is not None else None
            if (
                jump_instruction is None
                or jump_instruction.get("source_op") != "exit_probe"
                or not isinstance(jump_asm, str)
                or not jump_asm.startswith(f"jne {probe_label}")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针 jump 清单不一致")
            for instruction in (call_instruction, test_instruction, jump_instruction):
                if (
                    instruction.get("source_pc") != probe.get("source_pc")
                    or instruction.get("source_line") != probe.get("source_line")
                ):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} _exit 传播探针来源位置与清单不一致")
            for instruction, prefix in (
                (call_instruction, "call"),
                (test_instruction, "test"),
                (jump_instruction, "jump"),
            ):
                for instruction_field, probe_field in (
                    ("end_offset", f"{prefix}_end_offset"),
                    ("end_rva", f"{prefix}_end_rva"),
                    ("end_va", f"{prefix}_end_va"),
                ):
                    if instruction.get(instruction_field) != probe[probe_field]:
                        raise NativeCodegenError(
                            f"native 机器码 map 函数 {name} _exit 传播探针 {prefix} 清单范围不一致: "
                            f"{instruction_field} 记录 {instruction.get(instruction_field)}, 探针 {probe[probe_field]}"
                        )
        for instruction in instructions:
            if instruction.get("source_op") != "call":
                continue
            asm = instruction.get("asm")
            if not isinstance(asm, str) or not asm.startswith("call "):
                continue
            call_offset = instruction.get("offset")
            if call_offset not in probe_call_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call 缺少 _exit 传播探针记录: {asm}")
        function_labels[name] = labels
        exit_probe_jump_targets_by_function[name] = exit_probe_jump_targets
        call_frames = function.get("call_frames", [])
        if not isinstance(call_frames, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} call_frames 必须是列表")
        expected_call_frame_offsets = {
            instruction["offset"]
            for instruction in instructions
            if (
                instruction.get("source_op") == "call"
                and isinstance(instruction.get("asm"), str)
                and instruction["asm"].startswith("sub rsp, ")
                and isinstance(instruction.get("offset"), int)
                and not isinstance(instruction.get("offset"), bool)
            )
        }
        seen_call_frame_offsets: set[int] = set()
        for frame_index, frame in enumerate(call_frames):
            if not isinstance(frame, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call_frames[{frame_index}] 必须是对象")
            extra_frame_fields = sorted(set(frame) - _MAP_CALL_FRAME_FIELDS)
            if extra_frame_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} call_frames[{frame_index}] 存在未知字段: {', '.join(extra_frame_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} call_frames[{frame_index}]", frame)
            target = frame.get("target")
            if not isinstance(target, str) or not target:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 target 必须是非空字符串")
            if target not in function_ranges:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口目标未知: {target}")
            for field in (
                "offset",
                "end_offset",
                "rva",
                "end_rva",
                "va",
                "end_va",
                "call_offset",
                "call_end_offset",
                "call_rva",
                "call_end_rva",
                "call_va",
                "call_end_va",
                "add_offset",
                "add_end_offset",
                "add_rva",
                "add_end_rva",
                "add_va",
                "add_end_va",
                "arg_count",
                "register_arg_count",
                "stack_arg_count",
                "shadow_space_size",
                "stack_arg_bytes",
                "aligned_size",
                "stack_alignment",
            ):
                value = frame.get(field)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 {field} 必须是整数")
            for hash_field in ("sub_code_sha256", "call_code_sha256", "add_code_sha256"):
                hash_value = frame.get(hash_field)
                if not isinstance(hash_value, str):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 {hash_field} 必须是字符串")
                if len(hash_value) != 64:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口 {hash_field} 必须是 64 位十六进制字符串，"
                        f"实际长度 {len(hash_value)}"
                    )
                try:
                    bytes.fromhex(hash_value)
                except ValueError as error:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口 {hash_field} 不是合法十六进制: {error}"
                    ) from error
            expected_frame_rva = text_section["rva"] + frame["offset"]
            if frame["rva"] != expected_frame_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 rva 不一致: 记录 {frame['rva']}, 期望 {expected_frame_rva}"
                )
            expected_frame_va = text_section["va"] + frame["offset"]
            if frame["va"] != expected_frame_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 va 不一致: 记录 {frame['va']}, 期望 {expected_frame_va}"
                )
            if frame["arg_count"] != frame["register_arg_count"] + frame["stack_arg_count"]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口参数数量不一致")
            arg_types = frame.get("arg_types")
            if not isinstance(arg_types, list) or any(not isinstance(item, str) for item in arg_types):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 arg_types 必须是字符串列表")
            if len(arg_types) != frame["arg_count"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 arg_types 数量不一致: "
                    f"记录 {len(arg_types)}, 参数 {frame['arg_count']}"
                )
            param_types = frame.get("param_types")
            if not isinstance(param_types, list) or any(not isinstance(item, str) for item in param_types):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 param_types 必须是字符串列表")
            if len(param_types) != frame["arg_count"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 param_types 数量不一致: "
                    f"记录 {len(param_types)}, 参数 {frame['arg_count']}"
                )
            target_param_types = function_signatures[target][1]
            if param_types != target_param_types:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口形参类型与目标函数 {target} 签名不一致: "
                    f"记录 {param_types}, 签名 {target_param_types}"
                )
            for type_index, (arg_type, param_type) in enumerate(zip(arg_types, param_types)):
                if not is_argument_type_compatible(param_type, arg_type):
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口第 {type_index} 个参数类型不兼容: "
                        f"形参 {param_type}, 实参 {arg_type}"
                    )
            expected_register_arg_count = min(frame["arg_count"], len(argument_registers))
            if frame["register_arg_count"] != expected_register_arg_count:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口寄存器参数数量与 ABI 不一致: "
                    f"记录 {frame['register_arg_count']}, 期望 {expected_register_arg_count}"
                )
            expected_stack_arg_count = max(0, frame["arg_count"] - len(argument_registers))
            if frame["stack_arg_count"] != expected_stack_arg_count:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口栈参数数量与 ABI 不一致: "
                    f"记录 {frame['stack_arg_count']}, 期望 {expected_stack_arg_count}"
                )
            if frame["stack_arg_bytes"] != frame["stack_arg_count"] * abi_word_size:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口栈实参字节不一致")
            if frame["shadow_space_size"] < 0:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 shadow space 不能为负数")
            if frame["shadow_space_size"] != abi_shadow_space:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 shadow space 与 ABI 不一致: "
                    f"记录 {frame['shadow_space_size']}, 期望 {abi_shadow_space}"
                )
            if frame["stack_alignment"] <= 0:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口对齐必须为正数")
            if frame["stack_alignment"] != abi_stack_alignment:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口对齐与 ABI 不一致: "
                    f"记录 {frame['stack_alignment']}, 期望 {abi_stack_alignment}"
                )
            expected_size = frame["shadow_space_size"] + frame["stack_arg_bytes"]
            remainder = expected_size % frame["stack_alignment"]
            if remainder:
                expected_size += frame["stack_alignment"] - remainder
            if frame["aligned_size"] != expected_size:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口大小不一致: 记录 {frame['aligned_size']}, 期望 {expected_size}"
                )
            sub_rsp_size = len(encode_sub_rsp_imm32(frame["aligned_size"]))
            expected_frame_end_offset = frame["offset"] + sub_rsp_size
            if frame["end_offset"] != expected_frame_end_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 end_offset 不一致: "
                    f"记录 {frame['end_offset']}, 期望 {expected_frame_end_offset}"
                )
            expected_frame_end_rva = text_section["rva"] + expected_frame_end_offset
            if frame["end_rva"] != expected_frame_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 end_rva 不一致: "
                    f"记录 {frame['end_rva']}, 期望 {expected_frame_end_rva}"
                )
            expected_frame_end_va = text_section["va"] + expected_frame_end_offset
            if frame["end_va"] != expected_frame_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 end_va 不一致: "
                    f"记录 {frame['end_va']}, 期望 {expected_frame_end_va}"
                )
            if frame["offset"] < function_offset or frame["offset"] + sub_rsp_size > function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 sub rsp 越界: {frame['offset']}")
            if frame["offset"] in seen_call_frame_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口记录重复: {frame['offset']}")
            seen_call_frame_offsets.add(frame["offset"])
            sub_rsp_code = code[frame["offset"]:frame["offset"] + sub_rsp_size]
            if sub_rsp_code[:3] != b"\x48\x81\xEC":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 sub rsp opcode 不一致")
            actual_sub_hash = hashlib.sha256(sub_rsp_code).hexdigest()
            if frame["sub_code_sha256"] != actual_sub_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 sub_code_sha256 不一致: "
                    f"期望 {actual_sub_hash!r}, 实际 {frame['sub_code_sha256']!r}"
                )
            actual_size = int.from_bytes(sub_rsp_code[3:7], byteorder="little", signed=True)
            if actual_size != frame["aligned_size"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 sub rsp 大小不一致: 记录 {frame['aligned_size']}, 机器码 {actual_size}"
                )
            frame_instruction = instructions_by_offset.get(frame["offset"])
            if (
                frame_instruction is None
                or frame_instruction.get("source_op") != "call"
                or not isinstance(frame_instruction.get("asm"), str)
                or not frame_instruction["asm"].startswith("sub rsp, ")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口清单缺失")
            for instruction_field, frame_field in (
                ("end_offset", "end_offset"),
                ("end_rva", "end_rva"),
                ("end_va", "end_va"),
            ):
                if frame_instruction.get(instruction_field) != frame[frame_field]:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} 调用栈窗口清单范围不一致: "
                        f"{instruction_field} 记录 {frame_instruction.get(instruction_field)}, 栈窗口 {frame[frame_field]}"
                    )
            if (
                frame_instruction.get("source_pc") != frame.get("source_pc")
                or frame_instruction.get("source_line") != frame.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口来源位置与清单不一致")
            frame_instruction_index = instructions.index(frame_instruction)
            call_instruction = None
            call_instruction_index = None
            for candidate_index, candidate in enumerate(instructions[frame_instruction_index + 1:], start=frame_instruction_index + 1):
                asm = candidate.get("asm")
                if candidate.get("source_op") == "call" and isinstance(asm, str) and asm.startswith("call "):
                    call_instruction = candidate
                    call_instruction_index = candidate_index
                    break
            if call_instruction is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 call 清单缺失")
            call_asm = call_instruction["asm"]
            call_target = call_asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if call_target != target:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口目标与 call 清单不一致: 记录 {target}, 指令 {call_target}"
                )
            if (
                call_instruction.get("source_pc") != frame.get("source_pc")
                or call_instruction.get("source_line") != frame.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 call 来源位置与清单不一致")
            if frame["call_offset"] != call_instruction["offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_offset 与清单不一致: "
                    f"记录 {frame['call_offset']}, 清单 {call_instruction['offset']}"
                )
            if frame["call_end_offset"] != call_instruction["end_offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_end_offset 与清单不一致: "
                    f"记录 {frame['call_end_offset']}, 清单 {call_instruction['end_offset']}"
                )
            actual_call_hash = hashlib.sha256(code[frame["call_offset"]:frame["call_end_offset"]]).hexdigest()
            if frame["call_code_sha256"] != actual_call_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_code_sha256 不一致: "
                    f"期望 {actual_call_hash!r}, 实际 {frame['call_code_sha256']!r}"
                )
            expected_call_rva = text_section["rva"] + frame["call_offset"]
            if frame["call_rva"] != expected_call_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_rva 不一致: "
                    f"记录 {frame['call_rva']}, 期望 {expected_call_rva}"
                )
            expected_call_end_rva = text_section["rva"] + frame["call_end_offset"]
            if frame["call_end_rva"] != expected_call_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_end_rva 不一致: "
                    f"记录 {frame['call_end_rva']}, 期望 {expected_call_end_rva}"
                )
            expected_call_va = text_section["va"] + frame["call_offset"]
            if frame["call_va"] != expected_call_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_va 不一致: "
                    f"记录 {frame['call_va']}, 期望 {expected_call_va}"
                )
            expected_call_end_va = text_section["va"] + frame["call_end_offset"]
            if frame["call_end_va"] != expected_call_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 call_end_va 不一致: "
                    f"记录 {frame['call_end_va']}, 期望 {expected_call_end_va}"
                )
            if call_instruction_index is None or call_instruction_index + 1 >= len(instructions):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 清单缺失")
            add_instruction = instructions[call_instruction_index + 1]
            add_asm = add_instruction.get("asm")
            add_bytes = add_instruction.get("bytes")
            try:
                add_code = bytes.fromhex(add_bytes) if isinstance(add_bytes, str) else b""
            except ValueError as error:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp bytes 不是合法十六进制: {error}") from error
            if add_instruction.get("source_op") != "call" or add_asm != f"add rsp, {frame['aligned_size']}" or add_code[:3] != b"\x48\x81\xC4":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 清单不一致")
            add_size = int.from_bytes(add_code[3:7], byteorder="little", signed=True)
            if add_size != frame["aligned_size"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 大小不一致: 记录 {frame['aligned_size']}, 机器码 {add_size}"
                )
            if (
                add_instruction.get("source_pc") != frame.get("source_pc")
                or add_instruction.get("source_line") != frame.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口 add rsp 来源位置与清单不一致")
            if frame["add_offset"] != add_instruction["offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_offset 与清单不一致: "
                    f"记录 {frame['add_offset']}, 清单 {add_instruction['offset']}"
                )
            if frame["add_end_offset"] != add_instruction["end_offset"]:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_end_offset 与清单不一致: "
                    f"记录 {frame['add_end_offset']}, 清单 {add_instruction['end_offset']}"
                )
            actual_add_hash = hashlib.sha256(code[frame["add_offset"]:frame["add_end_offset"]]).hexdigest()
            if frame["add_code_sha256"] != actual_add_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_code_sha256 不一致: "
                    f"期望 {actual_add_hash!r}, 实际 {frame['add_code_sha256']!r}"
                )
            expected_add_rva = text_section["rva"] + frame["add_offset"]
            if frame["add_rva"] != expected_add_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_rva 不一致: "
                    f"记录 {frame['add_rva']}, 期望 {expected_add_rva}"
                )
            expected_add_end_rva = text_section["rva"] + frame["add_end_offset"]
            if frame["add_end_rva"] != expected_add_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_end_rva 不一致: "
                    f"记录 {frame['add_end_rva']}, 期望 {expected_add_end_rva}"
                )
            expected_add_va = text_section["va"] + frame["add_offset"]
            if frame["add_va"] != expected_add_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_va 不一致: "
                    f"记录 {frame['add_va']}, 期望 {expected_add_va}"
                )
            expected_add_end_va = text_section["va"] + frame["add_end_offset"]
            if frame["add_end_va"] != expected_add_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} 调用栈窗口 add_end_va 不一致: "
                    f"记录 {frame['add_end_va']}, 期望 {expected_add_end_va}"
                )
        for frame_offset in expected_call_frame_offsets:
            if frame_offset not in seen_call_frame_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} 调用栈窗口缺少记录: {frame_offset}")
    for function in functions:
        name = function["name"]
        function_offset, function_size = function_ranges[name]
        function_end = function_offset + function_size
        relocations = function.get("relocations", [])
        if not isinstance(relocations, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} relocations 必须是列表")
        instructions = function.get("instructions", [])
        instructions_by_offset = {
            instruction.get("offset"): instruction
            for instruction in instructions
            if isinstance(instruction, dict)
            and isinstance(instruction.get("offset"), int)
            and not isinstance(instruction.get("offset"), bool)
        }
        seen_relocation_offsets: set[int] = set()
        for relocation_index, relocation in enumerate(relocations):
            if not isinstance(relocation, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} relocations[{relocation_index}] 必须是对象")
            extra_relocation_fields = sorted(set(relocation) - _MAP_RELOCATION_FIELDS)
            if extra_relocation_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} relocations[{relocation_index}] 存在未知字段: {', '.join(extra_relocation_fields)}"
                )
            _validate_source_location_fields(f"native 机器码 map 函数 {name} relocations[{relocation_index}]", relocation)
            relocation_offset = relocation.get("offset")
            relocation_rva = relocation.get("rva")
            relocation_va = relocation.get("va")
            patch_offset = relocation.get("patch_offset")
            patch_rva = relocation.get("patch_rva")
            patch_va = relocation.get("patch_va")
            patch_end_offset = relocation.get("patch_end_offset")
            patch_end_rva = relocation.get("patch_end_rva")
            patch_end_va = relocation.get("patch_end_va")
            instruction_code_sha256 = relocation.get("instruction_code_sha256")
            patch_code_sha256 = relocation.get("patch_code_sha256")
            displacement = relocation.get("displacement")
            size = relocation.get("size")
            kind = relocation.get("kind")
            target = relocation.get("target")
            target_rva = relocation.get("target_rva")
            target_va = relocation.get("target_va")
            if not isinstance(relocation_offset, int) or isinstance(relocation_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 offset 必须是整数")
            if not isinstance(relocation_rva, int) or isinstance(relocation_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 rva 必须是整数")
            if not isinstance(relocation_va, int) or isinstance(relocation_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 va 必须是整数")
            if not isinstance(patch_offset, int) or isinstance(patch_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_offset 必须是整数")
            if not isinstance(patch_rva, int) or isinstance(patch_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_rva 必须是整数")
            if not isinstance(patch_va, int) or isinstance(patch_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_va 必须是整数")
            if not isinstance(patch_end_offset, int) or isinstance(patch_end_offset, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_end_offset 必须是整数")
            if not isinstance(patch_end_rva, int) or isinstance(patch_end_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_end_rva 必须是整数")
            if not isinstance(patch_end_va, int) or isinstance(patch_end_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 patch_end_va 必须是整数")
            if not isinstance(displacement, int) or isinstance(displacement, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 displacement 必须是整数")
            if not isinstance(size, int) or isinstance(size, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 size 必须是整数")
            if not isinstance(target_rva, int) or isinstance(target_rva, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 target_rva 必须是整数")
            if not isinstance(target_va, int) or isinstance(target_va, bool):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 target_va 必须是整数")
            for hash_field, hash_value in (
                ("instruction_code_sha256", instruction_code_sha256),
                ("patch_code_sha256", patch_code_sha256),
            ):
                if not isinstance(hash_value, str):
                    raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 {hash_field} 必须是字符串")
                if len(hash_value) != 64:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} rel32 {hash_field} 必须是 64 位十六进制字符串，"
                        f"实际长度 {len(hash_value)}"
                    )
                try:
                    bytes.fromhex(hash_value)
                except ValueError as error:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} rel32 {hash_field} 不是合法十六进制: {error}"
                    ) from error
            if kind not in {*REL32_JUMP_OPCODES, "call_rel32"}:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补类型暂不支持: {kind!r}")
            if relocation_offset in seen_relocation_offsets:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补记录重复: {relocation_offset}")
            seen_relocation_offsets.add(relocation_offset)
            relocation_instruction = instructions_by_offset.get(relocation_offset)
            if relocation_instruction is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补指令清单缺失: {relocation_offset}")
            if (
                relocation_instruction.get("source_pc") != relocation.get("source_pc")
                or relocation_instruction.get("source_line") != relocation.get("source_line")
            ):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 来源位置与清单不一致")
            if not isinstance(target, str) or not target:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 target 必须是非空字符串")
            if target not in function_ranges and target not in function_labels[name]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补目标未知: {target}")
            expected_exit_probe_target = exit_probe_jump_targets_by_function.get(name, {}).get(relocation_offset)
            if expected_exit_probe_target is not None and (kind != "jne_rel32" or target != expected_exit_probe_target):
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} _exit 传播探针 jump 修补目标不一致: "
                    f"探针 {expected_exit_probe_target}, 修补记录 {target}"
                )
            if size != 4:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补字段大小必须为 4，实际 {size}")
            expected_relocation_rva = text_section["rva"] + relocation_offset
            if relocation_rva != expected_relocation_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 RVA 不一致: 记录 {relocation_rva}, 期望 {expected_relocation_rva}"
                )
            expected_relocation_va = text_section["va"] + relocation_offset
            if relocation_va != expected_relocation_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 VA 不一致: 记录 {relocation_va}, 期望 {expected_relocation_va}"
                )
            expected_patch_offset = relocation_offset + (len(REL32_JUMP_OPCODES[kind]) if kind in REL32_JUMP_OPCODES else 1)
            if patch_offset != expected_patch_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 修补字段偏移不一致: 记录 {patch_offset}, 期望 {expected_patch_offset}"
                )
            expected_patch_end_offset = patch_offset + size
            if patch_end_offset != expected_patch_end_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_end_offset 不一致: 记录 {patch_end_offset}, 期望 {expected_patch_end_offset}"
                )
            expected_patch_rva = text_section["rva"] + patch_offset
            if patch_rva != expected_patch_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_rva 不一致: 记录 {patch_rva}, 期望 {expected_patch_rva}"
                )
            expected_patch_end_rva = expected_patch_rva + size
            if patch_end_rva != expected_patch_end_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_end_rva 不一致: 记录 {patch_end_rva}, 期望 {expected_patch_end_rva}"
                )
            expected_patch_va = text_section["va"] + patch_offset
            if patch_va != expected_patch_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_va 不一致: 记录 {patch_va}, 期望 {expected_patch_va}"
                )
            expected_patch_end_va = expected_patch_va + size
            if patch_end_va != expected_patch_end_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_end_va 不一致: 记录 {patch_end_va}, 期望 {expected_patch_end_va}"
                )
            target_offset = function_ranges[target][0] if target in function_ranges else function_labels[name][target]["offset"]
            expected_target_rva = text_section["rva"] + target_offset
            if target_rva != expected_target_rva:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 target_rva 不一致: 记录 {target_rva}, 期望 {expected_target_rva}"
                )
            expected_target_va = text_section["va"] + target_offset
            if target_va != expected_target_va:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 target_va 不一致: 记录 {target_va}, 期望 {expected_target_va}"
                )
            if relocation_offset < function_offset or relocation_offset >= function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 指令偏移越界: {relocation_offset}")
            if patch_offset < function_offset or patch_offset + size > function_end:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补字段越界: {patch_offset}")
            opcode = code[relocation_offset:patch_offset]
            if kind in REL32_JUMP_OPCODES and opcode != REL32_JUMP_OPCODES[kind]:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} {kind} opcode 不一致")
            if kind == "call_rel32" and opcode != b"\xE8":
                raise NativeCodegenError(f"native 机器码 map 函数 {name} call_rel32 opcode 不一致")
            actual_instruction_hash = hashlib.sha256(code[relocation_offset:patch_end_offset]).hexdigest()
            if instruction_code_sha256 != actual_instruction_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 instruction_code_sha256 不一致: "
                    f"期望 {actual_instruction_hash!r}, 实际 {instruction_code_sha256!r}"
                )
            actual_patch_hash = hashlib.sha256(code[patch_offset:patch_end_offset]).hexdigest()
            if patch_code_sha256 != actual_patch_hash:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 patch_code_sha256 不一致: "
                    f"期望 {actual_patch_hash!r}, 实际 {patch_code_sha256!r}"
                )
            actual_displacement = int.from_bytes(code[patch_offset:patch_offset + size], byteorder="little", signed=True)
            if actual_displacement != displacement:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 位移与机器码不一致: 记录 {displacement}, 机器码 {actual_displacement}"
                )
            expected_target_from_displacement = patch_offset + size + displacement
            if expected_target_from_displacement != target_offset:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 目标与位移不一致: 记录目标 {target_offset}, 位移目标 {expected_target_from_displacement}"
                )
            relocation_asm = relocation_instruction.get("asm")
            expected_asm_prefix = {**REL32_JUMP_ASM_PREFIXES, "call_rel32": "call "}[kind]
            if not isinstance(relocation_asm, str) or not relocation_asm.startswith(expected_asm_prefix):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} rel32 修补指令清单类型不一致")
            instruction_target = relocation_asm.split(" ", 1)[1].split(";", 1)[0].strip()
            if instruction_target != target:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 目标与清单不一致: 记录 {target}, 指令 {instruction_target}"
                )
        for relocation_offset, expected_kind in expected_relocations_by_function[name].items():
            if relocation_offset not in seen_relocation_offsets:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} rel32 指令缺少修补记录: offset {relocation_offset}, 类型 {expected_kind}"
                )
    if global_frame_owners and not global_owner_slots:
        owner = next(iter(global_frame_owners))
        raise NativeCodegenError(f"native 机器码 map 函数 {owner} 初始化 R11 global frame 但没有声明全局栈槽")
    for function_name, slots in non_owner_global_slots.items():
        for slot_name, slot_offset, slot_size in slots:
            owner_slot = global_owner_slots.get(slot_name)
            if owner_slot is None:
                raise NativeCodegenError(f"native 机器码 map 函数 {function_name} 全局栈槽缺少 global-frame owner 声明: {slot_name}")
            if owner_slot != (slot_offset, slot_size):
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {function_name} 全局栈槽 {slot_name} 与 global-frame owner 布局不一致"
                )
    for function in functions:
        name = function["name"]
        stack_slots = function.get("stack_slots", [])
        validate_native_array_layout(name, stack_slots, function["instructions"], function["frame_size"])
        expected_value_locations = [
            native_value_location(
                name,
                NativeStackSlotAllocation(
                    name=str(slot["name"]),
                    offset=int(slot["offset"]),
                    size=int(slot["size"]),
                ),
            )
            for slot in stack_slots
        ]
        if "value_locations" not in function:
            raise NativeCodegenError(f"native 机器码 map 函数 {name} 缺少 value_locations 字段")
        value_locations = function["value_locations"]
        if not isinstance(value_locations, list):
            raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations 必须是列表")
        if len(value_locations) != len(expected_value_locations):
            raise NativeCodegenError(
                f"native 机器码 map 函数 {name} value_locations 数量不一致: "
                f"记录 {len(value_locations)}, 期望 {len(expected_value_locations)}"
            )
        seen_value_locations: set[str] = set()
        for location_index, (location, expected_location) in enumerate(zip(value_locations, expected_value_locations)):
            if not isinstance(location, dict):
                raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations[{location_index}] 必须是对象")
            extra_location_fields = sorted(set(location) - _MAP_VALUE_LOCATION_FIELDS)
            if extra_location_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} value_locations[{location_index}] 存在未知字段: "
                    f"{', '.join(extra_location_fields)}"
                )
            missing_location_fields = sorted(_MAP_VALUE_LOCATION_FIELDS - set(location))
            if missing_location_fields:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} value_locations[{location_index}] 缺少字段: "
                    f"{', '.join(missing_location_fields)}"
                )
            location_name = location["name"]
            if not isinstance(location_name, str) or not location_name:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations[{location_index}].name 必须是非空字符串")
            if location_name in seen_value_locations:
                raise NativeCodegenError(f"native 机器码 map 函数 {name} value_locations 重复: {location_name}")
            seen_value_locations.add(location_name)
            for field in ("kind", "index", "storage", "base_register"):
                if not isinstance(location[field], str) or not location[field]:
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} value_locations[{location_index}].{field} 必须是非空字符串"
                    )
            for field in ("offset", "size"):
                if not isinstance(location[field], int) or isinstance(location[field], bool):
                    raise NativeCodegenError(
                        f"native 机器码 map 函数 {name} value_locations[{location_index}].{field} 必须是整数"
                    )
            if location != expected_location:
                raise NativeCodegenError(
                    f"native 机器码 map 函数 {name} value_locations[{location_index}] 与 stack_slots 不一致: "
                    f"记录 {location!r}, 期望 {expected_location!r}"
                )
    if entry not in function_ranges:
        raise NativeCodegenError(f"native 机器码 map 入口函数不在 functions 中: {entry}")
    if function_ranges[entry][0] != entry_offset:
        raise NativeCodegenError(
            f"native 机器码 map 入口偏移与函数偏移不一致: entry_offset {entry_offset}, 函数偏移 {function_ranges[entry][0]}"
        )
    symbols = metadata.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise NativeCodegenError("native 机器码 map 字段 symbols 必须是非空列表")
    seen_symbols: set[str] = set()
    entry_symbol_count = 0
    for index, symbol in enumerate(symbols):
        if not isinstance(symbol, dict):
            raise NativeCodegenError(f"native 机器码 map symbols[{index}] 必须是对象")
        extra_symbol_fields = sorted(set(symbol) - _MAP_SYMBOL_FIELDS)
        if extra_symbol_fields:
            raise NativeCodegenError(
                f"native 机器码 map symbols[{index}] 存在未知字段: {', '.join(extra_symbol_fields)}"
            )
        name = symbol.get("name")
        if not isinstance(name, str) or not name:
            raise NativeCodegenError(f"native 机器码 map symbols[{index}].name 必须是非空字符串")
        if name in seen_symbols:
            raise NativeCodegenError(f"native 机器码 map 符号重复: {name}")
        seen_symbols.add(name)
        if symbol.get("kind") != "function":
            raise NativeCodegenError(f"native 机器码 map 符号 {name} 类型暂不支持: {symbol.get('kind')!r}")
        if name not in function_ranges:
            raise NativeCodegenError(f"native 机器码 map 符号引用未知函数: {name}")
        return_type = symbol.get("return_type")
        if not isinstance(return_type, str) or return_type not in SUPPORTED_RETURN_TYPES:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} return_type 暂不支持: {return_type!r}")
        param_types = symbol.get("param_types")
        if not isinstance(param_types, list) or any(not isinstance(item, str) for item in param_types):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} param_types 必须是字符串列表")
        for param_index, param_type in enumerate(param_types):
            if param_type not in SUPPORTED_VALUE_TYPES:
                raise NativeCodegenError(
                    f"native 机器码 map 符号 {name} 第 {param_index} 个参数暂不支持类型: {param_type!r}"
                )
        expected_return_type, expected_param_types = function_signatures[name]
        if return_type != expected_return_type:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} return_type 与函数签名不一致: "
                f"符号 {return_type!r}, 函数 {expected_return_type!r}"
            )
        if param_types != expected_param_types:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} param_types 与函数签名不一致: "
                f"符号 {param_types}, 函数 {expected_param_types}"
            )
        offset = symbol.get("offset")
        size = symbol.get("size")
        end_offset = symbol.get("end_offset")
        rva = symbol.get("rva")
        end_rva = symbol.get("end_rva")
        va = symbol.get("va")
        end_va = symbol.get("end_va")
        symbol_hash = symbol.get("code_sha256")
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} offset 必须是整数")
        if not isinstance(size, int) or isinstance(size, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} size 必须是整数")
        if not isinstance(end_offset, int) or isinstance(end_offset, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} end_offset 必须是整数")
        if not isinstance(rva, int) or isinstance(rva, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} rva 必须是整数")
        if not isinstance(end_rva, int) or isinstance(end_rva, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} end_rva 必须是整数")
        if not isinstance(va, int) or isinstance(va, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} va 必须是整数")
        if not isinstance(end_va, int) or isinstance(end_va, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} end_va 必须是整数")
        if not isinstance(symbol_hash, str):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} code_sha256 必须是字符串")
        if (offset, size) != function_ranges[name]:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} 范围与函数不一致")
        expected_symbol_end_offset = offset + size
        if end_offset != expected_symbol_end_offset:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} end_offset 不一致: 记录 {end_offset}, 期望 {expected_symbol_end_offset}"
            )
        expected_symbol_rva = text_section["rva"] + offset
        if rva != expected_symbol_rva:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} RVA 不一致: 记录 {rva}, 期望 {expected_symbol_rva}"
            )
        expected_symbol_end_rva = expected_symbol_rva + size
        if end_rva != expected_symbol_end_rva:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} end_rva 不一致: 记录 {end_rva}, 期望 {expected_symbol_end_rva}"
            )
        expected_symbol_va = text_section["va"] + offset
        if va != expected_symbol_va:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} VA 不一致: 记录 {va}, 期望 {expected_symbol_va}"
            )
        expected_symbol_end_va = expected_symbol_va + size
        if end_va != expected_symbol_end_va:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} end_va 不一致: 记录 {end_va}, 期望 {expected_symbol_end_va}"
            )
        if len(symbol_hash) != 64:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} code_sha256 必须是 64 位十六进制字符串，实际长度 {len(symbol_hash)}")
        try:
            bytes.fromhex(symbol_hash)
        except ValueError as error:
            raise NativeCodegenError(f"native 机器码 map 符号 {name} code_sha256 不是合法十六进制: {error}") from error
        actual_symbol_hash = hashlib.sha256(code[offset:offset + size]).hexdigest()
        if symbol_hash != actual_symbol_hash:
            raise NativeCodegenError(
                f"native 机器码 map 符号 {name} code_sha256 不一致: 期望 {actual_symbol_hash!r}, 实际 {symbol_hash!r}"
            )
        is_entry = symbol.get("is_entry")
        if not isinstance(is_entry, bool):
            raise NativeCodegenError(f"native 机器码 map 符号 {name} is_entry 必须是布尔值")
        if is_entry:
            entry_symbol_count += 1
            if name != entry:
                raise NativeCodegenError(f"native 机器码 map 符号 {name} 入口标记与 entry 不一致")
    if entry_symbol_count != 1:
        raise NativeCodegenError(f"native 机器码 map 入口符号数量必须为 1，实际 {entry_symbol_count}")
    missing_symbols = sorted(set(function_ranges) - seen_symbols)
    if missing_symbols:
        raise NativeCodegenError(f"native 机器码 map 符号表缺少函数: {', '.join(missing_symbols)}")


def validate_native_text_section_map_bytes(text_raw: bytes, metadata: dict[str, object]) -> None:
    """校验补零后的 PE .text raw section 与结构化 map 一致。"""
    if not isinstance(text_raw, bytes):
        raise NativeCodegenError(f"native .text raw section 必须是 bytes，实际 {type(text_raw).__name__}")
    if not isinstance(metadata, dict):
        raise NativeCodegenError(f"native .text raw section map 必须是对象，实际 {type(metadata).__name__}")
    sections = metadata.get("sections")
    if not isinstance(sections, list) or not sections:
        raise NativeCodegenError("native .text raw section map 字段 sections 必须是非空列表")
    text_sections = [section for section in sections if isinstance(section, dict) and section.get("name") == ".text"]
    if len(text_sections) != 1:
        raise NativeCodegenError(f"native .text raw section map .text section 数量必须为 1，实际 {len(text_sections)}")
    text_section = text_sections[0]
    code_size = metadata.get("code_size")
    raw_size_aligned = text_section.get("raw_size_aligned")
    raw_padding_size = text_section.get("raw_padding_size")
    raw_padded_sha256 = text_section.get("raw_padded_sha256")
    if not isinstance(code_size, int) or isinstance(code_size, bool):
        raise NativeCodegenError("native .text raw section map 字段 code_size 必须是整数")
    if not isinstance(raw_size_aligned, int) or isinstance(raw_size_aligned, bool):
        raise NativeCodegenError("native .text raw section map .text section raw_size_aligned 必须是整数")
    if not isinstance(raw_padding_size, int) or isinstance(raw_padding_size, bool):
        raise NativeCodegenError("native .text raw section map .text section raw_padding_size 必须是整数")
    if not isinstance(raw_padded_sha256, str):
        raise NativeCodegenError("native .text raw section map .text section raw_padded_sha256 必须是字符串")
    if code_size < 0:
        raise NativeCodegenError(f"native .text raw section map 字段 code_size 必须是非负整数，实际 {code_size}")
    if raw_size_aligned < code_size:
        raise NativeCodegenError(
            f"native .text raw section map .text section raw_size_aligned 小于 code_size: "
            f"{raw_size_aligned} < {code_size}"
        )
    expected_padding_size = raw_size_aligned - code_size
    if raw_padding_size != expected_padding_size:
        raise NativeCodegenError(
            f"native .text raw section map .text section raw_padding_size 不一致: "
            f"期望 {expected_padding_size}, 实际 {raw_padding_size}"
        )
    if len(text_raw) != raw_size_aligned:
        raise NativeCodegenError(
            f"native .text raw section 大小不一致: 期望 {raw_size_aligned}, 实际 {len(text_raw)}"
        )
    if text_raw[code_size:] != bytes(raw_padding_size):
        raise NativeCodegenError("native .text raw section 尾部补零区域不一致")
    actual_padded_hash = hashlib.sha256(text_raw).hexdigest()
    if raw_padded_sha256 != actual_padded_hash:
        raise NativeCodegenError(
            f"native .text raw section raw_padded_sha256 不一致: "
            f"期望 {raw_padded_sha256!r}, 实际 {actual_padded_hash!r}"
        )
    validate_native_code_map_bytes(text_raw[:code_size], metadata)


def _validate_source_location_fields(owner: str, item: dict[str, object]) -> None:
    """校验 map 来源位置字段。"""
    for field in ("source_pc", "source_line"):
        if field not in item:
            raise NativeCodegenError(f"{owner}.{field} 缺失")
        value = item[field]
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise NativeCodegenError(f"{owner}.{field} 必须是非负整数或 null，实际 {type(value).__name__}")
        if value < 0:
            raise NativeCodegenError(f"{owner}.{field} 必须是非负整数或 null，实际 {value}")

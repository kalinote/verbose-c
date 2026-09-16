import hashlib
import pytest
from verbose_c.compiler.native import NativeCodeFunction, NativeCodeInstruction, NativeCodeProgram, NativeCodegenError, NativeSymbol, NativeTarget, format_native_code_program, native_code_program_map, validate_native_code_map_bytes, validate_native_code_program_map, validate_native_text_section_map_bytes
from verbose_c.compiler.native.encoder import encode_add_rsp_imm32, encode_call_rel32, encode_jne_rel32, encode_sub_rsp_imm32, encode_test_rdx_rdx
from verbose_c.engine.engine import run_source_file


def test_native_code_program_map_describes_raw_binary(tmp_path):
    source_path = tmp_path / "native_emit_map.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    validate_native_code_program_map(program, metadata)

    assert metadata["schema_version"] == 1
    assert metadata["target"] == "windows-x64"
    assert metadata["pe_machine"] == "AMD64"
    assert metadata["pe_machine_value"] == 0x8664
    assert metadata["pe_coff_header"] == {
        "Machine": 0x8664,
        "NumberOfSections": 1,
        "TimeDateStamp": 0,
        "PointerToSymbolTable": 0,
        "NumberOfSymbols": 0,
        "SizeOfOptionalHeader": 240,
        "Characteristics": 0x22,
    }
    assert metadata["pe_optional_header_magic"] == "PE32+"
    assert metadata["pe_optional_header_magic_value"] == 0x20B
    assert metadata["pe_optional_header"] == {
        "Magic": 0x20B,
        "SizeOfCode": ((len(program.code) + 511) // 512) * 512,
        "SizeOfInitializedData": 0,
        "SizeOfUninitializedData": 0,
        "AddressOfEntryPoint": 4096 + program.entry_offset,
        "BaseOfCode": 4096,
        "ImageBase": 0x140000000,
        "SectionAlignment": 4096,
        "FileAlignment": 512,
        "SizeOfImage": 4096 + ((len(program.code) + 4095) // 4096) * 4096,
        "SizeOfHeaders": 512,
        "Subsystem": 3,
        "NumberOfRvaAndSizes": 16,
    }
    assert metadata["pe_subsystem"] == "console"
    assert metadata["pe_subsystem_value"] == 3
    assert metadata["pe_number_of_sections"] == 1
    assert metadata["pe_dos_header_size"] == 64
    assert metadata["pe_lfanew"] == 0x80
    assert metadata["pe_signature_offset"] == 0x80
    assert metadata["pe_signature_size"] == 4
    assert metadata["pe_coff_header_offset"] == 0x84
    assert metadata["pe_coff_header_size"] == 20
    assert metadata["pe_optional_header_offset"] == 0x98
    assert metadata["pe_optional_header_size"] == 240
    assert metadata["pe_section_table_offset"] == 0x188
    assert metadata["pe_section_header_size"] == 40
    assert metadata["pe_section_table_size"] == 40
    assert metadata["pe_size_of_headers"] == 512
    assert metadata["pe_file_layout"] == {
        "dos_header": {"offset": 0, "size": 64, "end_offset": 64},
        "dos_stub_padding": {"offset": 64, "size": 64, "end_offset": 128},
        "pe_signature": {"offset": 128, "size": 4, "end_offset": 132},
        "coff_header": {"offset": 132, "size": 20, "end_offset": 152},
        "optional_header": {"offset": 152, "size": 240, "end_offset": 392},
        "section_table": {"offset": 392, "size": 40, "end_offset": 432},
        "headers_padding": {"offset": 432, "size": 80, "end_offset": 512},
        "text_raw": {
            "offset": 512,
            "size": ((len(program.code) + 511) // 512) * 512,
            "end_offset": 512 + ((len(program.code) + 511) // 512) * 512,
        },
        "file_size": 512 + ((len(program.code) + 511) // 512) * 512,
    }
    assert metadata["pe_base_of_code"] == 4096
    assert metadata["pe_address_of_entry_point"] == metadata["entry_rva"]
    assert metadata["pe_size_of_code"] == ((len(program.code) + 511) // 512) * 512
    assert metadata["pe_size_of_initialized_data"] == 0
    assert metadata["pe_size_of_uninitialized_data"] == 0
    assert metadata["pe_size_of_image"] == 4096 + ((len(program.code) + 4095) // 4096) * 4096
    assert metadata["pe_file_alignment"] == 512
    assert metadata["pe_section_alignment"] == 4096
    assert metadata["image_base"] == 0x140000000
    assert metadata["entry"] == "<module>"
    assert metadata["entry_offset"] == program.entry_offset
    assert metadata["entry_rva"] == 4096 + program.entry_offset
    assert metadata["entry_va"] == metadata["image_base"] + metadata["entry_rva"]
    assert metadata["abi"] == {
        "name": "windows-x64-msvc-mvp",
        "target": "windows-x64",
        "word_size": 8,
        "stack_alignment": 16,
        "shadow_space_size": 32,
        "argument_registers": ["RCX", "RDX", "R8", "R9"],
        "return_register": "RAX",
        "frame_pointer": "RBP",
        "stack_pointer": "RSP",
        "supported_value_types": ["int64", "bool64", "float32", "float64", "string", "void"],
    }
    assert metadata["global_frame_owner"] is None
    assert metadata["code_size"] == len(program.code)
    assert metadata["code_sha256"] == hashlib.sha256(program.code).hexdigest()
    assert metadata["sections"] == [
        {
            "name": ".text",
            "name_bytes": "2E 74 65 78 74 00 00 00",
            "offset": 0,
            "size": len(program.code),
            "end_offset": len(program.code),
            "virtual_size": len(program.code),
            "raw_size_aligned": ((len(program.code) + 511) // 512) * 512,
            "raw_padding_size": ((len(program.code) + 511) // 512) * 512 - len(program.code),
            "raw_padded_sha256": hashlib.sha256(
                program.code + bytes(((len(program.code) + 511) // 512) * 512 - len(program.code))
            ).hexdigest(),
            "virtual_size_aligned": ((len(program.code) + 4095) // 4096) * 4096,
            "rva": 4096,
            "end_rva": 4096 + len(program.code),
            "va": metadata["image_base"] + 4096,
            "end_va": metadata["image_base"] + 4096 + len(program.code),
            "entry_offset": program.entry_offset,
            "pe_raw_pointer": 512,
            "pe_raw_end_pointer": 512 + ((len(program.code) + 511) // 512) * 512,
            "pe_section_header": {
                "Name": ".text",
                "NameBytes": "2E 74 65 78 74 00 00 00",
                "VirtualSize": len(program.code),
                "VirtualAddress": 4096,
                "SizeOfRawData": ((len(program.code) + 511) // 512) * 512,
                "PointerToRawData": 512,
                "PointerToRelocations": 0,
                "PointerToLinenumbers": 0,
                "NumberOfRelocations": 0,
                "NumberOfLinenumbers": 0,
                "Characteristics": 0x60000020,
            },
            "sha256": hashlib.sha256(program.code).hexdigest(),
            "alignment": 16,
            "file_alignment": 512,
            "section_alignment": 4096,
            "permissions": ["read", "execute"],
            "characteristics": ["CNT_CODE", "MEM_EXECUTE", "MEM_READ"],
            "pe_characteristics": 0x60000020,
        }
    ]
    assert metadata["symbols"] == [
        {
            "name": symbol.name,
            "kind": symbol.kind,
            "return_type": symbol.return_type,
            "param_types": list(symbol.param_types),
            "offset": symbol.offset,
            "rva": 4096 + symbol.offset,
            "va": metadata["image_base"] + 4096 + symbol.offset,
            "size": symbol.size,
            "end_offset": symbol.offset + symbol.size,
            "end_rva": 4096 + symbol.offset + symbol.size,
            "end_va": metadata["image_base"] + 4096 + symbol.offset + symbol.size,
            "code_sha256": hashlib.sha256(program.functions[symbol.name].code).hexdigest(),
            "is_entry": symbol.is_entry,
        }
        for symbol in program.symbols
    ]
    functions = {item["name"]: item for item in metadata["functions"]}
    assert functions["<module>"]["register_allocation"] == {
        "strategy": "保守栈槽分配",
        "temporary_registers": ["RAX", "R10"],
        "argument_registers": [],
        "return_register": "RAX",
        "frame_pointer": "RBP",
        "stack_pointer": "RSP",
        "virtual_register_storage": "全部写入栈槽",
        "local_storage": "全部写入栈槽",
        "global_frame_register": None,
        "global_frame_role": "none",
    }
    assert functions["add2"]["register_allocation"]["argument_registers"] == ["RCX", "RDX"]
    assert functions["add2"]["register_allocation"]["global_frame_role"] == "none"
    assert functions["add2"]["return_type"] == "int64"
    assert functions["add2"]["param_types"] == ["int64", "int64"]
    assert program.functions["add2"].return_type == "int64"
    assert program.functions["add2"].param_types == ("int64", "int64")
    assert functions["add2"]["value_locations"][0] == {
        "name": "local[0]",
        "kind": "local",
        "index": "0",
        "storage": "stack",
        "base_register": "RBP",
        "offset": 8,
        "size": 8,
    }
    assert any(location["kind"] == "vreg" and location["name"].startswith("%v") for location in functions["add2"]["value_locations"])
    assert functions["main"]["call_frames"][0]["register_arg_count"] == 2
    assert functions["main"]["call_frames"][0]["arg_types"] == ["int64", "int64"]
    assert functions["main"]["call_frames"][0]["param_types"] == ["int64", "int64"]
    assert functions["<module>"]["offset"] == program.functions["<module>"].offset
    assert functions["<module>"]["end_offset"] == program.functions["<module>"].offset + len(program.functions["<module>"].code)
    assert functions["<module>"]["rva"] == 4096 + program.functions["<module>"].offset
    assert functions["<module>"]["end_rva"] == 4096 + program.functions["<module>"].offset + len(program.functions["<module>"].code)
    assert functions["<module>"]["va"] == metadata["image_base"] + functions["<module>"]["rva"]
    assert functions["<module>"]["end_va"] == metadata["image_base"] + functions["<module>"]["end_rva"]
    assert functions["<module>"]["code_sha256"] == hashlib.sha256(program.functions["<module>"].code).hexdigest()
    assert functions["main"]["rva"] == 4096 + program.functions["main"].offset
    assert functions["main"]["size"] == len(program.functions["main"].code)
    assert functions["main"]["end_offset"] == program.functions["main"].offset + len(program.functions["main"].code)
    assert functions["main"]["end_rva"] == 4096 + program.functions["main"].offset + len(program.functions["main"].code)
    assert functions["main"]["va"] == metadata["image_base"] + functions["main"]["rva"]
    assert functions["main"]["end_va"] == metadata["image_base"] + functions["main"]["end_rva"]
    assert functions["main"]["code_sha256"] == hashlib.sha256(program.functions["main"].code).hexdigest()
    first_main_instruction = functions["main"]["instructions"][0]
    assert first_main_instruction["end_offset"] == first_main_instruction["offset"] + first_main_instruction["size"]
    assert first_main_instruction["rva"] == 4096 + first_main_instruction["offset"]
    assert first_main_instruction["end_rva"] == first_main_instruction["rva"] + first_main_instruction["size"]
    assert first_main_instruction["va"] == metadata["image_base"] + first_main_instruction["rva"]
    assert first_main_instruction["end_va"] == metadata["image_base"] + first_main_instruction["end_rva"]
    assert first_main_instruction["code_sha256"] == hashlib.sha256(bytes.fromhex(first_main_instruction["bytes"])).hexdigest()
    main_call_relocation = next(item for item in functions["main"]["relocations"] if item["kind"] == "call_rel32")
    assert main_call_relocation["rva"] == 4096 + main_call_relocation["offset"]
    assert main_call_relocation["va"] == metadata["image_base"] + main_call_relocation["rva"]
    assert main_call_relocation["patch_rva"] == 4096 + main_call_relocation["patch_offset"]
    assert main_call_relocation["patch_va"] == metadata["image_base"] + main_call_relocation["patch_rva"]
    assert main_call_relocation["patch_end_offset"] == main_call_relocation["patch_offset"] + main_call_relocation["size"]
    assert main_call_relocation["patch_end_rva"] == main_call_relocation["patch_rva"] + main_call_relocation["size"]
    assert main_call_relocation["patch_end_va"] == main_call_relocation["patch_va"] + main_call_relocation["size"]
    assert main_call_relocation["instruction_code_sha256"] == hashlib.sha256(
        program.code[main_call_relocation["offset"]:main_call_relocation["patch_end_offset"]]
    ).hexdigest()
    assert main_call_relocation["patch_code_sha256"] == hashlib.sha256(
        program.code[main_call_relocation["patch_offset"]:main_call_relocation["patch_end_offset"]]
    ).hexdigest()
    assert main_call_relocation["target_rva"] == 4096 + program.functions["add2"].offset
    assert main_call_relocation["target_va"] == metadata["image_base"] + main_call_relocation["target_rva"]
    main_call_frame = functions["main"]["call_frames"][0]
    assert main_call_frame["rva"] == 4096 + main_call_frame["offset"]
    assert main_call_frame["end_offset"] == main_call_frame["offset"] + len(encode_sub_rsp_imm32(main_call_frame["aligned_size"]))
    assert main_call_frame["sub_code_sha256"] == hashlib.sha256(
        program.code[main_call_frame["offset"]:main_call_frame["end_offset"]]
    ).hexdigest()
    assert main_call_frame["end_rva"] == 4096 + main_call_frame["end_offset"]
    assert main_call_frame["va"] == metadata["image_base"] + main_call_frame["rva"]
    assert main_call_frame["end_va"] == metadata["image_base"] + main_call_frame["end_rva"]
    main_instructions = {item["offset"]: item for item in functions["main"]["instructions"]}
    assert main_call_frame["end_offset"] == main_instructions[main_call_frame["offset"]]["end_offset"]
    assert main_call_frame["end_rva"] == main_instructions[main_call_frame["offset"]]["end_rva"]
    assert main_call_frame["end_va"] == main_instructions[main_call_frame["offset"]]["end_va"]
    assert main_call_frame["call_rva"] == 4096 + main_call_frame["call_offset"]
    assert main_call_frame["call_end_offset"] == main_instructions[main_call_frame["call_offset"]]["end_offset"]
    assert main_call_frame["call_code_sha256"] == hashlib.sha256(
        program.code[main_call_frame["call_offset"]:main_call_frame["call_end_offset"]]
    ).hexdigest()
    assert main_call_frame["call_end_rva"] == main_instructions[main_call_frame["call_offset"]]["end_rva"]
    assert main_call_frame["call_va"] == metadata["image_base"] + main_call_frame["call_rva"]
    assert main_call_frame["call_end_va"] == main_instructions[main_call_frame["call_offset"]]["end_va"]
    assert main_call_frame["add_rva"] == 4096 + main_call_frame["add_offset"]
    assert main_call_frame["add_end_offset"] == main_instructions[main_call_frame["add_offset"]]["end_offset"]
    assert main_call_frame["add_code_sha256"] == hashlib.sha256(
        program.code[main_call_frame["add_offset"]:main_call_frame["add_end_offset"]]
    ).hexdigest()
    assert main_call_frame["add_end_rva"] == main_instructions[main_call_frame["add_offset"]]["end_rva"]
    assert main_call_frame["add_va"] == metadata["image_base"] + main_call_frame["add_rva"]
    assert main_call_frame["add_end_va"] == main_instructions[main_call_frame["add_offset"]]["end_va"]
    assert main_call_frame["call_offset"] in main_instructions
    assert main_call_frame["add_offset"] in main_instructions
    assert main_instructions[main_call_frame["call_offset"]]["asm"].startswith("call ")
    assert main_instructions[main_call_frame["add_offset"]]["asm"].startswith("add rsp, ")
    main_exit_probe = functions["main"]["exit_probes"][0]
    assert main_exit_probe["call_rva"] == 4096 + main_exit_probe["call_offset"]
    assert main_exit_probe["call_end_offset"] == main_exit_probe["call_offset"] + len(encode_call_rel32(0))
    assert main_exit_probe["call_code_sha256"] == hashlib.sha256(
        program.code[main_exit_probe["call_offset"]:main_exit_probe["call_end_offset"]]
    ).hexdigest()
    assert main_exit_probe["call_end_rva"] == 4096 + main_exit_probe["call_end_offset"]
    assert main_exit_probe["call_va"] == metadata["image_base"] + main_exit_probe["call_rva"]
    assert main_exit_probe["call_end_va"] == metadata["image_base"] + main_exit_probe["call_end_rva"]
    assert main_exit_probe["test_rva"] == 4096 + main_exit_probe["test_offset"]
    assert main_exit_probe["test_end_offset"] == main_exit_probe["test_offset"] + len(encode_test_rdx_rdx())
    assert main_exit_probe["test_code_sha256"] == hashlib.sha256(
        program.code[main_exit_probe["test_offset"]:main_exit_probe["test_end_offset"]]
    ).hexdigest()
    assert main_exit_probe["test_end_rva"] == 4096 + main_exit_probe["test_end_offset"]
    assert main_exit_probe["test_va"] == metadata["image_base"] + main_exit_probe["test_rva"]
    assert main_exit_probe["test_end_va"] == metadata["image_base"] + main_exit_probe["test_end_rva"]
    assert main_exit_probe["jump_rva"] == 4096 + main_exit_probe["jump_offset"]
    assert main_exit_probe["jump_end_offset"] == main_exit_probe["jump_offset"] + len(encode_jne_rel32(0))
    assert main_exit_probe["jump_code_sha256"] == hashlib.sha256(
        program.code[main_exit_probe["jump_offset"]:main_exit_probe["jump_end_offset"]]
    ).hexdigest()
    assert main_exit_probe["jump_end_rva"] == 4096 + main_exit_probe["jump_end_offset"]
    assert main_exit_probe["jump_va"] == metadata["image_base"] + main_exit_probe["jump_rva"]
    assert main_exit_probe["jump_end_va"] == metadata["image_base"] + main_exit_probe["jump_end_rva"]
    assert main_exit_probe["call_end_offset"] == main_instructions[main_exit_probe["call_offset"]]["end_offset"]
    assert main_exit_probe["call_end_rva"] == main_instructions[main_exit_probe["call_offset"]]["end_rva"]
    assert main_exit_probe["call_end_va"] == main_instructions[main_exit_probe["call_offset"]]["end_va"]
    assert main_exit_probe["test_end_offset"] == main_instructions[main_exit_probe["test_offset"]]["end_offset"]
    assert main_exit_probe["test_end_rva"] == main_instructions[main_exit_probe["test_offset"]]["end_rva"]
    assert main_exit_probe["test_end_va"] == main_instructions[main_exit_probe["test_offset"]]["end_va"]
    assert main_exit_probe["jump_end_offset"] == main_instructions[main_exit_probe["jump_offset"]]["end_offset"]
    assert main_exit_probe["jump_end_rva"] == main_instructions[main_exit_probe["jump_offset"]]["end_rva"]
    assert main_exit_probe["jump_end_va"] == main_instructions[main_exit_probe["jump_offset"]]["end_va"]
    main_labels = {item["name"]: item for item in functions["main"]["labels"]}
    assert main_exit_probe["probe_label"] in main_labels
    assert main_labels[main_exit_probe["probe_label"]]["rva"] == 4096 + main_labels[main_exit_probe["probe_label"]]["offset"]
    assert main_labels[main_exit_probe["probe_label"]]["va"] == metadata["image_base"] + main_labels[main_exit_probe["probe_label"]]["rva"]
    assert "source_pc" in main_labels[main_exit_probe["probe_label"]]
    assert "source_line" in main_labels[main_exit_probe["probe_label"]]
    assert any(relocation["kind"] == "call_rel32" and relocation["target"] == "add2" for relocation in functions["main"]["relocations"])
    assert any(instruction["source_op"] == "call" for instruction in functions["main"]["instructions"])


def test_native_code_program_map_synthesizes_symbols_when_missing():
    main = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        0,
    )
    helper = NativeCodeFunction(
        "helper",
        b"\xC3",
        [NativeCodeInstruction(1, b"\xC3", "ret", "ret")],
        0,
        offset=1,
        return_type="bool64",
        param_types=("int64",),
    )
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        main,
        {"main": main, "helper": helper},
        b"\xC3\xC3",
        0,
    )

    metadata = native_code_program_map(program)

    assert program.symbols == []
    assert metadata["symbols"] == [
        {
            "name": "main",
            "kind": "function",
            "offset": 0,
            "rva": 4096,
            "va": 0x140001000,
            "size": 1,
            "end_offset": 1,
            "end_rva": 4097,
            "end_va": 0x140001001,
            "code_sha256": hashlib.sha256(main.code).hexdigest(),
            "is_entry": True,
            "return_type": "int64",
            "param_types": [],
        },
        {
            "name": "helper",
            "kind": "function",
            "offset": 1,
            "rva": 4097,
            "va": 0x140001001,
            "size": 1,
            "end_offset": 2,
            "end_rva": 4098,
            "end_va": 0x140001002,
            "code_sha256": hashlib.sha256(helper.code).hexdigest(),
            "is_entry": False,
            "return_type": "bool64",
            "param_types": ["int64"],
        },
    ]
    validate_native_code_program_map(program, metadata)


def test_native_code_program_map_and_formatter_reject_symbol_table_shape():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
    )
    program.symbols = None

    with pytest.raises(NativeCodegenError) as exc_info:
        native_code_program_map(program)

    assert "native 机器码符号表必须是列表" in str(exc_info.value)

    program.symbols = ["bad"]

    with pytest.raises(NativeCodegenError) as exc_info:
        format_native_code_program(program)

    assert "native 机器码符号表第 0 项必须是 NativeSymbol" in str(exc_info.value)


def test_native_code_program_map_and_formatter_reject_unknown_symbol_function():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("missing", 0, 1)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        native_code_program_map(program)

    assert "native 机器码符号表引用未知函数: missing" in str(exc_info.value)

    with pytest.raises(NativeCodegenError) as exc_info:
        format_native_code_program(program)

    assert "native 机器码符号表引用未知函数: missing" in str(exc_info.value)


def test_native_code_program_map_records_global_frame_owner(tmp_path):
    source_path = tmp_path / "native_emit_map_global_frame_owner.vbc"
    source_path.write_text(
        "int a = 40;\n\n"
        "int read_global() {\n"
        "    return a + 2;\n"
        "}\n\n"
        "int main() {\n"
        "    return read_global();\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_frame_owner.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    validate_native_code_program_map(program, metadata)

    assert metadata["global_frame_owner"] == "<module>"


def test_native_code_program_map_validator_rejects_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_bad_map.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_bad_map.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["code_sha256"] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_program_map(program, metadata)

    assert "字段 code_sha256 不一致" in str(exc_info.value)


def test_native_code_program_map_validator_reports_symbol_field_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_symbol_field_bad_map.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_symbol_field_bad_map.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0], metadata["symbols"][1] = metadata["symbols"][1], metadata["symbols"][0]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_program_map(program, metadata)

    assert "字段 symbols 不一致" in str(exc_info.value)
    assert "symbols[0]" in str(exc_info.value)
    assert "字段 name 不一致" in str(exc_info.value)


def test_native_code_program_map_validator_reports_function_field_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_function_field_bad_map.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_function_field_bad_map.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["functions"][0], metadata["functions"][1] = metadata["functions"][1], metadata["functions"][0]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_program_map(program, metadata)

    assert "字段 functions 不一致" in str(exc_info.value)
    assert "functions[0]" in str(exc_info.value)
    assert "字段 name 不一致" in str(exc_info.value)


def test_native_code_program_map_validator_reports_nested_function_list_field_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_nested_function_field_bad_map.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_nested_function_field_bad_map.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = program.functions["main"]
    instruction = main.instructions[0]
    main.instructions[0] = NativeCodeInstruction(
        instruction.offset,
        instruction.code,
        instruction.asm,
        instruction.source_op,
        instruction.source_pc,
        instruction.source_line,
        {"program_map_probe": 1},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_program_map(program, metadata)

    message = str(exc_info.value)
    assert "字段 functions 不一致" in message
    assert "`main`" in message
    assert "字段 instructions" in message
    assert "字段 source_attrs" in message
    assert "program_map_probe" in message


def test_native_code_program_map_validator_reports_section_field_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_section_field_bad_map.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_section_field_bad_map.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"].append({"name": ".rdata", "offset": len(program.code), "size": 0, "entry_offset": 0, "sha256": ""})

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_program_map(program, metadata)

    assert "字段 sections 数量不一致: 期望 1, 实际 2" in str(exc_info.value)


def test_native_code_map_bytes_validator_accepts_raw_binary(tmp_path):
    source_path = tmp_path / "native_emit_map_bytes.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_bytes.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    validate_native_code_map_bytes(program.code, native_code_program_map(program))


def test_native_text_section_map_bytes_validator_accepts_padded_text_section(tmp_path):
    source_path = tmp_path / "native_emit_text_section_map_bytes.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_text_section_map_bytes.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    text_section = metadata["sections"][0]
    text_raw = program.code + bytes(text_section["raw_padding_size"])

    validate_native_text_section_map_bytes(text_raw, metadata)


def test_native_text_section_map_bytes_validator_rejects_bad_padding(tmp_path):
    source_path = tmp_path / "native_emit_text_section_map_bytes_bad_padding.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_text_section_map_bytes_bad_padding.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    text_section = metadata["sections"][0]
    assert text_section["raw_padding_size"] > 0
    text_raw = bytearray(program.code + bytes(text_section["raw_padding_size"]))
    text_raw[-1] = 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_text_section_map_bytes(bytes(text_raw), metadata)

    assert "尾部补零区域不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_extra_section(tmp_path):
    source_path = tmp_path / "native_emit_map_extra_section.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_extra_section.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"].append(
        {
            "name": ".rdata",
            "name_bytes": "2E 72 64 61 74 61 00 00",
            "offset": len(program.code),
            "size": 0,
            "end_offset": len(program.code),
            "virtual_size": 0,
            "raw_size_aligned": 0,
            "virtual_size_aligned": 0,
            "rva": 8192,
            "end_rva": 8192,
            "va": metadata["image_base"] + 8192,
            "end_va": metadata["image_base"] + 8192,
            "entry_offset": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
            "alignment": 16,
            "file_alignment": 512,
            "section_alignment": 4096,
            "permissions": ["read"],
            "characteristics": ["CNT_INITIALIZED_DATA", "MEM_READ"],
            "pe_characteristics": 0x40000040,
        }
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 sections 数量不一致: 期望 1, 实际 2" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_text_section_field(tmp_path):
    source_path = tmp_path / "native_emit_map_extra_text_section_field.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_extra_text_section_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["typo_raw_alignment"] = metadata["sections"][0]["raw_size_aligned"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section 存在未知字段: typo_raw_alignment" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_raw_code_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_raw_code_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_raw_code_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes("not bytes", native_code_program_map(program))

    assert "raw bytes 必须是 bytes" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_raw_binary_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_bytes_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_bytes_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code + b"\x90", native_code_program_map(program))

    assert "字段 code_size 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_size(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_size_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_size_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["size"] += 1
    metadata["sections"][0]["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section size 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_virtual_size(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_virtual_size_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_virtual_size_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["virtual_size"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section virtual_size 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_end_offset(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_end_offset_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_end_offset_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_aligned_sizes(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_aligned_sizes_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_aligned_sizes_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["raw_size_aligned"] += 512

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section raw_size_aligned 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["sections"][0]["virtual_size_aligned"] += 4096
    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section virtual_size_aligned 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_rva(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_rva_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_rva_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["rva"] = 8192

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section rva 必须为 4096" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_entry_rva(tmp_path):
    source_path = tmp_path / "native_emit_map_entry_rva_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_entry_rva_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["entry_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "入口 RVA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_image_base_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_image_base_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_image_base_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["image_base"] = "0x140000000"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 image_base 必须是整数" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["image_base"] = -1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 image_base 必须是非负整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_entry_va(tmp_path):
    source_path = tmp_path / "native_emit_map_entry_va_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_entry_va_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["entry_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "入口 VA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_end_rva(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_end_rva_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_end_rva_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["end_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section end_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_va(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_va_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_va_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_end_va(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_end_va_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_end_va_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["end_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section end_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_entry_offset(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_entry_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_entry_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["entry_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section entry_offset 与入口偏移不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_name_bytes(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_name_bytes_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_name_bytes_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["name_bytes"] = "2E 63 6F 64 65 00 00 00"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section name_bytes 必须" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_file_alignment(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_file_alignment_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_file_alignment_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["file_alignment"] = 256

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section file_alignment 必须为 512" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_section_alignment(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_section_alignment_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_section_alignment_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["section_alignment"] = 2048

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section section_alignment 必须为 4096" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_permissions(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_permissions_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_permissions_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["permissions"] = ["read", "write"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section permissions 必须" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_characteristics(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_characteristics_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_characteristics_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["characteristics"] = ["CNT_CODE", "MEM_READ"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section characteristics 必须" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_text_section_pe_characteristics(tmp_path):
    source_path = tmp_path / "native_emit_map_text_section_pe_characteristics_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_text_section_pe_characteristics_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["sections"][0]["pe_characteristics"] = 0x40000020

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section pe_characteristics 必须为 0x60000020" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_code_size_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_code_size_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_code_size_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["code_size"] = True

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 code_size 必须是整数" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["code_size"] = -1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 code_size 必须是非负整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_code_sha256_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_hash_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_hash_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["code_sha256"] = 7

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 code_sha256 必须是字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["code_sha256"] = "0" * 63

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 code_sha256 必须是 64 位十六进制字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["code_sha256"] = "g" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 code_sha256 不是合法十六进制" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_schema_version_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_schema_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_schema_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["schema_version"] = 2

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 schema_version 必须为 1" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_top_level_field(tmp_path):
    source_path = tmp_path / "native_emit_map_extra_top_level.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_extra_top_level.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["pe_typo_size_of_code"] = metadata["pe_size_of_code"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "存在未知顶层字段: pe_typo_size_of_code" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_missing_global_frame_owner_field(tmp_path):
    source_path = tmp_path / "native_emit_map_missing_global_owner.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_missing_global_owner.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    del metadata["global_frame_owner"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "缺少顶层字段 global_frame_owner" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_global_frame_owner_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_global_owner_mismatch.vbc"
    source_path.write_text(
        "int a = 40;\n\n"
        "int main() {\n"
        "    return a + 2;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_owner_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["global_frame_owner"] = "main"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 global_frame_owner 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_invalid_abi_metadata(tmp_path):
    source_path = tmp_path / "native_emit_map_bad_abi.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_bad_abi.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None

    metadata = native_code_program_map(program)
    metadata["abi"]["target"] = "linux-x64"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "abi.target 与 target 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["abi"]["typo_registers"] = []

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "abi 存在未知字段: typo_registers" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["abi"]["argument_registers"] = ["RCX", "rcx"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "abi.argument_registers 重复: rcx" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["abi"]["return_register"] = "RBX"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "abi.return_register 必须为 'RAX'" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_target_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_target_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_target_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["target"] = "linux-x64"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 target 必须为 'windows-x64'" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_pe_header_hint_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_pe_header_hint_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_pe_header_hint_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["pe_machine_value"] = 0x14C

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_machine_value 必须为 0x8664" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_optional_header_magic"] = "PE32"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_optional_header_magic 必须为 'PE32+'" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_subsystem_value"] = 2

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_subsystem_value 必须为 3" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_pe_header_layout_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_pe_header_layout_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_pe_header_layout_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None

    metadata = native_code_program_map(program)
    metadata["pe_optional_header_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_optional_header_offset 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_coff_header"]["NumberOfSections"] = 2

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "pe_coff_header.NumberOfSections 与 pe_number_of_sections 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_optional_header"]["ImageBase"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "pe_optional_header.ImageBase 与 image_base 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_file_layout"]["text_raw"]["offset"] += 1
    metadata["pe_file_layout"]["text_raw"]["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "pe_file_layout.text_raw.offset 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["sections"][0]["raw_padding_size"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section raw_padding_size 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["sections"][0]["raw_padded_sha256"] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section raw_padded_sha256 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["sections"][0]["pe_raw_pointer"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert ".text section pe_raw_pointer 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["sections"][0]["pe_section_header"]["PointerToRawData"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "pe_section_header.PointerToRawData 与 pe_raw_pointer 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["sections"][0]["pe_section_header"]["VirtualAddress"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "pe_section_header.VirtualAddress 与 rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_pe_optional_header_size_hint_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_pe_size_hint_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_pe_size_hint_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["pe_number_of_sections"] = 2

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_number_of_sections 必须为 1" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_file_alignment"] = 1024

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_file_alignment 必须为 512" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_section_alignment"] = 8192

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_section_alignment 必须为 4096" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_size_of_code"] += 512

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_size_of_code 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_size_of_initialized_data"] = 512

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_size_of_initialized_data 必须为 0" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_size_of_uninitialized_data"] = 512

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_size_of_uninitialized_data 必须为 0" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_base_of_code"] += 4096

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_base_of_code 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_address_of_entry_point"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_address_of_entry_point 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["pe_size_of_image"] += 4096

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "字段 pe_size_of_image 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_entry_offset_out_of_range(tmp_path):
    source_path = tmp_path / "native_emit_map_entry_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_entry_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["entry_offset"] = len(program.code)

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "入口偏移越界" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_function_range_out_of_range(tmp_path):
    source_path = tmp_path / "native_emit_map_function_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["functions"][0]["size"] = len(program.code) + 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 <module> 范围越界" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_overlapping_function_ranges(tmp_path):
    source_path = tmp_path / "native_emit_map_function_overlap.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_overlap.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["offset"] = metadata["functions"][0]["offset"]
    main["end_offset"] = main["offset"] + main["size"]
    main["rva"] = 4096 + main["offset"]
    main["end_rva"] = main["rva"] + main["size"]
    main["va"] = metadata["image_base"] + main["rva"]
    main["end_va"] = metadata["image_base"] + main["end_rva"]
    main["code_sha256"] = hashlib.sha256(program.code[main["offset"]:main["offset"] + main["size"]]).hexdigest()

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "范围与前序函数重叠" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_function_range_gap(tmp_path):
    source_path = tmp_path / "native_emit_map_function_gap.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_gap.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["offset"] += 1
    main["size"] -= 1
    main["rva"] = 4096 + main["offset"]
    main["end_rva"] = main["rva"] + main["size"]
    main["va"] = metadata["image_base"] + main["rva"]
    main["end_va"] = metadata["image_base"] + main["end_rva"]
    main["code_sha256"] = hashlib.sha256(program.code[main["offset"]:main["offset"] + main["size"]]).hexdigest()

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "范围前存在空洞" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_function_rva_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["rva"] = "4096"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_function_rva_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main RVA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_end_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_function_end_rva_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_end_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["end_rva"] = False

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main end_rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_end_offset_value(tmp_path):
    source_path = tmp_path / "native_emit_map_function_end_offset_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_end_offset_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_end_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_function_end_rva_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_end_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["end_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main end_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_function_va_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main VA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_end_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_function_end_va_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_end_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["end_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main end_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_function_field(tmp_path):
    source_path = tmp_path / "native_emit_map_function_extra_field.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["typo_frame_bytes"] = main["frame_size"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "functions[" in str(exc_info.value)
    assert "存在未知字段: typo_frame_bytes" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_register_allocation_field(tmp_path):
    source_path = tmp_path / "native_emit_map_register_allocation_extra_field.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_register_allocation_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["register_allocation"]["typo_register_policy"] = main["register_allocation"]["strategy"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main register_allocation 存在未知字段: typo_register_policy" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_register_allocation_argument_registers(tmp_path):
    source_path = tmp_path / "native_emit_map_register_allocation_args.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_register_allocation_args.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    add2 = next(item for item in metadata["functions"] if item["name"] == "add2")
    add2["register_allocation"]["argument_registers"] = ["RDX", "RCX"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 add2 register_allocation.argument_registers 与 ABI 前缀不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_stack_slot_field(tmp_path):
    source_path = tmp_path / "native_emit_map_stack_slot_extra_field.vbc"
    source_path.write_text("int main() {\n    int value = 42;\n    return value;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_stack_slot_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    assert main["stack_slots"]
    main["stack_slots"][0]["typo_slot_size"] = main["stack_slots"][0]["size"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main stack_slots[0] 存在未知字段: typo_slot_size" in str(exc_info.value)


def test_native_code_map_bytes_validator_requires_value_locations(tmp_path):
    source_path = tmp_path / "native_emit_map_value_locations_missing.vbc"
    source_path.write_text("int main() {\n    int value = 42;\n    return value;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_value_locations_missing.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    del main["value_locations"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main 缺少 value_locations 字段" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_value_locations_against_stack_slots(tmp_path):
    source_path = tmp_path / "native_emit_map_value_locations_mismatch.vbc"
    source_path.write_text("int main() {\n    int value = 42;\n    return value;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_value_locations_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    assert main["value_locations"]
    main["value_locations"][0]["base_register"] = "R11"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main value_locations[0] 与 stack_slots 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_code_sha256_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_function_hash_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_hash_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["code_sha256"] = 7

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main code_sha256 必须是字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["code_sha256"] = "0" * 63

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main code_sha256 必须是 64 位十六进制字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["code_sha256"] = "g" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main code_sha256 不是合法十六进制" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_function_code_sha256_value(tmp_path):
    source_path = tmp_path / "native_emit_map_function_hash_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_function_hash_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["code_sha256"] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main code_sha256 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_symbol_range_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["size"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> 范围与函数不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_offset_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_offset_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_offset_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["offset"] = False

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> offset 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_size_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_size_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_size_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["size"] = "1"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> size 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_rva_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["rva"] = "4096"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_rva_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> RVA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_end_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_end_rva_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_end_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["end_rva"] = False

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> end_rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_end_offset_value(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_end_offset_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_end_offset_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_end_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_end_rva_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_end_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["end_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> end_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_va_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> VA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_end_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_end_va_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_end_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["end_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> end_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_symbol_field(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_extra_field.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["typo_symbol_kind"] = metadata["symbols"][0]["kind"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "symbols[0] 存在未知字段: typo_symbol_kind" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_signature(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_signature.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_signature.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    symbol = next(item for item in metadata["symbols"] if item["name"] == "add2")
    symbol["return_type"] = "bool64"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 add2 return_type 与函数签名不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    symbol = next(item for item in metadata["symbols"] if item["name"] == "add2")
    symbol["param_types"] = ["int64"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 add2 param_types 与函数签名不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_code_sha256_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_hash_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_hash_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["code_sha256"] = 7

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> code_sha256 必须是字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["symbols"][0]["code_sha256"] = "0" * 63

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> code_sha256 必须是 64 位十六进制字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    metadata["symbols"][0]["code_sha256"] = "g" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> code_sha256 不是合法十六进制" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_symbol_code_sha256_value(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_hash_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_hash_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"][0]["code_sha256"] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号 <module> code_sha256 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_missing_function_symbol(tmp_path):
    source_path = tmp_path / "native_emit_map_symbol_missing.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_symbol_missing.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["symbols"] = [symbol for symbol in metadata["symbols"] if symbol["name"] != "add2"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "符号表缺少函数: add2" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_bytes(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    for function in metadata["functions"]:
        for instruction in function["instructions"]:
            if instruction["size"] > 0:
                instruction["bytes"] = " ".join("90" for _ in range(instruction["size"]))
                instruction["code_sha256"] = hashlib.sha256(bytes.fromhex(instruction["bytes"])).hexdigest()
                break
        else:
            continue
        break

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令字节与 raw bin 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_source_location(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_source_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_source_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["source_line"] = "3"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "source_line 必须是非负整数或 null" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_asm_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_asm_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_asm_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["asm"] = 7

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 asm 必须是字符串" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_source_op_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_source_op_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_source_op_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["source_op"] = ""

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 source_op 必须是非空字符串" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_source_attrs_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_source_attrs_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_source_attrs_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["source_attrs"] = []

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 source_attrs 必须是对象" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_source_attrs_key(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_source_attrs_key_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_source_attrs_key_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["source_attrs"] = {"": "bad"}

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 source_attrs key 必须是非空字符串" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_source_attrs_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_source_attrs_value_bad.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_source_attrs_value_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["source_attrs"] = {"target_type": []}

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 source_attrs.target_type 必须是字符串、整数、布尔值或 null" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_instruction_field(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_extra_field.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["typo_instruction_size"] = instruction["size"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "instructions[" in str(exc_info.value)
    assert "存在未知字段: typo_instruction_size" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_code_sha256_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_hash_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_hash_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["code_sha256"] = 7

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 code_sha256 必须是字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["code_sha256"] = "0" * 63

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 code_sha256 必须是 64 位十六进制字符串" in str(exc_info.value)

    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["code_sha256"] = "g" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 code_sha256 不是合法十六进制" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_code_sha256_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_hash_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_hash_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["code_sha256"] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 code_sha256 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_rva_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["rva"] = "4096"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_rva_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 RVA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_end_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_end_rva_shape.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_end_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["end_rva"] = False

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 end_rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_end_offset_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_end_offset_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_end_offset_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_end_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_end_rva_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_end_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["end_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 end_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_va_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 VA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_instruction_end_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_end_va_value.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_end_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    instruction = next(item for function in metadata["functions"] for item in function["instructions"])
    instruction["end_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令 end_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_overlapping_instruction_ranges(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_overlap.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_overlap.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    function = metadata["functions"][0]
    instruction = next(item for item in function["instructions"] if item["size"] > 0)
    function["instructions"].append(dict(instruction))

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令范围重叠" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_instruction_range_gap(tmp_path):
    source_path = tmp_path / "native_emit_map_instruction_gap.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_instruction_gap.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    function = metadata["functions"][0]
    first_nonempty = next(index for index, item in enumerate(function["instructions"]) if item["size"] > 0)
    del function["instructions"][first_nonempty]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "指令范围前存在空洞" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_relocation_field(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_extra_field.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["typo_patch_size"] = relocation["size"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "relocations[" in str(exc_info.value)
    assert "存在未知字段: typo_patch_size" in str(exc_info.value)


@pytest.mark.parametrize("field", ["instruction_code_sha256", "patch_code_sha256"])
def test_native_code_map_bytes_validator_requires_relocation_code_hash_fields(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_relocation_missing_{field}.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_relocation_missing_{field}.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation[field] = None

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"rel32 {field} 必须是字符串" in str(exc_info.value)


@pytest.mark.parametrize("field", ["instruction_code_sha256", "patch_code_sha256"])
def test_native_code_map_bytes_validator_checks_relocation_code_hashes(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_relocation_{field}_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_relocation_{field}_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation[field] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"rel32 {field} 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_rva_shape.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(function for function in metadata["functions"] if function["name"] == "main")
    relocation = next(item for item in main["relocations"] if item["kind"] == "call_rel32" and item["target"] == "add2")
    relocation["rva"] = "4096"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_rva_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 RVA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_patch_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_patch_rva_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_patch_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["patch_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 patch_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_patch_end_offset_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_patch_end_offset_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_patch_end_offset_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["patch_end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 patch_end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_target_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_target_rva_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_target_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["target_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 target_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_va_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 VA 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_patch_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_patch_va_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_patch_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["patch_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 patch_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_target_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_target_va_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_target_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"] if item["kind"] == "call_rel32")
    relocation["target_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 target_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_target_from_displacement(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_displacement_target_bad.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_displacement_target_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(function for function in metadata["functions"] if function["name"] == "main")
    relocation = next(item for item in main["relocations"] if item["kind"] == "call_rel32" and item["target"] == "add2")
    relocation["target"] = "main"
    relocation["target_rva"] = 4096 + program.functions["main"].offset
    relocation["target_va"] = metadata["image_base"] + relocation["target_rva"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 目标与位移不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_opcode(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_bad.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    for function in metadata["functions"]:
        call_relocation = next((item for item in function["relocations"] if item["kind"] == "call_rel32"), None)
        if call_relocation is not None:
            call_relocation["kind"] = "jmp_rel32"
            break

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "jmp_rel32 opcode 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_missing_relocation_record(tmp_path):
    source_path = tmp_path / "native_emit_map_missing_relocation.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_missing_relocation.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["relocations"] = [item for item in main["relocations"] if item["kind"] != "call_rel32"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 指令缺少修补记录" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_duplicate_relocation_record(tmp_path):
    source_path = tmp_path / "native_emit_map_duplicate_relocation.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_duplicate_relocation.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    relocation = next(item for item in main["relocations"] if item["kind"] == "call_rel32")
    main["relocations"].append(dict(relocation))

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 修补记录重复" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_source_location(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_source_bad.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_source_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"])
    del relocation["source_pc"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "source_pc 缺失" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_source_location_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_source_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation = next(item for function in metadata["functions"] for item in function["relocations"])
    relocation["source_line"] = (relocation["source_line"] or 0) + 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 来源位置与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_relocation_target_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_relocation_target_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int other(int a, int b) {\n"
        "    return a - b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_relocation_target_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    relocation = next(item for item in main["relocations"] if item["kind"] == "call_rel32" and item["target"] == "add2")
    instruction = next(item for item in main["instructions"] if item["offset"] == relocation["offset"])
    instruction["asm"] = instruction["asm"].replace("call add2", "call other", 1)
    main["call_frames"][0]["target"] = "other"
    main["exit_probes"][0]["target"] = "other"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "rel32 目标与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_size(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_bad.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    for function in metadata["functions"]:
        if function["call_frames"]:
            function["call_frames"][0]["aligned_size"] += 8
            break

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口大小不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_abi_consistency(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_abi_bad.vbc"
    source_path.write_text(
        "int pick5(int a, int b, int c, int d, int e) {\n"
        "    return a + e;\n"
        "}\n\n"
        "int main() {\n"
        "    return pick5(1, 2, 3, 4, 5);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_abi_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "pick5")
    frame["shadow_space_size"] += 8

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 shadow space 与 ABI 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "pick5")
    frame["stack_alignment"] = 32

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口对齐与 ABI 不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "pick5")
    frame["arg_count"] = 5
    frame["register_arg_count"] = 5
    frame["stack_arg_count"] = 0
    frame["stack_arg_bytes"] = 0

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口寄存器参数数量与 ABI 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_type_metadata(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_types_bad.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_types_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "add2")
    frame["arg_types"] = "int64"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 arg_types 必须是字符串列表" in str(exc_info.value)

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "add2")
    frame["arg_types"] = ["int64"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 arg_types 数量不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "add2")
    frame["param_types"] = []

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 param_types 数量不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "add2")
    frame["param_types"] = ["int64"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 param_types 数量不一致" in str(exc_info.value)

    metadata = native_code_program_map(program)
    target_function = next(item for item in metadata["functions"] if item["name"] == "add2")
    target_function["param_types"] = ["bool64", "int64"]
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "add2")
    frame["param_types"] = ["bool64", "int64"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口第 0 个参数类型不兼容" in str(exc_info.value)

    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"] if item["target"] == "add2")
    frame["param_types"] = ["bool64", "int64"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口形参类型与目标函数 add2 签名不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_call_frame_field(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_extra_field.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["typo_shadow_bytes"] = frame["shadow_space_size"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "call_frames[" in str(exc_info.value)
    assert "存在未知字段: typo_shadow_bytes" in str(exc_info.value)


@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
def test_native_code_map_bytes_validator_requires_structured_call_frame_address_fields(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_call_frame_missing_{field}.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_call_frame_missing_{field}.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame[field] = None

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"调用栈窗口 {field} 必须是整数" in str(exc_info.value)


@pytest.mark.parametrize("field", ["sub_code_sha256", "call_code_sha256", "add_code_sha256"])
def test_native_code_map_bytes_validator_requires_call_frame_code_hash_fields(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_call_frame_missing_{field}.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_call_frame_missing_{field}.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame[field] = None

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"调用栈窗口 {field} 必须是字符串" in str(exc_info.value)


@pytest.mark.parametrize("field", ["sub_code_sha256", "call_code_sha256", "add_code_sha256"])
def test_native_code_map_bytes_validator_checks_call_frame_code_hashes(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_call_frame_{field}_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_call_frame_{field}_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame[field] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"调用栈窗口 {field} 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_missing_call_frame_record(tmp_path):
    source_path = tmp_path / "native_emit_map_missing_call_frame.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_missing_call_frame.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"] = []

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口缺少记录" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_duplicate_call_frame_record(tmp_path):
    source_path = tmp_path / "native_emit_map_duplicate_call_frame.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_duplicate_call_frame.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"].append(dict(main["call_frames"][0]))

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口记录重复" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_source_location(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_source_bad.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_source_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["source_pc"] = True

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "source_pc 必须是非负整数或 null" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_rva_shape.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["rva"] = "4096"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_target_matches_call_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_target_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int other(int a, int b) {\n"
        "    return a - b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_target_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"][0]["target"] = "other"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口目标与 call 清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_source_location_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_source_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["source_line"] = (frame["source_line"] or 0) + 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口来源位置与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_call_source_location_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_call_source_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_call_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    probe = main["exit_probes"][0]
    new_line = (probe["source_line"] or 0) + 1
    probe["source_line"] = new_line
    for offset in (probe["call_offset"], probe["test_offset"], probe["jump_offset"]):
        instruction = next(item for item in main["instructions"] if item["offset"] == offset)
        instruction["source_line"] = new_line

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 call 来源位置与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_call_offset_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_call_offset_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_call_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"][0]["call_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 call_offset 与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_call_end_offset_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_call_end_offset_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_call_end_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"][0]["call_end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 call_end_offset 与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_add_source_location_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_add_source_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_add_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    frame = main["call_frames"][0]
    call_index = next(
        index
        for index, instruction in enumerate(main["instructions"])
        if instruction["offset"] > frame["offset"] and instruction["source_op"] == "call" and instruction["asm"].startswith("call ")
    )
    main["instructions"][call_index + 1]["source_line"] = (main["instructions"][call_index + 1]["source_line"] or 0) + 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 add rsp 来源位置与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_add_offset_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_add_offset_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_add_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"][0]["add_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 add_offset 与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_add_end_offset_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_add_end_offset_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_add_end_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["call_frames"][0]["add_end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 add_end_offset 与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_add_size_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_add_size_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_add_size_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    frame = main["call_frames"][0]
    call_index = next(
        index
        for index, instruction in enumerate(main["instructions"])
        if instruction["offset"] > frame["offset"] and instruction["source_op"] == "call" and instruction["asm"].startswith("call ")
    )
    main["instructions"][call_index + 1]["asm"] = f"add rsp, {frame['aligned_size'] + 16}"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 add rsp 清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_add_machine_size_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_add_machine_size_mismatch.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_add_machine_size_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    frame = main["call_frames"][0]
    call_index = next(
        index
        for index, instruction in enumerate(main["instructions"])
        if instruction["offset"] > frame["offset"] and instruction["source_op"] == "call" and instruction["asm"].startswith("call ")
    )
    add_instruction = main["instructions"][call_index + 1]
    bad_add_code = encode_add_rsp_imm32(frame["aligned_size"] + 16)
    raw_code = bytearray(program.code)
    raw_code[add_instruction["offset"]:add_instruction["offset"] + len(bad_add_code)] = bad_add_code
    raw_code = bytes(raw_code)
    add_instruction["bytes"] = bad_add_code.hex(" ").upper()
    add_instruction["code_sha256"] = hashlib.sha256(bad_add_code).hexdigest()
    metadata["code_sha256"] = hashlib.sha256(raw_code).hexdigest()
    metadata["sections"][0]["sha256"] = metadata["code_sha256"]
    metadata["sections"][0]["raw_padded_sha256"] = hashlib.sha256(
        raw_code + bytes(metadata["sections"][0]["raw_padding_size"])
    ).hexdigest()
    main["code_sha256"] = hashlib.sha256(raw_code[main["offset"]:main["end_offset"]]).hexdigest()
    symbol = next(item for item in metadata["symbols"] if item["name"] == "main")
    symbol["code_sha256"] = main["code_sha256"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(raw_code, metadata)

    assert "调用栈窗口 add rsp 大小不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_rva_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_va_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_call_frame_end_offset_value(tmp_path):
    source_path = tmp_path / "native_emit_map_call_frame_end_offset_value.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_call_frame_end_offset_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    frame = next(item for function in metadata["functions"] for item in function["call_frames"])
    frame["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "调用栈窗口 end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_flag_probe(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_bad.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    assert main["exit_probes"][0]["target"] == "stop"
    assert main["exit_probes"][0]["probe_label"].startswith("__propagate_exit_")
    for instruction in main["instructions"]:
        if instruction["asm"] == "test rdx, rdx ; native _exit flag":
            instruction["asm"] = "test rax, rax ; native _exit flag"
            break

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "call 后缺少 native _exit 标志检查" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_structured_exit_probe_offset(tmp_path):
    source_path = tmp_path / "native_emit_map_structured_exit_probe_bad.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_structured_exit_probe_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["test_offset"] += 1
    main["exit_probes"][0]["test_end_offset"] += 1
    main["exit_probes"][0]["test_rva"] += 1
    main["exit_probes"][0]["test_end_rva"] += 1
    main["exit_probes"][0]["test_va"] += 1
    main["exit_probes"][0]["test_end_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 test opcode 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_jump_relocation_target(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_jump_relocation_bad.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_jump_relocation_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    probe = main["exit_probes"][0]
    relocation = next(item for item in main["relocations"] if item["offset"] == probe["jump_offset"])
    relocation["target"] = "stop"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 jump 修补目标不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_call_relocation_target(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_call_relocation_bad.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_call_relocation_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    probe = main["exit_probes"][0]
    probe["target"] = "main"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 call 修补目标不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_exit_probe_field(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_extra_field.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["typo_probe_target"] = main["exit_probes"][0]["target"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "exit_probes[0] 存在未知字段: typo_probe_target" in str(exc_info.value)


@pytest.mark.parametrize("field", ["call_code_sha256", "test_code_sha256", "jump_code_sha256"])
def test_native_code_map_bytes_validator_requires_exit_probe_code_hash_fields(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_exit_probe_missing_{field}.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_exit_probe_missing_{field}.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0][field] = None

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"_exit 传播探针 {field} 必须是字符串" in str(exc_info.value)


@pytest.mark.parametrize("field", ["call_code_sha256", "test_code_sha256", "jump_code_sha256"])
def test_native_code_map_bytes_validator_checks_exit_probe_code_hashes(tmp_path, field):
    source_path = tmp_path / f"native_emit_map_exit_probe_{field}_mismatch.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / f"native_emit_map_exit_probe_{field}_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0][field] = "0" * 64

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert f"_exit 传播探针 {field} 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_rva_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_rva_shape.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_rva_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["call_rva"] = "4096"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 call_rva 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_rva_value.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["jump_rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 jump_rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_va_value.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["jump_va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 jump_va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_end_offset_value(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_end_offset_value.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_end_offset_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["jump_end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针 jump_end_offset 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_label_record_shape(tmp_path):
    source_path = tmp_path / "native_emit_map_label_shape.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_shape.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["labels"][0]["offset"] = "0"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "label" in str(exc_info.value)
    assert "offset 必须是整数" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_unknown_label_field(tmp_path):
    source_path = tmp_path / "native_emit_map_label_extra_field.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_extra_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    assert main["labels"]
    main["labels"][0]["typo_label_rva"] = main["labels"][0]["rva"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "函数 main labels[0] 存在未知字段: typo_label_rva" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_label_rva_value(tmp_path):
    source_path = tmp_path / "native_emit_map_label_rva_value.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_rva_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["labels"][0]["rva"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "label" in str(exc_info.value)
    assert "rva 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_label_va_value(tmp_path):
    source_path = tmp_path / "native_emit_map_label_va_value.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_va_value.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["labels"][0]["va"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "label" in str(exc_info.value)
    assert "va 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_label_source_location(tmp_path):
    source_path = tmp_path / "native_emit_map_label_source_bad.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_source_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["labels"][0]["source_line"] = "7"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "labels[0].source_line 必须是非负整数或 null" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_label_source_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_label_source_mismatch.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["labels"][0]["source_pc"] = None if main["labels"][0]["source_pc"] is not None else 0

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "来源位置与指令不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_requires_label_record_for_instruction_label(tmp_path):
    source_path = tmp_path / "native_emit_map_label_missing.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_label_missing.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["labels"] = []

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "labels 缺少指令标签" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_source_location(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_source_bad.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_source_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"][0]["source_line"] = -1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "source_line 必须是非负整数或 null" in str(exc_info.value)


def test_native_code_map_bytes_validator_checks_exit_probe_source_location_matches_instruction(tmp_path):
    source_path = tmp_path / "native_emit_map_exit_probe_source_mismatch.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_exit_probe_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    probe = main["exit_probes"][0]
    probe["source_line"] = (probe["source_line"] or 0) + 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "_exit 传播探针来源位置与清单不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_requires_exit_probe_field(tmp_path):
    source_path = tmp_path / "native_emit_map_missing_exit_probe_field.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_missing_exit_probe_field.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    del main["exit_probes"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "缺少 exit_probes 字段" in str(exc_info.value)


def test_native_code_map_bytes_validator_requires_exit_probe_record_for_call(tmp_path):
    source_path = tmp_path / "native_emit_map_missing_exit_probe_record.vbc"
    source_path.write_text(
        "void stop() {\n"
        "    _exit(7);\n"
        "}\n\n"
        "int main() {\n"
        "    stop();\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_missing_exit_probe_record.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    main["exit_probes"] = []

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "call 缺少 _exit 传播探针记录" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_duplicate_global_slot_offsets(tmp_path):
    source_path = tmp_path / "native_emit_map_global_slot_bad.vbc"
    source_path.write_text(
        "int a = 10;\n"
        "int b = 32;\n\n"
        "int sum_globals() {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return sum_globals();\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_slot_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    function = next(item for item in metadata["functions"] if item["name"] == "sum_globals")
    global_slots = [slot for slot in function["stack_slots"] if slot["name"].startswith("global[")]
    assert len(global_slots) == 2
    global_slots[1]["offset"] = global_slots[0]["offset"]

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "全局栈槽偏移重复" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_global_slot_without_owner(tmp_path):
    source_path = tmp_path / "native_emit_map_global_slot_without_owner.vbc"
    source_path.write_text(
        "int a = 40;\n\n"
        "int read_global() {\n"
        "    return a + 2;\n"
        "}\n\n"
        "int main() {\n"
        "    return read_global();\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_slot_without_owner.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    module = next(item for item in metadata["functions"] if item["name"] == "<module>")
    owner_init = next(item for item in module["instructions"] if item["asm"] == "mov r11, rbp ; global frame")
    owner_init["asm"] = "mov r11, rbp ; typo global frame"
    metadata["global_frame_owner"] = None
    module["register_allocation"]["global_frame_role"] = "borrowed"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "全局栈槽缺少 global-frame owner 声明: global[a]" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_global_frame_owner_opcode_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_global_frame_owner_opcode.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_frame_owner_opcode.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    main = next(item for item in metadata["functions"] if item["name"] == "<module>")
    prologue = next(item for item in main["instructions"] if item["source_op"] == "prologue")
    prologue["asm"] = "mov r11, rbp ; global frame"
    metadata["global_frame_owner"] = "<module>"

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "global-frame 初始化指令 bytes 不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_owner_global_slot_outside_frame(tmp_path):
    source_path = tmp_path / "native_emit_map_global_slot_owner_frame.vbc"
    source_path.write_text(
        "int a = 42;\n\n"
        "int main() {\n"
        "    return a;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_slot_owner_frame.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    module = next(item for item in metadata["functions"] if item["name"] == "<module>")
    module["frame_size"] = 0

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "栈槽超出栈帧" in str(exc_info.value)


def test_native_code_map_bytes_validator_rejects_global_slot_owner_layout_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_map_global_slot_owner_layout.vbc"
    source_path.write_text(
        "int a = 40;\n\n"
        "int read_global() {\n"
        "    return a + 2;\n"
        "}\n\n"
        "int main() {\n"
        "    return read_global();\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_global_slot_owner_layout.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    helper = next(item for item in metadata["functions"] if item["name"] == "read_global")
    helper_slot = next(slot for slot in helper["stack_slots"] if slot["name"] == "global[a]")
    helper_slot["offset"] += 8

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_code_map_bytes(program.code, metadata)

    assert "全局栈槽 global[a] 与 global-frame owner 布局不一致" in str(exc_info.value)


def test_native_code_map_bytes_validator_accepts_label_relocations(tmp_path):
    source_path = tmp_path / "native_emit_map_branch_relocation.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 1;\n"
        "    if (value) {\n"
        "        return 7;\n"
        "    }\n"
        "    return 3;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_branch_relocation.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    assert any(
        relocation["target"] not in {function["name"] for function in metadata["functions"]}
        for function in metadata["functions"]
        for relocation in function["relocations"]
    )
    validate_native_code_map_bytes(program.code, metadata)

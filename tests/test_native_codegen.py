import hashlib
import io
import json
import os
import subprocess
from dataclasses import replace
from unittest.mock import Mock

import pytest

import verbose_c.compiler.native.codegen as native_codegen_module
import verbose_c.compiler.native.runner as native_runner_module
from verbose_c.compiler.ir import lower_bytecode_unit_to_ir
from verbose_c.compiler.native import (
    MachineBlock,
    MachineFunction,
    MachineInstruction,
    MachineOperand,
    MachineProgram,
    MachineTerminator,
    NativeCallFrameAllocation,
    NativeCodeFunction,
    NativeCodeInstruction,
    NativeCodeProgram,
    NativeCodegenError,
    NativeExitProbe,
    NativeRelocation,
    NativeRegisterAllocation,
    NativeStackSlotAllocation,
    NativeSymbol,
    NativeTarget,
    StackSlot,
    VirtualRegister,
    format_native_code_program,
    generate_native_code,
    build_native_pe_image,
    lower_ir_program_to_machine,
    native_code_program_map,
    validate_native_pe_image_bytes,
    validate_native_code_map_bytes,
    validate_native_code_program_map,
    validate_native_text_section_map_bytes,
)
from verbose_c.compiler.native.abi import StackFrameLayout, WindowsX64ABI, WINDOWS_X64_ABI
from verbose_c.compiler.native.target import RegisterSet
from verbose_c.compiler.native.encoder import (
    ConditionCode,
    encode_add_rax_r10,
    encode_add_rdx_r10,
    encode_add_rsp_imm32,
    encode_call_rel32,
    encode_cmp_rax_r10,
    encode_cqo,
    encode_epilogue,
    encode_idiv_r10,
    encode_imul_rax_r10,
    encode_je_rel32,
    encode_jmp_rel32,
    encode_jns_rel32,
    encode_jne_rel32,
    encode_mov_rax_rdx,
    encode_mov_rax_from_rbp_positive_offset,
    encode_mov_rax_from_rbp_offset,
    encode_mov_rax_from_r11_offset,
    encode_mov_rax_imm64,
    encode_mov_r10_from_rbp_offset,
    encode_mov_r10_from_r11_offset,
    encode_mov_r10_imm64,
    encode_mov_rdx_imm64,
    encode_mov_reg_from_rax,
    encode_mov_rbp_offset_from_rax,
    encode_mov_rbp_offset_from_reg,
    encode_mov_r11_offset_from_rax,
    encode_mov_r11_rbp,
    encode_mov_rsp_offset_from_rax,
    encode_movzx_rax_al,
    encode_neg_rax,
    encode_prologue,
    encode_setcc_al,
    encode_sub_rsp_imm32,
    encode_sub_rax_r10,
    encode_test_rdx_rdx,
    encode_xor_rax_r10,
)
from verbose_c.compiler.native.runner import _run_code_in_memory, can_run_native_memory, run_native_bytes_in_memory, run_native_function_in_memory, run_native_program_in_memory
from verbose_c.compiler.opcode import Opcode
from verbose_c.engine.engine import run_bytecode_file, run_source_file
from verbose_c.engine.native_exporter import (
    NativeExportKind,
    NativeExportRequest,
    parse_native_export_kinds,
)
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_integer import VBCInteger


def _native_export_request(**outputs):
    """按测试指定路径构造统一 native 导出请求。"""
    kinds = {
        "listing": NativeExportKind.LISTING,
        "raw_binary": NativeExportKind.RAW_BINARY,
        "text_section": NativeExportKind.TEXT_SECTION,
        "pe_image": NativeExportKind.PE_IMAGE,
        "map": NativeExportKind.MAP,
    }
    return NativeExportRequest(outputs={kinds[name]: str(path) for name, path in outputs.items()})


def _machine_program(bytecode, constants=None, local_count=0):
    ir_function = lower_bytecode_unit_to_ir(
        name="main",
        bytecode=bytecode,
        constants=constants or [VBCInteger(42)],
        param_count=0,
        local_count=local_count,
        lineno_table=[(0, 3)],
    )
    ir_program = type("IRProgramStub", (), {"module": ir_function, "functions": {"main": ir_function}})()
    return lower_ir_program_to_machine(ir_program)


def test_x64_encoder_outputs_expected_bytes():
    assert encode_prologue(16) == bytes.fromhex("55 48 89 E5 48 81 EC 10 00 00 00")
    assert encode_epilogue() == bytes.fromhex("48 89 EC 5D C3")
    assert encode_mov_rax_imm64(42) == bytes.fromhex("48 B8 2A 00 00 00 00 00 00 00")
    assert encode_mov_r10_imm64(42) == bytes.fromhex("49 BA 2A 00 00 00 00 00 00 00")
    assert encode_mov_rdx_imm64(1) == bytes.fromhex("48 BA 01 00 00 00 00 00 00 00")
    assert encode_mov_r11_rbp() == bytes.fromhex("49 89 EB")
    assert encode_mov_rax_from_rbp_offset(8) == bytes.fromhex("48 8B 85 F8 FF FF FF")
    assert encode_mov_rax_from_r11_offset(8) == bytes.fromhex("49 8B 83 F8 FF FF FF")
    assert encode_mov_rax_from_rbp_positive_offset(48) == bytes.fromhex("48 8B 85 30 00 00 00")
    assert encode_mov_r10_from_rbp_offset(8) == bytes.fromhex("4C 8B 95 F8 FF FF FF")
    assert encode_mov_r10_from_r11_offset(8) == bytes.fromhex("4D 8B 93 F8 FF FF FF")
    assert encode_mov_rbp_offset_from_rax(8) == bytes.fromhex("48 89 85 F8 FF FF FF")
    assert encode_mov_r11_offset_from_rax(8) == bytes.fromhex("49 89 83 F8 FF FF FF")
    assert encode_mov_rbp_offset_from_reg(8, "RCX") == bytes.fromhex("48 89 8D F8 FF FF FF")
    assert encode_mov_rbp_offset_from_reg(8, "R8") == bytes.fromhex("4C 89 85 F8 FF FF FF")
    assert encode_mov_rbp_offset_from_reg(8, "R9") == bytes.fromhex("4C 89 8D F8 FF FF FF")
    assert encode_mov_rsp_offset_from_rax(32) == bytes.fromhex("48 89 84 24 20 00 00 00")
    assert encode_mov_reg_from_rax("RDX") == bytes.fromhex("48 89 C2")
    assert encode_mov_reg_from_rax("R8") == bytes.fromhex("49 89 C0")
    assert encode_mov_reg_from_rax("R9") == bytes.fromhex("49 89 C1")
    assert encode_add_rax_r10() == bytes.fromhex("4C 01 D0")
    assert encode_add_rdx_r10() == bytes.fromhex("4C 01 D2")
    assert encode_sub_rax_r10() == bytes.fromhex("4C 29 D0")
    assert encode_imul_rax_r10() == bytes.fromhex("49 0F AF C2")
    assert encode_neg_rax() == bytes.fromhex("48 F7 D8")
    assert encode_cqo() == bytes.fromhex("48 99")
    assert encode_idiv_r10() == bytes.fromhex("49 F7 FA")
    assert encode_mov_rax_rdx() == bytes.fromhex("48 89 D0")
    assert encode_xor_rax_r10() == bytes.fromhex("4C 31 D0")
    assert encode_cmp_rax_r10() == bytes.fromhex("4C 39 D0")
    assert encode_test_rdx_rdx() == bytes.fromhex("48 85 D2")
    assert encode_setcc_al(ConditionCode.GT) == bytes.fromhex("0F 9F C0")
    assert encode_movzx_rax_al() == bytes.fromhex("48 0F B6 C0")
    assert encode_jmp_rel32(-5) == bytes.fromhex("E9 FB FF FF FF")
    assert encode_je_rel32(6) == bytes.fromhex("0F 84 06 00 00 00")
    assert encode_jne_rel32(6) == bytes.fromhex("0F 85 06 00 00 00")
    assert encode_jns_rel32(6) == bytes.fromhex("0F 89 06 00 00 00")
    assert encode_call_rel32(7) == bytes.fromhex("E8 07 00 00 00")
    assert encode_sub_rsp_imm32(32) == bytes.fromhex("48 81 EC 20 00 00 00")
    assert encode_add_rsp_imm32(32) == bytes.fromhex("48 81 C4 20 00 00 00")


def test_native_codegen_generates_code_listing_for_simple_return():
    program = generate_native_code(_machine_program([(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)]))

    assert program.entry.code
    assert program.entry.instructions[0].offset == 0
    assert any(item.asm == "mov rax, 42" for item in program.entry.instructions)
    assert program.entry.instructions[-1].asm == "mov rsp, rbp; pop rbp; ret"


def test_native_codegen_rejects_unsupported_abi_word_size():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WindowsX64ABI(word_size=4),
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "native 机器码 MVP ABI word_size 必须为 8，实际 4" in str(exc_info.value)


def test_native_codegen_rejects_unsupported_abi_argument_register():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    registers = RegisterSet(
        argument_registers=("RSI",),
        return_register="RAX",
        frame_pointer="RBP",
        stack_pointer="RSP",
        caller_saved=(),
        callee_saved=(),
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WindowsX64ABI(registers=registers),
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "native 机器码 MVP ABI 参数寄存器暂不支持 RSI" in str(exc_info.value)


def test_native_codegen_rejects_duplicate_abi_argument_register():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    registers = RegisterSet(
        argument_registers=("RCX", "rcx"),
        return_register="RAX",
        frame_pointer="RBP",
        stack_pointer="RSP",
        caller_saved=(),
        callee_saved=(),
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WindowsX64ABI(registers=registers),
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "native 机器码 MVP ABI 参数寄存器重复: rcx" in str(exc_info.value)


def test_native_codegen_rejects_non_integer_abi_shadow_space():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WindowsX64ABI(shadow_space_size="32"),
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "native 机器码 MVP ABI shadow space 必须是整数，实际 str" in str(exc_info.value)


def test_native_codegen_supports_integer_locals_and_arithmetic():
    program = generate_native_code(
        _machine_program(
            [
                (Opcode.LOAD_CONSTANT, 0),
                (Opcode.STORE_LOCAL_VAR, 0),
                (Opcode.LOAD_CONSTANT, 1),
                (Opcode.STORE_LOCAL_VAR, 1),
                (Opcode.LOAD_LOCAL_VAR, 0),
                (Opcode.LOAD_LOCAL_VAR, 1),
                (Opcode.ADD,),
                (Opcode.RETURN,),
            ],
            constants=[VBCInteger(40), VBCInteger(2)],
            local_count=2,
        )
    )
    listing = format_native_code_program(program)
    allocation = program.entry.register_allocation

    assert isinstance(allocation, NativeRegisterAllocation)
    assert allocation.strategy == "保守栈槽分配"
    assert allocation.temporary_registers == ("RAX", "R10")
    assert allocation.argument_registers == ()
    assert allocation.return_register == "RAX"
    assert allocation.frame_pointer == "RBP"
    assert allocation.stack_pointer == "RSP"
    assert allocation.virtual_register_storage == "全部写入栈槽"
    assert allocation.local_storage == "全部写入栈槽"
    assert allocation.global_frame_register is None
    assert allocation.global_frame_role == "none"
    assert "x64 机器码" in listing
    assert f"入口偏移: `{program.entry_offset:04X}`" in listing
    assert f"- 入口 RVA: `0x{4096 + program.entry_offset:08X}`" in listing
    assert f"- 入口 VA: `0x{0x140000000 + 4096 + program.entry_offset:016X}`" in listing
    assert "- Global-frame owner: `-`" in listing
    assert f"- 程序 SHA-256: `{hashlib.sha256(program.code).hexdigest()}`" in listing
    assert "### PE/COFF 过渡摘要" in listing
    assert "| Machine | Machine 值 | OptionalHeader | OptionalHeader 值 | Subsystem | Subsystem 值 | Sections | e_lfanew | PE sig offset | COFF offset | Optional offset | Section table | SizeOfHeaders | Image base | BaseOfCode | AddressOfEntryPoint | SizeOfCode | SizeOfImage | Initialized data | Uninitialized data | File alignment | Section alignment |" in listing
    expected_raw_size = ((len(program.code) + 511) // 512) * 512
    expected_virtual_size = ((len(program.code) + 4095) // 4096) * 4096
    expected_pe_row = (
        f"| `AMD64` | `0x8664` | `PE32+` | `0x020B` | `console` | `3` | `1` | "
        f"`0x00000080` | `0x00000080` | `0x00000084` | `0x00000098` | `0x00000188` | `512` | "
        f"`0x0000000140000000` | `0x00001000` | `0x{4096 + program.entry_offset:08X}` | "
        f"`{expected_raw_size}` | `{4096 + expected_virtual_size}` | `0` | `0` | `512` | `4096` |"
    )
    assert expected_pe_row in listing
    assert "### PE 文件布局" in listing
    assert "| 段 | Offset | Size | End offset | 说明 |" in listing
    expected_raw_padding = expected_raw_size - len(program.code)
    expected_raw_padded_sha256 = hashlib.sha256(program.code + bytes(expected_raw_padding)).hexdigest()
    expected_file_layout_rows = [
        "| `dos_header` | `0` | `64` | `64` | `MZ header` |",
        "| `dos_stub_padding` | `64` | `64` | `128` | `padding before PE signature` |",
        "| `pe_signature` | `128` | `4` | `132` | `PE signature` |",
        "| `coff_header` | `132` | `20` | `152` | `IMAGE_FILE_HEADER` |",
        "| `optional_header` | `152` | `240` | `392` | `IMAGE_OPTIONAL_HEADER64` |",
        "| `section_table` | `392` | `40` | `432` | `.text section header` |",
        "| `headers_padding` | `432` | `80` | `512` | `align headers to FileAlignment` |",
        f"| `text_raw` | `512` | `{expected_raw_size}` | `{512 + expected_raw_size}` | `.text raw data` |",
        f"| `file_size` | `0` | `{512 + expected_raw_size}` | `{512 + expected_raw_size}` | `headers + .text raw` |",
    ]
    for expected_file_layout_row in expected_file_layout_rows:
        assert expected_file_layout_row in listing
    assert "### .text 代码节" in listing
    assert "| 名称 | Name bytes | Raw offset | Raw size | End offset | PE raw pointer | PE raw end | Raw aligned | Raw padding | Raw padded SHA-256 | Virtual size | Virtual aligned | Code alignment | RVA | End RVA | VA | End VA | Entry offset | SHA-256 | File alignment | Section alignment | 权限 | Characteristics | PE Characteristics |" in listing
    expected_text_row = (
        f"| `.text` | `2E 74 65 78 74 00 00 00` | `0` | `{len(program.code)}` | `{len(program.code)}` | "
        f"`512` | `{512 + expected_raw_size}` | `{expected_raw_size}` | `{expected_raw_padding}` | `{expected_raw_padded_sha256}` | "
        f"`{len(program.code)}` | `{expected_virtual_size}` | `16` | "
        f"`0x00001000` | `0x{4096 + len(program.code):08X}` | `0x0000000140001000` | "
        f"`0x{0x140000000 + 4096 + len(program.code):016X}` | `{program.entry_offset:04X}` | "
        f"`{hashlib.sha256(program.code).hexdigest()}` | `512` | `4096` | `read, execute` | "
        "`CNT_CODE, MEM_EXECUTE, MEM_READ` | `0x60000020` |"
    )
    assert expected_text_row in listing
    assert "### ABI" in listing
    assert "- 名称: `windows-x64-msvc-mvp`" in listing
    assert "- ABI 目标: `windows-x64`" in listing
    assert "- Word size: `8` bytes" in listing
    assert "- 参数寄存器: `RCX, RDX, R8, R9`" in listing
    assert "- 返回寄存器: `RAX`" in listing
    assert "- 帧指针 / 栈指针: `RBP` / `RSP`" in listing
    assert "- Shadow space: `32` bytes" in listing
    assert "- 栈对齐: `16` bytes" in listing
    assert "- 支持值类型: `int64, bool64, void`" in listing
    assert "寄存器分配" in listing
    assert "保守栈槽分配" in listing
    assert "临时寄存器: `RAX`, `R10`" in listing
    assert "虚拟寄存器保存: `全部写入栈槽`" in listing
    assert "栈槽分配" in listing
    assert "值位置摘要" in listing
    assert "| `%v0` | `vreg` | `0` | `stack` | `RBP` |" in listing
    assert "local[0]" in listing
    assert "%v0" in listing
    assert "add rax, r10" in listing
    assert "mov [rbp-" in listing


def test_native_codegen_supports_integer_division_and_modulo():
    program = generate_native_code(
        _machine_program(
            [
                (Opcode.LOAD_CONSTANT, 0),
                (Opcode.LOAD_CONSTANT, 1),
                (Opcode.DIVIDE,),
                (Opcode.STORE_LOCAL_VAR, 0),
                (Opcode.LOAD_CONSTANT, 2),
                (Opcode.LOAD_CONSTANT, 3),
                (Opcode.MODULO,),
                (Opcode.LOAD_LOCAL_VAR, 0),
                (Opcode.ADD,),
                (Opcode.RETURN,),
            ],
            constants=[VBCInteger(80), VBCInteger(2), VBCInteger(11), VBCInteger(2)],
            local_count=1,
        )
    )
    listing = format_native_code_program(program)

    assert "cqo" in listing
    assert "idiv r10" in listing
    assert "test rdx, rdx ; imod remainder" in listing
    assert "xor rax, r10 ; imod sign check" in listing
    assert "add rdx, r10 ; imod VM remainder" in listing
    assert "mov rax, rdx" in listing
    assert {item.kind for item in program.entry.relocations} == {"je_rel32", "jns_rel32"}


def test_native_codegen_supports_unary_neg_and_logical_not():
    neg_program = generate_native_code(_machine_program([(Opcode.LOAD_CONSTANT, 0), (Opcode.UNARY_MINUS,), (Opcode.RETURN,)], [VBCInteger(42)]))
    not_program = generate_native_code(_machine_program([(Opcode.LOAD_CONSTANT, 0), (Opcode.LOGICAL_NOT,), (Opcode.RETURN,)], [VBCInteger(0)]))

    assert "neg rax" in format_native_code_program(neg_program)
    assert "not_bool" in format_native_code_program(not_program)
    assert "seteq al" in format_native_code_program(not_program)


def test_native_codegen_supports_branch_code_listing():
    machine = _machine_program(
        [
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.JUMP_IF_FALSE, 4),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.RETURN,),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.RETURN,),
        ],
        constants=[VBCBool(True), VBCInteger(1), VBCInteger(0)],
    )
    program = generate_native_code(machine)
    listing = format_native_code_program(program)

    assert "bb_0:" in listing
    assert "jne bb_2" in listing
    assert "jmp bb_4" in listing
    assert "rel32=" in listing
    assert "#### 标签摘要" in listing
    assert "| 名称 | 偏移 | RVA | VA | 来源 |" in listing
    label_instructions = [
        instruction
        for instruction in program.entry.instructions
        if instruction.source_op == "label" and instruction.asm.endswith(":")
    ]
    assert {instruction.asm[:-1] for instruction in label_instructions} >= {"bb_0", "bb_2", "bb_4"}
    for instruction in label_instructions:
        label_rva = 4096 + instruction.offset
        label_va = 0x140000000 + label_rva
        expected_label_row = f"| `{instruction.asm[:-1]}` | `{instruction.offset:04X}` | `0x{label_rva:08X}` | `0x{label_va:016X}` | `-` |"
        assert expected_label_row in listing
    assert "#### rel32 修补记录" in listing
    assert {item.kind for item in program.entry.relocations} == {"jne_rel32", "jmp_rel32"}
    assert all(isinstance(item, NativeRelocation) for item in program.entry.relocations)
    assert all(item.size == 4 for item in program.entry.relocations)
    label_offsets = {instruction.asm[:-1]: instruction.offset for instruction in label_instructions}
    for relocation in program.entry.relocations:
        target_rva = 4096 + label_offsets[relocation.target]
        target_va = 0x140000000 + target_rva
        assert f"`{relocation.target}` | `0x{target_rva:08X}` | `0x{target_va:016X}` | `{relocation.displacement:+d}`" in listing


def test_native_codegen_supports_phi_edge_copies():
    machine = _machine_program(
        [
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.JUMP_IF_FALSE, 4),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.JUMP, 5),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.RETURN,),
        ],
        constants=[VBCBool(True), VBCInteger(7), VBCInteger(3)],
    )
    program = generate_native_code(machine)
    listing = format_native_code_program(program)

    assert "phi_copy" in listing
    assert "jmp bb_5" in listing


def test_native_codegen_reports_jump_rel32_overflow(monkeypatch):
    def fake_encode_jmp_rel32(displacement):
        if displacement:
            raise OverflowError("fake rel32 overflow")
        return encode_jmp_rel32(displacement)

    monkeypatch.setattr(native_codegen_module, "encode_jmp_rel32", fake_encode_jmp_rel32)
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["done"], source_pc=28, source_line=17),
            ),
            MachineBlock(
                name="pad",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(1)],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            ),
            MachineBlock(
                name="done",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "jmp rel32 位移超出范围" in message
    assert "Machine IR 指令 jmp" in message
    assert "行 17" in message
    assert "PC 28" in message


def test_native_codegen_supports_user_function_call(tmp_path):
    source_path = tmp_path / "native_codegen_call.vbc"
    source_path.write_text(
        "int add2(int a, int b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "int main() {\n"
        "    return add2(20, 22);\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    program = output.native_code_program
    listing = format_native_code_program(program)

    assert program is not None
    assert program.entry.name == "<module>"
    assert set(program.functions) == {"<module>", "add2", "main"}
    assert program.symbols == [
        NativeSymbol("<module>", program.functions["<module>"].offset, len(program.functions["<module>"].code), is_entry=True),
        NativeSymbol("add2", program.functions["add2"].offset, len(program.functions["add2"].code), param_types=("int64", "int64")),
        NativeSymbol("main", program.functions["main"].offset, len(program.functions["main"].code)),
    ]
    assert len(program.code) > len(program.functions["main"].code)
    assert "### 函数符号表" in listing
    assert "| 名称 | 类型 | 返回类型 | 形参类型 | 偏移 | End offset | RVA | VA | 大小 | End RVA | End VA | SHA-256 | 入口 |" in listing
    assert "| `<module>` | `function` | `int64` | `-` | `0000` |" in listing
    assert "| `yes` |" in listing
    for symbol in program.symbols:
        function = program.functions[symbol.name]
        symbol_rva = 4096 + symbol.offset
        symbol_end_offset = symbol.offset + symbol.size
        symbol_end_rva = symbol_rva + symbol.size
        symbol_va = 0x140000000 + symbol_rva
        symbol_end_va = 0x140000000 + symbol_end_rva
        symbol_hash = hashlib.sha256(function.code).hexdigest()
        symbol_params = ", ".join(symbol.param_types) if symbol.param_types else "-"
        expected_symbol_row = (
            f"| `{symbol.name}` | `{symbol.kind}` | `{symbol.return_type}` | `{symbol_params}` | "
            f"`{symbol.offset:04X}` | `{symbol_end_offset:04X}` | "
            f"`0x{symbol_rva:08X}` | `0x{symbol_va:016X}` | `{symbol.size}` | `0x{symbol_end_rva:08X}` | "
            f"`0x{symbol_end_va:016X}` | `{symbol_hash}` | `{'yes' if symbol.is_entry else 'no'}` |"
        )
        assert expected_symbol_row in listing
    for function in program.functions.values():
        expected_range = f"函数范围: `[{function.offset:04X}, {function.offset + len(function.code):04X})`"
        assert expected_range in listing
        function_rva = 4096 + function.offset
        function_end_rva = function_rva + len(function.code)
        function_va = 0x140000000 + function_rva
        function_end_va = 0x140000000 + function_end_rva
        assert f"函数 RVA 范围: `[0x{function_rva:08X}, 0x{function_end_rva:08X})`" in listing
        assert f"函数 VA 范围: `[0x{function_va:016X}, 0x{function_end_va:016X})`" in listing
    assert "call add2" in listing
    assert "call main" in listing
    assert "rel32=" in listing
    assert "#### rel32 修补记录" in listing
    assert (
        "| 指令偏移 | 指令 RVA | 指令 VA | 指令 SHA-256 | 字段偏移 | 字段结束 | 字段 RVA | 字段结束 RVA | "
        "字段 VA | 字段结束 VA | Patch SHA-256 | 类型 | 目标 | 目标 RVA | 目标 VA | 位移 | 字段大小 | 来源 |"
    ) in listing
    assert "| 偏移 | End offset | RVA | VA | End RVA | End VA | 字节 | SHA-256 | 伪汇编 | 来源 | 来源属性 |" in listing
    module_calls = [item for item in program.functions["<module>"].relocations if item.kind == "call_rel32"]
    main_calls = [item for item in program.functions["main"].relocations if item.kind == "call_rel32"]
    assert module_calls[0].target == "main"
    assert main_calls[0].target == "add2"
    main_call_rva = 4096 + main_calls[0].offset
    main_call_va = 0x140000000 + main_call_rva
    main_patch_rva = 4096 + main_calls[0].patch_offset
    main_patch_va = 0x140000000 + main_patch_rva
    main_patch_end_offset = main_calls[0].patch_offset + main_calls[0].size
    main_patch_end_rva = main_patch_rva + main_calls[0].size
    main_patch_end_va = main_patch_va + main_calls[0].size
    main_instruction_hash = hashlib.sha256(program.code[main_calls[0].offset:main_patch_end_offset]).hexdigest()
    main_patch_hash = hashlib.sha256(program.code[main_calls[0].patch_offset:main_patch_end_offset]).hexdigest()
    add2_target_rva = 4096 + program.functions["add2"].offset
    add2_target_va = 0x140000000 + add2_target_rva
    assert (
        f"| `{main_calls[0].offset:04X}` | `0x{main_call_rva:08X}` | `0x{main_call_va:016X}` | "
        f"`{main_instruction_hash}` | `{main_calls[0].patch_offset:04X}` | `{main_patch_end_offset:04X}` | "
        f"`0x{main_patch_rva:08X}` | `0x{main_patch_end_rva:08X}` | "
        f"`0x{main_patch_va:016X}` | `0x{main_patch_end_va:016X}` | `{main_patch_hash}` | "
        f"`call_rel32` | `add2` | `0x{add2_target_rva:08X}` | `0x{add2_target_va:016X}` | "
        f"`{main_calls[0].displacement:+d}` | `4` |"
    ) in listing
    first_instruction = program.functions["main"].instructions[0]
    first_instruction_end_offset = first_instruction.offset + len(first_instruction.code)
    first_instruction_rva = 4096 + first_instruction.offset
    first_instruction_va = 0x140000000 + first_instruction_rva
    first_instruction_end_rva = first_instruction_rva + len(first_instruction.code)
    first_instruction_end_va = 0x140000000 + first_instruction_end_rva
    first_instruction_hash = hashlib.sha256(first_instruction.code).hexdigest()
    assert (
        f"| `{first_instruction.offset:04X}` | `{first_instruction_end_offset:04X}` | "
        f"`0x{first_instruction_rva:08X}` | `0x{first_instruction_va:016X}` | "
        f"`0x{first_instruction_end_rva:08X}` | `0x{first_instruction_end_va:016X}` | "
    ) in listing
    assert f"`{first_instruction_hash}`" in listing
    assert all(item.patch_offset == item.offset + 1 for function in program.functions.values() for item in function.relocations if item.kind == "call_rel32")
    assert all(item.code != encode_call_rel32(0) for function in program.functions.values() for item in function.instructions if item.source_op == "call")
    assert "mov [rbp-" in listing
    assert "rcx" in listing
    assert "rdx" in listing


def test_native_codegen_reports_call_rel32_overflow(monkeypatch):
    def fake_encode_call_rel32(displacement):
        if displacement:
            raise OverflowError("fake rel32 overflow")
        return encode_call_rel32(displacement)

    monkeypatch.setattr(native_codegen_module, "encode_call_rel32", fake_encode_call_rel32)
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("helper")],
                        source_pc=29,
                        source_line=18,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    helper = MachineFunction(
        name="helper",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"helper": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call rel32 位移超出范围" in message
    assert "Machine IR 指令 call" in message
    assert "行 18" in message
    assert "PC 29" in message


def test_native_codegen_supports_stack_argument_call(tmp_path):
    source_path = tmp_path / "native_codegen_stack_arg.vbc"
    source_path.write_text(
        "int pick5(int a, int b, int c, int d, int e) {\n"
        "    return e + a;\n"
        "}\n\n"
        "int main() {\n"
        "    return pick5(1, 2, 3, 4, 41);\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    listing = format_native_code_program(output.native_code_program)

    assert "sub rsp, 48" in listing
    assert "mov [rsp+32], rax" in listing
    assert "mov rax, [rbp+48]" in listing
    assert "call pick5" in listing


def test_native_codegen_supports_multiple_stack_argument_call(tmp_path):
    source_path = tmp_path / "native_codegen_multi_stack_arg.vbc"
    source_path.write_text(
        "int pick6(int a, int b, int c, int d, int e, int f) {\n"
        "    return e + f + a;\n"
        "}\n\n"
        "int main() {\n"
        "    return pick6(1, 2, 3, 4, 20, 21);\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    listing = format_native_code_program(output.native_code_program)

    assert "call pick6" in listing
    assert "调用栈窗口" in listing
    assert (
        "| 偏移 | 结束偏移 | Sub SHA-256 | Call 偏移 | Call 结束 | Call SHA-256 | "
        "Add 偏移 | Add 结束 | Add SHA-256 | RVA | End RVA | VA | End VA | Call RVA 范围 | "
        "Call VA 范围 | Add RVA 范围 | Add VA 范围 | 目标 | 参数 | 实参类型 | 形参类型 | 寄存器参数 | 栈参数 | "
        "Shadow space | 栈实参字节 | 对齐后大小 | 对齐 |"
    ) in listing
    assert "sub rsp, 48" in listing
    assert "mov [rsp+32], rax" in listing
    assert "mov [rsp+40], rax" in listing
    assert "mov rax, [rbp+48]" in listing
    assert "mov rax, [rbp+56]" in listing
    module_call_frames = output.native_code_program.functions["<module>"].call_frames
    assert module_call_frames == [
        NativeCallFrameAllocation(
            offset=module_call_frames[0].offset,
            target="main",
            arg_count=0,
            register_arg_count=0,
            stack_arg_count=0,
            shadow_space_size=32,
            stack_arg_bytes=0,
            aligned_size=32,
            stack_alignment=16,
            source_pc=5,
            source_line=5,
            call_offset=module_call_frames[0].call_offset,
            call_end_offset=module_call_frames[0].call_end_offset,
            add_offset=module_call_frames[0].add_offset,
            add_end_offset=module_call_frames[0].add_end_offset,
            arg_types=(),
            param_types=(),
        )
    ]
    main_call_frames = output.native_code_program.functions["main"].call_frames
    assert main_call_frames == [
        NativeCallFrameAllocation(
            offset=main_call_frames[0].offset,
            target="pick6",
            arg_count=6,
            register_arg_count=4,
            stack_arg_count=2,
            shadow_space_size=32,
            stack_arg_bytes=16,
            aligned_size=48,
            stack_alignment=16,
            source_pc=7,
            source_line=6,
            call_offset=main_call_frames[0].call_offset,
            call_end_offset=main_call_frames[0].call_end_offset,
            add_offset=main_call_frames[0].add_offset,
            add_end_offset=main_call_frames[0].add_end_offset,
            arg_types=("int64", "int64", "int64", "int64", "int64", "int64"),
            param_types=("int64", "int64", "int64", "int64", "int64", "int64"),
        )
    ]
    assert "| `6` | `int64, int64, int64, int64, int64, int64` | `int64, int64, int64, int64, int64, int64` | `4` | `2` |" in listing
    main_frame_rva = 4096 + main_call_frames[0].offset
    main_frame_end_offset = main_call_frames[0].offset + len(encode_sub_rsp_imm32(main_call_frames[0].aligned_size))
    main_frame_end_rva = 4096 + main_frame_end_offset
    main_frame_va = 0x140000000 + main_frame_rva
    main_frame_end_va = 0x140000000 + main_frame_end_rva
    main_call_offset = main_call_frames[0].call_offset
    main_call_end_offset = main_call_frames[0].call_end_offset
    main_add_offset = main_call_frames[0].add_offset
    main_add_end_offset = main_call_frames[0].add_end_offset
    assert main_call_offset is not None
    assert main_call_end_offset is not None
    assert main_add_offset is not None
    assert main_add_end_offset is not None
    assert main_call_end_offset == main_add_offset
    assert main_add_end_offset == main_add_offset + len(encode_add_rsp_imm32(main_call_frames[0].aligned_size))
    main_call_rva = 4096 + main_call_offset
    main_call_end_rva = 4096 + main_call_end_offset
    main_add_rva = 4096 + main_add_offset
    main_add_end_rva = 4096 + main_add_end_offset
    main_call_va = 0x140000000 + main_call_rva
    main_call_end_va = 0x140000000 + main_call_end_rva
    main_add_va = 0x140000000 + main_add_rva
    main_add_end_va = 0x140000000 + main_add_end_rva
    native_program = output.native_code_program
    main_sub_code_sha256 = hashlib.sha256(
        native_program.code[main_call_frames[0].offset:main_frame_end_offset]
    ).hexdigest()
    main_call_code_sha256 = hashlib.sha256(
        native_program.code[main_call_offset:main_call_end_offset]
    ).hexdigest()
    main_add_code_sha256 = hashlib.sha256(
        native_program.code[main_add_offset:main_add_end_offset]
    ).hexdigest()
    assert (
        f"| `{main_call_frames[0].offset:04X}` | `{main_frame_end_offset:04X}` | "
        f"`{main_sub_code_sha256}` | `{main_call_offset:04X}` | `{main_call_end_offset:04X}` | "
        f"`{main_call_code_sha256}` | `{main_add_offset:04X}` | `{main_add_end_offset:04X}` | "
        f"`{main_add_code_sha256}` | "
        f"`0x{main_frame_rva:08X}` | `0x{main_frame_end_rva:08X}` | "
        f"`0x{main_frame_va:016X}` | `0x{main_frame_end_va:016X}` | "
        f"`0x{main_call_rva:08X}-0x{main_call_end_rva:08X}` | "
        f"`0x{main_call_va:016X}-0x{main_call_end_va:016X}` | "
        f"`0x{main_add_rva:08X}-0x{main_add_end_rva:08X}` | "
        f"`0x{main_add_va:016X}-0x{main_add_end_va:016X}` | "
        "`pick6 (pc 7, line 6)` | `6` | "
        "`int64, int64, int64, int64, int64, int64` | "
        "`int64, int64, int64, int64, int64, int64` | "
        "`4` | `2` | `32` | `16` | `48` | `16` |"
    ) in listing
    assert isinstance(output.native_code_program.functions["main"].stack_slots[0], NativeStackSlotAllocation)


def test_native_codegen_uses_abi_shadow_space_for_call():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("helper")],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    helper = MachineFunction(
        name="helper",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(42)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WindowsX64ABI(shadow_space_size=64),
        module=module,
        functions={"helper": helper},
    )

    native = generate_native_code(program)
    listing = format_native_code_program(native)
    metadata = native_code_program_map(native)

    assert "sub rsp, 64" in listing
    assert "add rsp, 64" in listing
    assert "- Shadow space: `64` bytes" in listing
    assert metadata["abi"]["shadow_space_size"] == 64
    validate_native_code_program_map(native, metadata)


def test_native_codegen_rejects_call_stack_window_outside_signed_int32():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("helper")],
                        source_pc=33,
                        source_line=18,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    helper = MachineFunction(
        name="helper",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WindowsX64ABI(shadow_space_size=2**31),
        module=module,
        functions={"helper": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call 栈窗口大小超出 signed int32 编码范围: 2147483648" in message
    assert "Machine IR 指令 call" in message
    assert "行 18" in message
    assert "PC 33" in message


def test_native_codegen_supports_top_level_stack_argument_call(tmp_path):
    source_path = tmp_path / "native_codegen_top_stack_arg.vbc"
    source_path.write_text(
        "int pick5(int a, int b, int c, int d, int e) {\n"
        "    return e + a;\n"
        "}\n\n"
        "_exit(pick5(1, 2, 3, 4, 41));\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    listing = format_native_code_program(output.native_code_program)

    assert "call pick5" in listing
    assert "sub rsp, 48" in listing
    assert "mov [rsp+32], rax" in listing
    assert "mov rax, [rbp+48]" in listing


def test_machine_dump_includes_native_code_for_supported_main(tmp_path):
    source_path = tmp_path / "native_codegen_dump.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    dump_path = tmp_path / "native_codegen_dump.md"
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "native_codegen_dump.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "Machine IR" in dump_text
    assert "x64 机器码" in dump_text
    assert "### ABI" in dump_text
    assert "- 参数寄存器: `RCX, RDX, R8, R9`" in dump_text
    assert "栈槽分配" in dump_text
    assert "mov rsp, rbp; pop rbp; ret" in dump_text


def test_machine_dump_recompiles_on_incremental_cache_hit(tmp_path):
    source_path = tmp_path / "native_codegen_cached_dump.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    output_path = tmp_path / "native_codegen_cached_dump.vbb"
    first_dump_path = tmp_path / "native_codegen_cached_dump_first.md"
    second_dump_path = tmp_path / "native_codegen_cached_dump_second.md"

    first = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(first_dump_path),
        output_path=str(output_path),
        execute=False,
        optimize_level=0,
    )
    second = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(second_dump_path),
        output_path=str(output_path),
        execute=False,
        optimize_level=0,
    )

    assert first.success
    assert second.success
    second_dump_text = second_dump_path.read_text(encoding="utf-8")
    assert "Machine IR" in second_dump_text
    assert "x64 机器码" in second_dump_text
    assert "mov rsp, rbp; pop rbp; ret" in second_dump_text


def test_machine_dump_keeps_machine_ir_when_native_codegen_fails(tmp_path):
    source_path = tmp_path / "native_codegen_dump_unsupported.vbc"
    source_path.write_text(
        "int main(int argc) {\n"
        "    return argc;\n"
        "}\n",
        encoding="utf-8",
    )
    dump_path = tmp_path / "native_codegen_dump_unsupported.md"
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "native_codegen_dump_unsupported.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "Machine IR" in dump_text
    assert "机器码生成跳过/失败原因" in dump_text
    assert "native 机器码 MVP 入口 main 暂不支持参数" in dump_text


def test_machine_dump_records_machine_lowering_failure(tmp_path):
    source_path = tmp_path / "native_codegen_dump_machine_unsupported.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    dump_path = tmp_path / "native_codegen_dump_machine_unsupported.md"
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "native_codegen_dump_machine_unsupported.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "IR" in dump_text
    assert "Machine IR 生成跳过/失败原因" in dump_text
    assert "native MVP 暂不支持特性 'array'" in dump_text


def test_native_codegen_uses_module_entry_for_source_program(tmp_path):
    source_path = tmp_path / "native_module_entry.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    program = output.native_code_program
    listing = format_native_code_program(program)

    assert program is not None
    assert program.entry.name == "<module>"
    assert program.entry_offset == program.functions["<module>"].offset
    assert "call main" in listing


def test_native_codegen_accepts_bool_main_return_type(tmp_path):
    source_path = tmp_path / "native_bool_main.vbc"
    source_path.write_text("bool main() {\n    return true;\n}\n", encoding="utf-8")
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)

    assert output.native_code_program is not None
    assert output.native_code_program.functions["main"].code


def test_run_source_file_can_execute_native_memory_bool_main(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_bool_main.vbc"
    source_path.write_text("bool main() {\n    return true;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_bool_main.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.exit_code == 1


def test_run_source_file_can_execute_native_memory_bool_main_with_local_read(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_bool_main_local.vbc"
    source_path.write_text("bool main() {\n    bool flag = true;\n    return flag;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_bool_main_local.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 1


def test_run_source_file_can_execute_native_memory_bool_main_with_global_read(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_bool_main_global.vbc"
    source_path.write_text(
        "int g = 41;\n"
        "int read_g() {\n"
        "    return g + 1;\n"
        "}\n\n"
        "bool main() {\n"
        "    return read_g() == 42;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_bool_main_global.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.exit_code == 1


def test_run_source_file_can_execute_native_memory_bool_parameter_return(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_bool_param.vbc"
    source_path.write_text(
        "bool identity(bool value) {\n"
        "    return value;\n"
        "}\n\n"
        "int main() {\n"
        "    if (identity(true)) {\n"
        "        return 42;\n"
        "    }\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_bool_param.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_native_codegen_rejects_unsupported_helper_return_type():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("helper")],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    helper = MachineFunction(
        name="helper",
        params=[],
        return_type="float64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"helper": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 helper 暂不支持返回类型 float64" in str(exc_info.value)


def test_native_codegen_rejects_unsupported_parameter_type():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    helper = MachineFunction(
        name="helper",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(42)]),
            )
        ],
        param_types=["Float(FLOAT)"],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"helper": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 helper 第 0 个参数暂不支持类型 Float(FLOAT)" in str(exc_info.value)


def test_native_codegen_rejects_parameter_type_count_mismatch():
    entry = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(42)]),
            )
        ],
    )
    helper = MachineFunction(
        name="helper",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(42)]),
            )
        ],
        param_types=["int64", "bool64"],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=entry,
        functions={"helper": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "参数类型数量不匹配: 标注 2, 参数 1" in str(exc_info.value)


def test_native_codegen_rejects_function_table_key_name_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    helper = MachineFunction(
        name="actual",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"alias": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数表键与函数名不一致: 键 alias, 函数 actual" in str(exc_info.value)


def test_native_codegen_rejects_distinct_module_function_table_entry():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    table_module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"<module>": table_module},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数表中的 <module> 必须与 program.module 指向同一函数" in str(exc_info.value)


def test_native_codegen_rejects_empty_function_name_in_table():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    helper = MachineFunction(
        name="",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"helper": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数表项 helper 的函数名不能为空" in str(exc_info.value)


def test_native_codegen_rejects_void_ret_with_value():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="void",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)], source_pc=7, source_line=3),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "void 函数 ret 不应携带返回值" in message
    assert "行 3" in message
    assert "PC 7" in message


def test_native_codegen_rejects_value_return_without_value():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[], source_pc=9, source_line=4),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "int64 函数 ret 必须携带 1 个返回值" in message
    assert "行 4" in message
    assert "PC 9" in message


def test_native_codegen_rejects_bool_return_with_int_value():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="bool64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)], source_pc=11, source_line=5),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "bool64 函数 ret 返回值类型不能是 int64" in message
    assert "行 5" in message
    assert "PC 11" in message


def test_native_codegen_allows_int_return_with_bool_value():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand("imm", 1, "bool64")]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    generated = generate_native_code(program)

    assert generated.code


def test_native_codegen_rejects_duplicate_block_names():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            ),
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 基本块名重复: entry" in str(exc_info.value)


def test_native_codegen_rejects_empty_block_name():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 基本块名称不能为空" in str(exc_info.value)


def test_native_codegen_rejects_missing_block_terminator_before_codegen():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=None,
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 需要基本块 entry 的终结指令" in str(exc_info.value)


def test_native_codegen_rejects_vreg_use_before_definition():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "add",
                        result=MachineOperand.vreg(VirtualRegister("v1")),
                        args=[MachineOperand.vreg(VirtualRegister("v0")), MachineOperand.imm(1)],
                        source_pc=10,
                        source_line=5,
                    ),
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(41)],
                        source_pc=11,
                        source_line=6,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v1"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "虚拟寄存器 %v0 在定义前被读取" in message
    assert "Machine IR 指令 add" in message
    assert "行 5" in message
    assert "PC 10" in message


def test_native_codegen_rejects_duplicate_vreg_definition():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(1)],
                        source_pc=12,
                        source_line=6,
                    ),
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(2)],
                        source_pc=13,
                        source_line=7,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "虚拟寄存器 %v0 被重复定义" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 7" in message
    assert "PC 13" in message


def test_native_codegen_rejects_vreg_operand_type_mismatch():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand("vreg", VirtualRegister("v0", "bool64"), "int64"),
                        args=[MachineOperand.imm(1)],
                        source_pc=14,
                        source_line=8,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0", "bool64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "虚拟寄存器 %v0 操作数类型 int64 与定义类型 bool64 不一致" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 8" in message
    assert "PC 14" in message


def test_native_codegen_rejects_unsupported_vreg_type():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0", "float64")),
                        args=[MachineOperand.imm(1)],
                        source_pc=15,
                        source_line=9,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0", "float64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "虚拟寄存器 %v0 类型暂不支持 float64" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 9" in message
    assert "PC 15" in message


def test_native_codegen_rejects_unsupported_immediate_operand_type():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand("imm", 1, "float64")],
                        source_pc=16,
                        source_line=10,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "imm 操作数类型暂不支持 float64" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 10" in message
    assert "PC 16" in message


def test_native_codegen_rejects_unsupported_slot_operand_type():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(local_slots=[StackSlot("local", 0)]),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "store_stack",
                        args=[MachineOperand("slot", StackSlot("local", 0), "float64"), MachineOperand.imm(1)],
                        source_pc=17,
                        source_line=11,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "slot 操作数类型暂不支持 float64" in message
    assert "Machine IR 指令 store_stack" in message
    assert "行 11" in message
    assert "PC 17" in message


def test_native_codegen_rejects_compare_result_type_mismatch():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "cmp_lt",
                        result=MachineOperand.vreg(VirtualRegister("v0", "int64")),
                        args=[MachineOperand.imm(1), MachineOperand.imm(2)],
                        source_pc=16,
                        source_line=10,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0", "int64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "指令 cmp_lt 结果类型必须是 bool64，实际 int64" in message
    assert "Machine IR 指令 cmp_lt" in message
    assert "行 10" in message
    assert "PC 16" in message


def test_native_codegen_rejects_arithmetic_result_type_mismatch():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "add",
                        result=MachineOperand.vreg(VirtualRegister("v0", "bool64")),
                        args=[MachineOperand.imm(1), MachineOperand.imm(2)],
                        source_pc=17,
                        source_line=11,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0", "bool64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "指令 add 结果类型必须是 int64，实际 bool64" in message
    assert "Machine IR 指令 add" in message
    assert "行 11" in message
    assert "PC 17" in message


def test_native_codegen_rejects_integer_cast_missing_target_type():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0", "int64")), args=[MachineOperand.imm(40)]),
                    MachineInstruction(
                        "cast_bool_int",
                        result=MachineOperand.vreg(VirtualRegister("v1", "int64")),
                        args=[MachineOperand.vreg(VirtualRegister("v0", "int64"))],
                        source_pc=18,
                        source_line=12,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v1", "int64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "cast_bool_int target_type 必须是非空字符串" in message
    assert "Machine IR 指令 cast_bool_int" in message
    assert "行 12" in message
    assert "PC 18" in message


def test_native_codegen_rejects_bool_cast_unsupported_target_type():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="bool64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0", "int64")), args=[MachineOperand.imm(1)]),
                    MachineInstruction(
                        "cast_int_bool",
                        result=MachineOperand.vreg(VirtualRegister("v1", "bool64")),
                        args=[MachineOperand.vreg(VirtualRegister("v0", "int64"))],
                        attrs={"target_type": "int"},
                        source_pc=19,
                        source_line=13,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v1", "bool64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "cast_int_bool target_type 暂不支持 int" in message
    assert "Machine IR 指令 cast_int_bool" in message
    assert "行 13" in message
    assert "PC 19" in message


def test_native_codegen_rejects_call_result_type_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0", "int64")),
                        args=[MachineOperand.symbol("flag")],
                        attrs={"argc": 0, "arg_locations": [], "return_register": "RAX", "callee_return_type": "bool64"},
                        source_pc=18,
                        source_line=12,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0", "int64"))]),
            )
        ],
    )
    flag = MachineFunction(
        name="flag",
        params=[],
        return_type="bool64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0", "bool64")), args=[MachineOperand.imm(1)]),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0", "bool64"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"flag": flag},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "bool64 调用 flag 结果类型必须是 bool64，实际 int64" in message
    assert "Machine IR 指令 call" in message
    assert "行 12" in message
    assert "PC 18" in message


def test_native_codegen_rejects_call_argument_type_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0", "int64")), args=[MachineOperand.imm(1)]),
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v1", "int64")),
                        args=[MachineOperand.symbol("needs_bool"), MachineOperand.vreg(VirtualRegister("v0", "int64"))],
                        attrs={"argc": 1, "arg_locations": [WINDOWS_X64_ABI.argument_location(0).__dict__], "return_register": "RAX", "callee_return_type": "int64"},
                        source_pc=21,
                        source_line=14,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v1", "int64"))]),
            )
        ],
    )
    needs_bool = MachineFunction(
        name="needs_bool",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(local_slots=[StackSlot("local", 0)]),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
        param_types=["bool64"],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"needs_bool": needs_bool},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "调用 needs_bool 第 0 个参数类型不匹配: 需要 bool64, 实际 int64" in message
    assert "Machine IR 指令 call" in message
    assert "行 14" in message
    assert "PC 21" in message


def test_native_codegen_allows_bool_argument_for_int_parameter():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0", "bool64")), args=[MachineOperand.imm(1)]),
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v1", "int64")),
                        args=[MachineOperand.symbol("needs_int"), MachineOperand.vreg(VirtualRegister("v0", "bool64"))],
                        attrs={"argc": 1, "arg_locations": [WINDOWS_X64_ABI.argument_location(0).__dict__], "return_register": "RAX", "callee_return_type": "int64"},
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v1", "int64"))]),
            )
        ],
    )
    needs_int = MachineFunction(
        name="needs_int",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(local_slots=[StackSlot("local", 0)]),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(2)]),
            )
        ],
        param_types=["int64"],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"needs_int": needs_int},
    )

    native_program = generate_native_code(program)

    assert native_program.functions["<module>"].call_frames[0].target == "needs_int"


def test_native_codegen_rejects_malformed_load_imm_argument_count():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[],
                        source_pc=18,
                        source_line=8,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "指令需要 1 个参数，实际 0 个" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 8" in message
    assert "PC 18" in message


def test_native_codegen_rejects_non_integer_immediate():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand("imm", "forty-two")],
                        source_pc=26,
                        source_line=15,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "立即数必须是整数，实际 str" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 15" in message
    assert "PC 26" in message


def test_native_codegen_rejects_immediate_outside_signed_int64():
    value = 2**63
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(value)],
                        source_pc=27,
                        source_line=16,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert f"立即数超出 signed int64 范围: {value}" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 16" in message
    assert "PC 27" in message


def test_native_codegen_rejects_immediate_zero_divisor():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "idiv",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(42), MachineOperand.imm(0)],
                        source_pc=31,
                        source_line=17,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 17" in message
    assert "PC 31" in message


def test_native_codegen_rejects_immediate_zero_modulo_divisor():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "imod",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(42), MachineOperand.imm(0)],
                        source_pc=32,
                        source_line=18,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "Machine IR 指令 imod" in message
    assert "行 18" in message
    assert "PC 32" in message


def test_native_codegen_rejects_source_literal_zero_divisor(tmp_path):
    source_path = tmp_path / "native_zero_divisor.vbc"
    source_path.write_text("int main() {\n    return 42 / 0;\n}\n", encoding="utf-8")
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeCodegenError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "函数 main" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 2" in message


def test_native_codegen_rejects_source_local_zero_divisor(tmp_path):
    source_path = tmp_path / "native_local_zero_divisor.vbc"
    source_path.write_text("int main() {\n    int z = 0;\n    return 42 / z;\n}\n", encoding="utf-8")
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeCodegenError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "函数 main" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 3" in message


def test_native_codegen_rejects_source_local_zero_modulo_divisor(tmp_path):
    source_path = tmp_path / "native_local_zero_modulo_divisor.vbc"
    source_path.write_text("int main() {\n    int z = 0;\n    return 42 % z;\n}\n", encoding="utf-8")
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeCodegenError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "函数 main" in message
    assert "Machine IR 指令 imod" in message
    assert "行 3" in message


def test_native_codegen_rejects_source_arithmetic_zero_divisor(tmp_path):
    source_path = tmp_path / "native_arithmetic_zero_divisor.vbc"
    source_path.write_text("int main() {\n    int z = 1 - 1;\n    return 42 / z;\n}\n", encoding="utf-8")
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeCodegenError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "函数 main" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 3" in message


def test_native_codegen_rejects_static_phi_zero_divisor():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("br", targets=["left", "right"], args=[MachineOperand.imm(1)]),
                successors=["left", "right"],
            ),
            MachineBlock(
                name="left",
                instructions=[MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0")), args=[MachineOperand.imm(0)])],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                predecessors=["entry"],
                successors=["merge"],
            ),
            MachineBlock(
                name="right",
                instructions=[MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v1")), args=[MachineOperand.imm(0)])],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                predecessors=["entry"],
                successors=["merge"],
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v2")),
                        args=[MachineOperand.vreg(VirtualRegister("v0")), MachineOperand.vreg(VirtualRegister("v1"))],
                        attrs={"incoming_blocks": ["left", "right"]},
                    ),
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v3")), args=[MachineOperand.imm(42)]),
                    MachineInstruction(
                        "idiv",
                        result=MachineOperand.vreg(VirtualRegister("v4")),
                        args=[MachineOperand.vreg(VirtualRegister("v3")), MachineOperand.vreg(VirtualRegister("v2"))],
                        source_pc=41,
                        source_line=25,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v4"))]),
                predecessors=["left", "right"],
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 25" in message
    assert "PC 41" in message


def test_native_codegen_rejects_source_cross_block_local_zero_divisor(tmp_path):
    source_path = tmp_path / "native_cross_block_local_zero_divisor.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int z = 0;\n"
        "    if (1) {\n"
        "        z = z;\n"
        "    }\n"
        "    return 42 / z;\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeCodegenError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "函数 main" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 6" in message


def test_native_codegen_rejects_handwritten_cross_block_zero_divisor_without_predecessor_metadata():
    slot = StackSlot("local", 0)
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(local_slots=[slot]),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0")), args=[MachineOperand.imm(0)]),
                    MachineInstruction("store_stack", args=[MachineOperand.slot(slot), MachineOperand.vreg(VirtualRegister("v0"))]),
                ],
                terminator=MachineTerminator("jmp", targets=["done"]),
            ),
            MachineBlock(
                name="done",
                instructions=[
                    MachineInstruction("load_stack", result=MachineOperand.vreg(VirtualRegister("v1")), args=[MachineOperand.slot(slot)]),
                    MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v2")), args=[MachineOperand.imm(42)]),
                    MachineInstruction(
                        "idiv",
                        result=MachineOperand.vreg(VirtualRegister("v3")),
                        args=[MachineOperand.vreg(VirtualRegister("v2")), MachineOperand.vreg(VirtualRegister("v1"))],
                        source_pc=42,
                        source_line=26,
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v3"))]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 26" in message
    assert "PC 42" in message


def test_native_codegen_rejects_source_cross_block_local_zero_modulo_divisor(tmp_path):
    source_path = tmp_path / "native_cross_block_local_zero_modulo_divisor.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int z = 0;\n"
        "    if (1) {\n"
        "        z = z;\n"
        "    }\n"
        "    return 42 % z;\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeCodegenError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    message = str(exc_info.value)
    assert "暂不生成除数为 0 的 idiv/imod 机器码" in message
    assert "函数 main" in message
    assert "Machine IR 指令 imod" in message
    assert "行 6" in message


def test_native_codegen_allows_cross_block_divisor_with_disagreeing_predecessors(tmp_path):
    source_path = tmp_path / "native_cross_block_divisor_unknown.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int z = 0;\n"
        "    if (1) {\n"
        "        z = 2;\n"
        "    }\n"
        "    return 42 / z;\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)

    assert output.native_code_error is None
    assert output.native_code_program is not None


def test_native_codegen_rejects_static_signed_division_overflow():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "idiv",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(-(2**63)), MachineOperand.imm(-1)],
                        source_pc=33,
                        source_line=19,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "signed int64 溢出" in message
    assert "Machine IR 指令 idiv" in message
    assert "行 19" in message
    assert "PC 33" in message


def test_native_codegen_rejects_static_signed_modulo_overflow():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "imod",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(-(2**63)), MachineOperand.imm(-1)],
                        source_pc=34,
                        source_line=20,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "signed int64 溢出" in message
    assert "Machine IR 指令 imod" in message
    assert "行 20" in message
    assert "PC 34" in message


@pytest.mark.parametrize(
    ("op", "args", "source_pc", "source_line"),
    [
        ("add", [MachineOperand.imm(2**63 - 1), MachineOperand.imm(1)], 35, 21),
        ("sub", [MachineOperand.imm(-(2**63)), MachineOperand.imm(1)], 36, 22),
        ("imul", [MachineOperand.imm(2**62), MachineOperand.imm(2)], 37, 23),
        ("neg", [MachineOperand.imm(-(2**63))], 38, 24),
    ],
)
def test_native_codegen_rejects_static_signed_arithmetic_overflow(op, args, source_pc, source_line):
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        op,
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=args,
                        source_pc=source_pc,
                        source_line=source_line,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "超出 signed int64 范围" in message
    assert f"Machine IR 指令 {op}" in message
    assert f"行 {source_line}" in message
    assert f"PC {source_pc}" in message


def test_native_codegen_rejects_non_converging_static_constant_analysis(monkeypatch):
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )
    counter = {"value": 0}

    def fake_walk_static_known_block(*args, **kwargs):
        counter["value"] += 1
        return {f"v{counter['value']}": counter["value"]}, {}

    monkeypatch.setattr(native_codegen_module, "_walk_static_known_block", fake_walk_static_known_block)

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "函数 <module>: native 机器码 MVP 静态常量分析未收敛" in message
    assert "已迭代" in message


def test_native_codegen_rejects_malformed_vreg_name():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("tmp")),
                        args=[MachineOperand.imm(1)],
                        source_pc=24,
                        source_line=13,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "虚拟寄存器名必须形如 %v0，实际 %tmp" in message
    assert "Machine IR 指令 load_imm" in message
    assert "行 13" in message
    assert "PC 24" in message


def test_native_codegen_rejects_non_word_stack_slot_size():
    bad_slot = StackSlot("local", 0, size=4)
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(local_slots=[bad_slot]),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(bad_slot)],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP local[0] 栈槽大小必须为 8 字节，实际 4" in str(exc_info.value)


def test_native_codegen_rejects_unsupported_stack_slot_kind():
    bad_slot = StackSlot("spill", 0)
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(bad_slot)],
                        source_pc=25,
                        source_line=14,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "栈槽类型暂不支持 spill" in message
    assert "Machine IR 指令 load_stack" in message
    assert "行 14" in message
    assert "PC 25" in message


def test_native_codegen_rejects_frame_size_outside_signed_int32(monkeypatch):
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )
    monkeypatch.setattr(native_codegen_module._NativeCodegenContext, "_build_frame_size", lambda self: 2**31)

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 栈帧大小超出 signed int32 编码范围: 2147483648" in str(exc_info.value)


def test_native_codegen_rejects_stack_slot_offset_outside_signed_int32(monkeypatch):
    result = MachineOperand.vreg(VirtualRegister("v0"))
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=result,
                        args=[MachineOperand.imm(0)],
                    )
                ],
                terminator=MachineTerminator("ret", args=[result]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )
    monkeypatch.setattr(native_codegen_module._NativeCodegenContext, "_build_slot_offsets", lambda self: {("temp", 0): 2**31})
    monkeypatch.setattr(native_codegen_module._NativeCodegenContext, "_build_frame_size", lambda self: 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 栈槽 temp[0] 偏移超出 signed int32 编码范围: 2147483648" in str(exc_info.value)


def test_native_codegen_rejects_phi_slot_result_operand():
    merge_slot = StackSlot("local", 0)
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(local_slots=[merge_slot]),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["merge"]),
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.slot(merge_slot),
                        args=[MachineOperand.imm(1)],
                        attrs={"incoming_blocks": ["entry"]},
                        source_pc=20,
                        source_line=9,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.slot(merge_slot)]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "指令结果操作数类型应为 vreg，实际 slot" in message
    assert "Machine IR 指令 phi" in message
    assert "行 9" in message
    assert "PC 20" in message


def test_native_codegen_rejects_jmp_with_argument():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["done"], args=[MachineOperand.imm(1)], source_pc=21, source_line=10),
            ),
            MachineBlock(
                name="done",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "jmp 不应携带参数" in message
    assert "Machine IR 指令 jmp" in message
    assert "行 10" in message
    assert "PC 21" in message


def test_native_codegen_rejects_ret_with_target():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", targets=["extra"], args=[MachineOperand.imm(0)], source_pc=22, source_line=11),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "ret 不应携带跳转目标" in message
    assert "Machine IR 指令 ret" in message
    assert "行 11" in message
    assert "PC 22" in message


def test_native_codegen_rejects_br_symbol_condition():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator(
                    "br",
                    targets=["yes", "no"],
                    args=[MachineOperand.symbol("flag")],
                    source_pc=23,
                    source_line=12,
                ),
            ),
            MachineBlock(
                name="yes",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            ),
            MachineBlock(
                name="no",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "第 0 个参数类型应为 imm / slot / vreg，实际 symbol" in message
    assert "Machine IR 指令 br" in message
    assert "行 12" in message
    assert "PC 23" in message


def test_native_codegen_rejects_exit_without_argument():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "exit",
                        args=[],
                        source_pc=12,
                        source_line=6,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "指令需要 1 个参数，实际 0 个" in message
    assert "Machine IR 指令 exit" in message
    assert "行 6" in message
    assert "PC 12" in message


def test_native_codegen_supports_helper_exit_instruction():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("stop")],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    helper = MachineFunction(
        name="stop",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "exit",
                        args=[MachineOperand.imm(7)],
                        source_pc=14,
                        source_line=8,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"stop": helper},
    )

    native_program = generate_native_code(program)
    listing = format_native_code_program(native_program)

    assert native_program.functions["stop"].instructions
    assert "mov rdx, 1 ; native _exit flag" in listing
    assert "test rdx, rdx ; native _exit flag" in listing
    assert "exit_propagate" in listing
    assert any(instruction.source_op == "exit_probe" for instruction in native_program.functions["<module>"].instructions)


def test_native_codegen_rejects_unknown_jump_target_with_location():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["missing"], source_pc=16, source_line=9),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "跳转到未知目标 missing" in message
    assert "Machine IR 指令 jmp" in message
    assert "行 9" in message
    assert "PC 16" in message


def test_native_codegen_rejects_phi_unknown_incoming_block():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["merge"]),
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(1)],
                        attrs={"incoming_blocks": ["missing"]},
                        source_pc=18,
                        source_line=10,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "phi 引用了未知前驱 missing" in message
    assert "Machine IR 指令 phi" in message
    assert "行 10" in message
    assert "PC 18" in message


def test_native_codegen_rejects_phi_non_predecessor_incoming_block():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["merge"]),
            ),
            MachineBlock(
                name="other",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.imm(1)],
                        attrs={"incoming_blocks": ["other"]},
                        source_pc=20,
                        source_line=11,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "phi 前驱 other 不会跳转到基本块 merge" in message
    assert "Machine IR 指令 phi" in message
    assert "行 11" in message
    assert "PC 20" in message


def test_native_codegen_rejects_phi_undefined_source_vreg():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("jmp", targets=["merge"]),
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.vreg(VirtualRegister("v9"))],
                        attrs={"incoming_blocks": ["entry"]},
                        source_pc=22,
                        source_line=12,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "phi 来源虚拟寄存器 %v9 未定义" in message
    assert "Machine IR 指令 phi" in message
    assert "行 12" in message
    assert "PC 22" in message


def test_native_codegen_rejects_phi_source_type_mismatch():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0", "int64")),
                        args=[MachineOperand.imm(1)],
                    ),
                ],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                successors=["merge"],
            ),
            MachineBlock(
                name="other",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v1", "bool64")),
                        args=[MachineOperand("imm", 1, "bool64")],
                    ),
                ],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                successors=["merge"],
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v2", "bool64")),
                        args=[
                            MachineOperand.vreg(VirtualRegister("v0", "int64")),
                            MachineOperand.vreg(VirtualRegister("v1", "bool64")),
                        ],
                        attrs={"incoming_blocks": ["entry", "other"]},
                        source_pc=88,
                        source_line=44,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v2", "bool64"))]),
                predecessors=["entry", "other"],
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "phi 结果类型 bool64 与第 0 个来源类型 int64 不一致" in message
    assert "Machine IR 指令 phi" in message
    assert "行 44" in message
    assert "PC 88" in message


def test_native_codegen_allows_bool_phi_source_into_int_result():
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v0", "bool64")),
                        args=[MachineOperand("imm", 1, "bool64")],
                    ),
                ],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                successors=["merge"],
            ),
            MachineBlock(
                name="other",
                instructions=[
                    MachineInstruction(
                        "load_imm",
                        result=MachineOperand.vreg(VirtualRegister("v1", "int64")),
                        args=[MachineOperand.imm(2)],
                    ),
                ],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                successors=["merge"],
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v2", "int64")),
                        args=[
                            MachineOperand.vreg(VirtualRegister("v0", "bool64")),
                            MachineOperand.vreg(VirtualRegister("v1", "int64")),
                        ],
                        attrs={"incoming_blocks": ["entry", "other"]},
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v2", "int64"))]),
                predecessors=["entry", "other"],
            ),
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    generated = generate_native_code(program)

    assert generated.code


def test_native_codegen_rejects_void_call_with_result():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("noop")],
                        source_pc=11,
                        source_line=5,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    noop = MachineFunction(
        name="noop",
        params=[],
        return_type="void",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"noop": noop},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "void 调用 noop 不应携带结果" in message
    assert "行 5" in message
    assert "PC 11" in message


def test_native_codegen_rejects_value_call_without_result():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        args=[MachineOperand.symbol("value")],
                        source_pc=13,
                        source_line=6,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    value = MachineFunction(
        name="value",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"value": value},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "int64 调用 value 必须携带结果" in message
    assert "行 6" in message
    assert "PC 13" in message


def test_native_codegen_rejects_call_return_type_metadata_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("value")],
                        attrs={"callee_return_type": "void"},
                        source_pc=14,
                        source_line=6,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    value = MachineFunction(
        name="value",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"value": value},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call callee_return_type 元数据不匹配: 标注 void, 实际 int64" in message
    assert "行 6" in message
    assert "PC 14" in message


def test_native_codegen_rejects_call_return_register_metadata_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("value")],
                        attrs={"return_register": "RDX"},
                        source_pc=25,
                        source_line=12,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    value = MachineFunction(
        name="value",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"value": value},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call return_register 元数据不匹配: 标注 RDX, 实际 RAX" in message
    assert "行 12" in message
    assert "PC 25" in message


def test_native_codegen_rejects_call_with_too_few_args():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("needs_one")],
                        source_pc=15,
                        source_line=7,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="needs_one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"needs_one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "调用 needs_one 参数数量不匹配: 需要 1, 实际 0" in message
    assert "行 7" in message
    assert "PC 15" in message


def test_native_codegen_rejects_call_with_too_many_args():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("takes_none"), MachineOperand.imm(1)],
                        source_pc=17,
                        source_line=8,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="takes_none",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"takes_none": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "调用 takes_none 参数数量不匹配: 需要 0, 实际 1" in message
    assert "行 8" in message
    assert "PC 17" in message


def test_native_codegen_rejects_call_argc_metadata_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("one"), MachineOperand.imm(1)],
                        attrs={"argc": 0},
                        source_pc=19,
                        source_line=9,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call argc 元数据不匹配: 标注 0, 实际 1" in message
    assert "行 9" in message
    assert "PC 19" in message


def test_native_codegen_rejects_call_argc_metadata_non_integer():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("one"), MachineOperand.imm(1)],
                        attrs={"argc": "one"},
                        source_pc=20,
                        source_line=10,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call argc 元数据必须是整数" in message
    assert "Machine IR 指令 call" in message
    assert "行 10" in message
    assert "PC 20" in message


def test_native_codegen_rejects_call_arg_locations_metadata_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("one"), MachineOperand.imm(1)],
                        attrs={"argc": 1, "arg_locations": []},
                        source_pc=21,
                        source_line=10,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call arg_locations 数量不匹配: 标注 0, 实际 1" in message
    assert "行 10" in message
    assert "PC 21" in message


def test_native_codegen_rejects_call_arg_locations_metadata_non_list():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("one"), MachineOperand.imm(1)],
                        attrs={"argc": 1, "arg_locations": {"kind": "register", "name": "RCX", "index": 0}},
                        source_pc=22,
                        source_line=11,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call arg_locations 元数据必须是列表" in message
    assert "Machine IR 指令 call" in message
    assert "行 11" in message
    assert "PC 22" in message


def test_native_codegen_rejects_call_arg_locations_metadata_missing_fields():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("one"), MachineOperand.imm(1)],
                        attrs={"argc": 1, "arg_locations": [{"kind": "register", "name": "RCX"}]},
                        source_pc=24,
                        source_line=12,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call arg_locations[0] 字段必须为 kind/name/index" in message
    assert "Machine IR 指令 call" in message
    assert "行 12" in message
    assert "PC 24" in message


def test_native_codegen_rejects_call_arg_locations_metadata_value_mismatch():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("one"), MachineOperand.imm(1)],
                        attrs={"argc": 1, "arg_locations": [WINDOWS_X64_ABI.argument_location(1).__dict__]},
                        source_pc=23,
                        source_line=11,
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="one",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"one": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "call arg_locations[0] 不符合 ABI" in message
    assert "需要 {'kind': 'register', 'name': 'RCX', 'index': 0}" in message
    assert "实际 {'kind': 'register', 'name': 'RDX', 'index': 1}" in message
    assert "行 11" in message
    assert "PC 23" in message


def test_native_codegen_rejects_malformed_function_param_location():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("bad_param"), MachineOperand.imm(1)],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    callee = MachineFunction(
        name="bad_param",
        params=[WINDOWS_X64_ABI.argument_location(1)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(1)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"bad_param": callee},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "函数 bad_param 第 0 个参数位置不符合 ABI" in message
    assert "需要 register:RCX:0" in message
    assert "实际 register:RDX:1" in message


def test_native_codegen_rejects_parameterized_module_entry():
    function = MachineFunction(
        name="<module>",
        params=[WINDOWS_X64_ABI.argument_location(0)],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "入口 <module> 暂不支持参数" in str(exc_info.value)


def test_native_codegen_supports_direct_entry_with_global_slots():
    frame = StackFrameLayout()
    frame.global_slots = [StackSlot("global", "g")]
    function = MachineFunction(
        name="main",
        params=[],
        return_type="int64",
        frame=frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "store_stack",
                        args=[MachineOperand.slot(frame.global_slots[0]), MachineOperand.imm(42)],
                    ),
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(frame.global_slots[0])],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"main": function},
    )

    native_program = generate_native_code(program)
    listing = format_native_code_program(native_program)

    assert native_program.entry.name == "main"
    assert native_program.entry.frame_size == 16
    assert "- Global-frame owner: `main`" in listing
    assert "mov r11, rbp ; global frame" in listing
    assert "全局帧寄存器: `R11` (当前函数初始化，`global[...]` 通过 `[r11-offset]` 访问)" in listing
    assert "| `global[g]` | `[r11-8]` |" in listing
    assert "mov [r11-8], rax" in listing
    assert "mov rax, [r11-8]" in listing


def test_native_codegen_rejects_direct_entry_calling_global_slot_function():
    main = MachineFunction(
        name="main",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("read_global")],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    helper_frame = StackFrameLayout()
    helper_frame.global_slots = [StackSlot("global", "g")]
    helper = MachineFunction(
        name="read_global",
        params=[],
        return_type="int64",
        frame=helper_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(helper_frame.global_slots[0])],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=main,
        functions={"main": main, "read_global": helper},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "入口 main 调用带全局槽的函数时需要声明全局槽" in message
    assert "初始化 R11 global frame" in message


def test_native_codegen_supports_direct_entry_shared_global_frame_call():
    main_frame = StackFrameLayout()
    main_frame.global_slots = [StackSlot("global", "g")]
    helper_frame = StackFrameLayout()
    helper_frame.global_slots = [StackSlot("global", "g")]
    main = MachineFunction(
        name="main",
        params=[],
        return_type="int64",
        frame=main_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "store_stack",
                        args=[MachineOperand.slot(main_frame.global_slots[0]), MachineOperand.imm(40)],
                    ),
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("read_global")],
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v0"))]),
            )
        ],
    )
    helper = MachineFunction(
        name="read_global",
        params=[],
        return_type="int64",
        frame=helper_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(helper_frame.global_slots[0])],
                    ),
                    MachineInstruction(
                        "add",
                        result=MachineOperand.vreg(VirtualRegister("v1")),
                        args=[MachineOperand.vreg(VirtualRegister("v0")), MachineOperand.imm(2)],
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v1"))]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=main,
        functions={"main": main, "read_global": helper},
    )

    native_program = generate_native_code(program)
    listing = format_native_code_program(native_program)

    assert native_program.entry.name == "main"
    assert "mov r11, rbp ; global frame" in listing
    assert "call read_global" in listing
    assert "mov [r11-8], rax" in listing
    assert "mov rax, [r11-8]" in listing
    if can_run_native_memory():
        assert run_native_program_in_memory(native_program) == 42


def test_native_codegen_rejects_missing_module_global_frame_for_callee_globals():
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("main")],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    main_frame = StackFrameLayout()
    main_frame.global_slots = [StackSlot("global", "g")]
    main = MachineFunction(
        name="main",
        params=[],
        return_type="int64",
        frame=main_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(main_frame.global_slots[0])],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"main": main},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "全局标量需要 <module> 栈帧声明全局槽" in message
    assert "初始化 R11 global frame" in message


def test_native_codegen_rejects_callee_global_slot_not_declared_by_module():
    module_frame = StackFrameLayout()
    module_frame.global_slots = [StackSlot("global", "g")]
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=module_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "call",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.symbol("main")],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    main_frame = StackFrameLayout()
    main_frame.global_slots = [StackSlot("global", "h")]
    main = MachineFunction(
        name="main",
        params=[],
        return_type="int64",
        frame=main_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[
                    MachineInstruction(
                        "load_stack",
                        result=MachineOperand.vreg(VirtualRegister("v0")),
                        args=[MachineOperand.slot(main_frame.global_slots[0])],
                    )
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={"main": main},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "函数 main 使用了 <module> 未声明的全局槽" in message
    assert "h" in message


def test_native_codegen_rejects_duplicate_global_slots():
    module_frame = StackFrameLayout()
    module_frame.global_slots = [StackSlot("global", "g"), StackSlot("global", "g")]
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=module_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "函数 <module>: native 机器码 MVP 栈槽重复声明: global[g]" in message


def test_native_codegen_rejects_duplicate_local_slots():
    module_frame = StackFrameLayout()
    module_frame.local_slots = [StackSlot("local", 0), StackSlot("local", 0)]
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=module_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 栈槽重复声明: local[0]" in str(exc_info.value)


def test_native_codegen_rejects_spill_slots_in_frame():
    module_frame = StackFrameLayout()
    module_frame.spill_slots = [StackSlot("spill", 0)]
    module = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=module_frame,
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)]),
            )
        ],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions={},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    assert "函数 <module>: native 机器码 MVP 暂不支持 spill 栈槽" in str(exc_info.value)


def test_native_codegen_error_includes_function_op_and_source_location():
    block = MachineBlock(
        name="entry",
        instructions=[
            MachineInstruction(
                "br_table",
                args=[MachineOperand.imm(1)],
                source_pc=34,
                source_line=12,
            )
        ],
        terminator=MachineTerminator("ret", args=[MachineOperand.imm(0)], source_pc=35, source_line=12),
    )
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[block],
    )
    program = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        generate_native_code(program)

    message = str(exc_info.value)
    assert "函数 <module>" in message
    assert "Machine IR 指令 br_table" in message
    assert "行 12" in message
    assert "PC 34" in message
    assert "暂不支持特性 'br_table'" in message


def test_native_codegen_rejects_array_runtime_objects(tmp_path):
    source_path = tmp_path / "native_unsupported_array.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.compiler.native import NativeLoweringError
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeLoweringError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    assert "IR 指令 alloc_array" in str(exc_info.value)
    assert "array" in str(exc_info.value)


def test_run_source_file_vm_ignores_native_codegen_failure_for_arrays(tmp_path):
    source_path = tmp_path / "native_unsupported_array_vm.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {40, 2};\n"
        "    return values[0] + values[1];\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_unsupported_array_vm.vbb"),
        execute=True,
        optimize_level=0,
    )

    assert result.success
    assert result.exit_code == 42
    assert result.compilation_output is not None
    assert result.compilation_output.machine_program is None
    assert result.compilation_output.machine_error is not None
    assert result.compilation_output.native_code_program is None
    assert "native MVP 暂不支持特性 'array'" in str(result.compilation_output.machine_error)


def test_native_codegen_rejects_pointer_runtime_objects(tmp_path):
    source_path = tmp_path / "native_unsupported_pointer.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 1;\n"
        "    int* ptr = &value;\n"
        "    return *ptr;\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.compiler.native import NativeLoweringError
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeLoweringError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    assert "IR 指令 address_of" in str(exc_info.value)
    assert "address_escape" in str(exc_info.value)


def test_native_codegen_rejects_struct_runtime_objects(tmp_path):
    source_path = tmp_path / "native_unsupported_struct.vbc"
    source_path.write_text(
        "struct Point {\n"
        "    int x;\n"
        "};\n\n"
        "int main() {\n"
        "    struct Point p;\n"
        "    p.x = 1;\n"
        "    return p.x;\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.compiler.native import NativeLoweringError
    from verbose_c.engine.engine import compile_module

    with pytest.raises(NativeLoweringError) as exc_info:
        compile_module(str(source_path), require_native_code=True)

    assert "IR 指令 alloc_struct" in str(exc_info.value)
    assert "struct" in str(exc_info.value)


def test_run_source_file_can_execute_native_memory_void_main(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_void_main.vbc"
    source_path.write_text("void main() {\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_void_main.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 0


def test_run_source_file_can_execute_native_memory_exit_builtin(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_exit.vbc"
    source_path.write_text(
        "int main() {\n"
        "    _exit(7);\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_exit.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 7


def test_run_source_file_can_execute_public_exit_alias_on_vm(tmp_path):
    source_path = tmp_path / "vm_public_exit_alias.vbc"
    source_path.write_text(
        "int main() {\n"
        "    exit(7);\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "vm_public_exit_alias.vbb"),
        execute=True,
        optimize_level=0,
    )

    assert result.success
    assert result.exit_code == 7


def test_run_source_file_can_lower_public_exit_alias_to_native(tmp_path, monkeypatch):
    source_path = tmp_path / "native_public_exit_alias.vbc"
    source_path.write_text(
        "int main() {\n"
        "    exit(7);\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("verbose_c.compiler.native.runner.run_native_program_in_memory", Mock(return_value=7))

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_public_exit_alias.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    listing = format_native_code_program(result.compilation_output.native_code_program)
    assert result.success
    assert result.exit_code == 7
    assert "mov rdx, 1 ; native _exit flag" in listing


def test_run_source_file_can_execute_native_memory_top_level_exit(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_exit.vbc"
    source_path.write_text("_exit(42);\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_exit.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_top_level_scalar_script(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_scalar.vbc"
    source_path.write_text(
        "int a = 40;\n"
        "int b = 2;\n"
        "_exit(a + b);\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_scalar.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_top_level_call_exit(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_call_exit.vbc"
    source_path.write_text(
        "int add(int a, int b) {\n"
        "    return a + b;\n"
        "}\n"
        "_exit(add(40, 2));\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_call_exit.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_top_level_stack_argument_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_stack_arg.vbc"
    source_path.write_text(
        "int pick5(int a, int b, int c, int d, int e) {\n"
        "    return e + a;\n"
        "}\n"
        "_exit(pick5(1, 2, 3, 4, 41));\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_stack_arg.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_top_level_normal_exit(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_normal.vbc"
    source_path.write_text(
        "int a = 40;\n"
        "int b = 2;\n"
        "a + b;\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_normal.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 0


def test_run_source_file_can_execute_native_memory_top_level_call_normal_exit(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_call_normal.vbc"
    source_path.write_text(
        "int add(int a, int b) {\n"
        "    return a + b;\n"
        "}\n"
        "int value = add(40, 2);\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_call_normal.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 0


def test_run_source_file_can_execute_native_memory_top_level_if_else(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_if.vbc"
    source_path.write_text(
        "int value = 2;\n"
        "int result = 0;\n"
        "if (value > 1) {\n"
        "    result = 40;\n"
        "} else {\n"
        "    result = 1;\n"
        "}\n"
        "_exit(result + 2);\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_if.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_top_level_loop_control(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_level_loop.vbc"
    source_path.write_text(
        "int total = 0;\n"
        "for (int i = 0; i < 6; i = i + 1) {\n"
        "    if (i == 2) {\n"
        "        continue;\n"
        "    }\n"
        "    if (i == 5) {\n"
        "        break;\n"
        "    }\n"
        "    total = total + i;\n"
        "}\n"
        "_exit(total);\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_level_loop.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 8


def test_machine_dump_includes_top_level_global_slots(tmp_path):
    source_path = tmp_path / "native_top_level_global_slots.vbc"
    source_path.write_text(
        "int a = 40;\n"
        "int b = 2;\n"
        "_exit(a + b);\n",
        encoding="utf-8",
    )
    dump_path = tmp_path / "native_top_level_global_slots.md"
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "native_top_level_global_slots.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "全局槽数量: `2`" in dump_text
    assert "global[a]" in dump_text
    assert "global[b]" in dump_text


def test_native_codegen_supports_function_reading_global_scalar(tmp_path):
    source_path = tmp_path / "native_function_read_global.vbc"
    source_path.write_text(
        "int g = 40;\n\n"
        "int add_global(int x) {\n"
        "    return g + x;\n"
        "}\n\n"
        "int main() {\n"
        "    return add_global(2);\n"
        "}\n",
        encoding="utf-8",
    )
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    listing = format_native_code_program(output.native_code_program)

    assert output.native_code_program.functions["add_global"].frame_size == 32
    assert "- Global-frame owner: `<module>`" in listing
    assert "mov r11, rbp ; global frame" in listing
    assert "全局帧寄存器: `R11` (当前函数初始化，当前函数内 `global[...]` 使用 `[rbp-offset]`，被调用户函数使用 `[r11-offset]`)" in listing
    assert "全局帧寄存器: `R11` (由 global-frame owner 初始化，`global[...]` 通过 `[r11-offset]` 访问)" in listing
    assert "global[g]" in listing
    assert "| `global[g]` | `[rbp-" in listing
    assert "| `global[g]` | `[r11-" in listing
    assert "| `local[0]` | `[rbp-8]`" in listing
    assert "mov rax, [r11-" in listing


def test_run_source_file_can_execute_native_memory_function_global_read(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_function_global_read.vbc"
    source_path.write_text(
        "int g = 40;\n\n"
        "int add_global(int x) {\n"
        "    return g + x;\n"
        "}\n\n"
        "int main() {\n"
        "    return add_global(2);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_function_global_read.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_native_codegen_assigns_distinct_offsets_for_multiple_function_globals(tmp_path):
    source_path = tmp_path / "native_function_two_globals.vbc"
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
        output_path=str(tmp_path / "native_function_two_globals.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    slots = {slot.name: slot.offset for slot in program.functions["sum_globals"].stack_slots}
    assert slots["global[a]"] == 8
    assert slots["global[b]"] == 16
    assert slots["%v0"] == 8


def test_run_source_file_can_execute_native_memory_function_multiple_global_read(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_function_multiple_global_read.vbc"
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
        output_path=str(tmp_path / "native_function_multiple_global_read.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_recursive_global_read(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_recursive_global_read.vbc"
    source_path.write_text(
        "int factor = 2;\n\n"
        "int scale(int n) {\n"
        "    if (n <= 0) {\n"
        "        return 0;\n"
        "    }\n"
        "    return factor + scale(n - 1);\n"
        "}\n\n"
        "int main() {\n"
        "    return scale(21);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_recursive_global_read.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_function_global_store(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_function_global_store.vbc"
    source_path.write_text(
        "int g = 1;\n\n"
        "void bump() {\n"
        "    g = g + 41;\n"
        "}\n\n"
        "int main() {\n"
        "    bump();\n"
        "    return g;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_function_global_store.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_function_global_bool(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_function_global_bool.vbc"
    source_path.write_text(
        "bool flag = false;\n\n"
        "void enable() {\n"
        "    flag = true;\n"
        "}\n\n"
        "bool enabled() {\n"
        "    return flag;\n"
        "}\n\n"
        "int main() {\n"
        "    enable();\n"
        "    if (enabled()) {\n"
        "        return 42;\n"
        "    }\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_function_global_bool.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_native_codegen_supports_nested_exit_builtin_propagation(tmp_path):
    source_path = tmp_path / "native_nested_exit.vbc"
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
    from verbose_c.engine.engine import compile_module

    output = compile_module(str(source_path), require_native_code=True)
    listing = format_native_code_program(output.native_code_program)

    assert output.native_code_program is not None
    assert "mov rdx, 1 ; native _exit flag" in listing
    assert "test rdx, rdx ; native _exit flag" in listing
    assert "exit_propagate" in listing
    assert "#### _exit 传播探针" in listing
    assert "Call 结束" in listing
    assert "Call SHA-256" in listing
    assert "Test SHA-256" in listing
    assert "Jump SHA-256" in listing
    assert "Jump End VA" in listing
    probes = output.native_code_program.functions["main"].exit_probes
    assert len(probes) == 1
    assert probes[0].target == "stop"
    assert probes[0].probe_label.startswith("__propagate_exit_")
    probe = probes[0]
    program_code = output.native_code_program.code
    assert hashlib.sha256(program_code[probe.call_offset:probe.call_offset + len(encode_call_rel32(0))]).hexdigest() in listing
    assert hashlib.sha256(program_code[probe.test_offset:probe.test_offset + len(encode_test_rdx_rdx())]).hexdigest() in listing
    assert hashlib.sha256(program_code[probe.jump_offset:probe.jump_offset + len(encode_jne_rel32(0))]).hexdigest() in listing
    assert any(instruction.source_op == "exit_probe" for instruction in output.native_code_program.functions["main"].instructions)


def test_run_source_file_can_execute_native_memory_nested_exit_builtin(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_nested_exit.vbc"
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
        output_path=str(tmp_path / "native_memory_nested_exit.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 7


def test_run_source_file_can_execute_native_memory_recursive_nested_exit_builtin(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_recursive_nested_exit.vbc"
    source_path.write_text(
        "int countdown(int n) {\n"
        "    if (n == 0) {\n"
        "        _exit(9);\n"
        "        return 0;\n"
        "    }\n"
        "    return countdown(n - 1) + 1;\n"
        "}\n\n"
        "int main() {\n"
        "    return countdown(3);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_recursive_nested_exit.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 9


def test_native_memory_runner_returns_int_value():
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    program = generate_native_code(_machine_program([(Opcode.LOAD_CONSTANT, 0), (Opcode.RETURN,)]))

    assert run_native_function_in_memory(program.entry) == 42


def test_native_memory_runner_rejects_empty_code_before_platform_check():
    function = NativeCodeFunction("main", b"", [], 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "非空机器码" in str(exc_info.value)


def test_native_memory_runner_rejects_function_code_shape_before_low_level_platform_check():
    function = NativeCodeFunction("main", "\xC3", [], 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "code 必须是 bytes" in str(exc_info.value)


def test_native_memory_runner_rejects_function_object_shape_before_low_level_platform_check():
    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(object())

    assert "NativeCodeFunction" in str(exc_info.value)


def test_native_memory_runner_rejects_function_instruction_listing_before_low_level_platform_check():
    instruction = NativeCodeInstruction(0, b"\x90", "nop", "prologue")
    function = NativeCodeFunction("main", b"\xC3", [instruction], 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "机器码清单字节与 function.code 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_function_argument_allocation_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [],
        0,
        register_allocation=NativeRegisterAllocation(argument_registers=("RCX",)),
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "必须是无参数函数" in str(exc_info.value)


def test_native_memory_runner_rejects_function_signature_before_low_level_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0, return_type="void")

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "return_type 暂不支持: 'void'" in str(exc_info.value)

    function = NativeCodeFunction("main", b"\xC3", [], 0, param_types=["int64"])

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "param_types 必须是字符串元组" in str(exc_info.value)

    function = NativeCodeFunction("main", b"\xC3", [], 0, param_types=("int64",))

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "必须是无参数函数" in str(exc_info.value)


def test_native_memory_runner_rejects_function_external_call_slice_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE8\x06\x00\x00\x00\xC3",
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "helper", 6)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "call_rel32 目标不在函数切片内" in str(exc_info.value)


def test_native_memory_runner_rejects_function_call_relocation_mismatch_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE8\x00\x00\x00\x00\xC3",
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "main", 1)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "call_rel32 位移与机器码不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_function_duplicate_relocation_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE8\x00\x00\x00\x00\xC3",
        [
            NativeCodeInstruction(0, b"\xE8\x00\x00\x00\x00", "call main ; rel32=+0", "call"),
            NativeCodeInstruction(5, b"\xC3", "ret", "ret"),
        ],
        0,
        relocations=[
            NativeRelocation(0, 1, "call_rel32", "main", 0),
            NativeRelocation(0, 1, "call_rel32", "main", 0),
        ],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "rel32 修补记录重复: 0" in str(exc_info.value)


def test_native_memory_runner_rejects_function_call_relocation_listing_target_mismatch_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE8\x00\x00\x00\x00\xC3",
        [
            NativeCodeInstruction(0, b"\xE8\x00\x00\x00\x00", "call helper ; rel32=+0", "call"),
            NativeCodeInstruction(5, b"\xC3", "ret", "ret"),
        ],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "main", 0)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "rel32 目标与清单不一致: 记录 main, 指令 helper" in str(exc_info.value)


def test_native_memory_runner_rejects_function_relocation_missing_listing_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE8\x00\x00\x00\x00\xC3",
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "main", 0)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "rel32 修补指令清单缺失: 0" in str(exc_info.value)


def test_native_memory_runner_rejects_function_jump_relocation_unknown_target_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE9\x00\x00\x00\x00\xC3",
        [
            NativeCodeInstruction(0, b"\xE9\x00\x00\x00\x00", "jmp done ; rel32=+0", "jmp"),
            NativeCodeInstruction(5, b"", "done:", "label"),
            NativeCodeInstruction(5, b"\xC3", "ret", "ret"),
        ],
        0,
        relocations=[NativeRelocation(0, 1, "jmp_rel32", "missing", 0)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "rel32 修补目标未知: missing" in str(exc_info.value)


def test_native_memory_runner_rejects_function_jump_relocation_opcode_mismatch_before_low_level_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xE8\x00\x00\x00\x00\xC3",
        [
            NativeCodeInstruction(0, b"\xE8\x00\x00\x00\x00", "jmp done ; rel32=+0", "jmp"),
            NativeCodeInstruction(5, b"", "done:", "label"),
            NativeCodeInstruction(5, b"\xC3", "ret", "ret"),
        ],
        0,
        relocations=[NativeRelocation(0, 1, "jmp_rel32", "done", 0)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "jmp_rel32 opcode 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_function_entry_offset_shape_before_low_level_platform_check():
    with pytest.raises(NativeCodegenError) as exc_info:
        _run_code_in_memory(b"\xC3", True)

    assert "入口偏移必须是整数" in str(exc_info.value)


def test_native_memory_runner_flushes_instruction_cache_before_call(monkeypatch):
    events = []
    kernel32 = type("Kernel32Mock", (), {})()
    kernel32.VirtualAlloc = Mock(return_value=0x1000)
    kernel32.VirtualFree = Mock(side_effect=lambda address, size, free_type: events.append("free") or True)
    kernel32.GetCurrentProcess = Mock(return_value=0x1234)
    kernel32.FlushInstructionCache = Mock(side_effect=lambda process, address, size: events.append("flush") or True)

    def fake_cfunctype(restype):
        def factory(address):
            def call():
                events.append("call")
                return 77

            return call

        return factory

    monkeypatch.setattr(native_runner_module, "can_run_native_memory", lambda: True)
    monkeypatch.setattr(native_runner_module.ctypes, "windll", type("WindllMock", (), {"kernel32": kernel32})(), raising=False)
    monkeypatch.setattr(native_runner_module.ctypes, "memmove", lambda address, code, size: events.append("memmove"))
    monkeypatch.setattr(native_runner_module.ctypes, "CFUNCTYPE", fake_cfunctype)

    assert native_runner_module._run_code_in_memory(b"\xC3", 0) == 77
    assert events == ["memmove", "flush", "call", "free"]
    kernel32.GetCurrentProcess.assert_called_once_with()
    kernel32.FlushInstructionCache.assert_called_once_with(0x1234, 0x1000, 1)


def test_native_memory_runner_reports_instruction_cache_flush_failure(monkeypatch):
    events = []
    kernel32 = type("Kernel32Mock", (), {})()
    kernel32.VirtualAlloc = Mock(return_value=0x1000)
    kernel32.VirtualFree = Mock(side_effect=lambda address, size, free_type: events.append("free") or True)
    kernel32.GetCurrentProcess = Mock(return_value=0x1234)
    kernel32.FlushInstructionCache = Mock(side_effect=lambda process, address, size: events.append("flush") or False)

    def fake_cfunctype(restype):
        def factory(address):
            def call():
                events.append("call")
                return 77

            return call

        return factory

    monkeypatch.setattr(native_runner_module, "can_run_native_memory", lambda: True)
    monkeypatch.setattr(native_runner_module.ctypes, "windll", type("WindllMock", (), {"kernel32": kernel32})(), raising=False)
    monkeypatch.setattr(native_runner_module.ctypes, "memmove", lambda address, code, size: events.append("memmove"))
    monkeypatch.setattr(native_runner_module.ctypes, "CFUNCTYPE", fake_cfunctype)

    with pytest.raises(NativeCodegenError) as exc_info:
        native_runner_module._run_code_in_memory(b"\xC3", 0)

    assert "FlushInstructionCache 刷新指令缓存失败" in str(exc_info.value)
    assert events == ["memmove", "flush", "free"]


def test_native_memory_runner_runs_raw_bytes_with_validated_map(tmp_path, monkeypatch):
    source_path = tmp_path / "native_raw_bytes_runner.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_raw_bytes_runner.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    raw_runner = Mock(return_value=77)
    monkeypatch.setattr(native_runner_module, "_run_code_in_memory", raw_runner)

    assert run_native_bytes_in_memory(program.code, metadata) == 77
    raw_runner.assert_called_once_with(program.code, program.entry_offset)


def test_native_memory_runner_rejects_raw_bytes_map_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_raw_bytes_runner_bad_map.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_raw_bytes_runner_bad_map.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["code_size"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_bytes_in_memory(program.code, metadata)

    assert "字段 code_size 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_raw_bytes_entry_offset_shape_after_map_validation(monkeypatch):
    monkeypatch.setattr(native_runner_module, "validate_native_code_map_bytes", Mock())

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_bytes_in_memory(b"\xC3", {"entry_offset": True})

    assert "native raw bin 内存执行 entry_offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_text_section_code_size_shape_after_map_validation(monkeypatch):
    monkeypatch.setattr(native_runner_module, "validate_native_text_section_map_bytes", Mock())

    with pytest.raises(NativeCodegenError) as exc_info:
        native_runner_module.run_native_text_section_bytes_in_memory(b"\xC3", {"code_size": True, "entry_offset": 0})

    assert "native .text 内存执行 code_size 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_text_section_code_size_range_after_map_validation(monkeypatch):
    monkeypatch.setattr(native_runner_module, "validate_native_text_section_map_bytes", Mock())

    with pytest.raises(NativeCodegenError) as exc_info:
        native_runner_module.run_native_text_section_bytes_in_memory(b"\xC3", {"code_size": 2, "entry_offset": 0})

    assert "native .text 内存执行 code_size 越界: 2, .text 长度 1" in str(exc_info.value)


def test_native_memory_runner_rejects_text_section_entry_offset_shape_after_map_validation(monkeypatch):
    monkeypatch.setattr(native_runner_module, "validate_native_text_section_map_bytes", Mock())

    with pytest.raises(NativeCodegenError) as exc_info:
        native_runner_module.run_native_text_section_bytes_in_memory(b"\xC3", {"code_size": 1, "entry_offset": True})

    assert "native .text 内存执行 entry_offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_program_target_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram("linux-x64", function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "暂不支持目标平台 linux-x64" in str(exc_info.value)


def test_native_memory_runner_rejects_missing_entry_function_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "入口函数不在函数表中: main" in str(exc_info.value)


def test_native_memory_runner_rejects_program_code_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, "\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "program.code 必须是 bytes" in str(exc_info.value)


def test_native_memory_runner_rejects_entry_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, "main", {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "entry 必须是 NativeCodeFunction" in str(exc_info.value)


def test_native_memory_runner_rejects_functions_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, [function], b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "functions 必须是函数表 dict" in str(exc_info.value)


def test_native_memory_runner_rejects_empty_entry_name_before_platform_check():
    function = NativeCodeFunction("", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "entry 函数名必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_entry_table_mismatch_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    table_function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": table_function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "入口函数表项与 entry 不一致: main" in str(exc_info.value)


def test_native_memory_runner_rejects_function_table_key_name_mismatch_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    helper = NativeCodeFunction("other", b"\xC3", [], 0, offset=1)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, "helper": helper}, b"\xC3\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数表 key 与函数名不一致: key helper, 函数 other" in str(exc_info.value)


def test_native_memory_runner_rejects_function_table_key_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, 1: function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数表 key 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_function_table_value_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, "helper": "helper"}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数表项 helper 必须是 NativeCodeFunction" in str(exc_info.value)


def test_native_memory_runner_rejects_function_table_empty_function_name_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    helper = NativeCodeFunction("", b"\xC3", [], 0, offset=1)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, "helper": helper}, b"\xC3\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数表项 helper 的函数名必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_entry_offset_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", True)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "entry_offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_entry_offset_mismatch_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0, offset=1)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\x90\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "入口偏移与函数偏移不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_negative_function_offset_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    helper = NativeCodeFunction("helper", b"\xC3", [], 0, offset=-1)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, "helper": helper}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数 helper offset 不能为负数" in str(exc_info.value)


def test_native_memory_runner_rejects_function_offset_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0, offset=False)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数 main offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_function_code_shape_before_platform_check():
    function = NativeCodeFunction("main", "\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "函数 main code 必须是 bytes" in str(exc_info.value)


def test_native_memory_runner_rejects_function_code_range_before_platform_check():
    function = NativeCodeFunction("main", b"\x90\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\x90", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码范围越界" in str(exc_info.value)


def test_native_memory_runner_rejects_function_code_slice_mismatch_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\x90", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码与 program.code 切片不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_overlapping_function_ranges_before_platform_check():
    function = NativeCodeFunction("main", b"\x90\xC3", [], 0)
    helper = NativeCodeFunction("helper", b"\xC3", [], 0, offset=1)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, "helper": helper}, b"\x90\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "范围与前序函数重叠" in str(exc_info.value)


def test_native_memory_runner_rejects_function_range_gap_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    helper = NativeCodeFunction("helper", b"\xC3", [], 0, offset=2)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function, "helper": helper}, b"\xC3\x90\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "范围前存在空洞" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_listing_offset_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(2, b"", "label:", "label")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单偏移越界" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_listing_offset_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction("0", b"\xC3", "ret", "ret")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单 offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_listing_bytes_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\x90", "ret", "ret")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单字节与 program.code 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_listing_code_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, "\xC3", "ret", "ret")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单 code 必须是 bytes" in str(exc_info.value)


def test_native_memory_runner_rejects_overlapping_instruction_listing_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\x90\xC3",
        [
            NativeCodeInstruction(0, b"\x90\xC3", "nop; ret", "test"),
            NativeCodeInstruction(1, b"\xC3", "ret", "ret"),
        ],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\x90\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单范围重叠" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_listing_gap_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\x90\xC3",
        [NativeCodeInstruction(1, b"\xC3", "ret", "ret")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\x90\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单范围前存在空洞" in str(exc_info.value)


def test_native_memory_runner_rejects_incomplete_instruction_listing_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\x90\xC3",
        [NativeCodeInstruction(0, b"\x90", "nop", "test")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\x90\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单范围未覆盖完整函数" in str(exc_info.value)


def test_native_memory_runner_rejects_bad_frame_size_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        8,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "frame_size 必须是非负 16 字节对齐整数" in str(exc_info.value)


def test_native_memory_runner_rejects_frame_size_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        False,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "frame_size 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_duplicate_stack_slot_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        16,
        stack_slots=[
            NativeStackSlotAllocation("local[x]", 8, 8),
            NativeStackSlotAllocation("local[x]", 16, 8),
        ],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "栈槽重复: local[x]" in str(exc_info.value)


def test_native_memory_runner_rejects_stack_slot_offset_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        16,
        stack_slots=[NativeStackSlotAllocation("local[x]", "8", 8)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "栈槽 local[x] offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_stack_slot_size_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        16,
        stack_slots=[NativeStackSlotAllocation("local[x]", 8, True)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "栈槽 local[x] size 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_stack_slot_outside_frame_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        16,
        stack_slots=[NativeStackSlotAllocation("local[x]", 24, 8)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "栈槽超出栈帧" in str(exc_info.value)


def test_native_memory_runner_rejects_owner_global_slot_outside_frame_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\x49\x89\xEB\xC3",
        [
            NativeCodeInstruction(0, b"\x49\x89\xEB", "mov r11, rbp ; global frame", "prologue"),
            NativeCodeInstruction(3, b"\xC3", "ret", "ret"),
        ],
        0,
        stack_slots=[NativeStackSlotAllocation("global[a]", 8, 8)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, function.code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "栈槽超出栈帧" in str(exc_info.value)


def test_native_memory_runner_rejects_global_frame_owner_opcode_mismatch_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\x90\x90\x90\xC3",
        [
            NativeCodeInstruction(0, b"\x90\x90\x90", "mov r11, rbp ; global frame", "prologue"),
            NativeCodeInstruction(3, b"\xC3", "ret", "ret"),
        ],
        16,
        stack_slots=[NativeStackSlotAllocation("global[a]", 8, 8)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, function.code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "global-frame 初始化指令 bytes 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_global_slot_without_owner_before_platform_check():
    function = NativeCodeFunction(
        "helper",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        0,
        stack_slots=[NativeStackSlotAllocation("global[a]", 8, 8)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"helper": function}, function.code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "全局栈槽缺少 global-frame owner 声明: global[a]" in str(exc_info.value)


def test_native_memory_runner_rejects_global_slot_owner_layout_mismatch_before_platform_check():
    owner = NativeCodeFunction(
        "main",
        b"\x49\x89\xEB\xC3",
        [
            NativeCodeInstruction(0, b"\x49\x89\xEB", "mov r11, rbp ; global frame", "prologue"),
            NativeCodeInstruction(3, b"\xC3", "ret", "ret"),
        ],
        16,
        stack_slots=[NativeStackSlotAllocation("global[a]", 8, 8)],
    )
    helper = NativeCodeFunction(
        "helper",
        b"\xC3",
        [NativeCodeInstruction(4, b"\xC3", "ret", "ret")],
        0,
        offset=4,
        stack_slots=[NativeStackSlotAllocation("global[a]", 16, 8)],
    )
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        owner,
        {"main": owner, "helper": helper},
        owner.code + helper.code,
        0,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "全局栈槽 global[a] 与 global-frame owner 布局不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_duplicate_global_slot_offset_before_platform_check():
    function = NativeCodeFunction(
        "helper",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        0,
        stack_slots=[
            NativeStackSlotAllocation("global[a]", 8, 8),
            NativeStackSlotAllocation("global[b]", 8, 8),
        ],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"helper": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "全局栈槽偏移重复: 8" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_source_location_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret", source_line=-1)],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单.source_line 必须是非负整数或 None" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_asm_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", 7, "ret")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单 asm 必须是字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_source_op_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "")],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单 source_op 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_source_attrs_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret", source_attrs=[])],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单 source_attrs 必须是对象" in str(exc_info.value)


def test_native_memory_runner_rejects_instruction_source_attrs_key_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret", source_attrs={"": "bad"})],
        0,
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "机器码清单 source_attrs key 必须是非空字符串" in str(exc_info.value)


def test_native_function_runner_rejects_instruction_source_attrs_value_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret", source_attrs={"target_type": []})],
        0,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_function_in_memory(function)

    assert "机器码清单 source_attrs.target_type 必须是字符串、整数、布尔值或 null" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_unknown_function_before_platform_check():
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
        run_native_program_in_memory(program)

    assert "符号表引用未知函数: missing" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_name_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("", 0, 1, is_entry=True)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 name 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_offset_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("main", True, 1, is_entry=True)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main offset 必须是整数" in str(exc_info.value)

    program.symbols = [NativeSymbol("main", -1, 1, is_entry=True)]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main offset 不能为负数" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_size_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("main", 0, False, is_entry=True)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main size 必须是整数" in str(exc_info.value)

    program.symbols = [NativeSymbol("main", 0, -1, is_entry=True)]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main size 不能为负数" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_entry_shape_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("main", 0, 1, is_entry="yes")],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main is_entry 必须是布尔值" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_offset_mismatch_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("main", 1, 1, is_entry=True)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main 偏移与函数不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_signature_mismatch_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0, return_type="bool64")
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        symbols=[NativeSymbol("main", 0, 1, is_entry=True, return_type="int64")],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main return_type 与函数签名不一致" in str(exc_info.value)

    program.symbols = [NativeSymbol("main", 0, 1, is_entry=True, return_type="bool64", param_types=("int64",))]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号 main param_types 与函数签名不一致" in str(exc_info.value)


def test_native_memory_runner_validates_synthesized_symbols_before_platform_check(monkeypatch):
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
    )
    monkeypatch.setattr(native_runner_module, "_native_program_symbols", Mock(return_value=[NativeSymbol("missing", 0, 1)]))

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert program.symbols == []
    assert "符号表引用未知函数: missing" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_table_shape_before_platform_check():
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
        run_native_program_in_memory(program)

    assert "native 机器码符号表必须是列表" in str(exc_info.value)

    program.symbols = ["bad"]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "native 机器码符号表第 0 项必须是 NativeSymbol" in str(exc_info.value)


def test_native_memory_runner_rejects_symbol_missing_function_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    helper = NativeCodeFunction("helper", b"\xC3", [], 0, offset=1)
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function, "helper": helper},
        b"\xC3\xC3",
        0,
        symbols=[NativeSymbol("main", 0, 1, is_entry=True)],
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "符号表缺少函数: helper" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_unknown_target_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "missing", 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 修补目标未知: missing" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_source_location_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "main", 0, source_pc=True)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 修补记录.source_pc 必须是非负整数或 None" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_missing_listing_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "main", 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 修补指令清单缺失: 0" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_source_location_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_relocation_source_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_relocation_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    relocation = next(item for item in main.relocations if item.kind == "call_rel32")
    main.relocations[main.relocations.index(relocation)] = NativeRelocation(
        relocation.offset,
        relocation.patch_offset,
        relocation.kind,
        relocation.target,
        relocation.displacement,
        relocation.size,
        relocation.source_pc,
        (relocation.source_line or 0) + 1,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 来源位置与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_target_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_relocation_target_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_relocation_target_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    relocation = next(item for item in main.relocations if item.kind == "call_rel32" and item.target == "add2")
    main.relocations[main.relocations.index(relocation)] = NativeRelocation(
        relocation.offset,
        relocation.patch_offset,
        relocation.kind,
        "other",
        relocation.displacement,
        relocation.size,
        relocation.source_pc,
        relocation.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 目标与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_integer_shape_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(True, 1, "call_rel32", "main", 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 offset 必须是整数" in str(exc_info.value)

    function.relocations = [NativeRelocation(0, 1, "call_rel32", "main", "0")]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 displacement 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_target_shape_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "", 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 target 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_kind_shape_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "bad_rel32", "main", 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 修补类型暂不支持" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_opcode_mismatch_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "jmp_rel32", "main", 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "jmp_rel32 opcode 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_relocation_displacement_mismatch_before_platform_check():
    code = b"\xE8\x00\x00\x00\x00\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        relocations=[NativeRelocation(0, 1, "call_rel32", "main", 1)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 位移与机器码不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_missing_relocation_record_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_missing_relocation.vbc"
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
        output_path=str(tmp_path / "native_runner_missing_relocation.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    main.relocations = [item for item in main.relocations if item.kind != "call_rel32"]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "rel32 指令缺少修补记录" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_unknown_target_before_platform_check():
    code = bytes.fromhex("48 81 EC 20 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "missing", 0, 0, 0, 32, 0, 32, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口目标未知: missing" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_target_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_target_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_target_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    main.call_frames[0] = replace(frame, target="other")

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口目标与 call 清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_target_shape_before_platform_check():
    code = bytes.fromhex("48 81 EC 20 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "", 0, 0, 0, 32, 0, 32, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 target 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_source_location_before_platform_check():
    code = bytes.fromhex("48 81 EC 20 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "main", 0, 0, 0, 32, 0, 32, 16, source_line="7")],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口.source_line 必须是非负整数或 None" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_source_location_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_source_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    main.call_frames[0] = replace(frame, source_line=(frame.source_line or 0) + 1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口来源位置与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_call_source_location_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_call_source_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_call_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    call_instruction = next(
        instruction
        for instruction in main.instructions
        if instruction.offset > frame.offset and instruction.source_op == "call" and instruction.asm.startswith("call ")
    )
    instruction_index = main.instructions.index(call_instruction)
    main.instructions[instruction_index] = NativeCodeInstruction(
        call_instruction.offset,
        call_instruction.code,
        call_instruction.asm,
        call_instruction.source_op,
        call_instruction.source_pc,
        (call_instruction.source_line or 0) + 1,
        call_instruction.source_attrs,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 call 来源位置与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_call_offset_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_call_offset_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_call_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    assert frame.call_offset is not None
    main.call_frames[0] = replace(frame, call_offset=frame.call_offset + 1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 call_offset 与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_call_end_offset_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_call_end_offset_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_call_end_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    assert frame.call_end_offset is not None
    main.call_frames[0] = replace(frame, call_end_offset=frame.call_end_offset + 1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 call_end_offset 与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_call_opcode_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_call_opcode_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_call_opcode_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    call_index = next(
        index
        for index, instruction in enumerate(main.instructions)
        if instruction.offset > frame.offset and instruction.source_op == "call" and instruction.asm.startswith("call ")
    )
    call_instruction = main.instructions[call_index]
    bad_call_code = b"\xE9" + call_instruction.code[1:]
    program_code = bytearray(program.code)
    program_code[call_instruction.offset:call_instruction.offset + len(bad_call_code)] = bad_call_code
    program.code = bytes(program_code)
    function_code = bytearray(main.code)
    local_offset = call_instruction.offset - main.offset
    function_code[local_offset:local_offset + len(bad_call_code)] = bad_call_code
    main.code = bytes(function_code)
    main.instructions[call_index] = NativeCodeInstruction(
        call_instruction.offset,
        bad_call_code,
        call_instruction.asm,
        call_instruction.source_op,
        call_instruction.source_pc,
        call_instruction.source_line,
        call_instruction.source_attrs,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 call opcode 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_add_source_location_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_add_source_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_add_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    call_index = next(
        index
        for index, instruction in enumerate(main.instructions)
        if instruction.offset > frame.offset and instruction.source_op == "call" and instruction.asm.startswith("call ")
    )
    add_instruction = main.instructions[call_index + 1]
    main.instructions[call_index + 1] = NativeCodeInstruction(
        add_instruction.offset,
        add_instruction.code,
        add_instruction.asm,
        add_instruction.source_op,
        add_instruction.source_pc,
        (add_instruction.source_line or 0) + 1,
        add_instruction.source_attrs,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 add rsp 来源位置与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_add_offset_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_add_offset_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_add_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    assert frame.add_offset is not None
    main.call_frames[0] = replace(frame, add_offset=frame.add_offset + 1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 add_offset 与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_add_end_offset_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_add_end_offset_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_add_end_offset_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    assert frame.add_end_offset is not None
    main.call_frames[0] = replace(frame, add_end_offset=frame.add_end_offset + 1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 add_end_offset 与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_add_size_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_add_size_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_add_size_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    call_index = next(
        index
        for index, instruction in enumerate(main.instructions)
        if instruction.offset > frame.offset and instruction.source_op == "call" and instruction.asm.startswith("call ")
    )
    add_instruction = main.instructions[call_index + 1]
    main.instructions[call_index + 1] = NativeCodeInstruction(
        add_instruction.offset,
        add_instruction.code,
        f"add rsp, {frame.aligned_size + 16}",
        add_instruction.source_op,
        add_instruction.source_pc,
        add_instruction.source_line,
        add_instruction.source_attrs,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 add rsp 清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_add_machine_size_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_add_machine_size_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_add_machine_size_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    call_index = next(
        index
        for index, instruction in enumerate(main.instructions)
        if instruction.offset > frame.offset and instruction.source_op == "call" and instruction.asm.startswith("call ")
    )
    add_instruction = main.instructions[call_index + 1]
    bad_add_code = encode_add_rsp_imm32(frame.aligned_size + 16)
    program_code = bytearray(program.code)
    program_code[add_instruction.offset:add_instruction.offset + len(bad_add_code)] = bad_add_code
    program.code = bytes(program_code)
    function_code = bytearray(main.code)
    local_offset = add_instruction.offset - main.offset
    function_code[local_offset:local_offset + len(bad_add_code)] = bad_add_code
    main.code = bytes(function_code)
    main.instructions[call_index + 1] = NativeCodeInstruction(
        add_instruction.offset,
        bad_add_code,
        add_instruction.asm,
        add_instruction.source_op,
        add_instruction.source_pc,
        add_instruction.source_line,
        add_instruction.source_attrs,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 add rsp 大小不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_integer_shape_before_platform_check():
    code = bytes.fromhex("48 81 EC 20 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(True, "main", 0, 0, 0, 32, 0, 32, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 offset 必须是整数" in str(exc_info.value)

    function.call_frames = [NativeCallFrameAllocation(0, "main", "0", 0, 0, 32, 0, 32, 16)]

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 arg_count 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_type_metadata_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_call_frame_types_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_call_frame_types_bad.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    frame = main.call_frames[0]
    main.call_frames[0] = replace(frame, arg_types=["int64", "int64"])

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 arg_types 必须是字符串元组" in str(exc_info.value)

    main.call_frames[0] = replace(frame, arg_types=("int64",))

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 arg_types 数量不一致" in str(exc_info.value)

    main.call_frames[0] = replace(frame, param_types=())

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 param_types 数量不一致" in str(exc_info.value)

    main.call_frames[0] = replace(frame, param_types=("int64",))

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 param_types 数量不一致" in str(exc_info.value)

    program.functions["add2"].param_types = ("bool64", "int64")
    program.symbols = [
        replace(symbol, param_types=("bool64", "int64")) if symbol.name == "add2" else symbol
        for symbol in program.symbols
    ]
    main.call_frames[0] = replace(frame, param_types=("bool64", "int64"))

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口第 0 个参数类型不兼容" in str(exc_info.value)

    program.functions["add2"].param_types = ("int64", "int64")
    program.symbols = [
        replace(symbol, param_types=("int64", "int64")) if symbol.name == "add2" else symbol
        for symbol in program.symbols
    ]
    main.call_frames[0] = replace(frame, param_types=("bool64", "int64"))

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口形参类型与目标函数 add2 签名不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_negative_shape_before_platform_check():
    code = bytes.fromhex("48 81 EC 20 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "main", -1, 0, 0, 32, 0, 32, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 arg_count 不能为负数" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_alignment_shape_before_platform_check():
    code = bytes.fromhex("48 81 EC 20 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "main", 0, 0, 0, 32, 0, 32, 0)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口对齐必须为正数" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_opcode_mismatch_before_platform_check():
    code = b"\xC3" + b"\x00" * 6
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "main", 0, 0, 0, 32, 0, 32, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 sub rsp opcode 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_abi_mismatch_before_platform_check():
    code = bytes.fromhex("48 81 EC 40 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "main", 0, 0, 0, 64, 0, 64, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 shadow space 与 ABI 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_program_abi_metadata_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        0,
    )
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        abi=WindowsX64ABI(word_size=4),
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "ABI word_size 必须为 8" in str(exc_info.value)

    registers = RegisterSet(
        argument_registers=("RCX", "rcx"),
        return_register="RAX",
        frame_pointer="RBP",
        stack_pointer="RSP",
        caller_saved=(),
        callee_saved=(),
    )
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        abi=WindowsX64ABI(registers=registers),
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "ABI 参数寄存器重复: rcx" in str(exc_info.value)

    registers = RegisterSet(
        argument_registers=("RCX", "RDX", "R8", "R9"),
        return_register="RBX",
        frame_pointer="RBP",
        stack_pointer="RSP",
        caller_saved=(),
        callee_saved=(),
    )
    program = NativeCodeProgram(
        NativeTarget.WINDOWS_X64,
        function,
        {"main": function},
        b"\xC3",
        0,
        abi=WindowsX64ABI(registers=registers),
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "ABI 返回寄存器必须为 RAX" in str(exc_info.value)


def test_native_memory_runner_rejects_register_allocation_argument_registers_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        0,
        register_allocation=NativeRegisterAllocation(argument_registers=("RDX",)),
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "register_allocation.argument_registers 与 ABI 前缀不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_register_allocation_global_role_before_platform_check():
    code = b"\x49\x89\xEB\xC3"
    function = NativeCodeFunction(
        "main",
        code,
        [
            NativeCodeInstruction(0, b"\x49\x89\xEB", "mov r11, rbp ; global frame", "prologue"),
            NativeCodeInstruction(3, b"\xC3", "ret", "ret"),
        ],
        16,
        stack_slots=[NativeStackSlotAllocation("global[a]", 8, 8)],
        register_allocation=NativeRegisterAllocation(global_frame_register="R11", global_frame_role="borrowed"),
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "register_allocation.global_frame_role 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_register_allocation_shape_before_platform_check():
    function = NativeCodeFunction(
        "main",
        b"\xC3",
        [NativeCodeInstruction(0, b"\xC3", "ret", "ret")],
        0,
    )
    function.register_allocation = "保守栈槽分配"
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "register_allocation 必须是 NativeRegisterAllocation" in str(exc_info.value)


def test_native_memory_runner_rejects_call_frame_size_mismatch_before_platform_check():
    code = bytes.fromhex("48 81 EC 10 00 00 00 C3")
    function = NativeCodeFunction(
        "main",
        code,
        [],
        0,
        call_frames=[NativeCallFrameAllocation(0, "main", 0, 0, 0, 32, 0, 32, 16)],
    )
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, code, 0)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口 sub rsp 大小不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_missing_call_frame_record_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_missing_call_frame.vbc"
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
        output_path=str(tmp_path / "native_runner_missing_call_frame.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    program.functions["main"].call_frames.clear()

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "调用栈窗口缺少记录" in str(exc_info.value)


def test_native_memory_runner_rejects_missing_exit_flag_probe_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    for index, instruction in enumerate(main.instructions):
        if instruction.asm == "test rdx, rdx ; native _exit flag":
            main.instructions[index] = NativeCodeInstruction(
                instruction.offset,
                instruction.code,
                "test rax, rax ; native _exit flag",
                instruction.source_op,
                instruction.source_pc,
                instruction.source_line,
            )
            break

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 test 清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_structured_exit_probe_offset_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_structured_exit_probe_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_structured_exit_probe_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        probe.call_offset,
        probe.test_offset + 1,
        probe.jump_offset,
        probe.target,
        probe.probe_label,
        probe.source_pc,
        probe.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 test opcode 不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_offset_shape_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_offset_shape_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_offset_shape_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        True,
        probe.test_offset,
        probe.jump_offset,
        probe.target,
        probe.probe_label,
        probe.source_pc,
        probe.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 call_offset 必须是整数" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_target_shape_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_target_shape_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_target_shape_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        probe.call_offset,
        probe.test_offset,
        probe.jump_offset,
        "",
        probe.probe_label,
        probe.source_pc,
        probe.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 target 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_label_shape_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_label_shape_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_label_shape_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        probe.call_offset,
        probe.test_offset,
        probe.jump_offset,
        probe.target,
        "",
        probe.source_pc,
        probe.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 probe_label 必须是非空字符串" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_source_location_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_source_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_source_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        probe.call_offset,
        probe.test_offset,
        probe.jump_offset,
        probe.target,
        probe.probe_label,
        probe.source_pc,
        -1,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针.source_line 必须是非负整数或 None" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_source_location_mismatch_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_source_mismatch.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_source_mismatch.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        probe.call_offset,
        probe.test_offset,
        probe.jump_offset,
        probe.target,
        probe.probe_label,
        probe.source_pc,
        (probe.source_line or 0) + 1,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针来源位置与清单不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_missing_structured_exit_probe_record_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_missing_structured_exit_probe.vbc"
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
        output_path=str(tmp_path / "native_runner_missing_structured_exit_probe.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    program.functions["main"].exit_probes.clear()

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "call 缺少 _exit 传播探针记录" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_jump_relocation_target_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_jump_relocation_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_jump_relocation_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    relocation = next(item for item in main.relocations if item.offset == probe.jump_offset)
    main.relocations[main.relocations.index(relocation)] = NativeRelocation(
        relocation.offset,
        relocation.patch_offset,
        relocation.kind,
        "stop",
        relocation.displacement,
        relocation.size,
        relocation.source_pc,
        relocation.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 jump 修补目标不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_exit_probe_call_relocation_target_before_platform_check(tmp_path):
    source_path = tmp_path / "native_runner_exit_probe_call_relocation_bad.vbc"
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
        output_path=str(tmp_path / "native_runner_exit_probe_call_relocation_bad.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    main = program.functions["main"]
    probe = main.exit_probes[0]
    main.exit_probes[0] = NativeExitProbe(
        probe.call_offset,
        probe.test_offset,
        probe.jump_offset,
        "main",
        probe.probe_label,
        probe.source_pc,
        probe.source_line,
    )

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "_exit 传播探针 call 修补目标不一致" in str(exc_info.value)


def test_native_memory_runner_rejects_negative_entry_offset_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", -1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "入口偏移不能为负数" in str(exc_info.value)


def test_native_memory_runner_rejects_out_of_range_entry_offset_before_platform_check():
    function = NativeCodeFunction("main", b"\xC3", [], 0)
    program = NativeCodeProgram(NativeTarget.WINDOWS_X64, function, {"main": function}, b"\xC3", 1)

    with pytest.raises(NativeCodegenError) as exc_info:
        run_native_program_in_memory(program)

    assert "入口偏移越界" in str(exc_info.value)


def test_run_source_file_can_execute_native_memory(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_main.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_main.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_utf8_bom_source(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_bom_main.vbc"
    source_path.write_bytes("\ufeffint main() {\n    return 42;\n}\n".encode("utf-8"))

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_bom_main.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_reports_native_memory_runner_error_as_compile_error(tmp_path, monkeypatch):
    source_path = tmp_path / "native_memory_runner_error.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    monkeypatch.setattr(
        "verbose_c.compiler.native.runner.run_native_program_in_memory",
        Mock(side_effect=NativeCodegenError("native 内存执行仅支持 Windows x64")),
    )
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_runner_error.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert not result.success
    assert result.exit_code == 1
    assert result.error is not None
    assert result.error.message == "native 内存执行仅支持 Windows x64"


def test_native_mvp_smoke_source_generates_and_runs(tmp_path):
    source_path = "tests/grammar/native_mvp_smoke_test.vbc"

    compile_result = run_source_file(
        source_path,
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_mvp_smoke_compile.vbb"),
        execute=False,
        optimize_level=0,
    )

    assert compile_result.success
    assert compile_result.compilation_output is not None
    assert compile_result.compilation_output.native_code_error is None
    assert compile_result.compilation_output.native_code_program is not None
    listing = format_native_code_program(compile_result.compilation_output.native_code_program)
    assert "call fact" in listing
    assert "call bump_bias" in listing
    assert "jmp" in listing

    if not can_run_native_memory():
        return

    native_result = run_source_file(
        source_path,
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_mvp_smoke_native.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert native_result.success
    assert native_result.exit_code == 99


def test_cli_native_mvp_smoke_can_report_result_file(tmp_path, monkeypatch, capsys):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    from verbose_c import cli

    result_path = tmp_path / "native_mvp_smoke_result.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            "tests/grammar/native_mvp_smoke_test.vbc",
            "--run-native-memory",
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
            "-o",
            str(tmp_path / "native_mvp_smoke_cli.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native 入口返回值: 99" in capsys.readouterr().out
    assert result_path.read_text(encoding="utf-8") == "99\n"


def test_run_source_file_can_execute_native_memory_compare(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_compare.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int left = 9;\n"
        "    int right = 4;\n"
        "    bool bigger = left > right;\n"
        "    return bigger;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_compare.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 1


def test_run_source_file_can_execute_native_memory_division_modulo(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_div_mod.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int quotient = 80 / 2;\n"
        "    int remainder = 11 % 2;\n"
        "    return quotient + remainder;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_div_mod.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 41


def test_run_source_file_can_execute_native_memory_signed_division(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_signed_div.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = -7;\n"
        "    return value / 2;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_signed_div.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == -3


def test_run_source_file_can_execute_native_memory_integer_width_mix(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_integer_width.vbc"
    source_path.write_text(
        "int main() {\n"
        "    char a = 40;\n"
        "    long b = 2;\n"
        "    return a + b;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_integer_width.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_if_else(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_if_else.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 7;\n"
        "    if (value > 4) {\n"
        "        return 10;\n"
        "    }\n"
        "    return 3;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_if_else.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 10


def test_run_source_file_can_execute_native_memory_while_loop(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_while_loop.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 0;\n"
        "    while (value < 4) {\n"
        "        value = value + 1;\n"
        "    }\n"
        "    return value;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_while_loop.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 4


def test_run_source_file_can_execute_native_memory_for_loop(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_for_loop.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int total = 0;\n"
        "    for (int i = 0; i < 5; i = i + 1) {\n"
        "        total = total + i;\n"
        "    }\n"
        "    return total;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_for_loop.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 10


def test_run_source_file_can_execute_native_memory_do_while_loop(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_do_while_loop.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 0;\n"
        "    do {\n"
        "        value = value + 2;\n"
        "    } while (value < 6);\n"
        "    return value;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_do_while_loop.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 6


def test_run_source_file_can_execute_native_memory_break_continue(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_break_continue.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int total = 0;\n"
        "    for (int i = 0; i < 6; i = i + 1) {\n"
        "        if (i == 2) {\n"
        "            continue;\n"
        "        }\n"
        "        if (i == 5) {\n"
        "            break;\n"
        "        }\n"
        "        total = total + i;\n"
        "    }\n"
        "    return total;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_break_continue.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 8


def test_run_source_file_can_execute_native_memory_switch(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_switch.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 2;\n"
        "    int result = 0;\n"
        "    switch (value) {\n"
        "        case 1:\n"
        "            result = 10;\n"
        "            break;\n"
        "        case 2:\n"
        "            result = 20;\n"
        "            break;\n"
        "        default:\n"
        "            result = 30;\n"
        "    }\n"
        "    return result + 2;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_switch.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 22


def test_run_source_file_can_execute_native_memory_switch_fallthrough(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_switch_fallthrough.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 1;\n"
        "    int result = 0;\n"
        "    switch (value) {\n"
        "        case 1:\n"
        "            result = result + 3;\n"
        "        case 2:\n"
        "            result = result + 4;\n"
        "            break;\n"
        "        default:\n"
        "            result = result + 30;\n"
        "    }\n"
        "    return result;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_switch_fallthrough.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 7


def test_run_source_file_can_execute_native_memory_python_style_modulo(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_python_style_modulo.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int a = -5;\n"
        "    int b = 2;\n"
        "    int c = 5;\n"
        "    int d = -2;\n"
        "    int e = -5;\n"
        "    int f = -2;\n"
        "    return (a % b) * 100 + (c % d) * 10 + (e % f);\n"
        "}\n",
        encoding="utf-8",
    )

    vm_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_python_style_modulo_vm.vbb"),
        execute=True,
        optimize_level=0,
    )
    native_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_python_style_modulo_native.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert vm_result.success
    assert native_result.success
    assert vm_result.exit_code == 89
    assert native_result.exit_code == vm_result.exit_code


def test_run_source_file_can_execute_native_memory_short_circuit_logic(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_short_circuit.vbc"
    source_path.write_text(
        "int fail() {\n"
        "    return 99;\n"
        "}\n\n"
        "int main() {\n"
        "    int left = 0;\n"
        "    int value = 0;\n"
        "    if (left && fail()) {\n"
        "        value = 40;\n"
        "    }\n"
        "    if (!left || fail()) {\n"
        "        value = value + 2;\n"
        "    }\n"
        "    return value;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_short_circuit.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 2


def test_run_source_file_can_execute_native_memory_user_function_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_call.vbc"
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
        output_path=str(tmp_path / "native_memory_call.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_recursive_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_recursive.vbc"
    source_path.write_text(
        "int fact(int n) {\n"
        "    if (n <= 1) {\n"
        "        return 1;\n"
        "    }\n"
        "    return n * fact(n - 1);\n"
        "}\n\n"
        "int main() {\n"
        "    return fact(5);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_recursive.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 120


def test_run_source_file_can_execute_native_memory_mutual_recursive_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_mutual_recursive.vbc"
    source_path.write_text(
        "int is_odd(int n);\n\n"
        "int is_even(int n) {\n"
        "    if (n == 0) {\n"
        "        return 1;\n"
        "    }\n"
        "    return is_odd(n - 1);\n"
        "}\n\n"
        "int is_odd(int n) {\n"
        "    if (n == 0) {\n"
        "        return 0;\n"
        "    }\n"
        "    return is_even(n - 1);\n"
        "}\n\n"
        "int main() {\n"
        "    return is_odd(7) + is_even(8);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_mutual_recursive.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 2


def test_run_source_file_can_execute_native_memory_bool_function_return(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_bool_return.vbc"
    source_path.write_text(
        "bool is_positive(int value) {\n"
        "    return value > 0;\n"
        "}\n\n"
        "int main() {\n"
        "    if (is_positive(3)) {\n"
        "        return 42;\n"
        "    }\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_bool_return.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_void_user_function_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_void_call.vbc"
    source_path.write_text(
        "void noop(int value) {\n"
        "    if (value > 0) {\n"
        "        return;\n"
        "    }\n"
        "}\n\n"
        "int main() {\n"
        "    noop(3);\n"
        "    return 42;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_void_call.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_enum_switch(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_enum_switch.vbc"
    source_path.write_text(
        "enum Mode {\n"
        "    OFF = 1,\n"
        "    ON = 2\n"
        "};\n\n"
        "int main() {\n"
        "    int value = ON;\n"
        "    switch (value) {\n"
        "        case OFF:\n"
        "            return 10;\n"
        "        case ON:\n"
        "            return 42;\n"
        "        default:\n"
        "            return 3;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_enum_switch.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_stack_argument_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_stack_arg.vbc"
    source_path.write_text(
        "int pick5(int a, int b, int c, int d, int e) {\n"
        "    return e + a;\n"
        "}\n\n"
        "int main() {\n"
        "    return pick5(1, 2, 3, 4, 41);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_stack_arg.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_multiple_stack_argument_call(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_multi_stack_arg.vbc"
    source_path.write_text(
        "int pick6(int a, int b, int c, int d, int e, int f) {\n"
        "    return e + f + a;\n"
        "}\n\n"
        "int main() {\n"
        "    return pick6(1, 2, 3, 4, 20, 21);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_multi_stack_arg.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_run_source_file_can_execute_native_memory_unary_ops(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_unary.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = -41;\n"
        "    return value + !0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_unary.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == -40


def test_run_source_file_can_execute_native_memory_scalar_casts(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_scalar_casts.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int narrowed = (char)40;\n"
        "    int widened = (long)2;\n"
        "    int truthy = (bool)42;\n"
        "    return narrowed + widened + truthy;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_scalar_casts.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 43
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is not None
    listing = format_native_code_program(result.compilation_output.native_code_program)
    assert "cast to char" in listing
    assert "cast to long" in listing
    assert "cast to bool" in listing
    assert "来源属性" in listing
    assert '{"target_type":"char"}' in listing
    assert '{"target_type":"long"}' in listing
    assert '{"target_type":"bool"}' in listing
    metadata = native_code_program_map(result.compilation_output.native_code_program)
    cast_attrs = [
        instruction["source_attrs"]
        for function in metadata["functions"]
        for instruction in function["instructions"]
        if instruction["source_op"] in {"cast_bool_int", "cast_int_bool"}
    ]
    assert {"target_type": "char"} in cast_attrs
    assert {"target_type": "long"} in cast_attrs
    assert {"target_type": "bool"} in cast_attrs


def test_run_source_file_can_execute_native_memory_local_static_narrow_integer_cast(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_local_static_narrow_cast.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 40;\n"
        "    char narrowed = (char)value;\n"
        "    return narrowed;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_local_static_narrow_cast.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 40
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is not None
    assert result.compilation_output.native_code_error is None


def test_run_source_file_can_execute_native_memory_arithmetic_static_narrow_integer_cast(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_arithmetic_static_narrow_cast.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 20 + 20;\n"
        "    char narrowed = (char)value;\n"
        "    return narrowed;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_arithmetic_static_narrow_cast.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 40
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is not None
    assert result.compilation_output.native_code_error is None


def test_native_memory_executes_static_phi_narrow_integer_cast():
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    function = MachineFunction(
        name="<module>",
        params=[],
        return_type="int64",
        frame=StackFrameLayout(),
        blocks=[
            MachineBlock(
                name="entry",
                instructions=[],
                terminator=MachineTerminator("br", targets=["left", "right"], args=[MachineOperand.imm(1)]),
                successors=["left", "right"],
            ),
            MachineBlock(
                name="left",
                instructions=[MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v0")), args=[MachineOperand.imm(40)])],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                predecessors=["entry"],
                successors=["merge"],
            ),
            MachineBlock(
                name="right",
                instructions=[MachineInstruction("load_imm", result=MachineOperand.vreg(VirtualRegister("v1")), args=[MachineOperand.imm(40)])],
                terminator=MachineTerminator("jmp", targets=["merge"]),
                predecessors=["entry"],
                successors=["merge"],
            ),
            MachineBlock(
                name="merge",
                instructions=[
                    MachineInstruction(
                        "phi",
                        result=MachineOperand.vreg(VirtualRegister("v2")),
                        args=[MachineOperand.vreg(VirtualRegister("v0")), MachineOperand.vreg(VirtualRegister("v1"))],
                        attrs={"incoming_blocks": ["left", "right"]},
                    ),
                    MachineInstruction(
                        "cast_bool_int",
                        result=MachineOperand.vreg(VirtualRegister("v3")),
                        args=[MachineOperand.vreg(VirtualRegister("v2"))],
                        attrs={"target_type": "char"},
                    ),
                ],
                terminator=MachineTerminator("ret", args=[MachineOperand.vreg(VirtualRegister("v3"))]),
                predecessors=["left", "right"],
            ),
        ],
    )
    machine = MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=function,
        functions={"<module>": function},
    )

    program = generate_native_code(machine)

    assert run_native_program_in_memory(program) == 40


def test_run_source_file_can_execute_native_memory_cross_block_static_narrow_integer_cast(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_cross_block_static_narrow_cast.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 40;\n"
        "    if (1) {\n"
        "        value = value;\n"
        "    }\n"
        "    char narrowed = (char)value;\n"
        "    return narrowed;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cross_block_static_narrow_cast.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 40
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is not None
    assert result.compilation_output.native_code_error is None


def test_run_source_file_rejects_native_memory_local_out_of_range_narrow_integer_cast(tmp_path):
    source_path = tmp_path / "native_local_out_of_range_narrow_cast.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 300;\n"
        "    char narrowed = (char)value;\n"
        "    return narrowed;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_local_out_of_range_narrow_cast.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert not result.success
    assert result.error is not None
    assert "cast 到 char 的立即数超出范围" in str(result.error)


def test_native_codegen_rejects_dynamic_narrow_integer_cast_without_blocking_vm(tmp_path):
    source_path = tmp_path / "native_dynamic_narrow_cast.vbc"
    source_path.write_text(
        "int narrow(int value) {\n"
        "    char narrowed = (char)value;\n"
        "    return narrowed;\n"
        "}\n"
        "int main() {\n"
        "    return narrow(40);\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_dynamic_narrow_cast.vbb"),
        execute=True,
        optimize_level=0,
    )

    assert result.success
    assert result.exit_code == 40
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is None
    assert result.compilation_output.native_code_error is not None
    assert "动态窄化整数 cast 到 char" in str(result.compilation_output.native_code_error)


def test_run_source_file_rejects_native_memory_out_of_range_narrow_integer_cast(tmp_path):
    source_path = tmp_path / "native_out_of_range_narrow_cast.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int narrowed = (char)300;\n"
        "    return narrowed;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_out_of_range_narrow_cast.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert not result.success
    assert result.error is not None
    assert "cast 到 char 的立即数超出范围" in str(result.error)


def test_native_lowering_rejects_float_cast_without_blocking_vm(tmp_path):
    source_path = tmp_path / "native_float_cast_unsupported.vbc"
    source_path.write_text(
        "int main() {\n"
        "    float value = (float)42;\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_float_cast_unsupported.vbb"),
        execute=True,
        optimize_level=0,
    )

    assert result.success
    assert result.exit_code == 0
    assert result.compilation_output is not None
    assert result.compilation_output.machine_program is None
    assert result.compilation_output.native_code_program is None
    assert result.compilation_output.machine_error is not None
    message = str(result.compilation_output.machine_error)
    assert "IR 指令 cast" in message
    assert "native MVP 暂不支持类型 'FLOAT'" in message


def test_native_codegen_rejects_float_parameter_without_blocking_vm(tmp_path):
    source_path = tmp_path / "native_float_param_unsupported.vbc"
    source_path.write_text(
        "int ignore(float value) {\n"
        "    return 42;\n"
        "}\n\n"
        "int main() {\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_float_param_unsupported.vbb"),
        execute=True,
        optimize_level=0,
    )

    assert result.success
    assert result.exit_code == 0
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is None
    assert result.compilation_output.native_code_error is not None
    assert "函数 ignore 第 0 个参数暂不支持类型 Float(FLOAT)" in str(result.compilation_output.native_code_error)


def test_run_source_file_rejects_native_memory_float_parameter(tmp_path):
    source_path = tmp_path / "native_memory_float_param_unsupported.vbc"
    source_path.write_text(
        "int ignore(float value) {\n"
        "    return 42;\n"
        "}\n\n"
        "int main() {\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_float_param_unsupported.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert not result.success
    assert "函数 ignore 第 0 个参数暂不支持类型 Float(FLOAT)" in str(result.error)


def test_run_source_file_can_execute_native_memory_inc_dec(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_inc_dec.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 1;\n"
        "    value++;\n"
        "    ++value;\n"
        "    value--;\n"
        "    return value;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_inc_dec.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 2


def test_run_source_file_can_execute_native_memory_compound_assignments(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_compound_assign.vbc"
    source_path.write_text(
        "int main() {\n"
        "    int value = 10;\n"
        "    value += 5;\n"
        "    value -= 3;\n"
        "    value *= 4;\n"
        "    value /= 6;\n"
        "    value %= 5;\n"
        "    return value;\n"
        "}\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_compound_assign.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 3


def test_run_source_file_can_execute_native_memory_top_level_exit_main_result(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_memory_top_exit_main.vbc"
    source_path.write_text(
        "int main() {\n"
        "    return 42;\n"
        "}\n\n"
        "_exit(main());\n",
        encoding="utf-8",
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_top_exit_main.vbb"),
        execute=False,
        optimize_level=0,
        run_native_memory=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_native_memory_runner_executes_phi_merge():
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    machine = _machine_program(
        [
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.JUMP_IF_FALSE, 4),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.JUMP, 5),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.RETURN,),
        ],
        constants=[VBCBool(True), VBCInteger(7), VBCInteger(3)],
    )
    program = generate_native_code(machine)

    assert run_native_function_in_memory(program.entry) == 7


def test_native_memory_runner_executes_phi_merge_false_path():
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    machine = _machine_program(
        [
            (Opcode.LOAD_CONSTANT, 0),
            (Opcode.JUMP_IF_FALSE, 4),
            (Opcode.LOAD_CONSTANT, 1),
            (Opcode.JUMP, 5),
            (Opcode.LOAD_CONSTANT, 2),
            (Opcode.RETURN,),
        ],
        constants=[VBCBool(False), VBCInteger(7), VBCInteger(3)],
    )
    program = generate_native_code(machine)

    assert run_native_function_in_memory(program.entry) == 3


def test_cli_run_native_memory_prints_return_value(tmp_path, monkeypatch, capsys):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    from verbose_c import cli

    source_path = tmp_path / "native_cli_main.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(source_path), "--run-native-memory", "-o", str(tmp_path / "native_cli_main.vbb")],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 42
    assert "native 入口返回值: 42" in capsys.readouterr().out


def test_run_source_file_can_write_native_result_file(tmp_path, monkeypatch):
    source_path = tmp_path / "native_memory_result_file.vbc"
    result_path = tmp_path / "nested" / "native_result.txt"
    source_path.write_text("int main() {\n    return 300;\n}\n", encoding="utf-8")
    monkeypatch.setattr("verbose_c.compiler.native.runner.run_native_program_in_memory", Mock(return_value=300))

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_memory_result_file.vbb"),
        execute=False,
        run_native_memory=True,
        native_result_path=str(result_path),
    )

    assert result.success
    assert result.exit_code == 300
    assert result_path.read_text(encoding="utf-8") == "300\n"


def test_cli_run_native_memory_writes_native_result_file(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_result_file.vbc"
    result_path = tmp_path / "native_cli_result.txt"
    source_path.write_text("int main() {\n    return 300;\n}\n", encoding="utf-8")
    monkeypatch.setattr("verbose_c.compiler.native.runner.run_native_program_in_memory", Mock(return_value=300))
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--run-native-memory",
            "--native-result",
            str(result_path),
            "-o",
            str(tmp_path / "native_cli_result_file.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 300
    assert "native 入口返回值: 300" in capsys.readouterr().out
    assert result_path.read_text(encoding="utf-8") == "300\n"


def test_cli_run_native_memory_can_force_zero_process_exit(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_zero_exit.vbc"
    result_path = tmp_path / "native_cli_zero_exit.txt"
    source_path.write_text("int main() {\n    return 300;\n}\n", encoding="utf-8")
    monkeypatch.setattr("verbose_c.compiler.native.runner.run_native_program_in_memory", Mock(return_value=300))
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--run-native-memory",
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
            "-o",
            str(tmp_path / "native_cli_zero_exit.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native 入口返回值: 300" in capsys.readouterr().out
    assert result_path.read_text(encoding="utf-8") == "300\n"


def test_run_source_file_can_run_native_pe_and_write_result(tmp_path, monkeypatch):
    source_path = tmp_path / "native_pe_result_file.vbc"
    result_path = tmp_path / "nested" / "native_pe_result.txt"
    source_path.write_text("int main() {\n    return 300;\n}\n", encoding="utf-8")
    monkeypatch.setattr("verbose_c.compiler.native.runner.can_run_native_memory", lambda: True)

    def fake_run(args, check):
        assert check is False
        assert len(args) == 1
        assert os.path.exists(args[0])
        assert args[0].endswith(".exe")
        return subprocess.CompletedProcess(args, 300)

    monkeypatch.setattr("verbose_c.engine.engine.subprocess.run", fake_run)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_pe_result_file.vbb"),
        execute=False,
        run_native_pe=True,
        native_result_path=str(result_path),
    )

    assert result.success
    assert result.exit_code == 300
    assert result_path.read_text(encoding="utf-8") == "300\n"


def test_cli_run_native_pe_prints_return_value(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_pe.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr("verbose_c.compiler.native.runner.can_run_native_memory", lambda: True)
    monkeypatch.setattr(
        "verbose_c.engine.engine.subprocess.run",
        lambda args, check: subprocess.CompletedProcess(args, 42),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(source_path), "--run-native-pe", "-o", str(tmp_path / "native_cli_pe.vbb")],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 42
    assert "native PE 入口返回值: 42" in capsys.readouterr().out


def test_cli_run_native_pe_can_force_zero_process_exit(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_pe_zero_exit.vbc"
    result_path = tmp_path / "native_cli_pe_zero_exit.txt"
    source_path.write_text("int main() {\n    return 300;\n}\n", encoding="utf-8")
    monkeypatch.setattr("verbose_c.compiler.native.runner.can_run_native_memory", lambda: True)
    monkeypatch.setattr(
        "verbose_c.engine.engine.subprocess.run",
        lambda args, check: subprocess.CompletedProcess(args, 300),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--run-native-pe",
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
            "-o",
            str(tmp_path / "native_cli_pe_zero_exit.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native PE 入口返回值: 300" in capsys.readouterr().out
    assert result_path.read_text(encoding="utf-8") == "300\n"


def test_run_bytecode_file_can_run_native_pe(tmp_path, monkeypatch):
    source_path = tmp_path / "native_bytecode_pe_input.vbc"
    bytecode_path = tmp_path / "native_bytecode_pe_input.vbb"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    assert compile_result.success
    monkeypatch.setattr("verbose_c.compiler.native.runner.can_run_native_memory", lambda: True)
    monkeypatch.setattr(
        "verbose_c.engine.engine.subprocess.run",
        lambda args, check: subprocess.CompletedProcess(args, 42),
    )

    result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
        run_native_pe=True,
    )

    assert result.success
    assert result.exit_code == 42


def test_parse_native_export_kinds_supports_lists_alias_and_bundle():
    assert parse_native_export_kinds(["asm,native-bin", "native-map"]) == frozenset({
        NativeExportKind.LISTING,
        NativeExportKind.RAW_BINARY,
        NativeExportKind.MAP,
    })
    assert parse_native_export_kinds(["native-bundle"]) == frozenset(NativeExportKind)

    with pytest.raises(ValueError) as exc_info:
        parse_native_export_kinds(["unknown"])

    assert "--emit 存在不支持的类型: unknown" in str(exc_info.value)


def test_run_source_file_can_export_native_bundle_and_record_manifest(tmp_path):
    source_path = tmp_path / "native_bundle.vbc"
    export_dir = tmp_path / "native_bundle_outputs"
    dump_path = tmp_path / "native_bundle_dump.md"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    request = NativeExportRequest.organized(
        str(source_path),
        str(export_dir),
        parse_native_export_kinds(["native-bundle"]),
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        output_path=str(tmp_path / "native_bundle.vbb"),
        execute=False,
        native_export_request=request,
    )

    assert result.success
    assert result.export_report is not None
    expected_names = {
        "native_bundle.native.md",
        "native_bundle.native.bin",
        "native_bundle.text.bin",
        "native_bundle.exe",
        "native_bundle.native.map.json",
    }
    assert {os.path.basename(artifact.path) for artifact in result.export_report.artifacts} == expected_names
    manifest_path = export_dir / "native_bundle.native.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["target"] == "windows-x64"
    assert manifest["entry"] == "<module>"
    assert {artifact["kind"] for artifact in manifest["artifacts"]} == {
        kind.value for kind in NativeExportKind
    }
    for artifact in manifest["artifacts"]:
        artifact_path = export_dir / artifact["path"]
        content = artifact_path.read_bytes()
        assert artifact["size"] == len(content)
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "## Native 导出产物" in dump_text
    assert "native_bundle.native.manifest.json" in dump_text
    assert "native-pe" in dump_text


def test_run_bytecode_file_accepts_unified_native_export_request(tmp_path):
    source_path = tmp_path / "native_vbb_export.vbc"
    bytecode_path = tmp_path / "native_vbb_export.vbb"
    export_dir = tmp_path / "native_vbb_outputs"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    request = NativeExportRequest.organized(
        str(bytecode_path),
        str(export_dir),
        parse_native_export_kinds(["native-bin,native-map"]),
    )

    result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
        native_export_request=request,
    )

    assert compile_result.success
    assert result.success
    assert (export_dir / "native_vbb_export.native.bin").read_bytes()
    assert (export_dir / "native_vbb_export.native.map.json").is_file()
    assert (export_dir / "native_vbb_export.native.manifest.json").is_file()


def test_cli_unified_emit_exports_selected_native_artifacts(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_unified.vbc"
    export_dir = tmp_path / "native_cli_unified_outputs"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-bin,native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_unified.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "native 产物已导出到" in output
    assert (export_dir / "native_cli_unified.native.bin").is_file()
    assert (export_dir / "native_cli_unified.native.map.json").is_file()
    assert (export_dir / "native_cli_unified.native.manifest.json").is_file()


def test_cli_emit_uses_timestamped_entry_directory_by_default(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_default_emit.vbc"
    source_path.write_text("int main() {\n    return 0;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-bin",
            "-o",
            str(tmp_path / "native_cli_default_emit.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    export_dirs = [path for path in tmp_path.glob("native_cli_default_emit_emit_out_*") if path.is_dir()]
    assert exc_info.value.code == 0
    assert len(export_dirs) == 1
    export_dir = export_dirs[0]
    timestamp = export_dir.name.removeprefix("native_cli_default_emit_emit_out_")
    assert len(timestamp) == 15
    assert timestamp[:8].isdigit() and timestamp[8] == "_" and timestamp[9:].isdigit()
    assert (export_dir / "native_cli_default_emit.native.bin").is_file()
    assert (export_dir / "native_cli_default_emit.native.manifest.json").is_file()
    assert f"native 产物已导出到: {export_dir}" in capsys.readouterr().out


def test_cli_ignores_emit_dir_without_emit(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_ignored_emit_dir.vbc"
    ignored_dir = tmp_path / "ignored_exports"
    source_path.write_text("int main() {\n    return 0;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit-dir",
            str(ignored_dir),
            "-o",
            str(tmp_path / "native_cli_ignored_emit_dir.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert not ignored_dir.exists()
    assert "native 产物已导出到" not in output


def test_cli_rejects_unknown_unified_emit_kind(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_unified_invalid.vbc"
    source_path.write_text("int main() {\n    return 0;\n}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(source_path), "--emit", "unknown"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--emit 存在不支持的类型: unknown" in capsys.readouterr().out


def test_run_source_file_can_emit_native_asm_listing(tmp_path):
    source_path = tmp_path / "native_emit_asm.vbc"
    asm_path = tmp_path / "native_emit_asm.txt"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_asm.vbb"),
        execute=False,
        native_export_request=_native_export_request(listing=asm_path),
    )

    assert result.success
    asm_text = asm_path.read_text(encoding="utf-8")
    assert "## x64 机器码" in asm_text
    assert "入口偏移:" in asm_text
    assert "入口 RVA:" in asm_text
    assert "程序 SHA-256:" in asm_text
    assert "### PE/COFF 过渡摘要" in asm_text
    assert "PE32+" in asm_text
    assert "### .text 代码节" in asm_text
    assert "2E 74 65 78 74 00 00 00" in asm_text
    assert "CNT_CODE, MEM_EXECUTE, MEM_READ" in asm_text
    assert "### ABI" in asm_text
    assert "- Shadow space: `32` bytes" in asm_text
    assert "#### 寄存器分配" in asm_text
    assert "mov rax, 42" in asm_text
    assert "mov rsp, rbp; pop rbp; ret" in asm_text


def test_run_source_file_can_emit_native_raw_binary(tmp_path):
    source_path = tmp_path / "native_emit_bin.vbc"
    bin_path = tmp_path / "nested" / "native_emit_bin.bin"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_bin.vbb"),
        execute=False,
        native_export_request=_native_export_request(raw_binary=bin_path),
    )

    assert result.success
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is not None
    raw = bin_path.read_bytes()
    assert raw == result.compilation_output.native_code_program.code
    assert raw.startswith(bytes.fromhex("55 48 89 E5"))
    assert raw.endswith(bytes.fromhex("48 89 EC 5D C3"))


def test_run_source_file_reports_native_raw_binary_write_self_check_failure(tmp_path, monkeypatch):
    import verbose_c.engine.engine as engine_module

    source_path = tmp_path / "native_emit_bin_self_check_bad.vbc"
    bin_path = tmp_path / "native_emit_bin_self_check_bad.bin"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):
        """模拟 raw bin 写后读回内容损坏。"""
        if str(path) == str(bin_path) and mode == "rb":
            return io.BytesIO(b"broken native bin")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(engine_module, "open", fake_open, raising=False)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_bin_self_check_bad.vbb"),
        execute=False,
        native_export_request=_native_export_request(raw_binary=bin_path),
    )

    assert not result.success
    assert result.error is not None
    assert "导出 x64 原始机器码自检失败" in str(result.error)


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
        "supported_value_types": ["int64", "bool64", "void"],
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


def test_native_pe_image_builder_emits_expected_headers_and_text_section(tmp_path):
    source_path = tmp_path / "native_emit_pe_image.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    pe_image = build_native_pe_image(program.code, metadata)

    validate_native_pe_image_bytes(pe_image, metadata)
    file_layout = metadata["pe_file_layout"]
    text_section = metadata["sections"][0]
    pe_lfanew = metadata["pe_lfanew"]
    assert pe_image[:2] == b"MZ"
    assert int.from_bytes(pe_image[0x3C:0x40], "little") == pe_lfanew
    assert pe_image[pe_lfanew:pe_lfanew + 4] == b"PE\x00\x00"
    assert len(pe_image) == file_layout["file_size"]
    text_offset = file_layout["text_raw"]["offset"]
    text_size = file_layout["text_raw"]["size"]
    assert pe_image[text_offset:text_offset + len(program.code)] == program.code
    assert pe_image[text_offset + len(program.code):text_offset + text_size] == bytes(text_section["raw_padding_size"])
    assert hashlib.sha256(pe_image[text_offset:text_offset + text_size]).hexdigest() == text_section["raw_padded_sha256"]


def test_native_pe_image_validator_rejects_bad_signature(tmp_path):
    source_path = tmp_path / "native_emit_pe_image_bad_signature.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image_bad_signature.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    pe_image = bytearray(build_native_pe_image(program.code, metadata))
    pe_image[metadata["pe_lfanew"]] = 0

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_pe_image_bytes(bytes(pe_image), metadata)

    assert "PE signature 不一致" in str(exc_info.value)


def test_native_pe_image_validator_rejects_bad_dos_header_padding(tmp_path):
    source_path = tmp_path / "native_emit_pe_image_bad_dos_header.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image_bad_dos_header.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    pe_image = bytearray(build_native_pe_image(program.code, metadata))
    pe_image[0x20] = 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_pe_image_bytes(bytes(pe_image), metadata)

    assert "DOS header 保留字段必须全部为 0" in str(exc_info.value)


def test_native_pe_image_validator_rejects_bad_dos_stub_padding(tmp_path):
    source_path = tmp_path / "native_emit_pe_image_bad_dos_stub.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image_bad_dos_stub.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    file_layout = metadata["pe_file_layout"]
    stub_offset = file_layout["dos_stub_padding"]["offset"]
    pe_image = bytearray(build_native_pe_image(program.code, metadata))
    pe_image[stub_offset] = 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_pe_image_bytes(bytes(pe_image), metadata)

    assert "DOS stub padding 必须全部为 0" in str(exc_info.value)


def test_native_pe_image_validator_rejects_bad_optional_header_default(tmp_path):
    source_path = tmp_path / "native_emit_pe_image_bad_optional_default.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image_bad_optional_default.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    optional_header_offset = metadata["pe_optional_header_offset"]
    pe_image = bytearray(build_native_pe_image(program.code, metadata))
    pe_image[optional_header_offset + 2] = 0

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_pe_image_bytes(bytes(pe_image), metadata)

    assert "OptionalHeader MajorLinkerVersion 默认值不一致" in str(exc_info.value)


def test_native_pe_image_validator_rejects_layout_segment_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_pe_image_bad_layout_segment.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image_bad_layout_segment.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    pe_image = build_native_pe_image(program.code, metadata)
    metadata["pe_file_layout"]["coff_header"]["offset"] += 1
    metadata["pe_file_layout"]["coff_header"]["end_offset"] += 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_pe_image_bytes(pe_image, metadata)

    assert "layout coff_header 不一致" in str(exc_info.value)


def test_native_pe_image_validator_rejects_text_raw_section_layout_mismatch(tmp_path):
    source_path = tmp_path / "native_emit_pe_image_bad_text_raw_layout.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_image_bad_text_raw_layout.vbb"),
        execute=False,
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    pe_image = build_native_pe_image(program.code, metadata)
    metadata["sections"][0]["raw_size_aligned"] -= 1

    with pytest.raises(NativeCodegenError) as exc_info:
        validate_native_pe_image_bytes(pe_image, metadata)

    assert "layout text_raw 不一致" in str(exc_info.value)


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


def test_run_source_file_can_emit_native_map_json(tmp_path):
    source_path = tmp_path / "native_emit_map_json.vbc"
    map_path = tmp_path / "nested" / "native_emit_map.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_map_json.vbb"),
        execute=False,
        native_export_request=_native_export_request(map=map_path),
    )

    assert result.success
    assert result.compilation_output is not None
    assert result.compilation_output.native_code_program is not None
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    validate_native_code_map_bytes(result.compilation_output.native_code_program.code, metadata)
    validate_native_code_program_map(result.compilation_output.native_code_program, metadata)
    assert metadata["entry"] == "<module>"
    assert metadata["code_size"] == len(result.compilation_output.native_code_program.code)
    assert metadata["code_sha256"] == hashlib.sha256(result.compilation_output.native_code_program.code).hexdigest()
    assert metadata["symbols"][0]["is_entry"] is True


def test_run_source_file_self_checks_emitted_native_bin_and_map(tmp_path, monkeypatch):
    source_path = tmp_path / "native_emit_bin_map_self_check.vbc"
    bin_path = tmp_path / "native_emit_bin_map_self_check.bin"
    map_path = tmp_path / "native_emit_bin_map_self_check.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    program_validator = Mock(side_effect=validate_native_code_program_map)
    raw_validator = Mock(side_effect=validate_native_code_map_bytes)
    monkeypatch.setattr("verbose_c.compiler.native.validate_native_code_program_map", program_validator)
    monkeypatch.setattr("verbose_c.compiler.native.validate_native_code_map_bytes", raw_validator)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_bin_map_self_check.vbb"),
        execute=False,
        native_export_request=_native_export_request(raw_binary=bin_path, map=map_path),
    )

    assert result.success
    assert bin_path.read_bytes()
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    program_validator.assert_called_once()
    raw_validator.assert_called_once_with(bin_path.read_bytes(), metadata)


def test_run_source_file_reports_emitted_native_bin_map_self_check_failure(tmp_path, monkeypatch):
    source_path = tmp_path / "native_emit_bin_map_self_check_bad.vbc"
    bin_path = tmp_path / "native_emit_bin_map_self_check_bad.bin"
    map_path = tmp_path / "native_emit_bin_map_self_check_bad.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "verbose_c.compiler.native.validate_native_code_map_bytes",
        Mock(side_effect=NativeCodegenError("故意的 raw/map 错配")),
    )

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_bin_map_self_check_bad.vbb"),
        execute=False,
        native_export_request=_native_export_request(raw_binary=bin_path, map=map_path),
    )

    assert not result.success
    assert result.error is not None
    assert "导出 x64 原始机器码与 map 自检失败" in str(result.error)
    assert "故意的 raw/map 错配" in str(result.error)


def test_run_source_file_can_emit_native_text_section_bin(tmp_path):
    source_path = tmp_path / "native_emit_text_section_bin.vbc"
    text_bin_path = tmp_path / "nested" / "native_emit_text_section.bin"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_text_section_bin.vbb"),
        execute=False,
        native_export_request=_native_export_request(text_section=text_bin_path),
    )

    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    raw_size_aligned = ((len(program.code) + 511) // 512) * 512
    expected_text_raw = program.code + bytes(raw_size_aligned - len(program.code))
    assert text_bin_path.read_bytes() == expected_text_raw


def test_run_source_file_self_checks_emitted_native_text_bin_and_map(tmp_path, monkeypatch):
    source_path = tmp_path / "native_emit_text_bin_map_self_check.vbc"
    text_bin_path = tmp_path / "native_emit_text_bin_map_self_check.bin"
    map_path = tmp_path / "native_emit_text_bin_map_self_check.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    text_validator = Mock(side_effect=validate_native_text_section_map_bytes)
    monkeypatch.setattr("verbose_c.compiler.native.validate_native_text_section_map_bytes", text_validator)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_text_bin_map_self_check.vbb"),
        execute=False,
        native_export_request=_native_export_request(text_section=text_bin_path, map=map_path),
    )

    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    assert text_validator.call_count == 2
    text_validator.assert_called_with(text_bin_path.read_bytes(), metadata)


def test_run_source_file_reports_emitted_native_text_bin_map_self_check_failure(tmp_path, monkeypatch):
    source_path = tmp_path / "native_emit_text_bin_map_self_check_bad.vbc"
    text_bin_path = tmp_path / "native_emit_text_bin_map_self_check_bad.bin"
    map_path = tmp_path / "native_emit_text_bin_map_self_check_bad.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    text_validator = Mock(side_effect=[None, NativeCodegenError("故意的 text/map 错配")])
    monkeypatch.setattr("verbose_c.compiler.native.validate_native_text_section_map_bytes", text_validator)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_text_bin_map_self_check_bad.vbb"),
        execute=False,
        native_export_request=_native_export_request(text_section=text_bin_path, map=map_path),
    )

    assert not result.success
    assert result.error is not None
    assert "导出 PE .text raw section 与 map 自检失败" in str(result.error)
    assert "故意的 text/map 错配" in str(result.error)


def test_run_source_file_can_emit_native_pe_image(tmp_path):
    source_path = tmp_path / "native_emit_pe.vbc"
    pe_path = tmp_path / "nested" / "native_emit_pe.exe"
    map_path = tmp_path / "nested" / "native_emit_pe.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )

    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    pe_image = pe_path.read_bytes()
    validate_native_pe_image_bytes(pe_image, metadata)
    assert pe_image[:2] == b"MZ"
    assert pe_image[metadata["pe_lfanew"]:metadata["pe_lfanew"] + 4] == b"PE\x00\x00"


def test_run_source_file_self_checks_emitted_native_pe_and_map(tmp_path, monkeypatch):
    source_path = tmp_path / "native_emit_pe_map_self_check.vbc"
    pe_path = tmp_path / "native_emit_pe_map_self_check.exe"
    map_path = tmp_path / "native_emit_pe_map_self_check.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    pe_validator = Mock(side_effect=validate_native_pe_image_bytes)
    monkeypatch.setattr("verbose_c.compiler.native.validate_native_pe_image_bytes", pe_validator)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_map_self_check.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )

    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    assert pe_validator.call_count == 2
    pe_validator.assert_called_with(pe_path.read_bytes(), metadata)


def test_run_source_file_reports_emitted_native_pe_map_self_check_failure(tmp_path, monkeypatch):
    source_path = tmp_path / "native_emit_pe_map_self_check_bad.vbc"
    pe_path = tmp_path / "native_emit_pe_map_self_check_bad.exe"
    map_path = tmp_path / "native_emit_pe_map_self_check_bad.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    pe_validator = Mock(side_effect=[None, NativeCodegenError("故意的 pe/map 错配")])
    monkeypatch.setattr("verbose_c.compiler.native.validate_native_pe_image_bytes", pe_validator)

    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_emit_pe_map_self_check_bad.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )

    assert not result.success
    assert result.error is not None
    assert "导出最小 PE image 与 map 自检失败" in str(result.error)
    assert "故意的 pe/map 错配" in str(result.error)


def test_cli_emit_asm_writes_native_listing(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_asm.vbc"
    export_dir = tmp_path / "native_cli_emit_asm_exports"
    asm_path = export_dir / "native_cli_emit_asm.native.md"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-listing",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_asm.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "mov rax, 7" in asm_path.read_text(encoding="utf-8")


def test_cli_emit_native_bin_writes_raw_machine_code(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_bin.vbc"
    export_dir = tmp_path / "native_cli_emit_bin_exports"
    bin_path = export_dir / "native_cli_emit_bin.native.bin"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-bin",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_bin.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    raw = bin_path.read_bytes()
    assert raw
    assert bytes.fromhex("48 B8 07 00 00 00 00 00 00 00") in raw


def test_cli_emit_native_text_bin_writes_padded_text_section(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_text_bin.vbc"
    export_dir = tmp_path / "native_cli_emit_text_bin_exports"
    text_bin_path = export_dir / "native_cli_emit_text_bin.text.bin"
    map_path = export_dir / "native_cli_emit_text_bin.native.map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-text-bin,native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_text_bin.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    text_raw = text_bin_path.read_bytes()
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    text_section = metadata["sections"][0]
    assert len(text_raw) == text_section["raw_size_aligned"]
    assert text_raw[:metadata["code_size"]]
    assert text_raw[metadata["code_size"]:] == bytes(text_section["raw_padding_size"])
    assert hashlib.sha256(text_raw).hexdigest() == text_section["raw_padded_sha256"]


def test_cli_emit_native_pe_writes_minimal_pe_image(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_pe.vbc"
    export_dir = tmp_path / "native_cli_emit_pe_exports"
    pe_path = export_dir / "native_cli_emit_pe.exe"
    map_path = export_dir / "native_cli_emit_pe.native.map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-pe,native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_pe.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    pe_image = pe_path.read_bytes()
    validate_native_pe_image_bytes(pe_image, metadata)
    assert pe_image[:2] == b"MZ"
    assert pe_image[metadata["pe_lfanew"]:metadata["pe_lfanew"] + 4] == b"PE\x00\x00"


@pytest.mark.skipif(not native_runner_module.can_run_native_memory(), reason="仅 Windows x64 支持运行生成的 PE image")
def test_cli_emit_native_pe_image_runs_as_windows_process(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_pe_run.vbc"
    export_dir = tmp_path / "native_cli_emit_pe_run_exports"
    pe_path = export_dir / "native_cli_emit_pe_run.exe"
    map_path = export_dir / "native_cli_emit_pe_run.native.map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-pe,native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_pe_run.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    validate_native_pe_image_bytes(pe_path.read_bytes(), metadata)
    completed = subprocess.run([str(pe_path)], check=False)
    assert completed.returncode == 7


@pytest.mark.skipif(not native_runner_module.can_run_native_memory(), reason="仅 Windows x64 支持运行生成的 PE image")
def test_cli_emit_native_pe_image_runs_imod_adjustment_as_windows_process(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_pe_run_imod.vbc"
    export_dir = tmp_path / "native_cli_emit_pe_run_imod_exports"
    pe_path = export_dir / "native_cli_emit_pe_run_imod.exe"
    map_path = export_dir / "native_cli_emit_pe_run_imod.native.map.json"
    source_path.write_text(
        "int main() {\n"
        "    int a = -5;\n"
        "    int b = 2;\n"
        "    int c = 5;\n"
        "    int d = -2;\n"
        "    int e = -5;\n"
        "    int f = -2;\n"
        "    return (a % b) * 100 + (c % d) * 10 + (e % f);\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-pe,native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_pe_run_imod.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    relocation_kinds = {
        relocation["kind"]
        for function in metadata["functions"]
        for relocation in function["relocations"]
    }
    assert {"je_rel32", "jns_rel32"} <= relocation_kinds
    validate_native_pe_image_bytes(pe_path.read_bytes(), metadata)
    completed = subprocess.run([str(pe_path)], check=False)
    assert completed.returncode == 89


def test_cli_emit_native_map_writes_json(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_map.vbc"
    export_dir = tmp_path / "native_cli_emit_map_exports"
    map_path = export_dir / "native_cli_emit_map.native.map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_map.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    assert metadata["entry"] == "<module>"
    assert metadata["code_size"] > 0
    assert len(metadata["code_sha256"]) == 64


def test_cli_check_native_map_accepts_matching_files(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_map.vbc"
    bin_path = tmp_path / "native_cli_check_map.bin"
    map_path = tmp_path / "native_cli_check_map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_map.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    bin_path.write_bytes(program.code)
    map_path.write_text(json.dumps(native_code_program_map(program), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--check-native-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native map 校验通过" in capsys.readouterr().out


def test_cli_check_native_map_accepts_imod_adjustment_relocations(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_map_imod.vbc"
    bin_path = tmp_path / "native_cli_check_map_imod.bin"
    map_path = tmp_path / "native_cli_check_map_imod.json"
    source_path.write_text(
        "int main() {\n"
        "    int a = -5;\n"
        "    int b = 2;\n"
        "    return a % b;\n"
        "}\n",
        encoding="utf-8",
    )
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_map_imod.vbb"),
        execute=False,
        native_export_request=_native_export_request(raw_binary=bin_path, map=map_path),
    )
    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    relocation_kinds = {
        relocation["kind"]
        for function in metadata["functions"]
        for relocation in function["relocations"]
    }
    assert {"je_rel32", "jns_rel32"} <= relocation_kinds
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--check-native-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native map 校验通过" in capsys.readouterr().out


def test_cli_check_native_map_reports_missing_map_path(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    bin_path = tmp_path / "native_cli_missing_map.bin"
    map_path = tmp_path / "native_cli_missing_map.json"
    bin_path.write_bytes(b"\xC3")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--check-native-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert f"错误: 文件 '{map_path}' 不存在" in output


@pytest.mark.parametrize(
    "option_name",
    [
        "--check-native-map",
        "--check-native-text-map",
        "--check-native-pe-map",
        "--run-native-pe-file",
        "--run-native-bin-memory",
        "--run-native-text-bin-memory",
    ],
)
def test_cli_native_file_entries_report_missing_map_path(tmp_path, monkeypatch, capsys, option_name):
    from verbose_c import cli

    artifact_path = tmp_path / f"{option_name[2:].replace('-', '_')}.bin"
    map_path = tmp_path / f"{option_name[2:].replace('-', '_')}.json"
    artifact_path.write_bytes(b"\xC3")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(artifact_path), option_name, str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert f"错误: 文件 '{map_path}' 不存在" in output


def test_run_native_bin_memory_file_reports_missing_bin_path(tmp_path, capsys):
    from verbose_c.cli import _run_native_bin_memory_file

    bin_path = tmp_path / "native_cli_missing_raw.bin"
    map_path = tmp_path / "native_cli_missing_raw.json"
    map_path.write_text("{}", encoding="utf-8")

    success, exit_code = _run_native_bin_memory_file(str(bin_path), str(map_path), None)

    assert not success
    assert exit_code == 1
    output = capsys.readouterr().out
    assert f"错误: 文件 '{bin_path}' 不存在" in output


def test_cli_check_native_text_map_accepts_matching_text_section(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_text_map.vbc"
    text_bin_path = tmp_path / "native_cli_check_text_map.text.bin"
    map_path = tmp_path / "native_cli_check_text_map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_text_map.vbb"),
        execute=False,
        native_export_request=_native_export_request(text_section=text_bin_path, map=map_path),
    )
    assert result.success
    monkeypatch.setattr("sys.argv", ["verbose-c", str(text_bin_path), "--check-native-text-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native .text map 校验通过" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("export_kind", "check_option", "suffix", "success_message"),
    [
        ("text_section", "--check-native-text-map", ".text.bin", "native .text map 校验通过"),
        ("pe_image", "--check-native-pe-map", ".exe", "native PE map 校验通过"),
    ],
)
def test_cli_check_native_container_maps_accept_imod_adjustment_relocations(
    tmp_path,
    monkeypatch,
    capsys,
    export_kind,
    check_option,
    suffix,
    success_message,
):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_container_imod.vbc"
    artifact_path = tmp_path / f"native_cli_check_container_imod{suffix}"
    map_path = tmp_path / "native_cli_check_container_imod.json"
    source_path.write_text(
        "int main() {\n"
        "    int a = 5;\n"
        "    int b = -2;\n"
        "    return a % b;\n"
        "}\n",
        encoding="utf-8",
    )
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_container_imod.vbb"),
        execute=False,
        native_export_request=_native_export_request(map=map_path, **{export_kind: artifact_path}),
    )
    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    relocation_kinds = {
        relocation["kind"]
        for function in metadata["functions"]
        for relocation in function["relocations"]
    }
    assert {"je_rel32", "jns_rel32"} <= relocation_kinds
    monkeypatch.setattr("sys.argv", ["verbose-c", str(artifact_path), check_option, str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert success_message in capsys.readouterr().out


def test_cli_check_native_text_map_rejects_bad_padding(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_text_map_bad_padding.vbc"
    text_bin_path = tmp_path / "native_cli_check_text_map_bad_padding.text.bin"
    map_path = tmp_path / "native_cli_check_text_map_bad_padding.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_text_map_bad_padding.vbb"),
        execute=False,
        native_export_request=_native_export_request(text_section=text_bin_path, map=map_path),
    )
    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    assert metadata["sections"][0]["raw_padding_size"] > 0
    text_raw = bytearray(text_bin_path.read_bytes())
    text_raw[-1] = 1
    text_bin_path.write_bytes(bytes(text_raw))
    monkeypatch.setattr("sys.argv", ["verbose-c", str(text_bin_path), "--check-native-text-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "native .text map 校验失败" in output
    assert "尾部补零区域不一致" in output


def test_cli_check_native_pe_map_accepts_matching_pe_image(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_pe_map.vbc"
    pe_path = tmp_path / "native_cli_check_pe_map.exe"
    map_path = tmp_path / "native_cli_check_pe_map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_pe_map.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )
    assert result.success
    monkeypatch.setattr("sys.argv", ["verbose-c", str(pe_path), "--check-native-pe-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native PE map 校验通过" in capsys.readouterr().out


def test_cli_check_native_pe_map_rejects_bad_signature(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_pe_map_bad_signature.vbc"
    pe_path = tmp_path / "native_cli_check_pe_map_bad_signature.exe"
    map_path = tmp_path / "native_cli_check_pe_map_bad_signature.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_pe_map_bad_signature.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )
    assert result.success
    pe_image = bytearray(pe_path.read_bytes())
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    pe_image[metadata["pe_lfanew"]] = 0
    pe_path.write_bytes(bytes(pe_image))
    monkeypatch.setattr("sys.argv", ["verbose-c", str(pe_path), "--check-native-pe-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "native PE map 校验失败" in output
    assert "PE signature 不一致" in output


def test_cli_run_native_pe_file_executes_checked_pe_image(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_pe_file.vbc"
    pe_path = tmp_path / "native_cli_run_pe_file.exe"
    map_path = tmp_path / "native_cli_run_pe_file.json"
    result_path = tmp_path / "nested" / "native_cli_run_pe_file_result.txt"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_pe_file.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )
    assert result.success
    monkeypatch.setattr("verbose_c.compiler.native.runner.can_run_native_memory", lambda: True)
    monkeypatch.setattr(
        "verbose_c.cli.subprocess.run",
        lambda args, check: subprocess.CompletedProcess(args, 300),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(pe_path),
            "--run-native-pe-file",
            str(map_path),
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert result_path.read_text(encoding="utf-8") == "300\n"
    assert "native PE 文件入口返回值: 300" in capsys.readouterr().out


def test_cli_run_native_pe_file_rejects_bad_signature(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_pe_file_bad_signature.vbc"
    pe_path = tmp_path / "native_cli_run_pe_file_bad_signature.exe"
    map_path = tmp_path / "native_cli_run_pe_file_bad_signature.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_pe_file_bad_signature.vbb"),
        execute=False,
        native_export_request=_native_export_request(pe_image=pe_path, map=map_path),
    )
    assert result.success
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    pe_image = bytearray(pe_path.read_bytes())
    pe_image[metadata["pe_lfanew"]] = 0
    pe_path.write_bytes(bytes(pe_image))
    monkeypatch.setattr("verbose_c.compiler.native.runner.can_run_native_memory", lambda: True)
    pe_runner = Mock(return_value=subprocess.CompletedProcess([str(pe_path)], 300))
    monkeypatch.setattr("verbose_c.cli.subprocess.run", pe_runner)
    monkeypatch.setattr("sys.argv", ["verbose-c", str(pe_path), "--run-native-pe-file", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    pe_runner.assert_not_called()
    assert "native PE 文件执行失败" in output
    assert "PE signature 不一致" in output


def test_cli_run_native_bin_memory_executes_matching_raw_bin(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_raw_bin.vbc"
    bin_path = tmp_path / "native_cli_run_raw_bin.bin"
    map_path = tmp_path / "native_cli_run_raw_bin.json"
    result_path = tmp_path / "nested" / "native_cli_run_raw_bin_result.txt"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_raw_bin.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    bin_path.write_bytes(program.code)
    map_path.write_text(json.dumps(native_code_program_map(program), ensure_ascii=False), encoding="utf-8")
    raw_runner = Mock(return_value=300)
    monkeypatch.setattr(native_runner_module, "_run_code_in_memory", raw_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bin_path),
            "--run-native-bin-memory",
            str(map_path),
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    raw_runner.assert_called_once_with(program.code, program.entry_offset)
    assert result_path.read_text(encoding="utf-8") == "300\n"
    assert "native raw bin 入口返回值: 300" in capsys.readouterr().out


def test_cli_run_native_bin_memory_rejects_mismatched_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_raw_bin_bad_map.vbc"
    bin_path = tmp_path / "native_cli_run_raw_bin_bad_map.bin"
    map_path = tmp_path / "native_cli_run_raw_bin_bad_map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_raw_bin_bad_map.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["code_size"] += 1
    bin_path.write_bytes(program.code)
    map_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    raw_runner = Mock(return_value=300)
    monkeypatch.setattr(native_runner_module, "_run_code_in_memory", raw_runner)
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--run-native-bin-memory", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    raw_runner.assert_not_called()
    output = capsys.readouterr().out
    assert "native raw bin 内存执行失败" in output
    assert "字段 code_size 不一致" in output


@pytest.mark.parametrize(
    ("option_name", "artifact_suffix", "message"),
    [
        ("--run-native-bin-memory", ".bin", "native raw bin 入口返回值: 89"),
        ("--run-native-text-bin-memory", ".text.bin", "native .text 入口返回值: 89"),
    ],
)
def test_cli_run_native_file_memory_accepts_imod_adjustment_relocations(
    tmp_path,
    monkeypatch,
    capsys,
    option_name,
    artifact_suffix,
    message,
):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_file_memory_imod.vbc"
    artifact_path = tmp_path / f"native_cli_run_file_memory_imod{artifact_suffix}"
    map_path = tmp_path / "native_cli_run_file_memory_imod.json"
    result_path = tmp_path / "nested" / "native_cli_run_file_memory_imod_result.txt"
    source_path.write_text(
        "int main() {\n"
        "    int a = -5;\n"
        "    int b = 2;\n"
        "    int c = 5;\n"
        "    int d = -2;\n"
        "    int e = -5;\n"
        "    int f = -2;\n"
        "    return (a % b) * 100 + (c % d) * 10 + (e % f);\n"
        "}\n",
        encoding="utf-8",
    )
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_file_memory_imod.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    relocation_kinds = {
        relocation["kind"]
        for function in metadata["functions"]
        for relocation in function["relocations"]
    }
    assert {"je_rel32", "jns_rel32"} <= relocation_kinds
    if option_name == "--run-native-bin-memory":
        artifact_path.write_bytes(program.code)
    else:
        artifact_path.write_bytes(program.code + bytes(metadata["sections"][0]["raw_padding_size"]))
    map_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    runner = Mock(return_value=89)
    monkeypatch.setattr(native_runner_module, "_run_code_in_memory", runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(artifact_path),
            option_name,
            str(map_path),
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    runner.assert_called_once_with(program.code, program.entry_offset)
    assert result_path.read_text(encoding="utf-8") == "89\n"
    assert message in capsys.readouterr().out


def test_cli_run_native_text_bin_memory_executes_matching_text_section(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_text_bin.vbc"
    text_bin_path = tmp_path / "native_cli_run_text_bin.text.bin"
    map_path = tmp_path / "native_cli_run_text_bin.json"
    result_path = tmp_path / "nested" / "native_cli_run_text_bin_result.txt"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_text_bin.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    text_section = metadata["sections"][0]
    text_raw = program.code + bytes(text_section["raw_padding_size"])
    text_bin_path.write_bytes(text_raw)
    map_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    text_runner = Mock(return_value=300)
    monkeypatch.setattr(native_runner_module, "_run_code_in_memory", text_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(text_bin_path),
            "--run-native-text-bin-memory",
            str(map_path),
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    text_runner.assert_called_once_with(program.code, program.entry_offset)
    assert result_path.read_text(encoding="utf-8") == "300\n"
    assert "native .text 入口返回值: 300" in capsys.readouterr().out


def test_cli_run_native_text_bin_memory_rejects_bad_padding(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_run_text_bin_bad_padding.vbc"
    text_bin_path = tmp_path / "native_cli_run_text_bin_bad_padding.text.bin"
    map_path = tmp_path / "native_cli_run_text_bin_bad_padding.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_run_text_bin_bad_padding.vbb"),
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
    text_bin_path.write_bytes(bytes(text_raw))
    map_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    text_runner = Mock(return_value=300)
    monkeypatch.setattr(native_runner_module, "_run_code_in_memory", text_runner)
    monkeypatch.setattr("sys.argv", ["verbose-c", str(text_bin_path), "--run-native-text-bin-memory", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    text_runner.assert_not_called()
    output = capsys.readouterr().out
    assert "native .text 内存执行失败" in output
    assert "尾部补零区域不一致" in output


def test_cli_check_native_map_rejects_mismatched_files(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_bad_map.vbc"
    bin_path = tmp_path / "native_cli_check_bad_map.bin"
    map_path = tmp_path / "native_cli_check_bad_map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_bad_map.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    bin_path.write_bytes(program.code + b"\x90")
    map_path.write_text(json.dumps(native_code_program_map(program), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--check-native-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "native map 校验失败" in output
    assert "字段 code_size 不一致" in output


def test_cli_check_native_map_rejects_target_mismatch(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_target_bad.vbc"
    bin_path = tmp_path / "native_cli_check_target_bad.bin"
    map_path = tmp_path / "native_cli_check_target_bad.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_target_bad.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    metadata = native_code_program_map(program)
    metadata["target"] = "linux-x64"
    bin_path.write_bytes(program.code)
    map_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--check-native-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "native map 校验失败" in output
    assert "字段 target 必须为 'windows-x64'" in output


def test_cli_check_native_map_accepts_utf8_bom_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_check_bom_map.vbc"
    bin_path = tmp_path / "native_cli_check_bom_map.bin"
    map_path = tmp_path / "native_cli_check_bom_map.json"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "native_cli_check_bom_map.vbb"),
        execute=False,
    )
    assert result.success
    assert result.compilation_output is not None
    program = result.compilation_output.native_code_program
    assert program is not None
    bin_path.write_bytes(program.code)
    map_path.write_bytes(("\ufeff" + json.dumps(native_code_program_map(program), ensure_ascii=False)).encode("utf-8"))
    monkeypatch.setattr("sys.argv", ["verbose-c", str(bin_path), "--check-native-map", str(map_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert "native map 校验通过" in capsys.readouterr().out


def test_cli_emit_asm_reports_native_codegen_failure(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_asm_unsupported.vbc"
    export_dir = tmp_path / "native_cli_emit_asm_unsupported_exports"
    asm_path = export_dir / "native_cli_emit_asm_unsupported.native.md"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-listing",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_asm_unsupported.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert f"编译错误: 文件 {source_path}" in output
    assert "native MVP 暂不支持特性 'array'" in output
    assert not asm_path.exists()


def test_cli_emit_native_bin_reports_native_codegen_failure(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_bin_unsupported.vbc"
    export_dir = tmp_path / "native_cli_emit_bin_unsupported_exports"
    bin_path = export_dir / "native_cli_emit_bin_unsupported.native.bin"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-bin",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_bin_unsupported.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert f"编译错误: 文件 {source_path}" in output
    assert "native MVP 暂不支持特性 'array'" in output
    assert not bin_path.exists()


def test_cli_emit_native_map_reports_native_codegen_failure(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_map_unsupported.vbc"
    export_dir = tmp_path / "native_cli_emit_map_unsupported_exports"
    map_path = export_dir / "native_cli_emit_map_unsupported.native.map.json"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-map",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_map_unsupported.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert f"编译错误: 文件 {source_path}" in output
    assert "native MVP 暂不支持特性 'array'" in output
    assert not map_path.exists()


def test_cli_emit_native_text_bin_reports_native_codegen_failure(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_emit_text_bin_unsupported.vbc"
    export_dir = tmp_path / "native_cli_emit_text_bin_unsupported_exports"
    text_bin_path = export_dir / "native_cli_emit_text_bin_unsupported.text.bin"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(source_path),
            "--compile-only",
            "--emit",
            "native-text-bin",
            "--emit-dir",
            str(export_dir),
            "-o",
            str(tmp_path / "native_cli_emit_text_bin_unsupported.vbb"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert f"编译错误: 文件 {source_path}" in output
    assert "native MVP 暂不支持特性 'array'" in output
    assert not text_bin_path.exists()


def test_cli_rejects_compile_parser_with_native_memory(monkeypatch, capsys):
    from verbose_c import cli

    monkeypatch.setattr("sys.argv", ["verbose-c", "Grammar/verbose_c.gram", "--compile-parser", "--run-native-memory"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-parser 不能与 --run-native-memory 同时使用" in capsys.readouterr().out


def test_cli_rejects_compile_only_with_native_memory(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_compile_only.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(source_path), "--compile-only", "--run-native-memory"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-only 不能与 --run-native-memory 同时使用" in capsys.readouterr().out


def test_cli_rejects_native_result_without_native_memory(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_result_without_run.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(source_path), "--native-result", str(tmp_path / "native_result.txt")],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--native-result 必须与 --run-native-memory、--run-native-pe、--run-native-pe-file、--run-native-bin-memory 或 --run-native-text-bin-memory 同时使用" in capsys.readouterr().out


def test_cli_rejects_native_zero_exit_without_native_memory(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_zero_exit_without_run.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verbose-c", str(source_path), "--native-zero-exit-code"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--native-zero-exit-code 必须与 --run-native-memory、--run-native-pe、--run-native-pe-file、--run-native-bin-memory 或 --run-native-text-bin-memory 同时使用" in capsys.readouterr().out


def test_cli_help_mentions_bytecode_native_input(monkeypatch, capsys):
    from verbose_c import cli

    monkeypatch.setattr("sys.argv", ["verbose-c", "-h"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert ".vbb 字节码" in output
    assert "raw native bin" in output
    assert "PE .text raw section" in output
    assert "最小 PE image" in output
    assert "源码或 .vbb" in output
    assert "--run-native-memory" in output
    assert "--run-native-pe" in output
    assert "--run-native-pe-file" in output
    assert "--run-native-bin-memory" in output
    assert "--run-native-text-bin-memory" in output
    assert "--emit KINDS" in output
    assert "--emit-dir" in output
    assert "native-bundle" in output
    assert "--check-native-text-map" in output
    assert "--check-native-pe-map" in output


def test_run_bytecode_file_can_generate_native_code_from_vbb(tmp_path):
    source_path = tmp_path / "native_bytecode_input.vbc"
    bytecode_path = tmp_path / "native_bytecode_input.vbb"
    dump_path = tmp_path / "native_bytecode_input_dump.md"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )

    result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules={"machine"},
        dump_path=str(dump_path),
        run_native_memory=False,
        native_export_request=_native_export_request(listing=tmp_path / "native_bytecode_input.asm"),
    )

    assert compile_result.success
    assert result.success
    assert result.compilation_output.native_code_program is not None
    dump_text = dump_path.read_text(encoding="utf-8")
    assert "Machine IR" in dump_text
    assert "x64 机器码" in dump_text
    assert "x64 机器码" in (tmp_path / "native_bytecode_input.asm").read_text(encoding="utf-8")


def test_cli_runs_native_memory_from_bytecode_input(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_bytecode.vbc"
    bytecode_path = tmp_path / "native_cli_bytecode.vbb"
    result_path = tmp_path / "native_cli_bytecode_result.txt"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    monkeypatch.setattr("verbose_c.compiler.native.runner.run_native_program_in_memory", Mock(return_value=42))
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bytecode_path),
            "--run-native-memory",
            "--native-result",
            str(result_path),
            "--native-zero-exit-code",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert compile_result.success
    assert exc_info.value.code == 0
    assert "native 入口返回值: 42" in capsys.readouterr().out
    assert result_path.read_text(encoding="utf-8") == "42\n"


def test_run_bytecode_file_preserves_bool_parameter_types_for_native(tmp_path):
    if not can_run_native_memory():
        pytest.skip("native 内存执行仅支持 Windows x64")
    source_path = tmp_path / "native_bytecode_bool_param.vbc"
    bytecode_path = tmp_path / "native_bytecode_bool_param.vbb"
    source_path.write_text(
        "bool identity(bool value) {\n"
        "    return value;\n"
        "}\n\n"
        "int main() {\n"
        "    if (identity(true)) {\n"
        "        return 42;\n"
        "    }\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )

    result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
        run_native_memory=True,
    )

    assert compile_result.success
    assert result.success
    assert result.exit_code == 42


def test_cli_emits_native_bin_and_map_from_bytecode_input(tmp_path, monkeypatch):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_bytecode_emit.vbc"
    bytecode_path = tmp_path / "native_cli_bytecode_emit.vbb"
    export_dir = tmp_path / "native_cli_bytecode_emit_exports"
    bin_path = export_dir / "native_cli_bytecode_emit.native.bin"
    map_path = export_dir / "native_cli_bytecode_emit.native.map.json"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bytecode_path),
            "--emit",
            "native-bin,native-map",
            "--emit-dir",
            str(export_dir),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert compile_result.success
    assert exc_info.value.code == 42
    assert bin_path.read_bytes()
    metadata = json.loads(map_path.read_text(encoding="utf-8"))
    assert metadata["code_size"] == len(bin_path.read_bytes())


def test_cli_dumps_machine_and_emits_asm_from_bytecode_input(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    from verbose_c import cli

    source_path = tmp_path / "native_cli_bytecode_dump.vbc"
    bytecode_path = tmp_path / "native_cli_bytecode_dump.vbb"
    export_dir = tmp_path / "native_cli_bytecode_dump_exports"
    asm_path = export_dir / "native_cli_bytecode_dump.native.md"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bytecode_path),
            "--dump",
            "machine",
            "--emit",
            "native-listing",
            "--emit-dir",
            str(export_dir),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert compile_result.success
    assert exc_info.value.code == 42
    output = capsys.readouterr().out
    dump_path = Path(output.rsplit("运行记录已保存到：", 1)[1].strip().splitlines()[0])
    dump_text = dump_path.read_text(encoding="utf-8")
    asm_text = asm_path.read_text(encoding="utf-8")
    assert "Machine IR" in dump_text
    assert "x64 机器码" in dump_text
    assert "x64 机器码" in asm_text
    assert "mov rax, 42" in asm_text
    dump_path.unlink()


def test_cli_rejects_compile_parser_with_emit(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            "Grammar/verbose_c.gram",
            "--compile-parser",
            "--emit",
            "native-listing",
            "--emit-dir",
            str(tmp_path / "parser_exports"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-parser 不能与 --emit 同时使用" in capsys.readouterr().out


def test_cli_rejects_compile_parser_with_run_native_pe(monkeypatch, capsys):
    from verbose_c import cli

    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", "Grammar/verbose_c.gram", "--compile-parser", "--run-native-pe"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-parser 不能与 --run-native-pe 同时使用" in capsys.readouterr().out


def test_cli_rejects_compile_only_with_run_native_pe(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_compile_only_pe.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(source_path), "--compile-only", "--run-native-pe"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-only 不能与 --run-native-pe 同时使用" in capsys.readouterr().out


def test_cli_rejects_run_native_memory_with_run_native_pe(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    source_path = tmp_path / "native_cli_memory_pe_combo.vbc"
    source_path.write_text("int main() {\n    return 42;\n}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(source_path), "--run-native-memory", "--run-native-pe"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--run-native-memory 不能与 --run-native-pe 同时使用" in capsys.readouterr().out


def test_cli_rejects_compile_parser_with_check_native_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    map_path = tmp_path / "parser.json"
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", "Grammar/verbose_c.gram", "--compile-parser", "--check-native-map", str(map_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-parser 不能与 --check-native-map 同时使用" in capsys.readouterr().out


def test_cli_rejects_compile_parser_with_check_native_text_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    map_path = tmp_path / "parser.json"
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", "Grammar/verbose_c.gram", "--compile-parser", "--check-native-text-map", str(map_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-parser 不能与 --check-native-text-map 同时使用" in capsys.readouterr().out


def test_cli_rejects_compile_parser_with_check_native_pe_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    map_path = tmp_path / "parser.json"
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", "Grammar/verbose_c.gram", "--compile-parser", "--check-native-pe-map", str(map_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--compile-parser 不能与 --check-native-pe-map 同时使用" in capsys.readouterr().out


def test_cli_rejects_check_native_map_with_check_native_text_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    bin_path = tmp_path / "native_check_combo.bin"
    map_path = tmp_path / "native_check_combo.json"
    bin_path.write_bytes(b"\xC3")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bin_path),
            "--check-native-map",
            str(map_path),
            "--check-native-text-map",
            str(map_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--check-native-map 不能与 --check-native-text-map 同时使用" in capsys.readouterr().out


def test_cli_rejects_check_native_map_with_check_native_pe_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    bin_path = tmp_path / "native_check_pe_combo.bin"
    map_path = tmp_path / "native_check_pe_combo.json"
    bin_path.write_bytes(b"\xC3")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bin_path),
            "--check-native-map",
            str(map_path),
            "--check-native-pe-map",
            str(map_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--check-native-map 不能与 --check-native-pe-map 同时使用" in capsys.readouterr().out


def test_cli_rejects_check_native_text_map_with_check_native_pe_map(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    bin_path = tmp_path / "native_check_text_pe_combo.bin"
    map_path = tmp_path / "native_check_text_pe_combo.json"
    bin_path.write_bytes(b"\xC3")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bin_path),
            "--check-native-text-map",
            str(map_path),
            "--check-native-pe-map",
            str(map_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--check-native-text-map 不能与 --check-native-pe-map 同时使用" in capsys.readouterr().out


def test_cli_rejects_run_native_bin_memory_with_run_native_text_bin_memory(tmp_path, monkeypatch, capsys):
    from verbose_c import cli

    bin_path = tmp_path / "native_run_combo.bin"
    map_path = tmp_path / "native_run_combo.json"
    bin_path.write_bytes(b"\xC3")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "verbose-c",
            str(bin_path),
            "--run-native-bin-memory",
            str(map_path),
            "--run-native-text-bin-memory",
            str(map_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "--run-native-text-bin-memory 不能与 --run-native-bin-memory 同时使用" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--compile-only"], "--compile-only 不能与 --check-native-map 同时使用"),
        (["--run-native-memory"], "--run-native-memory 不能与 --check-native-map 同时使用"),
        (["--run-native-pe"], "--run-native-pe 不能与 --check-native-map 同时使用"),
        (["--run-native-pe-file", "native.json"], "--run-native-pe-file 不能与 --check-native-map 同时使用"),
        (["--run-native-bin-memory", "native.json"], "--run-native-bin-memory 不能与 --check-native-map 同时使用"),
        (["--run-native-text-bin-memory", "native.json"], "--run-native-text-bin-memory 不能与 --check-native-map 同时使用"),
        (["--native-result", "native_result.txt"], "--native-result 不能与 --check-native-map 同时使用"),
        (["--native-zero-exit-code"], "--native-zero-exit-code 不能与 --check-native-map 同时使用"),
        (["--emit", "native-bundle", "--emit-dir", "exports"], "--emit 不能与 --check-native-map 同时使用"),
        (["-o", "native.vbb"], "-o/--output 不能与 --check-native-map 同时使用"),
        (["-rp"], "-rp/--refresh-parser 不能与 --check-native-map 同时使用"),
    ],
)
def test_cli_rejects_check_native_map_with_compile_or_emit_options(tmp_path, monkeypatch, capsys, extra_args, message):
    from verbose_c import cli

    bin_path = tmp_path / "native_check_combo.bin"
    map_path = tmp_path / "native_check_combo.json"
    bin_path.write_bytes(b"\xC3")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(bin_path), "--check-native-map", str(map_path), *extra_args],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--compile-only"], "--compile-only 不能与 --check-native-text-map 同时使用"),
        (["--run-native-memory"], "--run-native-memory 不能与 --check-native-text-map 同时使用"),
        (["--run-native-pe"], "--run-native-pe 不能与 --check-native-text-map 同时使用"),
        (["--run-native-pe-file", "native.json"], "--run-native-pe-file 不能与 --check-native-text-map 同时使用"),
        (["--run-native-bin-memory", "native.json"], "--run-native-bin-memory 不能与 --check-native-text-map 同时使用"),
        (["--run-native-text-bin-memory", "native.json"], "--run-native-text-bin-memory 不能与 --check-native-text-map 同时使用"),
        (["--native-result", "native_result.txt"], "--native-result 不能与 --check-native-text-map 同时使用"),
        (["--native-zero-exit-code"], "--native-zero-exit-code 不能与 --check-native-text-map 同时使用"),
        (["--emit", "native-bundle", "--emit-dir", "exports"], "--emit 不能与 --check-native-text-map 同时使用"),
        (["-o", "native.vbb"], "-o/--output 不能与 --check-native-text-map 同时使用"),
        (["-rp"], "-rp/--refresh-parser 不能与 --check-native-text-map 同时使用"),
    ],
)
def test_cli_rejects_check_native_text_map_with_compile_or_emit_options(tmp_path, monkeypatch, capsys, extra_args, message):
    from verbose_c import cli

    text_bin_path = tmp_path / "native_text_check_combo.bin"
    map_path = tmp_path / "native_text_check_combo.json"
    text_bin_path.write_bytes(b"\xC3")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(text_bin_path), "--check-native-text-map", str(map_path), *extra_args],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--compile-only"], "--compile-only 不能与 --check-native-pe-map 同时使用"),
        (["--run-native-memory"], "--run-native-memory 不能与 --check-native-pe-map 同时使用"),
        (["--run-native-pe"], "--run-native-pe 不能与 --check-native-pe-map 同时使用"),
        (["--run-native-pe-file", "native.json"], "--run-native-pe-file 不能与 --check-native-pe-map 同时使用"),
        (["--run-native-bin-memory", "native.json"], "--run-native-bin-memory 不能与 --check-native-pe-map 同时使用"),
        (["--run-native-text-bin-memory", "native.json"], "--run-native-text-bin-memory 不能与 --check-native-pe-map 同时使用"),
        (["--native-result", "native_result.txt"], "--native-result 不能与 --check-native-pe-map 同时使用"),
        (["--native-zero-exit-code"], "--native-zero-exit-code 不能与 --check-native-pe-map 同时使用"),
        (["--emit", "native-bundle", "--emit-dir", "exports"], "--emit 不能与 --check-native-pe-map 同时使用"),
        (["-o", "native.vbb"], "-o/--output 不能与 --check-native-pe-map 同时使用"),
        (["-rp"], "-rp/--refresh-parser 不能与 --check-native-pe-map 同时使用"),
    ],
)
def test_cli_rejects_check_native_pe_map_with_compile_or_emit_options(tmp_path, monkeypatch, capsys, extra_args, message):
    from verbose_c import cli

    pe_path = tmp_path / "native_check_pe_combo.exe"
    map_path = tmp_path / "native_check_pe_combo.json"
    pe_path.write_bytes(b"MZ")
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verbose-c", str(pe_path), "--check-native-pe-map", str(map_path), *extra_args],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert message in capsys.readouterr().out

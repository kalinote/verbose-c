"""Native 教学 listing 格式化。"""

import hashlib
import json
from verbose_c.compiler.native.encoder import encode_sub_rsp_imm32
from verbose_c.compiler.native.map_format import native_code_program_map
from verbose_c.compiler.native.model import (
    NativeCodeFunction,
    NativeCodeProgram,
    native_program_symbols,
    native_symbol_function,
    native_value_location,
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
    TEST_RDX_RDX_SIZE,
)


def format_native_code_program(program: NativeCodeProgram) -> str:
    """生成 x64 机器码 dump 文本。"""
    if program.runtime:
        metadata = native_code_program_map(program)
        lines = ["## x64 机器码\n\n", f"- 目标平台: `{program.target.value}`\n",
                 f"- 内存入口: `{program.entry.name}`\n",
                 f"- PE 入口 RVA: `0x{metadata['pe_address_of_entry_point']:08X}`\n",
                 "- 内置运行时: Windows 标准流、UTF-8 字符串、私有堆\n",
                 "- 系统导入: KERNEL32.dll\n\n",
                 "### PE 文件布局\n\n",
                 "| 节 | RVA | 文件偏移 | 文件大小 | 权限 |\n",
                 "| --- | --- | --- | --- | --- |\n"]
        for section in metadata["sections"]:
            header = section["pe_section_header"]
            lines.append(f"| {section['name']} | 0x{section['rva']:08X} | {header['PointerToRawData']} | "
                         f"{header['SizeOfRawData']} | {', '.join(section['permissions'])} |\n")
        lines.append("\n### KERNEL32 导入\n\n" + ", ".join(program.runtime["iat_offsets"]) + "\n\n")
        for function in program.functions.values():
            if function.name.startswith("<native:"):
                lines.append(f"- 内置函数 `{function.name}`: 偏移 {function.offset}，大小 {len(function.code)} 字节\n")
            else:
                lines.extend(_format_function(function, program.functions))
        return "".join(lines)
    text_rva = PE_TEXT_RVA
    image_base = PE_IMAGE_BASE
    code_size = len(program.code)
    raw_size_aligned = ((code_size + PE_FILE_ALIGNMENT - 1) // PE_FILE_ALIGNMENT) * PE_FILE_ALIGNMENT
    raw_padding_size = raw_size_aligned - code_size
    raw_padded_sha256 = hashlib.sha256(program.code + bytes(raw_padding_size)).hexdigest()
    virtual_size_aligned = ((code_size + PE_SECTION_ALIGNMENT - 1) // PE_SECTION_ALIGNMENT) * PE_SECTION_ALIGNMENT
    section_table_offset = PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE + PE_OPTIONAL_HEADER_SIZE
    section_table_size = PE_SECTION_HEADER_SIZE
    pe_size_of_headers = ((section_table_offset + section_table_size + PE_FILE_ALIGNMENT - 1) // PE_FILE_ALIGNMENT) * PE_FILE_ALIGNMENT
    entry_rva = text_rva + program.entry_offset
    entry_va = image_base + entry_rva
    code_sha256 = hashlib.sha256(program.code).hexdigest()
    symbols = native_program_symbols(program)
    global_frame_owners = [
        function.name
        for function in program.functions.values()
        if any(
            instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
            for instruction in function.instructions
        )
    ]
    global_frame_owner = global_frame_owners[0] if global_frame_owners else "-"
    lines = [
        "## x64 机器码\n\n",
        f"- 目标平台: `{program.target.value}`\n",
        f"- 入口函数: `{program.entry.name}`\n\n",
        f"- Global-frame owner: `{global_frame_owner}`\n",
        f"- 入口偏移: `{program.entry_offset:04X}`\n",
        f"- 入口 RVA: `0x{entry_rva:08X}`\n",
        f"- 入口 VA: `0x{entry_va:016X}`\n",
        f"- 程序机器码大小: `{code_size}` bytes\n",
        f"- 程序 SHA-256: `{code_sha256}`\n\n",
        "### PE/COFF 过渡摘要\n\n",
        "| Machine | Machine 值 | OptionalHeader | OptionalHeader 值 | Subsystem | Subsystem 值 | Sections | e_lfanew | PE sig offset | COFF offset | Optional offset | Section table | SizeOfHeaders | Image base | BaseOfCode | AddressOfEntryPoint | SizeOfCode | SizeOfImage | Initialized data | Uninitialized data | File alignment | Section alignment |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        f"| `AMD64` | `0x8664` | `PE32+` | `0x020B` | `console` | `3` | `1` | "
        f"`0x{PE_LFANEW:08X}` | `0x{PE_LFANEW:08X}` | `0x{PE_LFANEW + PE_SIGNATURE_SIZE:08X}` | "
        f"`0x{PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE:08X}` | `0x{section_table_offset:08X}` | "
        f"`{pe_size_of_headers}` | "
        f"`0x{image_base:016X}` | `0x{text_rva:08X}` | `0x{entry_rva:08X}` | "
        f"`{raw_size_aligned}` | `{text_rva + virtual_size_aligned}` | `0` | `0` | "
        f"`{PE_FILE_ALIGNMENT}` | `{PE_SECTION_ALIGNMENT}` |\n\n",
        "### PE 文件布局\n\n",
        "| 段 | Offset | Size | End offset | 说明 |\n",
        "| --- | --- | --- | --- | --- |\n",
        f"| `dos_header` | `0` | `{PE_DOS_HEADER_SIZE}` | `{PE_DOS_HEADER_SIZE}` | `MZ header` |\n",
        f"| `dos_stub_padding` | `{PE_DOS_HEADER_SIZE}` | `{PE_LFANEW - PE_DOS_HEADER_SIZE}` | `{PE_LFANEW}` | `padding before PE signature` |\n",
        f"| `pe_signature` | `{PE_LFANEW}` | `{PE_SIGNATURE_SIZE}` | `{PE_LFANEW + PE_SIGNATURE_SIZE}` | `PE signature` |\n",
        f"| `coff_header` | `{PE_LFANEW + PE_SIGNATURE_SIZE}` | `{PE_COFF_HEADER_SIZE}` | `{PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE}` | `IMAGE_FILE_HEADER` |\n",
        f"| `optional_header` | `{PE_LFANEW + PE_SIGNATURE_SIZE + PE_COFF_HEADER_SIZE}` | `{PE_OPTIONAL_HEADER_SIZE}` | `{section_table_offset}` | `IMAGE_OPTIONAL_HEADER64` |\n",
        f"| `section_table` | `{section_table_offset}` | `{section_table_size}` | `{section_table_offset + section_table_size}` | `.text section header` |\n",
        f"| `headers_padding` | `{section_table_offset + section_table_size}` | `{pe_size_of_headers - section_table_offset - section_table_size}` | `{pe_size_of_headers}` | `align headers to FileAlignment` |\n",
        f"| `text_raw` | `{pe_size_of_headers}` | `{raw_size_aligned}` | `{pe_size_of_headers + raw_size_aligned}` | `.text raw data` |\n",
        f"| `file_size` | `0` | `{pe_size_of_headers + raw_size_aligned}` | `{pe_size_of_headers + raw_size_aligned}` | `headers + .text raw` |\n\n",
        "### .text 代码节\n\n",
        "| 名称 | Name bytes | Raw offset | Raw size | End offset | PE raw pointer | PE raw end | Raw aligned | Raw padding | Raw padded SHA-256 | Virtual size | Virtual aligned | Code alignment | RVA | End RVA | VA | End VA | Entry offset | SHA-256 | File alignment | Section alignment | 权限 | Characteristics | PE Characteristics |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        f"| `.text` | `2E 74 65 78 74 00 00 00` | `0` | `{code_size}` | `{code_size}` | "
        f"`{pe_size_of_headers}` | `{pe_size_of_headers + raw_size_aligned}` | `{raw_size_aligned}` | `{raw_padding_size}` | `{raw_padded_sha256}` | `{code_size}` | "
        f"`{virtual_size_aligned}` | `16` | "
        f"`0x{text_rva:08X}` | `0x{text_rva + code_size:08X}` | `0x{image_base + text_rva:016X}` | "
        f"`0x{image_base + text_rva + code_size:016X}` | `{program.entry_offset:04X}` | `{code_sha256}` | "
        f"`{PE_FILE_ALIGNMENT}` | `{PE_SECTION_ALIGNMENT}` | `read, execute` | `CNT_CODE, MEM_EXECUTE, MEM_READ` | `0x60000020` |\n\n",
        "### ABI\n\n",
        f"- 名称: `{program.abi.name}`\n",
        f"- ABI 目标: `{program.abi.target.value}`\n",
        f"- Word size: `{program.abi.word_size}` bytes\n",
        f"- 参数寄存器: `{', '.join(program.abi.registers.argument_registers)}`\n",
        f"- 返回寄存器: `{program.abi.registers.return_register}`\n",
        f"- 帧指针 / 栈指针: `{program.abi.registers.frame_pointer}` / `{program.abi.registers.stack_pointer}`\n",
        f"- Shadow space: `{program.abi.shadow_space_size}` bytes\n",
        f"- 栈对齐: `{program.abi.stack_alignment}` bytes\n",
        f"- 支持值类型: `{', '.join(program.abi.supported_value_types)}`\n\n",
        "### 函数符号表\n\n",
        "| 名称 | 类型 | 返回类型 | 形参类型 | 偏移 | End offset | RVA | VA | 大小 | End RVA | End VA | SHA-256 | 入口 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    if symbols:
        for symbol in symbols:
            function = native_symbol_function(program, symbol)
            symbol_code = function.code
            param_types = ", ".join(symbol.param_types) if symbol.param_types else "-"
            symbol_rva = text_rva + symbol.offset
            symbol_end_rva = symbol_rva + symbol.size
            symbol_va = image_base + symbol_rva
            symbol_end_va = image_base + symbol_end_rva
            lines.append(
                f"| `{symbol.name}` | `{symbol.kind}` | `{symbol.return_type}` | `{param_types}` | "
                f"`{symbol.offset:04X}` | `{symbol.offset + symbol.size:04X}` | "
                f"`0x{symbol_rva:08X}` | `0x{symbol_va:016X}` | `{symbol.size}` | `0x{symbol_end_rva:08X}` | "
                f"`0x{symbol_end_va:016X}` | `{hashlib.sha256(symbol_code).hexdigest()}` | "
                f"`{'yes' if symbol.is_entry else 'no'}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `0000` | `0000` | `0x00000000` | `0x0000000000000000` | `0` | `0x00000000` | `0x0000000000000000` | `-` | `no` |\n")
    lines.append("\n")
    for function in program.functions.values():
        lines.extend(_format_function(function, program.functions))
    return "".join(lines)


def _format_function(function: NativeCodeFunction, functions: dict[str, NativeCodeFunction]) -> list[str]:
    """生成单个机器码函数的 dump 文本。"""
    text_rva = 4096
    image_base = 0x140000000
    function_rva = text_rva + function.offset
    function_va = image_base + function_rva
    function_end_rva = function_rva + len(function.code)
    function_end_va = image_base + function_end_rva
    param_types = ", ".join(function.param_types) if function.param_types else "-"
    has_global_slots = any(slot.name.startswith("global[") for slot in function.stack_slots)
    initializes_global_frame = any(
        instruction.source_op == "prologue" and instruction.asm == "mov r11, rbp ; global frame"
        for instruction in function.instructions
    )
    lines = [
        f"### `{function.name}`\n\n",
        f"- 函数偏移: `{function.offset:04X}`\n",
        f"- 函数范围: `[{function.offset:04X}, {function.offset + len(function.code):04X})`\n",
        f"- 函数 RVA 范围: `[0x{function_rva:08X}, 0x{function_end_rva:08X})`\n",
        f"- 函数 VA 范围: `[0x{function_va:016X}, 0x{function_end_va:016X})`\n",
        f"- 返回类型: `{function.return_type}`\n",
        f"- 形参类型: `{param_types}`\n",
        f"- 栈帧大小: `{function.frame_size}` bytes\n",
        f"- 机器码大小: `{len(function.code)}` bytes\n\n",
        "#### 寄存器分配\n\n",
        f"- 策略: `{function.register_allocation.strategy}`\n",
        f"- 临时寄存器: `{ '`, `'.join(function.register_allocation.temporary_registers) }`\n",
        f"- 参数寄存器: `{ '`, `'.join(function.register_allocation.argument_registers) if function.register_allocation.argument_registers else '-' }`\n",
        f"- 返回寄存器: `{function.register_allocation.return_register}`\n",
        f"- 帧指针: `{function.register_allocation.frame_pointer}`\n",
        f"- 栈指针: `{function.register_allocation.stack_pointer}`\n",
        f"- 虚拟寄存器保存: `{function.register_allocation.virtual_register_storage}`\n",
        f"- 局部变量保存: `{function.register_allocation.local_storage}`\n\n",
    ]
    if has_global_slots:
        if initializes_global_frame and function.name == "<module>":
            owner_text = "当前函数初始化，当前函数内 `global[...]` 使用 `[rbp-offset]`，被调用户函数使用 `[r11-offset]`"
        elif initializes_global_frame:
            owner_text = "当前函数初始化，`global[...]` 通过 `[r11-offset]` 访问"
        else:
            owner_text = "由 global-frame owner 初始化，`global[...]` 通过 `[r11-offset]` 访问"
        lines.append(f"- 全局帧寄存器: `{function.register_allocation.global_frame_register}` ({owner_text})\n")
    lines.extend([
        "\n",
        "#### 栈槽分配\n\n",
        "| 名称 | 位置 | 大小 |\n",
        "| --- | --- | --- |\n",
    ])
    if function.stack_slots:
        for slot in function.stack_slots:
            base = "r11" if function.name != "<module>" and slot.name.startswith("global[") else "rbp"
            lines.append(f"| `{slot.name}` | `[{base}-{slot.offset}]` | `{slot.size}` |\n")
    else:
        lines.append("| `-` | `-` | `0` |\n")
    lines.extend([
        "\n",
        "#### 值位置摘要\n\n",
        "| 名称 | 种类 | 索引 | 保存位置 | 基址寄存器 | 偏移 | 大小 |\n",
        "| --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.stack_slots:
        for slot in function.stack_slots:
            location = native_value_location(function.name, slot)
            lines.append(
                f"| `{location['name']}` | `{location['kind']}` | `{location['index']}` | "
                f"`{location['storage']}` | `{location['base_register']}` | `{location['offset']}` | "
                f"`{location['size']}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` | `-` | `0` |\n")
    label_instructions = [
        instruction
        for instruction in function.instructions
        if instruction.source_op == "label" and instruction.asm.endswith(":")
    ]
    label_offsets = {instruction.asm[:-1]: instruction.offset for instruction in label_instructions}
    lines.extend([
        "\n",
        "#### 标签摘要\n\n",
        "| 名称 | 偏移 | RVA | VA | 来源 |\n",
        "| --- | --- | --- | --- | --- |\n",
    ])
    if label_instructions:
        for instruction in label_instructions:
            label_rva = text_rva + instruction.offset
            label_va = image_base + label_rva
            details = []
            if instruction.source_pc is not None:
                details.append(f"pc {instruction.source_pc}")
            if instruction.source_line is not None:
                details.append(f"line {instruction.source_line}")
            source = ", ".join(details) if details else "-"
            lines.append(
                f"| `{instruction.asm[:-1]}` | `{instruction.offset:04X}` | `0x{label_rva:08X}` | "
                f"`0x{label_va:016X}` | `{source}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` |\n")
    lines.extend([
        "\n",
        "#### 调用栈窗口\n\n",
        "| 偏移 | 结束偏移 | Sub SHA-256 | Call 偏移 | Call 结束 | Call SHA-256 | Add 偏移 | Add 结束 | Add SHA-256 | RVA | End RVA | VA | End VA | Call RVA 范围 | Call VA 范围 | Add RVA 范围 | Add VA 范围 | 目标 | 参数 | 实参类型 | 形参类型 | 寄存器参数 | 栈参数 | Shadow space | 栈实参字节 | 对齐后大小 | 对齐 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.call_frames:
        for item in function.call_frames:
            item_end_offset = item.offset + len(encode_sub_rsp_imm32(item.aligned_size))
            item_local_offset = item.offset - function.offset
            item_local_end_offset = item_end_offset - function.offset
            sub_code_sha256 = hashlib.sha256(function.code[item_local_offset:item_local_end_offset]).hexdigest()
            item_rva = text_rva + item.offset
            item_end_rva = text_rva + item_end_offset
            item_va = image_base + item_rva
            item_end_va = image_base + item_end_rva
            call_offset = f"{item.call_offset:04X}" if item.call_offset is not None else "-"
            call_end_offset = f"{item.call_end_offset:04X}" if item.call_end_offset is not None else "-"
            add_offset = f"{item.add_offset:04X}" if item.add_offset is not None else "-"
            add_end_offset = f"{item.add_end_offset:04X}" if item.add_end_offset is not None else "-"
            if item.call_offset is None or item.call_end_offset is None:
                call_rva_range = "-"
                call_va_range = "-"
                call_code_sha256 = "-"
            else:
                call_local_offset = item.call_offset - function.offset
                call_local_end_offset = item.call_end_offset - function.offset
                call_code_sha256 = hashlib.sha256(function.code[call_local_offset:call_local_end_offset]).hexdigest()
                call_rva = text_rva + item.call_offset
                call_end_rva = text_rva + item.call_end_offset
                call_rva_range = f"0x{call_rva:08X}-0x{call_end_rva:08X}"
                call_va_range = f"0x{image_base + call_rva:016X}-0x{image_base + call_end_rva:016X}"
            if item.add_offset is None or item.add_end_offset is None:
                add_rva_range = "-"
                add_va_range = "-"
                add_code_sha256 = "-"
            else:
                add_local_offset = item.add_offset - function.offset
                add_local_end_offset = item.add_end_offset - function.offset
                add_code_sha256 = hashlib.sha256(function.code[add_local_offset:add_local_end_offset]).hexdigest()
                add_rva = text_rva + item.add_offset
                add_end_rva = text_rva + item.add_end_offset
                add_rva_range = f"0x{add_rva:08X}-0x{add_end_rva:08X}"
                add_va_range = f"0x{image_base + add_rva:016X}-0x{image_base + add_end_rva:016X}"
            details = []
            if item.source_pc is not None:
                details.append(f"pc {item.source_pc}")
            if item.source_line is not None:
                details.append(f"line {item.source_line}")
            target = item.target if not details else f"{item.target} ({', '.join(details)})"
            arg_types = ", ".join(item.arg_types) if item.arg_types else "-"
            param_types = ", ".join(item.param_types) if item.param_types else "-"
            lines.append(
                f"| `{item.offset:04X}` | `{item_end_offset:04X}` | `{sub_code_sha256}` | "
                f"`{call_offset}` | `{call_end_offset}` | `{call_code_sha256}` | "
                f"`{add_offset}` | `{add_end_offset}` | `{add_code_sha256}` | `0x{item_rva:08X}` | "
                f"`0x{item_end_rva:08X}` | `0x{item_va:016X}` | `0x{item_end_va:016X}` | "
                f"`{call_rva_range}` | `{call_va_range}` | `{add_rva_range}` | `{add_va_range}` | `{target}` | "
                f"`{item.arg_count}` | `{arg_types}` | `{param_types}` | `{item.register_arg_count}` | `{item.stack_arg_count}` | "
                f"`{item.shadow_space_size}` | `{item.stack_arg_bytes}` | "
                f"`{item.aligned_size}` | `{item.stack_alignment}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `0` | `-` | `-` | `0` | `0` | `0` | `0` | `0` | `0` |\n")
    lines.extend([
        "\n",
        "#### rel32 修补记录\n\n",
        "| 指令偏移 | 指令 RVA | 指令 VA | 指令 SHA-256 | 字段偏移 | 字段结束 | 字段 RVA | 字段结束 RVA | 字段 VA | 字段结束 VA | Patch SHA-256 | 类型 | 目标 | 目标 RVA | 目标 VA | 位移 | 字段大小 | 来源 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.relocations:
        for item in function.relocations:
            item_rva = text_rva + item.offset
            item_va = image_base + item_rva
            patch_rva = text_rva + item.patch_offset
            patch_va = image_base + patch_rva
            patch_end_offset = item.patch_offset + item.size
            patch_end_rva = patch_rva + item.size
            patch_end_va = patch_va + item.size
            local_offset = item.offset - function.offset
            local_patch_offset = item.patch_offset - function.offset
            local_patch_end_offset = patch_end_offset - function.offset
            instruction_code_sha256 = hashlib.sha256(function.code[local_offset:local_patch_end_offset]).hexdigest()
            patch_code_sha256 = hashlib.sha256(function.code[local_patch_offset:local_patch_end_offset]).hexdigest()
            target_function = functions.get(item.target)
            target_offset = target_function.offset if target_function is not None else label_offsets.get(item.target)
            target_rva = "-" if target_offset is None else f"0x{text_rva + target_offset:08X}"
            target_va = "-" if target_offset is None else f"0x{image_base + text_rva + target_offset:016X}"
            details = []
            if item.source_pc is not None:
                details.append(f"pc {item.source_pc}")
            if item.source_line is not None:
                details.append(f"line {item.source_line}")
            source = ", ".join(details) if details else "-"
            lines.append(
                f"| `{item.offset:04X}` | `0x{item_rva:08X}` | `0x{item_va:016X}` | `{instruction_code_sha256}` | "
                f"`{item.patch_offset:04X}` | "
                f"`{patch_end_offset:04X}` | `0x{patch_rva:08X}` | `0x{patch_end_rva:08X}` | "
                f"`0x{patch_va:016X}` | `0x{patch_end_va:016X}` | `{patch_code_sha256}` | `{item.kind}` | `{item.target}` | "
                f"`{target_rva}` | `{target_va}` | `{item.displacement:+d}` | `{item.size}` | `{source}` |\n"
            )
    else:
        lines.append("| `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `0` | `0` | `-` |\n")
    lines.extend([
        "\n",
        "#### _exit 传播探针\n\n",
        "| Call 偏移 | Call 结束 | Call SHA-256 | Call RVA | Call End RVA | Call VA | Call End VA | Test 偏移 | Test 结束 | Test SHA-256 | Test RVA | Test End RVA | Test VA | Test End VA | Jump 偏移 | Jump 结束 | Jump SHA-256 | Jump RVA | Jump End RVA | Jump VA | Jump End VA | 目标 | 传播标签 | 来源 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    if function.exit_probes:
        for item in function.exit_probes:
            call_end_offset = item.call_offset + CALL_REL32_SIZE
            call_local_offset = item.call_offset - function.offset
            call_local_end_offset = call_end_offset - function.offset
            call_code_sha256 = hashlib.sha256(function.code[call_local_offset:call_local_end_offset]).hexdigest()
            call_rva = text_rva + item.call_offset
            call_end_rva = text_rva + call_end_offset
            call_va = image_base + call_rva
            call_end_va = image_base + call_end_rva
            test_end_offset = item.test_offset + TEST_RDX_RDX_SIZE
            test_local_offset = item.test_offset - function.offset
            test_local_end_offset = test_end_offset - function.offset
            test_code_sha256 = hashlib.sha256(function.code[test_local_offset:test_local_end_offset]).hexdigest()
            test_rva = text_rva + item.test_offset
            test_end_rva = text_rva + test_end_offset
            test_va = image_base + test_rva
            test_end_va = image_base + test_end_rva
            jump_end_offset = item.jump_offset + JNE_REL32_SIZE
            jump_local_offset = item.jump_offset - function.offset
            jump_local_end_offset = jump_end_offset - function.offset
            jump_code_sha256 = hashlib.sha256(function.code[jump_local_offset:jump_local_end_offset]).hexdigest()
            jump_rva = text_rva + item.jump_offset
            jump_end_rva = text_rva + jump_end_offset
            jump_va = image_base + jump_rva
            jump_end_va = image_base + jump_end_rva
            details = []
            if item.source_pc is not None:
                details.append(f"pc {item.source_pc}")
            if item.source_line is not None:
                details.append(f"line {item.source_line}")
            source = ", ".join(details) if details else "-"
            lines.append(
                f"| `{item.call_offset:04X}` | `{call_end_offset:04X}` | `{call_code_sha256}` | "
                f"`0x{call_rva:08X}` | `0x{call_end_rva:08X}` | `0x{call_va:016X}` | `0x{call_end_va:016X}` | "
                f"`{item.test_offset:04X}` | `{test_end_offset:04X}` | `{test_code_sha256}` | "
                f"`0x{test_rva:08X}` | `0x{test_end_rva:08X}` | `0x{test_va:016X}` | `0x{test_end_va:016X}` | "
                f"`{item.jump_offset:04X}` | `{jump_end_offset:04X}` | `{jump_code_sha256}` | "
                f"`0x{jump_rva:08X}` | `0x{jump_end_rva:08X}` | `0x{jump_va:016X}` | `0x{jump_end_va:016X}` | "
                f"`{item.target}` | `{item.probe_label}` | `{source}` |\n"
            )
    else:
        lines.append(
            "| `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | "
            "`-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` | `-` |\n"
        )
    lines.extend([
        "\n",
        "#### 机器码清单\n\n",
        "| 偏移 | End offset | RVA | VA | End RVA | End VA | 字节 | SHA-256 | 伪汇编 | 来源 | 来源属性 |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ])
    for instruction in function.instructions:
        instruction_rva = text_rva + instruction.offset
        instruction_va = image_base + instruction_rva
        instruction_end_rva = instruction_rva + len(instruction.code)
        instruction_end_va = image_base + instruction_end_rva
        byte_text = " ".join(f"{item:02X}" for item in instruction.code)
        source = instruction.source_op
        details = []
        if instruction.source_pc is not None:
            details.append(f"pc {instruction.source_pc}")
        if instruction.source_line is not None:
            details.append(f"line {instruction.source_line}")
        if details:
            source += " (" + ", ".join(details) + ")"
        source_attrs = "-"
        if instruction.source_attrs:
            source_attrs = json.dumps(
                instruction.source_attrs,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        lines.append(
            f"| `{instruction.offset:04X}` | `{instruction.offset + len(instruction.code):04X}` | "
            f"`0x{instruction_rva:08X}` | `0x{instruction_va:016X}` | "
            f"`0x{instruction_end_rva:08X}` | `0x{instruction_end_va:016X}` | `{byte_text}` | "
            f"`{hashlib.sha256(instruction.code).hexdigest()}` | `{instruction.asm}` | `{source}` | `{source_attrs}` |\n"
        )
    lines.append("\n")
    return lines

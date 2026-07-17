from verbose_c.compiler.native.machine_ir import (
    MachineBlock,
    MachineFunction,
    MachineInstruction,
    MachineOperand,
    MachineProgram,
    MachineTerminator,
)


def format_machine_program(program: MachineProgram) -> str:
    """生成文本形式 Machine IR dump。"""
    abi = program.abi
    regs = abi.registers
    lines = [
        "## Machine IR\n\n",
        f"- 目标平台: `{program.target.value}`\n",
        f"- ABI: `{abi.name}`\n",
        f"- 参数寄存器: `{', '.join(regs.argument_registers)}`\n",
        f"- 返回寄存器: `{regs.return_register}`\n",
        f"- Shadow space: `{abi.shadow_space_size}` bytes\n",
        f"- 栈对齐: `{abi.stack_alignment}` bytes\n",
        f"- Caller-saved: `{', '.join(regs.caller_saved)}`\n",
        f"- Callee-saved: `{', '.join(regs.callee_saved)}`\n\n",
    ]
    lines.extend(_format_function(program.module))
    for function in program.functions.values():
        lines.append("\n")
        lines.extend(_format_function(function))
    return "".join(lines)


def _format_function(function: MachineFunction) -> list[str]:
    params = ", ".join(f"{item.index}:{item.kind}:{item.name}" for item in function.params) or "-"
    lines = [
        f"### `{function.name}`\n\n",
        f"- 返回类型: `{function.return_type}`\n",
        f"- 参数位置: `{params}`\n",
        f"- 栈帧大小: `{function.frame.frame_size}` bytes\n",
        f"- 全局槽数量: `{len(function.frame.global_slots)}`\n",
        f"- 局部槽数量: `{len(function.frame.local_slots)}`\n",
        f"- 临时槽数量: `{len(function.frame.temp_slots)}`\n",
        f"- 虚拟寄存器数量: `{function.virtual_register_count}`\n",
    ]
    if function.exit_code_value is not None:
        lines.append(f"- 入口退出码值: `{_format_operand(function.exit_code_value)}`\n")
    lines.append("\n")
    lines.extend(_format_stack_slots(function))
    for block in function.blocks:
        lines.extend(_format_block(block))
    return lines


def _format_stack_slots(function: MachineFunction) -> list[str]:
    """生成 Machine IR 栈槽表。"""
    lines = [
        "#### 栈槽\n\n",
        "| 类型 | 索引 | 大小 |\n",
        "| --- | --- | --- |\n",
    ]
    slots = [
        *function.frame.global_slots,
        *function.frame.local_slots,
        *function.frame.temp_slots,
        *function.frame.spill_slots,
    ]
    if not slots:
        lines.append("| `-` | `-` | `0` |\n")
    for slot in slots:
        lines.append(f"| `{slot.kind}` | `{slot.index}` | `{slot.size}` |\n")
    lines.append("\n")
    return lines


def _format_block(block: MachineBlock) -> list[str]:
    lines = [
        f"#### {block.name}\n\n",
        f"- 前驱基本块: `{', '.join(block.predecessors) or '-'}`\n",
        f"- 后继基本块: `{', '.join(block.successors) or '-'}`\n\n",
        "```text\n",
    ]
    for instruction in block.instructions:
        lines.append(_format_instruction(instruction) + "\n")
    if block.terminator:
        lines.append(_format_terminator(block.terminator) + "\n")
    lines.append("```\n\n")
    return lines


def _format_instruction(instruction: MachineInstruction) -> str:
    prefix = f"{_format_operand(instruction.result)} = " if instruction.result else ""
    args = ", ".join(_format_operand(item) for item in instruction.args)
    attrs = _format_attrs(instruction.attrs)
    text = f"{prefix}{instruction.op}"
    if args:
        text += f" {args}"
    if attrs:
        text += f" {attrs}"
    return _append_source(text, instruction.source_line, instruction.source_pc)


def _format_terminator(terminator: MachineTerminator) -> str:
    parts = [terminator.op]
    args = ", ".join(_format_operand(item) for item in terminator.args)
    if args:
        parts.append(args)
    if terminator.targets:
        parts.append(f"-> {', '.join(terminator.targets)}")
    return _append_source(" ".join(parts), terminator.source_line, terminator.source_pc)


def _format_operand(operand: MachineOperand | None) -> str:
    if operand is None:
        return "-"
    if operand.kind == "vreg":
        return f"%{operand.value.name}:{operand.type_hint}"
    if operand.kind == "slot":
        return f"{operand.value.kind}[{operand.value.index}]"
    if operand.kind == "imm":
        return f"#{operand.value}"
    if operand.kind == "symbol":
        return f"@{operand.value}"
    if operand.kind == "reg":
        return f"${operand.value}"
    return f"{operand.kind}({operand.value})"


def _format_attrs(attrs: dict) -> str:
    if not attrs:
        return ""
    return " ".join(f"{key}={value!r}" for key, value in attrs.items())


def _append_source(text: str, line: int | None, pc: int | None) -> str:
    suffix = []
    if pc is not None:
        suffix.append(f"pc {pc}")
    if line is not None:
        suffix.append(f"line {line}")
    if suffix:
        return f"{text}  ; {', '.join(suffix)}"
    return text

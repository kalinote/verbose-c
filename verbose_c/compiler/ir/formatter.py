from verbose_c.compiler.ir.model import IRBasicBlock, IRFunction, IRInstruction, IRProgram, IRTerminator, IRValue


def format_ir_program(program: IRProgram) -> str:
    """生成文本形式 IR dump。"""
    lines = ["## IR\n\n"]
    lines.extend(_format_function(program.module))
    for function in program.functions.values():
        lines.append("\n")
        lines.extend(_format_function(function))
    return "".join(lines)


def _format_function(function: IRFunction) -> list[str]:
    lines = [f"### `{function.name}`\n\n"]
    for block in function.blocks:
        lines.extend(_format_block(block))
    return lines


def _format_block(block: IRBasicBlock) -> list[str]:
    lines = [
        f"#### {block.name}  ; pc {block.start_pc}..{block.end_pc}\n\n",
        f"- 前驱基本块: `{', '.join(block.predecessors) or '-'}`\n",
        f"- 后继基本块: `{', '.join(block.successors) or '-'}`\n\n",
        "```text\n",
    ]
    for instruction in block.instructions:
        lines.append(_format_instruction(instruction) + "\n")
    if block.terminator is not None:
        lines.append(_format_terminator(block.terminator) + "\n")
    lines.append("```\n\n")
    return lines


def _format_instruction(instruction: IRInstruction) -> str:
    prefix = f"{_format_value(instruction.result)} = " if instruction.result is not None else ""
    attrs = _format_attrs(instruction.attrs)
    args = ", ".join(_format_value(value) for value in instruction.args)
    text = f"{prefix}{instruction.op}"
    if args:
        text += f" {args}"
    if attrs:
        text += f" {attrs}"
    return _append_source(text, instruction.source_line, instruction.source_pc)


def _format_terminator(terminator: IRTerminator) -> str:
    args = ", ".join(_format_value(value) for value in terminator.args)
    targets = ", ".join(terminator.targets)
    parts = [terminator.op]
    if args:
        parts.append(args)
    if targets:
        parts.append(f"-> {targets}")
    return _append_source(" ".join(parts), terminator.source_line, terminator.source_pc)


def _format_value(value: IRValue | None) -> str:
    if value is None:
        return "-"
    if value.kind == "temp":
        return str(value.name)
    if value.kind == "local":
        return f"local[{value.name}]"
    if value.kind == "global":
        return f"global[{value.name}]"
    if value.kind == "constant":
        return f"const[{value.name}]"
    return f"{value.kind}[{value.name}]"


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

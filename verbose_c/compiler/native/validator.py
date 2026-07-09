from verbose_c.compiler.native.errors import NativeLoweringError
from verbose_c.compiler.native.machine_ir import MachineFunction, MachineOperand


def validate_machine_function(function: MachineFunction) -> None:
    """校验 Machine IR 基本结构。"""
    block_names = {block.name for block in function.blocks}
    defined_vregs: set[str] = set()

    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.result and instruction.result.kind == "vreg":
                defined_vregs.add(instruction.result.value.name)

    for block in function.blocks:
        if block.terminator is None:
            raise NativeLoweringError(f"Machine IR 函数 {function.name} 的基本块 {block.name} 缺少终结指令")
        for target in block.successors:
            if target not in block_names:
                raise NativeLoweringError(f"Machine IR 函数 {function.name} 的基本块 {block.name} 跳转到未知目标 {target}")
        for instruction in block.instructions:
            for operand in instruction.args:
                _check_operand(function.name, block.name, operand, defined_vregs)
        for operand in block.terminator.args:
            _check_operand(function.name, block.name, operand, defined_vregs)


def _check_operand(function_name: str, block_name: str, operand: MachineOperand, defined_vregs: set[str]) -> None:
    if operand.kind != "vreg":
        return
    if operand.value.name not in defined_vregs:
        raise NativeLoweringError(
            f"Machine IR 函数 {function_name} 的基本块 {block_name} 使用未定义虚拟寄存器 {operand.value.name}"
        )


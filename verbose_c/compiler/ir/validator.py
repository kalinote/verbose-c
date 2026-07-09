from verbose_c.compiler.ir.model import IRFunction, IRLoweringError, IRValue


def validate_ir_function(function: IRFunction) -> None:
    """校验 IR 函数的基本 CFG 与 def-use 约束。"""
    block_names = {block.name for block in function.blocks}
    defined_temps: set[IRValue] = set()

    for block in function.blocks:
        if block.terminator is None:
            raise IRLoweringError(f"IR 函数 '{function.name}' 的基本块 {block.name} 缺少终结指令")

        for target in block.successors:
            if target not in block_names:
                raise IRLoweringError(f"IR 函数 '{function.name}' 的基本块 {block.name} 跳转到未知目标 {target}")

        for instruction in block.instructions:
            for value in instruction.args:
                _check_value_defined(function.name, block.name, value, defined_temps)
            if instruction.result is not None and instruction.result.kind == "temp":
                defined_temps.add(instruction.result)

        for value in block.terminator.args:
            _check_value_defined(function.name, block.name, value, defined_temps)


def _check_value_defined(function_name: str, block_name: str, value: IRValue, defined_temps: set[IRValue]) -> None:
    if value.kind != "temp":
        return
    if value not in defined_temps:
        raise IRLoweringError(
            f"IR 函数 '{function_name}' 的基本块 {block_name} 使用未定义临时值 {value.name}"
        )

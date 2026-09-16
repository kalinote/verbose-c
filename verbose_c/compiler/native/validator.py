from verbose_c.compiler.native.errors import NativeLoweringError
from verbose_c.compiler.native.abi import ARRAY_ELEMENT_TYPES, MAX_ARRAY_FRAME_SIZE
from verbose_c.compiler.native.machine_ir import ArraySlot, MachineFunction, MachineOperand


def validate_machine_function(function: MachineFunction) -> None:
    """校验 Machine IR 基本结构。"""
    validate_array_storage(function)
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


def validate_array_storage(function: MachineFunction, error_type=NativeLoweringError) -> None:
    """校验数组声明、操作数类型及初始化对读写的支配关系。

    Args:
        function: 待校验的函数，数组地址只能来自该函数的声明。
        error_type: lowering 或机器码入口使用的诊断类型。
    """
    def fail(message, node=None):
        """附带函数与源码位置报告数组验证错误。"""
        location = f"函数 {function.name}"
        if node is not None:
            location += f", Machine IR 指令 {node.op}, 行 {node.source_line}, PC {node.source_pc}"
        raise error_type(f"{location}: {message}")

    slots = {}
    for slot in function.frame.array_slots:
        if not isinstance(slot, ArraySlot) or type(slot.index) is not int or slot.index < 0:
            fail("数组存储声明无效")
        if slot.index in slots:
            fail("数组存储重复声明")
        if (type(slot.length) is not int or slot.length <= 0 or not isinstance(slot.element_type, str)
                or slot.element_type not in ARRAY_ELEMENT_TYPES or type(slot.size) is not int or slot.size != slot.length * 8):
            fail("数组长度或元素类型无效")
        if slot.size > MAX_ARRAY_FRAME_SIZE or function.name == "<module>":
            fail("数组栈帧过大或使用了不支持的全局数组")
        slots[slot.index] = slot
    allocations = {}
    uses = []
    for block in function.blocks:
        nodes = [*block.instructions, *([block.terminator] if block.terminator else [])]
        for position, node in enumerate(nodes):
            result = getattr(node, "result", None)
            operands = [item for item in [result, *node.args] if item is not None and item.kind == "array"]
            if node.op not in {"alloc_array", "load_index", "store_index"}:
                if operands:
                    fail("数组地址不能用作标量、参数或返回值", node)
                continue
            if len(operands) != 1:
                fail("数组操作必须引用一个已声明的数组地址", node)
            base = operands[0]
            if not isinstance(base.value, ArraySlot) or type(base.value.index) is not int or slots.get(base.value.index) != base.value or base.type_hint != "array_address":
                fail("数组地址来源与当前函数声明不一致", node)
            slot = base.value
            if node.attrs.get("length") != slot.length or node.attrs.get("element_type") != slot.element_type:
                fail("数组长度或元素类型与声明不一致", node)
            if node.op == "alloc_array":
                if result != base or node.args or slot.index in allocations:
                    fail("数组分配指令无效或重复", node)
                allocations[slot.index] = (block.name, position)
            else:
                if len(node.args) != (2 if node.op == "load_index" else 3) or node.args[0] != base:
                    fail("数组读写参数无效", node)
                if node.args[1].kind not in {"imm", "slot", "vreg"} or node.args[1].type_hint != "int64":
                    fail("数组下标必须是整数标量", node)
                value = result if node.op == "load_index" else node.args[2]
                if value is None or value.kind not in ({"vreg"} if node.op == "load_index" else {"imm", "slot", "vreg"}) or value.type_hint != ARRAY_ELEMENT_TYPES[slot.element_type]:
                    fail("数组读写值类型与元素类型不一致", node)
                if node.op == "store_index" and result is not None:
                    fail("数组写入不应携带结果操作数", node)
                uses.append((slot.index, block.name, position, node))
    if set(allocations) != set(slots):
        fail("数组存储缺少对应的分配指令")
    if not uses:
        return
    blocks = {block.name: block for block in function.blocks}
    entry = function.blocks[0].name
    reachable = {entry}
    pending = [entry]
    predecessors = {name: set() for name in blocks}
    for name in pending:
        terminator = blocks[name].terminator
        for target in terminator.targets if terminator else []:
            if target in blocks:
                predecessors[target].add(name)
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
    dominators = {name: ({entry} if name == entry else set(reachable)) for name in reachable}
    changed = True
    while changed:
        changed = False
        for name in reachable - {entry}:
            incoming = predecessors[name] & reachable
            updated = {name} | set.intersection(*(dominators[parent] for parent in incoming))
            if updated != dominators[name]:
                dominators[name] = updated
                changed = True
    for index, block, position, node in uses:
        origin, allocation_position = allocations[index]
        if (origin == block and allocation_position >= position) or (block in reachable and origin not in dominators[block]):
            fail("数组读写之前必须执行其初始化", node)

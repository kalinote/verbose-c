from verbose_c.compiler.native.errors import NativeLoweringError
from verbose_c.compiler.native.abi import ARRAY_ELEMENT_TYPES, ARRAY_REFERENCE_TYPES, MAX_ARRAY_FRAME_SIZE
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
        function: 待校验的函数，数组地址来自局部声明或共享全局存储。
        error_type: lowering 或机器码入口使用的诊断类型。
    """
    def fail(message, node=None):
        """附带函数与源码位置报告数组验证错误。"""
        location = f"函数 {function.name}"
        if node is not None:
            location += f", Machine IR 指令 {node.op}, 行 {node.source_line}, PC {node.source_pc}"
        raise error_type(f"{location}: {message}")

    slots = {}
    array_slots = [*function.frame.array_slots, *(slot for slot in function.frame.global_slots if isinstance(slot, ArraySlot))]
    for slot in array_slots:
        if not isinstance(slot, ArraySlot) or slot.kind not in {"array", "global"}:
            fail("数组存储声明无效")
        if (slot.kind == "array" and (type(slot.index) is not int or slot.index < 0)) or (slot.kind == "global" and not isinstance(slot.index, str)):
            fail("数组存储索引无效")
        key = (slot.kind, slot.index)
        if key in slots:
            fail("数组存储重复声明")
        if (type(slot.length) is not int or slot.length <= 0 or not isinstance(slot.element_type, str)
                or slot.element_type not in ARRAY_ELEMENT_TYPES or type(slot.size) is not int or slot.size != (slot.length + 1) * 8):
            fail("数组长度或元素类型无效")
        if slot.size > MAX_ARRAY_FRAME_SIZE:
            fail("数组栈帧过大")
        slots[key] = slot
    allocations = {}
    uses = []
    reference_slots = {("local", index): value_type for index, value_type in enumerate(function.param_types)
                       if value_type in ARRAY_REFERENCE_TYPES}
    parameter_slots = set(reference_slots)
    reference_definitions = {}
    reference_stores = {}
    reference_uses = []
    reference_loads = []
    for block in function.blocks:
        for position, node in enumerate(block.instructions):
            if node.result is not None and node.result.type_hint in ARRAY_REFERENCE_TYPES and node.result.kind == "vreg":
                name = node.result.value.name
                if name in reference_definitions:
                    fail("数组引用虚拟寄存器重复定义", node)
                reference_definitions[name] = (node.result.type_hint, block.name, position)
            if node.op == "store_stack" and len(node.args) == 2 and node.args[1].type_hint in ARRAY_REFERENCE_TYPES:
                target = node.args[0]
                if target.kind != "slot" or target.value.kind != "local":
                    fail("数组引用不能存入全局或未知地址", node)
                key = (target.value.kind, target.value.index)
                value_type = node.args[1].type_hint
                if reference_slots.get(key, value_type) != value_type:
                    fail("数组引用局部槽的元素类型不一致", node)
                reference_slots[key] = value_type
                reference_stores.setdefault(key, []).append((block.name, position))
    for block in function.blocks:
        nodes = [*block.instructions, *([block.terminator] if block.terminator else [])]
        for position, node in enumerate(nodes):
            result = getattr(node, "result", None)
            operands = [item for item in [result, *node.args] if item is not None and item.kind == "array"]
            references = [item for item in [result, *node.args] if item is not None and item.type_hint in ARRAY_REFERENCE_TYPES]
            if references:
                if node.op not in {"array_address", "load_stack", "store_stack", "phi", "call", "load_array_ref", "store_array_ref"}:
                    fail("数组引用不能参与标量运算或作为返回值", node)
                if any(item.kind not in {"slot", "vreg"} for item in references):
                    fail("数组引用必须来自数组存储或形参，不能伪造整数地址", node)
                for item in references:
                    if item.kind == "vreg":
                        definition = reference_definitions.get(item.value.name)
                        if definition is None or definition[0] != item.type_hint:
                            fail("数组引用缺少相同类型的定义来源", node)
                    elif reference_slots.get((item.value.kind, item.value.index)) != item.type_hint:
                        fail("数组引用栈槽缺少形参或赋值来源", node)
                for index, item in enumerate(node.args):
                    if item.type_hint in ARRAY_REFERENCE_TYPES and item.kind == "vreg":
                        predecessor = node.attrs.get("incoming_blocks", [])[index] if node.op == "phi" else block.name
                        reference_uses.append((item.value.name, predecessor, position if node.op != "phi" else float("inf"), node))
                if node.op == "store_stack" and (node.args[0].value.kind != "local" or len(references) != 2 or node.args[0].type_hint != node.args[1].type_hint):
                    fail("数组引用只能写入相同类型的局部槽", node)
                if node.op == "load_stack" and (len(references) != 2 or result.type_hint != node.args[0].type_hint):
                    fail("数组引用读取类型不一致", node)
                if node.op == "load_stack":
                    key = (node.args[0].value.kind, node.args[0].value.index)
                    if key not in parameter_slots:
                        reference_loads.append((key, block.name, position, node))
            if node.op in {"load_array_ref", "store_array_ref"}:
                if len(node.args) != (2 if node.op == "load_array_ref" else 3):
                    fail("数组引用读写参数数量无效", node)
                base, index = node.args[:2]
                element_type = node.attrs.get("element_type")
                if not isinstance(element_type, str) or element_type not in ARRAY_ELEMENT_TYPES or base.type_hint != f"array_ref:{element_type}" or base.kind not in {"slot", "vreg"}:
                    fail("数组引用与元素类型不一致", node)
                if index.kind not in {"imm", "slot", "vreg"} or index.type_hint != "int64":
                    fail("数组引用下标必须是整数", node)
                value = result if node.op == "load_array_ref" else node.args[2]
                if value is None or value.type_hint != ARRAY_ELEMENT_TYPES[element_type] or value.kind not in {"imm", "slot", "vreg"}:
                    fail("数组引用读写值与元素类型不一致", node)
                if node.op == "store_array_ref" and result is not None:
                    fail("数组引用写入不能携带结果", node)
                continue
            if node.op not in {"alloc_array", "load_index", "store_index", "array_address"}:
                if operands:
                    fail("数组地址不能用作标量、参数或返回值", node)
                continue
            if len(operands) != 1:
                fail("数组操作必须引用一个已声明的数组地址", node)
            base = operands[0]
            if not isinstance(base.value, ArraySlot) or slots.get((base.value.kind, base.value.index)) != base.value or base.type_hint != "array_address":
                fail("数组地址来源与当前函数声明不一致", node)
            slot = base.value
            key = (slot.kind, slot.index)
            if node.attrs.get("length") != slot.length or node.attrs.get("element_type") != slot.element_type:
                fail("数组长度或元素类型与声明不一致", node)
            if node.op == "alloc_array":
                if result != base or node.args or key in allocations or (slot.kind == "global" and function.name != "<module>"):
                    fail("数组分配指令无效或重复", node)
                allocations[key] = (block.name, position)
            elif node.op == "array_address":
                if node.args != [base] or result is None or result.kind != "vreg" or result.type_hint != f"array_ref:{slot.element_type}":
                    fail("数组引用必须保留存储的元素类型", node)
                if slot.kind != "global" or function.name == "<module>":
                    uses.append((key, block.name, position, node))
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
                if slot.kind != "global" or function.name == "<module>":
                    uses.append((key, block.name, position, node))
    required = {key for key in slots if key[0] != "global" or function.name == "<module>"}
    if set(allocations) != required:
        fail("数组存储缺少对应的分配指令")
    if not uses and not reference_uses and not reference_loads:
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
    for name, block, position, node in reference_uses:
        _, origin, definition_position = reference_definitions[name]
        if (origin == block and definition_position >= position) or (block in reachable and origin not in dominators[block]):
            fail("数组引用必须在使用前建立", node)
    for key, block, position, node in reference_loads:
        if block in reachable and not any(
            (origin == block and store_position < position) or (origin != block and origin in dominators[block])
            for origin, store_position in reference_stores.get(key, [])
        ):
            fail("数组引用局部槽必须在读取前初始化", node)

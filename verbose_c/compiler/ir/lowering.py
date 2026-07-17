from bisect import bisect_right
from collections import deque
from typing import Any

from verbose_c.compiler.ir.model import (
    IRBasicBlock,
    IRFunction,
    IRInstruction,
    IRLoweringError,
    IRProgram,
    IRTerminator,
    IRValue,
)
from verbose_c.compiler.ir.validator import validate_ir_function
from verbose_c.compiler.opcode import Opcode
from verbose_c.object.function import VBCFunction


_BINARY_OPS = {
    Opcode.ADD: "binary add",
    Opcode.SUBTRACT: "binary sub",
    Opcode.MULTIPLY: "binary mul",
    Opcode.DIVIDE: "binary div",
    Opcode.MODULO: "binary mod",
    Opcode.EQUAL: "binary eq",
    Opcode.NOT_EQUAL: "binary ne",
    Opcode.LESS_THAN: "binary lt",
    Opcode.LESS_EQUAL: "binary le",
    Opcode.GREATER_THAN: "binary gt",
    Opcode.GREATER_EQUAL: "binary ge",
}


def lower_compiler_output_to_ir(output: Any) -> IRProgram:
    """将编译输出中的模块与函数字节码 lowering 为 IR 程序。"""
    module_ir = lower_bytecode_unit_to_ir(
        name="<module>",
        bytecode=output.bytecode,
        constants=output.constant_pool,
        lineno_table=output.lineno_table or [],
        source_path=None,
    )
    functions = {}
    for name, result in output.function_compilation_results.items():
        if not isinstance(result, dict):
            continue
        function_ir = lower_bytecode_unit_to_ir(
            name=name,
            bytecode=result.get("bytecode", []),
            constants=result.get("constants", []),
            lineno_table=result.get("lineno_table", []),
            source_path=None,
            param_count=result.get("param_count", _function_param_count(result)),
            param_types=result.get("param_types", _function_param_types(result)),
            local_count=result.get("local_count", _function_local_count(result)),
            return_type=result.get("return_type", "int64"),
        )
        result["ir"] = function_ir
        functions[name] = function_ir
    return IRProgram(module=module_ir, functions=functions)


def lower_bytecode_unit_to_ir(
    *,
    name: str,
    bytecode: list[tuple[Any, ...]],
    constants: list[Any],
    lineno_table: list[tuple[int, int]] | None = None,
    source_path: str | None = None,
    param_count: int = 0,
    param_types: list[str] | None = None,
    local_count: int = 0,
    return_type: str = "int64",
) -> IRFunction:
    """将单个字节码单元 lowering 为 IR 函数。"""
    if not bytecode:
        function = IRFunction(
            name=name,
            blocks=[IRBasicBlock("bb_0", 0, 0, terminator=IRTerminator("halt"))],
            constants=constants,
            param_count=param_count,
            param_types=list(param_types or []),
            local_count=local_count,
            return_type=return_type,
            source_path=source_path,
            lineno_table=list(lineno_table or []),
        )
        validate_ir_function(function)
        return function

    lowering = _LoweringContext(name, bytecode, constants, list(lineno_table or []))
    function = lowering.lower(
        source_path=source_path,
        param_count=param_count,
        param_types=list(param_types or []),
        local_count=local_count,
        return_type=return_type,
    )
    validate_ir_function(function)
    return function


class _LoweringContext:
    def __init__(
        self,
        function_name: str,
        bytecode: list[tuple[Any, ...]],
        constants: list[Any],
        lineno_table: list[tuple[int, int]],
    ):
        self.function_name = function_name
        self.bytecode = bytecode
        self.constants = constants
        self.lineno_table = lineno_table
        self.blocks: list[IRBasicBlock] = []
        self.block_by_name: dict[str, IRBasicBlock] = {}
        self.block_by_start: dict[int, IRBasicBlock] = {}
        self.pc_to_block: dict[int, IRBasicBlock] = {}
        self.known_entry_stacks: set[str] = set()
        self.phi_inputs: dict[str, dict[int, dict[str, IRValue]]] = {}
        self.phi_values: dict[str, dict[int, IRValue]] = {}
        self.entry_stack_sources: dict[str, list[str]] = {}
        self.temp_id = 0

    def lower(self, *, source_path: str | None, param_count: int, param_types: list[str], local_count: int, return_type: str) -> IRFunction:
        self._create_blocks()
        self._simulate_blocks()
        function = IRFunction(
            name=self.function_name,
            blocks=self.blocks,
            constants=self.constants,
            param_count=param_count,
            param_types=param_types,
            local_count=local_count,
            return_type=return_type,
            source_path=source_path,
            lineno_table=self.lineno_table,
        )
        return function

    def _create_blocks(self) -> None:
        leaders = {0}
        for pc, instruction in enumerate(self.bytecode):
            opcode = instruction[0]
            if opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
                target = self._jump_target(instruction, pc)
                leaders.add(target)
                if pc + 1 < len(self.bytecode):
                    leaders.add(pc + 1)
            elif opcode in (Opcode.RETURN, Opcode.HALT) and pc + 1 < len(self.bytecode):
                leaders.add(pc + 1)

        sorted_leaders = sorted(leader for leader in leaders if leader <= len(self.bytecode))
        for index, start_pc in enumerate(sorted_leaders):
            if start_pc >= len(self.bytecode):
                continue
            next_start = sorted_leaders[index + 1] if index + 1 < len(sorted_leaders) else len(self.bytecode)
            block = IRBasicBlock(
                name=f"bb_{start_pc}",
                start_pc=start_pc,
                end_pc=next_start - 1,
            )
            self.blocks.append(block)
            self.block_by_name[block.name] = block
            self.block_by_start[start_pc] = block
            for pc in range(start_pc, next_start):
                self.pc_to_block[pc] = block

    def _simulate_blocks(self) -> None:
        entry = self.blocks[0]
        self._set_entry_stack(entry, tuple(), "<entry>")
        queue = deque([entry.name])
        iterations = 0
        max_iterations = max(20, len(self.blocks) * 20)

        while queue:
            iterations += 1
            if iterations > max_iterations:
                raise self._error(0, "IR lowering 工作队列未收敛")
            block_name = queue.popleft()
            block = self.block_by_name[block_name]

            block.instructions = []
            block.terminator = None
            block.successors = []
            self._emit_phi_instructions(block)
            stack = list(block.entry_stack)
            for pc in range(block.start_pc, block.end_pc + 1):
                instruction = self.bytecode[pc]
                opcode = instruction[0]
                if opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE, Opcode.RETURN, Opcode.HALT):
                    self._lower_terminator(block, pc, instruction, stack)
                    break
                self._lower_instruction(block, pc, instruction, stack)
            else:
                next_block = self._next_block(block)
                if next_block is None:
                    block.terminator = IRTerminator("halt", source_pc=block.end_pc, source_line=self._line_for_pc(block.end_pc))
                    block.successors = []
                else:
                    block.terminator = IRTerminator(
                        "jump",
                        targets=[next_block.name],
                        source_pc=block.end_pc,
                        source_line=self._line_for_pc(block.end_pc),
                    )
                    block.successors = [next_block.name]

            block.exit_stack = tuple(stack)
            for successor_name in block.successors:
                successor = self.block_by_name[successor_name]
                if block.name not in successor.predecessors:
                    successor.predecessors.append(block.name)
                outgoing_stack = self._stack_for_successor(block, successor, block.exit_stack)
                changed = self._set_entry_stack(successor, outgoing_stack, block.name)
                if changed:
                    queue.append(successor.name)

        unprocessed = [block.name for block in self.blocks if block.name not in self.known_entry_stacks]
        if unprocessed:
            for block_name in unprocessed:
                block = self.block_by_name[block_name]
                self._set_entry_stack(block, tuple(), "<unreachable>")
                queue.append(block.name)
            while queue:
                block_name = queue.popleft()
                block = self.block_by_name[block_name]
                block.instructions = []
                block.terminator = None
                block.successors = []
                self._emit_phi_instructions(block)
                stack = list(block.entry_stack)
                for pc in range(block.start_pc, block.end_pc + 1):
                    instruction = self.bytecode[pc]
                    opcode = instruction[0]
                    if opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE, Opcode.RETURN, Opcode.HALT):
                        self._lower_terminator(block, pc, instruction, stack)
                        break
                    self._lower_instruction(block, pc, instruction, stack)
                else:
                    block.terminator = IRTerminator("halt", source_pc=block.end_pc, source_line=self._line_for_pc(block.end_pc))

    def _lower_instruction(
        self,
        block: IRBasicBlock,
        pc: int,
        instruction: tuple[Any, ...],
        stack: list[IRValue],
    ) -> None:
        opcode = instruction[0]
        operand = instruction[1] if len(instruction) > 1 else None
        line = self._line_for_pc(pc)

        if opcode == Opcode.NOP or opcode in (Opcode.ENTER_SCOPE, Opcode.EXIT_SCOPE):
            return
        if opcode == Opcode.LOAD_CONSTANT:
            self._require_operand(opcode, operand, pc)
            if not isinstance(operand, int) or operand < 0 or operand >= len(self.constants):
                raise self._error(pc, f"LOAD_CONSTANT 常量索引无效: {operand!r}")
            result = self._temp(_constant_type_name(self.constants[operand]))
            value = IRValue.constant(operand, self.constants[operand])
            block.instructions.append(IRInstruction("const", result=result, args=[value], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.LOAD_LOCAL_VAR:
            self._require_operand(opcode, operand, pc)
            result = self._temp()
            local = IRValue.local(operand)
            block.instructions.append(IRInstruction("load_local", result=result, args=[local], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.STORE_LOCAL_VAR:
            self._require_operand(opcode, operand, pc)
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(
                IRInstruction("store_local", args=[IRValue.local(operand), value], source_pc=pc, source_line=line)
            )
            return
        if opcode == Opcode.LOAD_GLOBAL_VAR:
            self._require_operand(opcode, operand, pc)
            result = self._temp()
            block.instructions.append(
                IRInstruction("load_global", result=result, args=[IRValue.global_(str(operand))], source_pc=pc, source_line=line)
            )
            stack.append(result)
            return
        if opcode == Opcode.STORE_GLOBAL_VAR:
            self._require_operand(opcode, operand, pc)
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(
                IRInstruction("store_global", args=[IRValue.global_(str(operand)), value], source_pc=pc, source_line=line)
            )
            return
        if opcode in _BINARY_OPS:
            right = self._pop(stack, pc, opcode.name)
            left = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(
                IRInstruction(_BINARY_OPS[opcode], result=result, args=[left, right], source_pc=pc, source_line=line)
            )
            stack.append(result)
            return
        if opcode == Opcode.UNARY_MINUS:
            value = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(IRInstruction("unary neg", result=result, args=[value], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.LOGICAL_NOT:
            value = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(IRInstruction("unary not", result=result, args=[value], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.CAST:
            self._require_operand(opcode, operand, pc)
            value = self._pop(stack, pc, opcode.name)
            target_type = getattr(operand, "name", str(operand))
            result = self._temp(target_type)
            block.instructions.append(
                IRInstruction("cast", result=result, args=[value], attrs={"target_type": target_type}, source_pc=pc, source_line=line)
            )
            stack.append(result)
            return
        if opcode == Opcode.CALL_FUNCTION:
            self._require_operand(opcode, operand, pc)
            if not isinstance(operand, int):
                raise self._error(pc, f"CALL_FUNCTION 参数数量必须是整数: {operand!r}")
            args = [self._pop(stack, pc, opcode.name) for _ in range(operand)]
            args.reverse()
            callee = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(
                IRInstruction("call", result=result, args=[callee, *args], attrs={"argc": operand}, source_pc=pc, source_line=line)
            )
            stack.append(result)
            return
        if opcode == Opcode.LOAD_ADDRESS:
            self._require_operand(opcode, operand, pc)
            identifier, target_type = operand
            result = self._temp(_enum_name(target_type))
            args = [IRValue.local(identifier) if isinstance(identifier, int) else IRValue.global_(str(identifier))]
            block.instructions.append(
                IRInstruction(
                    "address_of",
                    result=result,
                    args=args,
                    attrs={"target_type": _enum_name(target_type)},
                    source_pc=pc,
                    source_line=line,
                )
            )
            stack.append(result)
            return
        if opcode == Opcode.LOAD_BY_POINTER:
            pointer = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(IRInstruction("load_pointer", result=result, args=[pointer], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.STORE_BY_POINTER:
            pointer = self._pop(stack, pc, opcode.name)
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(IRInstruction("store_pointer", args=[pointer, value], source_pc=pc, source_line=line))
            stack.append(value)
            return
        if opcode == Opcode.ALLOC_ARRAY:
            self._require_operand(opcode, operand, pc)
            length, element_type = operand
            result = self._temp("INT")
            block.instructions.append(
                IRInstruction(
                    "alloc_array",
                    result=result,
                    attrs={"length": length, "element_type": _enum_name(element_type)},
                    source_pc=pc,
                    source_line=line,
                )
            )
            stack.append(result)
            return
        if opcode == Opcode.LOAD_INDEX:
            self._require_operand(opcode, operand, pc)
            array_length, element_type = operand
            index = self._pop(stack, pc, opcode.name)
            base = self._pop(stack, pc, opcode.name)
            result = self._temp(_enum_name(element_type))
            block.instructions.append(
                IRInstruction(
                    "load_index",
                    result=result,
                    args=[base, index],
                    attrs={"length": array_length, "element_type": _enum_name(element_type)},
                    source_pc=pc,
                    source_line=line,
                )
            )
            stack.append(result)
            return
        if opcode == Opcode.STORE_INDEX:
            self._require_operand(opcode, operand, pc)
            array_length, element_type = operand
            index = self._pop(stack, pc, opcode.name)
            base = self._pop(stack, pc, opcode.name)
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(
                IRInstruction(
                    "store_index",
                    args=[base, index, value],
                    attrs={"length": array_length, "element_type": _enum_name(element_type)},
                    source_pc=pc,
                    source_line=line,
                )
            )
            stack.append(value)
            return
        if opcode == Opcode.ARRAY_DECAY:
            self._require_operand(opcode, operand, pc)
            base = self._pop(stack, pc, opcode.name)
            result = self._temp("POINTER")
            block.instructions.append(
                IRInstruction("array_decay", result=result, args=[base], attrs={"element_type": _enum_name(operand)}, source_pc=pc, source_line=line)
            )
            stack.append(result)
            return
        if opcode == Opcode.ALLOC_STRUCT:
            self._require_operand(opcode, operand, pc)
            result = self._temp("INT")
            block.instructions.append(IRInstruction("alloc_struct", result=result, attrs={"layout_const": operand}, source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.LOAD_FIELD:
            self._require_operand(opcode, operand, pc)
            slot_count, offset = operand
            base = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(
                IRInstruction(
                    "load_field",
                    result=result,
                    args=[base],
                    attrs={"slot_count": slot_count, "offset": offset},
                    source_pc=pc,
                    source_line=line,
                )
            )
            stack.append(result)
            return
        if opcode == Opcode.STORE_FIELD:
            self._require_operand(opcode, operand, pc)
            slot_count, offset = operand
            base = self._pop(stack, pc, opcode.name)
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(
                IRInstruction(
                    "store_field",
                    args=[base, value],
                    attrs={"slot_count": slot_count, "offset": offset},
                    source_pc=pc,
                    source_line=line,
                )
            )
            stack.append(value)
            return
        if opcode == Opcode.POINTER_ADDRESS:
            pointer = self._pop(stack, pc, opcode.name)
            result = self._temp("INT")
            block.instructions.append(IRInstruction("pointer_address", result=result, args=[pointer], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.COPY_STRUCT:
            self._require_operand(opcode, operand, pc)
            source = self._pop(stack, pc, opcode.name)
            result = self._temp("INT")
            block.instructions.append(IRInstruction("copy_struct", result=result, args=[source], attrs={"slot_count": operand}, source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode in (Opcode.POINTER_ADD, Opcode.POINTER_SUB):
            offset = self._pop(stack, pc, opcode.name)
            pointer = self._pop(stack, pc, opcode.name)
            result = self._temp("POINTER")
            op_name = "pointer_add" if opcode == Opcode.POINTER_ADD else "pointer_sub"
            block.instructions.append(IRInstruction(op_name, result=result, args=[pointer, offset], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.POINTER_DIFF:
            right = self._pop(stack, pc, opcode.name)
            left = self._pop(stack, pc, opcode.name)
            result = self._temp("INT")
            block.instructions.append(IRInstruction("pointer_diff", result=result, args=[left, right], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.GET_PROPERTY:
            property_name = self._pop(stack, pc, opcode.name)
            instance = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(IRInstruction("get_property", result=result, args=[instance, property_name], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.SET_PROPERTY:
            property_name = self._pop(stack, pc, opcode.name)
            instance = self._pop(stack, pc, opcode.name)
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(IRInstruction("set_property", args=[instance, property_name, value], source_pc=pc, source_line=line))
            stack.append(value)
            return
        if opcode == Opcode.NEW_INSTANCE:
            self._require_operand(opcode, operand, pc)
            if not isinstance(operand, int):
                raise self._error(pc, f"NEW_INSTANCE 参数数量必须是整数: {operand!r}")
            args = [self._pop(stack, pc, opcode.name) for _ in range(operand)]
            args.reverse()
            class_value = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(
                IRInstruction("new_instance", result=result, args=[class_value, *args], attrs={"argc": operand}, source_pc=pc, source_line=line)
            )
            stack.append(result)
            return
        if opcode == Opcode.SUPER_GET:
            property_name = self._pop(stack, pc, opcode.name)
            current_class = self._pop(stack, pc, opcode.name)
            instance = self._pop(stack, pc, opcode.name)
            result = self._temp()
            block.instructions.append(IRInstruction("super_get", result=result, args=[instance, current_class, property_name], source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.ALLOC_OBJECT:
            result = self._temp()
            block.instructions.append(IRInstruction("alloc_object", result=result, source_pc=pc, source_line=line))
            stack.append(result)
            return
        if opcode == Opcode.FREE_OBJECT:
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(IRInstruction("free_object", args=[value], source_pc=pc, source_line=line))
            return
        if opcode == Opcode.LOAD_FUNCTION:
            block.instructions.append(IRInstruction("load_function", source_pc=pc, source_line=line))
            return
        if opcode == Opcode.DEBUG_PRINT:
            value = self._peek(stack, pc, opcode.name) if stack else IRValue.constant(-1, "<empty>")
            block.instructions.append(IRInstruction("debug_print", args=[value], source_pc=pc, source_line=line))
            return
        if opcode == Opcode.SET_EXIT_CODE:
            value = self._pop(stack, pc, opcode.name) if stack else IRValue.constant(-1, 0)
            block.instructions.append(IRInstruction("set_exit_code", args=[value], source_pc=pc, source_line=line))
            return
        if opcode == Opcode.DUP:
            value = self._peek(stack, pc, opcode.name)
            stack.append(value)
            return
        if opcode == Opcode.SWAP:
            right = self._pop(stack, pc, opcode.name)
            left = self._pop(stack, pc, opcode.name)
            stack.append(right)
            stack.append(left)
            return
        if opcode == Opcode.POP:
            value = self._pop(stack, pc, opcode.name)
            block.instructions.append(IRInstruction("discard", args=[value], source_pc=pc, source_line=line))
            return
        raise self._error(pc, f"未知或暂不支持 opcode {opcode.name} lowering 到 IR")

    def _lower_terminator(
        self,
        block: IRBasicBlock,
        pc: int,
        instruction: tuple[Any, ...],
        stack: list[IRValue],
    ) -> None:
        opcode = instruction[0]
        line = self._line_for_pc(pc)
        if opcode == Opcode.JUMP:
            target = self._target_block_name(self._jump_target(instruction, pc), pc)
            block.terminator = IRTerminator("jump", targets=[target], source_pc=pc, source_line=line)
            block.successors = [target]
            return
        if opcode == Opcode.JUMP_IF_FALSE:
            condition = self._pop(stack, pc, opcode.name)
            false_target = self._target_block_name(self._jump_target(instruction, pc), pc)
            next_block = self._next_block(block)
            if next_block is None:
                raise self._error(pc, "JUMP_IF_FALSE 缺少 true fallthrough 基本块")
            block.terminator = IRTerminator(
                "branch",
                targets=[next_block.name, false_target],
                args=[condition],
                source_pc=pc,
                source_line=line,
            )
            block.successors = [next_block.name, false_target]
            return
        if opcode == Opcode.RETURN:
            value = self._pop(stack, pc, opcode.name)
            block.terminator = IRTerminator("return", args=[value], source_pc=pc, source_line=line)
            block.successors = []
            return
        if opcode == Opcode.HALT:
            block.terminator = IRTerminator("halt", source_pc=pc, source_line=line)
            block.successors = []
            return
        raise self._error(pc, f"{opcode.name} 不是有效的终结 opcode")

    def _set_entry_stack(self, block: IRBasicBlock, stack: tuple[IRValue, ...], predecessor: str) -> bool:
        if block.name not in self.known_entry_stacks:
            block.entry_stack = stack
            self.entry_stack_sources[block.name] = [predecessor for _value in stack]
            self.known_entry_stacks.add(block.name)
            return True
        if len(block.entry_stack) != len(stack):
            if len(block.entry_stack) > len(stack):
                block.entry_stack = block.entry_stack[:len(stack)]
                self.entry_stack_sources[block.name] = self.entry_stack_sources.get(block.name, [])[:len(stack)]
                for slot in list(self.phi_values.get(block.name, {})):
                    if slot >= len(stack):
                        self.phi_values[block.name].pop(slot, None)
                        self.phi_inputs.get(block.name, {}).pop(slot, None)
                return True
            stack = stack[:len(block.entry_stack)]
        if block.entry_stack != stack:
            changed = False
            merged = list(block.entry_stack)
            for index, (existing, incoming) in enumerate(zip(block.entry_stack, stack)):
                if existing == incoming:
                    continue
                phi_value = self.phi_values.setdefault(block.name, {}).get(index)
                if phi_value is None:
                    phi_value = self._temp(existing.type_hint or incoming.type_hint)
                    self.phi_values[block.name][index] = phi_value
                    existing_source = self.entry_stack_sources.get(block.name, ["<existing>"] * len(block.entry_stack))[index]
                    self.phi_inputs.setdefault(block.name, {})[index] = {existing_source: existing}
                    changed = True
                incoming_values = self.phi_inputs.setdefault(block.name, {}).setdefault(index, {})
                if incoming_values.get(predecessor) != incoming:
                    incoming_values[predecessor] = incoming
                    changed = True
                merged[index] = phi_value
            new_entry = tuple(merged)
            if block.entry_stack != new_entry:
                block.entry_stack = new_entry
                self.entry_stack_sources[block.name] = ["phi" for _value in new_entry]
                changed = True
            return changed
        return False

    def _stack_for_successor(self, block: IRBasicBlock, successor: IRBasicBlock, stack: tuple[IRValue, ...]) -> tuple[IRValue, ...]:
        if successor.name not in self.known_entry_stacks:
            return stack
        expected = successor.entry_stack
        if len(stack) > len(expected):
            trimmed = list(stack)
            while len(trimmed) > len(expected):
                value = trimmed.pop()
                block.instructions.append(
                    IRInstruction(
                        "discard",
                        args=[value],
                        attrs={"reason": "trim_stack_for_successor", "successor": successor.name},
                        source_pc=block.end_pc,
                        source_line=self._line_for_pc(block.end_pc),
                    )
                )
            return tuple(trimmed)
        return stack

    def _emit_phi_instructions(self, block: IRBasicBlock) -> None:
        for index, result in sorted(self.phi_values.get(block.name, {}).items()):
            incoming = self.phi_inputs.get(block.name, {}).get(index, {})
            block.instructions.append(
                IRInstruction(
                    "phi",
                    result=result,
                    args=list(incoming.values()),
                    attrs={"slot": index, "incoming_blocks": list(incoming.keys())},
                    source_pc=block.start_pc,
                    source_line=self._line_for_pc(block.start_pc),
                )
            )

    def _jump_target(self, instruction: tuple[Any, ...], pc: int) -> int:
        if len(instruction) != 2 or not isinstance(instruction[1], int):
            raise self._error(pc, f"{instruction[0].name} 缺少已解析的整数跳转目标")
        target = instruction[1]
        if target < 0 or target > len(self.bytecode):
            raise self._error(pc, f"{instruction[0].name} 跳转目标越界: {target}")
        return target

    def _target_block_name(self, target: int, pc: int) -> str:
        block = self.block_by_start.get(target)
        if block is None:
            raise self._error(pc, f"跳转目标 {target} 不是基本块入口")
        return block.name

    def _next_block(self, block: IRBasicBlock) -> IRBasicBlock | None:
        for index, candidate in enumerate(self.blocks):
            if candidate.name == block.name:
                return self.blocks[index + 1] if index + 1 < len(self.blocks) else None
        return None

    def _temp(self, type_hint: str | None = None) -> IRValue:
        value = IRValue.temp(f"t{self.temp_id}", type_hint=type_hint)
        self.temp_id += 1
        return value

    def _pop(self, stack: list[IRValue], pc: int, op_name: str) -> IRValue:
        if not stack:
            raise self._error(pc, f"{op_name} 需要操作数，但模拟栈为空")
        return stack.pop()

    def _peek(self, stack: list[IRValue], pc: int, op_name: str) -> IRValue:
        if not stack:
            raise self._error(pc, f"{op_name} 需要操作数，但模拟栈为空")
        return stack[-1]

    def _require_operand(self, opcode: Opcode, operand: Any, pc: int) -> None:
        if operand is None:
            raise self._error(pc, f"{opcode.name} 缺少操作数")

    def _line_for_pc(self, pc: int) -> int | None:
        if not self.lineno_table:
            return None
        offsets = [item[0] for item in self.lineno_table]
        index = bisect_right(offsets, pc)
        if index == 0:
            return None
        return self.lineno_table[index - 1][1]

    def _error(self, pc: int, message: str) -> IRLoweringError:
        line = self._line_for_pc(pc)
        location = f"函数 {self.function_name}, PC {pc}"
        if line is not None:
            location += f", 行 {line}"
        return IRLoweringError(f"{location}: {message}", line=line)


def _constant_type_name(value: Any) -> str | None:
    object_type = getattr(value, "_object_type", None)
    if object_type is not None:
        return getattr(object_type, "name", str(object_type))
    return type(value).__name__


def _enum_name(value: Any) -> str:
    return getattr(value, "name", str(value))


def _function_param_count(result: dict[str, Any]) -> int:
    for constant in result.get("constants", []):
        if isinstance(constant, VBCFunction):
            return constant.param_count
    return 0


def _function_param_types(result: dict[str, Any]) -> list[str]:
    """从旧函数元数据回退构造参数类型表。"""
    return ["int64"] * _function_param_count(result)


def _function_local_count(result: dict[str, Any]) -> int:
    for constant in result.get("constants", []):
        if isinstance(constant, VBCFunction):
            return constant.local_count
    return 0

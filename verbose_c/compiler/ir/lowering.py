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


_UNSUPPORTED_OPCODES = {
    Opcode.LOAD_ADDRESS,
    Opcode.LOAD_BY_POINTER,
    Opcode.STORE_BY_POINTER,
    Opcode.ALLOC_ARRAY,
    Opcode.LOAD_INDEX,
    Opcode.STORE_INDEX,
    Opcode.ARRAY_DECAY,
    Opcode.ALLOC_STRUCT,
    Opcode.LOAD_FIELD,
    Opcode.STORE_FIELD,
    Opcode.POINTER_ADDRESS,
    Opcode.COPY_STRUCT,
    Opcode.GET_PROPERTY,
    Opcode.SET_PROPERTY,
    Opcode.NEW_INSTANCE,
    Opcode.SUPER_GET,
    Opcode.DEBUG_PRINT,
    Opcode.POINTER_ADD,
    Opcode.POINTER_SUB,
    Opcode.POINTER_DIFF,
    Opcode.ALLOC_OBJECT,
    Opcode.FREE_OBJECT,
    Opcode.LOAD_FUNCTION,
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
            local_count=result.get("local_count", _function_local_count(result)),
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
    local_count: int = 0,
) -> IRFunction:
    """将单个字节码单元 lowering 为 IR 函数。"""
    if not bytecode:
        function = IRFunction(
            name=name,
            blocks=[IRBasicBlock("bb_0", 0, 0, terminator=IRTerminator("halt"))],
            constants=constants,
            param_count=param_count,
            local_count=local_count,
            source_path=source_path,
            lineno_table=list(lineno_table or []),
        )
        validate_ir_function(function)
        return function

    lowering = _LoweringContext(name, bytecode, constants, list(lineno_table or []))
    function = lowering.lower(
        source_path=source_path,
        param_count=param_count,
        local_count=local_count,
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
        self.temp_id = 0

    def lower(self, *, source_path: str | None, param_count: int, local_count: int) -> IRFunction:
        self._create_blocks()
        self._simulate_blocks()
        function = IRFunction(
            name=self.function_name,
            blocks=self.blocks,
            constants=self.constants,
            param_count=param_count,
            local_count=local_count,
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
        self._set_entry_stack(entry, tuple())
        queue = deque([entry.name])
        processed: set[str] = set()

        while queue:
            block_name = queue.popleft()
            block = self.block_by_name[block_name]
            if block_name in processed:
                continue
            processed.add(block_name)

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
                changed = self._set_entry_stack(successor, block.exit_stack)
                if changed:
                    queue.append(successor.name)

        unprocessed = [block.name for block in self.blocks if block.name not in processed]
        if unprocessed:
            raise self._error(0, f"存在不可达或入口栈未知的基本块: {', '.join(unprocessed)}")

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
        if opcode in _UNSUPPORTED_OPCODES:
            raise self._error(pc, f"暂不支持 opcode {opcode.name} lowering 到 IR")
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

    def _set_entry_stack(self, block: IRBasicBlock, stack: tuple[IRValue, ...]) -> bool:
        if block.name not in self.known_entry_stacks:
            block.entry_stack = stack
            self.known_entry_stacks.add(block.name)
            return True
        if block.entry_stack != stack:
            raise self._error(
                block.start_pc,
                f"控制流合流处栈状态不一致: {block.name} 已有 {block.entry_stack!r}, 新输入 {stack!r}",
            )
        return False

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


def _function_param_count(result: dict[str, Any]) -> int:
    for constant in result.get("constants", []):
        if isinstance(constant, VBCFunction):
            return constant.param_count
    return 0


def _function_local_count(result: dict[str, Any]) -> int:
    for constant in result.get("constants", []):
        if isinstance(constant, VBCFunction):
            return constant.local_count
    return 0

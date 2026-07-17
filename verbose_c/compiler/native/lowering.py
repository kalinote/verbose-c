from typing import Any

from verbose_c.compiler.ir.model import IRFunction, IRInstruction, IRProgram, IRTerminator, IRValue
from verbose_c.compiler.native.abi import StackFrameLayout, WINDOWS_X64_ABI
from verbose_c.compiler.native.errors import NativeLoweringError
from verbose_c.compiler.native.machine_ir import (
    MachineBlock,
    MachineFunction,
    MachineInstruction,
    MachineOperand,
    MachineProgram,
    MachineTerminator,
    StackSlot,
    VirtualRegister,
)
from verbose_c.compiler.native.target import NativeTarget
from verbose_c.compiler.native.validator import validate_machine_function
from verbose_c.object.function import VBCFunction
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_null import VBCNull
from verbose_c.vm.builtins_functions import BUILTIN_FUNCTION_SIGNATURES


_BINARY_OPS = {
    "binary add": "add",
    "binary sub": "sub",
    "binary mul": "imul",
    "binary div": "idiv",
    "binary mod": "imod",
    "binary eq": "cmp_eq",
    "binary ne": "cmp_ne",
    "binary lt": "cmp_lt",
    "binary le": "cmp_le",
    "binary gt": "cmp_gt",
    "binary ge": "cmp_ge",
}

_COMPARE_MACHINE_OPS = {"cmp_eq", "cmp_ne", "cmp_lt", "cmp_le", "cmp_gt", "cmp_ge"}

_NATIVE_INTEGER_CAST_TARGETS = {
    "char",
    "short",
    "int",
    "long",
    "longlong",
    "long long",
    "nlint",
    "unlimited int",
    "int64",
}

_NATIVE_BOOL_CAST_TARGETS = {"bool", "bool64"}

_UNSUPPORTED_FEATURES = {
    "alloc_array": "array",
    "load_index": "array",
    "store_index": "array",
    "array_decay": "array_decay",
    "alloc_struct": "struct",
    "load_field": "struct",
    "store_field": "struct",
    "copy_struct": "struct",
    "address_of": "address_escape",
    "load_pointer": "pointer_deref",
    "store_pointer": "pointer_deref",
    "pointer_add": "pointer_arithmetic",
    "pointer_sub": "pointer_arithmetic",
    "pointer_diff": "pointer_arithmetic",
    "pointer_address": "pointer_address",
    "get_property": "class_object",
    "set_property": "class_object",
    "new_instance": "class_object",
    "super_get": "class_object",
    "alloc_object": "gc_object",
    "free_object": "gc_object",
    "debug_print": "debug_print",
}


def lower_ir_program_to_machine(program: IRProgram) -> MachineProgram:
    """将三地址码 IR lowering 为 Windows x64 Machine IR。"""
    function_names = set(program.functions.keys())
    function_return_types = {name: function.return_type for name, function in program.functions.items()}
    function_return_types[program.module.name] = program.module.return_type
    global_slots: dict[str, StackSlot] = {}
    global_value_types: dict[str, str] = {}
    module = _MachineLoweringContext(program.module, function_names, function_return_types, global_slots, global_value_types).lower()
    functions = {
        name: _MachineLoweringContext(function, function_names, function_return_types, global_slots, global_value_types).lower()
        for name, function in program.functions.items()
    }
    shared_global_slots = list(global_slots.values())
    module.frame.global_slots = shared_global_slots
    for function in functions.values():
        function.frame.global_slots = shared_global_slots
    return MachineProgram(
        target=NativeTarget.WINDOWS_X64,
        abi=WINDOWS_X64_ABI,
        module=module,
        functions=functions,
    )


class _MachineLoweringContext:
    def __init__(
        self,
        function: IRFunction,
        function_names: set[str],
        function_return_types: dict[str, str],
        global_slots: dict[str, StackSlot] | None = None,
        global_value_types: dict[str, str] | None = None,
    ):
        self.function = function
        self.function_names = function_names
        self.function_return_types = function_return_types
        self.value_operands: dict[IRValue, MachineOperand] = {}
        self.global_slots = global_slots if global_slots is not None else {}
        self.global_value_types = global_value_types if global_value_types is not None else {}
        self.local_slots: dict[int, StackSlot] = {}
        self.local_value_types: dict[int, str] = {
            index: value_type
            for index, value_type in enumerate(function.param_types[:function.param_count])
            if value_type in {"int64", "bool64"}
        }
        self.temp_slots: list[StackSlot] = []
        self.vreg_id = 0
        self.exit_code_value: MachineOperand | None = None
        self.registered_function_symbols: set[str] = set()

    def lower(self) -> MachineFunction:
        """执行单个函数 lowering。"""
        frame = StackFrameLayout(word_size=WINDOWS_X64_ABI.word_size)
        frame.local_slots = [self._local_slot(index) for index in range(self.function.local_count)]
        machine_blocks = []
        for block in self.function.blocks:
            machine_block = MachineBlock(
                name=block.name,
                predecessors=list(block.predecessors),
                successors=list(block.successors),
            )
            for instruction in block.instructions:
                self._lower_instruction(machine_block, instruction)
            if block.terminator is not None:
                machine_block.terminator = self._lower_terminator(block.terminator)
            machine_blocks.append(machine_block)
        frame.global_slots = list(self.global_slots.values())
        frame.temp_slots = list(self.temp_slots)
        machine_function = MachineFunction(
            name=self.function.name,
            params=[WINDOWS_X64_ABI.argument_location(index) for index in range(self.function.param_count)],
            return_type=self.function.return_type,
            frame=frame,
            blocks=machine_blocks,
            source_path=self.function.source_path,
            virtual_register_count=self.vreg_id,
            exit_code_value=self.exit_code_value,
            param_types=list(self.function.param_types),
        )
        validate_machine_function(machine_function)
        return machine_function

    def _lower_instruction(self, block: MachineBlock, instruction: IRInstruction) -> None:
        op = instruction.op
        if op in _UNSUPPORTED_FEATURES:
            self._unsupported_feature(instruction, _UNSUPPORTED_FEATURES[op])
        if op == "const":
            self._lower_const(block, instruction)
            return
        if op == "load_local":
            local_index = int(instruction.args[0].name)
            result = self._define_result(instruction, type_hint=self.local_value_types.get(local_index))
            block.instructions.append(
                MachineInstruction(
                    "load_stack",
                    result=result,
                    args=[self._operand(instruction.args[0], instruction)],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if op == "store_local":
            target = instruction.args[0]
            value = self._operand(instruction.args[1], instruction)
            self.local_value_types[int(target.name)] = value.type_hint
            block.instructions.append(
                MachineInstruction(
                    "store_stack",
                    args=[self._operand(target, instruction), value],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if op == "load_global":
            symbol = instruction.args[0]
            if symbol.kind != "global":
                self._unsupported_feature(instruction, "non_global_symbol")
            if str(symbol.name) not in self.function_names and str(symbol.name) not in BUILTIN_FUNCTION_SIGNATURES:
                result = self._define_result(instruction, type_hint=self.global_value_types.get(str(symbol.name)))
                block.instructions.append(
                    MachineInstruction(
                        "load_stack",
                        result=result,
                        args=[MachineOperand.slot(self._global_slot(str(symbol.name)))],
                        source_pc=instruction.source_pc,
                        source_line=instruction.source_line,
                    )
                )
                return
            if instruction.result is not None:
                self.value_operands[instruction.result] = MachineOperand.symbol(str(symbol.name))
            return
        if op == "store_global":
            self._lower_store_global(block, instruction)
            return
        if op in _BINARY_OPS:
            machine_op = _BINARY_OPS[op]
            result_type = "bool64" if machine_op in _COMPARE_MACHINE_OPS else "int64"
            self._lower_value_instruction(block, instruction, machine_op, type_hint=result_type)
            return
        if op == "unary neg":
            self._lower_value_instruction(block, instruction, "neg")
            return
        if op == "unary not":
            self._lower_value_instruction(block, instruction, "not_bool", type_hint="bool64")
            return
        if op == "cast":
            raw_target_type = str(instruction.attrs.get("target_type", ""))
            target_type = raw_target_type.lower()
            if target_type in _NATIVE_BOOL_CAST_TARGETS:
                cast_op = "cast_int_bool"
                result_type = "bool64"
            elif target_type in _NATIVE_INTEGER_CAST_TARGETS:
                cast_op = "cast_bool_int"
                result_type = "int64"
            else:
                self._unsupported_type(instruction, raw_target_type or "<missing>")
            self._lower_value_instruction(block, instruction, cast_op, attrs={"target_type": target_type}, type_hint=result_type)
            return
        if op == "phi":
            args = [self._operand(value, instruction) for value in instruction.args]
            incoming_types = {operand.type_hint for operand in args}
            result_type = next(iter(incoming_types)) if len(incoming_types) == 1 and incoming_types <= {"int64", "bool64"} else "int64"
            result = self._define_result(instruction, type_hint=result_type)
            block.instructions.append(
                MachineInstruction(
                    "phi",
                    result=result,
                    args=args,
                    attrs=dict(instruction.attrs),
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if op == "call":
            self._lower_call(block, instruction)
            return
        if op == "set_exit_code":
            value = self._operand(instruction.args[0], instruction)
            self.exit_code_value = value
            block.instructions.append(
                MachineInstruction(
                    "set_exit_code",
                    args=[value],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if op == "discard":
            return
        if op == "load_function":
            self._unsupported_feature(instruction, "dynamic_function_object")
        self._unsupported_feature(instruction, op)

    def _lower_const(self, block: MachineBlock, instruction: IRInstruction) -> None:
        if not instruction.args or instruction.args[0].kind != "constant":
            self._unsupported_feature(instruction, "malformed_constant")
        constant_index = instruction.args[0].name
        constant = self.function.constants[constant_index]
        if isinstance(constant, VBCInteger):
            result = self._define_result(instruction)
            block.instructions.append(
                MachineInstruction(
                    "load_imm",
                    result=result,
                    args=[MachineOperand.imm(constant.value)],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if isinstance(constant, VBCBool):
            result = self._define_result(instruction, type_hint="bool64")
            block.instructions.append(
                MachineInstruction(
                    "load_imm",
                    result=result,
                    args=[MachineOperand.imm(1 if constant.value else 0)],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if isinstance(constant, VBCNull):
            result = self._define_result(instruction)
            block.instructions.append(
                MachineInstruction(
                    "load_imm",
                    result=result,
                    args=[MachineOperand.imm(0)],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if isinstance(constant, VBCFunction):
            if instruction.result is not None:
                self.value_operands[instruction.result] = MachineOperand.symbol(constant.name)
            return
        type_name = getattr(getattr(constant, "_object_type", None), "name", type(constant).__name__)
        self._unsupported_type(instruction, str(type_name))

    def _lower_store_global(self, block: MachineBlock, instruction: IRInstruction) -> None:
        target = instruction.args[0]
        value = self._operand(instruction.args[1], instruction)
        if value.kind == "symbol":
            self.registered_function_symbols.add(str(target.name))
            block.instructions.append(
                MachineInstruction(
                    "mov",
                    args=[MachineOperand.symbol(str(target.name)), value],
                    attrs={"kind": "register_function"},
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        if self.function.name == "<module>":
            self.global_value_types[str(target.name)] = value.type_hint
            block.instructions.append(
                MachineInstruction(
                    "store_stack",
                    args=[MachineOperand.slot(self._global_slot(str(target.name))), value],
                    source_pc=instruction.source_pc,
                    source_line=instruction.source_line,
                )
            )
            return
        self.global_value_types.setdefault(str(target.name), value.type_hint)
        block.instructions.append(
            MachineInstruction(
                "store_stack",
                args=[MachineOperand.slot(self._global_slot(str(target.name))), value],
                source_pc=instruction.source_pc,
                source_line=instruction.source_line,
            )
        )

    def _lower_call(self, block: MachineBlock, instruction: IRInstruction) -> None:
        callee = self._operand(instruction.args[0], instruction)
        if callee.kind != "symbol":
            self._unsupported_feature(instruction, "dynamic_call")
        callee_name = str(callee.value)
        if callee_name in {"_exit", "exit"}:
            self._lower_exit(block, instruction)
            return
        if callee_name in BUILTIN_FUNCTION_SIGNATURES:
            self._unsupported_feature(instruction, f"builtin_function:{callee_name}")
        if callee_name not in self.function_names:
            self._unsupported_feature(instruction, f"unknown_function:{callee_name}")
        args = [self._operand(value, instruction) for value in instruction.args[1:]]
        for arg in args:
            if arg.type_hint not in {"int64", "bool64"}:
                self._unsupported_feature(instruction, f"call_arg_type:{arg.type_hint}")
        arg_locations = [
            WINDOWS_X64_ABI.argument_location(index).__dict__
            for index in range(len(args))
        ]
        callee_return_type = self.function_return_types[callee_name]
        if callee_return_type == "void" and self.function.name == "<module>" and callee_name == "main" and instruction.result is not None:
            self.value_operands[instruction.result] = MachineOperand.imm(0)
        result = None if callee_return_type == "void" else self._define_result(instruction, type_hint=callee_return_type)
        block.instructions.append(
            MachineInstruction(
                "call",
                result=result,
                args=[callee, *args],
                attrs={
                    "argc": len(args),
                    "arg_locations": arg_locations,
                    "return_register": WINDOWS_X64_ABI.registers.return_register,
                    "callee_return_type": callee_return_type,
                },
                source_pc=instruction.source_pc,
                source_line=instruction.source_line,
            )
        )

    def _lower_exit(self, block: MachineBlock, instruction: IRInstruction) -> None:
        """lowering 受限 native _exit 调用。"""
        args = [self._operand(value, instruction) for value in instruction.args[1:]]
        if len(args) != 1:
            self._unsupported_feature(instruction, "builtin_function:_exit_argc")
        if args[0].type_hint not in {"int64", "bool64"}:
            self._unsupported_feature(instruction, f"builtin_function:_exit_arg_type:{args[0].type_hint}")
        if instruction.result is not None:
            self.value_operands[instruction.result] = args[0]
        block.instructions.append(
            MachineInstruction(
                "exit",
                args=[args[0]],
                source_pc=instruction.source_pc,
                source_line=instruction.source_line,
            )
        )

    def _lower_value_instruction(
        self,
        block: MachineBlock,
        instruction: IRInstruction,
        op: str,
        attrs: dict[str, Any] | None = None,
        type_hint: str = "int64",
    ) -> None:
        result = self._define_result(instruction, type_hint=type_hint)
        block.instructions.append(
            MachineInstruction(
                op,
                result=result,
                args=[self._operand(value, instruction) for value in instruction.args],
                attrs=attrs or {},
                source_pc=instruction.source_pc,
                source_line=instruction.source_line,
            )
        )

    def _lower_terminator(self, terminator: IRTerminator) -> MachineTerminator:
        if terminator.op == "jump":
            return MachineTerminator("jmp", targets=list(terminator.targets), source_pc=terminator.source_pc, source_line=terminator.source_line)
        if terminator.op == "branch":
            return MachineTerminator(
                "br",
                targets=list(terminator.targets),
                args=[self._operand(terminator.args[0], terminator)] if terminator.args else [],
                source_pc=terminator.source_pc,
                source_line=terminator.source_line,
            )
        if terminator.op == "return":
            if self.function.return_type == "void":
                args = []
            elif terminator.args:
                args = [self._operand(terminator.args[0], terminator)]
            else:
                args = [MachineOperand.imm(0)]
            return MachineTerminator("ret", args=args, source_pc=terminator.source_pc, source_line=terminator.source_line)
        if terminator.op == "halt":
            args = [] if self.function.return_type == "void" else [self.exit_code_value or MachineOperand.imm(0)]
            return MachineTerminator("ret", args=args, source_pc=terminator.source_pc, source_line=terminator.source_line)
        self._unsupported_feature(terminator, f"terminator:{terminator.op}")

    def _define_result(self, instruction: IRInstruction, type_hint: str | None = None) -> MachineOperand:
        if instruction.result is None:
            self._unsupported_feature(instruction, "missing_result")
        if type_hint is None:
            result_type = str(instruction.result.type_hint or "").lower()
            type_hint = "bool64" if result_type in _NATIVE_BOOL_CAST_TARGETS else "int64"
        result = MachineOperand.vreg(VirtualRegister(f"v{self.vreg_id}", type_hint))
        self.vreg_id += 1
        self.temp_slots.append(StackSlot("temp", len(self.temp_slots), WINDOWS_X64_ABI.word_size))
        self.value_operands[instruction.result] = result
        return result

    def _operand(self, value: IRValue, node: IRInstruction | IRTerminator) -> MachineOperand:
        if value.kind == "temp":
            operand = self.value_operands.get(value)
            if operand is None:
                self._unsupported_feature(node, f"undefined_temp:{value.name}")
            return operand
        if value.kind == "local":
            return MachineOperand.slot(self._local_slot(int(value.name)))
        if value.kind == "global":
            return MachineOperand.symbol(str(value.name))
        if value.kind == "constant":
            constant = self.function.constants[value.name] if isinstance(value.name, int) and value.name >= 0 else value.value_repr
            if isinstance(constant, VBCInteger):
                return MachineOperand.imm(constant.value)
            if isinstance(constant, VBCBool):
                return MachineOperand("imm", 1 if constant.value else 0, "bool64")
            if isinstance(constant, VBCNull):
                return MachineOperand.imm(0)
            self._unsupported_type(node, str(getattr(getattr(constant, "_object_type", None), "name", type(constant).__name__)))
        self._unsupported_feature(node, f"operand:{value.kind}")

    def _local_slot(self, index: int) -> StackSlot:
        slot = self.local_slots.get(index)
        if slot is None:
            slot = StackSlot("local", index, WINDOWS_X64_ABI.word_size)
            self.local_slots[index] = slot
        return slot

    def _global_slot(self, name: str) -> StackSlot:
        """取得模块入口内的受限全局标量栈槽。"""
        slot = self.global_slots.get(name)
        if slot is None:
            slot = StackSlot("global", name, WINDOWS_X64_ABI.word_size)
            self.global_slots[name] = slot
        return slot

    def _unsupported_type(self, node: IRInstruction | IRTerminator, type_name: str) -> None:
        raise NativeLoweringError(f"{self._location(node)}: native MVP 暂不支持类型 '{type_name}'")

    def _unsupported_feature(self, node: IRInstruction | IRTerminator, feature: str) -> None:
        raise NativeLoweringError(f"{self._location(node)}: native MVP 暂不支持特性 '{feature}'")

    def _location(self, node: IRInstruction | IRTerminator) -> str:
        op_name = getattr(node, "op", "<unknown>")
        parts = [f"函数 {self.function.name}", f"IR 指令 {op_name}"]
        if node.source_line is not None:
            parts.append(f"行 {node.source_line}")
        if node.source_pc is not None:
            parts.append(f"PC {node.source_pc}")
        return ", ".join(parts)

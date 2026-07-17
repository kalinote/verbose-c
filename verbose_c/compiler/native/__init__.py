from verbose_c.compiler.native.codegen import (
    NativeCallFrameAllocation,
    NativeCodeFunction,
    NativeCodeInstruction,
    NativeCodeProgram,
    NativeExitProbe,
    NativeRelocation,
    NativeRegisterAllocation,
    NativeStackSlotAllocation,
    NativeSymbol,
    format_native_code_program,
    generate_native_code,
    validate_native_code_map_bytes,
    validate_native_text_section_map_bytes,
    native_code_program_map,
    validate_native_code_program_map,
)
from verbose_c.compiler.native.errors import NativeCodegenError, NativeLoweringError
from verbose_c.compiler.native.formatter import format_machine_program
from verbose_c.compiler.native.lowering import lower_ir_program_to_machine
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
from verbose_c.compiler.native.pe_writer import build_native_pe_image, validate_native_pe_image_bytes
from verbose_c.compiler.native.target import NativeTarget
from verbose_c.compiler.native.runner import run_native_bytes_in_memory, run_native_text_section_bytes_in_memory

__all__ = [
    "MachineBlock",
    "MachineFunction",
    "MachineInstruction",
    "MachineOperand",
    "MachineProgram",
    "MachineTerminator",
    "NativeCodeFunction",
    "NativeCodeInstruction",
    "NativeCodeProgram",
    "NativeCallFrameAllocation",
    "NativeExitProbe",
    "NativeRelocation",
    "NativeRegisterAllocation",
    "NativeStackSlotAllocation",
    "NativeSymbol",
    "NativeCodegenError",
    "NativeLoweringError",
    "NativeTarget",
    "StackSlot",
    "VirtualRegister",
    "format_machine_program",
    "format_native_code_program",
    "native_code_program_map",
    "validate_native_code_map_bytes",
    "validate_native_text_section_map_bytes",
    "validate_native_code_program_map",
    "build_native_pe_image",
    "validate_native_pe_image_bytes",
    "lower_ir_program_to_machine",
    "generate_native_code",
    "run_native_bytes_in_memory",
    "run_native_text_section_bytes_in_memory",
]

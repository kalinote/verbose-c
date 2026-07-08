from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

from verbose_c.compiler.opcode import Opcode


JumpOpcodes = {Opcode.JUMP, Opcode.JUMP_IF_FALSE}
TerminatorOpcodes = {Opcode.JUMP, Opcode.RETURN, Opcode.HALT}


@dataclass
class BytecodeOptimizationStats:
    removed_nops: int = 0
    removed_unreachable: int = 0
    removed_redundant_jumps: int = 0
    redirected_jumps: int = 0
    passes: int = 0

    @property
    def removed_total(self) -> int:
        return (
            self.removed_nops
            + self.removed_unreachable
            + self.removed_redundant_jumps
        )


@dataclass
class BytecodeOptimizationResult:
    original_bytecode: list[tuple[Any, ...]]
    optimized_bytecode: list[tuple[Any, ...]]
    original_lineno_table: list[tuple[int, int]]
    optimized_lineno_table: list[tuple[int, int]]
    original_labels: dict[str, int]
    optimized_labels: dict[str, int]
    stats: BytecodeOptimizationStats = field(default_factory=BytecodeOptimizationStats)

    @property
    def changed(self) -> bool:
        return (
            self.original_bytecode != self.optimized_bytecode
            or self.original_lineno_table != self.optimized_lineno_table
            or self.original_labels != self.optimized_labels
        )


def optimize_bytecode(
    bytecode: list[tuple[Any, ...]],
    lineno_table: list[tuple[int, int]] | None = None,
    labels: dict[str, int] | None = None,
) -> BytecodeOptimizationResult:
    original_bytecode = list(bytecode)
    original_lineno_table = list(lineno_table or [])
    original_labels = dict(labels or {})

    current = list(bytecode)
    current_lineno = list(lineno_table or [])
    current_labels = dict(labels or {})
    total_stats = BytecodeOptimizationStats()

    while True:
        optimized, optimized_lineno, optimized_labels, stats = _optimize_once(
            current,
            current_lineno,
            current_labels,
        )
        total_stats.removed_nops += stats.removed_nops
        total_stats.removed_unreachable += stats.removed_unreachable
        total_stats.removed_redundant_jumps += stats.removed_redundant_jumps
        total_stats.redirected_jumps += stats.redirected_jumps
        total_stats.passes += 1

        if (
            optimized == current
            and optimized_lineno == current_lineno
            and optimized_labels == current_labels
        ):
            break

        current = optimized
        current_lineno = optimized_lineno
        current_labels = optimized_labels

    return BytecodeOptimizationResult(
        original_bytecode=original_bytecode,
        optimized_bytecode=current,
        original_lineno_table=original_lineno_table,
        optimized_lineno_table=current_lineno,
        original_labels=original_labels,
        optimized_labels=current_labels,
        stats=total_stats,
    )


def _optimize_once(
    bytecode: list[tuple[Any, ...]],
    lineno_table: list[tuple[int, int]],
    labels: dict[str, int],
) -> tuple[
    list[tuple[Any, ...]],
    list[tuple[int, int]],
    dict[str, int],
    BytecodeOptimizationStats,
]:
    _validate_jump_targets(bytecode)

    stats = BytecodeOptimizationStats()
    bytecode = _redirect_jump_chains(bytecode, stats)
    jump_targets = _collect_jump_targets(bytecode)
    keep = [True] * len(bytecode)

    unreachable = False
    for pc, instruction in enumerate(bytecode):
        opcode = instruction[0]
        is_target = pc in jump_targets

        if unreachable and not is_target:
            keep[pc] = False
            if opcode == Opcode.NOP:
                stats.removed_nops += 1
            else:
                stats.removed_unreachable += 1
            continue

        unreachable = False

        if opcode == Opcode.NOP:
            keep[pc] = False
            stats.removed_nops += 1
            continue

        if (
            opcode == Opcode.JUMP
            and len(instruction) == 2
            and instruction[1] == pc + 1
        ):
            keep[pc] = False
            stats.removed_redundant_jumps += 1
            continue

        if opcode in TerminatorOpcodes:
            unreachable = True

    pc_mapper = _build_pc_mapper(keep)
    optimized = []
    kept_old_pcs = []
    for pc, instruction in enumerate(bytecode):
        if not keep[pc]:
            continue
        kept_old_pcs.append(pc)
        optimized.append(_remap_instruction(instruction, pc_mapper))

    optimized_labels = {
        name: pc_mapper(position)
        for name, position in labels.items()
    }
    optimized_lineno = _remap_lineno_table(
        lineno_table,
        kept_old_pcs,
        pc_mapper,
        len(optimized),
    )

    return optimized, optimized_lineno, optimized_labels, stats


def _validate_jump_targets(bytecode: list[tuple[Any, ...]]) -> None:
    for pc, instruction in enumerate(bytecode):
        opcode = instruction[0]
        if opcode not in JumpOpcodes:
            continue
        if len(instruction) != 2:
            raise RuntimeError(f"{opcode.name} at pc {pc} missing jump target")
        target = instruction[1]
        if not isinstance(target, int):
            raise RuntimeError(f"{opcode.name} at pc {pc} has unresolved target {target!r}")
        if target < 0 or target > len(bytecode):
            raise RuntimeError(f"{opcode.name} at pc {pc} has invalid target {target}")


def _redirect_jump_chains(
    bytecode: list[tuple[Any, ...]],
    stats: BytecodeOptimizationStats,
) -> list[tuple[Any, ...]]:
    redirected = []
    for pc, instruction in enumerate(bytecode):
        opcode = instruction[0]
        if opcode not in JumpOpcodes or len(instruction) != 2:
            redirected.append(instruction)
            continue

        target = _resolve_jump_chain(bytecode, instruction[1])
        if target != instruction[1]:
            stats.redirected_jumps += 1
            redirected.append((opcode, target))
        else:
            redirected.append(instruction)
    return redirected


def _resolve_jump_chain(bytecode: list[tuple[Any, ...]], target: int) -> int:
    seen = set()
    while 0 <= target < len(bytecode):
        if target in seen:
            break
        seen.add(target)
        target_instruction = bytecode[target]
        if target_instruction[0] != Opcode.JUMP or len(target_instruction) != 2:
            break
        target = target_instruction[1]
    return target


def _collect_jump_targets(bytecode: list[tuple[Any, ...]]) -> set[int]:
    targets = set()
    for instruction in bytecode:
        if instruction[0] in JumpOpcodes and len(instruction) == 2:
            targets.add(instruction[1])
    return targets


def _build_pc_mapper(keep: list[bool]):
    old_to_new = {}
    new_pc = 0
    for old_pc, should_keep in enumerate(keep):
        if should_keep:
            old_to_new[old_pc] = new_pc
            new_pc += 1

    kept_positions = sorted(old_to_new)

    def map_pc(old_pc: int) -> int:
        if old_pc >= len(keep):
            return new_pc
        if old_pc in old_to_new:
            return old_to_new[old_pc]
        insertion = bisect_right(kept_positions, old_pc)
        if insertion < len(kept_positions):
            return old_to_new[kept_positions[insertion]]
        return new_pc

    return map_pc


def _remap_instruction(instruction: tuple[Any, ...], pc_mapper) -> tuple[Any, ...]:
    opcode = instruction[0]
    if opcode in JumpOpcodes and len(instruction) == 2:
        return (opcode, pc_mapper(instruction[1]))
    return instruction


def _line_for_pc(lineno_table: list[tuple[int, int]], pc: int) -> int | None:
    if not lineno_table:
        return None
    offsets = [item[0] for item in lineno_table]
    index = bisect_right(offsets, pc)
    if index == 0:
        return None
    return lineno_table[index - 1][1]


def _remap_lineno_table(
    lineno_table: list[tuple[int, int]],
    kept_old_pcs: list[int],
    pc_mapper,
    optimized_length: int,
) -> list[tuple[int, int]]:
    if not lineno_table:
        return []

    remapped: list[tuple[int, int]] = []
    last_line = None
    for old_pc in kept_old_pcs:
        line = _line_for_pc(lineno_table, old_pc)
        if line is None or line == last_line:
            continue
        new_pc = pc_mapper(old_pc)
        if new_pc >= optimized_length:
            continue
        remapped.append((new_pc, line))
        last_line = line
    return remapped

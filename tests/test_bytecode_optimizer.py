from verbose_c.compiler.bytecode_optimizer import optimize_bytecode
from verbose_c.compiler.opcode import Opcode


def test_bytecode_optimizer_removes_nop_and_remaps_lineno():
    bytecode = [
        (Opcode.NOP,),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.RETURN,),
    ]
    result = optimize_bytecode(bytecode, lineno_table=[(0, 10), (1, 11), (2, 12)])

    assert result.optimized_bytecode == [
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.RETURN,),
    ]
    assert result.stats.removed_nops == 1
    assert result.optimized_lineno_table == [(0, 11), (1, 12)]


def test_bytecode_optimizer_removes_unreachable_instruction():
    bytecode = [
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.RETURN,),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.RETURN,),
    ]
    result = optimize_bytecode(bytecode)

    assert result.optimized_bytecode == [
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.RETURN,),
    ]
    assert result.stats.removed_unreachable == 2


def test_bytecode_optimizer_removes_redundant_jump_to_next_instruction():
    bytecode = [
        (Opcode.JUMP, 1),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.RETURN,),
    ]
    result = optimize_bytecode(bytecode)

    assert result.optimized_bytecode == [
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.RETURN,),
    ]
    assert result.stats.removed_redundant_jumps == 1


def test_bytecode_optimizer_redirects_jump_chain():
    bytecode = [
        (Opcode.JUMP, 2),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.JUMP, 4),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.RETURN,),
    ]
    result = optimize_bytecode(bytecode)

    assert result.stats.redirected_jumps >= 1
    assert result.optimized_bytecode == [(Opcode.RETURN,)]


def test_bytecode_optimizer_preserves_jump_target_reachability():
    bytecode = [
        (Opcode.JUMP, 2),
        (Opcode.LOAD_CONSTANT, 0),
        (Opcode.LOAD_CONSTANT, 1),
        (Opcode.RETURN,),
    ]
    result = optimize_bytecode(bytecode)

    assert (Opcode.LOAD_CONSTANT, 1) in result.optimized_bytecode
    assert result.optimized_bytecode[0][1] == 1

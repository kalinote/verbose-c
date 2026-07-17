from enum import Enum


class ConditionCode(str, Enum):
    """x64 条件码。"""

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


_SETCC_OPCODE = {
    ConditionCode.EQ: 0x94,
    ConditionCode.NE: 0x95,
    ConditionCode.LT: 0x9C,
    ConditionCode.LE: 0x9E,
    ConditionCode.GT: 0x9F,
    ConditionCode.GE: 0x9D,
}


def encode_prologue(frame_size: int) -> bytes:
    """编码函数序言。"""
    code = bytearray([0x55, 0x48, 0x89, 0xE5])
    if frame_size:
        code.extend([0x48, 0x81, 0xEC])
        code.extend(_int32(frame_size))
    return bytes(code)


def encode_epilogue() -> bytes:
    """编码函数尾声。"""
    return bytes([0x48, 0x89, 0xEC, 0x5D, 0xC3])


def encode_mov_rax_imm64(value: int) -> bytes:
    """编码 mov rax, imm64。"""
    return bytes([0x48, 0xB8]) + _int64(value)


def encode_mov_r10_imm64(value: int) -> bytes:
    """编码 mov r10, imm64。"""
    return bytes([0x49, 0xBA]) + _int64(value)


def encode_mov_rdx_imm64(value: int) -> bytes:
    """编码 mov rdx, imm64。"""
    return bytes([0x48, 0xBA]) + _int64(value)


def encode_mov_r11_rbp() -> bytes:
    """编码 mov r11, rbp。"""
    return bytes([0x49, 0x89, 0xEB])


def encode_mov_rax_from_rbp_offset(offset: int) -> bytes:
    """编码 mov rax, [rbp-offset]。"""
    return bytes([0x48, 0x8B, 0x85]) + _negative_disp32(offset)


def encode_mov_rax_from_r11_offset(offset: int) -> bytes:
    """编码 mov rax, [r11-offset]。"""
    return bytes([0x49, 0x8B, 0x83]) + _negative_disp32(offset)


def encode_mov_rax_from_rbp_positive_offset(offset: int) -> bytes:
    """编码 mov rax, [rbp+offset]。"""
    return bytes([0x48, 0x8B, 0x85]) + _int32(offset)


def encode_mov_r10_from_rbp_offset(offset: int) -> bytes:
    """编码 mov r10, [rbp-offset]。"""
    return bytes([0x4C, 0x8B, 0x95]) + _negative_disp32(offset)


def encode_mov_r10_from_r11_offset(offset: int) -> bytes:
    """编码 mov r10, [r11-offset]。"""
    return bytes([0x4D, 0x8B, 0x93]) + _negative_disp32(offset)


def encode_mov_rbp_offset_from_rax(offset: int) -> bytes:
    """编码 mov [rbp-offset], rax。"""
    return bytes([0x48, 0x89, 0x85]) + _negative_disp32(offset)


def encode_mov_r11_offset_from_rax(offset: int) -> bytes:
    """编码 mov [r11-offset], rax。"""
    return bytes([0x49, 0x89, 0x83]) + _negative_disp32(offset)


def encode_mov_rsp_offset_from_rax(offset: int) -> bytes:
    """编码 mov [rsp+offset], rax。"""
    return bytes([0x48, 0x89, 0x84, 0x24]) + _int32(offset)


def encode_mov_rbp_offset_from_reg(offset: int, register: str) -> bytes:
    """编码 mov [rbp-offset], register。"""
    opcodes = {
        "RCX": bytes([0x48, 0x89, 0x8D]),
        "RDX": bytes([0x48, 0x89, 0x95]),
        "R8": bytes([0x4C, 0x89, 0x85]),
        "R9": bytes([0x4C, 0x89, 0x8D]),
    }
    return opcodes[register.upper()] + _negative_disp32(offset)


def encode_mov_reg_from_rax(register: str) -> bytes:
    """编码 mov register, rax。"""
    opcodes = {
        "RCX": bytes([0x48, 0x89, 0xC1]),
        "RDX": bytes([0x48, 0x89, 0xC2]),
        "R8": bytes([0x49, 0x89, 0xC0]),
        "R9": bytes([0x49, 0x89, 0xC1]),
    }
    return opcodes[register.upper()]


def encode_add_rax_r10() -> bytes:
    """编码 add rax, r10。"""
    return bytes([0x4C, 0x01, 0xD0])


def encode_add_rdx_r10() -> bytes:
    """编码 add rdx, r10。"""
    return bytes([0x4C, 0x01, 0xD2])


def encode_sub_rax_r10() -> bytes:
    """编码 sub rax, r10。"""
    return bytes([0x4C, 0x29, 0xD0])


def encode_imul_rax_r10() -> bytes:
    """编码 imul rax, r10。"""
    return bytes([0x49, 0x0F, 0xAF, 0xC2])


def encode_neg_rax() -> bytes:
    """编码 neg rax。"""
    return bytes([0x48, 0xF7, 0xD8])


def encode_cqo() -> bytes:
    """编码 cqo。"""
    return bytes([0x48, 0x99])


def encode_idiv_r10() -> bytes:
    """编码 idiv r10。"""
    return bytes([0x49, 0xF7, 0xFA])


def encode_mov_rax_rdx() -> bytes:
    """编码 mov rax, rdx。"""
    return bytes([0x48, 0x89, 0xD0])


def encode_xor_rax_r10() -> bytes:
    """编码 xor rax, r10。"""
    return bytes([0x4C, 0x31, 0xD0])


def encode_cmp_rax_r10() -> bytes:
    """编码 cmp rax, r10。"""
    return bytes([0x4C, 0x39, 0xD0])


def encode_test_rdx_rdx() -> bytes:
    """编码 test rdx, rdx。"""
    return bytes([0x48, 0x85, 0xD2])


def encode_setcc_al(condition: ConditionCode) -> bytes:
    """编码 setcc al。"""
    return bytes([0x0F, _SETCC_OPCODE[condition], 0xC0])


def encode_movzx_rax_al() -> bytes:
    """编码 movzx rax, al。"""
    return bytes([0x48, 0x0F, 0xB6, 0xC0])


def encode_jmp_rel32(displacement: int) -> bytes:
    """编码 jmp rel32。"""
    return bytes([0xE9]) + _int32(displacement)


def encode_jne_rel32(displacement: int) -> bytes:
    """编码 jne rel32。"""
    return bytes([0x0F, 0x85]) + _int32(displacement)


def encode_je_rel32(displacement: int) -> bytes:
    """编码 je rel32。"""
    return bytes([0x0F, 0x84]) + _int32(displacement)


def encode_jns_rel32(displacement: int) -> bytes:
    """编码 jns rel32。"""
    return bytes([0x0F, 0x89]) + _int32(displacement)


def encode_call_rel32(displacement: int) -> bytes:
    """编码 call rel32。"""
    return bytes([0xE8]) + _int32(displacement)


def encode_sub_rsp_imm32(value: int) -> bytes:
    """编码 sub rsp, imm32。"""
    return bytes([0x48, 0x81, 0xEC]) + _int32(value)


def encode_add_rsp_imm32(value: int) -> bytes:
    """编码 add rsp, imm32。"""
    return bytes([0x48, 0x81, 0xC4]) + _int32(value)


def _int32(value: int) -> bytes:
    """按小端有符号 int32 编码。"""
    return int(value).to_bytes(4, "little", signed=True)


def _int64(value: int) -> bytes:
    """按小端有符号 int64 编码。"""
    return int(value).to_bytes(8, "little", signed=True)


def _negative_disp32(offset: int) -> bytes:
    """按 rbp 负偏移编码 disp32。"""
    return (-int(offset)).to_bytes(4, "little", signed=True)

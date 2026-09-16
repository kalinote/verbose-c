"""x64 相对调用、跳转编码和 PE 基址重定位的共享约定。"""

import struct
from verbose_c.compiler.native.encoder import (
    encode_call_rel32,
    encode_jne_rel32,
    encode_test_rdx_rdx,
)
from verbose_c.compiler.native.errors import NativeCodegenError


CALL_REL32_SIZE = len(encode_call_rel32(0))


TEST_RDX_RDX_SIZE = len(encode_test_rdx_rdx())


JNE_REL32_SIZE = len(encode_jne_rel32(0))


REL32_JUMP_OPCODES = {
    "je_rel32": b"\x0F\x84",
    "jmp_rel32": b"\xE9",
    "jne_rel32": b"\x0F\x85",
    "jns_rel32": b"\x0F\x89",
}


REL32_JUMP_ASM_PREFIXES = {
    "je_rel32": "je ",
    "jmp_rel32": "jmp ",
    "jne_rel32": "jne ",
    "jns_rel32": "jns ",
}


def build_base_relocations(patch_rvas: list[int]) -> bytes:
    """按 4 KiB 页生成 PE32+ DIR64 重定位块。

    Args:
        patch_rvas: 映像中需要由 loader 修补的 64 位绝对地址字段的 RVA。

    Returns:
        含 DIR64 项和 ABSOLUTE 对齐填充项的 .reloc 节内容。

    Raises:
        NativeCodegenError: 地址越界、重复或修补字段互相重叠。
    """
    if not isinstance(patch_rvas, list) or any(type(rva) is not int or not 0 <= rva <= 0xFFFFFFF8 for rva in patch_rvas):
        raise NativeCodegenError("PE 基址重定位地址必须是有效的 32 位 RVA")
    ordered = sorted(patch_rvas)
    if any(right < left + 8 for left, right in zip(ordered, ordered[1:])):
        raise NativeCodegenError("PE 基址重定位修补字段重复或重叠")
    pages: dict[int, list[int]] = {}
    for rva in ordered:
        pages.setdefault(rva & ~0xFFF, []).append(0xA000 | (rva & 0xFFF))
    payload = bytearray()
    for page, entries in pages.items():
        if len(entries) % 2:
            entries.append(0)
        payload.extend(struct.pack("<II", page, 8 + len(entries) * 2))
        payload.extend(struct.pack(f"<{len(entries)}H", *entries))
    return bytes(payload)

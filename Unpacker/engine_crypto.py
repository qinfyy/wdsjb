from __future__ import annotations

from dataclasses import dataclass
from functools import cache, reduce
from typing import Final, Iterator

from engine_tables import ROUND_KEY_SOURCE, ROUND_KEY_XOR, SBOX_INVERSE, SHIFT_INVERSE

UINT64_MASK: Final[int] = (1 << 64) - 1
ROUND_KEY_SEED: Final[int] = 0x86DDC8  # CN 6.1.0 libunity.so 0x00BE1884
ENCODING_SEED: Final[int] = 0x46BE28  # CN 6.1.0 libunity.so 0x00BE0D5C
BOOTSTRAP_SEED: Final[int] = 0x4D867C  # CN 6.1.0 libunity.so 0x00BE20E0
# CN 6.1.0 libunity.so 0x0187B2F8
SEED_MARKER: Final[bytes] = bytes.fromhex("6d69486f596f20436f2e2c4c74642e")


def mt19937_64(seed: int) -> Iterator[int]:
    """CN 6.1.0 libunity.so 0x00C2F358 展开状态，0x00C2F244 生成输出；不是 Python random 的 MT32。"""
    state = [seed & UINT64_MASK]
    for index in range(1, 312):
        previous = state[-1]
        state.append((6364136223846793005 * (previous ^ (previous >> 62)) + index) & UINT64_MASK)
    cursor = 312
    while True:
        if cursor == 312:
            for index in range(312):
                value = (state[index] & 0xFFFFFFFF80000000) | (state[(index + 1) % 312] & 0x7FFFFFFF)
                state[index] = state[(index + 156) % 312] ^ (value >> 1)
                if value & 1:
                    state[index] ^= 0xB5026F5AA96619E9
            cursor = 0
        value = state[cursor]
        cursor += 1
        value ^= (value >> 29) & 0x555555555
        value ^= (value << 17) & 0x71D67FFFEDA60000
        value ^= (value << 37) & 0xFFF7EEE000000000
        yield value ^ (value >> 43)


def decode_xor_bytes(encoded: bytes) -> bytes:
    """CN 6.1.0 libunity.so 0x00FE4E28：每个逻辑字节由 16 个存储字节的 XOR 还原。"""
    if len(encoded) % 16:
        raise ValueError("字节编码长度必须是 16 的倍数")
    return bytes(reduce(int.__xor__, encoded[index:index + 16], 0) for index in range(0, len(encoded), 16))


def generate_seed_material(seed: int) -> bytes:
    """CN 6.1.0 libunity.so 0xBE37D8：填充 32 字节、随机位置插入固定字符串，再按 qword 异或。"""
    if not 0 < seed < 0x80000000:
        raise ValueError("这里只支持客户端的固定正 int32 种子，不使用 random_device")
    generator = mt19937_64(seed)
    result = bytearray(b"".join(next(generator).to_bytes(8, "little") for _ in range(4)))
    # BE3A48：位置取模 32 - string.size()，不是模 32，也不是追加字符串。
    position = next(generator) % (32 - len(SEED_MARKER))
    result[position:position + len(SEED_MARKER)] = SEED_MARKER
    # BE4DF0：保持同一个 MT 状态，从插入位置输出之后继续取四个 qword。
    for offset in range(0, 32, 8):
        value = int.from_bytes(result[offset:offset + 8], "little") ^ next(generator)
        result[offset:offset + 8] = value.to_bytes(8, "little")
    return bytes(result)


def decode_sbox(encoded: bytes) -> bytes:
    """CN 6.1.0 libunity.so 0x00FE4A58：查表后与输入值及 0xFF 异或；已核对正向和逆向 S-box。"""
    if len(encoded) != 256:
        raise ValueError("S-box 必须包含 256 项")
    return bytes(value ^ index ^ 0xFF for index, value in enumerate(encoded))


def decode_round_material(offset: int) -> bytes:
    """CN 6.1.0 libunity.so 0xBE18F0 / 0xBE15E8：source + offset 与固定 XOR 表按 qword 混合。"""
    if not 0 <= offset <= 0x1FF:
        raise ValueError("轮材料偏移必须在 0..511 内")
    source = ROUND_KEY_SOURCE[offset:offset + 0xB00]
    mask = ROUND_KEY_XOR[:0xB00]
    # 同一个 qword 盐写入记录的两半，在 16 字节 XOR 还原中抵消。
    return decode_xor_bytes(bytes(value ^ key for value, key in zip(source, mask)))


@dataclass(frozen=True, slots=True)
class Mr0kMaterial:
    offset: int
    rounds: bytes
    header_mask: bytes
    stream: bytes


@cache
def generate_mr0k_material() -> Mr0kMaterial:
    """CN 6.1.0 BE08F4；X24 保留 ROUND_KEY_SEED 的结果，不是 bootstrap。"""
    seed_material = generate_seed_material(ROUND_KEY_SEED)
    generator = mt19937_64(int.from_bytes(seed_material[:8], "little"))
    offset = next(generator) & 0x1FF
    # BE18A0: X24 = X27；BE1EF8 未改 X24；BE13CC 从 X24 + 16 + i 读字节。
    header_mask = bytes(ROUND_KEY_SOURCE[0xB00 + 2 * offset + index]
                        ^ ROUND_KEY_XOR[2 * offset + index]
                        ^ seed_material[16 + index] for index in range(16))
    # BE1EFC / BE1DE0 恢复同一个 MT 状态，继续生成 128 个 qword。
    stream = b"".join(next(generator).to_bytes(8, "little") for _ in range(128))
    return Mr0kMaterial(offset, decode_round_material(offset), header_mask, stream)


def inverse_mix_columns(state: bytes) -> bytes:
    """CN 6.1.0 libunity.so FE4784 的逆向 T-table 合并；各表相同的固定 XOR 相互抵消。"""
    if len(state) != 16:
        raise ValueError("AES 状态必须是 16 字节")

    def xtime(value: int) -> int:
        return ((value << 1) ^ (0x11B if value & 0x80 else 0)) & 0xFF

    result = bytearray(state)
    for offset in range(0, 16, 4):
        a, b, c, d = result[offset:offset + 4]
        u, v = xtime(xtime(a ^ c)), xtime(xtime(b ^ d))
        a, b, c, d = a ^ u, b ^ v, c ^ u, d ^ v
        total = a ^ b ^ c ^ d
        result[offset:offset + 4] = bytes((
            a ^ total ^ xtime(a ^ b), b ^ total ^ xtime(b ^ c),
            c ^ total ^ xtime(c ^ d), d ^ total ^ xtime(d ^ a),
        ))
    return bytes(result)


def decrypt_round_material(block: bytes, rounds: bytes) -> bytes:
    """CN 6.1.0 libunity.so FE4668 的十轮逆向操作；允许独立轮材料，不假定它来自标准密钥展开。"""
    if len(block) != 16 or len(rounds) != 176:
        raise ValueError("AES 输入必须为 16 字节，轮材料必须为 176 字节")
    sbox = decode_sbox(SBOX_INVERSE)
    shift = tuple(int.from_bytes(SHIFT_INVERSE[index:index + 8], "little") for index in range(0, 128, 8))
    if sorted(shift) != list(range(16)):
        raise ValueError("AES ShiftRows 表不是 0..15 的排列")
    state = bytes(value ^ key for value, key in zip(block, rounds[:16]))
    for index in range(1, 11):
        state = bytes(sbox[state[source]] for source in shift)
        if index < 10:
            state = inverse_mix_columns(state)
        state = bytes(value ^ key for value, key in zip(state, rounds[index * 16:(index + 1) * 16]))
    return state

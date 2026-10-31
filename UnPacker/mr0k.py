"""CN 6.1.0 UnityFS 类型 5 大块的 mr0k 静态预处理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from engine_crypto import UINT64_MASK, decrypt_round_material, generate_mr0k_material


# CN 6.1.0 libunity.so 0x007D3C28；初始化常量位于 0x0021F5D4 / 0x0156A110。
PREFIX_XOR_MASK: Final[bytes] = bytes.fromhex("257d020041c8030073a70500bf440700dd900800df690a00")
PREFIX_XOR_SIZE: Final[int] = 0xC00
# CN 6.1.0 libunity.so 0x00BE9064，返回 input + 0x14。
REMOVED_HEADER_SIZE: Final[int] = 0x14
DATA_OFFSET: Final[int] = 0x94


@dataclass(frozen=True, slots=True)
class Mr0kHeader:
    first: bytes
    second: bytes
    third: bytes

    @classmethod
    def parse(cls, data: bytes) -> Mr0kHeader:
        if len(data) < DATA_OFFSET or data[:4] != b"mr0k":
            raise ValueError("mr0k 头部缺失或长度不足")
        # CN 6.1.0 libunity.so 0x00BE9064 取三个 16 字节字段；0x00BE7FCC / 0x00BF3EBC 不改写 first。
        return cls(data[0x04:0x14], data[0x74:0x84], data[0x84:0x94])

    def xor_second(self, mask: bytes) -> Mr0kHeader:
        """CN 6.1.0 libunity.so 0x00BE9064：第二字段与初始化上下文 +0xE38 的 16 字节常量 XOR。"""
        if len(mask) != 16:
            raise ValueError("mr0k 头部掩码必须是 16 字节")
        return Mr0kHeader(self.first, bytes(value ^ key for value, key in zip(self.second, mask)), self.third)


def xor_compressed_prefix(data: bytes) -> bytes:
    """在 mr0k 预处理之后、LZ4 之前，对前 3072 字节循环异或。"""
    if len(data) < PREFIX_XOR_SIZE:
        raise ValueError("类型 5 大块长度不足 3072 字节")
    result = bytearray(data)
    for index in range(PREFIX_XOR_SIZE):
        result[index] ^= PREFIX_XOR_MASK[index % len(PREFIX_XOR_MASK)]
    return bytes(result)


def preprocess_mr0k(data: bytes, rounds: bytes, header_mask: bytes, stream: bytes) -> bytes:
    """CN 6.1.0 libunity.so 0xBE9064 的头部和 qword 变换；材料由初始化路径提供，不猜测密钥。"""
    header = Mr0kHeader.parse(data).xor_second(header_mask)
    if len(stream) != 0x400:
        raise ValueError("mr0k 固定流表必须是 1024 字节")
    first = decrypt_round_material(header.first, rounds)
    third = decrypt_round_material(header.third, rounds)
    mixed_first = bytes(a ^ b for a, b in zip(first, header.second))
    mixed_third = bytes(a ^ b for a, b in zip(third, first))
    result = bytearray(data)
    # CN 6.1.0 libunity.so 0xBE92A4 / 0xBE9E00 分别变换 first / third；CN 6.1.0 libunity.so 0xBEBE98 只写回第三字段。
    result[0x84:DATA_OFFSET] = mixed_third
    seed = (int.from_bytes(header.second[:8], "little") + len(data) - REMOVED_HEADER_SIZE) & UINT64_MASK
    salt = int.from_bytes(mixed_first[:8], "little") ^ int.from_bytes(mixed_third[:8], "little") ^ seed
    count = min((len(data) - DATA_OFFSET) // 0x80 * 0x10, 0x400)
    # CN 6.1.0 libunity.so 0xBEC9A8 / 0xBEC604 / 0xBE9FC4：按完整 qword 处理，不覆盖剩余数据。
    for offset in range(0, count, 8):
        start = DATA_OFFSET + offset
        value = int.from_bytes(result[start:start + 8], "little")
        value ^= salt ^ int.from_bytes(stream[offset:offset + 8], "little")
        result[start:start + 8] = value.to_bytes(8, "little")
    return bytes(result[REMOVED_HEADER_SIZE:])


def decrypt_mr0k(data: bytes) -> bytes:
    """移除 20 字节头、恢复压缩流；调用者仍须做 LZ4 与输出长度验证。"""
    Mr0kHeader.parse(data)
    material = generate_mr0k_material()
    return xor_compressed_prefix(preprocess_mr0k(data, material.rounds, material.header_mask, material.stream))

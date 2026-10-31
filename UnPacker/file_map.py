from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MappedFile:
    name: str
    block: str
    offset: int
    size: int
    md5: str
    tag: int
    build: int


@dataclass(frozen=True, slots=True)
class FileMap:
    version: tuple[int, int, int]
    blocks: dict[str, int]
    files: list[MappedFile]


class ByteBuf:
    """CN 6.1.0 libil2cpp.so BytesTools.ByteBuf：大端整数，UTF8 前缀为有符号 short。"""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, fmt: str) -> tuple[int, ...]:
        size = struct.calcsize(fmt)
        if self.offset + size > len(self.data):
            raise ValueError(f"xmf 结构提前结束，偏移 {self.offset:#x}")
        values = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        return values

    def string(self) -> str:
        size, = self.read(">h")
        if size < 0 or self.offset + size > len(self.data):
            raise ValueError("xmf 字符串长度无效")
        value = self.data[self.offset:self.offset + size].decode("utf-8")
        self.offset += size
        return value

    def count(self, minimum_size: int) -> int:
        value, = self.read(">i")
        if value < 0 or value > (len(self.data) - self.offset) // minimum_size:
            raise ValueError(f"xmf 条目数量无效：{value}")
        return value


def parse_file_map(data: bytes) -> FileMap:
    """CN 6.1.0 libil2cpp.so FileMapGroupInfo.ReadFromByteBuf 0x02C40C1C，拒绝校验失败的索引。"""
    if len(data) < 36 or hashlib.md5(data[16:]).digest() != data[:16]:
        raise ValueError("xmf MD5 校验失败")
    buf = ByteBuf(data)
    buf.offset = 16
    version = buf.read(">iii")
    if version[0] != 2:
        raise ValueError(f"不支持的 xmf 格式版本：{version[0]}")
    blocks: dict[str, int] = {}
    for _ in range(buf.count(26)):
        buf.string()
        first, second, size, tag = buf.read(">QQii")
        name = f"{first:016x}{second:016x}.blk"
        if size < 0 or name in blocks and blocks[name] != size:
            raise ValueError(f"xmf 块信息无效：{name}")
        blocks[name] = size
    files: list[MappedFile] = []
    names: set[str] = set()
    for _ in range(buf.count(66)):
        name = buf.string()
        name1, name2, md51, md52, tag, offset, size, block1, block2, build = buf.read(">QQQQiiiQQi")
        block = f"{block1:016x}{block2:016x}.blk"
        if name in names or block not in blocks or offset < 0 or size < 0 or offset + size > blocks[block]:
            raise ValueError(f"xmf 文件信息无效：{name}")
        names.add(name)
        files.append(MappedFile(name, block, offset, size, f"{md51:016x}{md52:016x}", tag, build))
    if buf.offset != len(data):
        raise ValueError(f"xmf 存在未解析尾部：{len(data) - buf.offset} 字节")
    return FileMap(version, blocks, files)

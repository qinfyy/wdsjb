from __future__ import annotations

import struct
from dataclasses import dataclass

import lz4.block
from UnityPy.files.BundleFile import BundleFile
from UnityPy.streams import EndianBinaryReader


@dataclass(frozen=True, slots=True)
class BundleNode:
    name: str
    offset: int
    size: int
    flags: int


@dataclass(frozen=True, slots=True)
class DecodedBundle:
    data: bytes
    nodes: list[BundleNode]
    compression: list[dict[str, int]]


class WDBundleFile(BundleFile):
    def __init__(self, data: bytes) -> None:
        self.compression: list[dict[str, int]] = []
        self.nodes: list[BundleNode] = []
        self.payload = b""
        super().__init__(EndianBinaryReader(data), parent=None)

    def decompress_data(self, compressed_data: bytes, uncompressed_size: int,
                        flags: int, index: int = 0) -> bytes:
        kind = int(flags) & 0x3F
        self.compression.append({"type": kind, "compressed": len(compressed_data), "uncompressed": uncompressed_size})
        if kind == 5:
            if len(compressed_data) >= 0x10000:
                from mr0k import decrypt_mr0k
                compressed_data = decrypt_mr0k(compressed_data)
            result = lz4.block.decompress(compressed_data, uncompressed_size=uncompressed_size)
        else:
            result = super().decompress_data(compressed_data, uncompressed_size, flags, index)
        if len(result) != uncompressed_size:
            raise ValueError(f"UnityFS 解压长度错误：期望 {uncompressed_size}，实际 {len(result)}")
        return result

    def read_files(self, reader: EndianBinaryReader, files: list) -> None:
        reader.Position = 0
        self.payload = reader.read_bytes(reader.Length)
        for node in files:
            if node.offset < 0 or node.size < 0 or node.offset + node.size > len(self.payload):
                raise ValueError(f"UnityFS 节点越界：{node.path}")
            self.nodes.append(BundleNode(node.path, node.offset, node.size, node.flags))


def unpack_unityfs(data: bytes) -> DecodedBundle:
    """重建无压缩 UnityFS，节点内容逐字节保留，不重新序列化 Unity 对象。"""
    if not data.startswith(b"UnityFS\x00"):
        raise ValueError("索引条目不是 UnityFS")
    header = EndianBinaryReader(data)
    header.read_string_to_null()
    header.read_u_int()
    header.read_string_to_null()
    header.read_string_to_null()
    if header.read_long() != len(data):
        raise ValueError("UnityFS 文件长度与索引不一致")
    bundle = WDBundleFile(data)
    size = len(bundle.payload)
    if size > 0xFFFFFFFF:
        raise ValueError("UnityFS 内容超过单块大小上限")
    info = bytearray(16)
    info += struct.pack(">iIIHi", 1, size, size, 0, len(bundle.nodes))
    for node in bundle.nodes:
        info += struct.pack(">qqI", node.offset, node.size, node.flags)
        info += node.name.encode("utf-8") + b"\x00"
    prefix = b"UnityFS\x00" + struct.pack(">I", bundle.version)
    prefix += bundle.version_player.encode("utf-8") + b"\x00"
    prefix += bundle.version_engine.encode("utf-8") + b"\x00"
    header_size = len(prefix) + 20
    padding = bytes((-header_size) % 16) if getattr(bundle, "_uses_block_alignment", False) else b""
    full_size = header_size + len(padding) + len(info) + size
    prefix += struct.pack(">QIII", full_size, len(info), len(info), 0x40)
    result = prefix + padding + info + bundle.payload
    return DecodedBundle(result, bundle.nodes, bundle.compression)

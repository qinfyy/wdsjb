"""从直接包含 BLK 的目录读取索引指定的完整资源块。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from file_map import FileMap, MappedFile


class BlockStore:
    def __init__(self, index: FileMap, root: Path) -> None:
        self.index = index
        self.root = root
        self.cache: tuple[str, bytes, str] | None = None
        self.checked: set[str] = set()

    def read_block(self, name: str) -> tuple[bytes, str]:
        if self.cache is not None and self.cache[0] == name:
            return self.cache[1:]
        path = self.root / name
        if not path.is_file():
            raise FileNotFoundError(f"缺少资源块：{name}")
        data = path.read_bytes()
        origin = str(path.resolve())
        if len(data) != self.index.blocks[name]:
            raise ValueError(f"资源块长度错误：{name}")
        if hashlib.md5(data).hexdigest() != Path(name).stem:
            raise ValueError(f"资源块 MD5 错误：{name}")
        self.checked.add(name)
        self.cache = (name, data, origin)
        return data, origin

    def read_file(self, entry: MappedFile) -> tuple[bytes, str]:
        block, origin = self.read_block(entry.block)
        data = block[entry.offset:entry.offset + entry.size]
        if len(data) != entry.size or hashlib.md5(data).hexdigest() != entry.md5:
            raise ValueError(f"索引文件 MD5 错误：{entry.name}")
        return data, origin

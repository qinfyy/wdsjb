"""protobuf schema 加载、客户端路由和无 schema 的原始 wire 检查。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.descriptor import Descriptor
from google.protobuf.message import DecodeError

from routes import SPLIT_MESSAGES


ROOT = Path(__file__).resolve().parent
PROTOC = ROOT.parent / "WDSniffer" / "protoc" / "protoc.exe"


def compile_schema(source: Path) -> Path:
    source = source.resolve()
    if source.is_file() and source.suffix.lower() == ".pb":
        return source
    if source.is_dir():
        files = sorted(path for path in source.rglob("*.proto") if path.is_file())
        root = source
    elif source.is_file() and source.suffix.lower() == ".proto":
        files, root = [source], source.parent
    else:
        raise ValueError(f"schema 必须是 proto 目录、.proto 或 FileDescriptorSet (.pb)：{source}")
    if not files:
        raise ValueError(f"schema 目录没有 .proto 文件：{source}")
    if not PROTOC.is_file():
        raise FileNotFoundError(f"protoc 未找到：{PROTOC}")
    identity = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    target = ROOT / "temp" / f"{source.stem}-{identity}.pb"
    target.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(PROTOC), f"--descriptor_set_out={target}", "--include_imports",
         f"--proto_path={root}", f"--proto_path={PROTOC.parent}",
         *(path.relative_to(root).as_posix() for path in files)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(f"protoc 编译失败：{source} ({completed.returncode})：{detail}")
    return target


class ConfigSchema:
    def __init__(self, paths: Path | list[Path]) -> None:
        sources = [paths] if isinstance(paths, Path) else paths
        if not sources:
            raise ValueError("至少需要一个 schema 目录或文件")
        temp = ROOT / "temp"
        if temp.resolve() != temp:
            raise ValueError("temp 目录不能是目录链接")
        if any(source.resolve().is_relative_to(temp) for source in sources):
            raise ValueError("schema 输入不能位于待清空的 temp 目录")
        if temp.exists():
            shutil.rmtree(temp)
        temp.mkdir()
        self.descriptor_paths = [compile_schema(source) for source in sources]
        self.pools: list[descriptor_pool.DescriptorPool] = []
        self.messages: dict[str, Descriptor] = {}
        digest = hashlib.sha256()
        self.descriptor_hashes: list[str] = []
        for path in self.descriptor_paths:
            data = path.read_bytes()
            digest.update(data)
            self.descriptor_hashes.append(hashlib.sha256(data).hexdigest())
            try:
                descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(data)
            except DecodeError as error:
                raise ValueError(f"schema 不是有效的 FileDescriptorSet：{path.name}") from error
            self._load_descriptor_set(descriptor_set)
        self.sha256 = digest.hexdigest()

    def _load_descriptor_set(self, descriptor_set: descriptor_pb2.FileDescriptorSet) -> None:
        if not descriptor_set.file:
            raise ValueError("schema 没有文件定义")
        # 每份描述符独立加载；忽略包名，后面的同名消息覆盖前面的。
        pool = descriptor_pool.DescriptorPool()
        self.pools.append(pool)
        pending = list(descriptor_set.file)
        loaded: set[str] = set()

        def visit(message: Descriptor) -> None:
            self.messages[message.name.casefold()] = message
            for nested in message.nested_types:
                visit(nested)

        while pending:
            ready = [file for file in pending if set(file.dependency) <= loaded]
            if not ready:
                raise ValueError("schema 存在缺失或循环依赖；请编译时使用 --include_imports")
            for file in ready:
                try:
                    pool.Add(file)
                except TypeError as error:
                    raise ValueError(f"无效的 schema：{file.name}：{error}") from error
                loaded.add(file.name)
                pending.remove(file)
                for message in file.message_type:
                    full_name = ".".join(part for part in (file.package, message.name) if part)
                    visit(pool.FindMessageTypeByName(full_name))

    def find_message(self, name: str) -> Descriptor | None:
        return self.messages.get(name.rsplit(".", 1)[-1].casefold())

    def route(self, stem: str, explicit: str | None = None) -> Descriptor | None:
        if explicit:
            message = self.find_message(explicit)
            if message is None:
                raise ValueError(f"schema 不包含消息：{explicit}")
            return message
        match = re.fullmatch(r"(story|explore|text|live2d)_([0-9]+)", stem)
        if match:
            return self.find_message(SPLIT_MESSAGES[match[1]])
        return self.find_message("All" + stem + "Datas")

    def decode(self, payload: bytes, descriptor: Descriptor) -> tuple[dict[str, Any], bool]:
        try:
            message = message_factory.GetMessageClass(descriptor).FromString(payload)
        except DecodeError as error:
            raise ValueError(f"{descriptor.full_name} 解析失败，可能截断或路由不匹配") from error
        before = message.SerializeToString(deterministic=True)
        message.DiscardUnknownFields()
        unknown = before != message.SerializeToString(deterministic=True)
        document = json_format.MessageToDict(message, preserving_proto_field_name=True,
                                             use_integers_for_enums=True)
        return document, unknown

    @staticmethod
    def verify_group(stem: str, document: dict[str, Any]) -> None:
        match = re.fullmatch(r"(story|explore|text|live2d)_([0-9]+)", stem)
        if not match:
            return
        name = {"story": "storyID", "explore": "mapID", "text": "iD", "live2d": "iD"}[match[1]]
        # proto3 的零值通常不出现在 JSON 中；不能把 text_0 当作缺少 ID。
        actual = document.get(name, 0)
        if actual != int(match[2]):
            raise ValueError(f"文件名分组 ID 与消息字段 {name} 不一致：{match[2]} != {actual}")


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("varint 截断")
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("varint 超出 uint64")
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise ValueError("varint 超长")


def inspect_wire(data: bytes) -> list[dict[str, Any]]:
    """保留字段编号、编码和原始字节，不臆造字段名、子消息或数值类型。"""
    fields: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        start = offset
        key, offset = read_varint(data, offset)
        tag, wire = key >> 3, key & 7
        if not 0 < tag < 1 << 29 or wire not in (0, 1, 2, 5):
            raise ValueError("不支持的 protobuf tag/wire")
        field: dict[str, Any] = {"offset": start, "tag": tag, "wire": wire}
        if wire == 0:
            value, offset = read_varint(data, offset)
            field["varint"] = str(value)
        else:
            size = 8 if wire == 1 else 4
            if wire == 2:
                size, offset = read_varint(data, offset)
            end = offset + size
            if end > len(data):
                raise ValueError("protobuf 字段截断")
            field["payloadHex"] = data[offset:end].hex()
            offset = end
        field["rawHex"] = data[start:offset].hex()
        fields.append(field)
    return fields

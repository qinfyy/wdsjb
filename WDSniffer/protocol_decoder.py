from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.descriptor import Descriptor
from google.protobuf.message import Message
from google.protobuf.unknown_fields import UnknownFieldSet


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "WDSniffer.json"
_CMD_NAMESPACE = re.compile(r"^\s*;\s*namespace\s+(.+?)\s*$")
_CMD_ENTRY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+)\s*$")


@dataclass(frozen=True)
class SnifferConfig:
    proto_paths: list[Path]
    cmd_ids_paths: list[Path]
    listening_port: int
    listening_address: str = "127.0.0.1"


def load_config(path: Path = DEFAULT_CONFIG) -> SnifferConfig:
    path = path.resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("WDSniffer.json 必须是 JSON 对象")

    def input_paths(key: str) -> list[Path]:
        value = config.get(key)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not value:
            raise ValueError(f"{key} 必须是非空的路径数组")
        targets: list[Path] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{key} 数组必须包含有效的路径字符串")
            target = Path(item)
            target = (target if target.is_absolute() else path.parent / target).resolve()
            if not target.is_file():
                raise FileNotFoundError(f"{key} 文件未找到: {target}")
            targets.append(target)
        return targets

    port = config.get("ListeningPort", 1984)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("ListeningPort 必须是 1 到 65535 的整数")
    address = config.get("ListeningAddress", "127.0.0.1")
    if not isinstance(address, str):
        raise ValueError("ListeningAddress 必须是字符串")
    address = address.strip() or "127.0.0.1"
    sources = config.get("proto")
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list) or not sources:
        raise ValueError("proto 必须是非空的路径数组")
    proto_paths: list[Path] = []
    for value in sources:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("proto 数组必须包含有效的路径字符串")
        target = Path(value)
        target = (target if target.is_absolute() else path.parent / target).resolve()
        if not target.is_dir() and not (target.is_file() and target.suffix.lower() == ".proto"):
            raise FileNotFoundError(f"proto 目录或文件未找到: {target}")
        proto_paths.append(target)
    cmd_ids_paths = input_paths("cmdId")
    return SnifferConfig(proto_paths, cmd_ids_paths, port, address)


@dataclass(frozen=True)
class CommandInfo:
    command_id: int
    clr_type: str

    @property
    def short_name(self) -> str:
        return self.clr_type.rsplit(".", 1)[-1].rsplit("/", 1)[-1]


def _read_cmd_ids(paths: list[Path]) -> dict[int, list[CommandInfo]]:
    commands: dict[str, CommandInfo] = {}
    for path in paths:
        namespace = ""
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = _CMD_NAMESPACE.match(line)
            if match:
                namespace = match.group(1)
                continue
            match = _CMD_ENTRY.match(line)
            if match:
                name, raw_command = match.groups()
                command_id = int(raw_command)
                info = CommandInfo(command_id, f"{namespace}.{name}" if namespace else name)
                # 忽略命名空间，后面的同名命令覆盖前面的。
                commands[info.short_name] = info
    if not commands:
        raise ValueError("CmdIds 文件中没有命令映射: " + ", ".join(str(path) for path in paths))
    entries: dict[int, list[CommandInfo]] = defaultdict(list)
    for info in commands.values():
        entries[info.command_id].append(info)
    return dict(entries)


def _message_coverage(message: Message) -> tuple[int, int]:
    fields = message.ListFields()
    known_count, unknown_count = len(fields), len(UnknownFieldSet(message))
    for field, value in fields:
        if field.message_type is None:
            continue
        if field.is_repeated:
            if field.message_type.GetOptions().map_entry:
                if field.message_type.fields_by_name["value"].message_type is None:
                    continue
                children = value.values()
            else:
                children = value
        else:
            children = (value,)
        for child in children:
            known, unknown = _message_coverage(child)
            known_count += known
            unknown_count += unknown
    return known_count, unknown_count


class WdProtocolDecoder:
    def __init__(self, config: SnifferConfig) -> None:
        self.proto_paths = config.proto_paths
        self.cmd_ids_paths = config.cmd_ids_paths
        self.protoc_path = ROOT / "protoc" / "protoc.exe"
        self.descriptor_paths: list[Path] = []
        self.command_types = _read_cmd_ids(self.cmd_ids_paths)
        self.pools: list[descriptor_pool.DescriptorPool] = []
        self.messages: dict[str, Descriptor] = {}
        self.descriptor_names: dict[str, str] = {}
        self._load_descriptor_pool()

    def _compile_descriptor(self, source: Path) -> Path:
        if not self.protoc_path.is_file():
            raise FileNotFoundError(f"protoc 未找到: {self.protoc_path}")
        source = source.resolve()
        root = source if source.is_dir() else source.parent
        files = sorted(path for path in source.rglob("*.proto") if path.is_file()) if source.is_dir() else [source]
        if not files:
            raise ValueError(f"proto 目录没有 .proto 文件: {source}")
        identity = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
        target = ROOT / "temp" / f"{source.stem}-{identity}.pb"
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [str(self.protoc_path), f"--descriptor_set_out={target}",
             "--include_imports", f"--proto_path={root}",
             f"--proto_path={self.protoc_path.parent}",
             *(path.relative_to(root).as_posix() for path in files)],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"protoc 编译失败: {source} ({completed.returncode}): {detail}")
        return target

    def _load_descriptor_pool(self) -> None:
        temp = ROOT / "temp"
        if temp.resolve() != temp:
            raise ValueError("temp 目录不能是目录链接")
        if any(source.resolve().is_relative_to(temp) for source in self.proto_paths):
            raise ValueError("proto 输入不能位于待清空的 temp 目录")
        if temp.exists():
            shutil.rmtree(temp)
        temp.mkdir()

        def visit(message: Descriptor) -> None:
            self.messages[message.name] = message
            for nested in message.nested_types:
                visit(nested)

        for source in self.proto_paths:
            target = self._compile_descriptor(source)
            self.descriptor_paths.append(target)
            descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(target.read_bytes())
            if not descriptor_set.file:
                raise ValueError(f"descriptor 没有文件定义: {target}")
            # 每份描述符独立加载；忽略包名，后面的同名消息覆盖前面的。
            pool = descriptor_pool.DescriptorPool()
            self.pools.append(pool)
            pending = list(descriptor_set.file)
            loaded: set[str] = set()
            while pending:
                ready = [item for item in pending if set(item.dependency) <= loaded]
                if not ready:
                    raise RuntimeError("descriptor 的依赖缺失或存在循环: " + ", ".join(item.name for item in pending))
                for item in ready:
                    pool.AddSerializedFile(item.SerializeToString())
                    loaded.add(item.name)
                    pending.remove(item)
                    for message in item.message_type:
                        full_name = ".".join(part for part in (item.package, message.name) if part)
                        visit(pool.FindMessageTypeByName(full_name))
        for candidates in self.command_types.values():
            for candidate in candidates:
                message = self.messages.get(candidate.short_name)
                if message is not None:
                    self.descriptor_names[candidate.clr_type] = message.full_name

    def status(self) -> dict[str, Any]:
        return {
            "proto_paths": [str(path) for path in self.proto_paths],
            "cmd_ids_paths": [str(path) for path in self.cmd_ids_paths],
            "descriptor_paths": [str(path) for path in self.descriptor_paths],
            "command_ids": len(self.command_types), "mapped_types": len(self.descriptor_names),
        }

    def decode_payload(
        self, payload: bytes, *, direction: str, command_id: int,
        runtime_class: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidates = self.command_types.get(command_id, [])
        record: dict[str, Any] = {
            "direction": direction, "protocol": "protobuf", "command_id": command_id,
            "command_name": "UNKNOWN", "message_type": None,
            "runtime_class": runtime_class, "payload_length": len(payload),
            "possible_protobuf_types": [item.clr_type for item in candidates],
            "raw_payload_base64": base64.b64encode(payload).decode("ascii"),
            "decoded": None, "decode_error": None, "candidate_decodes": [],
        }
        if not candidates:
            record.update(decode_status="mapping_missing", decode_error="CmdIds 中没有命令映射")
            return record

        best: tuple[dict[str, Any], dict[str, Any], tuple[bool, int]] | None = None
        for candidate in candidates:
            descriptor = self.messages.get(candidate.short_name)
            attempt: dict[str, Any] = {
                "command_name": candidate.short_name, "message_type": candidate.clr_type,
                "descriptor_name": descriptor.full_name if descriptor else None,
                "decode_status": "schema_missing", "decode_error": "schema 中未找到对应消息",
                "decoded_field_count": 0, "unknown_field_count": 0,
            }
            record["candidate_decodes"].append(attempt)
            if descriptor is None:
                continue
            try:
                message = message_factory.GetMessageClass(descriptor)()
                consumed = message.MergeFromString(payload)
                if consumed != len(payload):
                    raise ValueError(f"protobuf 只读取了 {consumed}/{len(payload)} 字节")
                if not message.IsInitialized():
                    raise ValueError("protobuf 缺少必填字段: " + ", ".join(message.FindInitializationErrors()))
                known_count, unknown_count = _message_coverage(message)
                decoded = json_format.MessageToDict(message, preserving_proto_field_name=True)
                complete = unknown_count == 0
                attempt.update(
                    decode_status="decoded" if complete else "decoded_partial",
                    decode_error=None if complete else f"部分解码: 已解析 {known_count} 个字段，仍有 {unknown_count} 个未知字段",
                    decoded_field_count=known_count, unknown_field_count=unknown_count,
                )
                # 完整候选并列取首个；只有部分候选才比较实际解析的字段数。
                score = (complete, 0 if complete else known_count)
                if best is None or score > best[2]:
                    best = (attempt, decoded, score)
            except Exception as error:
                attempt.update(decode_status="decode_error", decode_error=f"{type(error).__name__}: {error}")

        if best is None:
            failed = next((item for item in record["candidate_decodes"] if item["decode_status"] == "decode_error"),
                          record["candidate_decodes"][0])
            record.update(failed)
            if len(candidates) > 1:
                record["decode_error"] = "; ".join(
                    f"{item['command_name']}: {item['decode_error']}" for item in record["candidate_decodes"]
                )
            return record
        selected, decoded, _ = best
        record.update(selected, decoded=decoded)
        return record


def default_decoder(config_path: Path = DEFAULT_CONFIG) -> WdProtocolDecoder:
    return WdProtocolDecoder(load_config(config_path))

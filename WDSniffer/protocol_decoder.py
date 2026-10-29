"""BH2 主业务帧的 schema 驱动解码器。

仅 CommandMapBH2 对应的 ``bhxy2.*`` 命令会进入 Protobuf 解码。传统
COMMAND 始终保留原始负载，不会因为字节恰好符合 Protobuf wire 格式而猜测
字段结构。
"""

from __future__ import annotations

import base64
import json
import re
import struct
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory


HEADER_SIZE = 42
HEADER_STRUCT = struct.Struct(">IhHqqhhhqi")
MAX_HEX_PREVIEW_BYTES = 96
BH2_PROTOBUF_NAMESPACE = "bhxy2."

_CMD_NAMESPACE = re.compile(r"^\s*;\s*namespace\s+(.+?)\s*$")
_CMD_ENTRY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+)\s*$")
_COMMAND_TYPE_ENTRY = re.compile(
    r"\b(CMD_[A-Z0-9_]+)\s*(?:=|:)\s*(-?(?:0[xX][0-9A-Fa-f]+|\d+))"
)
@dataclass(frozen=True)
class CommandInfo:
    command_id: int
    clr_type: str

    @property
    def short_name(self) -> str:
        return self.clr_type.rsplit(".", 1)[-1].rsplit("/", 1)[-1]


def _read_cmd_ids(path: Path) -> dict[int, list[CommandInfo]]:
    namespace = ""
    entries: dict[int, list[CommandInfo]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        namespace_match = _CMD_NAMESPACE.match(line)
        if namespace_match:
            namespace = namespace_match.group(1)
            continue
        entry_match = _CMD_ENTRY.match(line)
        if entry_match is None:
            continue
        name, raw_command = entry_match.groups()
        command_id = int(raw_command)
        clr_type = f"{namespace}.{name}" if namespace else name
        info = CommandInfo(command_id=command_id, clr_type=clr_type)
        if info not in entries[command_id]:
            entries[command_id].append(info)
    return {command_id: values for command_id, values in entries.items()}


def _read_legacy_commands(path: Path) -> dict[int, str]:
    """读取 CommandType.txt 的传统 COMMAND 名称，仅用于 raw 包标签。"""

    source = path.read_text(encoding="utf-8-sig", errors="replace")
    commands: dict[int, str] = {}
    for match in _COMMAND_TYPE_ENTRY.finditer(source):
        name, raw_command = match.groups()
        commands.setdefault(int(raw_command, 0), name)
    return commands


class Bh2ProtocolDecoder:
    """仅解码已映射的 Protobuf 负载，并保留全部原始字节。"""

    def __init__(
        self,
        *,
        data_dir: Path,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.proto_path = self.data_dir / "bh2.proto"
        self.descriptor_path = self.data_dir / "bh2.pb"
        self.protoc_path = self.data_dir.parent / "protoc" / "protoc.exe"
        self.cmd_ids_path = self.data_dir / "CmdIds.txt"
        self.legacy_commands_path = self.data_dir / "CommandType.txt"
        self.command_types = _read_cmd_ids(self.cmd_ids_path)
        # CommandMapBH2 的 1002 项均为 bhxy2.*。CmdIds.txt 末尾的
        # proto.* 是旧 AgentProxy 的 CommandMap，不能作为主业务 Protobuf
        # 的判据。
        self.command_map_bh2_types = {
            command_id: [
                candidate
                for candidate in candidates
                if candidate.clr_type.startswith(BH2_PROTOBUF_NAMESPACE)
            ]
            for command_id, candidates in self.command_types.items()
            if any(candidate.clr_type.startswith(BH2_PROTOBUF_NAMESPACE) for candidate in candidates)
        }
        self.legacy_commands = _read_legacy_commands(self.legacy_commands_path)
        self.pool: descriptor_pool.DescriptorPool | None = None
        self.descriptor_error: str | None = None
        self.proto_package: str | None = None
        self.descriptor_names: dict[str, str] = {}
        self._load_descriptor_pool()

    def _load_descriptor_pool(self) -> None:
        try:
            if not self.protoc_path.is_file():
                raise FileNotFoundError(f"protoc 未找到: {self.protoc_path}")
            if not self.proto_path.is_file():
                raise FileNotFoundError(f"protobuf 源文件未找到: {self.proto_path}")

            completed = subprocess.run(
                [
                    str(self.protoc_path),
                    f"--descriptor_set_out={self.descriptor_path.name}",
                    "--include_imports",
                    self.proto_path.name,
                ],
                cwd=self.data_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"protoc 编译失败 ({completed.returncode}): {detail}")

            descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(
                self.descriptor_path.read_bytes()
            )
            source_descriptor = next(
                (
                    file_descriptor
                    for file_descriptor in descriptor_set.file
                    if Path(file_descriptor.name).name == self.proto_path.name
                ),
                None,
            )
            if source_descriptor is None:
                raise RuntimeError(
                    f"descriptor set 中未找到源文件: {self.proto_path.name}"
                )
            self.proto_package = source_descriptor.package

            pool = descriptor_pool.DescriptorPool()
            for file_descriptor in descriptor_set.file:
                pool.AddSerializedFile(file_descriptor.SerializeToString())
            self.pool = pool

            # CmdIds.txt 的短类名对应 schema package 下的顶层消息。package
            # 直接取自 protoc descriptor，避免与生成器的包名配置重复绑定。
            self.descriptor_names = {}
            for candidates in self.command_types.values():
                for candidate in candidates:
                    descriptor_name = ".".join(
                        part
                        for part in (self.proto_package, candidate.short_name)
                        if part
                    )
                    try:
                        pool.FindMessageTypeByName(descriptor_name)
                    except KeyError:
                        continue
                    self.descriptor_names[candidate.clr_type] = descriptor_name
        except Exception as error:
            self.pool = None
            self.proto_package = None
            self.descriptor_names = {}
            self.descriptor_error = f"{type(error).__name__}: {error}"

    def status(self) -> dict[str, Any]:
        mapped_types = sum(
            1
            for candidates in self.command_map_bh2_types.values()
            for candidate in candidates
            if candidate.clr_type in self.descriptor_names
        )
        return {
            "proto_path": str(self.proto_path),
            "cmd_ids_path": str(self.cmd_ids_path),
            "legacy_commands_path": str(self.legacy_commands_path),
            "schema_loader": "protoc_descriptor_set",
            "proto_package": self.proto_package,
            "descriptor_error": self.descriptor_error,
            "cmd_ids_command_ids": len(self.command_types),
            "protobuf_command_ids": len(self.command_map_bh2_types),
            "protobuf_mapped_types": mapped_types,
            "legacy_command_ids": len(self.legacy_commands),
            "clr_message_mappings": len(self.descriptor_names),
        }

    def _candidate_for_runtime_class(
        self,
        runtime_class: dict[str, Any] | None,
        candidates: list[CommandInfo],
    ) -> CommandInfo | None:
        if not isinstance(runtime_class, dict):
            return None
        full_name = runtime_class.get("full_name")
        if not isinstance(full_name, str):
            return None
        for candidate in candidates:
            if candidate.clr_type == full_name:
                return candidate
        return None

    def _resolve_protobuf_type(
        self,
        command_id: int,
        runtime_class: dict[str, Any] | None,
        protocol_hint: str | None,
    ) -> tuple[CommandInfo | None, str | None, list[str]]:
        all_candidates = self.command_map_bh2_types.get(command_id, [])
        descriptor_candidates = [
            candidate
            for candidate in all_candidates
            if candidate.clr_type in self.descriptor_names
        ]

        # GeneralPackage 的 Hook 已确认其调用路径是传统 COMMAND。即使
        # 命令号与 CommandMapBH2 重合，也不能把它当作 Protobuf。
        if protocol_hint == "command":
            return None, None, [candidate.clr_type for candidate in descriptor_candidates]

        runtime_candidate = self._candidate_for_runtime_class(runtime_class, all_candidates)

        if runtime_candidate is not None:
            return runtime_candidate, "runtime_class", [
                candidate.clr_type for candidate in descriptor_candidates
            ]

        # PB Hook 已处在 UnPackProtoBufPacket 或 SendProtoBufPacket 的调用
        # 链中，cmdId 因而可安全映射到 CommandMapBH2。
        if protocol_hint == "protobuf" and len(descriptor_candidates) == 1:
            return descriptor_candidates[0], "hook", [
                candidate.clr_type for candidate in descriptor_candidates
            ]

        # 无 Hook 标记的离线帧不能只按 cmdId 判别：CommandMapBH2 与旧
        # COMMAND 有少量重号。重号帧保持为 COMMAND raw，除非上方已有
        # PB Hook 或运行时类型作为明确证据。
        if command_id in self.legacy_commands:
            return None, None, [candidate.clr_type for candidate in descriptor_candidates]

        # 不属于旧 COMMAND 表的 cmdId 可按 CommandMapBH2 离线恢复。
        if len(descriptor_candidates) == 1:
            resolution = "command_map_bh2"
            return descriptor_candidates[0], resolution, [
                candidate.clr_type for candidate in descriptor_candidates
            ]
        return None, None, [candidate.clr_type for candidate in descriptor_candidates]

    def _decode_protobuf(self, clr_type: str, payload: bytes) -> tuple[dict[str, Any] | None, str | None, str]:
        descriptor_name = self.descriptor_names[clr_type]
        if self.pool is None:
            return None, self.descriptor_error or "descriptor pool is unavailable", descriptor_name
        try:
            descriptor = self.pool.FindMessageTypeByName(descriptor_name)
            message_class = message_factory.GetMessageClass(descriptor)
            message = message_class()
            consumed = message.MergeFromString(payload)
            if consumed != len(payload):
                raise ValueError(f"protobuf consumed {consumed} of {len(payload)} bytes")
            decoded = json_format.MessageToDict(
                message,
                preserving_proto_field_name=True,
            )
            return decoded, None, descriptor_name
        except Exception as error:
            return None, f"{type(error).__name__}: {error}", descriptor_name

    @staticmethod
    def _raw_fields(frame: bytes, payload: bytes) -> dict[str, Any]:
        return {
            "raw_frame_base64": base64.b64encode(frame).decode("ascii"),
            "raw_payload_base64": base64.b64encode(payload).decode("ascii"),
            "frame_hex_preview": frame[:MAX_HEX_PREVIEW_BYTES].hex(),
            "payload_hex_preview": payload[:MAX_HEX_PREVIEW_BYTES].hex(),
        }

    @staticmethod
    def _header(frame: bytes) -> dict[str, Any]:
        (
            declared_length,
            command_id,
            version,
            uid,
            session_id,
            gateway_id,
            namespace_id,
            work_type,
            reference,
            new_version,
        ) = HEADER_STRUCT.unpack_from(frame)
        return {
            "declared_length": declared_length,
            "command_id": command_id,
            "version": version,
            "uid": str(uid),
            "session_id": str(session_id),
            "gateway_id": gateway_id,
            "namespace_id": namespace_id,
            "work_type": work_type,
            "reference": str(reference),
            "new_version": new_version,
            "length_matches_capture": declared_length == len(frame),
        }

    def decode_frame(
        self,
        frame: bytes,
        *,
        direction: str,
        runtime_class: dict[str, Any] | None = None,
        protocol_hint: str | None = None,
        command_id_hint: int | None = None,
    ) -> dict[str, Any]:
        """返回可 JSON 序列化的包记录，并始终保留原始字节。"""

        normalized_hint = protocol_hint if protocol_hint in {"protobuf", "command"} else None

        if len(frame) < HEADER_SIZE:
            return {
                "direction": direction,
                "protocol": "raw",
                "decode_status": "not_a_complete_business_frame",
                "decode_error": f"frame is {len(frame)} bytes, shorter than {HEADER_SIZE}-byte ProtocolHead",
                "frame_length": len(frame),
                "payload_length": len(frame),
                "runtime_class": runtime_class,
                "protocol_hint": normalized_hint,
                "command_id_hint": command_id_hint,
                "decoded": None,
                "header": None,
                "command_id": None,
                "command_name": None,
                "message_type": None,
                "possible_protobuf_types": [],
                **self._raw_fields(frame, frame),
            }

        header = self._header(frame)
        payload = frame[HEADER_SIZE:]
        command_id = int(header["command_id"])
        candidate, resolution, possible_types = self._resolve_protobuf_type(
            command_id,
            runtime_class,
            normalized_hint,
        )
        record: dict[str, Any] = {
            "direction": direction,
            "protocol_hint": normalized_hint,
            "command_id_hint": command_id_hint,
            "frame_length": len(frame),
            "payload_length": len(payload),
            "runtime_class": runtime_class,
            "header": header,
            "command_id": command_id,
            "command_name": None,
            "message_type": None,
            "descriptor_name": None,
            "possible_protobuf_types": possible_types,
            "decoded": None,
            **self._raw_fields(frame, payload),
        }

        if not header["length_matches_capture"]:
            record.update(
                {
                    "protocol": "raw",
                    "decode_status": "frame_length_mismatch",
                    "decode_error": (
                        f"ProtocolHead declares {header['declared_length']} bytes, "
                        f"but hook captured {len(frame)} bytes"
                    ),
                }
            )
            return record

        if command_id_hint is not None and (int(command_id_hint) & 0xFFFF) != (command_id & 0xFFFF):
            record.update(
                {
                    "protocol": "raw",
                    "decode_status": "command_id_mismatch",
                    "decode_error": (
                        f"hook reports command {int(command_id_hint) & 0xFFFF}, "
                        f"but ProtocolHead contains {command_id & 0xFFFF}"
                    ),
                }
            )
            return record

        if candidate is None:
            if normalized_hint == "protobuf":
                record.update(
                    {
                        "protocol": "protobuf",
                        "decode_status": "mapping_missing",
                        "command_name": f"UNKNOWN_{command_id}",
                        "decode_error": "Protobuf hook captured a command absent from CommandMapBH2 schema",
                    }
                )
            else:
                record.update(
                    {
                        "protocol": "command",
                        "decode_status": "raw_only",
                        "command_name": self.legacy_commands.get(command_id, f"UNKNOWN_{command_id}"),
                        "decode_error": None,
                    }
                )
            return record

        decoded, decode_error, descriptor_name = self._decode_protobuf(candidate.clr_type, payload)
        record.update(
            {
                "protocol": "protobuf",
                "decode_status": "decoded" if decode_error is None else "decode_error",
                "decode_error": decode_error,
                "command_name": candidate.short_name,
                "message_type": candidate.clr_type,
                "descriptor_name": descriptor_name,
                "type_resolution": resolution,
                "decoded": decoded,
            }
        )
        return record


def default_decoder(sniffer_root: Path) -> Bh2ProtocolDecoder:
    """仅从 BH2Sniffer/data 构建运行时协议解码器。"""

    return Bh2ProtocolDecoder(data_dir=sniffer_root / "data")

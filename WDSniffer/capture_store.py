"""转换、保存和导入当前抓包器的七字段 JSON 包对象。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, TextIO


CAPTURE_PACKET_FIELDS = ("time", "fromServer", "packetId", "packetName", "object", "type", "raw")


class PacketCaptureWriter:
    """以 SSSniffer JSON 块格式追加包含 Type 的前端包对象。"""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._file: TextIO | None = None
        self.path: Path | None = None

    def write(self, packet: dict[str, Any]) -> None:
        with self._lock:
            if self._file is None:
                timestamp = time.localtime()
                stem = time.strftime("PacketCapture_%y-%m-%d_%H-%M-%S", timestamp)
                suffix = 0
                while True:
                    filename = f"{stem}.json" if suffix == 0 else f"{stem}_{suffix:02d}.json"
                    path = self._directory / filename
                    try:
                        # 使用 x 模式避免两个抓包器在同一秒覆盖彼此的记录。
                        self._file = path.open("x", encoding="utf-8", newline=None)
                        self.path = path
                        break
                    except FileExistsError:
                        suffix += 1
            self._file.write(json.dumps(packet, ensure_ascii=False, indent=4))
            self._file.write("\n")
            self._file.flush()

    def start_session(self) -> None:
        """Start a new capture file for the next Frida session."""
        with self._lock:
            if self._file is not None:
                self._file.close()
            self._file = None
            self.path = None

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


def record_to_frontend_packet(record: dict[str, Any], timestamp_ms: int | None = None) -> dict[str, Any]:
    """将解码记录转换为 App.vue 使用的七个 SSE/保存字段。"""

    command_id = record.get("command_id")
    packet_id = int(command_id) if isinstance(command_id, int) else 0
    protocol = record.get("protocol")

    if protocol == "protobuf":
        command_name = str(record.get("command_name") or f"UNKNOWN_{packet_id}")
        packet_name = command_name
        packet_type = "CmdId"
        packet_object = record.get("decoded") if record.get("decode_status") == "decoded" else None
    elif protocol == "command":
        command_name = str(record.get("command_name") or f"UNKNOWN_{packet_id}")
        packet_name = command_name
        packet_type = "COMMAND"
        packet_object = None
    else:
        packet_name = f"RAW.{packet_id}" if command_id is not None else "RAW.UNKNOWN"
        packet_type = "RAW"
        packet_object = None

    return {
        "time": int(timestamp_ms if timestamp_ms is not None else time.time() * 1000),
        "fromServer": record.get("direction") == "rx",
        "packetId": packet_id,
        "packetName": packet_name,
        "object": packet_object,
        "type": packet_type,
        "raw": str(record.get("raw_payload_base64") or ""),
    }


def parse_uploaded_capture(filename: str, content: bytes) -> list[dict[str, Any]]:
    """只接受当前抓包器导出的 .json 文件。"""

    if Path(filename).suffix.lower() != ".json":
        raise ValueError("unsupported file format; use the current sniffer's .json export")
    return _parse_json_capture(content)


def _parse_json_capture(content: bytes) -> list[dict[str, Any]]:
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("JSON capture must be UTF-8") from error

    packet_list: list[dict[str, Any]] = []
    json_decoder = json.JSONDecoder()
    position = 0
    source_length = len(source)

    while position < source_length:
        while position < source_length and source[position].isspace():
            position += 1
        if position >= source_length:
            break
        try:
            value, position = json_decoder.raw_decode(source, position)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON capture near character {error.pos}") from error

        if not isinstance(value, dict):
            raise ValueError("each JSON capture entry must be a current sniffer packet object")
        packet_list.append(_json_entry_to_frontend_packet(value))

    if not packet_list:
        raise ValueError("JSON capture contains no business packets")
    return packet_list


def _json_entry_to_frontend_packet(entry: dict[str, Any]) -> dict[str, Any]:
    """校验当前保存字段，不再推断协议类型或补齐旧字段。"""

    for field in CAPTURE_PACKET_FIELDS:
        if field not in entry:
            raise ValueError(f"capture packet is missing required field: {field}")
    for field in ("time", "packetId"):
        if isinstance(entry[field], bool) or not isinstance(entry[field], int):
            raise ValueError(f"packet {field} must be an integer")
    if not isinstance(entry["fromServer"], bool):
        raise ValueError("packet fromServer must be a boolean")
    if not isinstance(entry["packetName"], str):
        raise ValueError("packet packetName must be a string")
    if entry["object"] is not None and not isinstance(entry["object"], dict):
        raise ValueError("packet object must be an object or null")
    if entry["type"] not in ("CmdId", "COMMAND", "RAW"):
        raise ValueError("packet type must be CmdId, COMMAND, or RAW")
    if not isinstance(entry["raw"], str):
        raise ValueError("packet raw must be a Base64 string")
    return {field: entry[field] for field in CAPTURE_PACKET_FIELDS}

from __future__ import annotations

import base64
from collections import Counter
import math
import struct
from typing import Any

from google.protobuf.internal import decoder, wire_format
from google.protobuf.message import DecodeError


_WIRE_NAMES = {
    wire_format.WIRETYPE_VARINT: "varint",
    wire_format.WIRETYPE_FIXED64: "64b",
    wire_format.WIRETYPE_LENGTH_DELIMITED: "ld",
    wire_format.WIRETYPE_FIXED32: "32b",
}


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    try:
        value, end = decoder._DecodeVarint(data, offset)
    except IndexError as error:
        raise ValueError("varint 截断") from error
    except DecodeError as error:
        raise ValueError("varint 超长") from error
    if end - offset == 10 and data[end - 1] > 1:
        raise ValueError("varint 超出 uint64")
    return value, end


def _wire_parts(data: bytes) -> tuple[list[tuple[int, int, int | bytes]], bytes]:
    parts: list[tuple[int, int, int | bytes]] = []
    offset = 0
    if len(data) >= 5 and data[0] == 0 and int.from_bytes(data[1:5], "big", signed=True) <= len(data) - 5:
        offset = 5
    while offset < len(data):
        start = offset
        try:
            key, offset = read_varint(data, offset)
            tag, wire = wire_format.UnpackTag(key)
            if wire not in _WIRE_NAMES:
                raise ValueError("不支持的 protobuf wire")
            if wire == wire_format.WIRETYPE_VARINT:
                value, offset = read_varint(data, offset)
            else:
                size = 8 if wire == wire_format.WIRETYPE_FIXED64 else 4
                if wire == wire_format.WIRETYPE_LENGTH_DELIMITED:
                    size, offset = read_varint(data, offset)
                end = offset + size
                if end > len(data):
                    raise ValueError("protobuf 字段截断")
                value = data[offset:end]
                offset = end
        except ValueError:
            return parts, data[start:]
        parts.append((tag, wire, value))
    return parts, b""


def _decode_fixed(data: bytes) -> dict[str, Any]:
    decode_value, kind, encoding = (
        (decoder._DecodeFixed32, "float", wire_format.FORMAT_FLOAT_LITTLE_ENDIAN) if len(data) == 4
        else (decoder._DecodeFixed64, "double", wire_format.FORMAT_DOUBLE_LITTLE_ENDIAN)
    )
    unsigned, _ = decode_value(data, 0)
    floating = struct.unpack(encoding, data)[0]
    return {
        "int": unsigned,
        "signed_int": int.from_bytes(data, "little", signed=True),
        kind: floating if math.isfinite(floating) else None,
        "raw_hex": data.hex(),
    }


def _decode_length_delimited(data: bytes, depth: int) -> dict[str, Any]:
    nested = inspect_wire(data, depth + 1)
    if data and "leftOver" not in nested:
        return {"message": nested}
    try:
        text = data.decode("utf-8")
        readable = all(character.isprintable() or character in "\t\r\n" for character in text)
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        readable = False
    interpretations: dict[str, Any] = {
        "string": text, "raw_hex": data.hex(),
        "repeated_int": None, "repeated_signed_int": None,
    }
    if readable:
        return interpretations
    try:
        packed: list[int] = []
        offset = 0
        while offset < len(data):
            value, offset = read_varint(data, offset)
            packed.append(value)
        if packed:
            interpretations["repeated_int"] = packed
            interpretations["repeated_signed_int"] = [wire_format.ZigZagDecode(value) for value in packed]
    except ValueError:
        pass
    return interpretations


def inspect_wire(data: bytes, depth: int = 0) -> dict[str, Any]:
    if depth >= 64:
        return {"leftOver": base64.b64encode(data).decode("ascii")}
    parts, leftover = _wire_parts(data)
    document: dict[str, Any] = {}
    repeated: Counter[str] = Counter()
    for tag, wire, value in parts:
        key = str(tag)
        repeated[key] += 1
        if repeated[key] > 1:
            key += f"#{repeated[key]}"
        field: dict[str, Any] = {"wire": _WIRE_NAMES[wire]}
        if isinstance(value, int):
            field.update(int=value, signed_int=wire_format.ZigZagDecode(value))
        elif wire == wire_format.WIRETYPE_LENGTH_DELIMITED:
            field.update(_decode_length_delimited(value, depth))
        else:
            field.update(_decode_fixed(value))
        document[key] = field
    if leftover:
        document["leftOver"] = base64.b64encode(leftover).decode("ascii")
    return document

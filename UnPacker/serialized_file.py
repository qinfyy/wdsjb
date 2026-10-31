"""使用 UnityPy 提取 Unity SerializedFile 中的 TextAsset。"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import UnityPy


@dataclass(frozen=True, slots=True)
class TextAssetRecord:
    """一个 Unity TextAsset 的原始内容。"""

    name: str
    data: bytes
    path_id: int
    class_id: int
    container_path: str
    input_file: str = ""


def _read_aligned_bytes(raw: bytes, offset: int) -> tuple[bytes, int]:
    """读取 Unity SerializedFile 的长度前缀字节串。"""

    if offset + 4 > len(raw):
        raise ValueError("TextAsset 长度字段越界")
    size = struct.unpack_from("<I", raw, offset)[0]
    start = offset + 4
    end = start + size
    if end > len(raw):
        raise ValueError("TextAsset 字节串越界")
    return raw[start:end], (end + 3) & ~3


def extract_text_assets(serialized_file: bytes, input_file: str = "") -> tuple[list[TextAssetRecord], dict[int, int]]:
    """解析 SerializedFile，返回 TextAsset 和各 ClassID 的对象数量。"""

    environment = UnityPy.load(serialized_file)
    records: list[TextAssetRecord] = []
    objects = environment.objects
    text_objects = [obj for obj in objects if obj.class_id == 49]
    class_counts: dict[int, int] = {}
    for obj in objects:
        class_id = int(obj.class_id)
        class_counts[class_id] = class_counts.get(class_id, 0) + 1
    container_paths: dict[int, str] = {}
    try:
        container_paths = {obj.path_id: path for path, obj in environment.container.items()}
    except RuntimeError as error:
        if "dictionary changed size during iteration" not in str(error):
            raise

    for obj in text_objects:
        raw = obj.get_raw_data()
        name_bytes, script_offset = _read_aligned_bytes(raw, 0)
        script, _ = _read_aligned_bytes(raw, script_offset)
        records.append(
            TextAssetRecord(
                name_bytes.decode("utf-8", errors="replace"),
                script,
                int(obj.path_id),
                int(obj.class_id),
                container_paths.get(obj.path_id, ""),
                input_file,
            )
        )
    return records, class_counts

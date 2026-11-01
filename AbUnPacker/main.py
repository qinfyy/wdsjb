"""按 AssetBundleXMLData 目录表解包 AB 二层 VFS，或仅导出 JS/TS 脚本。"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import UnityPy
from UnityPy.files import BundleFile

from bundle_source import BundleTask, asset_path, canonical_path, catalog_data, load_bundle, prepare, script_name

INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_COMPONENT = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.IGNORECASE)


@dataclass
class ResourceAsset:
    entry: dict[str, object]
    data: bytes


@dataclass
class BundleRead:
    bundle: str
    text_assets: int
    script_assets: int
    assets: list[ResourceAsset]
    vfs: list[ResourceAsset]
    errors: list[dict[str, object]]
    warnings: list[dict[str, object]]


def safe_relative(name: str) -> Path:
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or any(
        not part or part in (".", "..") or INVALID_COMPONENT.search(part)
        or part.endswith((" ", ".")) or RESERVED_COMPONENT.fullmatch(part) for part in parts
    ):
        raise ValueError(f"资产路径无效：{name}")
    return Path(*parts)


def safe_component(name: str) -> str:
    name = INVALID_COMPONENT.sub("_", name).rstrip(" .")
    if not name or name in (".", "..") or RESERVED_COMPONENT.fullmatch(name):
        name = "_" + name
    return name


def asset_output(path: str, name: str, js_exporter: bool, text_asset: bool) -> Path:
    if js_exporter:
        selected = script_name(path)
        if selected is None:
            raise ValueError("目录表资源没有受支持的脚本后缀")
        path = selected[0]
    parts = list(safe_relative(path).parts)
    if parts[0].casefold() == "assets":
        parts.pop(0)
    if js_exporter and len(parts) >= 2 and [part.casefold() for part in parts[:2]] == ["assetbundles", "scripts"]:
        parts = parts[2:]
    named = script_name(name) if js_exporter else None
    if named and parts and parts[-1].casefold() == named[0].casefold():
        parts[-1] = named[0]
    relative = safe_relative("/".join(parts))
    return relative if text_asset else Path(str(relative) + ".serialized.bin")


def read_text_asset(raw: bytes) -> tuple[str, bytes]:
    """读取两个长度前缀字段，保留正文原始字节。"""
    def read_field(offset: int) -> tuple[bytes, int]:
        if offset + 4 > len(raw):
            raise ValueError("TextAsset 长度字段截断")
        size, = struct.unpack_from("<i", raw, offset)
        start, end = offset + 4, offset + 4 + size
        if size < 0 or end > len(raw):
            raise ValueError("TextAsset 字段长度越界")
        return raw[start:end], (end + 3) & ~3

    name, offset = read_field(0)
    data, _ = read_field(offset)
    return name.decode("utf-8"), data


def read_listed_bundle(task: BundleTask) -> BundleRead:
    result = BundleRead(task.bundle, 0, 0, [], [], [], [])
    try:
        environment = UnityPy.load(load_bundle(task))
        if not task.js_exporter:
            # 保留全部 CAB/resS 节点，避免只导出容器主对象而丢失组件、流式贴图或音频数据。
            for bundle in environment.files.values():
                if not isinstance(bundle, BundleFile):
                    continue
                for path, file in bundle.files.items():
                    reader = getattr(file, "reader", file)
                    data = reader.bytes
                    relative = (Path("__vfs") / safe_relative(task.bundle).with_suffix("")
                                / safe_relative(path)).as_posix()
                    entry = {"bundle": task.bundle, "serializedFile": path, "pathID": None,
                             "name": path, "category": "vfs", "format": "unityfs-node",
                             "extension": Path(path).suffix, "size": len(data),
                             "sha256": hashlib.sha256(data).hexdigest(), "output": relative}
                    result.vfs.append(ResourceAsset(entry, data))
        requested: dict[str, list[tuple[int, str]]] = {}
        for index, asset in enumerate(task.assets):
            path = asset_path(asset, task.js_exporter)
            for key in ("ResPath", "AssetFullName"):
                if asset.get(key):
                    requested.setdefault(canonical_path(asset[key]), []).append((index, path))
        found: set[int] = set()
        for asset_file in environment.assets:
            for path, pointer in asset_file.container.items():
                targets = requested.get(canonical_path(path))
                if not targets:
                    continue
                if all(index in found for index, _ in targets):
                    continue
                try:
                    obj = pointer.deref()
                    is_text = obj.class_id == 49
                    if task.js_exporter and not is_text:
                        raise ValueError(f"目录表脚本不是 TextAsset：{path}")
                    raw = obj.get_raw_data()
                    name, data = read_text_asset(raw) if is_text else (Path(path).name, raw)
                    for index, original_path in targets:
                        if index in found:
                            continue
                        relative = asset_output(original_path, name, task.js_exporter, is_text)
                        kind = script_name(original_path) if is_text else None
                        entry = {"bundle": task.bundle, "serializedFile": obj.assets_file.name,
                                 "pathID": obj.path_id, "name": name, "containerPaths": [original_path],
                                 "classID": obj.class_id, "type": obj.type.name, "category": "asset",
                                 "format": "text-asset" if is_text else "unity-serialized-object",
                                 "extension": kind[1] if kind else relative.suffix,
                                 "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                 "output": relative.as_posix()}
                        if task.location:
                            entry["location"] = task.location
                        result.assets.append(ResourceAsset(entry, data))
                        result.text_assets += is_text
                        result.script_assets += bool(kind)
                        found.add(index)
                except Exception as error:
                    result.errors.append({"bundle": task.bundle, "stage": "asset", "path": path,
                                          "reason": f"{type(error).__name__}: {error}"})
        for index, asset in enumerate(task.assets):
            if index not in found:
                result.errors.append({"bundle": task.bundle, "stage": "selection",
                                      "path": asset_path(asset, task.js_exporter),
                                      "reason": "AB 容器中未能读取目录表指定的资源"})
    except Exception as error:
        result.errors.append({"bundle": task.bundle, "stage": "bundle",
                              "reason": f"{type(error).__name__}: {error}"})
    return result


def output_path(root: Path, relative: str) -> Path:
    target = (root / safe_relative(relative)).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError(f"输出路径越界：{relative}")
    return target


def write_preserving(path: Path, data: bytes) -> str:
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError("已有不同内容，拒绝覆盖")
        return "existing"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return "exported"


def run(args: argparse.Namespace) -> dict[str, object]:
    source, output = args.input.resolve(), args.output.resolve()
    if not source.exists():
        raise ValueError("输入路径不存在")
    if source == output or (source.is_dir() and output.is_relative_to(source)):
        raise ValueError("输出目录不能等于输入目录或位于输入目录内")
    tasks, metadata = prepare(source, args.index, args.list, args.list_only, args.js_exporter)
    document = metadata.pop("table", None)
    output.mkdir(parents=True, exist_ok=True)
    if args.list_only:
        document = catalog_data(document)
        target = output_path(output, "manifest.json")
        with target.open("w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        bundles = document["BundleInfos"]
        print(f"完成：目录表 {len(bundles)} 个包，{sum(len(bundle.get('Assets') or []) for bundle in bundles)} 个资源",
              file=sys.stderr)
        print(f"清单：{target}", file=sys.stderr)
        return document

    entries: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    occupied: dict[str, str] = {}
    text_count = script_count = asset_count = vfs_count = bundles_with_assets = conflicts = 0
    for index, task in enumerate(tasks, 1):
        result = read_listed_bundle(task)
        text_count += result.text_assets
        script_count += result.script_assets
        asset_count += len(result.assets)
        vfs_count += len(result.vfs)
        bundles_with_assets += bool(result.assets)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        for resource in result.assets + result.vfs:
            entry = resource.entry
            relative = str(entry["output"])
            key = relative.casefold()
            digest = str(entry["sha256"])
            if key in occupied and occupied[key] != digest:
                conflicts += 1
                entry["conflictOutput"] = relative
                relative = (Path("__conflicts") / safe_relative(result.bundle).with_suffix("")
                            / safe_component(str(entry["serializedFile"])) / str(entry["pathID"])
                            / safe_relative(relative)).as_posix()
                entry["output"] = relative
                key = relative.casefold()
            occupied[key] = digest
            try:
                entry["status"] = write_preserving(output_path(output, relative), resource.data)
            except (OSError, ValueError) as error:
                entry.update(status="failed", reason=str(error))
                errors.append({"bundle": result.bundle, "pathID": entry["pathID"], "stage": "output",
                               "output": relative, "reason": str(error)})
            entries.append(entry)
        if index % 500 == 0 or index == len(tasks):
            print(f"[{index}/{len(tasks)}] 资源 {asset_count}，VFS 文件 {vfs_count}，错误 {len(errors)}", flush=True)
    counts = Counter(str(entry["extension"]) for entry in entries)
    report: dict[str, object] = {
        **metadata, "jsExporter": args.js_exporter, "bundleCount": len(tasks),
        "bundlesWithAssets": bundles_with_assets, "assetCount": asset_count, "vfsFileCount": vfs_count,
        "textAssetCount": text_count,
        "scriptAssetCount": script_count, "matchedCount": len(entries), "uniqueOutputCount": len(occupied),
        "extensions": dict(counts), "conflictCount": conflicts, "errorCount": len(errors),
        "warningCount": len(warnings), "assets": [entry for entry in entries if entry["category"] == "asset"],
        "vfsFiles": [entry for entry in entries if entry["category"] == "vfs"],
        "errors": errors, "warnings": warnings,
    }
    target = output_path(output, "report.json")
    with target.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"报告：{target}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="AB 目录或单个 AB；有 --index 时为 BLK 目录")
    parser.add_argument("--index", type=Path, help="XMF 文件或其目录，启用 BLK 模式")
    parser.add_argument("--output", type=Path, default=Path("output"), help="全部 VFS 文件和资源的输出目录；--list-only 时仅输出格式化 JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-only", action="store_true", help="只反序列化 AssetBundleXMLData.xml，不解码 AB")
    mode.add_argument("--list", type=Path, help="目录表 JSON 或其目录，恢复其中的资源")
    parser.add_argument("--js-exporter", action="store_true", help="仅导出 .js、.js.map、.ts TextAsset")
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    return 1 if result.get("errorCount", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""AB、XMF/BLK 和 AssetBundleXMLData 目录表的输入规划。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import sys
from typing import Any

import nrbf

UNPACKER = Path(__file__).resolve().parents[1] / "UnPacker"
sys.path.insert(0, str(UNPACKER))
from file_map import FileMap, MappedFile, parse_file_map
from resource_store import BlockStore
from unityfs import unpack_unityfs

SCRIPT_SUFFIXES = (".js.map", ".js", ".ts")
CATALOG_NAME = "AssetBundleXMLData.xml"
TABLE_TYPE = "Res.ABSystem.AssetBundleTable"


def script_name(name: str) -> tuple[str, str] | None:
    candidate = name[:-4] if name.casefold().endswith(".txt") else name
    return next(((candidate, suffix) for suffix in SCRIPT_SUFFIXES
                 if candidate.casefold().endswith(suffix)), None)


def canonical_path(path: str) -> str:
    path = path.replace("\\", "/").casefold()
    if path.startswith("assets/"):
        path = path[7:]
    return path[:-4] if path.endswith(".txt") and script_name(path) else path


def script_path(asset: dict[str, Any]) -> str | None:
    return next((path for key in ("ResPath", "AssetFullName")
                 if isinstance(path := asset.get(key), str) and script_name(path)), None)


def asset_path(asset: dict[str, Any], js_exporter: bool = False) -> str:
    if js_exporter:
        path = script_path(asset)
    else:
        path = next((path for key in ("AssetFullName", "ResPath")
                     if isinstance(path := asset.get(key), str) and path), None)
    if path is None:
        raise ValueError("目录表资源缺少有效路径")
    return path


@dataclass
class BundleTask:
    filename: str
    bundle: str
    location: dict[str, Any] | None = None
    assets: list[dict[str, Any]] = field(default_factory=list)
    js_exporter: bool = False


def inside(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if not name or "\\" in name or ":" in name or target == root or not target.is_relative_to(root):
        raise ValueError(f"输入条目路径越界：{name}")
    return target


def resolve_index(path: Path, root: Path) -> Path:
    if path.is_file():
        return path
    if not path.is_dir():
        raise ValueError("--index 指定的 XMF 文件或目录不存在")
    files = sorted(path.glob("*.xmf"))
    preferred = [file for file in files if file.stem.casefold() == root.name.casefold()]
    if len(preferred) == 1:
        return preferred[0]
    if len(files) == 1:
        return files[0]
    raise ValueError("XMF 目录没有唯一匹配项，请指定 AssetbundlesCache.xmf 文件")


def read_manifest(path: Path) -> dict[str, Any]:
    path = path / "manifest.json" if path.is_dir() else path
    with path.open(encoding="utf-8-sig") as stream:
        document = json.load(stream)
    catalog_assets(document)
    return document


def parse_catalog(data: bytes) -> dict[str, Any]:
    # CN 6.1.0 libil2cpp.so 0x02B86B6C：仅解析 BinaryFormatter 数据，不实例化 .NET 类型。
    try:
        document = nrbf.loads(data)
    except Exception as error:
        raise ValueError(f"{CATALOG_NAME} 反序列化失败：{error}") from error
    if not isinstance(document, dict) or document.get("__class__") != TABLE_TYPE:
        raise ValueError("AssetBundleXMLData.xml 不是 AssetBundleTable")
    catalog_assets(document)
    return document


def catalog_data(value: Any) -> Any:
    """保留全部原字段，移除 NRBF 解码器添加的重复类型标签。"""
    if isinstance(value, dict):
        return {key: catalog_data(item) for key, item in value.items() if key != "__class__"}
    if isinstance(value, list):
        return [catalog_data(item) for item in value]
    return value


def catalog_assets(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(document, dict) or document.get("__class__", TABLE_TYPE) != TABLE_TYPE:
        raise ValueError("清单不是 AssetBundleTable")
    bundles = document.get("BundleInfos")
    if not isinstance(bundles, list):
        raise ValueError("AssetBundleTable 缺少 BundleInfos")
    result: dict[str, list[dict[str, Any]]] = {}
    for bundle in bundles:
        if (not isinstance(bundle, dict) or not isinstance(bundle.get("BundleFileName"), str)
                or not bundle["BundleFileName"]):
            raise ValueError("BundleInfos 条目缺少 BundleFileName")
        # CN 6.1.0 libil2cpp.so 0x03F4BC38：BundleFileName + BundleExtension (.ab)。
        filename = bundle["BundleFileName"] + ".ab"
        assets = bundle.get("Assets")
        assets = [] if assets is None else assets
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise ValueError(f"{filename} 的 Assets 不是对象数组")
        for asset in assets:
            if any(asset.get(key) is not None and not isinstance(asset[key], str)
                   for key in ("ResPath", "AssetFullName")):
                raise ValueError(f"{filename} 的资源路径不是字符串")
        target = result.setdefault(filename, [])
        target.extend(asset for asset in assets if asset not in target)
    return result


def location(index: FileMap, entry: MappedFile) -> dict[str, Any]:
    return {**asdict(entry), "blockSize": index.blocks[entry.block]}


def prepare(root: Path, index_path: Path | None, listing: Path | None,
            list_only: bool, js_exporter: bool = False) -> tuple[list[BundleTask], dict[str, Any]]:
    index = None
    entries: dict[str, MappedFile] = {}
    metadata: dict[str, Any] = {"mode": "blk" if index_path else "ab", "planning": "asset-bundle-table"}
    if index_path:
        if not root.is_dir():
            raise ValueError("BLK 模式 --input 必须是直接包含 .blk 的目录")
        index = parse_file_map(resolve_index(index_path, root).read_bytes())
        entries = {entry.name: entry for entry in index.files}
    document = None
    if listing:
        document = read_manifest(listing)
        metadata["planning"] = "manifest"
    elif index:
        entry = entries.get(CATALOG_NAME)
        if entry is not None:
            raw_catalog, _ = BlockStore(index, root).read_file(entry)
            document = parse_catalog(raw_catalog)
    else:
        catalog_root = root if root.is_dir() else root.parent
        path = catalog_root / CATALOG_NAME
        if path.is_file():
            document = parse_catalog(path.read_bytes())
    if document is None:
        raise ValueError("缺少目录表，请提供 --list 或 AssetBundleXMLData.xml")
    if document is not None:
        metadata["table"] = document
        if not listing:
            metadata["planning"] = "asset-bundle-table"
    if list_only:
        if document is None:
            raise ValueError("缺少 AssetBundleXMLData.xml，无法生成目录表清单")
        return [], metadata

    catalog = catalog_assets(document) if document is not None else None
    if catalog is not None:
        tasks = []
        for bundle, all_assets in catalog.items():
            assets = [asset for asset in all_assets if script_path(asset)] if js_exporter else all_assets
            if root.is_file() and bundle != root.name:
                continue
            if js_exporter and not assets:
                continue
            mapped = None
            if index:
                if bundle not in entries:
                    raise ValueError(f"目录表 AB 不在当前 XMF 中：{bundle}")
                mapped = location(index, entries[bundle])
                filename = str(root)
            else:
                filename = str(inside(root, bundle)) if root.is_dir() else str(inside(root.parent, bundle))
            tasks.append(BundleTask(filename, bundle, location=mapped, assets=assets, js_exporter=js_exporter))
        if index:
            tasks.sort(key=lambda task: (task.location["block"], task.location["offset"]))
        metadata["candidateBundleCount"] = len(tasks)
        return tasks, metadata


_store: BlockStore | None = None


def load_bundle(task: BundleTask) -> str | bytes:
    global _store
    if task.location is None:
        return task.filename
    root = Path(task.filename)
    loc = task.location
    if _store is None or _store.root != root:
        _store = BlockStore(FileMap((2, 0, 0), {}, []), root)
    _store.index.blocks[loc["block"]] = loc["blockSize"]
    entry = MappedFile(**{key: loc[key] for key in MappedFile.__dataclass_fields__})
    data, _ = _store.read_file(entry)
    return unpack_unityfs(data).data

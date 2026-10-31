"""按 XMF 校验和拆分 BLK，输出文件直接沿用索引路径。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from itertools import groupby
from pathlib import Path

import UnityPy

from crypto import verify_signed_file
from file_map import parse_file_map
from resource_store import BlockStore
from unityfs import unpack_unityfs


def output_path(root: Path, name: str) -> Path:
    root = root.resolve()
    path = (root / name.replace("\\", "/")).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"输出路径越界：{name}")
    return path


def write_preserving(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"已有不同内容，不覆盖：{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(data)


def write_json(path: Path, document: dict) -> None:
    write_preserving(path, (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def decode_resource(data: bytes, name: str, signed: bool, mr0k: str) -> tuple[bytes, dict]:
    if signed:
        return verify_signed_file(data), {"format": "signed", "verification": "md5+rsa-sha1"}
    if not data.startswith(b"UnityFS\x00") and not name.lower().endswith(".ab"):
        return data, {"format": "raw", "verification": "md5"}
    if not data.startswith(b"UnityFS\x00"):
        raise ValueError("AB 文件不是 UnityFS")
    if mr0k == "keep":
        return data, {"format": "ab", "verification": "md5", "mr0k": "keep"}
    bundle = unpack_unityfs(data)
    environment = UnityPy.load(bundle.data)
    objects = environment.objects
    if not environment.files:
        raise ValueError("UnityPy 未读取到 Bundle")
    for obj in objects:
        if len(obj.get_raw_data()) != obj.byte_size:
            raise ValueError(f"Unity 对象数据截断：{obj.path_id}")
    return bundle.data, {"format": "ab", "verification": "md5+unityfs", "mr0k": "decrypt",
                         "objects": len(objects), "nodes": len(bundle.nodes), "compression": bundle.compression}


def run(args: argparse.Namespace) -> dict:
    index_bytes = args.index.read_bytes()
    index = parse_file_map(index_bytes)
    if args.list:
        listing = asdict(index)
        listing.update(block_count=len(index.blocks), file_count=len(index.files),
                       index_sha256=hashlib.sha256(index_bytes).hexdigest())
        path = args.output / f"{args.index.stem}.json"
        write_json(path, listing)
        print(f"索引包含 {len(index.blocks)} 个块、{len(index.files)} 个文件；清单：{path.resolve()}")
        return {"complete": True, "listing": str(path.resolve())}
    if args.root is None or not args.root.is_dir():
        raise ValueError("--root 必须是直接包含 .blk 文件的目录")
    signed = "pbstaticconfigure" in (args.index.stem.casefold(), args.root.name.casefold())
    report = {"version": list(index.version), "root": str(args.root.resolve()), "mr0k": args.mr0k,
              "index_sha256": hashlib.sha256(index_bytes).hexdigest(), "index_blocks": len(index.blocks),
              "index_files": len(index.files), "verified": 0, "failed": 0, "missing_files": 0,
              "missing_blocks": [], "mr0k_blocks": 0, "objects": 0, "files": []}
    compression_types: Counter = Counter()
    store = BlockStore(index, args.root)
    for block, entries_iter in groupby(sorted(index.files, key=lambda entry: entry.block), key=lambda entry: entry.block):
        entries = list(entries_iter)
        try:
            store.read_block(block)
        except FileNotFoundError:
            report["missing_files"] += len(entries)
            report["missing_blocks"].append({"block": block, "size": index.blocks[block], "files": len(entries)})
            continue
        except (OSError, ValueError) as error:
            report["failed"] += len(entries)
            report["files"].extend({"name": entry.name, "block": block, "status": "failed", "error": str(error)}
                                   for entry in entries)
            continue
        for entry in entries:
            record = {"name": entry.name, "block": block, "offset": entry.offset, "size": entry.size, "md5": entry.md5}
            try:
                data, origin = store.read_file(entry)
                record.update(origin=origin, source_sha256=hashlib.sha256(data).hexdigest())
                decoded, metadata = decode_resource(data, entry.name, signed, args.mr0k)
                record.update(metadata, decoded_size=len(decoded), decoded_sha256=hashlib.sha256(decoded).hexdigest())
                if not args.verify_only:
                    write_preserving(output_path(args.output, entry.name), decoded)
                record["status"] = "verified"
                report["verified"] += 1
                report["objects"] += metadata.get("objects", 0)
                compression = metadata.get("compression", [])
                report["mr0k_blocks"] += sum(item["type"] == 5 and item["compressed"] >= 0x10000 for item in compression)
                compression_types.update(item["type"] for item in compression)
            except Exception as error:
                record.update(status="failed", error=f"{type(error).__name__}: {error}")
                report["failed"] += 1
            report["files"].append(record)
        processed = report["verified"] + report["failed"]
        if processed and processed // 500 > (processed - len(entries)) // 500:
            print(f"已验证 {report['verified']}，失败 {report['failed']}，已检查块 {len(store.checked)}", flush=True)
    report["checked_blocks"] = len(store.checked)
    report["compression_types"] = dict(sorted(compression_types.items()))
    report["complete"] = report["failed"] == 0 and report["missing_files"] == 0
    write_json(args.output / "report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in ("files", "missing_blocks")},
                     ensure_ascii=False, indent=2))
    print(f"缺少 {len(report['missing_blocks'])} 个块；报告：{(args.output / 'report.json').resolve()}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True, help="索引 XMF 文件")
    parser.add_argument("--root", type=Path, help="直接包含 .blk 的目录，不是其父目录；--list 时可省略")
    parser.add_argument("--output", type=Path, default=Path("output"), help="解包或清单输出目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true", help="只验证并写报告，不导出资源")
    mode.add_argument("--list", action="store_true", help="反序列化 XMF 到 JSON，不读取 BLK")
    parser.add_argument("--mr0k", choices=("decrypt", "keep"), default="decrypt",
                        help="decrypt：解密并重建 AB；keep：保留原始 AB，只验证 MD5")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.list and args.root is None:
        parser.error("解包或验证时必须提供 --root BLK目录")
    try:
        return 0 if run(args)["complete"] else 1
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())

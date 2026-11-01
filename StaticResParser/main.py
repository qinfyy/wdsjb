"""读取 wd 的 PBStaticConfigure 解包内容，按客户端消息路由恢复 JSON。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from pb_config import ConfigSchema, inspect_wire


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = [ROOT.parent / "WDProtoDumper" / "output_pbconfig", ROOT.parent / "JsProtoDumper" / "output" / "pbconfig"]


def write_preserving(path: Path, data: bytes) -> None:
    """允许重复运行，但不覆盖已有的不同内容。"""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"输出已存在且内容不同：{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path: Path, document: object) -> None:
    write_preserving(path, (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def restore_file(path: Path, relative: Path, output: Path, schema: ConfigSchema,
                 signed: bool, verify_only: bool, message: str | None) -> dict[str, object]:
    raw = path.read_bytes()
    payload = raw
    if signed:
        # CN 6.1.0 libil2cpp.so 0x0603081C；已解包内容不得再次移除 0x80 字节。
        from Unpacker.crypto import verify_signed_file
        payload = verify_signed_file(raw)
    result: dict[str, object] = {
        "file": relative.as_posix(), "size": len(raw), "payloadSize": len(payload),
        "sha256": hashlib.sha256(raw).hexdigest(), "signed": signed,
    }
    if payload.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"{", b"[")):
        json.loads(payload.decode("utf-8-sig"))
        target = relative.with_suffix(".json")
        result.update(status="json", output=target.as_posix())
        if not verify_only:
            write_preserving(output / target, payload)
        return result
    descriptor = schema.route(relative.stem, message)
    if descriptor is not None:
        document, unknown = schema.decode(payload, descriptor)
        result.update(message=descriptor.full_name, status="partial" if unknown else "protobuf")
        if unknown:
            result["reason"] = "存在 schema 未识别的字段；未输出丢失字段的命名 JSON"
        else:
            schema.verify_group(relative.stem, document)
            target = relative.with_suffix(".json")
            result["output"] = target.as_posix()
            if not verify_only:
                write_json(output / target, document)
            return result
    else:
        result.update(status="unsupported", reason="当前 schema 没有对应根消息，未按相似类型猜测")
    result["preserved"] = relative.as_posix()
    if not verify_only:
        write_preserving(output / relative, payload)
    try:
        fields = inspect_wire(payload)
    except ValueError:
        result["format"] = "binary"
    else:
        result["format"] = "protobuf-wire"
        target = relative.with_suffix(".wire.json")
        result["wireOutput"] = target.as_posix()
        if not verify_only:
            write_json(output / target, {"schemaResolved": False, "fields": fields})
    return result


def run(args: argparse.Namespace) -> dict[str, object]:
    source, output = args.input.resolve(), args.output.resolve()
    if not source.exists():
        raise ValueError("输入路径不存在")
    if source == output or (source.is_dir() and output.is_relative_to(source)):
        raise ValueError("输出目录不能等于输入目录或位于输入目录内部")
    if args.message and not source.is_file():
        raise ValueError("--message 只用于单文件，不能对整个目录套用同一种消息")
    schema = ConfigSchema(args.schema or DEFAULT_SCHEMA)
    files = [source] if source.is_file() else sorted(source.rglob("*.bytes"))
    if not files:
        raise ValueError("没有找到 .bytes 配置文件")
    entries: list[dict[str, object]] = []
    for index, path in enumerate(files, 1):
        relative = Path(path.name) if source.is_file() else path.relative_to(source)
        try:
            entry = restore_file(path, relative, output, schema, args.signed, args.verify_only, args.message)
        except (OSError, ValueError) as error:
            entry = {"file": relative.as_posix(), "status": "failed", "reason": str(error)}
        entries.append(entry)
        if args.detailed_log or index % 1000 == 0 or index == len(files):
            print(f"[{index}/{len(files)}] {relative.as_posix()}：{entry['status']}")
    counts = Counter(str(entry["status"]) for entry in entries)
    report: dict[str, object] = {
        "version": "CN 6.1.0", "schemaSha256": schema.sha256,
        "schemas": [
            {"descriptor": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
             "sha256": digest}
            for path, digest in zip(schema.descriptor_paths, schema.descriptor_hashes)
        ],
        "verifyOnly": args.verify_only, "fileCount": len(entries),
        "counts": dict(counts), "files": entries,
    }
    # 报告是本次运行的状态；不清空输出，不改写已经导出的资源。
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="解包后的 .bytes 目录或单个文件")
    parser.add_argument("--output", type=Path, default=ROOT / "output", help="输出目录；不清空已有内容")
    parser.add_argument("--schema", type=Path, action="append", help="proto 目录、.proto 或 descriptor set (.pb)，可重复；默认使用配置的目录数组")
    parser.add_argument("--signed", action="store_true", help="输入仍含 RSA 签名时验签；已解包文件不要启用")
    parser.add_argument("--message", help="单文件显式指定消息名，不用于猜测未知 schema")
    parser.add_argument("--verify-only", action="store_true", help="只验证并写报告，不导出资源")
    parser.add_argument("--detailed-log", action="store_true", help="打印逐文件结果")
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    print("完成：" + json.dumps(report["counts"], ensure_ascii=False))
    counts = report["counts"]
    return 1 if isinstance(counts, dict) and any(counts.get(key, 0) for key in ("failed", "partial", "unsupported")) else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT.parent))
    raise SystemExit(main())

"""读取 wd 的 PBStaticConfigure 解包内容，按客户端消息路由恢复 JSON。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from lua_parser import LuaTask, is_lua_file, restore_lua, unluac_command
from pb_config import ConfigSchema
from protobuf_raw_parser import inspect_wire


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


def move_preserving(source: Path, target: Path) -> None:
    """移动临时文件；已有相同内容时只删除临时文件，不覆盖不同内容。"""
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise ValueError(f"输出已存在且内容不同：{target}")
        source.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def write_json(path: Path, document: object) -> None:
    write_preserving(path, (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def restore_file(path: Path, relative: Path, output: Path, schema: ConfigSchema,
                 signed: bool, verify_only: bool, message: str | None) -> dict[str, object]:
    raw = path.read_bytes()
    payload = raw
    if signed:
        # CN 6.1.0 libil2cpp.so 0x0603081C；已解包内容不得再次移除 0x80 字节。
        from UnPacker.crypto import verify_signed_file
        payload = verify_signed_file(raw)
    result: dict[str, object] = {
        "file": relative.as_posix(), "size": len(raw), "payloadSize": len(payload),
        "md5": hashlib.md5(raw).hexdigest(), "signed": signed,
    }
    if payload.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"{", b"[")):
        json.loads(payload.decode("utf-8-sig"))
        target = relative.with_suffix(".json")
        result.update(status="json", output=target.as_posix())
        if not verify_only:
            write_preserving(output / target, payload)
        return result
    descriptors = schema.route(relative.stem, message)
    if descriptors:
        try:
            decoded = schema.decode(payload, descriptors)
            if decoded.unknown_count == 0:
                schema.verify_group(relative.stem, decoded.document)
        except ValueError as error:
            result.update(status="failed", reason=str(error))
        else:
            unknown = decoded.unknown_count > 0
            result.update(message=decoded.descriptor.full_name, proto=decoded.descriptor.file.name,
                          status="partial" if unknown else "protobuf", decodedFieldCount=decoded.known_count,
                          unknownFieldCount=decoded.unknown_count)
            target = relative.with_suffix(".json")
            result["output"] = target.as_posix()
            if not verify_only:
                write_json(output / target, decoded.document)
            if not unknown:
                return result
            result["reason"] = f"已解析 {decoded.known_count} 个字段，仍有 {decoded.unknown_count} 个未知字段"
    else:
        result.update(status="unsupported", reason="当前 schema 没有对应根消息，未按相似类型猜测")
    result["preserved"] = relative.as_posix()
    if not verify_only:
        write_preserving(output / relative, payload)
    wire_document = inspect_wire(payload)
    result["format"] = "binary" if "leftOver" in wire_document else "protobuf-wire"
    target = relative.with_suffix(".wire.json")
    result["wireOutput"] = target.as_posix()
    if not verify_only:
        write_json(output / target, wire_document)
    return result


def run(args: argparse.Namespace) -> dict[str, object]:
    source, output = args.input.resolve(), args.output.resolve()
    if not source.exists():
        raise ValueError("输入路径不存在")
    if source == output or (source.is_dir() and output.is_relative_to(source)):
        raise ValueError("输出目录不能等于输入目录或位于输入目录内部")
    if args.message and not source.is_file():
        raise ValueError("--message 只用于单文件，不能对整个目录套用同一种消息")
    if args.lua_only and args.no_decrypt_lua:
        raise ValueError("--lua-only 不能与 --no-decrypt-lua 同时使用")
    if args.lua_workers < 1:
        raise ValueError("--lua-workers 必须是正整数")
    files = [source] if source.is_file() else sorted(
        path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in {".bytes", ".lua", ".luac"}
    )
    if not files:
        raise ValueError("没有找到 .bytes/.lua/.luac 资源文件")
    schema: ConfigSchema | None = None
    results: dict[Path, dict[str, object]] = {}
    lua_files: list[tuple[Path, Path]] = []
    pb_files: list[tuple[Path, Path]] = []
    for index, path in enumerate(files, 1):
        relative = Path(path.name) if source.is_file() else path.relative_to(source)
        try:
            if is_lua_file(path, args.signed):
                if not args.no_decrypt_lua:
                    lua_files.append((path, relative))
                    continue
                entry = {"file": relative.as_posix(), "status": "skipped_lua", "reason": "Lua 解密已关闭，未复制原始文件"}
            elif args.lua_only:
                continue
            else:
                pb_files.append((path, relative))
                continue
        except (OSError, ValueError) as error:
            entry = {"file": relative.as_posix(), "status": "failed", "reason": str(error)}
        results[path] = entry
        if args.detailed_log or index % 1000 == 0 or index == len(files):
            print(f"[{index}/{len(files)}] {relative.as_posix()}：{entry['status']}")
    if pb_files:
        schema = ConfigSchema(args.schema or DEFAULT_SCHEMA)
        for index, (path, relative) in enumerate(pb_files, 1):
            try:
                entry = restore_file(path, relative, output, schema, args.signed, args.verify_only, args.message)
            except (OSError, ValueError) as error:
                entry = {"file": relative.as_posix(), "status": "failed", "reason": str(error)}
            results[path] = entry
            if args.detailed_log or index % 1000 == 0 or index == len(pb_files):
                print(f"[{index}/{len(pb_files)}] {relative.as_posix()}：{entry['status']}")
    if lua_files:
        temp_lua = output / "temp-lua"
        try:
            try:
                command = unluac_command()
            except ValueError as error:
                for path, relative in lua_files:
                    results[path] = {"file": relative.as_posix(), "format": "lua", "status": "failed", "reason": str(error)}
            else:
                tasks = [LuaTask(path=path, relative=relative, command=command, signed=args.signed, output=output)
                         for path, relative in lua_files]
                workers = min(args.lua_workers, len(tasks))
                print(f"Lua：{len(tasks)} 个文件，{workers} 个工作进程")
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {executor.submit(restore_lua, task): task for task in tasks}
                    for index, future in enumerate(as_completed(futures), 1):
                        task = futures[future]
                        entry, source_path = future.result()
                        if source_path is not None:
                            try:
                                if args.verify_only:
                                    source_path.unlink(missing_ok=True)
                                else:
                                    move_preserving(source_path, output / str(entry["output"]))
                            except (OSError, ValueError) as error:
                                entry.update(status="failed", reason=str(error))
                                source_path.unlink(missing_ok=True)
                        results[task.path] = entry
                        if args.detailed_log or index % 100 == 0 or index == len(tasks):
                            print(f"[Lua {index}/{len(tasks)}] {task.relative.as_posix()}：{entry['status']}")
        finally:
            if temp_lua.exists():
                shutil.rmtree(temp_lua)
    entries = [results[path] for path in files if path in results]
    counts = Counter(str(entry["status"]) for entry in entries)
    report: dict[str, object] = {
        "version": "CN 6.1.0", "schemaMd5": schema.md5 if schema else None,
        "schemas": [
            {"descriptor": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
             "md5": digest}
            for path, digest in zip(schema.descriptor_paths, schema.descriptor_hashes)
        ] if schema else [],
        "verifyOnly": args.verify_only, "fileCount": len(entries),
        "decryptLua": not args.no_decrypt_lua, "luaOnly": args.lua_only, "scannedFileCount": len(files),
        "counts": dict(counts), "files": entries,
    }
    # 报告是本次运行的状态；不清空输出，不改写已经导出的资源。
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="解包后的 .bytes 目录或单个文件")
    parser.add_argument("--output", type=Path, default=ROOT / "output", help="输出目录；不清空已有内容")
    parser.add_argument("--schema", type=Path, action="append", help="proto 目录、.proto 或 descriptor set (.pb)，可重复；默认使用配置的目录数组")
    parser.add_argument("--signed", action="store_true", help="输入仍含 RSA 签名时验签；已解包文件不要启用")
    parser.add_argument("--message", help="单文件显式指定消息名，不用于猜测未知 schema")
    parser.add_argument("--verify-only", action="store_true", help="只验证并写报告，不导出资源")
    parser.add_argument("--detailed-log", action="store_true", help="打印逐文件结果")
    parser.add_argument("--no-decrypt-lua", action="store_true", default=False, help="跳过 Lua 解密和反编译，不复制原始 Lua")
    parser.add_argument("--lua-only", action="store_true", help="只处理 Lua，不加载 schema 或处理其他资源")
    parser.add_argument("--lua-workers", type=int, default=min(4, os.cpu_count() or 1), help="Lua 反编译并发进程数")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
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

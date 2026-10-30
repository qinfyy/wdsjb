"""从 ARM64 IL2CPP 的真实 Google.Protobuf 序列化输出恢复游戏网络协议。"""

import argparse
import json
import re
import shutil
import sys
import threading
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import frida


PACKAGE_NAME = "com.miHoYo.wd"
ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = ROOT / "FridaScript_arm64-v8a.js"
DEFAULT_OUTPUT = ROOT / "output" / "wd.proto"
DEFAULT_SCHEMA = ROOT / "output" / "wd_schema.json"
DEFAULT_ADB = Path("adb.exe")
DEFAULT_AGENT = ROOT.parent / "WDRedirector" / "frida-agent-arm64.so"
REMOTE_AGENT = "/data/local/tmp/re.frida.server/frida-agent-arm64.so"
PROTO_PACKAGE = "wd"
PROTO_INDENT = 4

PROTO_KEYWORDS = {
    "bool", "bytes", "double", "enum", "extend", "fixed32", "fixed64",
    "float", "group", "import", "int32", "int64", "map", "message",
    "oneof", "option", "optional", "package", "public", "repeated",
    "required", "reserved", "returns", "rpc", "service", "sfixed32",
    "sfixed64", "sint32", "sint64", "stream", "string", "syntax",
    "to", "uint32", "uint64", "weak",
}

MAP_KEYS = {
    "int32", "int64", "uint32", "uint64", "sint32", "sint64",
    "fixed32", "fixed64", "sfixed32", "sfixed64", "bool", "string",
}

WIRE_SCALARS = MAP_KEYS | {"bytes", "double", "float"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--attach", action="store_true", help="要求游戏已经运行并附加到游戏进程。")
    mode.add_argument("--spawn", action="store_true", help="启动游戏后再附加到游戏进程。")
    parser.add_argument("--package", default=PACKAGE_NAME, help="Android 应用包名。")
    parser.add_argument(
        "--namespace-prefix",
        default="Pb,Baseproto",
        help="筛选 CLR 命名空间，可用逗号分隔；默认导出 Pb 网络消息及 Baseproto 包头，传空字符串可包含配置消息。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 .proto 文件路径。")
    parser.add_argument("--schema-json", type=Path, default=DEFAULT_SCHEMA, help="原始运行时清单 JSON 路径。")
    parser.add_argument("--no-schema-json", action="store_true", help="不保存原始运行时清单 JSON。")
    parser.add_argument("--schema-input", type=Path, help="使用已保存的清单生成文件，不附加 Android 进程。")
    parser.add_argument("--realm", choices=("auto", "native", "emulated"), default="auto", help="x86_64 模拟器自动选择 emulated。")
    parser.add_argument("--device", help="Frida 设备 ID，默认使用 USB/模拟器设备。")
    parser.add_argument("--adb", type=Path, default=DEFAULT_ADB, help="ADB 可执行文件，默认从 PATH 查找 adb.exe。")
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT, help="与 Frida server 同版本的 ARM64 agent。")
    parser.add_argument("--messages", default="", help="只探测指定消息，用逗号分隔 CLR 全名或类名。")
    parser.add_argument("--inspect", action="store_true", help="只检查运行时消息和 descriptor 是否存在。")
    parser.add_argument("--allow-partial", action="store_true", help="允许输出存在明确诊断的部分结果；默认拒绝不完整 schema。")
    return parser.parse_args()


def proto_identifier(value: str, fallback: str) -> str:
    value = value.replace("global::", "")
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not value:
        value = fallback
    if value[0].isdigit():
        value = "_" + value
    if value in PROTO_KEYWORDS:
        value += "_"
    return value


def canonical_type(value: Any) -> str:
    return str(value or "").replace("global::", "").replace("+", "/").strip()


def integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def merge_records(raw_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        full_name = canonical_type(raw.get("full_name"))
        if kind not in {"message", "enum"} or not full_name:
            continue
        # 保留采集器确认的协议枚举，包括嵌套 CmdId。
        if kind == "enum" and not raw.get("is_proto_contract", False):
            continue
        record = dict(raw)
        record["full_name"] = full_name
        record["namespace"] = str(raw.get("namespace") or "")
        record["name"] = str(raw.get("name") or full_name.rsplit("/", 1)[-1].rsplit(".", 1)[-1])
        parent = canonical_type(raw.get("declaring_full_name"))
        record["declaring_full_name"] = parent or None
        member_key = "fields" if kind == "message" else "values"
        record[member_key] = list(raw.get(member_key) or [])
        previous = records.get(full_name)
        if previous is None:
            records[full_name] = record
            continue
        previous_key = "fields" if previous["kind"] == "message" else "values"
        previous_score = (not previous.get("extraction_failed", False), len(previous.get(previous_key, [])))
        record_score = (not record.get("extraction_failed", False), len(record.get(member_key, [])))
        if record_score > previous_score:
            records[full_name] = record
    return records


class ProtoRenderer:
    def __init__(self, records: dict[str, dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
        self.records = records
        self.warnings = warnings
        self.parents: dict[str, str | None] = {}
        self.children: dict[str | None, list[str]] = defaultdict(list)
        self.names: dict[str, str] = {}
        self.type_paths: dict[str, str] = {}
        self.type_full_names: dict[str, str] = {}
        self.enum_members: dict[str, list[tuple[dict[str, Any] | None, str]]] = {}
        self.root_names: set[str] = set()
        self.stubs: dict[str, dict[str, Any]] = {}
        self.stub_paths: dict[str, str] = {}
        self.diagnostics: list[str] = []
        self.build_tree()

    def build_tree(self) -> None:
        for full_name, record in self.records.items():
            parent = record.get("declaring_full_name")
            while parent and parent not in self.records and "/" in parent:
                parent = parent.rsplit("/", 1)[0]
            if parent not in self.records or self.records[parent]["kind"] != "message":
                parent = None
            self.parents[full_name] = parent
            self.children[parent].append(full_name)

        for parent, names in self.children.items():
            names.sort(key=lambda name: (
                self.records[name]["namespace"].lower(),
                self.records[name]["name"].lower(),
                name.lower(),
            ))
            used: set[str] = set()
            for full_name in names:
                base = proto_identifier(self.records[full_name]["name"], "Type")
                name = base
                suffix = 2
                while name in used:
                    name = f"{base}__{suffix}"
                    suffix += 1
                used.add(name)
                self.names[full_name] = name
                if parent is None:
                    self.root_names.add(name)

        # 仅处理嵌套类型与字段的名称冲突，不因枚举成员同名调整类型名。
        for parent, names in self.children.items():
            field_names = {
                proto_identifier(
                    str(field.get("wire_name") or field.get("name") or "field"),
                    "field",
                )
                for field in (self.records[parent].get("fields", []) if parent else [])
            }
            used = {self.names[full_name] for full_name in names}
            for full_name in names:
                current = self.names[full_name]
                if current not in field_names:
                    continue
                suffix_name = "" if self.records[full_name]["kind"] == "enum" else "Message"
                base = proto_identifier(current + suffix_name, "Type")
                replacement = base
                suffix = 2
                while replacement in used or replacement in field_names:
                    replacement = f"{base}__{suffix}"
                    suffix += 1
                used.remove(current)
                used.add(replacement)
                self.names[full_name] = replacement
                self.diagnostics.append(
                    f"{self.records[full_name]['kind']}类型 {full_name} 重命名为 {replacement}，"
                    "因为清理后的名称与字段名称完全冲突"
                )
        self.root_names = {self.names[name] for name in self.children.get(None, [])}

        def path_for(full_name: str) -> str:
            parent = self.parents[full_name]
            if parent is None:
                return self.names[full_name]
            return path_for(parent) + "." + self.names[full_name]

        for full_name in self.records:
            path = "." + PROTO_PACKAGE + "." + path_for(full_name)
            canonical_name = canonical_type(full_name)
            relative_path = path.removeprefix("." + PROTO_PACKAGE + ".")
            self.type_paths[canonical_name] = relative_path
            self.type_full_names[canonical_name] = full_name
            # IL2CPP 可能使用 '/' 或 '.' 表示嵌套 CLR 类型。两种写法都保留，
            # 这样泛型元素类型可以正常解析，不必回退到占位类型。
            dotted_name = canonical_name.replace("/", ".")
            self.type_paths[dotted_name] = relative_path
            self.type_full_names[dotted_name] = full_name
        self.build_enum_members()

    @staticmethod
    def ordered_enum_values(record: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            record.get("values", []),
            # 如果存在真正的零值 CLR 成员，优先保留它；负值和正值成员继续使用确定性排序。
            key=lambda item: (
                integer(item.get("value")) != 0,
                integer(item.get("value")),
                str(item.get("name") or ""),
            ),
        )

    def build_enum_members(self) -> None:
        # 非别名枚举仅给重名成员添加枚举名前缀，别名枚举保留原有命名。
        used_by_scope: dict[str | None, set[str]] = defaultdict(set)
        for full_name, parent in self.parents.items():
            if self.records[full_name]["kind"] == "message":
                used_by_scope[parent].add(self.names[full_name])
                used_by_scope[full_name].update(
                    proto_identifier(str(field.get("wire_name") or field.get("name") or "field"), "field")
                    for field in self.records[full_name].get("fields", [])
                )

        enum_names = sorted(
            (name for name, record in self.records.items() if record["kind"] == "enum"),
            key=lambda name: (
                self.parents[name] or "",
                self.records[name]["namespace"].lower(),
                self.names[name].lower(),
                name.lower(),
            ),
        )
        for full_name in enum_names:
            record = self.records[full_name]
            used = used_by_scope[self.parents[full_name]]
            values = self.ordered_enum_values(record)
            numeric_values = [integer(value.get("value")) for value in values]
            allow_alias = len(set(numeric_values)) != len(numeric_values)
            members: list[tuple[dict[str, Any] | None, str]] = []
            for value in values:
                source_name = str(value.get("name") or "UNKNOWN")
                base = proto_identifier(source_name, "UNKNOWN")
                if base == self.names[full_name]:
                    base += "Member"
                if base in used and not allow_alias:
                    base = self.names[full_name] + "_" + base
                emitted = self.unique_name(base, used, "UNKNOWN")
                members.append((value, emitted))
            self.enum_members[full_name] = members
            if not any(integer(value.get("value")) == 0 for value in values):
                zero_name = self.unique_name("UNSPECIFIED", used, "UNSPECIFIED")
                members.insert(0, (None, zero_name))

    @staticmethod
    def unique_name(value: str, used: set[str], fallback: str) -> str:
        base = proto_identifier(value, fallback)
        result = base
        suffix = 2
        while result in used:
            result = f"{base}_{suffix}"
            suffix += 1
        used.add(result)
        return result

    @staticmethod
    def unique_field_name(value: str, used: set[str], fallback: str) -> str:
        base = proto_identifier(value, fallback)
        result = base
        suffix = 2
        while result in used:
            result = f"{base}__{suffix}"
            suffix += 1
        used.add(result)
        return result

    def stub_for(self, raw_name: str, is_enum: bool) -> str:
        key = canonical_type(raw_name) or "UnknownType"
        existing = self.stub_paths.get(key)
        if existing is not None:
            return existing
        leaf = key.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        base = proto_identifier(leaf, "UnknownType")
        used = self.root_names | {item["name"] for item in self.stubs.values()}
        name = base
        suffix = 2
        while name in used:
            name = f"{base}__{suffix}"
            suffix += 1
        self.stubs[key] = {"name": name, "is_enum": is_enum}
        self.stub_paths[key] = name
        self.diagnostics.append(f"未解析的 CLR 类型 {key} 已按 {name} 占位类型输出")
        return self.stub_paths[key]

    def type_reference(self, candidate: str, owner_full_name: str | None) -> str | None:
        path = self.type_paths.get(candidate)
        target = self.type_full_names.get(candidate)
        if path is None or target is None:
            return None
        if owner_full_name:
            owner_path = self.type_paths.get(canonical_type(owner_full_name))
            if owner_path and path.startswith(owner_path + "."):
                # 当前消息的子类型可以使用局部引用。
                return path[len(owner_path) + 1:]
        return path

    def resolve_type(
        self,
        raw_type: str,
        field: dict[str, Any],
        owner_full_name: str | None,
    ) -> tuple[str, str | None]:
        raw_type = canonical_type(raw_type)
        if not raw_type:
            return self.stub_for("UnknownType", bool(field.get("is_enum"))), "CLR 类型为空"
        if raw_type == "map":
            key, key_note = self.resolve_type(str(field["map_key_type"]), {}, owner_full_name)
            value, value_note = self.resolve_type(str(field["map_value_type"]), field, owner_full_name)
            if key not in MAP_KEYS:
                raise ValueError(f"无效的 map key 类型：{key}")
            return f"map<{key}, {value}>", key_note or value_note
        if field.get("repeated"):
            element_field = dict(field, repeated=False)
            element, note = self.resolve_type(raw_type, element_field, owner_full_name)
            return f"repeated {element}", note
        if raw_type in WIRE_SCALARS:
            return raw_type, None
        metadata_name = canonical_type(field.get("type_full_name"))
        for candidate in (metadata_name, raw_type):
            reference = self.type_reference(candidate, owner_full_name)
            if reference is not None:
                return reference, None
        return (
            self.stub_for(metadata_name or raw_type, bool(field.get("is_enum"))),
            "运行时类型元数据不可用",
        )

    def render_enum(self, full_name: str, indent: int) -> list[str]:
        record = self.records[full_name]
        pad = " " * indent
        lines = [f"{pad}// Enum {full_name}", f"{pad}enum {self.names[full_name]} {{"]
        values = self.ordered_enum_values(record)
        numeric_values = [integer(item.get("value")) for item in values]
        member_pad = " " * (indent + PROTO_INDENT)
        if numeric_values and len(set(numeric_values)) != len(numeric_values):
            lines.append(f"{member_pad}option allow_alias = true;")
        for value, name in self.enum_members[full_name]:
            if value is None:
                lines.append(f"{member_pad}{name} = 0;")
                continue
            source_name = str(value.get("name") or "UNKNOWN")
            line = f"{member_pad}{name} = {integer(value.get('value'))};"
            if name != source_name:
                line += " // CLR 枚举成员：" + source_name
            lines.append(line)
        lines.append(f"{pad}}}")
        return lines

    def render_fields(self, record: dict[str, Any], indent: int) -> list[str]:
        pad = " " * indent
        lines: list[str] = []
        used_names: set[str] = set()
        used_tags: set[int] = set()
        fields = sorted(
            record.get("fields", []),
            key=lambda item: (integer(item.get("tag")), str(item.get("name") or "")),
        )
        for field in fields:
            tag = integer(field.get("tag"))
            source_name = str(field.get("wire_name") or field.get("name") or "field")
            if tag <= 0 or tag > 536_870_911 or 19_000 <= tag <= 19_999 or tag in used_tags:
                raise ValueError(f"{record['full_name']}.{source_name} 的字段编号无效或重复：{tag}")
            used_tags.add(tag)
            field_type, note = self.resolve_type(
                str(field.get("type") or ""),
                field,
                str(record.get("full_name") or "") or None,
            )
            name = self.unique_field_name(source_name, used_names, "field")
            comments: list[str] = []
            if name != source_name:
                comments.append("CLR 名称：" + source_name)
            if note:
                comments.append(note)
            line = f"{pad}{field_type} {name} = {tag};"
            if field.get("repeated") and (field.get("is_enum") or str(field.get("type")) in WIRE_SCALARS - {"string", "bytes"}):
                line = f"{pad}{field_type} {name} = {tag} [packed = {'true' if field.get('packed') else 'false'}];"
            if comments:
                line += " // " + "; ".join(comments)
            lines.append(line)
        if record.get("extraction_failed"):
            lines.append(f"{pad}// 运行时成员提取失败，请检查原始 schema JSON。")
        return lines

    def render_message(self, full_name: str, indent: int) -> list[str]:
        record = self.records[full_name]
        pad = " " * indent
        lines = [f"{pad}// Class {full_name}", f"{pad}message {self.names[full_name]} {{"]
        nested = self.children.get(full_name, [])
        nested_enums = [name for name in nested if self.records[name]["kind"] == "enum"]
        nested_messages = [name for name in nested if self.records[name]["kind"] == "message"]
        for child in nested_enums:
            lines.extend(self.render_enum(child, indent + PROTO_INDENT))
            lines.append("")
        fields = self.render_fields(record, indent + PROTO_INDENT)
        lines.extend(fields)
        if fields and nested_messages:
            lines.append("")
        for index, child in enumerate(nested_messages):
            lines.extend(self.render_message(child, indent + PROTO_INDENT))
            if index + 1 != len(nested_messages):
                lines.append("")
        lines.append(f"{pad}}}")
        return lines

    def render(self) -> str:
        lines = [
            "// WDProtoDumper, Written by Cyt\n",
            'syntax = "proto3";',
            "",
            "package " + PROTO_PACKAGE + ";",
            "",
        ]
        groups: dict[str, list[str]] = defaultdict(list)
        for full_name in self.children.get(None, []):
            groups[self.records[full_name]["namespace"]].append(full_name)
        for namespace in sorted(groups, key=str.lower):
            lines.append(f"// Namespace {namespace or '<global>'}")
            root_names = groups[namespace]
            for full_name in root_names:
                if self.records[full_name]["kind"] == "enum":
                    lines.extend(self.render_enum(full_name, 0))
                    lines.append("")
            for full_name in root_names:
                if self.records[full_name]["kind"] == "message":
                    lines.extend(self.render_message(full_name, 0))
                    lines.append("")
        if self.stubs:
            lines.append("// 以下类型未收集，仅在 --allow-partial 模式下允许占位。")
            for raw_name, stub in sorted(self.stubs.items(), key=lambda item: item[1]["name"].lower()):
                lines.append(f"// CLR 引用：{raw_name}")
                if stub["is_enum"]:
                    lines.append(f"enum {stub['name']} {{")
                    lines.append(
                        " " * PROTO_INDENT
                        + f"{stub['name']}_UNSPECIFIED = 0;"
                    )
                    lines.append("}")
                else:
                    lines.append(f"message {stub['name']} {{")
                    lines.append("}")
                lines.append("")
        if self.diagnostics:
            lines.append("// 生成诊断信息：")
            for diagnostic in sorted(set(self.diagnostics)):
                lines.append("// " + diagnostic)
            lines.append("")
        if self.warnings:
            lines.append("// 运行时提取警告已保存在 JSON 清单中。")
        return "\n".join(lines).rstrip() + "\n"


def running_pid(device: Any, package: str, adb_path: Path) -> int | None:
    # Android 的应用 PID 可能指向 :PushService，优先精确查询主进程。
    adb_executable = shutil.which(str(adb_path))
    if adb_executable:
        result = subprocess.run([adb_executable, "-s", device.id, "shell", "pidof", package],
                                capture_output=True, text=True, timeout=15)
        pids = result.stdout.split()
        return int(pids[0]) if result.returncode == 0 and pids and pids[0].isdecimal() else None
    for application in device.enumerate_applications():
        if application.identifier == package and application.pid and application.pid > 0:
            return application.pid
    return None


BRIDGE_SCRIPT = r"""
'use strict';
const bridge = Process.getModuleByName('libnativebridge.so');
const create = new NativeFunction(bridge.getExportByName('NativeBridgeCreateNamespace'), 'pointer', ['pointer', 'pointer', 'pointer', 'uint64', 'pointer', 'pointer']);
const address = bridge.getExportByName('NativeBridgeLoadLibrary');
const original = new NativeFunction(address, 'pointer', ['pointer', 'int']);
const loadExt = new NativeFunction(bridge.getExportByName('NativeBridgeLoadLibraryExt'), 'pointer', ['pointer', 'int', 'pointer']);
const directory = '/data/local/tmp/re.frida.server';
const ns = create(Memory.allocUtf8String('wd-proto-emulated'), Memory.allocUtf8String(directory),
    Memory.allocUtf8String(directory + ':/system/lib64/arm64:/system_ext/lib64/arm64'), 0,
    Memory.allocUtf8String(directory + ':/system'), ptr(0));
if (ns.isNull()) throw new Error('NativeBridgeCreateNamespace 返回空指针');
const replacement = new NativeCallback(function (path, flags) {
    if (path.readCString() === directory + '/frida-agent-arm64.so') return loadExt(path, flags, ns);
    return original(path, flags);
}, 'pointer', ['pointer', 'int']);
Interceptor.replace(address, replacement);
send({event: 'bridge-ready'});
"""


def collect_runtime_inventory(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not SCRIPT_PATH.is_file():
        raise FileNotFoundError(f"找不到 Frida 脚本：{SCRIPT_PATH}")
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    done: dict[str, Any] = {}
    errors: list[str] = []
    complete = threading.Event()
    bridge_ready = threading.Event()
    scripts: list[Any] = []
    sessions: list[Any] = []

    def on_message(message: dict[str, Any], _data: bytes | None) -> None:
        if message.get("type") != "send":
            errors.append(str(message.get("stack") or message.get("description") or message))
            complete.set()
            bridge_ready.set()
            return
        payload = message.get("payload", {})
        event = payload.get("event")
        if event == "bridge-ready":
            bridge_ready.set()
        elif event == "started":
            done["inspection"] = payload
            print(f"ARM64 运行时：类型 {payload['classes']}，消息 {payload['messages']}，"
                  f"descriptor 类型 {len(payload['descriptor_types'])}", flush=True)
            print("IMessage 方法：" + ", ".join(payload["imessage_methods"]), flush=True)
        elif event == "dumping":
            index = int(payload.get("index", 0))
            if index <= 3 or index % 50 == 0:
                print(f"[{index}/{payload.get('total')}] {payload.get('full_name')}", flush=True)
        elif event == "record":
            records.append(payload)
        elif event == "command":
            commands.append(payload)
        elif event == "warning":
            warnings.append(payload)
            detail = str(payload.get("error", "")).splitlines()[0]
            print(f"[警告] {payload.get('full_name')}.{payload.get('field')}：{detail}", flush=True)
        elif event == "error":
            errors.append(str(payload.get("error")))
            complete.set()
        elif event == "done":
            done.update(payload)
            complete.set()

    def on_detached(reason: str, crash: Any) -> None:
        if not complete.is_set():
            errors.append(f"游戏连接断开：{reason}，{crash}")
            complete.set()

    device = frida.get_device(args.device, timeout=15) if args.device else frida.get_usb_device(timeout=15)
    realm = args.realm
    if realm == "auto":
        realm = "emulated" if device.query_system_parameters().get("arch") in {"x64", "x86_64", "ia32"} else "native"
    if realm == "emulated":
        adb_executable = shutil.which(str(args.adb))
        if not adb_executable or not args.agent.is_file():
            raise FileNotFoundError(f"需要 ADB 和 ARM64 agent：{args.adb}，{args.agent}")
        adb = [adb_executable, "-s", device.id]
        subprocess.run(adb + ["shell", "mkdir", "-p", str(Path(REMOTE_AGENT).parent).replace("\\", "/")], check=True)
        subprocess.run(adb + ["push", str(args.agent), REMOTE_AGENT], check=True)
        subprocess.run(adb + ["shell", "chmod", "0644", REMOTE_AGENT], check=True)
    pid = running_pid(device, args.package, args.adb)
    spawned = False
    if args.attach and pid is None:
        raise RuntimeError(f"找不到正在运行的应用：{args.package}")
    if args.spawn or pid is None:
        if realm == "emulated":
            # Native Bridge 不需要早期挂起；ADB 启动避免 MuMu 的 Frida spawn 超时。
            resolved = subprocess.run(adb + ["shell", "cmd", "package", "resolve-activity", "--brief",
                                            "-a", "android.intent.action.MAIN",
                                            "-c", "android.intent.category.LAUNCHER", args.package],
                                      check=True, capture_output=True, text=True, timeout=15)
            components = [line.strip() for line in resolved.stdout.splitlines()
                          if line.strip().startswith(args.package + "/")]
            if not components:
                raise RuntimeError(f"找不到应用启动 Activity：{args.package}")
            subprocess.run(adb + ["shell", "am", "start", "-W", "-n", components[-1]],
                           check=True, capture_output=True, text=True, timeout=60)
            time.sleep(8)
            pid = running_pid(device, args.package, args.adb)
        else:
            pid = device.spawn([args.package])
            spawned = True
    if pid is None:
        raise RuntimeError(f"无法找到或启动应用：{args.package}")

    try:
        if realm == "emulated":
            native_session = device.attach(pid, realm="native")
            sessions.append(native_session)
            native_session.on("detached", on_detached)
            bridge_script = native_session.create_script(BRIDGE_SCRIPT)
            bridge_script.on("message", on_message)
            scripts.append(bridge_script)
            bridge_script.load()
            if not bridge_ready.wait(15) or errors:
                raise RuntimeError("Native Bridge 初始化失败：" + " | ".join(errors))
            session = device.attach(pid, realm="emulated", emulated_agent_path=REMOTE_AGENT)
        else:
            session = device.attach(pid, realm="native")
        sessions.append(session)
        session.on("detached", on_detached)
        script = session.create_script(SCRIPT_PATH.read_text(encoding="utf-8"))
        script.on("message", on_message)
        scripts.append(script)
        script.load()
        script.post({"type": "start", "payload": {
            "namespacePrefix": args.namespace_prefix,
            "messageFilter": args.messages,
            "inspectOnly": args.inspect,
        }})
        if spawned and realm == "native":
            device.resume(pid)
        print(f"PID={pid}，Realm={realm}，开始 Google.Protobuf 恢复", flush=True)
        complete.wait()
    finally:
        for script in reversed(scripts):
            try:
                script.unload()
            except frida.InvalidOperationError:
                pass
        for session in reversed(sessions):
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass

    done["commands"] = commands
    if errors:
        partial_path = args.schema_json.with_name("wd_schema.partial.json")
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_text(json.dumps({"completed": done, "warnings": warnings,
                                           "records": records, "errors": errors}, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        raise RuntimeError("Frida 导出失败：" + " | ".join(errors))
    if not done.get("engine"):
        raise RuntimeError("没有收到运行时完成事件")
    if not records and not args.inspect:
        raise RuntimeError("运行时没有返回 protobuf 消息")
    return records, warnings, done


def load_inventory(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise ValueError(f"schema 清单无效：{path}")
    warnings = document.get("warnings", [])
    completed = document.get("completed", {"source": str(path)})
    if not isinstance(warnings, list) or not isinstance(completed, dict):
        raise ValueError(f"schema 清单无效：{path}")
    return document["records"], warnings, completed


def main() -> int:
    args = parse_args()

    if args.schema_input:
        source_path = args.schema_input.resolve()
        raw_records, warnings, completed = load_inventory(source_path)
        print(f"正在使用已保存的运行时清单生成文件：{source_path}", flush=True)
    else:
        raw_records, warnings, completed = collect_runtime_inventory(args)

    if args.inspect:
        print(json.dumps(completed, ensure_ascii=False, indent=2), flush=True)
        return 0

    records = merge_records(raw_records)
    if not records:
        raise RuntimeError("没有收集到可用的 protobuf 记录")

    renderer = ProtoRenderer(records, warnings)
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proto_text = renderer.render()

    if not args.no_schema_json and not args.schema_input:
        schema_path = args.schema_json.resolve()
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(
            json.dumps(
                {
                    "completed": completed,
                    "warnings": warnings,
                    "records": [records[name] for name in sorted(records)],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    failed = [name for name, record in records.items() if record.get("extraction_failed")]
    if not args.allow_partial and (failed or renderer.stubs or warnings):
        raise RuntimeError(f"恢复不完整：失败消息 {len(failed)}，缺失类型 {len(renderer.stubs)}，警告 {len(warnings)}；详见 schema JSON")
    output_path.write_text(proto_text, encoding="utf-8")
    commands = completed.get("commands", [])
    if commands:
        command_path = output_path.with_name("CmdIds.txt")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for command in commands:
            grouped[str(command["namespace"])].append(command)
        command_path.write_text("\n\n".join(
            ";namespace " + namespace + "\n" + "\n".join(
                f"{item['name']} = {item['cmd_id']}" for item in sorted(items, key=lambda x: (x["cmd_id"], x["name"]))
            ) for namespace, items in sorted(grouped.items())
        ) + "\n", encoding="utf-8")

    message_count = sum(record["kind"] == "message" for record in records.values())
    enum_count = sum(record["kind"] == "enum" for record in records.values())
    print(
        f"已写入 {output_path}（消息 {message_count} 个，枚举 {enum_count} 个，"
        f"运行时警告 {len(warnings)} 个，占位类型 {len(renderer.stubs)} 个）",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1)

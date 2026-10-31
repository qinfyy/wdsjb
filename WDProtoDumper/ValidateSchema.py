"""编译恢复的 proto，并用独立的 Google.Protobuf 实现解析全部运行时样本。"""

import argparse
import json
import runpy
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.descriptor import FieldDescriptor

ROOT = Path(__file__).resolve().parent
DEFAULT_PROTOC = ROOT.parent / "WDSniffer" / "protoc" / "protoc.exe"
if not DEFAULT_PROTOC.is_file():
    DEFAULT_PROTOC = ROOT.parent / "BH2Sniffer" / "protoc" / "protoc.exe"
SAMPLE_STRING = "WD_PROTO_SAMPLE"
DUMPER = runpy.run_path(str(ROOT / "ProtoDumper_arm64-v8a.py"))
ProtoRenderer = DUMPER["ProtoRenderer"]
merge_records = DUMPER["merge_records"]


def expected_value(field: FieldDescriptor) -> Any:
    if field.type == FieldDescriptor.TYPE_MESSAGE:
        return None
    if field.type == FieldDescriptor.TYPE_ENUM:
        return 1
    if field.type == FieldDescriptor.TYPE_BOOL:
        return True
    if field.type == FieldDescriptor.TYPE_STRING:
        return SAMPLE_STRING
    if field.type == FieldDescriptor.TYPE_BYTES:
        return SAMPLE_STRING.encode("ascii")
    if field.type in {FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE}:
        return 12.5
    if field.type in {FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64,
                      FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
                      FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64}:
        return -37
    return 37


def validate(schema_path: Path, proto_path: Path, protoc: Path) -> dict[str, Any]:
    document = json.loads(schema_path.read_text(encoding="utf-8"))
    if document.get("warnings") or document["completed"].get("failed_messages"):
        raise ValueError("清单包含运行时失败，不能作为完整协议验证")
    records = merge_records(document["records"])
    descriptor_path = proto_path.with_suffix(".pb")
    subprocess.run([str(protoc), f"--proto_path={proto_path.parent}",
                    f"--descriptor_set_out={descriptor_path}", proto_path.name], check=True,
                   cwd=proto_path.parent)
    descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(descriptor_path.read_bytes())
    proto_descriptor = next(file for file in descriptor_set.file if file.name == proto_path.name)
    renderer = ProtoRenderer(records, [], package=proto_descriptor.package)
    renderer.render()
    if renderer.stubs:
        raise ValueError("清单存在缺失类型")
    pool = descriptor_pool.DescriptorPool()
    for file in descriptor_set.file:
        pool.Add(file)
    statistics: Counter[str] = Counter()
    failures: list[str] = []
    command_values: dict[str, int] = {}
    for full_name, record in records.items():
        generated_name = proto_descriptor.package + "." + renderer.type_paths[full_name]
        if record["kind"] == "enum":
            descriptor = pool.FindEnumTypeByName(generated_name)
            expected = {name: int(value["value"]) if value is not None else 0
                        for value, name in renderer.enum_members[full_name]}
            if {v.name: v.number for v in descriptor.values} != expected:
                failures.append(full_name + ": 枚举名称/数值不匹配")
            statistics["enums"] += 1
            if record["name"] == "CmdId":
                statistics["cmd_id_enums"] += 1
                owner = renderer.parents[full_name]
                values = [value for value in record["values"] if value["name"] in {"CmdId", "CMD_ID"}]
                if owner is not None and len(values) == 1:
                    if owner in command_values:
                        failures.append(owner + ": 存在多个 CmdId 枚举")
                    command_values[owner] = int(values[0]["value"])
            continue
        descriptor = pool.FindMessageTypeByName(generated_name)
        message_class = message_factory.GetMessageClass(descriptor)
        statistics["messages"] += 1
        fields = record.get("fields", [])
        if set(descriptor.fields_by_number) != {f["tag"] for f in fields}:
            failures.append(full_name + ": descriptor 字段编号不匹配")
        used_names: set[str] = set()
        for sample in sorted(fields, key=lambda f: (f["tag"], f["name"])):
            field = descriptor.fields_by_number[sample["tag"]]
            expected_name = renderer.unique_field_name(sample["wire_name"], used_names, "field")
            try:
                if field.name != expected_name:
                    raise ValueError("字段名称不匹配")
                message = message_class.FromString(bytes.fromhex(sample["sample_hex"]))
                if sample["tag"] not in {f.number for f, _ in message.ListFields()}:
                    raise ValueError("样本字段未被识别，可能存在 wire 类型错误")
                actual = getattr(message, field.name)
                if sample["type"] == "map":
                    if len(actual) != 1:
                        raise ValueError("map 样本不是单项")
                    key_descriptor = field.message_type.fields_by_number[1]
                    value_descriptor = field.message_type.fields_by_number[2]
                    key = expected_value(key_descriptor)
                    if key not in actual:
                        raise ValueError("map key 样本值错误")
                    expected = expected_value(value_descriptor)
                    if expected is not None and actual[key] != expected:
                        raise ValueError("map value 样本值错误")
                    statistics["map_fields"] += 1
                else:
                    if sample.get("repeated"):
                        if len(actual) != 1:
                            raise ValueError("repeated 样本不是单项")
                        actual = actual[0]
                        statistics["repeated_fields"] += 1
                        if field.is_packed != sample["packed"]:
                            raise ValueError("packed 设置不匹配")
                    expected = expected_value(field)
                    if expected is not None and actual != expected:
                        raise ValueError(f"样本值不匹配：{actual!r} != {expected!r}")
                statistics["field_samples"] += 1
            except Exception as error:
                failures.append(full_name + "." + sample["name"] + ": " + str(error))
    commands = document["completed"].get("commands", [])
    if commands:
        for command in commands:
            if command_values.get(command["full_name"]) != int(command["cmd_id"]):
                failures.append(command["full_name"] + ": CmdId 枚举缺失或与命令表数值不一致")
        command_path = proto_path.with_name("CmdIds.txt")
        expected_commands = {(item["namespace"], item["name"]): int(item["cmd_id"]) for item in commands}
        if not command_path.is_file():
            failures.append("缺少独立命令表：" + str(command_path))
        else:
            actual_commands: dict[tuple[str, str], int] = {}
            namespace = ""
            for line in command_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith(";namespace "):
                    namespace = line.removeprefix(";namespace ")
                    continue
                name, separator, value = line.partition(" = ")
                try:
                    if not separator or (namespace, name) in actual_commands:
                        raise ValueError("无效或重复的命令条目")
                    actual_commands[(namespace, name)] = int(value)
                except ValueError:
                    failures.append("命令表条目无效：" + line)
            if actual_commands != expected_commands:
                failures.append("CmdIds.txt 与运行时命令表不一致")
        statistics["cmd_ids"] = len(commands)
    result: dict[str, Any] = dict(statistics)
    result["failures"] = failures
    result["protoc_compiled"] = True
    result["schema"] = str(schema_path)
    result["proto"] = str(proto_path)
    report = proto_path.with_name(proto_path.stem + "_validation.json")
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise ValueError(f"独立样本验证失败 {len(failures)} 项，详见 {report}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=ROOT / "output" / "wd_schema.json")
    parser.add_argument("--proto", type=Path, default=ROOT / "output" / "wd.proto")
    parser.add_argument("--protoc", type=Path, default=DEFAULT_PROTOC)
    args = parser.parse_args()
    print(json.dumps(validate(args.schema.resolve(), args.proto.resolve(), args.protoc.resolve()),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

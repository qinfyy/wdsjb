# StaticResParser

读取 wd 的 PBStaticConfigure 解包文件，按客户端的 protobuf 消息类型恢复 JSON。BLK 切片、RSA 验签和 AB/mr0k 解密由 Unpacker 处理；本工具默认接收已经去掉签名的内容。

## 使用

先生成并验证配置协议：

```powershell
Set-Location ..\WDProtoDumper
py -X utf8 ProtoDumper_arm64-v8a.py --attach --namespace-prefix PbConfig --package config --output output_pbconfig\config.proto --schema-json output_pbconfig\wd_schema.json
py -X utf8 ValidateSchema.py --schema output_pbconfig\wd_schema.json --proto output_pbconfig\config.proto
```

再解析资源：

```powershell
Set-Location ..\StaticResParser
py -m pip install -r requirements.txt
py -X utf8 main.py --input 解包文件目录 --output output
py -X utf8 main.py --input 解包文件目录 --output verify_output --verify-only
py -X utf8 main.py --input card.bytes --output card_output
```

默认读取 `main.py` 的 `DEFAULT_SCHEMA` 目录数组，包括 WDProtoDumper 的 `output_pbconfig` 和 JsProtoDumper 的 `output/pbconfig`。每次运行先清空本工具的 `temp` 目录，再自动调用 `../WDSniffer/protoc/protoc.exe`，递归编译各目录中的 `.proto`，一个目录生成一个 FileDescriptorSet，保存到 `temp/<目录名>-<路径摘要>.pb`。schema 输入不能放在 `temp` 中。

消息匹配不使用 package，按目录数组顺序加载，后面的同名消息覆盖前面的。

## 参数

- `--input`：必填，已解包的目录或单个文件。目录递归查找 `.bytes`，不把 Unpacker 的报告当成资源。
- `--output`：默认 `output`。保留已有内容，相同结果可重复运行，不同内容拒绝覆盖；本次 `report.json` 会更新。
- `--schema`：覆盖默认目录数组；可重复指定 proto 目录，也兼容单个 `.proto` 或 FileDescriptorSet `.pb`。不接受原始表或清单 JSON。
- `--signed`：只有输入仍带 RSA 签名时才启用。PBStaticConfigureUnpack 的文件不要使用此参数。
- `--message`：单文件显式指定消息名；传入全名时只使用末尾的消息名。
- `--verify-only`：只检查并写报告，不导出任何资源。
- `--detailed-log`：打印逐文件结果。

## 输出

沿用输入相对目录，protobuf 恢复为同名 `.json`，现有 JSON 仅验证并原样保存。字段沿用 proto 名称，枚举保存数值，64 位整数按标准 protobuf JSON 使用字符串。

缺少 schema 或含未知字段的文件保留原始 `.bytes`。能验证 wire 结构时额外输出 `.wire.json`，只记录字段编号、编码和原始字节，不伪造字段名称。报告列出全部结果、摘要及原因。

存在失败、缺失 schema 或未知字段时返回码为 1；返回码 0 才表示全部输入成功恢复。读取规则及 CN 6.1.0 的 RVA 见 [ASSET_ANALYSIS.md](ASSET_ANALYSIS.md)。

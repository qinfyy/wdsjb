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
# 构建 Lua 反编译器（需要 JDK 17+）
& ..\unluac\build.ps1
# 只解密并反编译 Lua，不需要 protobuf schema
py -X utf8 main.py --input 解包文件目录 --output output --lua-only
# 只处理非 Lua 内容；跳过 Lua，不复制原始 Lua
py -X utf8 main.py --input 解包文件目录 --output pb_output --no-decrypt-lua
```

需要处理非 Lua 内容时，读取 `main.py` 的 `DEFAULT_SCHEMA` 目录数组，包括 WDProtoDumper 的 `output_pbconfig` 和 JsProtoDumper 的 `output/pbconfig`。加载 schema 时先清空本工具的 `temp` 目录，再自动调用 `../WDSniffer/protoc/protoc.exe`，递归编译各目录中的 `.proto`，一个目录生成一个 FileDescriptorSet，保存到 `temp/<目录名>-<路径摘要>.pb`。schema 输入不能放在 `temp` 中。`--lua-only` 不加载或编译 schema。

消息匹配不使用 package，按目录数组顺序加载，后面的同名消息覆盖前面的。

## 参数

- `--input`：必填，已解包的目录或单个文件。目录递归查找 `.bytes`、`.lua`、`.luac`，不把 Unpacker 的报告当成资源。
- `--output`：默认 `output`。保留已有内容，相同结果可重复运行，不同内容拒绝覆盖；本次 `report.json` 会更新。
- `--schema`：覆盖默认目录数组；可重复指定 proto 目录，也兼容单个 `.proto` 或 FileDescriptorSet `.pb`。不接受原始表或清单 JSON。
- `--signed`：只有输入仍带 RSA 签名时才启用。PBStaticConfigureUnpack 的文件不要使用此参数。
- `--message`：单文件显式指定消息名；传入全名时只使用末尾的消息名。
- `--verify-only`：只检查并写报告，不导出任何资源。
- `--detailed-log`：打印逐文件结果。
- `--decrypt-lua`：默认开启，解密并反编译 Lua；`--no-decrypt-lua` 关闭，直接跳过且不复制原始 Lua。
- `--lua-only`：只处理按内容识别的 Lua，不加载 schema，不解析、解密或复制其他资源；不能与 `--no-decrypt-lua` 同用。
- `--lua-workers`：Lua 反编译工作进程数，默认最多 4 个。

Lua 逻辑位于独立文件 `lua_parser.py`，按内容头识别，不依据 `LuaScript` 文件名前缀。在 `unluac` 与 `../unluac` 中自动查找反编译器，优先选择 `unluac.exe`，没有 exe 时使用 `unluac.jar` 和 PATH 中的 Java；缺少工具时记录失败，不复制原始文件。EXE 使用 GraalVM AOT 构建，不启动 JVM；通过多进程并发调用，JAR 分支仍会为每个任务启动 JVM。构建脚本和许可见 `../unluac/README.md`。

## 输出

沿用输入相对目录，protobuf 恢复为同名 `.json`，现有 JSON 仅验证并原样保存。字段沿用 proto 名称，枚举保存数值，64 位整数按标准 protobuf JSON 使用字符串。

Lua 恢复为同名 `.lua`，直接平铺到输出目录，不另建 `lua` 子目录；不同输入目录中的同名文件仍按已有输出保护规则处理，不覆盖不同内容。临时标准字节码不保存在输出目录，反编译失败记录原因，不用原始 `.bytes` 冒充源码。源码注释和已剥离的变量名不能逐字恢复。

非 Lua 内容缺少 schema 或含未知字段时保留原始 `.bytes`。能验证 wire 结构时额外输出 `.wire.json`，只记录字段编号、编码和原始字节，不伪造字段名称。报告列出全部结果、摘要及原因。

存在失败、缺失 schema 或未知字段时返回码为 1；返回码 0 才表示全部输入成功恢复。读取规则及 CN 6.1.0 的 RVA 见 [ASSET_ANALYSIS.md](ASSET_ANALYSIS.md)。

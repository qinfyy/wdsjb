# WDProtoDumper

从未定事件簿 `com.miHoYo.wd` 的 ARM64 IL2CPP 运行时恢复 Google.Protobuf 网络协议。默认只处理 `Pb,Baseproto`，不处理 HTTPSDK 或配置表。

## 恢复方式

参考 CastoriceDumper 的逐字段 `WriteTo` 探测：构造独立消息、填写一个字段、执行客户端的 `MessageExtensions.ToByteArray`，解析真实 tag、wire type、packed 和 map 编码。过程不依赖 FieldDescriptorProto 或 protobuf-net 特性，不发送这些测试消息。

当前运行时枚举到 29,055 个类型，没有 `Google.Protobuf.Reflection` 类型；`IMessage` 只有 `MergeFrom/WriteTo/CalculateSize/Reset`，没有 `Descriptor`。

`FridaScript_arm64-v8a.js` 的 `IL2CPP_RVAS` 明确列出每个绑定 API 的 RVA，统一使用 `libil2cpp.so.base + RVA`。不查找 ARM64 导出符号，不校验函数字节。地址仅适用于本次 Dump 对应的客户端，更新客户端后需重新定位。

## 使用

设备已安装同版本 Frida server。当前 MuMu 是 x86_64 系统、ARM64 游戏，脚本自动选择 Emulated Realm，先在 Native Realm 安装 Native Bridge loader，再加载 ARM64 agent。该环境通过 ADB 解析启动 Activity 并启动游戏，避免 Frida spawn 超时；PID 通过精确的 `pidof com.miHoYo.wd` 获取，避免误选 PushService。真实 ARM64 设备仍使用 Frida spawn。

```powershell
Set-Location D:\Il2Cpp\wd\WDProtoDumper
py -m pip install -r requirements.txt
py -X utf8 ProtoDumper_arm64-v8a.py --device emulator-5554 --attach
```

游戏未运行时去掉 `--attach`，或使用 `--spawn`。默认 ADB 为 `E:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe`，agent 为 `..\WDRedirector\frida-agent-arm64.so`。脚本自动推送到 `/data/local/tmp/re.frida.server/frida-agent-arm64.so`，Frida Python/server/agent 必须为相同版本。本次实际使用 17.17.0。

```powershell
# 仅检查类型和 descriptor
py -X utf8 ProtoDumper_arm64-v8a.py --attach --inspect --device emulator-5554
# 小批量测试，自动补充引用的消息类型
py -X utf8 ProtoDumper_arm64-v8a.py --attach --messages PacketHead,PingReq,PingRsp --output output\sample.proto --schema-json output\sample_schema.json
# 从保存的运行时清单重新生成，无需连接游戏
py -X utf8 ProtoDumper_arm64-v8a.py --schema-input output\wd_schema.json
# 从 Il2CppInspector 的拆分 CS 或单个 dump.cs 导出命令表
node DumpCmdIds.js
# protoc 编译和全部运行时字段样本的独立解析验证
py -X utf8 ValidateSchema.py
```

`--namespace-prefix` 可传逗号分隔的命名空间；显式传空字符串会包含游戏程序集中的配置消息。`--realm native` 用于真实 ARM64 设备。`--adb`、`--agent`、`--timeout` 可覆盖默认值。

## 产物与验证

- `output/wd.proto`：`package wd`，包含 PacketHead 的 1,343 个消息、489 个枚举、5,025 个字段。
- `output/wd_schema.json`：运行时 CLR 名称、偏移、tag、编码、逐字段 `sample_hex`、排除项、命令表和模块信息。
- `output/CmdIds.txt`：895 条运行时命令映射，与静态 Dump 完全一致。
- `output/wd.pb`：由生成 proto 编译出的 FileDescriptorSet，不是从游戏恢复出的 descriptor。
- `output/wd_validation.json`：5,025 个字段样本、901 个 repeated 字段、13 个 map 字段和全部枚举的独立验证，失败数 0。

`ValidateSchema.py` 默认使用 `..\WDSniffer\protoc\protoc.exe`（兼容旧目录 BH2Sniffer），可用 `--protoc` 指定其他路径。它使用标准 Python Google.Protobuf 解析每个客户端样本，检查字段是否被识别，以及字符串、整数、浮点数、map key/value 等值是否正确。

恢复失败会保存诊断；默认拒绝把有失败、警告或缺失引用的结果写成正式 proto。`--allow-partial` 仅用于明确需要部分结果的诊断场景。

## 支持边界

保留生成字段后备名称去掉末尾 `_` 后的拼写。字段的 uint32/int32 等类型以 CLR 类型和实际编码为准，不把 `_enum` 辅助属性强行替换到 wire 字段上。独立 `Pb` 枚举也保留供研究数值含义使用；名称冲突会确定性消歧，proto3 缺少零值的枚举补一个明确的 UNSPECIFIED 零值。这是可用于解码的恢复 schema，不是原始 proto 源码的逐字还原。

115 个 DateTime 字段和 12 个 List 缓存字段会修改样本并验证序列化输出不变，再记录为排除项。`Pb.TsMessageReq/TsMessageRsp` 是 TypeScript 原始字节包装器：前者 WriteTo 直接写现成 body 字节，后者的原生 WriteTo 为日志桩，不生成伪造的空 proto 消息。TypeScript 中额外定义的协议需要单独分析脚本资源。本次网络消息没有发现 oneof；当前脚本没有实现 oneof、group 或数值 XOR 混淆的恢复。

## Game Network

IDA 确认 `MoleMole.NetPacket.serialize`（RVA `0x05A24020`）的非加密封包结构，整数使用网络大端：

```text
u16 0x4567 | u16 CmdId | u16 HeadLength | u32 BodyLength
| Baseproto.PacketHead protobuf | Pb message protobuf | u16 0x89AB
```

固定开销为 12 字节。`NetPacket.serializeSec` 是另外的加密路径，不能把上述结论当作其加密算法。SR 的 protobuf 探测方法可参考，但封包常量不应直接照搬 LunarCore。

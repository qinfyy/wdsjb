# WDProtoDumper 开发约定

## 职责

运行时恢复 `.proto`。

当前客户端为 ARM64，已在 x86_64 MuMu 的 Emulated Realm 完成导出验证。不要在没有独立 RVA 和实际验证的情况下声称支持其他客户端版本或 ABI。

## 结构

- `ProtoDumper_arm64-v8a.py` 控制 Frida/ADB 会话、收集清单并渲染 `package wd` 的 proto。
- `FridaScript_arm64-v8a.js` 枚举 IL2CPP 类型，通过独立消息的逐字段序列化恢复 tag 和编码。
- `DumpCmdIds.js` 从 Il2CppInspector 的拆分 CS 目录或单个 CS 文件提取 `Types.CmdId.CmdId`。
- `ValidateSchema.py` 编译生成的 proto，并用标准 Python Google.Protobuf 验证字段样本和枚举。
- `output/` 是生成目录，不是手工维护的协议源。

## 约定

- JavaScript 使用 4 个空格缩进；Python 遵循官方风格并使用类型注解。
- 注释、日志和文档使用中文。
- IL2CPP API 保留原始 `il2cpp_*` 名称，每个绑定 API 的 RVA 明确写入 `IL2CPP_RVAS`，使用模块基址加 RVA；不依赖 ARM64 导出符号，不校验函数字节。`NativeFunction` 签名尽量保持单行。
- 闭合泛型类通过 `il2cpp_class_from_il2cpp_type` 获取；维护 ARM64 对象布局、正确的参数传递和 GC handle 生命周期。
- 字段类型、tag、wire type、packed 和 map 编码以运行时元数据及真实序列化样本为准，不依赖 descriptor 或 protobuf-net 特性，不按名称猜测。
- DateTime/List 等缓存字段只有验证修改后不影响序列化输出才可排除，并记录原因。不要把 TypeScript 字节包装器伪造成空 proto 消息。
- 保留独立协议枚举，不把 `_enum` 辅助属性强行替换到数值 wire 字段上。未支持的 oneof、group、数值 XOR 等情况不得静默伪造恢复结果。
- 不随意重命名 wire 字段。只有发生合法 proto 标识符冲突时才做确定性消歧，并记录诊断。
- `PROTO_PACKAGE` 保持 `wd`，默认生成 proto3；修改时同步检查类型引用、枚举零值和验证脚本。
- 默认拒绝输出有失败、警告或缺失引用的正式 proto；仅通过显式 `--allow-partial` 允许部分结果，失败时保留诊断清单。
- 不手工修补 `output/wd.proto` 作为长期协议源；应修正导出器后重新生成，客户端更新后重新定位 RVA 并导出。

## 运行环境

- ADB 默认从 PATH 查找 `adb.exe`，允许 `--adb` 指定路径，不硬编码本机安装目录。
- 默认 agent 为 `../WDRedirector/frida-agent-arm64.so`，本机 Frida、server、agent 版本必须一致。
- MuMu 使用 ADB 解析启动 Activity，并精确查询主进程 PID，避免误附加到 PushService；保持 Native/Emulated 双 Realm 接入流程。
- 无限等待模块、domain、游戏程序集和协议类型就绪，收集至完成事件；不恢复 `--startup-delay` 或 `--timeout`。出错、断开或 Ctrl+C 时清理会话；设备连接和 ADB 命令可保留操作超时。

## 验证与文档

- 修改 Python 后执行 `py -m compileall .`，修改 JavaScript 后执行 `node --check`。
- 涉及恢复逻辑时，在目标客户端实际导出，并运行 `py -X utf8 ValidateSchema.py`；按需核对运行时和静态 CmdId、字段覆盖及排除项。
- 用户明确要求不测试时不运行测试；仅修改文档不要求代码或运行时测试。
- 参数或输出变化时同步更新 `README.md`；README 保持简短，只写依赖、用法、参数和输出，不写恢复原理、逆向过程或版本统计。

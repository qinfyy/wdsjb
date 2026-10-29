# BH2ProtoDumper 开发约定

## 职责

BH2ProtoDumper 是面向开发者的 protobuf-net 运行时元数据导出器。它从客户端类型和特性恢复 `.proto`、原始 schema 清单与 CmdId，不参与服务器运行时解码。

当前 Frida 脚本面向 x86 客户端。不要在没有独立 RVA 和实际验证的情况下声称支持其他 ABI。

## 结构

- `ProtoDumper_x86.py` 控制 Frida 会话、合并元数据并渲染 `package bh2` 的 proto。
- `FridaScript_x86.js` 使用 IL2CPP 导出 API 枚举程序集、类型、属性和 protobuf-net 特性。
- `DumpCmdIds.js` 从运行时类型导出 CmdId 映射。
- `output/` 是生成目录，不是手工维护的协议源。

## 约定

- JavaScript 使用 4 个空格缩进；Python 遵循官方风格并使用类型注解。
- 注释、日志和文档使用中文。
- IL2CPP 导出函数保留原始 `il2cpp_*` 名称，`NativeFunction` 的 bind 签名尽量保持单行。
- 消息、枚举、嵌套类型、继承字段和 protobuf-net `DataFormat` 必须依据运行时元数据，不按名称猜测。
- 不随意重命名 wire 字段。只有发生合法 proto 标识符冲突时才做确定性消歧，并记录诊断。
- `PROTO_PACKAGE` 默认保持 `bh2`。修改包名必须同步检查类型引用和生成结果。
- 不把一次导出的 `output/bh2.proto` 当作永远正确的手写 schema；客户端版本变化后应重新导出。

## 验证与文档

- 修改 Python 后执行 `py -m compileall .`。
- 修改 JavaScript 后至少执行语法检查，并在目标客户端完成一次导出。
- 参数、输出结构、包名或支持边界变化时更新 `README.md`。

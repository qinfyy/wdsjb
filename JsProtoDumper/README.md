# JsProtoDumper

静态解析 protobufjs 生成的 JavaScript，恢复 `.proto`

## 使用

```powershell
cd D:\Il2Cpp\wd\JsProtoDumper
npm install
node index.js --input 输入目录 --output 输出目录
```

输入支持目录（递归读取 `.js`，忽略 `.js.map`）或单个 JS 文件。保留输入的相对目录及文件名，每个 JS 的每个 protobuf 包生成一份 `.proto`。

多个输入之间有类型引用时，在同一次运行中传入，自动生成 import：

```powershell
node index.js --input ..\AbUnPacker\output_Script\pb --input ..\AbUnPacker\output_Script\pbconfig --output output
```

多输入模式在输出目录下保留 `pb/`、`pbconfig/`。`report.json` 记录数量、输出文件、非协议 JS 和恢复错误。错误返回非零退出码，不把未知类型猜成 bytes。

## 恢复范围

- 从 decode 的 switch / 压缩 if 分支恢复字段名、编号、标量类型、消息引用、repeated 和 map。
- 从 encode 区分 packed / 非 packed，并从 toObject 恢复枚举字段类型。
- 恢复原始包名、嵌套消息、枚举数值、枚举别名及 oneof。
- 输出 proto3；没有零值的枚举添加注释标明的零值占位项。枚举成员出现作用域冲突时改名并注释原 JS 名称。

JS 不保留原始注释、文件级选项等完整源码信息；此工具恢复可观察的协议结构，不保证逐字还原原始 `.proto`。

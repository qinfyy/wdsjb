# WDProtoDumper

## 使用

准备 Python、Node.js 和设备上的 Frida server。本机 Frida、server、ARM64 agent 版本须一致；模拟器需要加载 `..\WDRedirector\frida-agent-arm64.so`，请保证文件存在。`adb.exe` 放入 PATH，或通过 `--adb` 指定路径。

```powershell
Set-Location .\WDProtoDumper
py -m pip install -r requirements.txt
py -X utf8 ProtoDumper_arm64-v8a.py --attach
```

游戏未运行时去掉 `--attach`，或使用 `--spawn`，持续等待和收集至完成，Ctrl+C 中止。

常用参数：`--device` 指定设备，`--adb` / `--agent` 指定工具路径，`--messages` 筛选消息，`--namespace-prefix` 筛选命名空间，`--output` / `--schema-json` 指定输出文件。

## 其他命令

```powershell
# 检查运行时
py -X utf8 ProtoDumper_arm64-v8a.py --attach --inspect
# 从保存的清单重新生成
py -X utf8 ProtoDumper_arm64-v8a.py --schema-input output\wd_schema.json
# 导出命令表，可追加 CS 文件/目录和输出路径
node DumpCmdIds.js
# 验证输出，可用 --protoc 指定编译器
py -X utf8 ValidateSchema.py
```

默认输出：`output/wd.proto`、`output/wd_schema.json`、`output/CmdIds.txt`。验证结果为 `output/wd_validation.json`。

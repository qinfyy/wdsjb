# WDProtoDumper

## 使用

准备 Python 和设备上的 Frida server。本机 Frida、server、ARM64 agent 版本须一致；模拟器需要加载 `..\WDRedirector\frida-agent-arm64.so`，请保证文件存在。`adb.exe` 放入 PATH，或通过 `--adb` 指定路径。

```powershell
Set-Location .\WDProtoDumper
py -m pip install -r requirements.txt
py -X utf8 ProtoDumper_arm64-v8a.py --attach
```

游戏未运行时去掉 `--attach`，或使用 `--spawn`，持续等待和收集至完成，Ctrl+C 中止。

常用参数：`--device` 指定设备，`--adb` / `--agent` 指定工具路径，`--messages` 筛选消息，`--namespace-prefix` 筛选命名空间。`--package` 设置 proto 包名；`--app-package` 设置 Android 应用包名。

`--output` 指定输出目录，默认 `output/`，不存在时自动创建；已有同名文件时直接报错，不覆盖该文件。目录内生成 `wd.proto`、`wd_schema.json`，有命令映射时还生成 `CmdIds.txt`。`--schema-json` 可单独指定清单 JSON 路径；`--no-schema-json` 不保存清单。

## 其他命令

```powershell
# 检查运行时
py -X utf8 ProtoDumper_arm64-v8a.py --attach --inspect
# 导出 PbConfig 到独立目录
py -X utf8 ProtoDumper_arm64-v8a.py --namespace-prefix PbConfig --output output_pbconfig
# 从保存的清单重新生成
py -X utf8 ProtoDumper_arm64-v8a.py --schema-input output\wd_schema.json --output regenerated
# 验证输出，可用 --protoc 指定编译器
py -X utf8 ValidateSchema.py
```

`--schema-input` 只读取已有清单并生成 proto 和命令表，不创建或复制 `*_schema.json`。

# WDRedirector

## 使用

需要 Python 3.10+、Node.js 24+、设备上的 Frida server。本机 Frida、server 和 `frida-agent-arm64.so` 版本须一致。模拟器需将 agent 放在本目录，`adb.exe` 放入 PATH，或通过参数指定路径。

```powershell
Set-Location .\WDRedirector
py -m pip install -r requirements.txt
npm install
npm run build
```

修改 `FridaScript.js` 后重新执行 `npm run build`，输出为 `dist/FridaScript.js`。

模拟器所需的 `frida-agent-arm64.so` 可通过 `ExtractFridaAgent.py` 获取。默认复用或下载与本机 Python Frida 同版本的 Android x86_64 Frida server，并将 agent 提取到本目录：

```powershell
py ExtractFridaAgent.py
```

`--server PATH` 指定已下载的同版本 server 或 `.xz` 压缩包；`--output PATH` 指定 agent 输出路径。

## 配置

修改 `Config.ini`：

```ini
[Settings]
HTTP_URL_BASE=http://192.168.0.108:21000
USE_JAVA_BYPASS_RSA=true
```

`HTTP_URL_BASE` 填设备可访问的 HTTP/HTTPS 服务端根地址，可带端口，不带路径。`USE_JAVA_BYPASS_RSA` 控制 SDK RSA 绕过，关闭时设为 `false`。

## 启动

```powershell
py Redirector.py
py Redirector.py --realm emulated
py Redirector.py --realm native
```

`--realm` 支持 `auto`、`native`、`emulated`，默认自动识别。`--device ID` 指定设备；`--adb PATH`、`--agent PATH` 指定工具路径。模拟器启动时自动上传 agent。

每次运行会重启游戏。Ctrl+C 停止注入，不关闭游戏。实际注入脚本保存到 `dist/FridaScript_Replacemented.js`。

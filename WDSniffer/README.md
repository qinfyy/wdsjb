# WDSniffer

## 运行

需要 Python 3.10+、Node.js 24+、设备上的 frida-server、同版本 ARM64 agent。

~~~powershell
Set-Location .\WDSniffer\frontend
npm install
npm build
Set-Location ..
python -m venv venv
& .\venv\Script\Activate.ps1
python -m pip install -r requirements.txt
python Srv.py
~~~

访问 http://127.0.0.1:1984 ，在网页启动或停止抓包。自动附加游戏d；没有主进程时自动启动游戏。

## 配置

WDSniffer.json 的路径相对该配置文件：

~~~json
{
  "cmdId": "..\\WDProtoDumper\\output\\CmdIds.txt",
  "proto": [
    "..\\WDProtoDumper\\output",
    "..\\JsProtoDumper\\output\\pb"
  ],
  "ListeningAddress": "127.0.0.1",
  "ListeningPort": 1984
}
~~~


消息匹配不使用 package，按数组顺序加载，后面的同名消息覆盖前面的。目录必须包含 `.proto`，`cmdId` 必须指向存在的命令清单；缺失时直接报错，不使用旧描述符。

~~~powershell
py Srv.py --realm emulated
py Srv.py --adb "D:\tools\adb.exe" --device emulator-5554
~~~

--realm 支持 auto、native、emulated，默认 auto；x86_64 模拟器自动选择 emulated。ADB 默认从 PATH 查找 adb.exe。ARM64 agent 固定读取 ../WDRedirector/frida-agent-arm64.so。

监听地址和端口只使用配置里的 ListeningAddress、ListeningPort，不提供命令行参数。ListeningAddress 缺省或为空时使用 127.0.0.1。

## 输出

PacketCapture_*.json 抓包输入文件。

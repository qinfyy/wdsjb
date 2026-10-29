# BH2Sniffer

BH2Sniffer 是面向开发者的 BH2 业务层抓包与解码工具。它通过 Frida 捕获传统 COMMAND 和 Protobuf 帧，使用 Flask + SSE 推送到 Vue 前端，并把会话保存为 JSON。

当前 Hook 使用 x86 `libil2cpp.so` 内唯一命中的特征码定位，不保存客户端版本或固定 RVA；暂不支持 ARM 架构，也不用于普通玩家的流量重定向。

## 安装与运行

```powershell
Set-Location BH2Sniffer
py -m pip install -r requirements.txt

Set-Location frontend
npm install
npm run build

Set-Location ..
py Srv.py
```

默认访问地址为 `http://127.0.0.1:1984`。网页可以启动/停止捕获，也可以导入 `.json` 文件进行离线查看。

常用后端参数：

```powershell
py Srv.py --host 127.0.0.1 --port 1984 --max-packet-bytes 8388608
```

开始捕获时，如果游戏尚未运行，后端会 spawn `com.miHoYo.HSoDv2Original`；如果游戏正在运行，则附加当前进程。捕获结果保存为 `PacketCapture_*.json`，不应提交仓库。

## 解码输入

`data/bh2.proto`、`data/CmdIds.txt` 和 `data/CommandType.txt` 是解码器的权威输入。每次启动解码器都会调用 `protoc/protoc.exe` 重新生成 `data/bh2.pb` 并加载 descriptor set；消息 package 直接从 descriptor 中读取，不在解码器中硬编码。

COMMAND 按客户端传统命令表标记，未知字段保留 raw；Protobuf 只有在运行时路径或命令映射足够明确时才反序列化。协议关系见 [网络协议分析](../docs/BH2_NETWORK_PROTOCOL_ANALYSIS.md)。

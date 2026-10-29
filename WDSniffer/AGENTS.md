# BH2Sniffer 开发约定

## 职责与边界

BH2Sniffer 是面向协议开发者的业务层抓包、解码和网页查看工具。它不负责流量重定向、私服响应或通用网络代理。

当前 Frida 特征码与对象布局面向开发使用的 x86 客户端。增加其他 ABI 时必须提供独立目标表和实际验证，不能复用 x86 特征或对象布局。

## 权威输入

- 解码器只能使用 `data/bh2.proto`、`data/CmdIds.txt` 和 `data/CommandType.txt`。
- 以上三个文件是只读输入。协议解码器改动不得修改它们，也不得引入对 `dump.cs`、外部 `.pb`、BH2ProtoDumper 输出或服务端 Gateway 文件的运行时依赖。
- 每次创建解码器时使用仓库内 `protoc/protoc.exe` 把 `data/bh2.proto` 编译为 `data/bh2.pb`，再从 descriptor set 加载；不要手写 `.proto` 解析器。
- `data/bh2.pb` 是生成文件，不是新的权威输入。

## 捕获与解码

- `fridaScript.js` 在业务层分别捕获传统 COMMAND 和 Protobuf 路径。
- `GeneralPackage.Pack/UnPack` 只代表 COMMAND；Protobuf 必须通过 `UnPackProtoBufPacket` 和发送链路 Hook 捕获。
- 离线判定优先使用明确的 Hook 协议提示和运行时类型。仅凭 cmdId 遇到 COMMAND/Protobuf 重号时不得强行解码。
- 无法可靠解码的包必须保留完整 raw 数据和明确状态，不能丢弃或伪造字段。
- 捕获文件可能包含认证和账号数据，不得提交仓库，也不得把原始内容复制到公开文档。

## 后端与前端

- Python 遵循官方风格并使用类型注解；注释和新增文档使用中文。
- JavaScript、Vue 和 TypeScript 使用 4 个空格缩进。
- `Srv.py` 负责 Flask API、Frida 生命周期和 SSE；协议解析保持在 `protocol_decoder.py`。
- 前端只消费稳定的公开包字段。增加字段时同步更新导入、实时 SSE 和保存格式。
- 不创建第二套捕获存储格式；捕获保存与导入统一放在 `capture_store.py`。

## 验证与文档

- 修改 Python 后执行 `py -m compileall .` 和依赖检查。
- 修改前端后在 `frontend` 执行 `npm run build`。
- 协议改动使用至少一帧 COMMAND 和一帧 Protobuf 做完整动态解码验证，并执行 `git diff --check`。
- 启动方式、输入文件、API 或支持范围变化时更新 `README.md`。

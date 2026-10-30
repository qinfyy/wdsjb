# WDSniffer 开发约定

- 不修改 frontend。SSE、保存和导入统一使用 time/fromServer/packetId/packetName/object/raw 的 JSON 块，不输出 type。GetConfig、SetConfig 返回 404 是预期行为。
- WDSniffer.json 的 proto、cmdId 是解码权威输入，路径相对配置文件；ListeningAddress、ListeningPort 指定监听地址和端口。地址缺省或为空时使用 127.0.0.1。
- CLI 只保留 --package、--max-packet-bytes、--adb、--realm、--device。不添加 --host、--port 或 --config；监听地址、端口和 schema 从默认 WDSniffer.json 读取。
- 每次创建解码器用本目录 protoc/protoc.exe 编译配置里的 schema，descriptor 只能输出到本目录被 Git 忽略的 temp/*.pb。不手写 proto 解析器、不修改输入 schema、不依赖 dump SDK 运行。
- FridaScript_arm64-v8a.js 使用唯一特征码匹配及 ARM64 对象布局，在 NetPacket 的 serialize/serializeSec、deserialize/deserializeSec 成功返回时读取明文 Body。不使用固定 RVA 或自动解析 ARM64 符号；不额外校验函数字节。特征码前写命名空间、类及完整函数签名；布局项写 CLR 字段或 Native 结构体字段注释。
- 默认 ADB 是 PATH 的 adb.exe，支持 --adb。ARM64 agent 固定为 ../WDRedirector/frida-agent-arm64.so，支持 --realm auto/native/emulated。自动检测主进程，未运行则启动。
- Srv.py 管理 Flask/SSE；frida_runtime.py 管理设备连接、Native Bridge 和注入；protocol_decoder.py 负责 schema 解码；capture_store.py 统一保存和导入。
- 无法解码时保留完整 raw 和明确诊断，不猜字段、不截断伪装成完整包。抓包含认证与账号数据，禁止提交或在公开文档里复制原始内容。
- Python 使用类型注解；JavaScript 使用四空格缩进。执行 Python 编译、后端测试和 git diff --check，不修改或构建前端。动态验证不主动登录、支付或发送业务请求。
- README 只写简短用法；网络分析与 RVA 记录在 NETWORK.md。

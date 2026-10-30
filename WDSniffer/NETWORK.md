# MoleMole Game Network

分析输入：Reverse/DUMP 的 ARM64 CN 6.1.0 SDK 和 libil2cpp.so，已用 IDA 核对函数实现。这里只记录游戏 TCP 网络，不涉及 HTTPSDK。

## 收发位置

| 函数 | 本版本 RVA | 职责 |
| --- | --- | --- |
| MoleMole.NetworkManager.SendPacket(IMessage) | 0x05A32DE8 | 构造 NetPacket，设置命令号并交给 TCP 客户端 |
| MoleMole.NetworkManager.SendRPCPacket(...) | 0x05A54FAC | RPC 请求入口 |
| MoleMole.TcpAsyncClient.send(NetPacket) | 0x05B573A0 | 设置时间戳、选择明文或加密封包、加入发送队列 |
| MoleMole.TcpAsyncClient.doAsyncSend() | 0x05B57788 | 将发送队列交给 Socket |
| MoleMole.TcpAsyncClient.onRecv(int) | 0x05B581E8 | 合并残帧，逐包反序列化并加入接收队列 |
| MoleMole.TcpAsyncClient.HandleRecvPacket() | 0x05B58918 | 调用 OnRecvPacketDelegate 分发接收队列 |
| MoleMole.NetworkManager.OnCmdCallBack(NetPacket) | 0x05A2C7F8 | 提取 CmdId/RpcId，进入 PacketCallbackManager |
| MoleMole.NetPacket.serialize(ref MemoryStream) | 0x05A24020 | 明文发送封包 |
| MoleMole.NetPacket.serializeSec(ref MemoryStream, ref byte[]) | 0x05A24570 | 加密发送封包 |
| MoleMole.NetPacket.deserialize(ref byte[]) | 0x05A2497C | 明文接收解包 |
| MoleMole.NetPacket.deserializeSec(ref byte[], ref byte[]) | 0x05A252B8 | 加密接收解包，也处理无需加密的命令 |

表中 RVA 只用于分析与复核。抓包脚本不按 RVA 定位，而是在 libil2cpp.so 的可执行映射中扫描四个 NetPacket 函数入口特征；Native Bridge 没有宿主执行权限时扫描只读代码映射。每个函数必须唯一命中后才安装 Hook。

## 帧与明文

固定前缀均为网络字节序：

~~~text
uint16  0x4567
uint16  cmdId
uint16  PacketHead 明文长度
uint32  Body 明文长度
bytes   PacketHead + Body（或二者一起加密后的内容）
uint16  0x89ab
~~~

PacketHead 是 Baseproto.PacketHead 的 Protobuf，不是 BH2 的固定 42 字节 ProtocolHead。未加密总长为 12 + head_len + body_len；加密区域长度经 getPackSize 计算为 (head_len + body_len + 16) & ~15。

NetPacket.Body 是已经序列化的消息 MemoryStream，NetPacket.cmdId 位于对象 +0x10，Body 位于 +0x20。发送函数成功返回后 Body 仍是明文；接收函数返回 PACKET_CORRECT=1 后 Body 已完成解密和填充。PACKET_NOT_COMPLETE=2、PACKET_NOT_CORRECT=3 不输出捕获事件，避免残帧和错误帧被误解包。

抓包在上述四个函数成功返回时复制 Body 的有效字节，不重复序列化 IMessage，不捕获密钥或伪造完整传输帧。命令号和 Body 通过 emit(payload, data) 交给后端，后端根据 CmdIds.txt 与 protoc descriptor 解包。

## 更新检查

- 函数签名、特征码及字段布局集中在 FridaScript_arm64-v8a.js，CLR 与 Native 字段均有对应注释。
- 特征码屏蔽地址、分支距离和 IFix 补丁编号；函数重编译导致寄存器分配或入口布局变化时仍需重新定位。
- 匹配为零或多处时明确报错，不回退固定 RVA，不猜选第一个结果。
- schema 只读，protoc 输出在 WDSniffer/temp/*.pb；不再使用 BH2 COMMAND 或 CommandType.txt。

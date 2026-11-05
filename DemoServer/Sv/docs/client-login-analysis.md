# WD 客户端登录与进门条件

分析日期：2026-11-05。对象为当前 DUMP 的 6.1.0.2 客户端。地址是 libil2cpp.so 的 RVA，不修改客户端。

## 抓包和客户端证据

`PacketCapture_26-11-05_00-05-56.json` 的实际记录时间为 2026-11-05 00:06:02 至 00:09:16（上海时间）。共 3644 条记录：

- PlayerLoginReq：407 次；PlayerLoginRsp：305 次。
- GetPlayerTokenReq：156 次；GetPlayerTokenRsp：153 次。
- 登录成功响应与 `-420 / 先取得玩家令牌` 交替出现。
- Unity 日志 00:06:10.827：`read head_magic=0x0, but expect head_magic=0x4567`。
- Unity 日志 00:06:10.831：`deserialize packet failed. PACKET_NOT_CORRECT`。

抓包在 NetPacket 序列化/反序列化时读取明文 Body，不记录完整 TCP 密文和 PacketHead。不能用其中的 raw 字段证明 TCP 上传输了明文，也不能据此重放业务数据。

## 频繁发送 103 的调用链

1. `TcpAsyncClient.onRecv`（0x05B581E8）解码失败时 disconnect。
2. `NetworkManager.Core`（0x05A2B9F4）检查连接并自动重连。
3. `_TryConnectAsync_b__79_0`（0x05A5B644）：VerifiedInGameServer 为 true 时直接 RequestLogin，否则 RequestToken。
4. `OnGetPlayerTokenRsp`（0x05B4240C）：retcode=1 时设置 UID 和 VerifiedInGameServer，再 RequestLogin。
5. `UILoginManager.OnGetPlayerLoginRsp`（0x060D5494）：retcode=1 发初始化请求；-483/-484 重新 dispatch；其他错误（含 -420）重新 RequestToken。
6. `RequestToken`（0x05A330E4）清除 VerifiedInGameServer 和客户端密钥，再发 101。

旧网关仅接受当前 TCP 连接通过 101 认证后的 103。断线后的直接 103 会返回 -420；重新 101/103 成功后，初始化帧错误再次断线，循环继续。不能通过无条件接受 UID 或把错误改成成功解决。

## TCP 帧与会话协商

- `PackUtil.ShouldNotSec`（0x05B3EFF4）：只有 101、102、103、104 明文。
- `NetPacket.getPackSize`（0x05A22A30）：`(headSize + bodySize + 16) & ~15`。
- `getPacketLen`（0x05A22910）：非登录帧即使没有密钥也按上述补齐长度前移游标。这是旧明文网关读偏到下一包中间的原因。
- 前缀为 10 字节：4567 magic / uint16 cmd / uint16 明文 head 长度 / uint32 明文 body 长度，均大端。
- 登录帧：前缀 + protobuf head + body + 89AB。
- 其他帧：前缀 + AES-CBC-PKCS7(head + body) + 89AB。头、体一起加密，前缀中的长度仍是明文长度。
- `AESUtils.Encrpt/Decrpt`（0x0692E974 / 0x0692EC28）：CBC=1、PKCS7=2。
- `AESUtils.cctor`（0x0692EEE4）引用 FieldInfo 0x0A6FB368；初始 IV 为 `000102030405060708090A0B0C0D0E0F`，不是网络运行时 IV。
- `NetworkManager` 构造函数末尾（0x05A29F5C）尾调用 `AESUtils.InitIfNeeded`（0x0692E5E8）。该函数将 IV 改写为 `43382817693913704338281769391371`。此前遗漏 JUMP_NEAR 引用，只检查普通调用而得出未使用的结论是错误的。
- `TcpAsyncClient.onRecv` 将 `PD(SessionValue1)` 写到 `session_read_key_`（0xA8），将 `PD(SessionValue2)` 写到 `session_write_key_`（0xB0）；`send` 把 0xB0 处的密钥交给 `serializeSec`。服务端密钥方向与之对应，无需交换。
- `StepUtils.PD`（0x05B516C8）：ck 字符逐个 XOR `(index+2)&3` 后导入 RSA XML，OAEP-SHA1 解密。
- `StepUtils.PE`（0x05B51474）：sk 字符逐个 XOR `(index+1)&3` 后导入 RSA XML，OAEP-SHA1 加密。
- `StepUtils.Step`（0x05B5191C）：SHA256 工作量挑战。深度 1 搜索 `SHA256(UTF8(org + decimal nonce))[0] == 0x23`。
- 服务端 102 的 SessionValue1/2 为加密到客户端公钥的随机服务端发送/接收密钥；SessionValue3 为挑战字符串，SessionValue4 为深度。
- 客户端解开密钥后，在明文 103 中通过 PE 回传密钥，并在 SessionValue4 回传挑战答案（`TcpAsyncClient.send`，0x05B573A0）。

本地实现使用已通过 SDK combo token 认证的当前连接和挑战校验，不把 PE 回传字段或 UID 当身份凭证。原服务器 RSA 私钥不在现有材料中，不伪造该私钥，也不允许仅凭 UID 跨连接登录；重连回退到 101 重新认证。

## 真正的进门门槛

`LoginStageState.CheckEnterMainOrStory`（0x05B67CBC）要求 IsGuideDataReady 和 IsBaseNetPackageReady 同时成立。

`OnRecvPackage`（0x05B679DC）从 runtimeRequirePackageList 删除已收到的响应；263 标记引导数据就绪；全部删除后进入 OnNetReadyForMainGame。cctor（0x05B682BC）要求这 22 个响应：

`109,125,113,111,1612,1614,135,131,149,119,197,185,263,203,269,352,381,397,440,813,747,815`

JS `gameplay/GameplayMgr.js:480` 转发 263 给 `TSForceGuideModel.OnGetGuideInfoRsp`。该脚本（154 行起）在成功时先设 NeedShowStory=true，按已完成 STORY_TIMELINE_1/2/3 选择剧情起点，完成 STORY_TIMELINE_4 才设为 false。空引导列表应该进入新手剧情，不是直接进入主页。

因此 104 成功不等于已进游戏；测试收齐网络响应也不等于各业务对象已完整。

## 本次验证与剩余问题

测试使用临时数据库，真实 SDK combo 认证，客户端 DUMP 的 RSA 解密算法及独立 AES 帧读取器；验证未认证的直接 103 被拒绝后可重新 101/103 登录、22 个必需响应和额外初始化请求的粘包/拆包，不使用官方抓包回放。17 项测试通过。

另一条已确认的业务异常是 `1在DesignProxy.Instance.chapterScheduleDic中不存在`。`DesignProxy.UpdateLevelData`（0x05CBCEE4）在 LevelDataAll=1 时清空 chapterScheduleDic，再按 chapterList 填回。旧网关只发送 levelList，章节字典始终为空。

现已在 LevelManager 内通过已加载的 ChapterData 表生成完整 chapterList；有当前 Demo 开放关卡的章节为 AlwaysOpen=1，其余为 Closed=0（DUMP 的 Pb.eOpenType），不扩大既有 IsOpen 范围、不伪造限时排期。此修改按用户要求未新增或运行测试。

业务初始化中的既有空成功兜底仍不等于完整实现。客户端当前未运行，本次不能宣称已经实际进入主界面。

## 00:51 抓包的失败位置与修正

`PacketCapture_26-11-05_00-51-35.json` 共 7280 条，实际时间为 00:51:40.999 至 00:57:52.175（上海时间）。103 有 329 次，104 有 258 次（成功 126 次、-420 共 132 次），101 有 140 次，102 有 133 次。

第一次 101/102/103/104 完成后，客户端发 262、950、108、124、112 等初始化请求。整份抓包的服务端响应只有 102/104，连 263 都没有。对应日志应读取 `Sv/logs/sv-20261105_001.log`，其中反复出现“帧解密失败”。故本轮故障发生在网关解密阶段，还没有进入业务初始化处理。

现修正 NetPacket 的双向 AES IV 为 NetworkManager 构造后实际使用的值；解密失败日志增加命令号、明文头体长度和密文长度，会话结束日志增加连接 ID 与底层异常信息，不记录密钥或 token。按用户要求不新增或运行测试；是否进入游戏仍须真实客户端确认。

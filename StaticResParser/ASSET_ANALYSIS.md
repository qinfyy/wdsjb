# wd 静态配置格式与读取规则

## 范围

本文针对 **CN 6.1.0 ARM64**。模块 RVA 使用“模块基址 + RVA”定位，不是 ELF 文件偏移。未标注版本或模块的结构偏移不能当作 RVA 使用。

StaticResParser 接收 PBStaticConfigure 的已解包文件。XMF 索引、BLK 切片、RSA 验签和 UnityFS/mr0k 解密属于 Unpacker，完整引擎封包算法见其 ASSET_ANALYSIS.md。本工具不保留 BH2 的 AES、版本 Bundle 或 TableToolsData 流程。

## 分层

```text
PBStaticConfigure.xmf
  -> FileMapSystem 按块名、文件偏移和长度读取 BLK
  -> 128 字节 RSA 签名 + 配置正文
  -> RSA1024 / PKCS#1 v1.5 / SHA1 验签
  -> 只移除签名
  -> 按文件读取规则选择 protobuf 消息，或读取 JSON
```

PBStaticConfigureUnpack 的文件已经处于最后一层：它们是配置正文，不再含 RSA 签名。再次删除 `0x80` 字节会直接截断 protobuf。扩展名 `.bytes` 不决定内容类型，也不意味着仍需 AES、mr0k 或 LZ4 解密。

AB 是另一条分支：UnityFS 的压缩块可经过 mr0k 预处理，再解压、拼接和读取 SerializedFile。不能把这条引擎流程套到已经恢复的 protobuf 配置正文上。

| 版本 | 模块 | RVA | 入口 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x0611E154` | PBStaticConfigure.Init |
| CN 6.1.0 | libil2cpp.so | `0x0611E1EC` | PBStaticConfigure.LoginInit |
| CN 6.1.0 | libil2cpp.so | `0x0611E5E8` | PBStaticConfigure.LoadMiscData |
| CN 6.1.0 | libil2cpp.so | `0x06030114` | RSASignedLoader.InstanceInit |
| CN 6.1.0 | libil2cpp.so | `0x06030300` | RSASignedLoader.LoadProtobufInBytes |
| CN 6.1.0 | libil2cpp.so | `0x0603058C` | RSASignedLoader.RsaVerify |
| CN 6.1.0 | libil2cpp.so | `0x0603081C` | RSASignedLoader.RSACheckContent |
| CN 6.1.0 | libil2cpp.so | `0x0A726CC8` | PUBLICKEY 字符串材料 |
| CN 6.1.0 | libunity.so | `0x003C0444` | UnityFS LZ4/mr0k 分支；不是 protobuf 读取入口 |

## 签名读取

带签名的配置文件布局：

| 文件偏移 | 长度 | 含义 |
| --- | ---: | --- |
| `0x00` | 128 | RSA 签名 |
| `0x80` | 文件长度减 128 | 配置正文 |

`LoadProtobufInBytes(data, rawLen)` 将前 128 字节复制到签名缓存，用 SHA1 和 PKCS#1 验证 `data[0x80:rawLen]`。成功返回原始数组，泛型读取路径随后用正文区间创建 protobuf 输入流；该函数自身不是正文裁剪函数。签名失败不能继续解析。

`RSACheckContent(data)` 成功后返回已经裁掉签名的数组；Unpacker 使用这条路径，因此本工具默认输入没有签名。合法空正文与损坏文件需要区分，不能用“文件短于 128 字节”推断已经解密失败。

## 汇总表

普通文件采用消息名 `All{文件名去扩展名}Datas`。例如：

```text
card.bytes
  -> PbConfig.AllcardDatas
  -> info: CardInfoDatas
  -> 配置行: CardInfoConfigure

item.bytes
  -> PbConfig.AllitemDatas
  -> 各子表包装
  -> 具体配置行
```

文件是完整的标准 protobuf wire message，不是 JSON、SerializedFile、连续裸行或“每行前缀一个固定长度”的结构。外层字段使用 protobuf 的 length-delimited 编码，其长度为 varint，不能把前四字节统一当作文件长度。

`CardConfigureManager.Init` 读取 `card.bytes` 并调用 `LoadProtobuf<AllcardDatas>`；成功后才将各子表构造成只读字典与数组。这些字典不是资源里额外的二进制目录。

| 版本 | 模块 | RVA | 证据 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x06D62138` | CardConfigureManager.Init |
| CN 6.1.0 | libil2cpp.so | `0x06D62200` | GetFileBytes(card.bytes) 调用点 |
| CN 6.1.0 | libil2cpp.so | `0x06D62254` | LoadProtobuf<AllcardDatas> MethodInfo 材料 |
| CN 6.1.0 | libil2cpp.so | `0x06D62268` | 共享泛型 LoadProtobuf 调用点 |
| CN 6.1.0 | libil2cpp.so | `0x02B85AF8` | LoadProtobuf(byte[]) 共享入口，将数组长度传给泛型读取路径 |
| CN 6.1.0 | libil2cpp.so | `0x06F51300` | AllcardDatas.WriteTo |
| CN 6.1.0 | libil2cpp.so | `0x06F52038` | AllcardDatas.MergeFrom(CodedInputStream) |
| CN 6.1.0 | libil2cpp.so | `0x074FB7A8` | CardInfoConfigure.WriteTo |
| CN 6.1.0 | libil2cpp.so | `0x074FE9C8` | CardInfoConfigure.MergeFrom(CodedInputStream) |

以 `card.bytes` 的 `0a cc f2 0c` 为例，`0a` 是 tag=1、wire=2，`cc f2 0c` 是正文长度 varint，不是加密头。

## 按需分表

分表的消息类型与汇总表不同，必须先识别文件名规则再解析：

| 文件规则 | 根消息 | 读取入口 | 版本 | 模块 | RVA |
| --- | --- | --- | --- | --- | --- |
| `story_<id>.bytes` | StoryInfoConfigure | StoryConfigureManager.LoadStoryConfig | CN 6.1.0 | libil2cpp.so | `0x071BA07C` |
| `explore_<id>.bytes` | ExploreMapDataConfigure | ExploreConfigureManager.LoadExploreConfig | CN 6.1.0 | libil2cpp.so | `0x06DA6AC0` |
| `text_<group>.bytes` | TextMapGroupConfigure | TextConfigureManager.LoadTextMap | CN 6.1.0 | libil2cpp.so | `0x0722BCD8` |
| `live2d_<group>.bytes` | Live2DStoryGroupConfigure | Live2DConfigureManager.GetLive2DStoryGroup | CN 6.1.0 | libil2cpp.so | `0x0747E7A4` |

对应消息都是 PbConfig 下的 CLR 类型。proto 包名可以不同，不能硬编码成 CLR 命名空间或固定 `wd`。

### Story 与 Explore

文件名中的 ID 直接对应根消息 tag=1：Story 为 `storyID`，Explore 为 `mapID`。客户端缓存成功加载的对象，按需再次读取，不把全部分表嵌入汇总消息。

| 版本 | 模块 | RVA | 证据 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x06DA6C80` | ExploreMapDataConfigure 泛型 MethodInfo |
| CN 6.1.0 | libil2cpp.so | `0x06DA6C94` | 对应 LoadProtobuf 调用点 |

### Text

Text 使用 20 个 ID 一组：

```text
group = trunc(textID / 20) * 20
file = text_<group>.bytes
```

`TextMapGroupConfigure` 的 tag=1 是 `iD`，tag=2 是重复的 `textMapItem`。组内 `TextMapConfigure.groupID` 才是客户端用于索引单条文本的 ID，不能与外层 `iD` 混淆。

proto3 默认值不一定写到文件中。`text_0.bytes` 可以没有外层 tag=1，这等价于外层 `iD=0`，不是文件截断。

字符串 ID 的规则：没有下划线且能转换为整数时直接使用该整数；存在下划线时尝试解析末尾数字，并用前缀查找 TextMapRange。最终数值由范围起点加末尾编号得到，不是直接对字符串做哈希。

| 版本 | 模块 | RVA | 证据 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x0722AFE4` | CalculateTxtmapID |
| CN 6.1.0 | libil2cpp.so | `0x0722B294` | FindMapRangeByKeyword |
| CN 6.1.0 | libil2cpp.so | `0x0722BD84` | 通过乘法和移位计算除以 20 |
| CN 6.1.0 | libil2cpp.so | `0x0722BF64` | TextMapGroupConfigure 泛型 MethodInfo |
| CN 6.1.0 | libil2cpp.so | `0x0722BF78` | LoadProtobuf 调用点 |

### Live2D

Live2D 使用 100 个 ID 一组：

```text
group = trunc(storyID / 100) * 100
file = live2d_<group>.bytes
```

外层 `Live2DStoryGroupConfigure.iD` 对应组 ID；tag=2 为重复的 `live2DStoryConfigure`。外层消息不是 Alllive2dDatas，也不是单条 Live2DStoryConfigure。

| 版本 | 模块 | RVA | 证据 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x0747E490` | FindLive2Dstory |
| CN 6.1.0 | libil2cpp.so | `0x0747E528` | 除以 100 的乘法常量 |
| CN 6.1.0 | libil2cpp.so | `0x0747E544` | 商乘 100，形成分组 ID |
| CN 6.1.0 | libil2cpp.so | `0x0747E9D0` | Live2DStoryGroupConfigure 泛型 MethodInfo |
| CN 6.1.0 | libil2cpp.so | `0x0747E9E4` | LoadProtobuf 调用点 |

## 非 PbConfig 内容

`JSON_*.bytes` 的正文可以直接是 UTF-8 JSON。应验证 JSON 并保留原始字节，不用 protobuf 消息强行解释。

`MiscData_misc_data.bytes` 经 RSACheckContent 后按 Encoding.Default 转为字符串，送入 ConstVariableManager；它不是 Allmisc_dataDatas。

`LuaScript_Battle_*.bytes` 也不是 PbConfig。客户端通过 GameBattleLuaManager 的脚本加载链处理它们。当前样本不是普通 protobuf，不能把 Lua 私有二进制格式的头部当作 protobuf 字段或再次套 mr0k。未恢复 Lua 的私有格式时只保留原始文件，不声称恢复出 Lua 源码。

| 版本 | 模块 | RVA | 入口 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x05E1DD48` | GameBattleLuaManager.myLoader |
| CN 6.1.0 | libil2cpp.so | `0x05E1E054` | GameBattleLuaManager.GetScriptEnv |
| CN 6.1.0 | libil2cpp.so | `0x070680A4` | XLua.SignatureLoader.load_and_verify |

部分普通文件虽然具有合法 protobuf wire 结构，但当前 CLR PbConfig 没有对应的 All…Datas。缺少消息定义不是解密失败，也不等于这些文件可以共用其他同形消息；需要继续定位其真正的 schema 来源，不能仅凭名称认定它们属于 TypeScript。

## Schema 恢复与完整性

配置类没有可用的 Google.Protobuf.Reflection descriptor。WDProtoDumper 使用真实运行时逐字段写入非默认样本，再调用 WriteTo 恢复 tag、wire、packed、枚举及引用关系。

运行时存在不参与序列化的计算缓存，例如 DateTime、普通 List、Dictionary、Vector3Int 和动画缓存。必须修改样本并确认序列化字节完全不变后才可排除；不能按字段名或类型直接忽略。重复 protobuf 字段使用 RepeatedField，与普通 List 缓存不同。

CN 6.1.0 的 PbConfig 已独立编译和验证：1726 个消息、371 个枚举、5890 个字段样本，无失败、警告或占位类型。此统计仅表示已导出 CLR 消息的完整性，不意味着每个解包文件都有对应 CLR schema。

StaticResParser 同时读取 WDProtoDumper 与 JsProtoDumper 的配置协议目录。每次运行先清空 StaticResParser 的 `temp`，再使用 WDSniffer 随附的 `protoc/protoc.exe`，将每个目录的 `.proto` 独立编译为包含 import 依赖的 FileDescriptorSet，保存到 `temp`。按目录数组顺序加载消息，匹配时忽略 package，后面的同名消息覆盖前面的；消息字段与引用仍由其原始描述符解析，不手工合并不同 schema。

解析一个消息后递归移除未知字段，比较移除前后的规范化序列化字节。存在变化时表示当前 schema 未覆盖全部字段，不能导出丢失信息的命名 JSON。分表还需要核对外层 ID 与文件名一致。

无 schema 的 wire 导出只保留：

- 原始文件及 SHA-256。
- 每个字段的偏移、tag、wire 和原始编码字节。
- varint 的无符号原值，或 length-delimited/fixed 字段的原始 payload。

缺少 schema 时，length-delimited 可以是字符串、字节串、子消息或 packed 数值；varint 可以是 bool、enum、int 或 ZigZag 编码。不能根据“能解析”自动赋予字段语义。

## 汇总读取入口

以下文件名和泛型消息从 SDK 方法范围及 IDA 反汇编中的字符串、MethodInfo 引用交叉核对。所有行均为 CN 6.1.0、libil2cpp.so；不存在的缓存文件不由本工具补造。

| 版本 | 模块 | 文件 | 消息 | Init RVA |
| --- | --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `ancient.bytes` | AllancientDatas | `0x07416F08` |
| CN 6.1.0 | libil2cpp.so | `ancientgame.bytes` | AllancientgameDatas | `0x06EBC430` |
| CN 6.1.0 | libil2cpp.so | `anniversary2nd.bytes` | Allanniversary2ndDatas | `0x06F0007C` |
| CN 6.1.0 | libil2cpp.so | `anniversary.bytes` | AllanniversaryDatas | `0x06F05DA0` |
| CN 6.1.0 | libil2cpp.so | `appraisal.bytes` | AllappraisalDatas | `0x06C9ECCC` |
| CN 6.1.0 | libil2cpp.so | `avatarPendants.bytes` | AllavatarPendantsDatas | `0x06CAB4A0` |
| CN 6.1.0 | libil2cpp.so | `badge.bytes` | AllbadgeDatas | `0x06CAC160` |
| CN 6.1.0 | libil2cpp.so | `basenxx.bytes` | AllbasenxxDatas | `0x06CB1D78` |
| CN 6.1.0 | libil2cpp.so | `battle.bytes` | AllbattleDatas | `0x06AA4364` |
| CN 6.1.0 | libil2cpp.so | `bighouse.bytes` | AllbighouseDatas | `0x06AB6300` |
| CN 6.1.0 | libil2cpp.so | `billing.bytes` | AllbillingDatas | `0x06AB9D18` |
| CN 6.1.0 | libil2cpp.so | `birthdayV3.bytes` | AllbirthdayV3Datas | `0x07255544` |
| CN 6.1.0 | libil2cpp.so | `businesscard.bytes` | AllbusinesscardDatas | `0x06DD3F14` |
| CN 6.1.0 | libil2cpp.so | `cafe.bytes` | AllcafeDatas | `0x06DD8A1C` |
| CN 6.1.0 | libil2cpp.so | `card.bytes` | AllcardDatas | `0x06D62138` |
| CN 6.1.0 | libil2cpp.so | `cardSort.bytes` | AllcardSortDatas | `0x07262E18` |
| CN 6.1.0 | libil2cpp.so | `chapter.bytes` | AllchapterDatas | `0x07267CB4` |
| CN 6.1.0 | libil2cpp.so | `character.bytes` | AllcharacterDatas | `0x0726B608` |
| CN 6.1.0 | libil2cpp.so | `clickeffect.bytes` | AllclickeffectDatas | `0x07271108` |
| CN 6.1.0 | libil2cpp.so | `clue.bytes` | AllclueDatas | `0x07273380` |
| CN 6.1.0 | libil2cpp.so | `coupleAppItem.bytes` | AllcoupleAppItemDatas | `0x074B6D98` |
| CN 6.1.0 | libil2cpp.so | `digitaldraw.bytes` | AlldigitaldrawDatas | `0x074E5920` |
| CN 6.1.0 | libil2cpp.so | `dlc.bytes` | AlldlcDatas | `0x06E855A0` |
| CN 6.1.0 | libil2cpp.so | `doll.bytes` | AlldollDatas | `0x06E8B64C` |
| CN 6.1.0 | libil2cpp.so | `download.bytes` | AlldownloadDatas | `0x06D1ED60` |
| CN 6.1.0 | libil2cpp.so | `egypt.bytes` | AllegyptDatas | `0x06D21B04` |
| CN 6.1.0 | libil2cpp.so | `event.bytes` | AlleventDatas | `0x06C601FC` |
| CN 6.1.0 | libil2cpp.so | `evidence.bytes` | AllevidenceDatas | `0x06D9144C` |
| CN 6.1.0 | libil2cpp.so | `explore.bytes` | AllexploreDatas | `0x06D9FE28` |
| CN 6.1.0 | libil2cpp.so | `functionopen.bytes` | AllfunctionopenDatas | `0x06CB92B4` |
| CN 6.1.0 | libil2cpp.so | `gamebubble.bytes` | AllgamebubbleDatas | `0x06CC16EC` |
| CN 6.1.0 | libil2cpp.so | `gamepaint.bytes` | AllgamepaintDatas | `0x06CC5DC8` |
| CN 6.1.0 | libil2cpp.so | `gamepoker.bytes` | AllgamepokerDatas | `0x06CC8E94` |
| CN 6.1.0 | libil2cpp.so | `gamequiz.bytes` | AllgamequizDatas | `0x06CCA4E4` |
| CN 6.1.0 | libil2cpp.so | `garden.bytes` | AllgardenDatas | `0x06F2E064` |
| CN 6.1.0 | libil2cpp.so | `generalactivity.bytes` | AllgeneralactivityDatas | `0x06F3FEFC` |
| CN 6.1.0 | libil2cpp.so | `getgift.bytes` | AllgetgiftDatas | `0x07013304` |
| CN 6.1.0 | libil2cpp.so | `guide.bytes` | AllguideDatas | `0x07021CB8` |
| CN 6.1.0 | libil2cpp.so | `hcexchange.bytes` | AllhcexchangeDatas | `0x0702AEE4` |
| CN 6.1.0 | libil2cpp.so | `homeland.bytes` | AllhomelandDatas | `0x0733A4E0` |
| CN 6.1.0 | libil2cpp.so | `iceland.bytes` | AllicelandDatas | `0x0702F1A8` |
| CN 6.1.0 | libil2cpp.so | `initpackage.bytes` | AllinitpackageDatas | `0x070431D8` |
| CN 6.1.0 | libil2cpp.so | `inquiry.bytes` | AllinquiryDatas | `0x07045190` |
| CN 6.1.0 | libil2cpp.so | `interactive.bytes` | AllinteractiveDatas | `0x06E48CD8` |
| CN 6.1.0 | libil2cpp.so | `inves.bytes` | AllinvesDatas | `0x06E4F7D8` |
| CN 6.1.0 | libil2cpp.so | `investigation.bytes` | AllinvestigationDatas | `0x06E56D1C` |
| CN 6.1.0 | libil2cpp.so | `invitation.bytes` | AllinvitationDatas | `0x06E350FC` |
| CN 6.1.0 | libil2cpp.so | `island.bytes` | AllislandDatas | `0x06E38470` |
| CN 6.1.0 | libil2cpp.so | `item.bytes` | AllitemDatas | `0x0687E734` |
| CN 6.1.0 | libil2cpp.so | `kitchen.bytes` | AllkitchenDatas | `0x06883934` |
| CN 6.1.0 | libil2cpp.so | `level.bytes` | AlllevelDatas | `0x0688F2FC` |
| CN 6.1.0 | libil2cpp.so | `live2d.bytes` | Alllive2dDatas | `0x0747E200` |
| CN 6.1.0 | libil2cpp.so | `longtimecard.bytes` | AlllongtimecardDatas | `0x06E6B08C` |
| CN 6.1.0 | libil2cpp.so | `mainlineCountdown.bytes` | AllmainlineCountdownDatas | `0x06E6F12C` |
| CN 6.1.0 | libil2cpp.so | `match.bytes` | AllmatchDatas | `0x06E75A28` |
| CN 6.1.0 | libil2cpp.so | `minigame.bytes` | AllminigameDatas | `0x06FB3330` |
| CN 6.1.0 | libil2cpp.so | `miscgoto.bytes` | AllmiscgotoDatas | `0x06FB9650` |
| CN 6.1.0 | libil2cpp.so | `month.bytes` | AllmonthDatas | `0x0727A60C` |
| CN 6.1.0 | libil2cpp.so | `negotiation.bytes` | AllnegotiationDatas | `0x0727DED4` |
| CN 6.1.0 | libil2cpp.so | `newbie.bytes` | AllnewbieDatas | `0x0728BE68` |
| CN 6.1.0 | libil2cpp.so | `newMessage.bytes` | AllnewMessageDatas | `0x0728E6BC` |
| CN 6.1.0 | libil2cpp.so | `notification.bytes` | AllnotificationDatas | `0x0729100C` |
| CN 6.1.0 | libil2cpp.so | `observe.bytes` | AllobserveDatas | `0x07155BC8` |
| CN 6.1.0 | libil2cpp.so | `oldPlayerReturn.bytes` | AlloldPlayerReturnDatas | `0x07160D84` |
| CN 6.1.0 | libil2cpp.so | `osdata.bytes` | AllosdataDatas | `0x06710268` |
| CN 6.1.0 | libil2cpp.so | `packageRelation.bytes` | AllpackageRelationDatas | `0x06716040` |
| CN 6.1.0 | libil2cpp.so | `parable.bytes` | AllparableDatas | `0x0671C550` |
| CN 6.1.0 | libil2cpp.so | `personal.bytes` | AllpersonalDatas | `0x0672A1FC` |
| CN 6.1.0 | libil2cpp.so | `pet.bytes` | AllpetDatas | `0x06EA66E8` |
| CN 6.1.0 | libil2cpp.so | `phone.bytes` | AllphoneDatas | `0x07084610` |
| CN 6.1.0 | libil2cpp.so | `photo.bytes` | AllphotoDatas | `0x070997C0` |
| CN 6.1.0 | libil2cpp.so | `playerbirthday.bytes` | AllplayerbirthdayDatas | `0x0709CFBC` |
| CN 6.1.0 | libil2cpp.so | `polaroid.bytes` | AllpolaroidDatas | `0x03788B64` |
| CN 6.1.0 | libil2cpp.so | `postcard.bytes` | AllpostcardDatas | `0x0378C4A0` |
| CN 6.1.0 | libil2cpp.so | `profession.bytes` | AllprofessionDatas | `0x0379983C` |
| CN 6.1.0 | libil2cpp.so | `railcruise.bytes` | AllrailcruiseDatas | `0x071A9010` |
| CN 6.1.0 | libil2cpp.so | `reputation.bytes` | AllreputationDatas | `0x06FEBE04` |
| CN 6.1.0 | libil2cpp.so | `richman.bytes` | AllrichmanDatas | `0x06CF8F88` |
| CN 6.1.0 | libil2cpp.so | `role.bytes` | AllroleDatas | `0x06FFAF50` |
| CN 6.1.0 | libil2cpp.so | `rpgminigame.bytes` | AllrpgminigameDatas | `0x07002888` |
| CN 6.1.0 | libil2cpp.so | `scrabble.bytes` | AllscrabbleDatas | `0x070080AC` |
| CN 6.1.0 | libil2cpp.so | `search2D.bytes` | Allsearch2DDatas | `0x0731CB60` |
| CN 6.1.0 | libil2cpp.so | `setting.bytes` | AllsettingDatas | `0x07321988` |
| CN 6.1.0 | libil2cpp.so | `shop.bytes` | AllshopDatas | `0x07325B50` |
| CN 6.1.0 | libil2cpp.so | `sound.bytes` | AllsoundDatas | `0x07331F14` |
| CN 6.1.0 | libil2cpp.so | `sourcepath.bytes` | AllsourcepathDatas | `0x073348D8` |
| CN 6.1.0 | libil2cpp.so | `splash.bytes` | AllsplashDatas | `0x071B292C` |
| CN 6.1.0 | libil2cpp.so | `story.bytes` | AllstoryDatas | `0x071B5CE0` |
| CN 6.1.0 | libil2cpp.so | `task.bytes` | AlltaskDatas | `0x06D78050` |
| CN 6.1.0 | libil2cpp.so | `tbrpg.bytes` | AlltbrpgDatas | `0x06D7D834` |
| CN 6.1.0 | libil2cpp.so | `tbrpgmap.bytes` | AlltbrpgmapDatas | `0x06D86010` |
| CN 6.1.0 | libil2cpp.so | `temporary.bytes` | AlltemporaryDatas | `0x06D86D18` |
| CN 6.1.0 | libil2cpp.so | `text.bytes` | AlltextDatas | `0x0722A32C` |
| CN 6.1.0 | libil2cpp.so | `timelineShow.bytes` | AlltimelineShowDatas | `0x0723AC1C` |
| CN 6.1.0 | libil2cpp.so | `tower.bytes` | AlltowerDatas | `0x0723CBAC` |
| CN 6.1.0 | libil2cpp.so | `train.bytes` | AlltrainDatas | `0x069BB820` |
| CN 6.1.0 | libil2cpp.so | `translationcn.bytes` | AlltranslationcnDatas | `0x0699A428` |
| CN 6.1.0 | libil2cpp.so | `translationen.bytes` | AlltranslationenDatas | `0x069A22D8` |
| CN 6.1.0 | libil2cpp.so | `translationjp.bytes` | AlltranslationjpDatas | `0x069AA188` |
| CN 6.1.0 | libil2cpp.so | `translationkr.bytes` | AlltranslationkrDatas | `0x069B2038` |
| CN 6.1.0 | libil2cpp.so | `translationtw.bytes` | AlltranslationtwDatas | `0x06B364C0` |
| CN 6.1.0 | libil2cpp.so | `urbanlegend.bytes` | AllurbanlegendDatas | `0x06C4D884` |
| CN 6.1.0 | libil2cpp.so | `vip.bytes` | AllvipDatas | `0x071D45D8` |
| CN 6.1.0 | libil2cpp.so | `wallet.bytes` | AllwalletDatas | `0x071D7D10` |
| CN 6.1.0 | libil2cpp.so | `weakguide.bytes` | AllweakguideDatas | `0x071DB218` |
| CN 6.1.0 | libil2cpp.so | `whisper.bytes` | AllwhisperDatas | `0x071DBEF8` |
| CN 6.1.0 | libil2cpp.so | `wiki.bytes` | AllwikiDatas | `0x071E2970` |

# 资源封包格式与 mr0k 解密

## 适用范围与记号

本文说明 **CN 6.1.0、ARM64** 客户端的资源封包。资源映射和 PB 验签位于 `libil2cpp.so`，UnityFS 压缩适配、mr0k 及其初始化材料位于 `libunity.so`。其他版本不能直接沿用本文的地址、静态表或派生材料。

所有 RVA 都相对所属模块加载基址：`运行时地址 = 模块基址 + RVA`，不是 ELF 文件偏移。各张地址表均明确标注版本和模块。

- `BE16/BE32/BE64`：大端整数；`LE32/LE64`：小端整数。
- `i16/i32/i64` 表示有符号整数，`u16/u32/u64` 表示无符号整数。
- `data[a:b]` 包含偏移 a，不包含偏移 b；偏移和长度均以字节计。
- `XOR` 为逐字节或同宽整数异或；64 位加法按 `mod 2^64` 截断。
- 公式中 `read_le64(bytes)` 读出小端 u64，`pack_le64(value)` 将 u64 写成八字节；大端写出用 `pack_be64`，`||` 表示字节串连接。
- SHA-256 参考值用于核对实现，不是封包自带的字段。

## 资源层次与加载链

```text
XMF 索引
    -> BLK 文件及逻辑文件的 offset / length / MD5
    -> BLK[offset : offset + length]
        -> 普通文件：保留原始字节
        -> PBStaticConfigure：RSA-SHA1 验签 -> 移除签名 -> 表内容
        -> AB：UnityFS 头 -> 压缩块信息及节点目录
            -> 各压缩块独立解码，类型 5 大块包含 mr0k
            -> 拼接解压数据 -> 按节点目录切出 SerializedFile 等内容
```

**BLK 不是整体加密的 AB，也不是带统一文件头的压缩包。** 它是多个逻辑资源的字节集合，边界由 XMF 决定。mr0k 位于逻辑 AB 内部的特定 UnityFS 压缩块，不能对整个 BLK 或整个 AB 直接执行 mr0k 解密。

| 版本 | 模块 | RVA | 入口或职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x02C40C1C` | `FileMapGroupInfo.ReadFromByteBuf`，读取 XMF |
| CN 6.1.0 | libil2cpp.so | `0x02C43658` | `FileMapSystem.InitFileMapInfo`，建立资源映射 |
| CN 6.1.0 | libil2cpp.so | `0x02C44DFC` / `0x02C44F84` | `FileMapSystem.GetFileBytes`，读取逻辑文件切片 |
| CN 6.1.0 | libil2cpp.so | `0x02C4412C` / `0x02C44688` | 同步及异步 `LoadBundleFromFile`，按映射加载 AB |
| CN 6.1.0 | libil2cpp.so | `0x0603081C` | `RSASignedLoader.RSACheckContent`，验证并移除签名 |
| CN 6.1.0 | libunity.so | `0x003C0254` | UnityFS 压缩器工厂 |
| CN 6.1.0 | libunity.so | `0x003C0444` | 压缩类型 5 包装，选择普通 LZ4 或 mr0k 分支 |

## XMF 索引格式

### 整体布局

XMF 使用大端整数。文件开头 16 字节是余下全部字节的 MD5：

```text
xmf[0x00:0x10] == MD5(xmf[0x10:])
```

| 顺序 / 偏移 | 类型 | 字段 | 含义 |
| --- | --- | --- | --- |
| `0x00` | 16 bytes | `MD51 + MD52` | 索引主体 MD5 的原始 16 字节 |
| `0x10` | BE i32 | `Version_Major` | 索引格式主版本，本文为 2 |
| `0x14` | BE i32 | `Version_Minor` | 索引次版本 |
| `0x18` | BE i32 | `Version_Build` | 索引构建版本 |
| `0x1C` | BE i32 | `block_count` | 后续块记录数量 |
| `0x20` 起 | 变长 | 块记录数组 | 连续读取 block_count 项 |
| 块记录之后 | BE i32 | `file_count` | 后续逻辑文件记录数量 |
| 文件计数之后 | 变长 | 文件记录数组 | 连续读取 file_count 项，结束后应到达 EOF |

索引版本三元组不是客户端版本字符串。例如 AB 索引 `(2, 2, 891705)` 与 PB 索引 `(2, 2, 793850)` 都可属于 CN 6.1.0，但不能据此混用不同索引的块。

### 字符串与 MD5 编码

字符串格式是 `BE i16 字节长度 + UTF-8 字节`，无末尾 NUL；长度不是字符数量。合法空字符串长度为 0，负长度应拒绝。

MD5 相关的两个 long 在磁盘上是连续的 16 字节。构造名称时将两半当作无符号 64 位数，分别转成补足 16 位的小写十六进制，再连接，不能按有符号十进制格式化。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x046D926C` | `BytesTools.ByteBuf.ReadInt`，BE i32 |
| CN 6.1.0 | libil2cpp.so | `0x046D940C` | `BytesTools.ByteBuf.ReadLong`，BE i64 |
| CN 6.1.0 | libil2cpp.so | `0x046D97A4` | `BytesTools.ByteBuf.ReadShort`，BE i16 |
| CN 6.1.0 | libil2cpp.so | `0x046DA0DC` | `BytesTools.ByteBuf.ReadUTF8`，带 short 长度前缀 |

### 块记录

每项固定部分为 26 字节，另加字符串内容长度。

| 顺序 | 类型 | 字段 | 含义 |
| --- | --- | --- | --- |
| 1 | UTF-8 字符串 | `FileName` | 记录中的原始名称，可为空 |
| 2 | BE u64 | `FileName_MD51` | 映射块名称摘要的前半 |
| 3 | BE u64 | `FileName_MD52` | 映射块名称摘要的后半 |
| 4 | BE i32 | `Len` | 完整 BLK 长度，不是某个逻辑文件长度 |
| 5 | BE i32 | `FileBlockTag` | 资源块标签 |

映射块名称：

```text
hex16(FileName_MD51) + hex16(FileName_MD52) + ".blk"
```

完整块的 MD5 应等于名称中的 32 位十六进制摘要。重复块记录可以指向同一个名称，但其 Len 必须一致；负长度必须拒绝。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x02C3FC74` | `FileMapBlockFileInfo.ReadFromByteBuf` |
| CN 6.1.0 | libil2cpp.so | `0x02C40048` | `FileMapBlockFileInfo.GetMappedFileName` |

### 逻辑文件记录

每项固定部分为 66 字节，另加文件名字符串内容长度。

| 顺序 | 类型 | 字段 | 含义 |
| --- | --- | --- | --- |
| 1 | UTF-8 字符串 | `FileName` | 逻辑文件名，可能含目录及扩展名 |
| 2 | BE u64 | `FileName_MD51` | 逻辑文件名称摘要前半 |
| 3 | BE u64 | `FileName_MD52` | 逻辑文件名称摘要后半 |
| 4 | BE u64 | `FileData_MD51` | 逻辑文件原始内容 MD5 前半 |
| 5 | BE u64 | `FileData_MD52` | 逻辑文件原始内容 MD5 后半 |
| 6 | BE i32 | `FileTag` | 文件标签，不是 UnityFS 压缩类型 |
| 7 | BE i32 | `Offset` | 该文件在所属 BLK 中的起始偏移 |
| 8 | BE i32 | `Len` | 该文件的原始字节长度 |
| 9 | BE u64 | `MapedFileName_MD51` | 所属 BLK 名称摘要前半 |
| 10 | BE u64 | `MapedFileName_MD52` | 所属 BLK 名称摘要后半 |
| 11 | BE i32 | `Version_Build` | 文件记录的构建版本 |

其中 MapedFileName 沿用客户端字段拼写。由它的两半摘要构造所属 `.blk` 名称，并执行：

```text
raw_file = blk[Offset : Offset + Len]
MD5(raw_file) == pack_be64(FileData_MD51) || pack_be64(FileData_MD52)
```

读取时必须检查所属块存在于索引、偏移和长度非负、`Offset + Len <= block.Len`、逻辑文件名不重复。文件名摘要与内容摘要是不同字段，不能拿前者校验资源内容。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x02C41408` | `FileMapInfo.ReadFromByteBuf` |
| CN 6.1.0 | libil2cpp.so | `0x02C41A34` | `FileMapInfo.GetMappedFileName` |

## BLK 切片与资源分类

BLK 没有要求统一的 magic、目录区或加密头。不能以扫描 UnityFS、mr0k 或 RSA 签名字节来代替索引切片，也不能假定每个文件紧接上一个文件。

处理顺序是：验证 XMF MD5，验证完整 BLK 的长度及 MD5，再按每条记录的 Offset/Len 切片并验证切片 MD5。切片 MD5 对应**变换前**的文件：PB 包含签名，AB 包含原始 UnityFS 头和压缩数据。

- PBStaticConfigure 的切片按签名文件处理。
- 以 `UnityFS\0` 开始的切片按 AB 处理；声明为 `.ab` 却没有该头，应报格式错误。
- XML 等普通文件直接保留切片字节，不能因为来自 AB 分组就强制按 UnityFS 解码。
- 缺块、块摘要不匹配、切片摘要不匹配分别是来源、版本或边界问题，不能靠修改解密材料修复。

## PBStaticConfigure 签名格式

### 文件布局与验证

```text
offset 0x00 : 128 字节 RSA 签名
offset 0x80 : 原始表内容，长度可为 0
```

采用 **RSA1024、PKCS#1 v1.5、SHA1**。签名验证覆盖 `data[0x80:]`，成功后返回该部分。它不是 RSA 私钥解密，也没有额外 AES 解密；`.bytes` 只是扩展名，内容可能是 Protobuf、JSON 或合法空内容。

验证算法：令 `s = BE整数(data[0:128])`，要求 `s < n`，计算 `EM = BE128(pow(s, e, n))`。EM 必须严格匹配：

```text
00 01 || FF * 90 || 00 || DigestInfo_SHA1 || SHA1(data[128:])
DigestInfo_SHA1 = 3021300906052b0e03021a05000414
```

长度正好为 128 字节的文件也必须对空内容验签，不能仅因没有正文而拒绝。只提取签名里的摘要而不与正文 SHA1 比较，不构成验签。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libil2cpp.so | `0x06030114` | `RSASignedLoader.InstanceInit`，初始化 RSA 和 SHA1 |
| CN 6.1.0 | libil2cpp.so | `0x0603058C` | `RSASignedLoader.RsaVerify` |
| CN 6.1.0 | libil2cpp.so | `0x0603081C` | `RSASignedLoader.RSACheckContent` |
| CN 6.1.0 | libil2cpp.so | `0x0A726CC8` | RSA 公钥字符串材料 |

### 公钥编码

公钥材料是 Base64 编码的 Windows CryptoAPI PUBLICKEYBLOB，不是 PEM。解码后的结构使用小端整数：

| 偏移 | 长度 | 字段 | 值 |
| --- | --- | --- | --- |
| `0x00` | 1 | `bType` | `0x06`，PUBLICKEYBLOB |
| `0x01` | 1 | `bVersion` | `0x02` |
| `0x02` | 2 | `reserved` | 0 |
| `0x04` | 4 | `aiKeyAlg` | `0x0000A400` |
| `0x08` | 4 | `magic` | `0x31415352`，字节为 RSA1 |
| `0x0C` | 4 | `bitlen` | 1024 |
| `0x10` | 4 | `pubexp` | 65537，即 `0x10001` |
| `0x14` | 128 | `modulus` | 小端模数，转换后才作为 RSA 整数使用 |

CN 6.1.0 的模数 n，以下按**大端整数十六进制**表示，各行直接连接：

```text
be90deb9d80142d42a805ae19143ba46df5312f4cf7ad6756278348458de414f5
386efabf83ebaa0ae2288cf8419820a238b83b3642a63eb820488abf0603d1c6e
7ad23325d98931a51d3145d038ea16206ba4152c5ecc13abcb32baa38617c30d
7d83f1abe6b030096b7405ec2960d234bb49b919379548ec9d04b1951d7d25
```

## AB 的 UnityFS 格式

### 文件头

AB 使用 UnityFS 容器。以下整数均为大端，两个版本字符串以 NUL 结束，因此除起始字段外，头部偏移不是固定常数。

| 顺序 | 类型 | 字段 | 含义 |
| --- | --- | --- | --- |
| 1 | 8 bytes | `signature` | `UnityFS\0` |
| 2 | BE u32 | `format_version` | UnityFS 容器版本，不是 CN 6.1.0 |
| 3 | NUL 字符串 | `version_player` | Player 版本标识 |
| 4 | NUL 字符串 | `version_engine` | Unity 引擎版本标识 |
| 5 | BE u64 | `bundle_size` | 完整 AB 文件长度，必须与 XMF 切片长度一致 |
| 6 | BE u32 | `compressed_info_size` | 压缩后的块信息和目录长度 |
| 7 | BE u32 | `uncompressed_info_size` | 解压后的块信息和目录长度 |
| 8 | BE u32 | `archive_flags` | 信息区压缩类型及容器布局标志 |

`archive_flags & 0x3F` 是**信息区**的压缩类型，不是所有数据块的共同类型。`0x40` 表示块信息和目录合并，`0x80` 表示信息区位于文件末尾，否则信息区在头部之后。头部及数据起始的 16 字节对齐必须按容器和 Unity 引擎版本的规则处理，不能统一写死；尤其不能跨引擎版本误用 `0x200` 的加密 / 对齐标志含义。

### 解压后的信息区

```text
16 bytes uncompressed_data_hash
BE i32   block_count
block_count * BlockInfo
BE i32   node_count
node_count * NodeInfo
```

uncompressed_data_hash 是 UnityFS 自身的 16 字节字段，不是 XMF MD5，也不能当作 mr0k 密钥。本解析流程不依赖它判断切片正确性。

每个 BlockInfo 长 10 字节：

| 类型 | 字段 | 含义 |
| --- | --- | --- |
| BE u32 | `uncompressed_size` | 当前块解压后的长度 |
| BE u32 | `compressed_size` | 当前块在 AB 中占用的原始长度 |
| BE u16 | `flags` | 当前块压缩类型取 `flags & 0x3F` |

每个 NodeInfo：

| 类型 | 字段 | 含义 |
| --- | --- | --- |
| BE i64 | `offset` | 在所有解压块拼接数据中的偏移 |
| BE i64 | `size` | 节点字节长度 |
| BE u32 | `flags` | 节点标志，保留原值 |
| NUL UTF-8 字符串 | `name` | 节点名称 |

按顺序读取每块的 compressed_size 字节，独立解码到 uncompressed_size 字节，再连接为一个数据流。节点切片使用这个**解压后**数据流的偏移，不是 BLK 偏移或 AB 文件偏移。每个节点必须满足 `offset >= 0`、`size >= 0`、`offset + size <= 解压数据总长`。

### 压缩类型

| 类型 | 解码方式 |
| --- | --- |
| 0 | 无压缩，直接使用块字节 |
| 1 | 标准 UnityFS LZMA，交由对应标准解码器处理 |
| 2 / 3 | 原始 LZ4 block；3 为 LZ4HC 编码，解码方式相同 |
| 5，小块 | 原始 LZ4 block，不经过 mr0k |
| 5，大块 | mr0k 预处理 -> 固定前缀 XOR -> 原始 LZ4 block |

本文的特殊适配是类型 5；不能将未知类型默认为 LZ4。这里的 LZ4 是 block 格式，不是带 magic 和帧头的 LZ4 frame，也不能在解码前额外读取四字节“原始长度”。期望长度来自 UnityFS 信息区。

CN 6.1.0 `libunity.so` RVA `0x003C0444` 使用 `UBFX X9, X2, #16, #16` 判断输入压缩长度 C 的 bits 16..31。对于正常 u32 长度，`C < 0x10000` 走普通 LZ4；`C >= 0x10000` 走 mr0k。判定依据是**压缩长度**，不是解压长度。LZ4 包装还检查输入和输出长度不超过 `0x7FFFFFFE`。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x003C03B8` | 类型 2/3 LZ4 包装 |
| CN 6.1.0 | libunity.so | `0x003C0444` | 类型 5 分支及 LZ4 调用 |
| CN 6.1.0 | libunity.so | `0x007D3C74` | 按需初始化后进入 mr0k 预处理 |
| CN 6.1.0 | libunity.so | `0x00C2FF94` / `0x00BE9064` | mr0k 入口及处理主体 |
| CN 6.1.0 | libunity.so | `0x007D3C28` | 预处理结果前 3072 字节的固定 XOR |
| CN 6.1.0 | libunity.so | `0x0091C380` | 原始 LZ4 block 解码 |

## mr0k 初始化材料

### 静态表与种子

mr0k 使用确定性初始化材料，不从 XMF 版本、BLK 名称或用户账号派生密钥。下列地址对应 CN 6.1.0 的原始静态表，读取的是表字节，不是模块内的指针值。

| 版本 | 模块 | RVA | 长度 | 材料 |
| --- | --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x015D8B4C` | `0x1000` | `SOURCE`，轮材料及头掩码源表 |
| CN 6.1.0 | libunity.so | `0x015D9B4C` | `0x1000` | `XOR_TABLE`，固定混合表 |
| CN 6.1.0 | libunity.so | `0x015DC2D8` | `0x80` | 正向 ShiftRows，16 个 LE u64 下标 |
| CN 6.1.0 | libunity.so | `0x015DC358` | `0x100` | 编码后的正向 S-box |
| CN 6.1.0 | libunity.so | `0x015DD458` | `0x80` | 逆向 ShiftRows，16 个 LE u64 下标 |
| CN 6.1.0 | libunity.so | `0x015DD4D8` | `0x100` | 编码后的逆向 S-box |
| CN 6.1.0 | libunity.so | `0x015DD5D8` | `0x400` | 逆向 T-table 0，256 个 LE u32 |
| CN 6.1.0 | libunity.so | `0x015DD9D8` | `0x400` | 逆向 T-table 1 |
| CN 6.1.0 | libunity.so | `0x015DDDD8` | `0x400` | 逆向 T-table 2 |
| CN 6.1.0 | libunity.so | `0x015DE1D8` | `0x400` | 逆向 T-table 3 |

正向 T-table 0..3 位于 CN 6.1.0 `libunity.so` RVA `0x015DC458`、`0x015DC858`、`0x015DCC58`、`0x015DD058`，每张长度 `0x400`；mr0k 解密不需要这些正向表。

| 版本 | 模块 | RVA | 初始化常量或职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00BE08F4` | mr0k 上下文初始化主体 |
| CN 6.1.0 | libunity.so | `0x00BE1884` | 轮材料种子 `0x86DDC8` |
| CN 6.1.0 | libunity.so | `0x00BE0D5C` | 编码辅助种子 `0x46BE28`，不代替轮材料种子 |
| CN 6.1.0 | libunity.so | `0x00BE20E0` | bootstrap 种子 `0x4D867C`，不参与下述头掩码公式 |
| CN 6.1.0 | libunity.so | `0x0187B2F8` | 固定字符串的编码存储位置 |
| CN 6.1.0 | libunity.so | `0x0187BE34` | 字符串解码的 8 字节掩码材料 |
| CN 6.1.0 | libunity.so | `0x00C22448` | 固定字符串解码 |

解码后的固定字符串为 15 字节 ASCII `miHoYo Co.,Ltd.`，十六进制为 `6d69486f596f20436f2e2c4c74642e`，末尾 NUL 不参与材料生成。

### MT19937-64

使用标准 **MT19937-64**，不是 Python random 使用的 MT19937-32。

| 参数 | 值 |
| --- | --- |
| 状态字数 / 每字宽度 | 312 / 64 bit |
| twist 间距 | 156 |
| 状态展开乘数 | `0x5851F42D4C957F2D` |
| twist 常量 | `0xB5026F5AA96619E9` |
| 拼接高 / 低位掩码 | `0xFFFFFFFF80000000` / `0x7FFFFFFF` |
| tempering 1 | `x ^= (x >> 29) & 0x0000000555555555` |
| tempering 2 | `x ^= (x << 17) & 0x71D67FFFEDA60000` |
| tempering 3 | `x ^= (x << 37) & 0xFFF7EEE000000000` |
| tempering 4 | `x ^= x >> 43` |

状态展开为 `state[0] = seed`，`state[i] = f * (state[i-1] XOR (state[i-1] >> 62)) + i mod 2^64`。每次初始化后先 twist 再输出；参考向量：种子 5489 的首个输出为 `14514284786278117030`。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00C2F194` / `0x00C2F358` | MT19937-64 初始化及状态展开 |
| CN 6.1.0 | libunity.so | `0x00C2F244` | twist、tempering、输出 |

### 生成 32 字节种子材料

设 `G = MT19937_64(0x86DDC8)`，next(G) 返回一个 u64：

```text
M = pack_le64(next(G)) || pack_le64(next(G)) || pack_le64(next(G)) || pack_le64(next(G))
p = next(G) % (32 - 15)                 # 即 % 17
M[p : p + 15] = ASCII("miHoYo Co.,Ltd.")
for j in 0, 8, 16, 24:
    M[j : j + 8] = pack_le64(read_le64(M[j : j + 8]) XOR next(G))
```

同一个 G 共消耗九次输出，不能在插入字符串后重新初始化；插入位置不是 `% 32`，也不是把字符串追加到 32 字节之后。仅复刻固定正 int32 种子的确定性路径，不需要执行引擎的随机初始化。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00BE37D8` | 32 字节种子材料生成主体 |
| CN 6.1.0 | libunity.so | `0x00BE5DAC` | 生成初始 32 字节 |
| CN 6.1.0 | libunity.so | `0x00BE3A48` | 选择字符串覆盖位置 |
| CN 6.1.0 | libunity.so | `0x00BE4DF0` | 继续取四个 qword 并异或 |

### 派生轮材料、头掩码和流表

另行初始化 `H = MT19937_64(read_le64(M[0:8]))`，先消费一次输出：

```text
offset = next(H) & 0x1FF
E[k] = SOURCE[offset + k] XOR XOR_TABLE[k]       # k = 0..0xAFF
R[j] = XOR(E[16*j : 16*j + 16])                 # j = 0..175
K[i] = SOURCE[0xB00 + 2*offset + i]
       XOR XOR_TABLE[2*offset + i]
       XOR M[16 + i]                            # i = 0..15
T = pack_le64(next(H)) || ... || pack_le64(next(H))  # 继续取 128 次
```

- R 是 176 字节，即 11 组 16 字节独立轮材料；源表轮材料区使用 offset，不是 2*offset。
- K 是 16 字节头掩码，只有此公式使用 2*offset。最后一项来自轮材料种子生成的 M，不是 bootstrap 材料或资源头。
- T 是 1024 字节固定流表。H 选完 offset 后继续输出，不能重新播种，也不能重新取首个输出。
- 引擎轮材料的每个逻辑字节以 16 字节 XOR 编码保存；同一 qword 编码盐在两半出现，解码时抵消。

头掩码来源的直接证据是 CN 6.1.0 `libunity.so` RVA `0x00BE189C` 的 `MOV X24, X27`，以及 RVA `0x00BE13CC` / `0x00BE13D0` 从 `X24 + 16 + i` 取字节。不能用初始化入口参数的表面名称推断其来源。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00BE18E4` / `0x00BE18F0` | SOURCE + offset |
| CN 6.1.0 | libunity.so | `0x00BE0BB4` | 轮材料循环，0x160 个 qword，即 0xB00 字节 |
| CN 6.1.0 | libunity.so | `0x00BE13CC` / `0x00BE13D0` | 头掩码中 M 的读取 |
| CN 6.1.0 | libunity.so | `0x00BE1EFC` / `0x00BE1DE0` | 保存并恢复同一个 H 的状态指针 |
| CN 6.1.0 | libunity.so | `0x00BE0C44` | 写入流表 qword |
| CN 6.1.0 | libunity.so | `0x00FE3D54` / `0x00FE4E28` | 字节的 16 字节编码及 XOR 解码 |

### 编码辅助掩码与 ChaCha20

引擎在编码状态上使用辅助流掩码。CN 6.1.0 `libunity.so` RVA `0x01316F3C` 和 `0x013170D0` 构造相同的 64 字节状态，RVA `0x01316FB0` 执行按字节 XOR；核心 RVA `0x01317144` 使用加法、XOR、16/12/8/7 位旋转及十次双轮，为 ChaCha20 结构。

其初始常量位于 CN 6.1.0 `libunity.so` RVA `0x0161784A`，原始 16 字节的十六进制是 `deadcafefaceb00cdeadcafefaceb00c`，不是 ASCII 字符串或标准 sigma。按四个 LE u32 读取为 `0xFECAADDE, 0x0CB0CEFA, 0xFECAADDE, 0x0CB0CEFA`。

这是引擎内部编码表示的辅助机制，不是 AB 解密后还要执行的一层资源 ChaCha20。在还原为逻辑字节并消去成对掩码后，资源算法直接使用 R、K、T。不能额外对 LZ4 输入执行一次标准 ChaCha20，也不能把这个辅助状态当作资源密钥。

## mr0k 的 16 字节逆向变换

Inv(block, R) 接受一个 16 字节块和 176 字节轮材料。它采用 AES 的逆向字节及列操作，但轮材料应视为独立数据，**不要求 R 符合由一个标准 AES key 展开的轮密钥**；不能直接把 R 的前 16 字节交给标准 AES API 代替整个变换。

编码 S-box 的还原规则是：

```text
S[i] = stored_sbox[i] XOR i XOR 0xFF
```

逆向 S-box 开头为 `52 09 6a d5 30 36 a5 38`。逆向 ShiftRows 的 16 个 LE u64 下标还原后为：

```text
0, 13, 10, 7, 4, 1, 14, 11, 8, 5, 2, 15, 12, 9, 6, 3
```

操作顺序：

```text
state = block XOR R[0:16]
for round in 1..10:
    state[i] = inverse_sbox[old_state[inverse_shift[i]]]
    if round < 10:
        state = InvMixColumns(state)
    state = state XOR R[16*round : 16*(round+1)]
return state
```

InvMixColumns 以连续四字节为一列，在 GF(2^8) 上使用 AES 多项式 `0x11B`，矩阵各行为 `(14,11,13,9)`、`(9,14,11,13)`、`(13,9,14,11)`、`(11,13,9,14)`。逆向 T 表各项与对应标准逆向表之间存在同一固定 XOR `0x07128419`；四表合并时该常量出现四次并抵消，可直接使用标准 InvMixColumns 运算。

| 版本 | 模块 | RVA | 职责 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00FE45EC` / `0x00FE4668` | 编码状态上的 16 字节逆向变换 |
| CN 6.1.0 | libunity.so | `0x00FE4784` | 逆向 T-table / InvMixColumns 合并 |
| CN 6.1.0 | libunity.so | `0x00FE4A58` | S-box 编码还原 |
| CN 6.1.0 | libunity.so | `0x00FE4C68` / `0x00FE4D44` | 方向 0 选择逆向表，方向 1 选择正向表 |

## mr0k 块布局与完整解密

### 原始块布局

设原始压缩块为 B，长度为 N。类型 5 大块必须具备 mr0k magic，不能仅凭块尺寸就将任意字节当作合法 mr0k。

| 原始块偏移 | 长度 | 角色 |
| --- | --- | --- |
| `0x00` | 4 | ASCII mr0k |
| `0x04` | 16 | 第一字段 A，送入逆向变换 |
| `0x14` | `0x60` | 中间压缩流字节，保留；不作为额外头部丢弃 |
| `0x74` | 16 | 第二字段 B2，参与头部混合 |
| `0x84` | 16 | 第三字段 C3，送入逆向变换并回写混合结果 |
| `0x94` 起 | 变长 | 后续数据，其中有限前缀执行 qword XOR |

这不是一个应整体删除的 0x94 字节头。预处理结束只移除 **0x14 字节**，原始偏移 0x14 之后仍属于要送入 LZ4 的压缩流。

### 第一步：变换三个字段

```text
a = Inv(B[0x04:0x14], R)
b = B[0x74:0x84] XOR K
c = Inv(B[0x84:0x94], R)
f = a XOR b
g = c XOR b XOR f = c XOR a
result = copy(B)
result[0x84:0x94] = g
```

两次逆向变换分别处理第一和第三字段，不是第一和第二字段；a、b、f 是临时计算值，回写原始块的是 g。第二字段掩码 K 对应引擎初始化上下文 `+0xE38` 的 16 字节材料，此数值是结构偏移，不是模块 RVA。

CN 6.1.0 `libunity.so` RVA `0x00BE7FCC` / `0x00BF3EBC` 的辅助调用不变换输入字段，不是额外 AES 层。

| 版本 | 模块 | RVA | 操作 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00BE92A4` | 第一字段逆向变换 |
| CN 6.1.0 | libunity.so | `0x00BEB65C` | 第二字段与上下文头掩码混合 |
| CN 6.1.0 | libunity.so | `0x00BE9E00` | 第三字段逆向变换 |
| CN 6.1.0 | libunity.so | `0x00BEA768` | 计算 f |
| CN 6.1.0 | libunity.so | `0x00BECB38` / `0x00BEBF34` | 计算 g |
| CN 6.1.0 | libunity.so | `0x00BEBE98` | 回写 g，共 16 字节 |

### 第二步：有限范围 qword XOR

```text
seed = (read_le64(b[0:8]) + N - 0x14) mod 2^64
salt = read_le64(f[0:8]) XOR read_le64(g[0:8]) XOR seed
L = min(((N - 0x94) // 0x80) * 0x10, 0x400)
for j in 0, 8, 16, ..., L-8:
    x = read_le64(result[0x94+j : 0x94+j+8])
    x = x XOR salt XOR read_le64(T[j : j+8])
    result[0x94+j : 0x94+j+8] = pack_le64(x)
```

L 是**处理字节数**，不是 qword 个数；最多处理 0x400 字节、128 个 qword。公式先向下取整到完整 0x80 字节组，再乘 0x10，不是直接处理全部剩余数据或前 1024 字节。未覆盖的数据保持原样。

| 版本 | 模块 | RVA | 操作 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x00BEB310` | 第二字段低 qword 加 N - 0x14 |
| CN 6.1.0 | libunity.so | `0x00BEC9A8` | 计算处理长度及 0x400 上限 |
| CN 6.1.0 | libunity.so | `0x00BEC604` | 将处理字节数换算为 qword 循环次数 |
| CN 6.1.0 | libunity.so | `0x00BE9FC4` | 执行 qword XOR |

### 第三步：移除 20 字节并恢复压缩前缀

CN 6.1.0 `libunity.so` RVA `0x00BEC1A0` / `0x00BEBEB0` 返回 input + 0x14，有效压缩长度变为 N - 0x14。在这个**已移除前缀的结果**上执行：

```text
P = result[0x14:]
MASK = 257d020041c8030073a70500bf440700dd900800df690a00
for i in 0..3071:
    P[i] = P[i] XOR MASK[i % 24]
```

固定 XOR 覆盖 24 字节掩码的 128 次重复，总计 3072 字节；剩余部分不处理。不能先对 B 的前 3072 字节做 XOR，再删除 20 字节，这会改变掩码相位及覆盖范围。

| 版本 | 模块 | RVA | 材料或操作 |
| --- | --- | --- | --- |
| CN 6.1.0 | libunity.so | `0x0021F5D4` | 初始化 24 字节前缀掩码 |
| CN 6.1.0 | libunity.so | `0x0156A110` | 掩码前 16 字节静态材料 |
| CN 6.1.0 | libunity.so | `0x007D3C28` | 执行 24 字节循环 XOR |

掩码尾八字节来自小端立即数 `0x000A69DF000890DD`，即 `dd900800df690a00`。

### 第四步：LZ4 与长度验证

```text
decoded = LZ4_block_decompress(P, expected_size = BlockInfo.uncompressed_size)
len(decoded) == BlockInfo.uncompressed_size
```

LZ4 成功仅代表当前压缩块成功。完整 AB 还必须验证所有块、拼接数据、节点边界及 SerializedFile 对象原始数据边界。若类型 5 信息区走大块分支，也应用完全相同的 mr0k 流程，期望输出长度则取 uncompressed_info_size。

## 解压数据与 AB 重建

节点数据通常包括 Unity SerializedFile 及外部资源流。SerializedFile 的类型、对象表和引用属于另一层标准 Unity 格式，不由 XMF 或 mr0k 解释；应按其自身版本和字节序解析，不能把完整节点当成连续 Protobuf。

TextAsset 的 ClassID 为 49。当前资源对象中的名称和 m_Script 均为小端 u32 长度前缀字节串，字段结束后向上对齐到 4 字节；m_Script 必须按其原始长度保留，不添加 NUL、不做 JSON 格式化、不重新序列化 Protobuf。其他对象类型不能套用 TextAsset 的字段布局。

恢复可读 AB 时可以重建无压缩 UnityFS：保留容器版本字符串和节点名称、偏移、长度、flags，将全部已解压数据作为类型 0 的单块，信息区也不压缩，`archive_flags = 0x40`，重新计算信息区长度和完整文件长度。重建的信息区 16 字节 hash 可置零；节点内容逐字节保留，不重新序列化 Unity 对象。

因此重建 AB 与原始 AB 的完整文件 MD5 一般不同，这不代表失败。XMF 中记录的原始文件 MD5 应在变换前验证；变换后检查解压长度、节点字节及对象边界，不能要求重建文件再匹配原始 MD5。

## 参考向量

### CN 6.1.0 初始化材料

```text
轮材料种子 = 0x86DDC8
M = 8ec3911eaf3176bab6095d945b7966bceebb8bb3c4fefc876eeeeaf83284a89b
offset = 7
K = a1f27eb35edc88c7b66cd876d67bb269
SHA256(R) = 5f5e870816f019e22d592c5bee5b47f63b96277993879ceb56f8f8cf632bad2f
SHA256(T) = d4af5b33f3f2d9a3ef88e8303b7e5a9310ebdd60888b60cab0f28f70302cd4fd
```

R 的 176 字节十六进制，各行直接连接：

```text
2fe08914e8234ee6916deded8662851cd70f872b64f3e040dc27174cc2734e6d0
0e791044e14608d1ae8364fcffb50a75d89517bbbeb4f1e56a0b01f486786213
1f8a2b5ed90a446f14e36386303a98c05d32b17b2189334e0aa632e39997d083
30c3fb007eed2b68e0ab43da6bf77afbe1783c0832a5783b2a8f7a3dee6584c
a533f1e09b3d7bc7260b0e87aa10b85bcd9d010b6492a8e4de76a8e3ada2c6b
979bcecf737cf6c3d0d68b11efc384385
```

以上数值是公式推导结果，不应代替种子、静态表及调用顺序。

### 类型 5 大块与完整 AB

| 项目 | 值 |
| --- | --- |
| mr0k 原始压缩块长度 | 101,038 bytes |
| 移除前缀后的 LZ4 输入长度 | 101,018 bytes |
| 解压输出长度 | 131,072 bytes |
| 原始压缩块 SHA-256 | `eec4dc126e05fa11817e51a2b09978c07e8c1268084762eca63ac26091cbada3` |
| 解压块 SHA-256 | `515b79460de0c03877a709a0ec9a2ee5942be6a9cbf597013a68e9e1d8bbef67` |
| 所属逻辑 AB | `5415704bb4773e1d.ab` |
| 原始 AB 长度 | 203,676 bytes |
| 无压缩重建 AB 长度 | 585,646 bytes |
| 重建 AB 对象数量 | 721 |
| 重建 AB SHA-256 | `5bad4185f3fb171f6f6d76ca1539906760a07e7e77eb287144a1d1facfcece1b` |

该 AB 的五个数据块按 `(解压长度, 压缩长度, 类型)` 排列为：

```text
(131072,  39311, 3)
(131072,  15218, 3)
(131072,  32558, 3)
(131072, 101038, 5)
( 61155,  15386, 3)
```

## 完整性与支持边界

1. XMF 主体 MD5、完整块 MD5、原始文件切片 MD5 必须全部匹配，三个层级不能互相代替。
2. PB 必须严格通过 RSA-SHA1 验签，合法空正文也不例外。
3. AB 信息区和每个数据块的解压长度必须匹配，节点及对象数据不能越界。
4. 保留原始 AB、只通过其 MD5，不等于 mr0k 已解密或 Unity 对象已解析。
5. BLK 缺失或索引版本混用属于输入不完整，算法不能恢复不存在的字节。
6. CN 6.1.0 的确定性材料不能未经验证用于其他版本；本文不声明所有游戏分组均使用同一种签名或内容格式。
7. AB 容器恢复与 MonoBehaviour schema、Protobuf schema 等业务层解析相互独立；缺少业务 schema 不等于 mr0k 解密失败。

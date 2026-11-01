# AbUnPacker

反序列化 WD 的 `AssetBundleXMLData.xml` 目录表，默认解包二层 VFS 的全部文件和目录表资源。支持已解包 AB 和直接读取 XMF/BLK；BLK 模式复用相邻 `UnPacker` 的块校验和 UnityFS/mr0k 解码，中间 AB 不落盘。`--js-exporter` 才限制为 `.js`、`.js.map`、`.ts` TextAsset。

## 使用

在本目录安装依赖：`py -m pip install -r requirements.txt`。

```powershell
py -X utf8 main.py --input AB目录 --output 清单目录 --list-only
py -X utf8 main.py --index XMF文件或目录 --input BLK目录 --output 清单目录 --list-only
py -X utf8 main.py --input AB目录 --output 资源目录 --list 清单目录
py -X utf8 main.py --index XMF文件或目录 --input BLK目录 --output 资源目录 --list 清单目录
py -X utf8 main.py --input AB目录 --output 脚本目录 --list 清单目录 --js-exporter
py -X utf8 main.py --index XMF文件或目录 --input BLK目录 --output 脚本目录 --list 清单目录 --js-exporter
py -X utf8 main.py --input 单个AB文件 --output 少量资源目录
```

`--input` 为 AB 目录或单个 AB；有 `--index` 时必须为直接包含 `.blk` 的目录。XMF 目录优先匹配 BLK 目录名称，无法唯一匹配时需指定文件。

## 清单

`--list-only` 只写 `manifest.json`，内容就是目录表本身：根字段 `BundleInfos` 和其全部条目。保留所有资源，不按 JS 后缀过滤。不包含 XMF 信息、BLK locator、JS 导出列表、运行统计或报告，也不保存 NRBF 解码器添加的重复 `__class__` 标签。使用 UTF-8、两空格缩进的格式化 JSON。

BundleInfo 保留 `BundleName`、`BundleNameMD5Struct`、`IsComplexName`、`DependenceBundleName`、`BundleFileName`、`Assets`、`IsInPackageAsset`。Assets 保留 `AssetFullName`、`ResPath`。MD5Struct 的 `MD51/MD52` 保留原始有符号整数，依赖保留逻辑包名。

`--list-only` 读取目录表后直接返回，不遍历 AB 目录、不解码 AB。AB 模式在输入根目录（单 AB 为父目录）读取目录表；BLK 模式通过当前 XMF 读取同名切片。目录表缺失或损坏即报错，不扫描生成替代清单。

`--list` 接受上述 JSON 或其目录，直接按 `BundleFileName + ".ab"` 定位输入包，并按目录表资源路径读取对应容器的资源，不扫描整个输入目录或所有对象。AB 目录模式要求对应包直接位于输入根目录。BLK 定位来自当前 XMF，不存入目录清单；读取时仍校验当前 XMF、块和切片摘要。需要部分恢复时可使用单个 AB 输入，或仅保留目标 BundleInfos/Assets 的目录表 JSON。

所有模式都由目录表驱动；没有指定 `--list` 时读取 `AssetBundleXMLData.xml`。目录表缺失即报错，不扫描 AB 目录，不扫描对象。没有搜索或扫描参数。

资源导出的统计、正文摘要和错误写入独立 `report.json`，不覆盖或复制目录清单。

## 格式与 RVA

以下均为 **CN 6.1.0 ARM64，libil2cpp.so RVA**：

| RVA | 逻辑 |
| --- | --- |
| `0x03F4C874` | `AssetBundlePathResolver..cctor` 设置 `DependFileName = "AssetBundleXMLData.xml"`；字符串 `0x0A71D670` |
| `0x03F49820` | `LoadFileMapperConfig` 调用 `FileMapSystem.GetFileBytes(DependFileName)` |
| `0x03F4A3BC` | `ParseBundleConfig` 反序列化 AssetBundleTable，遍历 BundleInfos 和 Assets |
| `0x02B86B6C` | `Serializer.FromBytes` 使用 MemoryStream 和 BinaryFormatter.Deserialize；文件并非文本 XML |
| `0x03F4BC38` | 未热补丁的 `GetBundleFileNameWithLangExtension` 返回 `BundleFileName + ".ab"` |
| `0x05CACCA8` / `0x05CACD84` | TS loader 的路径修正/读取；前缀 `AssetBundles/Scripts/` 位于 `0x0A725340` |

AssetBundleTable 的 `+0x10` 是 BundleInfos。BundleInfo 的 `+0x18/+0x28/+0x30/+0x38/+0x40/+0x48` 分别是 MD5Struct、IsComplexName、依赖、文件名、Assets、包内标记。AssetData 的 `+0x10/+0x18` 是 AssetFullName/ResPath。引擎用包键建立包字典，遍历全部 ResPath 建立资源路径到包键的字典。Python 仅解析 NRBF 数据，不实例化 .NET 类型。

## 输出

默认模式不按资源类型或扩展名过滤。AB 内全部 CAB、`.resS` 等 VFS 节点原字节保存到 `__vfs/包名/`，保留未单独列入目录表的组件和流式资源。目录表的 TextAsset 正文按原路径保存，仅去掉开头的 `Assets/`；非文本主对象追加 `.serialized.bin`，报告记录 ClassID、类型、CAB 文件名和 PathID。它们是 Unity 序列化对象数据，不伪装成原始 PNG、prefab 等格式；完整 CAB 和配套资源流同时保留，可供后续解析。

`--js-exporter` 仅导出 `.js`、`.js.map`、`.ts` 正文，不输出 CAB 或其他资源。保留 BOM、换行、大小写；识别 `.js.txt/.js.map.txt/.ts.txt`，输出去掉最后的 `.txt`，并去掉开头的 `Assets/AssetBundles/Scripts/` 或 `AssetBundles/Scripts/`。

JS、map 和 TS 均只导出原始正文，不解析 map 或重建源码。`--list-only` 只生成格式化 JSON，即使指定 `--js-exporter` 也不导出资源或报告。

路径冲突进入 `__conflicts/`；已有不同内容拒绝覆盖，不清空输出目录。失败返回 1，成功返回 0。


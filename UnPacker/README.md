# Unpacker

CN 6.1.0 资源解析器：按 XMF 切分 BLK，验签 PBStaticConfigure，恢复含 mr0k 的 UnityFS AB。算法、版本限制和验证记录见 [ASSET_ANALYSIS.md](ASSET_ANALYSIS.md)。

```powershell
py -m pip install -r requirements.txt
py main.py --index input/AssetbundlesCache.xmf --root D:\Il2Cpp\com.miHoYo.wd\AssetbundlesCache --output output
```

全量验证当前本地缓存，不导出资源：

```powershell
py main.py --index input/AssetbundlesCache.xmf --root D:\Il2Cpp\com.miHoYo.wd\AssetbundlesCache --output output/verify --verify-only
```

仅将 XMF 反序列化为 JSON，不需要 BLK：

```powershell
py main.py --index input/AssetbundlesCache.xmf --output output/list --list
```

保留原始 AB，不执行 mr0k 解密，只校验索引、整块和文件 MD5：

```powershell
py main.py --index input/AssetbundlesCache.xmf --root D:\Il2Cpp\com.miHoYo.wd\AssetbundlesCache --output output/raw-ab --mr0k keep
```
- `--root` 是直接包含 `.blk` 的目录，不是 `D:\Il2Cpp\com.miHoYo.wd`；不再搜索子目录或 APK。
- 默认 `--mr0k decrypt`，恢复压缩内容并重建无压缩 UnityFS，节点原始字节不变。
- 解包文件直接写入 `output/<索引文件路径>`，不再分 `original/`、`resources/`、`bundles/`。
- PBStaticConfigure 根据索引名或根目录名识别，验签后移除前 128 字节；普通 XML 等文件原样输出，不隐式转换 JSON / Protobuf。
- `--list` 写入 `<索引名>.json`；解包及 `--verify-only` 写入 `report.json`，包含摘要、对象数、压缩类型、缺块和失败明细。

已有不同内容不会被覆盖。退出码 0 表示索引清单已导出或全部文件通过，1 表示有缺块或失败，2 表示参数、索引或报告写入错误。缺失的块不能靠算法补出；换客户端版本需重新验证引擎材料。

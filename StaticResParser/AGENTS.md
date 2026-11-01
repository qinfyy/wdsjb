# StaticResParser 开发约定

## 职责

静态读取 wd 的 PBStaticConfigure 已解包文件，使用 WDProtoDumper 从真实运行时恢复并独立验证的 protobuf schema 导出 JSON。不再支持 BH2 的版本 Bundle、AES 密钥回退或 TableToolsData。

BLK/XMF、RSA 签名及 UnityFS/mr0k 属于 Unpacker 的职责；需要读取带签名的配置时复用其验签实现，不复制密码学常量。

## 数据原则

- 输入只读；不删除输入或清空输出目录。
- 保留原始 JSON 字节；protobuf JSON 使用原始 proto 字段名及枚举数值。
- 普通表与 story/explore/text/live2d 分表必须按客户端消息路由读取，不扫描全部消息猜类型。
- 缺少 schema、未知字段及损坏文件必须在报告中明确区分；不能把“解析器没有报错”当作字段完整恢复。
- 缺少 schema 的 wire 导出仅保留字段编号、编码和原始字节，不猜嵌套消息、字段名或有符号数类型。
- 输入路径写入报告时必须相对输入根目录；分析文档不包含本机绝对路径。
- 所有算法证据注明版本、模块和 RVA，并区分模块 RVA、结构偏移和文件偏移。

## 代码与验证

- Python 遵循官方风格，新增函数使用类型注解；注释和文档使用中文。
- 二进制/schema 解析放在 pb_config.py；main.py 只负责文件处理和命令行。
- 修改后执行 py -m compileall . 和单元测试，并使用真实 card.bytes、story、explore、text、live2d 样本验证。
- 大范围路由变化后验证整个可用输入目录，报告已恢复、缺失 schema、未知字段和失败数量。
- 修改参数时同步更新 README.md，修改读取规则时同步更新 ASSET_ANALYSIS.md。

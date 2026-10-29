# BH2Redirector 开发约定

## 职责

BH2Redirector 只负责通过 Frida spawn 启动 BH2，并把客户端 HTTP、资源请求和 Gateway 地址重定向到配置目标。不要在本项目中加入协议抓包、业务包解码、私服逻辑或与重定向无关的 Hook。

## 文件边界

- `Redirector.py` 是配置读取、Frida 会话和日志控制器。
- `FridaScript.js` 是唯一的 Hook 源码。
- `dist/FridaScript.js` 是 `frida-compile` 产物，`Redirector.py` 只检查和加载它，不负责自动编译。
- `Config.ini` 是唯一运行配置源，不新增命令行启动参数或环境变量配置。
- `patches/frida-java-bridge+7.0.13.patch` 是 Android 15 x86 兼容补丁，升级依赖时必须重新验证补丁上下文。

## 运行模型

- 只允许 spawn，不实现 attach。
- `CLIENT_ARCH=x86` 使用 Native Realm；`EMULATOR` 必须为 `false`。
- `CLIENT_ARCH=arm64-v8a`、`EMULATOR=false` 表示原生 ARM64 设备。
- `CLIENT_ARCH=arm64-v8a`、`EMULATOR=true` 表示 MuMu Native Bridge 环境，控制器使用 Native Realm + Emulated Realm。
- x86 与 ARM64 的对象偏移和字符串构造函数回退地址分别保存在 `TARGETS`，不得共用或按比例推导。
- 业务 Hook 使用 `FUNCTION_SIGNATURES` 候选数组在 `libil2cpp.so` 内定位。运行时按候选顺序扫描，不按版本号选地址，也不回退固定 RVA；实际采用的候选必须唯一命中。新候选必须来自对应版本 `dump.cs` 与 ELF 静态验证，且对每个声明支持的版本在模块可扫描范围内唯一命中。ARM64 方法见 [NATIVE_SIGNATURE_ANALYSIS.md](NATIVE_SIGNATURE_ANALYSIS.md)。

## Hook 约束

- IL2CPP Hook 应优先使用游戏自己的字符串构造 API，不伪造托管对象。
- Java URL 路径只修改已加载的 SDK 配置对象，不替换 OkHttp、`java.net.URL` 或通用 ART 方法；RSA Bypass
  只允许替换已确认的账号 SDK `RSAUtils` overload，不能借此扩大为通用 Java Hook。
- Java SDK URL 改写必须**常驻且幂等**，禁止写成「成功一次就 `clearInterval`」的一次性流程。
  客户端每次回到登录页都会走 `MonoTheIndex.UpdateForceLogin` -> `TheBaseAccountManager.Init` ->
  `MiHoYoSDK.Invoke("login_init")` -> Java `Porte.setup` -> `PorteInfo.setup`，把 `PorteInfo` 的
  7 个 URL 静态字段覆盖回官方域名；一次性改写会导致被踢下线后 Java SDK 请求全部落到官方服务器。
  常驻巡检用廉价指纹（字段值 / 对象身份）判断是否需要重扫，禁止每轮无条件全量扫描 `ConfigCenter`
  的上千条地址。
- 允许且仅允许在 `com.mihoyo.platform.account.sdk.PorteInfo.setup(Context, PorteConfig)` 上追加
  一个 URL 守护 Hook：调用原实现后同步重跑 `rewritePorteInfoUrls`。该 Hook 只读改 `PorteInfo`
  自己的静态字段，不得扩展到其他 Java 方法。
- 配置项 `UES_ZLIB_HOOK` 的历史拼写必须保持兼容；它同时控制 zlib Hook 和 VDEX/OAT 常量改写。
- `USE_JAVA_URL_MODIFY` 只控制原有 Java SDK URL 配置改写。
- `USE_JAVA_BYPASS_RSA` 只控制 SDK 登录字段 RSA Bypass。
- Gateway 二次下发的 Game 端口必须保留，不能在每次地址 Hook 时重新覆盖为 Dispatch 端口。
- 所有 Hook 安装都要验证目标地址已映射。Native Bridge guest 映射的特殊权限判断和只读段特征扫描只能用于 `arm64-v8a + EMULATOR=true`。
- 不扩大 URL 匹配范围到任意流量；新增域名必须有客户端请求证据。

### SDK RSA Hook 证据与故障边界

- 13.2.8_341 的主登录调用链是 `LoginManager.loginByPassword ->
  com.mihoyo.platform.account.sdk.utils.RSAUtils.INSTANCE.encryptByPublicKey(String) ->
  RequestUtils.createSign/createBody -> LoginApiService.loginByPassword`；短信登录通过同一个
  `RSAUtils.INSTANCE` 处理区号和手机号。
- 兼容旧账号模块时，只保留 `com.miHoYo.support.utils.RSAUtils` 的已确认 `String,String` 与
  `[B,[B` overload。`com.unicom`、`cn.com.chinatelecom` 等运营商 SDK 不属于 BH2 账号登录调用链，禁止加入 Hook。
- “Hook 已安装”不是业务证据。必须在真实登录请求中同时观察 `[RSA Bypass]`、`[命中]` 和 HTTP 服务端收到的原始字段；
  只有启动日志而没有调用日志时，应优先检查调用链和 SDK 加载时机。
- SDK 热更新或首次调用的 AOT/内联路径可能绕过已安装的 `RSAUtils` implementation。正式脚本收到配置后立即进入 Java Bridge，
  缺失类或 overload 时每 100ms 重试并覆盖四个已知 RSA 入口。
- `Redirector.py` 在单 Realm spawn 流程中等待 `script-configured` 握手后才恢复进程，避免首次自动登录抢在 Java Hook 初始化之前；
  握手超时不得阻塞启动，恢复后继续依赖 100ms 高频重试。
- 为覆盖首次登录绕过 RSA 方法入口的情况，只允许在已确认的密码登录四参数 overload 和手机验证码登录五参数
  `LoginManager.login(...)` 暂存原始字段。`RequestUtils.createSign/createBody(HashMap)` 只处理同时包含
  `account/password` 的密码 Map，或完整包含 `area_code/mobile/captcha/action_type` 的验证码登录 Map。
  不得扩展到其他 `LoginManager` overload、发送验证码请求、OkHttp、通用网络方法或通用加密 API。
- Android 15 x86 上，旧版 `frida-java-bridge` 的 ART/JVMTI 私有 ABI 以及多份 Bridge 并存都可能导致
  `SIGSEGV`、ANR 或点击登录卡死。临时追踪必须复用正式脚本并保持单 Agent；不得再次打包第二份 Bridge，
  不得在高频 Java 方法中同步发送日志或执行阻塞操作。
- `enumerateLoadedClassesSync()` 在当前 ia32 补丁环境可能报 `expected a pointer`，调试脚本不得依赖该调用；
  应在 `Java.perform` 内延迟、单次、只读地查找已知类和方法。
- 账号字段诊断日志只用于本地验收，不得提交真实账号、密码、令牌、设备标识或网络地址；验证结束后删除临时追踪
  文件和日志。

## 代码与验证

- JavaScript 使用 4 个空格缩进；Python 遵循官方风格并使用类型注解。
- 注释和文档使用中文，解释 Realm、ABI、对象布局和兼容回退。
- 不创建大量几行的包装函数；架构差异应集中在目标描述中，公共 Hook 流程保持单份。
- 修改脚本后执行 `npm run build`，再运行 `py Redirector.py` 实机验证。
- 验证必须看到具体 URL 或 Gateway 字段命中，不能只依据“Hook 已安装”日志。
- 配置、构建命令、支持矩阵或 Hook 边界变化时同步更新 `README.md` 和相关分析报告。
- RSA Bypass 的首次登录问题、失败实验和最终修复见 [SDK_RSA_BYPASS_ANALYSIS.md](SDK_RSA_BYPASS_ANALYSIS.md)。
- ARM64 Native 特征的跨版本提取、唯一性验证和 Emulated Realm 实测见 [NATIVE_SIGNATURE_ANALYSIS.md](NATIVE_SIGNATURE_ANALYSIS.md)。

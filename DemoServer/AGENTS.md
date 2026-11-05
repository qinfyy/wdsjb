# 开发约定

- 使用中文；定位为协议逆向与 Demo 联调研究，不以私服运营为目标。
- 先核对 DUMP SDK、IDA、JS 和抓包；使用 WD 协议，不照搬 BH2 的帧格式或业务字段。
- 用强类型协议实现真实逻辑；禁止抓包重放、硬编码 Payload、空成功或自动回复兜底。
- 表必须走 `ResourcesLoader` / `GameTableCatalog` / `TableBase`，按 `OnLoad → OnFinalize → Verification` 建模；校验失败立即终止启动。
- `Player` 是唯一聚合根，内存态即 `PlayerSaveData`；业务放在仅接收 `Player` 的 Logic/Manager，Handler 保持薄。
- 玩家状态变更必须持有 `player.SyncRoot`，完成后调用 `player.Save()`；各 Logic 只修改自己的存档切片。
- `GatewayRouter` 保持静态；连接 ID 由 `GatewayHostedService` 自增分配，会话仅保存。
- 玩家 UID 由数据库自增，新库从 1 开始；不保留玩家 `Uuid`。
- 不新增或运行测试；代码修改后在本目录执行 `dotnet build Sv/Sv.csproj`，须为 0 警告、0 错误。

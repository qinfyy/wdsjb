# WD DemoServer

wd 的协议逆向、策划资源解析与客户端联调研究项目。服务端用于验证客户端行为。

采用 .NET 10、ASP.NET Core、TCP/Protobuf 与 SQLite BLOB 存档。

## 运行

安装 .NET 10 SDK，在本目录执行：
```powershell
dotnet build Sv/Sv.csproj
dotnet run --project Sv/Sv.csproj
```

配置见 `Sv/appsettings.json`：HTTP 默认 `21000`，TCP 默认 `24088`；`AdvertiseHost` 填客户端可访问的地址，`GameData.TableRoot` 指向 `StaticResParser/output`。

仅供技术研究与学习；开发约定见 `AGENTS.md`。

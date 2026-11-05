using System.Text.Json;
using Sv.Configuration;
using Sv.Resources.Tables;

namespace Sv.Resources;

public static class ResourcesLoader
{
    public static void Load(GameDataOptions options)
    {
        GameTableCatalog catalog = new();
        LoadTable<PlayerLevelData>(catalog, options.TableRoot, "character.json", "levelInfo");
        LoadTable<RoleData>(catalog, options.TableRoot, "role.json", "role");
        LoadTable<DeskDisplayConfigData>(catalog, options.TableRoot, "MiscData_misc_data.json", "desk_display", singleton: true);
        LoadTable<CardData>(catalog, options.TableRoot, "card.json", "info");
        LoadTable<MaterialData>(catalog, options.TableRoot, "item.json", "material");
        LoadTable<WalletData>(catalog, options.TableRoot, "wallet.json", "info");
        LoadTable<TicketData>(catalog, options.TableRoot, "wallet.json", "ticketInfo");
        LoadTable<GuideData>(catalog, options.TableRoot, "guide.json", "GuideIndexInfo");
        LoadTable<ChapterData>(catalog, options.TableRoot, "chapter.json", "chapter");
        LoadTable<LevelRewardData>(catalog, options.TableRoot, "level.json", "reward");
        LoadTable<LevelData>(catalog, options.TableRoot, "level.json", "main");
        GameTableCatalog.Instance = catalog;
        catalog.BroadcastOnFinalize(); catalog.BroadcastVerification();
        if (catalog.GetDataById<PlayerLevelData>(1) is null || catalog.GetDataById<LevelData>(1) is null)
            throw new InvalidDataException("缺少玩家初始等级或新手关卡");
        catalog.IsLoaded = true;
    }
    private static void LoadTable<T>(GameTableCatalog catalog, string root, string fileName, string section, bool singleton = false) where T : TableBase
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root, fileName)));
            JsonElement data = document.RootElement.GetProperty(section);
            IEnumerable<JsonElement> elements = singleton ? [data] : data.GetProperty("datas").EnumerateArray();
            Dictionary<int, T> rows = [];
            foreach (JsonElement element in elements)
            {
                T row = element.Deserialize<T>() ?? throw new InvalidDataException($"{fileName}/{section}: 空行");
                row.OnLoad();
                if (row.GetId() <= 0 || !rows.TryAdd(row.GetId(), row)) throw new InvalidDataException($"{fileName}/{section}: 无效或重复 ID {row.GetId()}");
            }
            if (rows.Count == 0) throw new InvalidDataException($"{fileName}/{section}: 空表");
            catalog.PushTable(rows);
        }
        catch (Exception exception) when (exception is JsonException or KeyNotFoundException or FormatException or OverflowException)
        {
            throw new InvalidDataException($"{fileName}/{section}: 资源解析失败", exception);
        }
    }
}

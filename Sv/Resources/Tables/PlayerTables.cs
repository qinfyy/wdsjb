using System.Text.Json.Serialization;

namespace Sv.Resources.Tables;

public sealed class PlayerLevelData : TableBase
{
    [JsonPropertyName("lV")] public uint Level { get; init; }
    [JsonPropertyName("nextLevelEXP")] public int NextLevelExp { get; init; }
    [JsonPropertyName("stamina")] public uint Stamina { get; init; }
    [JsonPropertyName("hp")] public uint Hp { get; init; }
    [JsonPropertyName("friendNum")] public uint FriendLimit { get; init; }
    [JsonPropertyName("mainCard")] public uint MainCardLimit { get; init; }
    [JsonIgnore] public PlayerLevelData? NextLevel { get; private set; }
    public override int GetId() => checked((int)Level);
    public override void OnFinalize() => NextLevel = GameTableCatalog.Instance.GetDataById<PlayerLevelData>(Level + 1);
    public override void Verification()
    {
        if (Stamina == 0 || MainCardLimit == 0 || (NextLevel is not null && NextLevelExp <= 0))
            throw new InvalidDataException($"玩家等级 {Level} 数值无效");
    }
}

public sealed class GuideData : TableBase
{
    [JsonPropertyName("GuideGroupID")] public uint Id { get; init; }
    public override int GetId() => checked((int)Id);
}

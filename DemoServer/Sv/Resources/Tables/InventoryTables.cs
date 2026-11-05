using System.Text.Json.Serialization;

namespace Sv.Resources.Tables;

public sealed class RoleData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("codeNameTextID")] public string CodeNameTextId { get; init; } = string.Empty;
    [JsonIgnore] public List<CardData> Cards { get; } = [];
    public override int GetId() => checked((int)Id);
}

public sealed class CardData : TableBase
{
    [JsonPropertyName("cardID")] public uint Id { get; init; }
    [JsonPropertyName("maleRoleId")] public uint RoleId { get; init; }
    [JsonPropertyName("cardRate")] public uint Rarity { get; init; }
    [JsonPropertyName("cardLevel")] public uint LevelLimit { get; init; }
    [JsonPropertyName("skillID1")] public uint SkillId1 { get; init; }
    [JsonPropertyName("skillID2")] public uint SkillId2 { get; init; }
    [JsonPropertyName("skillID3")] public uint SkillId3 { get; init; }
    [JsonIgnore] public uint[] SkillIds { get; private set; } = [];
    [JsonIgnore] public RoleData? Role { get; private set; }
    public override int GetId() => checked((int)Id);
    public override void OnLoad() => SkillIds = new[] { SkillId1, SkillId2, SkillId3 }.Where(id => id != 0).Distinct().ToArray();
    public override void OnFinalize()
    {
        Role = GameTableCatalog.Instance.GetDataById<RoleData>(RoleId);
        Role?.Cards.Add(this);
    }
    public override void Verification()
    {
        if (Role is null || LevelLimit == 0 || Rarity == 0) throw new InvalidDataException($"卡牌 {Id} 的角色引用或数值无效");
    }
}

public sealed class MaterialData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("type")] public uint Type { get; init; }
    [JsonPropertyName("rarity")] public uint Rarity { get; init; }
    [JsonPropertyName("eXP")] public uint Exp { get; init; }
    public override int GetId() => checked((int)Id);
}

public sealed class WalletData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("max")] public uint Max { get; init; }
    public override int GetId() => checked((int)Id);
    public override void Verification()
    {
        if (Max > int.MaxValue) throw new InvalidDataException($"货币 {Id} 上限超过网络协议范围");
    }
}

public sealed class TicketData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("hCPrice")] public uint HcoinPrice { get; init; }
    public override int GetId() => checked((int)Id);
}

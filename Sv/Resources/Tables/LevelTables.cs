using System.Globalization;
using System.Text.Json.Serialization;
using Sv.Game;

namespace Sv.Resources.Tables;

public enum LevelType : uint { Battle = 1, Investigation = 2, Story = 3 }

public sealed class ChapterData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("chapterType")] public uint Type { get; init; }
    [JsonPropertyName("chapterID")] public uint ChapterId { get; init; }
    [JsonPropertyName("guideID")] public uint[] GuideIds { get; init; } = [];
    [JsonIgnore] public List<LevelData> Levels { get; } = [];
    public override int GetId() => checked((int)Id);
}

public sealed class LevelData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("groupID")] public uint GroupId { get; init; }
    [JsonPropertyName("levelType")] public LevelType Type { get; init; }
    [JsonPropertyName("parentid")] public uint[] ParentIds { get; init; } = [];
    [JsonPropertyName("chapterID")] public uint ChapterId { get; init; }
    [JsonPropertyName("staminaCost")] public uint StaminaCost { get; init; }
    [JsonPropertyName("playerExp")] public uint PlayerExp { get; init; }
    [JsonPropertyName("coin")] public uint Scoin { get; init; }
    [JsonPropertyName("firstReward")] public uint FirstRewardId { get; init; }
    [JsonPropertyName("storyID")] public string StoryIdText { get; init; } = string.Empty;
    [JsonIgnore] public uint[] StoryIds { get; private set; } = [];
    [JsonIgnore] public List<LevelData> Parents { get; } = [];
    [JsonIgnore] public List<LevelData> Children { get; } = [];
    [JsonIgnore] public ChapterData? Chapter { get; private set; }
    [JsonIgnore] public LevelRewardData? FirstReward { get; private set; }
    public override int GetId() => checked((int)Id);
    public override void OnLoad() => StoryIds = StoryIdText.Split('|', StringSplitOptions.RemoveEmptyEntries).Select(id => uint.Parse(id, CultureInfo.InvariantCulture)).ToArray();
    public override void OnFinalize()
    {
        foreach (uint id in ParentIds.Where(id => id != 0))
        {
            LevelData? parent = GameTableCatalog.Instance.GetDataById<LevelData>(id);
            if (parent is not null) { Parents.Add(parent); parent.Children.Add(this); }
        }
        Chapter = GameTableCatalog.Instance.GetDataById<ChapterData>(ChapterId); Chapter?.Levels.Add(this);
        FirstReward = GameTableCatalog.Instance.GetDataById<LevelRewardData>(FirstRewardId);
    }
    public override void Verification()
    {
        if (Parents.Count != ParentIds.Count(id => id != 0) || (ChapterId != 0 && Chapter is null) || (FirstRewardId != 0 && FirstReward is null))
            throw new InvalidDataException($"关卡 {Id} 的前置、章节或奖励引用无效");
    }
}

public sealed class LevelRewardData : TableBase
{
    [JsonPropertyName("iD")] public uint Id { get; init; }
    [JsonPropertyName("rewardInfos")] public RewardItemData[] Items { get; init; } = [];
    public override int GetId() => checked((int)Id);
    public override void Verification()
    {
        foreach (RewardItemData item in Items) item.Verification();
    }
}

public sealed class RewardItemData
{
    [JsonPropertyName("rewardID")] public uint RewardId { get; init; }
    [JsonPropertyName("materialID")] public uint ItemId { get; init; }
    [JsonPropertyName("type")] public RewardKind Type { get; init; }
    [JsonPropertyName("num")] public uint Count { get; init; }
    public void Verification()
    {
        if (Count == 0 || !Enum.IsDefined(Type)) throw new InvalidDataException("奖励类型或数量无效");
        bool exists = Type switch
        {
            RewardKind.Card => GameTableCatalog.Instance.GetDataById<CardData>(ItemId) is not null,
            RewardKind.Material => GameTableCatalog.Instance.GetDataById<MaterialData>(ItemId) is not null,
            RewardKind.Wallet => GameTableCatalog.Instance.GetDataById<WalletData>(ItemId) is not null,
            RewardKind.Ticket => GameTableCatalog.Instance.GetDataById<TicketData>(ItemId) is not null,
            _ => true,
        };
        if (!exists) throw new InvalidDataException($"奖励引用无效: {Type}/{ItemId}");
    }
}

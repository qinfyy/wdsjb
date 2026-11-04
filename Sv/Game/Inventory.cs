using Pbplayer;
using PlayerSaveProto;
using Sv.Resources;
using Sv.Resources.Tables;
using Sv.Utility;

namespace Sv.Game;

public sealed class Inventory(Player player) : PlayerLogicBase(player)
{
    private InventoryComp Comp => Player.SaveData.InventoryComp;
    public IEnumerable<CardBin> Cards => Comp.Cards.Values;
    public IEnumerable<DeckBin> Decks => Comp.Decks.Values;
    public IEnumerable<KeyValuePair<uint, uint>> Materials => Comp.Materials;
    public uint Material(uint id) => Comp.Materials.GetValueOrDefault(id);
    public bool OwnsCard(uint id) => Comp.Cards.ContainsKey(id);
    public DeckBin GetDeck(uint id) => Comp.Decks.TryGetValue(id, out DeckBin? deck) ? deck : throw new PlayerActionException(-2, "卡组不存在");
    public GetCardDataRsp CreateCardData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetCardDataRsp response = new() { Retcode = 1, CardDataAll = dataAll };
        foreach (CardBin card in Cards.Where(card => dataAll != 0 || ids is null || ids.Contains(card.Id)).OrderBy(card => card.Id))
            response.CardList.Add(CreateCardItem(card));
        return response;
    }
    public GetDeckDataRsp CreateDeckData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetDeckDataRsp response = new() { Retcode = 1, DeckDataAll = dataAll };
        foreach (DeckBin deck in Decks.Where(deck => dataAll != 0 || ids is null || ids.Contains(deck.Id)).OrderBy(deck => deck.Id))
        {
            DeckItem item = new()
            {
                DeckId = deck.Id, DeckName = deck.Name, CreateTime = deck.CreateTime, IsInit = 1,
                MainCardGroup = new(), AssistCardGroup = new(), CardGroupCfg = new(),
            };
            for (int index = 0; index < deck.MainCards.Count; index++)
                item.MainCardGroup.CardItems.Add(new DeckCardGroupItem { CardId = deck.MainCards[index], AddOrder = checked((uint)index) });
            for (int index = 0; index < deck.AssistCards.Count; index++)
                item.AssistCardGroup.CardItems.Add(new DeckCardGroupItem { CardId = deck.AssistCards[index], AddOrder = checked((uint)index) });
            foreach (uint id in deck.MainCards.Concat(deck.AssistCards).Where(id => id != 0))
                item.CardGroupCfg.CardItems.Add(CreateCardItem(Comp.Cards[id]));
            response.DeckItemList.Add(item);
        }
        return response;
    }
    public GetMaterialDataRsp CreateMaterialData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetMaterialDataRsp response = new() { Retcode = 1, MaterialDataAll = dataAll };
        foreach (var pair in Materials.Where(pair => dataAll != 0 || ids is null || ids.Contains(pair.Key)).OrderBy(pair => pair.Key))
            response.MaterialList.Add(new MaterialItem { MaterialId = pair.Key, MaterialNum = checked((int)pair.Value) });
        return response;
    }
    private static CardItem CreateCardItem(CardBin card)
    {
        CardItem item = new()
        {
            CardId = card.Id, ExpLevel = card.Level, Exp = card.Exp, Star = card.Star, EvolType = card.EvolType,
            RecvUnixtime = checked((uint)card.ReceiveTime), Status = card.Status, DisplayType = card.DisplayType, IsNew = card.IsNew ? 1u : 0u,
        };
        foreach (var pair in card.Skills.OrderBy(pair => pair.Key)) item.SkillItems.Add(new CardSkillItem { SkillId = pair.Key, SkillLevel = pair.Value });
        return item;
    }
    protected internal override void OnPlayerEventType(PlayerEventType type, int param1 = 0, int param2 = 0, int param3 = 0, object? state = null)
    {
        if (Player.Session is null) return;
        RewardItemData[] rewards = type == PlayerEventType.LevelSettled && param2 != 0 ? LevelManager.FirstRewards(checked((uint)param1)) : [];
        if (type == PlayerEventType.CardsChanged || rewards.Any(row => row.Type == RewardKind.Card))
            Player.Send((ushort)GetCardDataRsp.Types.CmdId.CmdId, CreateCardData());
        if (type == PlayerEventType.DecksChanged) Player.Send((ushort)GetDeckDataRsp.Types.CmdId.CmdId, CreateDeckData());
        if (type == PlayerEventType.MaterialsChanged || rewards.Any(row => row.Type == RewardKind.Material))
            Player.Send((ushort)GetMaterialDataRsp.Types.CmdId.CmdId, CreateMaterialData());
    }

    public override void OnCreate()
    {
        // Demo 初始卡组从真实表的最低稀有度中选取，不导入任何抓包资产。
        uint[] cards = GameTableCatalog.Instance.GetAllData<CardData>()
            .Where(row => row.RoleId is >= 1 and <= 4)
            .OrderBy(row => row.Rarity).ThenBy(row => row.Id)
            .GroupBy(row => row.RoleId).Select(group => group.First().Id).ToArray();
        foreach (uint id in cards) Grant(RewardKind.Card, id, 1, sync: false);
        DeckBin deck = new() { Id = 1, Name = "Demo", CreateTime = Time.Now.ToUnixTimeSeconds() };
        deck.MainCards.Add(cards.Take((int)Player.Profile.MaxMainCards)); Comp.Decks.Add(1, deck);
    }
    public void ChangeDeck(uint id, string name, uint[] mainCards, uint[] assistCards, bool sync = true)
    {
        DeckBin deck = GetDeck(id);
        if (name.Length > 32 || name.Any(char.IsControl)) throw new PlayerActionException(-2, "卡组名称无效");
        if (mainCards.Length > Player.Profile.MaxMainCards || assistCards.Length > 10) throw new PlayerActionException(-2, "卡组槽位超出上限");
        uint[] all = mainCards.Concat(assistCards).Where(value => value != 0).ToArray();
        if (all.Distinct().Count() != all.Length || all.Any(value => !OwnsCard(value))) throw new PlayerActionException(-2, "卡牌未持有或重复");
        deck.Name = name; deck.MainCards.Clear(); deck.MainCards.Add(mainCards);
        deck.AssistCards.Clear(); deck.AssistCards.Add(assistCards);
        if (sync) Player.Trigger(PlayerEventType.DecksChanged);
    }
    public void CheckGrant(RewardKind kind, uint id, uint count)
    {
        switch (kind)
        {
            case RewardKind.Card:
                if (GameTableCatalog.Instance.GetDataById<CardData>(id) is null || count != 1 || OwnsCard(id))
                    throw new PlayerActionException(-2, "卡牌不存在或重复卡转换尚未实现");
                break;
            case RewardKind.Material:
                if (GameTableCatalog.Instance.GetDataById<MaterialData>(id) is null || (ulong)Material(id) + count > int.MaxValue)
                    throw new PlayerActionException(-2, "材料不存在或超过上限");
                break;
            case RewardKind.Exp: Player.Profile.CheckAddExp(count); break;
            case RewardKind.Stamina: Player.Profile.CheckAddStamina(count); break;
            default: Player.Wallet.CheckAdd(kind, id, count); break;
        }
    }
    public void Grant(RewardKind kind, uint id, uint count, bool sync = true)
    {
        CheckGrant(kind, id, count);
        switch (kind)
        {
            case RewardKind.Card:
                CardData row = GameTableCatalog.Instance.GetDataById<CardData>(id)!;
                CardBin card = new() { Id = id, Level = 1, ReceiveTime = Time.Now.ToUnixTimeSeconds(), IsNew = true };
                foreach (uint skill in row.SkillIds) card.Skills[skill] = 1;
                Comp.Cards.Add(id, card);
                if (sync) Player.Trigger(PlayerEventType.CardsChanged);
                break;
            case RewardKind.Material:
                Comp.Materials[id] = Material(id) + count;
                if (sync) Player.Trigger(PlayerEventType.MaterialsChanged);
                break;
            case RewardKind.Exp: Player.Profile.AddExp(count, sync); break;
            case RewardKind.Stamina: Player.Profile.AddStamina(count, sync); break;
            default: Player.Wallet.Add(kind, id, count, sync); break;
        }
    }
    public void CheckRewards(IReadOnlyList<RewardItemData> rewards)
    {
        foreach (var group in rewards.GroupBy(row => (row.Type, row.ItemId)))
        {
            ulong count = 0;
            foreach (RewardItemData row in group) count += row.Count;
            if (count > uint.MaxValue) throw new PlayerActionException(-2, "奖励数量超过上限");
            CheckGrant(group.Key.Item1, group.Key.Item2, (uint)count);
        }
    }
    public void GrantRewards(IReadOnlyList<RewardItemData> rewards, bool sync = true)
    {
        CheckRewards(rewards);
        foreach (RewardItemData row in rewards) Grant(row.Type, row.ItemId, row.Count, sync);
    }
}

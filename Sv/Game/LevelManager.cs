using System.Security.Cryptography;
using Pbplayer;
using PlayerSaveProto;
using Sv.Resources;
using Sv.Resources.Tables;
using Sv.Utility;

namespace Sv.Game;

/// <summary>对应客户端 ServerEnum.pb.eLevelStatus。</summary>
public enum LevelStatus : uint { Done = 0, UnderProgress = 1, Deleted = 2, Locked = 4, LockedDone = 5 }

public sealed class LevelManager(Player player) : PlayerLogicBase(player)
{
    private LevelComp Comp => Player.SaveData.LevelComp;
    public uint Seed => Comp.Seed;
    public uint ActiveLevel => Comp.ActiveLevel;
    public uint PassCount(uint id) => Comp.Levels.TryGetValue(id, out LevelBin? state) ? state.PassCount : 0;
    public bool ClaimedFirstReward(uint id) => Comp.Levels.TryGetValue(id, out LevelBin? state) && state.FirstRewardClaimed;
    public IEnumerable<uint> OpenLevels => GameTableCatalog.Instance.GetAllData<LevelData>().Where(row => IsOpen(row.Id)).Select(row => row.Id);
    public static LevelData Definition(uint id) => GameTableCatalog.Instance.GetDataById<LevelData>(id) ?? throw new PlayerActionException(-2, "关卡不存在");
    public static RewardItemData[] FirstRewards(uint id) => Definition(id).FirstReward?.Items ?? [];
    public GetLevelDataRsp CreateLevelData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetLevelDataRsp response = new() { Retcode = 1, LevelDataAll = dataAll };
        foreach (uint id in OpenLevels.Where(id => dataAll != 0 || ids is null || ids.Contains(id)).Order())
        {
            uint passed = PassCount(id);
            response.LevelList.Add(new LevelItem
            {
                LevelId = id, Status = (uint)(passed > 0 ? LevelStatus.Done : LevelStatus.UnderProgress), CurPassCount = passed,
                HasGotItem = ClaimedFirstReward(id) ? 1u : 0u,
                Progress = passed > 0 ? 1u : 0u,
            });
        }
        return response;
    }
    public LevelEndRsp CreateLevelEnd(uint id, bool first, uint previousLevel)
    {
        LevelData row = Definition(id);
        LevelEndRsp response = new()
        {
            Retcode = 1, LevelId = id, ExpEarn = row.PlayerExp, ScoinEarn = row.Scoin, IsLevelUp = Player.Profile.Level > previousLevel ? 1u : 0u,
        };
        if (first)
        {
            foreach (RewardItemData reward in FirstRewards(id))
            {
                RewardDataItem item = new()
                {
                    RewardType = (uint)reward.Type, ItemId = reward.ItemId, ItemNum = reward.Count, RewardId = reward.RewardId, AddItemNum = reward.Count,
                };
                item.CurItemNum = reward.Type switch
                {
                    RewardKind.Card => Player.Inventory.OwnsCard(reward.ItemId) ? 1 : 0,
                    RewardKind.Material => Player.Inventory.Material(reward.ItemId),
                    RewardKind.Exp => Player.Profile.Exp, RewardKind.Stamina => Player.Profile.Stamina,
                    _ => Player.Wallet.Balance(reward.Type, reward.ItemId),
                };
                if (response.FirstPassRewardItem is null) response.FirstPassRewardItem = item;
                else response.DropItems.Add(item);
            }
        }
        return response;
    }
    protected internal override void OnPlayerEventType(PlayerEventType type, int param1 = 0, int param2 = 0, int param3 = 0, object? state = null)
    {
        if (Player.Session is null) return;
        if (type is PlayerEventType.LevelsChanged or PlayerEventType.LevelSettled)
            Player.Send((ushort)GetLevelDataRsp.Types.CmdId.CmdId, CreateLevelData());
    }
    public bool IsOpen(uint id)
    {
        LevelData? row = GameTableCatalog.Instance.GetDataById<LevelData>(id);
        if (row is null) return false;
        // 这里只开放本地 Demo 的主线；活动和限时关卡需要独立的排期逻辑。
        if (row.ChapterId != 1) return false;
        return row.Parents.All(parent => PassCount(parent.Id) > 0);
    }
    public uint Begin(uint id)
    {
        if (!IsOpen(id)) throw new PlayerActionException(-2, "关卡未解锁");
        if (Comp.ActiveLevel != 0) throw new PlayerActionException(-2, "已有进行中的关卡");
        LevelData row = Definition(id);
        if (row.Type != LevelType.Story) throw new PlayerActionException(-1, "战斗与调查结算尚未实现");
        if (Player.Profile.Stamina < row.StaminaCost) throw new PlayerActionException(-3, "体力不足");
        Comp.ActiveLevel = id; Comp.BeginTime = Time.Now.ToUnixTimeSeconds();
        Comp.Seed = BitConverter.ToUInt32(RandomNumberGenerator.GetBytes(4));
        return Comp.Seed;
    }
    public bool Complete(uint id, bool sync = true)
    {
        if (Comp.ActiveLevel != id || id == 0) throw new PlayerActionException(-2, "关卡尚未开始或已经结算");
        LevelData row = Definition(id);
        if (row.StoryIds.Any(id => !Player.Story.Completed(id))) throw new PlayerActionException(-2, "剧情尚未完成");
        uint cost = row.StaminaCost, exp = row.PlayerExp, coin = row.Scoin;
        if (Player.Profile.Stamina < cost || PassCount(id) == uint.MaxValue) throw new PlayerActionException(-3, "体力不足或通关次数超过上限");
        bool first = !ClaimedFirstReward(id);
        RewardItemData[] rewards = first ? FirstRewards(id) : [];
        Player.Inventory.CheckRewards(rewards); Player.Profile.CheckAddExp(exp); Player.Wallet.CheckAdd(RewardKind.Scoin, 0, coin);
        Player.Profile.SpendStamina(cost, sync: false); Player.Profile.AddExp(exp, sync: false);
        Player.Wallet.Add(RewardKind.Scoin, 0, coin, sync: false); Player.Inventory.GrantRewards(rewards, sync: false);
        if (!Comp.Levels.TryGetValue(id, out LevelBin? state)) { state = new() { Id = id }; Comp.Levels.Add(id, state); }
        state.PassCount++; state.FirstRewardClaimed = true; Comp.ActiveLevel = 0; Comp.Seed = 0; Comp.BeginTime = 0;
        Player.Trigger(PlayerEventType.LevelPassed, checked((int)id), first ? 1 : 0, checked((int)exp));
        if (sync) Player.Trigger(PlayerEventType.LevelSettled, checked((int)id), first ? 1 : 0);
        return first;
    }
    public void Abandon() { Comp.ActiveLevel = 0; Comp.Seed = 0; Comp.BeginTime = 0; }
}

using Pbplayer;
using PlayerSaveProto;
using Sv.Resources;
using Sv.Resources.Tables;

namespace Sv.Game;

public enum RewardKind : uint { Hcoin = 1, Scoin = 2, Wallet = 3, Ticket = 4, Card = 5, Material = 6, DeskDisplay = 8, Exp = 11, Stamina = 12, Ycoin = 13, FriendPoint = 14 }

public sealed class WalletLogic(Player player) : PlayerLogicBase(player)
{
    private WalletComp Comp => Player.SaveData.WalletComp;
    public long Hcoin => Comp.Hcoin;
    public long Scoin => Comp.Scoin;
    public long Ycoin => Comp.Ycoin;
    public long FriendPoint => Comp.FriendPoint;
    public IEnumerable<uint> CoinIds => GameTableCatalog.Instance.GetAllData<WalletData>().Select(row => row.Id);
    public IEnumerable<uint> TicketIds => GameTableCatalog.Instance.GetAllData<TicketData>().Select(row => row.Id);
    public long Coin(uint id) => Comp.Coins.GetValueOrDefault(id);
    public uint Ticket(uint id) => Comp.Tickets.GetValueOrDefault(id);
    public long Balance(RewardKind kind, uint id) => kind switch
    {
        RewardKind.Hcoin => Hcoin, RewardKind.Scoin => Scoin, RewardKind.Ycoin => Ycoin, RewardKind.FriendPoint => FriendPoint,
        RewardKind.Wallet => Coin(id), RewardKind.Ticket => Ticket(id), _ => throw new PlayerActionException(-2, "不是货币类型"),
    };
    public uint CoinLimit(uint id) => GameTableCatalog.Instance.GetDataById<WalletData>(id)!.Max;
    public GetWalletDataRsp CreateWalletData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetWalletDataRsp response = new() { Retcode = 1, WalletDataAll = dataAll };
        foreach (uint id in CoinIds.Where(id => dataAll != 0 || ids is null || ids.Contains(id)).Order())
            response.WalletList.Add(new WalletItem { CoinId = id, CoinNum = checked((int)Coin(id)), CoinMax = CoinLimit(id) });
        return response;
    }
    public GetTicketDataRsp CreateTicketData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetTicketDataRsp response = new() { Retcode = 1, TicketDataAll = dataAll };
        foreach (uint id in TicketIds.Where(id => dataAll != 0 || ids is null || ids.Contains(id)).Order())
            response.TicketList.Add(new TicketItem { TicketId = id, TicketNum = checked((int)Ticket(id)) });
        return response;
    }
    protected internal override void OnPlayerEventType(PlayerEventType type, int param1 = 0, int param2 = 0, int param3 = 0, object? state = null)
    {
        if (Player.Session is null) return;
        RewardItemData[] rewards = type == PlayerEventType.LevelSettled && param2 != 0 ? LevelManager.FirstRewards(checked((uint)param1)) : [];
        if (type == PlayerEventType.WalletChanged || rewards.Any(row => row.Type == RewardKind.Wallet))
            Player.Send((ushort)GetWalletDataRsp.Types.CmdId.CmdId, CreateWalletData());
        if (type == PlayerEventType.TicketsChanged || rewards.Any(row => row.Type == RewardKind.Ticket))
            Player.Send((ushort)GetTicketDataRsp.Types.CmdId.CmdId, CreateTicketData());
    }
    public void CheckAdd(RewardKind kind, uint id, long count)
    {
        if (count < 0) throw new PlayerActionException(-2, "发放数量不能为负");
        if (kind == RewardKind.Wallet && GameTableCatalog.Instance.GetDataById<WalletData>(id) is null) throw new PlayerActionException(-2, "货币不存在");
        if (kind == RewardKind.Ticket && GameTableCatalog.Instance.GetDataById<TicketData>(id) is null) throw new PlayerActionException(-2, "门票不存在");
        long max = kind == RewardKind.Wallet ? CoinLimit(id) : int.MaxValue;
        if (count > max - Balance(kind, id)) throw new PlayerActionException(-2, "资产超过上限");
    }
    public void Add(RewardKind kind, uint id, long count, bool sync = true)
    {
        CheckAdd(kind, id, count); Set(kind, id, Balance(kind, id) + count);
        if (sync) Sync(kind);
    }
    public void Spend(RewardKind kind, uint id, long count, bool sync = true)
    {
        if (count <= 0 || Balance(kind, id) < count) throw new PlayerActionException(-3, "余额不足或消耗数量无效");
        Set(kind, id, Balance(kind, id) - count);
        if (sync) Sync(kind);
    }
    private void Set(RewardKind kind, uint id, long value)
    {
        switch (kind)
        {
            case RewardKind.Hcoin: Comp.Hcoin = value; break;
            case RewardKind.Scoin: Comp.Scoin = value; break;
            case RewardKind.Ycoin: Comp.Ycoin = value; break;
            case RewardKind.FriendPoint: Comp.FriendPoint = value; break;
            case RewardKind.Wallet: Comp.Coins[id] = value; break;
            case RewardKind.Ticket: Comp.Tickets[id] = checked((uint)value); break;
            default: throw new PlayerActionException(-2, "不是货币类型");
        }
    }
    private void Sync(RewardKind kind)
    {
        if (kind == RewardKind.Ticket) Player.Trigger(PlayerEventType.TicketsChanged);
        else if (kind == RewardKind.Wallet) Player.Trigger(PlayerEventType.WalletChanged);
        else Player.Trigger(PlayerEventType.MainDataChanged);
    }
}

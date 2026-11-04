using Google.Protobuf;
using PlayerSaveProto;
using Sv.Database;
using Sv.Gateway;

namespace Sv.Game;

public sealed class Player
{
    private readonly PlayerLogicBase[] _logic;
    public uint Uid { get; }
    public int ChannelId { get; }
    public string OpenId { get; }
    public object SyncRoot { get; } = new();
    public PlayerSaveData SaveData { get; }
    public GatewaySession? Session { get; internal set; }
    public PlayerProfileLogic Profile { get; }
    public WalletLogic Wallet { get; }
    public Inventory Inventory { get; }
    public GuideLogic Guide { get; }
    public LevelManager Level { get; }
    public StoryLogic Story { get; }

    internal Player(long uid, int channelId, string openId, PlayerSaveData saveData, bool isNew)
    {
        Uid = checked((uint)uid); ChannelId = channelId; OpenId = openId; SaveData = saveData;
        Profile = new(this); Wallet = new(this); Inventory = new(this); Guide = new(this); Level = new(this); Story = new(this);
        _logic = [Profile, Wallet, Inventory, Guide, Level, Story];
        lock (SyncRoot)
        {
            if (isNew) foreach (PlayerLogicBase logic in _logic) logic.OnCreate();
            foreach (PlayerLogicBase logic in _logic) logic.OnLoad();
        }
    }

    public void OnLogin()
    {
        foreach (PlayerLogicBase logic in _logic) logic.OnLogin();
    }
    public void Save()
    {
        if (!Monitor.IsEntered(SyncRoot)) throw new InvalidOperationException("存盘前必须持有玩家锁");
        foreach (PlayerLogicBase logic in _logic) logic.BeforeSave();
        GameDatabase.Instance.Save(this);
    }
    public void Send(ushort cmdId, IMessage packet) => Session?.Send(cmdId, packet);
    public void Trigger(PlayerEventType type, int param1 = 0, int param2 = 0, int param3 = 0, object? state = null)
    {
        if (!Monitor.IsEntered(SyncRoot)) throw new InvalidOperationException("玩家事件必须持有玩家锁");
        foreach (PlayerLogicBase logic in _logic) logic.OnPlayerEventType(type, param1, param2, param3, state);
    }
}

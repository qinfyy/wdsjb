using System.Text;
using Pbplayer;
using PlayerSaveProto;
using Sv.Resources;
using Sv.Resources.Tables;
using Sv.Utility;

namespace Sv.Game;

public sealed class PlayerProfileLogic(Player player) : PlayerLogicBase(player)
{
    private PlayerBasicComp Comp => Player.SaveData.Playerdata;
    public string Nickname => Comp.Nickname;
    public string Language => Comp.Language;
    public uint Level => Comp.Level;
    public uint Exp => Comp.Exp;
    public uint Stamina => Comp.Stamina;
    public uint StaminaLimit => GameTableCatalog.Instance.GetDataById<PlayerLevelData>(Level)!.Stamina;
    public uint MaxMainCards => GameTableCatalog.Instance.GetDataById<PlayerLevelData>(Level)!.MainCardLimit;
    public uint LoginCount => Comp.LoginCount;
    public uint LastRpcId => Comp.LastRpcId;
    public uint DeskDisplayId => Comp.DeskDisplayId;
    public uint RecoveryLeftTime => Stamina >= StaminaLimit ? 0 : (uint)Math.Max(0, 360 - (Time.Now.ToUnixTimeSeconds() - Comp.LastStaminaTime));

    public override void OnCreate()
    {
        Comp.Nickname = "Demo"; Comp.Language = "zh-cn"; Comp.Level = 1; Comp.Stamina = StaminaLimit;
        Comp.CreateTime = Time.Now.ToUnixTimeSeconds(); Comp.LastStaminaTime = Comp.CreateTime;
    }
    public override void OnLoad()
    {
        if (GameTableCatalog.Instance.GetDataById<PlayerLevelData>(Level) is null) throw new InvalidDataException("存档玩家等级无效");
    }
    public override void OnLogin()
    {
        RecoverStamina(); Comp.LoginCount = checked(Comp.LoginCount + 1); Comp.LastLoginTime = Time.Now.ToUnixTimeSeconds();
    }
    public GetMainDataRsp CreateMainData(uint dataAll = 1)
    {
        DateTimeOffset now = Time.Now;
        return new GetMainDataRsp
        {
            Retcode = 1, DataAll = dataAll, Nickname = Nickname, ExpLevel = Level, Exp = Exp, Lang = Language,
            Hcoin = Player.Wallet.Hcoin, Scoin = Player.Wallet.Scoin, Ycoin = Player.Wallet.Ycoin, FriendPoint = Player.Wallet.FriendPoint,
            Stamina = Stamina, StaminaRecoverLeftTime = RecoveryLeftTime, StaminaRecoverConfigTime = 360, DeskDisplayId = DeskDisplayId,
            CurTime = now.ToUnixTimeSeconds(), CurTimeMs = now.ToUnixTimeMilliseconds(), CurZone = checked((int)now.Offset.TotalHours),
        };
    }
    protected internal override void OnPlayerEventType(PlayerEventType type, int param1 = 0, int param2 = 0, int param3 = 0, object? state = null)
    {
        if (Player.Session is null) return;
        if (type is PlayerEventType.MainDataChanged or PlayerEventType.LevelSettled)
            Player.Send((ushort)GetMainDataRsp.Types.CmdId.CmdId, CreateMainData());
    }
    public void Rename(string nickname, bool sync = true)
    {
        nickname = nickname.Trim().Normalize(NormalizationForm.FormC);
        if (nickname.EnumerateRunes().Count() is < 1 or > 16 || nickname.Any(char.IsControl)) throw new PlayerActionException(-2, "昵称不合法");
        Comp.Nickname = nickname;
        if (sync) Player.Trigger(PlayerEventType.MainDataChanged);
    }
    public void SetLanguage(string language)
    {
        if (language is not ("zh-cn" or "zh-tw" or "en-us" or "ja-jp" or "ko-kr")) throw new PlayerActionException(-2, "不支持的语言");
        Comp.Language = language;
    }
    public void RecordRpc(uint rpcId)
    {
        if (rpcId > Comp.LastRpcId) Comp.LastRpcId = rpcId;
    }
    public void RecoverStamina()
    {
        long now = Time.Now.ToUnixTimeSeconds();
        if (Stamina >= StaminaLimit) { Comp.LastStaminaTime = now; return; }
        long elapsed = Math.Max(0, now - Comp.LastStaminaTime);
        uint recovered = (uint)Math.Min(StaminaLimit - Stamina, elapsed / 360);
        Comp.Stamina += recovered; Comp.LastStaminaTime += recovered * 360L;
        if (Stamina >= StaminaLimit) Comp.LastStaminaTime = now;
    }
    public void SpendStamina(uint count, bool sync = true)
    {
        if (Stamina < count) throw new PlayerActionException(-3, "体力不足");
        if (Stamina >= StaminaLimit) Comp.LastStaminaTime = Time.Now.ToUnixTimeSeconds();
        Comp.Stamina -= count;
        if (sync) Player.Trigger(PlayerEventType.MainDataChanged);
    }
    public void CheckAddExp(uint count)
    {
        if ((ulong)Exp + count > uint.MaxValue) throw new PlayerActionException(-2, "经验超过上限");
    }
    public void AddExp(uint count, bool sync = true)
    {
        CheckAddExp(count); Comp.Exp += count;
        while (GameTableCatalog.Instance.GetDataById<PlayerLevelData>(Level)!.NextLevel is not null)
        {
            uint required = checked((uint)GameTableCatalog.Instance.GetDataById<PlayerLevelData>(Level)!.NextLevelExp);
            if (required == 0 || Comp.Exp < required) break;
            Comp.Exp -= required; Comp.Level++;
        }
        if (sync) Player.Trigger(PlayerEventType.MainDataChanged);
    }
    public void CheckAddStamina(uint count)
    {
        if ((ulong)Stamina + count > uint.MaxValue) throw new PlayerActionException(-2, "体力超过上限");
    }
    public void AddStamina(uint count, bool sync = true)
    {
        CheckAddStamina(count); Comp.Stamina += count;
        if (sync) Player.Trigger(PlayerEventType.MainDataChanged);
    }
}

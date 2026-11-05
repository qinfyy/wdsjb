using Pbplayer;
using Sv.Configuration;
using Sv.Database;
using Sv.Game;

namespace Sv.Gateway.Handlers;

public static class AccountHandler
{
    public static void Ping(GatewaySession session, byte[] request)
    {
        Pbmisc.PingReq req = Pbmisc.PingReq.Parser.ParseFrom(request);
        session.Send((ushort)Pbmisc.PingRsp.Types.CmdId.CmdId, new Pbmisc.PingRsp { Seq = req.Seq }, session.RequestHead);
    }
    public static void GetToken(GatewaySession session, byte[] request)
    {
        GetPlayerTokenReq req = GetPlayerTokenReq.Parser.ParseFrom(request);
        if (session.IsLoggedIn) throw new PlayerActionException(-2, "当前连接已经登录");
        if (req.UseCombo != 1 || req.ComboChannelId > int.MaxValue || !GameDatabase.Instance.ValidateAccountComboToken((int)req.ComboChannelId, req.ComboOpenId, req.ComboToken))
            throw new PlayerActionException(-420, "SDK combo 令牌无效");
        Player player = GameDatabase.Instance.GetOrCreateByAccount((int)req.ComboChannelId, req.ComboOpenId);
        session.Authenticate(player);
        session.Send((ushort)GetPlayerTokenRsp.Types.CmdId.CmdId, new GetPlayerTokenRsp { Retcode = 1, Uid = player.Uid }, session.RequestHead);
    }
    public static void Login(GatewaySession session, byte[] request)
    {
        PlayerLoginReq req = PlayerLoginReq.Parser.ParseFrom(request);
        Player player = session.Player ?? throw new PlayerActionException(-420, "先取得玩家令牌");
        lock (player.SyncRoot)
        {
            if (session.IsLoggedIn) throw new PlayerActionException(-2, "重复登录");
            if (req.ClientVersion != Config.Server.ClientVersion) throw new PlayerActionException(-2, "客户端版本不匹配");
            if (player.Profile.LastRpcId == uint.MaxValue) throw new PlayerActionException(-2, "RPC 游标已用尽");
            if (req.Lang.Length != 0) player.Profile.SetLanguage(req.Lang);
            bool first = player.Profile.LoginCount == 0;
            session.Login(); player.OnLogin(); player.Save();
            session.Send((ushort)PlayerLoginRsp.Types.CmdId.CmdId, new PlayerLoginRsp
            {
                Retcode = 1, IsFirstLogin = first ? 1u : 0u, LastRpcId = player.Profile.LastRpcId, NextRpcId = player.Profile.LastRpcId + 1,
            }, session.RequestHead);
        }
    }
    public static void Logout(GatewaySession session, byte[] request)
    {
        _ = PlayerLogoutReq.Parser.ParseFrom(request);
        Player player = session.Player ?? throw new PlayerActionException(-420, "连接尚未登录");
        lock (player.SyncRoot)
        {
            player.Level.Abandon(); player.Save();
            session.Send((ushort)PlayerLogoutRsp.Types.CmdId.CmdId, new PlayerLogoutRsp { Retcode = 1 }, session.RequestHead); session.DetachPlayer();
        }
    }
}

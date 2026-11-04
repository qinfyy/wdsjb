using Google.Protobuf;
using Pbplayer;
using Serilog;
using Sv.Game;
using Sv.Gateway.Handlers;

namespace Sv.Gateway;

public sealed class GatewayRouter
{
    private readonly Dictionary<ushort, Action<GatewaySession, byte[]>> _handlers = [];
    public GatewayRouter()
    {
        Register(Pbmisc.PingReq.Types.CmdId.CmdId, AccountHandler.Ping);
        Register(GetPlayerTokenReq.Types.CmdId.CmdId, AccountHandler.GetToken);
        Register(PlayerLoginReq.Types.CmdId.CmdId, AccountHandler.Login);
        Register(PlayerLogoutReq.Types.CmdId.CmdId, AccountHandler.Logout);
        Register(Pbmisc.SetLangReq.Types.CmdId.CmdId, PlayerHandler.SetLanguage);
        Register(GetMainDataReq.Types.CmdId.CmdId, PlayerHandler.GetMainData);
        Register(GetCardDataReq.Types.CmdId.CmdId, PlayerHandler.GetCards);
        Register(GetDeckDataReq.Types.CmdId.CmdId, PlayerHandler.GetDecks);
        Register(ChangeDeckReq.Types.CmdId.CmdId, PlayerHandler.ChangeDeck);
        Register(GetMaterialDataReq.Types.CmdId.CmdId, PlayerHandler.GetMaterials);
        Register(GetWalletDataReq.Types.CmdId.CmdId, PlayerHandler.GetWallet);
        Register(GetTicketDataReq.Types.CmdId.CmdId, PlayerHandler.GetTickets);
        Register(NickNameModifyReq.Types.CmdId.CmdId, PlayerHandler.Rename);
        Register(GetGuideInfoReq.Types.CmdId.CmdId, ProgressHandler.GetGuides);
        Register(StartGuideReq.Types.CmdId.CmdId, ProgressHandler.StartGuide);
        Register(PlayGuideReq.Types.CmdId.CmdId, ProgressHandler.PlayGuide);
        Register(GetStoryDataReq.Types.CmdId.CmdId, ProgressHandler.GetStories);
        Register(PlayStoryReq.Types.CmdId.CmdId, ProgressHandler.PlayStory);
        Register(ReadStoryReq.Types.CmdId.CmdId, ProgressHandler.ReadStory);
        Register(GetLevelDataReq.Types.CmdId.CmdId, ProgressHandler.GetLevels);
        Register(LevelBeginReq.Types.CmdId.CmdId, ProgressHandler.BeginLevel);
        Register(LevelEndReq.Types.CmdId.CmdId, ProgressHandler.EndLevel);
    }
    private void Register<T>(T cmdId, Action<GatewaySession, byte[]> handler) where T : struct, Enum
    {
        _handlers.Add(Convert.ToUInt16(cmdId), handler);
    }
    public void Dispatch(GatewaySession session, ushort id, byte[] body)
    {
        if (!_handlers.TryGetValue(id, out Action<GatewaySession, byte[]>? handler))
        {
            Log.Warning("未注册 TCP 命令: {Command}", id); session.Close(); return;
        }
        try
        {
            if (id == (ushort)Pbmisc.PingReq.Types.CmdId.CmdId || id == (ushort)GetPlayerTokenReq.Types.CmdId.CmdId || id == (ushort)PlayerLoginReq.Types.CmdId.CmdId)
            {
                handler(session, body);
                return;
            }
            Player player = session.Player ?? throw new PlayerActionException(-420, "连接尚未认证");
            lock (player.SyncRoot)
            {
                if (!session.IsLoggedIn || player.Session != session) throw new PlayerActionException(-420, "连接尚未登录或已被替换");
                handler(session, body);
            }
        }
        catch (PlayerActionException exception) { Error(session, id, exception.Retcode, exception.Message); }
        catch (InvalidProtocolBufferException) { Error(session, id, -2, "protobuf 请求格式错误"); }
        catch (Exception exception)
        {
            Log.Error(exception, "处理 TCP 命令 {Command} 失败", id); session.Close();
        }
    }
    private static void Error(GatewaySession session, ushort id, int retcode, string reason)
    {
        (ushort CmdId, IMessage? Message) response = id switch
        {
            (ushort)GetPlayerTokenReq.Types.CmdId.CmdId => ((ushort)GetPlayerTokenRsp.Types.CmdId.CmdId, new GetPlayerTokenRsp { Retcode = retcode, Msg = reason }),
            (ushort)PlayerLoginReq.Types.CmdId.CmdId => ((ushort)PlayerLoginRsp.Types.CmdId.CmdId, new PlayerLoginRsp { Retcode = retcode, Msg = reason }),
            (ushort)PlayerLogoutReq.Types.CmdId.CmdId => ((ushort)PlayerLogoutRsp.Types.CmdId.CmdId, new PlayerLogoutRsp { Retcode = retcode }),
            (ushort)Pbmisc.SetLangReq.Types.CmdId.CmdId => ((ushort)Pbmisc.SetLangRsp.Types.CmdId.CmdId, new Pbmisc.SetLangRsp { Retcode = retcode, Msg = reason }),
            (ushort)GetMainDataReq.Types.CmdId.CmdId => ((ushort)GetMainDataRsp.Types.CmdId.CmdId, new GetMainDataRsp { Retcode = retcode, Msg = reason }),
            (ushort)GetCardDataReq.Types.CmdId.CmdId => ((ushort)GetCardDataRsp.Types.CmdId.CmdId, new GetCardDataRsp { Retcode = retcode }),
            (ushort)GetDeckDataReq.Types.CmdId.CmdId => ((ushort)GetDeckDataRsp.Types.CmdId.CmdId, new GetDeckDataRsp { Retcode = retcode, Msg = reason }),
            (ushort)ChangeDeckReq.Types.CmdId.CmdId => ((ushort)ChangeDeckRsp.Types.CmdId.CmdId, new ChangeDeckRsp { Retcode = retcode, Msg = reason }),
            (ushort)GetMaterialDataReq.Types.CmdId.CmdId => ((ushort)GetMaterialDataRsp.Types.CmdId.CmdId, new GetMaterialDataRsp { Retcode = retcode }),
            (ushort)GetWalletDataReq.Types.CmdId.CmdId => ((ushort)GetWalletDataRsp.Types.CmdId.CmdId, new GetWalletDataRsp { Retcode = retcode, Msg = reason }),
            (ushort)GetTicketDataReq.Types.CmdId.CmdId => ((ushort)GetTicketDataRsp.Types.CmdId.CmdId, new GetTicketDataRsp { Retcode = retcode, Msg = reason }),
            (ushort)NickNameModifyReq.Types.CmdId.CmdId => ((ushort)NickNameModifyRsp.Types.CmdId.CmdId, new NickNameModifyRsp { Retcode = retcode, Msg = reason }),
            (ushort)GetGuideInfoReq.Types.CmdId.CmdId => ((ushort)GetGuideInfoRsp.Types.CmdId.CmdId, new GetGuideInfoRsp { Retcode = retcode }),
            (ushort)StartGuideReq.Types.CmdId.CmdId => ((ushort)StartGuideRsp.Types.CmdId.CmdId, new StartGuideRsp { Retcode = retcode }),
            (ushort)PlayGuideReq.Types.CmdId.CmdId => ((ushort)PlayGuideRsp.Types.CmdId.CmdId, new PlayGuideRsp { Retcode = retcode }),
            (ushort)GetStoryDataReq.Types.CmdId.CmdId => ((ushort)GetStoryDataRsp.Types.CmdId.CmdId, new GetStoryDataRsp { Retcode = retcode, Msg = reason }),
            (ushort)PlayStoryReq.Types.CmdId.CmdId => ((ushort)PlayStoryRsp.Types.CmdId.CmdId, new PlayStoryRsp { Retcode = retcode, Msg = reason }),
            (ushort)ReadStoryReq.Types.CmdId.CmdId => ((ushort)ReadStoryRsp.Types.CmdId.CmdId, new ReadStoryRsp { Retcode = retcode, Msg = reason }),
            (ushort)GetLevelDataReq.Types.CmdId.CmdId => ((ushort)GetLevelDataRsp.Types.CmdId.CmdId, new GetLevelDataRsp { Retcode = retcode, Msg = reason }),
            (ushort)LevelBeginReq.Types.CmdId.CmdId => ((ushort)LevelBeginRsp.Types.CmdId.CmdId, new LevelBeginRsp { Retcode = retcode, Msg = reason }),
            (ushort)LevelEndReq.Types.CmdId.CmdId => ((ushort)LevelEndRsp.Types.CmdId.CmdId, new LevelEndRsp { Retcode = retcode, Msg = reason }),
            _ => (0, null),
        };
        if (response.Message is null) session.Close();
        else session.Send(response.CmdId, response.Message, session.RequestHead);
        Log.Debug("拒绝 TCP 命令 {Command}: {Retcode} {Reason}", id, retcode, reason);
    }
}

using Pbplayer;
using Sv.Game;

namespace Sv.Gateway.Handlers;

public static class PlayerHandler
{
    private static Player RequirePlayer(GatewaySession session, bool requireRpc = false)
    {
        Player player = session.Player ?? throw new PlayerActionException(-420, "连接尚未登录");
        if (requireRpc && (session.RequestHead.RpcId == 0 || session.RequestHead.RpcId <= player.Profile.LastRpcId))
            throw new PlayerActionException(-2, "RPC 游标重复或无效");
        return player;
    }
    public static void GetMainData(GatewaySession session, byte[] request)
    {
        GetMainDataReq req = GetMainDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            player.Profile.RecoverStamina(); player.Save();
            GetMainDataRsp response = player.Profile.CreateMainData(req.DataAll); response.TypeList.Add(req.TypeList);
            session.Send((ushort)GetMainDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void GetCards(GatewaySession session, byte[] request)
    {
        GetCardDataReq req = GetCardDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetCardDataRsp response = player.Inventory.CreateCardData(req.CardDataAll, req.CardIdList);
            session.Send((ushort)GetCardDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void GetDecks(GatewaySession session, byte[] request)
    {
        GetDeckDataReq req = GetDeckDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetDeckDataRsp response = player.Inventory.CreateDeckData(req.DeckDataAll, req.DeckIdList);
            session.Send((ushort)GetDeckDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void GetMaterials(GatewaySession session, byte[] request)
    {
        GetMaterialDataReq req = GetMaterialDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetMaterialDataRsp response = player.Inventory.CreateMaterialData(req.MaterialDataAll, req.MaterialIdList);
            session.Send((ushort)GetMaterialDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void GetWallet(GatewaySession session, byte[] request)
    {
        GetWalletDataReq req = GetWalletDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetWalletDataRsp response = player.Wallet.CreateWalletData(req.WalletDataAll, req.WalletIdList);
            session.Send((ushort)GetWalletDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void GetTickets(GatewaySession session, byte[] request)
    {
        GetTicketDataReq req = GetTicketDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetTicketDataRsp response = player.Wallet.CreateTicketData(req.TicketDataAll, req.TicketIdList);
            session.Send((ushort)GetTicketDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void Rename(GatewaySession session, byte[] request)
    {
        NickNameModifyReq req = NickNameModifyReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            player.Profile.Rename(req.Nickname, sync: false); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)NickNameModifyRsp.Types.CmdId.CmdId, new NickNameModifyRsp { Retcode = 1 }, session.RequestHead);
            player.Trigger(PlayerEventType.MainDataChanged);
        }
    }
    public static void SetLanguage(GatewaySession session, byte[] request)
    {
        Pbmisc.SetLangReq req = Pbmisc.SetLangReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            player.Profile.SetLanguage(req.Lang); player.Save();
            session.Send((ushort)Pbmisc.SetLangRsp.Types.CmdId.CmdId, new Pbmisc.SetLangRsp { Retcode = 1 }, session.RequestHead);
        }
    }
    public static void ChangeDeck(GatewaySession session, byte[] request)
    {
        ChangeDeckReq req = ChangeDeckReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        DeckItem deck = req.DeckItem ?? throw new PlayerActionException(-2, "缺少卡组");
        lock (player.SyncRoot)
        {
            uint[] main = deck.MainCardGroup?.CardItems.Select(item => item.CardId).ToArray() ?? [];
            uint[] assist = deck.AssistCardGroup?.CardItems.Select(item => item.CardId).ToArray() ?? [];
            player.Inventory.ChangeDeck(deck.DeckId, deck.DeckName, main, assist, sync: false);
            player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)ChangeDeckRsp.Types.CmdId.CmdId, new ChangeDeckRsp { Retcode = 1 }, session.RequestHead);
            player.Trigger(PlayerEventType.DecksChanged);
        }
    }
}

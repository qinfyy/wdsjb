using Pbplayer;
using Sv.Game;

namespace Sv.Gateway.Handlers;

public static class ProgressHandler
{
    private static Player RequirePlayer(GatewaySession session, bool requireRpc = false)
    {
        Player player = session.Player ?? throw new PlayerActionException(-420, "连接尚未登录");
        if (requireRpc && (session.RequestHead.RpcId == 0 || session.RequestHead.RpcId <= player.Profile.LastRpcId))
            throw new PlayerActionException(-2, "RPC 游标重复或无效");
        return player;
    }
    public static void GetGuides(GatewaySession session, byte[] request)
    {
        _ = GetGuideInfoReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot) session.Send((ushort)GetGuideInfoRsp.Types.CmdId.CmdId, player.Guide.CreateGuideData(), session.RequestHead);
    }
    public static void StartGuide(GatewaySession session, byte[] request)
    {
        StartGuideReq req = StartGuideReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            player.Guide.Start(req.GuideId); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)StartGuideRsp.Types.CmdId.CmdId, new StartGuideRsp { Retcode = 1 }, session.RequestHead);
        }
    }
    public static void PlayGuide(GatewaySession session, byte[] request)
    {
        PlayGuideReq req = PlayGuideReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            player.Guide.Complete(req.GuideId); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)PlayGuideRsp.Types.CmdId.CmdId, new PlayGuideRsp { Retcode = 1 }, session.RequestHead);
        }
    }
    public static void GetStories(GatewaySession session, byte[] request)
    {
        GetStoryDataReq req = GetStoryDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetStoryDataRsp response = player.Story.CreateStoryData(req.StoryDataAll, req.StoryIdList);
            session.Send((ushort)GetStoryDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void PlayStory(GatewaySession session, byte[] request)
    {
        PlayStoryReq req = PlayStoryReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            player.Story.Complete(req.StoryId); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)PlayStoryRsp.Types.CmdId.CmdId, new PlayStoryRsp { Retcode = 1 }, session.RequestHead);
        }
    }
    public static void ReadStory(GatewaySession session, byte[] request)
    {
        ReadStoryReq req = ReadStoryReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            player.Story.Complete(req.StoryId); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)ReadStoryRsp.Types.CmdId.CmdId, new ReadStoryRsp { Retcode = 1 }, session.RequestHead);
        }
    }
    public static void GetLevels(GatewaySession session, byte[] request)
    {
        GetLevelDataReq req = GetLevelDataReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session);
        lock (player.SyncRoot)
        {
            GetLevelDataRsp response = player.Level.CreateLevelData(req.LevelDataAll, req.LevelIdList);
            session.Send((ushort)GetLevelDataRsp.Types.CmdId.CmdId, response, session.RequestHead);
        }
    }
    public static void BeginLevel(GatewaySession session, byte[] request)
    {
        LevelBeginReq req = LevelBeginReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            uint seed = player.Level.Begin(req.LevelId); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)LevelBeginRsp.Types.CmdId.CmdId, new LevelBeginRsp { Retcode = 1, LevelId = req.LevelId, Seed = seed }, session.RequestHead);
        }
    }
    public static void EndLevel(GatewaySession session, byte[] request)
    {
        LevelEndReq req = LevelEndReq.Parser.ParseFrom(request);
        Player player = RequirePlayer(session, requireRpc: true);
        lock (player.SyncRoot)
        {
            uint previousLevel = player.Profile.Level;
            bool first = player.Level.Complete(req.LevelId, sync: false); player.Profile.RecordRpc(session.RequestHead.RpcId); player.Save();
            session.Send((ushort)LevelEndRsp.Types.CmdId.CmdId, player.Level.CreateLevelEnd(req.LevelId, first, previousLevel), session.RequestHead);
            player.Trigger(PlayerEventType.LevelSettled, checked((int)req.LevelId), first ? 1 : 0);
        }
    }
}

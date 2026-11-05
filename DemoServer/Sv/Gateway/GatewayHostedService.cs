using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using Serilog;
using Sv.Configuration;
using Sv.Database;
using Sv.Game;

namespace Sv.Gateway;

public sealed class GatewayHostedService : BackgroundService
{
    private readonly TcpListener _listener = new(IPAddress.Any, Config.Server.GamePort);
    private readonly ConcurrentDictionary<GatewaySession, Task> _sessions = new();
    private long _nextConnectionId;
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _listener.Start(); Log.Information("TCP 网关已启动: {Port}", Config.Server.GamePort);
        using CancellationTokenSource lifetime = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
        Task accept = AcceptLoopAsync(lifetime.Token), save = SaveLoopAsync(lifetime.Token);
        try
        {
            await Task.WhenAny(accept, save);
            lifetime.Cancel(); _listener.Stop();
            await Task.WhenAll(accept, save);
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        finally
        {
            foreach (GatewaySession session in _sessions.Keys) session.Close();
            await Task.WhenAll(_sessions.Values.ToArray());
            SavePlayers();
        }
    }
    private async Task AcceptLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            TcpClient client = await _listener.AcceptTcpClientAsync(cancellationToken);
            GatewaySession session = new(client, Config.Server, Interlocked.Increment(ref _nextConnectionId));
            _sessions[session] = RunSessionAsync(session, cancellationToken);
        }
    }
    private async Task RunSessionAsync(GatewaySession session, CancellationToken cancellationToken)
    {
        await Task.Yield();
        try { await session.RunAsync(cancellationToken); }
        catch (Exception exception) { Log.Error(exception, "连接清理异常"); }
        finally { _sessions.TryRemove(session, out _); }
    }
    private static async Task SaveLoopAsync(CancellationToken cancellationToken)
    {
        using PeriodicTimer timer = new(TimeSpan.FromSeconds(Config.Server.SaveIntervalSeconds));
        while (await timer.WaitForNextTickAsync(cancellationToken)) SavePlayers();
    }
    private static void SavePlayers()
    {
        foreach (Player player in GameDatabase.Instance.GetLoadedPlayers())
        {
            lock (player.SyncRoot)
            {
                player.Profile.RecoverStamina(); player.Save();
            }
        }
    }
}

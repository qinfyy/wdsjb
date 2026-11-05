using System.Net.Sockets;
using System.Threading.Channels;
using Baseproto;
using Google.Protobuf;
using Serilog;
using Sv.Configuration;
using Sv.Game;
using Sv.Gateway.Protocol;

namespace Sv.Gateway;

public sealed class GatewaySession
{
    private readonly ServerOptions options;
    private readonly CancellationTokenSource _closed;
    private readonly object _sendLock;
    private uint _packetId;
    private SessionCryptography? _cryptography;
    private readonly long _connectionId;
    private readonly Channel<byte[]> _outgoing;
    public Player? Player { get; private set; }
    public bool IsLoggedIn { get; private set; }
    public PacketHead RequestHead { get; private set; }
    public bool IsClosed => _closed.IsCancellationRequested;
    private ILogger logger;
    private TcpClient? client;

    public GatewaySession(TcpClient client, ServerOptions options, long connectionId)
    {
        this.client = client;
        this.options = options;
        _closed = new();
        _sendLock = new();
        _connectionId = connectionId;
        _outgoing = Channel.CreateBounded<byte[]>(new BoundedChannelOptions(256) { SingleReader = true, FullMode = BoundedChannelFullMode.Wait });
        RequestHead = new();
        logger = Log.ForContext<GatewaySession>().ForContext("ConnectionId", _connectionId);
    }

    public async Task RunAsync(CancellationToken stoppingToken)
    {
        TcpClient? connection = client;
        if (connection is null || IsClosed) return;
        using CancellationTokenSource lifetime = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken, _closed.Token);
        connection.NoDelay = true;
        using NetworkStream stream = connection.GetStream();
        Task sender = SendLoopAsync(stream, lifetime.Token);
        try
        {
            while (!lifetime.IsCancellationRequested)
            {
                using CancellationTokenSource readTimeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                readTimeout.CancelAfter(TimeSpan.FromSeconds(options.IdleTimeoutSeconds));
                NetPacket? packet = await ReadPacketAsync(stream, readTimeout.Token);
                if (packet is null) break;
                RequestHead = packet.Head;
                logger.Information("TCP {Connection} 收包 {Command} 包序号 {PacketId} 长度 {Length}", _connectionId, packet.CmdId, packet.Head.PacketId, packet.Body.Length);
                GatewayRouter.Dispatch(this, packet.CmdId, packet.Body);
            }
        }
        catch (Exception exception) when (exception is OperationCanceledException or IOException or SocketException or InvalidDataException or InvalidProtocolBufferException)
        {
            if (!lifetime.IsCancellationRequested)
                logger.Information("TCP {Connection} 连接结束，玩家 {Uid}，已登录 {LoggedIn}: {Reason}；底层原因 {Detail}",
                    _connectionId, Player?.Uid, IsLoggedIn, exception.Message, exception.InnerException?.Message);
        }
        catch (Exception exception) { logger.Error(exception, "TCP 会话异常"); }
        finally
        {
            Close();
            try { await sender; } catch (Exception exception) when (exception is OperationCanceledException or IOException or SocketException) { }
            DetachPlayer();
            lock (_sendLock) _cryptography?.Dispose();
        }
    }
    private async Task SendLoopAsync(NetworkStream stream, CancellationToken cancellationToken)
    {
        try
        {
            await foreach (byte[] frame in _outgoing.Reader.ReadAllAsync(cancellationToken)) await stream.WriteAsync(frame, cancellationToken);
        }
        catch (Exception exception) when (exception is OperationCanceledException or IOException or SocketException or ObjectDisposedException)
        {
            if (!cancellationToken.IsCancellationRequested) logger.Information("TCP {Connection} 发送结束: {Reason}", _connectionId, exception.Message);
        }
        finally { Close(); }
    }
    private async ValueTask<NetPacket?> ReadPacketAsync(Stream stream, CancellationToken cancellationToken)
    {
        byte[] prefix = new byte[NetPacket.PrefixSize];
        if (await stream.ReadAsync(prefix.AsMemory(0, 1), cancellationToken) == 0) return null;
        await stream.ReadExactlyAsync(prefix.AsMemory(1), cancellationToken);
        int length = NetPacket.GetFrameLength(prefix, options.MaxFrameBytes);
        byte[] frame = new byte[length]; prefix.CopyTo(frame, 0);
        await stream.ReadExactlyAsync(frame.AsMemory(NetPacket.PrefixSize), cancellationToken);
        NetPacket packet = new(); packet.UnPack(frame, options.MaxFrameBytes, _cryptography is null ? [] : _cryptography.ReceiveKey);
        return packet;
    }
    public void Authenticate(Player player)
    {
        if (IsLoggedIn) throw new PlayerActionException(-2, "当前连接已经登录");
        _cryptography?.Dispose();
        _cryptography = new SessionCryptography();
        Player = player;
    }
    public void Login()
    {
        if (IsLoggedIn) throw new PlayerActionException(-2, "当前连接已经登录");
        Player player = Player ?? throw new PlayerActionException(-420, "连接尚未认证");
        if (_cryptography is null || !_cryptography.ValidateLogin(RequestHead, player.Uid)) throw new PlayerActionException(-420, "登录会话握手无效，请重新取得令牌");
        if (!Monitor.IsEntered(player.SyncRoot)) throw new InvalidOperationException("会话绑定必须持有玩家锁");
        if (IsClosed) throw new PlayerActionException(-420, "连接已经关闭");
        GatewaySession? previous = player.Session;
        player.Session = this; IsLoggedIn = true;
        if (previous is not null && previous != this) previous.Close();
    }
    public void DetachPlayer()
    {
        Player? player = Player;
        if (player is not null)
        {
            lock (player.SyncRoot)
            {
                if (player.Session == this)
                {
                    player.Level.Abandon(); player.Save(); player.Session = null;
                }
            }
        }
        Player = null; IsLoggedIn = false;
    }
    public void Close()
    {
        if (!IsClosed) logger.Information("TCP {Connection} 关闭，玩家 {Uid}，最后请求 {Command}", _connectionId, Player?.Uid, RequestHead.PacketId);
        _outgoing.Writer.TryComplete(); _closed.Cancel(); client?.Close();
    }
    public void Send(ushort cmdId, IMessage message, PacketHead? request = null)
    {
        lock (_sendLock)
        {
            if (IsClosed) return;
            PacketHead head = new()
            {
                PacketId = checked(++_packetId), RpcId = request?.RpcId ?? 0, ClientSequenceId = request?.ClientSequenceId ?? 0,
                ClientTs = request?.ClientTs ?? 0, UserId = Player?.Uid ?? 0, EnetIsReliable = 1,
            };
            if (cmdId == (ushort)Pbplayer.GetPlayerTokenRsp.Types.CmdId.CmdId && message is Pbplayer.GetPlayerTokenRsp { Retcode: 1 }) _cryptography!.WriteHandshake(head);
            NetPacket packet = new(cmdId, message, head);
            logger.Information("TCP {Connection} 发包 {Command} 包序号 {PacketId} 长度 {Length}", _connectionId, cmdId, head.PacketId, packet.Body.Length);
            if (!_outgoing.Writer.TryWrite(packet.Pack(options.MaxFrameBytes, _cryptography is null ? [] : _cryptography.SendKey))) Close();
        }
    }
}

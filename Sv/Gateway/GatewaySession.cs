using System.Buffers.Binary;
using System.Net.Sockets;
using System.Threading.Channels;
using Baseproto;
using Google.Protobuf;
using Serilog;
using Sv.Configuration;
using Sv.Game;
using Sv.Gateway.Protocol;

namespace Sv.Gateway;

public sealed class GatewaySession(TcpClient client, GatewayRouter router, ServerOptions options)
{
    private readonly CancellationTokenSource _closed = new();
    private readonly Channel<byte[]> _outgoing = Channel.CreateBounded<byte[]>(new BoundedChannelOptions(256) { SingleReader = true, FullMode = BoundedChannelFullMode.Wait });
    public Player? Player { get; private set; }
    public bool IsLoggedIn { get; private set; }
    public PacketHead RequestHead { get; private set; } = new();
    public bool IsClosed => _closed.IsCancellationRequested;

    public async Task RunAsync(CancellationToken stoppingToken)
    {
        using CancellationTokenSource lifetime = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken, _closed.Token);
        client.NoDelay = true;
        using NetworkStream stream = client.GetStream();
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
                router.Dispatch(this, packet.CmdId, packet.Body);
            }
        }
        catch (Exception exception) when (exception is OperationCanceledException or IOException or SocketException or InvalidDataException or InvalidProtocolBufferException)
        {
            if (!lifetime.IsCancellationRequested) Log.Information("TCP 连接结束: {Reason}", exception.Message);
        }
        catch (Exception exception) { Log.Error(exception, "TCP 会话异常"); }
        finally
        {
            Close();
            try { await sender; } catch (Exception exception) when (exception is OperationCanceledException or IOException or SocketException) { }
            DetachPlayer();
        }
    }
    private async Task SendLoopAsync(NetworkStream stream, CancellationToken cancellationToken)
    {
        try
        {
            await foreach (byte[] frame in _outgoing.Reader.ReadAllAsync(cancellationToken)) await stream.WriteAsync(frame, cancellationToken);
        }
        finally { Close(); }
    }
    private async ValueTask<NetPacket?> ReadPacketAsync(Stream stream, CancellationToken cancellationToken)
    {
        byte[] prefix = new byte[NetPacket.PrefixSize];
        if (await stream.ReadAsync(prefix.AsMemory(0, 1), cancellationToken) == 0) return null;
        await stream.ReadExactlyAsync(prefix.AsMemory(1), cancellationToken);
        if (BinaryPrimitives.ReadUInt16BigEndian(prefix) != NetPacket.BeginMagic) throw new InvalidDataException("帧头标记无效");
        int headLength = BinaryPrimitives.ReadUInt16BigEndian(prefix.AsSpan(4));
        uint bodyLength = BinaryPrimitives.ReadUInt32BigEndian(prefix.AsSpan(6));
        long length = (long)NetPacket.FixedSize + headLength + bodyLength;
        if (length > options.MaxFrameBytes || length > int.MaxValue) throw new InvalidDataException("接收帧超过长度上限");
        byte[] frame = new byte[(int)length]; prefix.CopyTo(frame, 0);
        await stream.ReadExactlyAsync(frame.AsMemory(NetPacket.PrefixSize), cancellationToken);
        NetPacket packet = new(); packet.UnPack(frame, options.MaxFrameBytes);
        return packet;
    }
    public void Authenticate(Player player)
    {
        if (IsLoggedIn) throw new PlayerActionException(-2, "当前连接已经登录");
        Player = player;
    }
    public void Login()
    {
        if (IsLoggedIn) throw new PlayerActionException(-2, "当前连接已经登录");
        Player player = Player ?? throw new PlayerActionException(-420, "连接尚未认证");
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
        _outgoing.Writer.TryComplete(); _closed.Cancel(); client.Close();
    }
    public void Send(ushort cmdId, IMessage message, PacketHead? request = null)
    {
        if (IsClosed) return;
        PacketHead head = new()
        {
            PacketId = cmdId, RpcId = request?.RpcId ?? 0, ClientSequenceId = request?.ClientSequenceId ?? 0,
            UserId = Player?.Uid ?? 0, EnetIsReliable = 1,
        };
        NetPacket packet = new(cmdId, message, head);
        if (!_outgoing.Writer.TryWrite(packet.Pack(options.MaxFrameBytes))) Close();
    }
}

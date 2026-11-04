using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using Baseproto;
using Google.Protobuf;
using Pbmisc;
using Sv.Configuration;
using Sv.Gateway;
using Sv.Gateway.Handlers;
using Sv.Gateway.Protocol;
using Xunit;

namespace Sv.Tests;

public sealed class GatewayTests
{
    [Fact]
    public async Task RawHandlerRoutesFragmentedAndCoalescedPackets()
    {
        using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start();
        using TcpClient client = new(); await client.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
        using TcpClient accepted = await listener.AcceptTcpClientAsync();
        GatewaySession session = new(accepted, new GatewayRouter(), new ServerOptions());
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(10));
        Task running = session.RunAsync(timeout.Token);
        try
        {
            NetworkStream stream = client.GetStream();
            byte[] first = new NetPacket(5, new PingReq { Seq = 21 }, new PacketHead { PacketId = 5, RpcId = 2, ClientSequenceId = 3 }).Pack(65536);
            byte[] second = new NetPacket(5, new PingReq { Seq = 22 }, new PacketHead { PacketId = 5, RpcId = 4 }).Pack(65536);
            await stream.WriteAsync(first.AsMemory(0, 3), timeout.Token);
            byte[] rest = [.. first.AsSpan(3).ToArray(), .. second]; await stream.WriteAsync(rest, timeout.Token);
            NetPacket response = await ReadPacketAsync(stream, timeout.Token);
            Assert.Equal((ushort)PingRsp.Types.CmdId.CmdId, response.CmdId); Assert.Equal(21u, PingRsp.Parser.ParseFrom(response.Body).Seq);
            Assert.Equal(2u, response.Head.RpcId); Assert.Equal(3u, response.Head.ClientSequenceId);
            NetPacket next = await ReadPacketAsync(stream, timeout.Token); Assert.Equal(22u, PingRsp.Parser.ParseFrom(next.Body).Seq);
        }
        finally { session.Close(); await running; }
    }
    [Fact]
    public async Task SendUsesExplicitCommandAndOptionalRequestHead()
    {
        using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start();
        using TcpClient client = new(); await client.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
        using TcpClient accepted = await listener.AcceptTcpClientAsync();
        GatewaySession session = new(accepted, new GatewayRouter(), new ServerOptions());
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(10));
        Task running = session.RunAsync(timeout.Token);
        try
        {
            session.Send(60000, new PingRsp { Seq = 42 }, new PacketHead { RpcId = 7, ClientSequenceId = 8 });
            NetPacket response = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)60000, response.CmdId); Assert.Equal(7u, response.Head.RpcId); Assert.Equal(8u, response.Head.ClientSequenceId);
            Assert.Equal(42u, PingRsp.Parser.ParseFrom(response.Body).Seq);
            session.Send(60001, new PingRsp { Seq = 43 });
            NetPacket notification = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)60001, notification.CmdId); Assert.Equal(0u, notification.Head.RpcId);
            Assert.True(notification.Head.SessionValue1.IsEmpty); Assert.True(notification.Head.SessionValue2.IsEmpty);
            Assert.Empty(notification.Head.SessionValue3);
        }
        finally { session.Close(); await running; }
    }
    [Fact]
    public void HandlersUseRawRequestSignatureAndSessionHasOnlyOneSendMethod()
    {
        Action<GatewaySession, byte[]> handler = AccountHandler.Ping;
        Assert.NotNull(handler);
        var methods = typeof(GatewaySession).GetMethods().Where(method => method.Name.StartsWith("Send", StringComparison.Ordinal)).ToArray();
        var send = Assert.Single(methods); Assert.Equal("Send", send.Name);
        Assert.Equal(new[] { typeof(ushort), typeof(IMessage), typeof(PacketHead) }, send.GetParameters().Select(parameter => parameter.ParameterType).ToArray());
    }
    private static async Task<NetPacket> ReadPacketAsync(Stream stream, CancellationToken cancellationToken)
    {
        byte[] prefix = new byte[10]; await stream.ReadExactlyAsync(prefix, cancellationToken);
        int head = BinaryPrimitives.ReadUInt16BigEndian(prefix.AsSpan(4)); uint body = BinaryPrimitives.ReadUInt32BigEndian(prefix.AsSpan(6));
        byte[] frame = new byte[12 + head + body]; prefix.CopyTo(frame, 0);
        await stream.ReadExactlyAsync(frame.AsMemory(10), cancellationToken);
        NetPacket packet = new(); packet.UnPack(frame, 65536); return packet;
    }
}

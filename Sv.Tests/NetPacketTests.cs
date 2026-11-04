using System.Buffers.Binary;
using Baseproto;
using Google.Protobuf;
using Pbmisc;
using Sv.Gateway.Protocol;
using Xunit;

namespace Sv.Tests;

public sealed class NetPacketTests
{
    private const int MaxFrameBytes = 65536;
    private static byte[] Frame()
    {
        NetPacket packet = new((ushort)PingReq.Types.CmdId.CmdId, new PingReq { Seq = 123 }, new PacketHead { PacketId = 5, RpcId = 9 });
        return packet.Pack(MaxFrameBytes);
    }
    [Fact]
    public void PackAndUnPackPreserveOnePacket()
    {
        byte[] frame = Frame(); NetPacket packet = new(); packet.UnPack(frame, MaxFrameBytes);
        Assert.Equal((ushort)PingReq.Types.CmdId.CmdId, packet.CmdId); Assert.Equal(9u, packet.Head.RpcId);
        Assert.Equal(123u, PingReq.Parser.ParseFrom(packet.Body).Seq); Assert.Equal(frame, packet.Pack(MaxFrameBytes));
        Assert.Equal(NetPacket.BeginMagic, BinaryPrimitives.ReadUInt16BigEndian(frame));
        Assert.Equal(NetPacket.EndMagic, BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(frame.Length - 2)));
    }
    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void UnPackRejectsInvalidMagic(int position)
    {
        byte[] frame = Frame(); frame[position < 0 ? frame.Length - 1 : position] ^= 1;
        Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(frame, MaxFrameBytes));
    }
    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(10)]
    [InlineData(11)]
    public void UnPackRejectsTruncation(int length) => Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(new byte[length], MaxFrameBytes));
    [Fact]
    public void UnPackRejectsInconsistentBodyLength()
    {
        byte[] frame = Frame(); BinaryPrimitives.WriteUInt32BigEndian(frame.AsSpan(6), uint.MaxValue);
        Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(frame, MaxFrameBytes));
    }
    [Fact]
    public void UnPackRejectsTrailingData()
    {
        byte[] frame = [.. Frame(), 0];
        Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(frame, MaxFrameBytes));
    }
    [Fact]
    public void UnPackRejectsCommandMismatch()
    {
        NetPacket packet = new(5, new PingReq(), new PacketHead { PacketId = 6 });
        Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(packet.Pack(MaxFrameBytes), MaxFrameBytes));
    }
    [Fact]
    public void PackAndUnPackEnforceLengthLimit()
    {
        byte[] frame = Frame();
        Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(frame, frame.Length - 1));
        Assert.Throws<InvalidDataException>(() => new NetPacket(5, new PingReq { Seq = 1 }, new PacketHead()).Pack(12));
    }
    [Fact]
    public void UnPackRejectsUnnegotiatedEncryption()
    {
        NetPacket packet = new(5, new PingReq(), new PacketHead { SessionValue1 = ByteString.CopyFromUtf8("test") });
        Assert.Throws<InvalidDataException>(() => new NetPacket().UnPack(packet.Pack(MaxFrameBytes), MaxFrameBytes));
    }
    [Fact]
    public void FailedUnPackDoesNotReplaceExistingPacket()
    {
        NetPacket packet = new(); packet.UnPack(Frame(), MaxFrameBytes);
        Assert.Throws<InvalidDataException>(() => packet.UnPack([], MaxFrameBytes));
        Assert.Equal(123u, PingReq.Parser.ParseFrom(packet.Body).Seq); Assert.Equal(9u, packet.Head.RpcId);
    }
}

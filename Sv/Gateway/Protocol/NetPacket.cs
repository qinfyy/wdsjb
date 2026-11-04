using System.Buffers.Binary;
using Google.Protobuf;
using Baseproto;

namespace Sv.Gateway.Protocol;

public sealed class NetPacket
{
    public const ushort BeginMagic = 0x4567;
    public const ushort EndMagic = 0x89AB;
    public const int FixedSize = 12;
    public const int PrefixSize = 10;
    public ushort CmdId { get; private set; }
    public PacketHead Head { get; private set; } = new();
    public byte[] Body { get; private set; } = [];

    public NetPacket() { }
    public NetPacket(ushort cmdId, IMessage message, PacketHead head)
    {
        CmdId = cmdId; Head = head; Body = message.ToByteArray();
    }

    public byte[] Pack(int maxFrameBytes)
    {
        byte[] headBytes = Head.ToByteArray();
        long size = (long)FixedSize + headBytes.Length + Body.Length;
        if (headBytes.Length > ushort.MaxValue || size > maxFrameBytes) throw new InvalidDataException("发送帧超过长度上限");
        byte[] frame = new byte[(int)size];
        BinaryPrimitives.WriteUInt16BigEndian(frame, BeginMagic);
        BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(2), CmdId);
        BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(4), (ushort)headBytes.Length);
        BinaryPrimitives.WriteUInt32BigEndian(frame.AsSpan(6), (uint)Body.Length);
        headBytes.CopyTo(frame, PrefixSize); Body.CopyTo(frame, PrefixSize + headBytes.Length);
        BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(frame.Length - 2), EndMagic);
        return frame;
    }
    public void UnPack(byte[] frame, int maxFrameBytes)
    {
        if (frame.Length < FixedSize) throw new InvalidDataException("接收帧被截断");
        if (BinaryPrimitives.ReadUInt16BigEndian(frame) != BeginMagic) throw new InvalidDataException("帧头标记无效");
        ushort command = BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(2));
        int headLength = BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(4));
        uint bodyLength = BinaryPrimitives.ReadUInt32BigEndian(frame.AsSpan(6));
        long length = (long)FixedSize + headLength + bodyLength;
        if (length > maxFrameBytes || length > int.MaxValue) throw new InvalidDataException("接收帧超过长度上限");
        if (length != frame.Length) throw new InvalidDataException("接收帧长度不一致");
        if (BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(frame.Length - 2)) != EndMagic) throw new InvalidDataException("帧尾标记无效");
        PacketHead head = PacketHead.Parser.ParseFrom(frame, PrefixSize, headLength);
        if (head.PacketId != 0 && head.PacketId != command) throw new InvalidDataException("帧命令与 protobuf 包头不一致");
        if (!head.SessionValue1.IsEmpty || !head.SessionValue2.IsEmpty || head.SessionValue3.Length != 0)
            throw new InvalidDataException("当前网关未协商加密会话");
        CmdId = command; Head = head; Body = frame.AsSpan(PrefixSize + headLength, (int)bodyLength).ToArray();
    }
}

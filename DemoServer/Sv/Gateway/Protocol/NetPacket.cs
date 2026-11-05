using System.Buffers.Binary;
using System.Security.Cryptography;
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

    public static bool IsPlaintext(ushort command) => command is >= 101 and <= 104;

    private static int GetFrameLength(ushort command, int headLength, uint bodyLength, int maxFrameBytes)
    {
        long payloadLength = (long)headLength + bodyLength;
        if (!IsPlaintext(command)) payloadLength = (payloadLength + 16) & ~15L;
        long length = FixedSize + payloadLength;
        if (length > maxFrameBytes || length > int.MaxValue) throw new InvalidDataException("帧超过长度上限");
        return (int)length;
    }

    public static int GetFrameLength(ReadOnlySpan<byte> prefix, int maxFrameBytes)
    {
        if (prefix.Length < PrefixSize) throw new InvalidDataException("接收帧头被截断");
        if (BinaryPrimitives.ReadUInt16BigEndian(prefix) != BeginMagic) throw new InvalidDataException("帧头标记无效");
        return GetFrameLength(BinaryPrimitives.ReadUInt16BigEndian(prefix[2..]), BinaryPrimitives.ReadUInt16BigEndian(prefix[4..]),
            BinaryPrimitives.ReadUInt32BigEndian(prefix[6..]), maxFrameBytes);
    }

    public byte[] Pack(int maxFrameBytes, ReadOnlySpan<byte> sessionKey = default)
    {
        byte[] headBytes = Head.ToByteArray();
        if (headBytes.Length > ushort.MaxValue) throw new InvalidDataException("发送包头超过长度上限");
        int size = GetFrameLength(CmdId, headBytes.Length, (uint)Body.Length, maxFrameBytes);
        byte[] payload = new byte[headBytes.Length + Body.Length];
        headBytes.CopyTo(payload, 0); Body.CopyTo(payload, headBytes.Length);
        if (!IsPlaintext(CmdId))
        {
            if (sessionKey.IsEmpty) throw new InvalidDataException("发送命令需要加密会话");
            using Aes aes = Aes.Create();
            aes.Key = sessionKey.ToArray();
            payload = aes.EncryptCbc(payload, SessionCryptography.Iv, PaddingMode.PKCS7);
        }
        byte[] frame = new byte[size];
        BinaryPrimitives.WriteUInt16BigEndian(frame, BeginMagic);
        BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(2), CmdId);
        BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(4), (ushort)headBytes.Length);
        BinaryPrimitives.WriteUInt32BigEndian(frame.AsSpan(6), (uint)Body.Length);
        payload.CopyTo(frame, PrefixSize);
        BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(frame.Length - 2), EndMagic);
        return frame;
    }
    public void UnPack(byte[] frame, int maxFrameBytes, ReadOnlySpan<byte> sessionKey = default)
    {
        if (frame.Length < FixedSize) throw new InvalidDataException("接收帧被截断");
        int length = GetFrameLength(frame, maxFrameBytes);
        ushort command = BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(2));
        int headLength = BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(4));
        uint bodyLength = BinaryPrimitives.ReadUInt32BigEndian(frame.AsSpan(6));
        if (length != frame.Length) throw new InvalidDataException("接收帧长度不一致");
        if (BinaryPrimitives.ReadUInt16BigEndian(frame.AsSpan(frame.Length - 2)) != EndMagic) throw new InvalidDataException("帧尾标记无效");
        byte[] payload = frame.AsSpan(PrefixSize, frame.Length - FixedSize).ToArray();
        if (!IsPlaintext(command))
        {
            if (sessionKey.IsEmpty) throw new InvalidDataException("接收命令需要加密会话");
            try
            {
                using Aes aes = Aes.Create();
                aes.Key = sessionKey.ToArray();
                payload = aes.DecryptCbc(payload, SessionCryptography.Iv, PaddingMode.PKCS7);
            }
            catch (CryptographicException exception)
            {
                throw new InvalidDataException($"帧解密失败: cmd={command}, head={headLength}, body={bodyLength}, cipher={payload.Length}", exception);
            }
        }
        if (payload.Length != (long)headLength + bodyLength) throw new InvalidDataException("解密后帧长度不一致");
        CmdId = command; Head = PacketHead.Parser.ParseFrom(payload, 0, headLength); Body = payload.AsSpan(headLength, (int)bodyLength).ToArray();
    }
}

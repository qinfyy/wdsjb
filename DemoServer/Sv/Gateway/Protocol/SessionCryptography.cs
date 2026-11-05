using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Baseproto;
using Google.Protobuf;

namespace Sv.Gateway.Protocol;

internal sealed class SessionCryptography : IDisposable
{
    // StepUtils.PD uses the client RSA key; only its public part is needed to send fresh session keys.
    private const string ClientModulus = "v76U5Cr1tTDoTNtiA+USEpac31neG4DA0nHNzvJ3ygTr0oTZhAyRRa6GaJpv++9DPWSCNu/RWfnn4HUM0PbjlZvldue4RQFF6BcYPVd6rnWn3qJolC9JdjklqxwveOVdE+kKoMGVBtS/Vjt4xuwuDZMv3v2/B8UTqsz/d6sC9SU=";
    private readonly byte[] _sendKey = RandomNumberGenerator.GetBytes(32);
    private readonly byte[] _receiveKey = RandomNumberGenerator.GetBytes(32);
    private readonly string _challenge = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
    private readonly long _proof;
    public ReadOnlySpan<byte> SendKey => _sendKey;
    public ReadOnlySpan<byte> ReceiveKey => _receiveKey;
    // NetworkManager's constructor calls AESUtils.InitIfNeeded, replacing the cctor's initial IV.
    public static ReadOnlySpan<byte> Iv => [67, 56, 40, 23, 105, 57, 19, 112, 67, 56, 40, 23, 105, 57, 19, 113];

    public SessionCryptography()
    {
        // Step(org, 1) searches for SHA256(UTF8(org + decimal nonce))[0] == 0x23.
        for (long nonce = 0; ; nonce++)
        {
            if (SHA256.HashData(Encoding.UTF8.GetBytes(_challenge + nonce.ToString(CultureInfo.InvariantCulture)))[0] != 0x23) continue;
            _proof = nonce;
            break;
        }
    }

    public void WriteHandshake(PacketHead head)
    {
        using RSA rsa = RSA.Create();
        rsa.ImportParameters(new RSAParameters { Modulus = Convert.FromBase64String(ClientModulus), Exponent = [1, 0, 1] });
        head.SessionValue1 = ByteString.CopyFrom(rsa.Encrypt(_sendKey, RSAEncryptionPadding.OaepSHA1));
        head.SessionValue2 = ByteString.CopyFrom(rsa.Encrypt(_receiveKey, RSAEncryptionPadding.OaepSHA1));
        head.SessionValue3 = _challenge;
        head.SessionValue4 = 1;
    }

    public bool ValidateLogin(PacketHead head, uint uid)
    {
        // PE echoes use the original server RSA public key. They are not an identity credential;
        // identity comes from the SDK combo token validated on this TCP connection before issuing the challenge.
        return head.UserId == uid && head.SessionValue1.Length == 128 && head.SessionValue2.Length == 128 && head.SessionValue4 == _proof;
    }

    public void Dispose()
    {
        CryptographicOperations.ZeroMemory(_sendKey);
        CryptographicOperations.ZeroMemory(_receiveKey);
    }
}

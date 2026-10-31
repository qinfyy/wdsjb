"""复刻 RSASignedLoader 的 RSA-SHA1 文件验签。"""

from __future__ import annotations

import base64
import hashlib
import struct
from typing import Final

from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15


# CN 6.1.0 libil2cpp.so 0x0A726CC8
PUBLIC_KEY_BLOB: Final[str] = (
    "BgIAAACkAABSU0ExAAQAAAEAAQAlfR2VsQSd7EiVNxm5Sbs00mAp7AV0awkwsOar8YN9DcMXhqO6MsurE8xeLBWkayAW"
    "6jjQRTEdpTGJ2SUz0npuHD1g8KuIBILrYypks4OLIwqCGYTPiCKuoLo++KvvhlNPQd5YhDR4YnXWes/0ElPfRrpDkeFagCrUQgHYud6Qvg=="
)
SIGNATURE_SIZE: Final[int] = 128
SHA1_DIGEST_INFO: Final[bytes] = bytes.fromhex("3021300906052b0e03021a05000414")


def read_public_key(blob: str = PUBLIC_KEY_BLOB) -> RSA.RsaKey:
    """ImportCspBlob 的 PUBLICKEYBLOB 使用小端 RSA 模数。"""
    raw = base64.b64decode(blob, validate=True)
    kind, version, reserved, algorithm, magic, bits, exponent = struct.unpack_from("<BBHIIII", raw)
    if (kind, version, reserved, magic) != (6, 2, 0, 0x31415352) or bits != 1024:
        raise ValueError("不支持的 RSA PUBLICKEYBLOB")
    if len(raw) != 20 + bits // 8:
        raise ValueError("RSA PUBLICKEYBLOB 长度错误")
    return RSA.construct((int.from_bytes(raw[20:], "little"), exponent))


PUBLIC_KEY: Final[RSA.RsaKey] = read_public_key()


def signature_digest(signature: bytes) -> bytes:
    """恢复签名中的 SHA1，供无索引块的边界验证使用，不代表已经验签。"""
    if len(signature) != SIGNATURE_SIZE:
        raise ValueError("RSA 签名长度错误")
    value = int.from_bytes(signature, "big")
    if value >= PUBLIC_KEY.n:
        raise ValueError("RSA 签名超出模数")
    encoded = pow(value, PUBLIC_KEY.e, PUBLIC_KEY.n).to_bytes(SIGNATURE_SIZE, "big")
    prefix = b"\x00\x01" + b"\xff" * (SIGNATURE_SIZE - 3 - len(SHA1_DIGEST_INFO) - 20)
    prefix += b"\x00" + SHA1_DIGEST_INFO
    if encoded[:len(prefix)] != prefix:
        raise ValueError("不是客户端的 RSA-SHA1 PKCS#1 v1.5 签名")
    return encoded[-20:]


def verify_signed_file(data: bytes) -> bytes:
    """RSASignedLoader.RSACheckContent：验签成功后移除前 128 字节。"""
    if len(data) < SIGNATURE_SIZE:
        raise ValueError("签名文件长度不足")
    payload = data[SIGNATURE_SIZE:]
    try:
        pkcs1_15.new(PUBLIC_KEY).verify(SHA1.new(payload), data[:SIGNATURE_SIZE])
    except (ValueError, TypeError) as error:
        raise ValueError("RSA-SHA1 验签失败，文件可能缺失、边界错误或使用了其他公钥") from error
    return payload


def payload_digest(data: bytes) -> str:
    """原始表内容的摘要，不包含签名。"""
    return hashlib.sha1(data).hexdigest()

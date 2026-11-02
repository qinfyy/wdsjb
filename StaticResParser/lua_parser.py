from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile


UNLUAC_DIR = Path(__file__).resolve().parent / "unluac"
XOR_KEY = bytes.fromhex("2f4f659d")
WD_HEADER = bytes.fromhex("1b4c7561530119930d0a1a0a0404080878560000000000000000000000287740")
LUA53_HEADER = WD_HEADER[:5] + b"\x00" + WD_HEADER[6:13] + b"\x04" + WD_HEADER[13:]


def decoded_header(data: bytes) -> bytes:
    if data.startswith(b"\x1bLua"):
        return data
    return bytes(value ^ XOR_KEY[index % 4] for index, value in enumerate(data))


def is_lua_file(path: Path, signed: bool = False) -> bool:
    """只读内容头识别格式；文件名不参与判断，签名在实际处理时验证。"""
    with path.open("rb") as stream:
        if signed:
            from UnPacker.crypto import SIGNATURE_SIZE
            stream.seek(SIGNATURE_SIZE)
        header = decoded_header(stream.read(len(LUA53_HEADER)))
    return header.startswith((WD_HEADER, LUA53_HEADER))


def convert_lua(data: bytes) -> tuple[bytes, bool]:
    """CN 6.1.0 libxlua.so 0x2EFD0/0x2F988：format 1 不含 size_t 长度字节。"""
    encrypted = not data.startswith(b"\x1bLua")
    decoded = decoded_header(data)
    if decoded.startswith(WD_HEADER):
        if len(decoded) <= len(WD_HEADER):
            raise ValueError("WD Lua 头部截断")
        return LUA53_HEADER + decoded[len(WD_HEADER):], encrypted
    if decoded.startswith(LUA53_HEADER):
        if len(decoded) <= len(LUA53_HEADER):
            raise ValueError("Lua 头部截断")
        return decoded, encrypted
    raise ValueError("内容不是支持的 WD Lua 5.3 字节码")


def unluac_command(directory: Path | None = None) -> tuple[str, ...]:
    directories = (directory,) if directory is not None else (UNLUAC_DIR, UNLUAC_DIR.parent.parent / "unluac")
    for root in directories:
        executable = root / "unluac.exe"
        if executable.is_file():
            return (str(executable),)
    for root in directories:
        jar = root / "unluac.jar"
        if not jar.is_file():
            continue
        java = shutil.which("java")
        if java is None:
            raise ValueError("unluac.jar 需要 Java；请安装 JDK 或提供 unluac.exe")
        return (java, "-jar", str(jar))
    raise ValueError("未找到 unluac 或 ../unluac 中的 unluac.exe/unluac.jar")


@dataclass(frozen=True)
class LuaTask:
    path: Path
    relative: Path
    command: tuple[str, ...]
    signed: bool = False


def restore_lua(task: LuaTask) -> tuple[dict[str, object], bytes | None]:
    """独立进程处理单个 Lua；只返回结果，输出保护由 main.py 统一执行。"""
    result: dict[str, object] = {"file": task.relative.as_posix(), "format": "lua", "signed": task.signed}
    try:
        raw = task.path.read_bytes()
        result.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        payload = raw
        if task.signed:
            from UnPacker.crypto import verify_signed_file
            payload = verify_signed_file(raw)
        bytecode, encrypted = convert_lua(payload)
        result.update(payloadSize=len(payload), xor=encrypted)
        with tempfile.TemporaryDirectory(prefix="wd-lua-") as temporary:
            root = Path(temporary)
            chunk, source = root / "chunk.luac", root / "source.lua"
            chunk.write_bytes(bytecode)
            completed = subprocess.run(
                [*task.command, "-o", str(source), str(chunk)], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip().replace(str(root), "<temp>")
                raise ValueError(f"unluac 反编译失败 ({completed.returncode})：{detail}")
            if not source.is_file():
                raise ValueError("unluac 未生成 Lua 源码")
            restored = source.read_bytes()
        result.update(status="lua", output=Path(task.relative.name).with_suffix(".lua").as_posix())
        return result, restored
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(status="failed", reason=str(error))
        return result, None

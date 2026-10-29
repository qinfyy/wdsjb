"""通过 Frida spawn 启动 BH2，并注入流量重定向脚本。"""

from __future__ import annotations

import configparser
import json
import signal
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import frida


PACKAGE_NAME = "com.miHoYo.HSoDv2Original"
PROJECT_DIRECTORY = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIRECTORY / "Config.ini"
SCRIPT_PATH = PROJECT_DIRECTORY / "dist" / "FridaScript.js"
EMULATED_REALM_ATTACH_DELAY_SECONDS = 8.0
NATIVE_BRIDGE_SETUP_WAIT_SECONDS = 5.0
EMULATED_AGENT_PATH = "/data/local/tmp/re.frida.server/frida-agent-arm64.so"

FRIDA_ERRORS = (
    frida.AddressInUseError,
    frida.ExecutableNotFoundError,
    frida.ExecutableNotSupportedError,
    frida.InvalidArgumentError,
    frida.InvalidOperationError,
    frida.NotSupportedError,
    frida.OperationCancelledError,
    frida.PermissionDeniedError,
    frida.ProcessNotFoundError,
    frida.ProcessNotRespondingError,
    frida.ProtocolError,
    frida.ServerNotRunningError,
    frida.TimedOutError,
    frida.TransportError,
)


def load_config() -> dict[str, object]:
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(CONFIG_PATH, encoding="utf-8-sig"):
        raise FileNotFoundError(f"找不到配置文件：{CONFIG_PATH}")
    if "Settings" not in parser:
        raise ValueError("Config.ini 缺少 [Settings] 节")

    settings = parser["Settings"]
    values: dict[str, str] = {}
    for name in ("HTTP_URL_BASE", "GATEWAY_HOST", "GATEWAY_IPV6"):
        value = settings.get(name, "").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        values[name] = value

    parsed_url = urlsplit(values["HTTP_URL_BASE"])
    if (
        parsed_url.scheme != "http"
        or not parsed_url.netloc
        or parsed_url.path not in ("", "/")
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError("HTTP_URL_BASE 必须是 HTTP 根地址，例如 http://192.168.0.108:21000")

    gateway_host = values["GATEWAY_HOST"]
    if (
        not gateway_host
        or any(character.isspace() for character in gateway_host)
        or any(character in gateway_host for character in ":/@?#")
    ):
        raise ValueError("GATEWAY_HOST 必须是不带协议和端口的 IPv4 地址或主机名")

    try:
        gateway_port = settings.getint("GATEWAY_PORT")
    except (TypeError, ValueError) as error:
        raise ValueError("GATEWAY_PORT 必须是整数") from error
    if gateway_port is None or not 1 <= gateway_port <= 65535:
        raise ValueError("GATEWAY_PORT 必须在 1 到 65535 之间")

    try:
        use_zlib_hook = settings.getboolean("UES_ZLIB_HOOK", fallback=True)
        use_java_url_modify = settings.getboolean(
            "USE_JAVA_URL_MODIFY", fallback=True
        )
        use_java_bypass_rsa = settings.getboolean(
            "USE_JAVA_BYPASS_RSA", fallback=True
        )
        emulator = settings.getboolean("EMULATOR", fallback=False)
    except ValueError as error:
        raise ValueError(
            "EMULATOR、UES_ZLIB_HOOK、USE_JAVA_URL_MODIFY 和 "
            "USE_JAVA_BYPASS_RSA 必须是布尔值"
        ) from error

    client_arch = settings.get("CLIENT_ARCH", "x86").strip().lower()
    if (
        len(client_arch) >= 2
        and client_arch[0] == client_arch[-1]
        and client_arch[0] in "\"'"
    ):
        client_arch = client_arch[1:-1].strip()
    if client_arch not in ("x86", "arm64-v8a"):
        raise ValueError("CLIENT_ARCH 只支持 x86 或 arm64-v8a")
    if client_arch == "x86" and emulator:
        raise ValueError("x86 客户端不使用 Emulated Realm，请设置 EMULATOR=false")

    return {
        "httpUrlBase": f"http://{parsed_url.netloc}",
        "gatewayHost": gateway_host,
        "gatewayPort": gateway_port,
        "gatewayIpv6": values["GATEWAY_IPV6"],
        "useZlibHook": use_zlib_hook,
        "useJavaUrlModify": use_java_url_modify,
        "useJavaBypassRsa": use_java_bypass_rsa,
        "clientArch": client_arch,
        "emulator": emulator,
    }


def main() -> int:
    config = load_config()
    if not SCRIPT_PATH.is_file():
        raise RuntimeError("缺少 Frida 编译产物，请先在 BH2Redirector 执行 npm run check")
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    stopped = threading.Event()
    native_bridge_ready = threading.Event()
    script_configured = threading.Event()
    device = frida.get_usb_device(timeout=10)
    pid: int | None = None
    sessions: list[frida.Session] = []
    scripts: list[frida.core.Script] = []
    attached_realms: list[str] = []
    resumed = False

    def on_message(
        message: dict[str, object],
        _data: bytes | None,
        realm_label: str,
    ) -> None:
        prefix = f"[{realm_label}] " if len(realm_specs) > 1 else ""
        if message.get("type") == "send":
            payload = message.get("payload")
            if isinstance(payload, dict):
                if payload.get("event") in (
                    "native-bridge-ready",
                    "native-bridge-failed",
                ):
                    native_bridge_ready.set()
                if payload.get("event") == "script-configured":
                    script_configured.set()
                detail = payload.get("message", json.dumps(payload, ensure_ascii=False))
                print(f"{prefix}{detail}", flush=True)
            else:
                print(f"{prefix}{payload}", flush=True)
            return

        description = message.get("description", "未知 Frida 错误")
        print(f"{prefix}[Frida 错误] {description}", file=sys.stderr, flush=True)
        if stack := message.get("stack"):
            print(stack, file=sys.stderr, flush=True)

    def on_detached(reason: str, crash: object | None, realm_label: str) -> None:
        if crash is None:
            print(f"[{realm_label}] 游戏进程连接已断开：{reason}", flush=True)
        else:
            print(
                f"[{realm_label}] 游戏进程异常退出：{reason}，{crash}",
                file=sys.stderr,
                flush=True,
            )
        stopped.set()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    if config["clientArch"] == "arm64-v8a" and config["emulator"]:
        realm_specs = (
            ("Native Realm", "native", "platform"),
            ("Emulated Realm", "emulated", "il2cpp"),
        )
    else:
        realm_specs = (("Native Realm", "native", "all"),)

    def attach_realm(realm_label: str, realm: str, runtime_role: str) -> None:
        if pid is None:
            raise RuntimeError("游戏进程尚未启动")

        if realm == "emulated":
            session = device.attach(
                pid,
                realm=realm,
                emulated_agent_path=EMULATED_AGENT_PATH,
            )
        else:
            session = device.attach(pid, realm=realm)

        def handle_detached(reason: str, crash: object | None) -> None:
            on_detached(reason, crash, realm_label)

        session.on("detached", handle_detached)
        sessions.append(session)

        script = session.create_script(source)
        script.on(
            "message",
            lambda message, data: on_message(message, data, realm_label),
        )
        script.load()
        script.post(
            {
                "type": "config",
                "payload": config
                | {
                    "runtimeRole": runtime_role,
                    "emulatedAgentPath": EMULATED_AGENT_PATH,
                },
            }
        )
        scripts.append(script)
        attached_realms.append(realm_label)

    try:
        print(f"正在通过 spawn 启动 {PACKAGE_NAME}...", flush=True)
        pid = device.spawn([PACKAGE_NAME])
        if len(realm_specs) > 1:
            device.resume(pid)
            resumed = True
            # MuMu 在 Houdini 装载 ARM 库前探测 Emulated Realm 会触发 linker 崩溃。
            if stopped.wait(EMULATED_REALM_ATTACH_DELAY_SECONDS):
                raise RuntimeError("等待 Native Bridge 初始化时游戏进程已退出")
            attach_realm(*realm_specs[0])
            if not native_bridge_ready.wait(NATIVE_BRIDGE_SETUP_WAIT_SECONDS):
                raise RuntimeError("等待 Native Bridge 兼容层初始化超时")
            try:
                attach_realm(*realm_specs[1])
            except FRIDA_ERRORS as error:
                if "process is not using emulation" not in str(error):
                    raise
                print(
                    "[Emulated Realm] [警告] 当前 Native Bridge 不受 Frida "
                    "Emulated Realm 支持，跳过 IL2CPP Hook",
                    flush=True,
                )
        else:
            attach_realm(*realm_specs[0])
            if not script_configured.wait(5.0):
                print(
                    "[警告] Frida 脚本配置握手超时，继续恢复游戏；Java RSA Hook 将在类加载后补装",
                    file=sys.stderr,
                    flush=True,
                )
            device.resume(pid)
            resumed = True

        realm_description = " + ".join(attached_realms)
        print(
            f"游戏已启动，PID={pid}，架构={config['clientArch']}，"
            f"Realm={realm_description}，HTTP={config['httpUrlBase']}，"
            f"Gateway={config['gatewayHost']}:{config['gatewayPort']}",
            flush=True,
        )
        while not stopped.wait(0.25):
            pass
    finally:
        if pid is not None and not resumed:
            try:
                device.resume(pid)
            except frida.InvalidOperationError:
                pass
        for script in reversed(scripts):
            try:
                script.unload()
            except frida.InvalidOperationError:
                pass
        for session in reversed(sessions):
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (configparser.Error, OSError, ValueError, RuntimeError) as error:
        print(f"启动失败：{error}", file=sys.stderr)
        sys.exit(1)
    except FRIDA_ERRORS as error:
        print(f"启动失败：{error}", file=sys.stderr)
        sys.exit(1)

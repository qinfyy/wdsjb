"""启动 WD，注入 SDK RSA Bypass 和 UnityWebRequest HTTP 重定向。"""

from __future__ import annotations

import argparse
import base64
import configparser
import json
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import frida


PACKAGE_NAME = "com.miHoYo.wd"
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "Config.ini"
SCRIPT_PATH = ROOT / "dist" / "FridaScript.js"
REPLACED_SCRIPT_PATH = ROOT / "dist" / "FridaScript_Replacemented.js"
DEFAULT_AGENT = ROOT / "frida-agent-arm64.so"
REMOTE_AGENT = "/data/local/tmp/re.frida.server/frida-agent-arm64.so"
CONFIG_MARKER = "__CONFIG_REPLACEMENT__"
BUNDLE_MAGIC = "\U0001f4e6\n"
BUNDLE_SEPARATOR = "\n\u2704\n"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--realm", choices=("auto", "native", "emulated"), default="auto", help="自动识别 ARM64 真机或模拟器，默认 auto。")
    parser.add_argument("--device", help="Frida 设备 ID，默认 USB/模拟器设备。")
    parser.add_argument("--adb", type=Path, default=Path("adb.exe"), help="ADB 路径，默认从 PATH 查找。")
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT, help="与 Frida server 同版本的 ARM64 agent，emulated 时自动上传。")
    return parser.parse_args()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8-sig") as config_file:
            parser.read_file(config_file)
    except configparser.Error as error:
        raise ValueError("Config.ini 格式错误：" + str(error)) from error
    if parser.sections() != ["Settings"] or parser.defaults():
        raise ValueError("Config.ini 必须且只能包含 [Settings] 配置节")
    config = parser["Settings"]
    unknown = config.keys() - {"http_url_base", "use_java_bypass_rsa"}
    if unknown:
        raise ValueError("不支持的配置项：" + ", ".join(sorted(unknown)))
    value = config.get("HTTP_URL_BASE")
    if not isinstance(value, str):
        raise ValueError("HTTP_URL_BASE 必须是 HTTP/HTTPS 根地址")
    url = urlsplit(value.strip())
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
            or url.password is not None or url.path not in {"", "/"} or url.query or url.fragment
            or any(character.isspace() for character in value) or "\\" in value):
        raise ValueError("HTTP_URL_BASE 必须是根地址，例如 http://192.168.0.108:21000")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("HTTP_URL_BASE 端口必须在 1 到 65535 之间")
    try:
        bypass = config.getboolean("USE_JAVA_BYPASS_RSA", fallback=True)
    except ValueError as error:
        raise ValueError("USE_JAVA_BYPASS_RSA 必须是有效的 INI 布尔值，例如 true/false") from error
    return {"httpUrlBase": f"{url.scheme}://{url.netloc}", "useJavaBypassRsa": bypass}


def configure_script(source: str, config: dict[str, Any]) -> str:
    if source.count(CONFIG_MARKER) != 1:
        raise ValueError("脚本必须且只能包含一个配置占位符，请重新执行 npm run build")
    encoded = base64.b64encode(json.dumps(config, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
    replacement = json.dumps(encoded)
    if not source.startswith(BUNDLE_MAGIC):
        return source.replace(CONFIG_MARKER, replacement)

    # frida-compile 使用 UTF-8 字节长度分隔模块；替换内容时必须同步修改清单。
    header, separator, body = source.partition(BUNDLE_SEPARATOR)
    if not separator:
        raise ValueError("Frida bundle 缺少模块分隔符")
    lines = header.split("\n")
    modules = body.encode("utf-8")
    delimiter = BUNDLE_SEPARATOR.encode("utf-8")
    offset = 0
    for index, line in enumerate(lines[1:], 1):
        if line.startswith("\u21bb "):
            continue
        size_text, space, name = line.partition(" ")
        if not space or not size_text.isdecimal() or not name:
            raise ValueError("无效的 Frida bundle 模块清单")
        size = int(size_text)
        end = offset + size
        chunk = modules[offset:end]
        if len(chunk) != size:
            raise ValueError("Frida bundle 模块长度不匹配")
        if CONFIG_MARKER.encode("ascii") in chunk:
            updated = chunk.replace(CONFIG_MARKER.encode("ascii"), replacement.encode("ascii"))
            lines[index] = f"{len(updated)} {name}"
            modules = modules[:offset] + updated + modules[end:]
            end = offset + len(updated)
        if end == len(modules):
            offset = end
        elif modules[end:end + len(delimiter)] == delimiter:
            offset = end + len(delimiter)
        else:
            raise ValueError("Frida bundle 模块边界不匹配")
    if offset != len(modules) or CONFIG_MARKER.encode("ascii") in modules:
        raise ValueError("Frida bundle 配置替换失败")
    return "\n".join(lines) + separator + modules.decode("utf-8")


def main() -> int:
    args = parse_args()
    config = load_config()
    if not SCRIPT_PATH.is_file():
        raise FileNotFoundError("缺少 dist/FridaScript.js，请先在 WDRedirector 执行 npm run build")
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    configure_script(source, config)
    device = frida.get_device(args.device, timeout=15) if args.device else frida.get_usb_device(timeout=15)
    realm = args.realm
    if realm == "auto":
        realm = "emulated" if device.query_system_parameters().get("arch") in {"x64", "x86_64", "ia32"} else "native"
    runtime_config = config | {"emulator": realm == "emulated", "emulatedAgentPath": REMOTE_AGENT}
    prepared_source = configure_script(source, runtime_config)
    REPLACED_SCRIPT_PATH.write_text(prepared_source, encoding="utf-8", newline="\n")
    print(f"[脚本] 已保存替换后的注入脚本：{REPLACED_SCRIPT_PATH}", flush=True)

    adb: list[str] = []
    if realm == "emulated":
        executable = shutil.which(str(args.adb))
        if not executable or not args.agent.is_file():
            raise FileNotFoundError(f"需要 ADB 和 ARM64 agent：{args.adb}，{args.agent}")
        adb = [executable, "-s", device.id]
        for command in (["shell", "mkdir", "-p", REMOTE_AGENT.rsplit("/", 1)[0]],
                        ["push", str(args.agent.resolve()), REMOTE_AGENT],
                        ["shell", "chmod", "0644", REMOTE_AGENT]):
            subprocess.run(adb + command, check=True, timeout=60)

    stopped = threading.Event()
    bridge_ready = threading.Event()
    script_ready = threading.Event()
    errors: list[str] = []
    sessions: list[Any] = []
    scripts: list[Any] = []
    pid: int | None = None
    resumed = False

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    def on_message(message: dict[str, Any], _data: bytes | None, label: str) -> None:
        payload = message.get("payload")
        if message.get("type") == "send" and isinstance(payload, dict):
            event = payload.get("event")
            if event == "bridge-ready":
                bridge_ready.set()
            elif event == "script-ready":
                script_ready.set()
            print(f"[{label}] {payload.get('message', payload)}", flush=True)
            if event != "error":
                return
            detail = str(payload.get("message", payload))
        else:
            detail = str(message.get("stack") or message.get("description") or message)
            print(f"[{label}] [Frida 错误] {detail}", file=sys.stderr, flush=True)
        errors.append(detail)
        stopped.set()
        bridge_ready.set()
        script_ready.set()

    def on_detached(reason: str, crash: Any) -> None:
        print(f"[断开] {reason}" + (f"，{crash}" if crash is not None else ""), flush=True)
        if not stopped.is_set():
            errors.append(f"游戏连接断开：{reason}")
            stopped.set()
            bridge_ready.set()
            script_ready.set()

    def attach(target_realm: str) -> None:
        options = {"emulated_agent_path": REMOTE_AGENT} if target_realm == "emulated" else {}
        session = device.attach(pid, realm=target_realm, **options)
        sessions.append(session)
        session.on("detached", on_detached)
        script = session.create_script(prepared_source)
        scripts.append(script)
        script.on("message", lambda message, data: on_message(message, data, target_realm))
        script.load()

    def check_startup() -> None:
        if errors:
            raise RuntimeError(" | ".join(errors))
        if stopped.is_set():
            raise InterruptedError("启动已取消")

    previous_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        if realm == "emulated":
            # 与 WDProtoDumper 一致，ADB 启动避开 MuMu 的早期 Frida spawn/linker 问题。
            resolved = subprocess.run(adb + ["shell", "cmd", "package", "resolve-activity", "--brief",
                                            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", PACKAGE_NAME],
                                      check=True, capture_output=True, text=True, timeout=15)
            components = [line.strip() for line in resolved.stdout.splitlines() if line.strip().startswith(PACKAGE_NAME + "/")]
            if not components:
                raise RuntimeError(f"找不到启动 Activity：{PACKAGE_NAME}")
            subprocess.run(adb + ["shell", "am", "force-stop", PACKAGE_NAME], check=True, timeout=15)
            subprocess.run(adb + ["shell", "am", "start", "-W", "-n", components[-1]],
                           check=True, capture_output=True, text=True, timeout=60)
            result = subprocess.run(adb + ["shell", "pidof", PACKAGE_NAME], capture_output=True, text=True, check=True, timeout=15)
            pids = result.stdout.split()
            if len(pids) != 1 or not pids[0].isdecimal():
                raise RuntimeError(f"无法确定 WD 主进程 PID：{result.stdout.strip()}")
            pid = int(pids[0])
            attach("native")
            if not bridge_ready.wait(15):
                raise RuntimeError("Native Bridge 初始化超时")
            check_startup()
            script_ready.clear()
            attach("emulated")
        else:
            pid = device.spawn([PACKAGE_NAME])
            attach("native")

        if not script_ready.wait(5):
            raise RuntimeError("WDRedirector 脚本启动超时")
        check_startup()
        if realm == "native":
            device.resume(pid)
            resumed = True
        print(f"WD 已启动，PID={pid}，Realm={realm}，HTTP={config['httpUrlBase']}，按 Ctrl+C 退出。", flush=True)
        while not stopped.wait(0.25):
            pass
        if errors:
            raise RuntimeError(" | ".join(errors))
    finally:
        if pid is not None and realm == "native" and not resumed:
            try:
                device.resume(pid)
            except FRIDA_ERRORS:
                pass
        stopped.set()
        for script in reversed(scripts):
            try:
                script.unload()
            except FRIDA_ERRORS:
                pass
        for session in reversed(sessions):
            try:
                session.detach()
            except FRIDA_ERRORS:
                pass
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, InterruptedError):
        sys.exit(0)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) + FRIDA_ERRORS as error:
        print(f"启动失败：{error}", file=sys.stderr)
        sys.exit(1)

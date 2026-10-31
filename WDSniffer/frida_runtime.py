"""ARM64 注入及 x86_64 模拟器 Native Bridge 支持。"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import frida


ROOT = Path(__file__).resolve().parent
DEFAULT_ADB = Path("adb.exe")
DEFAULT_AGENT = ROOT.parent / "WDRedirector" / "frida-agent-arm64.so"
REMOTE_AGENT = "/data/local/tmp/re.frida.server/frida-agent-arm64.so"
BRIDGE_SCRIPT = r"""
'use strict';
let sequence = 0;
function emit(payload) { send(Object.assign({ seq: ++sequence }, payload)); }
const bridge = Process.getModuleByName('libnativebridge.so');
// NativeBridge, native_bridge_namespace_t* NativeBridgeCreateNamespace(const char* name, const char* ld_library_path, const char* default_library_path, uint64_t type, const char* permitted_when_isolated_path, native_bridge_namespace_t* parent_ns);
const create = new NativeFunction(bridge.getExportByName('NativeBridgeCreateNamespace'), 'pointer',
    ['pointer', 'pointer', 'pointer', 'uint64', 'pointer', 'pointer']);
const address = bridge.getExportByName('NativeBridgeLoadLibrary');
// NativeBridge, void* NativeBridgeLoadLibrary(const char* libpath, int flag);
const original = new NativeFunction(address, 'pointer', ['pointer', 'int']);
// NativeBridge, void* NativeBridgeLoadLibraryExt(const char* libpath, int flag, native_bridge_namespace_t* ns);
const loadExt = new NativeFunction(bridge.getExportByName('NativeBridgeLoadLibraryExt'), 'pointer',
    ['pointer', 'int', 'pointer']);
const directory = '/data/local/tmp/re.frida.server';
const ns = create(Memory.allocUtf8String('wd-sniffer-emulated'), Memory.allocUtf8String(directory),
    Memory.allocUtf8String(directory + ':/system/lib64/arm64:/system_ext/lib64/arm64'),
    0, Memory.allocUtf8String(directory + ':/system'), ptr(0));
if (ns.isNull()) throw new Error('NativeBridgeCreateNamespace 返回空指针');
const replacement = new NativeCallback(function (path, flags) {
    if (path.readCString() === directory + '/frida-agent-arm64.so') return loadExt(path, flags, ns);
    return original(path, flags);
}, 'pointer', ['pointer', 'int']);
Interceptor.replace(address, replacement);
emit({event: 'bridge-ready'});
"""


def running_pid(device: Any, package: str, adb_path: Path) -> int | None:
    executable = shutil.which(str(adb_path))
    if executable:
        result = subprocess.run(
            [executable, "-s", device.id, "shell", "pidof", package],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            pids = result.stdout.split()
            return int(pids[0]) if pids and pids[0].isdecimal() else None
        if result.returncode == 1 and not result.stderr.strip():
            return None
    # 不用应用列表的 PID，避免误附加到 :PushService。
    for process in device.enumerate_processes():
        if process.name == package and process.pid > 0:
            return int(process.pid)
    return None


class FridaRuntime:
    def __init__(self, package: str, adb: Path = DEFAULT_ADB, realm: str = "auto",
                 device_id: str | None = None) -> None:
        if realm not in {"auto", "native", "emulated"}:
            raise ValueError(f"无效 realm: {realm}")
        self.package = package
        self.adb_path = adb
        self.realm = realm
        self.device_id = device_id
        self.pid: int | None = None
        self.device: Any = None
        self.sessions: list[Any] = []
        self.scripts: list[Any] = []
        self._suspended_pid: int | None = None

    def _adb(self, *args: str) -> subprocess.CompletedProcess[str]:
        executable = shutil.which(str(self.adb_path))
        if executable is None:
            raise FileNotFoundError(f"ADB 未找到: {self.adb_path}，请加入 PATH 或指定 --adb")
        return subprocess.run(
            [executable, "-s", self.device.id, *args],
            check=True, capture_output=True, text=True, timeout=60,
        )

    def _prepare_agent(self) -> None:
        if not DEFAULT_AGENT.is_file():
            raise FileNotFoundError(f"ARM64 agent 未找到: {DEFAULT_AGENT}")
        self._adb("shell", "mkdir", "-p", "/data/local/tmp/re.frida.server")
        self._adb("push", str(DEFAULT_AGENT), REMOTE_AGENT)
        self._adb("shell", "chmod", "0644", REMOTE_AGENT)

    def _launch_emulated(self) -> int:
        # Native Bridge 应用通过 Activity 启动，避免 MuMu 的挂起式 spawn 超时。
        result = self._adb(
            "shell", "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", self.package,
        )
        components = [line.strip() for line in result.stdout.splitlines()
                      if line.strip().startswith(self.package + "/")]
        if not components:
            raise RuntimeError(f"找不到启动 Activity: {self.package}")
        self._adb("shell", "am", "start", "-W", "-n", components[-1])
        while True:
            pid = running_pid(self.device, self.package, self.adb_path)
            if pid is not None:
                return pid
            time.sleep(0.25)

    def connect(self, source: str, on_message: Callable[..., None],
                on_detached: Callable[..., None]) -> None:
        self.device = (frida.get_device(self.device_id, timeout=15) if self.device_id
                       else frida.get_usb_device(timeout=15))
        if self.realm == "auto":
            arch = self.device.query_system_parameters().get("arch")
            self.realm = "emulated" if arch in {"x64", "x86_64", "ia32"} else "native"
        if self.realm == "emulated":
            self._prepare_agent()
        self.pid = running_pid(self.device, self.package, self.adb_path)
        launched = self.pid is None
        try:
            if self.pid is None:
                if self.realm == "emulated":
                    self.pid = self._launch_emulated()
                else:
                    self.pid = int(self.device.spawn([self.package]))
                    self._suspended_pid = self.pid
            if self.realm == "emulated":
                native_session = self.device.attach(self.pid, realm="native")
                self.sessions.append(native_session)
                native_session.on("detached", on_detached)
                bridge_ready = threading.Event()
                bridge_errors: list[str] = []

                def on_bridge(message: dict[str, Any], data: bytes | None) -> None:
                    if message.get("type") == "send":
                        if message.get("payload", {}).get("event") == "bridge-ready":
                            bridge_ready.set()
                    else:
                        bridge_errors.append(str(message.get("stack") or message.get("description")))
                        bridge_ready.set()

                bridge = native_session.create_script(BRIDGE_SCRIPT)
                self.scripts.append(bridge)
                bridge.on("message", on_bridge)
                bridge.load()
                if not bridge_ready.wait(15) or bridge_errors:
                    raise RuntimeError("Native Bridge 初始化失败: " + " | ".join(bridge_errors))
                session = self.device.attach(self.pid, realm="emulated", emulated_agent_path=REMOTE_AGENT)
            else:
                session = self.device.attach(self.pid, realm="native")
            self.sessions.append(session)
            session.on("detached", on_detached)
            script = session.create_script(source)
            self.scripts.append(script)
            script.on("message", on_message)
            script.load()
            if self._suspended_pid is not None:
                self.device.resume(self._suspended_pid)
                self._suspended_pid = None
            print(f"Frida {'已启动' if launched else '已附加'} PID={self.pid}，realm={self.realm}", flush=True)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for script in reversed(self.scripts):
            try:
                script.unload()
            except Exception:
                pass
        self.scripts.clear()
        for session in reversed(self.sessions):
            try:
                session.detach()
            except Exception:
                pass
        self.sessions.clear()
        if self._suspended_pid is not None and self.device is not None:
            try:
                self.device.resume(self._suspended_pid)
            except Exception:
                pass
            self._suspended_pid = None

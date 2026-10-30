from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from capture_store import PacketCaptureWriter, parse_uploaded_capture, record_to_frontend_packet
from frida_runtime import DEFAULT_ADB, FridaRuntime
from protocol_decoder import DEFAULT_CONFIG, WdProtocolDecoder, load_config


ROOT = Path(__file__).resolve().parent
FRIDA_SCRIPT_PATH = ROOT / "FridaScript_arm64-v8a.js"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEFAULT_PACKAGE = "com.miHoYo.wd"
MAX_UPLOAD_BYTES = 128 * 1024 * 1024


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return (
        f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    ).encode("utf-8")


class ClientHub:
    """Registered frontend windows and their independent SSE subscriptions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_subscription_id = 0
        self._subscriptions: dict[str, dict[int, queue.Queue[dict[str, Any]]]] = {}
        self._active_client_id: str | None = None

    def register(self, client_id: str) -> None:
        with self._lock:
            self._subscriptions.setdefault(client_id, {})

    def is_registered(self, client_id: str) -> bool:
        with self._lock:
            return client_id in self._subscriptions

    def subscribe(self, client_id: str) -> tuple[int, queue.Queue[dict[str, Any]]] | None:
        with self._lock:
            subscribers = self._subscriptions.get(client_id)
            if subscribers is None:
                return None
            self._next_subscription_id += 1
            subscription_id = self._next_subscription_id
            subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1_024)
            subscribers[subscription_id] = subscriber
            return subscription_id, subscriber

    def unsubscribe(self, client_id: str, subscription_id: int) -> None:
        with self._lock:
            subscribers = self._subscriptions.get(client_id)
            if subscribers is not None:
                subscribers.pop(subscription_id, None)

    def activate(self, client_id: str) -> None:
        with self._lock:
            if client_id not in self._subscriptions:
                raise ValueError("client not registered")
            self._active_client_id = client_id

    def deactivate_if_owner(self, client_id: str) -> bool:
        with self._lock:
            if self._active_client_id != client_id:
                return False
            self._active_client_id = None
            return True

    def publish_active(self, packet: dict[str, Any]) -> bool:
        with self._lock:
            client_id = self._active_client_id
        return client_id is not None and self.publish_to_client(client_id, packet)

    def publish_to_client(
        self,
        client_id: str,
        packet: dict[str, Any],
        *,
        blocking: bool = False,
    ) -> bool:
        with self._lock:
            subscribers = list(self._subscriptions.get(client_id, {}).values())
        delivered = False
        for subscriber in subscribers:
            try:
                if blocking:
                    subscriber.put(packet, timeout=5)
                else:
                    subscriber.put_nowait(packet)
                delivered = True
            except queue.Full:
                # Live capture favors timely packets.  Upload replay uses the
                # blocking path to preserve order for a connected window.
                continue
        return delivered


class FridaController:
    def __init__(
        self,
        package: str,
        max_packet_bytes: int,
        decoder: WdProtocolDecoder,
        clients: ClientHub,
        capture_writer: PacketCaptureWriter,
        adb: Path = DEFAULT_ADB,
        realm: str = "auto",
        device_id: str | None = None,
    ) -> None:
        self.package = package
        self.max_packet_bytes = max_packet_bytes
        self.decoder = decoder
        self.clients = clients
        self.capture_writer = capture_writer
        self.adb = adb
        self.realm = realm
        self.device_id = device_id
        self._lock = threading.RLock()
        self._runtime: FridaRuntime | None = None
        self._pid: int | None = None
        self._state = "stopped"
        self._last_error: str | None = None

    def _script_source(self) -> str:
        source = FRIDA_SCRIPT_PATH.read_text(encoding="utf-8")
        placeholder = "__MAX_PACKET_BYTES__"
        if placeholder not in source:
            raise RuntimeError(f"{FRIDA_SCRIPT_PATH} is missing {placeholder}")
        return source.replace(placeholder, str(self.max_packet_bytes))

    def _report_frida_event(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event") or "frida_event")
        if event == "hook_ready":
            print(
                "Frida hook ready: "
                f"{payload.get('hook', 'unknown')} "
                f"({payload.get('rva', 'unknown')})",
                flush=True,
            )
            return
        if event == "sniffer_ready":
            print("Frida sniffer hooks are ready", flush=True)
            return
        if event in {"hook_callback_error", "packet_skipped", "waiting_runtime"}:
            print(f"Frida {event}: {payload.get('error')}", flush=True)
            return
        if event in {"hook_install_error", "unsupported_runtime"}:
            detail = str(payload.get("error") or event)
            with self._lock:
                self._last_error = detail
                self._state = "error"
            print(f"Frida {event}: {detail}", flush=True)

    def _on_message(self, message: dict[str, Any], data: bytes | None) -> None:
        try:
            if message.get("type") != "send":
                detail = message.get("stack") or message.get("description") or json.dumps(message)
                with self._lock:
                    self._last_error = f"Frida error: {detail}"
                    self._state = "error"
                print(f"Frida error: {detail}", flush=True)
                return

            payload = message.get("payload")
            if not isinstance(payload, dict):
                return
            if payload.get("event") != "business_packet":
                self._report_frida_event(payload)
                return
            command_id = payload.get("command_id")
            if isinstance(command_id, bool) or not isinstance(command_id, int) or not 0 <= command_id <= 65535:
                raise ValueError("Frida command_id 无效")
            if data is None and payload.get("payload_length") == 0:
                data = b""
            if data is None or len(data) != payload.get("payload_length"):
                raise ValueError("Frida 明文负载缺失或长度不一致")
            record = self.decoder.decode_payload(
                bytes(data), command_id=command_id,
                direction=str(payload.get("direction") or "unknown"),
                runtime_class=payload.get("runtime_class")
                if isinstance(payload.get("runtime_class"), dict)
                else None,
            )
            if record["decode_status"] != "decoded":
                print(f"解包 {command_id}: {record['decode_status']}，{record['decode_error']}", flush=True)
            timestamp_ms = int(payload.get("ts_ms") or time.time() * 1000)
            packet = record_to_frontend_packet(record, timestamp_ms)
            try:
                self.capture_writer.write(packet)
            except OSError as error:
                print(f"Packet capture write failed: {error}", flush=True)
            self.clients.publish_active(packet)
        except Exception as error:
            detail = f"message handling failed: {type(error).__name__}: {error}"
            with self._lock:
                self._last_error = detail
            print(detail, flush=True)

    def _on_detached(self, reason: str, crash: Any = None) -> None:
        with self._lock:
            if self._state == "stopped":
                return
            self._state = "error"
            self._last_error = f"游戏连接断开: {reason}"
            self._pid = None
        self.capture_writer.close()
        print(self._last_error, flush=True)

    def start(self) -> None:
        with self._lock:
            if self._runtime is not None and self._state == "running":
                return
            if self._state == "starting":
                raise RuntimeError("Frida controller is already starting")
            self._state = "starting"
            self._last_error = None

        # 在加载 Hook 前切换会话，避免新进程恢复后的首包写入上一会话文件。
        self.capture_writer.start_session()

        if self._runtime is not None:
            self._runtime.close()
        runtime = FridaRuntime(self.package, self.adb, self.realm, self.device_id)
        self._runtime = runtime
        try:
            runtime.connect(self._script_source(), self._on_message, self._on_detached)
            with self._lock:
                if self._last_error is not None:
                    raise RuntimeError(self._last_error)
                self._pid = runtime.pid
                self._state = "running"
        except Exception as error:
            runtime.close()
            self._runtime = None
            self.capture_writer.close()
            detail = f"{type(error).__name__}: {error}"
            with self._lock:
                self._state = "error"
                self._last_error = detail
                self._pid = None
            raise RuntimeError(detail) from error

    def stop(self) -> None:
        with self._lock:
            runtime = self._runtime
            self._runtime = None
            self._pid = None
            self._state = "stopped"
        if runtime is not None:
            runtime.close()
        self.capture_writer.close()


def _replay_packets(clients: ClientHub, client_id: str, packets: list[dict[str, Any]]) -> None:
    for packet in packets:
        if not clients.publish_to_client(client_id, packet, blocking=True):
            return


def create_server(
    host: str = "127.0.0.1",
    port: int | None = None,
    package: str = DEFAULT_PACKAGE,
    max_packet_bytes: int = 8 * 1024 * 1024,
    config_path: Path = DEFAULT_CONFIG,
    adb: Path = DEFAULT_ADB,
    realm: str = "auto",
    device_id: str | None = None,
) -> Flask:
    if max_packet_bytes <= 0:
        raise ValueError("max_packet_bytes must be positive")
    if not FRONTEND_DIST.is_dir():
        raise RuntimeError(f"frontend build directory does not exist: {FRONTEND_DIST}")

    config = load_config(config_path)
    decoder = WdProtocolDecoder(config)
    print(f"Schema 已加载: {decoder.status()}", flush=True)
    clients = ClientHub()
    capture_writer = PacketCaptureWriter(ROOT)
    controller = FridaController(package, max_packet_bytes, decoder, clients, capture_writer,
                                 adb, realm, device_id)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["LISTENING_PORT"] = port if port is not None else config.listening_port
    app.controller = controller  # type: ignore[attr-defined]
    app.clients = clients  # type: ignore[attr-defined]
    app.capture_writer = capture_writer  # type: ignore[attr-defined]
    app.control_lock = threading.RLock()  # type: ignore[attr-defined]

    @app.after_request
    def add_cors_headers(response: Response) -> Response:
        origin = request.headers.get("Origin")
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        if request.method == "OPTIONS":
            allowed = {
                "/api/registration": "GET, OPTIONS",
                "/api/start": "GET, OPTIONS",
                "/api/stop": "GET, OPTIONS",
                "/api/stream": "GET, OPTIONS",
                "/api/upload": "POST, OPTIONS",
            }.get(request.path)
            if allowed:
                response.headers["Access-Control-Allow-Methods"] = allowed
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    def empty(status: int = 200) -> Response:
        response = Response(status=status)
        response.headers["Cache-Control"] = "no-store"
        return response

    def client_id(*, registered: bool) -> str | None:
        value = request.args.get("clientID", "")
        if not value or len(value) > 128:
            return None
        if registered and not clients.is_registered(value):
            return None
        return value

    @app.route("/api/registration", methods=["GET", "OPTIONS"])
    def registration() -> Response:
        if request.method == "OPTIONS":
            return empty(204)
        value = client_id(registered=False)
        if value is None:
            return jsonify(error="clientID required"), 400
        clients.register(value)
        return jsonify(success=True)

    @app.route("/api/start", methods=["GET", "OPTIONS"])
    def start_capture() -> Response:
        if request.method == "OPTIONS":
            return empty(204)
        value = client_id(registered=True)
        if value is None:
            return jsonify(error="clientID required or not registered"), 400
        with app.control_lock:  # type: ignore[attr-defined]
            try:
                clients.activate(value)
                controller.start()
            except RuntimeError as error:
                print(f"Frida start failed: {error}", flush=True)
                clients.deactivate_if_owner(value)
                return jsonify(error=str(error)), 500
        return empty()

    @app.route("/api/stop", methods=["GET", "OPTIONS"])
    def stop_capture() -> Response:
        if request.method == "OPTIONS":
            return empty(204)
        value = client_id(registered=True)
        if value is None:
            return jsonify(error="clientID required or not registered"), 400
        with app.control_lock:  # type: ignore[attr-defined]
            if clients.deactivate_if_owner(value):
                controller.stop()
        return empty()

    @app.route("/api/stream", methods=["GET", "OPTIONS"])
    def stream() -> Response:
        if request.method == "OPTIONS":
            return empty(204)
        value = client_id(registered=True)
        if value is None:
            return jsonify(error="clientID required or not registered"), 400
        subscription = clients.subscribe(value)
        if subscription is None:
            return jsonify(error="client not registered"), 400
        subscription_id, subscriber = subscription

        @stream_with_context
        def events():
            try:
                yield b"retry: 3000\n\n"
                while True:
                    try:
                        yield _sse("packetNotify", subscriber.get(timeout=15))
                    except queue.Empty:
                        yield b": keepalive\n\n"
            finally:
                clients.unsubscribe(value, subscription_id)

        response = Response(events(), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.route("/api/upload", methods=["POST", "OPTIONS"])
    def upload() -> Response:
        if request.method == "OPTIONS":
            return empty(204)
        value = client_id(registered=True)
        if value is None:
            return jsonify(error="clientID required or not registered"), 400
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify(error="file required"), 400
        content = uploaded.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return jsonify(error="upload is too large"), 413
        try:
            packets = parse_uploaded_capture(Path(uploaded.filename).name, content)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        threading.Thread(
            target=_replay_packets,
            args=(clients, value, packets),
            name="wd-upload-replay",
            daemon=True,
        ).start()
        return jsonify(success=True)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def static_files(path: str):
        if path.startswith("api/") or path.rstrip("/").lower() in {"getconfig", "setconfig"}:
            return jsonify(error="not found"), 404
        relative = path or "index.html"
        return send_from_directory(FRONTEND_DIST, relative)

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--max-packet-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--adb", type=Path, default=DEFAULT_ADB, help="默认从 PATH 查找 adb.exe")
    parser.add_argument("--realm", choices=("auto", "native", "emulated"), default="auto")
    parser.add_argument("--device", help="Frida/ADB 设备 ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = create_server(host=args.host, package=args.package,
                           max_packet_bytes=args.max_packet_bytes, adb=args.adb,
                           realm=args.realm, device_id=args.device)
    port = server.config["LISTENING_PORT"]
    print(f"WDSniffer listening on http://{args.host}:{port}", flush=True)
    try:
        server.run(host=args.host, port=port, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        server.controller.stop()
        server.capture_writer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

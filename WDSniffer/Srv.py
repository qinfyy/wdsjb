"""Local BH2 web sniffer controller and the frontend's minimal HTTP API.

The Vue frontend owns a UUID per browser window.  A running Frida capture has
one active owner, and packets are routed only to that owner's SSE connection.
Uploaded replays are instead routed only to the window that uploaded them.
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

import frida
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from capture_store import PacketCaptureWriter, parse_uploaded_capture, record_to_frontend_packet
from protocol_decoder import Bh2ProtocolDecoder, default_decoder


ROOT = Path(__file__).resolve().parent
FRIDA_SCRIPT_PATH = ROOT / "FridaScript_x86.js"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEFAULT_PACKAGE = "com.miHoYo.HSoDv2Original"
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
        decoder: Bh2ProtocolDecoder,
        clients: ClientHub,
        capture_writer: PacketCaptureWriter,
    ) -> None:
        self.package = package
        self.max_packet_bytes = max_packet_bytes
        self.decoder = decoder
        self.clients = clients
        self.capture_writer = capture_writer
        self._lock = threading.RLock()
        self._device: Any = None
        self._session: Any = None
        self._script: Any = None
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
        if event in {"hook_install_error", "unsupported_runtime", "hook_callback_error"}:
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
            if data is None:
                print("Frida business packet did not include byte data", flush=True)
                return

            protocol_hint = payload.get("protocol_hint")
            if protocol_hint not in {"protobuf", "command"}:
                protocol_hint = None
            command_id_hint = payload.get("command_id")
            if isinstance(command_id_hint, bool) or not isinstance(command_id_hint, int):
                command_id_hint = None

            record = self.decoder.decode_frame(
                bytes(data),
                direction=str(payload.get("direction") or "unknown"),
                runtime_class=payload.get("runtime_class")
                if isinstance(payload.get("runtime_class"), dict)
                else None,
                protocol_hint=protocol_hint,
                command_id_hint=command_id_hint,
            )
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

    def start(self, spawn_if_missing: bool = False) -> None:
        with self._lock:
            if self._script is not None:
                return
            if self._state == "starting":
                raise RuntimeError("Frida controller is already starting")
            self._state = "starting"
            self._last_error = None

        # 在加载 Hook 前切换会话，避免新进程恢复后的首包写入上一会话文件。
        self.capture_writer.start_session()

        session: Any = None
        script: Any = None
        spawned_pid: int | None = None
        try:
            device = frida.get_usb_device(timeout=10)
            application = next(
                (item for item in device.enumerate_applications() if item.identifier == self.package),
                None,
            )
            pid = int(application.pid) if application is not None and application.pid else 0
            launch_mode = "attached"
            if pid <= 0:
                if not spawn_if_missing:
                    raise RuntimeError(f"{self.package} is not running")
                pid = int(device.spawn([self.package]))
                spawned_pid = pid
                launch_mode = "spawned"

            session = device.attach(pid)
            script = session.create_script(self._script_source())
            script.on("message", self._on_message)
            script.load()
            if spawned_pid is not None:
                device.resume(spawned_pid)

            with self._lock:
                self._device = device
                self._session = session
                self._script = script
                self._pid = pid
                self._state = "running"
            print(f"Frida {launch_mode} pid={pid}", flush=True)
        except Exception as error:
            if script is not None:
                try:
                    script.unload()
                except Exception:
                    pass
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
            detail = f"{type(error).__name__}: {error}"
            with self._lock:
                self._state = "error"
                self._last_error = detail
                self._pid = None
            raise RuntimeError(detail) from error

    def stop(self) -> None:
        with self._lock:
            script = self._script
            session = self._session
            self._script = None
            self._session = None
            self._device = None
            self._pid = None
            self._state = "stopped"
        if script is not None:
            try:
                script.unload()
            except Exception:
                pass
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
        self.capture_writer.close()


def _replay_packets(clients: ClientHub, client_id: str, packets: list[dict[str, Any]]) -> None:
    for packet in packets:
        if not clients.publish_to_client(client_id, packet, blocking=True):
            return


def create_server(
    host: str = "127.0.0.1",
    port: int = 1984,
    package: str = DEFAULT_PACKAGE,
    max_packet_bytes: int = 8 * 1024 * 1024,
) -> Flask:
    if max_packet_bytes <= 0:
        raise ValueError("max_packet_bytes must be positive")
    if not FRONTEND_DIST.is_dir():
        raise RuntimeError(f"frontend build directory does not exist: {FRONTEND_DIST}")

    decoder = default_decoder(ROOT)
    clients = ClientHub()
    capture_writer = PacketCaptureWriter(ROOT)
    controller = FridaController(package, max_packet_bytes, decoder, clients, capture_writer)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
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
                controller.start(spawn_if_missing=True)
            except RuntimeError as error:
                print(f"Frida start failed: {error}", flush=True)
                return jsonify(error=str(error)), 500
            clients.activate(value)
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
            name="bh2-upload-replay",
            daemon=True,
        ).start()
        return jsonify(success=True)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def static_files(path: str):
        if path.startswith("api/"):
            return jsonify(error="not found"), 404
        relative = path or "index.html"
        return send_from_directory(FRONTEND_DIST, relative)

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1984)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--max-packet-bytes", type=int, default=8 * 1024 * 1024)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = create_server(args.host, args.port, args.package, args.max_packet_bytes)
    print(f"BH2Sniffer listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        server.controller.stop()
        server.capture_writer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

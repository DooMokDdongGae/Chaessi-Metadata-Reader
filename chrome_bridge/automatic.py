"""Reader-owned lifetime with an authenticated, small WebSocket notification channel.

Metadata continues to use the existing bounded HTTP request/result validation.
No browser process, settings page or native host process is started here.
"""
import hmac
import re
import secrets
import threading
import time

from chrome_bridge.server import Bridge, EXTENSION
from chrome_bridge.key_store import PairingKeyError
from chrome_bridge.socket_wire import SocketWire, WireError, upgrade_accept


class AutomaticBridge(Bridge):
    def __init__(self, *args, **kwargs):
        self.peer = None
        self.session = None
        self.stopping = False
        self.socket_slots = threading.BoundedSemaphore(3)
        self.socket_metrics = {name: 0 for name in (
            "upgrades", "authenticated", "disconnected", "rejected", "busy", "heartbeat", "wake")}
        self.started_at = time.monotonic()
        super().__init__(*args, **kwargs)

    def snapshot(self):
        with self.lock:
            result = super().snapshot()
            result.update(connected=self.peer is not None and not self.stopping,
                          socket_metrics=dict(self.socket_metrics))
            return result

    def session_allowed(self, session):
        with self.lock:
            return bool(not self.stopping and self.peer and isinstance(session, str) and self.session
                        and hmac.compare_digest(session, self.session))

    def change_pairing(self, import_key):
        """Commit to disk before changing the key and invalidating the previous peer."""
        with self.lock:
            if self.stopping or self.job is not None:
                raise PairingKeyError("PAIRING_KEY_BUSY")
            value = import_key(self.token)
            if hmac.compare_digest(self.token, value):
                return False
            peer = self.peer
            self.token = value
            self.peer = self.session = None
            if peer:
                self.socket_metrics["disconnected"] += 1
        if peer:
            peer.close()
        return True

    def claim_request(self, session):
        with self.lock:
            return super().claim() if self.session_allowed(session) else {"job": None}

    def accept_request(self, event, session):
        with self.lock:
            return self.session_allowed(session) and super().accept(event)

    def job_created(self):
        with self.lock:
            peer = self.peer
        if peer:
            self.notify(peer)

    def notify(self, peer):
        try:
            peer.send_json({"type": "wake"})
            with self.lock:
                self.socket_metrics["wake"] += 1
        except (OSError, WireError):
            self.drop_peer(peer)

    def drop_peer(self, peer):
        with self.lock:
            if self.peer is peer:
                self.peer = self.session = None
                self.socket_metrics["disconnected"] += 1
                job = self.job
                if job and not job["done"].is_set():
                    job["events"].append({"event": "error", "message":
                        "Chrome 연결이 끊겼습니다. 자동 복구 후 다시 가져오세요."})
                    job["done"].set()
        peer.close()

    def upgrade_socket(self, request):
        headers = request.headers
        host = "127.0.0.1:" + str(self.http.server_port)
        if (request.command != "GET" or request.path != "/socket" or
            headers.get_all("Host") != [host] or len(headers.get_all("Origin", [])) != 1 or
            not EXTENSION.fullmatch(headers.get("Origin", "")) or self.stopping):
            return request.reply(403)
        try:
            accept = upgrade_accept(headers)
        except WireError:
            return request.reply(400)
        if not self.socket_slots.acquire(blocking=False):
            return request.reply(503)
        peer = None
        auth_deadline = None
        request.close_connection = True
        try:
            request.connection.settimeout(4)
            request.protocol_version = "HTTP/1.1"
            request.send_response(101)
            request.send_header("Upgrade", "websocket")
            request.send_header("Connection", "Upgrade")
            request.send_header("Sec-WebSocket-Accept", accept)
            request.end_headers()
            peer = SocketWire(request.connection, request.rfile)
            auth_deadline = threading.Timer(4, peer.close)
            auth_deadline.daemon = True
            auth_deadline.start()
            with self.lock:
                self.socket_metrics["upgrades"] += 1
            auth = peer.receive_json()
            if (not isinstance(auth, dict) or set(auth) != {"type", "key"} or auth["type"] != "auth"
                or not isinstance(auth["key"], str) or not re.fullmatch(r"[a-f0-9]{64}", auth["key"])):
                peer.send_json({"type": "error", "code": "auth"})
                return
            auth_deadline.cancel()
            with self.lock:
                if not hmac.compare_digest(auth["key"], self.token):
                    peer.send_json({"type": "error", "code": "auth"})
                    return
                if self.stopping or self.peer is not None:
                    self.socket_metrics["busy"] += 1
                    peer.send_json({"type": "error", "code": "busy"})
                    return
                self.peer = peer
                self.session = secrets.token_hex(16)
                self.connected_at = time.monotonic()
                self.socket_metrics["authenticated"] += 1
                # Serialize ready before a concurrent job's wake frame.
                peer.send_json({"type": "ready", "session": self.session})
            auth = None
            request.connection.settimeout(45)
            self.notify(peer)
            while not self.stopping:
                packet = peer.receive_json()
                if packet is None:
                    break
                if packet != {"type": "ping"}:
                    raise WireError()
                with self.lock:
                    if self.peer is not peer:
                        break
                    self.socket_metrics["heartbeat"] += 1
                peer.send_json({"type": "pong"})
        except (OSError, ValueError, WireError):
            with self.lock:
                self.socket_metrics["rejected"] += 1
        finally:
            if auth_deadline:
                auth_deadline.cancel()
            if peer:
                self.drop_peer(peer)
            self.socket_slots.release()

    def close(self):
        with self.lock:
            if self.stopping:
                return
            self.stopping = True
            peer = self.peer
            if peer:
                try:
                    peer.send_json({"type": "shutdown"})
                except (OSError, WireError):
                    pass
        if peer:
            self.drop_peer(peer)
        super().close()

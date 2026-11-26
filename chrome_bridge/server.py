"""Authenticated loopback transport to the user's explicitly connected Chrome extension."""
import hmac
import json
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bundle.model import URL, decode_bundle
from chrome_bridge.key_store import BridgeKeyStore

ROOT = Path(__file__).resolve().parents[1]
PORT = 47921
INSPECT_URL = "https://novelai.net/inspect"
MAX_BODY = 16 * 1024 * 1024
EXTENSION = re.compile(r"chrome-extension://[a-p]{32}")


def installation_key():
    return BridgeKeyStore().load()[0]


class LoopbackServer(ThreadingHTTPServer):
    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = self.allow_reuse_port = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Bridge:
    def __init__(self, port=PORT, token=None, *, key_provider=installation_key):
        self.lock = threading.RLock()
        self.job = None
        self.connected_at = 0
        self.requests = {"total": 0, "valid_host": 0, "origin_present": 0,
                         "valid_origin": 0, "valid_auth": 0, "preflight": 0,
                         "missing_origin": 0, "destination_origin": 0}
        self.http = LoopbackServer(("127.0.0.1", port), handler(self))
        self.http.daemon_threads = True
        try:
            # Resolve credentials only after owning the local listener. A second
            # Reader must never initialize or repair keys for the running one.
            self.token = token or key_provider()
            self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
            self.worker.start()
        except BaseException:
            self.http.server_close()
            raise

    def close(self):
        self.http.shutdown()
        self.http.server_close()

    def snapshot(self):
        with self.lock:
            job = self.job
            return {"requests": dict(self.requests), "authenticated_extension_seen": bool(self.connected_at),
                    "job_claimed": bool(job and job["claimed"]),
                    "card_count_received": job.get("count") if job else None}

    def request(self, url, progress=lambda count: None, timeout=120, observe=None):
        if not isinstance(url, str) or not URL.fullmatch(url):
            raise ValueError("https://aitag.win/i/작품번호 형식의 주소를 입력하세요.")
        return self._request(url, progress, timeout, observe)

    def request_inspect(self, progress=lambda count: None, timeout=120, observe=None):
        return self._request(INSPECT_URL, progress, timeout, observe, kind="inspect")

    def _request(self, url, progress, timeout, observe, kind=None):
        job = {"id": secrets.token_hex(16), "url": url, "claimed": False, "events": [], "done": threading.Event()}
        if kind is not None:
            job["kind"] = kind
        with self.lock:
            if self.job is not None:
                raise ValueError("다른 묶음을 수집하는 중입니다.")
            self.job = job
        self.job_created()
        deadline = time.monotonic() + timeout
        observed_at = 0
        try:
            while time.monotonic() < deadline:
                job["done"].wait(.1)
                if observe and time.monotonic() - observed_at >= 1:
                    observe(self.snapshot())
                    observed_at = time.monotonic()
                with self.lock:
                    events, job["events"] = job["events"], []
                for event in events:
                    if event["event"] == "count":
                        progress(event["count"])
                    elif event["event"] == "error":
                        raise ValueError(event["message"])
                    elif event["event"] == "result":
                        return event["bundle"]
            raise ValueError("Chrome 연결 또는 작품 수집 시간이 초과됐습니다. Chrome 확장과 작품 접근 상태를 확인하세요.")
        finally:
            with self.lock:
                if self.job is job:
                    self.job = None

    def claim(self):
        with self.lock:
            self.connected_at = time.monotonic()
            if self.job is None or self.job["claimed"]:
                return {"job": None}
            self.job["claimed"] = True
            return {"job": {key: self.job[key] for key in ("id", "url", "kind") if key in self.job}}

    def job_created(self):
        pass

    def session_allowed(self, session):
        return True

    def claim_request(self, session):
        return self.claim()

    def accept_request(self, event, session):
        return self.accept(event)

    def accept(self, event):
        with self.lock:
            job = self.job
            if not isinstance(event, dict) or job is None or event.get("id") != job["id"] or job["done"].is_set():
                return False
            kind = event.get("event")
            if kind == "count":
                count = event.get("count")
                if type(count) is not int or not 1 <= count <= 1000 or "count" in job:
                    return False
                if job.get("kind") == "inspect" and count != 1:
                    return False
                job["count"] = count
            elif kind == "result":
                bundle = event.get("bundle")
                if not isinstance(bundle, dict) or event.get("url") != job["url"] or bundle.get("source") != job["url"]:
                    return False
                cards = decode_bundle(bundle)
                if job.get("count") != len(cards):
                    return False
                raw_cards = bundle["cards"]
                if len(raw_cards) != len(cards) or any(
                    not isinstance(card, dict) or type(card.get("index")) is not int or card["index"] != index
                    for index, card in enumerate(raw_cards)
                ):
                    return False
                expected_origin = "novelai_inspect" if job.get("kind") == "inspect" else "aitag"
                if any(card.get("origin", "aitag") != expected_origin for card in raw_cards):
                    return False
            elif kind == "error":
                message = event.get("message")
                if not isinstance(message, str) or not 1 <= len(message) <= 400:
                    return False
            else:
                return False
            job["events"].append(event)
            if kind != "count":
                job["done"].set()
            return True


def handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body=None):
            raw = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            origin = self.headers.get("Origin", "")
            destination = "http://127.0.0.1:" + str(self.server.server_port)
            if EXTENSION.fullmatch(origin) or origin == destination:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Reader-Session")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self, preflight=False):
            host = "127.0.0.1:" + str(self.server.server_port)
            valid_host = self.headers.get("Host") == host
            origin = self.headers.get("Origin", "")
            # Privileged Chrome extension requests may omit Origin for GET,
            # or use the destination origin for POST (Chromium OOR-CORS).
            # Neither form replaces the 256-bit bearer secret or exact Host.
            destination_origin = origin == "http://" + host
            valid_origin = bool(EXTENSION.fullmatch(origin)) or destination_origin or (
                not origin and self.command == "GET" and not preflight)
            valid_auth = hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge.token)
            with bridge.lock:
                for name, value in {"total": True, "valid_host": valid_host, "origin_present": bool(origin),
                                    "valid_origin": valid_origin, "valid_auth": valid_auth, "preflight": preflight,
                                    "missing_origin": not origin, "destination_origin": destination_origin}.items():
                    bridge.requests[name] += int(value)
            valid_session = preflight or bridge.session_allowed(self.headers.get("X-Reader-Session"))
            return valid_host and valid_origin and (preflight or valid_auth) and valid_session

        def do_OPTIONS(self):
            self.reply(200 if self.allowed(True) else 403)

        def do_GET(self):
            if self.path == "/socket" and hasattr(bridge, "upgrade_socket"):
                return bridge.upgrade_socket(self)
            if not self.allowed():
                return self.reply(403)
            if self.path != "/next":
                return self.reply(404)
            self.reply(200, bridge.claim_request(self.headers.get("X-Reader-Session")))

        def do_POST(self):
            if not self.allowed():
                return self.reply(403)
            if self.path != "/event":
                return self.reply(404)
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                    return self.reply(413)
                self.connection.settimeout(15)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    return self.reply(400)
                accepted = bridge.accept_request(json.loads(raw), self.headers.get("X-Reader-Session"))
                self.reply(200 if accepted else 409)
            except (ValueError, OSError, RecursionError):
                self.reply(400)
    return Handler

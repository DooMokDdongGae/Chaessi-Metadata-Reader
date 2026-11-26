import base64
import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from chrome_bridge.automatic import AutomaticBridge

ORIGIN = "chrome-extension://" + "a" * 32
KEY = "b" * 64


class Peer:
    def __init__(self, port, origin=ORIGIN, host=None):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.file = self.socket.makefile("rb")
        headers = ["GET /socket HTTP/1.1", "Host: " + (host or f"127.0.0.1:{port}"),
                   "Upgrade: websocket", "Connection: Upgrade", "Sec-WebSocket-Version: 13",
                   "Sec-WebSocket-Key: " + base64.b64encode(b"synthetic nonce!").decode()]
        # The nonce above has 16 bytes; no real connection key is used in tests.
        if origin is not None:
            headers.append("Origin: " + origin)
        self.socket.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
        self.status = int(self.file.readline().split()[1])
        while self.file.readline() not in (b"\r\n", b""):
            pass

    def send(self, data):
        raw = json.dumps(data).encode()
        mask = b"1234"
        prefix = bytes([0x81, 0x80 | len(raw)]) if len(raw) < 126 else b"\x81\xfe" + len(raw).to_bytes(2, "big")
        self.socket.sendall(prefix + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(raw)))

    def read(self):
        head = self.file.read(2)
        if len(head) != 2:
            return None
        length = head[1] & 127
        if length == 126:
            length = int.from_bytes(self.file.read(2), "big")
        elif length == 127:
            length = int.from_bytes(self.file.read(8), "big")
        raw = self.file.read(length)
        return json.loads(raw) if head[0] & 15 == 1 else None

    def auth(self, key=KEY):
        self.send({"type": "auth", "key": key})
        return self.read()

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.file.close()
        self.socket.close()


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.bridge = AutomaticBridge(port=0, token=KEY)
        self.port = self.bridge.http.server_port
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.pool.shutdown)
        self.addCleanup(self.bridge.close)

    def peer(self, **kwargs):
        peer = Peer(self.port, **kwargs)
        self.addCleanup(peer.close)
        return peer

    def connected(self):
        peer = self.peer()
        self.assertEqual(peer.status, 101)
        hello = peer.auth()
        self.assertEqual(hello["type"], "ready")
        self.assertEqual(peer.read(), {"type": "wake"})
        return peer, hello["session"]

    def http(self, path, session=None, body=None, *, method=None):
        headers = {"Authorization": "Bearer " + KEY, "Origin": ORIGIN}
        if session:
            headers["X-Reader-Session"] = session
        data = None if body is None else json.dumps(body).encode()
        if data:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}" + path, data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, None

    def test_web_origins_host_and_missing_origin_cannot_upgrade(self):
        for origin in (None, "null", "https://novelai.net", "https://evil.example", ORIGIN + ".example"):
            self.assertEqual(self.peer(origin=origin).status, 403)
        self.assertEqual(self.peer(host="localhost:" + str(self.port)).status, 403)
        self.assertFalse(self.bridge.snapshot()["connected"])

    def test_bad_auth_never_enables_http_or_connection(self):
        peer = self.peer()
        self.assertEqual(peer.status, 101)
        self.assertEqual(peer.auth("c" * 64), {"type": "error", "code": "auth"})
        self.assertEqual(self.http("/next")[0], 403)
        self.assertFalse(self.bridge.snapshot()["connected"])

    def test_authenticated_generation_and_ping(self):
        peer, session = self.connected()
        self.assertTrue(self.bridge.snapshot()["connected"])
        self.assertEqual(self.http("/next")[0], 403)
        self.assertEqual(self.http("/next", "0" * 32)[0], 403)
        self.assertEqual(self.http("/next", session), (200, {"job": None}))
        peer.send({"type": "ping"})
        self.assertEqual(peer.read(), {"type": "pong"})

    def test_duplicate_connection_does_not_replace_active_peer(self):
        _first, session = self.connected()
        duplicate = self.peer()
        self.assertEqual(duplicate.auth(), {"type": "error", "code": "busy"})
        self.assertEqual(self.http("/next", session)[0], 200)

    def test_job_is_notified_and_existing_http_result_validation_is_retained(self):
        peer, session = self.connected()
        future = self.pool.submit(self.bridge.request_inspect, timeout=3)
        self.assertEqual(peer.read(), {"type": "wake"})
        status, next_job = self.http("/next", session)
        self.assertEqual(status, 200)
        job = next_job["job"]
        self.assertEqual(job["kind"], "inspect")
        self.assertEqual(self.http("/event", session, {"id":job["id"],"event":"count","count":1})[0], 200)
        bundle = {"format":"chaessi.readable-bundle","version":1,"count":1,"source":job["url"],
                  "cards":[{"index":0,"status":"ok","readable":"synthetic", "base":"paper", "negative":"",
                            "characters":[],"structure":"single","origin":"novelai_inspect"}]}
        event = {"id":job["id"],"event":"result","url":job["url"],"bundle":bundle}
        wrong = dict(event, url="https://novelai.net/")
        self.assertEqual(self.http("/event", session, wrong)[0], 409)
        self.assertEqual(self.http("/event", session, event)[0], 200)
        self.assertEqual(future.result(timeout=3), bundle)

    def test_disconnect_aborts_job_and_old_session_cannot_claim_or_deliver(self):
        peer, session = self.connected()
        future = self.pool.submit(self.bridge.request_inspect, timeout=3)
        self.assertEqual(peer.read(), {"type": "wake"})
        self.assertEqual(self.http("/next", session)[0], 200)
        peer.close()
        with self.assertRaisesRegex(ValueError, "Chrome 연결이 끊겼습니다"):
            future.result(timeout=3)

        new_peer, new_session = self.connected()
        self.assertNotEqual(session, new_session)
        current = self.pool.submit(self.bridge.request_inspect, timeout=3)
        self.assertEqual(new_peer.read(), {"type": "wake"})
        self.assertEqual(self.http("/next", session)[0], 403)
        self.assertFalse(self.bridge.snapshot()["job_claimed"])
        # A rejected POST is answered before its body is read. An empty POST tests
        # the exact HTTP status without racing an unread upload against socket close.
        self.assertEqual(self.http("/event", session, method="POST")[0], 403)
        status, claimed = self.http("/next", new_session)
        self.assertEqual(status, 200)
        job_id = claimed["job"]["id"]
        event = {"id": job_id, "event": "count", "count": 1}
        self.assertFalse(self.bridge.accept_request(event, session))
        self.assertIsNone(self.bridge.snapshot()["card_count_received"])
        self.assertEqual(self.http("/event", new_session, event)[0], 200)
        self.assertEqual(self.bridge.snapshot()["card_count_received"], 1)
        end = {"id": job_id, "event": "error", "message": "synthetic completion"}
        self.assertEqual(self.http("/event", new_session, end)[0], 200)
        with self.assertRaisesRegex(ValueError, "synthetic completion"):
            current.result(timeout=3)

    def test_close_signals_shutdown_and_releases_listener(self):
        peer, _session = self.connected()
        self.bridge.close()
        self.assertEqual(peer.read(), {"type":"shutdown"})
        self.assertFalse(self.bridge.snapshot()["connected"])
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=.2)


if __name__ == "__main__":
    unittest.main()

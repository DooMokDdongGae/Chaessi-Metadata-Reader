import concurrent.futures
from contextlib import contextmanager
from email.message import Message
import io
import json
import socket
import threading
import time
import unittest

from chrome_bridge.socket_wire import MAX_MESSAGE, SocketWire, WireError, upgrade_accept


def upgrade_headers():
    headers = Message()
    headers["Connection"] = "keep-alive, UpGrAdE"
    headers["Upgrade"] = "WebSocket"
    headers["Sec-WebSocket-Key"] = "dGhlIHNhbXBsZSBub25jZQ=="
    headers["Sec-WebSocket-Version"] = "13"
    return headers


def client_frame(opcode, data=b"", final=True):
    mask = b"abcd"
    length = len(data)
    size = bytes([0x80 | length]) if length < 126 else b"\xfe" + length.to_bytes(2, "big")
    return bytes([opcode | (0x80 if final else 0)]) + size + mask + bytes(
        byte ^ mask[i % 4] for i, byte in enumerate(data))


@contextmanager
def _pair():
    # Windows Python creates the pair via loopback and accepts without a timeout.
    previous = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        local, peer = socket.socketpair()
    except (TimeoutError, PermissionError):
        raise unittest.SkipTest("loopback socketpair unavailable in this environment")
    finally:
        socket.setdefaulttimeout(previous)
    with local, peer:
        yield local, peer


class Output:
    def __init__(self):
        self.frames = []
        self.closed = False

    def sendall(self, frame):
        self.frames.append(frame)

    def shutdown(self, _):
        pass

    def close(self):
        self.closed = True


class WireTests(unittest.TestCase):
    def test_rfc_handshake_example(self):
        self.assertEqual(upgrade_accept(upgrade_headers()), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_missing_duplicate_and_invalid_headers(self):
        for field in upgrade_headers().keys():
            with self.subTest(field=field):
                headers = upgrade_headers()
                headers[field] = headers[field]
                with self.assertRaises(WireError):
                    upgrade_accept(headers)
                del headers[field]
                with self.assertRaises(WireError):
                    upgrade_accept(headers)
        for field, value in [
            ("Upgrade", "websockets"), ("Connection", "upgrader"),
            ("Connection", "upgrade,\r\ncontinued"), ("Sec-WebSocket-Version", "12"),
            ("Sec-WebSocket-Key", "ZA=="), ("Sec-WebSocket-Key", "!" * 24),
            ("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZR=="),
        ]:
            with self.subTest(field=field, value=value):
                headers = upgrade_headers()
                headers.replace_header(field, value)
                with self.assertRaises(WireError):
                    upgrade_accept(headers)

    def test_fragments_split_unicode_with_interleaved_control_and_next_message(self):
        text = '{"type":"준비"}'.encode("utf-8")
        point = text.index("준".encode("utf-8")) + 1
        combined = (client_frame(1, text[:point], False) + client_frame(9, b"hello")
                    + client_frame(10, b"other") + client_frame(0, text[point:])
                    + client_frame(1, b"{}"))
        out = Output()
        wire = SocketWire(out, io.BytesIO(combined))
        self.assertEqual(wire.receive_json(), {"type": "준비"})
        self.assertEqual(out.frames, [b"\x8a\x05hello"])
        self.assertEqual(wire.receive_json(), {})
        self.assertIsNone(wire.receive_json())
        self.assertTrue(out.closed)

    def test_sender_and_receiver_agree_on_utf8_limit_and_unmasked_server_lengths(self):
        # The JSON shell is eight bytes. One Hangul syllable occupies three bytes.
        prefix = "한" * ((MAX_MESSAGE - 8) // 3)
        content = prefix + "x" * ((MAX_MESSAGE - 8) % 3)
        out = Output()
        wire = SocketWire(out, io.BytesIO())
        wire.send_json({"x": content})
        frame = out.frames[0]
        self.assertEqual(frame[:4], b"\x81\x7e\x10\x00")
        self.assertEqual(len(frame[4:]), MAX_MESSAGE)
        wire = SocketWire(out, io.BytesIO(client_frame(1, frame[4:])))
        self.assertEqual(wire.receive_json(), {"x": content})
        for invalid in ({"x": content + "x"}, {"x": float("nan")}, {"x": "\ud800"}, []):
            with self.assertRaises(WireError):
                wire.send_json(invalid)
        self.assertEqual(len(out.frames), 1)

    def test_invalid_or_truncated_frames_permanently_end_stream(self):
        cases = [
            b"\xc1\x80", b"\x81\x00", b"\x83\x80", b"\x8b\x80", b"\x82\x80",
            b"\x09\x80", b"\x89\xfe", b"\x81\xfe\x00\x7d",
            b"\x81\xff" + (4096).to_bytes(8, "big"), b"\x81\xff" + b"\x80" + b"\0" * 7,
            b"\x81\xfe\x10\x01", b"\x81\xff" + (1 << 20).to_bytes(8, "big"),
            b"\x81", b"\x81\x80abc", b"\x81\x82abcda", client_frame(0),
            client_frame(1, b"{", False), client_frame(1, b"{", False) + client_frame(1, b"}"),
            client_frame(1, b"x" * MAX_MESSAGE, False) + client_frame(0, b"y"),
        ]
        for i, raw in enumerate(cases):
            with self.subTest(case=i):
                out = Output()
                wire = SocketWire(out, io.BytesIO(raw))
                with self.assertRaises(WireError) as caught:
                    wire.receive_json()
                self.assertEqual(str(caught.exception), "websocket")
                self.assertTrue(out.closed)
                self.assertIsNone(wire.receive_json())

    def test_only_strict_utf8_json_objects_without_ambiguous_keys(self):
        for data in (b"\xff", b"[]", b"true", b"{}", b'{ "x": 1, "x": 2 }',
                     b'{"x":NaN}', b'{"x":invalid}', b"\xef\xbb\xbf{}", b"{}{}"):
            with self.subTest(data=data):
                out = Output()
                wire = SocketWire(out, io.BytesIO(client_frame(1, data)))
                if data == b"{}":
                    self.assertEqual(wire.receive_json(), {})
                else:
                    with self.assertRaises(WireError) as caught:
                        wire.receive_json()
                    self.assertIsNone(caught.exception.__context__)
                    self.assertEqual(out.frames, [b"\x88\x02\x03\xef"])

    def test_close_codes_and_reason_validation(self):
        for code in (1000, 1010, 1013, 4000):
            with self.subTest(code=code):
                body = code.to_bytes(2, "big")
                out = Output()
                wire = SocketWire(out, io.BytesIO(client_frame(8, body + "끝".encode("utf-8"))))
                self.assertIsNone(wire.receive_json())
                self.assertEqual(out.frames, [b"\x88\x00" if code == 1010 else b"\x88\x02" + body])
                self.assertTrue(out.closed)
                with self.assertRaises(WireError):
                    wire.send_json({})
        out = Output()
        self.assertIsNone(SocketWire(out, io.BytesIO(client_frame(8))).receive_json())
        self.assertEqual(out.frames, [b"\x88\x00"])
        invalid = [i.to_bytes(2, "big") for i in (999, 1004, 1005, 1006, 1015, 2100, 5000)]
        for payload in [*invalid, b"x", b"\x03\xe8\xff"]:
            with self.subTest(payload=payload):
                with self.assertRaises(WireError):
                    SocketWire(Output(), io.BytesIO(client_frame(8, payload))).receive_json()

    def test_bounds_on_empty_fragment_and_control_runs(self):
        for frames in (client_frame(1, final=False) + client_frame(0, final=False) * MAX_MESSAGE,
                       client_frame(10) * 129):
            with self.assertRaises(WireError):
                SocketWire(Output(), io.BytesIO(frames)).receive_json()

    def test_concurrent_application_writes_are_serialized(self):
        class CheckedOutput(Output):
            def __init__(self):
                super().__init__()
                self.writing = threading.Lock()

            def sendall(self, frame):
                if not self.writing.acquire(blocking=False):
                    raise AssertionError("concurrent writes")
                try:
                    time.sleep(.002)
                    super().sendall(frame)
                finally:
                    self.writing.release()

        out = CheckedOutput()
        wire = SocketWire(out, io.BytesIO())
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            writes = [pool.submit(wire.send_json, {"n": i}) for i in range(12)]
            for write in writes:
                write.result(timeout=2)
        self.assertEqual({json.loads(frame[2:])["n"] for frame in out.frames}, set(range(12)))

    def test_socketpair_writes_and_close_interrupts_pending_read(self):
        with _pair() as (local, peer):
            local.settimeout(2)
            peer.settimeout(2)
            with local.makefile("rb") as reader, peer.makefile("rb") as response:
                wire = SocketWire(local, reader)
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                    writes = [pool.submit(wire.send_json, {"n": i}) for i in range(12)]
                    seen = set()
                    for _ in writes:
                        opcode, length = response.read(2)
                        self.assertEqual(opcode, 0x81)
                        self.assertLess(length, 126)
                        seen.add(json.loads(response.read(length))["n"])
                    for write in writes:
                        write.result(timeout=2)
                    self.assertEqual(seen, set(range(12)))
                    pending = pool.submit(wire.receive_json)
                    wire.close()
                    self.assertIsNone(pending.result(timeout=2))
                    wire.close()

    def test_read_timeout_and_failed_send_are_terminal(self):
        class TimeoutReader:
            calls = 0

            def read(self, size):
                self.calls += 1
                if self.calls == 1:
                    return b"\x81"
                raise TimeoutError()

        reader = TimeoutReader()
        wire = SocketWire(Output(), reader)
        with self.assertRaises(WireError):
            wire.receive_json()
        self.assertIsNone(wire.receive_json())
        self.assertEqual(reader.calls, 2)

        class Broken(Output):
            def sendall(self, frame):
                raise OSError("synthetic")

        wire = SocketWire(Broken(), io.BytesIO())
        with self.assertRaises(WireError) as caught:
            wire.send_json({})
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(wire.receive_json())

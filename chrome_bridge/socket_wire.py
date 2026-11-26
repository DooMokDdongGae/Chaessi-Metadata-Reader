"""Server-side RFC 6455 text frames for small local bridge control messages."""
import base64
import binascii
import hashlib
import json
import re
import socket
import threading


MAX_MESSAGE = 4096
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


class WireError(Exception):
    code = "websocket"

    def __init__(self, close_code=1002):
        super().__init__(self.code)
        self.close_code = close_code


def upgrade_accept(headers):
    """Validate the WebSocket upgrade fields. The caller checks origin and access."""
    def single(name):
        values = headers.get_all(name, [])
        if len(values) != 1:
            raise WireError()
        return values[0].strip(" \t")

    connection = [word.strip(" \t").lower() for word in single("Connection").split(",")]
    if (single("Upgrade").lower() != "websocket" or "upgrade" not in connection
            or not all(_TOKEN.fullmatch(word) for word in connection)
            or single("Sec-WebSocket-Version") != "13"):
        raise WireError()
    key = single("Sec-WebSocket-Key")
    if len(key) != 24:
        raise WireError()
    try:
        nonce = base64.b64decode(key, validate=True)
    except (ValueError, binascii.Error):
        nonce = b""
    if len(nonce) != 16 or base64.b64encode(nonce).decode("ascii") != key:
        raise WireError()
    digest = hashlib.sha1(key.encode("ascii") + _GUID, usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("ascii")


def _object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise WireError(1007)
    return obj


def _invalid_number(_):
    raise WireError(1007)


def _parse_message(data):
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_invalid_number)
    except (ValueError, RecursionError):
        obj = None
    if not isinstance(obj, dict):
        raise WireError(1007)
    return obj


def _close_reply(payload):
    if not payload:
        return b""
    if len(payload) < 2:
        raise WireError()
    code = int.from_bytes(payload[:2], "big")
    if not (1000 <= code <= 1003 or 1007 <= code <= 1014 or 3000 <= code <= 4999):
        raise WireError()
    try:
        payload[2:].decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        # A server never sends client-only 1010. A reason is optional.
        return b"" if code == 1010 else payload[:2]
    raise WireError(1007)


class SocketWire:
    """One reader and serialized writers. The HTTP handler owns the buffered reader."""
    def __init__(self, connection, reader):
        self._connection = connection
        self._reader = reader
        self._write_lock = threading.Lock()
        self._closed = threading.Event()

    def close(self):
        # Do not wait for the write lock. shutdown must also interrupt a blocked writer.
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._connection.close()
        except OSError:
            pass

    def _send_frame(self, opcode, payload):
        length = len(payload)
        size = bytes([length]) if length < 126 else b"\x7e" + length.to_bytes(2, "big")
        frame = bytes([0x80 | opcode]) + size + payload
        with self._write_lock:
            if self._closed.is_set():
                raise WireError()
            try:
                self._connection.sendall(frame)
            except OSError:
                self.close()
            else:
                if opcode == 8:
                    self.close()
                return
        raise WireError()

    def send_json(self, obj):
        if not isinstance(obj, dict):
            raise WireError()
        try:
            payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            payload = None
        if payload is None:
            raise WireError(1007)
        if len(payload) > MAX_MESSAGE:
            raise WireError(1009)
        self._send_frame(1, payload)

    def _read_exact(self, size, allow_eof=False):
        data = bytearray()
        while len(data) < size:
            chunk = self._reader.read(size - len(data))
            if not chunk:
                if allow_eof and not data:
                    return None
                raise WireError()
            data.extend(chunk)
        return data

    def _frame(self, remaining, fragmented):
        header = self._read_exact(2, allow_eof=not fragmented)
        if header is None:
            return None
        flags, size = header
        final, opcode, length = bool(flags & 0x80), flags & 0x0f, size & 0x7f
        if flags & 0x70 or not size & 0x80 or opcode not in (0, 1, 8, 9, 10):
            raise WireError(1003 if opcode == 2 else 1002)
        if opcode >= 8 and (not final or length > 125):
            raise WireError()
        if opcode < 8 and (opcode == 0) != fragmented:
            raise WireError()
        if length >= 126:
            width = 2 if length == 126 else 8
            length = int.from_bytes(self._read_exact(width), "big")
            if length < (126 if width == 2 else 65536) or length >= 1 << 63:
                raise WireError()
        if opcode < 8 and length > remaining:
            raise WireError(1009)
        mask = self._read_exact(4)
        payload = self._read_exact(length)
        for i in range(length):
            payload[i] ^= mask[i % 4]
        return final, opcode, payload

    def receive_json(self):
        if self._closed.is_set():
            return None
        data = bytearray()
        fragments = controls = 0
        try:
            while True:
                frame = self._frame(MAX_MESSAGE - len(data), fragments != 0)
                if frame is None:
                    self.close()
                    return None
                final, opcode, payload = frame
                if opcode == 8:
                    self._send_frame(8, _close_reply(payload))
                    return None
                if opcode in (9, 10):
                    controls += 1
                    if controls > 128:
                        raise WireError(1008)
                    if opcode == 9:
                        self._send_frame(10, payload)
                    continue
                data.extend(payload)
                if final:
                    return _parse_message(data)
                fragments += 1
                # Bound empty fragments as well as the total number of data bytes.
                if fragments > MAX_MESSAGE:
                    raise WireError(1008)
        except WireError as error:
            if not self._closed.is_set():
                try:
                    self._send_frame(8, error.close_code.to_bytes(2, "big"))
                except WireError:
                    pass
            self.close()
            raise
        except (OSError, ValueError):
            # Buffered socket readers cannot safely resume after a timeout.
            if self._closed.is_set():
                return None
            self.close()
        raise WireError()

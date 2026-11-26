"""Authenticated, user-initiated communication with a PRIVATE Preset instance."""
import hashlib
import hmac
import http.client
import json
import re
import secrets
import uuid
from contextlib import closing, nullcontext
from dataclasses import dataclass, field, replace

from bundle.model import UNREPRESENTABLE

PROTOCOL = "chaessi.prompt-transfer/1"
MAX_BODY = 1024 * 1024
MAX_TEXT = 256 * 1024
MAX_ITEMS = 128
STATES = {"pending", "applied", "cancelled", "stale", "expired", "failed"}
ERRORS = {
    "INVALID": "전송 형식 또는 목적지를 확인하세요.",
    "UNAUTHORIZED": "프리셋 인스턴스 인증에 실패했습니다.",
    "NOT_FOUND": "프리셋에서 이 요청을 찾지 못했습니다.",
    "BUSY": "프리셋에서 다른 미리보기를 처리 중입니다.",
    "STALE": "프리셋 초안이 변경됐습니다. 대상을 새로고침하고 다시 지정하세요.",
    "ID_CONFLICT": "같은 요청 번호에 다른 내용이 등록돼 있습니다.",
    "NOT_READY": "프리셋이 아직 준비되지 않았습니다.",
    "TOO_LARGE": "전송할 문구가 허용 크기를 초과합니다.",
    "TIMEOUT": "프리셋 요청 시간이 만료됐습니다.",
}


class TransferError(ValueError):
    def __init__(self, message, *, code=None, delivery_possible=True):
        super().__init__(message)
        self.code = code
        self.delivery_possible = delivery_possible


@dataclass(frozen=True)
class Endpoint:
    instance_id: str
    port: int
    secret: bytes = field(repr=False)
    pid: int
    exe: str = ""
    sha256: str = ""
    created: int = 0
    protocol: str = PROTOCOL
    compatibility: str = "unverified"
    hwnd: int | None = None
    transport_guard: object = field(default=None, compare=False, repr=False)
    liveness_check: object = field(default=None, compare=False, repr=False)


def canonical_id(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _json_bytes(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def make_preview(revision, items):
    if not isinstance(revision, str) or not revision or not 1 <= len(items) <= MAX_ITEMS:
        raise TransferError("현재 초안의 항목 1~128개를 선택하세요.")
    for item in items:
        text = item.get("text")
        if not isinstance(text, str):
            raise TransferError("문구가 없는 항목입니다.")
        if "\r" in text:
            raise TransferError("CR 또는 CRLF를 프리셋에 그대로 표시할 수 없습니다. 편집창에서 해당 줄바꿈을 바꾼 뒤 다시 담으세요.")
        if UNREPRESENTABLE.search(text) or re.search(r"[\x01-\x08\x0b-\x1f]", text):
            raise TransferError("표시할 수 없는 문자가 있습니다. 편집 후 다시 담으세요.")
        if len(text.encode("utf-8")) > MAX_TEXT:
            raise TransferError("항목 하나의 문구는 UTF-8 256 KiB까지 전송할 수 있습니다.")
    request_id = str(uuid.uuid4())
    body = _json_bytes({"requestId": request_id, "revision": revision, "items": items})
    if len(body) > MAX_BODY:
        raise TransferError("한 번에 전송할 수 있는 크기는 UTF-8 JSON 1 MiB입니다.")
    return request_id, body


def _mac(endpoint, prefix, nonce, body):
    digest = hashlib.sha256(body).hexdigest()
    return hmac.new(endpoint.secret, f"{prefix}\n{endpoint.instance_id}\n{nonce}\n{digest}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _request(conn, endpoint, path, body):
    nonce = secrets.token_hex(16)
    conn.request("POST", path, body=body, headers={
        "Content-Type": "application/json", "X-Chaessi-Instance": endpoint.instance_id,
        "X-Chaessi-Nonce": nonce, "X-Chaessi-Mac": _mac(endpoint, f"POST\n{path}", nonce, body)})
    res = conn.getresponse()
    content = res.read(MAX_BODY + 1)
    signature = res.getheader("X-Chaessi-Mac", "")
    if (len(content) > MAX_BODY or not re.fullmatch("[0-9a-f]{64}", signature)
            or not hmac.compare_digest(signature, _mac(endpoint, f"RES\n{res.status}", nonce, content))):
        raise TransferError("프리셋 응답 서명을 확인할 수 없습니다.")
    data = json.loads(content.decode("utf-8"))
    if not isinstance(data, dict):
        raise TransferError("프리셋 응답 형식이 올바르지 않습니다.")
    if res.status != 200 or data.get("ok") is not True:
        code = data.get("error")
        if not isinstance(code, str) or code not in ERRORS:
            raise TransferError("프리셋이 요청을 거부했습니다.")
        raise TransferError(ERRORS[code], code=code)
    return data


def _on_connection(endpoint, verify_process, path, body, timeout, *, discovery=False):
    from bundle.transfer_registry import verify_socket_owner

    submitted = False
    try:
        if path != "/v1/probe" and endpoint.compatibility != "compatible":
            raise TransferError("프리셋 인스턴스 인증에 실패했습니다.")
        with closing(http.client.HTTPConnection("127.0.0.1", endpoint.port, timeout=timeout)) as conn:
            conn.connect()
            conn.auto_open = False
            sock = conn.sock
            verify_process()
            verify_socket_owner(sock, endpoint)
            identity = _request(conn, endpoint, "/v1/probe", b"{}")
            version = identity.get("protocol")
            if (not isinstance(version, str) or not 0 < len(version) <= 128
                    or version != endpoint.protocol or (not discovery and version != PROTOCOL)
                    or identity.get("instanceId") != endpoint.instance_id
                    or type(identity.get("pid")) is not int or identity["pid"] != endpoint.pid):
                raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
            verify_process()
            if path == "/v1/probe":
                return identity
            if sock is None or conn.sock is not sock or sock.fileno() < 0:
                raise TransferError("인증한 연결이 종료됐습니다.")
            verify_socket_owner(sock, endpoint)
            submitted = path == "/v1/preview"
            return _request(conn, endpoint, path, body)
    except TransferError as exc:
        exc.delivery_possible = submitted
        raise
    except (OSError, http.client.HTTPException, ValueError, RecursionError, OverflowError):
        raise TransferError("프리셋 연결 또는 응답을 확인할 수 없습니다.", delivery_possible=submitted) from None


def identify_registration(endpoint, deadline, *, guard_factory=None):
    """Only an authenticated protocol declaration can establish incompatibility."""
    from bundle.transfer_registry import registered_process, remaining_time

    with registered_process(endpoint, discovering=True, deadline=deadline) as (observed, verify):
        timeout = min(3, remaining_time(deadline))
        try:
            guard = guard_factory(observed) if guard_factory is not None else nullcontext()
            with guard as verify_package:
                def verify_all():
                    verify()
                    if verify_package is not None:
                        verify_package()
                identity = _on_connection(observed, verify_all, "/v1/probe", b"{}", timeout, discovery=True)
        except TransferError as exc:
            if guard_factory is not None and exc.code in {
                    "preset.runtime_mismatch", "preset.signature_invalid", "preset.signature_expired",
                    "preset.signature_revoked", "preset.signature_rollback", "preset.changed"}:
                raise
            verify()  # Omit a dead process rather than presenting it as an unverified running app.
            return observed
        state = "compatible" if identity["protocol"] == PROTOCOL else "unsupported"
        return replace(observed, compatibility=state)


def _exchange(endpoint, path, body, timeout=3):
    from bundle.transfer_registry import registered_process

    pinned_process = False
    response_returned = False
    try:
        guard = endpoint.transport_guard() if endpoint.transport_guard is not None else nullcontext()
        with guard as verify_package, registered_process(endpoint) as (pinned, verify):
            pinned_process = True
            def verify_all():
                verify()
                if verify_package is not None:
                    verify_package()
            result = _on_connection(pinned, verify_all, path, body, timeout)
            response_returned = True
        return result
    except TransferError as exc:
        if not pinned_process:
            exc.delivery_possible = False
        elif response_returned and path == "/v1/preview":
            exc.delivery_possible = True
        raise
    except OSError:
        raise TransferError("프리셋 연결 또는 응답을 확인할 수 없습니다.",
                            delivery_possible=response_returned and path == "/v1/preview") from None


def probe(endpoint, *, timeout=3):
    return _exchange(endpoint, "/v1/probe", b"{}", timeout)


def targets(endpoint):
    data = _exchange(endpoint, "/v1/targets", b"{}")
    limit, count, rows = data.get("limit"), data.get("canCreate"), data.get("targets")
    if (data.get("instanceId") != endpoint.instance_id
            or not isinstance(data.get("revision"), str) or not data["revision"]
            or type(limit) is not int or type(count) is not int or not 0 <= count <= limit <= 1024
            or not isinstance(rows, list) or not 1 <= len(rows) <= limit + 1):
        raise TransferError("현재 프리셋의 슬롯 목록을 확인할 수 없습니다.")
    seen, numbers = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise TransferError("목적지 형식이 올바르지 않습니다.")
        slot, number, fields = row.get("slot"), row.get("number"), row.get("fields")
        if (not isinstance(slot, str) or not slot or slot.startswith("new:") or slot in seen
                or type(number) is not int or not 0 <= number <= limit or number in numbers
                or (number == 0) != (slot == "base")
                or not isinstance(fields, list) or len(fields) > 2 or
                any(f not in ("positive", "undesired") for f in fields) or len(set(fields)) != len(fields)):
            raise TransferError("슬롯 번호나 사용 가능한 필드를 확인할 수 없습니다.")
        seen.add(slot)
        numbers.add(number)
    if "base" not in seen:
        raise TransferError("Base 목적지가 없습니다.")
    return data


def _state(data, request_id):
    state = data.get("state")
    if data.get("requestId") != request_id or not isinstance(state, str) or state not in STATES:
        raise TransferError("전송 요청의 상태를 확인할 수 없습니다.")
    return state


def preview(endpoint, body):
    request_id = json.loads(body)["requestId"]
    return _state(_exchange(endpoint, "/v1/preview", body), request_id)


def status(endpoint, request_id):
    return _state(_exchange(endpoint, "/v1/status", _json_bytes({"requestId": request_id})), request_id)

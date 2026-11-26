"""Bind private local registrations to the selected running Windows executable.

The image is identified by its local path and on-disk SHA-256. A process handle
and its creation time distinguish PID reuse. The owner PID of the receiver end
of each established connection is checked before the signed probe and request.
Preset v1 identifies a receiver by instance ID and PID; an available HWND is
also checked against that PID. These checks do not attest loaded DLLs, Electron
resources, the process's live memory, or another process with the user's rights.
"""
import ctypes
import hashlib
import json
import os
from contextlib import contextmanager, ExitStack, nullcontext
from ctypes import wintypes as w
from dataclasses import replace
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time

from bundle.transfer_client import Endpoint, PROTOCOL, TransferError, canonical_id, identify_registration, probe

EXE = "Chaessi Preset Transfer PRIVATE.exe"
P = ctypes.c_void_p
READ_CONTROL = 0x20000


def _api(dll, name, restype, *args):
    func = getattr(dll, name)
    func.argtypes = args
    func.restype = restype
    return func


class WindowsSecurity:
    def __init__(self):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        self.open = _api(k, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD, P, w.DWORD, w.DWORD, P)
        self.close = _api(k, "CloseHandle", w.BOOL, w.HANDLE)
        self.free = _api(k, "LocalFree", P, P)
        self.info = _api(k, "GetFileInformationByHandleEx", w.BOOL, w.HANDLE, ctypes.c_int, P, w.DWORD)
        self.security = _api(a, "GetSecurityInfo", w.DWORD, w.HANDLE, ctypes.c_int, w.DWORD, P, P, P, P, P)
        self.sid_text = _api(a, "ConvertSidToStringSidW", w.BOOL, P, P)
        self.ace = _api(a, "GetAce", w.BOOL, P, w.DWORD, P)
        self.drive_type = _api(k, "GetDriveTypeW", w.UINT, w.LPCWSTR)
        token = w.HANDLE()
        open_token = _api(a, "OpenProcessToken", w.BOOL, w.HANDLE, w.DWORD, P)
        token_info = _api(a, "GetTokenInformation", w.BOOL, w.HANDLE, ctypes.c_int, P, w.DWORD, P)
        if not open_token(w.HANDLE(-1), 8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            n = w.DWORD()
            token_info(token, 1, None, 0, ctypes.byref(n))
            data = ctypes.create_string_buffer(n.value)
            if not token_info(token, 1, data, n.value, ctypes.byref(n)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.trusted = {self.sid(P.from_buffer(data).value), "S-1-5-18", "S-1-5-32-544"}
        finally:
            self.close(token)

    def sid(self, pointer):
        out = P()
        if not self.sid_text(pointer, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.wstring_at(out)
        finally:
            self.free(out)

    def check_acl(self, handle):
        owner, acl, descriptor = P(), P(), P()
        err = self.security(handle, 1, 5, ctypes.byref(owner), None, ctypes.byref(acl), None,
                            ctypes.byref(descriptor))
        if err:
            raise ctypes.WinError(err)
        try:
            if not acl.value or self.sid(owner) not in self.trusted:
                raise TransferError("등록 경로의 소유자 또는 접근 권한을 확인하세요.")
            count = ctypes.c_ushort.from_address(acl.value + 4).value
            for index in range(count):
                ace = P()
                if not self.ace(acl, index, ctypes.byref(ace)):
                    raise ctypes.WinError(ctypes.get_last_error())
                kind = ctypes.c_ubyte.from_address(ace.value).value
                if kind == 1:  # ACCESS_DENIED_ACE adds no access.
                    continue
                if kind != 0 or self.sid(ace.value + 8) not in self.trusted:
                    raise TransferError("개인 전송 등록 경로에 다른 계정의 접근 권한이 있습니다.")
        finally:
            self.free(descriptor)


def local_path(value):
    path = Path(value)
    if (not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive)
            or any(p in (".", "..") or ":" in p or p.endswith((" ", ".")) for p in path.parts[1:])):
        raise TransferError("이 PC의 절대 경로를 선택하세요.")
    return path


@contextmanager
def checked_handle(path, *, root=None, read=False, directory=False):
    """Pin each component against rename while validating and using the leaf."""
    path = local_path(path)
    if root is not None and not path.is_relative_to(local_path(root)):
        raise TransferError("등록 경로를 확인하세요.")
    api = WindowsSecurity()
    if api.drive_type(path.anchor) not in (2, 3, 6):
        raise TransferError("로컬 드라이브에서만 프리셋을 연결할 수 있습니다.")
    with ExitStack() as stack:
        for component in (*reversed(path.parents), path):
            leaf = component == path
            private = root is not None and component.is_relative_to(root)
            access = 0x80 | (READ_CONTROL if private else 0) | (0x80000000 if read and leaf else 0)
            # Share reading and writing on directories, reading only on the leaf file.
            handle = api.open(str(component), access, 1 if read and leaf else 3, None, 3, 0x02200000, None)
            if handle == P(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            stack.callback(api.close, handle)
            attrs = (w.DWORD * 2)()
            if not api.info(handle, 9, attrs, ctypes.sizeof(attrs)):
                raise ctypes.WinError(ctypes.get_last_error())
            if attrs[0] & 0x400 or bool(attrs[0] & 0x10) != (not leaf or directory):
                raise TransferError("연결 경로에 링크 또는 잘못된 파일 형식이 있습니다.")
            if private:
                api.check_acl(handle)
        yield path


def read_private_json(path, root):
    with checked_handle(path, root=root, read=True) as checked:
        return _read_json(checked)


def _read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise TransferError("프리셋 등록 파일이 너무 큽니다.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, RecursionError):
        raise TransferError("프리셋 등록 파일을 읽을 수 없습니다.") from None


def registry_dir():
    override = os.environ.get("CHAESSI_TRANSFER_REGISTRY")
    if override:
        return local_path(override)
    return local_path(Path(os.environ["LOCALAPPDATA"]) / "CHAESSI" / "PromptTransferPrivate" / "v1")


def _valid_hwnd(hwnd):
    return type(hwnd) is int and 0 < hwnd < 1 << (8 * ctypes.sizeof(P))


def _check_window(hwnd, pid):
    if hwnd is not None:
        if not _valid_hwnd(hwnd):
            raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
        owner = w.DWORD()
        window_pid = _api(ctypes.WinDLL("user32", use_last_error=True), "GetWindowThreadProcessId",
                          w.DWORD, w.HWND, P)
        if not window_pid(hwnd, ctypes.byref(owner)) or owner.value != pid:
            raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")


@contextmanager
def _process(pid, hwnd=None):
    """Hold a specific process object from path lookup until the exchange finishes."""
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        raise TransferError("프리셋 인스턴스 등록 정보가 올바르지 않습니다.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = _api(kernel, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
    close = _api(kernel, "CloseHandle", w.BOOL, w.HANDLE)
    wait = _api(kernel, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
    image = _api(kernel, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, P)
    times = _api(kernel, "GetProcessTimes", w.BOOL, w.HANDLE, P, P, P, P)
    handle = open_process(0x1000 | 0x100000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        length = w.DWORD(32768)
        name = ctypes.create_unicode_buffer(length.value)
        stamps = [w.FILETIME() for _ in range(4)]
        if (not image(handle, 0, name, ctypes.byref(length))
                or not times(handle, *(ctypes.byref(stamp) for stamp in stamps))):
            raise ctypes.WinError(ctypes.get_last_error())
        created = (stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime

        def verify():
            if wait(handle, 0) != 258:  # WAIT_TIMEOUT means this process object is still running.
                raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
            _check_window(hwnd, pid)

        verify()
        yield _exe_path(name.value), created, verify
    finally:
        close(handle)


def process_snapshot():
    """Read process names and creator PIDs without opening process data or profiles."""
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("default_heap", ctypes.c_size_t), ("module", w.DWORD),
                    ("threads", w.DWORD), ("parent", w.DWORD), ("priority", w.LONG),
                    ("flags", w.DWORD), ("name", w.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = _api(kernel, "CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
    first = _api(kernel, "Process32FirstW", w.BOOL, w.HANDLE, P)
    next_process = _api(kernel, "Process32NextW", w.BOOL, w.HANDLE, P)
    close = _api(kernel, "CloseHandle", w.BOOL, w.HANDLE)
    handle = create(2, 0)  # TH32CS_SNAPPROCESS
    if handle == P(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        row = ProcessEntry(size=ctypes.sizeof(ProcessEntry))
        rows = {}
        has_row = first(handle, ctypes.byref(row))
        while has_row:
            rows[row.pid] = (row.parent, row.name)
            has_row = next_process(handle, ctypes.byref(row))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return rows
    finally:
        close(handle)


class TcpOwnerRow(ctypes.Structure):
    _fields_ = [(name, w.DWORD) for name in ("state", "local_addr", "local_port",
                                             "remote_addr", "remote_port", "pid")]


def verify_socket_owner(sock, endpoint):
    """Look up the receiver half of this exact established IPv4 connection."""
    if sock is None or sock.getpeername() != ("127.0.0.1", endpoint.port):
        raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
    host, client_port = sock.getsockname()
    if host != "127.0.0.1":
        raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
    get_table = _api(ctypes.WinDLL("iphlpapi"), "GetExtendedTcpTable", w.DWORD,
                     P, P, w.BOOL, w.ULONG, ctypes.c_int, w.ULONG)
    size = w.DWORD()
    buffer = None
    for _ in range(4):
        result = get_table(buffer, ctypes.byref(size), False, socket.AF_INET, 4, 0)
        if result == 0 and buffer is not None:
            break
        if result != 122 or not 4 <= size.value <= 32 * 1024 * 1024:  # ERROR_INSUFFICIENT_BUFFER
            raise TransferError("프리셋 인스턴스 인증에 실패했습니다.")
        buffer = ctypes.create_string_buffer(size.value)
    else:
        raise TransferError("프리셋 인스턴스 인증에 실패했습니다.")
    count = w.DWORD.from_buffer(buffer).value
    header, row_size = ctypes.sizeof(w.DWORD), ctypes.sizeof(TcpOwnerRow)
    if count > (len(buffer) - header) // row_size:
        raise TransferError("프리셋 인스턴스 인증에 실패했습니다.")
    loopback = int.from_bytes(socket.inet_aton(host), "little")
    server_wire, client_wire = socket.htons(endpoint.port), socket.htons(client_port)
    for index in range(count):
        row = TcpOwnerRow.from_buffer(buffer, header + index * row_size)
        if (row.state == 5 and row.local_addr == row.remote_addr == loopback
                and (row.local_port & 0xffff) == server_wire and (row.remote_port & 0xffff) == client_wire):
            if row.pid == endpoint.pid:
                return
            break
    raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")


def _manifest(path, data):
    protocol, pid, port = data.get("protocol"), data.get("pid"), data.get("port")
    secret, hwnd = data.get("secret"), data.get("hwnd")
    if (not isinstance(protocol, str) or not 0 < len(protocol) <= 128 or data.get("instanceId") != path.stem
            or type(pid) is not int or not 0 < pid <= 0xffffffff
            or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(secret, str) or not re.fullmatch("[0-9a-f]{64}", secret)
            or (hwnd is not None and not _valid_hwnd(hwnd))):
        raise TransferError("프리셋 인스턴스 등록 정보가 올바르지 않습니다.")
    return Endpoint(path.stem, port, bytes.fromhex(secret), pid, protocol=protocol, hwnd=hwnd)


@contextmanager
def registered_process(endpoint, *, discovering=False, deadline=None):
    """Pin the manifest, its directories, the process and on-disk EXE through the exchange."""
    if (not canonical_id(endpoint.instance_id) or (not discovering and
            (not endpoint.created or not endpoint.exe or not re.fullmatch("[0-9a-f]{64}", endpoint.sha256)))):
        raise TransferError("프리셋 인스턴스 인증에 실패했습니다.", delivery_possible=False)
    root = registry_dir()
    manifest = root / "instances" / (endpoint.instance_id + ".json")
    with checked_handle(manifest, root=root, read=True) as path:
        current = _manifest(path, _read_json(path))
        if ((current.pid, current.port, current.protocol, current.secret)
                != (endpoint.pid, endpoint.port, endpoint.protocol, endpoint.secret)
                or (current.hwnd is not None and current.hwnd != endpoint.hwnd)):
            raise TransferError("프리셋 인스턴스 인증에 실패했습니다.", delivery_possible=False)
        with _process(endpoint.pid, endpoint.hwnd) as (process_exe, created, verify):
            if not discovering and (created != endpoint.created or process_exe != _exe_path(endpoint.exe)):
                raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.", delivery_possible=False)
            with checked_handle(process_exe, read=True) as pinned:
                digest = _digest(pinned, deadline=deadline)
                if discovering:
                    endpoint = replace(endpoint, exe=str(pinned), created=created, sha256=digest,
                                       compatibility="unverified")
                elif not pinned.samefile(endpoint.exe) or digest != endpoint.sha256:
                    raise TransferError("선택한 PRIVATE 실행 파일이 변경됐습니다. 다시 선택하세요.", delivery_possible=False)
                yield endpoint, verify


def attest(endpoint, *, path=None, sha256=None, hwnd=None):
    """Reauthenticate the selected process, optionally against an explicit library record or window."""
    selected = _exe_path(path) if path is not None else None
    if selected is not None and selected != Path(endpoint.exe):
        raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
    if sha256 is not None and sha256 != endpoint.sha256:
        raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
    if hwnd is not None:
        if endpoint.hwnd is not None and hwnd != endpoint.hwnd:
            raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
        endpoint = replace(endpoint, hwnd=hwnd)
    selected_file = checked_handle(selected, read=True) if selected is not None else nullcontext()
    try:
        with selected_file as pinned:
            # A Windows directory can be case-sensitive even when pathlib compares its names as equal.
            if pinned is not None and not pinned.samefile(endpoint.exe):
                raise TransferError("선택한 프리셋과 응답한 인스턴스가 다릅니다.")
            probe(endpoint)
    except OSError:
        raise TransferError("선택한 PRIVATE 실행 파일이 변경됐습니다. 다시 선택하세요.",
                            delivery_possible=False) from None
    return replace(endpoint, compatibility="compatible")


def remaining_time(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransferError("시간 안에 등록된 인스턴스를 모두 확인할 수 없습니다. 다시 연결하세요.",
                            code="TIMEOUT", delivery_possible=False)
    return remaining


def discover_instances(deadline=None, *, pid=None, pids=None, guard_factory=None):
    if deadline is None:
        deadline = time.monotonic() + 30
    root = registry_dir()
    folder = root / "instances"
    try:
        with checked_handle(folder, root=root, directory=True):
            names = list(folder.glob("*.json"))
    except FileNotFoundError:
        return []
    if len(names) > 128:
        raise TransferError("등록된 프리셋 인스턴스가 너무 많습니다.")
    candidates = []
    for path in names:
        remaining_time(deadline)
        if not canonical_id(path.stem):
            continue
        try:
            endpoint = _manifest(path, read_private_json(path, root))
            if ((pid is None or endpoint.pid == pid) and
                    (pids is None or endpoint.pid in pids)):
                candidates.append(identify_registration(endpoint, deadline, guard_factory=guard_factory)
                                  if guard_factory else identify_registration(endpoint, deadline))
        except (OSError, TransferError) as exc:
            if guard_factory is not None and isinstance(exc, TransferError) and exc.code in {
                    "preset.runtime_mismatch", "preset.signature_invalid", "preset.signature_expired",
                    "preset.signature_revoked", "preset.signature_rollback", "preset.changed"}:
                raise
            # Dead/stale registrations and records whose private identity cannot be read
            # are never eligible as targets.
            remaining_time(deadline)
    remaining_time(deadline)
    return candidates


def discover(deadline=None):
    return [endpoint for endpoint in discover_instances(deadline) if endpoint.compatibility == "compatible"]


def _exe_path(value):
    path = local_path(value)
    if path.suffix.lower() != ".exe":
        raise TransferError("이 PC의 EXE 파일을 선택하세요.")
    return path


def launcher_hash(path):
    with checked_handle(_exe_path(path), read=True) as exe:
        return _digest(exe)


def _digest(exe, *, deadline=None):
    with exe.open("rb") as handle:
        digest = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            if deadline is not None:
                remaining_time(deadline)
            digest.update(block)
        return digest.hexdigest()


def registered_launcher():
    root = registry_dir()
    try:
        info = read_private_json(root / "launcher.json", root)
    except FileNotFoundError:
        return None
    if info.get("protocol") != PROTOCOL or not isinstance(info.get("exe"), str):
        return None
    path = _exe_path(info["exe"])
    try:
        digest = launcher_hash(path)
    except FileNotFoundError:
        return None
    if digest != info.get("sha256"):
        return None
    try:
        prior = read_private_json(root / "reader-launcher.json", root)
    except FileNotFoundError:
        prior = None
    if prior is None or prior.get("exe") != str(path) or prior.get("sha256") != digest:
        return None
    return path, digest


def remember_launcher(path, digest):
    root = registry_dir()
    with checked_handle(root, root=root, directory=True):
        data = json.dumps(dict(exe=str(path), sha256=digest), ensure_ascii=False).encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=root, prefix="reader-launcher-", delete=False) as out:
            out.write(data)
        os.replace(out.name, root / "reader-launcher.json")


def launch(path, expected, *, confirmed=False):
    """Launch only the caller's explicitly confirmed local path and exact selected digest."""
    if confirmed is not True:
        raise TransferError("실행 파일을 확인한 뒤 실행을 승인하세요.")
    path = _exe_path(path)
    with checked_handle(path, read=True) as exe:
        if _digest(exe) != expected:
            raise TransferError("선택한 PRIVATE 실행 파일이 변경됐습니다. 다시 선택하세요.")
        return subprocess.Popen([str(exe)], executable=str(exe), cwd=exe.parent, shell=False, close_fds=True)

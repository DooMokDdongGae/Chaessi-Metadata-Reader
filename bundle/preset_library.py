"""Local EXE identities and the reader's protected, per-user registration list."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import uuid

from bundle import transfer_registry as registry
from bundle.transfer_client import TransferError, canonical_id


KNOWN_PRIVATE = "09483b2f0e175548c11a3ca2fcd6d378952827803d94ffbe80bf0b71ecb100c4"
MAX_CONFIG = 1024 * 1024
STATUS = ("unknown", "compatible", "unsupported")
DIGEST = re.compile("[0-9a-f]{64}")
BRAND = re.compile(r"^(?:chaessi[ _-]*preset|채씨[ _-]*프리셋)(?:$|[\s._(-])", re.IGNORECASE)


class LibraryError(TransferError):
    def __init__(self, code):
        super().__init__(code, code=code)


@dataclass(frozen=True)
class ExeInfo:
    path: Path
    digest: str
    version: str | None = None
    build: str | None = None
    product: str | None = None

    @property
    def recognized(self):
        return self.digest == KNOWN_PRIVATE or bool(self.product and BRAND.match(self.product))


@dataclass(frozen=True)
class PresetRecord(ExeInfo):
    id: str = ""
    name: str = ""
    last_compat: str = "unknown"


@dataclass(frozen=True)
class LibraryState:
    records: tuple[PresetRecord, ...] = ()
    last_selected: str | None = None

    def by_id(self, record_id):
        for record in self.records:
            if record.id == record_id:
                return record
        raise LibraryError("LIBRARY_MISSING")


def _text(value, max_length=256):
    return (isinstance(value, str) and 0 < len(value) <= max_length and bool(value.strip())
            and all(ch.isprintable() for ch in value))


def _default_name(path, product=None):
    if _text(product):
        return product
    # Windows allows format characters in filenames. Keep the exact path and
    # derive only a printable, editable display label from it.
    name = ''.join(ch for ch in path.stem if ch.isprintable()).strip()
    return name[:256] or 'Preset'


def _exe(path):
    path = registry.local_path(path)
    if path.suffix.casefold() != ".exe":
        raise LibraryError("NOT_EXE")
    return path


def _require_pe(path):
    with path.open("rb") as source:
        dos = source.read(64)
        if len(dos) != 64 or dos[:2] != b"MZ":
            raise LibraryError("NOT_EXE")
        offset = int.from_bytes(dos[60:64], "little")
        if offset < 64:
            raise LibraryError("NOT_EXE")
        source.seek(offset)
        coff = source.read(24)
        if len(coff) != 24 or coff[:4] != b"PE\0\0":
            raise LibraryError("NOT_EXE")
        size, flags = struct.unpack_from("<HH", coff, 20)
        optional = source.read(size)
        if (not flags & 2 or flags & 0x2000 or len(optional) != size or size < 96
                or optional[:2] not in (b"\x0b\x01", b"\x0b\x02")):
            raise LibraryError("NOT_EXE")


def _version_info(path):
    """Read VERSIONINFO as data, using the resource's own language/codepage table."""
    api = ctypes.WinDLL("version", use_last_error=True)
    ptr = ctypes.c_void_p
    size_fn = registry._api(api, "GetFileVersionInfoSizeExW", wintypes.DWORD,
                            wintypes.DWORD, wintypes.LPCWSTR, ptr)
    read_fn = registry._api(api, "GetFileVersionInfoExW", wintypes.BOOL,
                            wintypes.DWORD, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ptr)
    query_fn = registry._api(api, "VerQueryValueW", wintypes.BOOL, ptr, wintypes.LPCWSTR, ptr, ptr)
    size = size_fn(0, str(path), None)
    if not 0 < size <= 4 * 1024 * 1024:
        return None, None, None
    data = ctypes.create_string_buffer(size)
    if not read_fn(0, str(path), 0, size, data):
        return None, None, None

    def query(key):
        address, length = ptr(), wintypes.UINT()
        if not query_fn(data, key, ctypes.byref(address), ctypes.byref(length)):
            return 0, 0
        return address.value, length.value

    address, length = query(r"\VarFileInfo\Translation")
    languages = ctypes.string_at(address, length) if address and length % 4 == 0 else b""
    words = {}
    for lang, page in struct.iter_unpack("<HH", languages):
        for name in ("ProductName", "ProductVersion", "FileVersion"):
            if name in words:
                continue
            address, n = query(fr"\StringFileInfo\{lang:04x}{page:04x}\{name}")
            if address and 0 < n <= 257:
                value = ctypes.wstring_at(address, n).rstrip("\0").strip()
                if _text(value):
                    words[name] = value
    version = words.get("ProductVersion") or words.get("FileVersion")
    if not version:
        address, length = query("\\")
        if address and length >= 52:
            fields = struct.unpack("<13I", ctypes.string_at(address, 52))
            if fields[0] == 0xFEEF04BD:
                ms, ls = fields[4:6] if any(fields[4:6]) else fields[2:4]
                version = f"{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}"
    product = words.get("ProductName")
    build = None
    if product and BRAND.match(product):
        marker = re.search(r"\b(PRIVATE|PUBLIC)\b", product, re.IGNORECASE)
        build = marker[1].upper() if marker else None
    return version, build, product


def inspect_exe(path):
    with registry.checked_handle(_exe(path), read=True) as checked:
        _require_pe(checked)
        version, build, product = _version_info(checked)
        return ExeInfo(checked, registry.launcher_hash(checked), version, build, product)


def file_presence(record):
    """Check the local file's accessibility for listing, without reading its contents."""
    try:
        with registry.checked_handle(_exe(record.path), read=True):
            return "ready"
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError):
        return "unavailable"


def file_state(record):
    try:
        actual = registry.launcher_hash(_exe(record.path))
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError):
        return "unavailable"
    return "ready" if actual == record.digest else "changed"


@contextmanager
def _store_lock(directory):
    # Multiple reader processes may update separate entries in the same document.
    name = "Local\\Chaessi.ReaderLibrary." + hashlib.sha256(
        os.path.normcase(str(directory)).encode("utf-8")).hexdigest()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = registry._api(kernel, "CreateMutexW", wintypes.HANDLE, ctypes.c_void_p,
                           wintypes.BOOL, wintypes.LPCWSTR)
    wait = registry._api(kernel, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
    release = registry._api(kernel, "ReleaseMutex", wintypes.BOOL, wintypes.HANDLE)
    close = registry._api(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    handle = create(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = wait(handle, 4000)
        if result not in (0, 0x80):  # Acquired, or acquired after the previous owner exited.
            raise LibraryError("LIBRARY_BUSY")
        try:
            yield
        finally:
            release(handle)
    finally:
        close(handle)


@contextmanager
def _private_attributes():
    """Protect a new object at creation, even if its parent has no inheritable ACEs."""
    security = registry.WindowsSecurity()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    ptr = ctypes.c_void_p

    class Attributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ptr), ("inherit", wintypes.BOOL)]

    convert = registry._api(advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                            wintypes.BOOL, wintypes.LPCWSTR, wintypes.DWORD, ptr, ptr)
    descriptor = ptr()
    sddl = "D:P" + "".join(f"(A;OICI;FA;;;{sid})" for sid in sorted(security.trusted))
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield Attributes(ctypes.sizeof(Attributes), descriptor.value, False)
    finally:
        security.free(descriptor)


def _make_directory(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = registry._api(kernel, "CreateDirectoryW", wintypes.BOOL, wintypes.LPCWSTR, ctypes.c_void_p)
    with _private_attributes() as attrs:
        if not create(str(path), ctypes.byref(attrs)):
            error = ctypes.get_last_error()
            if error != 183:
                raise ctypes.WinError(error)


def _open_private(path):
    import msvcrt

    security = registry.WindowsSecurity()
    with _private_attributes() as attrs:
        handle = security.open(str(path), 0x40000000, 0, ctypes.byref(attrs), 1, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except OSError:
        security.close(handle)
        raise
    return os.fdopen(fd, "wb")


class PresetLibrary:
    def __init__(self, root=None, legacy_root=None):
        explicit_root = root is not None
        if root is None:
            override = os.environ.get("CHAESSI_TRANSFER_REGISTRY")
            root = (Path(override) / "reader-library" if override else
                    Path(os.environ["LOCALAPPDATA"]) / "CHAESSI" / "MetadataReader" / "launchers")
        self.root = registry.local_path(root)
        self.path = self.root / "presets.json"
        self.default_path = self.root / "default-preset.json"
        # A caller injecting a test root must not consult the user's registration.
        self.legacy_root = (registry.local_path(legacy_root) if legacy_root is not None else
                            None if explicit_root else registry.registry_dir())

    def _ensure_root(self):
        for component in (*reversed(self.root.parents), self.root):
            if component.parent == component or component.exists():
                continue
            with registry.checked_handle(component.parent, directory=True):
                if component == self.root:
                    _make_directory(component)
                else:
                    component.mkdir(exist_ok=True)
        # The caller checks the private root, even when an existing directory was present.

    def _legacy(self):
        if self.legacy_root is None:
            return LibraryState()
        try:
            data = registry.read_private_json(self.legacy_root / "reader-launcher.json", self.legacy_root)
        except FileNotFoundError:
            return LibraryState()
        if not isinstance(data.get("exe"), str) or not DIGEST.fullmatch(str(data.get("sha256", ""))):
            raise LibraryError("LIBRARY_INVALID")
        path = _exe(data["exe"])
        # Preserve the user's old digest even when the file has disappeared or changed.
        record = PresetRecord(path, data["sha256"], id=str(uuid.uuid4()), name=_default_name(path))
        return LibraryState((record,), record.id)

    def _read(self, path=None, *, allow_legacy=True, migrate_legacy=True):
        path = self.path if path is None else path
        try:
            with registry.checked_handle(path, root=self.root, read=True) as checked, checked.open("rb") as stream:
                raw = stream.read(MAX_CONFIG + 1)
        except FileNotFoundError:
            previous = self._legacy() if allow_legacy else LibraryState()
            if previous.records and migrate_legacy:
                self._write(previous, path)
            return previous
        if len(raw) > MAX_CONFIG:
            raise LibraryError("LIBRARY_INVALID")
        try:
            data = json.loads(raw.decode("utf-8"))
            if (not isinstance(data, dict) or type(data.get("format")) is not int or data["format"] != 1
                    or not isinstance(data.get("records"), list)):
                raise LibraryError("LIBRARY_INVALID")
            records, ids, paths = [], set(), set()
            for row in data["records"]:
                record = PresetRecord(**{**row, "path": _exe(row["path"])})
                if (not canonical_id(record.id) or record.id in ids or record.path in paths
                        or not DIGEST.fullmatch(record.digest) or not _text(record.name)
                        or record.last_compat not in STATUS or record.build not in (None, "PUBLIC", "PRIVATE")
                        or any(value is not None and not _text(value) for value in (record.version, record.product))):
                    raise LibraryError("LIBRARY_INVALID")
                records.append(record)
                ids.add(record.id)
                paths.add(record.path)
            last = data["last_selected"]
            if last is not None and last not in ids:
                raise LibraryError("LIBRARY_INVALID")
            return LibraryState(tuple(records), last)
        except (KeyError, TypeError, ValueError, RecursionError):
            raise LibraryError("LIBRARY_INVALID") from None

    def _write(self, state, path=None):
        path = self.path if path is None else path
        rows = [{**asdict(r), "path": str(r.path)} for r in state.records]
        raw = json.dumps({"format": 1, "records": rows, "last_selected": state.last_selected},
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_CONFIG:
            raise LibraryError("LIBRARY_LIMIT")
        self._ensure_root()
        with registry.checked_handle(self.root, root=self.root, directory=True):
            temp = self.root / (".presets-" + uuid.uuid4().hex + ".tmp")
            output = _open_private(temp)
            try:
                with output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)

    def load(self):
        with _store_lock(self.root):
            return self._read()

    def load_default(self, eligible):
        """Read the single choice, or safely import one usable pin from the old list."""
        with _store_lock(self.root):
            saved = self._read(self.default_path, allow_legacy=False)
            if saved.records:
                if len(saved.records) != 1 or saved.records[0].id != saved.last_selected:
                    raise LibraryError("LIBRARY_INVALID")
                return saved.records[0]
            legacy = self._read(migrate_legacy=False)
            choices = [record for record in legacy.records if eligible(record)]
            preferred = next((record for record in choices if record.id == legacy.last_selected), None)
            if preferred is None and len(choices) == 1:
                preferred = choices[0]
            if preferred is not None:
                self._write(LibraryState((preferred,), preferred.id), self.default_path)
            return preferred

    def select_default(self, info):
        """Save only the explicitly chosen identity; keep the old registration list."""
        record = PresetRecord(info.path, info.digest, info.version, info.build, info.product,
                              str(uuid.uuid4()), _default_name(info.path, info.product))
        with _store_lock(self.root):
            # Validate an existing selection's owner and ACL before replacing it.
            self._read(self.default_path, allow_legacy=False)
            self._write(LibraryState((record,), record.id), self.default_path)
        return record

    def register(self, info, name=None, record_id=None, *, previous=None):
        path = _exe(info.path)
        if name is not None and not _text(name):
            raise LibraryError("LIBRARY_NAME")
        if (not isinstance(info.digest, str) or not DIGEST.fullmatch(info.digest)
                or info.build not in (None, "PRIVATE", "PUBLIC")
                or any(v is not None and not _text(v) for v in (info.version, info.product))):
            raise LibraryError("LIBRARY_INVALID")
        with _store_lock(self.root):
            state = self._read()
            at_path = next((r for r in state.records if r.path == path), None)
            old = state.by_id(record_id) if record_id is not None else at_path
            if previous is not None and (old is None or (old.id, old.path, old.digest) !=
                                         (previous.id, previous.path, previous.digest)):
                raise LibraryError("LIBRARY_CHANGED")
            if at_path and old != at_path:
                raise LibraryError("LIBRARY_DUPLICATE")
            same_file = old and old.path == path and old.digest == info.digest
            if old and not same_file and (record_id is None or previous is None):
                raise LibraryError("LIBRARY_CHANGED")
            record = PresetRecord(path, info.digest, info.version, info.build, info.product,
                                  old.id if old else str(uuid.uuid4()),
                                  name or (old.name if old else _default_name(path, info.product)),
                                  old.last_compat if same_file else "unknown")
            records = tuple(record if r.id == record.id else r for r in state.records)
            self._write(LibraryState(records if old else (*records, record), state.last_selected))
            return record

    def select(self, record_id):
        with _store_lock(self.root):
            state = self._read()
            record = state.by_id(record_id)
            self._write(replace(state, last_selected=record.id))
            return record

    def rename(self, record_id, name):
        if not _text(name):
            raise LibraryError("LIBRARY_NAME")
        with _store_lock(self.root):
            state = self._read()
            record = replace(state.by_id(record_id), name=name)
            self._update(state, record)
            return record

    def remove(self, record_id):
        with _store_lock(self.root):
            state = self._read()
            state.by_id(record_id)
            self._write(LibraryState(tuple(r for r in state.records if r.id != record_id),
                                     None if state.last_selected == record_id else state.last_selected))

    def _update(self, state, record, *, select=False):
        self._write(LibraryState(tuple(record if r.id == record.id else r for r in state.records),
                                 record.id if select else state.last_selected))

    def _result(self, record_id, path, digest, status, *, select=False):
        if status not in STATUS:
            raise LibraryError("LIBRARY_INVALID")
        with _store_lock(self.root):
            state = self._read()
            old = state.by_id(record_id)
            if old.digest != digest or (path is not None and old.path != _exe(path)):
                raise LibraryError("LIBRARY_CHANGED")
            record = replace(old, last_compat=status)
            self._update(state, record, select=select)
            return record

    def set_compat(self, record_id, digest, state, *, path=None):
        return self._result(record_id, path, digest, state)

    def connected(self, record_id, path, digest):
        return self._result(record_id, path, digest, "compatible", select=True)

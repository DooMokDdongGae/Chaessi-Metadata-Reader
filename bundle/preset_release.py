"""Strict signed release consumer. No signing private keys are included.

Ed25519 is delegated exclusively to cryptography's supported SDK. Metadata is
not a replacement for transfer/1 authentication or the caller's process/socket
binding. Hold ``pin_tree`` across that authentication and each exchange, then
call ``commit_authenticated`` only after the authenticated receiver matched.
"""
import base64
import binascii
import ctypes
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from bundle import transfer_registry as registry
from bundle import preset_library as library
from bundle import preset_trust
from bundle.transfer_client import TransferError


RELEASE_SCHEMA = "chaessi.preset.release/1"
KEYS_SCHEMA = "chaessi.preset.keys/1"
PROTOCOL = "chaessi.prompt-transfer/1"
MAX_JSON = 8 * 1024 * 1024
MAX_FILES = 50000
MAX_FILE_SIZE = 16 * 1024**3
MAX_TOTAL_SIZE = 128 * 1024**3
MAX_INTEGER = 2**53 - 1
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z")
DEVICES = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"} | {
    f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(10)}


class ReleaseError(TransferError):
    def __init__(self, code="SIGNATURE_INVALID"):
        super().__init__(code, code=code, delivery_possible=False)


def _fail(code="SIGNATURE_INVALID"):
    raise ReleaseError(code)


def canonical(data):
    """Contract bytes, also useful for the independent producer's vectors."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _printable(value, maximum=1024):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and all(32 <= ord(ch) <= 126 for ch in value))


def _integer(value, minimum=0, maximum=MAX_INTEGER):
    return type(value) is int and minimum <= value <= maximum


def _exact(data, keys):
    if not isinstance(data, dict) or set(data) != set(keys.split()):
        _fail()


def _json(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_JSON:
        _fail()
    def reject(_):
        _fail()
    try:
        data = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                          parse_float=reject, parse_constant=reject)
        def check(value, depth=0):
            if depth > 16:
                _fail()
            if isinstance(value, dict):
                for key, child in value.items():
                    if not _printable(key, 128):
                        _fail()
                    check(child, depth + 1)
            elif isinstance(value, list):
                if len(value) > MAX_FILES:
                    _fail()
                for child in value:
                    check(child, depth + 1)
            elif isinstance(value, str):
                if not _printable(value, 4096):
                    _fail()
            elif not _integer(value):
                _fail()
        check(data)
        if canonical(data) != raw:
            _fail()
        return data
    except (UnicodeError, ValueError, TypeError, RecursionError):
        _fail()


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        _fail()
    try:
        stamp = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        _fail()
    return stamp


def _now(now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None:
        _fail()
    return now.astimezone(timezone.utc)


def _window(start, end, now):
    start, end = _timestamp(start), _timestamp(end)
    if not start < end:
        _fail()
    if not start <= now < end:
        _fail("SIGNATURE_EXPIRED")
    return start, end


def _b64(raw, size):
    if isinstance(raw, str):
        try:
            raw = raw.encode("ascii")
        except UnicodeError:
            _fail()
    if not isinstance(raw, bytes):
        _fail()
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        _fail()
    if len(decoded) != size or base64.b64encode(decoded) != raw:
        _fail()
    return decoded


def _signature(raw):
    # Contract framing is exactly 88 ASCII Base64 bytes followed by one LF.
    # publicKey remains strict padded Base64 without a terminator.
    if not isinstance(raw, bytes) or len(raw) != 89 or raw[-1:] != b"\n":
        _fail()
    return _b64(raw[:-1], 64)


def _verify(public, signature, domain, raw):
    try:
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        _fail("SIGNATURE_SDK_UNAVAILABLE")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, domain.encode("ascii") + b"\0" + raw)
        return True
    except (InvalidSignature, ValueError):
        return False
    except UnsupportedAlgorithm:
        _fail("SIGNATURE_SDK_UNAVAILABLE")


def _path(value):
    if not _printable(value, 1024) or "\\" in value or any(ch in value for ch in ':<>"|?*'):
        _fail()
    parts = value.split("/")
    if any(not p or p in (".", "..") or p.endswith((" ", "."))
           or p.split(".")[0].rstrip(" .").upper() in DEVICES for p in parts):
        _fail()
    return value


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str


def _file(data):
    _exact(data, "path size sha256")
    if not _integer(data["size"], maximum=MAX_FILE_SIZE) or not DIGEST.fullmatch(str(data["sha256"])):
        _fail()
    return FileRecord(_path(data["path"]), data["size"], data["sha256"])


def _inventory(rows):
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_FILES:
        _fail()
    files = tuple(_file(row) for row in rows)
    names = [row.path for row in files]
    if names != sorted(names) or len(set(names)) != len(names):
        _fail()
    components = {}
    file_names = set()
    for row in files:
        parts = row.path.split("/")
        for index in range(1, len(parts) + 1):
            name = "/".join(parts[:index])
            prior = components.setdefault(name.casefold(), name)
            if prior != name:
                _fail()
            if index < len(parts) and name.casefold() in file_names:
                _fail()
        file_names.add(row.path.casefold())
    for name in components:
        parts = name.split("/")
        if any("/".join(parts[:i]) in file_names for i in range(1, len(parts))):
            _fail()
    if sum(row.size for row in files) > MAX_TOTAL_SIZE:
        _fail()
    return files


def _identity(data, schema):
    if (data["schema"] != schema or data["issuer"] != "chaessi-studio"
            or data["product"] != "chaessi-preset" or data["channel"] != preset_trust.CHANNEL
            or not _integer(data["sequence"], 1)):
        _fail()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class VerifiedRelease:
    launcher: Path | None
    launcher_file: FileRecord
    receiver: str
    files: tuple[FileRecord, ...]
    layout: str
    sequence: int
    keyset_sequence: int
    key_id: str
    root_key_id: str
    release_raw: bytes = field(repr=False)
    keyset_raw: bytes = field(repr=False)
    _store: object = field(default=None, repr=False, compare=False)

    @property
    def launcher_digest(self):
        return self.launcher_file.sha256

    @property
    def metadata(self):
        return json.loads(self.release_raw)

    @property
    def release_digest(self):
        return _digest(self.release_raw)

    @property
    def keyset_digest(self):
        return _digest(self.keyset_raw)

    @property
    def release_id(self):
        return self.metadata["releaseId"]

    @property
    def version(self):
        return self.metadata["version"]

    def receiver_path(self, runtime_root):
        return registry.local_path(runtime_root).joinpath(*self.receiver.split("/"))

    def assert_current(self, *, store=None, now=None):
        now = _now(now)
        release, keys = self.metadata, json.loads(self.keyset_raw)
        _window(release["issuedAt"], release["expiresAt"], now)
        _window(keys["issuedAt"], keys["expiresAt"], now)
        signer = next(row for row in keys["keys"] if row["keyId"] == self.key_id)
        _window(signer["notBefore"], signer["notAfter"], now)
        store = self._store if store is None else store
        if store is not None:
            store.check_release(self)

    def commit_authenticated(self, store=None, *, now=None):
        """Caller guarantees successful HMAC, pinned runtime, process and socket."""
        store = self._store if store is None else store
        if store is None:
            _fail("SIGNATURE_STORE_REQUIRED")
        self.assert_current(store=store, now=now)
        store.commit_release(self)

    @contextmanager
    def pin_tree(self, runtime_root, *, now=None):
        """Validate exact inventory while all parent, directory and file pins live.

        checked_handle denies file write/delete and directory rename. A second
        inventory scan rejects added files after pins were acquired. The caller
        receives a recheck closure to detect new names before/after exchange.
        """
        with ExitStack() as stack:
            try:
                self.assert_current(now=now)
                root = registry.local_path(runtime_root)
                stack.enter_context(registry.checked_handle(root, directory=True))
                security = registry.WindowsSecurity()
                launcher = self.launcher
                if launcher is not None:
                    stack.enter_context(registry.checked_handle(launcher, read=True))
                    _check_file(launcher, self.launcher_file)
                if self.layout == "unpacked" and (launcher is None or not launcher.samefile(
                        root.joinpath(*self.launcher_file.path.split("/")))):
                    _fail("RUNTIME_MISMATCH")
                expected = {row.path: row for row in self.files}
                # Unpacked external signature documents are not runtime payload.
                excluded = _sidecar_names(launcher, root) if self.layout == "unpacked" else set()
                # _scan pins each child directory before traversing it and
                # retains those pins in this tree's lifetime stack. Root and
                # ancestor handles above are already held; repeating that
                # entire chain and the token/SID API setup for every leaf adds
                # no protection.
                files, directories = _scan(root, excluded, security=security,
                                           pins=stack, root_pinned=True)
                if files != set(expected):
                    _fail("RUNTIME_MISMATCH")
                parents = {root} | {root.joinpath(*name.split("/")) for name in directories}
                for name, record in sorted(expected.items()):
                    path = root.joinpath(*name.split("/"))
                    stack.enter_context(_pin_child(path, security, parents=parents))
                    _check_file(path, record)
                def recheck():
                    try:
                        self.assert_current(now=now)
                        if _scan(root, excluded, security=security, root_pinned=True) != (files, directories):
                            _fail("RUNTIME_MISMATCH")
                    except ReleaseError:
                        raise
                    except (OSError, TransferError, ValueError):
                        _fail("RUNTIME_MISMATCH")
                recheck()
            except ReleaseError:
                raise
            except (OSError, TransferError, ValueError):
                _fail("RUNTIME_MISMATCH")
            # No exception translation around the caller's exchange. In
            # particular preserve TransferError.delivery_possible after a
            # possibly delivered preview, instead of converting it to a safe
            # retry/runtime mismatch and risking a second delivery.
            yield recheck
            recheck()


def validate_metadata(release_raw, release_sig, keyset_raw, keyset_sig, roots,
                      *, store=None, now=None, launcher=None):
    """Validate original canonical bytes. ``roots`` is embedded/caller trusted.

    A valid newer root-signed revocation policy is recorded even when the
    release it accompanies is rejected. Release highwater is never committed
    here; it requires the separate authenticated receiver step.
    """
    now = _now(now)
    keys = _json(keyset_raw)
    _exact(keys, "schema issuer product channel sequence issuedAt expiresAt keys revokedKeyIds")
    _identity(keys, KEYS_SCHEMA)
    _window(keys["issuedAt"], keys["expiresAt"], now)
    if not isinstance(roots, dict) or not 0 < len(roots) <= 16:
        _fail()
    root_signature = _signature(keyset_sig)
    root_id = None
    for key_id, public in roots.items():
        if not isinstance(public, bytes) or len(public) != 32 or key_id != _digest(public):
            _fail()
        if _verify(public, root_signature, KEYS_SCHEMA, keyset_raw):
            root_id = key_id
    if root_id is None:
        _fail()
    rows, revoked = keys["keys"], keys["revokedKeyIds"]
    if (not isinstance(rows, list) or not 0 < len(rows) <= 256
            or not isinstance(revoked, list) or len(revoked) > 4096
            or any(not isinstance(k, str) or not DIGEST.fullmatch(k) for k in revoked)
            or revoked != sorted(set(revoked))):
        _fail()
    signers = {}
    for row in rows:
        _exact(row, "keyId publicKey notBefore notAfter")
        public = _b64(row["publicKey"], 32)
        key_id = row["keyId"]
        if key_id != _digest(public) or key_id in signers:
            _fail()
        start, end = _timestamp(row["notBefore"]), _timestamp(row["notAfter"])
        if not start < end:
            _fail()
        signers[key_id] = (public, start, end)
    if list(signers) != sorted(signers):
        _fail()
    if store is not None:
        store.accept_keyset(keys["sequence"], _digest(keyset_raw), revoked)
    data = _json(release_raw)
    _exact(data, "schema issuer product channel releaseId version sequence issuedAt expiresAt keyId minKeysetSequence protocols layout launcher receiver files")
    _identity(data, RELEASE_SCHEMA)
    issued, _ = _window(data["issuedAt"], data["expiresAt"], now)
    semver = SEMVER.fullmatch(str(data["version"]))
    if (not _printable(data["releaseId"], 128) or semver is None
            or (semver[4] and any(p.isdecimal() and len(p) > 1 and p[0] == "0" for p in semver[4].split(".")))
            or not _integer(data["minKeysetSequence"], 1)
            or keys["sequence"] < data["minKeysetSequence"]
            or data["protocols"] != [PROTOCOL] or data["layout"] not in ("portable", "unpacked")):
        _fail()
    key_id = data["keyId"]
    if not isinstance(key_id, str) or not DIGEST.fullmatch(key_id):
        _fail()
    if key_id in revoked:
        _fail("SIGNATURE_REVOKED")
    if key_id not in signers:
        _fail()
    public, start, end = signers[key_id]
    if not start <= issued < end or not start <= now < end:
        _fail("SIGNATURE_EXPIRED")
    if not _verify(public, _signature(release_sig), RELEASE_SCHEMA, release_raw):
        _fail()
    files = _inventory(data["files"])
    receiver, launcher_file = _path(data["receiver"]), _file(data["launcher"])
    inventory = {row.path: row for row in files}
    if receiver not in inventory or not receiver.lower().endswith(".exe") or not launcher_file.path.lower().endswith(".exe"):
        _fail()
    if data["layout"] == "unpacked" and (launcher_file.path != receiver or inventory.get(receiver) != launcher_file):
        _fail()
    result = VerifiedRelease(Path(launcher) if launcher is not None else None, launcher_file,
                             receiver, files, data["layout"], data["sequence"], keys["sequence"],
                             key_id, root_id, release_raw, keyset_raw, store)
    if store is not None:
        store.check_release(result)
    return result


def _sidecars(launcher):
    return (launcher.with_name(launcher.name + ".chaessi-release.json"),
            launcher.with_name(launcher.name + ".chaessi-release.sig"),
            launcher.with_name("chaessi-publisher-keys.json"),
            launcher.with_name("chaessi-publisher-keys.sig"))


def _sidecar_names(launcher, root):
    if launcher is None:
        return set()
    return {p.relative_to(root).as_posix() for p in _sidecars(launcher) if p.is_relative_to(root)}


def inspect_release(launcher, roots, store=None, *, now=None):
    launcher = registry.local_path(launcher)
    paths = _sidecars(launcher)
    # lexists distinguishes absent metadata from unsafe/broken links. Any part
    # present disables the caller's narrowly pinned legacy compatibility path.
    present = [os.path.lexists(p) for p in paths]
    if not any(present):
        return None
    if not all(present):
        _fail()
    try:
        with ExitStack() as stack:
            raw = []
            for index, path in enumerate(paths):
                stack.enter_context(registry.checked_handle(path, read=True))
                with path.open("rb") as stream:
                    value = stream.read(MAX_JSON + 1 if index % 2 == 0 else 128)
                raw.append(value)
            stack.enter_context(registry.checked_handle(launcher, read=True))
            result = validate_metadata(*raw, roots, store=store, now=now, launcher=launcher)
            _check_file(launcher, result.launcher_file)
            return result
    except ReleaseError:
        raise
    except (OSError, TransferError, ValueError):
        _fail()


def _check_file(path, record):
    with path.open("rb") as source:
        if os.fstat(source.fileno()).st_size != record.size:
            _fail("RUNTIME_MISMATCH")
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != record.sha256:
            _fail("RUNTIME_MISMATCH")


@contextmanager
def _pin_child(path, security, *, parents, directory=False):
    """Pin a direct child whose parent is already pinned for this lifetime.

    Same CreateFile flags, share mask and reparse/type check as checked_handle.
    The runtime tree is not a private configuration store, so neither version
    applies its ACL check here. The root's full ancestor chain is held once by
    checked_handle; no child can rename an already held directory around us.
    """
    if path.parent not in parents:
        _fail("RUNTIME_MISMATCH")
    handle = security.open(str(path), 0x80 | (0 if directory else 0x80000000),
                           3 if directory else 1, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attrs = (registry.w.DWORD * 2)()
        if not security.info(handle, 9, attrs, ctypes.sizeof(attrs)):
            raise ctypes.WinError(ctypes.get_last_error())
        if attrs[0] & 0x400 or bool(attrs[0] & 0x10) != directory:
            _fail("RUNTIME_MISMATCH")
        yield path
    finally:
        security.close(handle)


def _scan(root, excluded, *, security=None, pins=None, root_pinned=False):
    files, directories, names = set(), set(), {}
    pending = [(root, "")]
    with ExitStack() as local_pins:
        security = registry.WindowsSecurity() if security is None else security
        retained = local_pins if pins is None else pins
        if not root_pinned:
            retained.enter_context(registry.checked_handle(root, directory=True))
        parents = {root}
        while pending:
            folder, prefix = pending.pop()
            # No link is traversed by enumeration; checked_handle rejects reparse
            # points again while all directories are subsequently pinned.
            with os.scandir(folder) as entries:
                for entry in entries:
                    name = prefix + entry.name
                    try:
                        _path(name)
                    except ReleaseError:
                        _fail("RUNTIME_MISMATCH")
                    if names.setdefault(name.casefold(), name) != name or entry.is_symlink():
                        _fail("RUNTIME_MISMATCH")
                    if name in excluded:
                        if not entry.is_file(follow_symlinks=False):
                            _fail("RUNTIME_MISMATCH")
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        # Pin before traversing, including junctions not reported as
                        # symlinks by older Python runtimes.
                        child = Path(entry.path)
                        retained.enter_context(_pin_child(child, security, parents=parents, directory=True))
                        parents.add(child)
                        directories.add(name)
                        pending.append((Path(entry.path), name + "/"))
                    elif entry.is_file(follow_symlinks=False):
                        files.add(name)
                    else:
                        _fail("RUNTIME_MISMATCH")
                    if len(files) + len(directories) > MAX_FILES * 2:
                        _fail("RUNTIME_MISMATCH")
    return files, directories


class ReleaseStore:
    """Per-product/channel highwater using the reader's existing private ACLs."""
    def __init__(self, root):
        self.root = registry.local_path(root)
        self.path = self.root / "private-preset-release.json"
        self._directory = library.PresetLibrary(self.root)

    def _read(self):
        try:
            with registry.checked_handle(self.path, root=self.root, read=True) as path:
                with path.open("rb") as stream:
                    raw = stream.read(1024 * 1024 + 1)
        except FileNotFoundError:
            return {"format": 1, "keysetSequence": 0, "keysetSha256": "0" * 64,
                    "releaseSequence": 0, "releaseSha256": "0" * 64, "revokedKeyIds": []}
        try:
            data = _json(raw)
            _exact(data, "format keysetSequence keysetSha256 releaseSequence releaseSha256 revokedKeyIds")
            if (data["format"] != 1 or not _integer(data["keysetSequence"])
                    or not _integer(data["releaseSequence"])
                    or any(not DIGEST.fullmatch(str(data[k])) for k in ("keysetSha256", "releaseSha256"))
                    or not isinstance(data["revokedKeyIds"], list)
                    or len(data["revokedKeyIds"]) > 4096
                    or any(not DIGEST.fullmatch(str(k)) for k in data["revokedKeyIds"])
                    or data["revokedKeyIds"] != sorted(set(data["revokedKeyIds"]))):
                _fail()
            return data
        except ReleaseError:
            _fail("SIGNATURE_STORE_INVALID")

    def _write(self, data):
        self._directory._ensure_root()
        with registry.checked_handle(self.root, root=self.root, directory=True):
            temp = self.root / (".release-" + uuid.uuid4().hex + ".tmp")
            try:
                with library._open_private(temp) as stream:
                    stream.write(canonical(data))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)

    @staticmethod
    def _highwater(state, prefix, sequence, digest):
        old = state[prefix + "Sequence"]
        if sequence < old or (sequence == old and digest != state[prefix + "Sha256"]):
            _fail("SIGNATURE_ROLLBACK")

    def accept_keyset(self, sequence, digest, revoked):
        with library._store_lock(self.root):
            state = self._read()
            self._highwater(state, "keyset", sequence, digest)
            combined = sorted(set(state["revokedKeyIds"]) | set(revoked))
            if len(combined) > 4096:
                _fail("SIGNATURE_STORE_INVALID")
            state.update(keysetSequence=sequence, keysetSha256=digest,
                         revokedKeyIds=combined)
            self._write(state)

    def _check(self, state, info):
        self._highwater(state, "keyset", info.keyset_sequence, info.keyset_digest)
        self._highwater(state, "release", info.sequence, info.release_digest)
        if info.key_id in state["revokedKeyIds"]:
            _fail("SIGNATURE_REVOKED")

    def check_release(self, info):
        with library._store_lock(self.root):
            self._check(self._read(), info)

    def commit_release(self, info):
        with library._store_lock(self.root):
            state = self._read()
            self._check(state, info)
            revoked = sorted(set(state["revokedKeyIds"]) | set(json.loads(info.keyset_raw)["revokedKeyIds"]))
            if info.key_id in revoked:
                _fail("SIGNATURE_REVOKED")
            if len(revoked) > 4096:
                _fail("SIGNATURE_STORE_INVALID")
            # Also support inspect(store=None) followed by an explicit protected
            # store at authenticated commit, without leaving keyset highwater 0.
            state.update(keysetSequence=info.keyset_sequence, keysetSha256=info.keyset_digest,
                         revokedKeyIds=revoked)
            state.update(releaseSequence=info.sequence, releaseSha256=info.release_digest)
            self._write(state)

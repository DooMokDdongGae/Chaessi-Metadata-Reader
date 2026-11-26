"""Store Reader's Chrome pairing secret in a private, per-user Windows directory."""
import hmac
import os
from pathlib import Path
import re
import secrets
import uuid
from contextlib import contextmanager

from bundle import preset_library as private
from bundle import transfer_registry as registry


class PairingKeyError(OSError):
    """Expose only a localizable reason, never a path, file content or credential."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@contextmanager
def _safe_io():
    try:
        yield
    except PairingKeyError:
        raise
    except private.LibraryError:
        raise PairingKeyError("PAIRING_KEY_BUSY") from None
    except (PermissionError, registry.TransferError):
        raise PairingKeyError("PAIRING_KEY_UNSAFE") from None
    except (OSError, ValueError):
        raise PairingKeyError("PAIRING_KEY_STORAGE") from None


def _read(path, pattern):
    with registry.checked_handle(path, root=path.parent, read=True) as path:
        with path.open("rb") as stream:
            raw = stream.read(65)
    if not re.fullmatch(pattern, raw):
        raise PairingKeyError("PAIRING_KEY_INVALID")
    return raw.decode("ascii")


def _directory_exists(directory):
    try:
        with registry.checked_handle(directory, root=directory, directory=True):
            return True
    except FileNotFoundError:
        return False


def _ensure_directory(directory):
    for part in (*reversed(directory.parents), directory):
        if part == part.parent or part.exists():
            continue
        with registry.checked_handle(part.parent, directory=True):
            private._make_directory(part)


def _write(destination, value, *, replace):
    directory = destination.parent
    _ensure_directory(directory)
    with registry.checked_handle(directory, root=directory, directory=True):
        name = directory / (".pending-" + uuid.uuid4().hex)
        output = private._open_private(name)
        try:
            with output:
                output.write(value.encode("ascii"))
                output.flush()
                os.fsync(output.fileno())
            if replace:
                os.replace(name, destination)
            else:
                # Windows rename, unlike replace, cannot overwrite an existing entry.
                name.rename(destination)
        finally:
            name.unlink(missing_ok=True)


class BridgeKeyStore:
    def __init__(self, root=None):
        if root is None:
            local = os.environ.get("LOCALAPPDATA")
            if not local:
                raise PairingKeyError("PAIRING_KEY_STORAGE")
            root = Path(local) / "CHAESSI" / "MetadataReader" / "bridge"
        with _safe_io():
            self.root = registry.local_path(root)
        # Support the previous single-recovery layout without modifying its files.
        self.recovery = self.root.with_name(self.root.name + "-reconnected")
        self.index = self.root.with_name(self.root.name + "-pairing") / "active"
        self.generations = self.root.with_name(self.root.name + "-recovery-keys")

    def _key_path(self, generation):
        if generation == "primary":
            return self.root / "bridge-key"
        if generation == "previous":
            return self.recovery / "bridge-key"
        # Callers pass a generated ID or a bounded, strictly validated index value.
        return self.generations / generation

    def _existing(self):
        indexed = _directory_exists(self.index.parent)
        if indexed:
            try:
                generation = _read(self.index, b"primary|previous|[0-9a-f]{32}")
            except FileNotFoundError:
                raise PairingKeyError("PAIRING_KEY_INVALID") from None
        elif _directory_exists(self.generations):
            # The index directory was lost after recovery. Retired credentials are
            # still on disk, but none may become active without explicit recovery.
            raise PairingKeyError("PAIRING_KEY_INVALID")
        else:
            generation = "previous" if _directory_exists(self.recovery) else "primary"
        try:
            value = _read(self._key_path(generation), b"[0-9a-f]{64}")
        except FileNotFoundError:
            if indexed or generation != "primary":
                raise PairingKeyError("PAIRING_KEY_INVALID") from None
            value = None
        return generation, value, indexed

    def _reconnect(self):
        # A new generation is never advertised until both its bytes and its ACL
        # are on disk. An interrupted unpublished generation is never consulted.
        _ensure_directory(self.index.parent)
        with registry.checked_handle(self.index.parent, root=self.index.parent, directory=True):
            _ensure_directory(self.generations)
            with registry.checked_handle(self.generations, root=self.generations, directory=True):
                generation = uuid.uuid4().hex
                target = self._key_path(generation)
                value = secrets.token_hex(32)
                _write(target, value, replace=False)
                try:
                    _write(self.index, generation, replace=True)
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
                return value, True

    def _open(self, recover):
        with _safe_io(), private._store_lock(self.root):
            try:
                with _safe_io():
                    generation, value, indexed = self._existing()
            except PairingKeyError as exc:
                if not recover or exc.code not in ("PAIRING_KEY_INVALID", "PAIRING_KEY_UNSAFE"):
                    raise
                return self._reconnect()
            created = value is None
            if created:
                value = secrets.token_hex(32)
                _write(self._key_path(generation), value, replace=False)
            if not indexed:
                _write(self.index, generation, replace=False)
            return value, created

    def load(self):
        return self._open(recover=False)

    def recover(self):
        """After user confirmation, keep the damaged generation and pair afresh."""
        return self._open(recover=True)

    def verify(self, expected):
        with _safe_io(), private._store_lock(self.root):
            _, current, _ = self._existing()
            if current is None or not hmac.compare_digest(current, expected):
                raise PairingKeyError("PAIRING_KEY_CHANGED")

    def import_folder(self, selected_folder, expected):
        # Only the exact .local/bridge-key inside the user's selected Reader root.
        with _safe_io(), private._store_lock(self.root):
            generation, current, _ = self._existing()
            if current is None or not hmac.compare_digest(current, expected):
                raise PairingKeyError("PAIRING_KEY_CHANGED")
            legacy = registry.local_path(selected_folder) / ".local" / "bridge-key"
            try:
                imported = _read(legacy, b"[0-9a-f]{64}")
            except FileNotFoundError:
                raise PairingKeyError("PAIRING_KEY_MISSING") from None
            if not hmac.compare_digest(imported, current):
                _write(self._key_path(generation), imported, replace=True)
            return imported

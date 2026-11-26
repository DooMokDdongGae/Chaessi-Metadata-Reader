"""Private, per-user transactional updater invoked by Reader's NSIS packages."""
import argparse
from contextlib import ExitStack, contextmanager, nullcontext
import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

# PyInstaller treats this script as a top-level entry point. Retain package
# imports for source tests and make those same imports resolvable in a freeze.
if not getattr(sys, "frozen", False):
    for source in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parent):
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
import update_policy as policy


APP = policy.APP
MAX_CATALOGUE = 5 * 1024 * 1024
STATE = "state.json"
JOURNAL = "journal.json"
FRESH = "fresh.json"
RELOCATION_JOURNAL = "relocation.json"
RELOCATION_PATHS = ("payload", "uninstaller", "start_link", "guide_link", "desktop_link")
ARP = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ChaessiMetadataReader"
D_INSTALL = r"D:\MApp\Chaessi Reader"
BIN_EXTENSIONS = {".dll", ".pyd", ".exe", ".py", ".pyc", ".pyo", ".zip", ".local", ".pth"}
# The compact updater's generated frozen entry sets this to immutable bytes
# in its embedded Python archive. The separate FULL entry keeps its data file.
EMBEDDED_CATALOGUE = None


@dataclass(frozen=True)
class FileSnapshot:
    digest: str
    identity: tuple
    size: int


def valid_workspace_name(name):
    return (isinstance(name, str) and name.startswith("txn-") and len(name) == 36
            and all(char in "0123456789abcdef" for char in name[4:]))


class FileOperations:
    """Transaction filesystem operations. The production CLI always uses WindowsOperations."""
    def __init__(self, install, control, *, transaction_root=None, location=None):
        self.install = install
        self.control = control
        self.transaction_root = control if transaction_root is None else transaction_root
        self.location = location

    def transaction_workspace(self, name):
        policy.reject("INVALID_UPDATE_JOURNAL", not valid_workspace_name(name))
        return self.transaction_root / name

    def allocate_transaction_workspace(self):
        directory = self.transaction_workspace("txn-" + uuid.uuid4().hex)
        self.make_transaction_dir(directory)
        return directory

    def make_transaction_dir(self, path):
        self.make_dir(path)

    def kind(self, path):
        try:
            details = path.lstat()
        except FileNotFoundError:
            return None
        policy.reject("UNSAFE_FILE_OR_DIRECTORY", getattr(details, "st_file_attributes", 0) & 0x400
                      or stat.S_ISLNK(details.st_mode))
        if stat.S_ISDIR(details.st_mode):
            return "directory"
        policy.reject("UNSAFE_FILE_OR_DIRECTORY", not stat.S_ISREG(details.st_mode) or details.st_nlink != 1)
        return "file"

    def validate_chain(self, path):
        for parent in reversed(path.parents):
            kind = self.kind(parent)
            if kind is None:
                return
            policy.reject("UNSAFE_PARENT", kind != "directory")

    def pinned(self, path, *, read=False, directory=False):
        self.validate_chain(path)
        policy.reject("UNSAFE_FILE_OR_DIRECTORY", self.kind(path) != ("directory" if directory else "file"))
        return nullcontext(path)

    def inspect(self, path):
        self.validate_chain(path)
        if self.kind(path) is None:
            return None
        with self.pinned(path, read=True), path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
            fields = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            policy.reject("FILE_CHANGED_DURING_READ", fields(before) != fields(after) or after.st_nlink != 1)
            return FileSnapshot(digest, fields(after), after.st_size)

    def matches(self, path, expected):
        value = self.inspect(path)
        return value is not None and value.digest == expected

    def read(self, path, limit):
        self.validate_chain(path)
        if self.kind(path) is None:
            return None
        with self.pinned(path, read=True), path.open("rb") as file:
            raw = file.read(limit + 1)
        policy.reject("UPDATE_RECORD_TOO_LARGE", len(raw) > limit)
        return raw

    def make_dir(self, path):
        self.validate_chain(path)
        path.mkdir()

    def make_file(self, path):
        self.validate_chain(path)
        return path.open("xb")

    def durable_replace(self, src, dst):
        os.replace(src, dst)

    def write_record(self, dst, data):
        self.validate_chain(dst)
        policy.reject("UNSAFE_UPDATE_RECORD", self.kind(dst) not in (None, "file"))
        new = dst.parent / ("new-" + uuid.uuid4().hex)
        with self.make_file(new) as stream:
            stream.write(policy.bytes_for(data))
            stream.flush()
            os.fsync(stream.fileno())
        self.durable_replace(new, dst)

    def copy(self, src, dst, expected):
        with self.pinned(src, read=True), src.open("rb") as origin, self.make_file(dst) as output:
            shutil.copyfileobj(origin, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        policy.reject("STAGED_HASH_MISMATCH", not self.matches(dst, expected))

    def replace_owned(self, src, dst, displaced, before):
        with ExitStack() as pins:
            for parent in dict.fromkeys((src.parent, dst.parent, displaced.parent)):
                pins.enter_context(self.pinned(parent, directory=True))
            policy.reject("BASELINE_CHANGED_BEFORE_REPLACE", self.inspect(dst) != before)
            policy.reject("BACKUP_COLLISION", self.kind(displaced) is not None)
            self.atomic_file_replace(src, dst, displaced)

    def atomic_file_replace(self, src, dst, displaced):
        # Used only by filesystem tests on non-Windows. Preserve the displaced
        # original for the same postcondition tested by ReplaceFileW.
        shutil.copyfile(dst, displaced)
        os.replace(src, dst)

    def restore_absent(self, source, destination):
        policy.reject("DESTINATION_COLLISION", self.kind(destination) is not None)
        self.durable_replace(source, destination)

    def remove_owned(self, path, expected):
        with self.pinned(path.parent, directory=True):
            policy.reject("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", self.inspect(path) != expected)
            path.unlink()

    def ensure_payload_directory(self, path):
        if self.kind(path) is None:
            self.ensure_payload_directory(path.parent)
            self.make_dir(path)
        policy.reject("UNSAFE_PARENT", self.kind(path) != "directory")

    def prepare_displaced(self, path, expected):
        value = self.inspect(path)
        policy.reject("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", value is not None and value.digest != expected)
        return value

    def cleanup_workspace(self, directory, count):
        allowed = {f"{prefix}-{index}" for prefix in ("before", "after", "displaced", "restore", "removed")
                   for index in range(count)}
        if self.kind(directory) == "directory":
            with self.pinned(directory, directory=True):
                for entry in directory.iterdir():
                    if entry.name in allowed and self.kind(entry) == "file":
                        entry.unlink()
            if not any(directory.iterdir()):
                directory.rmdir()

    def has_registration(self):
        return self.kind(self.install / "Uninstall.exe") is not None

    def attest_owner(self):
        policy.reject("REGISTRATION_MISSING", not self.has_registration())
        receipt = self.inspect(self.install / "Uninstall.exe")
        policy.reject("UNINSTALLER_OWNERSHIP_MISMATCH",
                      receipt is None or receipt.size == 0 or not self.matches(
                          self.install / "uninstaller.copy", receipt.digest))

    def ensure_closed(self):
        pass

    def health(self):
        pass


def windows_api():
    from bundle import preset_library
    from bundle import transfer_registry
    return preset_library, transfer_registry


def known_folder(folder_id):
    kernel = ctypes.WinDLL("shell32", use_last_error=True)
    _, registry = windows_api()
    get = registry._api(kernel, "SHGetKnownFolderPath", ctypes.c_long, ctypes.c_void_p,
                        w.DWORD, w.HANDLE, ctypes.c_void_p)
    release = registry._api(ctypes.WinDLL("ole32"), "CoTaskMemFree", None, ctypes.c_void_p)
    guid = ctypes.create_string_buffer(uuid.UUID(folder_id).bytes_le)
    result = ctypes.c_void_p()
    status = get(ctypes.byref(guid), 0, None, ctypes.byref(result))
    try:
        policy.reject("OFFICIAL_PROFILE_UNAVAILABLE", status != 0 or not result.value)
        return registry.local_path(ctypes.wstring_at(result.value))
    finally:
        if result.value:
            release(result)


def mounted_install_volume(anchor):
    """Verify an actual fixed volume with persistent ACLs and return its GUID."""
    _, registry = windows_api()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    drive_type = registry._api(kernel, "GetDriveTypeW", w.UINT, w.LPCWSTR)
    mount_name = registry._api(kernel, "GetVolumeNameForVolumeMountPointW", w.BOOL,
                               w.LPCWSTR, w.LPWSTR, w.DWORD)
    volume_info = registry._api(kernel, "GetVolumeInformationW", w.BOOL,
                                w.LPCWSTR, w.LPWSTR, w.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p, w.LPWSTR, w.DWORD)
    name = ctypes.create_unicode_buffer(64)
    flags = w.DWORD()
    policy.reject("D_INSTALL_VOLUME_UNAVAILABLE", drive_type(anchor) != 3
                  or not mount_name(anchor, name, len(name)))
    policy.reject("D_INSTALL_VOLUME_REQUIRES_ACLS",
                  not volume_info(anchor, None, 0, None, None, ctypes.byref(flags), None, 0)
                  or not flags.value & 0x8)
    return name.value.casefold()


def reader_process_ids():
    class Entry(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                    ("parent", w.DWORD), ("priority", ctypes.c_long), ("flags", w.DWORD),
                    ("name", w.WCHAR * 260)]

    _, r = windows_api()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = r._api(kernel, "CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
    first = r._api(kernel, "Process32FirstW", w.BOOL, w.HANDLE, ctypes.c_void_p)
    following = r._api(kernel, "Process32NextW", w.BOOL, w.HANDLE, ctypes.c_void_p)
    close = r._api(kernel, "CloseHandle", w.BOOL, w.HANDLE)
    handle = snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        valid = first(handle, ctypes.byref(entry))
        while valid:
            if entry.name.casefold() == APP.casefold():
                yield entry.pid
            valid = following(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close(handle)


class WindowsOperations(FileOperations):
    @classmethod
    def for_user(cls, *, legacy=False):
        policy.reject("WINDOWS_X64_REQUIRED", sys.platform != "win32" or sys.maxsize <= 2**32)
        local = known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
        profile = known_folder("5E6C858F-0E22-4760-9AFE-EA3317B67173")
        policy.reject("UNSUPPORTED_LOCAL_APPDATA_PATH", local != profile / "AppData" / "Local")
        control = local / "CHAESSI" / "MetadataReaderUpdate"
        if legacy:
            return cls(local / "Programs" / "ChaessiMetadataReader", control)
        install = Path(D_INSTALL)
        return cls(install, control, transaction_root=install, location=mounted_install_volume(install.anchor))

    def verify_mount(self):
        if self.location is not None:
            policy.reject("D_INSTALL_VOLUME_CHANGED", mounted_install_volume(self.install.anchor) != self.location)
        return self.location

    @contextmanager
    def pinned(self, path, *, read=False, directory=False):
        _, registry = windows_api()
        root = self.control if path.is_relative_to(self.control) else None
        if root is None and self.location is not None and path.is_relative_to(self.transaction_root):
            relative = path.relative_to(self.transaction_root).parts
            if relative and valid_workspace_name(relative[0]):
                root = self.transaction_workspace(relative[0])
        try:
            with registry.checked_handle(path, root=root, read=read, directory=directory):
                policy.reject("UNSAFE_FILE_OR_DIRECTORY", self.kind(path) != ("directory" if directory else "file"))
                yield path
        except registry.TransferError as exc:
            # The shared native path/ACL guard reports a transfer-domain
            # ValueError. Translate its known refusal into the updater domain
            # so an in-progress transaction enters the existing rollback path.
            raise policy.Refusal("WINDOWS_FILE_GUARD_REFUSED") from exc

    def make_dir(self, path):
        library, _ = windows_api()
        with self.pinned(path.parent, directory=True):
            library._make_directory(path)
        with self.pinned(path, directory=True):
            pass

    def make_transaction_dir(self, path):
        library, registry = windows_api()
        create = registry._api(ctypes.WinDLL("kernel32", use_last_error=True), "CreateDirectoryW",
                               w.BOOL, w.LPCWSTR, ctypes.c_void_p)
        self.verify_mount()
        with self.pinned(path.parent, directory=True), library._private_attributes() as attrs:
            if not create(str(path), ctypes.byref(attrs)):
                raise ctypes.WinError(ctypes.get_last_error())
        with self.pinned(path, directory=True):
            pass

    def make_file(self, path):
        library, _ = windows_api()
        with self.pinned(path.parent, directory=True):
            return library._open_private(path)

    @contextmanager
    def lock(self):
        import msvcrt

        # NSIS retains its own original session mutex. Lock the same local file
        # across Windows sessions without reacquiring that named mutex.
        for folder in (self.control.parent, self.control):
            if self.kind(folder) is None:
                self.make_dir(folder)
        with self.pinned(self.control, directory=True):
            checked = self.control / "update.lock"
            if self.kind(checked) is None:
                try:
                    with self.make_file(checked) as stream:
                        stream.write(b"X")
                        stream.flush()
                        os.fsync(stream.fileno())
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in (80, 183):
                        raise
            with self.pinned(checked), checked.open("r+b") as stream:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise policy.Refusal("UPDATE_IN_PROGRESS") from None
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def durable_replace(self, src, dst, *, overwrite=True):
        _, r = windows_api()
        move = r._api(ctypes.WinDLL("kernel32", use_last_error=True), "MoveFileExW", w.BOOL,
                      w.LPCWSTR, w.LPCWSTR, w.DWORD)
        with ExitStack() as pins:
            for parent in dict.fromkeys((src.parent, dst.parent)):
                pins.enter_context(self.pinned(parent, directory=True))
            self.require_same_volume(src, dst)
            if not move(str(src), str(dst), 8 | int(overwrite)):
                raise ctypes.WinError(ctypes.get_last_error())

    def restore_absent(self, source, destination):
        self.durable_replace(source, destination, overwrite=False)

    def require_same_volume(self, *paths):
        if self.location is not None and any(path.is_relative_to(self.install) for path in paths):
            self.verify_mount()
        volumes = {os.stat(path.parent, follow_symlinks=False).st_dev for path in paths}
        policy.reject("UPDATE_REPLACEMENT_WRONG_VOLUME", len(volumes) != 1)

    def atomic_file_replace(self, src, dst, displaced):
        _, r = windows_api()
        replace = r._api(ctypes.WinDLL("kernel32", use_last_error=True), "ReplaceFileW", w.BOOL,
                         w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_void_p, ctypes.c_void_p)
        self.require_same_volume(src, dst, displaced)
        if not replace(str(dst), str(src), str(displaced), 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())

    def protect_displaced(self, path, expected):
        # ReplaceFileW retains the displaced installation file's original ACL.
        # Give only this exact, hash-verified transaction member a protected ACL
        # before the ordinary private-workspace guard reads it. No existing
        # installation directory or unrelated file ACL is modified.
        library, r = windows_api()
        security = r.WindowsSecurity()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        read = r._api(kernel, "ReadFile", w.BOOL, w.HANDLE, ctypes.c_void_p, w.DWORD,
                      ctypes.c_void_p, ctypes.c_void_p)
        get_dacl = r._api(advapi, "GetSecurityDescriptorDacl", w.BOOL, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        set_security = r._api(advapi, "SetSecurityInfo", w.DWORD, w.HANDLE, ctypes.c_int,
                              w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        with self.pinned(path.parent, directory=True):
            handle = security.open(str(path), 0x80000000 | r.READ_CONTROL | 0x40000,
                                   1, None, 3, 0x00200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                attrs = (w.DWORD * 2)()
                if not security.info(handle, 9, attrs, ctypes.sizeof(attrs)):
                    raise ctypes.WinError(ctypes.get_last_error())
                policy.reject("UNSAFE_FILE_OR_DIRECTORY", attrs[0] & (0x400 | 0x10)
                              or os.stat(path, follow_symlinks=False).st_nlink != 1)
                owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
                status = security.security(handle, 1, 1, ctypes.byref(owner), None, None, None,
                                           ctypes.byref(descriptor))
                try:
                    if status:
                        raise ctypes.WinError(status)
                    policy.reject("UNSAFE_DISPLACED_OWNER", security.sid(owner) not in security.trusted)
                finally:
                    if descriptor.value:
                        security.free(descriptor)
                digest = hashlib.sha256()
                buffer, count = ctypes.create_string_buffer(1024 * 1024), w.DWORD()
                while True:
                    if not read(handle, buffer, len(buffer), ctypes.byref(count), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not count.value:
                        break
                    digest.update(buffer.raw[:count.value])
                policy.reject("DISPLACED_FILE_HASH_MISMATCH", digest.hexdigest() != expected)
                with library._private_attributes() as attributes:
                    present, defaulted, acl = w.BOOL(), w.BOOL(), ctypes.c_void_p()
                    if not get_dacl(attributes.descriptor, ctypes.byref(present), ctypes.byref(acl),
                                    ctypes.byref(defaulted)) or not present.value or not acl.value:
                        raise policy.Refusal("PRIVATE_WORKSPACE_ACL_UNAVAILABLE")
                    status = set_security(handle, 1, 4 | 0x80000000, None, None, acl, None)
                    if status:
                        raise ctypes.WinError(status)
                security.check_acl(handle)
            finally:
                security.close(handle)

    def replace_owned(self, src, dst, displaced, before):
        super().replace_owned(src, dst, displaced, before)
        self.protect_displaced(displaced, before.digest)

    def prepare_displaced(self, path, expected):
        if self.kind(path) is None:
            return None
        policy.reject("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", expected is None)
        # A crash may have occurred after ReplaceFileW but before hardening.
        # Reopen only this exact journal member; verify approved bytes, one link,
        # trusted owner and pinned ancestry before changing its DACL by handle.
        self.protect_displaced(path, expected)
        return self.inspect(path)

    def remove_owned(self, path, expected):
        # Delete an added rollback member by the same file handle that was
        # hashed, never by a reopened path. Deny write/rename sharing throughout.
        _, r = windows_api()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = r._api(kernel, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
                        ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE)
        close = r._api(kernel, "CloseHandle", w.BOOL, w.HANDLE)
        read = r._api(kernel, "ReadFile", w.BOOL, w.HANDLE, ctypes.c_void_p, w.DWORD,
                      ctypes.c_void_p, ctypes.c_void_p)
        info = r._api(kernel, "GetFileInformationByHandleEx", w.BOOL, w.HANDLE, ctypes.c_int,
                      ctypes.c_void_p, w.DWORD)
        dispose = r._api(kernel, "SetFileInformationByHandle", w.BOOL, w.HANDLE, ctypes.c_int,
                         ctypes.c_void_p, w.DWORD)
        with self.pinned(path.parent, directory=True):
            handle = create(str(path), 0x80000000 | 0x10000, 1, None, 3, 0x00200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                attrs = (w.DWORD * 2)()
                if not info(handle, 9, attrs, ctypes.sizeof(attrs)):
                    raise ctypes.WinError(ctypes.get_last_error())
                policy.reject("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", attrs[0] & (0x400 | 0x10))
                details = os.stat(path, follow_symlinks=False)
                identity = (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)
                policy.reject("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", details.st_nlink != 1 or identity != expected.identity)
                digest = hashlib.sha256()
                buffer, count = ctypes.create_string_buffer(1024 * 1024), w.DWORD()
                while True:
                    if not read(handle, buffer, len(buffer), ctypes.byref(count), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not count.value:
                        break
                    digest.update(buffer.raw[:count.value])
                policy.reject("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", digest.hexdigest() != expected.digest)
                delete = w.BOOL(True)
                if not dispose(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                close(handle)

    def has_registration(self):
        import winreg

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP, 0,
                                 winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            return False
        with key:
            try:
                location, kind_location = winreg.QueryValueEx(key, "InstallLocation")
                uninstaller, kind_uninstaller = winreg.QueryValueEx(key, "UninstallString")
            except FileNotFoundError:
                raise policy.Refusal("INSTALL_LOCATION_MISMATCH") from None
        policy.reject("INSTALL_LOCATION_MISMATCH", kind_location != winreg.REG_SZ
                      or kind_uninstaller != winreg.REG_SZ or Path(location) != self.install
                      or uninstaller != '"' + str(self.install / "Uninstall.exe") + '"')
        return True

    def ensure_closed(self):
        _, registry = windows_api()
        for pid in reader_process_ids():
            try:
                with registry._process(pid) as (image, _created, verify):
                    verify()
                    policy.reject("READER_RUNNING_CLOSE_NORMALLY", image == self.install / APP)
            except OSError as exc:
                # A vanished PID is harmless. Failure to attest a live Reader
                # is unsafe because its executable could still be in use.
                if getattr(exc, "winerror", None) != 87:
                    raise policy.Refusal("READER_PROCESS_NOT_VERIFIED") from None

    def health(self):
        env = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY",
                    "CHAESSI_TRANSFER_REGISTRY"):
            env.pop(key, None)
        scratch = Path(tempfile.mkdtemp(prefix="self-test-", dir=self.control))
        try:
            env["LOCALAPPDATA"] = env["APPDATA"] = str(scratch)
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            result = subprocess.run([str(self.install / APP), "--reader-self-test"],
                                    cwd=self.install, env=env, timeout=30, check=False,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=0x08000000)
            policy.reject("NEW_READER_SELF_TEST_FAILED", result.returncode != 0)
        except (OSError, subprocess.TimeoutExpired):
            raise policy.Refusal("NEW_READER_SELF_TEST_FAILED") from None
        finally:
            # Only remove this exact empty directory; preserve any logs that
            # a failing self-test may have emitted for investigation.
            try:
                scratch.rmdir()
            except OSError:
                pass


class Updater:
    def __init__(self, catalogue, files, checkpoint=None):
        self.catalogue = catalogue
        self.files = files
        self.checkpoint = checkpoint or (lambda _phase: None)

    @property
    def state_path(self):
        return self.files.control / STATE

    @property
    def journal_path(self):
        return self.files.control / JOURNAL

    @property
    def fresh_path(self):
        return self.files.control / FRESH

    def read_state(self):
        value = self.files.read(self.state_path, 4096)
        return None if value is None else policy.State.from_json(policy.parse_json(value))

    def record_scope(self):
        return ({"schema": 1} if self.files.location is None
                else {"schema": 2, "volume": self.files.location})

    def validate_record_scope(self, row, fields, error):
        scope = self.record_scope()
        policy.reject(error, not isinstance(row, dict) or type(row.get("schema")) is not int)
        if any(row.get(key) != expected for key, expected in scope.items()):
            raise policy.Refusal("INTERRUPTED_UPDATE_REQUIRES_SAME_INSTALLATION", 3)
        policy.reject(error, set(row) != fields | scope.keys())

    def fresh_pending(self, state):
        value = self.files.read(self.fresh_path, 8192)
        if value is None:
            return False
        row = policy.parse_json(value)
        self.validate_record_scope(row, {"target", "state_before"}, "INVALID_FRESH_SETUP_RECORD")
        target = policy.State.from_json(row["target"])
        if target != self.catalogue.target.state:
            raise policy.Refusal("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER", 3)
        before = None if row["state_before"] is None else policy.State.from_json(row["state_before"])
        self.catalogue.check_high_water(before)
        policy.reject("RECOVERY_STATE_CHANGED", state not in (before, target))
        return True

    def matches_release(self, release, *, ignore=()):
        return all(path in ignore or self.files.matches(self.files.install / path, digest)
                   for path, digest in release.payload.items())

    def check_unowned_loaders(self, release):
        owned = {path.casefold() for path in release.payload}
        directories = [self.files.install]
        while directories:
            folder = directories.pop()
            with self.files.pinned(folder, directory=True):
                for entry in folder.iterdir():
                    rel = entry.relative_to(self.files.install).as_posix().casefold()
                    if rel in policy.OWNER_FILES or rel in owned:
                        continue
                    if rel == "_internal" or rel.startswith("_internal/"):
                        if self.files.kind(entry) == "directory":
                            directories.append(entry)
                            continue
                        raise policy.Refusal("UNEXPECTED_RUNTIME_FILE")
                    if entry.suffix.casefold() in BIN_EXTENSIONS:
                        raise policy.Refusal("UNEXPECTED_RUNTIME_FILE")

    def observed_release(self):
        app = self.files.inspect(self.files.install / APP)
        if app is None:
            policy.reject("UNKNOWN_OR_PARTIAL_INSTALLATION", self.files.has_registration())
            names = {name for release in self.catalogue.releases for name in release.payload}
            policy.reject("UNKNOWN_OR_PARTIAL_INSTALLATION", self.files.kind(self.files.install) == "file"
                          or any(self.files.kind(self.files.install / name) is not None for name in names)
                          or any(self.files.kind(self.files.install / name) is not None
                                 for name in policy.OWNER_FILES))
            if self.files.kind(self.files.install) == "directory":
                self.check_unowned_loaders(self.catalogue.target)
            return None
        self.files.attest_owner()
        for release in self.catalogue.releases:
            if release.payload[APP] == app.digest and self.matches_release(release, ignore=(APP,)):
                self.check_unowned_loaders(release)
                return release
        raise policy.Refusal("UNKNOWN_OR_PARTIAL_INSTALLATION")

    def status(self):
        state = self.read_state()
        self.catalogue.check_high_water(state)
        if self.files.kind(self.journal_path) is not None:
            raise policy.Refusal("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER", 3)
        pending = self.fresh_pending(state)
        decision = self.catalogue.decide(self.observed_release(), state)
        if decision == "current" and (pending or state != self.catalogue.target.state):
            decision = "adopt_current"
        policy.reject("FRESH_INSTALLATION_CONFLICT", pending and decision not in ("fresh", "adopt_current"))
        if decision not in ("fresh", "current"):
            self.files.ensure_closed()
        return decision

    def begin_setup(self):
        policy.reject("FRESH_SETUP_NOT_ALLOWED", self.status() != "fresh")
        state = self.read_state()
        if not self.fresh_pending(state):
            record = {**self.record_scope(), "target": self.catalogue.target.state.as_json(),
                      "state_before": None if state is None else state.as_json()}
            self.files.write_record(self.fresh_path, record)
        return "fresh_setup_begun"

    def commit_setup(self):
        state = self.read_state()
        self.catalogue.check_high_water(state)
        policy.reject("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER",
                      self.files.kind(self.journal_path) is not None)
        pending = self.fresh_pending(state)
        policy.reject("SETUP_TARGET_NOT_INSTALLED", self.observed_release() != self.catalogue.target)
        self.files.ensure_closed()
        if self.catalogue.target.self_test:
            self.files.health()
        if state != self.catalogue.target.state:
            self.files.write_record(self.state_path, self.catalogue.target.state.as_json())
        if pending:
            self.fresh_path.unlink()
        return "committed"

    def uninstall_guard(self):
        # Retain the high-water record even after a legitimate uninstall.
        state = self.read_state()
        if self.files.kind(self.journal_path) is not None or self.files.kind(self.fresh_path) is not None:
            raise policy.Refusal("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER", 3)
        target = self.catalogue.target
        if state is not None and state.sequence > target.state.sequence:
            # A path-preserving update deliberately retains an older
            # uninstaller. It can remove its own known names using its original
            # NSIS checks only when the protected ledger proves the same set.
            policy.reject("UNINSTALLER_OWNERSHIP_CHANGED",
                          state.owned_paths_sha256 != target.state.owned_paths_sha256)
            self.files.attest_owner()
            policy.reject("WRONG_PRODUCT_MARKER", not self.files.matches(
                self.files.install / "product.id", target.payload["product.id"]))
            for name in target.payload:
                self.files.validate_chain(self.files.install / name)
                policy.reject("UNSAFE_FILE_OR_DIRECTORY", self.files.kind(self.files.install / name) == "directory")
        else:
            self.catalogue.check_high_water(state)
            policy.reject("UNKNOWN_OR_PARTIAL_INSTALLATION", self.observed_release() is None)
        self.files.ensure_closed()
        return "uninstall_allowed"

    def parse_journal(self, value):
        row = policy.parse_json(value)
        fields = {"workspace", "before", "target", "state_before", "phase", "mode"}
        if isinstance(row, dict) and "ownership" in row:
            fields.add("ownership")
        self.validate_record_scope(row, fields, "INVALID_UPDATE_JOURNAL")
        policy.reject("INVALID_UPDATE_JOURNAL", row["phase"] not in ("prepared", "verified")
                      or row["mode"] not in ("patch", "setup") or not valid_workspace_name(row["workspace"]))
        before = self.catalogue.find(policy.State.from_json(row["before"]))
        target = policy.State.from_json(row["target"])
        if target != self.catalogue.target.state or before is None:
            raise policy.Refusal("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER", 3)
        prior = None if row["state_before"] is None else policy.State.from_json(row["state_before"])
        self.catalogue.decide(before, prior, patch=row["mode"] == "patch")
        self.transaction_paths(before, row.get("ownership"), patch=row["mode"] == "patch")
        return row, before, prior

    def transaction_paths(self, before, ownership, *, patch):
        paths = policy.changed_paths(before, self.catalogue.target, patch=patch)
        expanded = before.payload.keys() != self.catalogue.target.payload.keys()
        policy.reject("SETUP_NEW_UNINSTALLER_REQUIRED", expanded and ownership is None)
        if ownership is not None:
            policy.reject("INVALID_UPDATE_OWNERSHIP", patch or not expanded or not isinstance(ownership, dict)
                          or set(ownership) != {"before", "after"}
                          or not all(policy.valid_hash(ownership.get(key)) for key in ("before", "after")))
            paths += ("Uninstall.exe", "uninstaller.copy")
        return paths

    def transaction_hashes(self, before, after, ownership):
        old, new = dict(before.payload), dict(after.payload)
        if ownership is not None:
            old.update({name: ownership["before"] for name in ("Uninstall.exe", "uninstaller.copy")})
            new.update({name: ownership["after"] for name in ("Uninstall.exe", "uninstaller.copy")})
        return old, new

    def finish(self, directory, paths):
        self.journal_path.unlink()
        try:
            self.files.cleanup_workspace(directory, len(paths))
        except (OSError, policy.Refusal):
            pass  # Transaction is committed or restored. A leftover is inert.

    def rollback(self, directory, paths, before, after, ownership=None):
        old, new = self.transaction_hashes(before, after, ownership)
        if not self.matches_release(before, ignore=paths):
            raise policy.Refusal("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", 5)
        # Prevalidate every changed file and every required backup before
        # restoring any of them. Altered content is not ours to overwrite.
        snapshots = []
        for index, name in enumerate(paths):
            target = self.files.install / name
            current = self.files.inspect(target)
            original = old.get(name)
            displaced = self.files.prepare_displaced(directory / f"displaced-{index}", original)
            self.files.prepare_displaced(directory / f"removed-{index}", new[name])
            if (current and current.digest not in (original, new[name])
                    or displaced and displaced.digest != original
                    or original is None and displaced is not None
                    or original is not None and current is None and displaced is None):
                raise policy.Refusal("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", 5)
            if original is not None and not self.files.matches(directory / f"before-{index}", original):
                raise policy.Refusal("ROLLBACK_BACKUP_INVALID", 5)
            snapshots.append(current)
        for index in reversed(range(len(paths))):
            name = paths[index]
            target = self.files.install / name
            current = snapshots[index]
            original = old.get(name)
            if original is None:
                if current is not None:
                    self.files.remove_owned(target, current)
                continue
            if current is not None and current.digest == original:
                continue
            recovery = directory / f"restore-{index}"
            if self.files.kind(recovery) is None:
                self.files.copy(directory / f"before-{index}", recovery, original)
            if not self.files.matches(recovery, original):
                raise policy.Refusal("ROLLBACK_BACKUP_INVALID", 5)
            if current is None:
                self.files.restore_absent(recovery, target)
            else:
                # An interrupted restoration may leave a displaced target.
                # Allocate a safe, fresh name rather than overwrite evidence.
                removed = directory / f"removed-{index}"
                if self.files.kind(removed) is not None:
                    raise policy.Refusal("ROLLBACK_BLOCKED_EXTERNAL_CHANGE", 5)
                self.files.replace_owned(recovery, target, removed, current)
        if not self.matches_release(before):
            raise policy.Refusal("ROLLBACK_HASH_MISMATCH", 5)
        if ownership is not None:
            self.files.attest_owner()

    def recover(self, state):
        value = self.files.read(self.journal_path, 16384)
        if value is None:
            return False
        row, before, prior = self.parse_journal(value)
        target = self.catalogue.target
        if state != prior and not (row["phase"] == "verified" and state == target.state):
            raise policy.Refusal("RECOVERY_STATE_CHANGED", 5)
        directory = self.files.transaction_workspace(row["workspace"])
        ownership = row.get("ownership")
        paths = self.transaction_paths(before, ownership, patch=row["mode"] == "patch")
        self.files.ensure_closed()
        if row["phase"] == "verified" and state == target.state:
            if not self.matches_release(target):
                raise policy.Refusal("RECOVERY_TARGET_CHANGED", 5)
            self.files.attest_owner()
            self.check_unowned_loaders(target)
        else:
            self.rollback(directory, paths, before, target, ownership)
        self.finish(directory, paths)
        return True

    def verify_staging(self, stage, stock):
        with self.files.pinned(stage, directory=True):
            seen, queue = set(), [stage]
            while queue:
                folder = queue.pop()
                with self.files.pinned(folder, directory=True):
                    for item in folder.iterdir():
                        if self.files.kind(item) == "directory":
                            queue.append(item)
                            continue
                        relative = item.relative_to(stage).as_posix()
                        policy.reject("STAGED_PAYLOAD_MISMATCH", relative not in stock
                                      or not self.files.matches(item, stock[relative]))
                        seen.add(relative)
            policy.reject("STAGED_PAYLOAD_MISMATCH", seen != set(stock))

    def apply(self, stage, *, patch, uninstaller=None):
        state = self.read_state()
        self.catalogue.check_high_water(state)
        pending = self.fresh_pending(state)
        if pending and self.files.kind(self.journal_path) is not None:
            raise policy.Refusal("FRESH_INSTALLATION_CONFLICT", 3)
        recovered = self.recover(state)
        state = self.read_state()
        before = self.observed_release()
        decision = self.catalogue.decide(before, state, patch=patch)
        if decision == "current":
            if pending or state != self.catalogue.target.state:
                self.commit_setup()
                return "committed_existing"
            return "already_current"
        policy.reject("FRESH_INSTALLATION_CONFLICT", pending)
        policy.reject("USE_FULL_SETUP_FIRST", decision == "fresh")
        target = self.catalogue.target
        expanded = before.payload.keys() != target.payload.keys()
        ownership = None
        if expanded:
            policy.reject("SETUP_NEW_UNINSTALLER_REQUIRED", patch or uninstaller is None)
            policy.reject("UNAPPROVED_UNINSTALLER_STAGE",
                          uninstaller != stage.parent / "reader-uninstaller.generated")
            self.files.attest_owner()
            owner_before = self.files.inspect(self.files.install / "Uninstall.exe")
            owner_after = self.files.inspect(uninstaller)
            policy.reject("INVALID_NEW_UNINSTALLER", owner_after is None or not 0 < owner_after.size <= 100 * 1024 * 1024)
            ownership = {"before": owner_before.digest, "after": owner_after.digest}
        paths = self.transaction_paths(before, ownership, patch=patch)
        old, new = self.transaction_hashes(before, target, ownership)
        stock = {key: target.payload[key] for key in paths} if patch else target.payload
        self.verify_staging(stage, stock)
        self.files.ensure_closed()
        directory = self.files.allocate_transaction_workspace()
        fingerprints = []
        # Until the journal is flushed, only write to the private work area.
        for index, name in enumerate(paths):
            installed = self.files.install / name
            original = self.files.inspect(installed)
            policy.reject("BASELINE_CHANGED_BEFORE_BACKUP",
                          (original is None) != (name not in old) or original is not None and original.digest != old[name])
            if original is not None:
                self.files.copy(installed, directory / f"before-{index}", old[name])
            source = uninstaller if name in ("Uninstall.exe", "uninstaller.copy") else stage / name
            self.files.copy(source, directory / f"after-{index}", new[name])
            fingerprints.append(original)
        row = {**self.record_scope(), "workspace": directory.name, "before": before.state.as_json(),
               "target": target.state.as_json(), "state_before": None if state is None else state.as_json(),
               "phase": "prepared", "mode": "patch" if patch else "setup"}
        if ownership is not None:
            row["ownership"] = ownership
        self.files.write_record(self.journal_path, row)
        self.checkpoint("prepared")
        try:
            policy.reject("BASELINE_CHANGED_BEFORE_REPLACE", not self.matches_release(before))
            self.files.ensure_closed()
            for index, name in enumerate(paths):
                displaced = directory / f"displaced-{index}"
                destination = self.files.install / name
                if fingerprints[index] is None:
                    self.files.ensure_payload_directory(destination.parent)
                    self.files.restore_absent(directory / f"after-{index}", destination)
                else:
                    self.files.replace_owned(directory / f"after-{index}", destination,
                                             displaced, fingerprints[index])
                    policy.reject("DISPLACED_FILE_HASH_MISMATCH", not self.files.matches(displaced, old[name]))
                self.checkpoint("after_replace")
            policy.reject("TARGET_HASH_MISMATCH", not self.matches_release(target))
            self.check_unowned_loaders(target)
            self.files.attest_owner()
            if target.self_test:
                self.files.health()
            self.checkpoint("checked")
            row["phase"] = "verified"
            self.files.write_record(self.journal_path, row)
            self.checkpoint("verified")
            self.files.write_record(self.state_path, target.state.as_json())
            self.checkpoint("committed")
        except (OSError, policy.Refusal):
            try:
                if self.read_state() == target.state and state != target.state:
                    raise policy.Refusal("UPDATE_RECOVERY_REQUIRED", 5)
                self.rollback(directory, paths, before, target, ownership)
                self.finish(directory, paths)
            except OSError:
                raise policy.Refusal("ROLLBACK_IO_BLOCKED", 5) from None
            raise policy.Refusal("PATCH_ROLLED_BACK" if patch else "SETUP_ROLLED_BACK", 4) from None
        self.finish(directory, paths)
        return "recovered_and_applied" if recovered else ("repaired" if decision == "repair" else "applied")


def load_catalogue(argument):
    if getattr(sys, "frozen", False):
        # NSIS can pass its extracted catalogue for traceability. The frozen
        # embedded data dictates the trusted identity and permitted baselines.
        data = EMBEDDED_CATALOGUE
        if data is None:
            data = (Path(sys._MEIPASS) / "update-catalogue.json").read_bytes()
        policy.reject("INVALID_EMBEDDED_CATALOGUE", type(data) is not bytes)
        if argument is not None:
            with argument.open("rb") as file:
                policy.reject("CATALOGUE_PIN_MISMATCH", file.read(MAX_CATALOGUE + 1) != data)
    else:
        policy.reject("CATALOGUE_REQUIRED", argument is None)
        with argument.open("rb") as file:
            data = file.read(MAX_CATALOGUE + 1)
    policy.reject("CATALOGUE_TOO_LARGE", len(data) > MAX_CATALOGUE)
    return policy.Catalogue.from_json(policy.parse_json(data))


def run_action(args, catalogue, files):
    if args.action in ("relocate-guard", "relocate"):
        # The independent C-to-D coordinator cannot retain the normal update
        # lock while waiting for the recorded C uninstaller to finish.
        import relocation

        if args.action == "relocate-guard":
            code = relocation.guard(catalogue, files)
            states = {0: "ordinary_setup", 20: "relocation_required",
                      21: "relocation_trial_verified", 22: "relocation_recovery_required"}
            policy.reject("INVALID_RELOCATION_DECISION", type(code) is not int or code not in states)
            return states[code], code
        if args.operation == "stage":
            _, registry = windows_api()
            paths = {name: registry.local_path(getattr(args, name)) for name in RELOCATION_PATHS}
            language = args.installer_language
        else:
            paths = dict.fromkeys(RELOCATION_PATHS)
            language = None
        return relocation.migrate(catalogue, files, **paths, installer_language=language,
                                  operation=args.operation), 0

    updater = Updater(catalogue, files)
    with files.lock():
        if files.kind(files.control / RELOCATION_JOURNAL) is not None:
            raise policy.Refusal("RELOCATION_REQUIRES_SAME_SETUP", 5)
        if args.action == "guard":
            observed = updater.status()
            return observed, {"fresh": 0, "current": 10, "adopt_current": 12}.get(observed, 11)
        if args.action == "setup-begin":
            return updater.begin_setup(), 0
        if args.action == "setup-commit":
            return updater.commit_setup(), 0
        if args.action == "uninstall-guard":
            return updater.uninstall_guard(), 0
        _, registry = windows_api()
        uninstaller = getattr(args, "uninstaller", None)
        return updater.apply(registry.local_path(args.payload), patch=args.action == "patch",
                             uninstaller=None if uninstaller is None else registry.local_path(uninstaller)), 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("guard", "setup-begin", "setup-commit", "uninstall-guard", "relocate-guard"):
        sub.add_parser(action)
    for action in ("patch", "setup-apply"):
        command = sub.add_parser(action)
        command.add_argument("--payload", required=True, type=Path)
        if action == "setup-apply":
            command.add_argument("--uninstaller", type=Path)
    relocate = sub.add_parser("relocate")
    relocate.add_argument("--operation", required=True, choices=("stage", "commit", "cancel", "recover"))
    for name in RELOCATION_PATHS:
        relocate.add_argument("--" + name.replace("_", "-"), type=Path)
    relocate.add_argument("--installer-language", type=int, choices=(1033, 1041, 1042))
    args = parser.parse_args(argv)
    if args.action == "relocate":
        inputs = (getattr(args, name) for name in (*RELOCATION_PATHS, "installer_language"))
        supplied = [value is not None for value in inputs]
        if args.operation == "stage" and not all(supplied):
            relocate.error("stage requires all relocation paths and --installer-language")
        if args.operation != "stage" and any(supplied):
            relocate.error("only stage accepts relocation paths or --installer-language")
    try:
        policy.reject("PACKAGED_UPDATER_REQUIRED", not getattr(sys, "frozen", False))
        catalogue = load_catalogue(args.catalogue)
        files = WindowsOperations.for_user()
        observed, code = run_action(args, catalogue, files)
    except policy.Refusal as exc:
        observed, code = exc.code, exc.exit_code
    except (OSError, ValueError, RuntimeError) as exc:
        observed, code = "WINDOWS_IO_OR_PATH_REFUSED", 2
        # State diagnostics never echo input paths or account-specific details.
        print(json.dumps({"status": observed, "winerror": getattr(exc, "winerror", None),
                          "exit": code}, separators=(",", ":")), flush=True)
        return code
    print(json.dumps({"status": observed, "exit": code}, separators=(",", ":")), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

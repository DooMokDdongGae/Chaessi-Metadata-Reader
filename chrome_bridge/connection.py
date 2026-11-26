"""One authenticated local bridge owned by the reader window's lifetime."""
import ctypes
import os
import time
from ctypes import wintypes

from bundle.model import decode_bundle
from chrome_bridge.automatic import AutomaticBridge
from chrome_bridge.key_store import BridgeKeyStore, PairingKeyError
from chrome_bridge.server import PORT


def chrome_running():
    """Read process names only; never inspect Chrome profiles, arguments or pages."""
    if os.name != "nt":
        return None
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel.CreateToolhelp32Snapshot
    snapshot.argtypes, snapshot.restype = [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE
    first, next_entry, close = kernel.Process32FirstW, kernel.Process32NextW, kernel.CloseHandle
    first.argtypes = next_entry.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    first.restype = next_entry.restype = wintypes.BOOL
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    handle = snapshot(2, 0)
    if handle in (None, ctypes.c_void_p(-1).value):
        return None
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        available = first(handle, ctypes.byref(entry))
        while available:
            if entry.szExeFile.lower() == "chrome.exe":
                return True
            available = next_entry(handle, ctypes.byref(entry))
        return False
    finally:
        close(handle)


class ReaderConnection:
    def __init__(self, *, key_store=None, port=PORT, _recover=False):
        self.keys = key_store if key_store is not None else BridgeKeyStore()
        self.first_run = False
        def initialize_pairing():
            value, self.first_run = self.keys.recover() if _recover else self.keys.load()
            return value
        self.bridge = AutomaticBridge(port=port, key_provider=initialize_pairing)
        self._last_process_check = 0
        self._chrome_running = None
        self._disconnected_since = time.monotonic()
        self.closed = False

    @classmethod
    def recover_pairing(cls, *, key_store=None, port=PORT):
        return cls(key_store=key_store, port=port, _recover=True)

    def copy_pairing_key(self, copy_callback):
        """Pass the verified active key directly to an explicit user copy action."""
        with self.bridge.lock:
            if self.closed or self.bridge.stopping:
                raise PairingKeyError("PAIRING_KEY_BUSY")
            self.keys.verify(self.bridge.token)
            copy_callback(self.bridge.token)

    def import_legacy_folder(self, selected_reader_folder):
        return self.bridge.change_pairing(
            lambda active: self.keys.import_folder(selected_reader_folder, active))

    def state(self):
        if self.closed:
            return "연결 종료"
        if self.bridge.snapshot()["connected"]:
            self._disconnected_since = None
            return "연결됨"
        now = time.monotonic()
        if self._disconnected_since is None:
            self._disconnected_since = now
        if now - self._last_process_check >= 3:
            self._chrome_running = chrome_running()
            self._last_process_check = now
        if self._chrome_running is False:
            return "Chrome 실행 필요"
        if now - self._disconnected_since >= 65:
            return "Chrome 확장 확인 필요"
        return "연결 복구 중"

    def read_link(self, url, progress):
        return decode_bundle(self.bridge.request(url, progress, timeout=120))

    def read_inspect(self, progress):
        return decode_bundle(self.bridge.request_inspect(progress, timeout=120))

    def close(self):
        if not self.closed:
            self.closed = True
            self.bridge.close()

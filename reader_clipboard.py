"""Copy one exact prompt to the Windows clipboard as CF_UNICODETEXT."""

import ctypes
import sys
import time
from ctypes import wintypes


class ClipboardError(Exception):
    """A message suitable for the reader's status area."""


def _bind(library, name, restype, *argtypes):
    function = getattr(library, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


if sys.platform == "win32":
    _user = ctypes.WinDLL("user32", use_last_error=True)
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _is_window = _bind(_user, "IsWindow", wintypes.BOOL, wintypes.HWND)
    _open = _bind(_user, "OpenClipboard", wintypes.BOOL, wintypes.HWND)
    _close = _bind(_user, "CloseClipboard", wintypes.BOOL)
    _empty = _bind(_user, "EmptyClipboard", wintypes.BOOL)
    _set = _bind(_user, "SetClipboardData", wintypes.HANDLE, wintypes.UINT, wintypes.HANDLE)
    _register = _bind(_user, "RegisterClipboardFormatW", wintypes.UINT, wintypes.LPCWSTR)
    _alloc = _bind(_kernel, "GlobalAlloc", wintypes.HGLOBAL, wintypes.UINT, ctypes.c_size_t)
    _lock = _bind(_kernel, "GlobalLock", ctypes.c_void_p, wintypes.HGLOBAL)
    _unlock = _bind(_kernel, "GlobalUnlock", wintypes.BOOL, wintypes.HGLOBAL)
    _free = _bind(_kernel, "GlobalFree", wintypes.HGLOBAL, wintypes.HGLOBAL)


def copy_text(owner_hwnd: int, text: str, *, private=False) -> None:
    """Preserve the caller's Unicode text and line endings, including an empty string."""
    if sys.platform != "win32":
        raise ClipboardError("이 복사 기능은 Windows에서 사용할 수 있습니다.")
    if not isinstance(text, str):
        raise ClipboardError("복사할 텍스트가 없습니다.")
    if "\x00" in text:
        raise ClipboardError("원문에 NUL 문자가 있어 Windows 클립보드에 그대로 복사할 수 없습니다.")
    try:
        data = text.encode("utf-16-le") + b"\x00\x00"
    except UnicodeEncodeError as exc:
        raise ClipboardError("원문에 불완전한 유니코드 문자가 있어 복사할 수 없습니다.") from exc
    if not owner_hwnd or not _is_window(owner_hwnd):
        raise ClipboardError("복사에 사용할 창을 찾을 수 없습니다.")

    # Prepare the entire movable buffer before changing clipboard ownership.
    handle = _alloc(0x0002, len(data))  # GMEM_MOVEABLE
    if not handle:
        raise ClipboardError("복사할 메모리를 확보할 수 없습니다.")
    opened = False
    marker = None
    try:
        if private:
            format_id = _register("ExcludeClipboardContentFromMonitorProcessing")
            marker = _alloc(0x0042, 1)  # GMEM_MOVEABLE | GMEM_ZEROINIT
            if not format_id or not marker:
                raise ClipboardError("보호된 복사를 준비할 수 없습니다.")
        pointer = _lock(handle)
        if not pointer:
            raise ClipboardError("복사할 메모리를 열 수 없습니다.")
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            ctypes.set_last_error(0)
            if not _unlock(handle) and ctypes.get_last_error() != 0:
                raise ClipboardError("복사할 메모리를 준비할 수 없습니다.")

        for attempt in range(5):
            if _open(owner_hwnd):
                opened = True
                break
            if attempt < 4:
                time.sleep(0.02)
        if not opened:
            raise ClipboardError("클립보드를 열 수 없습니다. 잠시 후 다시 복사해 주세요.")
        if not _empty():
            raise ClipboardError("Windows 클립보드에 원문을 기록할 수 없습니다.")
        if marker:
            if not _set(format_id, marker):
                raise ClipboardError("보호된 복사를 준비할 수 없습니다.")
            marker = None
        if not _set(13, handle):  # CF_UNICODETEXT
            raise ClipboardError("Windows 클립보드에 원문을 기록할 수 없습니다.")
        handle = None  # SetClipboardData transferred ownership to Windows.
    finally:
        if marker:
            _free(marker)
        if handle:
            _free(handle)
        if opened and not _close():
            raise ClipboardError("Windows 클립보드를 닫을 수 없습니다.")

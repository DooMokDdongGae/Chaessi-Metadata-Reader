"""File drops and image paste owned by this Reader's Windows UI thread."""
import ctypes
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass

from reader_app import PNG_BATCH_COUNT, PNG_LIMIT
from reader_parser import PNG_SIGNATURE


CF_TEXT, CF_BITMAP, CF_OEMTEXT, CF_DIB, CF_UNICODETEXT, CF_HDROP, CF_DIBV5 = 1, 2, 7, 8, 13, 15, 17
WM_DROPFILES, WM_NCDESTROY = 0x0233, 0x0082
MAX_PATH_CHARS = 32767
PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
MAX_CLIPBOARD_PADDING = 4096


@dataclass(frozen=True)
class ImageInput:
    paths: tuple[str, ...] = ()
    png: bytes | None = None
    error: str | None = None


def clipboard_format(available, png_formats, *, editing):
    if CF_HDROP in available:
        return CF_HDROP
    if editing and available & {CF_UNICODETEXT, CF_TEXT, CF_OEMTEXT}:
        return None
    return next((fmt for fmt in (*png_formats, CF_DIBV5, CF_DIB, CF_BITMAP) if fmt in available), None)


def png_clipboard_bytes(data):
    """Remove only bounded zero allocation padding immediately after IEND."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("bad PNG signature")
    if not data.endswith(PNG_IEND):
        trimmed = data.rstrip(b"\x00")
        if len(data) - len(trimmed) <= MAX_CLIPBOARD_PADDING and trimmed.endswith(PNG_IEND):
            data = trimmed
    if len(data) > PNG_LIMIT:
        raise ValueError("PNG too large")
    return data


class WindowsImageInput:
    def __init__(self, blocked, generation):
        user = ctypes.WinDLL("user32", use_last_error=True)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        control = ctypes.WinDLL("comctl32", use_last_error=True)
        h, u, b = wintypes.HANDLE, wintypes.UINT, wintypes.BOOL
        up, ip = ctypes.c_size_t, ctypes.c_ssize_t
        subclass_proc = ctypes.WINFUNCTYPE(ip, wintypes.HWND, u, up, ip, up, up)
        self.callback = subclass_proc(self.window_message)
        self.blocked = blocked
        self.generation = generation

        def api(dll, name, result, *arguments):
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, arguments
            return fn

        self.ancestor = api(user, "GetAncestor", h, h, u)
        self.foreground_window = api(user, "GetForegroundWindow", h)
        self.enabled_window = api(user, "IsWindowEnabled", b, h)
        self.open_clipboard = api(user, "OpenClipboard", b, h)
        self.close_clipboard = api(user, "CloseClipboard", b)
        self.has_format = api(user, "IsClipboardFormatAvailable", b, u)
        self.get_data = api(user, "GetClipboardData", h, u)
        register = api(user, "RegisterClipboardFormatW", u, wintypes.LPCWSTR)
        self.png_formats = tuple(fmt for fmt in map(register, ("PNG", "image/png")) if fmt)
        self.accept = api(shell, "DragAcceptFiles", None, h, b)
        self.query = api(shell, "DragQueryFileW", u, h, u, wintypes.LPWSTR, u)
        self.finish = api(shell, "DragFinish", None, h)
        self.size = api(kernel, "GlobalSize", up, h)
        self.lock = api(kernel, "GlobalLock", ctypes.c_void_p, h)
        self.unlock = api(kernel, "GlobalUnlock", b, h)
        self.install = api(control, "SetWindowSubclass", b, h, subclass_proc, up, up)
        self.remove = api(control, "RemoveWindowSubclass", b, h, subclass_proc, up)
        self.next_message = api(control, "DefSubclassProc", ip, h, u, up, ip)
        self.hwnds = set()
        self.drops = deque(maxlen=4)

    def top(self, hwnd):
        return self.ancestor(hwnd, 2) or hwnd  # GA_ROOT, not the root owner.

    def attach(self, hwnd):
        # Tk has a client HWND and a Windows window-manager wrapper. Register
        # both possible recipients without subclassing individual text fields.
        for target in (hwnd, self.top(hwnd)):
            if target not in self.hwnds and self.install(target, self.callback, 1, 0):
                self.hwnds.add(target)
                self.accept(target, True)

    def close(self):
        for hwnd in tuple(self.hwnds):
            self.accept(hwnd, False)
            self.remove(hwnd, self.callback, 1)
        self.hwnds.clear()
        self.drops.clear()

    def drop_paths(self, handle):
        count = self.query(handle, 0xFFFFFFFF, None, 0)
        if not count or count > PNG_BATCH_COUNT:
            return ImageInput(error="image_count" if count else "image_unreadable")
        paths = []
        for index in range(count):
            size = self.query(handle, index, None, 0)
            if not 0 < size <= MAX_PATH_CHARS:
                return ImageInput(error="image_unreadable")
            name = ctypes.create_unicode_buffer(size + 1)
            if self.query(handle, index, name, len(name)) != size:
                return ImageInput(error="image_unreadable")
            paths.append(name.value)
        return ImageInput(paths=tuple(paths))

    def window_message(self, hwnd, message, wparam, lparam, _subclass, _data):
        if message == WM_DROPFILES:
            try:
                received_at = self.generation()
                if not self.enabled_window(self.top(hwnd)) or self.blocked():
                    value = ImageInput(error="image_busy")
                else:
                    value = self.drop_paths(wparam)
                self.drops.append((received_at, value))
            except Exception:
                self.drops.append((None, ImageInput(error="image_busy")))
            finally:
                self.finish(wparam)  # The message owns it; the clipboard does not.
            return 0
        if message == WM_NCDESTROY:
            self.hwnds.discard(hwnd)
            self.remove(hwnd, self.callback, 1)
        return self.next_message(hwnd, message, wparam, lparam)

    def paste(self, hwnd, *, editing):
        if self.top(hwnd) != self.foreground_window():
            return None
        formats = (CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_HDROP, CF_DIBV5, CF_DIB, CF_BITMAP, *self.png_formats)

        def choice():
            available = {fmt for fmt in formats if self.has_format(fmt)}
            return clipboard_format(available, self.png_formats, editing=editing)

        if choice() is None:
            return None
        if not self.enabled_window(self.top(hwnd)) or self.blocked():
            return ImageInput(error="image_busy")
        if not self.open_clipboard(hwnd):
            return ImageInput(error="image_clipboard_busy")
        try:
            fmt = choice()  # The clipboard may have changed before we acquired it.
            if fmt is None:
                return None
            if fmt in (CF_DIBV5, CF_DIB, CF_BITMAP):
                return ImageInput(error="image_bitmap")
            handle = self.get_data(fmt)
            if not handle:
                return ImageInput(error="image_unreadable")
            if fmt == CF_HDROP:
                return self.drop_paths(handle)
            size = self.size(handle)
            if not 0 < size <= PNG_LIMIT + MAX_CLIPBOARD_PADDING:
                return ImageInput(error="image_limit" if size else "image_unreadable")
            pointer = self.lock(handle)
            if not pointer:
                return ImageInput(error="image_unreadable")
            try:
                data = ctypes.string_at(pointer, size)
            finally:
                self.unlock(handle)
        finally:
            self.close_clipboard()
        try:
            return ImageInput(png=png_clipboard_bytes(data))
        except ValueError:
            return ImageInput(error="image_limit" if len(data) > PNG_LIMIT else "image_unreadable")

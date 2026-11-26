"""Run native clipboard checks on a new, noninteractive Windows station."""

import ctypes
import json
import subprocess
import sys
import unittest
import uuid
from ctypes import wintypes
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reader_clipboard as clipboard


SYNTHETIC_TEXTS = {
    "multiline": "  (눈:1.2)\r\n조명\n  pond\r끝  ",
    "literal_markup": '<em title="x">&amp;</em>',
    "unicode": "☀🌱e\u0301  한글\t ",
    "empty": "",
    "whitespace": " \t \n  ",
}


class IsolationUnavailable(Exception):
    pass


def _private_test_window():
    """Child process only. No clipboard call occurs until isolation is verified."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def bind(lib, name, result, *args):
        func = getattr(lib, name)
        func.argtypes, func.restype = args, result
        return func

    h, b, d, p = wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p
    string = wintypes.LPCWSTR
    create_station = bind(user, "CreateWindowStationW", h, string, d, d, p)
    set_station = bind(user, "SetProcessWindowStation", b, h)
    get_station = bind(user, "GetProcessWindowStation", h)
    info = bind(user, "GetUserObjectInformationW", b, h, ctypes.c_int, p, d, p)
    create_desktop = bind(user, "CreateDesktopW", h, string, string, p, d, d, p)
    set_desktop = bind(user, "SetThreadDesktop", b, h)
    thread_desktop = bind(user, "GetThreadDesktop", h, d)
    thread_id = bind(kernel, "GetCurrentThreadId", d)
    create_window = bind(
        user, "CreateWindowExW", h, d, string, string, d,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, h, h, h, p
    )

    def checked(value, name):
        if not value:
            raise OSError(ctypes.get_last_error(), name)
        return value

    def object_name(handle):
        name = ctypes.create_unicode_buffer(256)
        size = d()
        checked(info(handle, 2, name, ctypes.sizeof(name), ctypes.byref(size)), "object name")
        return name.value

    # CWF_CREATE_ONLY rules out attaching to an existing station. Standard user
    # accounts may only request the station named by Windows for this logon.
    original_name = object_name(get_station())
    station = create_station("ChaessiClip-" + uuid.uuid4().hex, 1, 0x000F, None)
    if not station:
        named_error = ctypes.get_last_error()
        station = create_station(None, 1, 0x000F, None)
        if not station:
            anon_error = ctypes.get_last_error()
            if named_error == 5 and anon_error in {5, 183}:
                raise IsolationUnavailable(f"new private station denied ({named_error}, {anon_error})")
            raise OSError(anon_error, "create private station")
    station_name = object_name(station)
    if not station_name or station_name.casefold() in {original_name.casefold(), "winsta0"}:
        raise RuntimeError("A distinct noninteractive station is required")
    checked(set_station(station), "set private station")
    desktop_name = "Desk-" + uuid.uuid4().hex
    desktop = checked(create_desktop(desktop_name, None, None, 0, 0x01FF, None), "create private desktop")
    checked(set_desktop(desktop), "set private desktop")
    if object_name(get_station()) != station_name or object_name(thread_desktop(thread_id())) != desktop_name:
        raise RuntimeError("Clipboard checks require the newly created private station and desktop")
    # A system STATIC window is enough to own immediate-rendered CF_UNICODETEXT.
    hwnd = create_window(0, "STATIC", "", 0, 0, 0, 1, 1, -3, None, None, None)
    return checked(hwnd, "create private clipboard owner")


def _isolated_check():
    hwnd = _private_test_window()
    get_data = clipboard._user.GetClipboardData
    get_data.argtypes, get_data.restype = [wintypes.UINT], wintypes.HANDLE
    size = clipboard._kernel.GlobalSize
    size.argtypes, size.restype = [wintypes.HGLOBAL], ctypes.c_size_t
    def verify(expected):
        if not clipboard._open(hwnd):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            handle = get_data(13)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            encoded = (expected + "\0").encode("utf-16-le")
            if size(handle) < len(encoded):
                raise AssertionError("Short CF_UNICODETEXT allocation")
            address = clipboard._lock(handle)
            if not address:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if ctypes.string_at(address, len(encoded)) != encoded:
                    raise AssertionError("CF_UNICODETEXT code units changed")
            finally:
                clipboard._unlock(handle)
        finally:
            clipboard._close()

    for value in SYNTHETIC_TEXTS.values():
        clipboard.copy_text(hwnd, value)
        verify(value)
    for invalid in ["a\x00b", "\ud800"]:
        try:
            clipboard.copy_text(hwnd, invalid)
        except clipboard.ClipboardError:
            verify(SYNTHETIC_TEXTS["whitespace"])
        else:
            raise AssertionError("Unrepresentable text was accepted")
    # The dedicated process exits, releasing all its station, desktop, and window handles.
    return {"private_station": True, "private_desktop": True, "exact_cases": list(SYNTHETIC_TEXTS),
            "rejected_and_preserved": ["embedded_nul", "unpaired_surrogate"]}


@unittest.skipUnless(sys.platform == "win32", "Windows clipboard")
class WindowsClipboardTests(unittest.TestCase):
    def test_exact_native_clipboard_in_isolation(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--isolated"],
            capture_output=True, timeout=20, check=False
        )
        if result.returncode == 77:
            self.skipTest(result.stdout.decode().strip())
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        evidence = json.loads(result.stdout)
        self.assertTrue(evidence["private_station"] and evidence["private_desktop"])
        self.assertEqual(len(evidence["exact_cases"]), 5)
        self.assertEqual(len(evidence["rejected_and_preserved"]), 2)

    def test_private_copy_sends_history_exclusion_before_text(self):
        with mock.patch.object(clipboard, "_is_window", return_value=True), \
             mock.patch.object(clipboard, "_open", return_value=True), \
             mock.patch.object(clipboard, "_empty", return_value=True), \
             mock.patch.object(clipboard, "_close", return_value=True), \
             mock.patch.object(clipboard, "_register", return_value=0xC123) as register, \
             mock.patch.object(clipboard, "_set", return_value=1) as recipient:
            clipboard.copy_text(1, "synthetic pairing test", private=True)
            register.assert_called_once_with("ExcludeClipboardContentFromMonitorProcessing")
            handles = [call.args for call in recipient.call_args_list]
            try:
                self.assertEqual([fmt for fmt, handle in handles], [0xC123, 13])
            finally:
                for _, handle in handles:
                    clipboard._free(handle)
            recipient.reset_mock()
            recipient.return_value = 0
            with self.assertRaises(clipboard.ClipboardError):
                clipboard.copy_text(1, "synthetic pairing test", private=True)
            self.assertEqual([call.args[0] for call in recipient.call_args_list], [0xC123])

    def test_exact_windows_allocation_with_synthetic_recipient(self):
        # The production allocator and encoder run unchanged. Only the recipient
        # is substituted; this process never invokes user clipboard functions.
        with mock.patch.object(clipboard, "_is_window", return_value=True), \
             mock.patch.object(clipboard, "_open", return_value=True), \
             mock.patch.object(clipboard, "_empty", return_value=True), \
             mock.patch.object(clipboard, "_close", return_value=True), \
             mock.patch.object(clipboard, "_set", return_value=1) as recipient:
            for label, value in SYNTHETIC_TEXTS.items():
                with self.subTest(label=label):
                    clipboard.copy_text(1, value)
                    fmt, handle = recipient.call_args.args
                    self.assertEqual(fmt, 13)
                    pointer = clipboard._lock(handle)
                    try:
                        self.assertTrue(pointer)
                        expected = (value + "\0").encode("utf-16-le")
                        self.assertEqual(ctypes.string_at(pointer, len(expected)), expected)
                    finally:
                        clipboard._unlock(handle)
                        clipboard._free(handle)

    def test_unrepresentable_input_fails_before_clipboard_access(self):
        with mock.patch.object(clipboard, "_open") as open_clipboard:
            for invalid in ["a\x00b", "\ud800"]:
                with self.assertRaises(clipboard.ClipboardError):
                    clipboard.copy_text(1, invalid)
            open_clipboard.assert_not_called()

    def test_busy_clipboard_reports_failure(self):
        # Only real allocation calls run here, all clipboard access is stubbed.
        with mock.patch.object(clipboard, "_is_window", return_value=True), \
             mock.patch.object(clipboard, "_open", return_value=False), \
             mock.patch.object(clipboard, "_empty") as empty:
            with self.assertRaisesRegex(clipboard.ClipboardError, "열 수 없습니다"):
                clipboard.copy_text(1, "synthetic")
            empty.assert_not_called()

    def test_invalid_owner_does_not_open_clipboard(self):
        with mock.patch.object(clipboard, "_open") as open_clipboard:
            with self.assertRaises(clipboard.ClipboardError):
                clipboard.copy_text(0, "synthetic")
            open_clipboard.assert_not_called()


if __name__ == "__main__":
    if sys.argv[1:] == ["--isolated"]:
        try:
            print(json.dumps(_isolated_check()))
        except IsolationUnavailable as exc:
            print(str(exc))
            sys.exit(77)
    else:
        unittest.main()

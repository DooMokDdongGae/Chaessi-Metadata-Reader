"""Bounded local PNG ingestion and editor state with synthetic input."""
from collections import deque
from pathlib import Path
import ctypes
import json
import struct
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import zlib

from bundle.i18n import Language
from bundle.image_input_win import (CF_DIB, CF_HDROP, CF_UNICODETEXT, WM_DROPFILES,
                                   ImageInput, WindowsImageInput, clipboard_format, png_clipboard_bytes)
from bundle.model import Card, FORMAT
from bundle.window import BundleReader
from reader_app import read_png_batch
from reader_parser import PNG_SIGNATURE


def chunk(kind, content):
    return (struct.pack(">I", len(content)) + kind + content
            + struct.pack(">I", zlib.crc32(kind + content)))


def png(**metadata):
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    labels = b"".join(chunk(b"iTXt", name.encode("ascii") + b"\0\0\0\0\0" + value.encode("utf-8"))
                      for name, value in metadata.items())
    return PNG_SIGNATURE + header + labels + chunk(b"IDAT", zlib.compress(b"\0" * 4)) + chunk(b"IEND", b"")


class ImageInputModelTests(unittest.TestCase):
    def test_clipboard_file_list_and_editor_text_precedence(self):
        png_format = 50100
        bmp_and_text = {CF_UNICODETEXT, CF_DIB}
        self.assertEqual(clipboard_format(bmp_and_text | {CF_HDROP}, (png_format,), editing=True), CF_HDROP)
        self.assertIsNone(clipboard_format(bmp_and_text, (png_format,), editing=True))
        self.assertIsNone(clipboard_format({png_format, CF_UNICODETEXT}, (png_format,), editing=True))
        self.assertEqual(clipboard_format({png_format}, (png_format,), editing=True), png_format)
        self.assertEqual(clipboard_format(bmp_and_text, (png_format,), editing=False), CF_DIB)
        self.assertIsNone(clipboard_format({CF_UNICODETEXT}, (png_format,), editing=False))

    def test_windows_allocator_padding_does_not_relax_file_parser(self):
        valid = png(prompt="quiet garden")
        self.assertEqual(png_clipboard_bytes(valid + b"\0" * 19), valid)
        self.assertEqual(png_clipboard_bytes(valid + b"\0" * 4097), valid + b"\0" * 4097)
        self.assertEqual((read_png_batch(png=valid + b"\0" * 19)[0].status), "failed")
        self.assertEqual(read_png_batch(png=png_clipboard_bytes(valid + b"\0" * 19))[0].status, "ok")
        with self.assertRaises(ValueError):
            png_clipboard_bytes(b"no PNG")

    def test_metadata_keys_cannot_rename_png_to_a_work_envelope(self):
        original = ' \r\n{"prompt": "한글と🌙", "uc": "\\t"}\r\n '
        (card,) = read_png_batch(png=png(Software="NovelAI", Comment=original, format=FORMAT, images="untrusted"))
        self.assertEqual(card.origin, "local_png")
        self.assertEqual(card.readable, original)
        self.assertEqual(card.fields(), [("Base Positive", "한글と🌙"), ("Base Undesired", "\t")])

    def test_ordered_partial_result_and_per_input_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            inputs = [
                ("first.png", png(prompt="first")),
                ("pixel-only.png", png()),
                ("other.jpg", b"wrong type"),
                ("last.png", png(prompt="last")),
            ]
            paths = [folder / name for name, _ in inputs]
            for path, (_, content) in zip(paths, inputs):
                path.write_bytes(content)
            cards = read_png_batch(paths=paths)
            self.assertEqual([card.filename for card in cards], [path.name for path in paths])
            self.assertEqual([card.status for card in cards], ["ok", "missing", "failed", "ok"])
            self.assertEqual([card.base for card in cards], ["first", None, None, "last"])
            self.assertEqual(json.loads(cards[-1].readable), {"prompt": "last"})
            with patch("reader_app.PNG_BATCH_LIMIT", len(inputs[0][1])):
                self.assertEqual([card.issue for card in read_png_batch(paths=paths[::3])],
                                 [None, "too_large"])
            with patch("reader_app.PNG_LIMIT", len(inputs[0][1]) - 1):
                self.assertEqual(read_png_batch(paths=paths[:1])[0].issue, "too_large")
            self.assertEqual(read_png_batch(paths=["untrusted.png"])[0].issue, "local_path")
        with self.assertRaises(ValueError):
            read_png_batch(paths=("more.png",) * 33)

    def test_large_original_is_not_exposed_as_incomplete_copy(self):
        with patch("bundle.model.PNG_ORIGINAL_LIMIT", 10):
            (card,) = read_png_batch(png=png(prompt="quiet garden"))
        self.assertEqual(card.base, "quiet garden")
        self.assertIsNone(card.readable)
        self.assertEqual(card.issue, "original_limit")

    def test_native_receive_blocks_immediately_and_finishes_owned_drop(self):
        native = WindowsImageInput.__new__(WindowsImageInput)
        native.top = lambda hwnd: hwnd
        native.generation = lambda: 7
        native.enabled_window = lambda hwnd: True
        native.blocked = Mock(return_value=True)
        native.drops = deque()
        native.drop_paths = Mock(return_value=ImageInput(paths=("fixture.png",)))
        native.finish = Mock()
        self.assertEqual(native.window_message(10, WM_DROPFILES, 99, 0, 1, 0), 0)
        native.drop_paths.assert_not_called()
        native.finish.assert_called_once_with(99)
        self.assertEqual(native.drops.popleft(), (7, ImageInput(error="image_busy")))
        native.blocked.return_value = False
        native.window_message(10, WM_DROPFILES, 100, 0, 1, 0)
        self.assertEqual(native.drops.popleft(), (7, ImageInput(paths=("fixture.png",))))
        native.drop_paths.assert_called_once_with(100)


class ImageInputTkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close)
        with patch.object(tk.Misc, "focus_set", autospec=True):
            self.reader = BundleReader(self.root, automatic=False,
                                       language=Language(preference_path=Path(self.temp.name) / "language.json"))
        self.reader.ui.set("ko")
        card = Card("ok", "Format: NAI\nsource", "characters", "base", "", (("character", "negative"),))
        self.reader.present([card, card], "fixture")

    def close(self):
        if hasattr(self, "reader") and self.reader.timer:
            self.root.after_cancel(self.reader.timer)
        self.root.destroy()

    def spin(self):
        end = time.monotonic() + 3
        while self.reader.running and time.monotonic() < end:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.reader.running)

    def test_expanded_field_keeps_widget_caret_selection_and_undo(self):
        panels = self.reader.prompts
        field = "Character 1 Positive"
        area = panels.panels[field][0]
        other = panels.panels["Character 1 Undesired"][0]
        area.insert("end-1c", " walking")
        area.mark_set("insert", "1.4")
        area.tag_add("sel", "1.3", "1.7")
        cursor, selection = area.index("insert"), area.get("sel.first", "sel.last")
        panels.activate(field)
        panels.expand_action.invoke()
        self.root.update_idletasks()
        self.assertIs(panels.panels[field][0], area)
        self.assertGreater(int(area.cget("height")), 3)
        self.assertEqual(int(other.cget("height")), 3)
        self.assertEqual(area.index("insert"), cursor)
        self.assertEqual(area.get("sel.first", "sel.last"), selection)
        self.assertEqual(panels.expand_action.cget("text"), "접기")
        self.reader.ui.set("en")
        self.assertEqual(panels.expand_action.cget("text"), "Collapse")
        panels.toggle_expanded("Base Positive")
        self.root.update_idletasks()
        self.assertEqual(int(area.cget("height")), 3)
        self.assertIs(panels.panels[field][0], area)
        area.edit_undo()
        self.assertEqual(area.get("1.0", "end-1c"), "character")
        self.reader.list.selection_clear(0, "end")
        self.reader.list.selection_set(1)
        self.reader.show_card()
        self.assertIsNone(panels.expanded)
        self.assertEqual(int(panels.panels["Base Positive"][0].cget("height")), 3)

    def test_partial_cancel_and_pending_transfer_keep_all_current_state(self):
        field = "Base Positive"
        area = self.reader.prompts.panels[field][0]
        area.insert("end-1c", " edited")
        self.reader.queue_field(field, False)
        original = self.reader.cards
        (entry,) = self.reader.transfer.items
        self.reader.transfer.pending = object()
        self.assertFalse(self.reader.start_image_input(ImageInput(png=png(prompt="new"))))
        self.assertIs(self.reader.transfer.items[0], entry)
        self.reader.transfer.pending = None
        good = Path(self.temp.name) / "good.png"
        missing = Path(self.temp.name) / "pixel.png"
        good.write_bytes(png(prompt="new"))
        missing.write_bytes(png())
        with patch("bundle.window.theme.confirm", return_value=False) as confirm:
            self.assertTrue(self.reader.start_image_input(ImageInput(paths=(str(good), str(missing)))))
            self.assertFalse(self.reader.start_image_input(ImageInput(png=png(prompt="second"))))
            self.spin()
        confirm.assert_called_once()
        body = confirm.call_args.args[2]
        self.assertIn("읽은 PNG 1장", body)
        self.assertIn("프롬프트 없음 1장", body)
        self.assertIn("현재 세션", body)
        self.assertIs(self.reader.cards, original)
        self.assertIs(self.reader.transfer.items[0], entry)
        self.assertEqual(area.get("1.0", "end-1c"), "base edited")
        with patch("bundle.window.theme.confirm", return_value=True) as confirm:
            self.assertTrue(self.reader.start_image_input(ImageInput(paths=(str(good), str(missing)))))
            self.spin()
        confirm.assert_called_once()
        self.assertEqual([card.status for card in self.reader.cards], ["ok", "missing"])
        self.assertEqual(self.reader.source, "local_png")
        self.assertFalse(self.reader.transfer.items)
        self.reader.toggle_raw()
        self.assertEqual(self.reader.raw_label.cget("text"), "PNG 메타데이터")
        self.assertEqual(json.loads(self.reader.raw.get("1.0", "end-1c")), {"prompt": "new"})

    def test_stale_import_does_not_unlock_active_collection(self):
        self.reader.serial = 8
        self.reader.set_running(True)
        self.reader.events.put((7, "local_done", [Card("ok", "stale", "single", "stale")]))
        try:
            end = time.monotonic() + .2
            while time.monotonic() < end:
                self.root.update()
                time.sleep(.01)
            self.assertTrue(self.reader.running)
            self.assertEqual(self.reader.read_btn.cget("state"), "disabled")
            self.assertEqual(self.reader.cards[0].base, "base")
        finally:
            self.reader.set_running(False)

    @unittest.skipUnless(hasattr(ctypes, "WinDLL"), "Windows clipboard and drop bindings")
    def test_nonmodal_toplevel_shares_early_paste_route(self):
        from types import SimpleNamespace

        aux = tk.Toplevel(self.root)
        aux.withdraw()
        entry = tk.Entry(aux)
        self.reader.tag_image_tree(aux)
        self.assertEqual(entry.bindtags()[0], self.reader.image_paste_tag)
        self.assertIs(entry.winfo_toplevel(), aux)
        with patch.object(self.reader.native_images, "paste", return_value=None) as paste:
            self.assertIsNone(self.reader.paste_image(SimpleNamespace(widget=entry)))
            self.assertEqual(paste.call_args.kwargs, {"editing": True})
        with patch.object(self.reader.native_images, "paste",
                          return_value=ImageInput(png=png(prompt="from nonmodal"))) as paste:
            self.assertEqual(self.reader.paste_image(SimpleNamespace(widget=entry)), "break")
            self.spin()
            self.assertEqual(self.reader.cards[0].base, "from nonmodal")
            self.assertEqual(paste.call_args.kwargs, {"editing": True})

    @unittest.skipUnless(hasattr(ctypes, "WinDLL"), "Windows file-drop delivery")
    def test_native_drop_reaches_own_hwnd_with_synthetic_file_list(self):
        import ctypes.wintypes as win

        def api(dll, name, restype, *argtypes):
            function = getattr(dll, name)
            function.restype, function.argtypes = restype, argtypes
            return function

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        alloc = api(kernel, "GlobalAlloc", win.HANDLE, win.UINT, ctypes.c_size_t)
        lock = api(kernel, "GlobalLock", ctypes.c_void_p, win.HANDLE)
        unlock = api(kernel, "GlobalUnlock", win.BOOL, win.HANDLE)
        free = api(kernel, "GlobalFree", win.HANDLE, win.HANDLE)
        send = api(user, "SendMessageW", ctypes.c_ssize_t, win.HWND, win.UINT, ctypes.c_size_t, ctypes.c_ssize_t)
        path = Path(self.temp.name) / "fixture.png"
        path.write_bytes(png(prompt="from in-process WM_DROPFILES"))
        packed = struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(path) + "\0\0").encode("utf-16-le")
        handle = alloc(2, len(packed))
        self.assertTrue(handle)
        hwnd = self.root.winfo_id()
        native = self.reader.native_images
        if hwnd not in native.hwnds:
            free(handle)
            self.fail("The Reader's own HWND did not register for file drops")
        pointer = lock(handle)
        if not pointer:
            free(handle)
            self.fail("Could not prepare synthetic file names")
        ctypes.memmove(pointer, packed, len(packed))
        unlock(handle)
        self.assertEqual(send(hwnd, WM_DROPFILES, handle, 0), 0)  # Reader now owns HDROP.
        self.assertEqual(len(native.drops), 1)
        _, value = native.drops[0]
        self.assertEqual(value, ImageInput(paths=(str(path),)))
        until = time.monotonic() + 3
        while self.reader.source != "local_png" and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(self.reader.cards[0].base, "from in-process WM_DROPFILES")


if __name__ == "__main__":
    unittest.main()

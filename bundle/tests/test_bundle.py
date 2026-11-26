import json
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bundle.i18n import Language
from bundle.model import FORMAT, decode_bundle, decode_input, summary
from bundle.window import BundleReader


def row(index, **changes):
    return dict({"index": index, "status": "ok", "readable": "프롬프트:\n  종이, (하늘:1.2)\r\n ",
                 "base": "  종이, (하늘:1.2)\r\n ", "negative": None, "structure": "single", "characters": []}, **changes)


def pack(*cards, count=None):
    return dict(format=FORMAT, version=1, count=len(cards) if count is None else count, cards=cards and list(cards) or [])


class ModelTests(unittest.TestCase):
    def test_slots_and_duplicate_text_are_independent(self):
        payload = pack(row(1), row(0), row(2, structure="characters", characters=[
            {"positive": " one character ", "negative": ""}, {"positive": "", "negative": None}]))
        a, b, c = decode_bundle(payload)
        self.assertEqual(a, b)
        self.assertEqual(a.structure, "single")
        self.assertEqual(len(c.characters), 2)
        self.assertEqual(c.fields()[-1:], [("Character 2 Positive", "")])
        self.assertTrue(all(value is not None for _, value in c.fields()))

    def test_partial_failures_preserve_slots_and_raw(self):
        cards = decode_bundle(pack(row(0), row(1, status="empty", readable=""), row(2, status="missing"),
                                   row(3, status="failed"), row(4, characters="bad"), count=6))
        self.assertEqual([c.status for c in cards], ["ok", "empty", "missing", "failed", "ok", "failed"])
        self.assertEqual(cards[4].readable, cards[0].readable)
        self.assertEqual(cards[4].structure, "unknown")
        self.assertIn("읽기 실패 2", summary(cards))

    def test_bad_number_and_duplicate_index_do_not_shift_other_cards(self):
        cards = decode_bundle(pack(row(0), row(0), row("2"), row(3)))
        self.assertEqual([c.status for c in cards], ["failed", "failed", "failed", "ok"])
        with self.assertRaises(ValueError):
            decode_bundle(pack(row(0), count=0))

    def test_injection_invalid_text_and_unsupported_version(self):
        a, b = decode_bundle(pack(row(0, readable="<b>cloud</b>", base="<b>cloud</b>"), row(1, readable="a\0b")))
        self.assertEqual(a.readable, "<b>cloud</b>")
        self.assertEqual(b.status, "failed")
        with self.assertRaises(ValueError):
            decode_input(dict(pack(row(0)), version=True))

    def test_legacy_file_does_not_invent_site_output(self):
        cards = decode_input(json.loads((ROOT / "fixtures/synthetic-work.json").read_bytes()))
        self.assertEqual(len(cards), 2)
        self.assertEqual([c.structure for c in cards], ["single", "characters"])
        self.assertIsNone(cards[1].readable)
        self.assertEqual(cards[1].characters[1][0], "  연필 & 지도  ")
        legacy = decode_input({"format": "image metadata", "prompt": "  pencil ", "uc": ""})
        self.assertEqual(legacy[0].base, "  pencil ")


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        preferences = tempfile.TemporaryDirectory()
        self.addCleanup(preferences.cleanup)
        language = Language(Path(preferences.name) / "language.json")
        language.set("ko")
        self.view = BundleReader(self.root, automatic=False, language=language)
        # Closing a synthetic edited draft during cleanup must never open a prompt.
        discard = patch("bundle.window.theme.confirm", return_value=True)
        discard.start()
        self.addCleanup(discard.stop)
        self.addCleanup(self.view.close)
        self.root.geometry("+20000+20000")
        self.root.update()

    def select(self, index):
        self.view.list.selection_clear(0, "end")
        self.view.list.selection_set(index)
        self.view.list.event_generate("<<ListboxSelect>>")
        self.root.update()

    def field_menu(self, name):
        _, copy_button = self.view.prompts.panels[name]
        menu_button, = (w for w in copy_button.master.winfo_children() if isinstance(w, ttk.Menubutton))
        return self.root.nametowidget(str(menu_button.cget("menu")))

    def test_panels_follow_current_image_and_copy_exact_values(self):
        cards = decode_bundle(pack(
            row(0, base="  (하늘:1.2)\r\n ", negative=""),
            row(1, base=None, negative="한 명", structure="characters", characters=[
                {"positive": "  ☂  ", "negative": None}]),
            row(2, base="셋", negative=None, structure="characters", characters=[
                {"positive": "동일", "negative": ""},
                {"positive": None, "negative": None},
                {"positive": "동일", "negative": "끝\n "}]),
            row(3, status="missing"),
        ))
        expected = [
            [("Base Positive", "  (하늘:1.2)\r\n "), ("Base Undesired", "")],
            [("Base Undesired", "한 명"), ("Character 1 Positive", "  ☂  ")],
            [("Base Positive", "셋"), ("Character 1 Positive", "동일"),
             ("Character 1 Undesired", ""), ("Character 3 Positive", "동일"),
             ("Character 3 Undesired", "끝\n ")],
            [],
        ]
        self.view.present(cards, "합성")
        with patch("bundle.window.copy_text") as sink:
            for index in (0, 1, 2, 3, 1, 0):
                old_controls = [widget for panel in self.view.prompts.panels.values() for widget in panel]
                self.select(index)
                with self.subTest(index=index):
                    panels = self.view.prompts.panels
                    self.assertEqual(list(panels), [name for name, _ in expected[index]])
                    current = {widget for panel in panels.values() for widget in panel}
                    for old in old_controls:
                        if old not in current and old.winfo_exists():
                            self.assertFalse(old.winfo_ismapped())
                    for name, value in expected[index]:
                        area, copy_button = panels[name]
                        self.assertTrue(area.winfo_ismapped())
                        self.assertTrue(copy_button.winfo_ismapped())
                        self.assertEqual(area.cget("state"), "normal")
                        self.assertEqual(area.get("1.0", "end-1c"), value)
                        sink.reset_mock()
                        copy_button.invoke()
                        sink.assert_called_once_with(self.root.winfo_id(), value)

    def test_edit_survives_image_switch_and_only_field_copy_uses_the_edit(self):
        cards = decode_bundle(pack(row(0, negative="원래 제외"), row(1)))
        typed = " 가중치 (달:1.3)\r\n둘째 줄  "
        self.view.present(cards, "합성")
        field = "Base Positive"
        area, _ = self.view.prompts.panels[field]
        area.delete("1.0", "end")
        area.insert("1.0", typed)
        # Change cards before a queued <<Modified>> event can run.
        self.select(1)
        other, _ = self.view.prompts.panels[field]
        self.assertEqual(other.get("1.0", "end-1c"), cards[1].base)
        self.select(0)
        area, copy_button = self.view.prompts.panels[field]
        self.assertEqual(area.get("1.0", "end-1c"), typed)
        self.assertEqual(cards[0].base, cards[1].base)
        negative, _ = self.view.prompts.panels["Base Undesired"]
        self.assertEqual(negative.get("1.0", "end-1c"), "원래 제외")
        with patch("bundle.window.copy_text") as sink:
            copy_button.invoke()
            sink.assert_called_once_with(self.root.winfo_id(), typed)
            sink.reset_mock()
            self.field_menu(field).invoke("원문 복사")
            sink.assert_called_once_with(self.root.winfo_id(), cards[0].base)
            sink.reset_mock()
            self.view.raw_btn.invoke()
            sink.assert_called_once_with(self.root.winfo_id(), cards[0].readable)

    def test_transfer_captures_exact_selection_and_empty_selection_requires_input(self):
        chosen = "  (달:1.4)🌙\r\n별  "
        full = "앞" + chosen + "뒤"
        self.view.present(decode_bundle(pack(row(0, base=full))), "합성")
        field = "Base Positive"
        area, _ = self.view.prompts.panels[field]
        menu = self.field_menu(field)
        with patch.object(self.view.transfer, "add_source") as target:
            menu.invoke("선택 문구 담기")
            target.assert_not_called()
            self.assertIn("선택", self.view.status.cget("text"))
            area.tag_add("sel", "1.1", "end-2c")
            menu.invoke("선택 문구 담기")
            target.assert_called_once()
            selection = target.call_args.args[0]
            self.assertEqual(selection.text, chosen)
            target.reset_mock()
            menu.invoke("전체 문구 담기")
            target.assert_called_once()
            self.assertEqual(target.call_args.args[0].text, full)
            self.assertEqual(area.get("1.0", "end-1c"), full)
            area.delete("1.0", "end")
            self.assertEqual(selection.text, chosen)
            self.assertEqual((selection.image, selection.field), (0, field))

    def test_cancelling_import_keeps_old_edits_until_replacement_is_confirmed(self):
        cards = decode_bundle(pack(row(0)))
        self.view.present(cards, "합성")
        field = "Base Positive"
        area, _ = self.view.prompts.panels[field]
        area.insert("1.0", "수정 ")
        incoming = decode_bundle(pack(row(0, base="새 자료")))
        with (patch("bundle.window.theme.confirm", return_value=False) as confirm,
              patch("bundle.window.read_link", return_value=incoming)):
            self.view.read_btn.invoke()
            self.spin(lambda: not self.view.running)
            confirm.assert_called_once()
        self.assertEqual(self.view.cards, cards)
        self.assertEqual(self.view.prompts.panels[field][0].get("1.0", "end-1c"), "수정 " + cards[0].base)
        with patch("bundle.window.theme.confirm", return_value=True) as confirm:
            self.view.load_file(ROOT / "fixtures/synthetic-work.json")
            confirm.assert_called_once()
        self.assertEqual(self.view.source, "synthetic-work.json")
        self.assertFalse(self.view.edits.dirty)

    def test_select_all_preserves_typed_trailing_newlines_and_excludes_tk_sentinel(self):
        full = "🙂\r\n\n"
        self.view.present(decode_bundle(pack(row(0, base=full))), "합성")
        field = "Base Positive"
        area, _ = self.view.prompts.panels[field]
        menu = self.field_menu(field)
        with patch.object(self.view.transfer, "add_source") as target:
            area.tag_add("sel", "1.0", "end")
            menu.invoke("선택 문구 담기")
            target.assert_called_once()
            self.assertEqual(target.call_args.args[0].text, full)
            target.reset_mock()
            area.tag_remove("sel", "1.0", "end")
            area.tag_add("sel", "end-1c", "end")
            menu.invoke("선택 문구 담기")
            target.assert_not_called()
            self.assertIn("선택", self.view.status.cget("text"))

    def test_queued_unedited_text_alone_protects_against_new_file_replacement(self):
        cards = decode_bundle(pack(row(0, base="첫째"), row(1, base="둘째")))
        self.view.present(cards, "합성")
        self.select(1)
        self.field_menu("Base Positive").invoke("전체 문구 담기")
        item, = self.view.transfer.items
        self.assertFalse(self.view.edits.dirty)
        with patch("bundle.window.theme.confirm", return_value=False) as confirm:
            self.view.load_file(ROOT / "fixtures/synthetic-work.json")
            confirm.assert_called_once()
        self.assertEqual(self.view.index, 1)
        self.assertIs(self.view.transfer.items[0], item)
        self.assertEqual(item.source.text, "둘째")
        with patch("bundle.window.theme.confirm", return_value=True) as confirm:
            self.view.load_file(ROOT / "fixtures/synthetic-work.json")
            confirm.assert_called_once()
        self.assertFalse(self.view.transfer.items)

    def test_field_restore_preserves_other_edit_and_exact_original_line_endings(self):
        cards = decode_bundle(pack(row(0, base="\t가\r\n\r\n🌙  ", negative="")))
        self.view.present(cards, "합성")
        field = "Base Positive"
        self.view.prompts.panels[field][0].delete("1.0", "end")
        self.view.prompts.panels["Base Undesired"][0].insert("1.0", "별도 수정")
        self.field_menu(field).invoke("원문으로 복원")
        restored = self.view.prompts.panels[field][0].get("1.0", "end-1c")
        self.assertEqual(restored, cards[0].base)
        self.assertEqual(self.view.prompts.panels["Base Undesired"][0].get("1.0", "end-1c"), "별도 수정")

    def test_raw_copy_and_disclosure_when_source_changes(self):
        cards = decode_bundle(pack(
            row(0, readable="  사이트 원문\r\n(가중치:1.2)  "),
            row(1, origin="novelai_inspect", readable="  Inspect\n\n 다음 줄  "),
            row(2, status="missing"), row(3, status="empty", readable="", base=None),
        ))
        self.view.present(cards, "합성")
        with patch("bundle.window.copy_text") as sink:
            for index in (0, 1, 3, 2, 0):
                self.select(index)
                self.assertFalse(self.view.raw.winfo_ismapped())
                title = "Simplified 원문" if index == 1 else "읽기 쉬운 내용 원문"
                self.assertIn("수집 원문 보기", self.view.raw_toggle.cget("text"))
                sink.reset_mock()
                self.view.raw_btn.invoke()
                if cards[index].readable is None:
                    self.assertEqual(self.view.raw_btn.cget("state"), "disabled")
                    sink.assert_not_called()
                    continue
                self.assertTrue(self.view.raw_btn.winfo_ismapped())
                sink.assert_called_once_with(self.root.winfo_id(), cards[index].readable)
                self.view.raw_toggle.invoke()
                self.root.update()
                self.assertTrue(self.view.raw.winfo_ismapped())
                self.assertEqual(title, self.view.raw_label.cget("text"))
                self.assertEqual(self.view.raw.cget("state"), "disabled")
                self.assertEqual(self.view.raw.get("1.0", "end-1c"), cards[index].readable)
                self.view.raw_toggle.invoke()
                self.root.update()
                self.assertFalse(self.view.raw.winfo_ismapped())
                self.view.raw_toggle.invoke()  # Switch images with the old raw source open.
                self.root.update()

    def test_panels_reflow_at_minimum_window_width(self):
        cards = decode_bundle(pack(row(0, structure="characters", characters=[{"positive": "기본", "negative": "제외"}])))
        self.view.present(cards, "합성")
        panels = self.view.prompts.panels
        positive, _ = panels["Character 1 Positive"]
        undesired, _ = panels["Character 1 Undesired"]
        for width in (1100, 680, 1100):
            self.root.geometry(f"{width}x600+20000+20000")
            self.root.update()
            with self.subTest(width=width):
                canvas = self.view.prompts.canvas
                left = canvas.winfo_rootx()
                right = left + canvas.winfo_width()
                for control in (self.view.link, self.view.read_btn, self.view.inspect_btn):
                    self.assertGreater(control.winfo_width(), 1)
                    self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                         self.root.winfo_rootx() + self.root.winfo_width())
                for panel in panels.values():
                    for widget in panel:
                        self.assertGreaterEqual(widget.winfo_rootx(), left)
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right)
                if width == 680:
                    self.assertGreaterEqual(undesired.winfo_rooty(),
                                            positive.winfo_rooty() + positive.winfo_height())
                else:
                    self.assertEqual(positive.winfo_rooty(), undesired.winfo_rooty())
                    self.assertLess(positive.winfo_rootx(), undesired.winfo_rootx())

    def test_wheel_scrolls_long_text_then_the_list_and_focus_reveals_controls(self):
        self.root.geometry("680x500+20000+20000")
        cards = decode_bundle(pack(row(0, base="한 줄\n" * 60, negative="",
                                       structure="characters", characters=[
                                           {"positive": f"캐릭터 {i}", "negative": None}
                                           for i in range(1, 5)])))
        self.view.present(cards, "합성")
        self.root.update()
        canvas = self.view.prompts.canvas
        panels = self.view.prompts.panels
        long_text, _ = panels["Base Positive"]
        self.assertLess(long_text.yview()[1], 1)
        self.assertLess(canvas.yview()[1], 1)
        initial_scroll = canvas.yview()
        long_text.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(long_text.yview()[0], 0)
        self.assertEqual(canvas.yview(), initial_scroll)
        long_text.yview_moveto(1)
        long_text.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(canvas.yview()[0], initial_scroll[0])

        widget = self.view.link
        tab_order = []
        while widget and widget not in tab_order:
            tab_order.append(widget)
            widget = widget.tk_focusNext()
        for area, copy_button in panels.values():
            self.assertIn(area, tab_order)
            self.assertIn(copy_button, tab_order)
        _, last_button = panels["Character 4 Positive"]
        last_button.event_generate("<FocusIn>")
        self.root.update()
        top = canvas.winfo_rooty()
        self.assertGreaterEqual(last_button.winfo_rooty(), top)
        self.assertLessEqual(last_button.winfo_rooty() + last_button.winfo_height(),
                             top + canvas.winfo_height())
        self.view.present(decode_bundle(pack(row(0))), "다음 작품")
        self.root.update()
        self.assertEqual(canvas.yview()[0], 0)

    def test_count_visible_before_result_and_stale_job_ignored(self):
        release = threading.Event()
        cards = decode_bundle(pack(row(0)))

        def fetch(_url, progress):
            progress(1)
            release.wait(3)
            return cards

        with patch("bundle.window.read_link", side_effect=fetch):
            self.view.read_btn.invoke()
            self.spin(lambda: self.view.counter.cget("text") == "이미지 1장 확인")
            self.view.load_file(ROOT / "fixtures/synthetic-work.json")
            release.set()
            self.spin(lambda: not self.view.running)
        self.assertEqual(len(self.view.cards), 2)
        self.assertEqual(self.view.source, "synthetic-work.json")

    def test_tab_crosses_long_result_sections_in_both_directions(self):
        slots = [{"positive": f"인물 {number}", "negative": f"제외 {number}"}
                 for number in range(1, 32)]
        self.view.present(decode_bundle(pack(row(0, structure="characters", characters=slots))), "합성")
        canvas = self.view.prompts.canvas
        panels = self.view.prompts.panels
        previous_text, _ = panels["Character 15 Undesired"]
        _, next_button = panels["Character 16 Positive"]
        _, final_button = panels["Character 31 Undesired"]

        def assert_visible(widget):
            self.assertTrue(widget.winfo_ismapped())
            y = widget.winfo_rooty() - canvas.winfo_rooty()
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y + widget.winfo_height(), canvas.winfo_height())

        def press(widget, sequence):
            if self.root.focus_get() is widget:
                widget.event_generate(sequence)
            else:
                # An inactive Windows toplevel drops key events. Deliver the
                # installed binding to this widget without taking desktop focus.
                binding = widget.bind(sequence)
                self.assertTrue(binding)
                widget.bind("<<OffscreenTab>>", binding)
                widget.event_generate("<<OffscreenTab>>")
                widget.unbind("<<OffscreenTab>>")
            self.root.update()

        for size in ("1020x748", "680x500"):
            with self.subTest(size=size):
                self.root.geometry(f"{size}+20000+20000")
                canvas.yview_moveto(0)
                self.root.update()
                previous_text.focus_set()
                previous_text.event_generate("<FocusIn>")
                self.root.update()
                assert_visible(previous_text)
                press(previous_text, "<Tab>")
                self.assertIs(self.root.focus_lastfor(), next_button)
                assert_visible(next_button)
                press(next_button, "<Shift-Tab>")
                self.assertIs(self.root.focus_lastfor(), previous_text)
                assert_visible(previous_text)

                canvas.yview_moveto(1)
                self.root.update()
                assert_visible(final_button)
                with patch("bundle.window.copy_text") as sink:
                    final_button.invoke()
                    sink.assert_called_once_with(self.root.winfo_id(), "제외 31")

    def test_destroy_cancels_pending_panel_measurement(self):
        self.view.present(decode_bundle(pack(row(0))), "합성")
        panels = self.view.prompts
        pending = panels.measure_job
        self.assertIsNotNone(pending)
        panels.destroy()
        self.assertNotIn(pending, self.root.tk.call("after", "info"))
        self.root.update_idletasks()

    def test_failed_new_link_disables_previous_result(self):
        self.view.present(decode_bundle(pack(row(0))), "합성")
        with patch("bundle.window.read_link", side_effect=ValueError("접근 제한")):
            self.view.read_btn.invoke()
            self.spin(lambda: not self.view.running)
        self.assertEqual(self.view.cards, [])
        self.assertFalse(self.view.prompts.panels)
        self.assertEqual(self.view.raw_btn.cget("state"), "disabled")
        self.assertEqual(self.view.hint.cget("text"), "접근 제한")

    def test_minimal_flow_and_explicit_format_label(self):
        self.assertFalse(hasattr(self.view, "open_btn"))
        self.assertEqual(self.view.help_button.cget("text"), "도움말")
        self.view.present(decode_bundle(pack(row(0, readable="형식: a1111\n"))), "합성")
        self.assertIn("A1111", self.view.heading.cget("text"))
        self.assertIn("모델 미확인", self.view.heading.cget("text"))

    def spin(self, done):
        end = time.monotonic() + 4
        while not done() and time.monotonic() < end:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(done())


if __name__ == "__main__":
    unittest.main()

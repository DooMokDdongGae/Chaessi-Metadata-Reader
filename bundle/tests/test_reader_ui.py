"""Exercise locale changes at the real editor widgets with synthetic, session-only data."""
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bundle.i18n import Language
from bundle.model import Card
from bundle.window import BundleReader


class ReaderLanguageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.preference = Path(directory.name) / "language.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.dispose_root)
        no_focus = patch.object(tk.Misc, "focus_set", autospec=True)
        no_focus.start()
        self.addCleanup(no_focus.stop)
        self.app = BundleReader(self.root, automatic=False,
                                language=Language(preference_path=self.preference))
        self.app.ui.set("ko")
        self.addCleanup(self.cancel_poll)
        self.card = Card("ok", "Format: NAI\n원문  \n\t日本語", "characters", "quiet garden", "",
                         (("파란 천", ""), ("별", "흐림")))
        self.app.present([self.card, self.card], "자료 이름 · 作例")
        self.app.list.selection_clear(0, "end")
        self.app.list.selection_set(1)
        self.app.show_card()

    def cancel_poll(self):
        if self.app.timer:
            self.root.after_cancel(self.app.timer)

    def dispose_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def pick_language(self, code):
        label = {"en": "English", "ja": "日本語", "ko": "한국어"}[code]
        self.app.language_picker.set(label)
        self.app.pick_language()
        self.assertEqual(self.app.ui.lang, code)

    def test_live_language_switch_preserves_unsaved_text_selection_and_open_original(self):
        field = "Character 2 Positive"
        area = self.app.prompts.panels[field][0]
        area.replace("1.0", "end-1c", "  雨, (달:1.25)\n\t끝  ")
        area.tag_add("sel", "1.5", "2.2")
        selected = area.get("sel.first", "sel.last")
        self.app.queue_field(field, selected_only=True)
        self.app.toggle_raw()
        self.app.link.insert(0, "https://example.invalid/合成")
        inspect_names = {"ko": "NovelAI Inspect 가져오기", "en": "Import from NovelAI Inspect",
                         "ja": "NovelAI Inspect から取り込む"}
        for code in ("en", "ja", "ko"):
            with self.subTest(code=code):
                self.pick_language(code)
                self.root.update_idletasks()
                self.assertEqual(self.app.inspect_btn.cget("text"), inspect_names[code])
                self.assertEqual(self.app.index, 1)
                self.assertEqual(tuple(self.app.list.curselection()), (1,))
                self.assertEqual(self.app.link.get(), "https://example.invalid/合成")
                self.assertEqual(self.app.raw.get("1.0", "end-1c"), self.card.readable)
                self.assertTrue(self.app.raw_frame.winfo_manager())
                self.assertEqual(tuple(self.app.prompts.panels), tuple(k for k, _ in self.card.fields()))
                current = self.app.prompts.panels[field][0]
                self.assertEqual(current.get("1.0", "end-1c"), "  雨, (달:1.25)\n\t끝  ")
                self.assertEqual(current.get("sel.first", "sel.last"), selected)
                item, = self.app.transfer.items
                self.assertEqual((item.source.image, item.source.field, item.source.scope, item.source.text),
                                 (1, field, "selection", selected))
                self.assertEqual(self.app.cards, [self.card, self.card])
                self.assertEqual(Language(preference_path=self.preference).lang, code)

    def test_full_and_selected_copies_of_identical_text_keep_their_own_scope(self):
        field = "Base Positive"
        area = self.app.prompts.panels[field][0]
        original = "  (紙:1.2)\n\t한글  \n"
        area.replace("1.0", "end-1c", original)
        area.tag_add("sel", "1.0", "end")
        self.app.queue_field(field, selected_only=False)
        self.app.queue_field(field, selected_only=True)
        area.replace("1.0", "end-1c", "편집창의 다음 값")
        self.app.ui.set("ja")
        self.assertEqual([(x.source.text, x.source.scope) for x in self.app.transfer.items],
                         [(original, "full"), (original, "selection")])
        self.assertEqual(self.app.prompts.panels[field][0].get("1.0", "end-1c"), "편집창의 다음 값")
        self.assertEqual(self.app.cards[1].base, "quiet garden")
        self.assertNotIn(original, self.preference.read_text(encoding="utf-8"))

    def test_replacing_a_collection_selects_only_the_first_new_image(self):
        replacement = Card("ok", "Format: NAI\nother", "single", "new", "")
        self.assertEqual(tuple(self.app.list.curselection()), (1,))
        self.assertTrue(self.app.present([replacement, replacement], "교체"))
        self.assertEqual(self.app.index, 0)
        self.assertEqual(tuple(self.app.list.curselection()), (0,))
        self.assertEqual(self.app.prompts.panels["Base Positive"][0].get("1.0", "end-1c"), "new")
        self.pick_language("en")
        self.assertEqual(tuple(self.app.list.curselection()), (0,))

    def test_language_change_preserves_pending_request_identity_and_row_mapping(self):
        self.app.queue_field("Base Undesired", selected_only=False)
        self.app.queue_field("Base Positive", selected_only=False)
        form = self.app.transfer
        class WithdrawnWindow(tk.Toplevel):
            def __init__(self, parent):
                super().__init__(parent)
                self.withdraw()

        def load_settings(work, success):
            success(work())

        with (patch("bundle.transfer_window.tk.Toplevel", WithdrawnWindow),
              patch.object(form.session, "configured", return_value=None),
              patch.object(form, "run", side_effect=load_settings)):
            form.show()
        queued, unmapped = form.items
        endpoint = SimpleNamespace(instance_id="instance-a", pid=101)
        form.install_targets(endpoint, {
            "revision": "draft-3", "limit": 1, "canCreate": 0,
            "targets": [{"slot": "base", "number": 0, "fields": ["positive"]},
                        {"slot": "slot-b", "number": 1, "fields": ["positive", "undesired"]}],
        })
        form.dest.current(1)
        form.assign()
        form.radios[1].invoke()
        self.assertTrue(form.send_button.instate(["!disabled"]))
        pending = (endpoint, "synthetic-id", b"synthetic body", (queued,))
        form.pending = pending
        labels = {"en": ("Character 1 · Positive", "Replace"), "ja": ("キャラクター 1 · ポジティブ", "上書き"),
                  "ko": ("캐릭터 1 · 긍정 프롬프트", "덮어 쓰기")}
        for code, (label, mode) in labels.items():
            with self.subTest(code=code):
                self.pick_language(code)
                self.assertIs(form.pending, pending)
                self.assertIs(form.selected(), queued)
                self.assertEqual(form.dest.get(), label)
                self.assertEqual(form.radios[1].cget("text"), mode)
                self.assertTrue(form.send_button.instate(["disabled"]))
                self.assertEqual((queued.instance, queued.revision, queued.slot, queued.field, queued.mode),
                                 ("instance-a", "draft-3", "slot-b", "positive", "replace"))
                self.assertEqual(queued.source.text, "")
                self.assertFalse(unmapped.slot)


if __name__ == "__main__":
    unittest.main()

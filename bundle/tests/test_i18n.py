"""Use temporary language preferences. These checks need no display or user profile."""
import ast
import json
from pathlib import Path
import re
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch

from bundle.help_ui import CHAPTERS, chapter_text
from bundle.i18n import COMMON, DIAGNOSTICS, LANGUAGE_NAMES, Language
from bundle.reader_strings import STRINGS as READER
from bundle.transfer_strings import STRINGS as TRANSFER


ROOT = Path(__file__).resolve().parents[2]


class LanguageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "reader" / "language.json"
        self.language = Language(self.path)

    def test_change_restart_and_unsubscribe(self):
        changes = []
        stop = self.language.subscribe(lambda: changes.append(self.language.lang))
        self.assertEqual(self.language.lang, "ko")
        self.assertFalse(self.path.exists())
        for code in ("en", "ja", "ko"):
            self.language.set(code)
            self.assertEqual(Language(self.path).lang, code)
            self.assertEqual(json.loads(self.path.read_bytes()), {"language": code})
            self.language.set(code)
        stop()
        self.language.set("ja")
        self.assertEqual(changes, ["en", "ja", "ko"])

    def test_recover_from_invalid_preferences_and_failed_write(self):
        self.path.parent.mkdir()
        for bad in (b"{", b'{"language":[]}', b'{"language":"unknown"}', b"42"):
            self.path.write_bytes(bad)
            self.assertEqual(Language(self.path).lang, "ko")
        self.language.set("en")
        with patch("bundle.i18n.os.replace", side_effect=PermissionError):
            with self.assertRaises(OSError):
                self.language.set("ja")
        self.assertEqual(self.language.lang, "en")
        self.assertEqual(json.loads(self.path.read_bytes()), {"language": "en"})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_string_contracts_and_approved_modes(self):
        self.assertFalse(COMMON.keys() & (READER.keys() | TRANSFER.keys()))
        self.assertFalse(READER.keys() & TRANSFER.keys())
        for key, translations in self.language._strings.items():
            with self.subTest(key=key):
                self.assertEqual(len(translations), 3)
                if key == "reader.blank":
                    self.assertEqual(translations, ("", "", ""))
                else:
                    self.assertTrue(all(s.strip() for s in translations))
                fields = [set(name for _, name, _, _ in Formatter().parse(s) if name)
                          for s in translations]
                self.assertEqual(fields[0], fields[1])
                self.assertEqual(fields[0], fields[2])
        for code, append, replace in (("ko", "추가", "덮어 쓰기"), ("en", "Append", "Replace"),
                                      ("ja", "末尾に追加", "上書き")):
            self.language.set(code)
            self.assertEqual(self.language.t("send.append"), append)
            self.assertEqual(self.language.t("send.replace"), replace)

    def test_help_uses_current_labels_and_preserves_step_content(self):
        for code in LANGUAGE_NAMES:
            self.language.set(code)
            for key in CHAPTERS:
                title, content = chapter_text(key, self.language)
                with self.subTest(locale=code, chapter=key):
                    self.assertTrue(title)
                    self.assertNotRegex(content, r"\{\w+\.")
                    if key != "web":
                        self.assertNotIn("aitag.win", content)
            _, text = chapter_text("send", self.language)
            for key in ("reader.select", "reader.full", "send.title", "send.destination",
                        "send.append", "send.replace", "send.action"):
                self.assertIn(self.language.t(key), text)

    def test_preset_and_extension_diagnostics_have_exact_translations(self):
        needed = set()
        for name in ("bundle/transfer_client.py", "bundle/transfer_registry.py", "reader_clipboard.py",
                     "chrome_bridge/client.py", "reader_parser.py", "bundle/model.py"):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                    for arg in node.exc.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.search("[가-힣]", arg.value):
                            needed.add(arg.value)
        from bundle.transfer_client import ERRORS
        needed.update(ERRORS.values())
        extension = (ROOT / "chrome_bridge/extension/bridge.js").read_text(encoding="utf-8")
        messages = extension.partition("const READER_ERRORS = Object.freeze({")[2].partition("});")[0]
        needed.update(re.findall(r'^\s*\w+: "([^"]+)"', messages, re.M))
        missing = needed - DIAGNOSTICS.keys()
        self.assertEqual(missing, set())
        for code in ("en", "ja"):
            self.language.set(code)
            for message in needed:
                self.assertNotRegex(self.language.diagnostic(message), "[가-힣]")
            self.assertIn("char_captions", self.language.diagnostic("char_captions에 복사할 수 없는 문자가 있습니다."))
            self.assertIn("37", self.language.diagnostic("JSON 문법 오류 · 37행 2열"))
            self.assertEqual(self.language.diagnostic("미등록 진단"), self.language.t("ui.diagnostic"))


if __name__ == "__main__":
    unittest.main()

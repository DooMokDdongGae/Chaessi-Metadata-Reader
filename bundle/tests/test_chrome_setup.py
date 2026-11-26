"""Exercise the real setup widgets using isolated preferences and a synthetic key."""
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from bundle.i18n import Language
from bundle.window import BundleReader
from chrome_bridge.key_store import PairingKeyError


class SetupTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.dispose)
        self.ui = Language(Path(temp.name) / "language.json")
        self.connection = Mock(first_run=True)
        self.connection.state.return_value = "연결됨"
        self.connection.copy_pairing_key.side_effect = lambda copy: copy("synthetic")

    def dispose(self):
        self.root.update_idletasks()
        self.root.destroy()

    def open(self, failure=None):
        with patch("bundle.window.ReaderConnection", return_value=self.connection, side_effect=failure):
            reader = BundleReader(self.root, language=self.ui)
            with patch.object(tk.Toplevel, "lift"):
                self.root.update_idletasks()
        self.addCleanup(lambda: self.root.after_cancel(reader.timer))
        return reader

    def test_first_run_and_explicit_private_copy_in_all_languages(self):
        app = self.open()
        setup = app.chrome_setup
        self.assertIsNotNone(setup.window)
        with patch("bundle.chrome_setup.copy_text") as clipboard:
            for code in ("en", "ja", "ko"):
                self.ui.set(code)
                self.assertEqual(setup.window.title(), self.ui.t("setup.title"))
                self.assertEqual(setup.copy.cget("text"), self.ui.t("setup.copy"))
                self.assertIn("0.3.1", setup.steps.get("1.0", "end"))
            clipboard.assert_not_called()
            setup.copy.invoke()
            clipboard.assert_called_once_with(setup.window.winfo_id(), "synthetic", private=True)
            self.assertNotIn("synthetic", setup.message.cget("text"))
        app.connection_state = self.connection.state()
        app.draw_connection()
        self.assertEqual(setup.status.cget("text"), self.ui.t("setup.ready"))

    def test_established_connection_and_explicit_legacy_choice(self):
        self.connection.first_run = False
        app = self.open()
        self.assertIsNone(app.chrome_setup.window)
        app.setup_button.invoke()
        with patch("bundle.chrome_setup.filedialog.askdirectory", return_value="previous"), \
                patch("bundle.chrome_setup.theme.confirm", side_effect=(False, True, True)):
            setup = app.chrome_setup
            setup.previous.invoke()
            self.connection.import_legacy_folder.assert_not_called()
            self.connection.import_legacy_folder.return_value = True
            setup.previous.invoke()
            self.connection.import_legacy_folder.assert_called_once_with("previous")
            self.assertEqual(setup.notice, "setup.imported")
            self.connection.import_legacy_folder.side_effect = PairingKeyError("PAIRING_KEY_MISSING")
            setup.previous.invoke()
            self.assertEqual(setup.message.cget("text"), self.ui.t("setup.PAIRING_KEY_MISSING"))

    def test_invalid_key_requires_confirmation_for_recovery(self):
        app = self.open(PairingKeyError("PAIRING_KEY_INVALID"))
        setup = app.chrome_setup
        self.assertEqual(setup.copy.cget("text"), self.ui.t("setup.recover"))
        with patch("bundle.window.ReaderConnection.recover_pairing", return_value=self.connection) as recover, \
                patch("bundle.chrome_setup.theme.confirm", side_effect=(False, True)):
            setup.copy.invoke()
            recover.assert_not_called()
            setup.copy.invoke()
            recover.assert_called_once()
            self.assertIs(app.connection, self.connection)
            self.assertEqual(setup.copy.cget("text"), self.ui.t("setup.copy"))

    def test_occupied_port_allows_retry_without_replacing_key(self):
        app = self.open(OSError("occupied"))
        setup = app.chrome_setup
        self.assertEqual(setup.copy.cget("text"), self.ui.t("setup.retry"))
        with patch("bundle.window.ReaderConnection", return_value=self.connection) as retry:
            setup.copy.invoke()
            retry.assert_called_once_with()
            retry.recover_pairing.assert_not_called()
        self.assertIsNone(app.connection_error)

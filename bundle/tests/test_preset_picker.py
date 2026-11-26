"""Check the single-Preset controls with Tk and synthetic session results."""
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bundle.i18n import Language
from bundle.transfer_client import TransferError
from bundle.transfer_window import TransferWindow


class WithdrawnWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.withdraw()


class PresetPickerTests(unittest.TestCase):
    def stub(self, name, **kwargs):
        patcher = patch(name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="reader-picker-test-")
        self.addCleanup(temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.errors = []
        self.root.report_callback_exception = lambda kind, value, trace: self.errors.append(value)
        self.ui = Language(Path(temp.name) / "language.json")
        self.session = Mock()
        self.session.configured.return_value = None
        self.endpoint = SimpleNamespace(instance_id="synthetic")
        self.record = SimpleNamespace(name="Chaessi Preset", path=Path(temp.name) / "Preset.exe", digest="exact")
        self.data = {"revision": "initial", "targets": [{"slot": "base", "number": 0, "fields": ["positive"]}],
                     "limit": 3, "canCreate": 0}
        self.session.inspect.return_value = self.record
        self.session.configure.return_value = self.record
        self.session.connect.return_value = (self.endpoint, self.data, self.record)
        self.dialog = self.stub("bundle.transfer_window.filedialog.askopenfilename", return_value="")
        self.confirm = self.stub("bundle.transfer_window.confirm", return_value=False)
        self.stub("tkinter.Toplevel", new=WithdrawnWindow)
        self.stub("bundle.transfer_window.brand", side_effect=lambda parent: tk.Label(parent))
        self.form = TransferWindow(self.root, lambda: None, self.ui, session=self.session)
        self.ui.subscribe(self.form.refresh_language)
        self.form.run = self.run_work
        self.form.show()

    def tearDown(self):
        self.assertFalse(self.errors)

    def run_work(self, work, success, error=None):
        try:
            result = work()
        except TransferError as exc:
            (error or self.form._error)(exc)
        else:
            success(result)
        self.form._controls()

    def test_explicit_confirmation_precedes_configure_and_launch(self):
        self.form.file_button.invoke()
        self.session.inspect.assert_not_called()
        self.dialog.return_value = str(self.record.path)
        self.form.file_button.invoke()
        self.session.inspect.assert_called_once_with(str(self.record.path))
        self.assertIn("*.exe", str(self.dialog.call_args.kwargs["filetypes"]))
        self.assertIn(str(self.record.path), self.confirm.call_args.args[2])
        self.session.configure.assert_not_called()
        self.session.connect.assert_not_called()
        self.confirm.return_value = True
        self.form.file_button.invoke()
        self.session.configure.assert_called_once_with(self.record)
        self.session.connect.assert_called_once_with(allow_launch=True)
        self.assertIs(self.form.endpoint, self.endpoint)
        self.assertEqual(self.form.connection_name.cget("text"), self.record.name)

    def test_first_connect_opens_one_file_dialog_only_for_missing_choice(self):
        self.session.connect.side_effect = [
            TransferError("preset.select_required", code="preset.select_required"),
            (self.endpoint, self.data, self.record),
        ]
        self.dialog.return_value = str(self.record.path)
        self.confirm.return_value = True
        self.form.connection_button.invoke()
        self.dialog.assert_called_once()
        self.assertIs(self.form.endpoint, self.endpoint)
        self.session.refresh.return_value = (self.endpoint, self.data, self.record)
        self.form.connection_button.invoke()
        self.session.refresh.assert_called_once_with(self.endpoint)
        self.dialog.assert_called_once()

    def test_changed_file_notice_and_language_do_not_open_another_window(self):
        self.session.connect.side_effect = TransferError("preset.changed", code="preset.changed")
        self.form.connection_button.invoke()
        for code in ("en", "ja", "ko"):
            self.ui.set(code)
            self.assertEqual(self.form.file_button.cget("text"), self.ui.t("send.preset_file"))
            self.assertEqual(self.form.status.cget("text"), self.ui.t("preset.changed"))
        self.dialog.assert_not_called()
        self.assertEqual(self.root.winfo_children(), [self.form.window])

    def test_pending_preview_locks_connection_and_file_controls(self):
        self.form.pending = (self.endpoint, "request", b"{}", ())
        self.form._controls()
        self.assertTrue(self.form.connection_button.instate(["disabled"]))
        self.assertTrue(self.form.file_button.instate(["disabled"]))
        self.form.connection_button.invoke()
        self.form.file_button.invoke()
        self.session.connect.assert_not_called()
        self.dialog.assert_not_called()


if __name__ == "__main__":
    unittest.main()

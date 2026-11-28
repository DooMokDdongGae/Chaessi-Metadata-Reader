"""Installation-root policy tests; no live user registry or folders are used."""
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_engine as engine
import update_policy as policy
from test_update_engine import TestOperations, Updater, catalogue, populate, TARGET


class InstallationPathTests(unittest.TestCase):
    def test_unicode_spaces_and_other_fixed_drive_spellings(self):
        for root in (r"C:\Users\가상 사용자\AppData\Local\Programs\ChaessiMetadataReader",
                     r"E:\설치 프로그램\채씨 리더", r"D:\MApp\Chaessi Reader",
                     "F:/Apps/Reader/"):
            with self.subTest(root=root):
                self.assertEqual(policy.installation_path(root), PureWindowsPath(root))

    def test_ambiguous_device_remote_and_unsafe_roots(self):
        for root in ("C:\\", r"C:Reader", r"\\server\share\Reader", r"\\?\C:\Reader",
                     r"C:\Apps\..\Reader", r"C:\Apps\.\Reader", r"C:\Apps\\Reader",
                     r"C:\Apps\NUL.txt", r"C:\Apps\COM4 .exe", r"C:\Apps\Reader.",
                     r"C:\Apps\COM¹", r"C:\Apps\LPT².txt", r"C:\Apps\CONOUT$",
                     "C:\\Apps\\Reader ", r"C:\Apps\Reader:stream", "C:\\Apps\\Read\ner"):
            with self.subTest(root=root), self.assertRaises(policy.Refusal) as refusal:
                policy.installation_path(root)
            self.assertEqual(refusal.exception.code, "UNSAFE_INSTALL_ROOT")


@unittest.skipUnless(sys.platform == "win32", "Windows Path semantics")
class RootSelectionTests(unittest.TestCase):
    def setUp(self):
        # Known-folder redirection is deliberately unrelated to Profile/AppData.
        self.local = Path(r"C:\Redirected Local\사용자")
        self.profile = Path(r"C:\Users\Synthetic")
        self.windows = Path(r"C:\Windows")
        folders = {"F1B32785-6FBA-4FCF-9D55-7B8E7F157091": self.local,
                   "5E6C858F-0E22-4760-9AFE-EA3317B67173": self.profile,
                   "F38BF404-1D43-42F2-9305-67DE0B28FC23": self.windows}
        self.enterContext(patch.object(engine, "known_folder", side_effect=folders.__getitem__))
        self.registration = self.enterContext(patch.object(engine, "registered_install_root", return_value=None))
        self.mount = self.enterContext(patch.object(engine, "mounted_install_volume", return_value="qa-volume"))
        self.kind = self.enterContext(patch.object(engine.WindowsOperations, "kind", return_value=None))
        self.pin = self.enterContext(patch.object(engine.WindowsOperations, "pinned", return_value=nullcontext()))

    def test_default_uses_actual_local_known_folder_without_profile_assumption(self):
        files = engine.WindowsOperations.for_user()
        self.assertEqual(files.install, self.local / "Programs" / "ChaessiMetadataReader")
        self.assertEqual(files.transaction_root, files.install)
        self.assertTrue(files.bind_install_root)
        self.mount.assert_called_once_with("C:\\")

    def test_existing_c_d_and_unicode_custom_root_are_preserved(self):
        for root in (self.local / "Programs" / "ChaessiMetadataReader",
                     Path(r"D:\MApp\Chaessi Reader"), Path(r"E:\프로그램\채씨 리더")):
            self.registration.return_value = root
            for explicit in (None, str(root)):
                with self.subTest(root=root, explicit=explicit):
                    files = engine.WindowsOperations.for_user(install_root=explicit)
                    self.assertEqual(files.install, root)
                    self.assertEqual(files.transaction_root, root)

    def test_registration_does_not_authorize_implicit_relocation(self):
        self.registration.return_value = Path(r"D:\MApp\Chaessi Reader")
        with self.assertRaises(policy.Refusal) as refusal:
            engine.WindowsOperations.for_user(install_root=r"E:\Another Reader")
        self.assertEqual(refusal.exception.code, "INSTALL_LOCATION_MISMATCH")
        self.mount.assert_not_called()

    def test_sensitive_overlap_and_windows_root_are_rejected_without_mutation(self):
        control = self.local / "CHAESSI" / "MetadataReaderUpdate"
        for root in (self.local, self.profile, self.windows / "Reader", control,
                     control / "Reader", control.parent):
            with self.subTest(root=root), self.assertRaises(policy.Refusal) as refusal:
                engine.WindowsOperations.for_user(install_root=str(root))
            self.assertEqual(refusal.exception.code, "UNSAFE_INSTALL_ROOT")
        self.mount.assert_not_called()

    def test_existing_chain_is_pinned_but_missing_chain_is_not_created(self):
        self.kind.side_effect = lambda path: "directory" if len(path.parts) < 3 else None
        with patch.object(engine.WindowsOperations, "make_dir") as create:
            engine.WindowsOperations.for_user(install_root=r"E:\Apps\새 리더")
            create.assert_not_called()
        self.assertTrue(self.pin.called)

    def test_archived_legacy_default_and_control_transaction_remain_unchanged(self):
        files = engine.WindowsOperations.for_user(legacy=True)
        self.assertEqual(files.install, self.local / "Programs" / "ChaessiMetadataReader")
        self.assertEqual(files.transaction_root, files.control)
        self.registration.assert_not_called()
        self.mount.assert_not_called()

    def test_cli_forwards_global_root_to_every_normal_action(self):
        for action in ("guard", "setup-begin", "setup-commit", "uninstall-guard",
                       "fresh-recover", "setup-apply", "patch"):
            extra = ["--payload", "qa-payload"] if action in ("setup-apply", "patch") else []
            if action == "setup-begin":
                extra = ["--uninstaller", "reader-uninstaller.generated"]
            with (self.subTest(action=action), patch.object(sys, "frozen", True, create=True),
                  patch.object(engine, "load_catalogue", return_value=object()),
                  patch.object(engine.WindowsOperations, "for_user", return_value=object()) as selected,
                  patch.object(engine, "run_action", return_value=("accepted", 0)),
                  redirect_stdout(StringIO())):
                self.assertEqual(engine.main(["--install-root", r"E:\채씨 리더", action, *extra]), 0)
                selected.assert_called_once_with(install_root=r"E:\채씨 리더")

    def test_existing_fresh_folder_unsafe_acl_fails_without_acl_changes(self):
        class AclRefusal(ValueError):
            pass

        checked = Mock(side_effect=AclRefusal("synthetic unsafe ACL"))
        files = engine.WindowsOperations(Path(r"E:\채씨 리더"), self.local / "private")
        api = SimpleNamespace(checked_handle=checked, TransferError=AclRefusal)
        with (patch.object(engine.FileOperations, "prepare_install_root") as prepare,
              patch.object(engine, "windows_api", return_value=(None, api))):
            with self.assertRaises(policy.Refusal) as refusal:
                files.prepare_install_root()
            self.assertEqual(refusal.exception.code, "INSTALL_ROOT_ACL_REFUSED")
            prepare.assert_called_once_with()
            checked.assert_called_once_with(files.install, root=files.install, directory=True)

    def test_prelicense_guard_with_no_control_or_lock_creates_nothing(self):
        files = engine.WindowsOperations(Path(r"E:\Apps\Reader"), self.local / "missing-control")
        with (patch.object(files, "make_dir") as mkdir,
              patch.object(files, "make_file") as makefile,
              patch.object(engine.Updater, "status", return_value="fresh")):
            self.assertEqual(engine.run_action(SimpleNamespace(action="guard"), object(), files), ("fresh", 0))
            mkdir.assert_not_called()
            makefile.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows Path semantics")
class InstallationHintTests(unittest.TestCase):
    def setUp(self):
        sandbox = tempfile.TemporaryDirectory(prefix="reader-root-hint-test-")
        self.addCleanup(sandbox.cleanup)
        self.root = Path(sandbox.name)
        self.local = self.root / "local"
        self.control = self.local / "CHAESSI" / "MetadataReaderUpdate"
        self.control.mkdir(parents=True)
        self.app = self.root / "설치 프로그램" / "리더"
        self.files = TestOperations(self.app, self.control, transaction_root=self.app, location="hint-qa-volume")
        self.files.bind_install_root = True
        self.catalogue = catalogue()
        self.updater = Updater(self.catalogue, self.files)
        self.exe = self.root / "helper.exe"
        self.output = self.root / "install-root.txt"
        self.enterContext(patch.object(engine.sys, "executable", str(self.exe)))
        self.enterContext(patch.object(engine, "known_folder", return_value=self.local))
        self.registration = self.enterContext(patch.object(engine, "registered_install_root", return_value=None))
        factory = Mock(return_value=self.files)
        factory.for_user.return_value = self.files
        self.factory = self.enterContext(patch.object(engine, "WindowsOperations", factory))

    def test_no_hint_keeps_user_default_without_creating_output_or_root(self):
        self.assertEqual(engine.locate_installation(self.catalogue, self.output), ("no_installation_hint", 10))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.app.exists())
        self.factory.for_user.assert_not_called()

    def test_protected_fresh_custom_root_survives_partial_copy_and_hint_is_utf16(self):
        self.updater.begin_setup()
        populate(self.app, {engine.APP: TARGET[engine.APP]})
        before = self.updater.fresh_path.read_bytes()
        self.assertEqual(engine.locate_installation(self.catalogue, self.output), ("installation_hint", 0))
        self.assertEqual(self.output.read_bytes(), str(self.app).encode("utf-16-le"))
        self.assertEqual(self.updater.fresh_path.read_bytes(), before)
        self.assertEqual((self.app / engine.APP).read_bytes(), TARGET[engine.APP])
        self.factory.for_user.assert_called_once_with(install_root=str(self.app))

    def test_registered_root_hint_does_not_relocate_or_mutate_installation(self):
        self.registration.return_value = self.app
        self.assertEqual(engine.locate_installation(self.catalogue, self.output), ("installation_hint", 0))
        self.assertFalse(self.app.exists())

    def test_conflicting_root_wrong_volume_target_or_state_never_writes_hint(self):
        self.updater.begin_setup()
        self.registration.return_value = self.root / "foreign-root"
        with self.assertRaises(policy.Refusal) as refusal:
            engine.locate_installation(self.catalogue, self.output)
        self.assertEqual(refusal.exception.code, "CONFLICTING_INSTALL_REGISTRATION")
        self.registration.return_value = None
        self.files.location = "wrong-volume"
        with self.assertRaises(policy.Refusal) as refusal:
            engine.locate_installation(self.catalogue, self.output)
        self.assertEqual(refusal.exception.code, "INTERRUPTED_UPDATE_REQUIRES_SAME_INSTALLATION")
        self.files.location = "hint-qa-volume"
        with self.assertRaises(policy.Refusal) as refusal:
            engine.locate_installation(catalogue(old=True), self.output)
        self.assertEqual(refusal.exception.code, "INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER")
        self.files.write_record(self.updater.state_path, self.catalogue.releases[1].state.as_json())
        with self.assertRaises(policy.Refusal) as refusal:
            engine.locate_installation(self.catalogue, self.output)
        self.assertEqual(refusal.exception.code, "RECOVERY_STATE_CHANGED")
        self.assertFalse(self.output.exists())

    def test_output_is_exact_nonoverwriting_sibling_only(self):
        with self.assertRaises(policy.Refusal) as refusal:
            engine.locate_installation(self.catalogue, self.root / "another.txt")
        self.assertEqual(refusal.exception.code, "INVALID_INSTALL_ROOT_OUTPUT")
        self.registration.return_value = self.app
        self.output.write_bytes(b"keep-existing-output")
        with self.assertRaises(FileExistsError):
            engine.locate_installation(self.catalogue, self.output)
        self.assertEqual(self.output.read_bytes(), b"keep-existing-output")

    def test_cli_locate_bypasses_global_default_factory_and_disallows_explicit_root(self):
        with (patch.object(sys, "frozen", True, create=True),
              patch.object(engine, "load_catalogue", return_value=self.catalogue),
              patch.object(engine, "locate_installation", return_value=("no_installation_hint", 10)) as locate,
              redirect_stdout(StringIO())):
            self.assertEqual(engine.main(["locate-installation", "--output", str(self.output)]), 10)
            locate.assert_called_once_with(self.catalogue, self.output)
            self.factory.for_user.assert_not_called()
            self.assertEqual(engine.main(["--install-root", str(self.app), "locate-installation", "--output", str(self.output)]), 2)


@unittest.skipUnless(sys.platform == "win32", "Windows Path semantics")
class RegistrationCandidateTests(unittest.TestCase):
    def read(self, rows):
        def opened(_hive, _name, _reserved, access):
            if access not in rows:
                raise FileNotFoundError
            return nullcontext(rows[access])

        def queried(row, key):
            row = row.enter_result
            if key not in row:
                raise FileNotFoundError
            return row[key]

        fake = SimpleNamespace(KEY_WOW64_64KEY=0x100, KEY_WOW64_32KEY=0x200, KEY_READ=1,
                               HKEY_CURRENT_USER=object(), REG_SZ=1, OpenKey=opened, QueryValueEx=queried)
        with patch.dict(sys.modules, {"winreg": fake}):
            return engine.registered_install_root()

    def row(self, root):
        return {"InstallLocation": (root, 1), "UninstallString": ('"' + root + r'\Uninstall.exe"', 1)}

    def test_32_64_registry_candidates_are_untrusted_but_consistent(self):
        self.assertIsNone(self.read({}))
        for view in (0x101, 0x201):
            self.assertEqual(self.read({view: self.row(r"E:\채씨 리더")}), Path(r"E:\채씨 리더"))
        self.assertEqual(self.read({view: self.row(r"D:\MApp\Chaessi Reader") for view in (0x101, 0x201)}),
                         Path(r"D:\MApp\Chaessi Reader"))

    def test_conflicting_views_missing_fields_and_wrong_remover_are_refused(self):
        with self.assertRaises(policy.Refusal) as refusal:
            self.read({0x101: self.row(r"E:\Reader"), 0x201: self.row(r"F:\Reader")})
        self.assertEqual(refusal.exception.code, "CONFLICTING_INSTALL_REGISTRATION")
        for row in ({}, {"InstallLocation": (r"E:\Reader", 1)},
                    {**self.row(r"E:\Reader"), "UninstallString": ('"F:\\Other\\Uninstall.exe"', 1)},
                    {**self.row(r"E:\Reader"), "InstallLocation": (r"E:\Reader", 2)}):
            with self.subTest(keys=tuple(row)), self.assertRaises(policy.Refusal) as refusal:
                self.read({0x101: row})
            self.assertEqual(refusal.exception.code, "INSTALL_LOCATION_MISMATCH")


if __name__ == "__main__":
    unittest.main()

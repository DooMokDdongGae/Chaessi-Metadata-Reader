"""Windows pairing and upgrade tests using only generated temporary profiles and peers."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import hmac
import os
from pathlib import Path
import secrets
import socket
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

from bundle import preset_library as private
from bundle import transfer_registry as win
from bundle.i18n import Language
from chrome_bridge.connection import ReaderConnection
from chrome_bridge.key_store import BridgeKeyStore, PairingKeyError
from chrome_bridge.tests.test_automatic import Peer


def shared_fixture(path, *, directory=False):
    """Create an empty fixture with an explicit readable-by-Users ACE at creation."""
    security = win.WindowsSecurity()
    sddl = "D:P" + "".join(f"(A;;FA;;;{sid})" for sid in security.trusted) + "(A;;FR;;;BU)"
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = win._api(advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW", wintypes.BOOL,
                       wintypes.LPCWSTR, wintypes.DWORD, win.P, win.P)
    descriptor = win.P()
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        with private._private_attributes() as attributes:
            attributes.descriptor = descriptor.value
            if directory:
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                create = win._api(kernel, "CreateDirectoryW", wintypes.BOOL, wintypes.LPCWSTR, win.P)
                if not create(str(path), ctypes.byref(attributes)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return
            handle = security.open(str(path), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
        if handle == win.P(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        security.close(handle)
    finally:
        security.free(descriptor)


@unittest.skipUnless(os.name == "nt", "Windows per-user key protection")
class PairingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="reader-pairing-synthetic-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.store = BridgeKeyStore(self.base / "current")

    def legacy(self, name="old", value=None):
        folder = self.base / name
        folder.mkdir()
        private._make_directory(folder / ".local")
        file = folder / ".local" / "bridge-key"
        with private._open_private(file) as output:
            output.write(value if value is not None else secrets.token_hex(32).encode("ascii"))
        return folder, file

    def assert_error(self, code, action, *args):
        with self.assertRaises(PairingKeyError) as failure:
            action(*args)
        self.assertEqual(str(failure.exception), code)

    def connect(self, recover=False, port=0):
        create = ReaderConnection.recover_pairing if recover else ReaderConnection
        reader = create(key_store=self.store, port=port)
        self.addCleanup(reader.close)
        return reader

    def active_file(self):
        generation = self.store.index.read_text("ascii")
        self.assertRegex(generation, r"^[0-9a-f]{32}$")
        return self.store.generations / generation

    def test_fresh_concurrent_installation_preserves_language_and_registered_settings(self):
        # Resolve the actual product defaults into this isolated profile.
        with patch.dict(os.environ, LOCALAPPDATA=str(self.base)):
            os.environ.pop("CHAESSI_TRANSFER_REGISTRY", None)
            language = Language()
            language.set("ja")
            installed = BridgeKeyStore()
            library = private.PresetLibrary()
            saved = library.register(private.ExeInfo(self.base / "stand-in.exe", "a" * 64))
            library.select(saved.id)
            snapshot = [(p, p.read_bytes()) for p in (language.path, library.path)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(lambda _: BridgeKeyStore().load(), range(8)))
            self.assertEqual(sum(created for _, created in values), 1)
            self.assertTrue(all(hmac.compare_digest(key, values[0][0]) for key, _ in values))
            self.assertEqual(len(values[0][0]), 64)
            self.assertEqual(installed.root, language.path.parent / "bridge")
            for path, before in snapshot:
                self.assertEqual(path.read_bytes(), before)
            self.assertEqual(Language().lang, "ja")
            self.assertEqual(library.load().last_selected, saved.id)

    def test_explicit_import_preserves_source_and_connected_peer_until_commit(self):
        reader = self.connect()
        self.assertTrue(reader.first_run)
        folder, source = self.legacy()
        original = source.read_bytes()
        old = []
        reader.copy_pairing_key(old.append)
        port = reader.bridge.http.server_port
        peer = Peer(port)
        self.addCleanup(peer.close)
        ready = peer.auth(old[0])
        self.assertEqual(ready["type"], "ready")
        self.assertTrue(reader.bridge.session_allowed(ready["session"]))
        self.assertEqual(peer.read(), {"type": "wake"})
        with patch("chrome_bridge.key_store.os.replace", side_effect=PermissionError):
            self.assert_error("PAIRING_KEY_UNSAFE", reader.import_legacy_folder, folder)
        self.assertTrue(reader.bridge.session_allowed(ready["session"]))
        self.assertTrue(hmac.compare_digest(self.store.load()[0], old[0]))
        self.assertEqual([p.name for p in self.store.root.iterdir()], ["bridge-key"])
        self.assertTrue(reader.import_legacy_folder(folder))
        self.assertFalse(reader.bridge.session_allowed(ready["session"]))
        self.assertTrue(hmac.compare_digest(source.read_bytes(), original))
        self.assertTrue(hmac.compare_digest(self.store.load()[0], original.decode("ascii")))
        new_peer = Peer(port)
        self.addCleanup(new_peer.close)
        again = new_peer.auth(original.decode("ascii"))
        self.assertEqual(again["type"], "ready")
        self.assertFalse(reader.import_legacy_folder(folder))
        self.assertTrue(reader.bridge.session_allowed(again["session"]))
        reader.close()
        new_peer.close()
        relaunched = self.connect(port=port)
        self.assertFalse(relaunched.first_run)
        copied = []
        relaunched.copy_pairing_key(copied.append)
        self.assertTrue(hmac.compare_digest(copied[0], original.decode("ascii")))

    def test_legacy_missing_malformed_or_shared_key_leaves_current_pairing_intact(self):
        reader = self.connect()
        expected = self.store.load()[0]
        self.assert_error("PAIRING_KEY_MISSING", reader.import_legacy_folder, self.base)
        folder, key = self.legacy(value=b"broken")
        self.assert_error("PAIRING_KEY_INVALID", reader.import_legacy_folder, folder)
        key.unlink()  # Replace only the disposable malformed test fixture.
        shared_fixture(key)
        self.assert_error("PAIRING_KEY_UNSAFE", reader.import_legacy_folder, folder)
        self.assertTrue(hmac.compare_digest(self.store.load()[0], expected))
        self.assertTrue(key.is_file())

    def test_explicit_recovery_retains_damaged_primary_and_reopens_the_new_key(self):
        self.store.load()
        damaged = self.store.root / "bridge-key"
        damaged.write_bytes(b"damaged fixture")
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        self.assertFalse(self.store.recovery.exists())
        reader = self.connect(recover=True)
        self.assertTrue(reader.first_run)
        self.assertEqual(damaged.read_bytes(), b"damaged fixture")
        recovered = self.store.load()[0]
        self.assertTrue(hmac.compare_digest(recovered, self.active_file().read_text("ascii")))
        self.assertFalse(self.store.recover()[1])
        reader.close()
        self.assertFalse(self.connect().first_run)

    def test_reader_already_on_port_prevents_any_key_creation_or_recovery(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
            owner.bind(("127.0.0.1", 0))
            owner.listen()
            port = owner.getsockname()[1]
            with self.assertRaises(OSError):
                ReaderConnection(key_store=self.store, port=port)
            self.assertFalse(self.store.root.exists())
            self.store.load()
            primary = self.store.root / "bridge-key"
            primary.write_bytes(b"previous installation fixture")
            with self.assertRaises(OSError):
                ReaderConnection.recover_pairing(key_store=self.store, port=port)
            self.assertEqual(primary.read_bytes(), b"previous installation fixture")
            self.assertFalse(self.store.recovery.exists())

    def test_shared_installed_key_is_refused_and_preserved_during_recovery(self):
        private._make_directory(self.store.root)
        old = self.store.root / "bridge-key"
        shared_fixture(old)
        self.assert_error("PAIRING_KEY_UNSAFE", self.store.load)
        reader = self.connect(recover=True)
        self.assertTrue(reader.first_run)
        self.assertTrue(old.is_file())
        self.assertEqual(old.stat().st_size, 0)
        self.assertFalse(self.store.load()[1])

    def test_old_fixed_recovery_upgrades_and_repeated_recovery_uses_only_active_generation(self):
        for directory in (self.store.root, self.store.recovery):
            private._make_directory(directory)
            with private._open_private(directory / "bridge-key") as stream:
                stream.write(secrets.token_hex(32).encode("ascii"))
        old = self.store.recovery / "bridge-key"
        prior = old.read_bytes()
        key, created = self.store.load()
        self.assertFalse(created)
        self.assertTrue(hmac.compare_digest(key.encode("ascii"), prior))
        self.assertEqual(self.store.index.read_text("ascii"), "previous")
        old.write_bytes(b"damaged old recovery")
        one, _ = self.store.recover()
        first_file = self.active_file()
        self.assertEqual(old.read_bytes(), b"damaged old recovery")
        # Even if an old copy becomes valid again, it must stay retired.
        old.write_bytes(prior)
        first_file.write_bytes(b"damaged second pairing")
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        two, created = self.store.recover()
        second_file = self.active_file()
        self.assertTrue(created)
        self.assertEqual(first_file.read_bytes(), b"damaged second pairing")
        self.assertNotEqual(first_file, second_file)
        second_file.unlink()
        shared_fixture(second_file)
        self.assert_error("PAIRING_KEY_UNSAFE", self.store.load)
        three, created = self.store.recover()
        self.assertTrue(created)
        self.assertEqual(len({key, one, two, three}), 4)
        self.assertEqual(second_file.stat().st_size, 0)
        self.assertTrue(hmac.compare_digest(old.read_bytes(), prior))
        reopened = BridgeKeyStore(self.store.root)
        self.assertTrue(hmac.compare_digest(reopened.load()[0], three))
        for retired in (key, one, two):
            self.assert_error("PAIRING_KEY_CHANGED", reopened.verify, retired)

    def test_lost_target_missing_or_malformed_index_never_selects_an_older_key(self):
        original = self.store.load()[0]
        initial = self.store.root / "bridge-key"
        initial.write_bytes(b"damaged fixture")
        self.store.recover()
        initial.write_text(original, encoding="ascii")
        self.active_file().unlink()
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        self.store.index.write_bytes(b"../primary")
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        self.store.index.unlink()
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        self.store.index.parent.rmdir()  # Synthetic, empty index directory only.
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        key, created = self.store.recover()
        self.assertTrue(created)
        self.assertFalse(hmac.compare_digest(key, original))
        self.assertTrue(hmac.compare_digest(self.store.load()[0], key))

    def test_denied_commit_preserves_previous_selection_and_two_recoveries_commit_only_once(self):
        self.store.load()
        old = self.store.root / "bridge-key"
        old.write_bytes(b"original damaged fixture")
        before = self.store.index.read_bytes()
        with patch("chrome_bridge.key_store.os.replace", side_effect=PermissionError):
            self.assert_error("PAIRING_KEY_UNSAFE", self.store.recover)
        self.assertEqual(self.store.index.read_bytes(), before)
        self.assertEqual(old.read_bytes(), b"original damaged fixture")
        self.assertEqual(list(self.store.generations.iterdir()), [])
        self.assert_error("PAIRING_KEY_INVALID", self.store.load)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: BridgeKeyStore(self.store.root).recover(), (0, 1)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertTrue(hmac.compare_digest(results[0][0], results[1][0]))
        self.assertEqual(list(self.store.generations.iterdir()), [self.active_file()])

    def test_unsafe_recovery_folder_returns_an_error_without_replacing_keys_or_index(self):
        self.store.load()
        initial = self.store.root / "bridge-key"
        initial.write_bytes(b"fixture requiring recovery")
        before = self.store.index.read_bytes()
        shared_fixture(self.store.generations, directory=True)
        self.assert_error("PAIRING_KEY_UNSAFE", self.store.recover)
        self.assertEqual(before, self.store.index.read_bytes())
        self.assertEqual(initial.read_bytes(), b"fixture requiring recovery")
        self.assertEqual(list(self.store.generations.iterdir()), [])

    def test_overlapping_edits_detect_changed_keys_and_never_copy_stale_values(self):
        reader = self.connect()
        expected, _ = self.store.load()
        first, _ = self.legacy("first")
        second, _ = self.legacy("second")
        def attempt(folder):
            try:
                self.store.import_folder(folder, expected)
            except PairingKeyError as exc:
                return exc.code
            return "updated"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (first, second)))
        self.assertCountEqual(results, ("updated", "PAIRING_KEY_CHANGED"))
        copied = Mock()
        self.assert_error("PAIRING_KEY_CHANGED", reader.copy_pairing_key, copied)
        copied.assert_not_called()

    def test_key_change_while_a_collection_is_active_preserves_the_job_and_key(self):
        reader = self.connect()
        folder, _ = self.legacy()
        expected = self.store.load()[0]
        # Use the actual bridge job lifecycle with no browser or user page.
        with ThreadPoolExecutor(max_workers=1) as pool:
            started = Event()
            with patch.object(reader.bridge, "job_created", side_effect=started.set):
                result = pool.submit(reader.bridge.request_inspect, timeout=1)
                self.assertTrue(started.wait(1))
                self.assert_error("PAIRING_KEY_BUSY", reader.import_legacy_folder, folder)
                with self.assertRaises(ValueError):
                    result.result(timeout=3)
        self.assertTrue(hmac.compare_digest(self.store.load()[0], expected))


if __name__ == "__main__":
    unittest.main()

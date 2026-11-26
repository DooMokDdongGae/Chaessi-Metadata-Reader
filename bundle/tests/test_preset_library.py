"""Synthetic EXE registrations in disposable, isolated Windows configuration folders."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from bundle import preset_library as lib


def sample(path, marker=b"a"):
    # Only enough header structure for identification. There is no executable code.
    dos = bytearray(64)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 60, len(dos))
    coff = struct.pack("<HHIIIHH", 0x8664, 0, 0, 0, 0, 240, 2)
    data = bytes(dos) + b"PE\0\0" + coff + b"\x0b\x02" + bytes(238) + marker
    expected = hashlib.sha256(data).hexdigest()
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise AssertionError("synthetic fixture changed")
    return path


@unittest.skipUnless(os.name == "nt", "Windows EXE and private ACL checks")
class PresetLibraryTests(unittest.TestCase):
    def setUp(self):
        parent = Path(tempfile.gettempdir()).resolve()
        temp = tempfile.TemporaryDirectory(prefix="reader-library-test-", dir=parent)
        self.base = Path(temp.name).resolve()
        self.assertEqual(self.base.parent, parent)
        self.addCleanup(temp.cleanup)
        self.root = self.base / "profile" / "launchers"
        self.library = lib.PresetLibrary(self.root)
        self.a = sample(self.base / "edition-a" / "portable.EXE")
        self.b = sample(self.base / "edition-b" / "portable.exe", b"b")

    def test_arbitrary_name_has_no_guessed_version_build_or_identity(self):
        aimed = sample(self.base / "PRIVATE-99.8" / "Chaessi Preset PRIVATE v99.8.exe")
        info = lib.inspect_exe(aimed)
        self.assertIsNone(info.version)
        self.assertIsNone(info.product)
        self.assertIsNone(info.build)
        self.assertFalse(info.recognized)
        self.assertEqual(info.digest, hashlib.sha256(aimed.read_bytes()).hexdigest())
        with patch("bundle.preset_library._version_info", return_value=("1.2.3", "PRIVATE", "Chaessi Preset PRIVATE")):
            assigned = lib.inspect_exe(self.a)
        self.assertEqual((assigned.version, assigned.build, assigned.recognized), ("1.2.3", "PRIVATE", True))
        joined = sample(self.base / "Portable\u200d版.exe")
        named = self.library.register(lib.inspect_exe(joined))
        self.assertEqual(self.library.load().by_id(named.id).path, joined)
        self.assertEqual(named.name, "Portable版")

    def test_rejects_non_exe_non_pe_and_dll_data(self):
        not_exe = self.base / "prompt.json"
        not_exe.write_bytes(b"{}")
        bad_exe = self.base / "wrong.exe"
        bad_exe.write_bytes(b"an unrelated text file")
        dll = sample(self.base / "library.exe")
        with dll.open("r+b") as f:
            f.seek(64 + 22)
            f.write(struct.pack("<H", 0x2002))
        for path in (not_exe, bad_exe, dll):
            with self.subTest(path=path.name), self.assertRaises(lib.LibraryError) as error:
                lib.inspect_exe(path)
            self.assertEqual(error.exception.code, "NOT_EXE")

    def test_multiple_registrations_same_name_and_last_selected_survive_restart(self):
        a = self.library.register(lib.inspect_exe(self.a), "버전 A")
        b = self.library.register(lib.inspect_exe(self.b), "버전 B")
        self.assertIsNone(self.library.load().last_selected)
        self.library.connected(b.id, b.path, b.digest)
        again = lib.PresetLibrary(self.root).load()
        self.assertEqual([r.id for r in again.records], [a.id, b.id])
        self.assertEqual(again.last_selected, b.id)
        self.assertEqual(again.by_id(a.id).last_compat, "unknown")
        self.assertEqual(again.by_id(b.id).last_compat, "compatible")
        self.assertEqual(self.library.rename(a.id, "Portable A").name, "Portable A")
        self.library.select(a.id)
        self.library.remove(a.id)
        self.assertIsNone(self.library.load().last_selected)
        self.assertTrue(self.a.is_file())
        self.assertEqual(lib.file_state(b), "ready")

    def test_file_change_requires_explicit_reselection_and_resets_old_result(self):
        a = self.library.register(lib.inspect_exe(self.a))
        self.library.connected(a.id, a.path, a.digest)
        sample(self.a, b"updated")
        self.assertEqual(lib.file_state(a), "changed")
        updated = lib.inspect_exe(self.a)
        with self.assertRaises(lib.LibraryError) as blocked:
            self.library.register(updated)
        self.assertEqual(blocked.exception.code, "LIBRARY_CHANGED")
        with self.assertRaises(lib.LibraryError):
            self.library.register(updated, record_id=a.id)
        accepted = self.library.register(updated, record_id=a.id, previous=a)
        self.assertEqual(accepted.last_compat, "unknown")
        self.assertEqual(accepted.id, a.id)
        with self.assertRaises(lib.LibraryError):
            self.library.connected(a.id, a.path, a.digest)
        with self.assertRaises(lib.LibraryError):
            self.library.register(updated, record_id=a.id, previous=a)
        self.assertEqual(self.library.load().by_id(a.id).digest, updated.digest)

    def test_listing_checks_access_without_reading_executable_bytes(self):
        row = self.library.register(lib.inspect_exe(self.a))
        self.a.write_bytes(b"updated fixture")
        with patch.object(lib.registry, "launcher_hash", side_effect=AssertionError("unexpected hash")):
            self.assertEqual(lib.file_presence(row), "ready")
            self.a.unlink()
            self.assertEqual(lib.file_presence(row), "missing")
            self.a.mkdir()
            self.assertEqual(lib.file_presence(row), "unavailable")

    def test_move_and_missing_never_select_another_target(self):
        a = self.library.register(lib.inspect_exe(self.a))
        b = self.library.register(lib.inspect_exe(self.b))
        self.library.select(a.id)
        target = self.base / "elsewhere.exe"
        self.a.rename(target)
        self.assertEqual(lib.file_state(a), "missing")
        self.assertEqual(self.library.load().last_selected, a.id)
        with self.assertRaises(lib.LibraryError) as refused:
            self.library.register(lib.inspect_exe(self.b), record_id=a.id, previous=a)
        self.assertEqual(refused.exception.code, "LIBRARY_DUPLICATE")
        moved = self.library.register(lib.inspect_exe(target), record_id=a.id, previous=a)
        self.assertEqual(moved.path, target)
        with self.assertRaises(lib.LibraryError):
            self.library.connected(a.id, a.path, moved.digest)
        self.assertEqual(self.library.load().by_id(b.id), b)

    def test_confirmed_legacy_pin_migrated_once_without_overwriting_changed_file(self):
        legacy = self.base / "legacy"
        lib._make_directory(legacy)
        info = lib.inspect_exe(self.a)
        with lib._open_private(legacy / "reader-launcher.json") as out:
            out.write(json.dumps({"exe": str(info.path), "sha256": info.digest}).encode())
        sample(self.a, b"changed")
        library = lib.PresetLibrary(self.root, legacy)
        migrated = library.load()
        self.assertEqual(len(migrated.records), 1)
        old = migrated.records[0]
        self.assertEqual(migrated.last_selected, old.id)
        self.assertEqual(old.digest, info.digest)
        self.assertEqual(lib.file_state(old), "changed")
        library.remove(old.id)
        self.assertEqual(lib.PresetLibrary(self.root, legacy).load(), lib.LibraryState())
        self.assertTrue((legacy / "reader-launcher.json").exists())

    def test_atomic_failure_and_invalid_disk_data_do_not_erase_prior_state(self):
        a = self.library.register(lib.inspect_exe(self.a))
        with patch("bundle.preset_library.os.replace", side_effect=PermissionError):
            with self.assertRaises(OSError):
                self.library.connected(a.id, a.path, a.digest)
        self.assertEqual(self.library.load().by_id(a.id), a)
        self.assertIsNone(self.library.load().last_selected)
        self.assertEqual(list(self.root.iterdir()), [self.library.path])
        self.library.path.write_bytes(b"{")
        with self.assertRaises(lib.LibraryError):
            self.library.remove(a.id)
        self.assertEqual(self.library.path.read_bytes(), b"{")

    def test_concurrent_writers_keep_both_records(self):
        inputs = [lib.inspect_exe(self.a), lib.inspect_exe(self.b)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            stored = list(pool.map(lambda row: lib.PresetLibrary(self.root).register(row), inputs))
        self.assertEqual({r.id for r in self.library.load().records}, {r.id for r in stored})


if __name__ == "__main__":
    unittest.main()

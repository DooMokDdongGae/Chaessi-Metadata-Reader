"""Exercise the migration state and rollback paths without system registration."""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relocation
import update_engine
import update_policy as policy


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class TestFiles(update_engine.FileOperations):
    def __init__(self, root, control, current_registration, *, transaction_root=None):
        super().__init__(root, control, transaction_root=transaction_root)
        self.current_registration = current_registration
        self.volume = "fixture-volume"

    def verify_mount(self):
        return self.volume

    def lock(self):
        return nullcontext()

    def has_registration(self):
        return relocation.applicable_registration(self.install, self.current_registration["arp"])


class RelocationTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.c = root / "volume-c"
        self.d = root / "volume-d"
        self.control = self.c / "control"
        self.source = self.c / "installed"
        self.target = self.d / "installed"
        self.release = root / "setup-payload"
        self.shortcuts = self.c / "links"
        for path in (self.control, self.source, self.target, self.release, self.shortcuts):
            path.mkdir(parents=True)
        self.records = self.target / "_installation-records"
        self.records.mkdir()
        self.marker = self.records / "preserve.txt"
        self.marker.write_bytes(b"unrelated record")
        self.links = {name: self.shortcuts / (name + ".lnk") for name in relocation.LINKS}
        self.source_links = {name: root / (name + ".lnk") for name in relocation.LINKS}
        for role, path in self.links.items():
            path.write_bytes(("C managed " + role).encode())
            (self.source / relocation.LINKS[role]).write_bytes(path.read_bytes())
            self.source_links[role].write_bytes(("D managed " + role).encode())
        old = {policy.APP: b"old app", "product.id": policy.PRODUCT_ID.encode(), "guide.txt": b"old guide"}
        new = {**old, policy.APP: b"new app", "guide.txt": b"new guide"}
        for files, data in ((self.source, old), (self.release, new)):
            for name, raw in data.items():
                (files / name).write_bytes(raw)
        old_remover = b"known official remover fixture"
        for name in ("Uninstall.exe", "uninstaller.copy"):
            (self.source / name).write_bytes(old_remover)
        self.remover = root / "new-uninstaller.generated"
        self.remover.write_bytes(b"new remover")
        self.arp = {"arp": relocation.registration(self.source, 1042)}
        self.old_arp = self.arp["arp"].copy()
        self.catalogue = policy.Catalogue.from_json({
            "schema": 1, "patch_baseline_id": None,
            "target": {"id": "reader-test-new", "sequence": 2, "payload": {k: sha(v) for k, v in new.items()}},
            "known": [{"id": relocation.LEGACY_ID, "sequence": 1, "payload": {k: sha(v) for k, v in old.items()}}],
        })
        self.old = self.catalogue.releases[1]
        self.c_files = TestFiles(self.source, self.control, self.arp)
        self.d_files = TestFiles(self.target, self.control, self.arp, transaction_root=self.target)
        self.c_files.write_record(self.control / update_engine.STATE, self.old.state.as_json())
        for name, value in (("registry_values", lambda: self.arp["arp"]),
                            ("write_registry", lambda data: self.arp.update(arp=data.copy())),
                            ("remove_registry", lambda: self.arp.update(arp=None)),
                            ("links_in_profile", lambda _: self.links),
                            ("assert_remover_stopped", lambda _: None),
                            ("require_legacy_mutex_available", lambda: None),
                            ("LEGACY_REMOVERS", {sha(old_remover)})):
            self.enterContext(patch.object(relocation, name, value))
        self.enterContext(patch.object(relocation.WindowsOperations, "for_user", return_value=self.c_files))
        self.migration = relocation.Migration(self.catalogue, self.d_files)

    def stage(self):
        self.assertEqual(self.migration.run("stage", payload=self.release, uninstaller=self.remover,
                                           source_links=self.source_links, language=1042), "staged_for_trial")
        self.assertEqual(self.migration.guard(), 21)
        self.assertEqual(self.arp["arp"], self.old_arp)
        self.assertEqual(self.migration.updater.read_state(), self.old.state)

    def retire(self, legacy, copy, digest):
        self.assertTrue(legacy.matches(copy, digest))
        self.assertTrue(self.d_files.matches(self.target / policy.APP, self.catalogue.target.payload[policy.APP]))
        self.assertEqual(self.arp["arp"], self.old_arp)
        for path in self.source.iterdir():
            path.unlink()
        for link in self.links.values():
            link.unlink()
        self.arp["arp"] = None

    def assert_restored(self):
        self.assertEqual(self.migration.legacy_updater.observed_release(), self.old)
        self.assertEqual(self.arp["arp"], self.old_arp)
        self.assertEqual(self.migration.updater.read_state(), self.old.state)
        self.assertFalse(self.migration.journal.exists())
        self.assertFalse((self.target / policy.APP).exists())
        self.assertEqual(self.marker.read_bytes(), b"unrelated record")
        self.assertTrue(all(link.read_bytes() == ("C managed " + role).encode() for role, link in self.links.items()))

    def test_transfers_after_d_payload_is_complete_and_keeps_existing_d_record(self):
        self.assertEqual(self.migration.guard(), 20)
        self.stage()
        with patch.object(relocation, "retire_uninstaller", side_effect=self.retire):
            self.assertEqual(self.migration.run("commit"), "relocated")
        self.assertEqual(self.migration.guard(), 0)
        self.assertEqual(self.migration.updater.observed_release(), self.catalogue.target)
        self.assertEqual(self.migration.updater.read_state(), self.catalogue.target.state)
        self.assertEqual(self.marker.read_bytes(), b"unrelated record")
        self.assertTrue(all(link.read_bytes() == ("D managed " + role).encode() for role, link in self.links.items()))

    def test_partial_legacy_removal_restores_original_program_registration_and_links(self):
        def fail(legacy, copy, digest):
            self.retire(legacy, copy, digest)
            raise policy.Refusal("LEGACY_REMOVE_FAILED")

        self.stage()
        with patch.object(relocation, "retire_uninstaller", side_effect=fail), self.assertRaises(policy.Refusal) as raised:
            self.migration.run("commit")
        self.assertEqual(raised.exception.exit_code, 4)
        self.assert_restored()

    def test_retry_recovers_after_process_death_before_d_commit(self):
        def crash(legacy, copy, digest):
            self.retire(legacy, copy, digest)
            raise KeyboardInterrupt

        self.stage()
        with patch.object(relocation, "retire_uninstaller", side_effect=crash), self.assertRaises(KeyboardInterrupt):
            self.migration.run("commit")
        self.assertTrue(self.migration.journal.exists())
        self.assertEqual(self.migration.guard(), 22)
        with self.assertRaises(policy.Refusal) as raised:
            self.migration.run("recover")
        self.assertEqual(raised.exception.exit_code, 4)
        self.assert_restored()

    def test_d_collision_prevents_migration_and_leaves_file_intact(self):
        unexpected = self.target / policy.APP
        unexpected.write_bytes(b"a program installed by the user")
        with self.assertRaises(policy.Refusal):
            self.migration.guard()
        self.assertEqual(unexpected.read_bytes(), b"a program installed by the user")
        self.assertEqual(self.arp["arp"], self.old_arp)

    def test_cancel_trial_never_retires_c(self):
        self.stage()
        with patch.object(relocation, "retire_uninstaller") as retire:
            self.assertEqual(self.migration.run("cancel"), "trial_cancelled")
        retire.assert_not_called()
        self.assert_restored()

    def test_cancel_preserves_a_c_update_and_its_new_protected_state(self):
        self.stage()
        newer_state = policy.State("reader-later-c", 3, sha(b"newer manifest"), self.old.state.owned_paths_sha256)
        self.c_files.write_record(self.control / update_engine.STATE, newer_state.as_json())
        (self.source / policy.APP).write_bytes(b"newer C app")
        self.arp["arp"]["DisplayVersion"][0] = "1.0.2"
        self.links["start"].write_bytes(b"C shortcut changed by a newer authorized installer")
        current_arp = self.arp["arp"].copy()
        self.assertEqual(self.migration.run("cancel"), "trial_cancelled")
        self.assertEqual(self.arp["arp"], current_arp)
        self.assertEqual(self.migration.updater.read_state(), newer_state)
        self.assertEqual((self.source / policy.APP).read_bytes(), b"newer C app")
        self.assertIn(b"newer authorized", self.links["start"].read_bytes())
        self.assertFalse((self.target / policy.APP).exists())
        self.assertEqual(self.marker.read_bytes(), b"unrelated record")

    def test_cancel_refuses_when_an_owned_d_link_is_already_live(self):
        self.stage()
        self.links["start"].write_bytes(self.source_links["start"].read_bytes())
        with self.assertRaises(policy.Refusal) as raised:
            self.migration.run("cancel")
        self.assertEqual(raised.exception.code, "D_TRIAL_ALREADY_HAS_MANAGED_LINKS")
        self.assertTrue((self.target / policy.APP).exists())
        self.assertEqual(self.migration.guard(), 21)

    def test_interrupted_cancellation_resumes_only_d_cleanup(self):
        self.stage()
        original = self.migration.remove_expected

        def stop_after_one(files, path, digest):
            original(files, path, digest)
            raise KeyboardInterrupt

        with patch.object(self.migration, "remove_expected", side_effect=stop_after_one), self.assertRaises(KeyboardInterrupt):
            self.migration.run("cancel")
        self.assertEqual(self.migration.guard(), 22)
        self.assertEqual(self.migration.run("recover"), "trial_cancelled")
        self.assert_restored()

    def test_competing_legacy_setup_keeps_the_complete_trial_and_source(self):
        self.stage()
        with (patch.object(relocation, "require_legacy_mutex_available",
                           side_effect=policy.Refusal("LEGACY_SETUP_IN_PROGRESS")),
              patch.object(relocation, "retire_uninstaller") as retire,
              self.assertRaises(policy.Refusal) as raised):
            self.migration.run("commit")
        retire.assert_not_called()
        self.assertEqual(raised.exception.code, "LEGACY_SETUP_IN_PROGRESS")
        self.assertEqual(self.migration.guard(), 21)
        self.assertEqual(self.migration.legacy_updater.observed_release(), self.old)


if __name__ == "__main__":
    unittest.main()

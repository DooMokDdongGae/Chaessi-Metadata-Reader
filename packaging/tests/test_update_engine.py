"""Exercise the same update policy and transaction with disposable files only."""
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_policy as p
from update_engine import FileOperations, RELOCATION_JOURNAL, Updater, WindowsOperations, main, run_action


def sha(data):
    return hashlib.sha256(data).hexdigest()


BASE_ID = "reader-20261123-slots-02"
LEGACY_ID = "reader-20261122-release-05"
TARGET_ID = "reader-20261124-01"
BASE = {p.APP: b"old-approved-reader", "_internal/runtime.dll": b"runtime",
        "docs/README.ko.html": b"document", "product.id": p.PRODUCT_ID.encode("ascii")}
LEGACY = dict(BASE, **{p.APP: b"older-reader", "docs/README.ko.html": b"older document"})
TARGET = dict(BASE, **{p.APP: b"target-reader"})


def build(id, sequence, files):
    return {"id": id, "sequence": sequence, "payload": {name: sha(data) for name, data in files.items()}}


def catalogue(old=False):
    base = build(BASE_ID, 2026112302, BASE)
    legacy = build(LEGACY_ID, 2026112205, LEGACY)
    target = build(TARGET_ID, 2026112401, TARGET)
    return p.Catalogue.from_json({"schema": 1, "target": base if old else target,
                                  "known": [legacy] if old else [base, legacy],
                                  "patch_baseline_id": None if old else BASE_ID})


def populate(root, files):
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class PowerLoss(BaseException):
    pass


class TestOperations(FileOperations):
    running = False
    health_failure = False
    health_count = 0

    def ensure_closed(self):
        p.reject("READER_RUNNING_CLOSE_NORMALLY", self.running)

    def health(self):
        self.health_count += 1
        p.reject("NEW_READER_SELF_TEST_FAILED", self.health_failure)

    def lock(self):
        return nullcontext()


class EngineTests(unittest.TestCase):
    def setUp(self):
        sandbox = tempfile.TemporaryDirectory(prefix="reader-updater-test-")
        self.addCleanup(sandbox.cleanup)
        root = Path(sandbox.name)
        self.app = root / "install"
        self.control = root / "control"
        self.patch = root / "patch-payload"
        self.full = root / "full-payload"
        self.control.mkdir()
        populate(self.patch, {p.APP: TARGET[p.APP]})
        populate(self.full, TARGET)
        self.files = TestOperations(self.app, self.control)
        self.catalogue = catalogue()
        self.updater = Updater(self.catalogue, self.files)

    def install(self, files=BASE):
        populate(self.app, files)
        populate(self.app, {"Uninstall.exe": b"owner proof", "uninstaller.copy": b"owner proof",
                            "_installation-records/note.txt": b"sensitive user note stays here"})

    def state(self, build_id):
        value = next(r.state for r in self.catalogue.releases if r.state.id == build_id)
        self.files.write_record(self.updater.state_path, value.as_json())
        return value

    @contextmanager
    def refused(self, code):
        with self.assertRaises(p.Refusal) as refusal:
            yield
        self.assertEqual(refusal.exception.code, code)

    def crash(self, stop):
        def checkpoint(phase):
            if phase == stop:
                raise PowerLoss()

        actor = Updater(self.catalogue, self.files, checkpoint)
        with self.assertRaises(PowerLoss):
            actor.apply(self.patch, patch=True)

    def assert_payload(self, table):
        for name, data in table.items():
            self.assertEqual((self.app / name).read_bytes(), data, name)
        self.assertEqual((self.app / "_installation-records/note.txt").read_bytes(),
                         b"sensitive user note stays here")
        self.assertEqual((self.app / "Uninstall.exe").read_bytes(), b"owner proof")

    def test_exact_patch_and_full_converge_preserving_owned_receipts_and_records(self):
        self.install()
        self.assertEqual(self.updater.status(), "upgrade")
        self.assertEqual(self.updater.apply(self.patch, patch=True), "applied")
        self.assert_payload(TARGET)
        self.assertEqual(self.updater.status(), "current")
        self.assertEqual(self.updater.apply(self.patch, patch=True), "already_current")
        self.assertEqual(self.files.health_count, 1)
        self.install(LEGACY)  # Simulates an already shipped, unguarded Setup.
        with self.refused("PATCH_REQUIRES_APPROVED_BASELINE"):
            self.updater.apply(self.patch, patch=True)
        self.assert_payload(LEGACY)
        self.assertEqual(self.updater.status(), "repair")
        self.assertEqual(self.updater.apply(self.full, patch=False), "repaired")
        self.assert_payload(TARGET)
        self.assertEqual(self.updater.read_state(), self.catalogue.target.state)

    def test_exact_previous_approved_overwrite_is_repaired_without_lowering_high_water(self):
        self.install()
        latest = self.state(TARGET_ID)
        self.assertEqual(self.updater.apply(self.patch, patch=True), "repaired")
        self.assertEqual(self.updater.read_state(), latest)
        self.assert_payload(TARGET)

    def test_protected_old_guard_blocks_newer_or_absent_install_with_newer_high_water(self):
        self.state(TARGET_ID)
        old = Updater(catalogue(old=True), self.files)
        with self.refused("DOWNGRADE_BLOCKED"):
            old.status()
        self.install(TARGET)
        with self.refused("DOWNGRADE_BLOCKED"):
            old.status()
        with self.refused("DOWNGRADE_BLOCKED"):
            old.apply(self.full, patch=False)
        self.assert_payload(TARGET)

    def test_guarded_older_uninstaller_retains_same_path_ownership_after_update(self):
        self.install()
        self.updater.apply(self.patch, patch=True)
        old = Updater(catalogue(old=True), self.files)
        with self.refused("DOWNGRADE_BLOCKED"):
            old.status()
        self.assertEqual(old.uninstall_guard(), "uninstall_allowed")
        latest = self.updater.read_state()
        forged = dict(latest.as_json(), owned_paths_sha256="e" * 64)
        self.files.write_record(self.updater.state_path, forged)
        with self.refused("UNINSTALLER_OWNERSHIP_CHANGED"):
            old.uninstall_guard()
        self.assert_payload(TARGET)

    def test_unrelated_known_id_with_wrong_hash_is_refused(self):
        self.install()
        current = self.state(BASE_ID)
        forged = dict(current.as_json(), manifest_sha256="a" * 64)
        self.files.write_record(self.updater.state_path, forged)
        with self.refused("UNKNOWN_RECORDED_BUILD"):
            self.updater.status()
        self.assert_payload(BASE)

    def test_partial_install_unknown_dll_and_invalid_owner_stop_prewrite(self):
        self.install()
        (self.app / "docs/README.ko.html").write_bytes(b"mixed")
        with self.refused("UNKNOWN_OR_PARTIAL_INSTALLATION"):
            self.updater.apply(self.patch, patch=True)
        self.assertEqual((self.app / p.APP).read_bytes(), BASE[p.APP])
        self.install()
        occupy = self.app / "_internal/unknown.dll"
        occupy.write_bytes(b"user binary")
        with self.refused("UNEXPECTED_RUNTIME_FILE"):
            self.updater.apply(self.patch, patch=True)
        self.assertEqual(occupy.read_bytes(), b"user binary")
        occupy.unlink()
        (self.app / "uninstaller.copy").write_bytes(b"other software")
        with self.refused("UNINSTALLER_OWNERSHIP_MISMATCH"):
            self.updater.apply(self.patch, patch=True)
        self.assertEqual((self.app / p.APP).read_bytes(), BASE[p.APP])
        self.assertFalse(self.updater.journal_path.exists())

    def test_hard_link_is_refused_without_touching_linked_data(self):
        self.install()
        sentinel = self.app.parent / "sentinel"
        try:
            os.link(self.app / p.APP, sentinel)
        except OSError:
            self.skipTest("hard links unavailable in this test sandbox")
        with self.refused("UNSAFE_FILE_OR_DIRECTORY"):
            self.updater.apply(self.patch, patch=True)
        self.assertEqual(sentinel.read_bytes(), BASE[p.APP])

    def test_running_reader_and_corrupt_staged_payload_stop_before_journal(self):
        self.install()
        self.files.running = True
        with self.refused("READER_RUNNING_CLOSE_NORMALLY"):
            self.updater.apply(self.patch, patch=True)
        self.files.running = False
        (self.patch / p.APP).write_bytes(b"wrong Reader")
        with self.refused("STAGED_PAYLOAD_MISMATCH"):
            self.updater.apply(self.patch, patch=True)
        self.assertFalse(self.updater.journal_path.exists())
        self.assert_payload(BASE)

    def test_health_failure_restores_files_and_preexisting_high_water(self):
        self.install()
        original = self.state(BASE_ID)
        self.files.health_failure = True
        with self.refused("PATCH_ROLLED_BACK"):
            self.updater.apply(self.patch, patch=True)
        self.assert_payload(BASE)
        self.assertEqual(self.updater.read_state(), original)
        self.assertFalse(self.updater.journal_path.exists())

    def test_full_setup_replaces_only_changed_files_and_can_repair_a_known_overwrite(self):
        self.install(LEGACY)
        self.state(BASE_ID)
        runtime = self.app / "_internal/runtime.dll"
        receipt = self.app / "Uninstall.exe"
        unchanged = {path: self.files.inspect(path) for path in (runtime, receipt)}
        self.assertEqual(self.updater.status(), "repair")
        self.assertEqual(self.updater.apply(self.full, patch=False), "repaired")
        self.assert_payload(TARGET)
        self.assertEqual({path: self.files.inspect(path) for path in unchanged}, unchanged)
        self.assertEqual(self.updater.status(), "current")
        self.assertEqual(self.updater.apply(self.full, patch=False), "already_current")
        self.assertEqual(self.files.health_count, 1)

    def test_full_setup_health_failure_rolls_back_without_advancing_high_water(self):
        self.install(LEGACY)
        initial = self.state(LEGACY_ID)
        self.files.health_failure = True
        with self.refused("SETUP_ROLLED_BACK"):
            self.updater.apply(self.full, patch=False)
        self.assertEqual(self.updater.read_state(), initial)
        self.assert_payload(LEGACY)
        self.assertFalse(self.updater.journal_path.exists())

    def expanded_setup(self):
        files = dict(TARGET, **{"_internal/cryptography/_rust.pyd": b"pinned SDK",
                                "docs/licenses/CRYPTOGRAPHY.txt": b"vendor terms"})
        target = build(TARGET_ID, 2026112401, files)
        self.catalogue = p.Catalogue.from_json({"schema": 1, "target": target,
            "known": [build(BASE_ID, 2026112302, BASE), build(LEGACY_ID, 2026112205, LEGACY)],
            "patch_baseline_id": None})
        self.updater = Updater(self.catalogue, self.files)
        populate(self.full, files)
        owner = self.full.parent / "reader-uninstaller.generated"
        owner.write_bytes(b"new remover owns SDK paths")
        return files, owner

    def test_full_additive_sdk_upgrade_replaces_both_remover_receipts_and_is_idempotent(self):
        files, owner = self.expanded_setup()
        self.install()
        self.state(BASE_ID)
        self.assertEqual(self.updater.apply(self.full, patch=False, uninstaller=owner), "applied")
        for name, data in files.items():
            self.assertEqual((self.app / name).read_bytes(), data)
        for name in ("Uninstall.exe", "uninstaller.copy"):
            self.assertEqual((self.app / name).read_bytes(), owner.read_bytes())
        self.assertEqual(self.updater.uninstall_guard(), "uninstall_allowed")
        self.assertEqual(self.updater.apply(self.full, patch=False, uninstaller=owner), "already_current")
        self.assertEqual((self.app / "_installation-records/note.txt").read_bytes(), b"sensitive user note stays here")
        with self.refused("UNINSTALLER_OWNERSHIP_CHANGED"):
            Updater(catalogue(old=True), self.files).uninstall_guard()

    def test_full_additive_upgrade_requires_new_remover_and_refuses_foreign_file_collision(self):
        files, owner = self.expanded_setup()
        self.install()
        with self.refused("SETUP_NEW_UNINSTALLER_REQUIRED"):
            self.updater.apply(self.full, patch=False)
        with self.refused("UNAPPROVED_UNINSTALLER_STAGE"):
            self.updater.apply(self.full, patch=False, uninstaller=owner.with_name("other.exe"))
        collision = self.app / "docs/licenses/CRYPTOGRAPHY.txt"
        collision.parent.mkdir(parents=True)
        collision.write_bytes(b"unrelated existing document")
        with self.refused("BASELINE_CHANGED_BEFORE_BACKUP"):
            self.updater.apply(self.full, patch=False, uninstaller=owner)
        self.assertEqual(collision.read_bytes(), b"unrelated existing document")
        self.assertFalse(self.updater.journal_path.exists())
        self.assert_payload(BASE)

    def test_full_additive_upgrade_health_failure_restores_old_remover_and_removes_added_files(self):
        files, owner = self.expanded_setup()
        self.install()
        initial = self.state(BASE_ID)
        self.files.health_failure = True
        with self.refused("SETUP_ROLLED_BACK"):
            self.updater.apply(self.full, patch=False, uninstaller=owner)
        self.assert_payload(BASE)
        self.assertEqual((self.app / "uninstaller.copy").read_bytes(), b"owner proof")
        for name in files.keys() - BASE.keys():
            self.assertFalse((self.app / name).exists())
        self.assertEqual(self.updater.read_state(), initial)
        self.assertFalse(self.updater.journal_path.exists())

    def test_full_additive_upgrade_recovers_interruption_after_each_changed_file_and_remover(self):
        files, owner = self.expanded_setup()
        count = len(p.changed_paths(next(r for r in self.catalogue.releases if r.state.id == BASE_ID),
                                    self.catalogue.target)) + 2
        for stop in range(1, count + 1):
            with self.subTest(after_replacement=stop):
                self.install()
                initial = self.state(BASE_ID)
                replaced = 0

                def crash(phase):
                    nonlocal replaced
                    if phase == "after_replace":
                        replaced += 1
                        if replaced == stop:
                            raise PowerLoss()

                with self.assertRaises(PowerLoss):
                    Updater(self.catalogue, self.files, crash).apply(self.full, patch=False, uninstaller=owner)
                self.assertTrue(self.updater.recover(initial))
                self.assert_payload(BASE)
                self.assertEqual((self.app / "uninstaller.copy").read_bytes(), b"owner proof")
                for name in files.keys() - BASE.keys():
                    self.assertFalse((self.app / name).exists())

    def test_added_file_changed_after_interruption_is_preserved_with_recovery_journal(self):
        _files, owner = self.expanded_setup()
        self.install()
        initial = self.state(BASE_ID)

        def crash(phase):
            if phase == "checked":
                raise PowerLoss()

        with self.assertRaises(PowerLoss):
            Updater(self.catalogue, self.files, crash).apply(self.full, patch=False, uninstaller=owner)
        changed = self.app / "_internal/cryptography/_rust.pyd"
        changed.write_bytes(b"external change preserve")
        with self.refused("ROLLBACK_BLOCKED_EXTERNAL_CHANGE"):
            self.updater.recover(initial)
        self.assertEqual(changed.read_bytes(), b"external change preserve")
        self.assertTrue(self.updater.journal_path.exists())

    def test_after_replacement_interruption_is_recovered_then_retried(self):
        self.install()
        self.crash("after_replace")
        self.assertEqual((self.app / p.APP).read_bytes(), TARGET[p.APP])
        with self.refused("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER"):
            self.updater.status()
        with self.refused("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER"):
            self.updater.uninstall_guard()
        with self.refused("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER"):
            Updater(catalogue(old=True), self.files).apply(self.full, patch=False)
        self.assertEqual(self.updater.apply(self.patch, patch=True), "recovered_and_applied")
        self.assert_payload(TARGET)

    def test_multi_file_full_update_interruption_rolls_back_before_next_attempt(self):
        self.install(LEGACY)

        def stop_after_first(phase):
            if phase == "after_replace":
                raise PowerLoss()

        with self.assertRaises(PowerLoss):
            Updater(self.catalogue, self.files, stop_after_first).apply(self.full, patch=False)
        self.assertEqual((self.app / p.APP).read_bytes(), TARGET[p.APP])
        self.assertEqual((self.app / "docs/README.ko.html").read_bytes(), LEGACY["docs/README.ko.html"])
        self.assertTrue(self.updater.recover(None))
        self.assert_payload(LEGACY)
        self.assertFalse(self.updater.journal_path.exists())
        self.assertEqual(self.updater.apply(self.full, patch=False), "applied")
        self.assert_payload(TARGET)

    def test_verified_but_not_committed_is_retried_and_committed_interruption_is_idempotent(self):
        self.install()
        self.crash("verified")
        self.assertIsNone(self.updater.read_state())
        self.assertEqual(self.updater.apply(self.patch, patch=True), "recovered_and_applied")
        self.install()
        self.crash("committed")
        self.assertEqual(self.updater.read_state(), self.catalogue.target.state)
        self.assertEqual(self.updater.apply(self.patch, patch=True), "already_current")
        self.assert_payload(TARGET)

    def test_recovery_never_overwrites_a_later_external_file(self):
        self.install()
        self.crash("after_replace")
        outsider = b"a different writer changed this after the crash"
        (self.app / p.APP).write_bytes(outsider)
        with self.refused("ROLLBACK_BLOCKED_EXTERNAL_CHANGE"):
            self.updater.apply(self.patch, patch=True)
        self.assertEqual((self.app / p.APP).read_bytes(), outsider)
        self.assertTrue(self.updater.journal_path.exists())

    def test_corrupt_rollback_backup_leaves_journal_and_current_bytes(self):
        self.install()
        self.crash("after_replace")
        path = next(self.control.glob("txn-*/before-0"))
        path.write_bytes(b"damaged backup")
        with self.refused("ROLLBACK_BACKUP_INVALID"):
            self.updater.apply(self.patch, patch=True)
        self.assert_payload(TARGET)
        self.assertTrue(self.updater.journal_path.exists())

    def test_fresh_commit_requires_observed_files_and_keeps_record_on_uninstall(self):
        self.assertEqual(self.updater.status(), "fresh")
        with self.refused("SETUP_TARGET_NOT_INSTALLED"):
            self.updater.commit_setup()
        self.install(TARGET)
        self.assertEqual(self.updater.status(), "adopt_current")
        self.assertEqual(self.updater.commit_setup(), "committed")
        self.assertEqual(self.updater.uninstall_guard(), "uninstall_allowed")
        self.assertEqual(self.updater.read_state(), self.catalogue.target.state)

    def test_completed_files_without_commit_are_adopted_only_after_health(self):
        self.install(TARGET)
        self.files.health_failure = True
        with self.refused("NEW_READER_SELF_TEST_FAILED"):
            self.updater.apply(self.patch, patch=True)
        self.assertIsNone(self.updater.read_state())
        self.assertEqual(self.updater.status(), "adopt_current")
        self.files.health_failure = False
        self.assertEqual(self.updater.apply(self.patch, patch=True), "committed_existing")
        self.assertEqual(self.updater.status(), "current")

    def test_fresh_reinstall_rechecks_health_even_with_retained_latest_ledger(self):
        self.state(TARGET_ID)
        self.assertEqual(self.updater.begin_setup(), "fresh_setup_begun")
        self.assertEqual(self.updater.status(), "fresh")
        self.assertEqual(self.updater.begin_setup(), "fresh_setup_begun")
        self.install(TARGET)
        self.assertEqual(self.updater.status(), "adopt_current")
        with self.refused("INTERRUPTED_UPDATE_REQUIRES_SAME_UPDATER"):
            self.updater.uninstall_guard()
        self.files.health_failure = True
        with self.refused("NEW_READER_SELF_TEST_FAILED"):
            self.updater.commit_setup()
        self.assertTrue(self.updater.fresh_path.exists())
        self.files.health_failure = False
        self.assertEqual(self.updater.commit_setup(), "committed")
        self.assertFalse(self.updater.fresh_path.exists())

    def relocated(self, location="fixed-qa-volume-a"):
        self.files = TestOperations(self.app, self.control, transaction_root=self.app, location=location)
        self.updater = Updater(self.catalogue, self.files)

    def test_d_update_and_rollback_use_the_install_volume_but_journal_stays_in_control(self):
        self.install()
        self.relocated()
        self.crash("after_replace")
        row = p.parse_json(self.updater.journal_path.read_bytes())
        directory = self.app / row["workspace"]
        self.assertEqual(row["volume"], self.files.location)
        self.assertEqual(row["schema"], 2)
        self.assertTrue(directory.is_dir())
        self.assertEqual((directory / "before-0").read_bytes(), BASE[p.APP])
        self.assertFalse(list(self.control.glob("txn-*")))
        self.assertTrue(self.updater.recover(None))
        self.assert_payload(BASE)
        self.assertFalse(directory.exists())
        self.assertEqual(self.updater.apply(self.full, patch=False), "applied")
        self.assert_payload(TARGET)

    def test_d_recovery_rejects_wrong_mount_and_unconfined_workspaces_without_mutation(self):
        self.install()
        self.relocated()
        self.crash("after_replace")
        row = p.parse_json(self.updater.journal_path.read_bytes())
        wrong_location = TestOperations(self.app, self.control, transaction_root=self.app,
                                        location="fixed-qa-volume-b")
        with self.refused("INTERRUPTED_UPDATE_REQUIRES_SAME_INSTALLATION"):
            Updater(self.catalogue, wrong_location).recover(None)
        self.assertEqual((self.app / p.APP).read_bytes(), TARGET[p.APP])
        self.files.write_record(self.updater.journal_path, {**row, "workspace": "../unsafe"})
        with self.refused("INVALID_UPDATE_JOURNAL"):
            self.updater.recover(None)
        self.files.write_record(self.updater.journal_path, row)
        self.assertTrue(self.updater.recover(None))
        self.assert_payload(BASE)

    def test_shared_control_records_cannot_be_adopted_by_the_wrong_installation(self):
        self.assertEqual(self.updater.begin_setup(), "fresh_setup_begun")
        self.relocated()
        with self.refused("INTERRUPTED_UPDATE_REQUIRES_SAME_INSTALLATION"):
            self.updater.status()
        self.assertTrue(self.updater.fresh_path.exists())

    def test_pending_relocation_blocks_ordinary_guard_and_remover(self):
        self.install()
        self.relocated()
        self.files.write_record(self.control / RELOCATION_JOURNAL, {"schema": 1})
        for action in ("guard", "setup-begin", "setup-commit", "setup-apply", "uninstall-guard"):
            with self.subTest(action=action), self.refused("RELOCATION_REQUIRES_SAME_SETUP"):
                run_action(SimpleNamespace(action=action), self.catalogue, self.files)
        self.assert_payload(BASE)

    def test_relocation_dispatch_never_locks_around_the_coordinator(self):
        status = {0: "ordinary_setup", 20: "relocation_required",
                  21: "relocation_trial_verified", 22: "relocation_recovery_required"}
        guard = Mock(side_effect=[*status, True, 23])
        migrate = Mock(return_value="relocated")
        stub = SimpleNamespace(guard=guard, migrate=migrate)
        args = SimpleNamespace(action="relocate", payload=self.full, uninstaller=self.app / "Uninstall.exe",
                               start_link=self.app / "start-link.copy", guide_link=self.app / "guide-link.copy",
                               desktop_link=self.app / "desktop-link.copy", installer_language=1042,
                               operation="stage")
        later_operations = ("commit", "cancel", "recover")
        guard_args = SimpleNamespace(action="relocate-guard")
        with (patch.dict(sys.modules, {"relocation": stub}),
              patch.object(self.files, "lock") as lock,
              patch("update_engine.windows_api", return_value=(None, SimpleNamespace(local_path=Path)))):
            for code, message in status.items():
                self.assertEqual(run_action(guard_args, self.catalogue, self.files), (message, code))
            for _ in range(2):
                with self.refused("INVALID_RELOCATION_DECISION"):
                    run_action(guard_args, self.catalogue, self.files)
            self.assertEqual(run_action(args, self.catalogue, self.files), ("relocated", 0))
            for operation in later_operations:
                later = SimpleNamespace(action="relocate", operation=operation)
                self.assertEqual(run_action(later, self.catalogue, self.files), ("relocated", 0))
            lock.assert_not_called()
        self.assertEqual(guard.call_args_list, [call(self.catalogue, self.files)] * 6)
        self.assertEqual(migrate.call_args_list, [
            call(self.catalogue, self.files, payload=self.full, uninstaller=args.uninstaller,
                 start_link=args.start_link, guide_link=args.guide_link, desktop_link=args.desktop_link,
                 installer_language=1042, operation="stage"),
            *(call(self.catalogue, self.files, payload=None, uninstaller=None, start_link=None, guide_link=None,
                   desktop_link=None, installer_language=None, operation=operation) for operation in later_operations)
        ])

    def test_relocation_requires_stage_inputs_only_for_stage(self):
        options = ["--payload", "payload", "--uninstaller", "uninstall.exe",
                   "--start-link", "start.lnk", "--guide-link", "guide.lnk", "--desktop-link", "desktop.lnk",
                   "--installer-language", "1042"]
        with (patch.object(sys, "frozen", True, create=True),
              patch("update_engine.load_catalogue", return_value=self.catalogue) as load,
              patch("update_engine.WindowsOperations.for_user", return_value=self.files),
              patch("update_engine.run_action", return_value=("accepted", 0)) as action,
              redirect_stderr(StringIO()), redirect_stdout(StringIO())):
            for index in range(0, len(options), 2):
                incomplete = options[:index] + options[index + 2:]
                with self.subTest(missing=options[index]), self.assertRaises(SystemExit) as refused:
                    main(["relocate", "--operation", "stage", *incomplete])
                self.assertEqual(refused.exception.code, 2)
                for operation in ("commit", "cancel", "recover"):
                    with self.subTest(operation=operation, extra=options[index]), self.assertRaises(SystemExit) as refused:
                        main(["relocate", "--operation", operation, *options[index:index + 2]])
                    self.assertEqual(refused.exception.code, 2)
            load.assert_not_called()
            self.assertEqual(main(["relocate", "--operation", "stage", *options]), 0)
            self.assertEqual(action.call_args.args[0].desktop_link, Path("desktop.lnk"))
            for operation in ("commit", "cancel", "recover"):
                self.assertEqual(main(["relocate", "--operation", operation]), 0)
                self.assertIsNone(action.call_args.args[0].installer_language)


class PolicyTests(unittest.TestCase):
    def test_rejects_non_normalized_windows_paths(self):
        for invalid in ("../out", "sub//outside", "NUL.txt", "COM4 .txt", "abé.dll", "sub\\path", "a."):
            with self.subTest(invalid=invalid), self.assertRaises(p.Refusal):
                p.relative_parts(invalid)

    def test_rejects_manifest_directory_case_and_file_conflicts(self):
        for names in (("Dir/a.txt", "dir/b.txt"), ("dir", "dir/a.txt")):
            with self.subTest(names=names), self.assertRaises(p.Refusal):
                new = dict(TARGET, **{name: b"sample" for name in names})
                p.Release.from_json(build(TARGET_ID, 2026112401, new))

    def test_added_paths_require_full_setup_and_removed_paths_remain_unsupported(self):
        source = p.Release.from_json(build(BASE_ID, 2026112302, BASE))
        extra = p.Release.from_json(build(TARGET_ID, 2026112401, dict(TARGET, **{"new.dll": b"module"})))
        with self.assertRaises(p.Refusal):
            p.changed_paths(source, extra, patch=True)
        self.assertEqual(p.changed_paths(source, extra), (p.APP, "new.dll"))
        with self.assertRaises(p.Refusal):
            p.changed_paths(extra, source)


@unittest.skipUnless(os.name == "nt", "requires Windows ReplaceFileW")
class NativePrimitiveTests(unittest.TestCase):
    def test_native_additive_full_upgrade_and_health_failure_rollback(self):
        class NativeOperations(WindowsOperations):
            has_registration = FileOperations.has_registration
            fail_health = False

            def verify_mount(self):
                return self.location

            def ensure_closed(self):
                pass

            def health(self):
                p.reject("NEW_READER_SELF_TEST_FAILED", self.fail_health)

        with tempfile.TemporaryDirectory(prefix="reader-native-expansion-") as temp:
            root = Path(temp)
            install, control, stage = root / "product", root / "private", root / "payload"
            files = NativeOperations(install, control, transaction_root=install, location="native-fixture-volume")
            files.make_dir(control)
            expanded = dict(TARGET, **{"_internal/sdk/rust.pyd": b"native SDK fixture"})
            cat = p.Catalogue.from_json({"schema": 1, "target": build(TARGET_ID, 2026112401, expanded),
                "known": [build(BASE_ID, 2026112302, BASE)], "patch_baseline_id": None})
            populate(install, BASE)
            populate(install, {"Uninstall.exe": b"old remover", "uninstaller.copy": b"old remover"})
            populate(stage, expanded)
            owner = root / "reader-uninstaller.generated"
            owner.write_bytes(b"expanded remover")
            updater = Updater(cat, files)
            files.fail_health = True
            with self.assertRaises(p.Refusal) as refusal:
                updater.apply(stage, patch=False, uninstaller=owner)
            self.assertEqual(refusal.exception.code, "SETUP_ROLLED_BACK", repr(refusal.exception.__cause__))
            self.assertTrue(updater.matches_release(cat.releases[1]))
            self.assertFalse((install / "_internal/sdk/rust.pyd").exists())
            self.assertEqual((install / "Uninstall.exe").read_bytes(), b"old remover")
            self.assertFalse(updater.journal_path.exists())
            files.fail_health = False
            with patch.object(files, "protect_displaced", side_effect=PowerLoss):
                with self.assertRaises(PowerLoss):
                    updater.apply(stage, patch=False, uninstaller=owner)
            self.assertTrue(updater.journal_path.exists())
            # Exact post-ReplaceFileW/pre-DACL crash: recovery must harden only
            # the known displaced bytes, then restore the protected baseline.
            self.assertTrue(updater.recover(None))
            self.assertTrue(updater.matches_release(cat.releases[1]))
            self.assertEqual((install / "Uninstall.exe").read_bytes(), b"old remover")
            self.assertEqual(updater.apply(stage, patch=False, uninstaller=owner), "applied")
            self.assertEqual((install / "Uninstall.exe").read_bytes(), b"expanded remover")
            self.assertEqual(updater.uninstall_guard(), "uninstall_allowed")

    def test_remove_added_rollback_member_uses_verified_windows_handle(self):
        with tempfile.TemporaryDirectory(prefix="reader-native-delete-") as temp:
            root = Path(temp)
            operations = WindowsOperations(root, root / "control")
            member = root / "sdk.pyd"
            member.write_bytes(b"known added SDK file")
            snapshot = operations.inspect(member)
            member.write_bytes(b"external new content")
            with self.assertRaises(p.Refusal) as refusal:
                operations.remove_owned(member, snapshot)
            self.assertEqual(refusal.exception.code, "ROLLBACK_BLOCKED_EXTERNAL_CHANGE")
            self.assertEqual(member.read_bytes(), b"external new content")
            operations.remove_owned(member, operations.inspect(member))
            self.assertFalse(member.exists())

    def test_transaction_workspace_creation_never_adopts_existing_directory(self):
        with tempfile.TemporaryDirectory(prefix="reader-native-workspace-") as temp:
            root = Path(temp)
            files = WindowsOperations(root / "product", root / "control")
            files.make_dir(files.control)
            transaction = files.allocate_transaction_workspace()
            keep = transaction / "outside-file"
            keep.write_bytes(b"preserve collision")
            with self.assertRaises(OSError) as refusal:
                files.make_transaction_dir(transaction)
            self.assertEqual(refusal.exception.winerror, 183)
            self.assertEqual(keep.read_bytes(), b"preserve collision")

    def test_different_volume_is_rejected_before_platform_replacement(self):
        control = Path(r"C:\SyntheticControl")
        install = Path(r"D:\SyntheticReader")
        files = WindowsOperations(install, control)
        with patch("update_engine.os.stat", side_effect=lambda path, **_: SimpleNamespace(
                st_dev=1 if path.drive == "C:" else 2)):
            with self.assertRaises(p.Refusal) as refusal:
                files.require_same_volume(control / "stage", install / p.APP, install / "backup")
            self.assertEqual(refusal.exception.code, "UPDATE_REPLACEMENT_WRONG_VOLUME")
            files.require_same_volume(install / "stage", install / p.APP, install / "backup")

    def test_real_replace_and_rollback_in_temporary_directory(self):
        with tempfile.TemporaryDirectory(prefix="reader-native-replace-") as temp:
            root = Path(temp)
            operations = WindowsOperations(root / "product", root / "control")
            operations.install.mkdir()
            operations.make_dir(operations.control)
            current = operations.install / p.APP
            staged = operations.control / "new-file"
            displaced = operations.control / "displaced-file"
            recovery = operations.control / "old-file"
            current.write_bytes(BASE[p.APP])
            staged.write_bytes(TARGET[p.APP])
            recovery.write_bytes(BASE[p.APP])
            snapshot = operations.inspect(current)
            operations.replace_owned(staged, current, displaced, snapshot)
            self.assertEqual(current.read_bytes(), TARGET[p.APP])
            self.assertEqual(displaced.read_bytes(), BASE[p.APP])
            operations.replace_owned(recovery, current, operations.control / "removed",
                                     operations.inspect(current))
            self.assertEqual(current.read_bytes(), BASE[p.APP])

    def test_real_file_lock_excludes_second_handle(self):
        with tempfile.TemporaryDirectory(prefix="reader-native-lock-") as temp:
            root = Path(temp)
            first = WindowsOperations(root / "product", root / "private")
            second = WindowsOperations(root / "product", root / "private")
            with first.lock():
                with self.assertRaises(p.Refusal) as lock_refusal:
                    with second.lock():
                        self.fail("allowed a competing update operation")
                self.assertEqual(lock_refusal.exception.code, "UPDATE_IN_PROGRESS")
            with second.lock():
                self.assertTrue((second.control / "update.lock").is_file())


if __name__ == "__main__":
    unittest.main()

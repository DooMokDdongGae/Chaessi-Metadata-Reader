"""Synthetic session regressions for CHS-REQ-20261125-001.

These tests exercise session/transport ordering without a real process, socket,
profile or publisher key. Cryptographic parsing is tested by test_preset_release;
none of the synthetic release objects here is a trusted package fixture.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bundle import preset_library as library
from bundle import preset_release as releases
from bundle import preset_session as session
from bundle import transfer_client as client
from bundle import transfer_registry as registry
from bundle.tests.test_preset_release import SigningFixture, Ed25519PrivateKey, NOW, row
from bundle.tests.test_preset_library import sample


class SyntheticRelease:
    """Match VerifiedRelease's public shape; expose pin lifetime to assertions."""

    def __init__(self, launcher, *, layout="unpacked", receiver="receiver.exe", sequence=1):
        self.launcher = launcher
        self.launcher_file = SimpleNamespace(path=receiver if layout == "unpacked" else launcher.name)
        self.layout, self.receiver = layout, receiver
        self.launcher_digest = "a" * 64
        self.metadata = {"sequence": sequence, "layout": layout, "receiver": receiver}
        self.events = []
        self.pinned = 0
        self.recheck = Mock()
        self.commit_authenticated = Mock(side_effect=lambda store: self.events.append("commit"))

    @contextmanager
    def pin_tree(self, root):
        self.events.append(("pin", root))
        self.pinned += 1
        try:
            yield self.recheck
        finally:
            self.pinned -= 1
            self.events.append(("unpin", root))


class SignedPresetSessionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.launcher = self.root / "receiver.exe"
        self.inner = self.root / "extracted" / "app" / "receiver.exe"
        for path in (self.launcher, self.inner):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic executable; never executed")
        # Avoid constructing a real protected settings store.
        self.reader = session.PresetSession.__new__(session.PresetSession)
        self.reader.store = Mock()
        self.reader.store.root = self.root / "reader-library"
        self.reader.release_store = object()
        self.reader.publisher_roots = {"synthetic": bytes(32)}
        self.record = library.ExeInfo(self.launcher, "b" * 64, "5.0.0", "PRIVATE", "Synthetic")
        self.release = SyntheticRelease(self.launcher)
        self.endpoint = client.Endpoint(
            "a7c71528-3279-4aa9-adc8-e7a27c94cf55", 31001, bytes(32), 100,
            str(self.launcher), "a" * 64, 10, compatibility="compatible")
        self.processes = {100: (1, self.launcher.name)}
        self.images = {100: (self.launcher, 10)}
        self.process_pins = set()
        self.process_checks = []
        self.file_pins = []
        self.enterContext(patch.object(registry, "checked_handle", side_effect=self.checked_handle))
        self.enterContext(patch.object(registry, "_process", side_effect=self.process))
        self.enterContext(patch.object(registry, "process_snapshot", side_effect=lambda: self.processes))
        self.enterContext(patch.object(registry, "_digest", return_value=self.release.launcher_digest))
        self.enterContext(patch.object(self.reader, "_exclusive", side_effect=nullcontext))

    @contextmanager
    def checked_handle(self, path, **kwargs):
        path = Path(path)
        self.file_pins.append(path)
        try:
            yield path
        finally:
            self.file_pins.remove(path)

    @contextmanager
    def process(self, pid, hwnd=None):
        if pid not in self.images:
            raise session._error("unverified")
        path, created = self.images[pid]
        self.process_pins.add(pid)
        try:
            yield path, created, lambda: self.process_checks.append(pid)
        finally:
            self.process_pins.discard(pid)

    def patch_release(self, release=None):
        return self.enterContext(patch.object(
            releases, "inspect_release", return_value=self.release if release is None else release))

    def signed_endpoint(self, release=None):
        return self.reader._signed_endpoint(
            self.endpoint, (100, 10), self.launcher, release or self.release)

    def portable(self):
        self.release = SyntheticRelease(self.launcher, layout="portable", receiver="app/receiver.exe")
        self.endpoint = replace(self.endpoint, pid=102, exe=str(self.inner), created=30)
        self.processes = {100: (1, self.launcher.name), 101: (100, "intermediate.exe"),
                          102: (101, self.inner.name)}
        self.images.update({101: (self.root / "intermediate.exe", 20), 102: (self.inner, 30)})

    @contextmanager
    def registered_process(self, endpoint):
        # Registered process/socket validation remains the existing transport's
        # responsibility. It must run inside, never instead of, the signed guard.
        self.assertGreater(self.release.pinned, 0)
        self.assertIn(self.launcher, self.file_pins)
        self.assertIn(100, self.process_pins)
        yield endpoint, lambda: None

    def test_signed_unknown_digest_can_be_configured_after_complete_unpacked_pin(self):
        self.patch_release()
        self.reader.store.select_default.side_effect = lambda record: record
        saved = self.reader.configure(self.record)
        self.assertEqual(saved.digest, self.release.launcher_digest)
        self.reader.store.select_default.assert_called_once_with(saved)
        self.assertIn(("pin", self.root), self.release.events)
        self.assertEqual(self.release.pinned, 0)
        self.release.commit_authenticated.assert_not_called()

    def test_new_signed_bytes_at_same_path_are_reverified_without_old_digest_whitelist(self):
        updated = SyntheticRelease(self.launcher, sequence=2)
        updated.launcher_digest = "c" * 64
        self.patch_release(updated)
        registry._digest.return_value = updated.launcher_digest
        with self.reader._selection(self.record) as (effective, path, verified):
            self.assertEqual(effective.digest, "c" * 64)
            self.assertEqual(path, self.launcher)
            self.assertIs(verified, updated)
            self.assertEqual(updated.pinned, 1)
        self.assertEqual(self.record.digest, "b" * 64)
        updated.commit_authenticated.assert_not_called()

    def test_invalid_or_partial_signature_never_falls_back_even_for_known_legacy_hash(self):
        legacy = replace(self.record, digest=session.PUBLIC_PORTABLE)
        with patch.object(releases, "inspect_release", side_effect=releases.ReleaseError()), \
                patch.object(session, "_selected_file") as fallback:
            with self.assertRaisesRegex(client.TransferError, r"preset\.signature_invalid"):
                with self.reader._selection(legacy):
                    self.fail("Invalid signed metadata reached selection")
            fallback.assert_not_called()

    def test_sidecar_absence_alone_keeps_existing_legacy_path(self):
        with patch.object(releases, "inspect_release", return_value=None), \
                patch.object(session, "_selected_file", side_effect=lambda record, **kw: nullcontext(record.path)) as fallback:
            with self.reader._selection(self.record) as (_, path, release):
                self.assertEqual(path, self.launcher)
                self.assertIsNone(release)
            fallback.assert_called_once_with(self.record, deadline=None)

    def test_signature_error_categories_are_not_hidden_as_legacy_or_availability(self):
        expected = {"SIGNATURE_EXPIRED": "signature_expired", "SIGNATURE_REVOKED": "signature_revoked",
                    "SIGNATURE_ROLLBACK": "signature_rollback", "RUNTIME_MISMATCH": "runtime_mismatch"}
        for reason, suffix in expected.items():
            with self.subTest(reason=reason), patch.object(
                    releases, "inspect_release", side_effect=releases.ReleaseError(reason)):
                with self.assertRaises(client.TransferError) as caught:
                    self.reader._release(self.launcher)
                self.assertEqual(caught.exception.code, "preset." + suffix)
                self.assertFalse(caught.exception.delivery_possible)

    def test_launcher_digest_change_blocks_before_saving_choice(self):
        self.patch_release()
        registry._digest.return_value = "f" * 64
        with self.assertRaisesRegex(client.TransferError, r"preset\.runtime_mismatch"):
            self.reader.configure(self.record)
        self.reader.store.select_default.assert_not_called()
        self.release.commit_authenticated.assert_not_called()

    def test_unpacked_receiver_must_be_the_exact_launcher_pid(self):
        self.patch_release()
        with self.reader._signed_bound(self.endpoint, (100, 10), self.launcher, self.release):
            self.assertEqual(self.release.pinned, 1)
        for altered in (replace(self.endpoint, pid=101), replace(self.endpoint, created=11),
                        replace(self.endpoint, exe=str(self.inner))):
            with self.subTest(endpoint=altered), self.assertRaises(client.TransferError):
                with self.reader._signed_bound(altered, (100, 10), self.launcher, self.release):
                    self.fail("Unpacked identity mismatch accepted")

    def test_same_executable_electron_children_have_one_topmost_launcher(self):
        self.processes.update({101: (100, self.launcher.name), 102: (100, self.launcher.name)})
        self.images.update({101: (self.launcher, 20), 102: (self.launcher, 30)})
        self.assertEqual(session._running(self.processes, self.launcher), (100, 10))
        self.assertEqual(set(self.process_checks), {100, 101, 102})
        with self.reader._signed_bound(self.endpoint, (100, 10), self.launcher, self.release):
            self.assertEqual(self.release.pinned, 1)
        self.assertEqual(self.release.pinned, 0)
        self.assertEqual(self.process_pins, set())

    def test_independently_started_same_executable_roots_remain_ambiguous(self):
        self.processes.update({101: (100, self.launcher.name), 200: (1, self.launcher.name),
                               201: (200, self.launcher.name)})
        self.images.update({101: (self.launcher, 20), 200: (self.launcher, 40),
                            201: (self.launcher, 50)})
        with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
            session._running(self.processes, self.launcher)
        self.assertEqual(self.process_pins, set())

    def test_electron_child_deduplication_does_not_accept_reused_launcher_creation(self):
        self.processes[101] = (100, self.launcher.name)
        self.images.update({100: (self.launcher, 40), 101: (self.launcher, 50)})
        self.assertEqual(session._running(self.processes, self.launcher), (100, 40))
        with self.assertRaisesRegex(client.TransferError, r"preset\.unverified"):
            with self.reader._signed_bound(self.endpoint, (100, 10), self.launcher, self.release):
                self.fail("Reused launcher creation accepted after child deduplication")
        self.assertEqual(self.release.events, [])

    def test_stale_parent_pid_newer_than_child_does_not_hide_an_independent_root(self):
        self.processes[200] = (100, self.launcher.name)
        self.images.update({100: (self.launcher, 40), 200: (self.launcher, 20)})
        with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
            session._running(self.processes, self.launcher)
        self.assertEqual(self.process_pins, set())

    def test_same_executable_dedup_checks_nonowner_intermediate_chronology(self):
        self.processes.update({150: (100, "helper.exe"), 200: (150, self.launcher.name)})
        self.images[200] = (self.launcher, 30)
        for intermediate_created in (40, 5):
            with self.subTest(intermediate_created=intermediate_created):
                self.images[150] = (self.root / "helper.exe", intermediate_created)
                with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
                    session._running(self.processes, self.launcher)
                self.assertEqual(self.process_pins, set())

    def test_dead_nonowner_intermediate_is_not_used_to_deduplicate_same_executable(self):
        self.processes.update({150: (100, "helper.exe"), 200: (150, self.launcher.name)})
        self.images[200] = (self.launcher, 30)
        @contextmanager
        def process_with_dead_intermediate(pid, hwnd=None):
            if pid == 150:
                raise OSError("synthetic intermediate exited before lineage verification")
            with self.process(pid, hwnd) as observed:
                yield observed
        with patch.object(registry, "_process", side_effect=process_with_dead_intermediate):
            with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
                session._running(self.processes, self.launcher)
        self.assertEqual(self.process_pins, set())

    def test_valid_nonowner_intermediate_keeps_same_executable_child_grouped(self):
        self.processes.update({150: (100, "helper.exe"), 200: (150, self.launcher.name)})
        self.images.update({150: (self.root / "helper.exe", 20), 200: (self.launcher, 30)})
        self.assertEqual(session._running(self.processes, self.launcher), (100, 10))
        self.assertIn(150, self.process_checks)
        self.assertEqual(self.process_pins, set())

    def test_owner_generation_change_between_snapshot_and_lineage_check_is_ambiguous(self):
        self.processes[200] = (100, self.launcher.name)
        self.images[200] = (self.launcher, 30)
        seen = set()
        @contextmanager
        def process_with_reused_owner(pid, hwnd=None):
            if pid == 100 and pid in seen:
                yield self.launcher, 11, lambda: None
            else:
                seen.add(pid)
                with self.process(pid, hwnd) as observed:
                    yield observed
        with patch.object(registry, "_process", side_effect=process_with_reused_owner):
            with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
                session._running(self.processes, self.launcher)
        self.assertEqual(self.process_pins, set())

    def test_configured_signed_choice_preserves_precise_signature_failure_reason(self):
        for code in ("signature_expired", "signature_revoked", "signature_rollback", "signature_invalid"):
            with self.subTest(code=code):
                error = session._error(code)
                self.reader.store.load_default.side_effect = error
                with self.assertRaises(client.TransferError) as caught:
                    self.reader.configured()
                self.assertIs(caught.exception, error)

    def test_unpacked_selection_maps_runtime_corruption_to_actionable_message(self):
        self.patch_release()
        @contextmanager
        def corrupt_tree(root):
            raise releases.ReleaseError("RUNTIME_MISMATCH")
            yield
        with patch.object(self.release, "pin_tree", side_effect=corrupt_tree):
            with self.assertRaisesRegex(client.TransferError, r"preset\.runtime_mismatch") as caught:
                with self.reader._selection(self.record):
                    self.fail("Corrupt unpacked resource tree accepted")
        self.assertEqual(caught.exception.code, "preset.runtime_mismatch")
        self.assertFalse(caught.exception.delivery_possible)

    def test_portable_has_no_filename_whitelist_and_pins_the_entire_ancestor_chain(self):
        self.portable()
        with self.reader._signed_bound(self.endpoint, (100, 10), self.launcher, self.release):
            self.assertEqual(self.process_pins, {100, 101, 102})
            self.assertEqual(self.release.pinned, 1)
        self.assertEqual(self.process_checks[-3:], [102, 101, 100])
        self.assertIn(("pin", self.inner.parent.parent), self.release.events)
        self.assertEqual(self.release.pinned, 0)

    def test_portable_rejects_unrelated_or_reused_ancestor(self):
        self.portable()
        for mutation in ("unrelated", "reused_parent", "reused_launcher", "receiver_creation"):
            with self.subTest(mutation=mutation):
                original_processes, original_images = dict(self.processes), dict(self.images)
                if mutation == "unrelated":
                    self.processes[101] = (999, "intermediate.exe")
                elif mutation == "reused_parent":
                    self.images[101] = (self.images[101][0], 31)
                elif mutation == "reused_launcher":
                    self.images[100] = (self.launcher, 11)
                else:
                    self.images[102] = (self.inner, 32)
                with self.assertRaises(client.TransferError):
                    with self.reader._signed_bound(self.endpoint, (100, 10), self.launcher, self.release):
                        self.fail("Portable identity mismatch accepted")
                self.processes, self.images = original_processes, original_images

    def test_portable_rejects_receiver_outside_signed_runtime_relative_path(self):
        self.portable()
        forged = replace(self.endpoint, exe=str(self.inner.with_name("other.exe")))
        with self.assertRaisesRegex(client.TransferError, r"preset\.runtime_mismatch"):
            with self.reader._signed_bound(forged, (100, 10), self.launcher, self.release):
                self.fail("Wrong receiver suffix accepted")

    def test_runtime_failure_is_fail_closed_before_transport(self):
        self.patch_release()
        @contextmanager
        def corrupt_tree(root):
            raise releases.ReleaseError("RUNTIME_MISMATCH")
            yield
        with patch.object(self.release, "pin_tree", side_effect=corrupt_tree), \
                patch.object(registry, "registered_process") as registered, \
                patch.object(client, "_on_connection") as exchange:
            with self.assertRaisesRegex(client.TransferError, r"preset\.runtime_mismatch") as caught:
                client._exchange(self.signed_endpoint(), "/v1/preview", b"{}")
            self.assertFalse(caught.exception.delivery_possible)
            registered.assert_not_called()
            exchange.assert_not_called()

    def test_every_transport_request_keeps_runtime_file_and_process_pins_alive(self):
        inspection = self.patch_release()
        endpoint = self.signed_endpoint()
        paths = ("/v1/probe", "/v1/targets", "/v1/preview", "/v1/status")
        def exchange(observed, verify, path, body, timeout):
            self.assertIs(observed, endpoint)
            self.assertEqual(self.release.pinned, 1)
            self.assertIn(100, self.process_pins)
            self.assertIn(self.launcher, self.file_pins)
            return path
        with patch.object(registry, "registered_process", side_effect=self.registered_process), \
                patch.object(client, "_on_connection", side_effect=exchange):
            for path in paths:
                self.assertEqual(client._exchange(endpoint, path, b"{}"), path)
                self.assertEqual(self.release.pinned, 0)
                self.assertEqual(self.process_pins, set())
        self.assertEqual(inspection.call_count, len(paths))
        self.release.commit_authenticated.assert_not_called()

    def test_pending_endpoint_rejects_replaced_manifest_without_replaying_to_new_release(self):
        inspection = self.patch_release()
        pending_endpoint = self.signed_endpoint()
        inspection.return_value = SyntheticRelease(self.launcher, sequence=2)
        with patch.object(registry, "registered_process") as registered, \
                patch.object(client, "_on_connection") as exchange:
            for path in ("/v1/preview", "/v1/status"):
                with self.subTest(path=path), self.assertRaisesRegex(client.TransferError, r"preset\.changed") as caught:
                    client._exchange(pending_endpoint, path, b"{}")
                self.assertFalse(caught.exception.delivery_possible)
            registered.assert_not_called()
            exchange.assert_not_called()

    def test_pending_endpoint_rejects_removed_sidecars_instead_of_legacy_fallback(self):
        inspection = self.patch_release()
        endpoint = self.signed_endpoint()
        inspection.return_value = None
        with patch.object(client, "_on_connection") as exchange:
            with self.assertRaisesRegex(client.TransferError, r"preset\.changed"):
                client._exchange(endpoint, "/v1/status", b"{}")
            exchange.assert_not_called()

    def native_transport(self):
        """Use the real transport control flow with an in-memory fake socket."""
        connection = Mock()
        connection.sock.fileno.return_value = 123
        identity = {"protocol": client.PROTOCOL, "instanceId": self.endpoint.instance_id,
                    "pid": self.endpoint.pid}
        self.enterContext(patch.object(client.http.client, "HTTPConnection", return_value=connection))
        self.enterContext(patch.object(registry, "verify_socket_owner"))
        requests = self.enterContext(patch.object(client, "_request", side_effect=[
            identity, {"ok": True, "state": "pending"}]))
        self.enterContext(patch.object(registry, "registered_process", side_effect=self.registered_process))
        return requests

    def test_runtime_inventory_is_rechecked_before_probe_and_before_preview_submission(self):
        self.patch_release()
        requests = self.native_transport()
        result = client._exchange(self.signed_endpoint(), "/v1/preview", b"{}")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(self.release.recheck.call_count, 2)
        self.assertEqual([call.args[2] for call in requests.call_args_list],
                         ["/v1/probe", "/v1/preview"])

    def test_runtime_addition_after_probe_blocks_preview_before_any_possible_delivery(self):
        self.patch_release()
        requests = self.native_transport()
        self.release.recheck.side_effect = [None, releases.ReleaseError("RUNTIME_MISMATCH")]
        with self.assertRaises(client.TransferError) as caught:
            client._exchange(self.signed_endpoint(), "/v1/preview", b"{}")
        self.assertFalse(caught.exception.delivery_possible)
        self.assertEqual([call.args[2] for call in requests.call_args_list], ["/v1/probe"])

    def test_post_submission_guard_failure_keeps_delivery_uncertain_for_pending_safety(self):
        self.patch_release()
        requests = self.native_transport()
        @contextmanager
        def postflight_failure(root):
            self.release.pinned += 1
            try:
                yield lambda: None
                raise releases.ReleaseError("RUNTIME_MISMATCH")
            finally:
                self.release.pinned -= 1
        with patch.object(self.release, "pin_tree", side_effect=postflight_failure):
            with self.assertRaises(client.TransferError) as caught:
                client._exchange(self.signed_endpoint(), "/v1/preview", b"{}")
        self.assertEqual([call.args[2] for call in requests.call_args_list],
                         ["/v1/probe", "/v1/preview"])
        self.assertTrue(caught.exception.delivery_possible)

    def test_post_submission_native_pin_error_also_keeps_delivery_uncertain(self):
        self.patch_release()
        requests = self.native_transport()
        @contextmanager
        def native_postflight_failure(root):
            self.release.pinned += 1
            try:
                yield lambda: None
                raise OSError("synthetic native handle recheck failed")
            finally:
                self.release.pinned -= 1
        with patch.object(self.release, "pin_tree", side_effect=native_postflight_failure):
            with self.assertRaises(client.TransferError) as caught:
                client._exchange(self.signed_endpoint(), "/v1/preview", b"{}")
        self.assertEqual([call.args[2] for call in requests.call_args_list],
                         ["/v1/probe", "/v1/preview"])
        self.assertTrue(caught.exception.delivery_possible)

    def test_discovery_or_process_match_alone_never_commits_release_highwater(self):
        self.patch_release()
        self.enterContext(patch.object(self.reader, "_record", return_value=self.record))
        self.enterContext(patch.object(self.reader, "_connect", side_effect=session._error("no_receiver")))
        with self.assertRaisesRegex(client.TransferError, r"preset\.no_receiver"):
            self.reader.connect(allow_launch=False)
        self.release.commit_authenticated.assert_not_called()

    def test_connect_commits_only_after_authenticated_targets_success(self):
        self.patch_release()
        self.enterContext(patch.object(self.reader, "_record", return_value=self.record))
        def authenticated(*args, **kwargs):
            self.release.commit_authenticated.assert_not_called()
            self.release.events.append("authenticated")
            return self.endpoint, {"revision": "synthetic-r1"}
        with patch.object(self.reader, "_connect", side_effect=authenticated):
            endpoint, data, record = self.reader.connect(allow_launch=False)
        self.assertIs(endpoint, self.endpoint)
        self.assertEqual(data["revision"], "synthetic-r1")
        self.assertEqual(record.digest, self.release.launcher_digest)
        self.assertLess(self.release.events.index("authenticated"), self.release.events.index("commit"))
        self.release.commit_authenticated.assert_called_once_with(self.reader.release_store)

    def test_refresh_failed_authentication_does_not_commit_or_launch(self):
        self.patch_release()
        self.enterContext(patch.object(self.reader, "_record", return_value=self.record))
        with patch.object(client, "targets", side_effect=client.TransferError("synthetic auth failure")), \
                patch.object(registry, "launch") as launch:
            with self.assertRaisesRegex(client.TransferError, "synthetic auth failure"):
                self.reader.refresh(self.endpoint)
        self.release.commit_authenticated.assert_not_called()
        launch.assert_not_called()

    def test_refresh_returns_guarded_endpoint_and_preserves_request_authentication(self):
        self.patch_release()
        self.enterContext(patch.object(self.reader, "_record", return_value=self.record))
        def targets(endpoint):
            self.assertIsNotNone(endpoint.transport_guard)
            with endpoint.transport_guard():
                self.assertGreater(self.release.pinned, 0)
            self.release.commit_authenticated.assert_not_called()
            return {"revision": "changed-draft-only"}
        with patch.object(client, "targets", side_effect=targets), patch.object(registry, "launch") as launch:
            endpoint, data, _ = self.reader.refresh(self.endpoint)
        self.assertEqual(endpoint.instance_id, self.endpoint.instance_id)
        self.assertEqual(data["revision"], "changed-draft-only")
        self.release.commit_authenticated.assert_called_once_with(self.reader.release_store)
        launch.assert_not_called()

    def discovery_runtime(self):
        """Keep real identify_registration, replacing only native registration IO."""
        observed = replace(self.endpoint, compatibility="unverified")
        verify_registration = Mock()
        @contextmanager
        def registration(endpoint, **kwargs):
            self.assertTrue(kwargs.get("discovering"))
            yield endpoint, verify_registration
        def discover(deadline, *, pids, guard_factory):
            self.assertEqual(pids, {100})
            self.assertTrue(callable(guard_factory))
            return [client.identify_registration(observed, deadline, guard_factory=guard_factory)]
        self.enterContext(patch.object(registry, "registered_process", side_effect=registration))
        self.enterContext(patch.object(registry, "remaining_time", return_value=3))
        self.enterContext(patch.object(registry, "discover_instances", side_effect=discover))
        return verify_registration

    def test_signed_discovery_pins_runtime_before_first_hmac_probe_and_rechecks_callbacks(self):
        self.patch_release()
        verify_registration = self.discovery_runtime()
        def probe(endpoint, verify, path, body, timeout, *, discovery):
            self.assertTrue(discovery)
            self.assertEqual(path, "/v1/probe")
            self.assertEqual(self.release.pinned, 1)
            self.assertEqual(self.process_pins, {100})
            verify()
            verify()
            return {"protocol": client.PROTOCOL}
        with patch.object(client, "_on_connection", side_effect=probe) as transport, \
                patch.object(client, "targets", return_value={"revision": "r1"}) as targets:
            endpoint, data = self.reader._receiver(
                self.processes, (100, 10), self.launcher, False, 123.0, release=self.release)
        self.assertEqual(endpoint.compatibility, "compatible")
        self.assertIsNotNone(endpoint.transport_guard)
        self.assertEqual(data, {"revision": "r1"})
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(verify_registration.call_count, 2)
        self.assertEqual(self.release.recheck.call_count, 2)
        self.assertEqual(self.release.pinned, 0)
        targets.assert_called_once_with(endpoint)
        self.release.commit_authenticated.assert_not_called()

    def test_signed_discovery_runtime_failure_blocks_hmac_socket_and_targets(self):
        self.patch_release()
        self.discovery_runtime()
        @contextmanager
        def corrupt_tree(root):
            raise releases.ReleaseError("RUNTIME_MISMATCH")
            yield
        with patch.object(self.release, "pin_tree", side_effect=corrupt_tree), \
                patch.object(client, "_on_connection") as transport, \
                patch.object(client, "targets") as targets:
            with self.assertRaisesRegex(client.TransferError, r"preset\.runtime_mismatch"):
                self.reader._receiver(
                    self.processes, (100, 10), self.launcher, False, 123.0, release=self.release)
        transport.assert_not_called()
        targets.assert_not_called()
        self.release.commit_authenticated.assert_not_called()

    def test_definitive_signed_target_failures_keep_their_reason_after_discovery(self):
        keys = ("signature_invalid", "signature_expired", "signature_revoked", "signature_rollback",
                "runtime_mismatch", "changed")
        self.enterContext(patch.object(registry, "discover_instances", return_value=[self.endpoint]))
        for key in keys:
            error = session._error(key)
            with self.subTest(key=key), patch.object(client, "targets", side_effect=error):
                with self.assertRaises(client.TransferError) as caught:
                    self.reader._receiver(self.processes, (100, 10), self.launcher, False,
                                          123.0, release=self.release)
                self.assertIs(caught.exception, error)
                self.assertFalse(caught.exception.delivery_possible)
        self.release.commit_authenticated.assert_not_called()

    def test_signed_heartbeat_checks_only_pinned_launcher_and_receiver_os_identity(self):
        self.portable()
        self.endpoint = replace(self.endpoint, hwnd=77)
        inspection = self.patch_release()
        with patch.object(client, "_on_connection") as transport:
            endpoint = self.signed_endpoint()
            endpoint.liveness_check()
        self.assertEqual([call.args for call in registry._process.call_args_list], [(100,), (102, 77)])
        self.assertEqual(self.process_checks, [100, 102])
        self.assertEqual(self.process_pins, set())
        self.assertEqual(self.file_pins, [])
        self.assertEqual(self.release.events, [])
        registry.process_snapshot.assert_not_called()
        registry._digest.assert_not_called()
        registry.checked_handle.assert_not_called()
        inspection.assert_not_called()
        transport.assert_not_called()

    def test_signed_heartbeat_rejects_reused_pid_creation_or_changed_image_for_either_process(self):
        self.portable()
        endpoint = self.signed_endpoint()
        original = dict(self.images)
        cases = [(100, self.inner, 10), (100, self.launcher, 11),
                 (102, self.launcher, 30), (102, self.inner, 31)]
        for pid, image, created in cases:
            with self.subTest(pid=pid, image=image, created=created):
                self.images = dict(original)
                self.images[pid] = (image, created)
                with self.assertRaisesRegex(client.TransferError, r"preset\.unverified"):
                    endpoint.liveness_check()
                self.assertEqual(self.process_pins, set())

    def test_signed_heartbeat_native_process_failure_is_not_running(self):
        self.portable()
        endpoint = self.signed_endpoint()
        for stopped_pid in (100, 102):
            @contextmanager
            def stopped(pid, hwnd=None):
                if pid == stopped_pid:
                    raise OSError("synthetic process stopped")
                with self.process(pid, hwnd) as observed:
                    yield observed
            with self.subTest(pid=stopped_pid), patch.object(registry, "_process", side_effect=stopped):
                with self.assertRaisesRegex(client.TransferError, r"preset\.not_running"):
                    endpoint.liveness_check()
                self.assertEqual(self.process_pins, set())

    def test_successful_heartbeat_does_not_skip_full_package_guard_for_next_preview(self):
        self.portable()
        inspection = self.patch_release()
        endpoint = self.signed_endpoint()
        endpoint.liveness_check()
        inspection.assert_not_called()
        self.assertEqual(self.release.events, [])
        requests = self.native_transport()
        result = client._exchange(endpoint, "/v1/preview", b"{}")
        self.assertEqual(result["state"], "pending")
        inspection.assert_called_once()
        self.assertIn(("pin", self.inner.parent.parent), self.release.events)
        self.assertEqual(self.release.recheck.call_count, 2)
        self.assertEqual([call.args[2] for call in requests.call_args_list],
                         ["/v1/probe", "/v1/preview"])


@unittest.skipUnless(os.name == "nt" and Ed25519PrivateKey is not None,
                     "Real Windows ACLs and cryptography Ed25519 SDK required")
class FreshSignedProfileWindowsTests(SigningFixture, unittest.TestCase):
    """Regression for first signed inspect creating an unsafe reader-library.

    Only a disposable C-drive parent is deliberately broadened. The package is
    a signed non-executable PE header; no app, process, user profile or socket is
    touched. Keyset persistence, locks, ACL checks and default writes are real.
    """

    def setUp(self):
        SigningFixture.setUp(self)
        patch.stopall()  # Use the actual protected-store mutexes for this class.
        self.base = Path(self.enterContext(TemporaryDirectory(prefix="reader-signed-acl-"))).resolve()
        if self.base.drive.casefold() != "c:":
            self.skipTest("Fresh-profile ACL regression requires the actual C-drive test root")
        self.parent = self.base / "broad-parent"
        self.parent.mkdir()
        self.icacls = Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe"
        changed = subprocess.run([str(self.icacls), str(self.parent), "/grant",
                                  "*S-1-5-32-545:(OI)(CI)(M)"],
                                 capture_output=True, check=False)
        self.assertEqual(changed.returncode, 0, "Cannot prepare disposable broad-parent ACL")
        self.profile = self.parent / "reader-library"
        self.launcher = sample(self.base / "package" / "portable.exe")
        self.launcher_data = self.launcher.read_bytes()
        self.data["launcher"] = row(self.launcher.name, self.launcher_data)
        for path, raw in zip(releases._sidecars(self.launcher), self.raw()):
            path.write_bytes(raw)
        self.reader = session.PresetSession(root=self.profile, publisher_roots=self.roots)
        self.enterContext(patch.object(session, "_temporary", return_value=False))
        self.enterContext(patch.object(releases, "_now", return_value=NOW))

    def assert_broad(self, path):
        with self.assertRaises(client.TransferError):
            with registry.checked_handle(path, root=path, directory=True):
                self.fail("Synthetic broad ACL unexpectedly accepted as private")

    def acl_bytes(self, path):
        result = subprocess.run([str(self.icacls), str(path)], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)
        return result.stdout

    def test_first_signed_inspect_then_configure_creates_private_profile_before_nested_trust(self):
        self.assert_broad(self.parent)
        self.assertFalse(self.profile.exists())
        info = self.reader.inspect(self.launcher)
        with registry.checked_handle(self.profile, root=self.profile, directory=True):
            pass
        trust = self.reader.release_store._read()
        self.assertEqual((trust["keysetSequence"], trust["releaseSequence"]), (1, 0))
        configured = self.reader.configure(info)
        self.assertEqual(configured.path, self.launcher)
        self.assertEqual(self.reader.configured(), configured)
        with registry.checked_handle(self.reader.store.default_path, root=self.profile, read=True):
            pass
        self.assertEqual(self.reader.release_store._read()["releaseSequence"], 0)
        self.assert_broad(self.parent)

    def test_existing_unsafe_profile_is_rejected_without_acl_rewrite_or_nested_trust(self):
        self.profile.mkdir()
        self.assert_broad(self.profile)
        before = self.acl_bytes(self.profile)
        with self.assertRaises(client.TransferError):
            self.reader.inspect(self.launcher)
        self.assertEqual(self.acl_bytes(self.profile), before)
        self.assertFalse(self.reader.store.default_path.exists())
        self.assertFalse((self.profile / "release-trust").exists())
        self.assert_broad(self.profile)


if __name__ == "__main__":
    unittest.main()

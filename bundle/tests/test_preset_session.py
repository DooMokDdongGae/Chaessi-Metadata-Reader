from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from bundle import preset_library as library
from bundle import preset_session as session
from bundle import transfer_client as client
from bundle import transfer_registry as registry


@unittest.skipUnless(os.name == "nt", "Uses Windows paths and protected settings")
class PresetSessionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.chosen = self.root / "Chaessi-Preset-v3.8.5-x64.exe"
        self.inner = self.root / "nswTEST.tmp" / "app" / "Chaessi Preset.exe"
        self.duplicate = self.root / "other" / self.chosen.name
        for image in (self.chosen, self.duplicate, self.inner):
            image.parent.mkdir(parents=True, exist_ok=True)
            image.touch()
        self.record = library.ExeInfo(self.chosen, session.PUBLIC_PORTABLE, "3.8.5", "PUBLIC", "Chaessi Preset")
        self.is_temporary = session._temporary
        self.enterContext(patch.object(session, "_temporary", side_effect=session._extracted))
        self.reader = session.PresetSession(root=self.root / "reader")
        self.endpoint = client.Endpoint("6fa35452-5a45-4c2a-8245-c183915342d1", 32101, bytes(32), 101,
                                        str(self.inner), session.PUBLIC_RECEIVER, 201, compatibility="compatible")
        self.catalogue = {"revision": "fresh"}
        self.processes = {100: (15, self.chosen.name), 101: (100, self.inner.name)}
        self.images = {100: (self.chosen, 100), 101: (self.inner, 201)}

    @contextmanager
    def fake_process(self, pid):
        path, created = self.images[pid]
        yield path, created, lambda: None

    def start_runtime(self):
        self.enterContext(patch.object(self.reader, "configured", return_value=self.record))
        self.enterContext(patch.object(registry, "_process", side_effect=self.fake_process))
        self.enterContext(patch.object(registry, "_digest", return_value=session.PUBLIC_PORTABLE))
        snapshot = self.enterContext(patch.object(registry, "process_snapshot", return_value=self.processes))
        self.enterContext(patch.object(registry, "discover_instances", return_value=[self.endpoint]))
        self.enterContext(patch.object(client, "targets", return_value=self.catalogue))
        launch = self.enterContext(patch.object(registry, "launch"))
        launch.return_value = Mock(pid=100, **{"poll.return_value": None})
        return snapshot, launch

    def test_windows_snapshot_returns_exact_running_process(self):
        table = registry.process_snapshot()
        pid = os.getpid()
        self.assertIn(pid, table)
        self.assertEqual(table[pid][1].casefold(), Path(sys.executable).name.casefold())
        with registry._process(pid) as (image, created, verify):
            # A CPython virtual environment can redirect to the base executable.
            self.assertTrue(any(image.samefile(path) for path in (sys.executable, sys._base_executable)))
            self.assertGreater(created, 0)
            verify()

    def test_migrates_single_eligible_pin_and_preserves_legacy_bytes(self):
        store = self.reader.store
        record = store.register(self.record)
        store.register(library.ExeInfo(self.inner, session.PUBLIC_PORTABLE))
        legacy = store.path.read_bytes()
        self.assertEqual(self.reader.configured(), record)
        self.assertEqual(session.PresetSession(root=store.root).configured(), record)
        self.assertEqual(store.path.read_bytes(), legacy)

    def test_ambiguous_migration_requires_selection_and_does_not_write(self):
        store = self.reader.store
        store.register(self.record)
        second = store.register(replace(self.record, path=self.duplicate))
        self.assertIsNone(self.reader.configured())
        self.assertFalse(store.default_path.exists())
        store.select(second.id)
        self.assertEqual(self.reader.configured(), second)

    def test_configure_safe_reselect_preserves_legacy_source(self):
        store = self.reader.store
        store.register(self.record)
        original = store.path.read_bytes()
        with patch.object(registry, "_digest", return_value=session.PUBLIC_PORTABLE):
            saved = self.reader.configure(self.record)
            other = self.reader.configure(replace(self.record, path=self.duplicate))
        self.assertEqual(saved.path, self.chosen)
        self.assertEqual(self.reader.configured(), other)
        self.assertEqual(other.path, self.duplicate)
        self.assertEqual(store.path.read_bytes(), original)

    def test_rejects_temp_or_unknown_image_despite_brand(self):
        with patch.object(library, "inspect_exe", return_value=replace(self.record, digest="0" * 64)):
            with self.assertRaisesRegex(client.TransferError, r"preset\.unsupported_image"):
                self.reader.inspect(self.chosen)
            with self.assertRaisesRegex(client.TransferError, r"preset\.temporary"):
                self.reader.inspect(self.inner)
        with patch.dict(os.environ, {"TEMP": str(self.root)}):
            self.assertTrue(self.is_temporary(self.chosen))

    def test_matching_running_portable_reuses_verified_receiver(self):
        _, launch = self.start_runtime()
        self.assertEqual(self.reader.connect(allow_launch=False), (self.endpoint, self.catalogue, self.record))
        registry.discover_instances.assert_called_once()
        self.assertEqual(registry.discover_instances.call_args.kwargs["pids"], {101})
        launch.assert_not_called()

    def test_cold_start_calls_only_the_exact_selected_outer_once(self):
        snapshot, launch = self.start_runtime()
        snapshot.side_effect = [{17: (0, "other.exe")}, self.processes]
        self.assertEqual(self.reader.connect(timeout=5)[0], self.endpoint)
        launch.assert_called_once_with(self.chosen, session.PUBLIC_PORTABLE, confirmed=True)

    def test_unsigned_old_private_hash_cannot_configure_or_connect_as_legacy(self):
        _, launch = self.start_runtime()
        old_private = replace(self.record, digest=library.KNOWN_PRIVATE)
        self.reader.configured.return_value = old_private
        registry._digest.return_value = library.KNOWN_PRIVATE
        with patch.object(library, "inspect_exe", return_value=old_private):
            with self.assertRaisesRegex(client.TransferError, r"preset\.unsupported_image"):
                self.reader.inspect(self.chosen)
        with self.assertRaisesRegex(client.TransferError, r"preset\.unsupported_image"):
            self.reader.configure(old_private)
        with self.assertRaisesRegex(client.TransferError, r"preset\.unsupported_image"):
            self.reader.connect(allow_launch=False)
        registry.discover_instances.assert_not_called()
        client.targets.assert_not_called()
        launch.assert_not_called()

    def test_no_launch_without_request_and_one_start_when_unready(self):
        snapshot, launch = self.start_runtime()
        snapshot.return_value = {}
        with self.assertRaisesRegex(client.TransferError, r"preset\.not_running"):
            self.reader.connect(allow_launch=False, timeout=1)
        launch.assert_not_called()
        with self.assertRaisesRegex(client.TransferError, r"preset\.no_receiver"):
            self.reader.connect(timeout=0.05)
        launch.assert_called_once()

    def test_duplicate_selected_path_is_never_auto_picked_or_launched(self):
        _, launch = self.start_runtime()
        self.processes[105] = (15, self.chosen.name)
        self.images[105] = (self.chosen, 110)
        with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
            self.reader.connect(allow_launch=False)
        client.targets.assert_not_called()
        launch.assert_not_called()

    def test_distinct_paths_and_forged_or_reused_process_do_not_bind(self):
        _, launch = self.start_runtime()
        self.images[106] = (self.duplicate, 101)
        self.processes[106] = (15, self.duplicate.name)
        self.processes[101] = (106, self.inner.name)
        with self.assertRaisesRegex(client.TransferError, r"preset\.no_receiver"):
            self.reader.connect(allow_launch=False)
        registry.discover_instances.assert_not_called()
        self.processes[101] = (100, self.inner.name)
        self.images[100] = (self.chosen, self.endpoint.created + 1)
        with self.assertRaisesRegex(client.TransferError, r"preset\.no_receiver"):
            self.reader.connect(allow_launch=False)
        client.targets.assert_not_called()
        launch.assert_not_called()

    def test_official_unbound_inner_blocks_second_start(self):
        _, launch = self.start_runtime()
        self.processes.pop(100)
        registry._digest.side_effect = [session.PUBLIC_PORTABLE, session.PUBLIC_RECEIVER]
        with self.assertRaisesRegex(client.TransferError, r"preset\.ambiguous"):
            self.reader.connect()
        launch.assert_not_called()

    def test_refresh_authenticates_same_instance_without_discovering_or_launching(self):
        _, launch = self.start_runtime()
        self.assertEqual(self.reader.refresh(self.endpoint), (self.endpoint, self.catalogue, self.record))
        registry.discover_instances.assert_not_called()
        launch.assert_not_called()
        registry._digest.return_value = "0" * 64
        with self.assertRaisesRegex(client.TransferError, r"preset\.changed"):
            self.reader.refresh(self.endpoint)
        client.targets.assert_called_once_with(self.endpoint)

    def test_refresh_then_reconnect_after_receiver_restart(self):
        _, launch = self.start_runtime()
        self.reader.refresh(self.endpoint)
        self.processes.pop(101)
        fresh = replace(self.endpoint, pid=121, created=401, port=32102,
                        instance_id="3affab3e-2b8a-4a53-8725-036c79b08ab1")
        self.images[121] = (self.inner, fresh.created)
        self.processes[121] = (100, self.inner.name)
        registry.discover_instances.return_value = [fresh]
        with self.assertRaisesRegex(client.TransferError, r"preset\.unverified"):
            self.reader.refresh(self.endpoint)
        self.assertEqual(self.reader.connect(allow_launch=False)[0], fresh)
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

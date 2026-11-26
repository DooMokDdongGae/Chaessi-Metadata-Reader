"""Use synthetic process identities to verify that an explicit choice cannot fall back."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bundle import preset_connections as connections
from bundle.transfer_client import TransferError


class PresetConnectionTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("A", "preset.exe")
        self.record = SimpleNamespace(id="first", path=self.path, digest="a")
        self.a = self.endpoint(12, self.path)
        self.store = Mock()
        self.store.connected.return_value = self.record

    def endpoint(self, pid, path):
        return SimpleNamespace(pid=pid, exe=str(path), sha256="a", compatibility="compatible")

    def test_cold_start_waits_for_the_launched_pid_and_exact_image(self):
        proc = Mock(pid=12)
        proc.poll.return_value = None
        other = self.endpoint(22, self.path)
        other_copy = self.endpoint(12, Path("B", "preset.exe"))
        with patch.object(connections.registry, "launch", return_value=proc) as launch, \
             patch.object(connections.registry, "discover_instances",
                          side_effect=[[other], [other_copy], [self.a]]) as scan, \
             patch.object(connections.time, "sleep"), \
             patch.object(connections.registry, "attest", return_value=self.a) as attest:
            self.assertIs(connections.launch_and_wait(self.record), self.a)
        launch.assert_called_once_with(self.path, "a", confirmed=True)
        self.assertEqual([c.kwargs["pid"] for c in scan.call_args_list], [12, 12, 12])
        attest.assert_called_once_with(self.a, path=self.path, sha256="a")

    def test_launch_exits_while_only_other_window_ready(self):
        proc = Mock(pid=12)
        proc.poll.side_effect = [None, 1]
        with patch.object(connections.registry, "launch", return_value=proc), \
             patch.object(connections.registry, "discover_instances", return_value=[self.endpoint(30, self.path)]), \
             patch.object(connections.time, "sleep"), patch.object(connections.registry, "attest") as auth:
            with self.assertRaisesRegex(TransferError, "preset.no_receiver"):
                connections.launch_and_wait(self.record)
        auth.assert_not_called()

    def test_changed_file_or_unregistered_unrecognized_requires_explicit_reselection(self):
        self.a.sha256 = "b"
        with patch.object(connections.registry, "attest") as auth:
            with self.assertRaisesRegex(TransferError, "preset.changed"):
                connections.open_running(self.a, [self.record], self.store)
            info = SimpleNamespace(digest="b", recognized=False)
            with patch.object(connections.library, "inspect_exe", return_value=info):
                with self.assertRaisesRegex(TransferError, "preset.register_first"):
                    connections.open_running(self.a, [], self.store)
            auth.assert_not_called()
            self.store.register.assert_not_called()

    def test_remember_after_verified_fields_only(self):
        with patch.object(connections.registry, "attest", return_value=self.a), \
             patch.object(connections.client, "targets", side_effect=[TransferError("offline"), {"targets": []}]):
            with self.assertRaisesRegex(TransferError, "offline"):
                connections.open_running(self.a, [self.record], self.store)
            self.store.connected.assert_not_called()
            ep, data, record = connections.open_running(self.a, [self.record], self.store)
        self.assertIs(ep, self.a)
        self.assertEqual(data, {"targets": []})
        self.assertIs(record, self.record)
        self.store.connected.assert_called_once_with("first", self.path, "a")

    def test_same_digest_in_other_folder_is_not_a_registered_match(self):
        self.assertEqual(connections.existing_for(self.record, [self.endpoint(22, Path("B", "preset.exe"))]), [])
        self.assertEqual(connections.existing_for(self.record, [self.a, self.endpoint(13, self.path)])[0], self.a)


if __name__ == "__main__":
    unittest.main()

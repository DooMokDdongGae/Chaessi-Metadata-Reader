"""Reader client contract checks with disposable in-memory loopback peers."""
import ctypes
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bundle.transfer_client import TransferError, make_preview, preview, probe, status, targets
from bundle import preset_library, transfer_registry as registry


PROTOCOL = "chaessi.prompt-transfer/1"
ITEM_LIMIT = 256 * 1024
BODY_LIMIT = 1024 * 1024


def item(text, field="positive"):
    return {"source": {"image": 1, "number": 0, "field": "positive"}, "slot": "base",
            "field": field, "mode": "append", "text": text}


class PreviewEncodingTests(unittest.TestCase):
    def test_exact_batch_selection_order_and_utf8_text(self):
        chosen = "  (정원:1.3)\n\t🌙,  "
        items = [item(chosen, "undesired"), item("추가"), dict(item(""), mode="replace")]
        request_id, body = make_preview("revision-1", items)
        self.assertEqual(str(uuid.UUID(request_id)), request_id)
        self.assertEqual(uuid.UUID(request_id).version, 4)
        self.assertEqual(json.loads(body.decode("utf-8")), {
            "requestId": request_id, "revision": "revision-1", "items": items})

    def test_unrepresentable_control_characters_are_rejected_without_changing_input(self):
        for text in ("first\r\nsecond", "first\rsecond", "\x00", "\x01", "\ud800"):
            with self.subTest(text=ascii(text)):
                row = item(text)
                with self.assertRaises(TransferError):
                    make_preview("rev", [row])
                self.assertEqual(row["text"], text)

    def test_each_text_limit_counts_utf8_bytes(self):
        text = "별" * (ITEM_LIMIT // 3) + "a" * (ITEM_LIMIT % 3)
        self.assertEqual(len(text.encode("utf-8")), ITEM_LIMIT)
        self.assertEqual(json.loads(make_preview("rev", [item(text)])[1])["items"][0]["text"], text)
        with self.assertRaises(TransferError):
            make_preview("rev", [item(text + "a")])

    def test_total_limit_includes_mapping_and_json_envelope(self):
        rows = [item("") for _ in range(4)]
        overhead = len(make_preview("rev", rows)[1])
        text_bytes = BODY_LIMIT - overhead
        for index, row in enumerate(rows):
            row["text"] = "x" * (text_bytes // 4 + int(index < text_bytes % 4))
        self.assertTrue(all(len(row["text"]) < ITEM_LIMIT for row in rows))
        self.assertEqual(len(make_preview("rev", rows)[1]), BODY_LIMIT)
        rows[0]["text"] += "x"
        with self.assertRaises(TransferError):
            make_preview("rev", rows)

    def test_batch_count_bounds(self):
        rows = [item("") for _ in range(128)]
        self.assertEqual(len(json.loads(make_preview("rev", rows)[1])["items"]), 128)
        for invalid in ([], rows + [item("")]):
            with self.subTest(count=len(invalid)), self.assertRaises(TransferError):
                make_preview("rev", invalid)


def mac(key, *lines):
    return hmac.new(key, "\n".join(lines).encode("utf-8"), hashlib.sha256).hexdigest()


class Receiver(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # Synthetic requests stay in memory.

    def do_POST(self):
        fixture = self.server
        headers = self.headers
        body = self.rfile.read(int(headers["Content-Length"]))
        nonce = headers.get("X-Chaessi-Nonce", "")
        fixture.events.append((self.path, self.client_address, body))
        signature = mac(fixture.secret, "POST", self.path, fixture.instance, nonce,
                        hashlib.sha256(body).hexdigest())
        if (headers.get("X-Chaessi-Instance") != fixture.instance
                or not re.fullmatch("[0-9a-f]{32}", nonce) or nonce in fixture.nonces
                or headers.get("X-Chaessi-Mac") != signature
                or headers.get("Host") != f"127.0.0.1:{fixture.server_port}"
                or headers.get_content_type() != "application/json"):
            fixture.invalid_request = True
            self.send_error(400)
            return
        fixture.nonces.add(nonce)
        code = 200
        request = json.loads(body)
        if self.path == "/v1/probe":
            result = {"ok": True, "instanceId": fixture.instance, "pid": fixture.pid, "protocol": fixture.protocol}
        elif self.path == "/v1/targets":
            result = {"ok": True, "instanceId": fixture.instance, "revision": "rev", "limit": 6,
                      "canCreate": 5, "targets": [
                          {"slot": "base", "number": 0, "fields": ["positive", "undesired"]},
                          {"slot": "existing-a", "number": 1, "fields": ["positive"]}]}
        elif self.path == "/v1/preview":
            if fixture.outcome == "busy":
                code, result = 409, {"ok": False, "error": "BUSY"}
            else:
                fixture.accepted_id = request["requestId"]
                if fixture.outcome == "disconnect_after_received":
                    self.close_connection = True
                    return
                result = {"ok": True, "requestId": fixture.accepted_id, "state": "pending"}
        elif self.path == "/v1/status" and request == {"requestId": fixture.accepted_id}:
            result = {"ok": True, "requestId": fixture.accepted_id, "state": "applied"}
        else:
            code, result = 404, {"ok": False, "error": "NOT_FOUND"}
        wire = json.dumps(result, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(wire)))
        response_mac = mac(fixture.secret, "RES", str(code), fixture.instance, nonce,
                           hashlib.sha256(wire).hexdigest())
        self.send_header("X-Chaessi-Mac", response_mac if fixture.outcome != "bad_signature" else "0" * 64)
        if fixture.outcome == "closed_probe" and self.path == "/v1/probe":
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(wire)


@unittest.skipUnless(os.name == "nt", "Receiver process and connection binding require Windows")
class LoopbackTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These integration tests use the real Windows owner table for every
        # connection. Restricted Windows tokens can disallow reading that table.
        size = registry.w.DWORD()
        get_table = registry._api(ctypes.WinDLL("iphlpapi"), "GetExtendedTcpTable", registry.w.DWORD,
                                  registry.P, registry.P, registry.w.BOOL, registry.w.ULONG,
                                  ctypes.c_int, registry.w.ULONG)
        if get_table(None, ctypes.byref(size), False, socket.AF_INET, 4, 0) == 5:
            raise unittest.SkipTest("Windows denied GetExtendedTcpTable (ERROR_ACCESS_DENIED 5); "
                                    "native process/socket integration requires a token with table access")
        temp = tempfile.TemporaryDirectory(prefix="chaessi-synthetic-receiver-")
        cls.addClassCleanup(temp.cleanup)
        # The OS temp directory can have explicit ACEs as well as inherited ones.
        # Create the synthetic registry with a protected DACL from its first open.
        cls.directory = Path(temp.name) / "registry"
        preset_library._make_directory(cls.directory)
        preset_library._make_directory(cls.directory / "instances")

    def setUp(self):
        peer = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        peer.secret = secrets.token_bytes(32)
        peer.instance, peer.pid, peer.protocol = str(uuid.uuid4()), os.getpid(), PROTOCOL
        peer.events, peer.nonces = [], set()
        peer.accepted_id = None
        peer.invalid_request = False
        peer.outcome = "ready"
        self.peer = peer
        self.addCleanup(peer.server_close)
        thread = threading.Thread(target=lambda: peer.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(peer.shutdown)
        env = patch.dict(os.environ, CHAESSI_TRANSFER_REGISTRY=str(self.directory))
        env.start()
        self.addCleanup(env.stop)
        self.manifest = self.directory / "instances" / (peer.instance + ".json")
        self.record = dict(instanceId=peer.instance, pid=peer.pid, protocol=PROTOCOL,
                           port=peer.server_port, secret=peer.secret.hex())
        with preset_library._open_private(self.manifest) as output:
            output.write(json.dumps(self.record).encode("utf-8"))
        self.addCleanup(self.manifest.unlink)
        self.endpoint, = registry.discover()
        peer.events.clear()

    def tearDown(self):
        self.assertFalse(self.peer.invalid_request, "Request failed the independent wire-format check")

    def test_discovery_and_separate_authenticated_targets(self):
        identity = probe(self.endpoint)
        self.assertEqual(identity["instanceId"], self.peer.instance)
        self.assertEqual(identity["pid"], self.peer.pid)
        destinations = targets(self.endpoint)
        self.assertEqual(destinations["targets"][1], {
            "slot": "existing-a", "number": 1, "fields": ["positive"]})
        paths = [path for path, _, _ in self.peer.events]
        self.assertIn("/v1/probe", paths)
        self.assertEqual(paths[-1], "/v1/targets")
        self.assertTrue(all(json.loads(body) == {} for _, _, body in self.peer.events))

    def test_preview_only_after_signed_probe_on_same_connection(self):
        request_id, body = make_preview("rev", [item("  잎\n  ")])
        self.assertEqual(preview(self.endpoint, body), "pending")
        self.assertEqual([entry[0] for entry in self.peer.events], ["/v1/probe", "/v1/preview"])
        probe_event, preview_event = self.peer.events
        self.assertEqual(probe_event[1], preview_event[1])
        self.assertEqual(preview_event[2], body)
        self.assertEqual(self.peer.accepted_id, request_id)

    def test_wrong_process_identity_is_refused_before_preview(self):
        self.peer.pid += 1
        _, body = make_preview("rev", [item("원래 인스턴스 대상")])
        with self.assertRaises(TransferError):
            preview(self.endpoint, body)
        self.assertEqual([path for path, _, _ in self.peer.events], ["/v1/probe"])

    def test_discovery_binds_image_hash_creation_time_and_refuses_another_selected_path(self):
        ep = self.endpoint
        self.assertTrue(Path(ep.exe).samefile(sys.executable))
        self.assertEqual(ep.sha256, registry.launcher_hash(sys.executable))
        self.assertGreater(ep.created, 0)
        self.assertEqual(ep.compatibility, "compatible")
        self.assertEqual(registry.attest(ep, path=ep.exe, sha256=ep.sha256), ep)
        with self.assertRaises(TransferError):
            registry.attest(ep, path=self.directory / "other.exe", sha256=ep.sha256)
        with patch.object(Path, "samefile", return_value=False), self.assertRaises(TransferError):
            registry.attest(ep, path=ep.exe.swapcase(), sha256=ep.sha256)
        for hwnd in (0, -1, 1 << 128, "invalid"):
            with self.subTest(hwnd=hwnd), self.assertRaises(TransferError):
                registry.attest(ep, hwnd=hwnd)

    def test_windows_owner_is_bound_to_both_ports_and_the_selected_process(self):
        ep = self.endpoint
        with socket.create_connection(("127.0.0.1", ep.port), timeout=1) as synthetic_connection:
            registry.verify_socket_owner(synthetic_connection, ep)
            with self.assertRaises(TransferError):
                registry.verify_socket_owner(synthetic_connection, replace(ep, pid=ep.pid + 1))
            with self.assertRaises(TransferError):
                registry.verify_socket_owner(synthetic_connection, replace(ep, port=1))

    def test_startup_search_filters_other_pids_and_hashes_the_matching_image_once(self):
        with patch.object(registry, "_digest", wraps=registry._digest) as digest:
            self.assertEqual(registry.discover_instances(pid=self.peer.pid + 1), [])
            digest.assert_not_called()
            candidate, = registry.discover_instances(pid=self.peer.pid)
            self.assertEqual(candidate, self.endpoint)
            digest.assert_called_once()

    def test_changed_pin_manifest_or_process_generation_fails_before_any_payload(self):
        ep = self.endpoint
        _, body = make_preview("rev", [item("합성")])
        for mismatch in (replace(ep, sha256="0" * 64), replace(ep, created=ep.created + 1),
                         replace(ep, secret=bytes(32)), replace(ep, exe=str(self.directory / "other.exe"))):
            with self.subTest(change=mismatch.created), self.assertRaises(TransferError) as caught:
                preview(mismatch, body)
            self.assertFalse(caught.exception.delivery_possible)
        self.manifest.write_text(json.dumps(dict(self.record, port=1)), encoding="utf-8")
        with self.assertRaises(TransferError):
            preview(ep, body)
        self.assertEqual(self.peer.events, [])

    def test_authenticated_other_protocol_is_distinguished_from_unverified_registration(self):
        version = "chaessi.prompt-transfer/synthetic-future"
        self.peer.protocol = version
        self.manifest.write_text(json.dumps(dict(self.record, protocol=version)), encoding="utf-8")
        other, = registry.discover_instances()
        self.assertEqual((other.protocol, other.compatibility), (version, "unsupported"))
        self.assertEqual(registry.discover(), [])
        with self.assertRaises(TransferError):
            registry.attest(other)
        self.peer.protocol = PROTOCOL
        contradictory, = registry.discover_instances()
        self.assertEqual(contradictory.compatibility, "unverified")
        self.peer.outcome = "bad_signature"
        uncertain, = registry.discover_instances()
        self.assertEqual(uncertain.compatibility, "unverified")
        self.assertTrue(all(event[0] == "/v1/probe" for event in self.peer.events))

    def test_peer_owner_is_checked_again_after_authenticated_probe(self):
        _, body = make_preview("rev", [item("합성")])
        with patch.object(registry, "verify_socket_owner",
                          side_effect=[None, TransferError("receiver unavailable")]) as verify_owner:
            with self.assertRaises(TransferError) as caught:
                preview(self.endpoint, body)
        self.assertEqual(verify_owner.call_count, 2)
        self.assertFalse(caught.exception.delivery_possible)
        self.assertEqual([event[0] for event in self.peer.events], ["/v1/probe"])

    def test_local_renamed_exe_requires_explicit_confirmation_and_matching_bytes(self):
        sample = self.directory / "portable-verification.EXE"
        sample.write_bytes(b"synthetic byte identity only")
        self.addCleanup(sample.unlink)
        digest = registry.launcher_hash(sample)
        with patch.object(subprocess, "Popen") as run:
            with self.assertRaises(TransferError):
                registry.launch(sample, digest)
            sample.write_bytes(b"changed synthetic fixture")
            with self.assertRaises(TransferError):
                registry.launch(sample, digest, confirmed=True)
            run.assert_not_called()

    def test_signature_and_closed_probe_prevent_preview_body(self):
        for outcome in ("bad_signature", "closed_probe"):
            with self.subTest(outcome=outcome):
                self.peer.outcome = outcome
                self.peer.events.clear()
                _, body = make_preview("rev", [item("가중치")])
                with self.assertRaises(TransferError):
                    preview(self.endpoint, body)
                self.assertTrue(self.peer.events)
                self.assertTrue(all(path == "/v1/probe" for path, _, _ in self.peer.events))

    def test_signed_busy_surfaces_without_repeat_preview(self):
        self.peer.outcome = "busy"
        _, body = make_preview("rev", [item("새 문구")])
        with self.assertRaises(TransferError) as caught:
            preview(self.endpoint, body)
        self.assertEqual(caught.exception.code, "BUSY")
        self.assertIsNone(self.peer.accepted_id)
        self.assertEqual(sum(path == "/v1/preview" for path, _, _ in self.peer.events), 1)

    def test_lost_receipt_then_status_only_uses_original_request_id(self):
        self.peer.outcome = "disconnect_after_received"
        request_id, body = make_preview("rev", [item("  달\n빛  ")])
        with self.assertRaises(TransferError):
            preview(self.endpoint, body)
        self.assertEqual(status(self.endpoint, request_id), "applied")
        self.assertEqual(self.peer.accepted_id, request_id)
        self.assertEqual(sum(path == "/v1/preview" for path, _, _ in self.peer.events), 1)
        path, _, queried = self.peer.events[-1]
        self.assertEqual(path, "/v1/status")
        self.assertEqual(json.loads(queried), {"requestId": request_id})


if __name__ == "__main__":
    unittest.main()

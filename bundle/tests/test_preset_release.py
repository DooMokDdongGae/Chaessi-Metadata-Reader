"""Synthetic signing keys stay in memory; no production/profile credentials."""
import base64
from contextlib import nullcontext
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bundle import preset_release as release

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None


NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
BEFORE = "2026-11-01T00:00:00Z"
AFTER = "2027-01-01T00:00:00Z"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def row(path, data):
    return dict(path=path, size=len(data), sha256=digest(data))


class MemoryStore(release.ReleaseStore):
    """Same highwater logic; filesystem ACLs are tested separately on Windows."""
    def __init__(self):
        self.root = Path("synthetic-memory-only")
        self.state = dict(format=1, keysetSequence=0, keysetSha256="0" * 64,
                          releaseSequence=0, releaseSha256="0" * 64, revokedKeyIds=[])

    def _read(self):
        return copy.deepcopy(self.state)

    def _write(self, data):
        self.state = copy.deepcopy(data)


class SigningFixture:
    def setUp(self):
        self.root = Ed25519PrivateKey.generate()
        self.signer = Ed25519PrivateKey.generate()
        self.root_public = public(self.root)
        self.key_id = digest(public(self.signer))
        self.roots = {digest(self.root_public): self.root_public}
        self.keys = dict(schema=release.KEYS_SCHEMA, issuer="chaessi-studio", product="chaessi-preset",
                         channel="public", sequence=1, issuedAt=BEFORE, expiresAt=AFTER,
                         keys=[dict(keyId=self.key_id, publicKey=base64.b64encode(public(self.signer)).decode(),
                                    notBefore=BEFORE, notAfter=AFTER)], revokedKeyIds=[])
        self.launcher_data = b"synthetic non-executable portable"
        self.receiver_data = b"synthetic non-executable receiver"
        self.resource_data = b"synthetic app resource"
        self.data = dict(schema=release.RELEASE_SCHEMA, issuer="chaessi-studio", product="chaessi-preset",
                         channel="public", releaseId="public-fixture-1", version="5.0.0",
                         sequence=1, issuedAt=BEFORE, expiresAt=AFTER, keyId=self.key_id,
                         minKeysetSequence=1, protocols=[release.PROTOCOL], layout="portable",
                         launcher=row("portable.exe", self.launcher_data), receiver="app.exe",
                         files=[row("app.exe", self.receiver_data), row("resources/app.asar", self.resource_data)])
        self.addCleanup(patch.stopall)
        patch("bundle.preset_release.library._store_lock", side_effect=lambda _: nullcontext()).start()

    def raw(self, data=None, keys=None):
        data = self.data if data is None else data
        keys = self.keys if keys is None else keys
        raw, keyraw = release.canonical(data), release.canonical(keys)
        sign = lambda key, domain, payload: base64.b64encode(key.sign(domain.encode() + b"\0" + payload)) + b"\n"
        return raw, sign(self.signer, release.RELEASE_SCHEMA, raw), keyraw, sign(self.root, release.KEYS_SCHEMA, keyraw)

    def validate(self, data=None, keys=None, **kwargs):
        return release.validate_metadata(*self.raw(data, keys), self.roots, now=NOW, **kwargs)

    def rejected(self, data=None, keys=None, code="SIGNATURE_INVALID", **kwargs):
        with self.assertRaises(release.ReleaseError) as caught:
            self.validate(data, keys, **kwargs)
        self.assertEqual(caught.exception.code, code)


@unittest.skipUnless(Ed25519PrivateKey is not None, "cryptography Ed25519 SDK required")
class MetadataTests(SigningFixture, unittest.TestCase):
    def test_valid_portable_and_unpacked_metadata(self):
        info = self.validate()
        self.assertEqual((info.layout, info.receiver, info.sequence, info.version),
                         ("portable", "app.exe", 1, "5.0.0"))
        self.assertEqual(info.launcher_digest, digest(self.launcher_data))
        self.assertEqual(info.root_key_id, digest(self.root_public))
        data = copy.deepcopy(self.data)
        data.update(layout="unpacked", launcher=data["files"][0])
        self.assertEqual(self.validate(data).layout, "unpacked")
        # Returned metadata is a copy, never the trusted immutable record.
        info.metadata["sequence"] = 999
        self.assertEqual(info.sequence, 1)

    def test_noncanonical_bytes_duplicates_bom_nonascii_float_bool_and_null(self):
        raw, sig, keys, ksig = self.raw()
        invalid = [raw + b"\n", b"\xef\xbb\xbf" + raw,
                   json.dumps(self.data).encode(), raw.replace(b'"sequence":1', b'"sequence":1,"sequence":1'),
                   raw.replace(b'"sequence":1', b'"sequence":1.0'),
                   raw.replace(b'"sequence":1', b'"sequence":true'),
                   raw.replace(b'"sequence":1', b'"sequence":null'),
                   raw.replace(b'"sequence":1', b'"sequence":9007199254740992'),
                   raw.replace(b'public-fixture-1', b'public-\\u0066ixture-1'),
                   raw.replace(b'public-fixture-1', 'public-한글'.encode())]
        for broken in invalid:
            with self.subTest(raw=broken[:32]), self.assertRaises(release.ReleaseError):
                signed = base64.b64encode(self.signer.sign(release.RELEASE_SCHEMA.encode() + b"\0" + broken)) + b"\n"
                release.validate_metadata(broken, signed, keys, ksig, self.roots, now=NOW)

    def test_tampered_signature_domain_base64_and_unknown_root(self):
        raw, sig, keys, ksig = self.raw()
        bad_domain = base64.b64encode(self.signer.sign(b"wrong\0" + raw)) + b"\n"
        unknown = public(Ed25519PrivateKey.generate())
        for signature in (bad_domain, sig + b"\n\n", sig + b"\r", b" " + sig,
                          sig[:-1].rstrip(b"=") + b"\n", b"A" * 88):
            with self.subTest(signature=signature[:8]), self.assertRaises(release.ReleaseError):
                release.validate_metadata(raw, signature, keys, ksig, self.roots, now=NOW)
        with self.assertRaises(release.ReleaseError):
            release.validate_metadata(raw, sig, keys, ksig, {digest(unknown): unknown}, now=NOW)
        with self.assertRaises(release.ReleaseError):
            release.validate_metadata(raw, sig, keys, ksig, {"f" * 64: self.root_public}, now=NOW)

    def test_signature_exact_89_bytes_with_one_lf_only(self):
        raw, sig, keys, ksig = self.raw()
        release.validate_metadata(raw, sig, keys, ksig, self.roots, now=NOW)
        for ending in (b"", b"\r", b"\r\n", b" \n", b"\n\n", b"\r\n\r\n"):
            with self.subTest(ending=ending), self.assertRaises(release.ReleaseError):
                release.validate_metadata(raw, sig, keys, ksig[:-1] + ending, self.roots, now=NOW)

    def test_extra_missing_fields_channel_product_protocol(self):
        for change in ({"extra": 1}, {"channel": "private"}, {"product": "other"},
                       {"protocols": [release.PROTOCOL, "other"]}, {"sequence": 0},
                       {"minKeysetSequence": 2}):
            data = {**self.data, **change}
            with self.subTest(change=change):
                self.rejected(data)
        data = copy.deepcopy(self.data)
        del data["version"]
        self.rejected(data)
        keys = {**self.keys, "extra": 1}
        self.rejected(keys=keys)

    def test_private_keyset_or_release_is_rejected_even_with_valid_signatures(self):
        self.rejected({**self.data, "channel": "private"})
        self.rejected(keys={**self.keys, "channel": "private"})
        self.rejected({**self.data, "channel": "private"},
                      keys={**self.keys, "channel": "private"})

    def test_semver_strict(self):
        for version in ("01.0.0", "1.0", "v1.0.0", "1.0.0-01", "1.0.0-", "1.0.0+", "1.0.0.1"):
            with self.subTest(version=version):
                self.rejected({**self.data, "version": version})
        for version in ("0.0.0", "1.0.0-alpha.1+build.01", "5.1.2"):
            self.validate({**self.data, "version": version})

    def test_expiry_future_and_signer_lifetime(self):
        for change in ({"expiresAt": "2026-11-25T12:00:00Z"},
                       {"issuedAt": "2026-11-26T00:00:00Z"}):
            self.rejected({**self.data, **change}, code="SIGNATURE_EXPIRED")
        keys = copy.deepcopy(self.keys)
        keys["keys"][0]["notBefore"] = "2026-11-02T00:00:00Z"
        self.rejected(keys=keys, code="SIGNATURE_EXPIRED")
        self.rejected(keys={**self.keys, "expiresAt": "2026-11-25T12:00:00Z"}, code="SIGNATURE_EXPIRED")
        self.rejected({**self.data, "issuedAt": "2026-11-01T00:00:60Z"})

    def test_revoked_missing_and_wrong_key_identity(self):
        self.rejected(keys={**self.keys, "revokedKeyIds": [self.key_id]}, code="SIGNATURE_REVOKED")
        self.rejected({**self.data, "keyId": "0" * 64})
        keys = copy.deepcopy(self.keys)
        keys["keys"][0]["keyId"] = "0" * 64
        self.rejected(keys=keys)

    def test_windows_paths_case_collisions_and_file_directory_collision(self):
        for name in ("../a.exe", "/a.exe", "C:/a.exe", "a\\b.exe", "a//b.exe", "a/./b.exe",
                     "a/NUL.txt", "COM0.exe", "LPT9", "con .txt", "a./b", "a /b", "a:b", "a?b", "a\u00e9"):
            data = copy.deepcopy(self.data)
            data["files"][1]["path"] = name
            data["files"].sort(key=lambda r: r["path"])
            with self.subTest(name=name):
                self.rejected(data)
        for paths in (("A/a", "a/b"), ("a", "a/b"), ("app.exe", "APP.exe")):
            data = copy.deepcopy(self.data)
            data["files"] += [row(name, b"x") for name in paths]
            data["files"].sort(key=lambda r: r["path"])
            self.rejected(data)

    def test_inventory_bounds_sorted_unique_and_receiver_required(self):
        for mutate in (lambda d: d.update(files=[]), lambda d: d["files"].reverse(),
                       lambda d: d["files"].append(d["files"][-1]),
                       lambda d: d.update(receiver="missing.exe"),
                       lambda d: d["files"][0].update(size=release.MAX_FILE_SIZE + 1),
                       lambda d: d["files"][0].update(sha256="A" * 64)):
            data = copy.deepcopy(self.data)
            mutate(data)
            self.rejected(data)
        self.rejected({**self.data, "layout": "unpacked"})

    def test_keyset_rotation_and_sorted_keys(self):
        other = Ed25519PrivateKey.generate()
        public_other = public(other)
        keys = copy.deepcopy(self.keys)
        keys["keys"].append(dict(keyId=digest(public_other), publicKey=base64.b64encode(public_other).decode(),
                                 notBefore=BEFORE, notAfter=AFTER))
        keys["keys"].sort(key=lambda r: r["keyId"])
        self.validate(keys=keys)
        keys["keys"].reverse()
        self.rejected(keys=keys)
        keys["keys"] = [keys["keys"][0]] * 2
        self.rejected(keys=keys)

    def test_release_highwater_only_after_authenticated_commit(self):
        store = MemoryStore()
        higher = self.validate({**self.data, "sequence": 2}, store=store)
        self.assertEqual(store.state["releaseSequence"], 0)
        self.validate(store=store)
        higher.commit_authenticated(now=NOW)
        self.assertEqual(store.state["releaseSequence"], 2)
        self.rejected(store=store, code="SIGNATURE_ROLLBACK")
        self.rejected({**self.data, "sequence": 2, "releaseId": "different"}, store=store,
                      code="SIGNATURE_ROLLBACK")
        self.validate({**self.data, "sequence": 2}, store=store)

    def test_explicit_store_at_commit_advances_keyset_as_well_as_release(self):
        info = self.validate()
        store = MemoryStore()
        info.commit_authenticated(store, now=NOW)
        self.assertEqual(store.state["keysetSequence"], 1)
        self.assertEqual(store.state["keysetSha256"], info.keyset_digest)
        self.assertEqual(store.state["releaseSequence"], 1)

    def test_keyset_highwater_equivocation_and_irreversible_revocation(self):
        store = MemoryStore()
        self.validate(store=store)
        keys = {**self.keys, "sequence": 2, "revokedKeyIds": [self.key_id]}
        self.rejected(keys=keys, store=store, code="SIGNATURE_REVOKED")
        self.assertEqual(store.state["keysetSequence"], 2)
        self.rejected(store=store, code="SIGNATURE_ROLLBACK")
        self.rejected(keys={**keys, "expiresAt": "2027-02-01T00:00:00Z"}, store=store,
                      code="SIGNATURE_ROLLBACK")
        # Even a newer root-signed policy cannot silently re-enable a key whose
        # revocation this reader already accepted.
        self.rejected(keys={**self.keys, "sequence": 3}, store=store, code="SIGNATURE_REVOKED")

    def test_unauthenticated_info_rejected_after_concurrent_revocation(self):
        store = MemoryStore()
        info = self.validate(store=store)
        self.rejected(keys={**self.keys, "sequence": 2, "revokedKeyIds": [self.key_id]},
                      store=store, code="SIGNATURE_REVOKED")
        with self.assertRaises(release.ReleaseError):
            info.commit_authenticated(now=NOW)
        self.assertEqual(store.state["releaseSequence"], 0)


@unittest.skipUnless(os.name == "nt" and Ed25519PrivateKey is not None, "Windows pins and SDK")
class FileAndStoreTests(SigningFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="reader-signed-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher = self.base / "renamed-safe-launcher.exe"
        self.launcher.write_bytes(self.launcher_data)
        self.runtime = self.base / "runtime"
        (self.runtime / "resources").mkdir(parents=True)
        (self.runtime / "app.exe").write_bytes(self.receiver_data)
        (self.runtime / "resources" / "app.asar").write_bytes(self.resource_data)

    def sidecars(self, data=None):
        for path, raw in zip(release._sidecars(self.launcher), self.raw(data)):
            path.write_bytes(raw)

    def test_no_sidecars_is_only_legacy_case(self):
        self.assertIsNone(release.inspect_release(self.launcher, self.roots, now=NOW))
        release._sidecars(self.launcher)[0].write_bytes(b"{}")
        with self.assertRaises(release.ReleaseError):
            release.inspect_release(self.launcher, self.roots, now=NOW)

    def test_portable_pins_files_and_rejects_resource_extra_missing_hash(self):
        self.sidecars()
        info = release.inspect_release(self.launcher, self.roots, now=NOW)
        with info.pin_tree(self.runtime, now=NOW) as recheck:
            recheck()
            for target in (self.launcher, self.runtime / "app.exe", self.runtime / "resources" / "app.asar"):
                with self.assertRaises(OSError):
                    target.write_bytes(b"changed")
                with self.assertRaises(OSError):
                    target.rename(target.with_name(target.name + ".renamed"))
                with self.assertRaises(OSError):
                    target.unlink()
            with self.assertRaises(OSError):
                (self.runtime / "resources").rename(self.runtime / "renamed-resources")
        resource = self.runtime / "resources" / "app.asar"
        resource.write_bytes(b"changed")
        with self.assertRaises(release.ReleaseError) as caught, info.pin_tree(self.runtime, now=NOW):
            pass
        self.assertEqual(caught.exception.code, "RUNTIME_MISMATCH")
        resource.write_bytes(self.resource_data)
        (self.runtime / "extra").write_bytes(b"extra")
        with self.assertRaises(release.ReleaseError), info.pin_tree(self.runtime, now=NOW):
            pass
        (self.runtime / "extra").unlink()
        resource.unlink()
        with self.assertRaises(release.ReleaseError), info.pin_tree(self.runtime, now=NOW):
            pass

    def test_inventory_recheck_detects_added_file_and_launcher_replacement(self):
        self.sidecars()
        info = release.inspect_release(self.launcher, self.roots, now=NOW)
        with self.assertRaises(release.ReleaseError):
            with info.pin_tree(self.runtime, now=NOW):
                (self.runtime / "extra-file").write_bytes(b"new")
        (self.runtime / "extra-file").unlink()
        self.launcher.write_bytes(b"changed")
        with self.assertRaises(release.ReleaseError), info.pin_tree(self.runtime, now=NOW):
            pass

    def test_unpacked_sidecars_excluded_but_other_extras_rejected(self):
        self.launcher = self.runtime / "app.exe"
        data = copy.deepcopy(self.data)
        data.update(layout="unpacked", launcher=data["files"][0])
        self.sidecars(data)
        info = release.inspect_release(self.launcher, self.roots, now=NOW)
        with info.pin_tree(self.runtime, now=NOW):
            pass
        with self.assertRaises(release.ReleaseError), info.pin_tree(self.base, now=NOW):
            pass

    def test_caller_delivery_uncertainty_and_valueerror_preserved_exactly(self):
        self.sidecars()
        info = release.inspect_release(self.launcher, self.roots, now=NOW)
        uncertain = release.TransferError("synthetic delivered request", code="UNAUTHORIZED", delivery_possible=True)
        ordinary = ValueError("synthetic caller parsing failure")
        for error in (uncertain, ordinary, OSError("synthetic caller IO")):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)) as caught:
                with info.pin_tree(self.runtime, now=NOW):
                    raise error
            self.assertIs(caught.exception, error)
        self.assertTrue(uncertain.delivery_possible)

    def test_direct_child_pin_requires_a_retained_parent(self):
        api = release.registry.WindowsSecurity()
        with self.assertRaises(release.ReleaseError), release._pin_child(
                self.runtime / "app.exe", api, parents=set()):
            pass
        with release.registry.checked_handle(self.runtime, directory=True):
            with release._pin_child(self.runtime / "app.exe", api, parents={self.runtime}):
                with self.assertRaises(OSError):
                    (self.runtime / "app.exe").write_bytes(b"changed")

    def test_runtime_junction_is_rejected_before_traversal(self):
        self.sidecars()
        info = release.inspect_release(self.launcher, self.roots, now=NOW)
        target = self.base / "external-synthetic-target"
        target.mkdir()
        (target / "synthetic.txt").write_bytes(b"not runtime")
        junction = self.runtime / "junction"
        # A directory junction needs no symlink privilege. Both paths are this
        # test's disposable fixture, with no user/profile target involved.
        made = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J",
                               str(junction), str(target)], capture_output=True, check=False)
        if made.returncode:
            self.skipTest("test environment refused synthetic junction creation")
        try:
            with self.assertRaises(release.ReleaseError) as caught, info.pin_tree(self.runtime, now=NOW):
                pass
            self.assertEqual(caught.exception.code, "RUNTIME_MISMATCH")
        finally:
            junction.rmdir()

    def test_real_protected_atomic_store_persists(self):
        # Remove only the in-memory mutex replacement. This test exercises real
        # private creation, ACL verification, atomic replacement and named lock.
        patch.stopall()
        store = release.ReleaseStore(self.base / "profile" / "release-trust")
        info = self.validate(store=store)
        info.commit_authenticated(now=NOW)
        again = release.ReleaseStore(store.root)
        self.assertEqual(again._read()["releaseSequence"], 1)
        with release.registry.checked_handle(store.path, root=store.root, read=True):
            pass
        self.validate({**self.data, "sequence": 2}, store=again).commit_authenticated(now=NOW)
        self.rejected(store=again, code="SIGNATURE_ROLLBACK")
        self.assertEqual(len(list(store.root.glob("*.tmp"))), 0)


if __name__ == "__main__":
    unittest.main()

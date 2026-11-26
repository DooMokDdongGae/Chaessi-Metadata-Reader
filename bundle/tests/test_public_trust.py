"""PUBLIC trust boundaries; synthetic signing keys exist in memory only."""
import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bundle import preset_release as release
from bundle import preset_session as session
from bundle import preset_trust as trust
from bundle.tests.test_preset_release import Ed25519PrivateKey, NOW, SigningFixture


# Public fingerprints of retired development test anchors, never trust inputs.
DEVELOPMENT_ROOT_IDS = frozenset((
    "90bc06e2edfeeca5a5e7215e642d73b5e544dcf5f3e9814801534520e8a5addd",
    "780431c63166b0c10a87eb4a38a7d44a0fbf6a417cb3a6b7c4ebbad23765931a",
    "ad971a88043c83ac46ba4e4227cd061c80d10305b6b8df5706f6480f16bfb47e",
    "b84b42f3df74a70acddb50e7a56fc7008bc2106674c620de64f5084300678a59",
))


class PublicTrustConfigurationTests(unittest.TestCase):
    def test_public_channel_and_dedicated_highwater_realm(self):
        self.assertEqual(trust.CHANNEL, "public")
        self.assertEqual(trust.REALM, "public-production")
        with TemporaryDirectory(prefix="reader-public-trust-") as directory:
            reader = session.PresetSession(root=Path(directory))
            self.assertIs(reader.publisher_roots, trust.ROOTS)
            self.assertEqual(reader.release_store.root,
                             Path(directory) / "release-trust" / "public-production")

    def test_embedded_anchors_are_nonempty_correctly_identified_and_exclude_development(self):
        self.assertTrue(trust.ROOTS, "A PUBLIC build must contain its production trust anchor")
        self.assertFalse(DEVELOPMENT_ROOT_IDS.intersection(trust.ROOTS))
        for key_id, public in trust.ROOTS.items():
            with self.subTest(key_id=key_id):
                self.assertIsInstance(public, bytes)
                self.assertEqual(len(public), 32)
                self.assertEqual(hashlib.sha256(public).hexdigest(), key_id)


@unittest.skipUnless(Ed25519PrivateKey is not None, "cryptography Ed25519 SDK required")
class PublicTrustMetadataTests(SigningFixture, unittest.TestCase):
    def test_public_positive_requires_explicit_synthetic_root_injection(self):
        info = self.validate()
        self.assertEqual(info.metadata["channel"], "public")
        self.assertNotIn(info.root_key_id, trust.ROOTS)
        with self.assertRaises(release.ReleaseError) as caught:
            release.validate_metadata(*self.raw(), trust.ROOTS, now=NOW)
        self.assertEqual(caught.exception.code, "SIGNATURE_INVALID")

    def test_private_signed_metadata_cannot_enter_public_consumer_with_injected_root(self):
        private_data = {**self.data, "channel": "private"}
        private_keys = {**self.keys, "channel": "private"}
        for data, keys in ((private_data, self.keys), (self.data, private_keys),
                           (private_data, private_keys)):
            with self.subTest(release=data["channel"], keyset=keys["channel"]):
                with self.assertRaises(release.ReleaseError) as caught:
                    release.validate_metadata(*self.raw(data, keys), self.roots, now=NOW)
                self.assertEqual(caught.exception.code, "SIGNATURE_INVALID")

    def test_public_keyset_rotation_uses_root_without_changing_embedded_anchors(self):
        from bundle.tests.test_preset_release import public, digest, BEFORE, AFTER
        import base64
        anchors_before = dict(trust.ROOTS)
        rotated_signer = Ed25519PrivateKey.generate()
        rotated_public = public(rotated_signer)
        keys = copy.deepcopy(self.keys)
        keys["sequence"] = 2
        keys["keys"].append(dict(keyId=digest(rotated_public),
                                  publicKey=base64.b64encode(rotated_public).decode(),
                                  notBefore=BEFORE, notAfter=AFTER))
        keys["keys"].sort(key=lambda item: item["keyId"])
        self.signer = rotated_signer
        data = {**self.data, "keyId": digest(rotated_public), "minKeysetSequence": 2,
                "sequence": 2}
        info = self.validate(data, keys)
        self.assertEqual(info.keyset_sequence, 2)
        self.assertEqual(info.root_key_id, next(iter(self.roots)))
        self.assertEqual(trust.ROOTS, anchors_before)


if __name__ == "__main__":
    unittest.main()

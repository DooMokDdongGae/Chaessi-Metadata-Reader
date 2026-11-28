"""Narrow offline tests for catalogue pins and candidate package scanning."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


PACKAGING = Path(__file__).resolve().parents[1]
DELTA = runpy.run_path(str(PACKAGING / "release_delta.py"))
AUDIT = runpy.run_path(str(PACKAGING / "audit.py"))


def payload(extra=False):
    result = {"ChaessiMetadataReader.exe": "a" * 64, "product.id": "b" * 64}
    if extra:
        result["docs/README.en.md"] = "c" * 64
    return result


class CatalogueTests(unittest.TestCase):
    def test_approved_manifest_requires_exact_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            original = json.dumps({"payload": payload()}).encode()
            path.write_bytes(original)
            identity = ("approved", 1, hashlib.sha256(original).hexdigest())
            self.assertEqual(DELTA["read_approved"](path, identity)["payload"], payload())
            path.write_bytes(original + b"\n")
            with self.assertRaisesRegex(ValueError, "not the approved file"):
                DELTA["read_approved"](path, identity)

    def test_v110_is_additive_and_preferred_without_removing_existing_pins(self):
        make = DELTA["catalogue"]
        def approved(path, identity):
            return {"id": identity[0], "sequence": identity[1], "payload": payload()}
        with patch.dict(make.__globals__, read_approved=approved):
            historical = make(payload(True), *range(5))
            current = make(payload(True), *range(6))
        self.assertEqual(len(historical["known"]), 5)
        self.assertEqual(len(current["known"]), 6)
        self.assertEqual(current["known"][0]["id"], DELTA["V110_BASELINE"][0])
        self.assertEqual(current["known"][1:], historical["known"])
        self.assertGreater(current["target"]["sequence"], current["known"][0]["sequence"])
        self.assertIsNone(current["patch_baseline_id"])

    def test_new_target_cannot_discard_old_owned_files(self):
        make = DELTA["catalogue"]
        def approved(path, identity):
            return {"id": identity[0], "sequence": identity[1], "payload": payload(True)}
        with patch.dict(make.__globals__, read_approved=approved):
            with self.assertRaisesRegex(ValueError, "cannot remove"):
                make(payload(), *range(6))

    def test_unsafe_payload_names_are_rejected(self):
        for name in ("../escape", "docs/NUL.txt", "docs/trailing ", "docs/colon:name", "docs/CON .txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                DELTA["validate_payload"]({**payload(), name: "c" * 64})


class PrivateScanTests(unittest.TestCase):
    def test_user_data_and_workspace_paths_rejected_in_both_encodings(self):
        paths = ["Q:" + "/Users/Synthetic/AppData/Local/test",
                 "Q:" + "/work/02_PROJECTS/test/main.py"]
        for value in paths:
            for encoding in ("utf-8", "utf-16-le"):
                with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                    AUDIT["check_private_strings"](value.encode(encoding), "synthetic")

    def test_private_key_marker_rejected_without_logging_values(self):
        for value in (("-----BEGIN " + "PRIVATE KEY-----"),
                      "Bearer " + "synthetic" * 4,
                      'access_token="' + "synthetic" * 4 + '"'):
            with self.subTest(category="synthetic credential"), self.assertRaisesRegex(ValueError, "synthetic"):
                AUDIT["check_private_strings"](value.encode(), "synthetic")

    def test_public_install_policy_and_upstream_paths_are_not_user_data(self):
        AUDIT["check_private_strings"](b"%LOCALAPPDATA%/Programs/ChaessiMetadataReader", "policy")
        AUDIT["check_private_strings"](b"/home/runner/work/dependency/src/build", "upstream")


if __name__ == "__main__":
    unittest.main()

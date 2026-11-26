"""Hash-pinned native SDK provenance for the PRIVATE Ed25519 verifier build."""
import hashlib
import importlib.metadata
import json
from pathlib import Path


def inputs():
    return json.loads(Path(__file__).with_name("sdk-inputs.json").read_bytes())


def verify_sdk_inputs():
    document = inputs()
    for name, entry in document["packages"].items():
        distribution = importlib.metadata.distribution(name)
        if distribution.version != entry["version"]:
            raise ValueError(f"Unexpected SDK version: {name}")
        for member, expected in entry["files"].items():
            path = Path(distribution.locate_file(member)).resolve()
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"SDK input differs from official pinned wheel: {member}")


def native_provenance(source):
    source = Path(source).resolve()
    for name, entry in inputs()["packages"].items():
        distribution = importlib.metadata.distribution(name)
        if distribution.version != entry["version"]:
            raise ValueError(f"Unexpected SDK version: {name}")
        for member, expected in entry["files"].items():
            if Path(member).suffix.lower() not in (".pyd", ".dll"):
                continue
            if source == Path(distribution.locate_file(member)).resolve():
                actual = hashlib.sha256(source.read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError(f"SDK native input changed: {member}")
                return {"sdk": name, "version": entry["version"], "wheel": entry["wheel"],
                        "wheel_sha256": entry["wheel_sha256"], "member": member, "sha256": actual}
    return None

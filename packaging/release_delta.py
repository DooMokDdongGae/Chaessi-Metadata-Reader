"""Create a trusted catalogue and classify the actual measured payload delta."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


APP_EXE = "ChaessiMetadataReader.exe"
APP_VERSION = "1.1.1"
TARGET_ID = "reader-20261128-01-public"
TARGET_SEQUENCE = 2026112801
V110_BASELINE = ("reader-20261126-01-public", 2026112601,
                 "595785f544625c4711f30755c9b098ae6dee2d63463ee2b4bfc21fe4f7d3f4a9")
RELOCATION_BASELINE = ("reader-20261125-02-d-relocation", 2026112502,
                       "f7bf31977be5f90c0d2d15859c859e4961accf3fe1c8c23e5d523eb905d359dc")
V101_BASELINE = ("reader-20261125-01", 2026112501,
                 "e7508ed5eeda16c021388cf1549552b5ce36ac81a97b252066fb7a0e384bf646")
PUBLIC_BASELINE = ("reader-20261124-01", 2026112401,
                   "305ef89bcc8919c4a2086dd38e4c0e5d8d13d746d83436731dcd4856db08e3b1")
NOV23_BASELINE = ("reader-20261123-slots-02", 2026112302,
                  "a038777d8b83a16cf29a68cae9c2c219721398923ae83f3cc84633508f585439")
NOV22_BASELINE = ("reader-20261122-release-05", 2026112205,
                  "ccabc5e2bc418d8d33847b9b6eaf1255be09853f1aaa7c192d03683d5be51e38")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_payload(payload):
    if not isinstance(payload, dict) or APP_EXE not in payload or "product.id" not in payload:
        raise ValueError("Payload must contain the Reader executable and product marker")
    normalized = set()
    for raw, digest in payload.items():
        name = PurePosixPath(raw)
        folded = name.as_posix().casefold()
        if (name.is_absolute() or name.as_posix() != raw or folded in normalized
                or any(not part.isascii() or not re.fullmatch(r"[\w .()+@,#=-]+", part)
                       or part in {".", ".."} or part.endswith((".", " "))
                       or part.split(".", 1)[0].rstrip(" .").casefold() in DEVICES for part in name.parts)
                or not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
            raise ValueError(f"Invalid measured payload member: {raw}")
        normalized.add(folded)
    return dict(sorted(payload.items()))


def read_approved(path, identity):
    build_id, sequence, sha256 = identity
    path = Path(path)
    if sha(path) != sha256:
        raise ValueError(f"The manifest for {build_id} is not the approved file")
    value = json.loads(path.read_bytes())
    return {"id": build_id, "sequence": sequence, "payload": validate_payload(value["payload"])}


def catalogue(target, baseline, nov23, nov22, v101, relocation, v110=None):
    target = {"id": TARGET_ID, "sequence": TARGET_SEQUENCE, "payload": validate_payload(target)}
    known = ([read_approved(v110, V110_BASELINE)] if v110 is not None else [])
    known += [read_approved(relocation, RELOCATION_BASELINE), read_approved(v101, V101_BASELINE),
             read_approved(baseline, PUBLIC_BASELINE), read_approved(nov23, NOV23_BASELINE),
             read_approved(nov22, NOV22_BASELINE)]
    if any(not entry["payload"].keys() <= target["payload"].keys() for entry in known):
        raise ValueError("The Setup cannot remove previously owned payload paths")
    return {"schema": 1, "target": target, "known": known, "patch_baseline_id": None}


def classify(before, after):
    common = before.keys() & after.keys()
    return {
        "unchanged": sorted(name for name in common if before[name] == after[name]),
        "changed": sorted(name for name in common if before[name] != after[name]),
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
    }


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, indent=2, ensure_ascii=False, sort_keys=True)
        file.write("\n")

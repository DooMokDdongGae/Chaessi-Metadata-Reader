"""Approved Reader build identities and update decisions, without Windows I/O."""
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import PureWindowsPath
from types import MappingProxyType


APP = "ChaessiMetadataReader.exe"
PRODUCT_ID = "chaessi-metadata-reader-{328AA667-9BAC-42AA-8124-525AD9EB95D2}"
SHA = re.compile(r"[0-9a-f]{64}")
BUILD_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
PATH_PART = re.compile(r"[\w .()+@,#=-]+", re.ASCII)
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}
INSTALL_RESERVED = RESERVED | {"CONIN$", "CONOUT$", "CLOCK$", *(f"COM{i}" for i in "¹²³"),
                               *(f"LPT{i}" for i in "¹²³")}
OWNER_FILES = {"uninstall.exe", "uninstaller.copy", "start-link.copy",
               "guide-link.copy", "desktop-link.copy"}


class Refusal(Exception):
    def __init__(self, code, exit_code=2):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def reject(code, condition=True):
    if condition:
        raise Refusal(code)


def bytes_for(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def parse_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            reject("DUPLICATE_JSON_KEY", key in result)
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Refusal("INVALID_JSON") from None


def valid_id(value):
    return isinstance(value, str) and bool(BUILD_ID.fullmatch(value))


def valid_hash(value):
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def valid_sequence(value):
    return type(value) is int and 0 < value <= 2147483647


def installation_path(value):
    """Validate a local installation root, independently of manifest filenames.

    Manifest members remain the existing ASCII allowlist. A user-selected root
    may contain Unicode and spaces, but must have one unambiguous Win32 spelling.
    This function grants no filesystem ownership or deletion authority.
    """
    reject("UNSAFE_INSTALL_ROOT", not isinstance(value, str) or not 3 < len(value) <= 200
           or not re.match(r"^[A-Za-z]:[\\/]", value))
    # Inspect the original spelling before PureWindowsPath normalizes dot/empty
    # components. Permit one conventional trailing separator, not interior ones.
    spelling = value.replace("/", "\\")
    components = spelling[3:].removesuffix("\\").split("\\")
    for part in components:
        reject("UNSAFE_INSTALL_ROOT", not part or part in (".", "..")
               or part.endswith((" ", "."))
               or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
               or part.split(".")[0].rstrip(" .").upper() in INSTALL_RESERVED)
    return PureWindowsPath(value)


def relative_parts(value):
    reject("UNSAFE_MANIFEST_PATH", not isinstance(value, str) or not 0 < len(value) <= 230)
    parts = value.split("/")
    for part in parts:
        reject("UNSAFE_MANIFEST_PATH", not PATH_PART.fullmatch(part)
               or part.endswith((" ", ".")) or part.split(".")[0].rstrip(" .").upper() in RESERVED)
    reject("UNSAFE_MANIFEST_PATH", parts[0].casefold() in OWNER_FILES)
    return tuple(parts)


@dataclass(frozen=True)
class State:
    id: str
    sequence: int
    manifest_sha256: str
    owned_paths_sha256: str

    @classmethod
    def from_json(cls, doc):
        reject("INVALID_UPDATE_STATE", not isinstance(doc, dict)
               or set(doc) != {"schema", "id", "sequence", "manifest_sha256", "owned_paths_sha256"}
               or type(doc["schema"]) is not int or doc["schema"] != 1
               or not valid_id(doc["id"]) or not valid_sequence(doc["sequence"])
               or not valid_hash(doc["manifest_sha256"]) or not valid_hash(doc["owned_paths_sha256"]))
        return cls(doc["id"], doc["sequence"], doc["manifest_sha256"], doc["owned_paths_sha256"])

    def as_json(self):
        return {"schema": 1, "id": self.id, "sequence": self.sequence,
                "manifest_sha256": self.manifest_sha256, "owned_paths_sha256": self.owned_paths_sha256}


@dataclass(frozen=True)
class Release:
    state: State
    payload: MappingProxyType
    self_test: bool

    @classmethod
    def from_json(cls, doc):
        reject("INVALID_BUILD", not isinstance(doc, dict) or not {"id", "sequence", "payload"} <= set(doc)
               or set(doc) - {"id", "sequence", "payload", "self_test"}
               or not valid_id(doc["id"]) or not valid_sequence(doc["sequence"])
               or type(doc.get("self_test", True)) is not bool or not isinstance(doc["payload"], dict)
               or not 1 < len(doc["payload"]) <= 4096)
        payload = doc["payload"]
        reject("MISSING_PRODUCT_FILES", APP not in payload or "product.id" not in payload)
        reject("WRONG_PRODUCT_MARKER", payload["product.id"] != hashlib.sha256(PRODUCT_ID.encode("ascii")).hexdigest())
        spellings = {}
        names = set()
        directories = set()
        for rel, sha in payload.items():
            parts = relative_parts(rel)
            reject("INVALID_BUILD_HASH", not valid_hash(sha))
            for length in range(1, len(parts) + 1):
                spelling = "/".join(parts[:length])
                key = spelling.casefold()
                reject("CASE_COLLISION", spellings.setdefault(key, spelling) != spelling)
                (names if length == len(parts) else directories).add(key)
        reject("FILE_DIRECTORY_COLLISION", bool(names & directories))
        state = State(doc["id"], doc["sequence"], hashlib.sha256(bytes_for(payload)).hexdigest(),
                      hashlib.sha256(bytes_for(sorted(payload))).hexdigest())
        return cls(state,
                   MappingProxyType(dict(payload)), doc.get("self_test", True))


@dataclass(frozen=True)
class Catalogue:
    target: Release
    releases: tuple
    patch_baseline_id: str | None

    @classmethod
    def from_json(cls, doc):
        reject("INVALID_CATALOGUE", not isinstance(doc, dict)
               or set(doc) != {"schema", "target", "known", "patch_baseline_id"}
               or type(doc["schema"]) is not int or doc["schema"] != 1 or not isinstance(doc["known"], list)
               or len(doc["known"]) > 12)
        target = Release.from_json(doc["target"])
        releases = (target, *(Release.from_json(row) for row in doc["known"]))
        for attribute in ("id", "sequence", "manifest_sha256"):
            reject("DUPLICATE_BUILD_IDENTITY", len({getattr(r.state, attribute) for r in releases}) != len(releases))
        baseline = doc["patch_baseline_id"]
        reject("INVALID_PATCH_BASELINE", baseline is not None and not any(
            r.state.id == baseline and r.state.sequence < target.state.sequence for r in releases))
        return cls(target, releases, baseline)

    def find(self, state):
        return next((r for r in self.releases if r.state == state), None)

    def check_high_water(self, state):
        if state is not None:
            target = self.target.state
            reject("DOWNGRADE_BLOCKED", state.sequence > target.sequence)
            reject("BUILD_SEQUENCE_CONFLICT", state.sequence == target.sequence and state != target)
            reject("UNKNOWN_RECORDED_BUILD", self.find(state) is None)

    def decide(self, observed, state, *, patch=False):
        self.check_high_water(state)
        target = self.target
        if observed is None:
            reject("PATCH_REQUIRES_APPROVED_BASELINE", patch)
            return "fresh"
        if observed == target:
            return "current"
        reject("DOWNGRADE_BLOCKED", observed.state.sequence >= target.state.sequence)
        reject("PATCH_REQUIRES_APPROVED_BASELINE", patch and observed.state.id != self.patch_baseline_id)
        if state and state.sequence > observed.state.sequence:
            # A Full Setup can move forward from an exact, catalogued older
            # overwrite even when the recorded official build predates this Setup.
            reject("UNAPPROVED_LEGACY_OVERWRITE", patch and state != target.state)
            return "repair"
        return "upgrade"


def changed_paths(before, after, *, patch=False):
    # FULL can add catalogued files only when the engine also transactionally
    # replaces both uninstaller receipts. Removal is deliberately unsupported.
    reject("SETUP_OWNERSHIP_CHANGE_UNSUPPORTED", not before.payload.keys() <= after.payload.keys()
           or patch and before.payload.keys() != after.payload.keys())
    paths = tuple(sorted(path for path, digest in after.payload.items() if before.payload.get(path) != digest))
    reject("PATCH_REQUIRES_EXE_ONLY", patch and paths != (APP,))
    return paths

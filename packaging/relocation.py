"""Migrate only the attested public C installation to the fixed D edition."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import re
import subprocess
import sys
import uuid
import winreg

from bundle.transfer_client import TransferError
import update_policy as policy
from update_engine import APP, ARP, FRESH, JOURNAL, STATE, Updater, WindowsOperations, known_folder, windows_api


RELOCATION = "relocation.json"
RECEIPT = "relocation-receipt.json"
LEGACY_ID = "reader-20261124-01"
# This exact stock 11/23 remover uses the common NSIS mutex but predates
# the update-engine file lock. A clean 11/24 installation is a different owner.
LEGACY_REMOVERS = {
    "8d285414b0386e159fa2686488b7b896220ab99aa070b28661298d4e8833c72e",
}
LINKS = {"start": "start-link.copy", "guide": "guide-link.copy", "desktop": "desktop-link.copy"}
OWNER = {"Uninstall.exe", "uninstaller.copy", *LINKS.values()}
LINK_LIMIT = 1024 * 1024
REGISTRY_TYPES = {winreg.REG_SZ, winreg.REG_DWORD}


def registry_values():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return None
    with key:
        children, count, _ = winreg.QueryInfoKey(key)
        policy.reject("UNSAFE_EXISTING_REGISTRATION", children != 0 or count > 24)
        result = {}
        for index in range(count):
            name, value, kind = winreg.EnumValue(key, index)
            policy.reject("UNSAFE_EXISTING_REGISTRATION",
                          not name or len(name) > 100 or kind not in REGISTRY_TYPES
                          or type(value) not in (str, int) or isinstance(value, str) and len(value) > 2048)
            result[name] = [value, kind]
        return result


def applicable_registration(install, values):
    return (isinstance(values, dict)
            and values.get("InstallLocation") == [str(install), winreg.REG_SZ]
            and values.get("UninstallString") == ['"' + str(install / "Uninstall.exe") + '"', winreg.REG_SZ])


def valid_registry_shape(values):
    return isinstance(values, dict) and len(values) <= 24 and all(
        isinstance(name, str) and 0 < len(name) <= 100 and isinstance(pair, list) and len(pair) == 2
        and ((pair[1] == winreg.REG_SZ and isinstance(pair[0], str) and len(pair[0]) <= 2048)
             or (pair[1] == winreg.REG_DWORD and type(pair[0]) is int and 0 <= pair[0] < 2**32))
        for name, pair in values.items())


def registration(install, language):
    exe = str(install / APP)
    uninstall = '"' + str(install / "Uninstall.exe") + '"'
    values = {"DisplayName": "Chaessi Metadata Reader", "Publisher": "CHAESSI",
              "DisplayVersion": "1.1.0", "DisplayIcon": exe, "InstallLocation": str(install),
              "UninstallString": uninstall, "QuietUninstallString": uninstall + " /S",
              "InstallerLanguage": str(language)}
    return {**{name: [value, winreg.REG_SZ] for name, value in values.items()},
            "NoModify": [1, winreg.REG_DWORD], "NoRepair": [1, winreg.REG_DWORD]}


def write_registry(values):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ARP, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
        for name, (value, kind) in values.items():
            winreg.SetValueEx(key, name, 0, kind, value)
        winreg.FlushKey(key)


def remove_registry():
    if registry_values() is not None:
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, ARP, winreg.KEY_WOW64_64KEY)


def links_in_profile(legacy):
    programs = known_folder("A77F5D77-2E2B-44C3-A6A2-ABA601054A51") / "Chaessi Metadata Reader"
    desktop = known_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
    links = {"start": programs / "Chaessi Metadata Reader.lnk", "guide": programs / "Guide.lnk",
             "desktop": desktop / "Chaessi Metadata Reader.lnk"}
    profile = known_folder("5E6C858F-0E22-4760-9AFE-EA3317B67173")
    for path in links.values():
        policy.reject("UNSUPPORTED_SHORTCUT_LOCATION", not path.is_relative_to(profile)
                      or path.drive.casefold() != legacy.control.drive.casefold())
        legacy.validate_chain(path)
    return links


def make_directory(files, path):
    kind = files.kind(path)
    if kind is None:
        make_directory(files, path.parent)
        files.make_dir(path)
    with files.pinned(path, directory=True):
        pass


def copy_into_place(files, source, target, expected, scratch):
    """Stage bytes next to the product's volume and publish without overwrite."""
    make_directory(files, target.parent)
    pending = scratch / ("place-" + uuid.uuid4().hex)
    files.copy(source, pending, expected)
    policy.reject("DESTINATION_COLLISION", files.kind(target) is not None)
    files.restore_absent(pending, target)


def verified_hash(files, path, *, limit=None):
    info = files.inspect(path)
    policy.reject("MISSING_OR_INVALID_MIGRATION_INPUT",
                  info is None or not info.size or limit is not None and info.size > limit)
    return info.digest


def observed(files, path):
    info = files.inspect(path)
    return None if info is None else info.digest


def prove_expected_or_missing(files, members):
    for path, digest in members.items():
        policy.reject("MIGRATION_EXTERNAL_FILE_CHANGE", observed(files, path) not in (None, digest))


def retire_uninstaller(legacy, copy, sha):
    # NSIS normally relaunches a temporary child and returns immediately.
    # Invoke a verified copy to obtain the actual result while allowing the
    # uninstaller to remove every owned C file, including the original exe.
    command = subprocess.list2cmdline([str(copy), "/S"]) + " _?=" + str(legacy.install)
    with legacy.pinned(copy, read=True):
        policy.reject("LEGACY_REMOVER_CHANGED", not legacy.matches(copy, sha))
        process = subprocess.Popen(command, executable=str(copy), cwd=copy.parent, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            raise policy.Refusal("LEGACY_REMOVAL_STILL_RUNNING", 5) from None
    policy.reject("LEGACY_REMOVE_FAILED", code != 0)


def assert_remover_stopped(copy):
    _, registry = windows_api()
    for pid, (_, basename) in registry.process_snapshot().items():
        if basename.casefold() != copy.name.casefold():
            continue
        try:
            with registry._process(pid) as (image, _, verify):
                verify()
                policy.reject("LEGACY_REMOVAL_STILL_RUNNING", image == copy)
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (6, 87, 1168):
                raise


def require_legacy_mutex_available():
    _, registry = windows_api()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    open_mutex = registry._api(api, "OpenMutexW", wintypes.HANDLE,
                               wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    close = registry._api(api, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    handle = open_mutex(0x00100000, False, r"Local\CHAESSI.MetadataReader.Setup")
    if handle:
        close(handle)
        raise policy.Refusal("LEGACY_SETUP_IN_PROGRESS")
    if ctypes.get_last_error() != 2:
        raise policy.Refusal("LEGACY_SETUP_MUTEX_NOT_VERIFIED")


class Migration:
    def __init__(self, catalogue, files):
        self.catalogue = catalogue
        self.files = files
        self.legacy = WindowsOperations.for_user(legacy=True)
        self.updater = Updater(catalogue, files)
        self.legacy_updater = Updater(catalogue, self.legacy)
        self.journal = files.control / RELOCATION
        self._links = None

    @property
    def links(self):
        if self._links is None:
            self._links = links_in_profile(self.legacy)
        return self._links

    def check_interference(self):
        for name in (JOURNAL, FRESH):
            policy.reject("LEGACY_UPDATE_PENDING", self.files.kind(self.files.control / name) is not None)
        self.legacy.ensure_closed()
        self.files.ensure_closed()

    def baseline(self):
        self.check_interference()
        known = self.legacy_updater.observed_release()
        state = self.updater.read_state()
        policy.reject("UNSUPPORTED_C_READER_BUILD", known is None or known.state.id != LEGACY_ID
                      or known.state != state)
        official = verified_hash(self.legacy, self.legacy.install / "Uninstall.exe")
        policy.reject("UNKNOWN_LEGACY_REMOVER", official not in LEGACY_REMOVERS)
        return known

    def verify_dest_clear(self):
        install = self.files.install
        self.files.validate_chain(install)
        kind = self.files.kind(install)
        policy.reject("INVALID_D_READER_ROOT", kind not in (None, "directory"))
        if kind == "directory":
            self.updater.check_unowned_loaders(self.catalogue.target)
        for name in (*self.catalogue.target.payload, *OWNER):
            path = install / name
            self.files.validate_chain(path)
            policy.reject("DESTINATION_COLLISION", self.files.kind(path) is not None)

    def guard(self):
        if self.files.kind(self.journal) is not None:
            row, _ = self.read_journal()
            return 21 if row["phase"] == "trial" else 22
        current = registry_values()
        if applicable_registration(self.legacy.install, current):
            self.baseline()
            self.verify_dest_clear()
            return 20
        if not applicable_registration(self.files.install, current):
            policy.reject("UNKNOWN_READER_REGISTRATION", current is not None)
        policy.reject("UNREGISTERED_C_READER",
                      any(self.legacy.kind(self.legacy.install / name) is not None
                          for name in (APP, "Uninstall.exe", "product.id")))
        return 0

    def archive(self, name, baseline, uninstaller, link_sources, language):
        workspace = self.files.control / name
        self.legacy.make_dir(workspace)
        old_files = dict(baseline.payload)
        for owner in OWNER:
            value = observed(self.legacy, self.legacy.install / owner)
            if value:
                old_files[owner] = value
        old_links = {}
        new_links = {}
        link_payload = {}
        for role, path in self.links.items():
            value = observed(self.legacy, path)
            owned = old_files.get(LINKS[role])
            if role in ("start", "guide"):
                policy.reject("SHORTCUT_CONFLICT", value is not None and value != owned)
            if value is not None and value == owned:
                old_links[role] = value
            if role != "desktop" or role in old_links:
                policy.reject("MISSING_RELOCATION_SHORTCUT", link_sources[role] is None)
                new_links[role] = verified_hash(self.files, link_sources[role], limit=LINK_LIMIT)
                link_payload[LINKS[role]] = new_links[role]
        new_exe = verified_hash(self.files, uninstaller)
        old_registry = registry_values()
        policy.reject("LEGACY_REGISTRATION_CHANGED", not applicable_registration(self.legacy.install, old_registry))
        saved = workspace / "snapshot"
        self.legacy.make_dir(saved)
        for member, sha in old_files.items():
            destination = saved / member
            make_directory(self.legacy, destination.parent)
            self.legacy.copy(self.legacy.install / member, destination, sha)
        self.legacy.copy(saved / "Uninstall.exe", workspace / "migration-legacy-remover.exe",
                         old_files["Uninstall.exe"])
        return {"schema": 1, "phase": "preparing", "target": self.catalogue.target.state.as_json(),
                "before": baseline.state.as_json(),
                "workspace": name, "volume": self.files.verify_mount(), "old_registry": old_registry,
                "old_owner": {key: sha for key, sha in old_files.items() if key in OWNER},
                "old_links": old_links, "new_links": new_links, "new_owner": {
                    "Uninstall.exe": new_exe, "uninstaller.copy": new_exe, **link_payload},
                "language": language}

    def read_journal(self):
        row = policy.parse_json(self.files.read(self.journal, 32768))
        required = {"schema", "phase", "target", "before", "workspace", "volume", "old_registry", "old_owner",
                    "old_links", "new_links", "new_owner", "language"}
        policy.reject("INVALID_RELOCATION_JOURNAL", not isinstance(row, dict) or set(row) != required
                      or type(row["schema"]) is not int or row["schema"] != 1 or not isinstance(row["workspace"], str)
                      or not re.fullmatch(r"relocate-[0-9a-f]{32}", row["workspace"])
                      or type(row["language"]) is not int or row["language"] not in (1033, 1041, 1042)
                      or row["phase"] not in ("preparing", "trial", "retiring", "cancelling")
                      or not valid_registry_shape(row["old_registry"])
                      or not applicable_registration(self.legacy.install, row["old_registry"]))
        for key, permitted in (("old_owner", OWNER), ("new_owner", OWNER),
                               ("old_links", LINKS), ("new_links", LINKS)):
            value = row[key]
            policy.reject("INVALID_RELOCATION_JOURNAL", not isinstance(value, dict)
                          or any(name not in permitted or not policy.valid_hash(sha) for name, sha in value.items()))
        before = self.catalogue.find(policy.State.from_json(row["before"]))
        policy.reject("RELOCATION_REQUIRES_SAME_SETUP", before is None or before.state.id != LEGACY_ID
                      or policy.State.from_json(row["target"]) != self.catalogue.target.state
                      or row["volume"] != self.files.verify_mount())
        policy.reject("INVALID_RELOCATION_JOURNAL", row["old_owner"].get("Uninstall.exe") not in LEGACY_REMOVERS
                      or row["old_owner"].get("Uninstall.exe") != row["old_owner"].get("uninstaller.copy")
                      or row["new_owner"].get("Uninstall.exe") != row["new_owner"].get("uninstaller.copy")
                      or not row["new_owner"].get("Uninstall.exe")
                      or set(row["new_links"]) not in ({"start", "guide"}, {"start", "guide", "desktop"})
                      or any(row["old_owner"].get(LINKS[role]) != digest for role, digest in row["old_links"].items())
                      or any(row["new_owner"].get(LINKS[role]) != digest for role, digest in row["new_links"].items()))
        return row, before

    def deploy(self, row, payload, uninstaller, source_links):
        install = self.files.install
        make_directory(self.files, install)
        scratch = self.files.allocate_transaction_workspace()
        for name, digest in self.catalogue.target.payload.items():
            copy_into_place(self.files, payload / name, install / name, digest, scratch)
        for name in ("Uninstall.exe", "uninstaller.copy"):
            copy_into_place(self.files, uninstaller, install / name, row["new_owner"][name], scratch)
        for role, digest in row["new_links"].items():
            copy_into_place(self.files, source_links[role], install / LINKS[role], digest, scratch)
        scratch.rmdir()
        self.verify_trial(row)
        self.files.health()


    def verify_trial(self, row):
        policy.reject("D_READER_HASH_MISMATCH", not self.updater.matches_release(self.catalogue.target))
        self.updater.check_unowned_loaders(self.catalogue.target)
        for name, sha in row["new_owner"].items():
            policy.reject("D_OWNERSHIP_MISMATCH", not self.files.matches(self.files.install / name, sha))

    def verify_legacy_unchanged(self, row, before):
        previous = self.baseline()
        policy.reject("LEGACY_BASELINE_CHANGED_BEFORE_RETIREMENT",
                      previous != before or registry_values() != row["old_registry"])
        for name, sha in row["old_owner"].items():
            policy.reject("LEGACY_OWNERSHIP_CHANGED", not self.legacy.matches(self.legacy.install / name, sha))
        for role in (set(row["old_links"]) | {"start", "guide"}):
            policy.reject("LEGACY_SHORTCUT_CHANGED", observed(self.legacy, self.links[role]) != row["old_links"].get(role))

    def verify_removed(self, row, before):
        policy.reject("LEGACY_REGISTRATION_NOT_REMOVED", registry_values() is not None)
        for name in (*before.payload, *row["old_owner"]):
            policy.reject("LEGACY_FILE_NOT_REMOVED", self.legacy.kind(self.legacy.install / name) is not None)
        for role in row["old_links"]:
            policy.reject("LEGACY_SHORTCUT_NOT_REMOVED", self.legacy.kind(self.links[role]) is not None)

    def register(self, row, workspace):
        for role, sha in row["new_links"].items():
            copy_into_place(self.legacy, self.files.install / LINKS[role], self.links[role], sha, workspace)
        policy.reject("REGISTRATION_COLLISION", registry_values() is not None)
        write_registry(registration(self.files.install, row["language"]))

    def verify_committed(self, row):
        expected = registration(self.files.install, row["language"])
        policy.reject("D_REGISTRATION_MISMATCH", registry_values() != expected)
        policy.reject("D_READER_HASH_MISMATCH", self.updater.observed_release() != self.catalogue.target)
        for role, sha in row["new_links"].items():
            policy.reject("D_SHORTCUT_MISMATCH", not self.legacy.matches(self.links[role], sha))

    def remove_expected(self, files, path, digest):
        if files.kind(path) is not None:
            with files.pinned(path.parent, directory=True):
                policy.reject("MIGRATION_EXTERNAL_FILE_CHANGE", not files.matches(path, digest))
                path.unlink()

    def rollback(self, row, before, workspace):
        self.check_interference()
        assert_remover_stopped(workspace / "migration-legacy-remover.exe")
        c_owned = {**before.payload, **row["old_owner"]}
        d_owned = {**self.catalogue.target.payload, **row["new_owner"]}
        saved = workspace / "snapshot"
        prove_expected_or_missing(self.legacy, {self.legacy.install / name: sha for name, sha in c_owned.items()})
        prove_expected_or_missing(self.files, {self.files.install / name: sha for name, sha in d_owned.items()})
        for name, digest in c_owned.items():
            policy.reject("LEGACY_BACKUP_HASH_MISMATCH", not self.legacy.matches(saved / name, digest))
        current = registry_values()
        expected = registration(self.files.install, row["language"])
        if current is not None:
            policy.reject("MIGRATION_EXTERNAL_REGISTRATION_CHANGE", current != row["old_registry"]
                          and any(value != expected.get(name) for name, value in current.items()))
        for role in set(row["old_links"]) | set(row["new_links"]):
            actual = observed(self.legacy, self.links[role])
            policy.reject("MIGRATION_EXTERNAL_SHORTCUT_CHANGE",
                          actual not in (None, row["old_links"].get(role), row["new_links"].get(role)))
        for name, digest in c_owned.items():
            destination = self.legacy.install / name
            if self.legacy.kind(destination) is None:
                copy_into_place(self.legacy, saved / name, destination, digest, workspace)
        for role, digest in row["new_links"].items():
            path = self.links[role]
            if observed(self.legacy, path) == digest:
                self.remove_expected(self.legacy, path, digest)
        for role, digest in row["old_links"].items():
            if self.legacy.kind(self.links[role]) is None:
                copy_into_place(self.legacy, saved / LINKS[role], self.links[role], digest, workspace)
        if current != row["old_registry"]:
            remove_registry()
            write_registry(row["old_registry"])
        policy.reject("LEGACY_ROLLBACK_VERIFICATION_FAILED", self.legacy_updater.observed_release() != before
                      or registry_values() != row["old_registry"])
        for role, digest in row["old_links"].items():
            policy.reject("LEGACY_SHORTCUT_ROLLBACK_FAILED", not self.legacy.matches(self.links[role], digest))
        for name, digest in reversed(tuple(d_owned.items())):
            self.remove_expected(self.files, self.files.install / name, digest)
        self.finish(row, "restored_c")

    def restore_after_failure(self, row, before, workspace):
        try:
            self.rollback(row, before, workspace)
        except (OSError, policy.Refusal, TransferError):
            raise policy.Refusal("RELOCATION_RECOVERY_REQUIRES_VERIFICATION", 5) from None

    def cancel_trial(self, row):
        # Before retirement this installer has no authority over C. A separate
        # official C update may have advanced its files and high-water.
        policy.reject("D_TRIAL_NOT_READY", row["phase"] != "trial")
        self.files.ensure_closed()
        policy.reject("C_REGISTRATION_REQUIRED_TO_CANCEL_TRIAL",
                      not applicable_registration(self.legacy.install, registry_values())
                      or not self.legacy.matches(self.legacy.install / "product.id", self.catalogue.target.payload["product.id"]))
        self.legacy.attest_owner()
        self.verify_trial(row)
        self.require_unregistered_trial(row)
        row["phase"] = "cancelling"
        self.files.write_record(self.journal, row)
        return self.finish_cancel(row)

    def require_unregistered_trial(self, row):
        policy.reject("C_REGISTRATION_REQUIRED_TO_CANCEL_TRIAL",
                      not applicable_registration(self.legacy.install, registry_values()))
        for role, sha in row["new_links"].items():
            policy.reject("D_TRIAL_ALREADY_HAS_MANAGED_LINKS", self.legacy.matches(self.links[role], sha))

    def finish_cancel(self, row):
        try:
            self.files.ensure_closed()
            self.require_unregistered_trial(row)
            expected = {**self.catalogue.target.payload, **row["new_owner"]}
            targets = {self.files.install / name: sha for name, sha in expected.items()}
            prove_expected_or_missing(self.files, targets)
            for path, sha in reversed(tuple(targets.items())):
                self.remove_expected(self.files, path, sha)
            self.finish(row, "trial_cancelled")
        except (OSError, policy.Refusal, TransferError):
            raise policy.Refusal("D_CANCELLATION_REQUIRES_VERIFICATION", 5) from None
        return "trial_cancelled"

    def finish(self, row, result):
        self.files.write_record(self.files.control / RECEIPT,
                                {"result": result, "before": row["before"], "target": row["target"],
                                 "backup": row["workspace"]})
        self.journal.unlink()

    def stage(self, payload, uninstaller, source_links, language):
        policy.reject("RELOCATION_ALREADY_PENDING", self.files.kind(self.journal) is not None)
        before = self.baseline()
        self.verify_dest_clear()
        self.updater.verify_staging(payload, self.catalogue.target.payload)
        name = "relocate-" + uuid.uuid4().hex
        workspace = self.files.control / name
        row = self.archive(name, before, uninstaller, source_links, language)
        self.files.write_record(self.journal, row)
        try:
            self.deploy(row, payload, uninstaller, source_links)
            self.verify_legacy_unchanged(row, before)
            row["phase"] = "trial"
            self.files.write_record(self.journal, row)
        except (OSError, policy.Refusal, TransferError):
            self.restore_after_failure(row, before, workspace)
            raise policy.Refusal("RELOCATION_RESTORED_C", 4) from None
        return "staged_for_trial"

    def commit(self, row, before, workspace):
        policy.reject("D_TRIAL_NOT_READY", row["phase"] != "trial")
        self.verify_trial(row)
        self.verify_legacy_unchanged(row, before)
        require_legacy_mutex_available()
        row["phase"] = "retiring"
        self.files.write_record(self.journal, row)
        # The stock remover acquires its NSIS mutex itself. This coordinator
        # retains the common update-engine lock until commit or rollback.
        try:
            with self.files.pinned(self.files.install, directory=True):
                retire_uninstaller(self.legacy, workspace / "migration-legacy-remover.exe", row["old_owner"]["Uninstall.exe"])
                self.check_interference()
                self.verify_removed(row, before)
                self.register(row, workspace)
                self.verify_committed(row)
                self.files.write_record(self.updater.state_path, self.catalogue.target.state.as_json())
                self.finish(row, "completed")
        except (OSError, policy.Refusal, TransferError):
            if self.updater.read_state() != before.state:
                raise policy.Refusal("RELOCATION_REQUIRES_VERIFICATION", 5) from None
            self.restore_after_failure(row, before, workspace)
            raise policy.Refusal("RELOCATION_RESTORED_C", 4) from None
        return "relocated"

    def run(self, operation, *, payload=None, uninstaller=None, source_links=None, language=None):
        with self.files.lock():
            if operation == "stage":
                return self.stage(payload, uninstaller, source_links, language)
            row, before = self.read_journal()
            workspace = self.files.control / row["workspace"]
            if operation == "cancel":
                return self.cancel_trial(row)
            if operation == "recover" and row["phase"] == "cancelling":
                return self.finish_cancel(row)
            state = self.updater.read_state()
            if operation == "recover" and row["phase"] == "retiring" and state == self.catalogue.target.state:
                self.verify_committed(row)
                self.finish(row, "completed")
                return "relocated"
            policy.reject("RELOCATION_HIGH_WATER_CHANGED", state != before.state)
            if operation == "commit":
                return self.commit(row, before, workspace)
            policy.reject("RELOCATION_RECOVERY_NOT_REQUIRED", operation != "recover" or row["phase"] == "trial")
            self.restore_after_failure(row, before, workspace)
            raise policy.Refusal("RELOCATION_RESTORED_C_RERUN_SETUP", 4)


def guard(catalogue, files):
    return Migration(catalogue, files).guard()


def migrate(catalogue, files, *, operation, payload, uninstaller, start_link, guide_link, desktop_link,
            installer_language):
    if operation == "stage":
        policy.reject("INVALID_INSTALLER_LANGUAGE", installer_language not in (1033, 1041, 1042))
    if operation == "stage" and getattr(sys, "frozen", False):
        stage = Path(sys.executable).parent
        expected = (stage / "payload", stage / "reader-uninstaller.generated",
                    stage / "reader-start.lnk", stage / "reader-guide.lnk", stage / "reader-desktop.lnk")
        policy.reject("UNAPPROVED_RELOCATION_STAGE", (payload, uninstaller, start_link, guide_link, desktop_link) != expected)
    links = {"start": start_link, "guide": guide_link, "desktop": desktop_link}
    return Migration(catalogue, files).run(operation, payload=payload, uninstaller=uninstaller,
                                           source_links=links, language=installer_language)

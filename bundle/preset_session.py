"""Remember one explicitly approved Preset image and connect to its local receiver."""
import os
import re
import time
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path

from bundle import preset_library as library
from bundle import transfer_client as client
from bundle import transfer_registry as registry
from bundle import preset_release as releases, preset_trust


# The PUBLIC release is an NSIS wrapper. Its Electron receiver is a different
# process and file, extracted into an ephemeral directory by the wrapper.
PUBLIC_PORTABLE = "e4d32d855e54bbb8f122719063134d5e86940b8fc9d03d995244dedc4c611a7d"
PUBLIC_RECEIVER = "e4eb5e73f169e30e554f694913dfa5821a0bd8a0f8f592d1c7db2137e8331b69"
PORTABLE_NAME = "chaessi preset.exe"
EXTRACTION = re.compile(r"ns[^\\/]*\.tmp", re.IGNORECASE)
APPROVED_IMAGES = frozenset((PUBLIC_PORTABLE,))
PROCESS_GONE = (6, 87, 1168)
# A clean Windows guest took over 40 seconds to unpack and publish PUBLIC 3.8.5.
STARTUP_SECONDS = 90


def _error(reason):
    code = "preset." + reason
    return client.TransferError(code, code=code, delivery_possible=False)


def _gone(error):
    return getattr(error, "winerror", None) in PROCESS_GONE


def _extracted(path):
    return (path.name.casefold() == PORTABLE_NAME and path.parent.name.casefold() == "app"
            and EXTRACTION.fullmatch(path.parent.parent.name) is not None)


def _temporary(path):
    if any(EXTRACTION.fullmatch(part) for part in path.parts):
        return True
    roots = [Path(os.environ[key]) for key in ("TEMP", "TMP") if os.environ.get(key)]
    roots.extend(Path(os.environ[key]) / "Temp" for key in ("LOCALAPPDATA", "WINDIR") if os.environ.get(key))
    return any(root.is_absolute() and path.is_relative_to(root) for root in roots)


def _eligible(record):
    return record.digest in APPROVED_IMAGES and not _temporary(record.path)


def _lineage(processes, pid):
    """Walk snapshot creator IDs. Handle times are checked before trusting any link."""
    seen = {pid}
    while pid in processes and len(seen) <= 8:
        parent, _ = processes[pid]
        if not parent or parent in seen:
            return
        seen.add(parent)
        yield parent
        pid = parent


def _running(processes, chosen_path):
    owners = {}
    for pid, (_, basename) in processes.items():
        if basename.casefold() != chosen_path.name.casefold():
            continue
        try:
            with registry._process(pid) as (image, created, verify):
                if image == chosen_path and image.samefile(chosen_path):
                    verify()
                    owners[pid] = created
        except OSError as exc:
            if not _gone(exc):
                raise _error("unavailable") from None
        except client.TransferError:
            # Native process lookup also rejects a process that exited mid-snapshot.
            continue
    # Electron runs its renderer, GPU and local server from the same EXE. Only
    # an ancestor outside that same-image group can be the selected launcher.
    def has_older_owner(pid):
        chain = list(_lineage(processes, pid))
        if not any(parent in owners for parent in chain):
            return False
        child_created = owners[pid]
        for parent in chain:
            try:
                with registry._process(parent) as (_, stamp, verify):
                    verify()
                    if stamp >= child_created:
                        return False
                    if parent in owners:
                        return stamp == owners[parent]
                    child_created = stamp
            except (OSError, client.TransferError):
                return False
        return False

    roots = {pid: created for pid, created in owners.items() if not has_older_owner(pid)}
    if len(roots) > 1:
        raise _error("ambiguous")
    return next(iter(roots.items()), None)


def _other_portable_running(processes, deadline):
    """An unattached official receiver may be from a different or retired wrapper."""
    checked = set()
    for pid, (_, basename) in processes.items():
        if basename.casefold() != PORTABLE_NAME:
            continue
        registry.remaining_time(deadline)
        try:
            with registry._process(pid) as (image, _, verify):
                if not _extracted(image) or image in checked:
                    continue
                with registry.checked_handle(image, read=True) as pinned:
                    if registry._digest(pinned, deadline=deadline) == PUBLIC_RECEIVER:
                        verify()
                        return True
                    checked.add(image)
        except OSError as exc:
            if not _gone(exc):
                raise _error("unavailable") from None
        except client.TransferError as exc:
            if exc.code == "TIMEOUT":
                raise
    return False


@contextmanager
def _selected_file(record, *, deadline=None):
    if not _eligible(record):
        raise _error("temporary" if _temporary(record.path) else "unsupported_image")
    with ExitStack() as stack:
        try:
            path = stack.enter_context(registry.checked_handle(record.path, read=True))
            digest = registry._digest(path, deadline=deadline)
        except FileNotFoundError:
            raise _error("missing") from None
        except OSError:
            raise _error("unavailable") from None
        except client.TransferError as exc:
            if exc.code == "TIMEOUT":
                raise
            raise _error("unavailable") from None
        if digest != record.digest:
            raise _error("changed")
        yield path


@contextmanager
def _bound(endpoint, processes, launcher, path, *, portable):
    """Pin the exact receiver and a strictly older, selected launcher process."""
    launcher_pid, launcher_created = launcher
    if portable:
        if endpoint.sha256 != PUBLIC_RECEIVER or not _extracted(Path(endpoint.exe)):
            raise _error("unverified")
        parents = list(_lineage(processes, endpoint.pid))
        if launcher_pid not in parents:
            raise _error("unverified")
        chain = [endpoint.pid, *parents[:parents.index(launcher_pid) + 1]]
    else:
        if endpoint.pid != launcher_pid or endpoint.sha256 != library.KNOWN_PRIVATE:
            raise _error("unverified")
        chain = [endpoint.pid]

    with ExitStack() as stack:
        verified = []
        last = None
        try:
            for pid in chain:
                exe, created, verify = stack.enter_context(registry._process(pid))
                if last is None and (created != endpoint.created or exe != Path(endpoint.exe)
                                     or not exe.samefile(endpoint.exe)):
                    raise _error("unverified")
                if last is not None and created >= last:
                    raise _error("unverified")
                if pid == launcher_pid and (created != launcher_created or exe != path or not exe.samefile(path)):
                    raise _error("unverified")
                last = created
                verified.append(verify)
        except (OSError, client.TransferError):
            raise _error("unverified") from None
        yield
        try:
            for verify in verified:
                verify()
        except (OSError, client.TransferError):
            raise _error("unverified") from None


class PresetSession:
    """Single chosen file, one bounded startup per connection, and no queued writes."""

    def __init__(self, root=None, legacy_root=None, *, publisher_roots=None):
        self.store = library.PresetLibrary(root, legacy_root)
        self.publisher_roots = preset_trust.ROOTS if publisher_roots is None else publisher_roots
        self.release_store = releases.ReleaseStore(self.store.root / "release-trust" / preset_trust.REALM)

    def _release(self, path):
        try:
            # Initialize the parent as the library's protected root first.
            # Creating the nested release store first would create this root
            # as a generic intermediate directory with inherited permissions.
            self.store._ensure_root()
            with registry.checked_handle(self.store.root, root=self.store.root, directory=True):
                return releases.inspect_release(path, self.publisher_roots, store=self.release_store)
        except releases.ReleaseError as exc:
            code = {
                "SIGNATURE_EXPIRED": "signature_expired", "SIGNATURE_REVOKED": "signature_revoked",
                "SIGNATURE_ROLLBACK": "signature_rollback", "RUNTIME_MISMATCH": "runtime_mismatch",
            }.get(exc.code, "signature_invalid")
            raise _error(code) from None

    def _eligible_choice(self, record):
        if _temporary(record.path):
            return False
        return self._release(record.path) is not None or _eligible(record)

    @contextmanager
    def _selection(self, record, *, deadline=None):
        release = self._release(record.path)
        if release is None:
            with _selected_file(record, deadline=deadline) as path:
                yield record, path, None
            return
        with registry.checked_handle(record.path, read=True) as path:
            if registry._digest(path, deadline=deadline) != release.launcher_digest:
                raise _error("runtime_mismatch")
            with ExitStack() as stack:
                if release.layout == "unpacked":
                    relative = Path(release.launcher_file.path)
                    root = path.parents[len(relative.parts) - 1]
                    try:
                        stack.enter_context(release.pin_tree(root))
                    except releases.ReleaseError:
                        raise _error("runtime_mismatch") from None
                yield replace(record, digest=release.launcher_digest), path, release

    @contextmanager
    def _signed_bound(self, endpoint, launcher, path, release):
        """Hold package bytes and process identities throughout each signed exchange."""
        processes = registry.process_snapshot()
        pid, created = launcher
        actual = _running(processes, path)
        if actual != launcher:
            raise _error("unverified")
        receiver = Path(endpoint.exe)
        relative = Path(release.receiver)
        if tuple(part.casefold() for part in receiver.parts[-len(relative.parts):]) != tuple(
                part.casefold() for part in relative.parts):
            raise _error("runtime_mismatch")
        root = receiver.parents[len(relative.parts) - 1]
        if release.layout == "unpacked":
            if endpoint.pid != pid or receiver != path:
                raise _error("unverified")
            chain = [pid]
        else:
            parents = list(_lineage(processes, endpoint.pid))
            if pid not in parents:
                raise _error("unverified")
            chain = [endpoint.pid, *parents[:parents.index(pid) + 1]]
        try:
            with ExitStack() as stack:
                recheck = stack.enter_context(release.pin_tree(root))
                last = None
                checks = []
                for current in chain:
                    image, stamp, check = stack.enter_context(registry._process(current))
                    if last is None and (stamp != endpoint.created or image != receiver):
                        raise _error("unverified")
                    if last is not None and stamp >= last:
                        raise _error("unverified")
                    if current == pid and (stamp != created or image != path):
                        raise _error("unverified")
                    checks.append(check)
                    last = stamp
                yield recheck
                for check in checks:
                    check()
        except releases.ReleaseError:
            raise _error("runtime_mismatch") from None

    def _signed_endpoint(self, endpoint, launcher, path, release):
        def alive():
            # This local UI heartbeat sends no credentials or requests. Full
            # package pins still run before every authenticated operation.
            try:
                with registry._process(launcher[0]) as (image, stamp, verify):
                    if image != path or stamp != launcher[1]:
                        raise _error("unverified")
                    with registry._process(endpoint.pid, endpoint.hwnd) as (receiver, created, check):
                        if receiver != Path(endpoint.exe) or created != endpoint.created:
                            raise _error("unverified")
                        verify()
                        check()
            except OSError:
                raise _error("not_running") from None

        def guard():
            @contextmanager
            def verify():
                current = self._release(path)
                if current is None or current.metadata != release.metadata:
                    raise _error("changed")
                with registry.checked_handle(path, read=True), self._signed_bound(endpoint, launcher, path, current) as recheck:
                    yield recheck
            return verify()
        return replace(endpoint, transport_guard=guard, liveness_check=alive)

    @contextmanager
    def _exclusive(self):
        try:
            with library._store_lock(self.store.root / "preset-session"):
                yield
        except library.LibraryError as exc:
            raise _error("busy" if exc.code == "LIBRARY_BUSY" else "unavailable") from None
        except OSError:
            raise _error("unavailable") from None

    def configured(self):
        try:
            return self.store.load_default(self._eligible_choice)
        except (OSError, client.TransferError) as exc:
            if isinstance(exc, client.TransferError) and str(exc.code).startswith("preset."):
                raise
            raise _error("busy" if getattr(exc, "code", None) == "LIBRARY_BUSY" else "unavailable") from None

    def inspect(self, path):
        try:
            path = registry.local_path(path)
            if _temporary(path):
                raise _error("temporary")
            info = library.inspect_exe(path)
        except FileNotFoundError:
            raise _error("missing") from None
        except OSError:
            raise _error("unavailable") from None
        except client.TransferError as exc:
            if exc.code == "preset.temporary":
                raise
            raise _error("unsupported_image") from None
        if not self._eligible_choice(info):
            raise _error("unsupported_image")
        return info

    def configure(self, info):
        """Save a choice the UI has already confirmed; recheck it before writing."""
        with self._exclusive(), self._selection(info) as (current, _, _):
            return self.store.select_default(current)

    def _record(self):
        record = self.configured()
        if record is None:
            raise _error("select_required")
        return record

    def refresh(self, endpoint):
        """Reauthenticate one endpoint and fetch its latest slots without a launch."""
        with self._exclusive():
            record = self._record()
            with self._selection(record) as (record, path, release):
                processes = registry.process_snapshot()
                launcher = _running(processes, path)
                if launcher is None:
                    raise _error("not_running")
                if release is not None:
                    signed = self._signed_endpoint(endpoint, launcher, path, release)
                    data = client.targets(signed)
                    release.commit_authenticated(self.release_store)
                    return signed, data, record
                with _bound(endpoint, processes, launcher, path, portable=record.digest == PUBLIC_PORTABLE):
                    return endpoint, client.targets(endpoint), record

    def connect(self, *, allow_launch=True, timeout=STARTUP_SECONDS):
        """Find the authenticated receiver for the choice, or start that choice once."""
        with self._exclusive():
            record = self._record()
            deadline = time.monotonic() + timeout
            try:
                with self._selection(record, deadline=deadline) as (record, path, release):
                    endpoint, data = self._connect(record, path, deadline, allow_launch, release=release)
                    if release is not None:
                        release.commit_authenticated(self.release_store)
            except client.TransferError as exc:
                if exc.code == "TIMEOUT":
                    raise _error("no_receiver") from None
                raise
            return endpoint, data, record

    def _connect(self, record, path, deadline, allow_launch, *, release=None):
        portable = record.digest == PUBLIC_PORTABLE or (release is not None and release.layout == "portable")
        started = None
        observed = False
        failure = "no_receiver"
        while time.monotonic() < deadline:
            processes = registry.process_snapshot()
            launcher = _running(processes, path)
            if launcher is not None:
                observed = True
                if started is not None and started.pid != launcher[0]:
                    raise _error("ambiguous")
                match = self._receiver(processes, launcher, path, portable, deadline, release=release)
                if match is not None:
                    endpoint, data = match
                    if data is not None:
                        return endpoint, data
                    failure = "unverified"
            elif not observed and started is None:
                if portable and _other_portable_running(processes, deadline):
                    raise _error("ambiguous")
                if not allow_launch:
                    raise _error("not_running")
                started = registry.launch(path, record.digest, confirmed=True)
            elif (started is None or started.poll() is not None) and observed:
                break
            if not allow_launch or (started is not None and started.poll() is not None):
                break
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        raise _error(failure)

    def _receiver(self, processes, launcher, path, portable, deadline, *, release=None):
        owner, _ = launcher
        if portable:
            pids = {pid for pid, (_, name) in processes.items()
                    if (release is not None or name.casefold() == PORTABLE_NAME) and owner in _lineage(processes, pid)}
        else:
            pids = {owner}
        if not pids:
            return None
        eligible = []
        guard_factory = (lambda endpoint: self._signed_bound(endpoint, launcher, path, release)) if release else None
        discovered = (registry.discover_instances(deadline, pids=pids, guard_factory=guard_factory)
                      if release else registry.discover_instances(deadline, pids=pids))
        for endpoint in discovered:
            if release is not None:
                eligible.append(endpoint)
                continue
            try:
                binding = (self._signed_bound(endpoint, launcher, path, release) if release is not None else
                           _bound(endpoint, processes, launcher, path, portable=portable))
                with binding:
                    eligible.append(endpoint)
            except client.TransferError:
                continue
        if len(eligible) > 1:
            raise _error("ambiguous")
        if not eligible:
            return None
        endpoint = eligible[0]
        if release is not None:
            endpoint = self._signed_endpoint(endpoint, launcher, path, release)
        if endpoint.compatibility == "unsupported":
            raise _error("unsupported")
        if endpoint.compatibility != "compatible":
            return endpoint, None
        try:
            binding = (ExitStack() if release is not None else
                       _bound(endpoint, processes, launcher, path, portable=portable))
            with binding:
                data = client.targets(endpoint)
        except client.TransferError as exc:
            # The same process may publish a replacement instance while rendering
            # starts. Only this read is retried by the bounded startup search.
            # Package policy failures are definitive, not transient startup state.
            if str(exc.code).startswith("preset."):
                raise
            return endpoint, None
        return endpoint, data

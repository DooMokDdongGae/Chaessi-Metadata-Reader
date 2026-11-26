"""Match an explicit Reader choice to one authenticated Preset process."""
import time
from pathlib import Path

from bundle import preset_library as library
from bundle import transfer_client as client
from bundle import transfer_registry as registry


def same_image(endpoint, record):
    return Path(endpoint.exe) == record.path and endpoint.sha256 == record.digest


def open_running(endpoint, records, store, record=None):
    if endpoint.compatibility != "compatible":
        raise client.TransferError("preset." + endpoint.compatibility)
    path = Path(endpoint.exe)
    if record is None:
        record = next((item for item in records if item.path == path), None)
    if record is not None and not same_image(endpoint, record):
        raise client.TransferError("preset.changed")
    info = None
    if record is None:
        info = library.inspect_exe(path)
        if info.digest != endpoint.sha256:
            raise client.TransferError("preset.changed")
        if not info.recognized:
            raise client.TransferError("preset.register_first")
    digest = record.digest if record else endpoint.sha256
    selected_path = record.path if record else path
    verified = registry.attest(endpoint, path=selected_path, sha256=digest)
    data = client.targets(verified)
    if record is None:
        record = store.register(info)
    record = store.connected(record.id, selected_path, digest)
    return verified, data, record


def existing_for(record, endpoints):
    """Only a selection of a registered executable may resolve by image."""
    same_path = [ep for ep in endpoints if Path(ep.exe) == record.path]
    if any(ep.sha256 != record.digest for ep in same_path):
        raise client.TransferError("preset.changed")
    return same_path


def launch_and_wait(record, timeout=30):
    process = registry.launch(record.path, record.digest, confirmed=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise client.TransferError("preset.no_receiver")
        for endpoint in registry.discover_instances(deadline, pid=process.pid):
            if endpoint.pid != process.pid or not same_image(endpoint, record):
                continue
            if endpoint.compatibility == "unsupported":
                raise client.TransferError("preset.unsupported")
            if endpoint.compatibility == "compatible" and process.poll() is None:
                return registry.attest(endpoint, path=record.path, sha256=record.digest)
        time.sleep(.25)
    raise client.TransferError("preset.no_receiver")

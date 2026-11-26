"""Inspect the frozen code, runtime origins and actual NSIS solid archive without installing it."""
import ast
import hashlib
import json
import marshal
import runpy
from pathlib import Path
import struct
import sys
from types import CodeType
import zipfile
import zlib

from PyInstaller.archive.readers import CArchiveReader


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_private_strings(data, label):
    for prefix in ("E:/CHAESSI_STUDIO/", "D:/AI/CodexApps/", str(Path.home()).replace("\\", "/") + "/"):
        for form in (prefix, prefix.replace("/", "\\")):
            if any(form.lower().encode(enc) in data.lower() for enc in ("utf-8", "utf-16-le")):
                raise ValueError(f"Development path in {label}")


def inspect_code(code, label):
    if not isinstance(code, CodeType):
        return
    if Path(code.co_filename).is_absolute():
        raise ValueError(f"Absolute frozen source location: {label}")
    check_private_strings(marshal.dumps(code), label)


def native_source(source, data):
    source = Path(source).resolve()
    runtime = Path(sys.base_prefix).resolve()
    if source.read_bytes() != data:
        raise ValueError("Native runtime does not match reviewed input")
    if source.is_relative_to(runtime):
        return {"psf_source": source.relative_to(runtime).as_posix(), "sha256": sha(data)}
    sdk = runpy.run_path(str(Path(__file__).with_name("sdk_inputs.py")))
    provenance = sdk["native_provenance"](source)
    if provenance is None:
        raise ValueError("Unapproved native runtime origin")
    return provenance


def inspect_runtime(work, payload, files):
    runtime = Path(sys.base_prefix).resolve()
    sdk = runpy.run_path(str(Path(__file__).with_name("sdk_inputs.py")))
    sdk["verify_sdk_inputs"]()
    toc = ast.literal_eval((work / "analysis" / "reader" / "Analysis-00.toc").read_text("utf-8"))
    inputs = {}
    for group in toc:
        if isinstance(group, list):
            for item in group:
                if isinstance(item, tuple) and len(item) == 3 and item[2] in ("BINARY", "EXTENSION"):
                    inputs[Path(item[0]).as_posix().lower()] = Path(item[1])
    binaries = {}
    for rel in files:
        data = (payload / rel).read_bytes()
        check_private_strings(data, str(rel))
        if rel.suffix.lower() in (".py", ".pyw", ".pdb", ".env", ".map"):
            raise ValueError(f"Development file in application payload: {rel}")
        if rel.parts[0] != "_internal" or rel.suffix.lower() not in (".dll", ".pyd", ".exe"):
            continue
        name = Path(*rel.parts[1:]).as_posix().lower()
        source = inputs[name].resolve()
        binaries[rel.as_posix()] = native_source(source, data)
    with zipfile.ZipFile(payload / "_internal" / "base_library.zip") as stdlib:
        for name in stdlib.namelist():
            inspect_code(marshal.loads(stdlib.read(name)[16:]), name)
    exe = CArchiveReader(str(payload / "ChaessiMetadataReader.exe"))
    pyz = exe.open_embedded_archive("PYZ.pyz")
    for name in exe.toc:
        if name != "PYZ.pyz":
            inspect_code(marshal.loads(exe.extract(name)), name)
    for name in pyz.toc:
        inspect_code(pyz.extract(name), name)
    return binaries


def installer_blocks(data):
    signature = b"\xef\xbe\xad\xdeNullsoftInst"
    start = data.index(signature) - 4
    header_size, archive_size = struct.unpack_from("<II", data, start + 20)
    expected_crc = struct.unpack_from("<I", data, len(data) - 4)[0]
    if start % 512 or start + archive_size != len(data) or zlib.crc32(data[512:-4]) != expected_crc:
        raise ValueError("Invalid NSIS archive length or CRC")
    inflater = zlib.decompressobj(-15)
    plain = inflater.decompress(data[start + 28:-4], 256 * 1024 * 1024)
    if not inflater.eof or inflater.unused_data:
        raise ValueError("Invalid zlib-solid installer stream")
    position = 0
    blocks = []
    while position < len(plain):
        length = struct.unpack_from("<I", plain, position)[0]
        position += 4
        if position + length > len(plain):
            raise ValueError("Invalid installer data block")
        blocks.append(plain[position:position + length])
        position += length
    if len(blocks[0]) != header_size:
        raise ValueError("Invalid installer header size")
    return blocks


def inspect_installer(executable, expected, nsis, *, bootstrap=None, uninstaller=True):
    blocks = installer_blocks(executable.read_bytes())
    check_private_strings(blocks[0], "installer file table")
    packed = {sha(block) for block in blocks[1:]}
    wanted = set(expected.values()) | set((bootstrap or {}).values())
    if not wanted <= packed:
        raise ValueError("Frozen payload file missing from the compiled installer")
    components = ["Contrib/Graphics/Wizard/win.bmp",
                  *("Plugins/x86-unicode/" + name for name in ("nsDialogs.dll", "System.dll", "LangDLL.dll"))]
    compiler_files = {name: sha((nsis / name).read_bytes()) for name in components}
    if not set(compiler_files.values()) <= packed:
        raise ValueError("Unexpected installer plugin or UI resource")
    extras = [b for b in blocks[1:] if sha(b) not in wanted | set(compiler_files.values())]
    # NSIS writes the uninstaller icon patch followed by its format-specific
    # first header (flags=FH_FLAGS_UNINSTALL) and compressed instruction data.
    if uninstaller:
        if len(extras) != 2 or extras[1][:20] != b"\x01\0\0\0\xef\xbe\xad\xdeNullsoftInst":
            raise ValueError("Unexpected non-payload item in the compiled installer")
    elif extras:
        raise ValueError("Unexpected non-payload item in the compiled patch")
    return {"payload_unique_sha256_count": len(set(expected.values())), "solid_blocks": len(blocks),
            "nsis_resources": compiler_files, "bootstrap": bootstrap or {},
            "uninstaller_block_sha256": sha(extras[1]) if uninstaller else None}


def audit(work, payload, files, setup, nsis, *, bootstrap=None):
    expected = {f.as_posix(): sha((payload / f).read_bytes()) for f in files}
    report = {"native_inputs": inspect_runtime(work, payload, files),
              "setup": inspect_installer(setup, expected, nsis, bootstrap=bootstrap)}
    (work / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return expected

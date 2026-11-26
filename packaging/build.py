"""Build one x64 Reader candidate in a new private working directory outside the checkout."""
import argparse
import ast
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXT_SOURCE = ROOT / "chrome_bridge" / "extension"
DOCS = ROOT / "release-docs"
APP = "ChaessiMetadataReader"
SETUP = "Chaessi-Metadata-Reader-Setup-x64.exe"
ZIP = "Chaessi-Metadata-Reader-Chrome-Extension.zip"
MARKER = "chaessi-metadata-reader-{328AA667-9BAC-42AA-8124-525AD9EB95D2}"
LICENSES = ("BLAKE2", "CC0", "HACL", "NSIS", "OPENSSL", "PYINSTALLER",
            "PYTHON-ACKNOWLEDGEMENTS", "PYTHON-WINDOWS", "TCL-LIBTOMMATH",
            "TCL-REGEX", "TCL", "TK", "UNICODE", "XZ", "ZLIB",
            "CRYPTOGRAPHY", "CRYPTOGRAPHY-APACHE", "CRYPTOGRAPHY-BSD", "CFFI", "PYCPARSER")
READER_TEXT_ASSETS = ("bookmark.html", "collect.js", "page-reader.js")
RUNTIME_LICENSES = {
    "licenses/PYTHON-WINDOWS.txt": ("LICENSE.txt", "62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120"),
    "licenses/TK.txt": ("tcl/tk8.6/license.terms", "0d1e4405f6273f091732764ed89b57066be63ce64869be6c71ea337dc4f2f9b5"),
}
EXT_FILES = (
    "manifest.json", "open.js", "auto-worker.js", "bridge.js", "inspect.js",
    "collector.js", "connect.html", "connect.css", "connect.js",
)
NSIS_SHA256 = "f2b2b7726ac0d4e720dff52bfca11a5518d550fc75ed34a48dc47921527293f0"
NSIS_INPUTS = {
    "Bin/makensis.exe": "e277b7378931b74392015f5ad6b1d744dcd8a347baa4480350a75ebeab8d8e3d",
    "Stubs/zlib_solid-x86-unicode": "5e2dd27e22064762668c62dafdbe569452c3f6c7d8ca565514a357c7524d65d2",
    "Plugins/x86-unicode/nsDialogs.dll": "1e40211af65923c2f4fd02ce021458a7745d28e2f383835e3015e96575632172",
    "Plugins/x86-unicode/System.dll": "3eb38ae99653a7dbc724132ee240f6e5c4af4bfe7c01d31d23faf373f9f2eaca",
    "Plugins/x86-unicode/LangDLL.dll": "6f14c8f01f50a30743dac68c5ac813451463dfb427eb4e35fcdfe2410e1a913b",
    "Contrib/Graphics/Wizard/win.bmp": "3ad2dc318056d0a2024af1804ea741146cfc18cc404649a44610cbf8b2056cf2",
}


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def source_snapshot():
    excluded = {".git", "__pycache__", ".local", "handoff", ".pytest_cache"}
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(ROOT.rglob("*"))
            if p.is_file() and not excluded.intersection(p.relative_to(ROOT).parts)
            and p.suffix.lower() not in (".pyc", ".pyo")}


def check_source_snapshot(work):
    saved = json.loads((work / "source-at-freeze.json").read_bytes())
    if source_snapshot() != saved:
        raise ValueError("Source changed after the candidate freeze; preserve it and build a fresh candidate")


def extension(work):
    stage = work / "extension"
    stage.mkdir()
    # Use the reviewed generator, directing its atomic output into the fresh stage.
    generate = runpy.run_path(str(EXT_SOURCE / "prepare.py"))["build"]
    generate.__globals__.update(DIRECTORY=stage, OUTPUT=stage / "collector.js")
    generate()
    for name in EXT_FILES:
        if name != "collector.js":
            (stage / name).write_bytes((EXT_SOURCE / name).read_bytes().replace(b"\r\n", b"\n"))
    manifest = json.loads((stage / "manifest.json").read_bytes())
    if manifest["manifest_version"] != 3 or manifest["version"] != "0.3.1":
        raise ValueError("Review the extension manifest and compatibility pin")
    output = work / "release" / ZIP
    with zipfile.ZipFile(output, "x") as archive:
        for name in sorted(EXT_FILES):
            info = zipfile.ZipInfo(name, (2026, 11, 22, 0, 0, 0))
            info.create_system = 0
            info.external_attr = 0x20
            archive.writestr(info, (stage / name).read_bytes(), zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() or archive.namelist() != sorted(EXT_FILES):
            raise ValueError("Invalid extension ZIP")
        for name in EXT_FILES:
            if archive.read(name) != (stage / name).read_bytes():
                raise ValueError("Unexpected extension ZIP member")


def freeze_environment(work):
    if (sys.version_info[:3] != (3, 13, 17) or sys.maxsize <= 2**32
            or sys.prefix == sys.base_prefix or importlib.metadata.version("pyinstaller") != "6.22.3"):
        raise ValueError("Use the pinned x64 CPython/PyInstaller build environment")
    runtime = Path(sys.base_prefix)
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    env = dict(os.environ, PATH=os.pathsep.join(str(p) for p in (runtime, runtime / "DLLs", system32)),
               PYINSTALLER_CONFIG_DIR=str(work / "cache"), PYTHONHASHSEED="0",
               SOURCE_DATE_EPOCH="1795305600", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    for name in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(name, None)
    return env


def public_trust():
    trust = runpy.run_path(str(ROOT / "bundle" / "preset_trust.py"))
    roots = trust.get("ROOTS")
    retired_development = {
        "90bc06e2edfeeca5a5e7215e642d73b5e544dcf5f3e9814801534520e8a5addd",
        "780431c63166b0c10a87eb4a38a7d44a0fbf6a417cb3a6b7c4ebbad23765931a",
        "ad971a88043c83ac46ba4e4227cd061c80d10305b6b8df5706f6480f16bfb47e",
        "b84b42f3df74a70acddb50e7a56fc7008bc2106674c620de64f5084300678a59",
    }
    if (trust.get("CHANNEL") != "public" or trust.get("REALM") != "public-production"
            or not isinstance(roots, dict) or len(roots) != 1
            or retired_development.intersection(roots)
            or any(not isinstance(key, bytes) or len(key) != 32 or hashlib.sha256(key).hexdigest() != key_id
                   for key_id, key in roots.items())):
        raise ValueError("Pin the reviewed production public trust before building a release")
    return {"channel": "public", "realm": "public-production", "root_sha256": sorted(roots)}


def freeze(work):
    public_trust()
    env = freeze_environment(work)
    work.mkdir(exist_ok=False, parents=True)
    (work / "release").mkdir()
    (work / "source-at-freeze.json").write_text(json.dumps(source_snapshot(), sort_keys=True, indent=2), encoding="utf-8")
    extension(work)
    subprocess.run([sys.executable, "-B", "-s", "-m", "PyInstaller", "--distpath", str(work / "dist"),
                    "--workpath", str(work / "analysis"), str(ROOT / "packaging" / "reader.spec")],
                   cwd=ROOT, check=True, env=env)
    payload = work / "dist" / APP
    for name in READER_TEXT_ASSETS:
        # Keep the published text bytes independent of checkout line endings.
        asset = payload / "_internal" / "bundle" / name
        asset.write_bytes(asset.read_bytes().replace(b"\r\n", b"\n"))
    image = payload / (APP + ".exe")
    with image.open("rb") as stream:
        stream.seek(60)
        stream.seek(struct.unpack("<I", stream.read(4))[0])
        if stream.read(6) != b"PE\0\0\x64\x86":
            raise ValueError("The frozen application is not x64")
    check_source_snapshot(work)


def safe_files(directory):
    files = []
    for path in sorted(directory.rglob("*")):
        if path.lstat().st_file_attributes & 0x400:
            raise ValueError("Reparse point in release input")
        if path.is_file():
            rel = path.relative_to(directory)
            if not all(re.fullmatch(r"[\w .()+@,#=-]+", part) for part in rel.parts):
                raise ValueError(f"Unsupported release filename: {rel}")
            files.append(rel)
    return files


def public_docs(payload):
    import markdown

    docs = ["THIRD-PARTY-NOTICES.md"]
    for lang in ("ko", "en", "ja"):
        docs.extend([f"README.{lang}.md", f"RELEASE-NOTES.{lang}.md"])
    docs.extend(f"licenses/{name}.txt" for name in LICENSES)
    docs.extend(("licenses/CRYPTOGRAPHY-sbom.json", "licenses/CRYPTOGRAPHY-cryptography-rust.cyclonedx.json"))
    if (payload / "docs").exists():
        raise ValueError("Package a fresh freeze to avoid stale notices or guides")
    for name in docs:
        source = DOCS / name
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"Missing release document: {name}")
        dest = payload / "docs" / name
        dest.parent.mkdir(exist_ok=True, parents=True)
        data = source.read_bytes().replace(b"\r\n", b"\n")
        if name in RUNTIME_LICENSES:
            # Preserve the original vendor line endings and verify that the
            # checkout contains the same terms.
            source_name, source_hash = RUNTIME_LICENSES[name]
            terms = Path(sys.base_prefix) / source_name
            original = terms.read_bytes()
            if (hashlib.sha256(original).hexdigest() != source_hash
                    or original.replace(b"\r\n", b"\n") != data):
                raise ValueError(f"The vendor license is not the reviewed text: {name}")
            data = original
        dest.write_bytes(data)
        if dest.suffix == ".md":
            original = source.read_text("utf-8")
            body = markdown.markdown(original, extensions=["tables"])
            body = re.sub(r'href="([\w.-]+)\.md(#[\w-]+)?"', r'href="\1.html\2"', body)
            lang = next((code for code in ("ko", "en", "ja") if dest.name.endswith(f".{code}.md")), "en")
            title = html.escape(original.splitlines()[0].lstrip("# "))
            # File links and text work offline. CSP prohibits script and remote page assets.
            page = (f'<!doctype html><html lang="{lang}"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
                    f'<title>{title}</title><style>body{{font:1rem/1.65 system-ui,sans-serif;'
                    'max-width:52rem;margin:auto;padding:2rem;color:#222;background:#fff}'
                    'li{margin:.5rem 0}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.5rem}'
                    'a{color:#493b9b}code{overflow-wrap:anywhere}</style><main>' + body + '</main></html>')
            dest.with_suffix(".html").write_text(page, encoding="utf-8", newline="\n")


def nsis_lists(work, files):
    # Pin ancestors before any file operations. Missing directories are created
    # only by the installer. All removal operations name individual shipped files.
    dirs = sorted({d for f in files for d in f.parents if d.parts}, key=lambda d: (len(d.parts), str(d)))
    by_directory = {d: [] for d in [Path("."), *dirs]}
    for file in files:
        by_directory[file.parent].append(file)
    lines = []
    for mode in ("Install", "Remove", "Update"):
        lines.append(f"!macro {mode}PayloadDirs")
        for directory in dirs:
            lines.append(f'  !insertmacro {mode}Dir "$INSTDIR\\{directory}"')
        lines.append("!macroend")
    lines.append("!macro InstallFiles")
    for directory, members in by_directory.items():
        if members:
            path = "$INSTDIR" if not directory.parts else f"$INSTDIR\\{directory}"
            lines.append(f'  SetOutPath "{path}"')
            for member in members:
                lines.append(f'  !insertmacro InstallFile "{member}"')
    lines.append("!macroend")
    lines.append("!macro StageFiles")
    for directory, members in by_directory.items():
        if members:
            path = "$PLUGINSDIR\\payload" + (f"\\{directory}" if directory.parts else "")
            lines.append(f'  SetOutPath "{path}"')
            for member in members:
                lines.extend(("  ClearErrors", f'  File "${{PAYLOAD}}\\{member}"',
                              "  IfErrors 0 +4", "  !insertmacro Stop"))
    lines.append("!macroend")
    lines.append("!macro RemoveFiles")
    for directory, members in by_directory.items():
        if not members:
            continue
        path = "$INSTDIR" if not directory.parts else f"$INSTDIR\\{directory}"
        lines.extend([f'  ${{If}} ${{FileExists}} "{path}\\."', f'  StrCpy $GuardPath "{path}"',
                      "  Call un.PinChain"])
        lines.extend(f'  Delete "$INSTDIR\\{f}"' for f in members)
        lines.append('  ${EndIf}')
    lines.append("!macroend")
    lines.append("!macro CheckFiles PREFIX")
    receipts = ["Uninstall.exe", "uninstaller.copy", "guide-link.copy", "start-link.copy", "desktop-link.copy"]
    for f in [*files, *receipts]:
        lines.extend([f'  StrCpy $R0 "$INSTDIR\\{f}"', '  Call ${PREFIX}CheckFile'])
    lines.append("!macroend")
    lines.append("!macro RemoveEmptyDirs")
    lines.extend(f'  !insertmacro RemoveEmpty "$INSTDIR\\{d}"' for d in reversed(dirs))
    lines.append("!macroend")
    (work / "files.nsh").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def compiler_environment(makensis):
    if not makensis.is_file() or digest(makensis) != NSIS_SHA256:
        raise ValueError("Use the approved NSIS 3.0.4.1 Unicode compiler")
    for rel, expected in NSIS_INPUTS.items():
        if digest(makensis.parent / rel) != expected:
            raise ValueError(f"NSIS toolchain input mismatch: {rel}")
    return dict(os.environ, NSISDIR=str(makensis.parent))


def compile_nsis(work, payload, makensis, updater, app_version, build_id):
    flags = [f"/DWORK={work}", f"/DPAYLOAD={payload}", f"/DUPDATER_EXE={updater}",
             f"/DAPP_VERSION={app_version}", f"/DBUILD_ID={build_id}"]
    script = ROOT / "packaging" / "reader.nsi"
    subprocess.run([str(makensis), "/V2", "/INPUTCHARSET", "UTF8", *flags, str(script)],
                   check=True, env=compiler_environment(makensis))


def freeze_updater(work, catalogue_path):
    env = freeze_environment(work)
    source = ROOT / "packaging" / "update_engine.py"
    subprocess.run([sys.executable, "-B", "-s", "-m", "PyInstaller", "--onefile", "--console",
                    "--name", "chaessi-update", "--distpath", str(work / "bin"),
                    "--workpath", str(work / "analysis-updater"), "--specpath", str(work),
                    "--paths", str(ROOT), "--add-data", f"{catalogue_path}:.",
                    "--exclude-module", "tkinter", "--exclude-module", "unittest", str(source)],
                   cwd=ROOT, check=True, env=env)
    updater = work / "bin" / "chaessi-update.exe"
    audit_updater(work, updater, catalogue_path)
    return updater


def audit_updater(work, updater, catalogue_path):
    from PyInstaller.archive.readers import CArchiveReader

    inspect = runpy.run_path(str(ROOT / "packaging" / "audit.py"))
    image = CArchiveReader(str(updater))
    if image.extract("update-catalogue.json") != catalogue_path.read_bytes():
        raise ValueError("The updater does not contain the expected trusted catalogue")
    pyz = image.open_embedded_archive("PYZ.pyz")
    for name in pyz.toc:
        inspect["inspect_code"](pyz.extract(name), name)
    module_names = {Path(name).name for name in image.toc}
    if "update_engine" not in module_names or not {"update_policy", "relocation"} <= set(pyz.toc):
        raise ValueError("Updater modules are missing from its signed-off freeze")
    toc = ast.literal_eval((work / "analysis-updater" / "chaessi-update" / "Analysis-00.toc").read_text("utf-8"))
    inputs = {Path(item[0]).as_posix().lower(): Path(item[1])
              for group in toc if isinstance(group, list) for item in group
              if isinstance(item, tuple) and len(item) == 3 and item[2] in ("BINARY", "EXTENSION")}
    native_inputs = {}
    for name in image.toc:
        if name.lower().endswith((".dll", ".pyd", ".exe")):
            data = image.extract(name)
            inspect["check_private_strings"](data, name)
            source = inputs[Path(name).as_posix().lower()]
            native_inputs[name] = inspect["native_source"](source, data)
    (work / "updater-native-inputs.json").write_text(json.dumps(native_inputs, sort_keys=True, indent=2), encoding="utf-8")
    (work / "updater-sha256.txt").write_text(digest(updater) + "\n", encoding="ascii")


def prepare_lists(work, payload, files):
    terms = payload / "docs" / "licenses" / "PYTHON-WINDOWS.txt"
    (work / "license-page.txt").write_text(terms.read_text("utf-8-sig"), encoding="utf-16")
    nsis_lists(work, files)


def package(work, makensis, baseline, nov23, nov22, v101, relocation):
    check_source_snapshot(work)
    compiler_environment(makensis)
    delta = runpy.run_path(str(ROOT / "packaging" / "release_delta.py"))
    audit = runpy.run_path(str(ROOT / "packaging" / "audit.py"))
    payload = work / "dist" / APP
    if not (payload / (APP + ".exe")).is_file() or (work / "release" / SETUP).exists():
        raise ValueError("Use a completed fresh freeze without an existing installer")
    public_docs(payload)
    (payload / "product.id").write_text(MARKER, encoding="ascii")
    files = safe_files(payload)
    expected = {file.as_posix(): digest(payload / file) for file in files}
    policy = delta["catalogue"](expected, baseline, nov23, nov22, v101, relocation)
    target = policy["target"]
    from_baseline = policy["known"][0]
    changes = delta["classify"](from_baseline["payload"], expected)
    delta["write_json"](work / "payload-delta.json", {**changes, "baseline": from_baseline["id"],
                                                    "target": target["id"]})
    catalogue_path = work / "update-catalogue.json"
    delta["write_json"](catalogue_path, policy)
    updater = freeze_updater(work, catalogue_path)
    bootstrap = {"chaessi-update.exe": digest(updater)}
    prepare_lists(work, payload, files)
    compile_nsis(work, payload, makensis, updater, delta["APP_VERSION"], target["id"])
    released = work / "release"
    audit["audit"](work, payload, files, released / SETUP, makensis.parent, bootstrap=bootstrap)
    hashes = {name: digest(released / name) for name in (SETUP, ZIP)}
    sums = "".join(f"{value}  {name}\n" for name, value in hashes.items())
    (released / "SHA256SUMS.txt").write_text(sums, encoding="ascii")
    manifest = {"app": delta["APP_VERSION"], "extension": "0.3.1", "tools": {"python": "3.13.17",
                "pyinstaller": "6.22.3", "nsis": "3.0.4.1", "nsis_sha256": NSIS_SHA256},
                "release": hashes, "payload": expected, "build": target["id"],
                "sequence": target["sequence"], "install_location": "D:/MApp/Chaessi Reader",
                "edition": "public-production-signed-release", "preset_trust": public_trust(),
                "upgrade_baseline": from_baseline["id"],
                "known_upgrade_builds": [entry["id"] for entry in policy["known"]],
                "catalogue_sha256": digest(catalogue_path)}
    delta["write_json"](work / "manifest.json", manifest)
    check_source_snapshot(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["freeze", "setup"])
    parser.add_argument("work", type=Path)
    parser.add_argument("--makensis", type=Path)
    parser.add_argument("--baseline", type=Path, help="Approved public build 2026112401 manifest")
    parser.add_argument("--nov23", type=Path, help="Approved November 23 public manifest")
    parser.add_argument("--nov22", type=Path, help="Approved November 22 public manifest")
    parser.add_argument("--v101", type=Path, help="Approved public 1.0.1 build 2026112501 manifest")
    parser.add_argument("--relocation", type=Path, help="Approved D relocation build 2026112502 manifest")
    args = parser.parse_args()
    work = args.work.resolve()
    if work.is_relative_to(ROOT) or not work.is_absolute():
        parser.error("Build outside the source checkout")
    if args.step == "freeze":
        freeze(work)
    elif all((args.makensis, args.baseline, args.nov23, args.nov22, args.v101, args.relocation)):
        package(work, *(argument.resolve() for argument in (args.makensis, args.baseline, args.nov23, args.nov22,
                                                            args.v101, args.relocation)))
    else:
        parser.error("setup requires --makensis, --baseline, --nov23, --nov22, --v101 and --relocation")


if __name__ == "__main__":
    main()

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
import runpy

project = Path(SPECPATH).parent.resolve()
sdk = runpy.run_path(str(project / "packaging" / "sdk_inputs.py"))
sdk["verify_sdk_inputs"]()
analysis = Analysis(
    [str(project / "bundle_reader.pyw")],
    pathex=[str(project)],
    datas=[(str(project / "bundle" / name), "bundle")
           for name in ("bookmark.html", "collect.js", "page-reader.js")],
    excludes=["unittest", "pytest", "pydoc", "doctest", "idlelib", "pip", "setuptools"],
)
runtime = Path(sys.base_prefix).resolve()
# Win10/11 provides the Universal CRT and API sets as OS components.
# All remaining native dependencies must come from the verified PSF runtime.
native = []
for dest, source, kind in analysis.binaries:
    name = Path(dest).name.lower()
    if name == "ucrtbase.dll" or name.startswith(("api-ms-win-", "ext-ms-win-")):
        continue
    if not Path(source).resolve().is_relative_to(runtime) and sdk["native_provenance"](source) is None:
        raise ValueError(f"Unexpected binary provenance: {dest} from {source}")
    native.append((dest, source, kind))
analysis.binaries = native
archive = PYZ(analysis.pure)
app = EXE(archive, analysis.scripts, [], exclude_binaries=True,
          name="ChaessiMetadataReader", console=False, strip=False, upx=False,
          version=str(project / "packaging" / "version.txt"), icon="NONE")
COLLECT(app, analysis.binaries, analysis.datas, strip=False, upx=False, name="ChaessiMetadataReader")

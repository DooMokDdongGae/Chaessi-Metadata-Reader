"""Exercise installer file guards on disposable Windows files, without installing Reader."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path, help="new empty directory outside the checkout")
    parser.add_argument("--makensis", required=True, type=Path)
    args = parser.parse_args()
    work, compiler = args.work.resolve(), args.makensis.resolve()
    if work.is_relative_to(Path(__file__).resolve().parents[1]) or work.exists():
        parser.error("Use a fresh directory outside the checkout")
    if hashlib.sha256(compiler.read_bytes()).hexdigest() != "f2b2b7726ac0d4e720dff52bfca11a5518d550fc75ed34a48dc47921527293f0":
        parser.error("Unexpected compiler")
    work.mkdir(parents=True)
    temp = work / "temp"
    temp.mkdir()
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), NSISDIR=str(compiler.parent))
    source = work / "fixture.nsi"
    owned = work / "owned"
    owned.mkdir()
    source.write_text(r'''Unicode true
RequestExecutionLevel user
SilentInstall silent
AutoCloseWindow true
Name "Reader private file guard test"
OutFile "fixture.exe"
!include LogicLib.nsh
!include FileFunc.nsh
!include "${GUARDS}"
LoadLanguageFile "${NSISDIR}\Contrib\Language files\English.nlf"
LangString Unsafe ${LANG_ENGLISH} "Private fixture rejected"
!insertmacro Guards ""
!insertmacro CompareFiles ""
Section
  StrCpy $Pins 0
  StrCpy $INSTDIR "$EXEDIR\owned"
  StrCpy $ProfileBoundary "$EXEDIR"
  StrCpy $GuardPath "$INSTDIR"
  Call PinChain
  StrCpy $R0 "$INSTDIR\payload.dat"
  Call CheckFile
  StrCpy $R0 "$INSTDIR\Uninstall.exe"
  Call CheckFile
  !insertmacro OwnedUninstaller ""
  Call ReleasePins
  SetErrorLevel 0
SectionEnd
''', encoding="utf-8")
    executable = work / "fixture.exe"
    include = Path(__file__).resolve().with_name("guards.nsh")
    subprocess.run([str(compiler), "/V2", f"/DGUARDS={include}", str(source)], env=env, check=True)
    valid = b"Reader generated uninstaller fixture"
    uninstaller, receipt, payload = (owned / name for name in ("Uninstall.exe", "uninstaller.copy", "payload.dat"))
    uninstaller.write_bytes(valid)
    receipt.write_bytes(valid)
    payload.write_bytes(b"unchanged original payload")

    def check(name, code):
        before = {f: f.read_bytes() for f in (uninstaller, receipt, payload) if f.exists()}
        result = subprocess.run([str(executable), "/S"], env=env, timeout=30)
        if result.returncode != code or any(f.read_bytes() != old for f, old in before.items()):
            raise ValueError(f"Fixture failed: {name} (actual exit {result.returncode}, expected {code})")
        print(name, "PASS")

    check("matching marker and readable files", 0)
    uninstaller.write_bytes(b"another application")
    check("unknown uninstaller survives rejection", 2)
    uninstaller.write_bytes(valid)
    payload.chmod(0o444)
    try:
        check("read-only payload survives rejection", 2)
    finally:
        payload.chmod(0o666)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes, close.restype = (wintypes.HANDLE,), wintypes.BOOL
    handle = create(str(payload), 0x80000000, 1, None, 3, 0x80, None)  # other readers only
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        check("locked payload survives rejection", 2)
    finally:
        close(handle)
    check("retry after releasing lock", 0)


if __name__ == "__main__":
    main()

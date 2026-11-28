# Reader 1.1.1 public build

Display version `1.1.1`, build `reader-20261128-01-public`, sequence `2026112801`. One FULL Setup supports fresh per-user installation at `%LOCALAPPDATA%\Programs\ChaessiMetadataReader`, safe selectable local roots (spaces/Unicode/other drives included), and retention of the verified existing C/D/custom root during an upgrade. The [official release](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.1) publishes Setup, unchanged extension 0.3.1 ZIP and checksums. The approved private03 installation-engine evidence is reused; final public packaging and the exact final Preset pair are checked separately. Only official PUBLIC publisher anchors are embedded; signing private keys are never build inputs. Keep local signing vaults, profiles and QA evidence outside the checkout and release.

## Verified build inputs

Use the PSF full x64 CPython 3.13.17 ZIP, SHA-256 `b26ca4b4ee51e157836049934d2b8eabd55939be296f3130254251b6df96ec2f`, and verify its Authenticode-signed interpreter. [PSF manifest](https://www.python.org/ftp/python/3.13.17/windows-3.13.17.json). The fresh build venv uses hash-pinned wheels in `requirements-build.txt`: PyInstaller 6.22.3, official PyCA cryptography 50.0.2, cffi 2.1.1 and pycparser 3.12. `sdk-inputs.json` pins the whole official wheel inputs; the spec and audit accept only PSF native binaries or those exact SDK members. The Windows cryptography wheel statically links OpenSSL 4.0.3. Original licenses and the vendor's dependency SBOMs accompany the release.

NSIS 3.0.4.1's top-level compiler driver is pinned at `f2b2b7726ac0d4e720dff52bfca11a5518d550fc75ed34a48dc47921527293f0`, its `Bin/makensis.exe` at `e277b7378931b74392015f5ad6b1d744dcd8a347baa4480350a75ebeab8d8e3d`, with relative stubs/plugins/UI resource pins in `build.py`. Pass the top-level driver, not the child Bin executable.

```powershell
& "$psfRuntime/python.exe" -I -B packaging/build-env.py $newEnvironment
& "$newEnvironment/Scripts/python.exe" -I -B packaging/build.py freeze $freshCandidate
& "$newEnvironment/Scripts/python.exe" -I -B packaging/build.py setup $freshCandidate --makensis $nsisDriver --baseline $public2401Manifest --nov23 $public2302Manifest --nov22 $public2205Manifest --v101 $public2501Manifest --relocation $relocation2502Manifest --v110 $public2601Manifest
```

Use absolute paths outside the source checkout and a new candidate directory. `source-at-freeze.json` must match the complete source before and after freezing and packaging. A changed source needs a new candidate; preserve the rejected build as evidence. The extension ZIP remains the reviewed nine-file 0.3.1 ZIP.

## Installation ownership and recovery

The primary baseline is exact approved public 1.1.0 build `2026112601` (whole-manifest SHA-256 `595785f544625c4711f30755c9b098ae6dee2d63463ee2b4bfc21fe4f7d3f4a9`). Relocation build `2026112502` remains a separate pinned baseline. Exact public builds `2026112501`, `2026112401`, `2026112302` and `2026112205` are separately pinned whole-manifest baselines. Unknown, mixed, modified or newer installations are refused. No downgrade escape is provided. The package emits only a FULL Setup, extension ZIP and checksums; no EXE-only patch is implied.

FULL may add catalogued SDK/notices paths; it may not remove an older owned payload path. Additive upgrades require the newly generated uninstaller. Both remover copies are replaced in the same rollback journal as changed and added files. Shortcut receipts and unrelated installation records are preserved. A retained old remover intentionally rejects an expanded ownership set.

ReplaceFileW retains the displaced file's former ACL. The updater opens only the exact transaction evidence member, pins ancestry and file identity, rejects links and untrusted owners, hashes approved bytes, sets a protected trusted DACL by the same handle, then reapplies the strict private-workspace check. Recovery handles interruption between replacement and this hardening step. It does not waive the workspace ACL check or alter unrelated D directories or user files.

Close Reader normally before updating. The updater uses the same target volume for replacements and rollback bytes, while the protected high-water record and journal remain in the Windows profile. After successful payload/self-test commit, Setup records Windows DisplayVersion. Rerun the same approved Setup after an interrupted transaction; preserve files and records if it reports a conflict. A later different candidate cannot silently adopt another candidate's pending journal. Old unprotected public Setup limitations remain as documented in the inherited guides.

## Isolated acceptance and evidence reuse

Installer fixtures use an explicitly owned Windows Sandbox with a separate fixed NTFS D volume. Map release inputs read-only and a small evidence directory writable, with networking/clipboard/audio/video/printer redirection disabled. Never run these fixtures on a user's installed Reader. An approved release conversion may reuse the reviewed, unchanged installation-engine evidence while revalidating the changed trust policy and actual signed connection; distinguish reused evidence from fresh execution.

Validate no-D fresh default and safe custom C/Unicode/space/other-drive roots, retained C/D upgrades from each approved baseline; all target payload hashes; Windows registration 1.1.1; both replacement remover copies; same-candidate no-op; protected old Setup refusal; failure rollback; uninstall; reinstall; settings, owned links and unrelated records. The locked-document fixture permits backup reads while denying replacement, exercising rollback without modifying package bytes. Normal Windows temporary-file tests also cover power loss immediately after ReplaceFileW and before ACL hardening. AppContainer ACL rewriting is a distinct execution condition and must not be reported as an ordinary Windows pass.

Public-channel signature verification and legacy official Preset 3.8.5 compatibility remain separate from file/installer audits. A file audit does not prove actual UI/protocol results. Development roots must never be substituted for the embedded production anchors.

`verify-installed.ps1` requires explicit `-InstallRoot` for the actual installation under test; it never assumes a personal drive. `manifest.json.install_policy` describes path policy rather than asserting a fixed installed root. `--v110` is mandatory for setup packaging; the pure catalogue API keeps an optional argument for historical fixture callers only.

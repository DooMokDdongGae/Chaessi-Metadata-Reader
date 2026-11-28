# Chaessi Metadata Reader 1.1.1

Windows x64 · 2026-11-28 · Build `reader-20261128-01-public` · Sequence `2026112801`

[Official release](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.1) · [Install and use](README.en.md) · [AI setup-assistant prompt](README.en.md#ai-setup)

- **Normal Windows installation paths.** Fresh installation defaults to `%LOCALAPPDATA%\Programs\ChaessiMetadataReader`. Safe local custom folders, spaces, Unicode and another drive are supported; D is not required. An upgrade retains the verified existing location. Registration, shortcuts, removal, same-volume replacement and recovery follow the actual selected root.
- **One Setup.** Use `Chaessi-Metadata-Reader-Setup-x64.exe` for fresh installation and exact supported upgrades. It checks whole-file baselines `2026112205`, `2026112302`, `2026112401`, `2026112501`, `2026112502` and `2026112601`. A version label or folder selection alone does not authorize modified, mixed or unknown contents. There is no general downgrade bypass.
- **Features and trust.** The production root, `public`/`public-production`, `chaessi.prompt-transfer/1`, SDK signatures, complete resource/process/socket checks, nonce/HMAC, revision and preview/cancel/apply/Undo remain. [Preset 3.9.1](https://github.com/DooMokDdongGae/Chaessi-Preset/releases/tag/v3.9.1) uses a separate ZIP with its EXE and four signature/manifest files kept together. Publication is prepared in parallel; check the actual release and files. The exact corrected 2026-11-23 official 3.8.5 also remains supported; every future version is not guaranteed. Test keys are not trusted.
- **Data and Chrome.** Settings, language, pairing, Preset selection and extension **0.3.1** are retained. Do not reinstall or re-pair a working extension. Only for a first install, extract to a permanent folder and let the user load it and review initial Chrome permissions. Paste the connection key only into local extension settings, never AI chat, logs or screenshots.
- **Recovery and removal.** Close Reader normally first. After interruption, rerun the same Setup and follow recovery guidance; preserve files and records on conflict. It cannot prevent an old unprotected installer from running later, so do not overwrite with one. Verify the unsigned Windows installer's filename and SHA-256 and respect security policies. Uninstall preserves user settings and separate Preset data.

## Verification scope and known limitations

- Earlier isolated signed-candidate measurements observed approximately **6.97 seconds** for preview transfer and **14.35 seconds** for full authentication. Depending on package size and environment, checks can take several seconds or longer. These are observations, not guaranteed response times. Wait for a result instead of repeatedly sending.
- Discovery may fail immediately after launching a closed Preset. Wait for its window to be ready, then retry **Connect to Preset**. Draft revisions and slot changes are separate from process connection lifetime and may require destination confirmation.
- Reused isolated Windows evidence from the verified development baseline covers no-D fresh installation, default/Unicode/space/other-volume paths, existing C/D in-place upgrades, actual replacement failure/rollback/same-Setup retry, uninstall/settings retention, Chrome 0.3.1 reconnection without re-pairing and synthetic PNG input/editing. This is not a new all-PC test of the PUBLIC build. Minimal final public-pair validation is distinguished in the release acceptance record.
- Full online Chrome/NovelAI Inspect collection was not rerun during this public conversion. Browser **Copy image** can strip metadata; use the original PNG file. Original provider Precise/Character PNG samples and some external-image handling paths remain unverified. Native observations of saving/busy timing are also incomplete.
- Offline Reader cannot know about publisher-key revocations it has not received. The system clock and damage to same-user storage remain operational limitations.

### Interrupted fresh installation boundary

The same Setup checks the protected fresh record's root, volume and target build. It can resume after cleaning only partial files whose product ownership and target hashes are proven. A complete payload awaiting diagnostics/registration uses a separate commit path. Changed/unproven files and invalid recovery state are preserved and refused. Do not delete partial files or `fresh.json`, or reset settings.

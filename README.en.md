# Chaessi Metadata Reader 1.1.1

Windows x64 · Build `reader-20261128-01-public` · Sequence `2026112801`

[Latest stable release](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.1)

Use the same **Chaessi-Metadata-Reader-Setup-x64.exe** for a fresh install or a supported official upgrade. A fresh install defaults to `%LOCALAPPDATA%\Programs\ChaessiMetadataReader` and lets you select a safe local folder, including spaces and Unicode. An upgrade retains the verified existing installation location. Chrome extension **0.3.1** is unchanged.

[한국어](README.ko.md) · [日本語](README.ja.md) · [Release notes](RELEASE-NOTES.en.md)

Import an image’s prompts from NovelAI Inspect, edit them, and send selected text to a Base or Character field in CHAESSI PRESET. Chaessi Metadata Reader is independently developed.

<a id="ai-setup"></a>

## Ask Codex, Claude Code or GPT for setup help

Copy the complete prompt below into your AI chat. Computer control depends on the AI's tools and policies. Never add your connection key to the prompt.

    Help me install and connect Chaessi Metadata Reader 1.1.1 and Chrome extension 0.3.1 on my Windows x64 PC.
    First check which computer and browser tools you can use. Help directly only where supported; otherwise tell me which button to choose, one step at a time. Let me handle user approval, UAC, security and permission confirmations as your tool policies require. Do not bypass restrictions or organizational policies.

    1. Obtain Chaessi-Metadata-Reader-Setup-x64.exe, the extension ZIP Chaessi-Metadata-Reader-Chrome-Extension.zip if needed, and SHA256SUMS.txt from this official 1.1.1 release. Verify filenames and SHA-256 hashes. Stop and tell me if the page is not available yet or files/hashes do not match.
    https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.1
    The same Setup handles new installations and supported official upgrades. A fresh install defaults to %LOCALAPPDATA%\Programs\ChaessiMetadataReader and permits a safe local folder, including spaces, Unicode and another drive. An upgrade retains its verified existing location; do not move its files manually. Close Reader normally and read the installer prompts. The installer has no code signature: stop if hashes differ or policy blocks it. Preserve existing keys, language, Preset selection, Chrome profiles and user data.

    2. If Chrome extension 0.3.1 already works, keep its existing folder, profile and pairing. Do not reinstall, re-pair or create duplicates. Only for a first install, extract the ZIP to a permanent dedicated folder. In my intended Chrome profile, guide me to chrome://extensions → Developer mode → Load unpacked, where I select the folder containing manifest.json. Check for one ‘채씨 메타데이터 리더 연결’ card at version 0.3.1. Tell me not to move or delete the folder afterward.

    3. Only for initial pairing, guide me to Chrome connection setup → Copy connection key in Reader. I will paste it only into ‘리더의 연결 키’ in this PC's extension settings and choose ‘최초 연결 저장’ (save initial pairing). Do not request the key or its file, or send it to chat, logs, screenshots or external services. After ‘NovelAI Inspect 접근 허용’ (allow Inspect access), let me review Chrome's initial permission request. Check that Reader shows Chrome connected, close the setup tab, then reopen Reader with the same Chrome profile to check reconnection. Do not reset a working pairing.

    4. Explain how to view Simplified in NovelAI Inspect, import it into Reader and edit text. Obtain Preset 3.9.1 as a separate ZIP from the official release below, verify SHA-256 and extract it to a stable folder. Publication may be prepared in parallel: do not assume a page or ZIP that is not yet available exists.
    https://github.com/DooMokDdongGae/Chaessi-Preset/releases/tag/v3.9.1
    Keep Chaessi-Preset-v3.9.1-x64.exe and its four signature/manifest files together. Choose that stable EXE once in Reader’s Select/change executable, not a temporarily extracted internal EXE. Use that same file path even when Preset is already running. The corrected 2026-11-23 official 3.8.5 is also supported separately. Do not assume compatibility with every future version. Choose Base/Character Positive/Undesired and Append/Replace, then Send to Preset → review the changes in Preset → apply or cancel. Undo can restore the draft after applying. Never create a signature trust exception. Setup checks do not require sending my images or prompts externally or calling an image generation API.

## Install Reader and the Chrome extension

Use Windows 10 or 11 x64 and Chrome 120 or later. Reader includes Python and Tk. You can run it without installing developer tools.

1. Download **Chaessi-Metadata-Reader-Setup-x64.exe** and, if needed, **Chaessi-Metadata-Reader-Chrome-Extension.zip** from the [official 1.1.1 release](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.1). To check a download in PowerShell, run `Get-FileHash -Algorithm SHA256 "filename"` and compare the result with the release checksum.
2. Finish your work and close Reader if it is open. Run the same **Setup** to install for your Windows account or update an official installation. Open **Chaessi Metadata Reader** from Start. A fresh installation offers a desktop shortcut.
3. Keep the existing extension if 0.3.1 is already paired. For a first install, extract the ZIP to a folder you plan to keep. In the Chrome profile you use for Inspect, open `chrome://extensions`. Turn on **Developer mode**, choose **Load unpacked**, and select the folder containing **manifest.json**.
4. Check the extension card for **채씨 메타데이터 리더 연결**, version **0.3.1**. Leave the extracted folder in place while the extension is installed. [Chrome’s unpacked-extension guide](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked)

## Pair this Chrome profile once

The extension’s setup page is in Korean. The labels below match what appears there.

1. In Reader, choose **Chrome connection setup → Copy connection key**. Open the Reader extension from Chrome’s Extensions menu.
2. Paste into **리더의 연결 키** (Reader connection key) and choose **최초 연결 저장** (save pairing). Choose **NovelAI Inspect 접근 허용** (allow Inspect access), review the Chrome prompt for `novelai.net`, then allow it.
3. Once Reader shows that Chrome is connected, close the setup tab. On later launches, open Reader and Chrome with the same profile. Reconnection can take 30 seconds or longer when Chrome is idle.

## Send prompts to a Preset draft

1. Open an image in NovelAI Inspect and check its **Simplified** text. In Reader, choose **Import from NovelAI Inspect**. If several Inspect tabs are open, select the one you want first.
2. Pick an image under **Imported images**. Edit the Base or Character **Positive** or **Undesired** field. **Copy text** copies the current edit. **Show original text** displays the source, and **Restore original** resets an individual field.
3. Highlight part of a field and choose **Add selection**, or choose **Add full text** for the whole field. Each item is a copy made at that moment. Add it again to capture a later edit.
4. In Reader, open **Send to Preset → Choose or change EXE**, select `Chaessi-Preset-v3.9.1-x64.exe` from the separate official ZIP with all four signature/manifest files beside it, and confirm once. **Connect to Preset** uses the matching running app or starts it when closed. [CHAESSI PRESET v3.9.1 release](https://github.com/DooMokDdongGae/Chaessi-Preset/releases/tag/v3.9.1)
5. Select a text item and its **Destination prompt field**. **Append** adds a comma and a space between two nonempty texts. **Replace** replaces the field’s contents. Assign every row a destination and choose **Send to Preset**. This sends the whole list from top to bottom. To send one item, remove the other items from the list; the originals and editor fields stay unchanged.
6. In the **Preset window**, compare the current and final text, then apply or cancel. After applying, use Preset’s Undo to restore the previous edit. Applying changes the open draft. Sending does not save a preset, create a History entry, generate an image or call a paid API.

Reader checks the selected executable and authenticates the receiver using `chaessi.prompt-transfer/1`. Use the corrected 2026-11-23 official v3.8.5 build. Choose the Portable download itself. Choose the file again if its path changes. An official signed update at the same path is revalidated with its new signature and process; it does not need a new registration for every release. Reader rechecks destinations when the draft or slots change and marks any field that needs you to choose it again.

You can choose character numbers with gaps or in reverse order. With one existing character, sending to **Character 4 (new)** creates empty Off slots at positions 2 and 3. Review the creation range in Preset before applying. Cancel creates no slots. Undo removes the added slots together. Unrelated existing slots keep their contents. **Move up / Move down** changes the application order for text sent to the same field.

## Troubleshooting, updates and removal

- **Installer blocked.** The installer is unsigned, so Windows may show an unknown publisher. Check the release filename and SHA-256. Stop if they differ. If your organization restricts installation or Chrome Developer mode, check with your administrator.
- **Waiting for Chrome.** Check that the extension is enabled in the intended Chrome profile and only one Reader is open. To replace an incorrect key, choose **연결 해제** (disconnect) on the extension’s setup page, then copy and save the key again. For Inspect, also check site permission and that an image is open.
- **Preset connection fails.** Check the official Portable’s build and location. Choose the file again if it moved. A valid signed update at the same path is revalidated on reconnection. Reader tries to reconnect when the same Preset app is open again. Recheck any row marked as needing a destination.
- **Update and recovery.** Close Reader normally and run this 1.1.1 Setup. It checks exact approved whole-file baselines for official 1.0.x and 1.1.0 and retains the verified existing C, D or chosen local location. Choosing a folder does not authorize its existing contents. Modified or mixed files and unknown builds are refused. After an interruption, rerun the same Setup and follow its recovery instructions. Preserve files and records if a conflict is reported. This installer cannot prevent an old unprotected Setup from being run later; do not overwrite it with an old installer. Keep the paired Chrome extension 0.3.1 and its settings.
- **Move from an earlier development copy.** Close the previous Reader. In the installed app, use **Chrome connection setup → Choose previous Reader folder** to import its existing key. Keep the Chrome profile and unpacked extension path to retain the extension ID and permissions. If Reader cannot safely read the previous folder, copy Reader’s current connection key and save it in the extension. If access to your Windows user’s recovery folder is denied, the key stays unchanged. Check the folder permissions and try again.
- **Uninstall.** Remove Reader in **Windows Settings → Apps → Installed apps**. Remove the extension separately in `chrome://extensions`; then you can delete its extracted folder. Removing Reader preserves user settings and Preset data.

## Privacy and local data

Imported originals, edits and queued text last for the Reader session. Copy anything you need before replacing a collection or closing Reader. Reader stores your language, chosen Preset executable and connection key per Windows user. Chrome stores the key and site permission in the paired profile. Paste the key only in this PC’s extension settings. Reader and the extension communicate over loopback. Reading an image or post starts when you request an import.

Open **Help** in Reader for offline instructions, including the optional aitag.win web-post importer and transfer-status checks. [Third-party software notices](THIRD-PARTY-NOTICES.md)

## Signed Preset packages

Official **Preset 3.9.1** is distributed separately as a Windows x64 ZIP through its [release page](https://github.com/DooMokDdongGae/Chaessi-Preset/releases/tag/v3.9.1). Its publication is prepared in parallel with Reader; check that the page and files are actually available. Keep the ZIP’s EXE and four signature/manifest files together. The **official corrected 2026-11-23 Preset 3.8.5** also remains supported. Arbitrary unsigned PRIVATE builds are not supported. Signed packages must satisfy both `chaessi.prompt-transfer/1` and PUBLIC production trust; this does not guarantee compatibility with every future version.

A signed Portable needs these four files next to its EXE. `<EXE filename>` includes `.exe`.

- `<EXE filename>.chaessi-release.json`
- `<EXE filename>.chaessi-release.sig`
- `chaessi-publisher-keys.json`
- `chaessi-publisher-keys.sig`

Keep and update the complete official package together without editing its signature files. Preserve the whole directory layout for an unpacked distribution. Reader checks publisher keys, signatures, validity, revocation, highest accepted sequences, all resources, the actual receiving process and socket, then uses the existing per-request nonce/HMAC authentication. Test keys are not trusted. The production trust channel is `public` and its storage realm is `public-production`. For errors, check the PC date and time and reselect a complete current official package. There is no option to disable verification or create a trust exception.

## PNG input and editing

Drop a PNG containing prompt metadata onto Reader, or paste supported PNG files/image clipboard data to import offline. Pasting ordinary text into an editor remains text editing. Reader does not invent prompts when metadata is absent. Expand an editor to read long text and collapse it to return to the original layout. If replacing imported data requires confirmation, review your edits and queued text before continuing.

## Verification scope and known limitations

- Earlier isolated signed-candidate measurements observed approximately **6.97 seconds** for preview transfer and **14.35 seconds** for full authentication. Depending on package size and environment, checks can take several seconds or longer. These are observations, not guaranteed response times. Wait for a result instead of repeatedly sending.
- Discovery may fail immediately after launching a closed Preset. Wait for its window to be ready, then retry **Connect to Preset**. Draft revisions and slot changes are separate from process connection lifetime and may require destination confirmation.
- Reused isolated Windows evidence from the verified development baseline covers no-D fresh installation, default/Unicode/space/other-volume paths, existing C/D in-place upgrades, actual replacement failure/rollback/same-Setup retry, uninstall/settings retention, Chrome 0.3.1 reconnection without re-pairing and synthetic PNG input/editing. This is not a new all-PC test of the PUBLIC build. Minimal final public-pair validation is distinguished in the release acceptance record.
- Full online Chrome/NovelAI Inspect collection was not rerun during this public conversion. Browser **Copy image** can strip metadata; use the original PNG file. Original provider Precise/Character PNG samples and some external-image handling paths remain unverified. Native observations of saving/busy timing are also incomplete.
- Offline Reader cannot know about publisher-key revocations it has not received. The system clock and damage to same-user storage remain operational limitations.

### Earlier public releases

[1.0.0 build 2026112401](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0%2B2026112401) · [1.0.0 baseline](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0)

Accepted whole-file upgrade baselines are `2026112205`, `2026112302`, `2026112401`, `2026112501`, previous build `2026112502` and `2026112601`. A matching version label alone does not authorize an arbitrary installation.

1.0.1 and the withdrawn 1.1.0 remain historical installation baselines; they are not offered as current download links.

### Interrupted fresh installation boundary

After an interrupted fresh copy, the same Setup checks the protected fresh record's installation root, volume and target build. It can remove only proven product files that exactly match the target hashes, then restart installation. A complete target awaiting diagnostics or registration follows a separate commit path. Changed or unproven files, another installation registration and invalid recovery state are preserved and refused. Do not delete partial files or `fresh.json`, or reset settings; preserve conflict records and request diagnosis. Interruption-and-rerun evidence is reused from the verified isolated development baseline and distinguished from the new public-file audit.

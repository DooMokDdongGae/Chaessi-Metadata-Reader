# Chaessi Metadata Reader 1.0.0

[Download the latest Reader](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/latest) · [November 23, 2026 patch baseline](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0)

[한국어](README.ko.md) · [日本語](README.ja.md) · [Release notes](RELEASE-NOTES.en.md)

Import an image’s prompts from NovelAI Inspect, edit them, and send selected text to a Base or Character field in CHAESSI PRESET. Chaessi Metadata Reader is independently developed.

<a id="ai-setup"></a>

## Ask Claude or GPT to help with setup

If installation or pairing gets stuck, copy the entire prompt into your AI chat. The text to copy contains no connection key.

    Help me install and connect Chaessi Metadata Reader 1.0.0 and Chrome extension
    0.3.1 on my Windows x64 PC. First check which computer and browser tools you can
    use. Help directly where supported. For steps you cannot perform, tell me which
    button to choose, one step at a time. Respect approval prompts and tool
    restrictions.

    1. Open this official GitHub release and verify the owner, repository and v1.0.0
    tag.
    https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/latest
    Download Chaessi-Metadata-Reader-Setup-x64.exe and
    Chaessi-Metadata-Reader-Chrome-Extension.zip. Compare both SHA-256 values with
    SHA256SUMS.txt from that release and stop if either differs. Preserve my existing
    Reader, Chrome profile and extension settings, connection key, language and
    registered Presets. Run the per-user installer and let me handle any required
    approval or UAC prompt.

    2. Extract the extension ZIP to a dedicated folder that will stay in place. In my
    chosen Chrome profile, open chrome://extensions and check for an existing Reader
    extension. For an update, keep the original folder and reload its card. For a new
    install, guide me through Developer mode and Load unpacked so I select the folder
    containing manifest.json myself. Check that there is one ‘채씨 메타데이터 리더
    연결’ card at version 0.3.1. Keep the extracted folder after installation.

    3. Guide me to Chrome connection setup → Copy connection key in Reader. I will
    paste it only into the ‘리더의 연결 키’ field in the local Reader extension and
    select ‘최초 연결 저장’ (save pairing). Do not request the key or its file, or
    put it in chat, logs, screenshots or external services. Guide me to ‘NovelAI
    Inspect 접근 허용’ (allow Inspect access) and let me review and grant Chrome’s
    permission. When Reader shows ‘Chrome connected’, close the extension setup tab.
    Reopen Reader with the same Chrome profile and check that it reconnects.

    4. Show me how to import the image’s Simplified prompts from NovelAI Inspect and
    edit them in Reader. Start the official CHAESSI PRESET v3.8.5 Portable first. In
    Send to Preset → Connect to Preset → Running Presets, choose that window and the
    destination field, then review the change in Preset. Setup does not require
    sending my images or prompts to an external service or calling an image
    generation API.

## Install Reader and the Chrome extension

Use Windows 10 or 11 x64 and Chrome 120 or later. Reader includes Python and Tk. You can run it without installing developer tools.

1. Download **Chaessi-Metadata-Reader-Setup-x64.exe** and **Chaessi-Metadata-Reader-Chrome-Extension.zip** from this release. To check a download in PowerShell, run `Get-FileHash -Algorithm SHA256 "filename"` and compare the result with the release checksum.
2. Run the installer for your Windows account. Open **Chaessi Metadata Reader** from Start. You can select a desktop shortcut during installation.
3. Extract the extension ZIP to a folder you plan to keep. In the Chrome profile you use for Inspect, open `chrome://extensions`. Turn on **Developer mode**, choose **Load unpacked**, and select the folder containing **manifest.json**.
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
4. **Start the official `Chaessi-Preset-v3.8.5-x64.exe` Portable first.** In Reader, choose **Send to Preset → Connect to Preset**. Under **Running Presets**, choose the v3.8.5 window and **Connect to this Preset**. Check the displayed path and window when several are running. [Get CHAESSI PRESET v3.8.5](https://github.com/DooMokDdongGae/Chaessi-Preset/releases/tag/v3.8.5)
5. Select a text item and its **Destination prompt field**. **Append** adds a comma and a space between two nonempty texts. **Replace** replaces the field’s contents. Assign every row a destination and choose **Send to Preset**. This sends the whole list from top to bottom. To send one item, remove the other items from the list; the originals and editor fields stay unchanged.
6. In the **Preset window**, compare the current and final text, then apply or cancel. After applying, use Preset’s Undo to restore the previous edit. Applying changes the open draft. Sending does not save a preset, create a History entry, generate an image or call a paid API.

A compatible folder-based build can be registered and started after you confirm its path. For the public v3.8.5 Portable, start it yourself each time and select its running window. Reader authenticates the receiver using the `chaessi.prompt-transfer/1` protocol. Older releases without a receiver cannot accept transfers. Switching windows keeps your text list and requires you to choose the destinations again.

You can choose character numbers with gaps or in reverse order. With one existing character, sending to **Character 4 (new)** creates empty Off slots at positions 2 and 3. Review the creation range in Preset before applying. Cancel creates nothing; Undo removes the added slots together. Unrelated existing slots keep their contents. **Move up / Move down** changes the application order for text sent to the same field. Both apps need the **2026-11-23 corrected build** for this behavior.

## Troubleshooting, updates and removal

- **Installer blocked.** The installer is unsigned, so Windows may show an unknown publisher. Check the release filename and SHA-256. Stop if they differ. If your organization restricts installation or Chrome Developer mode, check with your administrator.
- **Waiting for Chrome.** Check that the extension is enabled in the intended Chrome profile and only one Reader is open. To replace an incorrect key, choose **연결 해제** (disconnect) on the extension’s setup page, then copy and save the key again. For Inspect, also check site permission and that an image is open.
- **Preset window missing.** Let the Portable finish starting, then refresh the running list. If you switched windows or the draft changed, refresh the fields and select each destination again.
- **Update.** Close Reader and run the new installer. For the extension, extract the updated files over the same folder and use **Reload** on the existing card in `chrome://extensions`. A different folder can create a separate extension ID and require fresh pairing and permission in that profile.
- **Move from an earlier development copy.** Close the previous Reader. In the installed app, use **Chrome connection setup → Choose previous Reader folder** to import its existing key. Keep the Chrome profile and unpacked extension path to retain the extension ID and permissions. If Reader cannot safely read the previous folder, copy Reader’s current connection key and save it in the extension. If access to your Windows user’s recovery folder is denied, the key stays unchanged. Check the folder permissions and try again.
- **Uninstall.** Remove Reader in **Windows Settings → Apps → Installed apps**. Remove the extension separately in `chrome://extensions`; then you can delete its extracted folder. Removing Reader preserves user settings and Preset data.

## Privacy and local data

Imported originals, edits and queued text last for the Reader session. Copy anything you need before replacing a collection or closing Reader. Reader stores your language, registered Presets, last selection and connection key per Windows user. Chrome stores the key and site permission in the paired profile. Paste the key only in this PC’s extension settings. Reader and the extension communicate over loopback. Reading an image or post starts when you request an import.

Open **Help** in Reader for offline instructions, including the optional aitag.win web-post importer and transfer-status checks. [Third-party software notices](THIRD-PARTY-NOTICES.md)

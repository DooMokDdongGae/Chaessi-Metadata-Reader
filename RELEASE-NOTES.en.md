# Chaessi Metadata Reader 1.0.0

## Corrected build — 2026-11-23

A single **Send to Preset** action sends the whole list. If no connection or destination is selected, it explains what to choose. New character numbers can have gaps or be selected in reverse order; the UI shows the actual destination character number. Preset previews any empty Off slots created in between, and Cancel/Undo also cover those slots. Use the corrected 2026-11-23 build of both apps. Version numbers and original Git tags are retained; see the public Release notes for the correction commit, build date and new SHA-256 checksums.

The first Windows installer lets you bring image prompts from NovelAI Inspect’s Simplified view into Reader, edit them, and send text to the fields you choose in CHAESSI PRESET.

| Component | Version and how to use it |
|---|---|
| Windows x64 Reader | 1.0.0. Per-user installer with Python and Tk included |
| Chrome extension | 0.3.1. Extract the ZIP and load the folder in Chrome 120 or later |
| Official CHAESSI PRESET | Start v3.8.5 x64 Portable first, then select its running window |

**First-time setup** starts in **Chrome connection setup → Copy connection key**. Save the key in the extension and grant NovelAI Inspect access. Reader reconnects automatically in the same Chrome profile.

**Editing and transfer** support Base and Character Positive/Undesired fields, the imported original, full or selected text, and Append or Replace across multiple destinations. Compare the current and final text in Preset, apply or cancel, and use Undo immediately after applying. Sending text does not save the draft or generate an image.

**When updating**, keep the same Chrome profile and reload the existing extension folder. Setup, usage and troubleshooting are available in three languages. [Installation and user guide](README.en.md) · [Third-party notices](THIRD-PARTY-NOTICES.md)

If you need help installing or pairing, copy the prompt under **Ask Claude or GPT to help with setup** in the installation guide into your AI chat. The assistant can help using its available tools. You enter the key locally and approve Chrome’s first permission request. [Copy the setup prompt](README.en.md)

## Verification scope

Before this documentation update, installation, launch, update, removal, reinstallation and settings retention were verified on Windows without Python or Node.js installed. First-time Chrome pairing with the final installer and ZIP remains unverified, as does the full sequence from Inspect import through apply and Undo in official CHAESSI PRESET 3.8.5. The complete online workflow on a fresh Windows system also remains unverified.

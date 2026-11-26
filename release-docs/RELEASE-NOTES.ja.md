# Chaessi Metadata Reader 1.1.0

Windows x64 · 2026-11-26 · ビルド `reader-20261126-01-public` · シーケンス `2026112601`

[公式 1.1.0 リリース](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.0) · [最新の安定版](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/latest) · [インストール・使い方](README.ja.md) · [AI セットアップ支援の依頼文](README.ja.md#ai-setup)

- **公式署名付きパッケージの検証。** PUBLIC 本番信頼で発行者キー、署名、有効期間、失効、受理済み最高シーケンス、全リソース、実際の受信プロセスとソケットを確認します。試験キーや任意の署名なし PRIVATE ビルドは受け付けません。署名付き Portable の EXE と署名・キーファイル4個を一緒に保管してください。新しい Preset 公開版がすでに発行されたという案内ではありません。
- **従来の公式 3.8.5 に対応。** 2026-11-23 修正版の公式 CHAESSI PRESET 3.8.5 Portable、`chaessi.prompt-transfer/1`、リクエストごとの nonce/HMAC 認証を維持します。Base/Character Positive/Undesired を選び、プリセットでプレビュー、キャンセル、適用、Undo を行います。転送は保存、History 記録、画像生成を実行しません。
- **Setup を一本化。** `Chaessi-Metadata-Reader-Setup-x64.exe` で `D:\MApp\Chaessi Reader` への新規インストールと、許可された正確な公式 1.0.x/D 移行版 `2026112502` からの更新を行います。任意のフォルダー、混在・改変されたファイル、不明なビルドは拒否します。先に通常の手順でリーダーを閉じてください。設定、接続、登録と Chrome 拡張機能 **0.3.1** は保持します。拡張機能の初回のみ ZIP を固定フォルダーに展開し、ユーザーが Chrome で読み込みと初回権限を確認してください。
- **復旧と旧インストーラーの注意。** 中断後は同じ Setup を再実行して復旧の案内に従ってください。競合が出たらファイルと記録を保持してください。保護のない旧インストーラーを後で実行することまで防げないため、古い Setup で上書きしないでください。Windows インストーラーにはコード署名がありません。ファイル名と SHA-256 を照合し、セキュリティー方針を守ってください。

## 既知の制限と検証範囲

以前の隔離署名候補では、プレビュー転送が約 **6.97秒**、全体認証が約 **14.35秒**でした。今回の公開版の保証時間ではなく、環境により待ち時間が変わります。起動直後の検出が失敗したら、画面の準備ができてから接続を再試行してください。従来のインストール、D 更新、ロールバック、削除、UI、転送、オフライン PNG の証拠を再利用しました。最新候補でオンライン Chrome/NovelAI Inspect の取り込み全体は再試験していません。未受信の失効情報、ローカル時計と同じユーザーが書き込める保存領域の破損は運用上の制限です。

[以前の 1.0.1](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.1) · [1.0.0 ビルド 2026112401](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0%2B2026112401) · [1.0.0 基準版](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0)

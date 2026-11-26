"""Reader presentation strings and a language-only, per-user preference."""
import json
import os
from pathlib import Path
import re
import tempfile


LANGUAGE_NAMES = {"ko": "한국어", "en": "English", "ja": "日本語"}
LOCALES = tuple(LANGUAGE_NAMES)
COMMON = {
    "ui.yes": ("확인", "Confirm", "確認"),
    "ui.cancel": ("취소", "Cancel", "キャンセル"),
    "ui.close": ("닫기", "Close", "閉じる"),
    "ui.help": ("도움말", "Help", "ヘルプ"),
    "ui.about": ("앱 정보", "About", "このアプリについて"),
    "ui.diagnostic": ("작업을 완료할 수 없습니다.", "The operation could not be completed.", "操作を完了できませんでした。"),
}


class Language:
    def __init__(self, preference_path=None):
        from bundle.reader_strings import STRINGS as reader
        from bundle.transfer_strings import STRINGS as transfer
        self._strings = {**COMMON, **reader, **transfer}
        self.path = Path(preference_path) if preference_path is not None else (
            Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / ".config"
        ) / "CHAESSI" / "MetadataReader" / "language.json"
        self.lang = "ko"
        self._listeners = []
        try:
            with self.path.open("rb") as file:
                data = json.loads(file.read(129))
            if isinstance(data, dict) and data.get("language") in LOCALES:
                self.lang = data["language"]
        except (OSError, ValueError, RecursionError):
            pass

    def t(self, key, **values):
        template = self._strings[key][LOCALES.index(self.lang)]
        return template.format(**values)

    def set(self, lang):
        if lang not in LOCALES:
            raise ValueError("Unsupported language")
        if lang == self.lang:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".language-", delete=False) as file:
                temp = Path(file.name)
                json.dump({"language": lang}, file)
            os.replace(temp, self.path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        self.lang = lang
        for callback in self._listeners.copy():
            callback()

    def subscribe(self, callback):
        self._listeners.append(callback)
        def unsubscribe():
            if callback in self._listeners:
                self._listeners.remove(callback)
        return unsubscribe

    def diagnostic(self, message):
        message = str(message)
        if self.lang == "ko":
            return message
        entry = DIAGNOSTICS.get(message)
        if entry is not None:
            return entry[0 if self.lang == "en" else 1]
        if not message:
            return ""
        code = re.match(r"\[(?:WinError|Errno) (\d+)\]", message)
        if code:
            return f"{self.t('ui.diagnostic')} ({code[0]})"
        for pattern, en, ja in DIAGNOSTIC_PATTERNS:
            match = re.fullmatch(pattern, message)
            if match:
                return (en if self.lang == "en" else ja).format(*match.groups())
        return self.t("ui.diagnostic")


DIAGNOSTIC_PATTERNS = (
    (r"JSON 문법 오류 · (\d+)행 (\d+)열", "Invalid JSON at line {0}, column {1}.", "JSONの{0}行目、{1}列目に構文エラーがあります。"),
    (r"이 파일 형식은 (\d+) MiB까지 열 수 있습니다\.", "This file type is limited to {0} MiB.", "この形式は{0} MiBまで開けます。"),
    (r"(.+)에 JSON 객체가 필요합니다\.", "{0} must contain a JSON object.", "{0}にはJSONオブジェクトが必要です。"),
    (r"(.+)의 JSON을 읽을 수 없습니다\.", "The JSON in {0} could not be read.", "{0}内のJSONを読み込めませんでした。"),
    (r"(.+)에 문자열이 필요합니다\.", "{0} must contain text.", "{0}には文字列が必要です。"),
    (r"(.+)에 복사할 수 없는 문자가 있습니다\.", "{0} contains a character that cannot be copied.", "{0}にコピーできない文字があります。"),
    (r"한 이미지에서 (\d+)개까지 캐릭터를 읽을 수 있습니다\.", "Up to {0} characters can be imported per image.", "1枚の画像から取り込めるキャラクターは{0}人までです。"),
    (r"작품당 (\d+)개까지 이미지를 읽을 수 있습니다\.", "Up to {0} images can be imported per post.", "1つの投稿から取り込める画像は{0}枚までです。"),
)


# Only program-emitted diagnostics are passed here. Never pass user prompt text.
DIAGNOSTICS = {
    "보호된 복사를 준비할 수 없습니다.": ("Could not prepare protected clipboard copying.", "保護されたクリップボードへのコピーを準備できません。"),
    "실행 파일을 확인한 뒤 실행을 승인하세요.": ("Review the executable and confirm before launching it.", "実行ファイルを確認してから起動を承認してください。"),
    "이 PC의 EXE 파일을 선택하세요.": ("Choose an EXE file on this computer.", "このPCのEXEファイルを選んでください。"),
    "JSON은 8 MiB까지 열 수 있습니다.": (
        "JSON files may be up to 8 MiB.",
        "JSONファイルは8 MiBまで開けます。"),
    "UTF-8 JSON 파일을 선택해 주세요.": (
        "Choose a JSON file encoded in UTF-8.",
        "UTF-8形式のJSONファイルを選んでください。"),
    "카드 상태 오류": (
        "The image record has an invalid status.",
        "画像データの状態が正しくありません。"),
    "카드 원문 오류": (
        "The image record has invalid source text.",
        "画像データの原文が正しくありません。"),
    "슬롯 목록 오류": (
        "The slot list is invalid.",
        "スロット一覧の形式が正しくありません。"),
    "구조 불일치": (
        "The prompt layout does not match the data.",
        "プロンプトの構成とデータが一致しません。"),
    "브라우저가 묶음 결과를 전달하지 못했습니다.": (
        "Chrome could not return the import result.",
        "Chromeから取り込み結果を受け取れませんでした。"),
    "연결 실패 · 다른 리더가 열려 있는지 확인하세요": (
        "Connection failed. Check for another Reader window.",
        "接続できません。別のリーダーが開いていないか確認してください。"),
    "char_captions에 배열이 필요합니다.": (
        "The char_captions field must contain a list.",
        "char_captions欄には配列が必要です。"),
    "노드 그래프 형식의 프롬프트는 지원하지 않습니다.": (
        "Node graph prompts cannot be imported.",
        "ノードグラフ形式のプロンプトには対応していません。"),
    "parameters에서 지원하는 SD 생성 정보 형식을 찾지 못했습니다.": (
        "No supported SD generation data was found in parameters.",
        "parameters欄に対応形式のSD生成情報が見つかりません。"),
    "images에 이미지 목록이 필요합니다.": (
        "The images field must contain an image list.",
        "images欄には画像の一覧が必要です。"),
    "메타데이터 객체 또는 이미지 배열을 선택해 주세요.": (
        "Choose a metadata object or a list of images.",
        "メタデータのオブジェクトまたは画像の配列を選んでください。"),
    "이미지 목록이 비어 있습니다.": (
        "The image list is empty.",
        "画像一覧が空です。"),
    "PNG 텍스트가 허용 크기를 초과했습니다.": (
        "The PNG text exceeds the size limit.",
        "PNGに含まれるテキストが上限を超えています。"),
    "64 MiB 이하의 PNG를 선택해 주세요.": (
        "Choose a PNG up to 64 MiB.",
        "64 MiB以下のPNGを選んでください。"),
    "PNG 파일 서명을 확인할 수 없습니다.": (
        "The file is missing a valid PNG signature.",
        "PNGファイルのシグネチャを確認できませんでした。"),
    "PNG 청크 수가 허용 범위를 초과했습니다.": (
        "The PNG has too many data chunks.",
        "PNGのデータチャンク数が上限を超えています。"),
    "PNG 텍스트 청크를 읽을 수 없습니다.": (
        "The PNG text chunk could not be read.",
        "PNGのテキストチャンクを読み込めませんでした。"),
    "PNG 청크 길이, 무결성 또는 끝 표시를 확인할 수 없습니다.": (
        "The PNG has an invalid chunk length, checksum or end marker.",
        "PNGのチャンク長、チェックサム、終端のいずれかを確認できませんでした。"),
    "전송 형식 또는 목적지를 확인하세요.": (
        "Check the transfer format and destination field.",
        "送る内容の形式と送信先の欄を確認してください。"),
    "프리셋 인스턴스 인증에 실패했습니다.": (
        "The Preset window could not be authenticated.",
        "プリセットのウィンドウを認証できませんでした。"),
    "프리셋에서 이 요청을 찾지 못했습니다.": (
        "Preset could not find this request.",
        "プリセットにこのリクエストが見つかりません。"),
    "프리셋에서 다른 미리보기를 처리 중입니다.": (
        "Preset is already reviewing another request.",
        "プリセットで別の変更内容を確認中です。"),
    "프리셋 초안이 변경됐습니다. 대상을 새로고침하고 다시 지정하세요.": (
        "The draft changed. Refresh the fields and choose the destination again.",
        "下書きが変わりました。送信先を更新し、欄を選び直してください。"),
    "같은 요청 번호에 다른 내용이 등록돼 있습니다.": (
        "This request ID is already in use for different text.",
        "同じリクエスト番号に別の内容が登録されています。"),
    "프리셋이 아직 준비되지 않았습니다.": (
        "Preset is still starting. Try again when it is ready.",
        "プリセットを準備中です。起動が終わってから再試行してください。"),
    "전송할 문구가 허용 크기를 초과합니다.": (
        "The text exceeds the transfer size limit.",
        "送るテキストが上限を超えています。"),
    "프리셋 요청 시간이 만료됐습니다.": (
        "The Preset request expired.",
        "プリセットへのリクエストが期限切れになりました。"),
    "현재 초안의 항목 1~128개를 선택하세요.": (
        "Choose between 1 and 128 items for this draft.",
        "現在の下書きに送る項目を1～128件選んでください。"),
    "문구가 없는 항목입니다.": (
        "This item is missing its text field.",
        "この項目にはテキスト欄がありません。"),
    "CR 또는 CRLF를 프리셋에 그대로 표시할 수 없습니다. 편집창에서 해당 줄바꿈을 바꾼 뒤 다시 담으세요.": (
        "Preset cannot preserve CR or CRLF line endings. Change those line breaks in the editor, then add the text again.",
        "プリセットではCR・CRLF改行をそのまま表示できません。編集欄で該当の改行を直してから、もう一度追加してください。"),
    "표시할 수 없는 문자가 있습니다. 편집 후 다시 담으세요.": (
        "The text contains an unsupported character. Edit it and add it again.",
        "表示できない文字があります。編集してからもう一度追加してください。"),
    "항목 하나의 문구는 UTF-8 256 KiB까지 전송할 수 있습니다.": (
        "Each text item can contain up to 256 KiB of UTF-8 text.",
        "1項目のテキストはUTF-8で256 KiBまでです。"),
    "한 번에 전송할 수 있는 크기는 UTF-8 JSON 1 MiB입니다.": (
        "One transfer can contain up to 1 MiB of UTF-8 JSON.",
        "1回に送れるUTF-8 JSONの上限は1 MiBです。"),
    "프리셋 응답 서명을 확인할 수 없습니다.": (
        "The Preset response signature could not be verified.",
        "プリセットの応答の署名を確認できませんでした。"),
    "프리셋 응답 형식이 올바르지 않습니다.": (
        "The Preset response has an invalid format.",
        "プリセットの応答形式が正しくありません。"),
    "프리셋이 요청을 거부했습니다.": (
        "Preset declined the request.",
        "プリセットがリクエストを拒否しました。"),
    "선택한 프리셋과 응답한 인스턴스가 다릅니다.": (
        "A different Preset instance responded.",
        "選んだプリセットとは別のウィンドウが応答しました。"),
    "인증한 연결이 종료됐습니다.": (
        "The authenticated connection closed.",
        "認証済みの接続が閉じました。"),
    "프리셋 연결 또는 응답을 확인할 수 없습니다.": (
        "The Preset connection or response could not be verified.",
        "プリセットへの接続または応答を確認できませんでした。"),
    "현재 프리셋의 슬롯 목록을 확인할 수 없습니다.": (
        "The current Preset field list is unavailable.",
        "現在のプリセットの欄一覧を取得できませんでした。"),
    "목적지 형식이 올바르지 않습니다.": (
        "The destination field has an invalid format.",
        "送信先の欄の形式が正しくありません。"),
    "슬롯 번호나 사용 가능한 필드를 확인할 수 없습니다.": (
        "The slot numbers or available fields could not be verified.",
        "スロット番号または選べる欄を確認できませんでした。"),
    "Base 목적지가 없습니다.": (
        "The destination list has no Base field.",
        "送信先一覧にベースの欄がありません。"),
    "전송 요청의 상태를 확인할 수 없습니다.": (
        "The transfer status could not be verified.",
        "送信状況を確認できませんでした。"),
    "등록 경로의 소유자 또는 접근 권한을 확인하세요.": (
        "Check the owner and permissions of the registration folder.",
        "登録先の所有者とアクセス権を確認してください。"),
    "개인 전송 등록 경로에 다른 계정의 접근 권한이 있습니다.": (
        "Another account has access to the private transfer registration.",
        "専用の転送登録先に別のアカウントのアクセス権があります。"),
    "이 PC의 절대 경로를 선택하세요.": (
        "Choose an absolute path on this PC.",
        "このPCの絶対パスを選んでください。"),
    "등록 경로를 확인하세요.": (
        "Check the registration path.",
        "登録先のパスを確認してください。"),
    "로컬 드라이브에서만 프리셋을 연결할 수 있습니다.": (
        "Choose a Preset installation on a local drive.",
        "ローカルドライブにあるプリセットを選んでください。"),
    "연결 경로에 링크 또는 잘못된 파일 형식이 있습니다.": (
        "The connection path contains a link or an unexpected file type.",
        "接続先のパスにリンクまたは対応していない種類のファイルがあります。"),
    "프리셋 등록 파일이 너무 큽니다.": (
        "The Preset registration file is too large.",
        "プリセットの登録ファイルが大きすぎます。"),
    "프리셋 등록 파일을 읽을 수 없습니다.": (
        "The Preset registration file could not be read.",
        "プリセットの登録ファイルを読み込めませんでした。"),
    "등록된 프리셋 인스턴스가 너무 많습니다.": (
        "Too many Preset instances are registered.",
        "登録されたプリセットの数が多すぎます。"),
    "시간 안에 등록된 인스턴스를 모두 확인할 수 없습니다. 다시 연결하세요.": (
        "Checking all registered instances timed out. Connect again.",
        "時間内に登録済みのプリセットをすべて確認できませんでした。接続し直してください。"),
    "프리셋 인스턴스 등록 정보가 올바르지 않습니다.": (
        "The Preset instance registration is invalid.",
        "プリセットの登録情報が正しくありません。"),
    "Chaessi Preset Transfer PRIVATE.exe 파일을 선택하세요.": (
        "Choose Chaessi Preset Transfer PRIVATE.exe.",
        "Chaessi Preset Transfer PRIVATE.exe を選んでください。"),
    "선택한 PRIVATE 실행 파일이 변경됐습니다. 다시 선택하세요.": (
        "The selected PRIVATE executable changed. Choose it again.",
        "選んだPRIVATE実行ファイルが変わりました。選び直してください。"),
    "연결 종료": (
        "Disconnected",
        "切断されました"),
    "연결됨": (
        "Connected",
        "接続済み"),
    "Chrome 실행 필요": (
        "Open Chrome",
        "Chromeを起動してください"),
    "Chrome 확장 확인 필요": (
        "Check the Chrome extension",
        "Chrome拡張機能を確認してください"),
    "연결 복구 중": (
        "Reconnecting",
        "再接続中"),
    "승인된 aitag.win 작품 링크가 아닙니다.": (
        "Choose a supported aitag.win post link.",
        "対応しているaitag.winの投稿リンクを選んでください。"),
    "사이트가 접근 확인을 요구합니다. Chrome 작품 탭에서 상태를 확인하세요.": (
        "The site requires an access check. Open the post in Chrome and check its status.",
        "サイトのアクセス確認が必要です。Chromeで投稿を開いて状態を確認してください。"),
    "수집 중 작품 주소 또는 화면이 바뀌었습니다.": (
        "The post URL or page changed during import.",
        "取り込み中に投稿のURLまたは画面が変わりました。"),
    "수집 전용 Chrome 탭과 확장의 aitag.win 사이트 접근 권한을 확인하세요.": (
        "Check the import tab and the extension’s access to aitag.win in Chrome.",
        "Chromeの取り込み用タブと、拡張機能のaitag.winへのアクセス権を確認してください。"),
    "작품의 공식 복사 화면 또는 형식을 확인할 수 없습니다.": (
        "The post's copy control or format could not be identified.",
        "投稿のコピー画面または形式を確認できませんでした。"),
    "현재 aitag.win의 공식 복사 기능 버전을 지원하지 않습니다. 리더와 Chrome 확장의 업데이트를 확인하세요.": (
        "This version of the site's copy control is unsupported. Check for Reader and Chrome extension updates.",
        "サイトのコピー機能が未対応のバージョンです。リーダーとChrome拡張機能の更新を確認してください。"),
    "공식 복사 동작을 격리할 수 없습니다.": (
        "The site's copy action could not be isolated.",
        "サイトのコピー操作を分離できませんでした。"),
    "시간 안에 작품의 이미지 목록을 확인하지 못했습니다.": (
        "The post's image list did not appear in time.",
        "時間内に投稿の画像一覧を確認できませんでした。"),
    "작품의 이미지 목록이 아직 준비되지 않았습니다.": (
        "The post's image list is still loading.",
        "投稿の画像一覧を読み込み中です。"),
    "묶음의 수집 크기 또는 이미지 수 제한을 넘었습니다.": (
        "The post exceeds the import size or image count limit.",
        "取り込めるデータのサイズまたは画像数の上限を超えました。"),
    "이미 처리한 요청입니다. 리더에서 다시 요청하세요.": (
        "This request was already handled. Start a new import in Reader.",
        "処理済みのリクエストです。リーダーから取り込み直してください。"),
    "로컬 리더 연결을 확인하세요.": (
        "Check the connection to Reader on this PC.",
        "このPCのリーダーとの接続を確認してください。"),
    "연결 키를 확인하세요.": (
        "Check the extension's pairing key.",
        "拡張機能の接続キーを確認してください。"),
    "Chrome 확장 연결 탭에서 NovelAI Inspect 접근을 허용하세요.": (
        "Allow access to NovelAI Inspect in the extension’s connection tab.",
        "Chrome拡張機能の接続タブでNovelAI Inspectへのアクセスを許可してください。"),
    "Chrome에 이전 확장 설정이 남아 있습니다. 확장 관리에서 ‘채씨 메타데이터 리더 연결’을 새로고침한 뒤 연결 탭을 다시 여세요.": (
        "Chrome still has the previous extension settings. Reload the Reader extension on the extensions page, then reopen its connection tab.",
        "Chromeに以前の拡張機能の設定が残っています。拡張機能管理でリーダーの拡張機能を再読み込みし、接続タブを開き直してください。"),
    "Chrome이 NovelAI 접근을 허용하지 않았습니다. 연결 탭의 권한 요청 결과를 확인하세요.": (
        "Chrome did not grant access to NovelAI. Check the permission result in the extension's connection tab.",
        "ChromeがNovelAIへのアクセスを許可しませんでした。接続タブの権限リクエストの結果を確認してください。"),
    "Chrome에서 NovelAI 권한 요청에 오류가 발생했습니다. 연결 탭에 표시된 Chrome 오류를 확인하세요.": (
        "Chrome could not request access to NovelAI. Read the Chrome error in the connection tab.",
        "ChromeでNovelAIへのアクセス許可を要求できませんでした。接続タブに表示されたChromeのエラーを確認してください。"),
    "Chrome에서 NovelAI Inspect를 열고 이미지를 선택하세요.": (
        "Open NovelAI Inspect in Chrome and select an image.",
        "ChromeでNovelAI Inspectを開き、画像を選んでください。"),
    "Inspect 탭이 여러 개입니다. 가져올 Inspect 탭을 활성화한 뒤 다시 시도하세요.": (
        "Several Inspect tabs are open. Activate the tab to import and try again.",
        "Inspectタブが複数あります。取り込みたいタブを選び、もう一度試してください。"),
    "Inspect에서 이미지의 Simplified 메타데이터를 확인한 뒤 다시 시도하세요.": (
        "Check the image’s Simplified metadata in Inspect, then try again.",
        "Inspectで画像のSimplifiedメタデータを確認してから再試行してください。"),
    "Inspect에서 NovelAI가 생성한 이미지의 메타데이터를 확인하세요.": (
        "Check the metadata of a NovelAI-generated image in Inspect.",
        "InspectでNovelAIが生成した画像のメタデータを確認してください。"),
    "Inspect의 Simplified 필드 구성을 확인할 수 없습니다.": (
        "The Simplified fields in Inspect could not be identified.",
        "InspectのSimplifiedの欄を確認できませんでした。"),
    "Inspect의 대화상자를 닫은 뒤 다시 시도하세요.": (
        "Close the dialog in Inspect and try again.",
        "Inspectのダイアログを閉じてから再試行してください。"),
    "가져오는 동안 Inspect 탭 또는 이미지가 바뀌었습니다. 다시 시도하세요.": (
        "The Inspect tab or image changed during import. Try again.",
        "取り込み中にInspectタブまたは画像が変わりました。もう一度試してください。"),
    "https://aitag.win/i/작품번호 형식의 주소를 입력하세요.": (
        "Enter a post link in the form https://aitag.win/i/post-number.",
        "https://aitag.win/i/投稿番号 の形式でリンクを入力してください。"),
    "Chrome 연결을 열지 못했습니다. 다른 리더나 Stage1 실행기가 열려 있는지 확인하세요.": (
        "The Chrome connection could not be opened. Check for another running Reader.",
        "Chrome接続を開けませんでした。別のリーダーが開いていないか確認してください。"),
    "Chrome 연결을 열지 못했습니다. 다른 리더나 시험기를 종료한 뒤 다시 시도하세요.": (
        "The Chrome connection could not be opened. Close any other Reader or test instance, then try again.",
        "Chrome接続を開けませんでした。他のリーダーやテスト用のリーダーを閉じてから再試行してください。"),
    "로컬 Chrome 연결 키 형식이 올바르지 않습니다.": (
        "The local Chrome pairing key is invalid.",
        "ローカルのChrome接続キーの形式が正しくありません。"),
    "다른 묶음을 수집하는 중입니다.": (
        "Another import is in progress.",
        "別の取り込みを処理しています。"),
    "Chrome 연결 또는 작품 수집 시간이 초과됐습니다. Chrome 확장과 작품 접근 상태를 확인하세요.": (
        "The Chrome connection or import timed out. Check the extension and access to the post.",
        "Chrome接続または取り込みが時間切れになりました。拡張機能と投稿へのアクセスを確認してください。"),
    "Chrome 연결이 끊겼습니다. 자동 복구 후 다시 가져오세요.": (
        "Chrome disconnected. Import again after it reconnects.",
        "Chromeとの接続が切れました。自動再接続後にもう一度取り込んでください。"),
    "이 복사 기능은 Windows에서 사용할 수 있습니다.": (
        "Clipboard copying is available on Windows.",
        "クリップボードへのコピーはWindowsで利用できます。"),
    "복사할 텍스트가 없습니다.": (
        "There is no text to copy.",
        "コピーするテキストがありません。"),
    "원문에 NUL 문자가 있어 Windows 클립보드에 그대로 복사할 수 없습니다.": (
        "The original contains a NUL character that Windows Clipboard cannot preserve.",
        "原文にNUL文字があり、Windowsのクリップボードにそのままコピーできません。"),
    "원문에 불완전한 유니코드 문자가 있어 복사할 수 없습니다.": (
        "An incomplete Unicode character prevents copying.",
        "不完全なUnicode文字があるためコピーできません。"),
    "복사에 사용할 창을 찾을 수 없습니다.": (
        "The window for copying could not be found.",
        "コピーに使用するウィンドウが見つかりません。"),
    "복사할 메모리를 확보할 수 없습니다.": (
        "There is not enough memory to copy the text.",
        "コピー用のメモリを確保できませんでした。"),
    "복사할 메모리를 열 수 없습니다.": (
        "The clipboard memory could not be opened.",
        "コピー用のメモリを開けませんでした。"),
    "복사할 메모리를 준비할 수 없습니다.": (
        "The clipboard memory could not be prepared.",
        "コピー用のメモリを準備できませんでした。"),
    "클립보드를 열 수 없습니다. 잠시 후 다시 복사해 주세요.": (
        "The clipboard is busy. Try copying again shortly.",
        "クリップボードを開けません。少し待ってからコピーしてください。"),
    "Windows 클립보드에 원문을 기록할 수 없습니다.": (
        "The original text could not be written to Windows Clipboard.",
        "原文をWindowsのクリップボードに書き込めませんでした。"),
    "Windows 클립보드를 닫을 수 없습니다.": (
        "The Windows clipboard could not be closed.",
        "Windowsのクリップボードを閉じられませんでした。"),
    "Windows에서 그대로 복사할 수 없는 문자열입니다.": (
        "Windows cannot copy this string exactly.",
        "Windowsでそのままコピーできない文字列です。"),
    "지원하지 않는 묶음 파일입니다.": (
        "This bundle file is unsupported.",
        "この形式のファイルには対応していません。"),
    "묶음의 전체 이미지 수 또는 카드 목록을 확인할 수 없습니다.": (
        "The total image count or card list is invalid.",
        "画像の総数または一覧を確認できませんでした。"),
    "PNG는 32 MiB까지 읽을 수 있습니다.": (
        "PNG files may be up to 32 MiB.",
        "PNGファイルは32 MiBまで読み込めます。"),
    "로컬 JSON은 UTF-8 파일만 지원합니다.": (
        "Choose a local JSON file encoded in UTF-8.",
        "UTF-8形式のローカルJSONを選んでください。"),
    "JSON 파일은 8 MiB까지 열 수 있습니다.": (
        "JSON files may be up to 8 MiB.",
        "JSONファイルは8 MiBまで開けます。"),
    "JSON 중첩이 너무 깊습니다.": (
        "The JSON nesting is too deep.",
        "JSONの入れ子が深すぎます。"),
    "묶음 파일은 16 MiB까지 열 수 있습니다.": (
        "Bundle files may be up to 16 MiB.",
        "まとめて取り込むファイルは16 MiBまで開けます。"),
    "일반 JSON 파일은 8 MiB까지 열 수 있습니다.": (
        "Standard JSON files may be up to 8 MiB.",
        "通常のJSONファイルは8 MiBまで開けます。"),
}

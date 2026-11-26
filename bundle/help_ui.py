"""Offline reader guide. Button names are rendered from the live UI catalog."""
import re
import tkinter as tk
from tkinter import ttk

from bundle.i18n import LOCALES
from bundle.ui import BG, CYAN, INPUT, LINE, TEXT, font

# Each paragraph is a step. References such as {reader.inspect} follow the app's wording.
CHAPTERS = {
    "start": (
        ("처음 사용하기", "Windows 시작 메뉴에서 Chaessi Metadata Reader를 열고 ‘{setup.title}’을 누르세요. 처음에는 확장 ZIP을 설치하고 연결키를 등록해야 합니다.\n\nChrome에서 NovelAI Inspect를 열어 이미지를 선택하세요. 리더에서 ‘{reader.inspect}’를 누르면 원문과 베이스·캐릭터의 편집 칸이 표시됩니다. 필요한 글을 담아 ‘{send.title}’에서 받을 칸을 고를 수 있습니다."),
        ("Getting started", "Open Chaessi Metadata Reader from the Windows Start menu and choose “{setup.title}”. On first use, install the extension ZIP and pair it with the key.\n\nIn Chrome, open NovelAI Inspect and choose your image. In Reader, choose “{reader.inspect}” to see the original text and edit the Base and Character fields. Queue the text you want and choose its destination in “{send.title}”."),
        ("はじめに", "WindowsのスタートメニューからChaessi Metadata Readerを開き、「{setup.title}」を選びます。初回は拡張機能のZIPを展開して読み込み、接続キーを登録します。\n\nChromeでNovelAI Inspectを開き、画像を選びます。リーダーで「{reader.inspect}」を押すと、原文とベース・キャラクター別の編集欄が表示されます。必要な文章を一覧に追加し、「{send.title}」で送信先を選びます。"),
    ),
    "chrome": (
        ("Chrome 연결하기", "{setup.steps}\n\n업데이트한 경우 같은 Chrome 프로필과 기존 확장 폴더를 사용하세요. ‘{setup.import}’로 이전 리더의 키를 가져올 수 있습니다. 예전 리더가 실행 중이면 작업을 마치고 닫은 뒤 연결을 다시 시도하세요. 자동 재연결은 30초 이상 걸릴 수 있습니다."),
        ("Connecting Chrome", "{setup.steps}\n\nFor an update, keep the same Chrome profile and extension folder. Use “{setup.import}” to reuse an existing Reader key. If an older Reader is running, finish your work, close it, and retry the connection. Automatic reconnection can take 30 seconds or more."),
        ("Chromeに接続する", "{setup.steps}\n\n更新時は同じChromeプロファイルと拡張機能のフォルダーを使います。「{setup.import}」で以前のキーを引き継げます。古いリーダーが起動中の場合は作業を終えて閉じ、再接続してください。自動再接続には30秒以上かかる場合があります。"),
    ),
    "inspect": (
        ("Inspect에서 가져오기", "1. Chrome에서 https://novelai.net/inspect 를 엽니다. 읽을 이미지를 Inspect에 넣고 Simplified에 글이 보이는지 확인합니다.\n\n2. 리더 위쪽의 ‘{reader.inspect}’를 누릅니다. Inspect 탭이 여러 개라면 가져올 탭을 Chrome에서 먼저 선택합니다.\n\n3. ‘{reader.images}’에서 이미지를 선택합니다. 가운데에 그 이미지의 프롬프트가 나타납니다. 다른 이미지를 Inspect에 넣으면 가져오기 버튼을 다시 누릅니다."),
        ("Importing from Inspect", "1. In Chrome, open https://novelai.net/inspect. Add the image you want to read and look for its text under Simplified.\n\n2. At the top of Reader, choose “{reader.inspect}”. If several Inspect tabs are open, select the right one in Chrome first.\n\n3. Choose an image under “{reader.images}”. Its prompt appears in the editor. After putting a different image in Inspect, import again."),
        ("Inspectから取り込む", "1. Chromeで https://novelai.net/inspect を開きます。読み取りたい画像を入れ、Simplifiedに文章が表示されることを確認します。\n\n2. リーダーの上部で「{reader.inspect}」を押します。Inspectタブが複数ある場合は、先にChromeで取り込みたいタブを選びます。\n\n3. 「{reader.images}」から画像を選ぶと、中央にプロンプトが表示されます。Inspectの画像を入れ替えたら、もう一度取り込んでください。"),
    ),
    "edit": (
        ("문구 편집하기", "1. ‘{reader.base}’는 그림 전체에 관한 글이고 각 캐릭터 칸에는 인물별 글이 있습니다. ‘{reader.positive}’는 넣고 싶은 요소, ‘{reader.undesired}’는 피하고 싶은 요소를 적는 칸입니다.\n\n2. 가운데 칸을 클릭해 글을 고칩니다. 가져온 원문은 따로 보관합니다. 다른 이미지를 골랐다 돌아와도 고친 내용이 남습니다. ‘{reader.restore}’로 그 칸만 처음 상태로 돌릴 수 있습니다.\n\n3. ‘{reader.copy}’는 지금 보이는 글을 복사합니다. 가져온 내용을 확인하려면 ‘{reader.show_raw}’를 누릅니다. ‘{reader.raw_copy}’는 원래 글을 복사합니다."),
        ("Editing a prompt", "1. “{reader.base}” describes the whole image. Character fields hold words for each person. “{reader.positive}” lists things to include. “{reader.undesired}” lists things to avoid.\n\n2. Click a field and edit it. Reader keeps the original separately. Your edits stay when you switch images. “{reader.restore}” returns just this field to its imported text.\n\n3. “{reader.copy}” copies the text as it is now. To inspect the imported data, choose “{reader.show_raw}”. “{reader.raw_copy}” copies the original."),
        ("文章を編集する", "1. 「{reader.base}」は画像全体の説明です。キャラクター欄には人物ごとの説明があります。「{reader.positive}」には入れたいものを、「{reader.undesired}」には避けたいものを書きます。\n\n2. 中央の欄をクリックして文章を直します。取り込んだ原文は別に保たれます。画像を切り替えて戻っても編集内容は残ります。「{reader.restore}」を押すと、その欄だけ元に戻ります。\n\n3. 「{reader.copy}」は現在の文章をコピーします。取り込んだ内容を見るには「{reader.show_raw}」を押します。「{reader.raw_copy}」で原文をコピーできます。"),
    ),
    "send": (
        ("프리셋으로 보내기", "1. 보낼 글을 마우스로 끌어 선택한 다음 ‘{reader.select}’를 누릅니다. 한 칸을 통째로 담으려면 ‘{reader.full}’를 누릅니다. 담은 뒤 편집해도 담아 둔 글은 그대로입니다.\n\n2. 숫자가 붙은 ‘{send.title}’를 엽니다. 처음에는 ‘{send.preset_file}’로 공식 Portable을 확인합니다. ‘{send.connect}’로 지정한 프리셋에 연결할 수 있습니다.\n\n3. ‘{send.list}’에서 한 행을 고른 뒤 ‘{send.destination}’의 화살표를 누릅니다. 원하는 칸을 고르면 그 행에 바로 표시됩니다. 받을 칸은 가져온 칸과 달라도 됩니다.\n\n4. ‘{send.append}’는 기존 글 끝에 붙입니다. 양쪽에 글이 있으면 쉼표와 공백으로 잇습니다. ‘{send.replace}’는 그 칸의 글을 새 글로 바꿉니다.\n\n5. 모든 행의 받을 칸을 지정하고 ‘{send.action}’를 누릅니다. 목록 전체를 위에서부터 보냅니다. 한 문구만 보내려면 나머지는 목록에서 빼세요. 원문과 편집창은 그대로 남습니다. 프리셋에서 현재 문구와 적용 후 문구를 살펴보고 ‘초안에 적용’ 또는 ‘취소’를 누릅니다."),
        ("Sending to Preset", "1. Drag to highlight the words you want, then choose “{reader.select}”. For the whole field, choose “{reader.full}”. Each item keeps the words you added even if you edit the field later.\n\n2. Open “{send.title}” beside the item count. On first use, confirm the official Portable with “{send.preset_file}”. Connect to the chosen app with “{send.connect}”.\n\n3. Select a row in “{send.list}”, open the arrow under “{send.destination}” and choose a field. The row updates immediately. You can choose a different field from the one you imported.\n\n4. “{send.append}” adds your words at the end. If both parts have text, a comma and a space separate them. “{send.replace}” puts your text in place of the current text.\n\n5. Assign a destination to every row and choose “{send.action}”. All items are sent from top to bottom. To send just one, remove the other items from the list; the originals and editor fields stay unchanged. In Preset, read Current text and Final text, then choose Apply to draft or Cancel."),
        ("プリセットに送る", "1. 送りたい文章をドラッグして「{reader.select}」を押します。欄全体を送るには「{reader.full}」を押します。後で編集しても、一覧に追加済みの文章は変わりません。\n\n2. 件数が付いた「{send.title}」を開きます。初回は「{send.preset_file}」で公式Portableを選んで確認します。「{send.connect}」で指定したアプリに接続できます。\n\n3. 「{send.list}」の行を選び、「{send.destination}」の矢印から欄を選びます。選んだ欄がその行にすぐ表示されます。取り込み元と違う欄にも送れます。\n\n4. 「{send.append}」は今ある文の末尾に追加します。両方に文があるときはコンマと半角スペースで区切ります。「{send.replace}」はその欄の文を送る文に置き換えます。\n\n5. すべての行に送信先を指定して「{send.action}」を押すと、一覧の全項目を上から順に送ります。1件だけ送るには、他の項目を一覧から外します。原文と編集欄はそのまま残ります。プリセットで現在のテキストと適用後のテキストを読み、「下書きに適用」または「キャンセル」を選びます。"),
    ),
    "notes": (
        ("알아두기", "전송 순서는 ‘{send.up}’·‘{send.down}’으로 바꿀 수 있습니다. 같은 칸에 여러 문구를 보내면 위에서부터 적용합니다. 새 캐릭터 번호는 건너뛰어도 됩니다. 필요한 중간 슬롯은 빈 꺼짐 상태로 만들며, 실제 번호와 생성 범위를 프리셋 미리보기에서 확인합니다. 빈 문구로 기존 글을 지울 때만 별도 확인합니다. 공식 프리셋 v3.8.5는 2026-11-23 수정본을 사용하세요.\n\n적용하면 프리셋 초안이 바뀝니다. 저장하고 싶을 때만 그 앱의 ‘프리셋 저장’을 누릅니다. 적용을 되돌리려면 ‘리더 전송 되돌리기’를 누릅니다. 전송은 이미지 생성을 실행하지 않습니다.\n\n리더를 닫거나 새 자료로 바꾸면 이번 편집과 보낼 문구가 사라질 수 있습니다. 필요한 문구를 먼저 복사하거나 프리셋에서 직접 저장하세요. 연결 결과가 불분명하면 ‘{send.check}’를 누릅니다. 다시 선택하라고 표시된 행은 받을 칸을 확인합니다."),
        ("Before you close", "Use “{send.up}” and “{send.down}” to change the order. Items going to the same field are applied from top to bottom. New character numbers may skip positions. Any intervening slots are created empty and Off; review the actual numbers and creation range in Preset. Clearing existing text requires separate confirmation. Use the official 2026-11-23 corrected Preset v3.8.5 build.\n\nApplying changes updates the Preset draft. To keep it, choose Save Preset in that app. To undo the change, choose Undo Reader transfer. Sending text does not generate an image.\n\nClosing Reader or importing new data can discard your edits and list. Copy text you need or save the draft in Preset first. If the transfer result is unclear, choose “{send.check}”. Recheck any row marked as needing a destination."),
        ("覚えておくこと", "「{send.up}」「{send.down}」で順番を変えられます。同じ欄に送る文章は上から順に反映されます。新規キャラクターの番号は飛ばせます。途中の枠は空のオフ状態で作成されるため、実際の番号と作成範囲をプリセットのプレビューで確認します。既存の文を空にするときだけ別途確認します。公式プリセットv3.8.5は2026-11-23修正版を使用してください。\n\n適用するとプリセットの下書きが変わります。保存したいときに「プリセットを保存」を押してください。元に戻すには「リーダー転送を元に戻す」を押します。テキストを送っても画像生成は始まりません。\n\nリーダーを閉じたり、新しいデータを開いたりすると、今回の編集内容と一覧が消えることがあります。必要な文は先にコピーするか、プリセットで下書きを保存してください。結果が不明なときは「{send.check}」を押します。再選択が必要と表示された行は、送信先を確認してください。"),
    ),
    "web": (
        ("웹 게시물 가져오기 · aitag.win", "1. Chrome에서 읽으려는 aitag.win 공개 게시물을 엽니다. 주소가 https://aitag.win/i/숫자 형태인지 확인하고 링크를 복사합니다.\n\n2. 리더의 ‘{reader.link}’에 붙여넣고 ‘{reader.web}’를 누릅니다. 사이트 접근 확인이 뜨면 Chrome 게시물 탭에서 확인한 뒤 다시 가져옵니다.\n\n3. 왼쪽에서 이미지를 선택합니다. 원문을 제공하는 이미지는 Inspect 이미지와 같은 방법으로 편집하고 보낼 수 있습니다. 누락된 필드는 표시되지 않습니다."),
        ("Importing a web post · aitag.win", "1. Open a public aitag.win post in Chrome. Copy its address, which should look like https://aitag.win/i/ followed by a number.\n\n2. Paste the link under “{reader.link}” and choose “{reader.web}”. If the site asks you to confirm access, complete that check in Chrome and import again.\n\n3. Select an image on the left. When source text is available, you can edit and send it just like text imported from Inspect. Missing fields are omitted."),
        ("ウェブ投稿の取り込み · aitag.win", "1. Chromeで読みたいaitag.winの公開投稿を開きます。https://aitag.win/i/ の後に数字が続くURLをコピーします。\n\n2. リーダーの「{reader.link}」に貼り付けて「{reader.web}」を押します。サイトのアクセス確認が出たら、Chromeの投稿タブで確認してから取り込み直します。\n\n3. 左側で画像を選びます。原文がある画像はInspectから取り込んだものと同じように編集して送れます。元データにない欄は表示されません。"),
    ),
    "about": (
        ("앱 정보", "채씨 메타데이터 리더 1.1.0 · Chrome 확장 0.3.1\n빌드 reader-20261126-01-public (2026112601)\n\nNovelAI Inspect에서 읽은 이미지의 프롬프트를 편집해 채씨 프리셋의 원하는 칸으로 보내는 Windows 도구입니다. 웹 게시물에서도 가져올 수 있습니다.\n\n채씨의 독립 도구입니다. NovelAI 서비스의 제휴 제품이 아닙니다. 리더에는 NovelAI 계정이나 API 토큰을 입력할 필요가 없습니다. UI 언어 설정은 이 PC에 보관합니다."),
        ("About", "Chaessi Metadata Reader 1.1.0 · Chrome extension 0.3.1\nBuild reader-20261126-01-public (2026112601)\n\nEdit image prompts imported from NovelAI Inspect and send any part to the field you choose in Chaessi Preset. You can also import text from supported web posts.\n\nAn independent Windows tool from Chaessi, unaffiliated with NovelAI. Reader does not require a NovelAI account or API token. Your interface language is saved on this PC."),
        ("このアプリについて", "Chaessi Metadata Reader 1.1.0 · Chrome 拡張機能 0.3.1\nビルド reader-20261126-01-public (2026112601)\n\nNovelAI Inspectから取り込んだ画像のプロンプトを編集し、Chaessi Presetで選んだ欄へ送るWindows用のツールです。対応しているウェブ投稿からも取り込めます。\n\nChaessiが開発する独立したツールです。NovelAIとの提携製品ではありません。リーダーにNovelAIのアカウントやAPIトークンを入力する必要はありません。表示言語はこのPCに保存されます。"),
    ),
    "connections": (
        ("프리셋 연결", "‘{send.title} → {send.preset_file}’에서 공식 CHAESSI PRESET v3.8.5 수정본의 "
         "Portable 파일을 한 번 선택하고 확인하세요. 다운로드한 Portable 파일을 선택하세요.\n\n"
         "‘{send.connect}’를 누르면 리더가 지정한 프로그램에 연결합니다. 프리셋이 꺼져 있으면 리더가 실행합니다. "
         "같은 프리셋을 다시 열면 보내기 창에서 자동으로 다시 연결을 시도합니다.\n\n"
         "파일을 옮기거나 지원되는 실행 파일로 교체했다면 ‘{send.preset_file}’을 다시 사용하세요. "
         "초안이나 슬롯이 바뀌면 리더가 받을 칸을 확인합니다. 다시 선택하라는 표시가 난 행의 받을 칸을 확인하세요."),
        ("Connecting a Preset", "In “{send.title} → {send.preset_file}”, choose and confirm the official corrected "
         "CHAESSI PRESET v3.8.5 Portable file once. Select the Portable download itself.\n\n"
         "“{send.connect}” connects to the chosen app or starts it if closed. The send window tries to reconnect "
         "when the same Preset app is open again.\n\n"
         "If the file moves or you replace it with a supported executable, use “{send.preset_file}” again. "
         "Reader rechecks destinations when the draft or slots change. Recheck any row marked as needing a destination."),
        ("プリセットの接続", "「{send.title} → {send.preset_file}」で、公式CHAESSI PRESET v3.8.5修正版の"
         "Portableファイルを一度選んで確認します。ダウンロードしたPortable本体を選んでください。\n\n"
         "「{send.connect}」を押すと、指定したアプリに接続します。起動していなければ起動します。"
         "同じプリセットを開き直すと、送信画面で再接続を試みます。\n\n"
         "ファイルを移動したり、対応する実行ファイルに交換したりした場合は「{send.preset_file}」を使います。"
         "下書きや枠の変更後はリーダーが送信先を確認します。再選択が必要と表示された行は、欄を確認してください。"),
    ),
}


def chapter_text(chapter, language):
    title, text = CHAPTERS[chapter][LOCALES.index(language.lang)]
    return title, re.sub(r"\{([\w.]+)\}", lambda m: language.t(m[1]), text)


class HelpWindow:
    def __init__(self, root, language):
        self.root, self.language = root, language
        self.window = None
        self.chapter = "start"

    def show(self, chapter="start"):
        self.chapter = chapter if chapter in CHAPTERS else "start"
        if self.window is None:
            window = self.window = tk.Toplevel(self.root)
            window.configure(bg=BG, padx=12, pady=12)
            window.geometry("650x475")
            window.minsize(385, 310)
            window.columnconfigure(0, weight=1)
            window.rowconfigure(2, weight=1)
            self.heading = tk.Label(window, bg=BG, fg=TEXT, anchor="w")
            self.heading.grid(row=0, column=0, sticky="ew")
            self.navigation = ttk.Combobox(window, state="readonly")
            self.navigation.grid(row=1, column=0, sticky="ew", pady=(7, 8))
            self.navigation.bind("<<ComboboxSelected>>", self.select)
            frame = ttk.Frame(window)
            frame.grid(row=2, column=0, sticky="nsew")
            self.article = tk.Text(frame, wrap="word", padx=12, pady=10, width=10, height=5, bg=INPUT,
                                   fg=TEXT, relief="flat", highlightthickness=1, highlightbackground=LINE,
                                   highlightcolor=CYAN, spacing3=4, takefocus=True, state="disabled")
            scroll = ttk.Scrollbar(frame, command=self.article.yview)
            self.article.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            self.article.pack(side="left", fill="both", expand=True)
            self.close = ttk.Button(window, command=window.destroy)
            self.close.grid(row=3, column=0, sticky="e", pady=(8, 0))
            self.article.bind("<Tab>", lambda _: self.traverse(self.close))
            self.article.bind("<Shift-Tab>", lambda _: self.traverse(self.navigation))
            window.bind("<Escape>", lambda _: window.destroy())
            self.unsubscribe = self.language.subscribe(self.refresh)
            window.bind("<Destroy>", self.destroyed)
        self.refresh()
        self.window.deiconify()
        self.window.lift()
        self.navigation.focus_set()

    @staticmethod
    def traverse(widget):
        widget.focus_set()
        return "break"

    def destroyed(self, event):
        if event.widget is self.window:
            self.unsubscribe()
            self.window = None

    def select(self, _event):
        self.chapter = tuple(CHAPTERS)[self.navigation.current()]
        self.refresh()

    def refresh(self):
        if self.window is None:
            return
        language = self.language
        title = language.t("ui.about" if self.chapter == "about" else "ui.help")
        self.window.title(f"{title} · {language.t('reader.name')}")
        self.heading.configure(text=title, font=font(language, 15, True))
        self.navigation.configure(values=[entry[LOCALES.index(language.lang)][0] for entry in CHAPTERS.values()],
                                  font=font(language))
        self.navigation.current(tuple(CHAPTERS).index(self.chapter))
        self.close.configure(text=language.t("ui.close"))
        _, body = chapter_text(self.chapter, language)
        self.article.configure(state="normal", font=font(language, 11))
        self.article.delete("1.0", "end")
        self.article.insert("1.0", body)
        self.article.configure(state="disabled")
        self.article.yview_moveto(0)

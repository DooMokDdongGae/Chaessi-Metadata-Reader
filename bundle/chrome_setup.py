"""First pairing and recovery for the user's installed Chrome extension."""
import tkinter as tk
from tkinter import filedialog, ttk

from bundle import ui as theme
from bundle.i18n import LANGUAGE_NAMES
from chrome_bridge.key_store import PairingKeyError
from reader_clipboard import ClipboardError, copy_text


class ChromeSetup:
    def __init__(self, reader):
        self.reader = reader
        self.ui = reader.ui
        self.window = None
        self.notice = None

    def show(self):
        if self.window is not None:
            self.window.deiconify()
            self.window.lift()
            return
        window = self.window = tk.Toplevel(self.reader.root)
        window.configure(bg=theme.SURFACE, padx=14, pady=12)
        window.geometry("590x485")
        window.minsize(375, 330)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        self.language = ttk.Combobox(window, values=tuple(LANGUAGE_NAMES.values()), width=10, state="readonly")
        self.language.grid(row=0, column=1, sticky="e")
        self.language.bind("<<ComboboxSelected>>", self.select_language)
        self.status = ttk.Label(window, wraplength=240)
        self.status.grid(row=0, column=0, sticky="w")
        body = ttk.Frame(window)
        body.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        self.steps = tk.Text(body, wrap="word", width=16, height=5, padx=10, pady=8,
                             bg=theme.INPUT, fg=theme.TEXT, relief="flat", takefocus=False)
        scroll = ttk.Scrollbar(body, command=self.steps.yview)
        self.steps.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.steps.pack(side="left", fill="both", expand=True)
        self.copy = ttk.Button(window, command=self.copy_key, style="Primary.TButton")
        self.copy.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.previous = ttk.Button(window, command=self.import_previous)
        self.previous.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.message = ttk.Label(window, wraplength=350)
        self.message.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.help = ttk.Button(window, command=lambda: self.reader.help_window.show("chrome"))
        self.help.grid(row=5, column=0, sticky="w", pady=(7, 0))
        self.close = ttk.Button(window, command=window.destroy)
        self.close.grid(row=5, column=1, sticky="e", pady=(7, 0))
        window.bind("<Escape>", lambda _: window.destroy())
        window.bind("<Destroy>", self.destroyed)
        self.refresh()
        window.lift()
        self.language.focus_set()

    def destroyed(self, event):
        if event.widget is self.window:
            self.window = None
            self.notice = None

    def select_language(self, _event):
        try:
            self.ui.set(tuple(LANGUAGE_NAMES)[self.language.current()])
        except OSError:
            self.notice = "reader.language_error"
        self.refresh()

    def refresh(self):
        if self.window is None:
            return
        self.window.title(self.ui.t("setup.title"))
        self.language.set(LANGUAGE_NAMES[self.ui.lang])
        self.steps.configure(state="normal", font=theme.font(self.ui))
        self.steps.delete("1.0", "end")
        self.steps.insert("1.0", self.ui.t("setup.steps"))
        self.steps.configure(state="disabled")
        self.previous.configure(text=self.ui.t("setup.import"))
        self.help.configure(text=self.ui.t("ui.help"))
        self.close.configure(text=self.ui.t("ui.close"))
        self.update_status()

    def update_status(self):
        if self.window is None:
            return
        connected = self.reader.connection_state == "연결됨"
        error = self.reader.connection_error
        self.status.configure(text=self.ui.t("setup.ready" if connected else
                                             "setup.check" if error else "setup.wait"),
                              foreground=theme.OK if connected else theme.TEXT)
        recoverable = error in ("PAIRING_KEY_INVALID", "PAIRING_KEY_UNSAFE")
        self.copy.configure(text=self.ui.t("setup.recover" if recoverable else
                                           "setup.retry" if error else "setup.copy"))
        self.previous.configure(state="normal" if self.reader.connection else "disabled")
        message = self.notice or self.reader.connection_error_label()
        self.message.configure(text=self.ui.t(message) if message else "")

    def copy_key(self):
        if self.reader.connection is None:
            recover = self.reader.connection_error in ("PAIRING_KEY_INVALID", "PAIRING_KEY_UNSAFE")
            if recover and not theme.confirm(self.window, self.ui.t("setup.recover"),
                                             self.ui.t("setup.confirm_recover"), self.ui):
                return
            self.notice = None
            self.reader.open_connection(recover=recover)
        else:
            try:
                self.reader.connection.copy_pairing_key(
                    lambda value: copy_text(self.window.winfo_id(), value, private=True))
                self.notice = "setup.copied"
            except PairingKeyError as error:
                self.notice = "setup." + error.code
            except ClipboardError:
                self.notice = "setup.copy_failure"
        self.update_status()

    def import_previous(self):
        previous = filedialog.askdirectory(parent=self.window, title=self.ui.t("setup.import"), mustexist=True)
        if not previous or not theme.confirm(self.window, self.ui.t("setup.import"),
                                             self.ui.t("setup.confirm_import"), self.ui):
            return
        try:
            changed = self.reader.connection.import_legacy_folder(previous)
            self.notice = "setup.imported" if changed else "setup.same"
            if changed:
                self.reader.connection_state = self.reader.connection.state()
                self.reader.draw_connection()
        except PairingKeyError as error:
            self.notice = "setup." + error.code
        self.update_status()

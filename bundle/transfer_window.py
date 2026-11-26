"""Session-only transfer list and destination controls for the reader."""
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, font as tkfont, ttk

from reader_app import display
from bundle.editing import SourceText
from bundle.i18n import Language
from bundle.ui import (BG, SURFACE, SURFACE2, LINE, TEXT, MUTED, VIOLET, MAGENTA, CYAN,
                       OK, INPUT, HEADER, brand, font, confirm)
from bundle import transfer_client as client
from bundle.preset_session import PresetSession


CONNECTION_MESSAGES = {
    "preset.select_required", "preset.changed", "preset.missing", "preset.unverified",
    "preset.ambiguous", "preset.unsupported", "preset.no_receiver", "preset.not_running",
    "preset.unavailable", "preset.busy", "preset.temporary", "preset.unsupported_image",
    "preset.signature_invalid", "preset.signature_expired", "preset.signature_revoked",
    "preset.signature_rollback", "preset.runtime_mismatch",
}
WATCH_MS = 10000


@dataclass(eq=False)
class QueueItem:
    source: SourceText
    instance: str = ""
    revision: str = ""
    slot: str = ""
    field: str = ""
    mode: str = "append"
    needs_selection: bool = False
    position: tuple[str, int] | None = None


class TransferWindow:
    def __init__(self, root, changed, ui=None, *, session=None):
        self.root = root
        self.changed = changed
        self.ui = ui if ui is not None else Language()
        self.t = self.ui.t
        self.catalogue = []
        self.labels = {}
        self.fonts = {}
        self.message = ("send.add_first", {})
        self.shown = None
        self.show_help = None
        self.items = []
        self.window = None
        self.session = PresetSession() if session is None else session
        self.record = None
        self.endpoint = None
        self.revision = None
        self.targets = {}
        self.target_names = {}
        self.target_positions = {}
        self.watch_connection = False
        self.connecting = False
        self.choosing = False
        self.busy = False
        self.pending = None
        self.needs_check = False
        self.events = queue.Queue()

    def add_source(self, source):
        item = QueueItem(source)
        self.items.append(item)
        if self.message[0] == "send.add_first":
            self.message = ("send.need_connection", {}) if not self.endpoint else ("send.choose_target", {"n": len(self.items)})
        self.refresh_list(item)
        self._render_note()

    def clear(self):
        self.items.clear()
        self.message = ("send.add_first", {})
        self.refresh_list()
        self._render_note()

    def _label(self, parent, key=None, *, size=10, bold=False, color=TEXT, wrap=False):
        widget = tk.Label(parent, bg=parent["bg"], fg=color, anchor="w", justify="left",
                          font=font(self.ui, size, bold), padx=0, pady=0)
        self.fonts[widget] = (size, bold)
        if key:
            self.labels[widget] = key
        if wrap:
            widget.bind("<Configure>", lambda e: widget.configure(wraplength=max(80, e.width - 3))
                        if widget.winfo_pixels(widget.cget("wraplength")) != max(80, e.width - 3) else None)
        return widget

    def _button(self, parent, key, command, primary=False):
        widget = ttk.Button(parent, command=command, takefocus=True,
                            style="Primary.TButton" if primary else "TButton")
        self.labels[widget] = key
        return widget

    def show(self):
        if self.window is not None:
            self.window.deiconify()
            self.window.lift()
            return
        win = self.window = tk.Toplevel(self.root)
        win.configure(bg=BG)
        win.geometry(f"{min(1060, win.winfo_screenwidth()-30)}x{min(690, win.winfo_screenheight()-70)}")
        win.minsize(475, 385)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        header = tk.Frame(win, bg=HEADER, padx=14, pady=7)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        brand(header).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self._label(header, "send.brand", size=9, color=MUTED).grid(row=0, column=1, sticky="w")
        self._label(header, "send.title", size=15, bold=True).grid(row=1, column=1, sticky="w")
        if self.show_help:
            self._button(header, "send.help", self.show_help).grid(row=0, column=2, rowspan=2)

        viewport = tk.Frame(win, bg=BG)
        viewport.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar = ttk.Scrollbar(viewport, command=self.canvas.yview)
        self.bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.body_id = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.queue_box = self._build_queue(self.body)
        self.detail_box = self._build_details(self.body)
        self._build_footer(win)
        self.wide = None
        self.canvas.bind("<Configure>", self._layout)
        self.body.bind("<Configure>", lambda _e: self._measure())
        win.bind("<FocusIn>", self._reveal_control, add="+")
        win.bind("<MouseWheel>", self._wheel, add="+")
        # Keep the scroll wheel for scrolling instead of changing a mapping by accident.
        self.dest.bind("<MouseWheel>", lambda e: self._wheel(e) or "break")
        self.refresh_language()
        self.refresh_list(self.items[0] if self.items else None)
        self.tree.focus_set()
        self.run(self.session.configured, self.show_configured)
        self.root.after(WATCH_MS, self.watch)

    def _box(self, parent):
        return tk.Frame(parent, bg=SURFACE, highlightbackground=LINE, highlightthickness=1,
                        padx=10, pady=7)

    def _build_queue(self, parent):
        box = self._box(parent)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        head = tk.Frame(box, bg=SURFACE)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        self._label(head, "send.list", bold=True, size=12).pack(side="left")
        self.queue_count = self._label(head, color=CYAN, bold=True)
        self.queue_count.pack(side="left", padx=6)
        style = ttk.Style(box)
        rows_font = tkfont.Font(box, font=font(self.ui, 10))
        style.configure("Transfer.Treeview", font=font(self.ui, 10),
                        background=SURFACE2, fieldbackground=SURFACE2, foreground=TEXT,
                        rowheight=3 * rows_font.metrics("linespace") + 10)
        style.map("Transfer.Treeview", background=[("selected", "#38293d")],
                  foreground=[("selected", TEXT)])
        self.tree = ttk.Treeview(box, show="tree", height=4, selectmode="browse",
                                 style="Transfer.Treeview", takefocus=True)
        self.tree.column("#0", width=160, minwidth=30, stretch=True)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_item())
        tools = tk.Frame(box, bg=SURFACE)
        tools.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.up = self._button(tools, "send.up", lambda: self.move(-1))
        self.down = self._button(tools, "send.down", lambda: self.move(1))
        self.remove_button = self._button(tools, "send.remove", self.remove)
        for widget in (self.up, self.down, self.remove_button):
            widget.pack(side="left", padx=(0, 4))
        return box

    def _build_details(self, parent):
        stack = tk.Frame(parent, bg=BG)
        stack.columnconfigure(0, weight=1)
        conn = self._box(stack)
        conn.grid(row=0, column=0, sticky="ew")
        conn.columnconfigure(0, weight=1)
        self.connection_name = self._label(conn, size=12, bold=True, wrap=True)
        self.connection_name.grid(row=0, column=0, sticky="ew")
        self.connection_state = self._label(conn, color=MUTED, wrap=True)
        self.connection_state.grid(row=1, column=0, sticky="ew")
        actions = tk.Frame(conn, bg=SURFACE)
        actions.grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.connection_button = self._button(actions, "send.connect", self.connect)
        self.connection_button.grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.file_button = self._button(actions, "send.preset_file", self.choose_executable)
        self.file_button.grid(row=0, column=1, sticky="w")
        conn.bind("<Configure>", lambda e: self.fit_connection_buttons(e.width))
        edit = self._box(stack)
        edit.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        stack.rowconfigure(1, weight=1)
        edit.columnconfigure(0, weight=1)
        edit.rowconfigure(1, weight=1)
        self.detail_title = self._label(edit, size=12, bold=True)
        self.detail_title.grid(row=0, column=0, sticky="w")
        exframe = tk.Frame(edit, bg=SURFACE)
        exframe.grid(row=1, column=0, sticky="nsew", pady=5)
        self.excerpt = tk.Text(exframe, height=3, width=1, wrap="word", state="disabled",
                               bg=SURFACE2, fg=MAGENTA, selectbackground=VIOLET, relief="flat",
                               highlightthickness=1, highlightbackground=LINE, highlightcolor=CYAN,
                               font=font(self.ui, 10), takefocus=True, padx=5, pady=3)
        scrollbar = ttk.Scrollbar(exframe, command=self.excerpt.yview)
        scrollbar.pack(side="right", fill="y")
        self.excerpt.configure(yscrollcommand=scrollbar.set)
        self.excerpt.pack(fill="both", expand=True)
        self.excerpt.bind("<Tab>", lambda _: self._tab_from_excerpt(False))
        self.excerpt.bind("<Shift-Tab>", lambda _: self._tab_from_excerpt(True))
        self._label(edit, "send.destination", bold=True).grid(row=2, column=0, sticky="w")
        self.dest = ttk.Combobox(edit, state="readonly", width=1, takefocus=True)
        self.dest.grid(row=3, column=0, sticky="ew", pady=(3, 4))
        self.dest.bind("<<ComboboxSelected>>", lambda _: self.assign())
        self.row_hint = self._label(edit, color=MUTED, size=9, wrap=True)
        self.row_hint.grid(row=4, column=0, sticky="ew")
        self._label(edit, "send.mode", bold=True).grid(row=5, column=0, sticky="w", pady=(6, 2))
        self.mode = tk.StringVar(master=edit, value="append")
        self.radios = []
        for index, mode in enumerate(("append", "replace")):
            radio = tk.Radiobutton(edit, variable=self.mode, value=mode, command=self.assign_mode,
                                   bg=SURFACE, fg=TEXT, activebackground=SURFACE, activeforeground=TEXT,
                                   disabledforeground=MUTED, selectcolor=INPUT, highlightcolor=CYAN,
                                   highlightbackground=SURFACE, anchor="w", font=font(self.ui, 10, True))
            self.labels[radio] = "send." + mode
            self.fonts[radio] = (10, True)
            radio.grid(row=6 + index*2, column=0, sticky="w")
            self.radios.append(radio)
            self._label(edit, "send." + mode + "_hint", color=MUTED, size=9, wrap=True).grid(
                row=7 + index*2, column=0, sticky="ew", padx=(19, 0))
        return stack

    def _build_footer(self, win):
        self.footer = tk.Frame(win, bg=BG, padx=12, pady=6)
        self.footer.grid(row=2, column=0, sticky="ew")
        self.footer.columnconfigure(0, weight=1)
        self.summary = self._label(self.footer, color=TEXT, bold=True, wrap=True)
        self.summary.grid(row=0, column=0, sticky="ew")
        self.commands = tk.Frame(self.footer, bg=BG)
        self.commands.grid(row=0, column=1, sticky="e")
        self.all_count = self._label(self.commands, color=MUTED, size=9)
        self.all_count.grid(row=0, column=0, padx=(0, 5))
        self.send_button = self._button(self.commands, "send.action", self.send, primary=True)
        self.send_button.grid(row=0, column=1)
        notices = tk.Frame(self.footer, bg=BG)
        notices.grid(row=2, column=0, columnspan=2, sticky="ew")
        notices.columnconfigure(0, weight=1)
        self.status = self._label(notices, color=CYAN, wrap=True)
        self.status.grid(row=0, column=0, sticky="ew")
        self.result_button = self._button(notices, "send.check", self.check_result)
        self.result_button.grid(row=0, column=1)
        self._label(self.footer, "send.explain", color=MUTED, size=9, wrap=True).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(3, 0))

    def _tab_from_excerpt(self, reverse):
        (self.excerpt.tk_focusPrev() if reverse else self.excerpt.tk_focusNext()).focus_set()
        return "break"

    def _layout(self, event):
        wide = event.width >= self.window.winfo_pixels("565p")
        if self.wide != wide:
            self.wide = wide
            self.body.columnconfigure(0, weight=1, uniform="transfer" if wide else "")
            self.body.columnconfigure(1, weight=int(wide), uniform="transfer" if wide else "")
            self.body.rowconfigure(0, weight=1 if wide else 0)
            self.queue_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6 if wide else 0))
            self.detail_box.grid(row=0 if wide else 1, column=1 if wide else 0, sticky="nsew",
                                 pady=(0 if wide else 6, 0))
            self.commands.grid(row=0 if wide else 1, column=1 if wide else 0,
                               columnspan=1 if wide else 2, sticky="e")
        self._fit_commands(event.width)
        self.canvas.itemconfigure(self.body_id, width=event.width)
        self._measure()

    def _measure(self):
        height = max(self.canvas.winfo_height(), self.body.winfo_reqheight())
        self.canvas.itemconfigure(self.body_id, height=height)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), height))

    def _fit_commands(self, width):
        full = sum(w.winfo_reqwidth() for w in (self.send_button, self.all_count)) + 18
        if not self.wide and full > width:
            self.send_button.grid(row=1, column=0, columnspan=2, sticky="e", pady=(3, 0))
        else:
            self.send_button.grid(row=0, column=1, columnspan=1, sticky="e", pady=0)

    def fit_connection_buttons(self, width):
        narrow = self.connection_button.winfo_reqwidth() + self.file_button.winfo_reqwidth() + 26 > width
        self.file_button.grid(row=int(narrow), column=int(not narrow), pady=(3 if narrow else 0, 0))

    def _wheel(self, event):
        if event.widget not in (self.tree, self.excerpt) and event.delta:
            self.canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
            return "break"

    def _reveal_control(self, event):
        if not str(event.widget).startswith(str(self.body) + "."):
            return
        top = event.widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        height = self.canvas.winfo_height()
        if top < 0 or bottom > height:
            offset = top - 4 if top < 0 else bottom - height + 4
            self.canvas.yview_moveto(max(0, self.canvas.canvasy(0) + offset) / max(1, self.body.winfo_height()))

    def refresh_language(self):
        if self.window is None:
            return
        selected = self.selected()
        self.window.title(self.t("send.title"))
        for widget, key in self.labels.items():
            widget.configure(text=self.t(key))
        for widget, (size, bold) in self.fonts.items():
            widget.configure(font=font(self.ui, size, bold))
        self.excerpt.configure(font=font(self.ui, 10))
        transfer_font = font(self.ui, 10)
        linespace = tkfont.Font(self.window, font=transfer_font).metrics("linespace")
        ttk.Style(self.window).configure("Transfer.Treeview", font=transfer_font, rowheight=3 * linespace + 10)
        self._format_targets()
        self.fit_connection_buttons(self.connection_name.master.winfo_width())
        self.refresh_list(selected)
        self._render_note()
        self._fit_commands(self.canvas.winfo_width())

    def _field_name(self, label):
        group, field = label.rsplit(" ", 1)
        return self._target_name("base" if group == "Base" else "character",
                                 0 if group == "Base" else int(group.split()[1]), field.lower())

    def _target_name(self, kind, number, field):
        return self.t("send." + kind, n=number) + " · " + self.t("send." + field)

    def _format_targets(self):
        self.targets = {self._target_name(kind, number, field): (slot, field)
                        for slot, number, kind, field in self.catalogue}
        self.target_names = {value: key for key, value in self.targets.items()}
        self.target_positions = {(slot, field): (kind, number) for slot, number, kind, field in self.catalogue}
        self.dest.configure(values=list(self.targets))

    def _name_for_item(self, item):
        if not item.slot:
            return self.t("send.missing")
        if not self.is_current(item):
            return self.t("send.reselect")
        return self.target_names.get((item.slot, item.field), self.t("send.reselect"))

    def _row_text(self, index, item, active):
        source = item.source
        scope = getattr(source, "scope", None)
        tag = self.t("send." + (scope if scope in ("full", "selection") else "text"))
        selected = self.t("send.item") + " · " if active else ""
        heading = f"{index}   {self.t('send.image', n=source.image+1)} · {self._field_name(source.field)}   {selected}{tag}"
        snippet = source.text[:90].replace("\n", " ↵ ").replace("\t", " ⇥ ")
        if len(source.text) > 90:
            snippet += "…"
        return f"{heading}\n     {snippet or self.t('send.empty')}\n     → {self._name_for_item(item)} · {self.t('send.' + item.mode)}"

    def refresh_list(self, selected=None):
        self.changed()
        if self.window is None:
            return
        old = set(self.tree.get_children())
        for index, item in enumerate(self.items):
            key = str(id(item))
            content = self._row_text(index+1, item, item is selected)
            if key in old:
                self.tree.item(key, text=content)
                self.tree.move(key, "", index)
                old.remove(key)
            else:
                self.tree.insert("", "end", iid=key, text=content)
        if old:
            self.tree.delete(*old)
        if selected in self.items:
            key = str(id(selected))
            if self.tree.selection() != (key,):
                self.tree.selection_set(key)
            self.tree.focus(key)
            self.tree.see(key)
        self.show_item()

    def selected(self):
        keys = self.tree.selection()
        return next((item for item in self.items if str(id(item)) in keys), None)

    def is_current(self, item):
        return (not item.needs_selection and self.endpoint is not None
                and item.instance == self.endpoint.instance_id and item.revision == self.revision
                and self.target_positions.get((item.slot, item.field)) == item.position and item.position is not None)

    def show_item(self):
        item = self.selected()
        if item is not self.shown:
            for row in (self.shown, item):
                if row in self.items:
                    index = self.items.index(row) + 1
                    self.tree.item(str(id(row)), text=self._row_text(index, row, row is item))
            display(self.excerpt, item.source.text if item else "")
        self.shown = item
        self.mode.set(item.mode if item else "append")
        self.dest.set(self._name_for_item(item) if item and item.slot else self.t("send.placeholder"))
        number = self.items.index(item)+1 if item else 0
        self.detail_title.configure(text=(f"{number}  " if number else "") + self.t("send.detail"))
        hint_key = "send.assigned" if item and item.slot and self.is_current(item) else "send.choose_target"
        if item and self.is_current(item) and item.slot.startswith("new:"):
            hint_key = "send.new_hint"
        self.row_hint.configure(text=self.t(hint_key, n=number) if item else self.t("send.choose_row"))
        self._controls()

    def _controls(self):
        if self.window is None:
            return
        locked = bool(self.busy or self.pending or self.choosing)
        item = self.selected()
        current = [row for row in self.items if row.slot and self.is_current(row)]
        self.queue_count.configure(text=str(len(self.items)))
        self.all_count.configure(text=self.t("send.count", n=len(self.items)))
        state = self.t("send.add_first")
        if self.items:
            if len(current) < len(self.items):
                missing = next(i for i, row in enumerate(self.items, 1) if not row.slot or not self.is_current(row))
                state = self.t("send.choose_target", n=missing)
            elif len(self.items) > client.MAX_ITEMS:
                state = self.t("send.batch_limit", n=client.MAX_ITEMS)
            else:
                state = self.t("send.ready")
            state += "\n" + self.t("send.mapped", ready=len(current), total=len(self.items))
        self.summary.configure(text=state)
        key = ("send.connecting" if self.connecting else "send.connected" if self.endpoint else
               "send.disconnected" if self.record else "send.preset_unset")
        self.connection_state.configure(text=self.t(key),
                                        fg=OK if self.endpoint else MUTED)
        self.connection_name.configure(text=self.record.name if self.record else self.t("send.preset_name"))
        self.dest.configure(state="readonly" if item and self.targets and not locked else "disabled")
        for radio in self.radios:
            radio.configure(state="normal" if item and not locked else "disabled")
        # A click on an incomplete form explains what to choose. Only an active
        # request/connection operation locks Send; missing inputs do not hide why.
        for widget, enabled in ((self.send_button, True),
                                (self.up, item and self.items[0] is not item),
                                (self.down, item and self.items[-1] is not item),
                                (self.remove_button, item), (self.connection_button, True), (self.file_button, True)):
            widget.state(["!disabled" if enabled and not locked else "disabled"])
        if self.pending and self.needs_check:
            self.result_button.grid()
            self.result_button.state(["disabled" if self.busy else "!disabled"])
        else:
            self.result_button.grid_remove()

    def note(self, key, **params):
        self.message = (key, params)
        self._render_note()

    def _render_note(self):
        if not hasattr(self, "status"):
            return
        key, params = self.message
        message = self.ui.diagnostic(params["error"]) if key == "diagnostic" else self.t(key, **params)
        self.status.configure(text=message)
        self._controls()

    def unlocked(self):
        if self.busy or self.pending or self.choosing:
            self.note("send.locked")
            return False
        return True

    def assign(self):
        item = self.selected()
        title = self.dest.get()
        if not self.unlocked() or not item or not self.endpoint or title not in self.targets:
            return
        if self.window is not None and item is not self.shown:
            self.show_item()
            return
        item.instance = self.endpoint.instance_id
        item.revision = self.revision
        item.slot, item.field = self.targets[title]
        item.position = self.target_positions[item.slot, item.field]
        item.needs_selection = False
        item.mode = self.mode.get()
        self.refresh_list(item)

    def assign_mode(self):
        item = self.selected()
        if item and self.unlocked() and item is self.shown:
            item.mode = self.mode.get()
            self.refresh_list(item)

    def move(self, offset):
        item = self.selected()
        if item and self.unlocked():
            index = self.items.index(item)
            other = index + offset
            if 0 <= other < len(self.items):
                self.items[index], self.items[other] = self.items[other], item
                self.refresh_list(item)

    def remove(self):
        item = self.selected()
        if item and self.unlocked():
            index = self.items.index(item)
            self.items.remove(item)
            self.refresh_list(self.items[min(index, len(self.items)-1)] if self.items else None)

    def run(self, work, success, error=None):
        if self.busy:
            return
        self.busy = True
        self._controls()

        def worker():
            try:
                value = work()
            except client.TransferError as exc:
                self.events.put((False, exc))
            except Exception:
                self.events.put((False, client.TransferError("send.connection_error")))
            else:
                self.events.put((True, value))

        def finish():
            try:
                ok, result = self.events.get_nowait()
            except queue.Empty:
                self.root.after(40, finish)
                return
            self.busy = False
            if ok:
                success(result)
            elif error:
                error(result)
            else:
                self._error(result)
            self._controls()

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(40, finish)

    def _error(self, error):
        message = str(error)
        if message in CONNECTION_MESSAGES or message == "send.connection_error":
            self.note(message)
        else:
            self.note("diagnostic", error=message)

    def connect(self):
        if self.unlocked():
            self._connect(allow_launch=True, prompt=True, report=True)

    def show_configured(self, record):
        self.record = record
        if record is None and self.items:
            self.note("preset.select_required")
        self._controls()

    def choose_executable(self, on_ready=None):
        if not self.unlocked():
            return
        self.choosing = True
        self._controls()
        try:
            options = {"initialdir": str(self.record.path.parent)} if self.record else {}
            path = filedialog.askopenfilename(parent=self.window, title=self.t("send.preset_file"),
                                             filetypes=((self.t("preset.exe"), "*.exe"),), **options)
        finally:
            self.choosing = False
            self._controls()
        if not path:
            self.note("send.no_exe")
            return

        def inspected(info):
            self.choosing = True
            self._controls()
            try:
                accepted = confirm(self.window, self.t("send.preset_file"),
                                   self.t("send.preset_confirm", path=str(info.path)), self.ui)
            finally:
                self.choosing = False
                self._controls()
            if accepted:
                self.run(lambda: self.session.configure(info), configured)
            else:
                self.note("send.no_exe")

        def configured(record):
            if self.record is None or (record.path, record.digest) != (self.record.path, self.record.digest):
                self.endpoint = None
                self.invalidate_catalogue(reselect=True)
            self.record = record
            self._connect(allow_launch=True, report=True, on_ready=on_ready)

        self.run(lambda: self.session.inspect(path), inspected)

    def watch(self):
        self.root.after(WATCH_MS, self.watch)
        if (self.watch_connection and self.window.state() != "withdrawn" and
                not (self.busy or self.pending or self.choosing)):
            if self.endpoint is not None and self.endpoint.liveness_check is not None:
                try:
                    self.endpoint.liveness_check()
                    return
                except client.TransferError:
                    pass
            self._connect()

    def _connect(self, *, allow_launch=False, prompt=False, report=False, on_ready=None):
        previous = self.endpoint
        self.connecting = report
        if report:
            self.note("send.connecting")

        def work():
            if previous is not None:
                try:
                    return self.session.refresh(previous)
                except client.TransferError as error:
                    if error.code in ("preset.changed", "preset.missing", "preset.select_required"):
                        raise
            return self.session.connect(allow_launch=allow_launch)

        def ready(result):
            endpoint, data, self.record = result
            self.connecting = False
            self.watch_connection = True
            self.install_targets(endpoint, data)
            if report or (previous is None and self.message[0] in CONNECTION_MESSAGES):
                self.note("send.connection_ready")
            if on_ready:
                on_ready()

        def failed(error):
            self.connecting = False
            self.endpoint = None
            if self.revision is not None:
                self.invalidate_catalogue()
            if error.code in ("preset.changed", "preset.missing", "preset.select_required"):
                self.watch_connection = False
            if prompt and error.code == "preset.select_required":
                self.choose_executable(on_ready)
            elif report or previous is not None:
                self._error(error)

        self.run(work, ready, failed)

    def invalidate_catalogue(self, *, reselect=False):
        if reselect:
            for row in self.items:
                if row.slot:
                    row.needs_selection = True
        self.revision = None
        self.catalogue = []
        self._format_targets()
        self.refresh_list(self.selected())

    def install_targets(self, endpoint, data):
        catalogue = []
        for row in data["targets"]:
            for field in row["fields"]:
                catalogue.append((row["slot"], row["number"], "character" if row["number"] else "base", field))
        # Preset v1 declares model-wide field availability on its catalogue rows.
        create_fields = [field for field in ("positive", "undesired")
                         if all(field in row["fields"] for row in data["targets"])]
        # A receiver may omit unaddressable rows (e.g. missing/duplicate IDs).
        # canCreate uses the full character array length, not catalogue row count.
        existing = data["limit"] - data["canCreate"]
        for number in range(1, data["canCreate"] + 1):
            for field in create_fields:
                catalogue.append((f"new:{number}", existing + number, "new", field))
        changed = (self.endpoint != endpoint or self.revision != data["revision"] or self.catalogue != catalogue)
        self.endpoint = endpoint
        if not changed:
            return
        self.revision = data["revision"]
        self.catalogue = catalogue
        self._format_targets()
        for item in self.items:
            if not item.slot or item.needs_selection:
                continue
            if (item.instance == endpoint.instance_id and item.position is not None and
                    self.target_positions.get((item.slot, item.field)) == item.position):
                item.revision = self.revision
            else:
                item.needs_selection = True
        self.refresh_list(self.selected())

    def send(self):
        if not self.unlocked():
            return
        rows = tuple(self.items)
        if not rows:
            self.note("send.add_first")
            return
        if len(rows) > client.MAX_ITEMS:
            self.note("send.batch_limit", n=client.MAX_ITEMS)
            return
        self._connect(allow_launch=True, prompt=True, report=self.endpoint is None,
                      on_ready=lambda: self.send_ready(rows))

    def send_ready(self, rows, *, reconnect=True):
        if not all(row in self.items for row in rows):
            self.note("send.add_first")
            return
        for number, row in enumerate(rows, 1):
            if not self.is_current(row):
                self.refresh_list(row)
                self.note("send.choose_target", n=number)
                return
        items = []
        for row in rows:
            source = row.source
            group, field = source.field.rsplit(" ", 1)
            number = 0 if group == "Base" else int(group.split(" ")[1])
            items.append(dict(source=dict(image=source.image+1, number=number, field=field.lower()),
                              slot=row.slot, field=row.field, mode=row.mode, text=source.text))
        try:
            request_id, body = client.make_preview(self.revision, items)
        except client.TransferError as exc:
            self._error(exc)
            return
        self.pending = (self.endpoint, request_id, body, rows)
        self.submit_pending(reconnect=reconnect)

    def submit_pending(self, *, reconnect=False):
        endpoint, _, body, _ = self.pending
        self.needs_check = False
        self.note("send.submitting")
        self.run(lambda: client.preview(endpoint, body), self.receive_state,
                 lambda error: self.preview_error(error, reconnect=reconnect))

    def preview_error(self, error, *, reconnect=False):
        # Nothing was sent if the authenticated probe failed. Never redirect or replay
        # a preview whose delivery is uncertain. Status remains pinned to its endpoint.
        if reconnect and not error.delivery_possible and error.code in (None, "NOT_READY", "UNAUTHORIZED"):
            rows = self.pending[3]
            self.pending = None
            self.endpoint = None
            self.invalidate_catalogue()
            self._connect(allow_launch=True, report=True, on_ready=lambda: self.send_ready(rows, reconnect=False))
            return
        if not error.delivery_possible or error.code in (
                "INVALID", "BUSY", "STALE", "TOO_LARGE", "NOT_READY", "UNAUTHORIZED", "ID_CONFLICT"):
            self.pending = None
            if error.code == "STALE":
                self.changed_revision()
            else:
                self._error(error)
        else:
            self.needs_check = True
            self.note("send.inspect_result")

    def changed_revision(self):
        self.invalidate_catalogue()
        self.note("send.stale")
        self._connect()

    def check_result(self, manual=True):
        if self.busy or not self.pending:
            return
        endpoint, request_id, _, _ = self.pending
        self.run(lambda: client.status(endpoint, request_id), self.receive_state,
                 lambda error: self.result_error(error, manual))

    def result_error(self, error, manual=True):
        if manual and error.code == "NOT_FOUND":
            if confirm(self.window, self.t("send.retry_title"), self.t("send.retry_body"), self.ui):
                self.submit_pending()
                return
        if manual and confirm(self.window, self.t("send.stop_title"), self.t("send.stop_body"), self.ui):
            for row in self.pending[3]:
                row.instance = row.revision = row.slot = row.field = ""
                row.position = None
            self.pending = None
            self.invalidate_catalogue()
            self.note("send.stopped")
            self._connect()
            return
        self.needs_check = True
        self.note("send.inspect_result")

    def receive_state(self, state):
        self.needs_check = False
        if state == "pending":
            self.note("send.pending")
            request = self.pending
            self.root.after(800, lambda: self.check_result(manual=False) if self.pending is request else None)
            return
        rows = self.pending[3]
        self.pending = None
        if state == "applied":
            self.items[:] = [item for item in self.items if item not in rows]
        self.refresh_list(self.items[0] if self.items else None)
        if state == "stale":
            self.changed_revision()
        else:
            self.note("send." + state)
            if state == "applied":
                self.invalidate_catalogue()
                self._connect()

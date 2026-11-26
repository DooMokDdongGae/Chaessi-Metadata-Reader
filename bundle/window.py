"""Windows reader for the official, per-card readable copy of a work."""
import ctypes
import json
import os
import queue
import threading
import time
import tkinter as tk
from itertools import groupby
from pathlib import Path
from tkinter import filedialog, ttk

from reader_app import button, display, label, read_local, read_png_batch, text_area
from bundle import ui as theme
from bundle.i18n import LANGUAGE_NAMES, Language
from bundle.help_ui import HelpWindow
from bundle.chrome_setup import ChromeSetup
from bundle.ui import BG, CYAN, DANGER, HEADER, LINE, MUTED, OK, SURFACE, TEXT, VIOLET
from reader_clipboard import ClipboardError, copy_text
from bundle.editing import EditSession
from bundle.image_input_win import WindowsImageInput
from bundle.model import FORMAT, URL, decode_input
from bundle.transfer_window import TransferWindow
from chrome_bridge.client import read_link, read_inspect
from chrome_bridge.connection import ReaderConnection
from chrome_bridge.key_store import PairingKeyError


class PromptPanels(tk.Frame):
    """Scrollable, responsive field groups for the selected card."""

    def __init__(self, parent, owner):
        super().__init__(parent, bg=BG)
        self.owner = owner
        self.panels = {}
        self.headers = {}
        self.group_titles = []
        self.active = None
        self.expanded = None
        self.anchor_job = None
        self.actions = None
        self.groups = []
        self.sections = []
        self.measure_job = None
        self.content_height = 1
        self.wide = False
        self.column_break = self.winfo_pixels("470p")
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=1,
                                highlightbackground=LINE, highlightcolor=CYAN,
                                width=1, height=1, takefocus=True, yscrollincrement=12)
        bar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self.resize)
        self.scroll_tag = f"PromptScroll{self}"
        self.bind_class(self.scroll_tag, "<MouseWheel>", self.wheel)
        for key, amount, units in (("Up", -1, "units"), ("Down", 1, "units"),
                                   ("Prior", -1, "pages"), ("Next", 1, "pages")):
            self.bind_class(self.scroll_tag, f"<{key}>",
                            lambda e, n=amount, u=units: None if isinstance(e.widget, tk.Text)
                            else self.scroll(e.widget, n, u))
        for key, fraction in (("Home", 0), ("End", 1)):
            self.bind_class(self.scroll_tag, f"<{key}>",
                            lambda e, f=fraction: None if isinstance(e.widget, tk.Text)
                            else self.jump(e.widget, f))
        self.bind_class(self.scroll_tag, "<FocusIn>", self.reveal_focus)
        self.tag_children(self)

    def destroy(self):
        if self.measure_job is not None:
            self.after_cancel(self.measure_job)
        if self.anchor_job is not None:
            self.after_cancel(self.anchor_job)
        self.panels.clear()
        super().destroy()

    def tag_children(self, widget):
        widget.bindtags((self.scroll_tag, *widget.bindtags()))
        for child in widget.winfo_children():
            self.tag_children(child)

    def resize(self, event):
        for _, item in self.sections:
            self.canvas.itemconfigure(item, width=max(1, event.width - 2))
        wide = event.width >= self.column_break
        if self.wide != wide:
            self.wide = wide
            for group, cells in self.groups:
                self.layout(group, cells)
        self.schedule_measure()

    def schedule_measure(self, _event=None):
        if self.measure_job is None:
            self.measure_job = self.after_idle(self.measure)

    def measure(self):
        self.measure_job = None
        y = 1
        for frame, item in self.sections:
            self.canvas.coords(item, 1, y)
            y += frame.winfo_reqheight()
        self.content_height = y
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), y + 1))

    def add_section(self):
        frame = tk.Frame(self.canvas, bg=BG, padx=8, pady=3)
        frame.columnconfigure(0, weight=1)
        frame.bind("<Configure>", self.schedule_measure)
        frame.bindtags((self.scroll_tag, *frame.bindtags()))
        item = self.canvas.create_window(1, 1, anchor="nw", window=frame,
                                         width=max(1, self.canvas.winfo_width() - 2))
        self.sections.append((frame, item))
        return frame

    def focus_section_edge(self, target, item, last):
        # Tk traversal skips unmapped canvas windows. Reveal the adjacent section
        # before asking Tk to focus its first copy button or last text box.
        bounds = self.canvas.bbox(item)
        top = bounds[3] - self.canvas.winfo_height() if last else bounds[1]
        self.canvas.yview_moveto(max(0, top) / self.content_height)
        self.canvas.update_idletasks()
        target.focus_set()
        return "break"

    def layout(self, group, cells):
        paired = self.wide and len(cells) == 2 and group is not self.base_group
        group.columnconfigure(0, weight=1, uniform="field")
        group.columnconfigure(1, weight=int(paired), uniform="field" if paired else "")
        for i, cell in enumerate(cells):
            cell.grid(row=1 if paired else i + 1, column=i if paired else 0,
                      sticky="new", padx=(0, 8 if paired and i == 0 else 0), pady=(0, 5))

    def show(self, fields):
        if self.anchor_job is not None:
            self.after_cancel(self.anchor_job)
            self.anchor_job = None
        for frame, item in self.sections:
            self.canvas.delete(item)
            frame.destroy()
        self.sections.clear()
        self.group_titles.clear()
        self.headers.clear()
        self.actions = None
        self.active = None
        self.expanded = None
        self.base_group = None
        self.groups.clear()
        self.panels.clear()
        last_text = None
        for row, (name, pairs) in enumerate(groupby(fields, lambda pair: pair[0].rsplit(" ", 1)[0])):
            # One very tall Windows child clips coordinates beyond 32K pixels.
            # Independent canvas windows keep even 256 stacked groups reachable.
            section_row = row % 16
            if section_row == 0:
                section = self.add_section()
            group = tk.Frame(section, bg=BG)
            group.grid(row=section_row, column=0, sticky="ew", pady=(3, 5))
            if name == "Base":
                self.base_group = group
            title = label(group, self.owner.group_name(name), size=12, bold=True, anchor="w")
            title.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 2))
            self.group_titles.append((name, title))
            cells = []
            for full_name, value in pairs:
                field = full_name.rsplit(" ", 1)[1]
                cell = tk.Frame(group, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
                cells.append(cell)
                header = tk.Frame(cell, bg=SURFACE)
                header.pack(fill="x", padx=7, pady=(4, 0))
                field_label = label(header, self.owner.t(field.lower()), size=9, bold=True)
                field_label.pack(side="left")
                action = button(header, self.owner.t("copy"), lambda key=full_name: self.owner.copy(self.text_value(key)))
                action.configure(padx=7, pady=0)
                action.pack(side="right")
                menu_button = ttk.Menubutton(header, text=self.owner.t("restore"), takefocus=True)
                menu_button.pack(side="right", padx=2)
                menu = tk.Menu(menu_button, tearoff=False)
                menu_button.configure(menu=menu)
                menu.add_command(label=self.owner.t("full"), command=lambda key=full_name: self.owner.queue_field(key, False))
                menu.add_command(label=self.owner.t("select"), command=lambda key=full_name: self.owner.queue_field(key, True))
                menu.add_separator()
                menu.add_command(label=self.owner.t("raw_copy"), command=lambda key=full_name: self.owner.copy_original(key))
                menu.add_command(label=self.owner.t("restore"), command=lambda key=full_name: self.owner.restore_field(key))
                menu.add_separator()
                menu.add_command(label=self.owner.t("expand_field"),
                                 command=lambda key=full_name: self.toggle_expanded(key))
                frame, text = text_area(cell, editable=True)
                self.headers[full_name] = (field_label, menu_button, menu, cell)
                frame.configure(bg=SURFACE, padx=0, pady=0)
                frame.pack(fill="x", padx=1, pady=1)
                text.configure(height=3, padx=8, pady=3, takefocus=True,
                               highlightthickness=1, highlightbackground=LINE, highlightcolor=CYAN)
                text.configure(exportselection=False, undo=True, maxundo=50)
                text.insert("1.0", value)
                text.edit_reset()
                text.edit_modified(False)
                text.bind("<<Modified>>", lambda _, key=full_name, w=text: self.save_change(key, w))
                text.bind("<FocusIn>", lambda _, key=full_name: self.activate(key))
                text.bind("<Button-1>", lambda _, key=full_name: self.activate(key), add=True)
                bind_text_traversal(text)
                if section_row == 0 and len(cells) == 1 and last_text is not None:
                    prev_item, next_item = self.sections[-2][1], self.sections[-1][1]
                    last_text.bind("<Tab>", lambda e, w=action, i=next_item: self.focus_section_edge(w, i, False))
                    action.bind("<Shift-Tab>", lambda e, w=last_text, i=prev_item: self.focus_section_edge(w, i, True))
                last_text = text
                self.panels[full_name] = (text, action)
            self.groups.append((group, cells))
            self.layout(group, cells)
            self.tag_children(group)
        if self.panels:
            self.activate(next(iter(self.panels)))
        self.schedule_measure()
        self.canvas.yview_moveto(0)

    def activate(self, key):
        if self.active == key:
            return
        if self.actions is not None:
            self.actions.destroy()
        self.active = key
        self.actions = tk.Frame(self.headers[key][3], bg=SURFACE)
        self.actions.pack(fill="x", padx=6, pady=(0, 4))
        self.add_selection = button(self.actions, self.owner.t("select"), lambda: self.owner.queue_field(key, True))
        self.add_full = button(self.actions, self.owner.t("full"), lambda: self.owner.queue_field(key, False))
        self.expand_action = button(self.actions, self.expansion_text(key), lambda: self.toggle_expanded(key))
        self.compact_actions = None
        for control in (self.add_selection, self.add_full, self.expand_action):
            control.configure(padx=8, pady=2)
        self.arrange_actions()
        self.actions.bind("<Configure>", lambda _: self.arrange_actions())
        self.tag_children(self.actions)
        self.schedule_measure()

    def arrange_actions(self):
        controls = (self.add_selection, self.add_full, self.expand_action)
        width = self.actions.master.winfo_width() - 12
        compact = sum(control.winfo_reqwidth() + 5 for control in controls) > width
        if compact != self.compact_actions:
            self.compact_actions = compact
            for i, control in enumerate(controls):
                control.grid(row=int(compact and i == 2), column=0 if compact and i == 2 else i,
                             sticky="w", padx=(0, 5))

    def expansion_text(self, key):
        return self.owner.t("collapse_field" if self.expanded == key else "expand_field")

    def toggle_expanded(self, key):
        widget = self.panels[key][0]
        target_y = widget.winfo_rooty() - self.canvas.winfo_rooty()
        old_key = self.expanded
        self.expanded = None if key == old_key else key
        if self.anchor_job is not None:
            self.after_cancel(self.anchor_job)
        bookmarks = {}
        for affected in dict.fromkeys((old_key, key)):
            if affected is None:
                continue
            area = self.panels[affected][0]
            bookmarks[area] = area.index("@0,0")
            area.configure(height=11 if self.expanded == affected else 3)
            self.headers[affected][2].entryconfigure(6, label=self.expansion_text(affected))
        if self.actions is not None:
            self.expand_action.configure(text=self.expansion_text(self.active))
            self.arrange_actions()
        self.schedule_measure()

        def restore_view():
            self.anchor_job = None
            for area, first in bookmarks.items():
                area.yview(first)
            new_y = widget.winfo_rooty() - self.canvas.winfo_rooty()
            top = self.canvas.canvasy(0) + new_y - target_y
            self.canvas.yview_moveto(max(0, top) / self.content_height)

        self.anchor_job = self.after_idle(restore_view)

    def refresh_language(self):
        for name, title in self.group_titles:
            title.configure(text=self.owner.group_name(name))
        for key, (field_label, menu_button, menu, _) in self.headers.items():
            field_label.configure(text=self.owner.t(key.rsplit(" ", 1)[1].lower()))
            self.panels[key][1].configure(text=self.owner.t("copy"))
            menu_button.configure(text=self.owner.t("restore"))
            for index, entry in ((0, "full"), (1, "select"), (3, "raw_copy"), (4, "restore")):
                menu.entryconfigure(index, label=self.owner.t(entry))
            menu.entryconfigure(6, label=self.expansion_text(key))
        if self.actions is not None:
            self.add_selection.configure(text=self.owner.t("select"))
            self.add_full.configure(text=self.owner.t("full"))
            self.expand_action.configure(text=self.expansion_text(self.active))
            self.arrange_actions()
        self.schedule_measure()

    def text_value(self, key):
        return self.panels[key][0].get("1.0", "end-1c")

    def save_change(self, key, widget):
        if self.owner.index >= 0 and widget.edit_modified():
            self.owner.edits.set_value(self.owner.index, key, widget.get("1.0", "end-1c"))
            widget.edit_modified(False)

    def flush(self):
        for key, (widget, _) in self.panels.items():
            self.save_change(key, widget)

    def reveal_focus(self, event):
        target = event.widget
        if target == self.canvas or not isinstance(target, (tk.Button, tk.Text, ttk.Menubutton)):
            return
        top = target.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + target.winfo_height()
        height = self.canvas.winfo_height()
        if top < 2 or bottom > height - 2:
            offset = top - 4 if top < 2 else bottom - height + 14
            self.canvas.yview_moveto((self.canvas.canvasy(0) + offset) / self.content_height)

    def scroll(self, widget, amount, units):
        if isinstance(widget, tk.Text):
            first, last = widget.yview()
            if (amount < 0 and first > 0) or (amount > 0 and last < 1):
                widget.yview_scroll(amount, units)
                return "break"
        self.canvas.yview_scroll(amount, units)
        return "break"

    def wheel(self, event):
        if event.delta:
            steps = max(1, round(abs(event.delta) / 120)) * 3
            return self.scroll(event.widget, -steps if event.delta > 0 else steps, "units")

    def jump(self, widget, fraction):
        target = widget if isinstance(widget, tk.Text) and widget.yview() != (0.0, 1.0) else self.canvas
        target.yview_moveto(fraction)
        return "break"


def bind_text_traversal(text):
    # The Tk Text class normally consumes Tab to insert a tab character.
    for sequence, direction in (("<Tab>", "tk_focusNext"), ("<Shift-Tab>", "tk_focusPrev")):
        def move(_event, direction=direction):
            text.tk.call("focus", text.tk.call(direction, text))
            return "break"
        text.bind(sequence, move)


class BundleReader:
    def __init__(self, root, *, automatic=True, language=None):
        self.root = root
        self.ui = language if language is not None else Language()
        theme.install(root)
        self.cards = []
        self.edits = EditSession(())
        self.serial = 0
        self.running = False
        self.events = queue.Queue()
        self.source = ""
        self.pending_source = "aitag.win"
        self.index = -1
        self.timer = None
        self.connection = None
        self.connection_error = None
        self.connection_check_at = 0
        self.connection_state = ""
        self.raw_open = False
        self.note_state = ("blank", False, {})
        self.blank_state = ("empty_title", "empty_hint", {})
        self.count_state = None
        self.file_dialog_open = False
        self.native_images = None
        if automatic:
            self.open_connection()
        root.geometry(f"{min(1180, root.winfo_screenwidth()-35)}x{min(820, root.winfo_screenheight()-85)}")
        root.minsize(680, 500)
        root.configure(bg=BG)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.help_window = HelpWindow(root, self.ui)
        self.chrome_setup = ChromeSetup(self)
        self.header = head = tk.Frame(root, bg=HEADER, padx=14, pady=6)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        self.brand = theme.brand(head)
        self.brand.grid(row=0, column=0, padx=(0, 9))
        self.title = label(head, size=14, bold=True)
        self.title.grid(row=0, column=1, sticky="w")
        self.help_button = button(head, "", self.help_window.show)
        self.help_button.grid(row=0, column=5, sticky="e")
        self.about_button = button(head, self.ui.t("ui.about"), lambda: self.help_window.show("about"))
        self.about_button.grid(row=0, column=4, sticky="e", padx=4)
        self.language_picker = ttk.Combobox(head, values=tuple(LANGUAGE_NAMES.values()), width=8,
                                             state="readonly", takefocus=True)
        self.language_picker.grid(row=0, column=3, sticky="e", padx=5)
        self.language_picker.bind("<<ComboboxSelected>>", self.pick_language)
        self.connection_status = label(head, size=9, color=MUTED)
        self.connection_status.grid(row=0, column=2, sticky="e", padx=(0, 4))
        self.compact_header = None
        self.compact_import = None
        self.layout_job = None

        self.source_bar = source = tk.Frame(root, bg=SURFACE, padx=12, pady=7)
        source.grid(row=1, column=0, sticky="ew")
        source.columnconfigure(2, weight=1)
        self.inspect_btn = button(source, "", self.start_inspect)
        self.inspect_btn.configure(fg=VIOLET)
        self.inspect_btn.grid(row=0, column=0, padx=(0, 10))
        self.link_label = label(source, size=9, color=MUTED)
        self.link_label.grid(row=0, column=1, padx=(0, 5))
        self.link = ttk.Entry(source, width=8)
        self.link.grid(row=0, column=2, sticky="ew")
        self.link.bind("<Return>", lambda _: self.start())
        self.read_btn = button(source, "", self.start)
        self.read_btn.grid(row=0, column=3, padx=(6, 0))

        body = tk.Frame(root, bg=BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        self.side = side = tk.Frame(body, bg=SURFACE, width=170, height=48, padx=6)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)
        self.side_title = label(side, size=11, bold=True, anchor="w")
        self.side_title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(10, 2))
        self.counter = label(side, size=9, color=MUTED, anchor="w", justify="left", wraplength=150)
        self.counter.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4)
        self.image_rows = tk.StringVar(root)
        self.list = tk.Listbox(side, listvariable=self.image_rows, bg=SURFACE, fg=TEXT,
                               selectbackground="#59344b", selectforeground=TEXT, relief="flat",
                               bd=0, highlightthickness=1, highlightbackground=SURFACE, highlightcolor=CYAN,
                               activestyle="dotbox", exportselection=False, width=1, font=("Malgun Gothic", 10))
        self.list.grid(row=2, column=0, sticky="nsew", pady=6)
        bar = ttk.Scrollbar(side, command=self.list.yview)
        bar.grid(row=2, column=1, sticky="ns", pady=6)
        self.list.configure(yscrollcommand=bar.set)
        self.list.bind("<<ListboxSelect>>", lambda _: self.show_card())
        self.setup_button = button(side, "", self.chrome_setup.show)
        self.setup_button.configure(wraplength=115, padx=3)
        self.setup_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 7))
        self.transfer = TransferWindow(root, self.queue_changed, ui=self.ui)
        self.transfer.show_help = lambda: self.help_window.show("send")
        self.main = tk.Frame(body, bg=BG, padx=8, pady=4)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)
        top = tk.Frame(self.main, bg=BG)
        top.grid(row=0, column=0, sticky="ew", padx=4, pady=(3, 2))
        top.columnconfigure(0, weight=1)
        self.heading = label(top, size=9, color=MUTED, anchor="w")
        self.heading.grid(row=0, column=0, sticky="ew")
        self.edit_label = label(top, size=14, bold=True, anchor="w")
        self.edit_label.grid(row=1, column=0, sticky="ew")
        self.transfer_button = button(top, "", self.transfer.show, primary=True)
        self.transfer_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.prompts = PromptPanels(self.main, self)
        self.prompts.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        raw_header = tk.Frame(self.main, bg=BG)
        raw_header.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.raw_toggle = button(raw_header, "", self.toggle_raw)
        self.raw_toggle.pack(side="left")
        self.raw_label = label(raw_header, size=9, color=MUTED)
        self.raw_label.pack(side="left", padx=6)
        self.raw_btn = button(raw_header, "", self.copy_raw)
        self.raw_btn.pack(side="right")
        self.raw_frame, self.raw = text_area(self.main)
        self.raw.configure(height=3, takefocus=True)
        bind_text_traversal(self.raw)
        self.raw_frame.grid(row=3, column=0, sticky="ew", pady=(3, 0))

        self.blank = tk.Frame(body, bg=BG)
        self.blank.grid(row=0, column=1, sticky="nsew")
        center = tk.Frame(self.blank, bg=BG)
        center.place(relx=.5, rely=.45, anchor="center")
        self.blank_title = label(center, size=15, bold=True, wraplength=340)
        self.blank_title.pack()
        self.hint = label(center, size=10, color=MUTED, wraplength=340)
        self.hint.pack(padx=8, pady=(8, 0))
        self.status = label(root, size=9, color=MUTED, anchor="w", bg=HEADER, padx=12, pady=3)
        self.status.grid(row=3, column=0, sticky="ew")
        root.bind("<Configure>", self.resize, add=True)
        self.clear("empty_title", "empty_hint")
        self.unsubscribe = self.ui.subscribe(self.refresh_language)
        self.refresh_language()
        self.inspect_btn.focus_set()
        if os.name == "nt":
            try:
                self.native_images = WindowsImageInput(self.image_blocked, lambda: self.serial)
            except OSError:
                pass
        if self.native_images is not None:
            self.image_paste_tag = f"ReaderImageInput{root}"
            root.bind_class(self.image_paste_tag, "<<Paste>>", self.paste_image)
            root.bind_all("<Map>", self.tag_image_widget, add=True)
            root.bind("<Destroy>", self.destroy_image_input, add=True)
            self.tag_image_tree(root)
        self.timer = root.after(40, self.poll)
        if automatic and (self.connection_error or self.connection.first_run):
            root.after_idle(self.chrome_setup.show)

    def open_connection(self, *, recover=False):
        try:
            self.connection = ReaderConnection.recover_pairing() if recover else ReaderConnection()
        except PairingKeyError as exc:
            self.connection_error = exc.code
        except OSError:
            self.connection_error = "connect_busy"
        else:
            self.connection_error = None
            self.connection_check_at = 0

    def connection_error_label(self):
        if self.connection_error == "connect_busy":
            return "reader.connect_busy"
        return "setup." + self.connection_error if self.connection_error else None

    def t(self, key, **values):
        return self.ui.t("reader." + key, **values)

    def group_name(self, name):
        if name == "Base":
            return self.t("base")
        return self.t("character", n=name.split()[1])

    def field_name(self, field):
        group, kind = field.rsplit(" ", 1)
        return self.group_name(group) + " · " + self.t(kind.lower())

    def pick_language(self, _event=None):
        index = self.language_picker.current()
        if index >= 0:
            try:
                self.ui.set(tuple(LANGUAGE_NAMES)[index])
            except OSError:
                self.note("language_error", True)
            self.language_picker.set(LANGUAGE_NAMES[self.ui.lang])

    def resize(self, event):
        if event.widget is self.root:
            small = event.width < self.root.winfo_pixels("650p")
            width = 140 if small else 184
            if self.side.winfo_reqwidth() != width:
                self.side.configure(width=width)
                self.counter.configure(wraplength=width-16)
            self.status.configure(wraplength=max(280, event.width-30))
            self.schedule_layout()

    def schedule_layout(self):
        if self.layout_job is None:
            self.layout_job = self.root.after_idle(self.arrange)

    def arrange(self):
        self.layout_job = None
        width = self.root.winfo_width()
        head_widgets = (self.brand, self.title, self.connection_status, self.language_picker,
                        self.about_button, self.help_button)
        compact = sum(w.winfo_reqwidth() for w in head_widgets) + 70 > width
        if compact != self.compact_header:
            self.compact_header = compact
            self.brand.grid_configure(rowspan=2 if compact else 1)
            self.title.grid_configure(columnspan=2 if compact else 1)
            self.connection_status.grid_configure(row=int(compact), column=1 if compact else 2,
                                                 sticky="w" if compact else "e")
            self.about_button.grid_configure(row=int(compact), column=3 if compact else 4,
                                            columnspan=3 if compact else 1)
            self.help_button.grid_configure(column=4 if compact else 5)
        controls = (self.inspect_btn, self.link_label, self.read_btn)
        compact = sum(w.winfo_reqwidth() for w in controls) + self.root.winfo_pixels("100p") > width
        if compact != self.compact_import:
            self.compact_import = compact
            self.source_bar.columnconfigure(1, weight=int(compact))
            self.source_bar.columnconfigure(2, weight=int(not compact))
            self.inspect_btn.grid_configure(row=0, column=0, columnspan=3 if compact else 1, sticky="w")
            self.link_label.grid_configure(row=int(compact), column=0 if compact else 1)
            self.link.grid_configure(row=int(compact), column=1 if compact else 2)
            self.read_btn.grid_configure(row=int(compact), column=2 if compact else 3)

    def refresh_language(self):
        self.root.title(self.t("name"))
        self.about_button.configure(text=self.ui.t("ui.about"))
        self.setup_button.configure(text=self.ui.t("setup.title"))
        self.chrome_setup.refresh()
        self.language_picker.set(LANGUAGE_NAMES[self.ui.lang])
        for widget, key in ((self.title, "name"), (self.help_button, "help"), (self.inspect_btn, "inspect"),
                            (self.link_label, "link"), (self.read_btn, "web"), (self.side_title, "images"),
                            (self.edit_label, "edit"), (self.raw_btn, "raw_copy")):
            widget.configure(text=self.t(key))
        self.queue_changed()
        self.draw_connection()
        self.draw_blank()
        self.draw_list()
        self.draw_heading()
        self.draw_counter()
        self.draw_raw_label()
        self.draw_note()
        self.prompts.refresh_language()
        self.transfer.refresh_language()
        self.schedule_layout()

    def source_name(self):
        if self.source in ("aitag.win", "local_png"):
            return self.t("source_web" if self.source == "aitag.win" else "source_png")
        return self.source

    def card_kind(self, card):
        if card.status != "ok":
            return self.t(card.status)
        return self.t(card.structure, n=len(card.characters))

    def draw_list(self):
        offset = self.list.yview()[0]
        rows = [f"{i+1:02}  {self.card_kind(card)}" for i, card in enumerate(self.cards)]
        self.image_rows.set(tuple(rows))
        if self.index >= 0:
            self.list.selection_set(self.index)
            self.list.activate(self.index)
            self.list.yview_moveto(offset)

    def draw_heading(self):
        if self.index < 0:
            self.heading.configure(text="")
            return
        card = self.cards[self.index]
        parts = [self.t("image", n=self.index+1), card.source_format if card.source_format != "unknown"
                 else self.t("format_unknown")]
        if card.model_family == "unknown":
            parts.append(self.t("family_unknown"))
        parts.append(self.card_kind(card))
        if card.filename:
            parts.append(card.filename[:128] + ("…" if len(card.filename) > 128 else ""))
        self.heading.configure(text=" · ".join(parts))

    def draw_counter(self):
        if self.count_state is not None:
            key, n = self.count_state
            value = self.t(key, n=n)
        elif self.cards:
            counts = [f"{self.t(key)} {sum(c.status == key for c in self.cards)}"
                      for key in ("ok", "empty", "missing", "failed") if any(c.status == key for c in self.cards)]
            value = self.source_name() + " · " + self.t("total", n=len(self.cards)) + "\n" + " · ".join(counts)
        else:
            value = ""
        self.counter.configure(text=value)

    def draw_connection(self):
        key = {"연결됨": "connected", "연결 종료": "closed", "Chrome 실행 필요": "open_chrome",
               "Chrome 확장 확인 필요": "extension", "연결 복구 중": "reconnect"}.get(self.connection_state)
        if self.connection_error:
            key = None
        text = self.t(key) if key else ""
        if self.connection_error:
            text = self.ui.t("setup.check")
        self.chrome_setup.update_status()
        if self.connection_status.cget("text") != text:
            self.connection_status.configure(text=text, fg=OK if key == "connected" else MUTED)
            self.schedule_layout()

    def close(self):
        if self.transfer.pending:
            if not theme.confirm(self.root, self.t("exit"), self.t("exit_pending"), self.ui):
                return
        elif not self.confirm_discard("exit"):
            return
        self.unsubscribe()
        if self.layout_job is not None:
            self.root.after_cancel(self.layout_job)
        if self.timer:
            self.root.after_cancel(self.timer)
        if self.connection:
            self.connection.close()
        self.root.destroy()

    def queue_changed(self):
        self.transfer_button.configure(text=self.t("send", n=len(self.transfer.items)))

    def has_work(self):
        self.prompts.flush()
        return self.edits.dirty or bool(self.transfer.items)

    def confirm_discard(self, operation, detail=None):
        if self.transfer.pending:
            self.note("wait_result", True)
            return False
        discard = self.has_work()
        messages = [note for note in (detail, self.t("discard") if discard else None) if note]
        return not messages or theme.confirm(self.root, self.t(operation), "\n\n".join(messages), self.ui)

    def copy_original(self, field):
        self.copy(self.edits.original(self.index, field))

    def restore_field(self, field):
        widget = self.prompts.panels[field][0]
        widget.replace("1.0", "end-1c", self.edits.original(self.index, field))
        self.prompts.save_change(field, widget)
        self.note("restored", field=field)

    def queue_field(self, field, selected_only):
        widget = self.prompts.panels[field][0]
        if selected_only:
            if not widget.tag_ranges("sel") or widget.compare("sel.first", ">=", "end-1c"):
                self.note("no_selection", True)
                return
            last = "end-1c" if widget.compare("sel.last", ">", "end-1c") else "sel.last"
            text = widget.get("sel.first", last)
        else:
            text = self.prompts.text_value(field)
        self.transfer.add_source(self.edits.capture(self.index, field, text, scope="selection" if selected_only else "full"))
        self.note("added", n=self.index+1, field=field)

    def local_message(self, key, values):
        params = values.copy()
        if "detail" in params:
            detail = params["detail"]
            params["detail"] = (self.ui.t(detail) if detail == "reader.connect_busy" or
                                detail.startswith("setup.PAIRING_KEY_") else self.ui.diagnostic(detail))
        if "title" in params:
            params["title"] = self.t(params["title"])
        if "field" in params:
            params["field"] = self.field_name(params["field"])
        if key == "position":
            params["source"] = self.source_name()
        return self.t(key, **params)

    def note(self, key, error=False, **values):
        self.note_state = (key, error, values)
        self.draw_note()

    def draw_note(self):
        key, error, values = self.note_state
        self.status.configure(text=self.local_message(key, values), fg=DANGER if error else MUTED)

    def draw_blank(self):
        title, detail, values = self.blank_state
        self.blank_title.configure(text=self.t(title))
        self.hint.configure(text=self.local_message(detail, values))

    def clear(self, title, detail_key, **values):
        self.serial += 1
        self.cards = []
        self.edits = EditSession(())
        self.index = -1
        self.source = ""
        self.count_state = None
        self.list.delete(0, "end")
        self.heading.configure(text="")
        self.counter.configure(text="")
        self.raw_btn.configure(state="disabled")
        self.raw_toggle.configure(state="disabled")
        self.set_raw_open(False)
        display(self.raw, "")
        self.prompts.show(())
        self.main.grid_remove()
        self.blank.tkraise()
        self.blank_state = (title, detail_key, values)
        self.draw_blank()
        self.note("blank")

    def start(self):
        self.start_source("aitag.win")

    def start_inspect(self):
        self.start_source("NovelAI Inspect")

    def start_source(self, source):
        if self.running:
            return
        inspect = source == "NovelAI Inspect"
        url = self.link.get().strip()
        if self.has_work():
            self.note("collecting")
        else:
            self.clear("request", "inspect_detail" if inspect else "web_detail")
        if self.connection_error:
            self.collection_error("connect_fail", self.connection_error_label())
            return
        self.pending_source = source
        self.serial += 1
        turn = self.serial
        self.set_running(True)

        def work():
            try:
                progress = lambda count: self.events.put((turn, "count", count))
                if self.connection:
                    cards = self.connection.read_inspect(progress) if inspect else self.connection.read_link(url, progress)
                else:
                    cards = read_inspect(progress) if inspect else read_link(url, progress)
                self.events.put((turn, "done", cards))
            except (ValueError, OSError, RecursionError) as exc:
                self.events.put((turn, "error", str(exc)))
            except Exception:
                self.events.put((turn, "error", "브라우저가 묶음 결과를 전달하지 못했습니다."))

        threading.Thread(target=work, daemon=True).start()

    def set_running(self, value):
        self.running = value
        state = "disabled" if value else "normal"
        self.read_btn.configure(state=state)
        self.inspect_btn.configure(state=state)

    def tag_image_tree(self, widget):
        self.tag_image_widget(widget)
        for child in widget.winfo_children():
            self.tag_image_tree(child)

    def tag_image_widget(self, event):
        widget = event.widget if isinstance(event, tk.Event) else event
        if not isinstance(widget, tk.Misc):
            return  # Tk-only widgets, such as the Combobox popdown.
        tags = widget.bindtags()
        if self.image_paste_tag not in tags:
            widget.bindtags((self.image_paste_tag, *tags))
        if widget is self.root or isinstance(widget, tk.Toplevel):
            self.native_images.attach(widget.winfo_id())

    def destroy_image_input(self, event):
        if event.widget is self.root and self.native_images is not None:
            self.native_images.close()
            self.native_images = None

    def image_blocked(self):
        return (self.running or self.transfer.pending or self.transfer.busy or self.file_dialog_open
                # A Tk-only popdown can hold a grab without a Python widget.
                or bool(self.root.tk.call("grab", "current", self.root)))

    def paste_image(self, event):
        widget = event.widget
        if not isinstance(widget, tk.Misc):
            return None
        editing = (isinstance(widget, (tk.Text, tk.Entry, tk.Spinbox, ttk.Entry))
                   and str(widget.cget("state")) == "normal")
        value = self.native_images.paste(widget.winfo_id(), editing=editing)
        if value is not None:
            self.start_image_input(value)
            return "break"

    def start_image_input(self, value):
        if self.image_blocked():
            self.note("image_busy", True)
            return False
        if value.error:
            self.note(value.error, True)
            return False
        self.serial += 1
        turn = self.serial
        self.set_running(True)
        self.note("image_reading")

        def work():
            try:
                cards = read_png_batch(paths=value.paths, png=value.png)
            except (ValueError, OSError, RecursionError):
                self.events.put((turn, "local_error", None))
            else:
                self.events.put((turn, "local_done", cards))

        threading.Thread(target=work, daemon=True).start()
        return True

    def present_images(self, cards):
        if self.image_blocked():
            self.note("image_busy", True)
            return
        useful = sum(card.status == "ok" for card in cards)
        missing = sum(card.status == "missing" for card in cards)
        if not useful:
            if len(cards) == 1:
                self.note(self.image_note(cards[0]), True)
            else:
                self.note("image_no_results", True, missing=missing, failed=len(cards)-missing)
            return
        detail = (self.t("image_partial", ok=useful, missing=missing, failed=len(cards)-useful-missing)
                  if useful != len(cards) else None)
        if self.present(cards, "local_png", detail=detail):
            self.link.delete(0, "end")
        else:
            self.note("image_cancelled")

    @staticmethod
    def image_note(card):
        if card.status == "missing":
            return "image_no_metadata"
        return {"unsupported": "image_unsupported", "local_path": "image_local_only",
                "too_large": "image_limit", "original_limit": "image_original_limit"}.get(
                    card.issue, "image_unreadable" if card.status == "failed" else "image_original")

    def poll(self):
        now = time.monotonic()
        if now - self.connection_check_at >= 1:
            self.connection_check_at = now
            self.connection_state = self.connection.state() if self.connection else ""
            self.draw_connection()
        while True:
            try:
                turn, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if turn != self.serial:
                continue
            if kind != "count":
                self.set_running(False)
            if kind == "count":
                if self.cards:
                    self.note("progress", n=value)
                    break
                inspect = self.pending_source == "NovelAI Inspect"
                self.count_state = ("progress_inspect" if inspect else "progress", value)
                self.draw_counter()
                self.blank_state = ("reading", "inspect_detail" if inspect else "reading_web", {"n": value})
                self.draw_blank()
                # Let Tk paint the confirmed count before consuming an already
                # queued result from a small, quickly collected work.
                break
            elif kind == "done":
                self.present(value, self.pending_source)
            elif kind == "local_done":
                self.present_images(value)
            elif kind == "local_error":
                self.note("image_unreadable", True)
            else:
                self.collection_error("import_fail", value)
        if self.native_images is not None and self.native_images.drops:
            received_at, value = self.native_images.drops.popleft()
            if received_at == self.serial:
                self.start_image_input(value)
            else:
                self.note("image_busy", True)
        self.timer = self.root.after(40, self.poll)

    def open_bookmark(self):
        guide = Path(__file__).resolve().with_name("bookmark.html").as_uri()
        match = URL.fullmatch(self.link.get().strip())
        if match:
            guide += "#work=" + match["work"]
            if match["lang"]:
                guide += "&lang=" + match["lang"]
        try:
            os.startfile(guide)
        except OSError:
            self.note("bookmark", True)

    def open_file(self):
        if self.image_blocked():
            self.note("image_busy", True)
            return
        self.file_dialog_open = True
        try:
            filename = filedialog.askopenfilename(parent=self.root, title=self.t("file_open"),
                                                  filetypes=[(self.t("file_types"), "*.json *.png"), (self.t("all_files"), "*.*")])
        finally:
            self.file_dialog_open = False
        if filename:
            self.load_file(Path(filename))

    def collection_error(self, title, detail):
        if self.cards:
            self.note("failed_note", True, title=title, detail=detail)
        else:
            self.clear(title, "diagnostic", detail=detail)
            self.note("retry", True)

    def load_file(self, path):
        self.serial += 1
        if self.running:
            self.set_running(False)
        if not self.has_work():
            self.clear("file_read", "blank")
        try:
            if path.suffix.lower() == ".png":
                data = read_local(path)
            else:
                with path.open("rb") as source:
                    content = source.read(16 * 1024 * 1024 + 1)
                if len(content) > 16 * 1024 * 1024:
                    raise ValueError("묶음 파일은 16 MiB까지 열 수 있습니다.")
                data = json.loads(content.decode("utf-8-sig"))
                if len(content) > 8 * 1024 * 1024 and not (isinstance(data, dict) and data.get("format") == FORMAT):
                    raise ValueError("일반 JSON 파일은 8 MiB까지 열 수 있습니다.")
            cards = decode_input(data, png=path.suffix.lower() == ".png",
                                 filename=path.name if path.suffix.lower() == ".png" else None)
            if self.present(cards, path.name):
                self.link.delete(0, "end")
        except (ValueError, OSError, RecursionError) as exc:
            self.collection_error("file_fail", str(exc))

    def present(self, cards, source, *, detail=None):
        if not cards:
            self.collection_error("no_images", "")
            return False
        if not self.confirm_discard("replace", detail):
            return False
        self.transfer.clear()
        self.index = -1
        self.edits = EditSession(cards)
        self.cards = cards
        self.source = source
        self.count_state = None
        self.draw_counter()
        self.draw_list()
        self.list.selection_clear(0, "end")
        self.list.selection_set(0)
        self.list.activate(0)
        self.list.see(0)
        self.main.grid()
        self.main.tkraise()
        self.show_card()
        return True

    def show_card(self):
        selected = self.list.curselection()
        if not selected or not self.cards or self.index == selected[0]:
            return
        self.prompts.flush()
        self.index = selected[0]
        card = self.cards[self.index]
        self.draw_heading()
        self.raw_btn.configure(state="disabled" if card.readable is None else "normal")
        self.raw_toggle.configure(state=self.raw_btn.cget("state"))
        self.set_raw_open(False)
        display(self.raw, card.readable or "")
        self.prompts.show(self.edits.fields(self.index) if card.status == "ok" else ())
        if card.origin == "local_png":
            self.note(self.image_note(card), card.status != "ok")
        elif card.status != "ok":
            self.note("note_" + card.status)
        elif card.local:
            self.note("note_local")
        elif card.structure == "unknown":
            self.note("note_unknown")
        else:
            self.note("position", n=self.index+1, total=len(self.cards))

    def draw_raw_label(self):
        self.raw_toggle.configure(text=("▾ " if self.raw_open else "▸ ") +
                                  self.t("hide_raw" if self.raw_open else "show_raw"))
        origin = self.cards[self.index].origin if self.index >= 0 else None
        kind = {"novelai_inspect": "raw_inspect", "local_png": "raw_png"}.get(origin, "raw_web")
        self.raw_label.configure(text=self.t(kind) if self.raw_open else "")

    def set_raw_open(self, opened):
        self.raw_open = opened
        if opened:
            self.raw_frame.grid()
        else:
            self.raw_frame.grid_remove()
        self.draw_raw_label()

    def toggle_raw(self):
        self.set_raw_open(not self.raw_frame.winfo_manager())

    def copy(self, value):
        if value is None:
            return
        try:
            copy_text(self.root.winfo_id(), value)
        except ClipboardError as exc:
            self.note("diagnostic", True, detail=str(exc))
        else:
            self.note("copy_empty" if value == "" else "copied")

    def copy_raw(self):
        if self.index >= 0:
            self.copy(self.cards[self.index].readable)

def main():
    if os.name == "nt":
        ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    BundleReader(root)
    root.mainloop()

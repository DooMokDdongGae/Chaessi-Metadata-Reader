"""Dark Tk controls shared by the reader and transfer windows."""
import hashlib
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

BG, HEADER, SURFACE, SURFACE2 = "#07080b", "#0d1017", "#11141b", "#171b25"
LINE, TEXT, MUTED = "#2a3140", "#edf3ff", "#91a0b6"
VIOLET, MAGENTA, CYAN, BLUE = "#a78bfa", "#f472b6", "#67e8f9", "#7dd3fc"
DANGER, OK, INPUT, PRIMARY = "#fb7185", "#86efac", "#090c12", "#853ea0"
_BRANDING = Path(__file__).resolve().parent / "assets" / "branding"
_SYMBOL_SHA = "151085074a237f856cf900b586641600ed04638af8b1ba0d7923df651b152d73"


def font(lang, size=10, bold=False):
    code = getattr(lang, "lang", lang)
    family = {"ko": "Malgun Gothic", "en": "Segoe UI", "ja": "Yu Gothic UI"}.get(code, "Segoe UI")
    return family, size, "bold" if bold else "normal"


def install(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    root.option_add("*Font", "TkDefaultFont")
    root.option_add("*Menu.background", SURFACE)
    root.option_add("*Menu.foreground", TEXT)
    root.option_add("*Menu.activeBackground", SURFACE2)
    root.option_add("*Menu.activeForeground", CYAN)
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", PRIMARY)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    style.configure(".", background=SURFACE, foreground=TEXT, bordercolor=LINE, focuscolor=CYAN,
                    lightcolor=LINE, darkcolor=LINE, troughcolor=BG, selectbackground=PRIMARY,
                    selectforeground=TEXT, fieldbackground=INPUT, arrowcolor=TEXT)
    style.configure("TButton", background=SURFACE2, padding=(9, 5))
    style.map("TButton", background=[("disabled", SURFACE), ("active", "#232a3b")],
              foreground=[("disabled", MUTED)], bordercolor=[("focus", CYAN), ("active", VIOLET)])
    style.configure("Primary.TButton", background=PRIMARY, foreground="#ffffff", bordercolor="#c961a7")
    style.map("Primary.TButton", background=[("disabled", SURFACE), ("active", "#ad4483")])
    style.configure("TEntry", padding=5)
    style.map("TEntry", bordercolor=[("focus", CYAN)])
    style.configure("TCombobox", padding=4, arrowsize=15, arrowcolor=TEXT)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE2), ("disabled", SURFACE)],
              foreground=[("disabled", MUTED), ("readonly", TEXT)],
              background=[("readonly", SURFACE2)], bordercolor=[("focus", CYAN)])
    style.configure("Treeview", background=INPUT, fieldbackground=INPUT, foreground=TEXT, rowheight=26)
    style.map("Treeview", background=[("selected", "#483046")], foreground=[("selected", "#fce3f3")])
    style.configure("Treeview.Heading", background=SURFACE2, foreground=TEXT, padding=4)
    style.configure("TCheckbutton", background=SURFACE, foreground=TEXT)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=VIOLET)
    return style


def brand(parent):
    folder = Path(os.environ.get("CHAESSI_BRANDING_DIR") or _BRANDING)
    label = tk.Label(parent, text="CHAESSI", fg=MAGENTA, bg=HEADER, font=("Segoe UI", 10, "bold"))
    if not folder.is_absolute() or folder.drive.startswith("\\\\"):
        return label
    try:
        with (folder / "chaessi-symbol.png").open("rb") as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != _SYMBOL_SHA:
            return label
        original = tk.PhotoImage(master=parent, data=data, format="png")
        image = original.subsample(max(1, round(original.width() / parent.winfo_fpixels("34p"))))
        label.configure(image=image, text="")
        label.brand_image = image
        parent.winfo_toplevel().iconphoto(True, image)
    except (tk.TclError, OSError):
        pass
    return label


def _message(parent, title, message, language, question):
    window = tk.Toplevel(parent)
    window.withdraw()
    window.title(title)
    window.configure(bg=SURFACE, padx=16, pady=14)
    window.transient(parent.winfo_toplevel())
    window.columnconfigure(0, weight=1)
    body = tk.Label(window, text=message, justify="left", anchor="w", wraplength=460,
                    bg=SURFACE, fg=TEXT, font=font(language))
    body.grid(row=0, column=0, sticky="ew", pady=(0, 14))
    controls = ttk.Frame(window)
    controls.grid(row=1, column=0, sticky="e")
    confirmed = False

    def finish(yes):
        nonlocal confirmed
        confirmed = yes
        window.destroy()

    if question:
        initial = ttk.Button(controls, text=language.t("ui.cancel"), command=lambda: finish(False))
        initial.pack(side="left", padx=(0, 6))
        ttk.Button(controls, text=language.t("ui.yes"), command=lambda: finish(True)).pack(side="left")
    else:
        initial = ttk.Button(controls, text=language.t("ui.close"), command=lambda: finish(True))
        initial.pack()
    window.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    window.bind("<Escape>", lambda _: finish(False))
    window.update_idletasks()
    top = parent.winfo_toplevel()
    x = max(0, top.winfo_rootx() + (top.winfo_width() - window.winfo_reqwidth()) // 2)
    y = max(0, top.winfo_rooty() + (top.winfo_height() - window.winfo_reqheight()) // 2)
    window.geometry(f"+{x}+{y}")
    window.deiconify()
    window.wait_visibility()
    window.grab_set()
    initial.focus_set()
    parent.wait_window(window)
    return confirmed


def confirm(parent, title, message, language):
    return _message(parent, title, message, language, True)


def info(parent, title, message, language):
    _message(parent, title, message, language, False)

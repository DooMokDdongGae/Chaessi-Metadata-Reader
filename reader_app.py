"""Shared visual and bounded local-input helpers for the bundle reader."""

import json
import os
import re
import stat
import tkinter as tk
from pathlib import Path

from reader_parser import ParserError, load_png
from tkinter import ttk
from bundle import ui
from bundle.model import Card, decode_input


FONT = "Malgun Gothic"
JSON_LIMIT = 8 * 1024 * 1024
PNG_LIMIT = 32 * 1024 * 1024
PNG_BATCH_LIMIT = 64 * 1024 * 1024
PNG_BATCH_COUNT = 32
PNG_BATCH_TEXT_LIMIT = 16 * 1024 * 1024



def parse_json(text):
    if len(text) > JSON_LIMIT or len(text.encode("utf-8")) > JSON_LIMIT:
        raise ValueError("JSON은 8 MiB까지 열 수 있습니다.")
    try:
        return json.loads(text.lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 문법 오류 · {exc.lineno}행 {exc.colno}열") from exc
    except RecursionError as exc:
        raise ValueError("JSON 중첩이 너무 깊습니다.") from exc


def read_local(path):
    png = path.suffix.lower() == ".png"
    limit = PNG_LIMIT if png else JSON_LIMIT
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"이 파일 형식은 {limit // (1024 * 1024)} MiB까지 열 수 있습니다.")
    if png:
        return read_png_bytes(data)
    try:
        return parse_json(data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError("UTF-8 JSON 파일을 선택해 주세요.") from exc


def read_png_bytes(data):
    if len(data) > PNG_LIMIT:
        raise ParserError("too_large", "PNG files must be at most 32 MiB.")
    return load_png(data)


def local_png_path(name, drive_type=None):
    path = Path(name)
    if path.suffix.lower() != ".png":
        raise ParserError("unsupported", "Only PNG files are supported.")
    if not path.is_absolute() or ".." in path.parts:
        raise ParserError("local_path", "Choose an absolute local file.")
    if os.name == "nt":
        # Drive-relative, UNC, device, alternate data stream and remote
        # drive paths are not local image inputs.
        if not re.fullmatch(r"[a-zA-Z]:\\", path.anchor) or any(":" in part for part in path.parts[1:]):
            raise ParserError("local_path", "Choose a local drive.")
        if drive_type is None:
            from ctypes import windll
            drive_type = windll.kernel32.GetDriveTypeW
        if drive_type(path.anchor) not in (2, 3, 5, 6):
            raise ParserError("local_path", "Choose a local drive.")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ParserError("local_path", "Linked paths are not supported.")
    if not stat.S_ISREG(info.st_mode):
        raise ParserError("local_path", "Choose a regular file.")
    return path


def read_png_batch(*, paths=(), png=None):
    """Return one ordered result per input. This worker never touches Tk."""
    if png is not None and paths or len(paths) > PNG_BATCH_COUNT:
        raise ParserError("batch_count", "Too many image files.")
    cards = []
    budget = PNG_BATCH_LIMIT
    text_budget = PNG_BATCH_TEXT_LIMIT
    for name in paths if png is None else (None,):
        filename = Path(name).name if name is not None else None
        try:
            data = png
            if name is not None:
                path = local_png_path(name)
                with path.open("rb") as source:
                    size = os.fstat(source.fileno()).st_size
                    if size > PNG_LIMIT or size > budget:
                        raise ParserError("too_large", "Image exceeds the input budget.")
                    data = source.read(min(PNG_LIMIT, budget) + 1)
            if len(data) > budget:
                raise ParserError("too_large", "Image exceeds the input budget.")
            budget -= len(data)
            (card,) = decode_input(read_png_bytes(data), png=True, filename=filename)
            used = len(card.readable or "") + sum(len(value) for _, value in card.fields())
            if used > text_budget:
                raise ParserError("too_large", "Image metadata exceeds the batch text budget.")
            text_budget -= used
        except (ValueError, OSError, RecursionError) as exc:
            issue = exc.code if isinstance(exc, ParserError) else "malformed"
            card = Card("failed", local=True, origin="local_png", filename=filename, issue=issue)
        cards.append(card)
    return cards


def label(parent, text="", size=10, *, bold=False, color=ui.TEXT, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent.cget("bg"), fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), **kw)


def button(parent, text, command, primary=False):
    color = ui.PRIMARY if primary else ui.SURFACE2
    return tk.Button(parent, text=text, command=command, padx=12, pady=5,
                     font=(FONT, 10, "bold" if primary else "normal"), bg=color,
                     fg=ui.TEXT, relief="flat", bd=0, disabledforeground=ui.MUTED,
                     activebackground=ui.SURFACE2, activeforeground=ui.CYAN, cursor="hand2",
                     highlightthickness=1, highlightbackground=ui.LINE, highlightcolor=ui.CYAN, takefocus=True)


def text_area(parent, *, editable=False, mono=False):
    outer = tk.Frame(parent, bg=ui.LINE, padx=1, pady=1)
    text = tk.Text(outer, width=1, height=2, wrap="word", bg=ui.INPUT, fg=ui.TEXT, relief="flat",
                   borderwidth=0, padx=12, pady=8, spacing1=2, spacing3=2, undo=False,
                   font=("Consolas", 10) if mono else (FONT, 11),
                   insertbackground=ui.CYAN, inactiveselectbackground="#59344b",
                   selectbackground="#70415f", selectforeground=ui.TEXT)
    bar = ttk.Scrollbar(outer, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(fill="both", expand=True)
    if not editable:
        text.configure(state="disabled")
    return outer, text


def display(widget, value):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")
    widget.yview_moveto(0)

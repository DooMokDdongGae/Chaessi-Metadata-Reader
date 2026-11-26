"""Bounded startup check used by the installer after it verifies the image."""

import json
import os
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import zlib

from bundle.i18n import Language
from bundle.model import decode_input
from bundle.window import BundleReader
from reader_parser import load_png


def sample():
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    comment = json.dumps({"prompt": "synthetic startup", "uc": "synthetic negative"}).encode("ascii")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"tEXt", b"Software\0NovelAI")
            + chunk(b"tEXt", b"Comment\0" + comment)
            + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b""))


def self_test():
    # A normal Reader starts the Chrome bridge. This test never starts it and
    # supplies a throwaway preference path and Tk profile instead.
    previous_home = os.environ.get("HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="chaessi-reader-health-") as work:
            os.environ["HOME"] = work
            root = tk.Tk(className="ChaessiReaderHealth")
            root.withdraw()
            try:
                reader = BundleReader(root, automatic=False, language=Language(Path(work) / "language.json"))
                cards = decode_input(load_png(sample()), png=True, filename="synthetic.png")
                if not reader.present(cards, "local"):
                    return 2
                root.update_idletasks()
                field = reader.prompts.panels["Base Positive"][0]
                if field.get("1.0", "end-1c") != "synthetic startup" or not cards[0].readable:
                    return 2
                return 0
            finally:
                root.destroy()
    except Exception:
        return 2
    finally:
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home

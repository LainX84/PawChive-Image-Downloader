"""PawChive Image Downloader launcher.

Double-click this file to start the application without a console window
(Windows opens .pyw files with pythonw.exe). It also works from a terminal:

    python PawChiveDownloader.pyw
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def _show_error(message: str) -> None:
    """Report a startup problem even when no console is attached."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "PawChive Image Downloader", 0x10)
        return
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("PawChive Image Downloader", message)
        root.destroy()
    except Exception:
        if sys.stderr:
            print(message, file=sys.stderr)


if sys.version_info < (3, 11):
    _show_error(f"Python 3.11 or newer is required (found {sys.version.split()[0]}).")
    raise SystemExit(1)

_missing = []
for _module in ("PySide6", "httpx", "keyring", "platformdirs"):
    try:
        __import__(_module)
    except ImportError:
        _missing.append(_module)
if _missing:
    _show_error(
        "Some required packages are not installed: " + ", ".join(_missing)
        + "\n\nOpen a terminal in the application folder and run:\n\n    python -m pip install -r requirements.txt"
    )
    raise SystemExit(1)

from pawchive_downloader.app import main  # noqa: E402

raise SystemExit(main())

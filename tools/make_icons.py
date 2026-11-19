"""Regenerate the application icons in packaging/icons from ui/icons.py.

    python tools/make_icons.py

Writes app.png (512 px), app.ico (Windows, 16-256 px) and app.icns (macOS).
Requires Pillow (``python -m pip install pillow``) for the .ico and .icns files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from pawchive_downloader.ui.icons import app_icon_pixmap  # noqa: E402


def main() -> int:
    target = ROOT / "packaging" / "icons"
    target.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(sys.argv)  # noqa: F841 - needed for QPixmap
    sizes = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
    files = {}
    for size in sizes:
        path = target / f"app-{size}.png"
        app_icon_pixmap(size).save(str(path))
        files[size] = path
    (target / "app.png").write_bytes(files[512].read_bytes())
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed: only PNG files were written.")
        return 0
    Image.open(files[256]).save(target / "app.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    Image.open(files[1024]).save(target / "app.icns")
    for path in files.values():
        path.unlink()
    print(f"Icons written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

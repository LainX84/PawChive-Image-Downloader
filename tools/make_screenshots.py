"""Render screenshots of every page with demo data (no real website access).

Usage (development dependencies required):

    python tools/make_screenshots.py docs/screenshots

The demo uses invented authors and generated images served by a simulated
PawChive (respx). It is also a quick way to try the interface.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

import respx  # noqa: E402

from conftest import FakeFile, FakePost, FakeSite, make_image  # noqa: E402
from pawchive_downloader.config.paths import prepare_directories  # noqa: E402
from pawchive_downloader.config.settings import Settings, SettingsStore  # noqa: E402
from pawchive_downloader.core.engine import Engine  # noqa: E402
from pawchive_downloader.diagnostics.logging_setup import setup_logging  # noqa: E402
from pawchive_downloader.site.http import HttpClient  # noqa: E402
from pawchive_downloader.storage.db import Database  # noqa: E402
from pawchive_downloader.storage.migrate import migrate  # noqa: E402
from pawchive_downloader.ui.main_window import MainWindow  # noqa: E402
from pawchive_downloader.downloads.throttle import SpeedMeter  # noqa: E402
from pawchive_downloader.i18n import set_language  # noqa: E402
from pawchive_downloader.ui.theme import apply_theme  # noqa: E402

PALETTES = [("#2b1d4e", "#e86aa6"), ("#0f3b4a", "#7fe0c3"), ("#3a1f12", "#f2b25c"), ("#1b2a52", "#8fb6ff"),
            ("#3d1430", "#ff9e7a"), ("#102a1c", "#b6f08a")]


def artwork(seed: int, label: str, w: int = 900, h: int = 1200) -> bytes:
    """A colourful placeholder 'page' (PNG bytes)."""
    top, bottom = PALETTES[seed % len(PALETTES)]
    image = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, w * 0.3, h)
    grad.setColorAt(0, QColor(top))
    grad.setColorAt(1, QColor(bottom))
    p.fillRect(0, 0, w, h, grad)
    for i in range(7):
        rg = QRadialGradient(QPointF((seed * 97 + i * 211) % w, (seed * 53 + i * 157) % h), 160 + 40 * i)
        rg.setColorAt(0, QColor(255, 255, 255, 60))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(rg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF((seed * 97 + i * 211) % w, (seed * 53 + i * 157) % h), 160 + 40 * i, 160 + 40 * i)
    p.setPen(QColor(255, 255, 255, 230))
    font = QFont("Inter", 46)
    font.setBold(True)
    p.setFont(font)
    p.drawText(image.rect().adjusted(40, 0, -40, -80), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, label)
    p.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def demo_site() -> FakeSite:
    site = FakeSite()
    site.add_creator("41000001", "Lumi Arts")
    site.add_creator("41000002", "Moonfox Studio")
    site.add_creator("41000003", "Kestrel Ink")
    seed = 0

    def pg(cid: str, pid: str, title: str, labels: list[str], node: str = "n1", extra: list[FakeFile] | None = None,
           has_full: bool = True, date: str = "2026-10-01T12:00:00") -> FakePost:
        nonlocal seed
        files = []
        for label in labels:
            seed += 1
            files.append(FakeFile(f"{label.replace(' ', '_').lower()}.png", artwork(seed, label), node))
        return site.publish(cid, FakePost(pid, title, files + (extra or []), has_full=has_full, published=date))

    a, b, c = "41000001", "41000002", "41000003"
    pg(a, "101", "A Specter of Love - Part 2 - Page 32", ["Page 32"], "n2", date="2026-09-02T18:00:00")
    pg(a, "102", "Isla: Origins - Chapter 1 - Pages 10-11", ["Page 10", "Page 11"], "n3", date="2026-09-10T18:00:00")
    pg(a, "103", "Development Update", [], date="2026-09-15T10:00:00")
    pg(a, "104", "A Specter of Love - Part 2 - Page 35", ["Page 35"], "n1",
       extra=[FakeFile("Part2_HiRes_pack.7z", make_image(7, 300_000, "7z"), "n4")], date="2026-10-01T18:00:00")
    pg(a, "105", "Isla: Origins - Chapter 1 - Page 12", ["Page 12"], "n2", date="2026-10-04T18:00:00")
    pg(a, "106", "A Specter of Love - Part 2 - Page 34", ["Page 34"], "n4", date="2026-10-08T18:00:00")
    pg(a, "107", "The Portrait - Page 36", ["Page 36"], "n3", date="2026-10-12T18:00:00")
    pg(a, "108", "Chapter 26, Page 16", ["Page 16"], "n1", date="2026-10-20T18:00:00")
    pg(a, "109", "A Spectre of Love - Part 2 - Page 36", ["Page 36"], "n2", date="2026-10-25T18:00:00")
    pg(b, "201", "Moonlit Tales Part II - Chapter 3 - Page 7", ["Page 7"], "n1", date="2026-08-14T09:00:00")
    pg(b, "202", "Moonlit Tales Part II - Chapter 3 - Page 8", ["Page 8"], "n2", date="2026-08-21T09:00:00")
    pg(b, "203", "Barbara Halloween costume", ["Costume"], "n3", has_full=False, date="2026-10-30T09:00:00")
    pg(b, "204", "Sunset Diaries Vol. 2 - Page 5", ["Page 5"], "n4",
       extra=[FakeFile("turnaround.mp4", make_image(9, 500_000, "mp4"), "n1")], date="2026-11-01T09:00:00")
    pg(c, "301", "Kaerwyn: Issue 23 Page 78", ["Page 78"], "n2", date="2026-11-02T20:00:00")
    pg(c, "302", "Kaerwyn: Issue 23 Page 79", ["Page 79"], "n3", date="2026-11-05T20:00:00")
    return site


def main(out_dir: Path) -> None:
    app.setStyle("Fusion")
    set_language("en")
    apply_theme(app, "dark")
    app.setFont(QFont("Inter", 10))
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="pawchive-demo-"))
    settings = Settings(scan_on_startup=False).resolved(base)
    prepare_directories(settings)
    setup_logging(settings.logs_path, "INFO")
    db = Database(settings.database_path)
    migrate(db)
    site = demo_site()
    with respx.mock(assert_all_called=False) as router:
        site.install(router)
        http = HttpClient("https://pawchive.pw", "demo", request_delay=0.0, file_request_delay=0.0)
        engine = Engine(settings, db, http)
        for cid in ("41000001", "41000002", "41000003"):
            result = engine.add_author(f"https://pawchive.pw/patreon/user/{cid}")
            engine.scan_author(result.author.id, manual=True)
        # Make the queue page interesting: one interrupted, one unavailable, one pending.
        late = site.publish("41000003", FakePost("303", "Kaerwyn: Issue 23 Pages 80-81", [
            FakeFile("p80.png", artwork(80, "Page 80"), "n1"), FakeFile("p81.png", artwork(81, "Page 81"), "n4")],
            published="2026-11-08T12:00:00"))
        site.fail_file_once[late.files[0].sha] = 120_000
        site.file_status[late.files[1].sha] = 404
        engine.downloads.run_pending()
        engine.scan_author(engine.repos.authors.find("patreon", "41000003").id, manual=True)
        engine.downloads.run_pending()
        site.publish("41000002", FakePost("205", "Sunset Diaries Vol. 2 - Pages 6-7", [
            FakeFile("p6.png", artwork(6, "Page 6"), "n2"), FakeFile("p7.png", artwork(7, "Page 7"), "n3")],
            published="2026-11-08T13:00:00"))
        engine.scan_author(engine.repos.authors.find("patreon", "41000002").id, manual=True)
        # Simulated live progress for the dashboard and the queue.
        rows = [r for r in engine.repos.queue.all_with_files() if r["status"] == "waiting"]
        for r, frac in zip(rows, (0.62, 0.18)):
            engine.downloads._active[r["file_id"]] = r["host"]
            engine.downloads._progress[r["file_id"]] = (int(1_900_000 * frac), 1_900_000)
            engine.repos.queue.update(r["file_id"], status="active")
            meter = SpeedMeter(window=1e9)
            done = int(1_900_000 * frac)
            meter._samples.extend([(time.monotonic() - 4, done - 4 * 310_000), (time.monotonic(), done)])
            engine.downloads._meters[r["file_id"]] = meter

        window = MainWindow(engine, SettingsStore(base / "config"), lambda p: p)
        window.resize(1360, 860)
        window.show()
        shots = {"Dashboard": "01-dashboard", "Authors": "02-authors", "Works": "03-works", "Review": "04-review",
                 "Queue": "05-queue", "Settings": "06-settings", "Activity log": "07-log", "About": "08-about"}
        for title, name in shots.items():
            window.show_page(title)
            page = window.current_page()
            if title == "Works":
                tree = page.tree
                for t in range(tree.topLevelItemCount()):
                    top = tree.topLevelItem(t)
                    for i in range(top.childCount()):
                        if top.child(i).text(0).startswith("A Specter"):
                            tree.setCurrentItem(top.child(i))
                app.processEvents()
                page.files.selectRow(2)
            for _ in range(5):
                app.processEvents()
            if title != "Works":
                page.refresh()
            app.processEvents()
            window.grab().save(str(out_dir / f"{name}.png"))
            print("saved", name)
        window._quitting = True
        window.close()
        # The same application in Italian with the light theme.
        set_language("it")
        apply_theme(app, "light")
        window = MainWindow(engine, SettingsStore(base / "config"), lambda p: p)
        window.resize(1360, 860)
        window.show()
        for title, name in (("Dashboard", "09-dashboard-light-it"), ("Queue", "10-queue-light-it")):
            window.show_page(title)
            for _ in range(5):
                app.processEvents()
            window.current_page().refresh()
            app.processEvents()
            window.grab().save(str(out_dir / f"{name}.png"))
            print("saved", name)
        window._quitting = True
        window.close()
        engine.http.close()
    db.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots")

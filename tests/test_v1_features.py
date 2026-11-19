"""Speed limit and measurement, queue order, timed pause, translations, themes and notifications."""

from __future__ import annotations

import ast
import os
import string
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import FakeFile, FakePost, FakeSite, make_engine, make_image
from pawchive_downloader.config.settings import Settings
from pawchive_downloader.core.engine import Engine
from pawchive_downloader.core.events import EventType
from pawchive_downloader.downloads.throttle import BandwidthLimiter, SpeedMeter
from pawchive_downloader.storage.db import utcnow

CID = "82443765"
URL = f"https://pawchive.pw/patreon/user/{CID}"
SRC = Path(__file__).resolve().parents[1] / "src" / "pawchive_downloader"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.now += seconds


def setup_author(engine: Engine, site: FakeSite):
    site.add_creator(CID, "Exce")
    return engine.add_author(URL).author


def publish_pages(site: FakeSite, pages: list[int]) -> None:
    for n in pages:
        site.publish(CID, FakePost(str(n), f"The Portrait - Page {n}", [FakeFile(f"{n}.png", make_image(n))]))


# ------------------------------------------------------------------ throttle
def test_bandwidth_limiter_keeps_total_rate():
    clock = FakeClock()
    limiter = BandwidthLimiter(1000, clock=clock, sleep=clock.sleep)
    for _ in range(10):
        limiter.consume(500)  # 5000 bytes at 1000 B/s
    assert 4.0 <= clock.slept <= 5.5


def test_bandwidth_limiter_unlimited_and_live_change():
    clock = FakeClock()
    limiter = BandwidthLimiter(0, clock=clock, sleep=clock.sleep)
    limiter.consume(10_000_000)
    assert clock.slept == 0
    limiter.set_rate(2000)
    limiter.consume(4000)
    assert clock.slept == pytest.approx(2.0, abs=0.3)


def test_speed_meter_average_and_stall():
    clock = FakeClock()
    meter = SpeedMeter(window=4.0, clock=clock)
    for i in range(5):
        meter.add(i * 1000)
        clock.now += 1
    assert meter.speed() == pytest.approx(1000, rel=0.01)
    clock.now += 10
    assert meter.speed() == 0.0


def test_speed_limit_comes_from_settings(settings, router):
    settings.max_download_speed_kbps = 512
    engine = make_engine(settings)
    try:
        assert engine.downloads.limiter.rate == 512 * 1024
        engine.downloads.set_speed_limit(0)
        assert engine.downloads.limiter.rate == 0
    finally:
        engine.db.close()
        engine.http.close()


# --------------------------------------------------------------- queue order
def test_move_to_top_downloads_first(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    publish_pages(site, [1, 2, 3])
    engine.scan_author(author.id, manual=True)
    rows = engine.repos.queue.all_with_files()
    last = rows[-1]["file_id"]
    assert engine.move_to_top(last)
    assert engine.repos.queue.all_with_files()[0]["file_id"] == last
    engine.downloads.run_pending(1)
    assert engine.repos.files.get(last).status == "complete"


def test_move_to_bottom(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    publish_pages(site, [1, 2, 3])
    engine.scan_author(author.id, manual=True)
    first = engine.repos.queue.all_with_files()[0]["file_id"]
    assert engine.move_to_bottom(first)
    assert engine.repos.queue.all_with_files()[-1]["file_id"] == first


def test_move_to_top_releases_a_held_file(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    publish_pages(site, [1, 2])
    engine.scan_author(author.id, manual=True)
    held = engine.repos.queue.all_with_files()[1]["file_id"]
    engine.hold_file(held)
    engine.move_to_top(held)
    assert engine.repos.queue.get(held).status == "waiting"
    engine.downloads.run_pending(1)
    assert engine.repos.files.get(held).status == "complete"


# ---------------------------------------------------------------- timed pause
def test_timed_pause_resumes_by_itself(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    publish_pages(site, [1])
    engine.scan_author(author.id, manual=True)
    engine.downloads.set_paused(True, until=utcnow() + timedelta(hours=1))
    assert engine.downloads.run_pending() == 0
    assert not engine.downloads.check_pause_expired()
    engine.downloads._paused_until = utcnow() - timedelta(seconds=1)
    assert engine.downloads.run_pending() == 1  # the claim notices the expired pause
    assert not engine.downloads.paused and engine.downloads.paused_until is None


def test_timed_pause_survives_restart(settings, router):
    first = make_engine(settings)
    until = utcnow() + timedelta(hours=2)
    first.downloads.set_paused(True, until=until)
    first.db.close()
    first.http.close()
    second = make_engine(settings)
    try:
        assert second.downloads.paused
        assert abs((second.downloads.paused_until - until).total_seconds()) < 1
    finally:
        second.db.close()
        second.http.close()


def test_completed_event_marks_fresh_downloads(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    publish_pages(site, [7])
    events = []
    engine.events.subscribe(lambda e: events.append(e) if e.type is EventType.FILE_COMPLETED else None)
    engine.scan_author(author.id, manual=True)
    engine.downloads.run_pending()
    assert events and events[0].payload["fresh"] is True
    assert events[0].payload["work_title"] == "The Portrait" and events[0].payload["page"] == 7


# ------------------------------------------------------------------ settings
def test_interface_settings_are_validated():
    s = Settings(language="klingon", theme="neon", max_download_speed_kbps=-5).resolved(Path("/tmp/x"))
    assert (s.language, s.theme, s.max_download_speed_kbps) == ("system", "system", 0)
    data = Settings(language="it", theme="dark", minimize_to_tray=False).to_dict()
    back = Settings.from_dict(data)
    assert (back.language, back.theme, back.minimize_to_tray) == ("it", "dark", False)


# -------------------------------------------------------------- translations
def _source_strings() -> set[str]:
    found = set()
    for path in SRC.rglob("*.py"):
        if path.name.startswith("i18n"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def _fields(text: str) -> list[tuple[str, str]]:
    return sorted((name, spec) for _lit, name, spec, _conv in string.Formatter().parse(text) if name is not None)


def test_every_interface_text_has_an_italian_translation():
    from pawchive_downloader.i18n_it import IT
    from pawchive_downloader.legal import DISCLAIMER

    missing = sorted((_source_strings() | set(DISCLAIMER)) - set(IT))
    assert not missing, f"untranslated texts: {missing[:10]}"


def test_translations_keep_placeholders():
    from pawchive_downloader.i18n_it import IT

    bad = [k for k, v in IT.items() if _fields(k) != _fields(v)]
    assert not bad, bad[:5]


def test_language_switch():
    from pawchive_downloader import i18n

    try:
        i18n.set_language("it")
        assert i18n._("Pause downloads") == "Sospendi download"
        assert i18n._("{0} new file(s)", 3) == "3 nuovi file"
        assert i18n._("A text without translation") == "A text without translation"
        i18n.set_language("en")
        assert i18n._("Pause downloads") == "Pause downloads"
        assert i18n.resolve_language("system") in i18n.LANGUAGES
    finally:
        i18n.set_language("en")


# ---------------------------------------------------------------------- GUI
@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_light_and_dark_themes(qapp):
    from pawchive_downloader.ui import theme

    for mode in ("light", "dark"):
        assert theme.apply_theme(qapp, mode) == mode
        sheet = qapp.styleSheet()
        assert theme.PALETTES[mode]["bg"] in sheet and "{" in sheet and "{p[" not in sheet
        assert theme.status_color("failed") == theme.PALETTES[mode]["danger"]
    assert theme.effective_mode("system") in ("light", "dark")
    theme.apply_theme(qapp, "dark")


def test_window_in_italian_with_sections(qapp, engine, tmp_path):
    from pawchive_downloader import i18n
    from pawchive_downloader.config.settings import SettingsStore
    from pawchive_downloader.ui.main_window import MainWindow

    i18n.set_language("it")
    try:
        window = MainWindow(engine, SettingsStore(tmp_path / "cfg"), lambda p: p)
        titles = [window.nav.topLevelItem(i).text(0) for i in range(window.nav.topLevelItemCount())]
        assert titles == ["PANORAMICA", "LIBRERIA", "DOWNLOAD", "APPLICAZIONE"]
        window.show_page("Queue")
        assert window.current_page().title == "Queue"
        assert window.pause_toggle.text() == "Sospendi download"
        section = window.nav.topLevelItem(1)
        window._item_clicked(section)
        assert not section.isExpanded()
        window.show_page("Works")  # opening a page expands its section again
        assert section.isExpanded()
        window.show_page("About")
        window.current_page().refresh()
        window._quitting = True
        window.close()
    finally:
        i18n.set_language("en")


def test_tray_groups_new_pages_per_work(qapp, engine, tmp_path):
    from pawchive_downloader.config.settings import SettingsStore
    from pawchive_downloader.core.events import Event
    from pawchive_downloader.ui.main_window import MainWindow

    window = MainWindow(engine, SettingsStore(tmp_path / "cfg"), lambda p: p)
    tray = window.tray
    tray.available = True
    shown = []
    tray.tray.showMessage = lambda title, body, *args: shown.append((title, body))  # type: ignore[method-assign]
    for page in (35, 34):
        tray.on_event(Event(EventType.FILE_COMPLETED, {"fresh": True, "work_id": 1, "work_title": "A Specter of Love",
                                                       "page": page}))
    tray.on_event(Event(EventType.FILE_COMPLETED, {"fresh": False, "work_id": 2, "work_title": "Moved", "page": 1}))
    tray._flush()
    assert shown == [("A Specter of Love", "2 new files · pages 34, 35")]
    shown.clear()
    for work in (1, 2):
        tray.on_event(Event(EventType.FILE_COMPLETED, {"fresh": True, "work_id": work, "work_title": f"W{work}"}))
    tray._flush()
    assert shown[0][0] == "2 new files in 2 works"
    window._quitting = True
    window.close()


def test_pause_menu_offers_timed_pauses(qapp, engine):
    from PySide6.QtWidgets import QMenu

    from pawchive_downloader.ui.pause_controls import pause_state_text, populate_pause_menu

    menu = QMenu()
    populate_pause_menu(menu, engine, lambda: None, None)
    labels = [a.text() for a in menu.actions()]
    assert "Pause for 1 hour" in labels and "Pause until…" in labels
    next(a for a in menu.actions() if a.text() == "Pause for 1 hour").trigger()
    assert engine.downloads.paused and engine.downloads.paused_until is not None
    assert "resumes at" in pause_state_text(engine)
    populate_pause_menu(menu, engine, lambda: None, None)
    next(a for a in menu.actions() if a.text() == "Resume now").trigger()
    assert not engine.downloads.paused

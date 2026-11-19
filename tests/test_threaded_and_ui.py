"""The engine with real background threads, and a UI smoke test."""

from __future__ import annotations

import os
import time

import pytest

from conftest import FakeFile, FakePost, FakeSite, make_engine, make_image

CID = "82443765"


def _wait(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_background_threads_scan_and_download(settings, router, site: FakeSite):
    site.add_creator(CID, "Exce")
    for n in range(1, 6):
        site.publish(CID, FakePost(str(n), f"Night Shift - Page {n}", [FakeFile(f"{n}.png", make_image(n), f"n{n % 4 + 1}")]))
    engine = make_engine(settings)
    engine.start()
    try:
        engine.add_author(f"https://pawchive.pw/patreon/user/{CID}")
        assert _wait(lambda: len(engine.repos.files.by_status("complete")) == 5)
        files = sorted(p.name for p in (settings.archive_path / "Exce" / "Night Shift").iterdir())
        assert files == [f"Page {n}.png" for n in range(1, 6)]
    finally:
        engine.stop()
        engine.db.close()


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_pages_render(qapp, engine, site: FakeSite, tmp_path):
    from pawchive_downloader.config.settings import SettingsStore
    from pawchive_downloader.ui.main_window import MainWindow

    site.add_creator(CID, "Exce")
    site.publish(CID, FakePost("1", "Chapter 26, Page 16", [FakeFile("a.png", make_image(1))]))
    site.publish(CID, FakePost("2", "The Portrait - Page 36", [FakeFile("b.png", make_image(2))]))
    author = engine.add_author(f"https://pawchive.pw/patreon/user/{CID}").author
    engine.scan_author(author.id, manual=True)
    engine.downloads.run_pending()

    window = MainWindow(engine, SettingsStore(tmp_path / "cfg"), lambda p: p)
    window.show()
    for title in ("Dashboard", "Authors", "Works", "Review", "Queue", "Activity log", "Settings", "About"):
        window.show_page(title)
        qapp.processEvents()
        assert window.current_page().title == title
    assert window.pages[3].list.count() == 1  # one publication waiting for review
    window.close()


def test_review_page_filter_search_and_bulk(qapp, engine, site: FakeSite, tmp_path):
    from pawchive_downloader.config.settings import SettingsStore
    from pawchive_downloader.ui.main_window import MainWindow

    site.add_creator(CID, "Exce")
    site.add_creator("777", "Kestrel")
    for n in (1, 2, 3):
        site.publish(CID, FakePost(f"a{n}", f"Spectre - Chapter {n}, Page {n}", [FakeFile(f"{n}.png", make_image(n))]))
    site.publish(CID, FakePost("a9", "Chapter 9, Page 99", [FakeFile("9.png", make_image(9))]))
    site.publish("777", FakePost("b1", "Chapter 5, Page 2", [FakeFile("k.png", make_image(50))]))
    # Force review for the Spectre pages: an existing similar work.
    for cid in (CID, "777"):
        a = engine.add_author(f"https://pawchive.pw/patreon/user/{cid}").author
        engine.scan_author(a.id, manual=True)
    engine.downloads.run_pending()
    total = len(engine.repos.reviews.open_requests())
    assert total >= 2

    window = MainWindow(engine, SettingsStore(tmp_path / "cfg"), lambda p: p)
    window.show_page("Review")
    page = window.current_page()
    assert page.list.count() == total
    # filter by author
    page.author_filter.setCurrentIndex(page.author_filter.findText("Kestrel (1)"))
    assert page.list.count() == 1
    page.author_filter.setCurrentIndex(0)
    # search narrows the list
    page.search.setText("chapter 9")
    assert page.list.count() == 1
    page.search.setText("")
    # bulk: select all of one author and create one work
    page.author_filter.setCurrentIndex(page.author_filter.findText("Kestrel (1)"))
    page.list.selectAll()
    page.new_title.setText("Kestrel Comic - Chapter 5")
    page._create()
    assert len(engine.repos.reviews.open_requests()) == total - 1
    window.close()

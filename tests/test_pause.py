"""Pausing the whole queue and putting single files on hold."""

from __future__ import annotations

import threading
import time

import httpx

from conftest import FakeFile, FakePost, FakeSite, make_engine, make_image
from pawchive_downloader.core.engine import Engine

CID = "82443765"
URL = f"https://pawchive.pw/patreon/user/{CID}"


def setup_author(engine: Engine, site: FakeSite):
    site.add_creator(CID, "Exce")
    return engine.add_author(URL).author


def page(post_id: str, title: str, seed: int, node: str = "n1") -> FakePost:
    return FakePost(post_id, title, [FakeFile(f"img{seed}.png", make_image(seed, size=8192), node)])


def file_id_of(engine: Engine, author_id: int, post_id: str) -> int:
    return engine.repos.files.for_gallery(engine.repos.galleries.find(author_id, post_id).id)[0].id


def archive_files(engine: Engine) -> list[str]:
    root = engine.settings.archive_path
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


class _GatedStream(httpx.SyncByteStream):
    """Sends the first bytes, then waits for the test before sending the rest."""

    def __init__(self, data: bytes, cut: int, gate: threading.Event) -> None:
        self.data, self.cut, self.gate = data, cut, gate

    def __iter__(self):  # type: ignore[override]
        yield self.data[: self.cut]
        self.gate.wait(10)
        yield self.data[self.cut:]


def test_pause_all_stops_active_transfer_and_resumes_from_part(engine: Engine, site: FakeSite, router):
    author = setup_author(engine, site)
    post = site.publish(CID, page("1", "The Portrait - Page 36", 36, node="slow"))
    data = post.files[0].data
    gate = threading.Event()

    def slow(request: httpx.Request) -> httpx.Response:
        site.requests.append(request)
        if "Range" in request.headers:
            start = int(request.headers["Range"].split("=")[1].rstrip("-"))
            return httpx.Response(206, content=data[start:], headers={
                "Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}", "Content-Type": "image/png",
                "Content-Length": str(len(data) - start)})
        return httpx.Response(200, headers={"Content-Length": str(len(data)), "Content-Type": "image/png"},
                              stream=_GatedStream(data, 3000, gate))

    router.route(host="slow.pawchive.pw").mock(side_effect=slow)
    assert engine.scan_author(author.id, manual=True) == "ok"
    file_id = file_id_of(engine, author.id, "1")

    worker = threading.Thread(target=engine.downloads.run_pending)
    worker.start()
    deadline = time.monotonic() + 10
    while engine.downloads.progress().get(file_id, (0, 0))[0] < 3000 and time.monotonic() < deadline:
        time.sleep(0.01)
    engine.downloads.set_paused(True)
    gate.set()
    worker.join(10)

    item = engine.repos.queue.get(file_id)
    assert item.status == "waiting" and item.attempts == 0 and item.last_error is None
    assert engine.part_path(post.files[0].sha, "png").stat().st_size == 3000
    assert archive_files(engine) == []
    assert engine.downloads.run_pending() == 0  # nothing starts while paused

    engine.downloads.set_paused(False)
    engine.downloads.run_pending()
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]
    ranged = [r for r in site.requests if r.url.host == "slow.pawchive.pw" and "Range" in r.headers]
    assert ranged and ranged[-1].headers["Range"] == "bytes=3000-"


def test_pause_state_and_reason_survive_restart(settings, router, site: FakeSite):
    first = make_engine(settings)
    first.downloads.set_paused(True)
    assert first.downloads.pause_reason == "Paused by you"
    first.db.close()
    first.http.close()

    second = make_engine(settings)
    try:
        assert second.downloads.paused and second.downloads.pause_reason == "Paused by you"
        second.downloads.set_paused(False)
        assert second.downloads.pause_reason is None
    finally:
        second.db.close()
        second.http.close()


def test_hold_single_file_skips_it_until_released(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    site.publish(CID, page("2", "The Portrait - Page 37", 37))
    assert engine.scan_author(author.id, manual=True) == "ok"
    held = file_id_of(engine, author.id, "1")

    assert engine.hold_file(held)
    assert engine.downloads.run_pending() == 1
    assert archive_files(engine) == ["Exce/The Portrait/Page 37.png"]
    assert engine.repos.queue.get(held).status == "on_hold"
    assert engine.repos.queue.counts().get("on_hold") == 1

    assert engine.release_all_held() == 1
    engine.downloads.run_pending()
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png", "Exce/The Portrait/Page 37.png"]


def test_hold_active_file_stops_only_that_transfer(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    assert engine.scan_author(author.id, manual=True) == "ok"
    file_id = file_id_of(engine, author.id, "1")

    item = engine.downloads._claim()
    assert item is not None and item.file_id == file_id
    assert engine.hold_file(file_id)  # requested while the file is active
    engine.downloads.process(item)
    assert engine.repos.queue.get(file_id).status == "on_hold"
    assert not engine.downloads.paused
    assert engine.release_file(file_id)
    engine.downloads.run_pending()
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]


def test_queue_page_pause_controls(engine: Engine, site: FakeSite, tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pawchive_downloader.config.settings import SettingsStore
    from pawchive_downloader.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    author = setup_author(engine, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    engine.scan_author(author.id, manual=True)

    window = MainWindow(engine, SettingsStore(tmp_path / "cfg"), lambda p: p)
    window.show_page("Queue")
    queue = window.current_page()
    queue.refresh()
    assert window.pause_toggle.text() == "Pause downloads"
    window.pause_toggle.toggle()
    queue.refresh()
    assert engine.downloads.paused
    assert window.pause_toggle.text() == "Resume downloads"
    assert queue.pause_btn.text() == "Resume downloads"
    assert not queue.paused_banner.isHidden()

    queue.table.selectRow(0)
    assert queue.hold_btn.isEnabled() and not queue.release_btn.isEnabled()
    queue._hold()
    queue.table.selectRow(0)
    assert "paused by you" in queue.table.item(0, 3).text()
    assert queue.release_btn.isEnabled()
    window.pause_toggle.toggle()
    queue.refresh()
    assert queue.paused_banner.isHidden()
    window.close()

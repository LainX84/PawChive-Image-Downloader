"""Acceptance scenarios A-J from the specification (section 13).

They run the real engine against the simulated site of ``conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

from conftest import FakeFile, FakePost, FakeSite, make_engine, make_image
from pawchive_downloader.core.engine import Engine

CID = "82443765"
URL = f"https://pawchive.pw/patreon/user/{CID}"


def setup_author(engine: Engine, site: FakeSite, name: str = "Exce"):
    site.add_creator(CID, name)
    result = engine.add_author(URL)
    assert result.author is not None
    return result.author


def scan_and_download(engine: Engine, author_id: int) -> None:
    assert engine.scan_author(author_id, manual=True) == "ok"
    engine.downloads.run_pending()


def archive_files(engine: Engine) -> list[str]:
    root = engine.settings.archive_path
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def page(post_id: str, title: str, seed: int, ext: str = "png", node: str = "n1") -> FakePost:
    return FakePost(post_id, title, [FakeFile(f"img{seed}.{ext}", make_image(seed, kind="jpg" if ext == "jpg" else "png"), node)])


# --------------------------------------------------------------------- A
def test_scenario_a_existing_artwork(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "A Specter of Love - Part 2 - Page 35", 35))
    scan_and_download(engine, author.id)
    site.publish(CID, page("2", "A Specter of Love - Part 2 - Page 34", 34))
    scan_and_download(engine, author.id)
    assert archive_files(engine) == [
        "Exce/A Specter of Love - Part 2/Page 34.png",
        "Exce/A Specter of Love - Part 2/Page 35.png",
    ]
    assert len(engine.repos.works.for_author(author.id)) == 1


# --------------------------------------------------------------------- B
def test_scenario_b_multiple_artworks(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "A Specter of Love - Part 2 - Page 35", 35))
    site.publish(CID, page("2", "Isla: Origins - Chapter 1 - Page 12", 12, ext="jpg"))
    site.publish(CID, page("3", "The Portrait - Page 36", 36))
    scan_and_download(engine, author.id)
    assert archive_files(engine) == [
        "Exce/A Specter of Love - Part 2/Page 35.png",
        "Exce/Isla - Origins - Chapter 1/Page 12.jpg",
        "Exce/The Portrait/Page 36.png",
    ]


# --------------------------------------------------------------------- C
def test_scenario_c_out_of_order_and_same_page_never_overwritten(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("2", "A Specter of Love - Part 2 - Page 35", 35))
    scan_and_download(engine, author.id)
    site.publish(CID, page("1", "A Specter of Love - Part 2 - Page 34", 34))
    # A revised Page 35 (different bytes) must not overwrite the first one.
    site.publish(CID, page("3", "A Specter of Love - Part 2 - Page 35", 350))
    scan_and_download(engine, author.id)
    files = archive_files(engine)
    assert files == [
        "Exce/A Specter of Love - Part 2/Page 34.png",
        "Exce/A Specter of Love - Part 2/Page 35 (2).png",
        "Exce/A Specter of Love - Part 2/Page 35.png",
    ]
    pages = [f.page_number for f in engine.repos.files.for_work(engine.repos.works.for_author(author.id)[0].id)]
    assert pages == [34, 35, 35]  # ordered by page, not by download order


# --------------------------------------------------------------------- D
def test_scenario_d_empty_gallery(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, FakePost("10", "Development Update"))
    scan_and_download(engine, author.id)
    gallery = engine.repos.galleries.find(author.id, "10")
    assert gallery is not None and gallery.status == "empty"
    assert gallery.next_recheck_at is not None  # configurable recheck
    assert site.file_requests() == []
    assert engine.repos.works.for_author(author.id) == []
    assert not any(engine.settings.archive_path.rglob("*"))  # no empty directories
    # Re-scanning does not reprocess it; a later recheck picks up new attachments.
    assert engine.scan_author(author.id, full=True, manual=True) == "ok"
    site.posts[CID][0].files.append(FakeFile("late.png", make_image(99)))
    site.files[site.posts[CID][0].files[0].sha] = site.posts[CID][0].files[0].data
    engine.recheck_gallery(engine.repos.galleries.find(author.id, "10"))
    engine.downloads.run_pending()
    assert len(archive_files(engine)) == 1


def test_previews_only_gallery_is_not_downloaded(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, FakePost("11", "Barbara Halloween costume", [FakeFile("b.png", make_image(5))], has_full=False))
    scan_and_download(engine, author.id)
    gallery = engine.repos.galleries.find(author.id, "11")
    assert gallery.status == "awaiting_full"
    assert site.file_requests() == [] and archive_files(engine) == []
    # The site imports the originals later: the recheck downloads them.
    site.posts[CID][0].has_full = True
    engine.recheck_gallery(gallery)
    engine.downloads.run_pending()
    assert archive_files(engine) == ["Exce/Barbara Halloween costume/2026-01-01 - b.png"]


# --------------------------------------------------------------------- E
def test_scenario_e_single_page_joins_existing_work(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, FakePost("1", "Isla: Origins - Chapter 1 - Pages 10-11",
                               [FakeFile("a.png", make_image(10)), FakeFile("b.png", make_image(11))]))
    scan_and_download(engine, author.id)
    site.publish(CID, page("2", "isla origins - chapter 1 - page 12", 12))
    scan_and_download(engine, author.id)
    assert archive_files(engine) == [
        "Exce/Isla - Origins - Chapter 1/Page 10.png",
        "Exce/Isla - Origins - Chapter 1/Page 11.png",
        "Exce/Isla - Origins - Chapter 1/Page 12.png",
    ]


# --------------------------------------------------------------------- F
def test_scenario_f_interrupted_download_resumes(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    post = site.publish(CID, page("1", "The Portrait - Page 36", 36))
    sha = post.files[0].sha
    site.fail_file_once[sha] = 1500  # connection drops after 1500 bytes
    assert engine.scan_author(author.id, manual=True) == "ok"
    engine.downloads.run_pending()
    part = engine.part_path(sha, "png")
    assert part.exists() and part.stat().st_size == 1500
    item = engine.repos.queue.get(engine.repos.files.for_gallery(engine.repos.galleries.find(author.id, "1").id)[0].id)
    assert item.status == "backoff" and item.attempts == 1
    engine.retry_file(item.file_id)
    engine.downloads.run_pending()
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]
    range_requests = [r for r in site.file_requests() if "Range" in r.headers]
    assert range_requests and range_requests[-1].headers["Range"] == "bytes=1500-"
    assert not part.exists()


def test_server_without_range_support_restarts_cleanly(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    post = site.publish(CID, page("1", "The Portrait - Page 36", 36))
    site.fail_file_once[post.files[0].sha] = 1000
    site.support_ranges = False
    engine.scan_author(author.id, manual=True)
    engine.downloads.run_pending()
    engine.retry_all_failed()
    engine.downloads.run_pending()
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]


# --------------------------------------------------------------------- G
def test_scenario_g_restart_restores_queue(settings, router, site: FakeSite):
    first = make_engine(settings)
    author = setup_author(first, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    site.publish(CID, page("2", "The Portrait - Page 37", 37))
    assert first.scan_author(author.id, manual=True) == "ok"
    # Simulate a crash in the middle of a download.
    item = first.downloads._claim()
    assert item is not None
    first.db.close()
    first.http.close()

    second = make_engine(settings)
    assert second.repos.queue.get(item.file_id).status == "waiting"
    assert second.repos.authors.get(author.id).last_success_at is not None
    second.downloads.run_pending()
    assert archive_files(second) == ["Exce/The Portrait/Page 36.png", "Exce/The Portrait/Page 37.png"]
    second.db.close()
    second.http.close()


# --------------------------------------------------------------------- H
def test_scenario_h_no_duplicate_downloads(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    post = site.publish(CID, page("1", "The Portrait - Page 36", 36))
    scan_and_download(engine, author.id)
    requests_after_first = len(site.file_requests())
    scan_and_download(engine, author.id)                       # incremental
    assert engine.scan_author(author.id, full=True, manual=True) == "ok"  # full rescan
    engine.downloads.run_pending()
    assert len(site.file_requests()) == requests_after_first
    # The same file re-posted in another gallery is recognized by hash.
    site.publish(CID, FakePost("2", "The Portrait - Page 36 (repost)", [post.files[0]]))
    scan_and_download(engine, author.id)
    assert len(site.file_requests()) == requests_after_first
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]


# --------------------------------------------------------------------- I
def test_scenario_i_original_retrieved_and_verified(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    original = make_image(1, size=50_000)
    post = site.publish(CID, FakePost("1", "The Portrait - Page 36", [FakeFile("full.png", original, "n3")]))
    scan_and_download(engine, author.id)
    saved = engine.settings.archive_path / "Exce/The Portrait/Page 36.png"
    assert saved.read_bytes() == original
    urls = [str(r.url) for r in site.file_requests()]
    assert urls == [f"https://n3.pawchive.pw/data{post.files[0].path}?f=full.png"]
    assert not any("thumbnail" in u for u in urls)


def test_corrupted_or_preview_bytes_are_rejected(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    post = site.publish(CID, page("1", "The Portrait - Page 36", 36))
    sha = post.files[0].sha
    site.files[sha] = make_image(0, 100, "webp")  # server sends a small preview instead
    scan_and_download(engine, author.id)
    assert archive_files(engine) == []
    record = engine.repos.files.for_gallery(engine.repos.galleries.find(author.id, "1").id)[0]
    assert record.status == "queued"
    assert engine.repos.queue.get(record.id).error_class == "integrity"
    assert not engine.part_path(sha, "png").exists()


# --------------------------------------------------------------------- J
def test_scenario_j_authentication_required(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    post = site.publish(CID, page("1", "The Portrait - Page 36", 36))
    site.file_status[post.files[0].sha] = 401
    events = []
    engine.events.subscribe(events.append)
    scan_and_download(engine, author.id)
    engine.downloads.run_pending()
    file_requests = len(site.file_requests())
    assert file_requests == 1  # not retried in a loop
    record = engine.repos.files.for_gallery(engine.repos.galleries.find(author.id, "1").id)[0]
    assert engine.repos.queue.get(record.id).status == "paused"
    assert any(e.type.value == "auth.problem" for e in events)

    site.api_status = 401
    assert engine.scan_author(author.id, manual=True) == "auth"
    assert "authentication" in engine.repos.authors.get(author.id).status_message.lower()


# ----------------------------------------------------------- more behaviour
def test_rate_limit_pauses_host_and_blocks_are_reported(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.api_status, site.api_headers = 429, {"Retry-After": "600"}
    assert engine.scan_author(author.id, manual=True) == "blocked"
    assert "pawchive.pw" in engine.http.paused_hosts()
    assert engine.repos.authors.get(author.id).status == "blocked"
    calls = len(site.requests)
    assert engine.scan_author(author.id, manual=True) == "blocked"
    assert len(site.requests) == calls  # paused host: no new request at all


def test_extras_are_archived_with_the_work(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, FakePost("1", "A Specter of Love - Part 2 - Page 35", [
        FakeFile("p35.png", make_image(35)), FakeFile("Part2_full.7z", make_image(1, kind="7z"), "n2"),
        FakeFile("anim.mp4", make_image(2, kind="mp4"), "n4"),
    ]))
    scan_and_download(engine, author.id)
    assert archive_files(engine) == [
        "Exce/A Specter of Love - Part 2/Page 35.png",
        "Exce/A Specter of Love - Part 2/Part2_full.7z",
        "Exce/A Specter of Love - Part 2/anim.mp4",
    ]


def test_low_confidence_waits_for_review_then_is_remembered(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "Chapter 26, Page 16", 16))
    scan_and_download(engine, author.id)
    assert archive_files(engine) == []  # held in Temp, no folder created
    review = engine.repos.reviews.open_requests()[0]
    held = engine.repos.files.by_status("held")
    assert len(held) == 1 and Path(held[0].held_path).exists()
    work = engine.resolve_review(review.id, new_title="Lift - Chapter 26")
    assert archive_files(engine) == ["Exce/Lift - Chapter 26/Page 16.png"]
    # Next page with the same ambiguous title goes straight to the confirmed work.
    site.publish(CID, page("2", "Chapter 26, Page 17", 17))
    scan_and_download(engine, author.id)
    assert engine.repos.reviews.open_requests() == []
    assert "Exce/Lift - Chapter 26/Page 17.png" in archive_files(engine)
    assert work.user_confirmed


def test_similar_title_review_assign_to_existing(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "A Specter of Love - Part 2 - Page 35", 35))
    scan_and_download(engine, author.id)
    site.publish(CID, page("2", "A Spectre of Love - Part 2 - Page 36", 36))
    site.publish(CID, page("3", "A Spectre of Love - Part 2 - Page 37", 37))
    scan_and_download(engine, author.id)
    reviews = engine.repos.reviews.open_requests()
    assert len(reviews) == 2
    target = engine.repos.works.for_author(author.id)[0]
    engine.resolve_review(reviews[0].id, work_id=target.id)
    assert engine.repos.reviews.open_requests() == []  # same key resolved together
    assert archive_files(engine) == [f"Exce/A Specter of Love - Part 2/Page {n}.png" for n in (35, 36, 37)]


def test_rename_merge_and_reassign(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "The Portrait - Page 1", 1))
    site.publish(CID, page("2", "Portrait Studies - Page 1", 2))
    scan_and_download(engine, author.id)
    works = {w.display_title: w for w in engine.repos.works.for_author(author.id)}
    renamed = engine.rename_work(works["The Portrait"].id, "The Portrait (Final)")
    assert "Exce/The Portrait (Final)/Page 1.png" in archive_files(engine)
    merged = engine.merge_works(works["Portrait Studies"].id, renamed.id)
    assert archive_files(engine) == ["Exce/The Portrait (Final)/Page 1 (2).png", "Exce/The Portrait (Final)/Page 1.png"]
    assert len(engine.repos.works.for_author(author.id)) == 1
    gallery = engine.repos.galleries.find(author.id, "2")
    engine.reassign_gallery(gallery.id, new_title="Portrait Studies")
    assert "Exce/Portrait Studies/Page 1.png" in archive_files(engine)  # clean name restored
    assert merged.id == renamed.id


def test_add_author_from_post_url_needs_confirmation(engine: Engine, site: FakeSite):
    site.add_creator(CID, "Exce")
    result = engine.add_author(f"{URL}/post/123")
    assert result.needs_confirmation and result.author is None
    result = engine.add_author(f"{URL}/post/123", confirmed=True)
    assert result.author is not None
    again = engine.add_author(URL)
    assert again.already_monitored


def test_remove_author_keeps_archive(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    scan_and_download(engine, author.id)
    engine.remove_author(author.id)
    assert engine.repos.authors.all() == []
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]


def test_pagination_incremental_scan_stops_early(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    for i in range(120):
        site.publish(CID, FakePost(str(i), f"Text post {i}"))
    assert engine.scan_author(author.id, manual=True) == "ok"
    assert len(engine.repos.galleries.for_author(author.id)) == 120
    site.publish(CID, page("new", "The Portrait - Page 1", 1))
    before = len(site.requests)
    assert engine.scan_author(author.id, manual=True) == "ok"
    api_calls = [r for r in site.requests[before:] if "/posts" in r.url.path]
    assert len(api_calls) == 1  # only the first page was needed


def test_initial_scan_processes_oldest_first_so_typos_do_not_win(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    for n in (32, 33, 34):
        site.publish(CID, FakePost(str(n), f"A Specter of Love - Part 2 - Page {n}",
                                   [FakeFile(f"{n}.png", make_image(n))], published=f"2026-01-{n - 20:02d}T10:00:00"))
    site.publish(CID, FakePost("99", "A Spectre of Love - Part 2 - Page 35", [FakeFile("35.png", make_image(35))],
                               published="2026-02-01T10:00:00"))
    scan_and_download(engine, author.id)
    works = engine.repos.works.for_author(author.id)
    assert [w.display_title for w in works] == ["A Specter of Love - Part 2"]
    reviews = engine.repos.reviews.open_requests()
    assert len(reviews) == 1 and "Spectre" in engine.repos.galleries.get(reviews[0].gallery_id).title


def test_bulk_review_resolution_and_disk_usage(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    for n in (16, 17, 18):
        site.publish(CID, page(str(n), f"Chapter 26, Page {n}", n))
    site.publish(CID, page("50", "Regarding this page...", 50))
    scan_and_download(engine, author.id)
    reviews = engine.repos.reviews.open_requests()
    assert len(reviews) == 4  # one request per publication
    chapter = [r.id for r in reviews if r.proposed_key == "|chapter:26"]
    other = [r.id for r in reviews if r.proposed_key != "|chapter:26"]
    assert len(chapter) == 3
    work, count = engine.resolve_reviews(chapter, new_title="Lift - Chapter 26")
    assert work is not None and count == 3
    assert [f for f in archive_files(engine) if "Lift" in f] == [
        f"Exce/Lift - Chapter 26/Page {n}.png" for n in (16, 17, 18)]
    engine.dismiss_reviews(other)
    assert engine.repos.reviews.open_requests() == []
    size, files = engine.author_disk_usage(engine.repos.authors.get(author.id))
    expected = sum(p.stat().st_size for p in (engine.settings.archive_path / "Exce").rglob("*") if p.is_file())
    assert (size, files) == (expected, 3)


def test_bulk_review_refuses_mixed_authors(engine: Engine, site: FakeSite):
    from pawchive_downloader.core.engine import EngineError
    import pytest

    first = setup_author(engine, site)
    site.add_creator("777", "Other")
    second = engine.add_author("https://pawchive.pw/patreon/user/777").author
    site.publish(CID, page("1", "Chapter 1, Page 1", 1))
    site.publish("777", page("2", "Chapter 2, Page 1", 2))
    scan_and_download(engine, first.id)
    scan_and_download(engine, second.id)
    ids = [r.id for r in engine.repos.reviews.open_requests()]
    with pytest.raises(EngineError):
        engine.resolve_reviews(ids, new_title="Mixed")


def test_new_sketches_get_their_own_folder(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "A Specter of Love - Part 2 - Page 35", 35))
    site.publish(CID, page("2", "A Specter of Love - Part 2 - Page 35 (Sketch)", 135))
    site.publish(CID, page("3", "A Specter of Love - Part 2 - Page 36 WIP", 136))
    scan_and_download(engine, author.id)
    assert archive_files(engine) == [
        "Exce/A Specter of Love - Part 2 - Sketches/Page 35.png",
        "Exce/A Specter of Love - Part 2 - Sketches/Page 36.png",
        "Exce/A Specter of Love - Part 2/Page 35.png",
    ]
    assert engine.repos.reviews.open_requests() == []


def test_repair_archive_with_sketches_mixed_in(engine: Engine, site: FakeSite):
    """Archives made by earlier versions: sketches filed with the finished pages."""
    author = setup_author(engine, site)
    site.publish(CID, page("1", "A Specter of Love - Part 2 - Page 34", 34))
    site.publish(CID, page("2", "A Specter of Love - Part 2 - Page 35", 35))
    site.publish(CID, page("3", "A Specter of Love - Part 2 - Page 35 Sketch", 135))
    site.publish(CID, page("4", "A Specter of Love - Part 2 - Page 36 lineart", 136))
    scan_and_download(engine, author.id)
    main = engine.repos.works.by_key(author.id, "a specter of love|part:2")
    # Recreate the old, wrong state: move the sketches into the finished work.
    sketch_ids = [engine.repos.galleries.find(author.id, pid).id for pid in ("3", "4")]
    engine.reassign_galleries(sketch_ids, main.id)
    assert len([f for f in archive_files(engine) if "/A Specter of Love - Part 2/" in f]) == 4

    mixes = engine.find_variant_mixes()
    assert [(w.id, sorted(g.id for g in gs)) for w, gs in mixes] == [(main.id, sorted(sketch_ids))]
    engine.split_sketches(main.id, sketch_ids)
    assert archive_files(engine) == [
        "Exce/A Specter of Love - Part 2 - Sketches/Page 35.png",
        "Exce/A Specter of Love - Part 2 - Sketches/Page 36.png",
        "Exce/A Specter of Love - Part 2/Page 34.png",
        "Exce/A Specter of Love - Part 2/Page 35.png",
    ]
    assert engine.find_variant_mixes() == []
    # Future sketch pages go straight to the Sketches work.
    site.publish(CID, page("5", "A Specter of Love - Part 2 - Page 37 Sketch", 137))
    scan_and_download(engine, author.id)
    assert "Exce/A Specter of Love - Part 2 - Sketches/Page 37.png" in archive_files(engine)


def test_reassign_to_same_work_is_a_no_op(engine: Engine, site: FakeSite):
    author = setup_author(engine, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    scan_and_download(engine, author.id)
    gallery = engine.repos.galleries.find(author.id, "1")
    engine.reassign_gallery(gallery.id, gallery.work_id)
    assert archive_files(engine) == ["Exce/The Portrait/Page 36.png"]


def test_moving_data_folders_keeps_everything(settings, router, site: FakeSite, tmp_path):
    """The user's case: data created in ...\\download\\PawChiveDownloader, wanted in ...\\download."""
    from dataclasses import replace

    from pawchive_downloader.config.paths import prepare_directories
    from pawchive_downloader.config.relocate import FOLDER_SETTINGS, plan_relocation, relocate

    first = make_engine(settings)
    author = setup_author(first, site)
    site.publish(CID, page("1", "The Portrait - Page 36", 36))
    site.publish(CID, page("2", "Chapter 26, Page 16", 16))          # held for review
    late = site.publish(CID, page("3", "The Portrait - Page 37", 37))
    site.fail_file_once[late.files[0].sha] = 1000                     # partial .part
    first.scan_author(author.id, manual=True)
    first.downloads.run_pending()
    first.db.close()
    first.http.close()

    old_base = Path(settings.archive_dir).parent
    new_base = old_base.parent / "download"
    moved = replace(settings, archive_dir=str(new_base / "Archive"), temp_dir=str(new_base / "Temp"),
                    database_dir=str(new_base / "Database"), logs_dir=str(new_base / "Logs"))
    pairs = plan_relocation({k: getattr(settings, k) for k in FOLDER_SETTINGS},
                            {k: getattr(moved, k) for k in FOLDER_SETTINGS})
    assert len(pairs) >= 3
    prepare_directories(moved)              # empty destination folders already exist
    report = relocate(pairs)
    assert report.ok and not old_base.exists()

    second = make_engine(moved)
    assert len(second.repos.authors.all()) == 1
    held = second.repos.files.by_status("held")
    assert held and Path(held[0].held_path).exists() and str(new_base) in held[0].held_path
    review = second.repos.reviews.open_requests()[0]
    second.resolve_review(review.id, new_title="Lift - Chapter 26")
    second.retry_all_failed()
    second.downloads.run_pending()
    files = sorted(p.relative_to(moved.archive_path).as_posix() for p in moved.archive_path.rglob("*") if p.is_file())
    assert files == ["Exce/Lift - Chapter 26/Page 16.png", "Exce/The Portrait/Page 36.png", "Exce/The Portrait/Page 37.png"]
    resumed = [r for r in site.file_requests() if r.headers.get("Range") == "bytes=1000-"]
    assert resumed, "the partial download resumed from the moved Temp folder"
    second.db.close()
    second.http.close()


def _anya_like_site(site: FakeSite) -> None:
    """A small copy of the real AnyaArt history (titles from the user's archive)."""
    posts = [
        ("1", "A Spector of Love - Page 1", "2024-01-28", [1]),
        ("2", "A Spector of Love - Page 2", "2024-01-29", [2]),
        ("3", "Sketches - A Spector of Love - Pages 3 & 4", "2024-02-02", [103, 104]),
        ("4", "A Spector of Love - Page 3", "2024-02-03", [3]),
        ("5", "Page 4 Sketch", "2024-02-04", [204]),              # no series name
        ("6", "A Specter of Love - Page 4", "2024-02-06", [4]),
        ("7", "A Specter of Love Page 5 Sketch", "2024-02-07", [105]),
        ("8", "A Specter of Love - Page 5", "2024-02-08", [5]),
        ("9", "A Specter of Love - Part 2 - Page 1", "2026-05-22", [21]),
        ("10", "A Specter of Love Pages 1 - 5", "2026-06-06", [1, 2, 3, 4, 5]),   # compilation (same files)
        ("11", "A Specter of Love Part 2 Pages 1 & 2 Sketches", "2026-06-07", [121, 122]),
        ("12", "A Specter of Love - Part 2 - Page 2", "2026-06-08", [22]),
    ]
    for pid, title, date, seeds in posts:
        site.publish(CID, FakePost(pid, title, [FakeFile(f"f{s}.png", make_image(s)) for s in seeds],
                                   published=f"{date}T10:00:00"))


def test_rebuild_fixes_a_broken_archive(engine: Engine, site: FakeSite):
    author = setup_author(engine, site, name="AnyaArt")
    _anya_like_site(site)
    scan_and_download(engine, author.id)
    # Reproduce the user's broken state: wrong remembered associations put
    # both seasons into a work called "... - Sketches".
    wrong = engine._create_work(author, parse_title_for_test("A Specter of Love - Sketches"), 1.0, True,
                                title_override="A Specter of Love - Sketches")
    for g in engine.repos.galleries.for_author(author.id):
        if g.work_id is not None and "Spector" not in g.title:
            engine.reassign_gallery(g.id, wrong.id)
    assert any("Sketches" in f for f in archive_files(engine))

    preview = engine.preview_rebuild(author.id)
    similar = {(e["key"], e["other_key"]) for e in preview["similar"]}
    assert ("a specter of love", "a spector of love") in similar
    stats = engine.rebuild_author(author.id, series_map={"a spector of love": "A Specter of Love",
                                                          "a specter of love": "A Specter of Love"})
    files = archive_files(engine)
    season1 = [f for f in files if f.startswith("AnyaArt/A Specter of Love/")]
    assert season1 == [f"AnyaArt/A Specter of Love/Page {n}.png" for n in range(1, 6)]
    assert sorted(f for f in files if "/A Specter of Love - Part 2/" in f) == [
        "AnyaArt/A Specter of Love - Part 2/Page 1.png", "AnyaArt/A Specter of Love - Part 2/Page 2.png"]
    sketches = sorted(f.rsplit("/", 1)[-1] for f in files if f.startswith("AnyaArt/A Specter of Love - Sketches/"))
    assert sketches == ["Page 3.png", "Page 4 (2).png", "Page 4.png", "Page 5.png"]  # incl. "Page 4 Sketch" via context
    assert sorted(f for f in files if "Part 2 - Sketches" in f) == [
        "AnyaArt/A Specter of Love - Part 2 - Sketches/Page 1.png", "AnyaArt/A Specter of Love - Part 2 - Sketches/Page 2.png"]
    assert stats["review"] == 0 and engine.repos.reviews.open_requests() == []
    assert len(files) == len(set(files)) == 13
    # No file was lost: every completed file exists on disk.
    for record in engine.repos.files.by_status("complete"):
        assert engine.absolute(record.local_path).exists()
    # The confirmed spelling is remembered for future publications.
    site.publish(CID, FakePost("13", "A Spector of Love - Page 6", [FakeFile("f6.png", make_image(6))],
                               published="2026-07-01T10:00:00"))
    scan_and_download(engine, author.id)
    assert "AnyaArt/A Specter of Love/Page 6.png" in archive_files(engine)


def parse_title_for_test(title: str):
    from pawchive_downloader.recognition.title_parser import parse_title

    return parse_title(title)

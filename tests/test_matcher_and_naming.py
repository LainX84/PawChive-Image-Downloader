"""Work matching and archive naming."""

from __future__ import annotations

from datetime import datetime, timezone

from pawchive_downloader.archive.naming import FileInfo, plan_file_names, safe_component, safe_file_name
from pawchive_downloader.recognition.matcher import MatchAction, WorkRef, match_work
from pawchive_downloader.recognition.title_parser import parse_title


def works(*items: tuple[int, str]) -> list[WorkRef]:
    return [WorkRef(i, parse_title(t).work_key(), parse_title(t).display_title()) for i, t in items]


def test_exact_key_matches_existing_work():
    decision = match_work(parse_title("A Specter of Love - Part 2 - Page 34"), works((1, "A Specter of Love - Part 2")), {})
    assert decision.action is MatchAction.EXISTING and decision.work_id == 1


def test_new_confident_title_creates_work():
    decision = match_work(parse_title("The Portrait - Page 36"), works((1, "A Specter of Love - Part 2")), {})
    assert decision.action is MatchAction.CREATE


def test_different_part_of_same_series_is_a_new_work():
    decision = match_work(parse_title("A Specter of Love - Part 3 - Page 1"), works((1, "A Specter of Love - Part 2")), {})
    assert decision.action is MatchAction.CREATE


def test_similar_title_is_never_merged_automatically():
    decision = match_work(parse_title("A Spectre of Love - Part 2 - Page 36"), works((1, "A Specter of Love - Part 2")), {})
    assert decision.action is MatchAction.REVIEW
    assert decision.candidates and decision.candidates[0].work_id == 1


def test_missing_marker_of_existing_series_goes_to_review():
    decision = match_work(parse_title("A Specter of Love - Page 36"), works((1, "A Specter of Love - Part 2")), {})
    assert decision.action is MatchAction.REVIEW


def test_alias_remembers_user_decision():
    parsed = parse_title("Chapter 26, Page 17")
    first = match_work(parsed, works((7, "Lift - Chapter 26")), {})
    assert first.action is MatchAction.REVIEW
    second = match_work(parsed, works((7, "Lift - Chapter 26")), {parsed.work_key(): 7})
    assert second.action is MatchAction.EXISTING and second.work_id == 7


def test_low_confidence_goes_to_review():
    decision = match_work(parse_title("[LIFT Update] Chapter 5, Page 2"), [], {})
    assert decision.action is MatchAction.REVIEW


def test_safe_component_matches_spec_folder_names():
    assert safe_component("Isla: Origins - Chapter 1") == "Isla - Origins - Chapter 1"
    assert safe_component("A Specter of Love - Part 2") == "A Specter of Love - Part 2"
    assert safe_component('bad<>"/\\|?*name. ') == "bad name"
    assert safe_component("CON") == "CON_"
    assert safe_component("") == "Untitled"


def test_safe_file_name():
    assert safe_file_name("Page 35", "PNG") == "Page 35.png"


PUBLISHED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_single_image_named_by_page():
    plan = plan_file_names([FileInfo(0, "x.png", "png", "image")], 35, None, PUBLISHED)
    assert [p.file_name for p in plan] == ["Page 35.png"]


def test_page_range_assigns_consecutive_pages():
    files = [FileInfo(i, f"{i}.jpg", "jpg", "image") for i in range(3)]
    plan = plan_file_names(files, 10, 12, PUBLISHED)
    assert [(p.page_number, p.file_name) for p in plan] == [(10, "Page 10.jpg"), (11, "Page 11.jpg"), (12, "Page 12.jpg")]


def test_several_images_one_page_get_counters():
    files = [FileInfo(i, f"{i}.png", "png", "image") for i in range(2)]
    assert [p.file_name for p in plan_file_names(files, 35, None, PUBLISHED)] == ["Page 35 (1).png", "Page 35 (2).png"]


def test_no_page_uses_date_and_original_name_and_extras_keep_names():
    files = [FileInfo(0, "Bunny.png", "png", "image"), FileInfo(1, "SpookyBarbara.7z", "7z", "archive"),
             FileInfo(2, "clip.mp4", "mp4", "video")]
    names = [p.file_name for p in plan_file_names(files, None, None, PUBLISHED)]
    assert names == ["2026-01-02 - Bunny.png", "SpookyBarbara.7z", "clip.mp4"]


def test_no_page_several_images_follow_website_order():
    # Real case (Nanorumi, "NTR Experience - PART 3"): the main file -98 is shown
    # first on the website, followed by -71 ... -94.
    names_on_site = ["Red Femboy-98.jpg"] + [f"Red Femboy-{n}.jpg" for n in range(71, 95)]
    files = [FileInfo(i, name, "jpg", "image") for i, name in enumerate(names_on_site)]
    names = [p.file_name for p in plan_file_names(files, None, None, PUBLISHED)]
    assert names[0] == "2026-01-02 - 01 - Red Femboy-98.jpg"
    assert names[1] == "2026-01-02 - 02 - Red Femboy-71.jpg"
    assert names[-1] == "2026-01-02 - 25 - Red Femboy-94.jpg"
    assert sorted(names) == names  # name order == website order


def test_names_unique_within_post():
    files = [FileInfo(0, "a.png", "png", "image"), FileInfo(1, "a.png", "png", "image")]
    names = [p.file_name for p in plan_file_names(files, None, None, None)]
    assert len(set(names)) == 2


def test_sketches_never_join_finished_work():
    decision = match_work(parse_title("A Specter of Love - Part 2 - Page 35 Sketch"),
                          works((1, "A Specter of Love - Part 2")), {})
    assert decision.action is MatchAction.CREATE
    assert decision.display_title == "A Specter of Love - Part 2 - Sketches"
    again = match_work(parse_title("A Specter of Love - Part 2 - Page 36 WIP"),
                       works((1, "A Specter of Love - Part 2"), (2, "A Specter of Love - Part 2 - Page 1 sketch")), {})
    assert again.action is MatchAction.EXISTING and again.work_id == 2


def test_compilation_pages_follow_file_name_numbers_not_api_order():
    # Real case: "A Specter of Love Part 2 Pages 1 - 12" arrived shuffled from the API.
    shuffled = [280, 283, 286, 288, 277, 282, 285, 279, 278, 281, 284, 287]
    files = [FileInfo(i, f"A-Spector-of-Love---{n}.jpg", "jpg", "image") for i, n in enumerate(shuffled)]
    plan = {p.position: p for p in plan_file_names(files, 1, 12, PUBLISHED)}
    for info, n in zip(files, shuffled):
        assert plan[info.position].file_name == f"Page {n - 276}.jpg"


def test_names_without_numbers_keep_post_order():
    files = [FileInfo(0, "b.png", "png", "image"), FileInfo(1, "a.png", "png", "image")]
    assert [p.file_name for p in plan_file_names(files, 1, 2, PUBLISHED)] == ["Page 1.png", "Page 2.png"]

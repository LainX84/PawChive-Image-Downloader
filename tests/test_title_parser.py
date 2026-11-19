"""Title recognition, including real titles observed on PawChive."""

from __future__ import annotations

import pytest

from pawchive_downloader.recognition.normalize import clean_text, normalize_key
from pawchive_downloader.recognition.title_parser import parse_title


def test_spec_example_part():
    p = parse_title("A Specter of Love - Part 2 - Page 35")
    assert (p.series, p.part, p.page) == ("A Specter of Love", 2, 35)
    assert p.display_title() == "A Specter of Love - Part 2"
    assert p.work_key() == "a specter of love|part:2"
    assert p.confidence == 1.0


def test_spec_example_chapter_with_colon():
    p = parse_title("Isla: Origins - Chapter 1 - Page 12")
    assert (p.series, p.chapter, p.page) == ("Isla: Origins", 1, 12)
    assert p.display_title() == "Isla: Origins - Chapter 1"


def test_spec_example_standalone_page():
    p = parse_title("The Portrait - Page 36")
    assert (p.series, p.page, p.groups) == ("The Portrait", 36, {})


@pytest.mark.parametrize(
    "title, series, groups, page",
    [
        ("A big appetite part 2 (page 2)", "A big appetite", {"part": 2}, 2),
        ("Super Rivals #11 page 27", "Super Rivals", {"issue": 11}, 27),
        ("Louds in the club part 4 page 41", "Louds in the club", {"part": 4}, 41),
        ("Charisma Check | Page 72", "Charisma Check", {}, 72),
        ("Kaerwyn: Issue 23 Page 78", "Kaerwyn", {"issue": 23}, 78),
        ("Play House P. 23/?", "Play House", {}, 23),
        ("The Warchief's Challenge - Page 4", "The Warchief's Challenge", {}, 4),
        ("Frieren: Mage´s gift page 27", "Frieren: Mage's gift", {}, 27),
        ("Ride Home (Finished) Page 1", "Ride Home", {}, 1),
        ("The Bad Tenant Ch. 27", "The Bad Tenant", {"chapter": 27}, None),
        ("My Own Villainess - Chapter 59 - A Life Worth Living", "My Own Villainess", {"chapter": 59}, None),
        ("Moonlit Tales Part II - Chapter Three - Page 7", "Moonlit Tales", {"part": 2, "chapter": 3}, 7),
        ("Sunset Diaries Vol. 2 - Page 5", "Sunset Diaries", {"volume": 2}, 5),
        ("Star Crossed Ep. 4 - Pg 10", "Star Crossed", {"episode": 4}, 10),
        ("Night Shift - Page 035", "Night Shift", {}, 35),
    ],
)
def test_real_world_titles(title, series, groups, page):
    p = parse_title(title)
    assert p.series == series
    assert p.groups == groups
    assert p.page == page
    assert p.confidence >= 0.75


def test_page_range():
    p = parse_title("Isla: Origins - Chapter 1 - Pages 10-12")
    assert (p.page, p.page_end) == (10, 12)


def test_subtitle_is_not_part_of_identity():
    a = parse_title("My Own Villainess - Chapter 59 - A Life Worth Living")
    b = parse_title("My Own Villainess - Chapter 59 - Page 2")
    assert a.subtitle == "A Life Worth Living"
    assert a.work_key() == b.work_key()


def test_no_series_name_has_low_confidence():
    p = parse_title("Chapter 26, Page 16")
    assert p.series is None
    assert p.chapter == 26 and p.page == 16
    assert p.confidence < 0.75
    assert "no series name in title" in p.warnings


def test_bracket_prefix_used_as_series_with_lower_confidence():
    p = parse_title("[LIFT Update] Chapter 5, Page 2")
    assert p.series == "LIFT"
    assert p.chapter == 5 and p.page == 2
    assert p.confidence < 0.75


def test_page_word_without_number_is_suspicious():
    p = parse_title("Regarding this page...")
    assert p.page is None
    assert p.confidence < 0.75


@pytest.mark.parametrize("title", [
    "A Specter of Love - Part 2 - Page 35 (Sketch)",
    "A Specter of Love Part 2 WIP page 35",
    "[Sketch] A Specter of Love - Part 2 - Page 35",
    "A Specter of Love - Part 2 - Lineart Page 35",
    "A Specter of Love - Part 2 - Page 35 rough",
])
def test_sketches_are_a_separate_work(title):
    finished = parse_title("A Specter of Love - Part 2 - Page 35")
    sketch = parse_title(title)
    assert sketch.variant == "sketches" and finished.variant is None
    assert sketch.series == "A Specter of Love" and sketch.part == 2 and sketch.page == 35
    assert sketch.work_key() == "a specter of love|part:2|variant:sketches" != finished.work_key()
    assert sketch.display_title() == "A Specter of Love - Part 2 - Sketches"


def test_preview_is_not_a_sketch_but_less_certain():
    p = parse_title("A Specter of Love - Part 2 - Page 39 Preview")
    assert p.variant is None and p.confidence < 1.0


def test_standalone_title():
    p = parse_title("Barbara Halloween costume")
    assert p.series == "Barbara Halloween costume"
    assert not p.has_markers
    assert p.confidence >= 0.75


def test_lost_emoji_removed():
    assert parse_title("?? Evelyn ??  ").series == "Evelyn"


def test_words_containing_keywords_are_not_markers():
    p = parse_title("Chill Partners Chapel - Page 3")
    assert p.series == "Chill Partners Chapel"
    assert p.groups == {}
    assert p.page == 3


def test_case_punctuation_whitespace_insensitive_keys():
    a = parse_title("A Specter of Love - Part 2 - Page 35")
    b = parse_title("a specter  of love: PART 2 | page 36")
    c = parse_title("A Specter of Love! - Part 2 - Page 1")
    assert a.work_key() == b.work_key() == c.work_key()


def test_normalize_helpers():
    assert clean_text("Mage´s – gift") == "Mage's - gift"
    assert normalize_key("Isla: Origins") == "isla origins"
    assert normalize_key("The Warchief's") == normalize_key("The Warchiefs")


def test_empty_title():
    p = parse_title("")
    assert p.series is None and p.confidence == 0.0


def test_sketch_detected_from_file_names():
    from pawchive_downloader.recognition.title_parser import apply_file_name_hints

    p = parse_title("A Specter of Love Pages 190")
    apply_file_name_hints(p, ["Sketch---190.jpg"])
    assert p.variant == "sketches"
    q = parse_title("A Specter of Love - Page 190")
    apply_file_name_hints(q, ["A-Spector-of-Love---190.jpg"])
    assert q.variant is None

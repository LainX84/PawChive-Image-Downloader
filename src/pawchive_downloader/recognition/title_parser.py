"""Publication title parser.

Turns titles such as ``"Isla: Origins - Chapter 1 - Page 12"`` into a
:class:`ParsedTitle` (series ``Isla: Origins``, chapter ``1``, page ``12``).

The parser is a pipeline of small, ordered rules rather than one large regular
expression:

1. clean the text (unicode, quotes, dashes, emoji);
2. handle bracketed groups: unwrap ones that contain markers, drop the rest as noise;
3. find group markers (volume, part, chapter, issue, episode);
4. find the page marker (rightmost wins);
5. the text before the first marker is the series name; text after the last
   group marker is a subtitle (kept for display, not used for identity);
6. strip noise words at segment edges and score the confidence.

Every decision that is a guess lowers ``confidence`` and adds a ``warning``.
Low-confidence results are sent to the user for confirmation by the matcher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import clean_text, normalize_key

GROUP_ORDER = ("volume", "part", "chapter", "issue", "episode")
GROUP_LABELS = {"volume": "Volume", "part": "Part", "chapter": "Chapter", "issue": "Issue", "episode": "Episode"}

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_ROMAN_RE = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", re.IGNORECASE)
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

_NUM_LONG = r"(?P<n>\d{1,4}|[ivxlcdm]{1,7}|" + "|".join(_WORD_NUMBERS) + r")"
_NUM_SHORT = r"(?P<n>\d{1,4})"

# (kind, long keywords allowing roman/word numbers, short keywords digits only)
_GROUP_SPECS: tuple[tuple[str, str, str], ...] = (
    ("volume", r"volume", r"vol|vols|v(?=\s*\d)"),
    ("part", r"part", r"pt"),
    ("chapter", r"chapter|chapitre|capitulo|capítulo|kapitel", r"chap|chp|ch|cap"),
    ("issue", r"issue", r"iss|no(?=\.\s*\d)"),
    ("episode", r"episode", r"ep|eps"),
)

_GROUP_PATTERNS: list[tuple[str, re.Pattern[str]]] = []
for _kind, _long, _short in _GROUP_SPECS:
    _GROUP_PATTERNS.append(
        (_kind, re.compile(rf"(?<![\w])(?:{_long})\s*[.:#-]?\s*{_NUM_LONG}(?![\w])", re.IGNORECASE))
    )
    _GROUP_PATTERNS.append(
        (_kind, re.compile(rf"(?<![\w])(?:{_short})\s*[.:#-]?\s*{_NUM_SHORT}(?!\d)(?![a-z])", re.IGNORECASE))
    )
_GROUP_PATTERNS.append(("issue", re.compile(r"(?<![\w&])#\s?(?P<n>\d{1,4})(?!\d)")))

_PAGE_RANGE_RE = re.compile(
    r"(?<![\w])(?:pages?|pgs?|pp)\s*\.?\s*(?P<a>\d{1,4})\s*(?:-|to|&|~)\s*(?P<b>\d{1,4})(?!\d)", re.IGNORECASE
)
_PAGE_RE = re.compile(
    r"(?<![\w])(?:pages?|pg|pagina|página|seite|planche)\s*\.?\s*[#:]?\s*(?P<a>\d{1,4})"
    r"(?:\s*(?:/|of)\s*(?:\d{1,4}|\?))?(?!\d)",
    re.IGNORECASE,
)
_PAGE_SHORT_RE = re.compile(r"(?<![\w])p\.?\s?(?P<a>\d{1,4})(?:\s*/\s*(?:\d{1,4}|\?))?(?![\w])", re.IGNORECASE)
_FRACTION_END_RE = re.compile(r"(?<![\w#./])(?P<a>\d{1,4})\s*/\s*(?:\d{1,4}|\?)\s*$")
_TRAILING_NUMBER_RE = re.compile(r"(?<=[\w!?.)\]]\s)(?P<a>\d{1,4})\s*$")
_PAGE_WORD_RE = re.compile(r"(?<![\w])pages?(?![\w])", re.IGNORECASE)

_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]|\(([^()]*)\)|【([^【】]*)】|\{([^{}]*)\}")

# Words that describe the state of a publication rather than its identity.
# They are only removed at the edges of a segment, never from the middle.
NOISE_WORDS = (
    "work in progress", "early access", "line art", "full res", "high res", "hi-res", "full page",
    "wip", "sketch", "sketches", "preview", "previews", "lineart", "teaser", "finished", "final",
    "colored", "coloured", "colors", "uncensored", "censored", "nsfw", "sfw", "update", "updated",
    "hd", "hq", "4k", "full", "new", "release", "released", "public", "exclusive", "reward",
    "rewards", "ea", "fin", "end", "the end", "complete", "completed", "alt", "version",
    "rough", "roughs", "draft", "drafts", "storyboard", "storyboards",
)
# Sketches, WIPs, line art and drafts are a *different work* from the
# finished pages: they get their own folder ("<work> - Sketches").
SKETCH_VARIANT = "sketches"
_SKETCH_RE = re.compile(
    r"(?<![\w])(?:sketch(?:es|ed)?|wips?|work in progress|line ?arts?|rough(?:s)?|drafts?|storyboards?)(?![\w])",
    re.IGNORECASE,
)
# Previews/teasers are announcements of a page: kept with the work but less certain.
_PREVIEW_RE = re.compile(r"(?<![\w])(?:previews?|teasers?)(?![\w])", re.IGNORECASE)
_NOISE_EDGE_RE = re.compile(
    r"^(?:\s|[-|:,~/.!])*(?P<w>" + "|".join(re.escape(w) for w in sorted(NOISE_WORDS, key=len, reverse=True)) + r")(?![\w])",
    re.IGNORECASE,
)
_NOISE_EDGE_END_RE = re.compile(
    r"(?<![\w])(?P<w>" + "|".join(re.escape(w) for w in sorted(NOISE_WORDS, key=len, reverse=True)) + r")(?:\s|[-|:,~/.!])*$",
    re.IGNORECASE,
)

_EDGE_CHARS = " -|:,~/.;_+*=>"
_MARK = "\x00"


def _to_int(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    if token in _WORD_NUMBERS:
        return _WORD_NUMBERS[token]
    if token and _ROMAN_RE.match(token):
        total, prev = 0, 0
        for ch in reversed(token):
            value = _ROMAN_VALUES[ch]
            total = total - value if value < prev else total + value
            prev = max(prev, value)
        return total or None
    return None


@dataclass
class ParsedTitle:
    raw: str
    series: str | None = None
    subtitle: str | None = None
    volume: int | None = None
    part: int | None = None
    chapter: int | None = None
    issue: int | None = None
    episode: int | None = None
    page: int | None = None
    page_end: int | None = None
    variant: str | None = None  # "sketches" for sketch / WIP / line-art publications
    noise: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 1.0

    @property
    def groups(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in GROUP_ORDER if getattr(self, k) is not None}

    @property
    def has_markers(self) -> bool:
        return bool(self.groups) or self.page is not None

    @property
    def series_key(self) -> str:
        return normalize_key(self.series or "")

    def work_key(self) -> str:
        """Identity of the work within an author, e.g. ``"isla origins|chapter:1"``."""
        key = self.series_key + "".join(f"|{k}:{v}" for k, v in self.groups.items())
        return key + (f"|variant:{self.variant}" if self.variant else "")

    def display_title(self) -> str:
        """Human title of the work, e.g. ``"Isla: Origins - Chapter 1"``."""
        parts = [self.series or "Untitled"]
        parts += [f"{GROUP_LABELS[k]} {v}" for k, v in self.groups.items()]
        if self.variant:
            parts.append(self.variant.capitalize())
        return " - ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw, "series": self.series, "subtitle": self.subtitle, "volume": self.volume,
            "part": self.part, "chapter": self.chapter, "issue": self.issue, "episode": self.episode,
            "page": self.page, "page_end": self.page_end, "variant": self.variant, "noise": self.noise, "warnings": self.warnings,
            "confidence": round(self.confidence, 3),
        }


def _strip_edges(text: str, noise: list[str]) -> str:
    """Trim separators and edge noise words repeatedly."""
    previous = None
    while previous != text:
        previous = text
        text = text.strip(_EDGE_CHARS)
        if m := _NOISE_EDGE_RE.match(text):
            rest = text[m.end():]
            if rest.strip(_EDGE_CHARS):  # never strip a title down to nothing
                noise.append(m["w"])
                text = rest
        if m := _NOISE_EDGE_END_RE.search(text):
            rest = text[: m.start()]
            if rest.strip(_EDGE_CHARS):
                noise.append(m["w"])
                text = rest
    return re.sub(r"\s+", " ", text).strip()


_NOISE_SET = {w.casefold() for w in NOISE_WORDS}


def _strip_noise_only(text: str) -> str:
    """Return *text* without noise words; empty if it contained nothing else."""
    words = normalize_key(text).split()
    remaining = [w for w in words if w not in _NOISE_SET]
    return " ".join(remaining)


def apply_file_name_hints(parsed: ParsedTitle, image_names: list[str]) -> None:
    """Mark a publication as sketches when every image file is named as one
    ("Sketch---190.jpg"), even if the title does not say so."""
    if parsed.variant or not image_names:
        return
    if all(_SKETCH_RE.search(clean_text(name.replace("_", " ").replace("-", " "))) for name in image_names):
        parsed.variant = SKETCH_VARIANT
        parsed.warnings.append("sketch detected from the file names")


def _contains_marker(text: str) -> bool:
    return any(p.search(text) for _, p in _GROUP_PATTERNS) or bool(
        _PAGE_RANGE_RE.search(text) or _PAGE_RE.search(text) or _PAGE_SHORT_RE.search(text)
    )


def parse_title(title: str) -> ParsedTitle:
    result = ParsedTitle(raw=title)
    text = clean_text(title)
    if not text:
        result.series = None
        result.confidence = 0.0
        result.warnings.append("empty title")
        return result

    # --- 1. bracketed groups ------------------------------------------------
    bracket_prefix: str | None = None

    def _bracket(m: re.Match[str]) -> str:
        nonlocal bracket_prefix
        content = next(g for g in m.groups() if g is not None).strip()
        if _contains_marker(content):
            return f" - {content} - "
        if content:
            result.noise.append(content)
            if m.start() == 0 and bracket_prefix is None:
                bracket_prefix = content
        return " - "

    for _ in range(3):  # nested brackets
        new_text = _BRACKET_RE.sub(_bracket, text)
        if new_text == text:
            break
        text = new_text

    # --- 2. group markers -----------------------------------------------------
    spans: list[tuple[int, int, str]] = []  # (start, end, kind)

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e, _ in spans)

    for kind, pattern in _GROUP_PATTERNS:
        for m in pattern.finditer(text):
            if _overlaps(m.start(), m.end()):
                continue
            value = _to_int(m["n"])
            if value is None:
                continue
            if getattr(result, kind) is None:
                setattr(result, kind, value)
                spans.append((m.start(), m.end(), kind))
            elif getattr(result, kind) != value:
                result.warnings.append(f"conflicting {kind} numbers")
                spans.append((m.start(), m.end(), "dup"))
            break  # only the first occurrence of each pattern

    # --- 3. page marker (rightmost wins) --------------------------------------
    page_candidates: list[tuple[int, int, int, int | None]] = []
    for m in _PAGE_RANGE_RE.finditer(text):
        if not _overlaps(m.start(), m.end()):
            page_candidates.append((m.start(), m.end(), int(m["a"]), int(m["b"])))
    for pattern in (_PAGE_RE, _PAGE_SHORT_RE):
        for m in pattern.finditer(text):
            if _overlaps(m.start(), m.end()) or any(
                not (m.end() <= s or m.start() >= e) for s, e, *_ in page_candidates
            ):
                continue
            page_candidates.append((m.start(), m.end(), int(m["a"]), None))
    unlabelled_page = False
    if not page_candidates:
        m = _FRACTION_END_RE.search(text)
        if m and not _overlaps(m.start(), m.end()):
            page_candidates.append((m.start(), m.end(), int(m["a"]), None))
    if not page_candidates and not result.groups:
        m = _TRAILING_NUMBER_RE.search(text)
        if m and not _overlaps(m.start(), m.end()) and m.start() > 0:
            page_candidates.append((m.start(), m.end(), int(m["a"]), None))
            unlabelled_page = True
    if page_candidates:
        page_candidates.sort()
        start, end, first, last = page_candidates[-1]
        if last is not None and last < first:
            first, last = last, first
        result.page = first
        result.page_end = last if last and last != first else None
        spans.append((start, end, "page"))
        distinct = {c[2] for c in page_candidates}
        if len(distinct) > 1:
            result.warnings.append("several page numbers in title")
        for s, e, *_ in page_candidates[:-1]:
            spans.append((s, e, "dup"))

    # --- 4. split into segments ------------------------------------------------
    spans.sort()
    chars = list(text)
    for start, end, _ in spans:
        for i in range(start, end):
            chars[i] = _MARK
    marked = "".join(chars)
    segments = [seg for seg in re.split(f"{_MARK}+", marked)]
    group_spans = [s for s in spans if s[2] in GROUP_ORDER]

    before_first = segments[0] if spans else marked
    series = _strip_edges(before_first, result.noise)
    series_source = "leading"
    if spans and group_spans:
        last_group_end = max(e for _, e, _ in group_spans)
        tail = marked[last_group_end:].replace(_MARK, " ")
        if page_spans := [s for s in spans if s[2] == "page" and s[0] >= last_group_end]:
            tail = marked[last_group_end:page_spans[0][0]]
        subtitle = _strip_edges(tail.replace(_MARK, " "), result.noise)
        result.subtitle = subtitle or None

    if not series:
        remaining = [_strip_edges(seg, result.noise) for seg in segments[1:]]
        remaining = [r for r in remaining if r]
        if result.subtitle and remaining and remaining[0] == result.subtitle:
            remaining = []  # the only text left is a chapter subtitle, not a series
        if remaining:
            series = remaining[0]
            series_source = "trailing"
        elif bracket_prefix:
            series = _strip_edges(bracket_prefix, [])
            series_source = "bracket"

    # A "series" made only of noise words ("Sketches", "WIP", "Final") is no series.
    if series and not _strip_noise_only(series):
        result.noise.append(series)
        series = ""
    result.series = series or None

    # --- 5. confidence -----------------------------------------------------------
    confidence = 1.0 if result.has_markers and not unlabelled_page else 0.85
    if result.series is None:
        confidence -= 0.6
        result.warnings.append("no series name in title")
    else:
        if series_source == "bracket":
            confidence -= 0.3
            result.warnings.append("series name taken from a bracketed prefix")
        elif series_source == "trailing":
            confidence -= 0.25
            result.warnings.append("series name found after the markers")
        if len(normalize_key(result.series)) < 2:
            confidence -= 0.3
            result.warnings.append("series name is very short")
        if _PAGE_WORD_RE.search(result.series):
            confidence -= 0.3
            result.warnings.append("the word 'page' appears without a page number")
    if unlabelled_page:
        confidence -= 0.15
        result.warnings.append("unlabelled trailing number interpreted as a page number")
    if _SKETCH_RE.search(clean_text(title)):
        result.variant = SKETCH_VARIANT
    elif _PREVIEW_RE.search(clean_text(title)):
        confidence -= 0.1
        result.warnings.append("title marks a preview/teaser")
    if any(w.startswith("conflicting") or w.startswith("several") for w in result.warnings):
        confidence -= 0.2
    result.confidence = max(0.0, min(1.0, round(confidence, 3)))
    return result

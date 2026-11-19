"""Decide which work a parsed publication belongs to.

Rules (in order):

1. A remembered association (alias) for this work key wins.
2. An existing work with exactly the same key is used.
3. A confident parse with no *similar* existing work creates a new work.
4. Everything else goes to the user for review, with ranked candidates.

"Similar" never leads to an automatic merge: two different artworks with
similar names stay separate unless the user says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from .normalize import compact_key
from .title_parser import ParsedTitle


class MatchAction(str, Enum):
    EXISTING = "existing"
    CREATE = "create"
    REVIEW = "review"


@dataclass(frozen=True)
class WorkRef:
    """Minimal view of a stored work used for matching."""

    work_id: int
    work_key: str
    display_title: str

    @property
    def series_key(self) -> str:
        return self.work_key.split("|", 1)[0]

    @property
    def variant(self) -> str | None:
        for token in self.work_key.split("|")[1:]:
            if token.startswith("variant:"):
                return token.split(":", 1)[1]
        return None

    @property
    def groups(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for token in self.work_key.split("|")[1:]:
            kind, _, value = token.partition(":")
            if value.isdigit():
                out[kind] = int(value)
        return out


@dataclass
class Candidate:
    work_id: int
    display_title: str
    score: float
    reason: str


@dataclass
class MatchDecision:
    action: MatchAction
    work_key: str
    display_title: str
    work_id: int | None = None
    confidence: float = 1.0
    reason: str = ""
    candidates: list[Candidate] = field(default_factory=list)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_candidates(parsed: ParsedTitle, works: list[WorkRef], threshold: float) -> list[Candidate]:
    """Existing works that could plausibly be the same artwork."""
    series_key = parsed.series_key
    groups = parsed.groups
    found: dict[int, Candidate] = {}

    for work in works:
        score = 0.0
        reason = ""
        w_groups = work.groups
        if series_key:
            if work.series_key == series_key and work.variant != parsed.variant:
                # Sketches vs finished pages of the same series: different works.
                if w_groups == groups:
                    score, reason = 0.5, "same series; sketches and finished pages are kept apart"
            elif work.series_key == series_key:
                if w_groups == groups:
                    score, reason = 1.0, "same title"
                elif set(groups.items()) < set(w_groups.items()):
                    score, reason = 0.9, "same series; this title has fewer part/chapter markers"
                elif set(w_groups.items()) < set(groups.items()):
                    # e.g. "Isla: Origins" exists and "Isla: Origins - Chapter 1" arrives:
                    # a numbered chapter/part of a series is its own work.
                    score, reason = 0.5, "same series; this title adds part/chapter markers"
                else:
                    score, reason = 0.5, "same series, different part/chapter"
            elif compact_key(work.series_key) == compact_key(series_key):
                score, reason = 0.95, "same title apart from spacing"
            else:
                ratio = _similarity(work.series_key, series_key)
                if ratio >= threshold:
                    score, reason = ratio * 0.9, f"similar title ({ratio:.0%})"
        else:
            # No series name: propose works with identical markers.
            if groups and w_groups == groups:
                score, reason = 0.6, "same part/chapter numbers"
            elif groups and set(groups.items()) <= set(w_groups.items()):
                score, reason = 0.4, "matching part/chapter numbers"
        if score > 0:
            found[work.work_id] = Candidate(work.work_id, work.display_title, round(score, 3), reason)
    return sorted(found.values(), key=lambda c: (-c.score, c.display_title))


def match_work(
    parsed: ParsedTitle,
    works: list[WorkRef],
    aliases: dict[str, int],
    auto_create_min_confidence: float = 0.75,
    similarity_threshold: float = 0.85,
) -> MatchDecision:
    key = parsed.work_key()
    title = parsed.display_title()
    by_id = {w.work_id: w for w in works}

    # 1. remembered association
    if key in aliases and aliases[key] in by_id:
        work = by_id[aliases[key]]
        return MatchDecision(MatchAction.EXISTING, key, work.display_title, work.work_id, 1.0, "confirmed association")

    # 2. exact work key
    for work in works:
        if work.work_key == key and parsed.series_key:
            return MatchDecision(MatchAction.EXISTING, key, work.display_title, work.work_id, 1.0, "same work key")

    candidates = find_candidates(parsed, works, similarity_threshold)
    # Different part/chapter of the same series is a different work; it is
    # not a reason for review by itself.
    risky = [c for c in candidates if c.score >= 0.6]

    if not parsed.series_key:
        return MatchDecision(
            MatchAction.REVIEW, key, title, None, parsed.confidence,
            "the title has no series name", candidates,
        )
    if risky:
        return MatchDecision(
            MatchAction.REVIEW, key, title, None, min(parsed.confidence, 0.6),
            "similar existing work: " + risky[0].reason, candidates,
        )
    if parsed.confidence < auto_create_min_confidence:
        reason = "; ".join(parsed.warnings) or "low recognition confidence"
        return MatchDecision(MatchAction.REVIEW, key, title, None, parsed.confidence, reason, candidates)
    return MatchDecision(MatchAction.CREATE, key, title, None, parsed.confidence, "new work", candidates)

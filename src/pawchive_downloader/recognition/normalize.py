"""Text normalization used for title parsing and work matching."""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({
    "´": "'", "‘": "'", "’": "'", "‛": "'", "`": "'", "ʼ": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "―": "-", "−": "-", "‐": "-", "‑": "-",
    "｜": "|", "│": "|", "：": ":", "・": " ", "·": " ", "•": " ",
})
_ZERO_WIDTH = re.compile(r"[​-‏⁠﻿]")
_WHITESPACE = re.compile(r"\s+")
_LOST_EMOJI = re.compile(r"\?{2,}")  # emoji that became '??' during import


def strip_symbols(text: str) -> str:
    """Remove emoji and other pictographic symbols."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("So", "Cs", "Co") or ch in "️⃣":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def clean_text(text: str) -> str:
    """Canonical display form: NFKC, unified quotes/dashes, no emoji, single spaces."""
    # Translate before NFKC: NFKC decomposes U+00B4 into a space + combining accent.
    text = (text or "").translate(_QUOTES)
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.translate(_QUOTES)
    text = strip_symbols(text)
    text = _LOST_EMOJI.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_key(text: str) -> str:
    """Matching key: case-, punctuation- and whitespace-insensitive.

    ``"Isla: Origins"`` and ``"isla  origins!"`` both become ``"isla origins"``.
    Apostrophes are dropped rather than turned into spaces so that
    ``"Warchief's"`` and ``"Warchiefs"`` compare equal.
    """
    text = clean_text(text).casefold()
    text = text.replace("'", "").replace("&", " and ")
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return _WHITESPACE.sub(" ", text).strip()


def compact_key(text: str) -> str:
    """Key without any spaces, to catch 'Spectre ofLove' style spacing typos."""
    return normalize_key(text).replace(" ", "")

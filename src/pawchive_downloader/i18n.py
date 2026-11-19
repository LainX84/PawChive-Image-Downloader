"""User-interface translations (English and Italian).

English text is the key; :data:`CATALOGS` maps it to other languages. Text is
looked up with :func:`_` and formatted with :meth:`str.format` when arguments
are given, so templates use ``{0}``/``{name}`` placeholders. Pure Python: the
engine may use it for messages shown to the user (logs stay in English).
"""

from __future__ import annotations

import locale
import os
from typing import Any

from .i18n_it import IT

LANGUAGES = {"en": "English", "it": "Italiano"}
CATALOGS: dict[str, dict[str, str]] = {"en": {}, "it": IT}
_current = "en"


def system_language() -> str:
    """Best guess of the operating system language among the supported ones."""
    candidates = [os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    try:
        from PySide6.QtCore import QLocale  # optional: precise on Windows/macOS

        candidates.insert(0, QLocale.system().name())
    except Exception:  # noqa: BLE001 - Qt missing or not initialized
        pass
    for value in candidates:
        code = value.lower()[:2]
        if code in LANGUAGES:
            return code
        if value.lower().startswith("italian"):
            return "it"
    return "en"


def resolve_language(setting: str) -> str:
    return setting if setting in LANGUAGES else system_language()


def set_language(code: str) -> None:
    global _current
    _current = resolve_language(code)


def language() -> str:
    return _current


def _(text: str, *args: Any, **kwargs: Any) -> str:
    translated = CATALOGS.get(_current, {}).get(text, text)
    if args or kwargs:
        try:
            return translated.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return text.format(*args, **kwargs)
    return translated


def plural(count: int, one: str, many: str) -> str:
    """``plural(n, "{0} file", "{0} files")`` translated and formatted."""
    return _(one if count == 1 else many, count)

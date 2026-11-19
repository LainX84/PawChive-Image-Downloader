"""Typed application settings, persisted as JSON.

Settings never contain secrets. Authentication cookies are stored separately
in the operating system's credential store (see :mod:`pawchive_downloader.auth`).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir

from ..version import APP_ID

log = logging.getLogger(__name__)

SETTINGS_FILE_NAME = "settings.json"

# Lower bounds that protect the website from excessive load. Values below
# these are clamped, whatever the settings file says.
MIN_MONITOR_INTERVAL_MINUTES = 30
MIN_REQUEST_DELAY_SECONDS = 0.5
MAX_CONCURRENT_DOWNLOADS = 4


def default_base_dir() -> Path:
    """Default root folder holding Archive/, Temp/, Database/ and Logs/."""
    return Path(user_data_dir(APP_ID, appauthor=False))


def default_config_dir() -> Path:
    return Path(user_config_dir(APP_ID, appauthor=False))


@dataclass
class Settings:
    """All user-configurable options. Paths are stored as strings."""

    # --- Paths -----------------------------------------------------------
    archive_dir: str = ""
    temp_dir: str = ""
    database_dir: str = ""
    logs_dir: str = ""

    # --- Website ---------------------------------------------------------
    base_url: str = "https://pawchive.pw"

    # --- Monitoring ------------------------------------------------------
    monitor_interval_minutes: int = 360
    scan_on_startup: bool = True
    full_rescan_days: int = 7  # periodic full pass to catch edits of older posts
    empty_gallery_recheck_hours: int = 72
    previews_only_recheck_hours: int = 24
    unavailable_file_recheck_hours: int = 48
    max_rechecks: int = 10

    # --- Requests --------------------------------------------------------
    request_delay_seconds: float = 1.5
    request_timeout_seconds: float = 30.0
    max_concurrent_downloads: int = 2
    max_downloads_per_host: int = 1

    # --- Retries ---------------------------------------------------------
    retry_base_seconds: int = 60
    retry_max_seconds: int = 6 * 3600
    max_download_attempts: int = 8
    blocked_pause_minutes: int = 30
    max_download_speed_kbps: int = 0  # total for all downloads; 0 = unlimited

    # --- Recognition -----------------------------------------------------
    auto_create_min_confidence: float = 0.75
    similarity_review_threshold: float = 0.85

    # --- Maintenance -----------------------------------------------------
    database_backups_to_keep: int = 7
    log_level: str = "INFO"

    # --- Interface -------------------------------------------------------
    language: str = "system"  # "system", "en" or "it"
    theme: str = "system"  # "system", "light" or "dark"
    minimize_to_tray: bool = True  # closing the window keeps the app in the notification area
    notify_new_pages: bool = True  # desktop notification when a work receives new pages

    # Extra keys from newer/older versions are preserved here so that saving
    # never silently drops them.
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def resolved(self, base_dir: Path | None = None) -> "Settings":
        """Return a copy with empty paths filled with defaults and limits enforced."""
        base = base_dir or default_base_dir()
        s = Settings(**{f.name: getattr(self, f.name) for f in fields(self)})
        s.archive_dir = s.archive_dir or str(base / "Archive")
        s.temp_dir = s.temp_dir or str(base / "Temp")
        s.database_dir = s.database_dir or str(base / "Database")
        s.logs_dir = s.logs_dir or str(base / "Logs")
        s.monitor_interval_minutes = max(MIN_MONITOR_INTERVAL_MINUTES, int(s.monitor_interval_minutes))
        s.request_delay_seconds = max(MIN_REQUEST_DELAY_SECONDS, float(s.request_delay_seconds))
        s.max_concurrent_downloads = min(MAX_CONCURRENT_DOWNLOADS, max(1, int(s.max_concurrent_downloads)))
        s.max_downloads_per_host = min(s.max_concurrent_downloads, max(1, int(s.max_downloads_per_host)))
        s.max_download_attempts = max(1, int(s.max_download_attempts))
        s.retry_base_seconds = max(5, int(s.retry_base_seconds))
        s.retry_max_seconds = max(s.retry_base_seconds, int(s.retry_max_seconds))
        s.auto_create_min_confidence = min(1.0, max(0.0, float(s.auto_create_min_confidence)))
        s.similarity_review_threshold = min(1.0, max(0.5, float(s.similarity_review_threshold)))
        if s.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            s.log_level = "INFO"
        s.log_level = s.log_level.upper()
        s.base_url = s.base_url.rstrip("/")
        s.max_download_speed_kbps = max(0, int(s.max_download_speed_kbps))
        if s.language not in ("system", "en", "it"):
            s.language = "system"
        if s.theme not in ("system", "light", "dark"):
            s.theme = "system"
        return s

    # Convenience path accessors (valid on resolved settings) --------------
    @property
    def archive_path(self) -> Path:
        return Path(self.archive_dir)

    @property
    def temp_path(self) -> Path:
        return Path(self.temp_dir)

    @property
    def downloads_temp_path(self) -> Path:
        """In-progress ``.part`` files."""
        return Path(self.temp_dir) / "Downloads"

    @property
    def held_temp_path(self) -> Path:
        """Verified files waiting for the user to choose their work."""
        return Path(self.temp_dir) / "Incomplete"

    @property
    def database_path(self) -> Path:
        return Path(self.database_dir) / "pawchive.db"

    @property
    def logs_path(self) -> Path:
        return Path(self.logs_dir)

    # Serialization -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra", {}) or {}
        return {**extra, **data}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name: f for f in fields(cls) if f.name != "extra"}
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        defaults = cls()
        for key, value in data.items():
            if key in known:
                expected = type(getattr(defaults, key))
                try:
                    if expected is bool:
                        kwargs[key] = bool(value)
                    elif expected in (int, float, str):
                        kwargs[key] = expected(value)
                    else:
                        kwargs[key] = value
                except (TypeError, ValueError):
                    log.warning("Ignoring invalid value for setting %r", key)
            else:
                extra[key] = value
        return cls(**kwargs, extra=extra)


class SettingsStore:
    """Loads and saves :class:`Settings` atomically."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else default_config_dir()
        self.path = self.config_dir / SETTINGS_FILE_NAME

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings root is not an object")
            return Settings.from_dict(data)
        except (OSError, ValueError) as exc:
            backup = self.path.with_suffix(".invalid.json")
            log.error("Settings file is unreadable (%s); using defaults. Copy kept at %s", exc, backup)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return Settings()

    def save(self, settings: Settings) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=self.config_dir, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

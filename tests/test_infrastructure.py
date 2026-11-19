"""Database, settings, logging, session storage and verification."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import zipfile
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend

from conftest import make_image
from pawchive_downloader.archive.organizer import Organizer
from pawchive_downloader.auth.session import SessionStore, parse_cookie_text
from pawchive_downloader.config.paths import validate_paths
from pawchive_downloader.config.settings import Settings, SettingsStore
from pawchive_downloader.diagnostics.export import export_diagnostics
from pawchive_downloader.diagnostics.logging_setup import RedactingFilter, setup_logging
from pawchive_downloader.downloads.verify import detect_type, verify_file
from pawchive_downloader.site.errors import IntegrityError
from pawchive_downloader.storage.backup import backup_database
from pawchive_downloader.storage.db import Database
from pawchive_downloader.storage.migrate import MigrationError, available_migrations, current_version, migrate


# -------------------------------------------------------------- database
def test_migration_creates_schema_and_is_idempotent(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    latest = available_migrations()[-1][0]
    assert migrate(db, tmp_path / "backups") == latest
    assert migrate(db, tmp_path / "backups") == latest
    tables = {r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"authors", "galleries", "works", "files", "download_queue", "work_aliases"} <= tables
    assert db.scalar("PRAGMA journal_mode") == "wal"
    db.close()


def test_newer_schema_is_refused(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    db.execute("PRAGMA user_version = 999")
    with pytest.raises(MigrationError):
        migrate(db)
    db.close()


def test_transaction_rolls_back(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    migrate(db)
    with pytest.raises(RuntimeError):
        with db.transaction() as c:
            c.execute("INSERT INTO app_state (key, value) VALUES ('a', 'b')")
            raise RuntimeError
    assert db.scalar("SELECT COUNT(*) FROM app_state") == 0
    db.close()


def test_backup_and_rotation(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    migrate(db)
    db.execute("INSERT INTO app_state (key, value) VALUES ('k', 'v')")
    for _ in range(4):
        path = backup_database(db, tmp_path / "backups", keep=2)
        os.utime(path, None)
    backups = list((tmp_path / "backups").glob("*.db"))
    assert 1 <= len(backups) <= 2
    with sqlite3.connect(backups[0]) as copy:
        assert copy.execute("SELECT value FROM app_state WHERE key='k'").fetchone()[0] == "v"
    assert current_version(db) >= 1
    db.close()


# --------------------------------------------------------------- settings
def test_settings_roundtrip_and_limits(tmp_path: Path):
    store = SettingsStore(tmp_path)
    s = Settings(monitor_interval_minutes=1, request_delay_seconds=0.0, max_concurrent_downloads=50,
                 extra={"future_option": 1})
    store.save(s)
    loaded = store.load()
    assert loaded.extra == {"future_option": 1}
    resolved = loaded.resolved(tmp_path / "base")
    assert resolved.monitor_interval_minutes == 30          # protects the website
    assert resolved.request_delay_seconds == 0.5
    assert resolved.max_concurrent_downloads == 4
    assert resolved.archive_dir.endswith("Archive")


def test_corrupt_settings_fall_back_to_defaults(tmp_path: Path):
    (tmp_path / "settings.json").write_text("{not json")
    assert SettingsStore(tmp_path).load() == Settings()
    assert (tmp_path / "settings.invalid.json").exists()


def test_path_validation(tmp_path: Path):
    s = Settings().resolved(tmp_path)
    assert validate_paths(s) == []
    s.temp_dir = str(Path(s.archive_dir) / "Temp")
    assert any(p.setting == "temp_dir" for p in validate_paths(s))
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    s = Settings(archive_dir=str(blocker)).resolved(tmp_path)
    assert any(p.setting == "archive_dir" for p in validate_paths(s))


# ---------------------------------------------------------------- logging
def test_redaction_filter_masks_secrets():
    f = RedactingFilter(lambda: ["supersecretvalue123"])
    text = f.redact("Cookie: session=abcdef; other=1 token=xyz value supersecretvalue123")
    assert "abcdef" not in text and "xyz" not in text and "supersecretvalue123" not in text
    assert "[REDACTED]" in text


def test_log_file_is_json_and_redacted(tmp_path: Path):
    setup_logging(tmp_path, "INFO", lambda: ["hunter2-secret"])
    logging.getLogger("pawchive_downloader.test").warning("sending Cookie: session=topsecret and hunter2-secret")
    for handler in logging.getLogger().handlers:
        handler.flush()
    line = (tmp_path / "pawchive.log").read_text().strip().splitlines()[-1]
    record = json.loads(line)
    assert record["level"] == "WARNING"
    assert "topsecret" not in line and "hunter2-secret" not in line


def test_diagnostics_export(tmp_path: Path):
    s = Settings().resolved(tmp_path)
    Path(s.logs_dir).mkdir(parents=True)
    (Path(s.logs_dir) / "pawchive.log").write_text("Cookie: session=abc123456\n")
    db = Database(tmp_path / "db.sqlite")
    migrate(db)
    bundle = export_diagnostics(tmp_path, s, db, RedactingFilter())
    with zipfile.ZipFile(bundle) as z:
        assert {"info.json", "settings.json", "database-stats.json", "logs/pawchive.log"} <= set(z.namelist())
        assert "abc123456" not in z.read("logs/pawchive.log").decode()
    db.close()


# ---------------------------------------------------------------- session
class MemoryKeyring(KeyringBackend):
    priority = 10  # type: ignore[assignment]

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        self.data.pop((service, username), None)


def test_session_store_uses_keyring_only(tmp_path: Path):
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    store = SessionStore("PawChiveTest")
    assert store.cookie_header() is None
    assert store.set_cookies("session=abcdef123; Path=/; HttpOnly") == 1
    assert store.cookie_header() == "session=abcdef123"
    assert "abcdef123" in store.secret_values()
    store.clear()
    assert store.cookie_header() is None and backend.data == {}


def test_cookie_parsing_formats():
    netscape = "# Netscape HTTP Cookie File\n.pawchive.pw\tTRUE\t/\tTRUE\t0\tsession\tabc\nexample.com\tTRUE\t/\tFALSE\t0\tx\ty\n"
    assert parse_cookie_text(netscape) == {"session": "abc"}
    assert parse_cookie_text("a=1; b=2") == {"a": "1", "b": "2"}


# ----------------------------------------------------------- verification
def test_verify_detects_signatures_and_hash(tmp_path: Path):
    import hashlib

    data = make_image(3)
    path = tmp_path / "x.png"
    path.write_bytes(data)
    verify_file(path, hashlib.sha256(data).hexdigest(), "png", len(data))
    with pytest.raises(IntegrityError):
        verify_file(path, "0" * 64, "png")
    html = tmp_path / "y.png"
    html.write_bytes(b"<html>error</html>")
    with pytest.raises(IntegrityError):
        verify_file(html, hashlib.sha256(html.read_bytes()).hexdigest(), "png")
    assert detect_type(make_image(1, kind="webp")[:32]) == "webp"


def test_organizer_never_overwrites(tmp_path: Path):
    org = Organizer()
    target = tmp_path / "work"
    a, b = tmp_path / "a.part", tmp_path / "b.part"
    a.write_bytes(b"first")
    b.write_bytes(b"second")
    first = org.place(a, target, "Page 1.png")
    second = org.place(b, target, "Page 1.png")
    assert first.path.name == "Page 1.png" and second.path.name == "Page 1 (2).png"
    assert first.path.read_bytes() == b"first" and second.path.read_bytes() == b"second"
    assert not list(target.glob(".*.incoming"))


def test_organizer_cross_volume_fallback(tmp_path: Path, monkeypatch):
    org = Organizer()
    src = tmp_path / "s.part"
    src.write_bytes(b"data")
    real_replace = os.replace

    def fake_replace(a, b):
        if str(a).endswith(".part"):
            raise OSError(18, "Invalid cross-device link")
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", fake_replace)
    result = org.place(src, tmp_path / "dest", "f.bin")
    assert result.path.read_bytes() == b"data" and not src.exists()


def test_redaction_does_not_deadlock_when_provider_logs(tmp_path: Path):
    """Regression: the secrets provider (keyring) may log while being asked
    for secrets; that must not re-enter the filter and deadlock."""
    import threading

    lock = threading.RLock()

    def provider() -> list[str]:
        with lock:
            logging.getLogger("keyring").warning("backend message")
            return ["s3cr3t-value"]

    setup_logging(tmp_path, "INFO", provider)
    logging.getLogger("keyring").setLevel(logging.INFO)
    done = threading.Event()

    def emit() -> None:
        logging.getLogger("pawchive_downloader.test").warning("value s3cr3t-value")
        done.set()

    worker = threading.Thread(target=emit, daemon=True)
    worker.start()
    assert done.wait(5), "logging deadlocked"
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "s3cr3t-value" not in (tmp_path / "pawchive.log").read_text()
    for handler in list(logging.getLogger().handlers):  # do not leak into other tests
        logging.getLogger().removeHandler(handler)
        handler.close()
    logging.getLogger("keyring").setLevel(logging.WARNING)

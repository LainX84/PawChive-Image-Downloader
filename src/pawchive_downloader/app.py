"""Application bootstrap: settings → logging → database → engine → window."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .version import APP_ID, APP_NAME, ORGANIZATION, __version__
from .i18n import _

log = logging.getLogger("pawchive_downloader")


def _fatal(message: str) -> None:
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.critical(None, APP_NAME, message)


def _install_exception_hook() -> None:
    """Under pythonw there is no console: log unexpected errors and show them."""

    def hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Unhandled error", exc_info=(exc_type, exc, tb))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(None, APP_NAME, _('An unexpected error occurred:\n\n{0}\n\nDetails were written to the log file.', exc))
        except Exception:
            pass

    sys.excepthook = hook


def _apply_pending_relocation(store, settings):  # type: ignore[no-untyped-def]
    """Move data folders scheduled from the Settings page (before anything is opened)."""
    from PySide6.QtWidgets import QMessageBox

    from .config.relocate import PENDING_KEY, relocate

    pairs = settings.extra.get(PENDING_KEY)
    if not pairs:
        return settings
    report = relocate([tuple(p) for p in pairs])
    settings.extra.pop(PENDING_KEY, None)
    store.save(settings)
    lines = [_("The data folders were moved:")] + [f"• {m}" for m in report.moved]
    if report.skipped:
        lines += ["", _("{0} item(s) already existed at the destination and were left in place:", len(report.skipped))]
        lines += [f"• {s}" for s in report.skipped[:10]]
    if report.problems:
        lines += ["", _("Problems:")] + [f"• {p}" for p in report.problems]
        QMessageBox.warning(None, APP_NAME, "\n".join(lines))
    else:
        QMessageBox.information(None, APP_NAME, "\n".join(lines))
    return settings


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QDialog

    from .auth.session import SessionStore
    from .config.paths import prepare_directories, validate_paths
    from .config.settings import SettingsStore
    from .core.engine import Engine
    from .diagnostics.export import export_diagnostics
    from .diagnostics.logging_setup import setup_logging
    from .storage.backup import backup_database, latest_backup_date
    from .storage.db import Database
    from .storage.migrate import MigrationError, migrate
    from .ui.dialogs.first_run import FirstRunDialog
    from .ui.main_window import MainWindow
    from .i18n import set_language
    from .ui.icons import app_icon
    from .ui.theme import apply_theme

    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        if sys.stdout:  # windowed builds have no console
            print(f"{APP_NAME} {__version__}")
        return 0
    if "--self-test" in argv:
        return self_test()
    _install_exception_hook()
    _set_windows_app_id()
    QApplication.setApplicationName(APP_ID)
    QApplication.setOrganizationName(ORGANIZATION)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    app = QApplication(argv)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    app.setDesktopFileName(APP_ID)
    font = QFont(app.font())
    if sys.platform == "win32":
        font.setFamily("Segoe UI")
    app.setFont(font)

    store = SettingsStore()
    first_run = not store.path.exists()
    settings = store.load()
    set_language(settings.language)
    apply_theme(app, settings.theme)
    if first_run:
        dialog = FirstRunDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return 0
        settings = dialog.settings()
        store.save(settings)
    settings = _apply_pending_relocation(store, settings)
    if settings is None:
        return 1
    settings = settings.resolved()

    if not first_run and not settings.database_path.exists():
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            None, APP_NAME,
            _('No database was found at:\n{0}\n\nIf you moved the data folders by hand, choose No and update the folders in the settings file:\n{1}\n\nCreate a new, empty database here?', settings.database_path, store.path),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 1

    problems = validate_paths(settings)
    if problems:
        _fatal(_("Some configured folders cannot be used:\n\n") + "\n".join(
            f"• {p.setting}: {p.path} {p.message}" for p in problems) + _('\n\nEdit {0} or delete it to start over.', store.path))
        return 1
    prepare_directories(settings)

    # Only one instance may work on the same database.
    lock = QLockFile(str(Path(settings.database_dir) / "pawchive.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        _fatal(_("PawChive Image Downloader is already running with this data folder."))
        return 1

    session = SessionStore()
    redactor = setup_logging(settings.logs_path, settings.log_level, session.secret_values,
                             console="--console" in argv)
    log.info("%s %s starting", APP_NAME, __version__)
    session.load()

    db = Database(settings.database_path)
    backups = Path(settings.database_dir) / "backups"
    try:
        migrate(db, backups, settings.database_backups_to_keep)
    except MigrationError as exc:
        _fatal(_('The database cannot be opened: {0}', exc))
        return 1
    last = latest_backup_date(backups)
    if last is None or datetime.now() - last > timedelta(days=1):
        try:
            backup_database(db, backups, settings.database_backups_to_keep, label="daily")
        except Exception as exc:  # a failed backup must not prevent starting
            log.warning("Daily database backup failed: %s", exc)

    engine = Engine.create(settings, db, session)

    def export(target: Path) -> Path:
        return export_diagnostics(target, settings, db, redactor)

    window = MainWindow(engine, store, export)
    window.show()
    engine.start()
    code = app.exec()

    log.info("Shutting down")
    engine.stop()
    db.close()
    lock.unlock()
    restart = bool(app.property("restart_requested"))
    logging.shutdown()
    if restart:
        _relaunch()
    return code


def self_test() -> int:
    """Check that a packaged build is complete (used by the release workflow)."""
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .i18n import CATALOGS
    from .storage.db import Database
    from .storage.migrate import available_migrations, migrate
    from .ui.icons import app_icon_pixmap
    from .ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    assert available_migrations(), "database migrations are missing"
    assert CATALOGS["it"], "translations are missing"
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        version = migrate(db)
        db.close()
    assert not app_icon_pixmap(64).isNull()
    apply_theme(app, "dark")
    import keyring  # noqa: F401 - backends must be bundled

    if sys.stdout:
        print(f"{APP_NAME} {__version__}: self-test passed (schema {version})")
    return 0


def _relaunch() -> None:
    """Start a new instance with the same command line (after this one released its lock)."""
    import subprocess

    if getattr(sys, "frozen", False):
        command = [sys.executable, *sys.argv[1:]]
    else:
        command = [sys.executable, *getattr(sys, "orig_argv", [sys.executable, *sys.argv])[1:]]
    kwargs: dict[str, object] = {"close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)  # noqa: S603 - our own executable


def _set_windows_app_id() -> None:
    """Group the taskbar button and notifications under the application's own icon on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORGANIZATION}.{APP_ID}")
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


if __name__ == "__main__":
    raise SystemExit(main())

"""The application engine: the single entry point used by the UI.

It wires together the website client, recognition, the archive, the database
and the download manager. It has no dependency on Qt.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from ..archive.naming import FileInfo, plan_file_names, safe_component, with_counter
from ..archive.organizer import Organizer
from ..auth.session import SessionStore
from ..config.settings import Settings
from ..downloads.queue import DownloadManager
from ..downloads.retry import RetryPolicy
from ..monitor.discovery import GalleryStatus, PostKind, classify_post, fingerprint
from ..recognition.matcher import MatchAction, MatchDecision, WorkRef, match_work
from ..recognition.normalize import normalize_key
from ..recognition.title_parser import ParsedTitle, apply_file_name_hints, parse_title
from ..site.api import PawChiveApi
from ..site.errors import (
    AccessBlocked,
    AuthRequired,
    HostPaused,
    InvalidUrl,
    NetworkError,
    NotFound,
    PawChiveError,
    RateLimited,
    ServerError,
    SiteStructureChanged,
)
from ..site.http import HttpClient
from ..site.models import Creator, Post
from ..site.urls import PostUrl, parse_url, post_url, profile_url
from ..storage.db import Database, utcnow
from ..storage.repositories import Author, FileRecord, Gallery, Repositories, Work
from ..version import USER_AGENT
from .events import EventBus, EventType
from ..i18n import _

if TYPE_CHECKING:
    from ..monitor.scheduler import Scheduler

log = logging.getLogger(__name__)

# Days around a post in which other posts are used to infer a missing series.
CONTEXT_DAYS = 21


class EngineError(Exception):
    """User-facing error with a readable message."""


@dataclass
class AddAuthorResult:
    creator: Creator
    author: Author | None
    needs_confirmation: bool  # True when a post URL was pasted
    already_monitored: bool = False
    message: str = ""


@dataclass
class PostOutcome:
    new_gallery: bool = False
    changed: bool = False
    new_files: int = 0


class Engine:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        http: HttpClient,
        session: SessionStore | None = None,
        events: EventBus | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.db = db
        self.repos = Repositories(db)
        self.http = http
        self.api = PawChiveApi(http, settings.base_url)
        self.session = session
        self.events = events or EventBus()
        self.clock = clock
        self.organizer = Organizer()
        self._scan_lock = threading.Lock()
        self.downloads = DownloadManager(
            self.repos,
            http,
            self.events,
            finalize=self.finalize_file,
            on_host_problem=self._on_host_problem,
            policy=RetryPolicy(settings.retry_base_seconds, settings.retry_max_seconds, settings.max_download_attempts),
            max_concurrent=settings.max_concurrent_downloads,
            max_per_host=settings.max_downloads_per_host,
            unavailable_recheck=timedelta(hours=settings.unavailable_file_recheck_hours),
            max_unavailable_rechecks=settings.max_rechecks,
            clock=clock,
            speed_limit_bytes=settings.max_download_speed_kbps * 1024,
        )
        self.scheduler: "Scheduler | None" = None
        self._restore_state()

    # ------------------------------------------------------------ factory
    @classmethod
    def create(cls, settings: Settings, db: Database, session: SessionStore | None = None,
               events: EventBus | None = None) -> "Engine":
        http = HttpClient(
            settings.base_url,
            USER_AGENT,
            request_delay=settings.request_delay_seconds,
            timeout=settings.request_timeout_seconds,
            cookie_provider=session.cookie_header if session else None,
        )
        return cls(settings, db, http, session, events)

    def _restore_state(self) -> None:
        self._remap_temp_paths()
        restored = self.repos.queue.reset_active()
        if restored:
            log.info("Recovered %d interrupted downloads from the previous session", restored)
        now = self.clock()
        for host, (until, reason) in self.repos.hosts.active_pauses(now).items():
            self.http.pause_host(host, until.timestamp(), reason)
        for author in self.repos.authors.all():
            if author.status == "scanning":
                self.repos.authors.update(author.id, status="idle", full_scan_done=False)

    def _remap_temp_paths(self) -> None:
        """Temporary file locations are derived from the file hash, so they
        can always be recomputed. This keeps partial and held files usable
        after the Temp folder has been moved or reconfigured."""
        rows = self.db.query(
            "SELECT q.file_id, q.temp_path, f.sha256, f.extension FROM download_queue q JOIN files f ON f.id=q.file_id")
        changed = 0
        with self.db.transaction():
            for row in rows:
                expected = str(self.part_path(row["sha256"], row["extension"]))
                if row["temp_path"] != expected:
                    self.repos.queue.update(row["file_id"], temp_path=expected)
                    changed += 1
            for record in self.repos.files.by_status("held"):
                expected = str(self.settings.held_temp_path / f"{record.sha256}.{record.extension}")
                if record.held_path != expected:
                    self.repos.files.update(record.id, held_path=expected)
                    changed += 1
        if changed:
            log.info("Updated %d temporary file location(s) to the current Temp folder", changed)

    # ---------------------------------------------------------- lifecycle
    def start(self) -> None:
        from ..monitor.scheduler import Scheduler

        if self.settings.scan_on_startup:
            for author in self.repos.authors.all():
                if author.monitoring_enabled:
                    self.repos.authors.update(author.id, next_scan_at=self.clock())
        self.downloads.start()
        self.scheduler = Scheduler(self)
        self.scheduler.start()

    def stop(self) -> None:
        if self.scheduler:
            self.scheduler.stop()
        self.downloads.stop()
        self.http.close()

    # -------------------------------------------------------------- paths
    def author_dir(self, author: Author) -> Path:
        return self.settings.archive_path / author.archive_dir

    def work_dir(self, work: Work, author: Author | None = None) -> Path:
        author = author or self.repos.authors.get(work.author_id)
        assert author is not None
        return self.author_dir(author) / work.archive_dir

    def absolute(self, relative: str) -> Path:
        return self.settings.archive_path / Path(*PurePosixPath(relative).parts)

    def part_path(self, sha256: str, extension: str) -> Path:
        return self.settings.downloads_temp_path / f"{sha256}.{extension}.part"

    # ----------------------------------------------------- host problems
    def _on_host_problem(self, host: str, seconds: float, reason: str) -> None:
        if seconds < 0:  # blocked: use the configured pause
            seconds = self.settings.blocked_pause_minutes * 60
        until = time.time() + seconds
        self.http.pause_host(host, until, reason)
        self.repos.hosts.set_pause(host, datetime.fromtimestamp(until).astimezone(), reason)
        self.events.publish(EventType.HOST_PAUSED, host=host, seconds=seconds, reason=reason)

    def resume_all_hosts(self) -> None:
        for host in list(self.http.paused_hosts()):
            self.http.resume_host(host)
            self.repos.hosts.set_pause(host, None, None)
        self.downloads.wake()

    # ============================================================ authors
    def inspect_url(self, text: str) -> AddAuthorResult:
        """Resolve a pasted URL to its creator without adding anything."""
        try:
            parsed = parse_url(text, self.settings.base_url)
        except InvalidUrl as exc:
            raise EngineError(str(exc)) from exc
        try:
            creator = self.api.get_profile(parsed.service, parsed.creator_id)
        except NotFound as exc:
            raise EngineError(_("This author does not exist on PawChive (or was removed).")) from exc
        except PawChiveError as exc:
            raise EngineError(_('Could not contact PawChive: {0}', exc)) from exc
        existing = self.repos.authors.find(creator.service, creator.creator_id)
        return AddAuthorResult(
            creator=creator,
            author=existing,
            needs_confirmation=isinstance(parsed, PostUrl),
            already_monitored=existing is not None,
            message=(_("{0} is already monitored.", creator.name) if existing else ""),
        )

    def add_author(self, text: str, confirmed: bool = False) -> AddAuthorResult:
        """Add the author of a profile URL. For a post URL, the first call
        returns ``needs_confirmation``; call again with ``confirmed=True``."""
        result = self.inspect_url(text)
        if result.already_monitored:
            return result
        if result.needs_confirmation and not confirmed:
            result.message = _("This post belongs to {0}. Add this author to monitoring?", result.creator.name)
            return result
        author = self._register(result.creator)
        result.author = author
        result.needs_confirmation = False
        result.message = _("{0} added. A full scan will start shortly.", author.name)
        return result

    def _register(self, creator: Creator) -> Author:
        taken = self.repos.authors.archive_dirs()
        base = safe_component(creator.name, fallback=creator.creator_id)
        dir_name = base
        if dir_name.casefold() in taken or (self.settings.archive_path / dir_name).exists():
            dir_name = safe_component(f"{creator.name} [{creator.service}-{creator.creator_id}]")
        author = self.repos.authors.add(
            creator.service, creator.creator_id, creator.name, creator.public_id,
            profile_url(self.settings.base_url, creator.service, creator.creator_id), dir_name, self.clock(),
        )
        log.info("Author added: %s (%s/%s)", author.name, author.service, author.creator_id)
        self.events.publish(EventType.AUTHORS_CHANGED)
        if self.scheduler:
            self.scheduler.request_scan(author.id, full=True)
        return author

    def remove_author(self, author_id: int) -> None:
        """Stop monitoring and forget the author. Archived files are kept on disk."""
        author = self.repos.authors.get(author_id)
        if author is None:
            return
        for item in self.repos.queue.items_for_author(author_id):
            Path(item.temp_path).unlink(missing_ok=True)
        for record in self.repos.files.by_status("held"):
            gallery = self.repos.galleries.get(record.gallery_id)
            if gallery and gallery.author_id == author_id and record.held_path:
                Path(record.held_path).unlink(missing_ok=True)
        self.repos.authors.delete(author_id)
        log.info("Author removed from monitoring: %s (archive kept)", author.name)
        self.events.publish(EventType.AUTHORS_CHANGED)
        self.events.publish(EventType.QUEUE_CHANGED)

    def set_monitoring(self, author_id: int, enabled: bool) -> None:
        fields: dict[str, object] = {"monitoring_enabled": enabled, "status": "idle" if enabled else "paused"}
        if enabled:
            fields["next_scan_at"] = self.clock()
        self.repos.authors.update(author_id, **fields)
        self.events.publish(EventType.AUTHORS_CHANGED)
        if enabled and self.scheduler:
            self.scheduler.wake()

    def set_author_interval(self, author_id: int, minutes: int | None) -> None:
        from ..config.settings import MIN_MONITOR_INTERVAL_MINUTES

        value = None if minutes is None else max(MIN_MONITOR_INTERVAL_MINUTES, int(minutes))
        self.repos.authors.update(author_id, scan_interval_min=value)
        self.events.publish(EventType.AUTHORS_CHANGED)

    def request_scan(self, author_id: int, full: bool = False) -> None:
        if self.scheduler:
            self.scheduler.request_scan(author_id, full)
        else:
            self.scan_author(author_id, full=full, manual=True)

    def _interval(self, author: Author) -> timedelta:
        return timedelta(minutes=author.scan_interval_min or self.settings.monitor_interval_minutes)

    # =============================================================== scans
    def scan_author(self, author_id: int, full: bool | None = None, manual: bool = False) -> str:
        """Scan one author. Returns the result code (ok/blocked/error/…)."""
        with self._scan_lock:
            author = self.repos.authors.get(author_id)
            if author is None:
                return "missing"
            if not author.monitoring_enabled and not manual:
                return "skipped"
            return self._scan(author, full, manual)

    def _scan(self, author: Author, full: bool | None, manual: bool) -> str:
        now = self.clock()
        full_scan = bool(full) or not author.full_scan_done or (
            self.settings.full_rescan_days > 0 and author.last_full_scan_at is not None
            and now - author.last_full_scan_at > timedelta(days=self.settings.full_rescan_days)
        )
        log_id = self.repos.scans.start(author.id)
        self.repos.authors.update(author.id, status="scanning", status_message=None)
        self.events.publish(EventType.SCAN_STARTED, author_id=author.id, name=author.name, full=full_scan)
        log.info("Scan started: %s (%s)", author.name, "full" if full_scan else "incremental")
        pages = new_galleries = new_files = 0
        result, message = "ok", ""
        next_scan = now + self._interval(author)
        completed = False
        try:
            creator = self.api.get_profile(author.service, author.creator_id)
            if creator.name != author.name:
                self.repos.authors.update(author.id, name=creator.name)
            if not full_scan and creator.updated and creator.updated == author.remote_updated:
                message = _("no changes since the last scan")
                completed = True
            else:
                # 1. Collect new or changed posts (the API lists newest first).
                pending: list[Post] = []
                for page in self.api.iter_post_pages(author.service, author.creator_id):
                    pages += 1
                    reached_known = False
                    for post in page:
                        if self._is_unchanged(author, post):
                            reached_known = True
                        else:
                            pending.append(post)
                    # Once a page contains an already known, unchanged post,
                    # older pages are known as well. Edits of old posts are
                    # caught by the periodic full scan.
                    if not full_scan and reached_known:
                        break
                # 2. Process them oldest first, so that the title an author has
                #    used for a long time defines the work - not a recent typo.
                for post in sorted(pending, key=self._chronological_key):
                    outcome = self.process_post(author, post)
                    new_galleries += int(outcome.new_gallery)
                    new_files += outcome.new_files
                completed = True
                message = _("{0} page(s), {1} new galleries, {2} new files", pages, new_galleries, new_files)
            self.repos.authors.update(author.id, remote_updated=creator.updated)
        except (HostPaused, RateLimited, AccessBlocked) as exc:
            result, message = "blocked", str(exc)
            if isinstance(exc, RateLimited):
                wait = exc.retry_after or 120
                self._on_host_problem(exc.host, wait, "rate limited (HTTP 429)")
            elif isinstance(exc, AccessBlocked):
                self._on_host_problem(exc.host, -1, str(exc))
            pause = self.http.paused_hosts().get(urlsplit(self.settings.base_url).hostname or "")
            if pause:
                next_scan = datetime.fromtimestamp(pause[0]).astimezone() + timedelta(seconds=5)
        except AuthRequired:
            result, message = "auth", _("PawChive asked for authentication. Configure session cookies in Settings.")
            if self.session:
                self.session.expired = True
            self.events.publish(EventType.AUTH_PROBLEM, message=message, author_id=author.id)
        except NotFound:
            result, message = "not_found", _("The author no longer exists on PawChive.")
        except SiteStructureChanged as exc:
            result, message = "error", _("PawChive's data format changed: {0}", exc)
            self.events.publish(EventType.SITE_STRUCTURE_CHANGED, message=str(exc))
        except (NetworkError, ServerError) as exc:
            result, message = "error", _("Network problem: {0}", exc)
            next_scan = now + timedelta(minutes=15)
            self.events.publish(EventType.NETWORK_ERROR, message=str(exc))
        except PawChiveError as exc:
            result, message = "error", str(exc)
        except Exception as exc:  # unexpected bug: report, keep the app alive
            log.exception("Unexpected error while scanning %s", author.name)
            result, message = "error", _("Unexpected error: {0}", exc)
        finally:
            finished = self.clock()
            status = {"ok": "idle", "blocked": "blocked", "not_found": "not_found"}.get(result, "error")
            current = self.repos.authors.get(author.id)
            if current is not None and not current.monitoring_enabled:
                status = "paused"
            summary = {"result": result, "message": message, "pages": pages,
                       "new_galleries": new_galleries, "new_files": new_files, "full": full_scan}
            fields: dict[str, object] = {
                "status": status, "status_message": message if result != "ok" else None,
                "last_scan_at": finished, "next_scan_at": next_scan, "last_scan_summary": summary,
            }
            if result == "ok":
                fields["last_success_at"] = finished
                if completed and full_scan:
                    fields["full_scan_done"] = True
                    fields["last_full_scan_at"] = finished
            else:
                # An interrupted scan may have skipped posts: do a full pass next time.
                fields["full_scan_done"] = False
            if current is not None:
                self.repos.authors.update(author.id, **fields)
                self.repos.scans.finish(log_id, result, pages, new_galleries, new_files, message)
            log.info("Scan finished: %s -> %s (%s)", author.name, result, message)
            self.events.publish(EventType.SCAN_FINISHED, author_id=author.id, name=author.name, result=result,
                                message=message, new_galleries=new_galleries, new_files=new_files)
            self.events.publish(EventType.AUTHORS_CHANGED)
            self.downloads.wake()
        return result

    def _is_unchanged(self, author: Author, post: Post) -> bool:
        gallery = self.repos.galleries.find(author.id, post.post_id)
        if gallery is None:
            return False
        if gallery.fingerprint == fingerprint(post):
            self.repos.galleries.update(gallery.id, last_checked_at=self.clock())
            return True
        return False

    @staticmethod
    def _chronological_key(post: Post) -> tuple[float, int, str]:
        stamp = post.published.timestamp() if post.published else float("inf")
        numeric = int(post.post_id) if post.post_id.isdigit() else 0
        return (stamp, numeric, post.post_id)

    def recheck_gallery(self, gallery: Gallery) -> None:
        """Re-fetch one post that was empty, previews-only or had unavailable files."""
        author = self.repos.authors.get(gallery.author_id)
        if author is None:
            return
        now = self.clock()
        try:
            post = self.api.get_post(author.service, author.creator_id, gallery.post_id)
        except NotFound:
            self.repos.galleries.update(gallery.id, status=GalleryStatus.REMOVED.value, next_recheck_at=None,
                                        status_message="removed from PawChive")
            return
        except (HostPaused, RateLimited, AccessBlocked, NetworkError, ServerError) as exc:
            self.repos.galleries.update(gallery.id, next_recheck_at=now + timedelta(hours=1))
            log.info("Recheck of gallery %s postponed: %s", gallery.post_id, exc)
            if isinstance(exc, RateLimited):
                self._on_host_problem(exc.host, exc.retry_after or 120, "rate limited (HTTP 429)")
            return
        except PawChiveError as exc:
            self.repos.galleries.update(gallery.id, next_recheck_at=now + timedelta(hours=6), status_message=str(exc))
            return
        outcome = self.process_post(author, post)
        refreshed = self.repos.galleries.get(gallery.id)
        if refreshed and not outcome.changed and refreshed.status in (GalleryStatus.EMPTY.value, GalleryStatus.AWAITING_FULL.value):
            count = refreshed.recheck_count + 1
            base = (self.settings.empty_gallery_recheck_hours if refreshed.status == GalleryStatus.EMPTY.value
                    else self.settings.previews_only_recheck_hours)
            next_at = None if count >= self.settings.max_rechecks else now + timedelta(hours=base * min(8, 2 ** (count - 1)))
            self.repos.galleries.update(gallery.id, recheck_count=count, next_recheck_at=next_at, last_checked_at=now)

    # ======================================================== post handling
    def process_post(self, author: Author, post: Post) -> PostOutcome:
        now = self.clock()
        fp = fingerprint(post)
        gallery = self.repos.galleries.find(author.id, post.post_id)
        if gallery is not None and gallery.fingerprint == fp:
            self.repos.galleries.update(gallery.id, last_checked_at=now)
            return PostOutcome()
        if gallery is not None and gallery.status == GalleryStatus.IGNORED.value:
            self.repos.galleries.update(gallery.id, fingerprint=fp, last_checked_at=now)
            return PostOutcome()

        outcome = PostOutcome(new_gallery=gallery is None, changed=gallery is not None)
        parsed = parse_title(post.title)
        apply_file_name_hints(parsed, [f.name for f in post.files if f.kind == "image"])
        base_fields: dict[str, object] = {
            "url": post_url(self.settings.base_url, author.service, author.creator_id, post.post_id),
            "title": post.title,
            "normalized_title": normalize_key(post.title),
            "parsed_title": parsed.to_dict(),
            "published_at": post.published,
            "edited_at": post.edited,
            "has_full": post.has_full,
            "file_count": len(post.files),
            "fingerprint": fp,
            "last_checked_at": now,
        }
        kind = classify_post(post)

        if kind is PostKind.UNREADABLE:
            gallery = self.repos.galleries.upsert(
                author.id, post.post_id, **base_fields, status=GalleryStatus.ERROR.value,
                status_message="; ".join(post.skipped_paths)[:500], next_recheck_at=now + timedelta(hours=24),
            )
            self.events.publish(EventType.SITE_STRUCTURE_CHANGED, message=f"post {post.post_id}: files not understood")
            return outcome

        if kind is PostKind.EMPTY:
            if gallery is None or gallery.status != GalleryStatus.EMPTY.value:
                self.repos.galleries.upsert(
                    author.id, post.post_id, **base_fields, status=GalleryStatus.EMPTY.value,
                    next_recheck_at=now + timedelta(hours=self.settings.empty_gallery_recheck_hours),
                    recheck_count=0,
                )
            else:
                self.repos.galleries.update(gallery.id, fingerprint=fp, last_checked_at=now)
            log.info("Empty gallery skipped: %s", post.title)
            self.events.publish(EventType.GALLERY_EMPTY, author_id=author.id, title=post.title)
            return outcome

        if kind is PostKind.PREVIEWS_ONLY:
            if gallery is None or gallery.status != GalleryStatus.AWAITING_FULL.value:
                self.repos.galleries.upsert(
                    author.id, post.post_id, **base_fields, status=GalleryStatus.AWAITING_FULL.value,
                    status_message="only previews are on the server; originals not imported yet",
                    next_recheck_at=now + timedelta(hours=self.settings.previews_only_recheck_hours),
                    recheck_count=0,
                )
            else:
                self.repos.galleries.update(gallery.id, fingerprint=fp, last_checked_at=now)
            log.info("Gallery has previews only, will recheck: %s", post.title)
            self.events.publish(EventType.GALLERY_PREVIEWS_ONLY, author_id=author.id, title=post.title)
            return outcome

        # ---- gallery with original files ------------------------------------
        with self.db.transaction():
            work: Work | None = None
            decision: MatchDecision | None = None
            if gallery is not None and gallery.work_id is not None:
                work = self.repos.works.get(gallery.work_id)
            open_review = False
            if work is None:
                decision = self._decide(author, parsed, post.published)
                if decision.action is MatchAction.EXISTING and decision.work_id is not None:
                    work = self.repos.works.get(decision.work_id)
                elif decision.action is MatchAction.CREATE:
                    work = self._create_work(author, parsed, decision.confidence, confirmed=False)
                else:
                    open_review = True

            gallery = self.repos.galleries.upsert(
                author.id, post.post_id, **base_fields,
                status=(GalleryStatus.AWAITING_REVIEW if open_review else GalleryStatus.QUEUED).value,
                status_message=None, work_id=work.id if work else None, next_recheck_at=None,
            )
            if open_review and decision is not None:
                self.repos.reviews.open(
                    gallery.id, decision.work_key, decision.display_title,
                    [{"work_id": c.work_id, "title": c.display_title, "score": c.score, "reason": c.reason}
                     for c in decision.candidates],
                    decision.reason,
                )
            outcome.new_files = self._add_files(gallery, post, parsed, work)
            self._refresh_gallery_status(gallery.id)

        if outcome.new_gallery:
            self.events.publish(EventType.GALLERY_DISCOVERED, author_id=author.id, title=post.title,
                                files=len(post.files))
        if work is not None and decision is not None:
            self.events.publish(EventType.WORK_RECOGNIZED, author_id=author.id, work_id=work.id,
                                title=work.display_title, action=decision.action.value)
        if open_review:
            log.info("Review needed for '%s': %s", post.title, decision.reason if decision else "")
            self.events.publish(EventType.REVIEW_NEEDED, author_id=author.id, title=post.title)
        if outcome.new_files:
            self.events.publish(EventType.FILE_QUEUED, count=outcome.new_files)
            self.downloads.wake()
        return outcome

    def _decide(self, author: Author, parsed: ParsedTitle, published: datetime | None = None,
                pool: list[tuple[datetime | None, ParsedTitle]] | None = None) -> MatchDecision:
        self._apply_context(author.id, parsed, published, pool, self.series_aliases(author.id))
        works = [WorkRef(w.id, w.work_key, w.display_title) for w in self.repos.works.for_author(author.id)]
        return match_work(
            parsed, works, self.repos.works.aliases(author.id),
            self.settings.auto_create_min_confidence, self.settings.similarity_review_threshold,
        )

    # ------------------------------------------------- series aliases & context
    def series_aliases(self, author_id: int) -> dict[str, str]:
        """Confirmed spellings: series key -> canonical series name (e.g. a typo)."""
        import json

        raw = self.repos.state.get(f"series_aliases:{author_id}")
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def set_series_aliases(self, author_id: int, mapping: dict[str, str]) -> None:
        import json

        current = self.series_aliases(author_id)
        current.update({k: v for k, v in mapping.items() if k})
        self.repos.state.set(f"series_aliases:{author_id}", json.dumps(current, ensure_ascii=False))

    def _context_pool(self, author_id: int, published: datetime | None) -> list[tuple[datetime | None, ParsedTitle]]:
        if published is None:
            return []
        window = timedelta(days=CONTEXT_DAYS)
        rows = self.db.query(
            "SELECT title, published_at FROM galleries WHERE author_id=? AND published_at BETWEEN ? AND ?",
            (author_id, (published - window).isoformat(timespec="seconds"),
             (published + window).isoformat(timespec="seconds")),
        )
        from ..storage.db import from_db_time

        return [(from_db_time(r["published_at"]), parse_title(r["title"])) for r in rows]

    def _apply_context(self, author_id: int, parsed: ParsedTitle, published: datetime | None,
                       pool: list[tuple[datetime | None, ParsedTitle]] | None, aliases: dict[str, str]) -> None:
        """Use confirmed spellings, and infer a missing series from nearby posts.

        "Page 72 Sketch" with no series name belongs to the series that has a
        page 72 published within a few days - if exactly one series does.
        """
        if parsed.series and parsed.series_key in aliases:
            parsed.series = aliases[parsed.series_key]
        if parsed.series or parsed.page is None or published is None:
            return
        pages = set(range(parsed.page, (parsed.page_end or parsed.page) + 1))
        candidates: dict[tuple[str, tuple[tuple[str, int], ...]], str] = {}
        for other_time, other in (pool if pool is not None else self._context_pool(author_id, published)):
            if not other.series or other.page is None or other_time is None:
                continue
            if abs((other_time - published).total_seconds()) > CONTEXT_DAYS * 86400:
                continue
            other_pages = set(range(other.page, (other.page_end or other.page) + 1))
            if pages & other_pages:
                series_name = aliases.get(other.series_key, other.series)
                key = (normalize_key(series_name), tuple(sorted(other.groups.items())))
                candidates.setdefault(key, series_name)
        if len(candidates) == 1:
            (series_key, groups), name = next(iter(candidates.items()))
            parsed.series = name
            for kind, value in groups:
                if getattr(parsed, kind) is None:
                    setattr(parsed, kind, value)
            parsed.warnings.append("series inferred from publications of the same days")
            parsed.confidence = max(parsed.confidence, 0.8)

    def _unique_work_dir(self, author_id: int, title: str, exclude_work: int | None = None) -> str:
        taken = self.repos.works.archive_dirs(author_id)
        if exclude_work is not None:
            current = self.repos.works.get(exclude_work)
            if current:
                taken.discard(current.archive_dir.casefold())
        base = safe_component(title)
        name, counter = base, 2
        while name.casefold() in taken:
            name = f"{base} ({counter})"
            counter += 1
        return name

    def _create_work(self, author: Author, parsed: ParsedTitle, confidence: float, confirmed: bool,
                     title_override: str | None = None) -> Work:
        if title_override:
            override = parse_title(title_override)
            if override.series_key:
                parsed = override
            display = title_override.strip()
        else:
            display = parsed.display_title()
        key = parsed.work_key() if parsed.series_key else normalize_key(display)
        existing = self.repos.works.by_key(author.id, key)
        if existing:
            return existing
        work = self.repos.works.add(
            author.id, display, key, parsed.groups, parsed.series,
            self._unique_work_dir(author.id, display), confidence, confirmed,
        )
        log.info("New work recognized: %s / %s", author.name, work.display_title)
        self.events.publish(EventType.WORKS_CHANGED, author_id=author.id)
        return work

    def _add_files(self, gallery: Gallery, post: Post, parsed: ParsedTitle, work: Work | None) -> int:
        now = self.clock()
        known = {f.sha256 for f in self.repos.files.for_gallery(gallery.id)}
        plans = {p.position: p for p in plan_file_names(
            [FileInfo(f.position, f.name, f.extension, f.kind) for f in post.files],
            parsed.page, parsed.page_end, post.published,
        )}
        taken = self.repos.files.taken_names(work.id) if work else set()
        added = 0
        for remote in post.files:
            if remote.sha256 in known:
                continue
            plan = plans[remote.position]
            name = plan.file_name
            counter = 2
            while name.casefold() in taken:
                name = with_counter(plan.file_name, counter)
                counter += 1
            taken.add(name.casefold())
            duplicate = self.repos.files.active_with_hash(remote.sha256)
            fields = dict(
                gallery_id=gallery.id, work_id=work.id if work else None, sha256=remote.sha256,
                original_name=remote.name, extension=remote.extension, kind=remote.kind, server=remote.server,
                remote_path=remote.path, source_url=remote.url, position=remote.position,
                page_number=plan.page_number, target_name=name,
            )
            if duplicate is not None:
                self.repos.files.add(**fields, status="duplicate", duplicate_of=duplicate.id,
                                     local_path=duplicate.local_path)
                log.info("Duplicate file skipped (%s already archived or queued)", remote.name)
                continue
            record = self.repos.files.add(**fields, status="queued")
            self.repos.queue.add(record.id, str(self.part_path(remote.sha256, remote.extension)),
                                 urlsplit(remote.server).hostname or "", now)
            added += 1
        return added

    def _refresh_gallery_status(self, gallery_id: int) -> None:
        gallery = self.repos.galleries.get(gallery_id)
        if gallery is None or gallery.status in (GalleryStatus.IGNORED.value, GalleryStatus.REMOVED.value):
            return
        statuses = [f.status for f in self.repos.files.for_gallery(gallery_id)]
        if not statuses:
            return
        if gallery.work_id is None:
            status = GalleryStatus.AWAITING_REVIEW
        elif any(s in ("queued", "downloading", "pending", "held") for s in statuses):
            status = GalleryStatus.QUEUED
        elif any(s in ("failed", "unavailable") for s in statuses):
            status = GalleryStatus.PARTIAL
        else:
            status = GalleryStatus.COMPLETE
        if status.value != gallery.status:
            self.repos.galleries.update(gallery_id, status=status.value)

    # ========================================================== finalization
    def finalize_file(self, record: FileRecord, part: Path) -> None:
        """Called by the download manager after a verified download."""
        current = self.repos.files.get(record.id) or record
        if current.work_id is None:
            self.settings.held_temp_path.mkdir(parents=True, exist_ok=True)
            held = self.settings.held_temp_path / f"{current.sha256}.{current.extension}"
            os.replace(part, held)
            self.repos.files.update(current.id, status="held", held_path=str(held), size_bytes=held.stat().st_size)
            self._refresh_gallery_status(current.gallery_id)
            return
        self._place(current, part, fresh=True)

    def _place(self, record: FileRecord, source: Path, fresh: bool = False) -> None:
        """Move a verified file into its work folder. *fresh*: it was just downloaded
        (used for "new pages" notifications; reorganizing the archive is not news)."""
        work = self.repos.works.get(record.work_id)  # type: ignore[arg-type]
        if work is None:
            raise EngineError(_("work disappeared"))
        directory = self.work_dir(work)
        size = source.stat().st_size
        placed = self.organizer.place(source, directory, record.target_name, record.sha256)
        relative = placed.path.relative_to(self.settings.archive_path).as_posix()
        self.repos.files.update(record.id, status="complete", local_path=relative, held_path=None,
                                size_bytes=size, completed_at=self.clock())
        self._refresh_gallery_status(record.gallery_id)
        log.info("Archived %s", relative)
        self.events.publish(EventType.FILE_COMPLETED, file_id=record.id, path=relative, work_id=work.id,
                            work_title=work.display_title, author_id=work.author_id, page=record.page_number,
                            kind=record.kind, fresh=fresh)

    def _place_held_files(self, gallery_id: int) -> None:
        for record in self.repos.files.for_gallery(gallery_id):
            if record.status == "held" and record.held_path and record.work_id is not None:
                path = Path(record.held_path)
                if path.exists():
                    self._place(record, path)
                else:  # lost held file: download again
                    self.repos.files.update(record.id, status="queued", held_path=None)
                    self.repos.queue.add(record.id, str(self.part_path(record.sha256, record.extension)),
                                         urlsplit(record.server).hostname or "", self.clock())
        self.downloads.wake()

    # =============================================================== reviews
    def resolve_review(self, review_id: int, work_id: int | None = None, new_title: str | None = None) -> Work:
        """Assign the gallery of a review request to a work (existing or new)
        and remember the decision for future publications."""
        review = self.repos.reviews.get(review_id)
        if review is None:
            raise EngineError(_("This review request no longer exists."))
        gallery = self.repos.galleries.get(review.gallery_id)
        if gallery is None:
            raise EngineError(_("The gallery no longer exists."))
        author = self.repos.authors.get(gallery.author_id)
        assert author is not None
        with self.db.transaction():
            if work_id is not None:
                work = self.repos.works.get(work_id)
                if work is None or work.author_id != author.id:
                    raise EngineError(_("Choose a work of the same author."))
                self.repos.works.update(work.id, user_confirmed=True)
            else:
                parsed = parse_title(gallery.title)
                work = self._create_work(author, parsed, 1.0, confirmed=True,
                                         title_override=new_title or review.proposed_title)
            self.repos.works.set_alias(author.id, review.proposed_key, work.id, "user")
            to_resolve = [review] + [
                r for r in self.repos.reviews.open_requests()
                if r.id != review.id and r.proposed_key == review.proposed_key
                and (g := self.repos.galleries.get(r.gallery_id)) is not None and g.author_id == author.id
            ]
            for item in to_resolve:
                self._assign_gallery_files(item.gallery_id, work)
                self.repos.reviews.resolve(item.id)
        for item in to_resolve:
            self._place_held_files(item.gallery_id)
            self._refresh_gallery_status(item.gallery_id)
        self.events.publish(EventType.REVIEW_RESOLVED, review_id=review_id, work_id=work.id, count=len(to_resolve))
        self.events.publish(EventType.WORKS_CHANGED, author_id=author.id)
        return work

    def _assign_gallery_files(self, gallery_id: int, work: Work) -> None:
        taken = self.repos.files.taken_names(work.id)
        self.repos.galleries.update(gallery_id, work_id=work.id, status=GalleryStatus.QUEUED.value)
        for record in self.repos.files.for_gallery(gallery_id):
            name = record.target_name
            counter = 2
            while name.casefold() in taken:
                name = with_counter(record.target_name, counter)
                counter += 1
            taken.add(name.casefold())
            self.repos.files.update(record.id, work_id=work.id, target_name=name)

    def resolve_reviews(self, review_ids: list[int], work_id: int | None = None,
                        new_title: str | None = None) -> tuple[Work | None, int]:
        """Resolve several review requests at once (all of the same author).

        With *new_title* the work is created by the first request and the
        others are added to it. Returns the work and the number resolved.
        """
        reviews = [r for r in (self.repos.reviews.get(i) for i in review_ids) if r and r.status == "open"]
        authors = {g.author_id for r in reviews if (g := self.repos.galleries.get(r.gallery_id))}
        if len(authors) > 1:
            raise EngineError(_("Select publications of a single author."))
        work: Work | None = None
        resolved = 0
        for review in reviews:
            current = self.repos.reviews.get(review.id)
            if current is None or current.status != "open":
                resolved += 1  # already resolved together with an earlier one (same title key)
                continue
            if work is None:
                work = self.resolve_review(review.id, work_id=work_id, new_title=new_title)
            else:
                self.resolve_review(review.id, work_id=work.id)
            resolved += 1
        return work, resolved

    def dismiss_reviews(self, review_ids: list[int]) -> int:
        for review_id in review_ids:
            self.dismiss_review(review_id)
        return len(review_ids)

    def dismiss_review(self, review_id: int) -> None:
        """Ignore the gallery entirely (nothing is archived)."""
        review = self.repos.reviews.get(review_id)
        if review is None:
            return
        for record in self.repos.files.for_gallery(review.gallery_id):
            item = self.repos.queue.get(record.id)
            if item:
                Path(item.temp_path).unlink(missing_ok=True)
                self.repos.queue.remove(record.id)
            if record.held_path:
                Path(record.held_path).unlink(missing_ok=True)
            self.repos.files.update(record.id, status="skipped", held_path=None)
        self.repos.galleries.update(review.gallery_id, status=GalleryStatus.IGNORED.value)
        self.repos.reviews.resolve(review_id)
        self.events.publish(EventType.REVIEW_RESOLVED, review_id=review_id, work_id=None, count=1)
        self.events.publish(EventType.QUEUE_CHANGED)

    # ======================================================= work management
    def rename_work(self, work_id: int, new_name: str) -> Work:
        work = self.repos.works.get(work_id)
        if work is None:
            raise EngineError(_("Work not found."))
        author = self.repos.authors.get(work.author_id)
        assert author is not None
        new_dir = self._unique_work_dir(author.id, new_name, exclude_work=work.id)
        if new_dir == work.archive_dir:
            self.repos.works.update(work.id, display_title=new_name.strip() or work.display_title)
            return self.repos.works.get(work.id)  # type: ignore[return-value]
        old_path = self.work_dir(work, author)
        new_path = self.author_dir(author) / new_dir
        if new_path.exists() and old_path.exists() and old_path.resolve() != new_path.resolve():
            raise EngineError(_("A folder named '{0}' already exists.", new_dir))
        with self.db.transaction():
            if old_path.exists():
                old_path.rename(new_path)
            self.repos.works.update(work.id, archive_dir=new_dir, display_title=new_name.strip(), user_confirmed=True)
            for record in self.repos.files.for_work(work.id):
                if record.local_path:
                    rel = PurePosixPath(record.local_path)
                    new_rel = PurePosixPath(author.archive_dir, new_dir, rel.name).as_posix()
                    self.repos.files.update(record.id, local_path=new_rel)
        log.info("Work renamed: %s -> %s", work.archive_dir, new_dir)
        self.events.publish(EventType.WORKS_CHANGED, author_id=author.id)
        return self.repos.works.get(work.id)  # type: ignore[return-value]

    def _planned_name(self, record: FileRecord) -> str:
        """The clean name a file would get from its publication's title
        (undoes " (2)" suffixes added while it shared a folder with others)."""
        gallery = self.repos.galleries.get(record.gallery_id)
        if gallery is None:
            return record.target_name
        parsed = parse_title(gallery.title)
        siblings = self.repos.files.for_gallery(gallery.id)
        plans = plan_file_names([FileInfo(f.position, f.original_name, f.extension, f.kind) for f in siblings],
                                parsed.page, parsed.page_end, gallery.published_at)
        for plan in plans:
            if plan.position == record.position:
                return plan.file_name
        return record.target_name

    def _move_file_to_work(self, record: FileRecord, target: Work) -> None:
        taken = self.repos.files.taken_names(target.id)
        base = self._planned_name(record)
        name = base
        counter = 2
        while name.casefold() in taken:
            name = with_counter(base, counter)
            counter += 1
        fields: dict[str, object] = {"work_id": target.id, "target_name": name}
        if record.status == "complete" and record.local_path:
            current = self.absolute(record.local_path)
            if current.exists():
                new_path = self.organizer.move_within_archive(current, self.work_dir(target), name)
                fields["local_path"] = new_path.relative_to(self.settings.archive_path).as_posix()
                fields["target_name"] = new_path.name
        self.repos.files.update(record.id, **fields)

    def merge_works(self, source_id: int, target_id: int) -> Work:
        """Move everything from *source* into *target* (user-confirmed)."""
        if source_id == target_id:
            raise EngineError(_("Choose two different works."))
        source, target = self.repos.works.get(source_id), self.repos.works.get(target_id)
        if source is None or target is None or source.author_id != target.author_id:
            raise EngineError(_("Both works must belong to the same author."))
        source_dir = self.work_dir(source)
        with self.db.transaction():
            for record in self.repos.files.for_work(source.id):
                self._move_file_to_work(record, target)
            self.db.execute("UPDATE galleries SET work_id=? WHERE work_id=?", (target.id, source.id))
            self.repos.works.move_aliases(source.id, target.id)
            self.repos.works.set_alias(source.author_id, source.work_key, target.id, "merge")
            self.repos.works.delete(source.id)
            self.repos.works.update(target.id, user_confirmed=True)
        Organizer.remove_empty_dirs(source_dir, self.settings.archive_path)
        log.info("Merged work '%s' into '%s'", source.display_title, target.display_title)
        self.events.publish(EventType.WORKS_CHANGED, author_id=target.author_id)
        return self.repos.works.get(target.id)  # type: ignore[return-value]

    def reassign_gallery(self, gallery_id: int, target_work_id: int | None = None, new_title: str | None = None,
                         remember: bool = False) -> Work:
        """Move one gallery's files to another (or a new) work."""
        gallery = self.repos.galleries.get(gallery_id)
        if gallery is None:
            raise EngineError(_("Gallery not found."))
        author = self.repos.authors.get(gallery.author_id)
        assert author is not None
        old_work = self.repos.works.get(gallery.work_id) if gallery.work_id else None
        with self.db.transaction():
            if target_work_id is not None:
                target = self.repos.works.get(target_work_id)
                if target is None or target.author_id != author.id:
                    raise EngineError(_("Choose a work of the same author."))
            else:
                if not new_title:
                    raise EngineError(_("Enter a title for the new work."))
                target = self._create_work(author, parse_title(new_title), 1.0, True, title_override=new_title)
            if gallery.work_id == target.id:
                return target  # already there: nothing to move
            for record in self.repos.files.for_gallery(gallery.id):
                self._move_file_to_work(record, target)
            self.repos.galleries.update(gallery.id, work_id=target.id)
            if remember:
                parsed = parse_title(gallery.title)
                self.repos.works.set_alias(author.id, parsed.work_key(), target.id, "user")
        if old_work is not None:
            Organizer.remove_empty_dirs(self.work_dir(old_work, author), self.settings.archive_path)
            if not self.repos.files.for_work(old_work.id) and not self.repos.galleries.for_work(old_work.id):
                self.repos.works.delete(old_work.id)
        self._place_held_files(gallery.id)
        self._refresh_gallery_status(gallery.id)
        self.events.publish(EventType.WORKS_CHANGED, author_id=author.id)
        return target

    # ======================================================= variant repair
    def find_variant_mixes(self, author_id: int | None = None) -> list[tuple[Work, list[Gallery]]]:
        """Works that contain both finished pages and sketch/WIP publications.

        Archives created by earlier versions filed sketches together with the
        finished pages. Returns each such work with the galleries that the
        current recognizer would file as a separate "Sketches" work.
        """
        from ..recognition.title_parser import SKETCH_VARIANT

        authors = [self.repos.authors.get(author_id)] if author_id else self.repos.authors.all()
        found: list[tuple[Work, list[Gallery]]] = []
        for author in authors:
            if author is None:
                continue
            for work in self.repos.works.for_author(author.id):
                if "|variant:" in work.work_key:
                    continue
                galleries = self.repos.galleries.for_work(work.id)
                sketches = [g for g in galleries if self._parse_gallery(g).variant == SKETCH_VARIANT]
                if sketches:
                    found.append((work, sketches))
        return found

    def split_sketches(self, work_id: int, gallery_ids: list[int]) -> Work | None:
        """Move the given galleries of *work_id* into "<work> - Sketches"."""
        from ..recognition.title_parser import SKETCH_VARIANT

        work = self.repos.works.get(work_id)
        if work is None or not gallery_ids:
            return None
        author = self.repos.authors.get(work.author_id)
        assert author is not None
        key = f"{work.work_key}|variant:{SKETCH_VARIANT}"
        with self.db.transaction():
            target = self.repos.works.by_key(author.id, key)
            if target is None:
                title = f"{work.display_title} - {SKETCH_VARIANT.capitalize()}"
                groups = {k: getattr(work, k) for k in ("volume", "part", "chapter", "issue", "episode")
                          if getattr(work, k) is not None}
                target = self.repos.works.add(author.id, title, key, groups, work.series_name,
                                              self._unique_work_dir(author.id, title), 1.0, True)
            for gallery_id in gallery_ids:
                gallery = self.repos.galleries.get(gallery_id)
                if gallery is None or gallery.work_id != work.id:
                    continue
                for record in self.repos.files.for_gallery(gallery.id):
                    self._move_file_to_work(record, target)
                self.repos.galleries.update(gallery.id, work_id=target.id)
        Organizer.remove_empty_dirs(self.work_dir(work, author), self.settings.archive_path)
        log.info("Moved %d sketch publication(s) from '%s' to '%s'", len(gallery_ids), work.display_title,
                 target.display_title)
        self.events.publish(EventType.WORKS_CHANGED, author_id=author.id)
        return target

    def reassign_galleries(self, gallery_ids: list[int], target_work_id: int | None = None,
                           new_title: str | None = None, remember: bool = False) -> Work | None:
        """Move several galleries (same author) to one work."""
        target: Work | None = None
        for gallery_id in gallery_ids:
            if target is None:
                target = self.reassign_gallery(gallery_id, target_work_id, new_title, remember)
            else:
                self.reassign_gallery(gallery_id, target.id, None, remember)
        return target

    # ======================================================= archive rebuild
    def _rebuild_candidates(self, author_id: int) -> list[Gallery]:
        skip = {GalleryStatus.EMPTY.value, GalleryStatus.AWAITING_FULL.value, GalleryStatus.IGNORED.value,
                GalleryStatus.REMOVED.value, GalleryStatus.ERROR.value}
        galleries = [g for g in self.repos.galleries.for_author(author_id) if g.status not in skip]
        galleries.sort(key=lambda g: (g.published_at.timestamp() if g.published_at else float("inf"),
                                      int(g.post_id) if g.post_id.isdigit() else 0))
        return galleries

    def _rebuild_pool(self, galleries: list[Gallery]) -> list[tuple[datetime | None, ParsedTitle]]:
        return [(g.published_at, self._parse_gallery(g)) for g in galleries]

    def preview_rebuild(self, author_id: int, series_map: dict[str, str] | None = None) -> dict[str, object]:
        """Simulate a rebuild. Changes nothing.

        Returns the works that would exist (title, files), the publications
        that would need review, and pairs of *similar series names* that the
        user should confirm as the same artwork or not (typos)."""
        aliases = {**self.series_aliases(author_id), **(series_map or {})}
        galleries = self._rebuild_candidates(author_id)
        pool = self._rebuild_pool(galleries)
        refs: list[WorkRef] = []
        titles: dict[int, str] = {}
        counts: dict[int, int] = {}
        review: list[str] = []
        similar: dict[tuple[str, str], dict[str, object]] = {}
        next_id = -1
        for gallery in galleries:
            parsed = self._parse_gallery(gallery)
            self._apply_context(author_id, parsed, gallery.published_at, pool, aliases)
            decision = match_work(parsed, refs, {}, self.settings.auto_create_min_confidence,
                                  self.settings.similarity_review_threshold)
            files = [f for f in self.repos.files.for_gallery(gallery.id) if f.status != "skipped"]
            unique = sum(f.status != "duplicate" for f in files)
            if decision.action is MatchAction.EXISTING and decision.work_id is not None:
                counts[decision.work_id] += unique
                continue
            if decision.action is MatchAction.CREATE:
                refs.append(WorkRef(next_id, decision.work_key, decision.display_title))
                titles[next_id] = decision.display_title
                counts[next_id] = unique
                next_id -= 1
                continue
            review.append(gallery.title)
            # A similar *series name* (typo) blocks everything behind it: report it.
            for cand in decision.candidates:
                ref = next((r for r in refs if r.work_id == cand.work_id), None)
                if ref and parsed.series_key and ref.series_key != parsed.series_key and cand.score >= 0.6:
                    pair = (parsed.series_key, ref.series_key)
                    other_name = next((p.series for _gallery, p in pool if p.series_key == ref.series_key and p.series),
                                      ref.display_title)
                    entry = similar.setdefault(pair, {
                        "key": parsed.series_key, "name": parsed.series,
                        "other_key": ref.series_key, "other_name": other_name, "count": 0})
                    entry["count"] = int(entry["count"]) + 1  # type: ignore[arg-type]
                    break
        key_counts: dict[str, int] = {}
        for _gallery, parsed in pool:
            if parsed.series_key:
                key_counts[parsed.series_key] = key_counts.get(parsed.series_key, 0) + 1
        for entry in similar.values():
            entry["count"] = key_counts.get(str(entry["key"]), entry["count"])
            entry["other_count"] = key_counts.get(str(entry["other_key"]), 0)
        works = sorted(((titles[i], counts[i]) for i in titles), key=lambda t: t[0].casefold())
        similar_list = sorted(similar.values(), key=lambda e: -int(e["count"]) - int(e["other_count"]))  # type: ignore[arg-type]
        return {"works": works, "review": review, "similar": similar_list}

    def _unfile(self, record: FileRecord) -> None:
        """Move an archived file back to Temp/Incomplete (held, no work)."""
        held = self.settings.held_temp_path / f"{record.sha256}.{record.extension}"
        held.parent.mkdir(parents=True, exist_ok=True)
        if record.status == "complete" and record.local_path:
            source = self.absolute(record.local_path)
            if source.exists():
                if held.exists():
                    source.unlink()  # identical content already held (same hash)
                else:
                    try:
                        os.replace(source, held)
                    except OSError:  # Temp on another drive
                        shutil.copy2(source, held)
                        source.unlink()
            if held.exists():
                self.repos.files.update(record.id, status="held", held_path=str(held), local_path=None, work_id=None)
            else:  # file missing on disk: download it again
                self.repos.files.update(record.id, status="queued", local_path=None, held_path=None, work_id=None)
                self.repos.queue.add(record.id, str(self.part_path(record.sha256, record.extension)),
                                     urlsplit(record.server).hostname or "", self.clock())
        else:
            self.repos.files.update(record.id, work_id=None)

    def rebuild_author(self, author_id: int, progress: Callable[[str], None] | None = None,
                       series_map: dict[str, str] | None = None) -> dict[str, int]:
        """Re-run recognition for every publication of an author and move the
        archived files accordingly. Files are not downloaded again.

        Previous associations (aliases, review decisions, renamed works) are
        discarded. The operation is crash-safe: files are first moved back to
        the temporary "held" area one by one (each step committed), then filed
        again exactly like new downloads.
        """
        author = self.repos.authors.get(author_id)
        if author is None:
            raise EngineError(_("Author not found."))
        if series_map:
            self.set_series_aliases(author_id, series_map)
        report = progress or (lambda _msg: None)
        was_paused = self.downloads.paused
        self.downloads.set_paused(True, "Rebuilding the archive")
        self.downloads._cancel.set()
        deadline = time.monotonic() + 60
        while self.downloads.active_ids() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.downloads._cancel.clear()
        try:
            with self._scan_lock:
                galleries = self._rebuild_candidates(author_id)
                records = [f for g in galleries for f in self.repos.files.for_gallery(g.id)]
                # 1. Un-file: archived files go back to the held area.
                for index, record in enumerate(records, start=1):
                    if record.status in ("complete", "held", "queued", "unavailable", "failed", "duplicate"):
                        self._unfile(record)
                    if index % 50 == 0:
                        report(f"Collecting files… {index}/{len(records)}")
                # 2. Forget previous organization.
                with self.db.transaction():
                    self.db.execute("DELETE FROM work_aliases WHERE author_id=?", (author_id,))
                    self.db.execute(
                        "DELETE FROM review_requests WHERE gallery_id IN (SELECT id FROM galleries WHERE author_id=?)",
                        (author_id,))
                    self.db.execute("UPDATE galleries SET work_id=NULL WHERE author_id=?", (author_id,))
                    self.db.execute("DELETE FROM works WHERE author_id=?", (author_id,))
                self._remove_empty_tree(self.author_dir(author))
                # 3. Recognize again, oldest first, and file the held files.
                stats = {"galleries": 0, "works": 0, "review": 0, "files": 0}
                pool = self._rebuild_pool(galleries)
                for index, gallery in enumerate(galleries, start=1):
                    outcome = self._refile_gallery(author, gallery, pool)
                    stats["galleries"] += 1
                    stats["review"] += int(outcome == "review")
                    if index % 20 == 0:
                        report(f"Filing publications… {index}/{len(galleries)}")
                stats["works"] = len(self.repos.works.for_author(author_id))
                stats["files"] = sum(1 for f in self.repos.files.by_status("complete")
                                     if f.work_id and (w := self.repos.works.get(f.work_id)) and w.author_id == author_id)
        finally:
            self.downloads.set_paused(was_paused)
        log.info("Archive of %s rebuilt: %s", author.name, stats)
        self.events.publish(EventType.WORKS_CHANGED, author_id=author_id)
        self.events.publish(EventType.QUEUE_CHANGED)
        return stats

    def _parse_gallery(self, gallery: Gallery) -> ParsedTitle:
        parsed = parse_title(gallery.title)
        apply_file_name_hints(parsed, [f.original_name for f in self.repos.files.for_gallery(gallery.id)
                                       if f.kind == "image"])
        return parsed

    def _refile_gallery(self, author: Author, gallery: Gallery,
                        pool: list[tuple[datetime | None, ParsedTitle]] | None = None) -> str:
        parsed = self._parse_gallery(gallery)
        decision = self._decide(author, parsed, gallery.published_at, pool)
        work: Work | None = None
        if decision.action is MatchAction.EXISTING and decision.work_id is not None:
            work = self.repos.works.get(decision.work_id)
        elif decision.action is MatchAction.CREATE:
            work = self._create_work(author, parsed, decision.confidence, confirmed=False)
        files = self.repos.files.for_gallery(gallery.id)
        plans = {p.position: p for p in plan_file_names(
            [FileInfo(f.position, f.original_name, f.extension, f.kind) for f in files],
            parsed.page, parsed.page_end, gallery.published_at)}
        taken = self.repos.files.taken_names(work.id) if work else set()
        with self.db.transaction():
            for record in files:
                plan = plans.get(record.position)
                base = plan.file_name if plan else record.target_name
                name, counter = base, 2
                while work and name.casefold() in taken:
                    name = with_counter(base, counter)
                    counter += 1
                taken.add(name.casefold())
                self.repos.files.update(record.id, work_id=work.id if work else None, target_name=name,
                                        page_number=plan.page_number if plan else record.page_number)
            if work is None:
                self.repos.galleries.update(gallery.id, work_id=None, status=GalleryStatus.AWAITING_REVIEW.value)
                self.repos.reviews.open(
                    gallery.id, decision.work_key, decision.display_title,
                    [{"work_id": c.work_id, "title": c.display_title, "score": c.score, "reason": c.reason}
                     for c in decision.candidates],
                    decision.reason,
                )
            else:
                self.repos.galleries.update(gallery.id, work_id=work.id, status=GalleryStatus.QUEUED.value)
        if work is not None:
            self._place_held_files(gallery.id)
        self._refresh_gallery_status(gallery.id)
        return "review" if work is None else "filed"

    def _remove_empty_tree(self, root: Path) -> None:
        """Delete empty folders below *root* (never files)."""
        if not root.is_dir():
            return
        for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()  # only succeeds when empty
            except OSError:
                pass

    # ============================================================ downloads
    def retry_file(self, file_id: int) -> bool:
        return self.downloads.retry(file_id)

    def hold_file(self, file_id: int) -> bool:
        return self.downloads.hold(file_id)

    def release_file(self, file_id: int) -> bool:
        return self.downloads.release_hold(file_id)

    def move_to_top(self, file_id: int) -> bool:
        return self.downloads.move_to_top(file_id)

    def move_to_bottom(self, file_id: int) -> bool:
        return self.downloads.move_to_bottom(file_id)

    def release_all_held(self) -> int:
        return sum(int(self.downloads.release_hold(row["file_id"]))
                   for row in self.repos.queue.all_with_files() if row["status"] == "on_hold")

    def retry_all_failed(self) -> int:
        count = 0
        for row in self.repos.queue.all_with_files():
            if row["status"] in ("failed", "backoff", "paused"):
                count += int(self.downloads.retry(row["file_id"]))
        return count

    # ============================================================== helpers
    def dashboard(self) -> dict[str, object]:
        stats: dict[str, object] = dict(self.repos.dashboard_stats())
        stats["last_success"] = self.repos.scans.last_success()
        stats["active"] = self.downloads.active_ids()
        stats["downloads_paused"] = self.downloads.paused
        stats["paused_hosts"] = self.http.paused_hosts()
        return stats

    def clear_temp_orphans(self) -> int:
        """Delete .part files that no queue entry refers to."""
        referenced = {Path(r["temp_path"]).name for r in self.db.query("SELECT temp_path FROM download_queue")}
        removed = 0
        for part in self.settings.downloads_temp_path.glob("*.part"):
            if part.name not in referenced:
                part.unlink(missing_ok=True)
                removed += 1
        return removed

    def author_disk_usage(self, author: Author) -> tuple[int, int]:
        """Real size on disk of an author's archive folder: (bytes, files).

        Walks the folder, so it also counts files added by hand. Call it from
        a background thread for large archives.
        """
        total = count = 0
        stack = [self.author_dir(author)]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False) and not entry.name.endswith(".incoming"):
                                total += entry.stat(follow_symlinks=False).st_size
                                count += 1
                        except OSError:
                            continue
            except OSError:
                continue
        return total, count

    def disk_free(self) -> int | None:
        try:
            return shutil.disk_usage(self.settings.archive_path).free
        except OSError:
            return None


"""Data access objects. All SQL lives here."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .db import Database, from_db_time, to_db_time, utcnow

# --------------------------------------------------------------------------- rows


@dataclass
class Author:
    id: int
    service: str
    creator_id: str
    name: str
    public_id: str | None
    profile_url: str
    archive_dir: str
    monitoring_enabled: bool
    scan_interval_min: int | None
    status: str
    status_message: str | None
    remote_updated: str | None
    full_scan_done: bool
    last_full_scan_at: datetime | None
    last_scan_at: datetime | None
    last_success_at: datetime | None
    next_scan_at: datetime | None
    last_scan_summary: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Author":
        return cls(
            id=r["id"], service=r["service"], creator_id=r["creator_id"], name=r["name"],
            public_id=r["public_id"], profile_url=r["profile_url"], archive_dir=r["archive_dir"],
            monitoring_enabled=bool(r["monitoring_enabled"]), scan_interval_min=r["scan_interval_min"],
            status=r["status"], status_message=r["status_message"], remote_updated=r["remote_updated"],
            full_scan_done=bool(r["full_scan_done"]), last_full_scan_at=from_db_time(r["last_full_scan_at"]),
            last_scan_at=from_db_time(r["last_scan_at"]),
            last_success_at=from_db_time(r["last_success_at"]), next_scan_at=from_db_time(r["next_scan_at"]),
            last_scan_summary=json.loads(r["last_scan_summary"]) if r["last_scan_summary"] else None,
            created_at=from_db_time(r["created_at"]),  # type: ignore[arg-type]
        )


@dataclass
class Work:
    id: int
    author_id: int
    display_title: str
    work_key: str
    series_name: str | None
    volume: int | None
    part: int | None
    chapter: int | None
    issue: int | None
    episode: int | None
    archive_dir: str
    confidence: float
    user_confirmed: bool
    created_at: datetime

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Work":
        return cls(
            id=r["id"], author_id=r["author_id"], display_title=r["display_title"], work_key=r["work_key"],
            series_name=r["series_name"], volume=r["volume"], part=r["part"], chapter=r["chapter"],
            issue=r["issue"], episode=r["episode"], archive_dir=r["archive_dir"], confidence=r["confidence"],
            user_confirmed=bool(r["user_confirmed"]), created_at=from_db_time(r["created_at"]),  # type: ignore[arg-type]
        )


@dataclass
class Gallery:
    id: int
    author_id: int
    post_id: str
    url: str
    title: str
    normalized_title: str
    parsed_title: dict[str, Any] | None
    published_at: datetime | None
    edited_at: datetime | None
    has_full: bool
    file_count: int
    fingerprint: str
    status: str
    status_message: str | None
    work_id: int | None
    recheck_count: int
    first_seen_at: datetime
    last_checked_at: datetime
    next_recheck_at: datetime | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Gallery":
        return cls(
            id=r["id"], author_id=r["author_id"], post_id=r["post_id"], url=r["url"], title=r["title"],
            normalized_title=r["normalized_title"],
            parsed_title=json.loads(r["parsed_title"]) if r["parsed_title"] else None,
            published_at=from_db_time(r["published_at"]), edited_at=from_db_time(r["edited_at"]),
            has_full=bool(r["has_full"]), file_count=r["file_count"], fingerprint=r["fingerprint"],
            status=r["status"], status_message=r["status_message"], work_id=r["work_id"],
            recheck_count=r["recheck_count"], first_seen_at=from_db_time(r["first_seen_at"]),  # type: ignore[arg-type]
            last_checked_at=from_db_time(r["last_checked_at"]),  # type: ignore[arg-type]
            next_recheck_at=from_db_time(r["next_recheck_at"]),
        )


@dataclass
class FileRecord:
    id: int
    gallery_id: int
    work_id: int | None
    sha256: str
    original_name: str
    extension: str
    kind: str
    server: str
    remote_path: str
    source_url: str
    position: int
    page_number: int | None
    target_name: str
    local_path: str | None
    held_path: str | None
    size_bytes: int | None
    status: str
    duplicate_of: int | None
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "FileRecord":
        return cls(
            id=r["id"], gallery_id=r["gallery_id"], work_id=r["work_id"], sha256=r["sha256"],
            original_name=r["original_name"], extension=r["extension"], kind=r["kind"], server=r["server"],
            remote_path=r["remote_path"], source_url=r["source_url"], position=r["position"],
            page_number=r["page_number"], target_name=r["target_name"], local_path=r["local_path"],
            held_path=r["held_path"], size_bytes=r["size_bytes"], status=r["status"],
            duplicate_of=r["duplicate_of"], created_at=from_db_time(r["created_at"]),  # type: ignore[arg-type]
            completed_at=from_db_time(r["completed_at"]),
        )


@dataclass
class QueueItem:
    file_id: int
    temp_path: str
    host: str
    bytes_done: int
    bytes_total: int | None
    attempts: int
    status: str
    error_class: str | None
    last_error: str | None
    next_attempt_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "QueueItem":
        return cls(
            file_id=r["file_id"], temp_path=r["temp_path"], host=r["host"], bytes_done=r["bytes_done"],
            bytes_total=r["bytes_total"], attempts=r["attempts"], status=r["status"],
            error_class=r["error_class"], last_error=r["last_error"],
            next_attempt_at=from_db_time(r["next_attempt_at"]),  # type: ignore[arg-type]
            updated_at=from_db_time(r["updated_at"]),  # type: ignore[arg-type]
        )


@dataclass
class ReviewRequest:
    id: int
    gallery_id: int
    proposed_key: str
    proposed_title: str
    candidates: list[dict[str, Any]]
    reason: str
    status: str
    created_at: datetime

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "ReviewRequest":
        return cls(
            id=r["id"], gallery_id=r["gallery_id"], proposed_key=r["proposed_key"],
            proposed_title=r["proposed_title"], candidates=json.loads(r["candidates"] or "[]"),
            reason=r["reason"], status=r["status"], created_at=from_db_time(r["created_at"]),  # type: ignore[arg-type]
        )


# ------------------------------------------------------------------- repositories


class AuthorRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, service: str, creator_id: str, name: str, public_id: str | None, profile_url: str,
            archive_dir: str, next_scan_at: datetime) -> Author:
        with self.db.transaction() as c:
            cur = c.execute(
                """INSERT INTO authors (service, creator_id, name, public_id, profile_url, archive_dir,
                   next_scan_at, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (service, creator_id, name, public_id, profile_url, archive_dir, to_db_time(next_scan_at),
                 to_db_time(utcnow())),
            )
            return self.get(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get(self, author_id: int) -> Author | None:
        row = self.db.query_one("SELECT * FROM authors WHERE id=?", (author_id,))
        return Author.from_row(row) if row else None

    def find(self, service: str, creator_id: str) -> Author | None:
        row = self.db.query_one("SELECT * FROM authors WHERE service=? AND creator_id=?", (service, creator_id))
        return Author.from_row(row) if row else None

    def all(self) -> list[Author]:
        return [Author.from_row(r) for r in self.db.query("SELECT * FROM authors ORDER BY name COLLATE NOCASE")]

    def archive_dirs(self) -> set[str]:
        return {r[0].casefold() for r in self.db.query("SELECT archive_dir FROM authors")}

    def due(self, now: datetime) -> list[Author]:
        rows = self.db.query(
            """SELECT * FROM authors WHERE monitoring_enabled=1 AND status NOT IN ('scanning')
               AND (next_scan_at IS NULL OR next_scan_at <= ?) ORDER BY next_scan_at""",
            (to_db_time(now),),
        )
        return [Author.from_row(r) for r in rows]

    def update(self, author_id: int, **fields: Any) -> None:
        if not fields:
            return
        conv: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(value, datetime):
                value = to_db_time(value)
            elif isinstance(value, bool):
                value = int(value)
            elif isinstance(value, dict):
                value = json.dumps(value)
            conv[key] = value
        sets = ", ".join(f"{k}=?" for k in conv)
        self.db.execute(f"UPDATE authors SET {sets} WHERE id=?", (*conv.values(), author_id))

    def delete(self, author_id: int) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM authors WHERE id=?", (author_id,))


class WorkRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, author_id: int, display_title: str, work_key: str, groups: dict[str, int],
            series_name: str | None, archive_dir: str, confidence: float, user_confirmed: bool) -> Work:
        with self.db.transaction() as c:
            cur = c.execute(
                """INSERT INTO works (author_id, display_title, work_key, series_name, volume, part, chapter,
                   issue, episode, archive_dir, confidence, user_confirmed, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (author_id, display_title, work_key, series_name, groups.get("volume"), groups.get("part"),
                 groups.get("chapter"), groups.get("issue"), groups.get("episode"), archive_dir, confidence,
                 int(user_confirmed), to_db_time(utcnow())),
            )
            return self.get(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get(self, work_id: int) -> Work | None:
        row = self.db.query_one("SELECT * FROM works WHERE id=?", (work_id,))
        return Work.from_row(row) if row else None

    def for_author(self, author_id: int) -> list[Work]:
        rows = self.db.query("SELECT * FROM works WHERE author_id=? ORDER BY display_title COLLATE NOCASE", (author_id,))
        return [Work.from_row(r) for r in rows]

    def by_key(self, author_id: int, work_key: str) -> Work | None:
        row = self.db.query_one("SELECT * FROM works WHERE author_id=? AND work_key=?", (author_id, work_key))
        return Work.from_row(row) if row else None

    def archive_dirs(self, author_id: int) -> set[str]:
        return {r[0].casefold() for r in self.db.query("SELECT archive_dir FROM works WHERE author_id=?", (author_id,))}

    def update(self, work_id: int, **fields: Any) -> None:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(f"UPDATE works SET {sets} WHERE id=?", (*[int(v) if isinstance(v, bool) else v for v in fields.values()], work_id))

    def delete(self, work_id: int) -> None:
        self.db.execute("DELETE FROM works WHERE id=?", (work_id,))

    def aliases(self, author_id: int) -> dict[str, int]:
        return {r["alias_key"]: r["work_id"] for r in self.db.query(
            "SELECT alias_key, work_id FROM work_aliases WHERE author_id=?", (author_id,))}

    def set_alias(self, author_id: int, alias_key: str, work_id: int, source: str) -> None:
        self.db.execute(
            """INSERT INTO work_aliases (author_id, alias_key, work_id, source, created_at) VALUES (?,?,?,?,?)
               ON CONFLICT(author_id, alias_key) DO UPDATE SET work_id=excluded.work_id, source=excluded.source""",
            (author_id, alias_key, work_id, source, to_db_time(utcnow())),
        )

    def move_aliases(self, from_work: int, to_work: int) -> None:
        self.db.execute("UPDATE work_aliases SET work_id=? WHERE work_id=?", (to_work, from_work))

    def stats(self, work_id: int) -> dict[str, int]:
        row = self.db.query_one(
            """SELECT SUM(status NOT IN ('duplicate','skipped')) AS total,
                      SUM(status='complete') AS complete,
                      SUM(status IN ('pending','queued','downloading','held')) AS pending,
                      SUM(status IN ('failed','unavailable')) AS failed,
                      COALESCE(SUM(CASE WHEN status='complete' THEN size_bytes END),0) AS bytes
               FROM files WHERE work_id=?""",
            (work_id,),
        )
        return {k: int(row[k] or 0) for k in ("total", "complete", "pending", "failed", "bytes")}  # type: ignore[index]


class GalleryRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, gallery_id: int) -> Gallery | None:
        row = self.db.query_one("SELECT * FROM galleries WHERE id=?", (gallery_id,))
        return Gallery.from_row(row) if row else None

    def find(self, author_id: int, post_id: str) -> Gallery | None:
        row = self.db.query_one("SELECT * FROM galleries WHERE author_id=? AND post_id=?", (author_id, post_id))
        return Gallery.from_row(row) if row else None

    def upsert(self, author_id: int, post_id: str, **fields: Any) -> Gallery:
        conv = {k: (to_db_time(v) if isinstance(v, datetime) else json.dumps(v) if isinstance(v, dict)
                    else int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
        existing = self.find(author_id, post_id)
        if existing is None:
            conv.setdefault("first_seen_at", to_db_time(utcnow()))
            cols = ["author_id", "post_id", *conv]
            self.db.execute(
                f"INSERT INTO galleries ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                (author_id, post_id, *conv.values()),
            )
        else:
            sets = ", ".join(f"{k}=?" for k in conv)
            self.db.execute(f"UPDATE galleries SET {sets} WHERE id=?", (*conv.values(), existing.id))
        return self.find(author_id, post_id)  # type: ignore[return-value]

    def update(self, gallery_id: int, **fields: Any) -> None:
        if fields:
            conv = {k: (to_db_time(v) if isinstance(v, datetime) else int(v) if isinstance(v, bool) else v)
                    for k, v in fields.items()}
            sets = ", ".join(f"{k}=?" for k in conv)
            self.db.execute(f"UPDATE galleries SET {sets} WHERE id=?", (*conv.values(), gallery_id))

    def due_rechecks(self, now: datetime, limit: int = 20) -> list[Gallery]:
        rows = self.db.query(
            """SELECT g.* FROM galleries g JOIN authors a ON a.id=g.author_id
               WHERE a.monitoring_enabled=1 AND g.next_recheck_at IS NOT NULL AND g.next_recheck_at <= ?
               ORDER BY g.next_recheck_at LIMIT ?""",
            (to_db_time(now), limit),
        )
        return [Gallery.from_row(r) for r in rows]

    def for_work(self, work_id: int) -> list[Gallery]:
        rows = self.db.query("SELECT * FROM galleries WHERE work_id=? ORDER BY published_at", (work_id,))
        return [Gallery.from_row(r) for r in rows]

    def for_author(self, author_id: int, statuses: tuple[str, ...] | None = None) -> list[Gallery]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            rows = self.db.query(f"SELECT * FROM galleries WHERE author_id=? AND status IN ({marks}) ORDER BY published_at DESC", (author_id, *statuses))
        else:
            rows = self.db.query("SELECT * FROM galleries WHERE author_id=? ORDER BY published_at DESC", (author_id,))
        return [Gallery.from_row(r) for r in rows]


class FileRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, **fields: Any) -> FileRecord:
        fields.setdefault("created_at", to_db_time(utcnow()))
        cols = list(fields)
        cur = self.db.execute(
            f"INSERT INTO files ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(fields.values())
        )
        return self.get(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get(self, file_id: int) -> FileRecord | None:
        row = self.db.query_one("SELECT * FROM files WHERE id=?", (file_id,))
        return FileRecord.from_row(row) if row else None

    def for_gallery(self, gallery_id: int) -> list[FileRecord]:
        return [FileRecord.from_row(r) for r in self.db.query("SELECT * FROM files WHERE gallery_id=? ORDER BY position", (gallery_id,))]

    def for_work(self, work_id: int) -> list[FileRecord]:
        rows = self.db.query(
            """SELECT f.* FROM files f JOIN galleries g ON g.id=f.gallery_id WHERE f.work_id=?
               ORDER BY f.page_number IS NULL, f.page_number, g.published_at, f.position""",
            (work_id,),
        )
        return [FileRecord.from_row(r) for r in rows]

    def completed_with_hash(self, sha256: str) -> FileRecord | None:
        row = self.db.query_one(
            "SELECT * FROM files WHERE sha256=? AND status='complete' ORDER BY id LIMIT 1", (sha256,)
        )
        return FileRecord.from_row(row) if row else None

    def active_with_hash(self, sha256: str, exclude_id: int | None = None) -> FileRecord | None:
        row = self.db.query_one(
            "SELECT * FROM files WHERE sha256=? AND status IN ('queued','downloading','held','complete') AND id != ? ORDER BY id LIMIT 1",
            (sha256, exclude_id or -1),
        )
        return FileRecord.from_row(row) if row else None

    def taken_names(self, work_id: int) -> set[str]:
        rows = self.db.query(
            "SELECT target_name, local_path FROM files WHERE work_id=? AND status NOT IN ('duplicate')", (work_id,)
        )
        names: set[str] = set()
        for r in rows:
            names.add(r["target_name"].casefold())
            if r["local_path"]:
                names.add(r["local_path"].replace("\\", "/").rsplit("/", 1)[-1].casefold())
        return names

    def update(self, file_id: int, **fields: Any) -> None:
        if fields:
            conv = {k: (to_db_time(v) if isinstance(v, datetime) else v) for k, v in fields.items()}
            sets = ", ".join(f"{k}=?" for k in conv)
            self.db.execute(f"UPDATE files SET {sets} WHERE id=?", (*conv.values(), file_id))

    def by_status(self, *statuses: str) -> list[FileRecord]:
        marks = ",".join("?" * len(statuses))
        return [FileRecord.from_row(r) for r in self.db.query(f"SELECT * FROM files WHERE status IN ({marks})", statuses)]


class QueueRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, file_id: int, temp_path: str, host: str, now: datetime) -> None:
        self.db.execute(
            """INSERT INTO download_queue (file_id, temp_path, host, status, next_attempt_at, updated_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT(file_id) DO NOTHING""",
            (file_id, temp_path, host, "waiting", to_db_time(now), to_db_time(now)),
        )

    def get(self, file_id: int) -> QueueItem | None:
        row = self.db.query_one("SELECT * FROM download_queue WHERE file_id=?", (file_id,))
        return QueueItem.from_row(row) if row else None

    def ready(self, now: datetime, limit: int = 50) -> list[QueueItem]:
        rows = self.db.query(
            """SELECT * FROM download_queue WHERE status IN ('waiting','backoff') AND next_attempt_at <= ?
               ORDER BY priority DESC, attempts, next_attempt_at, file_id LIMIT ?""",
            (to_db_time(now), limit),
        )
        return [QueueItem.from_row(r) for r in rows]

    def update(self, file_id: int, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        conv = {k: (to_db_time(v) if isinstance(v, datetime) else v) for k, v in fields.items()}
        sets = ", ".join(f"{k}=?" for k in conv)
        self.db.execute(f"UPDATE download_queue SET {sets} WHERE file_id=?", (*conv.values(), file_id))

    def remove(self, file_id: int) -> None:
        self.db.execute("DELETE FROM download_queue WHERE file_id=?", (file_id,))

    def reset_active(self) -> int:
        """After a crash/restart, nothing is actually downloading."""
        cur = self.db.execute("UPDATE download_queue SET status='waiting' WHERE status='active'")
        self.db.execute("UPDATE files SET status='queued' WHERE status='downloading'")
        return cur.rowcount

    def all_with_files(self) -> list[sqlite3.Row]:
        return self.db.query(
            """SELECT q.*, f.target_name, f.original_name, f.kind, f.status AS file_status, f.work_id,
                      g.title AS gallery_title, a.name AS author_name, w.display_title AS work_title
               FROM download_queue q JOIN files f ON f.id=q.file_id JOIN galleries g ON g.id=f.gallery_id
               JOIN authors a ON a.id=g.author_id LEFT JOIN works w ON w.id=f.work_id
               ORDER BY CASE q.status WHEN 'active' THEN 0 WHEN 'waiting' THEN 1 WHEN 'backoff' THEN 2
                        WHEN 'paused' THEN 3 WHEN 'on_hold' THEN 4 ELSE 5 END, q.priority DESC, q.attempts,
                        q.next_attempt_at, q.file_id"""
        )

    def priority_bounds(self) -> tuple[int, int]:
        row = self.db.query_one("SELECT MIN(priority) AS lo, MAX(priority) AS hi FROM download_queue")
        return (int(row["lo"] or 0), int(row["hi"] or 0)) if row else (0, 0)

    def counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.db.query("SELECT status, COUNT(*) AS n FROM download_queue GROUP BY status")}

    def items_for_author(self, author_id: int) -> list[QueueItem]:
        rows = self.db.query(
            """SELECT q.* FROM download_queue q JOIN files f ON f.id=q.file_id JOIN galleries g ON g.id=f.gallery_id
               WHERE g.author_id=?""",
            (author_id,),
        )
        return [QueueItem.from_row(r) for r in rows]


class ReviewRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def open(self, gallery_id: int, proposed_key: str, proposed_title: str, candidates: list[dict[str, Any]], reason: str) -> None:
        self.db.execute(
            """INSERT INTO review_requests (gallery_id, proposed_key, proposed_title, candidates, reason, status, created_at)
               VALUES (?,?,?,?,?,'open',?) ON CONFLICT(gallery_id) DO UPDATE SET proposed_key=excluded.proposed_key,
               proposed_title=excluded.proposed_title, candidates=excluded.candidates, reason=excluded.reason,
               status='open', resolved_at=NULL""",
            (gallery_id, proposed_key, proposed_title, json.dumps(candidates), reason, to_db_time(utcnow())),
        )

    def get(self, review_id: int) -> ReviewRequest | None:
        row = self.db.query_one("SELECT * FROM review_requests WHERE id=?", (review_id,))
        return ReviewRequest.from_row(row) if row else None

    def open_requests(self) -> list[ReviewRequest]:
        return [ReviewRequest.from_row(r) for r in self.db.query("SELECT * FROM review_requests WHERE status='open' ORDER BY created_at")]

    def resolve(self, review_id: int) -> None:
        self.db.execute("UPDATE review_requests SET status='resolved', resolved_at=? WHERE id=?", (to_db_time(utcnow()), review_id))

    def count_open(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM review_requests WHERE status='open'") or 0)


class HostRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def set_pause(self, host: str, until: datetime | None, reason: str | None) -> None:
        self.db.execute(
            """INSERT INTO host_state (host, paused_until, reason, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(host) DO UPDATE SET paused_until=excluded.paused_until, reason=excluded.reason,
               updated_at=excluded.updated_at""",
            (host, to_db_time(until), reason, to_db_time(utcnow())),
        )

    def active_pauses(self, now: datetime) -> dict[str, tuple[datetime, str]]:
        rows = self.db.query("SELECT * FROM host_state WHERE paused_until > ?", (to_db_time(now),))
        return {r["host"]: (from_db_time(r["paused_until"]), r["reason"] or "") for r in rows}  # type: ignore[misc]


class ScanLogRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, author_id: int) -> int:
        cur = self.db.execute("INSERT INTO scan_log (author_id, started_at) VALUES (?,?)", (author_id, to_db_time(utcnow())))
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def finish(self, log_id: int, result: str, pages: int, new_galleries: int, new_files: int, message: str = "") -> None:
        self.db.execute(
            """UPDATE scan_log SET finished_at=?, result=?, pages_fetched=?, new_galleries=?, new_files=?, message=?
               WHERE id=?""",
            (to_db_time(utcnow()), result, pages, new_galleries, new_files, message, log_id),
        )

    def last_success(self) -> datetime | None:
        return from_db_time(self.db.scalar("SELECT MAX(finished_at) FROM scan_log WHERE result='ok'"))

    def recent(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.query(
            """SELECT s.*, a.name AS author_name FROM scan_log s LEFT JOIN authors a ON a.id=s.author_id
               ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        )


class StateRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        value = self.db.scalar("SELECT value FROM app_state WHERE key=?", (key,))
        return default if value is None else value

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO app_state (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


class Repositories:
    """Bundle of all repositories sharing one database."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.authors = AuthorRepo(db)
        self.works = WorkRepo(db)
        self.galleries = GalleryRepo(db)
        self.files = FileRepo(db)
        self.queue = QueueRepo(db)
        self.reviews = ReviewRepo(db)
        self.hosts = HostRepo(db)
        self.scans = ScanLogRepo(db)
        self.state = StateRepo(db)

    def dashboard_stats(self) -> dict[str, int]:
        row = self.db.query_one(
            """SELECT
                (SELECT COUNT(*) FROM authors) AS authors,
                (SELECT COUNT(*) FROM authors WHERE monitoring_enabled=1) AS monitored,
                (SELECT COUNT(*) FROM galleries) AS galleries,
                (SELECT COUNT(*) FROM galleries WHERE status='empty') AS empty_galleries,
                (SELECT COUNT(*) FROM galleries WHERE status='awaiting_full') AS awaiting_full,
                (SELECT COUNT(*) FROM works) AS works,
                (SELECT COUNT(*) FROM files WHERE status='complete' AND kind='image') AS images,
                (SELECT COUNT(*) FROM files WHERE status='complete') AS files_done,
                (SELECT COUNT(*) FROM files WHERE status IN ('queued','downloading','pending')) AS pending,
                (SELECT COUNT(*) FROM files WHERE status='held') AS held,
                (SELECT COUNT(*) FROM files WHERE status IN ('failed','unavailable')) AS failed,
                (SELECT COUNT(*) FROM review_requests WHERE status='open') AS reviews,
                (SELECT COALESCE(SUM(size_bytes),0) FROM files WHERE status='complete') AS bytes"""
        )
        return {k: int(row[k] or 0) for k in row.keys()}  # type: ignore[union-attr]

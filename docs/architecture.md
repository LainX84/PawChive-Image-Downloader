# Architecture and Database Design

Stage 4 of the development workflow. This builds on
[`website-analysis.md`](website-analysis.md).

## 1. Guiding decisions

| Decision | Choice | Reason |
|---|---|---|
| Data source | PawChive JSON API (`/api/v1`) | Public, structured, no login. HTML is used only for diagnostics. |
| Browser automation | **None** (no Playwright) | Originals are plain HTTPS files listed by the API. |
| Language / runtime | Python 3.11+ | Spec recommendation; `tomllib` and modern typing. |
| GUI | PySide6 | Spec recommendation. |
| HTTP | `httpx` (sync client, HTTP/1.1) | Streaming, Range, timeouts; mockable with `respx`. |
| Database | SQLite (stdlib `sqlite3`), WAL mode | Crash-safe, zero setup. |
| Secrets | `keyring` | OS credential store (Windows Credential Manager, macOS Keychain, Secret Service). |
| Paths | `platformdirs` | Per-OS default data/log dirs, all overridable. |
| Integrity | SHA-256 from the remote path | The path name **is** the file's SHA-256 (verified). |
| Fuzzy matching | stdlib `difflib` | Enough for "similar title" detection. No extra dependency. |
| Tests | `pytest`, `respx`, `pytest-qt` (UI smoke only) | Mocked HTTP and local JSON fixtures. |

Runtime dependencies: `PySide6`, `httpx`, `keyring`, `platformdirs`. That's all.

### Core/UI separation

The engine (`core`) has **no Qt import**. It runs in background worker threads
and publishes events on a small thread-safe event bus. The UI subscribes
through a Qt adapter that turns events into signals. This keeps the engine
fully testable without a GUI. It also makes a later **headless mode** (CLI or
service, for example on a home server) cheap to add without touching the
engine.

## 2. Package layout

```text
src/pawchive_downloader/
├── __main__.py              # python -m pawchive_downloader
├── app.py                   # bootstrap: settings → logging → DB → engine → UI
├── version.py               # version, author and project links
├── i18n.py, i18n_it.py      # _() translation lookup (pure Python) + Italian catalogue
├── legal.py                 # MIT license, disclaimer and third-party credits shown in About
├── config/
│   ├── settings.py          # typed Settings dataclass, load/save (TOML/JSON)
│   └── paths.py             # resolve + validate dirs, write-permission checks
├── site/                    # PawChive website client
│   ├── urls.py              # parse/classify pasted URLs (profile / post)
│   ├── http.py              # HttpClient: throttling, per-host limits, 429/Retry-After
│   ├── api.py               # typed endpoint wrappers + response validation
│   ├── models.py            # Creator, Post, RemoteFile dataclasses
│   └── errors.py            # SiteStructureChanged, AccessBlocked, NotFound, …
├── auth/
│   └── session.py           # optional cookies in keyring; redaction helpers
├── recognition/
│   ├── normalize.py         # unicode/case/punctuation/whitespace normalization
│   ├── title_parser.py      # title → ParsedTitle (series, part, chapter, page…)
│   └── matcher.py           # ParsedTitle + author → existing Work / new / review
├── archive/
│   ├── naming.py            # safe folder/file names (Windows-safe), collision rules
│   └── organizer.py         # final placement, rename/merge/reassign operations
├── downloads/
│   ├── verify.py            # SHA-256, size, content-type, magic-byte checks
│   ├── downloader.py        # single file: .part, Range resume, atomic finalize
│   ├── queue.py             # persistent queue, worker pool, per-host concurrency,
│   │                        #   pause (also timed), per-file hold, priority, speed/ETA
│   ├── throttle.py          # BandwidthLimiter (shared token bucket), SpeedMeter
│   └── retry.py             # error classification, exponential backoff policy
├── monitor/
│   ├── discovery.py         # list posts, diff vs DB, classify galleries
│   └── scheduler.py         # per-author intervals, rechecks, startup scan
├── storage/
│   ├── db.py                # connection, WAL, transactions
│   ├── migrations/          # 0001_initial.sql, 0002_….sql
│   ├── migrate.py           # PRAGMA user_version based migrator
│   ├── backup.py            # online backup before migrations + rotating daily
│   └── repositories.py      # AuthorRepo, GalleryRepo, WorkRepo, FileRepo, QueueRepo
├── core/
│   ├── events.py            # EventBus + event dataclasses
│   └── engine.py            # facade the UI talks to (add author, scan, retry, …)
├── diagnostics/
│   ├── logging_setup.py     # JSON-lines file log + console; secret redaction filter
│   └── export.py            # zip logs + sanitized settings + DB stats
└── ui/
    ├── qt_bridge.py         # EventBus → Qt signals
    ├── main_window.py       # sectioned sidebar, pages, status bar (speed / time left)
    ├── theme.py             # light and dark palettes, stylesheet, follow-the-system
    ├── icons.py             # painted line icons and the application icon
    ├── pause_controls.py    # pause button with "pause for / until" menu
    ├── tray.py              # notification-area icon, menu, "new pages" notifications
    ├── pages/               # dashboard, authors, works, queue, review, settings, about
    └── dialogs/             # first run, rebuild archive
```

## 3. Domain model

```text
Author 1──* Gallery 1──* RemoteFile *──1 Work *──1 Author
                                          ▲
                        WorkAlias ────────┘   (confirmed title → work mappings)
```

- **Author**: a monitored creator, keyed by `(service, creator_id)`.
- **Gallery**: one PawChive post.
- **Work**: one archive folder, for example "A Specter of Love - Part 2". The
  identity is the **normalized work key** within an author.
- **RemoteFile**: one file of a gallery, identified by its SHA-256. The spec's
  "Images" table is generalized to all attachment types, since non-image files
  are archived too.
- **WorkAlias**: a remembered association "normalized title key X → work Y",
  created when the user confirms or corrects a classification (spec §4.2).

## 4. Database schema (migration `0001_initial.sql`)

> The authoritative schema is `src/pawchive_downloader/storage/migrations/0001_initial.sql`.
> The implementation added a few columns to the design below: `authors.last_full_scan_at`,
> `authors.status_message`, `galleries.status_message`, `galleries.recheck_count`,
> `works.episode`, `files.target_name`, `files.held_path`, `download_queue.host`, and the
> `app_state` key/value table.

Timestamps are UTC ISO-8601 text. Archive paths are stored **relative to the
archive root**, so the user can move the archive and change one setting.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE authors (
    id                  INTEGER PRIMARY KEY,
    service             TEXT    NOT NULL,             -- 'patreon' | 'fanbox' | …
    creator_id          TEXT    NOT NULL,             -- numeric id as text
    name                TEXT    NOT NULL,
    public_id           TEXT,
    profile_url         TEXT    NOT NULL,
    archive_dir         TEXT    NOT NULL,             -- relative, e.g. 'Exce'
    monitoring_enabled  INTEGER NOT NULL DEFAULT 1,
    scan_interval_min   INTEGER,                      -- NULL → global default
    status              TEXT    NOT NULL DEFAULT 'idle',
        -- idle | scanning | paused | blocked | error | not_found
    remote_updated      TEXT,                         -- profile.updated at last scan
    last_scan_at        TEXT,
    last_success_at     TEXT,
    next_scan_at        TEXT,
    last_scan_summary   TEXT,                         -- JSON: counts, errors
    created_at          TEXT    NOT NULL,
    UNIQUE (service, creator_id)
);

CREATE TABLE galleries (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    post_id             TEXT    NOT NULL,
    url                 TEXT    NOT NULL,
    title               TEXT    NOT NULL,             -- original title
    normalized_title    TEXT    NOT NULL,
    parsed_title        TEXT,                         -- JSON ParsedTitle
    published_at        TEXT,
    edited_at           TEXT,
    has_full            INTEGER NOT NULL,
    file_count          INTEGER NOT NULL,             -- distinct files after dedup
    fingerprint         TEXT    NOT NULL,             -- sha256(sorted hashes + has_full + edited)
    status              TEXT    NOT NULL,
        -- empty | awaiting_full | awaiting_review | queued | partial | complete | error
    work_id             INTEGER REFERENCES works(id) ON DELETE SET NULL,
    first_seen_at       TEXT    NOT NULL,
    last_checked_at     TEXT    NOT NULL,
    next_recheck_at     TEXT,                         -- for empty / awaiting_full
    UNIQUE (author_id, post_id)
);
CREATE INDEX ix_galleries_status  ON galleries(status, next_recheck_at);

CREATE TABLE works (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    display_title       TEXT    NOT NULL,             -- 'Isla: Origins - Chapter 1'
    work_key            TEXT    NOT NULL,             -- 'isla origins|chapter:1'
    series_name         TEXT    NOT NULL,             -- 'Isla: Origins'
    volume              INTEGER,
    part                INTEGER,
    chapter             INTEGER,
    issue               INTEGER,
    archive_dir         TEXT    NOT NULL,             -- relative to author dir
    confidence          REAL    NOT NULL,
    user_confirmed      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    UNIQUE (author_id, work_key),
    UNIQUE (author_id, archive_dir)
);

CREATE TABLE work_aliases (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    alias_key           TEXT    NOT NULL,             -- work_key the parser produced
    work_id             INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    source              TEXT    NOT NULL,             -- 'user' | 'merge'
    created_at          TEXT    NOT NULL,
    UNIQUE (author_id, alias_key)
);

CREATE TABLE files (
    id                  INTEGER PRIMARY KEY,
    gallery_id          INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    work_id             INTEGER REFERENCES works(id) ON DELETE SET NULL,
    sha256              TEXT    NOT NULL,             -- from remote path
    original_name       TEXT    NOT NULL,
    extension           TEXT    NOT NULL,
    kind                TEXT    NOT NULL,             -- image | video | archive | document | other
    server              TEXT    NOT NULL,
    remote_path         TEXT    NOT NULL,
    source_url          TEXT    NOT NULL,
    position            INTEGER NOT NULL,             -- order inside the post
    page_number         INTEGER,
    page_suffix         TEXT,                         -- disambiguator, e.g. '2' → 'Page 35 (2)'
    local_path          TEXT,                         -- relative to archive root, set on completion
    size_bytes          INTEGER,
    status              TEXT    NOT NULL,
        -- pending | held | queued | downloading | complete | duplicate | unavailable | failed
    duplicate_of        INTEGER REFERENCES files(id),
    completed_at        TEXT,
    UNIQUE (gallery_id, sha256)
);
CREATE INDEX ix_files_sha    ON files(sha256);
CREATE INDEX ix_files_work   ON files(work_id, page_number);

CREATE TABLE download_queue (
    file_id             INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    temp_path           TEXT    NOT NULL,             -- absolute, under Temp/Downloads
    bytes_done          INTEGER NOT NULL DEFAULT 0,
    bytes_total         INTEGER,
    attempts            INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL,             -- waiting | active | backoff | failed | paused
    error_class         TEXT,                         -- transient | permanent | blocked | integrity | disk
    last_error          TEXT,
    next_attempt_at     TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE review_requests (                        -- low-confidence classifications
    id                  INTEGER PRIMARY KEY,
    gallery_id          INTEGER NOT NULL UNIQUE REFERENCES galleries(id) ON DELETE CASCADE,
    proposed_key        TEXT    NOT NULL,
    proposed_title      TEXT    NOT NULL,
    candidates          TEXT    NOT NULL,             -- JSON [{work_id, score, reason}]
    reason              TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'open', -- open | resolved
    created_at          TEXT    NOT NULL
);

CREATE TABLE host_state (                             -- throttling / blocking per host
    host                TEXT    PRIMARY KEY,
    paused_until        TEXT,
    reason              TEXT,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE scan_log (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    started_at          TEXT    NOT NULL,
    finished_at         TEXT,
    result              TEXT,                         -- ok | partial | blocked | error
    pages_fetched       INTEGER,
    new_galleries       INTEGER,
    new_files           INTEGER,
    message             TEXT
);
```

Settings (non-secret) live in a `settings.json` file next to the database.
That way they stay readable, can be edited, and survive a damaged DB. Cookies,
if ever configured, live only in the OS keyring.

### Migrations and backups

- `PRAGMA user_version` holds the schema version. `migrate.py` applies the
  numbered `.sql` files in order, each inside one transaction.
- Before any migration, and once per day, the app takes an **online backup**
  with `sqlite3.Connection.backup()` to `Database/backups/pawchive-YYYYMMDD.db`
  and keeps the last N (default 7).
- `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`. Every
  state transition is one short transaction.

## 5. Key flows

### 5.1 Add author

1. `urls.parse(text)` returns `ProfileUrl(service, id)` or
   `PostUrl(service, id, post_id)`. Anything else is rejected with a clear
   message (also for other domains or Discord).
2. A post URL leads to the dialog "This post belongs to *X*. Monitor this
   author?"
3. `GET …/profile` checks that the creator exists and gets the name.
4. Duplicate check on `(service, creator_id)`.
5. Insert the author and pick an author folder (`naming.author_dir`, with
   collision suffix ` [patreon-82443765]`). Schedule an immediate **full scan**.

### 5.2 Scan (discovery)

```text
profile (1 request) ─ unchanged `updated` and no rechecks due? → done
   │
   └─ posts?o=0,50,100…  (≥ request delay between pages)
        for each post:
           unknown              → new gallery
           known, fingerprint ≠ → changed gallery (new files / has_full flipped)
           known, same          → unchanged; incremental scan stops after a
                                  full page of unchanged posts
```

Each new or changed gallery is classified:

| Condition | Status | Action |
|---|---|---|
| no files after dedup | `empty` | no folder, no tasks; `next_recheck_at = now + empty_recheck` |
| `has_full == false` | `awaiting_full` | **nothing downloaded** (originals 404); recheck later |
| files, title confidently matched | `queued` | files → queue with target work |
| files, low confidence | `awaiting_review` | files downloaded into Temp and **held**; review request opened; no archive folder until the user decides |

A full scan is done when an author is added, and on demand. Normal cycles are
incremental. Galleries due for recheck (`empty`, `awaiting_full`) are fetched
with the single-post endpoint, not by re-listing.

### 5.3 Recognition (spec §4)

`title_parser.parse(title) -> ParsedTitle`:

```python
@dataclass
class ParsedTitle:
    raw: str
    series: str | None          # "A Specter of Love", "Isla: Origins"
    volume: int | None
    part: int | None
    chapter: int | None
    issue: int | None           # "#11", "Issue 23"
    page: int | None
    page_end: int | None        # "Pages 10-12"
    noise: list[str]            # "[LIFT Update]", "(Finished)", "WIP"
    confidence: float           # 0..1
    warnings: list[str]         # "no series name", "page word without number", …
```

The parser is a **pipeline of ordered regex rules**, each with its own test
case, rather than a single regex:

1. Normalize unicode (NFKC), quotes (`´ ’ → '`), dashes (`– — → -`), whitespace.
2. Strip and record noise: leading `[...]`, trailing `(Finished)`, `WIP`,
   `Sketch`, `Preview`, emoji, `??`.
3. Extract the page from the right end: `Page N`, `Pages N-M`, `pg N`,
   `P. N`, `pN`, `N/?`, `N/M`, `(page N)`.
4. Extract the group markers: `Vol(ume) N`, `Part N`, `Chapter N` / `Ch. N`,
   `Issue N` / `#N`.
5. What remains, trimmed of separators (`- | : ,`), is the series name.
6. Score confidence and add warnings: missing series, "page" with no number,
   only a number, and so on.

`work_key = normalize_key(series) + "|" + "vol:1|part:2|chapter:…"`, where
`normalize_key` casefolds, removes punctuation, and collapses whitespace.
`display_title` keeps the original casing: `"Isla: Origins - Chapter 1"`.
The folder name is a Windows-safe form of it: `"Isla - Origins - Chapter 1"`
(`:` and other reserved characters → ` - `, trailing dots/spaces removed,
reserved names such as `CON` escaped).

`matcher.match(author, parsed)` decides, in this order:

1. `work_aliases` hit for `(author, work_key)` → that work (confidence 1.0).
2. Exact `works.work_key` hit → that work.
3. The parse is confident and no existing work is **similar**
   (`difflib` ratio ≥ 0.85 on the series name, or the same series with
   different punctuation that normalizes differently) → create a new work
   automatically.
4. Otherwise → `awaiting_review`, with ranked candidates. Similar titles are
   **never merged automatically** (spec §4.2). The user's decision is stored as
   a `work_aliases` row, so the next publication matches at step 1.

Posts without any series markers (for example "Barbara Halloween costume")
become a work named after the cleaned title. This happens **only after** the
similarity check, so a lone page of an existing series goes to review instead
of quietly creating a new folder (spec §5).

The thresholds (`auto_create_min_confidence`, `similarity_review_threshold`)
are settings, with defaults tuned against the real-title fixtures.

### 5.4 File naming inside a work folder

| Case | Name |
|---|---|
| image, post has page N, only image in post | `Page 35.png` |
| images, post has a page range N–M and the count matches | `Page 10.png`, `Page 11.png`, `Page 12.png` |
| several images, single page N | `Page 35 (1).png`, `Page 35 (2).png` |
| image, no page number | `{published date} - {original name}` |
| non-image (7z, mp4, pdf, …) | original name, e.g. `SpookyBarbara.7z` |
| name collision with a **different** file | add ` (2)`, ` (3)` …. **Never overwrite** |
| same SHA-256 already archived anywhere | not downloaded again; `files.status = duplicate`, `duplicate_of` set |

Page numbers are padded only for sorting in the UI. Filenames stay
`Page 35`, as in the spec. Extensions come from the remote path, which is the
true type.

### 5.5 Download pipeline (spec §8)

```text
queued ─► active ─► Temp/Downloads/<sha256>.<ext>.part
            │  Range: bytes=<bytes_done>-   (resume; restart if server ignores Range)
            │  stream to disk, update bytes_done every ~1 MB (one small UPDATE)
            ▼
         verify:  HTTP 200/206 · Content-Type not text/html
                  size == Content-Length/Content-Range total
                  SHA-256 == hash in remote path            ← authoritative
                  magic bytes match extension (images only)
            ▼
         finalize: copy/rename into  <archive>/<author>/<work>/.<name>.incoming
                   fsync → os.replace() to final name       ← atomic on same volume
                   DB: files.complete + local_path, queue row deleted (one txn)
```

- `Temp/` and `Archive/` may be on different drives. The `.incoming` temp name
  inside the destination folder keeps the final `os.replace` atomic in every
  case.
- Failure classification (`retry.py`):

| Signal | Class | Behaviour |
|---|---|---|
| timeout, connection reset, 5xx | transient | exponential backoff `base·2^n` (+ jitter), max attempts, keep `.part` |
| 429 | transient | honor `Retry-After`; pause the host in `host_state` |
| 403, HTML challenge, `cf-mitigated` | blocked | pause the host, notify the user, no retries until the pause expires or the user resumes |
| 401 | auth | stop and show "authentication required/expired" (spec scenario J) |
| 404 on an original | permanent (unavailable) | mark the file `unavailable`; the gallery is rechecked on a long interval |
| SHA-256 mismatch | integrity | delete `.part`, restart from zero once, then `failed` |
| disk full / permission | disk | pause the whole queue, notify |

- On startup, every `active` queue row is reset to `waiting`. The `.part` file
  on disk is the source of truth for `bytes_done` (truncate to its real size).
- Concurrency: 1 API request at a time with ≥ `request_delay` between them.
  Files: global `max_concurrent_downloads` (default 2), at most 1 per node
  host by default.

### 5.6 Scheduler

- One scheduler thread wakes each minute (or on demand). It picks authors with
  `next_scan_at <= now`, galleries due for recheck, and queue rows with
  `next_attempt_at <= now`.
- Per-author interval: default 6 h, minimum 30 min (enforced, to keep load
  low).
- "Scan now" ignores the interval but **not** host pauses or throttling.
- "Scan on startup" is optional (setting).

## 6. Logging and secrets

- JSON-lines log in `Logs/pawchive.log` with rotation, plus a human-readable
  console/UI log.
- A `RedactingFilter` on every handler masks `Cookie`, `Set-Cookie`,
  `Authorization`, and any known secret value before formatting.
- Event types follow spec §11: `scan.started/finished`, `gallery.discovered`,
  `gallery.empty`, `work.recognized`, `file.queued/completed/failed`,
  `retry.scheduled`, `auth.problem`, `net.error`, `site.structure_changed`.
- "Export diagnostics" zips the logs, the settings without secrets, DB table
  counts, and the app version.

## 7. Spec scenario → component map

| Scenario | Main components | Test style |
|---|---|---|
| A, B, C, E | `title_parser`, `matcher`, `naming`, `organizer` | pure unit + temp-dir integration |
| D | `discovery` | fixture post with no files |
| F | `downloader` | `respx` stream that drops mid-body, then a 206 resume |
| G | `queue`, `migrate`, `db` | close/reopen DB with active rows |
| H | `discovery` fingerprint + SHA-256 dedup | same fixture scanned twice |
| I | `api` + `verify` | thumbnail URL rejected; WebP-in-`.png` rejected; hash checked |
| J | `retry` | 401/403 responses → no retry loop, user-facing event |

## 8. Implementation notes (v1.0)

Decisions taken while implementing and testing, which refine the design above:

- **Scan order.** A scan first collects new or changed posts (the API lists newest first) and
  then processes them **oldest first**. Without this, a recent typo ("A Spectre of Love") would
  become the reference work during the first scan and push all correctly titled older pages into
  review.
- **Incremental stop.** An incremental scan stops after the first page that contains an already
  known, unchanged post. A **full rescan** runs every `full_rescan_days` (default 7) to catch edits
  of old posts, and after any interrupted scan.
- **Held files.** Files of publications waiting for review are downloaded and verified, then kept
  in `Temp/Incomplete/<sha256>.<ext>` (`files.status = held`). No archive folder is created until
  the user decides. Resolving one review resolves every open review with the same proposed key.
- **Streaming.** Files are requested with `Accept-Encoding: identity` and written with
  `iter_raw()`, so every byte received before an interruption is kept and Range offsets match the
  bytes on disk.
- **Duplicates.** A file whose SHA-256 is already archived or queued anywhere is recorded as
  `duplicate` and not downloaded again.
- **Single instance.** A `QLockFile` in the database folder prevents two instances from working
  on the same data.
- **Launcher.** `PawChiveDownloader.pyw` starts the app without a console on Windows, checks the
  Python version and dependencies, and reports problems in a message box. `--version` and
  `--self-test` (used by the release workflow on the packaged application) exit immediately.
- **Pausing.** Pausing the queue sets a per-transfer cancel flag: active transfers stop between two
  chunks, the `.part` file is flushed and fsynced, and the queue row goes back to `waiting`
  without counting an attempt. A timed pause stores `downloads_paused_until` in `app_state`; the
  workers and the UI timer resume the queue when it expires. Files put on hold by the user get the
  queue status `on_hold` and are skipped by `ready()`.
- **Queue order.** Migration `0002_queue_priority.sql` adds `download_queue.priority`; `ready()`
  orders by `priority DESC, attempts, next_attempt_at`. "Move to top" sets `max(priority) + 1`.
- **Speed.** One `BandwidthLimiter` (token bucket, one-second burst) is shared by all transfers, so
  the limit applies to the total speed; it can change while downloads run. A `SpeedMeter` per
  active transfer averages the last four seconds for the speed and time-left columns.
- **Interface text.** Every user-facing string is English source text wrapped in `_()`; the Italian
  catalogue maps it to Italian. Messages stored in the database keep the language that was active
  when they were written; recognition reasons are stored in English and translated when shown.
- **Notifications.** `FILE_COMPLETED` events carry `fresh=True` only for files that were just
  downloaded (not for files moved by a rebuild or a merge). The tray controller groups the events
  of a few seconds into one notification per work, or one summary for several works.

## 9. Open points

- Exact default thresholds for recognition: tuned in stage 6 against the
  fixture corpus.
- Discord servers: out of scope for v1. The URL parser recognizes them and
  explains that they aren't supported.
- Headless mode: not in v1, but possible by design (§1).

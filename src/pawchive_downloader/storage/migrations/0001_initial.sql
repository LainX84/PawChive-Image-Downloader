-- PawChive Image Downloader - initial schema.
-- Timestamps: UTC ISO-8601 text. Archive paths: relative to the archive root.

CREATE TABLE authors (
    id                  INTEGER PRIMARY KEY,
    service             TEXT    NOT NULL,
    creator_id          TEXT    NOT NULL,
    name                TEXT    NOT NULL,
    public_id           TEXT,
    profile_url         TEXT    NOT NULL,
    archive_dir         TEXT    NOT NULL,
    monitoring_enabled  INTEGER NOT NULL DEFAULT 1,
    scan_interval_min   INTEGER,
    status              TEXT    NOT NULL DEFAULT 'idle',
    status_message      TEXT,
    remote_updated      TEXT,
    full_scan_done      INTEGER NOT NULL DEFAULT 0,
    last_full_scan_at   TEXT,
    last_scan_at        TEXT,
    last_success_at     TEXT,
    next_scan_at        TEXT,
    last_scan_summary   TEXT,
    created_at          TEXT    NOT NULL,
    UNIQUE (service, creator_id),
    UNIQUE (archive_dir)
);

CREATE TABLE works (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    display_title       TEXT    NOT NULL,
    work_key            TEXT    NOT NULL,
    series_name         TEXT,
    volume              INTEGER,
    part                INTEGER,
    chapter             INTEGER,
    issue               INTEGER,
    episode             INTEGER,
    archive_dir         TEXT    NOT NULL,
    confidence          REAL    NOT NULL,
    user_confirmed      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    UNIQUE (author_id, work_key),
    UNIQUE (author_id, archive_dir)
);

CREATE TABLE work_aliases (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    alias_key           TEXT    NOT NULL,
    work_id             INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    source              TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    UNIQUE (author_id, alias_key)
);

CREATE TABLE galleries (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    post_id             TEXT    NOT NULL,
    url                 TEXT    NOT NULL,
    title               TEXT    NOT NULL,
    normalized_title    TEXT    NOT NULL,
    parsed_title        TEXT,
    published_at        TEXT,
    edited_at           TEXT,
    has_full            INTEGER NOT NULL,
    file_count          INTEGER NOT NULL,
    fingerprint         TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    status_message      TEXT,
    work_id             INTEGER REFERENCES works(id) ON DELETE SET NULL,
    recheck_count       INTEGER NOT NULL DEFAULT 0,
    first_seen_at       TEXT    NOT NULL,
    last_checked_at     TEXT    NOT NULL,
    next_recheck_at     TEXT,
    UNIQUE (author_id, post_id)
);
CREATE INDEX ix_galleries_status ON galleries(status, next_recheck_at);
CREATE INDEX ix_galleries_work ON galleries(work_id);

CREATE TABLE files (
    id                  INTEGER PRIMARY KEY,
    gallery_id          INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    work_id             INTEGER REFERENCES works(id) ON DELETE SET NULL,
    sha256              TEXT    NOT NULL,
    original_name       TEXT    NOT NULL,
    extension           TEXT    NOT NULL,
    kind                TEXT    NOT NULL,
    server              TEXT    NOT NULL,
    remote_path         TEXT    NOT NULL,
    source_url          TEXT    NOT NULL,
    position            INTEGER NOT NULL,
    page_number         INTEGER,
    target_name         TEXT    NOT NULL,
    local_path          TEXT,
    held_path           TEXT,
    size_bytes          INTEGER,
    status              TEXT    NOT NULL,
    duplicate_of        INTEGER REFERENCES files(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL,
    completed_at        TEXT,
    UNIQUE (gallery_id, sha256)
);
CREATE INDEX ix_files_sha ON files(sha256);
CREATE INDEX ix_files_work ON files(work_id, page_number);
CREATE INDEX ix_files_status ON files(status);

CREATE TABLE download_queue (
    file_id             INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    temp_path           TEXT    NOT NULL,
    host                TEXT    NOT NULL,
    bytes_done          INTEGER NOT NULL DEFAULT 0,
    bytes_total         INTEGER,
    attempts            INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL,
    error_class         TEXT,
    last_error          TEXT,
    next_attempt_at     TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
CREATE INDEX ix_queue_ready ON download_queue(status, next_attempt_at);

CREATE TABLE review_requests (
    id                  INTEGER PRIMARY KEY,
    gallery_id          INTEGER NOT NULL UNIQUE REFERENCES galleries(id) ON DELETE CASCADE,
    proposed_key        TEXT    NOT NULL,
    proposed_title      TEXT    NOT NULL,
    candidates          TEXT    NOT NULL,
    reason              TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'open',
    created_at          TEXT    NOT NULL,
    resolved_at         TEXT
);

CREATE TABLE host_state (
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
    result              TEXT,
    pages_fetched       INTEGER NOT NULL DEFAULT 0,
    new_galleries       INTEGER NOT NULL DEFAULT 0,
    new_files           INTEGER NOT NULL DEFAULT 0,
    message             TEXT
);
CREATE INDEX ix_scan_log_author ON scan_log(author_id, started_at);

CREATE TABLE app_state (
    key                 TEXT    PRIMARY KEY,
    value               TEXT
);

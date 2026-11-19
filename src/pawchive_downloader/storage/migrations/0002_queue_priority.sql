-- Manual ordering of the download queue: higher priority downloads first.
ALTER TABLE download_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
CREATE INDEX ix_queue_priority ON download_queue(priority DESC, attempts, next_attempt_at);

-- Add-only: page_counts for the self-hosted page counter. Idempotent.
CREATE TABLE IF NOT EXISTS page_counts (
  day  TEXT    NOT NULL,                              -- YYYY-MM-DD, UTC
  path TEXT    NOT NULL,                              -- e.g. / or /about.html
  n    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, path)
);

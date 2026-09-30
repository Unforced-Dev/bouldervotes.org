-- bouldervotes-feedback D1 schema. Submissions are stored only; never rendered publicly.
CREATE TABLE IF NOT EXISTS feedback (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at        TEXT    NOT NULL,                 -- ISO 8601 UTC
  kind              TEXT    NOT NULL CHECK (kind IN ('correction', 'suggestion', 'other')),
  page_url          TEXT,
  message           TEXT    NOT NULL,                 -- 10 to 4000 characters
  contact           TEXT,                             -- optional email or name, at most 200
  submitter_type    TEXT    NOT NULL DEFAULT 'person' CHECK (submitter_type IN ('person', 'ai-agent')),
  agent_name        TEXT,
  on_behalf_of_user INTEGER NOT NULL DEFAULT 0,       -- 0/1, agents only
  source_url        TEXT,
  user_agent        TEXT,                             -- truncated
  ip_hash           TEXT    NOT NULL,                 -- SHA-256(ip + SALT); the raw IP is never stored
  status            TEXT    NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'reviewed', 'fixed', 'declined'))
);
CREATE INDEX IF NOT EXISTS feedback_ip_time ON feedback (ip_hash, created_at);
CREATE INDEX IF NOT EXISTS feedback_time    ON feedback (created_at);
CREATE INDEX IF NOT EXISTS feedback_status  ON feedback (status, created_at);

CREATE TABLE IF NOT EXISTS bridge_jobs (
  job_id TEXT PRIMARY KEY CHECK (length(job_id) = 32),
  schema_version INTEGER NOT NULL DEFAULT 1,
  origin TEXT NOT NULL,
  created_by TEXT NOT NULL,
  ai_chat_share_id TEXT,
  external_write INTEGER NOT NULL DEFAULT 0 CHECK (external_write IN (0, 1)),
  request_text TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER))
);
CREATE INDEX IF NOT EXISTS idx_bridge_jobs_share ON bridge_jobs(ai_chat_share_id) WHERE ai_chat_share_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS bridge_job_locks (
  job_id TEXT PRIMARY KEY REFERENCES bridge_jobs(job_id) ON DELETE CASCADE,
  created_by TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'claimed', 'done', 'failed', 'cancelled')),
  claim_token TEXT,
  claimed_by TEXT,
  claimed_at INTEGER,
  lease_until INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  result_path TEXT,
  result_sha256 TEXT,
  last_error TEXT,
  created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
  updated_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER))
);
CREATE INDEX IF NOT EXISTS idx_bridge_job_locks_status ON bridge_job_locks(status, created_at);
CREATE TABLE IF NOT EXISTS bridge_job_results (
  job_id TEXT NOT NULL REFERENCES bridge_jobs(job_id) ON DELETE CASCADE,
  claim_token TEXT NOT NULL,
  result_text TEXT NOT NULL,
  result_sha256 TEXT NOT NULL,
  exit_code INTEGER,
  created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
  PRIMARY KEY (job_id, claim_token)
);
CREATE TABLE IF NOT EXISTS bridge_job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES bridge_jobs(job_id) ON DELETE CASCADE,
  at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
  actor TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('queued', 'claimed', 'released', 'completed', 'failed', 'cancelled', 'note')),
  body TEXT
);
CREATE INDEX IF NOT EXISTS idx_bridge_job_events_job ON bridge_job_events(job_id, id);
CREATE TRIGGER IF NOT EXISTS bridge_job_locks_queued AFTER INSERT ON bridge_job_locks
BEGIN
  INSERT INTO bridge_job_events (job_id, actor, kind) VALUES (NEW.job_id, NEW.created_by, 'queued');
END;
CREATE TRIGGER IF NOT EXISTS bridge_job_locks_changed AFTER UPDATE OF status, claim_token ON bridge_job_locks
WHEN NEW.status IS NOT OLD.status OR NEW.claim_token IS NOT OLD.claim_token
BEGIN
  INSERT INTO bridge_job_events (job_id, actor, kind, body) VALUES (
    NEW.job_id,
    COALESCE(NEW.claimed_by, NEW.created_by),
    CASE NEW.status WHEN 'claimed' THEN 'claimed' WHEN 'done' THEN 'completed' WHEN 'failed' THEN 'failed' WHEN 'cancelled' THEN 'cancelled' ELSE 'released' END,
    CASE WHEN NEW.status = 'claimed' THEN 'attempt ' || NEW.attempts ELSE NEW.last_error END
  );
END;

-- cmdb_migrate_fix.sql (idempotent, safe on empty DB)
BEGIN;

-- 1) Drop legacy view if present (it may point to old columns)
DROP VIEW IF EXISTS routing_summary_legacy;

-- 2) Ensure new canonical table exists (no destructive rename/copy)
CREATE TABLE IF NOT EXISTS routing_summary (
  host TEXT PRIMARY KEY,
  last_collected_at TEXT,
  peers_total INTEGER DEFAULT 0,
  peers_established INTEGER DEFAULT 0,
  ospf_neighbors INTEGER DEFAULT 0,
  status TEXT,
  last_error TEXT
);

-- 3) Recreate legacy-compatibility view mapping to new columns
CREATE VIEW IF NOT EXISTS routing_summary_legacy AS
SELECT
  host,
  last_collected_at,
  peers_total       AS peer_count,
  peers_established AS established_peers,
  ospf_neighbors,
  status,
  last_error
FROM routing_summary;

COMMIT;

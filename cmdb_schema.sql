-- cmdb_schema.sql
-- Generated: 2025-10-05T21:00:09.535511Z
-- SQLite schema for routing CMDB extensions

PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE TRANSACTION;

-- 1) schema_meta: simple versioning
CREATE TABLE IF NOT EXISTS schema_meta(
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL
);

-- 2) objects_ext: our extension storage (idempotent)
CREATE TABLE IF NOT EXISTS objects_ext(
  kind TEXT NOT NULL,
  id   TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY(kind, id)
);

-- 3) objects_all: unified view (assumes existing VIEW/TABLE 'objects' is present)
--    If 'objects' does not exist in your DB, run the fallback block at the end.
DROP VIEW IF EXISTS objects_all;
CREATE VIEW objects_all AS
  SELECT kind, id, data FROM objects
  UNION ALL
  SELECT kind, id, data FROM objects_ext;

-- 4) Routing: BGP peers
CREATE TABLE IF NOT EXISTS routing_bgp_peer(
  host               TEXT NOT NULL,
  peer_ip            TEXT NOT NULL,
  peer_as            INTEGER,
  state              TEXT,
  uptime_sec         INTEGER,
  prefixes_received  INTEGER,
  collected_at       TEXT NOT NULL,
  source             TEXT,
  PRIMARY KEY(host, peer_ip, collected_at)
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_bgp_host ON routing_bgp_peer(host);
CREATE INDEX IF NOT EXISTS idx_bgp_collected ON routing_bgp_peer(collected_at);
CREATE INDEX IF NOT EXISTS idx_bgp_state ON routing_bgp_peer(state);

-- 5) Routing: OSPF neighbors
CREATE TABLE IF NOT EXISTS routing_ospf_neighbor(
  host           TEXT NOT NULL,
  neighbor_id    TEXT NOT NULL,
  iface          TEXT,
  state          TEXT,
  dead_time_raw  TEXT,
  address        TEXT,
  collected_at   TEXT NOT NULL,
  PRIMARY KEY(host, neighbor_id, collected_at)
);

CREATE INDEX IF NOT EXISTS idx_ospf_host ON routing_ospf_neighbor(host);
CREATE INDEX IF NOT EXISTS idx_ospf_collected ON routing_ospf_neighbor(collected_at);

-- 6) Routing summary per host
CREATE TABLE IF NOT EXISTS routing_summary(
  host               TEXT PRIMARY KEY,
  last_collected_at  TEXT,
  peer_count         INTEGER,
  established_peers  INTEGER,
  ospf_neighbors     INTEGER,
  status             TEXT,      -- ok / partial / error
  last_error         TEXT
);

-- 7) Future: change log
CREATE TABLE IF NOT EXISTS routing_change(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  host          TEXT NOT NULL,
  kind          TEXT NOT NULL,        -- bgp_peer | ospf_neighbor
  change_type   TEXT NOT NULL,        -- add | remove | update
  ref           TEXT,
  before_json   TEXT,
  after_json    TEXT,
  detected_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_host_time ON routing_change(host, detected_at);

-- 8) Node metadata
CREATE TABLE IF NOT EXISTS node_meta(
  host   TEXT NOT NULL,
  key    TEXT NOT NULL,
  value  TEXT,
  PRIMARY KEY(host, key)
);

-- Record migration (bump version as needed)
INSERT OR REPLACE INTO schema_meta(version, applied_at)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ','now'));

COMMIT;

-- ---------------------------------------------------------------------------
-- Fallback helper (optional): If your DB does NOT have 'objects', you can use:
--
-- BEGIN;
-- DROP VIEW IF EXISTS objects_all;
-- CREATE VIEW objects_all AS
--   SELECT kind, id, data FROM objects_ext;
-- COMMIT;
--
-- Later, when 'objects' is added, re-run the main section above to UNION ALL.
-- ---------------------------------------------------------------------------

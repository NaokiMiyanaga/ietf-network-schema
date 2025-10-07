-- cmdb_schema.sql (2025-10-06)
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS objects_ext(
  kind TEXT NOT NULL,
  id   TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY(kind,id)
);

CREATE VIEW IF NOT EXISTS objects_all AS
  SELECT kind,id,data FROM objects
  UNION ALL
  SELECT kind,id,data FROM objects_ext;

CREATE TABLE IF NOT EXISTS routing_bgp_peer(
  host TEXT NOT NULL,
  peer_ip TEXT NOT NULL,
  peer_as INTEGER,
  state TEXT,
  uptime_sec INTEGER,
  prefixes_received INTEGER,
  collected_at TEXT,
  source TEXT,
  PRIMARY KEY(host, peer_ip, collected_at)
);

CREATE TABLE IF NOT EXISTS routing_ospf_neighbor(
  host TEXT NOT NULL,
  neighbor_id TEXT,
  iface TEXT,
  state TEXT,
  dead_time_raw TEXT,
  address TEXT,
  collected_at TEXT,
  PRIMARY KEY(host, neighbor_id, collected_at)
);

-- Aggregated stats (safe for older SQLite)
DROP VIEW IF EXISTS routing_bgp_peer_stats;
CREATE VIEW IF NOT EXISTS routing_bgp_peer_stats AS
  SELECT
    host,
    COUNT(*) AS peers_total,
    SUM(CASE WHEN state='Established' OR state='OK' THEN 1 ELSE 0 END) AS peers_established
  FROM routing_bgp_peer
  GROUP BY host;

DROP VIEW IF EXISTS routing_ospf_neighbor_stats;
CREATE VIEW IF NOT EXISTS routing_ospf_neighbor_stats AS
  SELECT
    host,
    COUNT(*) AS ospf_neighbors
  FROM routing_ospf_neighbor
  GROUP BY host;

CREATE TABLE IF NOT EXISTS routing_summary(
  host TEXT PRIMARY KEY,
  last_collected_at TEXT,
  peers_total INTEGER DEFAULT 0,
  peers_established INTEGER DEFAULT 0,
  ospf_neighbors INTEGER DEFAULT 0,
  status TEXT,
  last_error TEXT
);

CREATE VIEW IF NOT EXISTS routing_summary_legacy AS
  SELECT
    host,
    last_collected_at,
    peers_total AS peer_count,
    peers_established AS established_peers,
    ospf_neighbors,
    status,
    last_error
  FROM routing_summary;

CREATE TABLE IF NOT EXISTS schema_meta (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT NOT NULL,
  schema_sha1 TEXT,
  applied_at TEXT NOT NULL,
  applied_by TEXT,
  schema_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_schema_meta_v ON schema_meta(version);

-- === Phase 2.1: ETL reproducibility snapshots & meta (non-destructive) ===
-- NOTE: existing schema_meta(version, applied_at) is kept as-is to avoid breakage.
--       Below are additive tables & indexes for snapshots and diffs.

-- raw_state: original payload per host per run (opaque JSON)
CREATE TABLE IF NOT EXISTS raw_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT NOT NULL,
  host TEXT NOT NULL,
  kind TEXT NOT NULL,         -- 'bgp' or 'ospf'
  payload_json TEXT NOT NULL, -- raw JSON string
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_state_vhk ON raw_state(version, host, kind);

-- normalized_state: flattened rows used for summary/diffs (one row per peer/neighbor)
CREATE TABLE IF NOT EXISTS normalized_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT NOT NULL,
  host TEXT NOT NULL,
  kind TEXT NOT NULL,    -- 'bgp_peer' or 'ospf_neighbor'
  k TEXT NOT NULL,       -- key (e.g., peer IP or neighbor_id)
  v TEXT NOT NULL,       -- normalized JSON per unit
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_norm_state_vhkk ON normalized_state(version, host, kind, k);

-- summary_diff: computed deltas between two versions per host/kind
CREATE TABLE IF NOT EXISTS summary_diff (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  base_version TEXT NOT NULL,
  new_version TEXT NOT NULL,
  host TEXT NOT NULL,
  kind TEXT NOT NULL,
  k TEXT NOT NULL,
  change TEXT NOT NULL,  -- 'added' | 'changed' | 'removed'
  before TEXT,           -- JSON
  after TEXT,            -- JSON
  computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summary_diff_bnhkk ON summary_diff(base_version, new_version, host, kind, k);

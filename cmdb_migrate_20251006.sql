-- 壊さない移行：存在しない場合に備えて順序固定、誤列名は使わない
BEGIN;

-- 旧ビューを先に消す（存在しなくてもOK）
DROP VIEW IF EXISTS routing_summary_legacy;

-- 新テーブル（既にあれば保持）
CREATE TABLE IF NOT EXISTS routing_summary (
  host TEXT PRIMARY KEY,
  last_collected_at TEXT,
  peers_total INTEGER DEFAULT 0,
  peers_established INTEGER DEFAULT 0,
  ospf_neighbors INTEGER DEFAULT 0,
  status TEXT DEFAULT 'ok',
  last_error TEXT DEFAULT ''
);

-- 旧互換ビュー（誤列名をこちらでマッピング）
CREATE VIEW IF NOT EXISTS routing_summary_legacy AS
SELECT
  host,
  last_collected_at AS collected_at,
  peers_total      AS peer_count,
  peers_established AS established_peers,
  ospf_neighbors   AS ospf,
  status,
  last_error
FROM routing_summary;

COMMIT;

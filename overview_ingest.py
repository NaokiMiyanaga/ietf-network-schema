import os, json, re, html, sqlite3, urllib.request

MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:9000/tools/call")
MCP_TOKEN = os.environ["MCP_TOKEN"]
DB = os.environ.get("CMDB_DB", "rag.db")

req_body = {
  "id":"probe_overview",
  "name":"ansible.playbook",
  "arguments":{"playbook":"network_overview"}
}
data = json.dumps(req_body).encode()
req = urllib.request.Request(MCP_URL, data=data,
         headers={"Content-Type":"application/json","Authorization":f"Bearer {MCP_TOKEN}"})
resp = urllib.request.urlopen(req)
payload = json.loads(resp.read())
stdout = payload["result"]["ansible"]["stdout"]

# Ansible の stdout 中に "msg": "<JSON文字列>" が複数ある → 抜く
json_strs = re.findall(r'"msg":\s*"({.*?})"', stdout, flags=re.S)
entries = [json.loads(html.unescape(s)) for s in json_strs]

def as_int(v, default=0):
    try: return int(v)
    except: return default

with sqlite3.connect(DB) as cx:
    cx.execute("PRAGMA journal_mode=WAL")
    # objects が VIEW の環境なので objects_ext に書く
    up_summary = cx.cursor()
    up_raw     = cx.cursor()
    up_bgp     = cx.cursor()

    for e in entries:
        host = e.get("host")
        if not host:
            continue

        # objects_ext: routing.raw （保全用）
        up_raw.execute("""
          INSERT OR REPLACE INTO objects_ext(kind,id,data)
          VALUES('routing.raw', ?, json_object('host',?, 'command','network_overview', 'raw', json(?)))
        """, (f"{host}|network_overview", host, json.dumps(e, ensure_ascii=False)))

        # BGP peers を routing_bgp_peer に反映（あれば）
        peers = (e.get("bgp") or {}).get("peers") or {}
        est = 0
        for ip, p in peers.items():
            state = p.get("state") or p.get("peerState")
            if (state or "").lower() == "established" or state == "OK":
                est += 1
            up_bgp.execute("""
              INSERT OR REPLACE INTO routing_bgp_peer
                (host, peer_ip, peer_as, state, uptime_sec, prefixes_received, collected_at, source)
              VALUES(?, ?, ?, ?, ?, ?, datetime('now'), 'network_overview')
            """, (
              host,
              ip,
              as_int(p.get("remoteAs")),
              state,
              0,
              as_int(p.get("pfxRcd"))
            ))

        # objects_ext: routing.summary
        peer_total = len(peers)
        status = "ok" if peer_total >= 0 else "partial"
        up_summary.execute("""
          INSERT OR REPLACE INTO objects_ext(kind,id,data)
          VALUES('routing.summary', ?, json_object(
            'host', ?, 'bgp', json_object('peers', ?, 'peers_established', ?),
            'ospf', json_object('neighbors', 0),
            'status', ?, 'environment', 'test'
          ))
        """, (host, host, peer_total, est, status))

    cx.commit()
print(f"ingested {len(entries)} overview entries into {DB}")

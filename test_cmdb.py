import os, sqlite3, json, subprocess, pathlib
db = os.environ.get("CMDB_DB", "/app/cmdb-mcp/rag.db")
print(f"db : {db}")
p = pathlib.Path(db)
print(f"parent: {p.parent}")
try:
    res = subprocess.run(["ls", "-la", str(p.parent)], capture_output=True, text=True)
    print(res.stdout)
except Exception as e:
    print(f"[ls error] {e}")
try:
    st = p.stat()
    print(f"file exists: True, size={st.st_size} bytes")
except FileNotFoundError:
    print("file exists: False")
cx = sqlite3.connect(db)
cx.row_factory = sqlite3.Row
cur = cx.cursor()

def show(sql, limit=10):
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    print(f"\nSQL> {sql}\nrows={len(rows)}")
    for r in rows[:limit]:
        print(r)

# スキーマ確認
show("SELECT name,type FROM sqlite_master WHERE name IN ('objects','docs','docs_fts') ORDER BY name")

# objects の内訳
try:
    show("SELECT kind, COUNT(*) AS n FROM objects GROUP BY kind ORDER BY n DESC", limit=100)
    show("SELECT id, kind FROM objects LIMIT 10")
except Exception as e:
    print(f"[objects check error] {e}")

# docs / docs_fts があれば確認
try:
    show("SELECT type, COUNT(*) AS n FROM docs GROUP BY type ORDER BY n DESC", limit=100)
    show("SELECT COUNT(*) AS n FROM docs_fts")
except Exception as e:
    print(f"[docs check error] {e}")

# サンプルでノード詳細（あれば）
for target in ("r1","r2","l2a","l2b","h10","h20"):
    try:
        cur.execute("""
            SELECT id, kind,
                   json_extract(data,'$.mgmt.hostname') AS hostname,
                   json_extract(data,'$.mgmt.ipv4')     AS ipv4,
                   json_extract(data,'$.platform')      AS platform,
                   json_extract(data,'$.classes')       AS classes
            FROM objects WHERE id=?
        """, (target,))
        row = cur.fetchone()
        if row:
            print(f"\n[id={target}] -> {dict(row)}")
    except Exception as e:
        print(f"[detail {target} error] {e}")

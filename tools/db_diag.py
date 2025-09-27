#!/usr/bin/env python3
# /app/cmdb-mcp/tools/db_diag.py
import os, sys, time, sqlite3, pathlib, json

def q(cur, sql):
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        sample = [dict(row) for row in rows[:5]]
        return {"ok": True, "count": len(rows), "sample": sample}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main():
    db = os.environ.get("CMDB_DB", "/app/cmdb-mcp/rag.db")
    p  = pathlib.Path(db)
    info = {
        "CMDB_DB": db,
        "exists": p.exists(),
        "size": (p.stat().st_size if p.exists() else 0),
        "mtime": (time.strftime("%F %T", time.localtime(p.stat().st_mtime)) if p.exists() else None),
    }
    print("=== DB info ===")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    try:
        cx = sqlite3.connect(db)
        cx.row_factory = sqlite3.Row
        cur = cx.cursor()
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"connect fail: {e}"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print("\n=== sqlite_master ===")
    print(json.dumps(q(cur, "SELECT name,type FROM sqlite_master "
                            "WHERE name IN ('objects','docs','docs_fts') ORDER BY name"),
                    ensure_ascii=False, indent=2))

    print("\n=== objects (sample) ===")
    print(json.dumps(q(cur, "SELECT kind,id FROM objects ORDER BY id LIMIT 10"),
                    ensure_ascii=False, indent=2))

    print("\n=== docs (type counts) ===")
    print(json.dumps(q(cur, "SELECT type, COUNT(*) AS cnt FROM docs GROUP BY type ORDER BY cnt DESC LIMIT 10"),
                    ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

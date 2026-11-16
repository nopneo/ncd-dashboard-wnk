"""ดึง HDC ครั้งเดียวเพื่ออุ่นแคชและดูคอลัมน์ (dev) — ใช้: python scripts_warm_hdc.py 2569"""
import sys, json
import hdc
fy = int(sys.argv[1])
for t in hdc.TABLES:
    r = hdc.fetch_table(t, fy, refresh=True, patient=True)
    print(t, fy, "ERR " + r.error if r.error else f"ok stale={r.stale} units={len(r.by_unit)}", json.dumps(r.totals, ensure_ascii=False)[:600], flush=True)

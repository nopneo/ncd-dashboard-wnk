"""ตรวจความพร้อมก่อนใช้งาน NCD Dashboard — รันหลังกรอกค่าฐานข้อมูลใน .env

    python setup_check.py              ตรวจสภาพแวดล้อม + ฐานข้อมูล + Data Audit (ปีงบปัจจุบัน)
    python setup_check.py --no-audit   ข้าม Data Audit (เร็วกว่า)
    python setup_check.py --fy 2569    ตรวจ Data Audit ด้วยปีงบที่ระบุ

อ่านฐานข้อมูลอย่างเดียว ไม่แก้ข้อมูลใน HOSxP · แสดงเฉพาะจำนวนนับ ไม่มีข้อมูลรายคน
ผล ✘ = ต้องแก้ก่อนใช้งาน (exit 1) · ⚠ = ใช้ได้แต่ควรตรวจ · ส่งผลทั้งหมดนี้มาด้วยเมื่อแจ้งปัญหา
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import sys
from datetime import date, datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

#: ตารางที่แดชบอร์ดอ่าน — ไม่มี = หน้าที่ใช้ตารางนั้นล้ม
TABLES = ["ovst", "patient", "opdscreen", "ovstdiag", "iptdiag", "ipt", "lab_head", "lab_order", "lab_items",
          "clinic", "clinicmember", "oapp", "opitemrece", "drugitems", "nondrugitems"]
TABLES_OPTIONAL = ["hospcode"]          # ไม่มีก็ใช้ได้ (ชื่อหน่วยบริการใน HDC จะแสดงเป็นรหัส)
#: สิทธิ์ที่บัญชีอ่านอย่างเดียวมีได้
SAFE_PRIVS = {"SELECT", "USAGE", "SHOW VIEW"}

results = []      # (ระดับ, ข้อความ) — ok / warn / fail / info


def say(level, msg):
    results.append((level, msg))
    print(f"  {({'ok': '✔', 'warn': '⚠', 'fail': '✘', 'info': '·'})[level]} {msg}")


def head(title):
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def risky_privs(grant_lines, dbname=None):
    """บรรทัดผลของ SHOW GRANTS → สิทธิ์ที่เกินกว่าอ่านอย่างเดียว (เช่น INSERT, ALL PRIVILEGES)
    dbname = นับเฉพาะสิทธิ์บนฐานข้อมูลนี้และ *.* (สิทธิ์เขียนบนฐานอื่นไม่กระทบ HOSxP)"""
    out = set()
    for line in grant_lines:
        m = re.match(r"\s*GRANT\s+(.+?)\s+ON\s+(\S+)", line or "", re.I)
        if not m:
            continue
        target = m.group(2).split(".")[0].strip("`'\"")
        if dbname and target not in ("*", dbname):
            continue
        for p in re.sub(r"\(.*?\)", "", m.group(1)).split(","):
            p = p.strip().upper()
            if p and p not in SAFE_PRIVS:
                out.add(p)
        if re.search(r"WITH\s+GRANT\s+OPTION", line, re.I):
            out.add("GRANT OPTION")
    return sorted(out)


def check_env():
    head("1. สภาพแวดล้อมของเครื่อง")
    v = sys.version_info
    say("ok" if v >= (3, 9) else "fail", f"Python {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 9) else " — ต้องใช้ 3.9 ขึ้นไป"))
    for mod, pkg in (("flask", "Flask"), ("pymysql", "PyMySQL"), ("dotenv", "python-dotenv")):
        try:
            __import__(mod)
            say("ok", f"ไลบรารี {pkg}")
        except ImportError:
            say("fail", f"ไม่พบไลบรารี {pkg} — pip install -r requirements.txt")


def check_config():
    head("2. การตั้งค่า")
    import db
    say("info", f"โหมดฐานข้อมูล: {db.MODE} · host {db.DB_HOST}:{db.DB_PORT} · ฐาน {db.DB_NAME}")
    if os.getenv("NCD_DATA_AUDITED") == "1":
        say("info", "NCD_DATA_AUDITED=1 (ซ่อนแถบเตือนแล้ว)")
    else:
        say("warn", "ยังไม่ตั้ง NCD_DATA_AUDITED=1 — หน้าเว็บจะแสดงแถบเตือน \"ตัวเลขยังไม่ได้ตรวจ\" จนกว่าจะตรวจกับรายงานเดิม")


def check_db():
    head("3. ฐานข้อมูล HOSxP")
    import db
    try:
        row = db.fetch_one("select version() v", {})
        say("ok", "เชื่อมต่อได้" + (f" · เซิร์ฟเวอร์ {row['v']}" if row.get("v") else ""))
    except Exception as e:      # noqa: BLE001
        say("fail", f"เชื่อมต่อฐานข้อมูลไม่ได้: {type(e).__name__} {str(e)[:150]}")
        return False
    try:
        lines = [str(next(iter(r.values()))) for r in db.fetch("show grants for current_user()", {})]
        risky = risky_privs(lines, db.DB_NAME)
        say("fail" if risky else "ok", ("บัญชีมีสิทธิ์เกินอ่านอย่างเดียว: " + ", ".join(risky) + " — ใช้บัญชีอ่านอย่างเดียวเท่านั้น")
            if risky else "บัญชีมีสิทธิ์อ่านอย่างเดียว")
    except Exception as e:      # noqa: BLE001
        say("warn", f"ตรวจสิทธิ์ของบัญชีไม่ได้: {type(e).__name__}")
    for t in TABLES:
        try:
            db.fetch(f"select 1 from {t} limit 1", {})
        except Exception as e:  # noqa: BLE001
            say("fail", f"ไม่พบตาราง {t} ({str(e)[:80]})")
    for t in TABLES_OPTIONAL:
        try:
            db.fetch(f"select 1 from {t} limit 1", {})
        except Exception:       # noqa: BLE001
            say("warn", f"ไม่พบตาราง {t} (ไม่บังคับ)")
    if not any(lv == "fail" and "ตาราง" in m for lv, m in results):
        say("ok", f"พบตารางที่ใช้ครบ {len(TABLES)} ตาราง")
    try:
        name = db.fetch_one("select c.name from clinic c where c.name regexp '[ก-๙]' limit 1", {}).get("name")
        thai = bool(name) and re.search(r"[฀-๿]", name) and "?" not in name and "�" not in name
        say("ok" if thai else "fail", "อ่านภาษาไทยได้ถูกต้อง" if thai else "อ่านภาษาไทยไม่ถูกต้อง — ตรวจ charset tis620 ของการเชื่อมต่อ")
    except Exception as e:      # noqa: BLE001
        say("fail", f"ตรวจภาษาไทยไม่ได้: {type(e).__name__}")
    try:
        d = db.fetch_one("select max(vstdate) d from ovst", {}).get("d")
        age = (date.today() - d).days if d else None
        say("ok" if d and age <= 14 else "warn", f"visit ล่าสุด: {d} ({age} วันที่แล้ว)" if d else "ไม่พบข้อมูล visit")
    except Exception as e:      # noqa: BLE001
        say("warn", f"ตรวจ visit ล่าสุดไม่ได้: {type(e).__name__}")
    return True


def check_audit(fy):
    import check
    import periods
    head("4. Data Audit — รหัสของโรงพยาบาลนี้เทียบกับข้อมูลจริง")
    p = periods.make(fy) if fy else periods.parse({}, date.today())
    try:
        rows = check.audit(p)
    except Exception as e:      # noqa: BLE001
        say("fail", f"ตรวจข้อมูลไม่สำเร็จ: {type(e).__name__} {str(e)[:150]}")
        return
    for r in rows:
        if r["status"] == "error":
            say("fail", f"{r['item']}: แอปใช้ {r['app_uses']} → {r['found']}" + (f" · ตั้ง {r['env_hint']}" if r["env_hint"] else ""))
        elif r["status"] == "warn":
            say("warn", f"{r['item']}: แอปใช้ {r['app_uses']} → {r['found']}" + (f" · ตรวจ {r['env_hint']}" if r["env_hint"] else ""))
    ok = sum(1 for r in rows if r["status"] == "ok")
    say("ok", f"ตรงและมีข้อมูล {ok} จาก {len(rows)} รายการ")
    print("      รายละเอียดและวิธีแก้: เปิดหน้า /check ของแดชบอร์ด")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-audit", action="store_true", help="ข้าม Data Audit")
    ap.add_argument("--fy", type=int, default=None, help="ปีงบประมาณ (พ.ศ.) ที่ใช้ตรวจ Data Audit")
    args = ap.parse_args(argv)

    results.clear()
    print(f"NCD Dashboard — ตรวจความพร้อม · {datetime.now():%Y-%m-%d %H:%M} · {platform.platform()}")
    check_env()
    if any(lv == "fail" for lv, _ in results):
        print("\nแก้ข้อ ✘ ด้านบนก่อน แล้วรันใหม่")
        return 1
    check_config()
    if check_db() and not args.no_audit:
        check_audit(args.fy)

    n = {lv: sum(1 for x, _ in results if x == lv) for lv in ("ok", "warn", "fail")}
    head("สรุป")
    print(f"  ✔ {n['ok']} ผ่าน · ⚠ {n['warn']} ควรตรวจ · ✘ {n['fail']} ต้องแก้")
    if n["fail"]:
        print("  ยังไม่พร้อมใช้งาน — แก้ข้อ ✘ แล้วรันใหม่")
    elif n["warn"]:
        print("  ใช้งานได้ แต่ตัวเลขบางส่วนอาจคลาดเคลื่อน — ตรวจข้อ ⚠ และหน้า /check ก่อนใช้จริง")
    else:
        print("  พร้อมใช้งาน — เทียบตัวเลขกับรายงานเดิม 1–2 สัปดาห์ แล้วตั้ง NCD_DATA_AUDITED=1")
    return 1 if n["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())

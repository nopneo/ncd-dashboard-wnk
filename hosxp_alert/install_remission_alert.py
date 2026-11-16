"""ติดตั้งหน้าต่างเตือน DM Remission ใน HOSxP — เพิ่มบล็อกต่อท้าย SYS_VN_SCRIPT เดิม (script เตือน Sepsis ยังทำงานเหมือนเดิม)

คำสั่ง
  preview  --from <ไฟล์ .pas>        สร้าง script ที่รวมแล้วลงไฟล์ (ไม่ต่อฐาน) ไว้ตรวจด้วยตา
  check    --host ... --user ...    อ่านอย่างเดียว: สถานะ script, ติดตั้งแล้วหรือยัง, วันนี้จะเตือนผู้ป่วยกี่ราย
  install  --host ... --user ...    สำรอง script เดิม → รวมบล็อก → เขียน (ต้องพิมพ์ YES) → อ่านกลับตรวจ
  remove   --host ... --user ...    เอาบล็อก DM Remission ออก (ส่วน Sepsis คงเดิม)
  rollback --host ... --user ... --backup <ไฟล์>   คืน script จากไฟล์สำรอง

ลำดับที่ต้องทำ: ติดตั้งฐานทดสอบ (เช่น --db hos_test) → ทดสอบใน HOSxP → จึงติดตั้งฐานจริง
ห้ามติดตั้งบน replica · รหัสผ่านถามแบบซ่อน (หรือ ALERT_DB_PASS เฉพาะหน้าต่างคำสั่งนั้น) ไม่เก็บลงไฟล์ใด ๆ
ถ้าติดตั้ง/อัปเดตตัวเตือน Sepsis ใหม่ (install_alert.py) บล็อกนี้จะหาย — ให้รันคำสั่ง install ของไฟล์นี้ซ้ำ
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from hosxp_alert import remission_alert as ra  # noqa: E402

BACKUPS = os.path.join(HERE, "backups")
SCRIPT_NAME = "SYS_VN_SCRIPT"
SEPSIS_VENDOR = os.path.join(HERE, "..", "..", "sepsis_bundle", "hosxp_alert", "_vendor")


def cfg_from(args) -> ra.Config:
    if getattr(args, "probe", False) and "test" not in (getattr(args, "db", "") or "").lower():
        sys.exit("!! --probe ใช้กับฐานทดสอบเท่านั้น (ขึ้นข้อความทุกครั้งที่บันทึก)")
    return ra.Config(lab=args.lab, drugs=[d.strip() for d in args.drugs.split(",") if d.strip()], pp=args.pp,
                     cut=args.cut, due=args.due, mx=args.max, probe=getattr(args, "probe", False),
                     demo_hn=(getattr(args, "demo_hn", None) or "").strip())


def connect(args):
    try:
        import pymysql
    except ImportError:
        sys.path.insert(0, os.path.abspath(SEPSIS_VENDOR))
        import pymysql
    pw = os.environ.get("ALERT_DB_PASS") or getpass.getpass(f"รหัสผ่าน {args.user}@{args.host} (พิมพ์แล้วไม่แสดง): ")
    if any(ord(ch) > 255 for ch in pw):
        sys.exit("!! รหัสผ่านมีอักษรไทย — สลับแป้นเป็นภาษาอังกฤษแล้วรันใหม่")
    try:
        return pymysql.connect(host=args.host, port=args.port, user=args.user, password=pw, database=args.db,
                               charset="tis620", connect_timeout=10, autocommit=False)
    finally:
        pw = None


def current(cur):
    cur.execute("select app_script_id, script_text, md5(script_text) from sys_app_script where script_name=%s "
                "order by app_script_id", (SCRIPT_NAME,))
    rows = cur.fetchall()
    if len(rows) > 1:
        sys.exit(f"!! มีแถว {SCRIPT_NAME} มากกว่า 1 แถว — ตรวจด้วยตัวเองก่อน")
    return rows[0] if rows else None


def banner(args):
    kind = "ฐานทดสอบ" if "test" in args.db.lower() else "** ฐานจริง **"
    print(f"เป้าหมาย: {args.db} @ {args.host} ({kind})")


def backup(row, args) -> str:
    os.makedirs(BACKUPS, exist_ok=True)
    path = os.path.join(BACKUPS, f"SYS_VN_SCRIPT_{args.db}_{args.host}_{datetime.now():%Y%m%d-%H%M%S}.pas")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(row[1] or "")
    return path


def confirm(args, action):
    if args.yes:
        return
    if input(f"\n{action} บนฐาน {args.db} @ {args.host} — พิมพ์ YES เพื่อยืนยัน: ").strip() != "YES":
        sys.exit("ยกเลิก")


def write(c, cur, row, new_text, args, action):
    path = backup(row, args)
    print("สำรอง script เดิมไว้ที่", path)
    confirm(args, action)
    n = cur.execute("update sys_app_script set script_text=%s, update_date_time=now() where app_script_id=%s and md5(script_text)=%s",
                    (new_text, row[0], row[2]))
    if n != 1:
        c.rollback()
        sys.exit(f"!! เขียนได้ {n} แถว (ต้องเป็น 1) — script อาจถูกแก้ระหว่างนี้ ยกเลิก")
    c.commit()
    after = current(cur)
    ok = after and after[1].replace("\r\n", "\n") == new_text.replace("\r\n", "\n")
    print("เขียนแล้ว — อ่านกลับตรงกับต้นฉบับ" if ok else "!! อ่านกลับไม่ตรง — ให้ rollback ทันที")
    print(f"ย้อนกลับ: python \"{__file__}\" rollback --host {args.host} --db {args.db} --user {args.user} --backup \"{path}\"")


def count_states(cur, cfg) -> dict:
    """วันนี้จะเตือนผู้ป่วยที่ลงทะเบียนกี่ราย (นับอย่างเดียว ไม่แสดง HN)"""
    cur.execute("select distinct s.hn from pp_special s join pp_special_type t on t.pp_special_type_id = s.pp_special_type_id "
                "where t.pp_special_code = %s", (cfg.pp,))
    hns = [r[0] for r in cur.fetchall() if r[0]]
    sql = ra.sqls(cfg)["state"].replace('"{HN}"', "%s")
    out = {0: 0, 10: 0, 20: 0, 30: 0}
    for hn in hns:
        cur.execute(sql, (hn,) * sql.count("%s"))
        out[int(float(cur.fetchone()[0] or 0))] += 1
    return {"registered": len(hns), **out}


def cmd_samples(args):
    """แสดง HN ตัวอย่างกลุ่มละไม่เกิน 3 ราย ไว้ทดสอบใน HOSxP — แสดงบนจอเครื่องนี้เท่านั้น ห้ามคัดลอก/ส่งต่อออกนอก รพ."""
    banner(args)
    cfg = cfg_from(args)
    c = connect(args)
    cur = c.cursor()
    cur.execute("select distinct s.hn from pp_special s join pp_special_type t on t.pp_special_type_id = s.pp_special_type_id "
                "where t.pp_special_code = %s", (cfg.pp,))
    hns = [r[0] for r in cur.fetchall() if r[0]]
    sql = ra.sqls(cfg)["state"].replace('"{HN}"', "%s")
    picks = {0: [], 10: [], 20: [], 30: []}
    for hn in hns:
        cur.execute(sql, (hn,) * sql.count("%s"))
        st = int(float(cur.fetchone()[0] or 0))
        if len(picks[st]) < 3:
            picks[st].append(hn)
        if all(len(v) >= 3 for v in picks.values()):
            break
    names = {10: "เตือน: รอครบ 90 วัน", 20: "เตือน: ถึงช่วงเจาะ", 30: "เตือน: เกิน 180 วัน", 0: "ลงทะเบียนแต่ไม่เตือน"}
    print("** ข้อมูลผู้ป่วย — ใช้ทดสอบบนเครื่องนี้เท่านั้น ห้ามถ่ายภาพ/คัดลอกส่งออกนอก รพ. **")
    for st in (10, 20, 30, 0):
        print(f"{names[st]}: {', '.join(picks[st]) or '-'}")
    c.close()


def cmd_preview(args):
    text = open(args.src, encoding="utf-8", newline="").read()
    new = ra.merge(text, cfg_from(args))
    out = args.out or os.path.splitext(args.src)[0] + "_with_remission.pas"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    print(f"เขียน script ที่รวมแล้ว: {out} ({len(new.splitlines())} บรรทัด · เดิม {len(text.splitlines())})")


def cmd_check(args):
    banner(args)
    c = connect(args)
    cur = c.cursor()
    row = current(cur)
    if not row:
        print("ยังไม่มีแถว SYS_VN_SCRIPT — ติดตั้งตัวเตือน Sepsis ก่อน (install_alert.py) แล้วค่อยเพิ่มบล็อกนี้")
    else:
        print(f"SYS_VN_SCRIPT id {row[0]} · ยาว {len(row[1] or '')} ตัว · md5 {row[2]}")
        print("บล็อก DM Remission:", "ติดตั้งแล้ว" if ra.installed(row[1]) else "ยังไม่ติดตั้ง")
        try:
            ra.merge(row[1], cfg_from(args))
            print("รูปแบบ script: รวมบล็อกได้")
        except ValueError as e:
            print("!! รวมบล็อกไม่ได้:", e)
    s = count_states(cur, cfg_from(args))
    print(f"ผู้ลงทะเบียน {args.pp}: {s['registered']:,} ราย · ถ้าเปิดวันนี้จะเตือน: รอครบ {args.due} วัน {s[10]:,} · "
          f"ถึงช่วงเจาะ {s[20]:,} · เกิน {args.max} วัน {s[30]:,} · ไม่เตือน {s[0]:,}")
    c.close()


def cmd_install(args):
    banner(args)
    c = connect(args)
    cur = c.cursor()
    row = current(cur)
    if not row:
        sys.exit("!! ไม่มีแถว SYS_VN_SCRIPT — ติดตั้งตัวเตือน Sepsis ก่อน")
    try:
        new = ra.merge(row[1], cfg_from(args))
    except ValueError as e:
        sys.exit(f"!! {e}")
    if new.replace("\r\n", "\n") == (row[1] or "").replace("\r\n", "\n"):
        sys.exit("ฉบับนี้ติดตั้งอยู่แล้ว — ไม่ต้องทำอะไร")
    mode = f" (โหมดทดสอบเฉพาะ HN {args.demo_hn})" if getattr(args, "demo_hn", None) else ""
    write(c, cur, row, new, args, ("อัปเดต" if ra.installed(row[1]) else "ติดตั้ง") + "หน้าต่างเตือน DM Remission" + mode)
    print("เปิด HOSxP ใหม่ที่เครื่องทดสอบ แล้วทดสอบตาม README (ข้อความ Sepsis/SOS ต้องยังขึ้นเหมือนเดิม)")
    c.close()


def cmd_remove(args):
    banner(args)
    c = connect(args)
    cur = c.cursor()
    row = current(cur)
    if not row or not ra.installed(row[1]):
        sys.exit("ไม่มีบล็อก DM Remission ใน script — ไม่ต้องทำอะไร")
    write(c, cur, row, ra.strip(row[1]), args, "เอาหน้าต่างเตือน DM Remission ออก")
    c.close()


def cmd_rollback(args):
    banner(args)
    text = open(args.backup, encoding="utf-8", newline="").read()
    c = connect(args)
    cur = c.cursor()
    row = current(cur)
    if not row:
        sys.exit("ไม่มีแถว SYS_VN_SCRIPT")
    write(c, cur, row, text, args, f"คืน SYS_VN_SCRIPT จาก {os.path.basename(args.backup)}")
    c.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="หน้าต่างเตือน DM Remission ใน HOSxP (บล็อกใน SYS_VN_SCRIPT)")
    ap.add_argument("command", choices=["preview", "check", "samples", "install", "remove", "rollback"])
    ap.add_argument("--host")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--db", default="hos")
    ap.add_argument("--user")
    ap.add_argument("--from", dest="src", help="preview: ไฟล์ script เดิม (.pas)")
    ap.add_argument("--out", help="preview: ไฟล์ผลลัพธ์")
    ap.add_argument("--backup", help="rollback: ไฟล์สำรอง")
    d = ra.Config()
    ap.add_argument("--lab", default=d.lab, help=f"lab_items_code ของ HbA1c (ค่าเริ่มต้น {d.lab})")
    ap.add_argument("--drugs", default=",".join(d.drugs), help="icode ยาลดน้ำตาลทุกชนิด คั่นด้วย ,")
    ap.add_argument("--pp", default=d.pp, help=f"pp_special_code ของ NCDs remission clinic (ค่าเริ่มต้น {d.pp})")
    ap.add_argument("--cut", type=float, default=d.cut)
    ap.add_argument("--due", type=int, default=d.due, help="วันขั้นต่ำก่อนเจาะครั้งถัดไป (90)")
    ap.add_argument("--max", type=int, default=d.mx, help="เกินนี้ = เลยช่วง (180)")
    ap.add_argument("--yes", action="store_true", help="ไม่ถาม YES (ใช้กับฐานทดสอบเท่านั้น)")
    ap.add_argument("--probe", action="store_true", help="ฉบับตรวจ: ขึ้นข้อความ RM1-RM4 ทุกขั้น (ฐานทดสอบเท่านั้น)")
    ap.add_argument("--demo-hn", help="ทดสอบบนฐานจริง: ข้อความ RM2-RM4 + บังคับหน้าต่าง DM เฉพาะผู้ป่วยทดสอบ HN นี้ "
                                      "(ผู้ป่วยอื่นทำงานปกติ) — ผ่านแล้วให้ install ซ้ำโดยไม่ใส่ตัวเลือกนี้")
    args = ap.parse_args(argv)
    if args.command == "preview":
        if not args.src:
            ap.error("preview ต้องระบุ --from")
        return cmd_preview(args)
    if not (args.host and args.user):
        ap.error("ต้องระบุ --host และ --user")
    if args.command == "rollback" and not args.backup:
        ap.error("rollback ต้องระบุ --backup")
    {"check": cmd_check, "samples": cmd_samples, "install": cmd_install, "remove": cmd_remove,
     "rollback": cmd_rollback}[args.command](args)


if __name__ == "__main__":
    main()

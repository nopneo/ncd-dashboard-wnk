"""ชั้นเชื่อมต่อฐานข้อมูล HOSxP (อ่านอย่างเดียว) — ยกจาก opd_dashboard

รองรับ 3 โหมด (env NCD_DB_MODE)
  - direct  : ต่อ MariaDB ตรง ๆ ด้วย pymysql อ่านค่าจาก .env (production)
  - ssh     : ยิงคำสั่งผ่าน `ssh <host> mariadb hos` แล้วอ่าน TSV (dev ที่ไม่มีรหัส DB)
  - keyring : ดึง user/รหัสจาก Windows Credential Manager (บริการ "hosdb") — เครื่อง dev เท่านั้น
ข้อมูลใน HOSxP เก็บเป็น tis-620 จึงต้องระบุ charset ให้ถูกทั้งสองทาง

ค่าที่มาจากผู้ใช้ส่งเป็นพารามิเตอร์เสมอ: fetch("... where d = %(d1)s", {"d1": d1})
**ส่ง args เป็น dict เสมอ (แม้ว่าง {})** — pymysql แปลง %% → % เฉพาะเมื่อ args ไม่ใช่ None
เครื่องหมาย % ที่เป็นตัวอักษรใน SQL ต้องเขียน %% (เช่น time_format(x, '%%H:%%i'))
"""
import os
import shlex
import subprocess
import threading
from decimal import Decimal

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

DB_HOST = os.getenv("NCD_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("NCD_DB_PORT", "3306"))
DB_NAME = os.getenv("NCD_DB_NAME", "hos")
DB_USER = os.getenv("NCD_DB_USER", "")
DB_PASS = os.getenv("NCD_DB_PASS", "")
SSH_HOST = os.getenv("NCD_SSH_HOST", "")
#: เวลาสูงสุดต่อคำสั่ง SQL (วินาที) — กัน query ค้างจนกิน worker และภาระของ DB HOSxP
QUERY_TIMEOUT = int(os.getenv("NCD_DB_TIMEOUT", "60"))
MODE = os.getenv("NCD_DB_MODE") or ("ssh" if SSH_HOST and not DB_PASS else "direct")

#: connection ต่อเธรด — ใช้ซ้ำทุกคำสั่งใน request เดียวกัน แล้ว app ปิดตอนจบ request (close())
_local = threading.local()


def _credentials():
    if MODE == "keyring":
        import keyring

        user = keyring.get_password("hosdb", "user")
        pw = keyring.get_password("hosdb", "password")
        if not user or not pw:
            raise RuntimeError("ยังไม่ได้ตั้งค่า Credential Manager (บริการ hosdb)")
        return user, pw
    return DB_USER, DB_PASS


def _conn():
    import pymysql

    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    user, pw = _credentials()
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=user,
        password=pw,
        database=DB_NAME,
        charset="tis620",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=QUERY_TIMEOUT + 5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            # ให้ MariaDB หยุด query เองเมื่อเกินเวลา (MySQL ไม่มีตัวแปรนี้ — ข้ามได้)
            cur.execute(f"set session max_statement_time = {QUERY_TIMEOUT:d}")
    except pymysql.MySQLError:
        pass
    _local.conn = conn
    return conn


def close():
    """ปิด connection ของเธรดนี้ (app เรียกตอนจบทุก request)"""
    conn = getattr(_local, "conn", None)
    _local.conn = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _fetch_direct(sql, args):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    except Exception:
        close()                 # connection อาจเสีย/หมดเวลา — คำสั่งถัดไปเปิดใหม่
        raise


def _bind(sql, args):
    """แทนพารามิเตอร์ลง SQL สำหรับโหมด ssh และ test — escape แบบเดียวกับ pymysql"""
    if args is None:
        return sql
    from pymysql.converters import escape_item

    if isinstance(args, dict):
        return sql % {k: escape_item(v, "utf8") for k, v in args.items()}
    return sql % tuple(escape_item(v, "utf8") for v in args)


def _fetch_ssh(sql, args):
    """รันผ่าน ssh แล้วแปลง TSV กลับเป็น list[dict]"""
    sql = _bind(sql, args)
    remote = (
        "mariadb --default-character-set=tis620 --batch --raw "
        f"{shlex.quote(DB_NAME)} -e {shlex.quote(' '.join(sql.split()))}"
    )
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                           SSH_HOST, remote],
                          capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    text = proc.stdout.decode("tis-620", "replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        rows.append({k: (None if v == "NULL" else v) for k, v in zip(header, cells)})
    return rows


def fetch(sql, args=None):
    rows = _fetch_ssh(sql, args) if MODE == "ssh" else _fetch_direct(sql, args)
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def fetch_one(sql, args=None):
    rows = fetch(sql, args)
    return rows[0] if rows else {}


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def num(v, default=0):
    """แปลงค่าที่ได้จาก DB (อาจเป็น str จากโหมด ssh) ให้เป็นตัวเลขเสมอ"""
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f == int(f) else f

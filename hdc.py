"""ดึงข้อมูลระดับอำเภอจาก HDC (MoPH Open Data) พร้อมแคชในไฟล์ — ปรับจาก health_threat_2569/hdc_sync.py

แหล่ง  : https://opendata.moph.go.th/api/report_data (API สาธารณะ · POST · ไม่ต้องล็อกอิน · ตัวเลขสรุป ไม่มีข้อมูลรายบุคคล)
         ส่งออกเฉพาะ ชื่อตาราง / ปีงบ / รหัสจังหวัด เท่านั้น
พื้นที่ : จังหวัด 30 แล้วเลือกแถวที่ areacode ขึ้นต้นด้วยรหัสอำเภอ (3025 = อ.วังน้ำเขียว) — API กรองอำเภอฝั่งเซิร์ฟเวอร์ไม่ได้
ผลลัพธ์: HdcResult(totals = ผลรวมคอลัมน์ตัวเลขทั้งอำเภอ, by_unit = แยกตามหน่วยบริการ (hospcode), ...)
การทำงาน: **ดึงวันละครั้งแบบเบื้องหลัง** (sync — เธรดอุ่นแคชเรียกทุกรอบ แต่ดึงจริงเฉพาะตารางที่ข้อมูลเก่ากว่า 24 ชม.)
         หน้าเว็บอ่านจากแคชในไฟล์เท่านั้น (get — ไม่เรียก API เลย จึงไม่ค้าง)
ความทนทาน: เรียกไม่สำเร็จ/ตอบผิดรูปแบบ/ไม่พบแถวของอำเภอ → ใช้แคชเดิมต่อ และ **ไม่ทับแคชด้วยข้อมูลว่าง**
         · ปีงบที่เลือกยังไม่มีข้อมูล (HDC ยังไม่ปล่อย) → แสดงข้อมูลล่าสุดที่เคยดึงของปีงบก่อนหน้า พร้อมแจ้งให้รู้ (fallback_fy)
         · ไม่มีแคชเลยสักปี → error (หน้าแสดง "ไม่มีข้อมูล")
คำเตือน: HDC จำกัดความถี่คำขอ (429) — _post เว้นช่วงและถอยรอเอง อย่าเรียกซ้ำถี่ ๆ
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

import config

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.getenv("NCD_HDC_CACHE", os.path.join(HERE, "data", "hdc_cache.json"))
API = "https://opendata.moph.go.th/api/report_data"
PROVINCE = config.get("HDC_PROVINCE", "30")
DISTRICT = config.get("HDC_DISTRICT", "3025")
TTL = timedelta(hours=config.get_float("HDC_TTL_HOURS", 24))       # ดึงใหม่วันละครั้ง
#: เกิน TTL + เวลานี้แล้วยังไม่มีข้อมูลใหม่ = การดึงรอบล่าสุดล้ม → หน้าเว็บขึ้นคำเตือน "ข้อมูลที่ดึงไว้เมื่อ ..."
STALE_GRACE = timedelta(hours=3)
TABLES = ["s_dm_control", "s_ht_control", "s_dm_screen", "s_ht_screen", "s_dm_incidence", "s_ht_incidence",
          "s_ckd_stage_typearea", "s_kpi_ckd_screen", "s_dm_retina_kpi", "s_copd_pop_age", "s_copd_incidence",
          "s_stroke_pop_age", "s_ht_pop_age", "s_dm_pop_age",
          # คลินิกชะลอไตเสื่อม (ระดับ รพ.) + CKD รายใหม่รายหน่วยบริการ
          "s_kpi_ckd_egfr", "s_kpi_ckd_bp", "s_kpi_ckd_acei_arb", "s_kpi_ckd_hb", "s_kpi_ckd_hba1c",
          "s_kpi_ckd_statin", "s_kpi_ckd_upcr", "s_kpi_ckd_incidence",
          "s_dm_remission_coverage",     # DM remission (ตัวชี้วัด 10.2)
          # คัดกรองความเสี่ยง HT/DM · ตรวจเท้า DM · หืด/IHD รายใหม่ · STEMI · CVD risk
          "s_ht_screen_risk", "s_dm_screen_risk", "s_dm_foot", "s_asthma_incidence", "s_ihd_incidence",
          "s_stemi_death", "s_kpi_cvd_risk"]
SKIP = {"id", "flag_sent", "ip", "b_year", "date_com", "__pvcode"}
KEY_COLS = ("hospcode", "areacode", "age_group", "groupcode", "groupname", "yymm")


@dataclass
class HdcResult:
    totals: Dict[str, float] = field(default_factory=dict)
    by_unit: Dict[str, Dict[str, float]] = field(default_factory=dict)
    fetched_at: Optional[str] = None
    stale: bool = False
    error: Optional[str] = None
    fallback_fy: Optional[int] = None      # ไม่มีข้อมูลปีงบที่ขอ → นี่คือปีงบของข้อมูลที่แสดงแทน


#: เรียก HDC ล้มเมื่อไหร่ (ต่อ ตาราง|ปี) — ภายใน FAIL_TTL วินาทีไม่ลองซ้ำ กัน request ค้างทุกครั้งที่เปิดหน้าตอน HDC ล่ม
_FAILED = {}
FAIL_TTL = 120
#: ดึงไม่สำเร็จ (เครือข่าย/429) → sync ลองใหม่เมื่อผ่านไป RETRY_AFTER วินาที · HDC ยังไม่ปล่อยข้อมูลปีงบนั้น (0 แถว) → ถามใหม่ทุก EMPTY_WAIT
_NOROWS = {}
RETRY_AFTER = 3600
EMPTY_WAIT = 24 * 3600


class NoRows(ValueError):
    """HDC ตอบสำเร็จแต่ไม่มีแถวของอำเภอเรา (มักเป็นปีงบที่ยังไม่ปล่อยข้อมูล)"""
#: งบเวลารวมของการดึงหนึ่งตารางตอนเปิดหน้าเว็บ (วินาที) — โหมด patient (สคริปต์อุ่นแคช) ไม่จำกัด
INTERACTIVE_BUDGET = 20


def _post(body, tries=5, timeout=60):
    """เรียก API แบบสุภาพ: เว้นช่วงระหว่างคำขอ และถอยรอเมื่อโดนจำกัดความถี่ (429)"""
    last = None
    for k in range(tries):
        try:
            time.sleep(1.2)
            req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(20 * (k + 1) if e.code == 429 else 3 * (k + 1))
        except Exception as e:      # noqa: BLE001
            last = e
            time.sleep(3 * (k + 1))
    raise last


def _district_rows(table, fy, tries=5, timeout=60, budget=None):
    """แถวของอำเภอ (ตัดชุดซ้ำจากหลายรอบประมวลผล: คงแถวล่าสุดของ หน่วยบริการ+พื้นที่+กลุ่ม)"""
    rows, off = {}, 0
    deadline = None if budget is None else time.monotonic() + budget
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("เกินงบเวลาดึง HDC")
        j = _post({"tableName": table, "year": str(fy), "province": PROVINCE,
                   "type": "json", "limit": 5000, "offset": off}, tries=tries, timeout=timeout)
        if not isinstance(j, dict) or not isinstance(j.get("data"), list):
            raise ValueError("รูปแบบข้อมูลจาก HDC ไม่ถูกต้อง")
        d = j["data"]
        total = int(j.get("total") or 0)
        for x in d:
            if str(x.get("areacode", "")).startswith(DISTRICT):
                k = tuple(x.get(c) for c in KEY_COLS)
                if k not in rows or str(x.get("date_com") or "") >= str(rows[k].get("date_com") or ""):
                    rows[k] = x
        off += len(d)
        if not d or off >= total:
            break
    return list(rows.values())


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _aggregate(rows):
    totals, by_unit = {}, {}
    for x in rows:
        unit = by_unit.setdefault(str(x.get("hospcode") or ""), {})
        for c, v in x.items():
            n = _num(v)
            if c in SKIP or c in KEY_COLS or n is None:
                continue
            totals[c] = totals.get(c, 0.0) + n
            unit[c] = unit.get(c, 0.0) + n
    return totals, by_unit


def _load():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(cache):
    """เขียนแบบ atomic (ไฟล์ชั่วคราว → rename) กัน worker หลายตัวอ่านไฟล์ที่เขียนค้าง"""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _result(entry, stale, hospcode, fallback_fy=None):
    by_unit = entry.get("by_unit", {})
    totals = by_unit.get(hospcode, {}) if hospcode else entry.get("totals", {})
    return HdcResult(totals=dict(totals), by_unit={k: dict(v) for k, v in by_unit.items()},
                     fetched_at=entry.get("fetched_at"), stale=stale, fallback_fy=fallback_fy)


def fetch_table(table: str, fy: int, hospcode: Optional[str] = None, refresh: bool = False, patient: bool = False) -> HdcResult:
    """ดึงจาก API จริง (ใช้ผ่าน sync() หรือสคริปต์อุ่นแคชเท่านั้น — หน้าเว็บใช้ get() ที่อ่านแคช)
    patient=False (ค่าเริ่มต้น, ตอนเปิดหน้าเว็บ): ลองครั้งเดียว timeout สั้น งบเวลารวม 20 วินาที และจำการล้มไว้ 2 นาที
    patient=True (สคริปต์อุ่นแคช/เบื้องหลัง): ลองซ้ำและถอยรอตามปกติ"""
    key = f"{table}|{fy}"
    cache = _load()
    entry = cache.get(key)
    if entry and not refresh:
        try:
            if datetime.now() - datetime.fromisoformat(entry["fetched_at"]) < TTL:
                return _result(entry, False, hospcode)
        except (KeyError, ValueError):
            pass
    try:
        if not patient and time.time() - _FAILED.get(key, 0) < FAIL_TTL:
            raise RuntimeError("เพิ่งดึงไม่สำเร็จ — รอสักครู่ก่อนลองใหม่")
        rows = (_district_rows(table, fy) if patient else _district_rows(table, fy, tries=1, timeout=15, budget=INTERACTIVE_BUDGET))
        if not rows:
            raise NoRows(f"ไม่พบแถวของอำเภอ {DISTRICT}")
        totals, by_unit = _aggregate(rows)
        entry = {"fetched_at": datetime.now().isoformat(timespec="seconds"),
                 "totals": totals, "by_unit": by_unit}
        cache[key] = entry
        _save(cache)
        _FAILED.pop(key, None)
        _NOROWS.pop(key, None)
        return _result(entry, False, hospcode)
    except Exception as e:      # noqa: BLE001 — ล้มทุกกรณี: ใช้แคชเดิม ไม่ทับ
        if isinstance(e, NoRows):
            _NOROWS[key] = time.time()
        elif "เพิ่งดึงไม่สำเร็จ" not in str(e):
            _FAILED[key] = time.time()
        if entry:
            return _result(entry, True, hospcode)
        return HdcResult(error=f"HDC {table} ปี {fy}: ดึงข้อมูลไม่ได้ ({type(e).__name__})")


def _age(entry):
    try:
        return datetime.now() - datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, ValueError, TypeError):
        return None


def get(table: str, fy: int, hospcode: Optional[str] = None, refresh: bool = False) -> HdcResult:
    """อ่านจากแคชในไฟล์เท่านั้น (ไม่เรียก API — ไม่ค้าง) · ข้อมูลใหม่มาจาก sync() วันละครั้ง
    ไม่มีข้อมูลปีงบ fy → ใช้ข้อมูลล่าสุดของปีงบก่อนหน้าที่เคยดึงไว้ (fallback_fy) · ไม่มีเลย → error
    stale=True เมื่อการดึงรอบล่าสุดไม่สำเร็จ (ข้อมูลเก่ากว่า TTL + STALE_GRACE) หรือเป็นข้อมูลของปีงบอื่น"""
    cache = _load()
    entry = cache.get(f"{table}|{fy}")
    if isinstance(entry, dict) and entry.get("by_unit") is not None:
        age = _age(entry)
        return _result(entry, age is None or age >= TTL + STALE_GRACE, hospcode)
    older = []
    for k, v in cache.items():
        name, _sep, y = k.partition("|")
        if name == table and y.isdigit() and int(y) < fy and isinstance(v, dict) and v.get("by_unit") is not None:
            older.append((int(y), v))
    if older:
        y, v = max(older, key=lambda t: t[0])
        return _result(v, True, hospcode, fallback_fy=y)
    return HdcResult(error=f"HDC {table} ปี {fy}: ยังไม่มีข้อมูลที่ดึงไว้")


def sync(fy: int, tables=None) -> dict:
    """ดึงข้อมูลปีงบ fy จาก HDC เข้าแคช — **ดึงจริงเฉพาะตารางที่ถึงกำหนด** (ไม่มีแคช หรือเก่ากว่า TTL = 24 ชม.)
    เรียกจากเธรดเบื้องหลังเท่านั้น (ใช้โหมดอดทน: ลองซ้ำ/ถอยรอเมื่อโดนจำกัดความถี่) · ตารางที่ล้มไม่ทำให้ตารางอื่นหยุด
    คืน dict: ok ดึงสำเร็จ · fresh ยังใหม่อยู่ · empty HDC ยังไม่มีข้อมูลปีนี้ · failed ดึงไม่ได้ · waiting รอรอบหน้า"""
    out = {"ok": [], "fresh": [], "empty": [], "failed": [], "waiting": []}
    for table in (tables or TABLES):
        key = f"{table}|{fy}"
        entry = _load().get(key)
        age = _age(entry) if isinstance(entry, dict) else None
        if age is not None and age < TTL:
            out["fresh"].append(table)
            continue
        now = time.time()
        if now - _NOROWS.get(key, 0) < EMPTY_WAIT or now - _FAILED.get(key, 0) < RETRY_AFTER:
            out["waiting"].append(table)
            continue
        r = fetch_table(table, fy, refresh=True, patient=True)
        if r.error is None and not r.stale:
            out["ok"].append(table)
        elif key in _NOROWS and time.time() - _NOROWS[key] < 60:
            out["empty"].append(table)
        else:
            out["failed"].append(table)
    return out

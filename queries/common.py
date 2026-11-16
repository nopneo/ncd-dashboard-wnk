"""ชั้น query ร่วมของทุกหน้า — SQL บาง ๆ คืน list/dict ธรรมดา · ตรรกะแบ่งกลุ่มอยู่ใน classify.py

ทุกคำสั่งอ่านอย่างเดียว ส่งค่าผ่านพารามิเตอร์เสมอ (args เป็น dict) · เรียกผ่าน db.fetch เพื่อให้ test แทนด้วยตัวปลอมได้
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

import classify
import db
import ui
from periods import Period, months

#: เงื่อนไขสมาชิกทะเบียนคลินิก (alias m) ที่ยังอยู่ในทะเบียนช่วงใดช่วงหนึ่ง:
#: ลงทะเบียนก่อนสิ้นช่วง และไม่ได้จำหน่าย (discharge='Y') ก่อนเริ่มช่วง
MEMBER_COND = ("m.clinic = %(clinic)s and (m.regdate is null or m.regdate <= %(end)s) "
               "and not (m.discharge = 'Y' and coalesce(m.dchdate, '9999-12-31') < %(start)s)")
MEMBER_SUBQUERY = f"select m.hn from clinicmember m where {MEMBER_COND}"
CHUNK = 500


def today() -> date:
    return date.today()


def _mp(clinic, start, end, **extra) -> dict:
    d = {"clinic": clinic, "start": start, "end": end}
    d.update(extra)
    return d


def _n(row, key="n") -> int:
    return int(db.num(row.get(key), 0))


def _in(prefix: str, values) -> Tuple[str, dict]:
    """(%(p0)s, %(p1)s, ...) และพารามิเตอร์ที่ตรงกัน"""
    params = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return ", ".join(f"%({k})s" for k in params), params


# --- ทะเบียนและ visit -------------------------------------------------------

def registry_count(clinic: str, p: Period) -> int:
    row = db.fetch_one(f"select count(distinct m.hn) n from clinicmember m where {MEMBER_COND}",
                       _mp(clinic, p.start, p.end))
    return _n(row)


def registry_hns(clinic: str, p: Period) -> List[str]:
    rows = db.fetch(f"select m.hn from clinicmember m where {MEMBER_COND} group by m.hn",
                    _mp(clinic, p.start, p.end))
    return [r["hn"] for r in rows]


def visit_count(clinic: str, p: Period) -> int:
    row = db.fetch_one(f"select count(*) n from ovst o where o.vstdate between %(start)s and %(end)s "
                       f"and o.hn in ({MEMBER_SUBQUERY})", _mp(clinic, p.start, p.end))
    return _n(row)


def visited_patients(clinic: str, p: Period) -> int:
    row = db.fetch_one(f"select count(distinct o.hn) n from ovst o where o.vstdate between %(start)s and %(end)s "
                       f"and o.hn in ({MEMBER_SUBQUERY})", _mp(clinic, p.start, p.end))
    return _n(row)


def visited_hns(clinic: str, p: Period) -> Set[str]:
    rows = db.fetch("select distinct o.hn from ovst o where o.vstdate between %(start)s and %(end)s "
                    f"and o.hn in ({MEMBER_SUBQUERY})", _mp(clinic, p.start, p.end))
    return {r["hn"] for r in rows}


def monthly_visits(clinic: str, p: Period) -> List[int]:
    rows = db.fetch("select date_format(o.vstdate, '%%Y-%%m') ym, count(*) n from ovst o "
                    "where o.vstdate between %(start)s and %(end)s "
                    f"and o.hn in ({MEMBER_SUBQUERY}) group by date_format(o.vstdate, '%%Y-%%m')",
                    _mp(clinic, p.start, p.end))
    by = {r["ym"]: _n(r) for r in rows}
    return [by.get(d.strftime("%Y-%m"), 0) for d, _label in months(p)]


def new_members_by_month(clinic: str, p: Period) -> List[int]:
    """ผู้ป่วยขึ้นทะเบียนใหม่รายเดือน (clinicmember.regdate) เรียงตาม periods.months"""
    rows = db.fetch("select date_format(m.regdate, '%%Y-%%m') ym, count(*) n from clinicmember m "
                    "where m.clinic = %(clinic)s and m.regdate between %(start)s and %(end)s "
                    "group by date_format(m.regdate, '%%Y-%%m')", _mp(clinic, p.start, p.end))
    by = {r["ym"]: _n(r) for r in rows}
    return [by.get(d.strftime("%Y-%m"), 0) for d, _label in months(p)]


def daily_counts(clinic: str, p: Period, lab_codes=None) -> Optional[dict]:
    """วันล่าสุด (ภายใน 30 วันก่อนสิ้นช่วง/วันนี้) ที่มีผู้รับบริการ: {date, visits, labs}"""
    asof = min(p.end, today())
    params = _mp(clinic, p.start, p.end, since=asof - timedelta(days=30), asof=asof)
    row = db.fetch_one("select o.vstdate d, count(*) visits from ovst o "
                       "where o.vstdate between %(since)s and %(asof)s "
                       f"and o.hn in ({MEMBER_SUBQUERY}) group by o.vstdate order by o.vstdate desc limit 1", params)
    if not row:
        return None
    out = {"date": row["d"], "visits": _n(row, "visits"), "labs": None}
    if lab_codes:
        ph, lp = _in("l", list(lab_codes))
        lp.update(params, day=row["d"])
        lrow = db.fetch_one("select count(distinct h.hn) n from lab_head h "
                            "join lab_order o on o.lab_order_number = h.lab_order_number "
                            f"where o.lab_items_code in ({ph}) and h.order_date = %(day)s "
                            f"and h.hn in ({MEMBER_SUBQUERY})", lp)
        out["labs"] = _n(lrow)
    return out


def followup_hns(clinic: str, p: Period, on: date) -> Dict[str, Set[str]]:
    """ขาดนัด >3 เดือน และนัดที่เลยกำหนด ณ วันที่ on — เฉพาะสมาชิกของทะเบียนในช่วง p (MEMBER_COND เดียวกับตัวหาร)

    อิง ovst/oapp (clinicmember.lastvisit และ next_app_date ไม่ถูกอัปเดตใน HOSxP จึงเชื่อไม่ได้) และนับ visit เฉพาะถึงวัน on
    (ช่วงในอดีต: visit หลังสิ้นช่วงต้องไม่ลบการขาดนัด ณ สิ้นช่วง)
      lost_3m = ไม่มี visit ใดเลยใน 90 วันก่อน on
      overdue = มีนัดที่ครบกำหนดใน 180 วันก่อน on แต่ไม่มี visit ตั้งแต่วันนัดจนถึง on
    """
    params = _mp(clinic, p.start, p.end, today=on, lost=on - timedelta(days=90), since=on - timedelta(days=180))
    lost = db.fetch(f"select distinct m.hn from clinicmember m where {MEMBER_COND} "
                    "and not exists (select 1 from ovst o where o.hn = m.hn and o.vstdate between %(lost)s and %(today)s)", params)
    late = db.fetch(f"select distinct m.hn from clinicmember m where {MEMBER_COND} "
                    "and exists (select 1 from oapp a where a.hn = m.hn and a.nextdate >= %(since)s and a.nextdate < %(today)s "
                    "and not exists (select 1 from ovst o where o.hn = a.hn and o.vstdate >= a.nextdate and o.vstdate <= %(today)s))", params)
    return {"lost_3m": {r["hn"] for r in lost}, "overdue": {r["hn"] for r in late}}


def followup_gaps(clinic: str, p: Period, on: date) -> dict:
    h = followup_hns(clinic, p, on)
    return {"lost_3m": len(h["lost_3m"]), "overdue": len(h["overdue"])}


# --- lab ------------------------------------------------------------------

def _lab_rows(item_codes, clinic, start, end):
    codes = list(item_codes) if isinstance(item_codes, (list, tuple, set)) else [item_codes]
    ph, params = _in("l", codes)
    member = f" and h.hn in ({MEMBER_SUBQUERY})" if clinic else ""
    params.update(start=start, end=end)
    if clinic:
        params["clinic"] = clinic
    return db.fetch("select h.hn, o.lab_order_result result, h.order_date d "
                    "from lab_head h join lab_order o on o.lab_order_number = h.lab_order_number "
                    f"where o.lab_items_code in ({ph}) and h.order_date between %(start)s and %(end)s"
                    + member + " order by h.hn, h.order_date, h.lab_order_number", params)


def latest_lab_by_hn(item_code, clinic: Optional[str], p: Period, allow_zero: bool = False) -> List[dict]:
    """ผล lab ล่าสุด **ที่อ่านเป็นตัวเลขได้** ของแต่ละ HN ในช่วง · ไม่มีผลที่อ่านได้ → value=None"""
    latest: Dict[str, dict] = {}
    for r in sorted(_lab_rows(item_code, clinic, p.start, p.end), key=lambda r: (r["hn"], r["d"])):
        v = classify.parse_result(r["result"], allow_zero)
        cur = latest.get(r["hn"])
        if v is not None or cur is None:
            latest[r["hn"]] = {"hn": r["hn"], "value": v, "date": r["d"]}
    return list(latest.values())


def lab_series_by_hn(item_code, clinic: Optional[str], start: date, end: date,
                     allow_zero: bool = False) -> Dict[str, List[Tuple[date, float]]]:
    out: Dict[str, List[Tuple[date, float]]] = {}
    for r in sorted(_lab_rows(item_code, clinic, start, end), key=lambda r: (r["hn"], r["d"])):
        v = classify.parse_result(r["result"], allow_zero)
        if v is not None:
            out.setdefault(r["hn"], []).append((r["d"], v))
    return out


# --- รหัสโรค / ยา -----------------------------------------------------------

def icd_hns(prefixes: List[str], p: Period, clinic: Optional[str] = None) -> Set[str]:
    """HN ไม่ซ้ำที่ได้รับ diagnosis ขึ้นต้นด้วย prefix ใดก็ได้ (OPD + IPD) ในช่วง

    IPD เอา HN จาก ipt (iptdiag.hn ว่างราวครึ่งหนึ่งของแถวใน HOSxP นี้ — ถ้าใช้ d.hn ผู้ป่วยใน admit จะหายไป) · ตัด HN ว่าง
    """
    if not prefixes:
        return set()
    params = {f"i{k}": pre + "%" for k, pre in enumerate(prefixes)}
    ors = " or ".join(f"d.icd10 like %(i{k})s" for k in range(len(prefixes)))
    params.update(start=p.start, end=p.end)
    opd_member = ipd_member = ""
    if clinic:
        params["clinic"] = clinic
        opd_member = f" and d.hn in ({MEMBER_SUBQUERY})"
        ipd_member = f" and i.hn in ({MEMBER_SUBQUERY})"
    opd = db.fetch("select distinct d.hn from ovstdiag d where d.vstdate between %(start)s and %(end)s "
                   f"and ({ors}){opd_member}", params)
    ipd = db.fetch("select distinct i.hn from iptdiag d join ipt i on i.an = d.an "
                   "where coalesce(i.dchdate, i.regdate) between %(start)s and %(end)s "
                   f"and ({ors}){ipd_member}", params)
    return {r["hn"] for r in opd + ipd if r.get("hn")}


def drug_monthly_visits(icodes: List[str], p: Period) -> List[int]:
    """จำนวนครั้ง (vn ไม่ซ้ำ) ที่ได้รับยาตามรหัส รายเดือน เรียงตาม periods.months"""
    if not icodes:
        return [0] * len(months(p))
    ph, params = _in("c", icodes)
    params.update(start=p.start, end=p.end)
    rows = db.fetch("select date_format(r.vstdate, '%%Y-%%m') ym, count(distinct r.vn) n from opitemrece r "
                    f"where r.icode in ({ph}) and r.vstdate between %(start)s and %(end)s "
                    "group by date_format(r.vstdate, '%%Y-%%m')", params)
    by = {r["ym"]: _n(r) for r in rows}
    return [by.get(d.strftime("%Y-%m"), 0) for d, _label in months(p)]


def icd_admissions(prefixes: List[str], p: Period) -> int:
    """จำนวนการ Admit (an ไม่ซ้ำ) ที่มี diagnosis ขึ้นต้นด้วย prefix ใดก็ได้ในช่วง"""
    if not prefixes:
        return 0
    params = {f"i{k}": pre + "%" for k, pre in enumerate(prefixes)}
    ors = " or ".join(f"d.icd10 like %(i{k})s" for k in range(len(prefixes)))
    params.update(start=p.start, end=p.end)
    row = db.fetch_one("select count(distinct d.an) n from iptdiag d join ipt i on i.an = d.an "
                       f"where coalesce(i.dchdate, i.regdate) between %(start)s and %(end)s and ({ors})", params)
    return _n(row)


def icd_admission_rows(prefixes: List[str], p: Period) -> List[dict]:
    """การ Admit (an ไม่ซ้ำ) ที่มี diagnosis ขึ้นต้นด้วย prefix ใดก็ได้ในช่วง: hn, regdate, dchdate (ใช้คำนวณ Admit ซ้ำ)"""
    if not prefixes:
        return []
    params = {f"i{k}": pre + "%" for k, pre in enumerate(prefixes)}
    ors = " or ".join(f"d.icd10 like %(i{k})s" for k in range(len(prefixes)))
    params.update(start=p.start, end=p.end)
    return db.fetch("select distinct i.an, i.hn, i.regdate, i.dchdate from iptdiag d join ipt i on i.an = d.an "
                    f"where coalesce(i.dchdate, i.regdate) between %(start)s and %(end)s and ({ors})", params)


def icd_deaths(prefixes: List[str], statuses: List[str], p: Period) -> int:
    """จำนวนการ Admit (an ไม่ซ้ำ) ที่มี diagnosis ตามรหัสและจำหน่ายด้วยสถานะ 'ตาย' (ipt.dchstts)"""
    if not prefixes or not statuses:
        return 0
    params = {f"i{k}": pre + "%" for k, pre in enumerate(prefixes)}
    ors = " or ".join(f"d.icd10 like %(i{k})s" for k in range(len(prefixes)))
    sph, sp = _in("s", statuses)
    params.update(sp, start=p.start, end=p.end)
    row = db.fetch_one("select count(distinct d.an) n from iptdiag d join ipt i on i.an = d.an "
                       f"where coalesce(i.dchdate, i.regdate) between %(start)s and %(end)s and i.dchstts in ({sph}) "
                       f"and ({ors})", params)
    return _n(row)


def visited_among(hns: List[str], p: Period) -> Set[str]:
    """ใน hns ใครมี visit (ovst) ในช่วงบ้าง"""
    out: Set[str] = set()
    hns = list(hns)
    for i in range(0, len(hns), CHUNK):
        ph, params = _in("h", hns[i:i + CHUNK])
        params.update(start=p.start, end=p.end)
        for r in db.fetch("select distinct o.hn from ovst o where o.vstdate between %(start)s and %(end)s "
                          f"and o.hn in ({ph})", params):
            out.add(r["hn"])
    return out


def bp_latest_for_hns(hns: List[str], p: Period) -> Dict[str, Tuple[float, float]]:
    """HN → (sbp, dbp) ล่าสุดที่ valid ในช่วง (ไม่มีค่าที่ valid → ไม่อยู่ในผลลัพธ์)"""
    latest: Dict[str, Tuple] = {}
    hns = list(hns)
    for i in range(0, len(hns), CHUNK):
        ph, params = _in("h", hns[i:i + CHUNK])
        params.update(start=p.start, end=p.end)
        rows = db.fetch("select s.hn, s.bps sbp, s.bpd dbp, s.vstdate d from opdscreen s "
                        "where s.vstdate between %(start)s and %(end)s and s.bps is not null "
                        f"and s.hn in ({ph})", params)
        for r in sorted(rows, key=lambda r: (r["hn"], r["d"])):
            if classify.valid_bp(r["sbp"], r["dbp"]):
                latest[r["hn"]] = (r["sbp"], r["dbp"])
    return latest


def drug_hns(icodes: List[str], clinic: Optional[str], p: Period) -> Set[str]:
    """HN ไม่ซ้ำที่ได้รับยาตามรหัส (opitemrece) ในช่วง · ระบุ clinic → เฉพาะผู้ในทะเบียนช่วงนั้น

    ตัดกับทะเบียนใน Python แทน `hn IN (subquery)` เพราะ opitemrece ใหญ่มาก (แบบ subquery ช้าราว 15 วินาที)
    """
    if not icodes:
        return set()
    ph, params = _in("c", icodes)
    params.update(start=p.start, end=p.end)
    rows = db.fetch(f"select distinct r.hn from opitemrece r where r.icode in ({ph}) "
                    "and r.vstdate between %(start)s and %(end)s", params)
    hns = {r["hn"] for r in rows}
    return hns & set(registry_hns(clinic, p)) if clinic else hns


def drug_dates_by_hn(icodes: List[str], hns, start: date, end: date) -> Dict[str, List[date]]:
    """HN → วันที่ได้รับยาตามรหัส (opitemrece รวม OPD/IPD) เฉพาะ HN ที่ระบุ"""
    out: Dict[str, List[date]] = {}
    hns = list(hns)
    if not icodes:
        return out
    for i in range(0, len(hns), CHUNK):
        ph, params = _in("h", hns[i:i + CHUNK])
        cph, cparams = _in("c", icodes)
        params.update(cparams, start=start, end=end)
        for r in db.fetch(f"select distinct r.hn, r.vstdate d from opitemrece r where r.icode in ({cph}) "
                          f"and r.vstdate between %(start)s and %(end)s and r.hn in ({ph})", params):
            out.setdefault(r["hn"], []).append(r["d"])
    return out


def pp_special_hns(codes: List[str], p: Period) -> Set[str]:
    """HN ที่มีรหัสกิจกรรมส่งเสริมป้องกัน (pp_special) ตามรหัสในช่วง — เช่น 1I20 เข้าร่วม NCDs remission clinic"""
    if not codes:
        return set()
    ph, params = _in("c", codes)
    params.update(start=p.start, nxt=p.end + timedelta(days=1))
    rows = db.fetch("select distinct s.hn from pp_special s join pp_special_type t on t.pp_special_type_id = s.pp_special_type_id "
                    f"where t.pp_special_code in ({ph}) and s.entry_datetime >= %(start)s and s.entry_datetime < %(nxt)s", params)
    return {r["hn"] for r in rows}


def pp_special_first_dates(codes: List[str]) -> Dict[str, date]:
    """HN → วันที่บันทึกรหัสกิจกรรมครั้งแรก (ทุกช่วงเวลา) — ใช้เป็นวันลงทะเบียน NCDs remission clinic"""
    if not codes:
        return {}
    ph, params = _in("c", codes)
    rows = db.fetch("select s.hn, date(min(s.entry_datetime)) d from pp_special s "
                    "join pp_special_type t on t.pp_special_type_id = s.pp_special_type_id "
                    f"where t.pp_special_code in ({ph}) group by s.hn", params)
    return {r["hn"]: r["d"] for r in rows if r.get("hn") and r.get("d")}


# --- ประชากร / หน่วยบริการ -----------------------------------------------------

def demographics(hns: List[str], on: Optional[date] = None) -> Dict[str, Tuple[Optional[str], Optional[int]]]:
    """HN → (เพศ '1'/'2', อายุ ณ วันที่ on) · HN ที่ไม่พบในตาราง patient จะไม่อยู่ในผลลัพธ์"""
    on = on or today()
    out: Dict[str, Tuple[Optional[str], Optional[int]]] = {}
    hns = list(hns)
    for i in range(0, len(hns), CHUNK):
        ph, params = _in("h", hns[i:i + CHUNK])
        for r in db.fetch(f"select p.hn, p.sex, p.birthday from patient p where p.hn in ({ph})", params):
            b = r.get("birthday")
            age = None if b is None else on.year - b.year - ((on.month, on.day) < (b.month, b.day))
            out[r["hn"]] = (r.get("sex"), age)
    return out


def patient_rows(hns, p: Period, on: Optional[date] = None) -> Dict[str, dict]:
    """HN → {name, age, last_visit} สำหรับหน้ารายชื่อ (เปิดเฉพาะ LAN ของ รพ.) · last_visit = มารับบริการล่าสุดในช่วง"""
    on = on or today()
    out: Dict[str, dict] = {}
    hns = list(hns)
    for i in range(0, len(hns), CHUNK):
        ph, params = _in("h", hns[i:i + CHUNK])
        for r in db.fetch(f"select p.hn, p.pname, p.fname, p.lname, p.birthday from patient p where p.hn in ({ph})", params):
            b = r.get("birthday")
            name = f"{r.get('pname') or ''}{r.get('fname') or ''} {r.get('lname') or ''}".strip()
            out.setdefault(r["hn"], {}).update(
                name=name, age=None if b is None else on.year - b.year - ((on.month, on.day) < (b.month, b.day)))
        params.update(start=p.start, end=p.end)
        for r in db.fetch("select o.hn, max(o.vstdate) d from ovst o where o.vstdate between %(start)s and %(end)s "
                          f"and o.hn in ({ph}) group by o.hn", params):
            out.setdefault(r["hn"], {})["last_visit"] = r["d"]
    return out


def short_unit_name(name: str) -> str:
    """ย่อชื่อหน่วยบริการให้พอดีตาราง: โรงพยาบาลส่งเสริมสุขภาพตำบล → รพ.สต. (ชื่ออื่นคงเดิม)"""
    return re.sub(r"โรงพยาบาลส่งเสริมสุขภาพตำบล\s*", "รพ.สต.", name).strip()


def hospital_names(codes: List[str]) -> Dict[str, str]:
    codes = sorted({str(c) for c in codes})
    names = {c: c for c in codes}
    if codes:
        ph, params = _in("c", codes)
        for r in db.fetch(f"select h.hospcode, h.name from hospcode h where h.hospcode in ({ph})", params):
            if r.get("name"):
                names[str(r["hospcode"])] = short_unit_name(str(r["name"]))
    return names


# --- ตรรกะแยกกลุ่ม (ฟังก์ชันบริสุทธิ์) -------------------------------------------

def age_group(age: Optional[int]) -> str:
    if age is None:
        return "ไม่ระบุ"
    if age < 40:
        return "<40"
    if age < 60:
        return "40-59"
    return "60-79" if age < 80 else "80+"


_SEX = {"1": "ชาย", "2": "หญิง"}
_ORDER = {"sex": ["ชาย", "หญิง", "ไม่ระบุ"], "age": ["<40", "40-59", "60-79", "80+", "ไม่ระบุ"]}


def control_by_group(rows: List[dict], demo: dict, key: str) -> List[dict]:
    """ตารางควบคุมได้แยกเพศ (key='sex') หรือกลุ่มอายุ (key='age')

    rows = [{"hn", "status"}] ของ**ทุกคนในทะเบียน** (status ว่าง = ไม่มีค่า นับในตัวหาร) · HN ที่ไม่มีข้อมูลประชากร → "ไม่ระบุ"
    """
    tot: Dict[str, int] = {}
    ctl: Dict[str, int] = {}
    for r in rows:
        sex, age = demo.get(r["hn"], (None, None))
        g = _SEX.get(sex, "ไม่ระบุ") if key == "sex" else age_group(age)
        tot[g] = tot.get(g, 0) + 1
        if r["status"] == "controlled":
            ctl[g] = ctl.get(g, 0) + 1
    return [{"group": g, "total": tot[g], "controlled": ctl.get(g, 0), "pct": ui.pct(ctl.get(g, 0), tot[g])}
            for g in _ORDER[key] if g in tot]


def group_table(clinic: str, p: Period, status_by_hn: dict, key: str, what: str) -> dict:
    """ตาราง "<what> แยกตามเพศ/กลุ่มอายุ" ของทุกคนในทะเบียน (status 'controlled' = ผ่านเกณฑ์ · ไม่มีค่า = นับในตัวหาร)"""
    hns = registry_hns(clinic, p)
    rows = [{"hn": hn, "status": status_by_hn.get(hn)} for hn in hns]
    demo = demographics(hns, on=min(p.end, today()))
    label = "เพศ" if key == "sex" else "กลุ่มอายุ"
    return {"type": "table", "title": f"{what}แยกตาม{label}",
            "columns": [label, "ผู้ป่วยในทะเบียน", "ผ่านเกณฑ์", "ร้อยละ"],
            "rows": [[g["group"], ui.fmt_int(g["total"]), ui.fmt_int(g["controlled"]), ui.fmt_pct(g["pct"])]
                     for g in control_by_group(rows, demo, key)]}

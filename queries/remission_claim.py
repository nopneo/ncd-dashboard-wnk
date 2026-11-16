"""เกณฑ์การเบิกงบบริการ DM Remission (กรอบแนวทาง "สิ่งที่ส่งมาด้วย ๒") — รายการติดตามรายคน ณ วันนี้

ผู้ป่วย = ผู้ที่เคยมีรหัสกิจกรรม 1I20 (วันลงทะเบียน = 1I20 ครั้งแรก) · ผล HbA1c / ยาลดน้ำตาลจาก HOSxP
  ครั้งที่ 1 : HbA1c <6.5 หลังลงทะเบียน และ
               - ไม่เคยได้ยาลดน้ำตาลก่อนหน้า → ห่างจากลงทะเบียน ≥180 วัน (Intensive lifestyle)
               - เคยได้ยา → หยุดยามาแล้ว ≥90 วัน
  ครั้งที่ 2 : ห่างจากครั้งที่ 1 ≥90 วัน (เพดานตั้งได้) ผลระหว่างนั้นต้อง <6.5 และไม่มียา → Successful case (4,000)
               มีผล ≥6.5 หรือได้ยาระหว่างนั้น → เริ่มจับคู่ใหม่
  ครั้งที่ 3 : ห่างจากครั้งที่ 2 90–180 วัน ยัง <6.5 ไม่มียา → Maintenance case (2,000) · ครั้งเดียว
ตัวเลข/รายชื่อใช้ติดตามงาน — การเบิกจริงยึดผลตรวจสอบของ สปสช./HDC
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import config
import ui
from queries import common

Point = Tuple[date, float]

#: สถานะ → (ชื่อเต็ม, ข้อความสั้น) เรียงตามความเร่งด่วนของงาน
STATUSES = [
    ("due2", "ถึงกำหนดเจาะ HbA1c ครั้งที่ 2 (ถ้า <6.5 เบิก Successful case)", "ถึงกำหนดเจาะครั้งที่ 2"),
    ("due3", "ถึงช่วงเจาะ HbA1c ครั้งที่ 3 (ถ้า <6.5 เบิก Maintenance case)", "ถึงช่วงเจาะครั้งที่ 3"),
    ("wait2", "มีผล HbA1c ครั้งที่ 1 แล้ว รอครบกำหนดเจาะครั้งที่ 2 (ห้ามสั่งยาลดน้ำตาล)", "รอครบกำหนดครั้งที่ 2"),
    ("wait3", "เข้าสู่ระยะสงบแล้ว รอช่วงเจาะครั้งที่ 3 (ห้ามสั่งยาลดน้ำตาล)", "รอช่วงเจาะครั้งที่ 3"),
    ("need1", "ครบเกณฑ์แล้ว แต่ยังไม่มีผล HbA1c <6.5 ที่นับเป็นครั้งที่ 1", "ยังไม่มีผลครั้งที่ 1"),
    ("wait1", "ยังไม่ครบ lifestyle 180 วัน / หยุดยา 90 วัน ก่อนเจาะครั้งที่ 1", "ยังไม่ครบเกณฑ์ก่อนครั้งที่ 1"),
    ("on_drug", "ยังได้รับยาลดน้ำตาล (ภายใน 90 วัน)", "ยังได้รับยา"),
    ("maint_done", "สำเร็จทั้ง Successful + Maintenance", "สำเร็จ + Maintenance"),
    ("success", "สำเร็จ (Successful case) · หมดสิทธิ์ Maintenance", "สำเร็จ (ไม่ได้ Maintenance)"),
]
LABEL = {k: (full, short) for k, full, short in STATUSES}
_MEMO: Dict[tuple, tuple] = {}
TTL = 600


def _days(n: int) -> timedelta:
    return timedelta(days=n)


def claim_status(points: List[Point], drug_dates: List[date], reg: date, today: date) -> dict:
    """สถานะการเบิกรายคน (ฟังก์ชันบริสุทธิ์) → {status, first, second, third, next_from, next_to}"""
    cut = config.REMISSION_HBA1C
    pts = sorted(p for p in points if p[0] <= today)
    drugs = sorted(d for d in drug_dates if d <= today)

    def last_drug_before(d):
        prev = [x for x in drugs if x <= d]
        return prev[-1] if prev else None

    def valid_first(d):
        if d < reg:
            return False
        ld = last_drug_before(d)
        if ld is None:
            return (d - reg).days >= config.CLAIM_LIFESTYLE_DAYS
        return (d - ld).days >= config.CLAIM_DRUGFREE_DAYS

    def drug_between(a, b):              # (a, b]
        return any(a < x <= b for x in drugs)

    first: Optional[Point] = None
    second: Optional[Point] = None
    third: Optional[Point] = None
    maint_lost = False
    for d, v in pts:
        if second is None:
            if first is not None:
                gap = (d - first[0]).days
                if v >= cut or drug_between(first[0], d) or (config.CLAIM_PAIR_MAX_DAYS and gap > config.CLAIM_PAIR_MAX_DAYS):
                    first = None                         # คู่เดิมใช้ไม่ได้ → พิจารณาผลนี้เป็นครั้งที่ 1 ใหม่
                elif gap >= config.CLAIM_PAIR_MIN_DAYS:
                    second = (d, v)
                    continue
                else:
                    continue                             # ผล <6.5 ระหว่างคู่ — คงครั้งที่ 1 ไว้
            if v < cut and valid_first(d):
                first = (d, v)
            continue
        gap = (d - second[0]).days                       # หาครั้งที่ 3
        if v >= cut or drug_between(second[0], d) or gap > config.CLAIM_MAINT_MAX_DAYS:
            maint_lost = True
            break
        if gap >= config.CLAIM_MAINT_MIN_DAYS:
            third = (d, v)
            break

    out = {"first": first, "second": second, "third": third, "next_from": None, "next_to": None}
    if second is not None:
        if third is not None:
            out["status"] = "maint_done"
            return out
        lo, hi = second[0] + _days(config.CLAIM_MAINT_MIN_DAYS), second[0] + _days(config.CLAIM_MAINT_MAX_DAYS)
        if maint_lost or drug_between(second[0], today) or today > hi:
            out["status"] = "success"
            return out
        out.update(status="due3" if today >= lo else "wait3", next_from=lo, next_to=hi)
        return out
    if first is not None and not drug_between(first[0], today):
        due = first[0] + _days(config.CLAIM_PAIR_MIN_DAYS)
        hi = first[0] + _days(config.CLAIM_PAIR_MAX_DAYS) if config.CLAIM_PAIR_MAX_DAYS else None
        out.update(status="due2" if today >= due else "wait2", next_from=due, next_to=hi)
        return out
    out["first"] = None
    ld = drugs[-1] if drugs else None
    if ld is not None and (today - ld).days < config.CLAIM_DRUGFREE_DAYS:
        out.update(status="on_drug", next_from=ld + _days(config.CLAIM_DRUGFREE_DAYS))
        return out
    eligible = max(reg, ld + _days(config.CLAIM_DRUGFREE_DAYS)) if ld else reg + _days(config.CLAIM_LIFESTYLE_DAYS)
    out.update(status="need1" if today >= eligible else "wait1", next_from=eligible)
    return out


def claims(r: dict) -> List[dict]:
    """รายการที่เบิกได้ของผู้ป่วยหนึ่งราย (วันที่ = วันตรวจที่ยืนยัน)"""
    out = []
    if r.get("second"):
        out.append({"kind": "success", "date": r["second"][0], "baht": config.CLAIM_SUCCESS_BAHT})
    if r.get("third"):
        out.append({"kind": "maint", "date": r["third"][0], "baht": config.CLAIM_MAINT_BAHT})
    return out


def _inputs(today: date):
    """(วันลงทะเบียน 1I20 ครั้งแรกรายคน, HbA1c รายคน, วันที่ได้ยาลดน้ำตาลรายคน)"""
    reg = common.pp_special_first_dates(config.PP_REMISSION)
    if not reg:
        return {}, {}, {}
    since = min(reg.values()) - _days(365)
    series = {h: pts for h, pts in common.lab_series_by_hn(config.LAB_HBA1C, None, since, today).items() if h in reg}
    drugs = common.drug_dates_by_hn(config.DRUG_DM, reg, since, today)
    return reg, series, drugs


def evaluate(today: date = None) -> Dict[str, dict]:
    """HN → ผล claim_status ของผู้ลงทะเบียนทุกราย (เก็บไว้ชั่วคราวในหน่วยความจำ)"""
    today = today or common.today()
    hit = _MEMO.get(today)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    reg, series, drugs = _inputs(today)
    out = {h: dict(claim_status(series.get(h, []), drugs.get(h, []), d, today), reg=d,
                   last_drug=max(drugs[h]) if drugs.get(h) else None) for h, d in reg.items()}
    _MEMO.clear()
    _MEMO[today] = (time.monotonic(), out)
    return out


def section(p) -> dict:
    """ตารางบนหน้า DM ฝั่ง HOSxP: สถานะรายคน ณ วันนี้ + ยอดเบิกที่ยืนยันผลในช่วงที่ดู"""
    res = evaluate()
    counts = {k: 0 for k, _f, _s in STATUSES}
    for r in res.values():
        counts[r["status"]] += 1
    got = [c for r in res.values() for c in claims(r) if p.start <= c["date"] <= p.end]
    n_s = sum(1 for c in got if c["kind"] == "success")
    n_m = sum(1 for c in got if c["kind"] == "maint")
    baht = sum(c["baht"] for c in got)

    def link(g, n):
        return {"page": "dm", "ind": "claim", "g": g, "text": f"ดูรายชื่อ ({n:,} ราย)"} if n else None

    rows = [[{"text": f"ยืนยันผลในช่วงนี้: Successful {n_s:,} ราย · Maintenance {n_m:,} ราย", "cls": "tot",
              "sub": f"ประมาณการเบิก {config.CLAIM_SUCCESS_BAHT:,.0f} / {config.CLAIM_MAINT_BAHT:,.0f} บาทต่อราย"},
             {"text": f"{baht:,.0f} บาท", "cls": "nw"}],
            [{"text": "ผู้ลงทะเบียน NCDs remission clinic ทั้งหมด (1I20)", "list": link("all", len(res))},
             {"text": f"{len(res):,} ราย", "cls": "nw"}]]
    for k, full, _short in STATUSES:
        rows.append([{"text": full, "list": link(k, counts[k])}, {"text": f"{counts[k]:,} ราย", "cls": "nw"}])
    return {"title": "เบิกงบบริการ DM Remission · สถานะรายคน ณ วันนี้", "columns": ["สถานะ / สิ่งที่ต้องทำ", "จำนวน"],
            "rows": rows, "wide": True}


def notes() -> list:
    return [{"tone": "info", "text": "ตารางเบิก DM Remission ใช้เกณฑ์การเบิก (ครั้งที่ 1→2 ≥90 วัน, ครั้งที่ 2→3 90–180 วัน, "
                                     "lifestyle 180 วัน / หยุดยา 90 วันก่อนครั้งที่ 1) ต่างจากตัวชี้วัด HDC 10.2 ด้านบน — "
                                     "ใช้ติดตามงานและนัดเจาะ การเบิกจริงยึดผลตรวจสอบของ สปสช./HDC"}]


def _fmt(pt) -> str:
    return f"{pt[1]:g}% ({ui.thai_date(pt[0])})" if pt else "—"


def _next(r) -> str:
    if not r.get("next_from"):
        return "—"
    if r.get("next_to"):
        return f"{ui.thai_date(r['next_from'])} – {ui.thai_date(r['next_to'])}"
    return f"ตั้งแต่ {ui.thai_date(r['next_from'])}"


def patient_list(p, ind: str, g: str) -> dict:
    """รายชื่อตามสถานะการเบิก (g = สถานะ หรือ all) · รายการที่ไม่รู้จัก → KeyError ก่อนแตะฐาน"""
    if ind != "claim" or (g != "all" and g not in LABEL):
        raise KeyError(f"{ind}/{g}")
    res = evaluate()
    order = {k: i for i, (k, _f, _s) in enumerate(STATUSES)}
    hns = sorted((h for h, r in res.items() if g == "all" or r["status"] == g),
                 key=lambda h: (order[res[h]["status"]], res[h]["next_from"] or date.max, h))
    info = common.patient_rows(hns, p)
    rows = []
    for i, h in enumerate(hns, 1):
        r, x = res[h], info.get(h, {})
        rows.append([str(i), h, x.get("name") or "(ไม่พบชื่อ)", f"{x['age']}" if x.get("age") is not None else "—",
                     LABEL[r["status"]][1], _next(r), _fmt(r["first"]), _fmt(r["second"]), _fmt(r["third"]),
                     ui.thai_date(r["last_drug"]) if r["last_drug"] else "ไม่เคยได้", ui.thai_date(r["reg"])])
    title = "เบิก DM Remission — ผู้ลงทะเบียนทั้งหมด" if g == "all" else f"เบิก DM Remission — {LABEL[g][0]}"
    return {"title": title, "count": len(hns), "rows": rows,
            "note": "สถานะ ณ วันนี้ ตามเกณฑ์การเบิก · ช่วงที่ควรเจาะ = วันที่ควรนัดเจาะ HbA1c ครั้งถัดไป",
            "columns": ["ลำดับ", "HN", "ชื่อ-สกุล", "อายุ", "สถานะ", "ช่วงที่ควรเจาะ / เริ่มนับได้", "HbA1c ครั้งที่ 1",
                        "ครั้งที่ 2", "ครั้งที่ 3", "ยาลดน้ำตาลล่าสุด", "ลงทะเบียน 1I20"]}

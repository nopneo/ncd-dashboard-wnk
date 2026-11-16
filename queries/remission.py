"""DM remission (โรคเบาหวานระยะสงบ) ฝั่ง HOSxP — ตามตัวชี้วัด HDC 10.2 (กองโรคไม่ติดต่อ ฉบับ 13 ก.พ. 2569)

ผู้เข้าร่วม (B1) = มีรหัสกิจกรรม 1I20 (pp_special) ในช่วงที่ดู
ระยะสงบ (A1)     = HbA1c 2 ครั้งล่าสุด <6.5% ห่างกัน 90–180 วัน ครั้งที่ 2 อยู่ในช่วงที่ดู
                   และไม่ได้รับยาลดน้ำตาลตั้งแต่ผลแรกที่ <6.5% ถึงผลยืนยัน
ต่างจาก HDC: ยังไม่ตัดผู้ป่วยไม่เข้าเกณฑ์ (อายุ <18, ภาวะแทรกซ้อนตามตาราง 3, CKD 3–5/หัวใจ/สมองใน 180 วัน)
และไม่ได้จัดสรรผู้ป่วยข้ามหน่วยบริการ — ตัวเลขจึงใกล้เคียงแต่ไม่เท่า HDC
รายชื่อผู้ป่วยเปิดได้เฉพาะ LAN ของ รพ. (app.py ตรวจสิทธิ์ก่อนเรียก patient_list)
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Dict, List, Set, Tuple

import config
import ui
from queries import common

#: (สถานะ, ชื่อในตาราง, ข้อความลิงก์) เรียงตามลำดับแสดง
STATUSES = [
    ("remission", "เข้าสู่ระยะสงบ (DM remission)", "เข้าสู่ระยะสงบ"),
    ("waiting", "HbA1c ล่าสุด <6.5% รอตรวจยืนยัน (ห่าง 90–180 วัน)", "รอตรวจยืนยัน"),
    ("on_drug", "HbA1c <6.5% แต่ยังได้รับยาลดน้ำตาล", "ยังได้รับยา"),
    ("not_yet", "HbA1c ล่าสุด ≥6.5%", "HbA1c ≥6.5%"),
    ("no_a1c", "ยังไม่มีผล HbA1c", "ยังไม่มีผล HbA1c"),
]
LABEL = {k: (name, short) for k, name, short in STATUSES}
_MEMO: Dict[tuple, tuple] = {}
TTL = 600


def remission_status(points: List[Tuple[date, float]], drug_dates: List[date], period_start: date) -> str:
    """สถานะรายคน (ฟังก์ชันบริสุทธิ์) จากผล HbA1c (วันที่, ค่า) และวันที่ได้ยาลดน้ำตาล"""
    pts = sorted(points)
    if not pts:
        return "no_a1c"
    d2, v2 = pts[-1]
    cut = config.REMISSION_HBA1C
    if v2 >= cut:
        return "not_yet"
    start = d2
    if len(pts) >= 2 and pts[-2][1] < cut:
        d1 = pts[-2][0]
        start = d1
        if (config.REMISSION_MIN_DAYS <= (d2 - d1).days <= config.REMISSION_MAX_DAYS and d2 >= period_start
                and not any(d1 <= d <= d2 for d in drug_dates)):
            return "remission"
    if any(d >= start for d in drug_dates):
        return "on_drug"
    return "waiting"


def _inputs(p):
    """(ผู้เข้าร่วม, HbA1c รายคน, วันที่ได้ยาลดน้ำตาลรายคน) — ย้อนหลัง 1 ปีก่อนช่วงเพื่อหาผลยืนยันข้ามปีงบ"""
    part = common.pp_special_hns(config.PP_REMISSION, p)
    since = p.start - timedelta(days=365)
    series = {h: pts for h, pts in common.lab_series_by_hn(config.LAB_HBA1C, None, since, p.end).items() if h in part}
    drugs = common.drug_dates_by_hn(config.DRUG_DM, part, since, p.end)
    return part, series, drugs


def statuses(part: Set[str], series, drugs, p) -> Dict[str, str]:
    return {h: remission_status(series.get(h, []), drugs.get(h, []), p.start) for h in part}


def summarize(part, series, drugs, p) -> dict:
    s = statuses(part, series, drugs, p)
    counts = {k: 0 for k, _n, _s in STATUSES}
    for v in s.values():
        counts[v] += 1
    return {"participants": len(part), "counts": counts}


def _link(g, n):
    if not n:
        return None
    text = f"ดูรายชื่อทั้งหมด ({n:,} ราย)" if g == "all" else f"ดูรายชื่อ: {LABEL[g][1]} ({n:,} ราย)"
    return {"page": "dm", "ind": "remission", "g": g, "text": text}


def section(p) -> dict:
    """ตาราง DM remission บนหน้า DM ฝั่ง HOSxP (จำนวนนับ + ลิงก์รายชื่อที่แสดงเฉพาะ LAN)"""
    s = summarize(*_inputs(p), p)
    n, c = s["participants"], s["counts"]
    title = "DM remission · NCDs remission clinic (รหัสกิจกรรม " + ",".join(config.PP_REMISSION) + ")"
    tgt = config.TARGET_DM_REMISSION
    pct = ui.pct(c["remission"], n)
    rows = [[{"text": "ร้อยละผู้เข้าร่วม clinic ที่เข้าสู่ระยะสงบ (A1/B1)",
              "sub": f"HbA1c 2 ครั้งล่าสุด <{config.REMISSION_HBA1C:g}% ห่างกัน {config.REMISSION_MIN_DAYS}–{config.REMISSION_MAX_DAYS} วัน "
                     "โดยไม่ได้รับยาลดน้ำตาล", "list": _link("remission", c["remission"])},
             {"text": f"≥ {tgt:g}%", "cls": "nw"}, {"text": f"{c['remission']:,} / {n:,}", "cls": "nw"},
             {"text": ui.fmt_pct(pct), "cls": "nw"}, ui.target_chip(pct, tgt)],
            [{"text": "ผู้ป่วยที่เข้าร่วม NCDs remission clinic (B1)", "sub": "มีรหัสกิจกรรมในช่วงที่ดู", "list": _link("all", n)},
             {"text": "—", "cls": "nw"}, {"text": f"{n:,}", "cls": "nw"}, {"text": "100.0%" if n else "—", "cls": "nw"}, ""]]
    for k, name, _short in STATUSES[1:]:
        rows.append([{"text": f"— {name}", "list": _link(k, c[k])}, {"text": "—", "cls": "nw"},
                     {"text": f"{c[k]:,}", "cls": "nw"}, {"text": ui.fmt_pct(ui.pct(c[k], n)), "cls": "nw"}, ""])
    return {"title": title, "columns": ["ตัวชี้วัด / กลุ่ม", "เป้าหมาย", "จำนวน (ราย)", "ร้อยละ", "สถานะ"], "rows": rows, "wide": True}


def notes(p) -> list:
    return [{"tone": "info", "text": "DM remission ฝั่ง HOSxP นับผู้มีรหัสกิจกรรม " + ",".join(config.PP_REMISSION) +
             " ในช่วง ยังไม่ตัดผู้ไม่เข้าเกณฑ์ตามนิยาม HDC (อายุ <18 ปี, ภาวะแทรกซ้อนรุนแรง, CKD 3–5/หัวใจ/สมองใน 180 วัน) "
             "ตัวเลขจึงต่างจาก HDC ได้ — รหัสยาลดน้ำตาลตั้งที่ NCD_DRUG_DM (ตรวจที่หน้า /check)"}]


def _basis(p):
    key = (p.start, p.end)
    hit = _MEMO.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    data = _inputs(p)
    _MEMO[key] = (time.monotonic(), data)
    return data


def _fmt(pt):
    return f"{pt[1]:g}% ({ui.thai_date(pt[0])})" if pt else "—"


def patient_list(p, ind: str, g: str) -> dict:
    """รายชื่อผู้เข้าร่วม clinic ตามสถานะ (g = สถานะ หรือ all) · รายการที่ไม่รู้จัก → KeyError ก่อนแตะฐาน"""
    if ind != "remission" or (g != "all" and g not in LABEL):
        raise KeyError(f"{ind}/{g}")
    part, series, drugs = _basis(p)
    s = statuses(part, series, drugs, p)
    hns = [h for h, v in s.items() if g == "all" or v == g]
    order = {k: i for i, (k, _n, _s) in enumerate(STATUSES)}

    def last(h):
        pts = sorted(series.get(h, []))
        return pts[-1] if pts else None

    hns.sort(key=lambda h: (order[s[h]], last(h)[1] if last(h) else 99, h))
    info = common.patient_rows(hns, p)
    rows = []
    for i, h in enumerate(hns, 1):
        pts = sorted(series.get(h, []))
        dd = sorted(drugs.get(h, []))
        x = info.get(h, {})
        lv = x.get("last_visit")
        rows.append([str(i), h, x.get("name") or "(ไม่พบชื่อ)", f"{x['age']}" if x.get("age") is not None else "—",
                     _fmt(pts[-1] if pts else None), _fmt(pts[-2] if len(pts) >= 2 else None),
                     ui.thai_date(dd[-1]) if dd else "ไม่ได้รับ", LABEL[s[h]][1], ui.thai_date(lv) if lv else "ไม่มาในช่วง"])
    title = "ผู้เข้าร่วม NCDs remission clinic ทั้งหมด" if g == "all" else f"NCDs remission clinic — {LABEL[g][0]}"
    return {"title": title, "count": len(hns), "rows": rows,
            "note": f"HbA1c ย้อนหลังถึง 1 ปีก่อนช่วง · ยาลดน้ำตาลตามรหัส NCD_DRUG_DM",
            "columns": ["ลำดับ", "HN", "ชื่อ-สกุล", "อายุ", "HbA1c ล่าสุด", "HbA1c ก่อนหน้า", "ได้ยาลดน้ำตาลล่าสุด",
                        "สถานะ", "มารับบริการล่าสุด"]}

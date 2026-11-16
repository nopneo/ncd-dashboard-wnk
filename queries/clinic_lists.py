"""รายชื่อผู้ป่วยหน้า DM / HT (เปิดเฉพาะ LAN ของ รพ. — app.py ตรวจสิทธิ์ก่อนเรียก patient_list)

กลุ่มสร้างจากชุดข้อมูลเดียวกับตัวเลขบนหน้า (ทะเบียนคลินิก, ค่าล่าสุดในช่วง, การมารับบริการ, ขาดนัด/นัดเลยกำหนด)
จำนวนในรายชื่อจึงเท่ากับตัวเลขบนหน้า · หน้า DM/HT เก็บแคชร่วมกัน จึงใส่เฉพาะ "ลิงก์ + จำนวน" ไม่ใส่ HN
"""
from __future__ import annotations

import time
from typing import Dict, Set, Tuple

import classify
import config
import ui
from queries import common

#: page → กลุ่ม → (หัวเรื่องหน้ารายชื่อ, ข้อความลิงก์สั้น)
GROUPS = {
    "dm": {
        "lt7": ("ผู้ป่วย DM ที่ควบคุมได้ (HbA1c ล่าสุด <7%)", "ควบคุมได้"),
        "7to79": ("ผู้ป่วย DM HbA1c ล่าสุด 7–7.9%", "HbA1c 7–7.9%"),
        "ge8": ("ผู้ป่วย DM ที่ควบคุมไม่ได้ (HbA1c ล่าสุด ≥8%)", "HbA1c ≥8%"),
        "ge9": ("ผู้ป่วย DM HbA1c ล่าสุด ≥9% (ติดตามเร่งด่วน)", "HbA1c ≥9%"),
        "above7": ("ผู้ป่วย DM ที่ยังไม่ถึงเป้า (HbA1c ล่าสุด ≥7%)", "ยังไม่ถึงเป้า (HbA1c ≥7%)"),
        "no_a1c": ("ผู้ป่วย DM ในทะเบียนที่ยังไม่ได้เจาะ HbA1c ในช่วง", "ยังไม่ได้เจาะ HbA1c"),
        "not_visited": ("ผู้ป่วย DM ในทะเบียนที่ไม่มารับบริการในช่วง", "ไม่มารับบริการในช่วง"),
        "lost_3m": ("ผู้ป่วย DM ขาดนัด >3 เดือน (ไม่มี visit ใน 90 วัน)", "ขาดนัด >3 เดือน"),
        "overdue": ("ผู้ป่วย DM ที่นัดเลยกำหนดแล้วยังไม่มา", "นัดเลยกำหนด"),
    },
    "ht": {
        "controlled": ("ผู้ป่วย HT ที่ควบคุมได้ (ความดันล่าสุด <140/90)", "ควบคุมได้"),
        "partial": ("ผู้ป่วย HT ความดันล่าสุด 140–159 / 90–99", "140–159 / 90–99"),
        "uncontrolled": ("ผู้ป่วย HT ที่ควบคุมไม่ได้ (ความดันล่าสุด ≥160/100)", "≥160/100"),
        "not_controlled": ("ผู้ป่วย HT ที่ยังไม่ถึงเป้า (ความดันล่าสุด ≥140/90)", "ยังไม่ถึงเป้า (≥140/90)"),
        "no_bp": ("ผู้ป่วย HT ในทะเบียนที่ไม่มีค่าความดันในช่วง", "ไม่มีค่าความดัน"),
        "streak": ("ผู้ป่วย HT ควบคุมไม่ได้ติดต่อกัน ≥2 ครั้ง (ทบทวนการปรับยา)", "ควบคุมไม่ได้ติดต่อกัน ≥2 ครั้ง"),
        "crisis": ("ผู้ป่วย HT ที่มีความดัน ≥180/110 อย่างน้อย 1 ครั้งในช่วง", "ความดัน ≥180/110"),
        "not_visited": ("ผู้ป่วย HT ในทะเบียนที่ไม่มารับบริการในช่วง", "ไม่มารับบริการในช่วง"),
        "lost_3m": ("ผู้ป่วย HT ขาดนัด >3 เดือน (ไม่มี visit ใน 90 วัน)", "ขาดนัด >3 เดือน"),
        "overdue": ("ผู้ป่วย HT ที่นัดเลยกำหนดแล้วยังไม่มา", "นัดเลยกำหนด"),
    },
}
_MEMO: Dict[tuple, tuple] = {}
TTL = 600


def link(page: str, g: str, n) -> dict:
    """ลิงก์ "ดูรายชื่อ" (แสดงเฉพาะผู้ดูใน LAN) — ไม่มีผู้ป่วย → None"""
    if not n:
        return None
    return {"page": page, "ind": "group", "g": g, "text": f"ดูรายชื่อ: {GROUPS[page][g][1]} ({int(n):,} ราย)"}


def _followup(clinic, p, reg) -> dict:
    gaps = common.followup_hns(clinic, p, min(p.end, common.today()))
    return {"not_visited": reg - common.visited_hns(clinic, p), "lost_3m": set(gaps["lost_3m"]), "overdue": set(gaps["overdue"])}


def dm_groups(p) -> Tuple[Dict[str, Set[str]], dict]:
    """(กลุ่ม → HN, HN → (วันที่, HbA1c ล่าสุด)) — นิยามเดียวกับ dm.summarize_hba1c / followup_gaps"""
    clinic = config.CLINIC_DM
    reg = set(common.registry_hns(clinic, p))
    vals = {r["hn"]: (r["date"], r["value"]) for r in common.latest_lab_by_hn(config.LAB_HBA1C, clinic, p)
            if classify.hba1c_group(r["value"])}
    g = {k: {h for h, (_d, v) in vals.items() if classify.hba1c_group(v) == k} for k in ("lt7", "7to79", "ge8")}
    g["ge9"] = {h for h, (_d, v) in vals.items() if v >= 9}
    g["above7"] = g["7to79"] | g["ge8"]
    g["no_a1c"] = reg - set(vals)
    g.update(_followup(clinic, p, reg))
    return g, vals


def ht_groups(p) -> Tuple[Dict[str, Set[str]], dict]:
    """(กลุ่ม → HN, HN → (วันที่, sbp, dbp) ล่าสุด) — นิยามเดียวกับ ht.summarize / _risk_tiles"""
    from queries import ht
    clinic = config.CLINIC_HT
    reg = set(common.registry_hns(clinic, p))
    series = ht.bp_series_by_hn(clinic, p)
    latest = {h: s[-1] for h, s in series.items() if s}
    grp = {h: classify.bp_group(sb, db_) for h, (_d, sb, db_) in latest.items()}
    g = {k: {h for h, v in grp.items() if v == k} for k in ("controlled", "partial", "uncontrolled")}
    g["not_controlled"] = g["partial"] | g["uncontrolled"]
    g["no_bp"] = reg - {h for h, v in grp.items() if v}
    g["streak"] = {h for h, s in series.items() if ht.uncontrolled_streak(s)}
    g["crisis"] = {h for h, s in series.items() if any(sb >= 180 or db_ >= 110 for _d, sb, db_ in s)}
    g.update(_followup(clinic, p, reg))
    return g, latest


GROUPS["copd"] = {
    "registry": ("ผู้ป่วยในทะเบียน", "ทั้งหมดในทะเบียน"),
    "reg_copd": ("ผู้ป่วยในทะเบียนคลินิก COPD", "ทะเบียน COPD"),
    "reg_asthma": ("ผู้ป่วยในทะเบียนคลินิกหืด", "ทะเบียนหืด"),
    "visited": ("ผู้ป่วยในทะเบียนที่มารับบริการในช่วง", "มารับบริการ"),
    "not_visited": ("ผู้ป่วยในทะเบียนที่ไม่มารับบริการในช่วง", "ไม่มารับบริการในช่วง"),
    "lost_3m": ("ผู้ป่วยขาดนัด >3 เดือน (ไม่มี visit ใน 90 วัน)", "ขาดนัด >3 เดือน"),
    "gap": ("ผู้ป่วยที่มีรหัสโรค COPD/หืดในช่วงแต่ยังไม่อยู่ในทะเบียนคลินิก", "มีรหัสโรคแต่ไม่อยู่ในทะเบียน"),
    "no_spiro": ("ผู้ป่วยในทะเบียนที่ยังไม่เคยตรวจสมรรถภาพปอด", "ยังไม่เคยตรวจสมรรถภาพปอด"),
    "no_inhaler": ("ผู้ป่วยในทะเบียนที่ไม่ได้รับยาพ่นควบคุมอาการในช่วง", "ไม่ได้รับยาพ่นควบคุม"),
}
GROUPS["cvd"] = {
    "stroke": ("ผู้ป่วย stroke ในช่วง (นับจากรหัสโรค)", "Stroke"),
    "ami": ("ผู้ป่วย AMI ในช่วง (นับจากรหัสโรค)", "AMI"),
    "new": ("ผู้ป่วย stroke/AMI รายใหม่ (ไม่มีรหัสเดียวกันใน 3 ปีก่อน)", "รายใหม่"),
    "prior_known": ("ผู้ป่วย stroke/AMI ที่เคยเป็นมาก่อน", "เคยเป็นมาก่อน"),
    "no_statin": ("ผู้ป่วย stroke/AMI (3 ปี) ที่ไม่ได้รับยา statin ในปีงบ", "ไม่ได้รับ statin"),
    "no_antithrombotic": ("ผู้ป่วย stroke/AMI (3 ปี) ที่ไม่ได้รับยาต้านเกล็ดเลือด/ต้านการแข็งตัว", "ไม่ได้รับยาต้านเกล็ดเลือด"),
    "bp_not_controlled": ("ผู้ป่วย stroke/AMI (3 ปี) ที่ความดันล่าสุดไม่ถึงเป้าหรือไม่มีค่า", "ความดันไม่ถึงเป้า/ไม่มีค่า"),
    "a1c_not": ("ผู้ป่วย stroke/AMI ที่เป็น DM และ HbA1c ล่าสุดไม่ถึงเป้าหรือไม่ได้ตรวจ", "HbA1c ไม่ถึงเป้า/ไม่ได้ตรวจ"),
    "not_visited": ("ผู้ป่วย stroke/AMI (3 ปี) ที่ไม่มารับบริการในปีงบ", "ไม่มารับบริการ"),
    "in_neither": ("ผู้ป่วย stroke/AMI (3 ปี) ที่ไม่อยู่ในทะเบียน HT และ DM", "ไม่อยู่ในทะเบียน HT/DM"),
}


def copd_groups(p, grp: str = "all"):
    """(กลุ่ม → HN, HN → ข้อความทะเบียน) — นิยามเดียวกับ copd._core"""
    from queries import copd
    core = copd._core(p, copd._norm(grp))
    reg = core["registry"]
    g = {"registry": reg, "visited": core["visited"], "not_visited": reg - core["visited"],
         "lost_3m": core["lost_hns"], "gap": core["gap_hns"]}
    names = {config.CLINIC_COPD: ("reg_copd", "COPD"), config.CLINIC_ASTHMA: ("reg_asthma", "หืด")}
    for c, hns in core["regs"].items():
        g[names[c][0]] = set(hns)
    if core["spiro"] is not None:
        g["no_spiro"] = reg - core["spiro"]
    if core["inhaler"] is not None:
        g["no_inhaler"] = reg - core["inhaler"]

    def value(h):
        tags = [names[c][1] for c, hns in core["regs"].items() if h in hns]
        return " + ".join(tags) if tags else "ไม่อยู่ในทะเบียน"
    return g, value


def cvd_groups(p):
    """(กลุ่ม → HN, HN → ข้อความโรค/ค่าล่าสุด) — นิยามเดียวกับ cvd._core / secondary_prevention"""
    from queries import cvd
    core = cvd._core(p)
    s = core["sec_in"]
    cohort, dm_in = s["cohort"], s["cohort"] & s["dm"]
    bp_ok = {h for h in cohort if h in s["bp"] and classify.bp_group(*s["bp"][h]) == "controlled"}
    a1c_ok = {h for h in dm_in if s["hba1c"].get(h) is not None and s["hba1c"][h] < config.HBA1C_TARGET}
    g = {"stroke": core["stroke"], "ami": core["ami"], "new": core["current"] - core["prior"],
         "prior_known": core["current"] & core["prior"], "no_statin": cohort - s["statin"],
         "no_antithrombotic": cohort - s["antithrombotic"], "bp_not_controlled": cohort - bp_ok,
         "a1c_not": dm_in - a1c_ok, "not_visited": cohort - s["visited"], "in_neither": cohort - (core["ht"] | s["dm"])}

    def value(h):
        dx = [n for n, hs in (("Stroke", core["stroke"]), ("AMI", core["ami"])) if h in hs]
        bp = s["bp"].get(h)
        a1c = s["hba1c"].get(h)
        parts = [" + ".join(dx) if dx else "ในกลุ่ม 3 ปี"]
        if bp:
            parts.append(f"BP {bp[0]:g}/{bp[1]:g}")
        if a1c is not None:
            parts.append(f"HbA1c {a1c:g}%")
        return " · ".join(parts)
    return g, value


GROUPS["warfarin"] = {
    "all": ("ผู้ป่วยที่ได้รับ warfarin ในช่วง", "ทั้งหมด"),
    "ttr_below": ("ผู้ป่วย warfarin ที่ TTR ต่ำกว่าเป้า (ตรวจ INR ≥2 ครั้ง)", "TTR ต่ำกว่าเป้า"),
    "critical_high": ("ผู้ป่วย warfarin ที่มี INR >4.5 อย่างน้อย 1 ครั้งในช่วง", "INR >4.5"),
    "bleeding": ("ผู้ป่วย warfarin ที่มีรหัสโรคเลือดออกในช่วง", "เลือดออก"),
    "no_recent": ("ผู้ป่วย warfarin ที่ไม่มีผล INR ใน 90 วันล่าสุด", "ไม่มี INR ใน 90 วัน"),
}


def warfarin_groups(p):
    """(กลุ่ม → HN, HN → ข้อความ INR/TTR) — นิยามเดียวกับ warfarin._core / summarize / recent_inr"""
    from datetime import timedelta
    from queries import warfarin
    core = warfarin._core(p)
    cohort, series = core["cohort"], core["series"]
    ttr = {h: classify.ttr_rosendaal(sorted(pts), config.INR_LOW, config.INR_HIGH) for h, pts in series.items()}
    on = min(p.end, common.today())
    since = on - timedelta(days=90)
    recent = {h for h, pts in series.items() if any(since <= d <= on for d, _v in pts)}
    g = {"all": set(cohort), "ttr_below": {h for h, t in ttr.items() if t is not None and t < config.TTR_TARGET},
         "critical_high": {h for h, pts in series.items() if any(v > warfarin.CRITICAL_HIGH for _d, v in pts)},
         "bleeding": set(core["bleeding_hns"]), "no_recent": set(cohort) - recent}

    def value(h):
        pts = sorted(series.get(h, []))
        if not pts:
            return "ไม่มีผล INR ในช่วง"
        d, v = pts[-1]
        out = f"INR {v:g} ({ui.thai_date(d)}) · สูงสุด {max(x for _d, x in pts):g}"
        return out + (f" · TTR {ttr[h]:.0f}%" if ttr.get(h) is not None else "")
    value.key = lambda h: (h not in series, -max((x for _d, x in series.get(h, [])), default=0), h)   # INR สูงสุดก่อน
    return g, value


def _dm_fmt(vals, h):
    return f"{vals[h][1]:g}% ({ui.thai_date(vals[h][0])})" if h in vals else "—"


def _ht_fmt(vals, h):
    return f"{vals[h][1]:g}/{vals[h][2]:g} ({ui.thai_date(vals[h][0])})" if h in vals else "—"


def _worst_first(vals, h):
    return (h not in vals, -(vals[h][1]) if h in vals else 0, h)


#: page → (สร้างกลุ่ม(p, opts), ชื่อคอลัมน์ค่า, จัดรูปค่า(data, hn), ลำดับ(data, hn))
BUILDERS = {
    "dm": (lambda p, o: dm_groups(p), "HbA1c ล่าสุด", _dm_fmt, _worst_first),
    "ht": (lambda p, o: ht_groups(p), "ความดันล่าสุด", _ht_fmt, _worst_first),
    "copd": (lambda p, o: copd_groups(p, o.get("grp", "all")), "ทะเบียน", lambda v, h: v(h), lambda v, h: (v(h), h)),
    "cvd": (lambda p, o: cvd_groups(p), "โรค / ค่าล่าสุด", lambda v, h: v(h), lambda v, h: (v(h), h)),
    "warfarin": (lambda p, o: warfarin_groups(p), "INR ล่าสุด / สูงสุด / TTR", lambda v, h: v(h), lambda v, h: v.key(h)),
}


def _basis(page, p, opts):
    key = (page, p.start, p.end, tuple(sorted(opts.items())))
    hit = _MEMO.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    data = BUILDERS[page][0](p, opts)
    _MEMO[key] = (time.monotonic(), data)
    return data


def patient_list(page: str, p, ind: str, g: str, **opts) -> dict:
    """รายชื่อของกลุ่ม g · รายการที่ไม่รู้จัก → KeyError ก่อนแตะฐาน (opts: grp ของหน้า COPD)"""
    if page not in GROUPS or ind != "group" or g not in GROUPS[page]:
        raise KeyError(f"{page}/{ind}/{g}")
    groups, vals = _basis(page, p, opts)
    if g not in groups:                     # เช่น ไม่ได้ตั้งรหัส spirometry
        raise KeyError(g)
    hns = groups[g]
    _b, col, fmt_, sort_ = BUILDERS[page]
    sort_key = lambda h: sort_(vals, h)     # noqa: E731
    fmt = lambda h: fmt_(vals, h)           # noqa: E731
    order = sorted(hns, key=sort_key)
    info = common.patient_rows(order, p)
    rows = []
    for i, h in enumerate(order, 1):
        x = info.get(h, {})
        lv = x.get("last_visit")
        rows.append([str(i), h, x.get("name") or "(ไม่พบชื่อ)", f"{x['age']}" if x.get("age") is not None else "—",
                     fmt(h), ui.thai_date(lv) if lv else "ไม่มาในช่วง"])
    note = {"cvd": "นับจากรหัสโรค (ไม่มีทะเบียนคลินิก) · ยา/ความดัน/HbA1c ดูทั้งปีงบ",
            "warfarin": f"ผู้ป่วยนับจากการจ่ายยา warfarin ในช่วง · INR ในเกณฑ์ {config.INR_LOW:g}–{config.INR_HIGH:g} · เป้า TTR ≥{config.TTR_TARGET:g}%",
            "copd": "ทะเบียนคลินิก COPD/หืดที่ยังติดตามในช่วง"}.get(page, "ผู้ป่วยในทะเบียนคลินิกที่ยังติดตามในช่วง · ค่าล่าสุดในช่วงที่ดู")
    title = GROUPS[page][g][0]
    if page == "copd" and opts.get("grp") in ("copd", "asthma"):
        title += " · " + ("COPD" if opts["grp"] == "copd" else "หืด")
    return {"title": title, "count": len(hns), "rows": rows, "note": note,
            "columns": ["ลำดับ", "HN", "ชื่อ-สกุล", "อายุ", col, "มารับบริการล่าสุด"]}

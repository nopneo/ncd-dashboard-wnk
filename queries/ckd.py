"""หน้า CKD — ไตเรื้อรัง

ทะเบียน CKD ใน HOSxP ว่าง (clinic_ckd_member = 0 แถว) จึงนิยามจากข้อมูลจริง:
  ผู้ป่วย CKD = eGFR ล่าสุด <60 และมีค่า <60 อีกครั้งห่างกัน ≥90 วัน  หรือ  มีรหัสโรค N18.x (ICD_CKD) ในช่วง
  ระยะแบ่งตาม eGFR ล่าสุด (G3a 45–59, G3b 30–44, G4 15–29, G5 <15) · มีเฉพาะรหัส N18 ไม่มี eGFR = ไม่ทราบระยะ
ทีมคลินิกไตควรยืนยันนิยามนี้ก่อนนำไปใช้รายงานทางการ
"""
from __future__ import annotations

import dataclasses
import time
from datetime import date, timedelta
from typing import Dict, List, Set, Tuple

import classify
import config
import periods
import sections
import ui
from queries import common

TITLE = "ไตเรื้อรัง (CKD)"
NODATA = "ไม่มีข้อมูล"
BLUE, GREEN, AMBER, RED, GREY = "#2563eb", "#16a34a", "#f59e0b", "#ef4444", "#94a3b8"


def identify_ckd(series: Dict[str, List[Tuple[date, float]]], n18_hns: Set[str],
                 in_period_from: date = None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for hn in set(series) | set(n18_hns):
        pts = sorted(series.get(hn, []))
        has_icd = hn in n18_hns
        latest = pts[-1] if pts else None
        persistent = bool(latest and latest[1] < 60
                          and any(v < 60 and (latest[0] - d).days >= 90 for d, v in pts[:-1]))
        if not (has_icd or persistent):
            continue
        n_period = sum(1 for d, _v in pts if in_period_from is None or d >= in_period_from)
        if not has_icd and in_period_from is not None and n_period == 0:
            continue                            # ผลล่าสุดเก่ากว่าช่วงที่ดู และไม่มีรหัส N18 ในช่วง
        # eGFR ลดเร็ว: ต้องมี ≥3 ผลครอบคลุม ≥1 ปี (ผลสั้น/น้อยแกว่งง่ายจากการป่วยเฉียบพลัน)
        slope = (classify.egfr_slope_per_year(pts) if len(pts) >= 3 and (pts[-1][0] - pts[0][0]).days >= 365 else None)
        egfr = latest[1] if latest else None
        out[hn] = {"egfr": egfr, "stage": classify.ckd_stage(egfr), "persistent": persistent,
                   "slope": slope, "rapid": slope is not None and slope < -5, "n_period": n_period}
    return out


def summarize(cohort: Dict[str, dict]) -> dict:
    c = {"G3a": 0, "G3b": 0, "G4": 0, "G5": 0, "G1-2": 0, None: 0}
    for v in cohort.values():
        c[v["stage"]] += 1
    return {"g3a": c["G3a"], "g3b": c["G3b"], "g4": c["G4"], "g5": c["G5"], "g12": c["G1-2"], "unknown": c[None],
            "stage3": c["G3a"] + c["G3b"], "stage345": c["G3a"] + c["G3b"] + c["G4"] + c["G5"],
            "egfr_lt30": c["G4"] + c["G5"], "total": len(cohort),
            "rapid_decline": sum(1 for v in cohort.values() if v.get("rapid")),
            "monitored": sum(1 for v in cohort.values() if v.get("n_period", 0) >= 2)}


# --- ตัวชี้วัดการชะลอไตเสื่อม (ข้อมูล รพ. เอง) -------------------------------------------

STAGE34 = ("G3a", "G3b", "G4")
STAGE345 = ("G3a", "G3b", "G4", "G5")


def _ind(key, label, num, den, target=None, note=""):
    return {"key": key, "label": label, "num": num, "den": den, "target": target, "note": note}


def slowdown_groups(cohort, prior_ckd, dm, ht, dm_visited, uacr_tested, visited, acei, hb, hct, a1c,
                    dialysis) -> Dict[str, Tuple[Set[str], Set[str]]]:
    """ชุด HN (ตัวตั้ง, ตัวหาร) ของแต่ละตัวชี้วัด (ฟังก์ชันบริสุทธิ์) — ใช้ทั้งนับบนหน้าเว็บและทำรายชื่อ"""
    dmht = (set(dm) | set(ht)) - set(prior_ckd)
    new = {h for h in cohort if h in dmht}
    acei_den = {h for h, v in cohort.items() if h in visited and v["stage"] != "G5" and h not in dialysis}
    s345 = {h for h, v in cohort.items() if v["stage"] in STAGE345}
    tested = {h for h in s345 if h in hb or h in hct}
    ok_hb = {h for h in tested if (hb.get(h) is not None and hb[h] > config.CKD_HB_MIN)
             or (hct.get(h) is not None and hct[h] > config.CKD_HCT_MIN)}
    dm34 = {h for h, v in cohort.items() if v["stage"] in STAGE34 and h in dm}
    a1c_ok = {h for h in dm34 if a1c.get(h) is not None and a1c[h] < config.CKD_DM_HBA1C_TARGET}
    return {"new_ckd": (new, dmht), "uacr": (set(uacr_tested) & set(dm_visited), set(dm_visited)),
            "acei": (acei_den & set(acei), acei_den), "anemia_tested": (tested, s345),
            "anemia": (ok_hb, tested), "dm_a1c": (a1c_ok, dm34)}


def slowdown(cohort, prior_ckd, dm, ht, dm_visited, uacr_tested, visited, acei, hb, hct, a1c, dialysis) -> List[dict]:
    """คำนวณตัวชี้วัด (ฟังก์ชันบริสุทธิ์ — รับชุด HN / ค่า lab ล่าสุดรายคน คืนตัวตั้ง/ตัวหาร)"""
    g = slowdown_groups(cohort, prior_ckd, dm, ht, dm_visited, uacr_tested, visited, acei, hb, hct, a1c, dialysis)

    def n(key):
        return len(g[key][0]), len(g[key][1])

    return [
        _ind("new_ckd", "ร้อยละผู้ป่วย DM/HT ที่เป็น CKD รายใหม่ในช่วง", *n("new_ckd"),
             note="ตัวหาร = ผู้ป่วยในทะเบียน DM/HT ที่ยังไม่เป็น CKD ก่อนช่วง (ยิ่งต่ำยิ่งดี)"),
        _ind("uacr", "ร้อยละผู้ป่วย DM ได้ตรวจ Microalbumin (คัดกรองไต)", *n("uacr"),
             note="ตัวหาร = ผู้ป่วย DM ที่มารับบริการในช่วง"),
        _ind("acei", "ร้อยละผู้ป่วย CKD ที่มารับบริการได้รับ ACEI/ARB", *n("acei"),
             config.TARGET_CKD_ACEI_ARB, "ไม่รวมระยะ 5 และผู้ล้างไต · ยังไม่ได้ตัดผู้ที่มีข้อห้าม (AKI, K สูง)"),
        _ind("anemia_tested", "ร้อยละผู้ป่วย CKD ระยะ 3–5 ได้ตรวจ Hb/Hct", *n("anemia_tested")),
        _ind("anemia", f"ร้อยละผู้ป่วย CKD ระยะ 3–5 มี Hb >{config.CKD_HB_MIN:g} g/dl หรือ Hct >{config.CKD_HCT_MIN:g}%",
             *n("anemia"), config.TARGET_CKD_ANEMIA, "ค่าล่าสุดในช่วง · ตัวหาร = ผู้ที่ได้ตรวจ"),
        _ind("dm_a1c", f"ร้อยละผู้ป่วย DM ที่มี CKD ระยะ 3–4 HbA1c <{config.CKD_DM_HBA1C_TARGET:g}%", *n("dm_a1c"),
             config.TARGET_CKD_DM_A1C, "ค่าล่าสุดในช่วง · ไม่ได้ตรวจนับเป็นไม่ผ่าน")]


def count_readmits(rows: List[dict], days: int = 28) -> int:
    """จำนวนการ Admit ที่เกิดภายใน days วันหลังจำหน่ายครั้งก่อนของคนเดียวกัน (ครั้งก่อนไม่มีวันจำหน่าย → ใช้วันรับ)"""
    n, last = 0, {}
    for r in sorted(rows, key=lambda r: (r["hn"], r["regdate"])):
        prev = last.get(r["hn"])
        if prev is not None and 0 <= (r["regdate"] - prev).days <= days:
            n += 1
        last[r["hn"]] = r.get("dchdate") or r["regdate"]
    return n


def _latest_values(codes, clinic, p, among) -> Dict[str, float]:
    if not codes:
        return {}
    return {r["hn"]: r["value"] for r in common.latest_lab_by_hn(codes, clinic, p)
            if r["value"] is not None and r["hn"] in among}


def _slowdown_inputs(p, core) -> dict:
    """ข้อมูลตั้งต้นของตัวชี้วัดชะลอไตเสื่อม (ชุด HN + ค่า lab ล่าสุดรายคน) — ใช้ร่วมกับหน้ารายชื่อ"""
    cohort, series = core["cohort"], core["series"]
    prior_p = dataclasses.replace(p, start=p.start - timedelta(days=365), end=p.start - timedelta(days=1))
    prior_series = {h: [(d, v) for d, v in pts if d < p.start] for h, pts in series.items()}
    prior = identify_ckd(prior_series, common.icd_hns(config.ICD_CKD, prior_p))
    hns = set(cohort)
    uacr = ({r["hn"] for r in common.latest_lab_by_hn(config.LAB_UACR, config.CLINIC_DM, p, allow_zero=True)}
            if config.LAB_UACR else set())
    return dict(
        cohort=cohort, prior_ckd=set(prior),
        dm=set(common.registry_hns(config.CLINIC_DM, p)), ht=set(common.registry_hns(config.CLINIC_HT, p)),
        dm_visited=set(common.visited_hns(config.CLINIC_DM, p)), uacr_tested=uacr,
        visited=common.visited_among(list(hns), p), acei=common.drug_hns(config.DRUG_ACEI_ARB, None, p) & hns,
        hb=_latest_values(config.LAB_HB, None, p, hns), hct=_latest_values(config.LAB_HCT, None, p, hns),
        a1c=_latest_values([config.LAB_HBA1C], config.CLINIC_DM, p, hns), dialysis=core["dialysis_hns"])


def _slowdown_core(p, core):
    rows = slowdown(**_slowdown_inputs(p, core))
    return {"rows": rows,
            "readmits": count_readmits(common.icd_admission_rows(config.ICD_CKD, p), config.READMIT_DAYS),
            "deaths": common.icd_deaths(config.ICD_CKD, config.DCHSTTS_DEAD, p)}


_chip = ui.target_chip

# --- รายชื่อผู้ป่วย (เปิดเฉพาะ LAN ของ รพ. — app.py ตรวจสิทธิ์ก่อนเรียก) ------------------------------
#: ตัวชี้วัด → กลุ่มที่ให้ดูรายชื่อ: "num" = อยู่ในตัวตั้ง · "miss" = อยู่ในตัวหารแต่ไม่อยู่ในตัวตั้ง → (หัวเรื่อง, ข้อความลิงก์)
LIST_META = {
    "new_ckd": {"num": ("ผู้ป่วย DM/HT ที่เป็น CKD รายใหม่", "CKD รายใหม่")},
    "uacr": {"miss": ("ผู้ป่วย DM ที่มารับบริการแต่ยังไม่ได้ตรวจ Microalbumin", "ยังไม่ได้ตรวจ Microalbumin")},
    "acei": {"miss": ("ผู้ป่วย CKD ที่มารับบริการแต่ยังไม่ได้รับ ACEI/ARB", "ยังไม่ได้รับ ACEI/ARB")},
    "anemia_tested": {"miss": ("ผู้ป่วย CKD ระยะ 3–5 ที่ยังไม่ได้ตรวจ Hb/Hct", "ยังไม่ได้ตรวจ Hb/Hct")},
    "anemia": {"miss": ("ผู้ป่วย CKD ระยะ 3–5 ที่ Hb/Hct ต่ำกว่าเกณฑ์", "Hb/Hct ต่ำกว่าเกณฑ์")},
    "dm_a1c": {"miss": ("ผู้ป่วย DM ที่มี CKD ระยะ 3–4 ที่ HbA1c ไม่ถึงเป้าหรือยังไม่ได้ตรวจ", "HbA1c ไม่ถึงเป้า/ยังไม่ได้ตรวจ")},
}
STAGE_LIST = {"G3a": "ระยะ 3a (eGFR 45–59)", "G3b": "ระยะ 3b (eGFR 30–44)", "G4": "ระยะ 4 (eGFR 15–29)",
              "G5": "ระยะ 5 (eGFR <15)", "G1-2": "ระยะ 1–2 (eGFR ≥60 มีรหัส N18)", "none": "ไม่ทราบระยะ"}
STAGE_SHORT = {"G3a": "3a", "G3b": "3b", "G4": "4", "G5": "5", "G1-2": "1–2"}
#: ข้อมูลตั้งต้นของรายชื่อ เก็บไว้ชั่วคราว (กดดูหลายรายการติดกันไม่ต้องคำนวณใหม่) — อยู่ในหน่วยความจำเท่านั้น
_LIST_MEMO: Dict[tuple, tuple] = {}
LIST_TTL = 600


def _link(ind, g, n):
    if not n or ind not in LIST_META and ind != "stage":
        return None
    text = f"ดูรายชื่อ ({n:,} ราย)" if ind == "stage" else f"ดูรายชื่อ: {LIST_META[ind][g][1]} ({n:,} ราย)"
    return {"page": "ckd", "ind": ind, "g": g, "text": text}


def _list_basis(p):
    key = (p.start, p.end)
    hit = _LIST_MEMO.get(key)
    if hit and time.monotonic() - hit[0] < LIST_TTL:
        return hit[1], hit[2]
    core = _core(p)
    inputs = _slowdown_inputs(p, core)
    _LIST_MEMO[key] = (time.monotonic(), core, inputs)
    return core, inputs


def _num(v):
    return f"{v:g}" if v is not None else "—"


def _value_column(ind, inputs):
    """คอลัมน์ค่า lab ที่เกี่ยวกับตัวชี้วัด (ไม่มี → None)"""
    if ind in ("anemia", "anemia_tested"):
        hb, hct = inputs["hb"], inputs["hct"]
        return "Hb / Hct ล่าสุด", lambda h: " · ".join(
            x for x in (f"Hb {hb[h]:g}" if h in hb else "", f"Hct {hct[h]:g}" if h in hct else "") if x) or "—"
    if ind == "dm_a1c":
        a1c = inputs["a1c"]
        return "HbA1c ล่าสุด", lambda h: f"{a1c[h]:g}%" if h in a1c else "ไม่ได้ตรวจ"
    return None


def patient_list(p, ind: str, g: str) -> dict:
    """รายชื่อผู้ป่วยของตัวชี้วัด/ระยะ CKD · รายการที่ไม่รู้จัก → KeyError (ตรวจก่อนแตะฐาน)"""
    if ind == "stage":
        if g not in STAGE_LIST:
            raise KeyError(g)
        title, note = f"ผู้ป่วย CKD {STAGE_LIST[g]}", "ระยะตาม eGFR ล่าสุด · นิยาม CKD จาก eGFR <60 ต่อเนื่อง ≥90 วัน หรือรหัส N18"
    elif g in LIST_META.get(ind, {}):
        title, note = LIST_META[ind][g][0], ""
    else:
        raise KeyError(f"{ind}/{g}")
    core, inputs = _list_basis(p)
    cohort = core["cohort"]
    value = None
    if ind == "stage":
        st = None if g == "none" else g
        hns = {h for h, v in cohort.items() if v["stage"] == st}
    else:
        num, den = slowdown_groups(**inputs)[ind]
        hns = num if g == "num" else den - num
        value = _value_column(ind, inputs)
        r = next(x for x in slowdown(**inputs) if x["key"] == ind)
        note = f"จากตัวชี้วัด: {r['label']}" + (f" ({r['note']})" if r["note"] else "")
    info = common.patient_rows(hns, p)

    def egfr(h):
        return cohort.get(h, {}).get("egfr")

    order = sorted(hns, key=lambda h: (egfr(h) is None, egfr(h) or 0, h))
    columns = ["ลำดับ", "HN", "ชื่อ-สกุล", "อายุ", "ระยะ CKD", "eGFR ล่าสุด"] + ([value[0]] if value else []) + ["มารับบริการล่าสุด"]
    rows = []
    for i, h in enumerate(order, 1):
        x, c = info.get(h, {}), cohort.get(h, {})
        lv = x.get("last_visit")
        rows.append([str(i), h, x.get("name") or "(ไม่พบชื่อ)", _num(x.get("age")),
                     STAGE_SHORT.get(c.get("stage"), "ไม่ทราบ" if h in cohort else "—"),
                     f"{egfr(h):.0f}" if egfr(h) is not None else "—"]
                    + ([value[1](h)] if value else []) + [ui.thai_date(lv) if lv else "ไม่มาในช่วง"])
    return {"title": title, "note": note, "count": len(hns), "columns": columns, "rows": rows}


def _slowdown_table(sd, label):
    title = f"ตัวชี้วัดการชะลอไตเสื่อม · {label}"
    if "error" in sd:
        return dict(sd, title=title)
    rows = []
    for r in sd["rows"]:
        pct = ui.pct(r["num"], r["den"])
        g = next(iter(LIST_META.get(r["key"], {})), None)
        n = r["num"] if g == "num" else r["den"] - r["num"]
        rows.append([{"text": r["label"], "sub": r["note"], "list": _link(r["key"], g, n) if g else None},
                     {"text": f"> {r['target']:.0f}%" if r["target"] is not None else "—", "cls": "nw"},
                     {"text": f"{r['num']:,} / {r['den']:,}", "cls": "nw"}, {"text": ui.fmt_pct(pct), "cls": "nw"},
                     _chip(pct, r["target"])])
    return {"title": title, "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลงาน (ราย)", "ร้อยละ", "สถานะ"], "rows": rows,
            "wide": True}       # เต็มความกว้าง: ชื่อตัวชี้วัดยาว ครึ่งจอจะเบียดคอลัมน์ตัวเลข


def _slow_notes(sd):
    if "error" in sd:
        return []
    r = {x["key"]: x for x in sd["rows"]}
    out = [{"tone": "info", "text": "ตัวชี้วัดการชะลอไตเสื่อมคำนวณจากข้อมูลของ รพ. เอง (ยา ACEI/ARB, Hb/Hct, HbA1c, Microalbumin) "
                                    "ตามรหัสและเกณฑ์ที่ตั้งใน .env (ตรวจได้ที่หน้า /check) — ยังไม่ตัดผู้มีข้อห้ามใช้ยาหรือปฏิเสธการรักษา "
                                    "ควรให้ทีมคลินิกไตทวนก่อนรายงานทางการ"}]
    t = r.get("anemia_tested")
    if t and t["den"] and t["num"] < t["den"]:
        out.append({"tone": "warn", "text": f"ผู้ป่วย CKD ระยะ 3–5 จำนวน {t['den'] - t['num']:,} ราย ยังไม่ได้ตรวจ Hb/Hct ในช่วงนี้ "
                                            "— ควรตรวจ CBC เพื่อประเมินภาวะซีด"})
    return out


def _core(p):
    end = p.end
    series = common.lab_series_by_hn(config.LAB_EGFR, None, p.start - timedelta(days=365), end)
    cohort = identify_ckd(series, common.icd_hns(config.ICD_CKD, p), in_period_from=p.start)
    out = {"series": series, "cohort": cohort, "summary": summarize(cohort), "label": p.label,
            "dialysis_hns": common.icd_hns(config.ICD_DIALYSIS, p),
            "admits": common.icd_admissions(config.ICD_CKD, p)}
    out["dialysis"] = len(out["dialysis_hns"])
    return out


def _monthly(p, core):
    members = set(core["cohort"])
    per_month = {}
    for hn in members:
        for d, _v in core["series"].get(hn, []):
            per_month.setdefault(d.strftime("%Y-%m"), set()).add(hn)
    return {"labels": [label for _d, label in periods.months(p)],
            "series": [{"name": "ผู้ป่วย CKD ที่ตรวจ eGFR", "color": "#1d6ff2",
                        "values": [len(per_month.get(d.strftime("%Y-%m"), ())) for d, _l in periods.months(p)]}]}


def _kpis(core):
    s = core["summary"]
    return [
        {"label": "ผู้ป่วย CKD", "value": ui.fmt_int(s["total"]), "unit": "ราย", "tone": "blue", "icon": "bean",
         "sub": "นิยามจาก eGFR + รหัส N18"},
        {"label": "CKD ระยะ 3–5", "value": ui.fmt_int(s["stage345"]), "unit": "ราย", "tone": "teal", "icon": "activity",
         "sub": f"{ui.fmt_pct(ui.pct(s['stage345'], s['total']))} ของผู้ป่วย CKD"},
        {"label": "ล้างไต/ส่งต่อ (Dialysis)", "value": ui.fmt_int(core["dialysis"]), "unit": "ราย", "tone": "orange", "icon": "droplet",
         "sub": "นับจากรหัสโรค " + ",".join(config.ICD_DIALYSIS)},
        {"label": "ติดตามค่าไต ≥2 ครั้งในช่วง", "value": ui.fmt_int(s["monitored"]), "unit": "ราย", "tone": "purple", "icon": "calendar-check",
         "sub": f"{ui.fmt_pct(ui.pct(s['monitored'], s['total']))} ของผู้ป่วย CKD"}]


def _donut(core):
    s = core["summary"]
    return {"title": "สัดส่วนผู้ป่วย CKD ตามระยะ (eGFR ล่าสุด)", "center": ui.fmt_int(s["total"]),
            "total_label": f"ผู้ป่วย CKD {s['total']:,} ราย",
            "parts": [("ระยะ 3 (eGFR 30–59)", s["stage3"], GREEN), ("ระยะ 4 (15–29)", s["g4"], AMBER),
                      ("ระยะ 5 (<15)", s["g5"], RED), ("ระยะ 1–2 (มีรหัส N18)", s["g12"], BLUE),
                      ("ไม่ทราบระยะ (มีรหัส N18 ไม่มี eGFR)", s["unknown"], GREY)]}


def _table(core):
    s = core["summary"]
    rows = [("G3a", s["g3a"]), ("G3b", s["g3b"]), ("G4", s["g4"]), ("G5", s["g5"]), ("G1-2", s["g12"]), ("none", s["unknown"])]
    return {"title": f"ผู้ป่วย CKD ตามระยะ · {core['label']}", "columns": ["ระยะ CKD", "จำนวน (ราย)", "ร้อยละ"],
            "rows": [[{"text": STAGE_LIST[g], "list": _link("stage", g, v)}, ui.fmt_int(v), ui.fmt_pct(ui.pct(v, s["total"]))]
                     for g, v in rows]
                    + [[{"text": "รวม", "cls": "tot"}, ui.fmt_int(s["total"]), ui.fmt_pct(100.0 if s["total"] else None)]]}


def _indicators(core, sd=None):
    s = core["summary"]
    extra = []
    if sd and "error" not in sd:
        extra = [{"label": f"Admit ซ้ำ ≤{config.READMIT_DAYS} วัน", "value": ui.fmt_int(sd["readmits"]),
                  "sub": "ครั้ง (นับจากวันจำหน่ายครั้งก่อน)", "tone": "orange"},
                 {"label": "เสียชีวิตขณะ Admit (มีรหัส CKD)", "value": ui.fmt_int(sd["deaths"]),
                  "sub": "ครั้ง (สถานะจำหน่าย " + ",".join(config.DCHSTTS_DEAD) + ")", "tone": "red"}]
    return {"type": "tiles", "title": "ตัวชี้วัดสำคัญคลินิก CKD", "items": [
        {"label": "Admit ด้วย CKD", "value": ui.fmt_int(core["admits"]), "sub": "ครั้ง (รหัส " + ",".join(config.ICD_CKD) + ")", "tone": "red"}] + extra + [
        {"label": "eGFR <30 (ระยะ 4–5)", "value": ui.fmt_int(s["egfr_lt30"]), "sub": "ราย", "tone": "orange"},
        {"label": "eGFR ลดเร็ว >5/ปี", "value": ui.fmt_int(s["rapid_decline"]), "sub": "ราย (≥3 ผล ครอบคลุม ≥1 ปี)", "tone": "purple"},
        {"label": "ส่งปรึกษาแพทย์/ไต", "value": NODATA, "sub": "ไม่มีแหล่งบันทึกใน HOSxP", "tone": "blue"},
        {"label": "ตารางความเสี่ยง KDIGO", "value": NODATA, "sub": "ยังไม่ยืนยันหน่วย Microalbumin", "tone": "blue"}]}


def _notes(core):
    s, out = core["summary"], []
    out.append({"tone": "info", "text": "ทะเบียนคลินิกไตใน HOSxP ไม่มีข้อมูล จึงนับผู้ป่วย CKD จาก eGFR ต่ำต่อเนื่อง ≥90 วัน หรือรหัสโรค N18 — "
                                        "ควรให้ทีมคลินิกไตยืนยันนิยามก่อนใช้รายงานทางการ"})
    if s["rapid_decline"]:
        out.append({"tone": "warn", "text": f"ผู้ป่วย {s['rapid_decline']:,} ราย มี eGFR ลดเร็วกว่า 5 mL/min/1.73m² ต่อปี ควรทบทวนสาเหตุและเฝ้าระวังเป็นพิเศษ"})
    if s["egfr_lt30"]:
        out.append({"tone": "warn", "text": f"ผู้ป่วย eGFR <30 จำนวน {s['egfr_lt30']:,} ราย ควรได้รับการส่งปรึกษาอายุรแพทย์/แพทย์โรคไตและวางแผนการรักษา"})
    return out


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        from queries import hdc_views
        return hdc_views.build_ckd(p)
    data = {"title": TITLE, "subtitle": "ผู้ป่วยไตเรื้อรังที่ รพ. ดูแล นิยามจากผล eGFR และรหัสโรค (ข้อมูล รพ. จาก HOSxP)",
            "monthly_title": "ผู้ป่วย CKD ที่ได้ตรวจ eGFR รายเดือน"}
    core = sections.safe("ผู้ป่วย CKD", _core, p)
    if "error" in core:
        data.update(kpis=core, donut=core, table=core, monthly=core, extra=[core])
        return data
    sd = sections.safe("ตัวชี้วัดการชะลอไตเสื่อม", _slowdown_core, p, core)
    data.update(kpis=_kpis(core), donut=_donut(core), table=_table(core), notes=_notes(core) + _slow_notes(sd),
                monthly=sections.safe("แนวโน้มรายเดือน", _monthly, p, core),
                extra=[_slowdown_table(sd, core["label"]), _indicators(core, sd)])
    return data

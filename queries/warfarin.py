"""หน้า Warfarin — คลินิกวาร์ฟาริน

ทะเบียน warfarin ใน HOSxP ว่าง (clinicmember รหัส 026 ไม่มีสมาชิก) จึงกำหนดผู้ป่วยจากการจ่ายยา warfarin (DRUG_WARFARIN)
ในช่วง แล้วดูผล INR (LAB_INR) เฉพาะผู้ป่วยกลุ่มนั้น (INR ของหอผู้ป่วยในที่ไม่ได้ใช้ warfarin จะไม่ถูกนับ)
ตัวชี้วัดหลักคือ TTR (Rosendaal) · รายการเตือนแสดงเป็นจำนวน ไม่ระบุตัวผู้ป่วย
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Dict, List, Tuple

import classify
import config
import periods
import sections
import ui
from queries import clinic_lists, common

TITLE = "วาร์ฟาริน (Warfarin)"
NODATA = "ไม่มีข้อมูล"
GREEN, AMBER, RED = "#16a34a", "#f59e0b", "#ef4444"
CRITICAL_HIGH, CRITICAL_LOW = 4.5, 1.5

Series = Dict[str, List[Tuple[date, float]]]


def summarize(series: Series, p, patients: int = None) -> dict:
    groups = {"in": 0, "low": 0, "high": 0}
    critical = critical_patients = total = 0
    ttrs, gaps = [], []
    for pts in series.values():
        pts = sorted(pts)
        over = False
        for _d, v in pts:
            groups[classify.inr_group(v)] += 1
            total += 1
            if v > CRITICAL_HIGH:
                critical += 1
                over = True
        critical_patients += over
        gaps += [(b[0] - a[0]).days for a, b in zip(pts, pts[1:])]
        t = classify.ttr_rosendaal(pts, config.INR_LOW, config.INR_HIGH)
        if t is not None:
            ttrs.append(t)
    return {"patients": len(series) if patients is None else patients,
            "inr_in": groups["in"], "inr_low": groups["low"], "inr_high": groups["high"], "inr_total": total,
            "in_pct": ui.pct(groups["in"], total),
            "critical_gt45": critical, "critical_patients": critical_patients,
            "ttr_patients": len(ttrs), "ttr_mean": round(sum(ttrs) / len(ttrs), 1) if ttrs else None,
            "ttr_ge_target_pct": ui.pct(sum(1 for t in ttrs if t >= config.TTR_TARGET), len(ttrs)) if ttrs else None,
            "ttr_below": sum(1 for t in ttrs if t < config.TTR_TARGET),
            "median_gap_days": float(statistics.median(gaps)) if gaps else None}


def recent_inr(series: Series, on: date, days: int = 90) -> int:
    """ผู้ป่วยที่มีผล INR ภายใน days วันก่อนวันที่ on"""
    since = on - timedelta(days=days)
    return sum(1 for pts in series.values() if any(since <= d <= on for d, _v in pts))


def alert_rows(series: Series, limit: int = 5) -> List[list]:
    """รายการเตือน INR >4.5 / <1.5 รวมนับตามวัน (ล่าสุดก่อน) — ไม่มี HN"""
    counts: Dict[Tuple[date, str], int] = {}
    for pts in series.values():
        for d, v in pts:
            kind = "INR >4.5" if v > CRITICAL_HIGH else "INR <1.5" if v < CRITICAL_LOW else None
            if kind:
                counts[(d, kind)] = counts.get((d, kind), 0) + 1
    order = sorted(counts, key=lambda k: (k[0], k[1]), reverse=True)[:limit]
    return [[ui.thai_date(d), kind, ui.fmt_int(counts[(d, kind)])] for d, kind in order]


def _core(p):
    cohort = common.drug_hns(config.DRUG_WARFARIN, None, p)
    series = {hn: s for hn, s in common.lab_series_by_hn(config.LAB_INR, None, p.start, p.end).items() if hn in cohort}
    summary = summarize(series, p, patients=len(cohort))
    bleeding = common.icd_hns(config.ICD_BLEEDING, p) & cohort
    return {"cohort": cohort, "series": series, "summary": summary, "label": p.label,
            "bleeding": len(bleeding), "bleeding_hns": bleeding,
            "recent": recent_inr(series, min(p.end, common.today()))}


def _monthly(p):
    return {"labels": [label for _d, label in periods.months(p)],
            "series": [{"name": "ครั้งที่รับยา warfarin", "values": common.drug_monthly_visits(config.DRUG_WARFARIN, p), "color": "#1d6ff2"}]}


def _chip(value, target):
    if value is None:
        return {"text": NODATA, "chip": "warn"}
    return {"text": "ผ่าน", "chip": "ok"} if value >= target else {"text": "ต่ำกว่าเป้า", "chip": "bad"}


def _kpis(core):
    s, n = core["summary"], core["summary"]["patients"]
    return [
        {"label": "ผู้ป่วยที่ได้รับ warfarin", "value": ui.fmt_int(n), "unit": "ราย", "tone": "blue", "icon": "pill",
         "sub": f"ตรวจ INR {s['inr_total']:,} ครั้ง"},
        {"label": f"INR อยู่ในเกณฑ์ ({config.INR_LOW:g}–{config.INR_HIGH:g})", "value": ui.fmt_int(s["inr_in"]), "unit": "ครั้ง", "tone": "green",
         "icon": "target", "sub": f"{ui.fmt_pct(s['in_pct'])} ของผล INR ทั้งหมด"},
        {"label": "เหตุการณ์เลือดออก", "value": ui.fmt_int(core["bleeding"]), "unit": "ราย", "tone": "red", "icon": "droplet",
         "sub": "นับจากรหัสโรคในผู้ป่วย warfarin"},
        {"label": "มี INR ใน 90 วันล่าสุด", "value": ui.fmt_int(core["recent"]), "unit": "ราย", "tone": "purple", "icon": "calendar-check",
         "sub": f"{ui.fmt_pct(ui.pct(core['recent'], n))} ของผู้ป่วย warfarin"}]


def _donut(core):
    s = core["summary"]
    return {"title": "สถานะการควบคุมค่า INR (ผลทั้งหมดในช่วง)", "center": ui.fmt_pct(s["in_pct"]),
            "total_label": f"รวมผล INR ทั้งหมด {s['inr_total']:,} ครั้ง",
            "parts": [(f"อยู่ในเกณฑ์ ({config.INR_LOW:g}–{config.INR_HIGH:g})", s["inr_in"], GREEN),
                      (f"ต่ำกว่าเกณฑ์ (<{config.INR_LOW:g})", s["inr_low"], AMBER),
                      (f"สูงกว่าเกณฑ์ (>{config.INR_HIGH:g})", s["inr_high"], RED)]}


def _table(core):
    s = core["summary"]
    L = clinic_lists.link
    n = s["patients"]
    return {"title": f"ตัวชี้วัดสำคัญ (KPI) Warfarin Clinic · {core['label']}", "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลการดำเนินงาน", "สถานะ"],
            "rows": [
                [{"text": "ผู้ป่วยที่ได้รับ warfarin ในช่วง (ราย)", "list": L("warfarin", "all", n)}, "—", ui.fmt_int(n), ""],
                [f"ร้อยละ INR อยู่ในเกณฑ์ ({config.INR_LOW:g}–{config.INR_HIGH:g})", f"≥ {config.TARGET_INR_IN_RANGE:.0f}%",
                 ui.fmt_pct(s["in_pct"]), _chip(s["in_pct"], config.TARGET_INR_IN_RANGE)],
                ["TTR เฉลี่ย (Rosendaal, ผู้ที่ตรวจ INR ≥2 ครั้ง)", f"≥ {config.TTR_TARGET:.0f}%",
                 ui.fmt_pct(s["ttr_mean"]), _chip(s["ttr_mean"], config.TTR_TARGET)],
                [{"text": "ร้อยละผู้ป่วยที่ TTR ถึงเป้า", "list": L("warfarin", "ttr_below", s.get("ttr_below"))},
                 "—", ui.fmt_pct(s["ttr_ge_target_pct"]), ""],
                [{"text": "เหตุการณ์เลือดออก (ราย)", "list": L("warfarin", "bleeding", core["bleeding"])}, "—", ui.fmt_int(core["bleeding"]), ""],
                [{"text": f"INR >{CRITICAL_HIGH:g} (ครั้ง)", "sub": f"ผู้ป่วย {s['critical_patients']:,} ราย",
                  "list": L("warfarin", "critical_high", s["critical_patients"])}, "—", ui.fmt_int(s["critical_gt45"]), ""],
                [{"text": "ผู้ป่วยที่ไม่มีผล INR ใน 90 วันล่าสุด (ราย)", "list": L("warfarin", "no_recent", n - core["recent"])},
                 "—", ui.fmt_int(n - core["recent"]), ""],
                ["ช่วงห่างระหว่างตรวจ INR (มัธยฐาน, วัน)", "—", "—" if s["median_gap_days"] is None else f"{s['median_gap_days']:.0f}", ""],
                ["Identification Error (ครั้ง)", "0", NODATA, {"text": NODATA, "chip": "warn"}]]}


def _alerts(core):
    return {"title": "รายการที่ต้องติดตาม (นับจำนวน ไม่ระบุตัวผู้ป่วย)", "columns": ["วันที่", "รายการ", "จำนวน (ครั้ง)"],
            "rows": alert_rows(core["series"])}


def _notes(core):
    s, out = core["summary"], []
    if s["ttr_mean"] is not None and s["ttr_mean"] < config.TTR_TARGET:
        out.append({"tone": "warn", "text": f"TTR เฉลี่ย {ui.fmt_pct(s['ttr_mean'])} ต่ำกว่าเป้า {config.TTR_TARGET:.0f}% — ทบทวนการปรับขนาดยา การให้ความรู้ และยา/อาหารที่มีปฏิกิริยา"})
    if s["critical_gt45"]:
        out.append({"tone": "warn", "text": f"พบ INR >4.5 จำนวน {s['critical_gt45']:,} ครั้ง ({s['critical_patients']:,} ราย) เสี่ยงเลือดออก ควรติดตามตามแนวทาง"})
    out.append({"tone": "info", "text": "ผู้ป่วยในหน้านี้นับจากการจ่ายยา warfarin ในช่วงที่เลือก (ทะเบียนคลินิกวาร์ฟารินใน HOSxP ไม่มีข้อมูล) "
                                        "และไม่มีบันทึก Identification Error ใน HOSxP"})
    return out


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        return {"title": TITLE + " · HDC", "subtitle": "ไม่มีตัวชี้วัดคลินิกวาร์ฟารินใน HDC",
                "notes": [{"tone": "info", "text": "HDC ไม่มีตัวชี้วัดของคลินิกวาร์ฟาริน — กรุณาดูข้อมูลฝั่ง HOSxP (กดปุ่ม HOSxP ด้านบน)"}]}
    data = {"title": TITLE, "subtitle": "ผู้ป่วยที่ได้รับ warfarin และคุณภาพการคุมค่า INR (ข้อมูล รพ. จาก HOSxP)",
            "monthly_title": "แนวโน้มจำนวนครั้งที่รับยา warfarin รายเดือน"}
    core = sections.safe("ผู้ป่วย warfarin", _core, p)
    if "error" in core:
        data.update(kpis=core, donut=core, table=core, recent=core)
    else:
        data.update(kpis=_kpis(core), donut=_donut(core), table=_table(core), recent=_alerts(core), notes=_notes(core))
    data["monthly"] = sections.safe("แนวโน้มรายเดือน", _monthly, p)
    data["extra"] = []
    return data

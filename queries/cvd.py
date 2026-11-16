"""หน้า CVD — หลอดเลือดสมอง (stroke) และกล้ามเนื้อหัวใจขาดเลือด (AMI)

ไม่มีทะเบียนคลินิก จึงนับจากรหัสโรคใน ovstdiag/iptdiag (ICD_STROKE, ICD_AMI ตั้งผ่าน env)
  • ผู้ป่วยในช่วง = มีรหัสโรคนี้ในช่วงที่เลือก (แยกรายใหม่ = ไม่มีรหัสเดียวกันใน 3 ปีก่อนหน้า)
  • กลุ่มที่รู้จัก (cohort) = มีรหัสโรคนี้ในช่วง 3 ปีย้อนหลังจากสิ้นช่วง — ใช้วัดการป้องกันการเป็นซ้ำและช่องว่างทะเบียน HT/DM
ตัวหารของร้อยละใช้กลุ่มทั้งหมด (คนที่ไม่มีข้อมูลนับในตัวหาร) · รายการรหัสยาให้เภสัชกรยืนยัน
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Dict, Optional, Set

import classify
import config
import periods
import sections
import ui
from queries import clinic_lists, common

TITLE = "หลอดเลือดสมอง/หัวใจ (CVD)"
NODATA = "ไม่มีข้อมูล"
BLUE, GREEN, AMBER, RED, GREY = "#2563eb", "#16a34a", "#f59e0b", "#ef4444", "#94a3b8"


def _years_back(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                       # 29 ก.พ.
        return d.replace(year=d.year - years, day=28)


def split_new_vs_prior(current: Set[str], prior: Set[str]) -> dict:
    return {"new": len(current - prior), "prior_known": len(current & prior), "total": len(current)}


def registry_overlap(hns: Set[str], ht: Set[str], dm: Set[str]) -> dict:
    """ผู้ป่วยกลุ่ม hns อยู่ในทะเบียน HT/DM กี่ราย (HT∩DM ซ้อนกันได้ → in_any ≠ in_ht + in_dm)"""
    total, in_any = len(hns), len(hns & (ht | dm))
    return {"total": total, "in_ht": len(hns & ht), "in_dm": len(hns & dm), "in_any": in_any,
            "in_neither": total - in_any,
            "in_ht_pct": ui.pct(len(hns & ht), total), "in_dm_pct": ui.pct(len(hns & dm), total),
            "in_neither_pct": ui.pct(total - in_any, total)}


def secondary_prevention(cohort: Set[str], statin: Set[str], antithrombotic: Set[str], bp: Dict[str, tuple],
                         hba1c: Dict[str, Optional[float]], dm: Set[str], visited: Set[str]) -> dict:
    n = len(cohort)
    dm_in = cohort & dm
    bp_ok = sum(1 for hn in cohort if hn in bp and classify.bp_group(*bp[hn]) == "controlled")
    a1c_ok = sum(1 for hn in dm_in if hba1c.get(hn) is not None and hba1c[hn] < config.HBA1C_TARGET)
    return {"n": n, "dm_in_cohort": len(dm_in),
            "statin_pct": ui.pct(len(statin & cohort), n), "antithrombotic_pct": ui.pct(len(antithrombotic & cohort), n),
            "bp_controlled_pct": ui.pct(bp_ok, n), "hba1c_lt7_pct": ui.pct(a1c_ok, len(dm_in)),
            "visited_pct": ui.pct(len(visited & cohort), n),
            # จำนวนกลุ่มที่ยังไม่ได้ (ใช้กับลิงก์รายชื่อ — ต้องตรงกับ clinic_lists.cvd_groups)
            "miss": {"no_statin": n - len(statin & cohort), "no_antithrombotic": n - len(antithrombotic & cohort),
                     "bp_not_controlled": n - bp_ok, "a1c_not": len(dm_in) - a1c_ok, "not_visited": n - len(visited & cohort)}}


def _core(p):
    on = min(p.end, common.today())
    both = config.ICD_STROKE + config.ICD_AMI
    stroke, ami = common.icd_hns(config.ICD_STROKE, p), common.icd_hns(config.ICD_AMI, p)
    current = stroke | ami
    prior = common.icd_hns(both, replace(p, start=_years_back(p.start, 3), end=p.start - timedelta(days=1)))
    cohort = common.icd_hns(both, replace(p, start=_years_back(on, 3), end=on))
    cl = list(cohort)
    fy_p = periods.make(p.fy)       # ยา/ความดัน/HbA1c/มารับบริการ ดูทั้งปีงบ ไม่ใช่เฉพาะเดือน/ไตรมาสที่เลือก (กลุ่มคือผู้ป่วย 3 ปี)
    antithrombotic_codes = config.DRUG_ANTIPLATELET + config.DRUG_WARFARIN
    hba1c = {r["hn"]: r["value"] for r in common.latest_lab_by_hn(config.LAB_HBA1C, config.CLINIC_DM, fy_p) if r["hn"] in cohort}
    sec_in = dict(cohort=cohort, statin=common.drug_hns(config.DRUG_STATIN, None, fy_p),
                  antithrombotic=common.drug_hns(antithrombotic_codes, None, fy_p), bp=common.bp_latest_for_hns(cl, fy_p),
                  hba1c=hba1c, dm=set(common.registry_hns(config.CLINIC_DM, fy_p)), visited=common.visited_among(cl, fy_p))
    ht = set(common.registry_hns(config.CLINIC_HT, fy_p))
    return {
        "stroke": stroke, "ami": ami, "current": current, "prior": prior, "split": split_new_vs_prior(current, prior), "cohort": cohort,
        "admits": common.icd_admissions(both, p), "deaths": common.icd_deaths(both, config.DCHSTTS_DEAD, p),
        "sec_in": sec_in, "ht": ht, "sec": secondary_prevention(**sec_in),
        "overlap": registry_overlap(cohort, ht, sec_in["dm"]),
        "types": [(name, len(common.icd_hns(ids, p))) for name, ids in (
            ("Ischemic stroke (I63)", ["I63"]), ("Hemorrhagic stroke (I60–I62)", ["I60", "I61", "I62"]),
            ("Stroke ไม่ระบุ (I64)", ["I64"]), ("STEMI/AMI (I21)", ["I21"]), ("AMI ซ้ำ (I22)", ["I22"]))],
        "label": p.label}


def _kpis(core):
    return [
        {"label": "ผู้ป่วย stroke", "value": ui.fmt_int(len(core["stroke"])), "unit": "ราย", "tone": "purple", "icon": "heart-pulse",
         "sub": "รหัส " + ",".join(config.ICD_STROKE)},
        {"label": "ผู้ป่วย AMI", "value": ui.fmt_int(len(core["ami"])), "unit": "ราย", "tone": "red", "icon": "activity",
         "sub": "รหัส " + ",".join(config.ICD_AMI)},
        {"label": "Admit ด้วยโรคกลุ่มนี้", "value": ui.fmt_int(core["admits"]), "unit": "ครั้ง", "tone": "orange", "icon": "triangle-alert",
         "sub": "นับ an ไม่ซ้ำ"},
        {"label": "เสียชีวิตใน รพ.", "value": ui.fmt_int(core["deaths"]), "unit": "ราย", "tone": "blue", "icon": "users",
         "sub": "จำหน่ายสถานะตาย (ipt.dchstts)"}]


def _donut(core):
    s = core["split"]
    return {"title": "ผู้ป่วย stroke/AMI ในช่วง: รายใหม่ / เคยเป็นมาก่อน", "center": ui.fmt_int(s["total"]) if s["total"] else "—",
            "total_label": f"ผู้ป่วยในช่วง {s['total']:,} ราย (รายใหม่ = ไม่มีรหัสเดียวกันใน 3 ปีก่อนหน้า)",
            "parts": [("รายใหม่", s["new"], RED), ("เคยเป็นมาก่อน", s["prior_known"], BLUE)],
            "lists": [clinic_lists.link("cvd", "new", s["new"]), clinic_lists.link("cvd", "prior_known", s["prior_known"])]}


def _types_table(core):
    L = clinic_lists.link
    top = [[{"text": "Stroke ทั้งหมด (รหัส " + ",".join(config.ICD_STROKE) + ")", "cls": "tot", "list": L("cvd", "stroke", len(core["stroke"]))},
            ui.fmt_int(len(core["stroke"]))],
           [{"text": "AMI ทั้งหมด (รหัส " + ",".join(config.ICD_AMI) + ")", "cls": "tot", "list": L("cvd", "ami", len(core["ami"]))},
            ui.fmt_int(len(core["ami"]))]]
    return {"title": f"ชนิดของโรค · {core['label']}", "columns": ["ชนิด/รหัสโรค", "ผู้ป่วย (ราย)"],
            "rows": top + [[n, ui.fmt_int(v)] for n, v in core["types"]]}


def _sec_table(core):
    s = core["sec"]
    miss = s.get("miss", {})

    def row(name, denom, v, g):
        return [{"text": name, "list": clinic_lists.link("cvd", g, miss.get(g))}, denom, ui.fmt_pct(v) if v is not None else "—"]

    n, dn = f"{s['n']:,} ราย", f"{s['dm_in_cohort']:,} ราย"
    return {"type": "table", "title": "การป้องกันการเป็นซ้ำ (ผู้ป่วย stroke/AMI ที่รู้จักในช่วง 3 ปี)",
            "columns": ["ตัวชี้วัด", "ตัวหาร", "ผลการดำเนินงาน"],
            "rows": [row("ได้รับยา statin ในช่วง", n, s["statin_pct"], "no_statin"),
                     row("ได้รับยาต้านเกล็ดเลือด/ต้านการแข็งตัว", n, s["antithrombotic_pct"], "no_antithrombotic"),
                     row("ความดันล่าสุด <140/90", n, s["bp_controlled_pct"], "bp_not_controlled"),
                     row("HbA1c ล่าสุด <7% (เฉพาะที่เป็น DM)", dn, s["hba1c_lt7_pct"], "a1c_not"),
                     row("มารับบริการในช่วง", n, s["visited_pct"], "not_visited")]}


def _overlap_tiles(core):
    o = core["overlap"]
    return {"type": "tiles", "title": "ผู้ป่วยที่อยู่ในทะเบียน HT/DM (ช่องว่างการดูแลปฐมภูมิ)", "items": [
        {"label": "อยู่ในทะเบียน HT", "value": ui.fmt_pct(o["in_ht_pct"]), "sub": f"{o['in_ht']:,} ราย", "tone": "blue"},
        {"label": "อยู่ในทะเบียน DM", "value": ui.fmt_pct(o["in_dm_pct"]), "sub": f"{o['in_dm']:,} ราย", "tone": "purple"},
        {"label": "ไม่อยู่ในทั้งสองทะเบียน", "value": ui.fmt_pct(o["in_neither_pct"]), "sub": f"{o['in_neither']:,} ราย (ควรทบทวนความเสี่ยง)",
         "tone": "orange", "list": clinic_lists.link("cvd", "in_neither", o["in_neither"])}]}


def _notes(core):
    s, out = core["sec"], []
    if s["statin_pct"] is not None and s["statin_pct"] < config.TARGET_STATIN:
        out.append({"tone": "warn", "text": f"ผู้ป่วย stroke/AMI ได้รับยา statin เพียง {ui.fmt_pct(s['statin_pct'])} — ควรทบทวนการป้องกันการเป็นซ้ำ (ตรวจรายการรหัสยากับเภสัชกร)"})
    if core["overlap"]["in_neither"]:
        out.append({"tone": "info", "text": f"ผู้ป่วย {core['overlap']['in_neither']:,} ราย ไม่อยู่ในทะเบียน HT/DM — อาจมีความเสี่ยงที่ยังไม่ได้รับการดูแลต่อเนื่อง"})
    out.append({"tone": "info", "text": "นับจากรหัสโรคใน HOSxP (ไม่มีทะเบียนคลินิก) · ยังไม่รวม door-to-needle/Fast track และ CVD risk score (เฟสถัดไป)"})
    return out


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        from queries import hdc_views
        return hdc_views.build_cvd(p)
    data = {"title": TITLE, "subtitle": "ผู้ป่วย stroke/AMI นับจากรหัสโรค และการป้องกันการเป็นซ้ำ (ข้อมูล รพ. จาก HOSxP)"}
    core = sections.safe("หลอดเลือดสมอง/หัวใจ", _core, p)
    if "error" in core:
        data.update(kpis=core, donut=core, table=core, extra=[core])
        return data
    data.update(kpis=_kpis(core), donut=_donut(core), table=_types_table(core),
                extra=[_sec_table(core), _overlap_tiles(core)], notes=_notes(core))
    return data

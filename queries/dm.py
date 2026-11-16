"""หน้า DM — คลินิกโรคเบาหวาน

นับ HbA1c <7 รายคนจากผลล่าสุด (ที่อ่านเป็นตัวเลขได้) ของปีงบ ตัวหาร = ผู้ป่วยในทะเบียนที่ยังติดตาม
คนที่ไม่ได้เจาะ HbA1c นับในตัวหารและแสดง "ร้อยละที่ได้เจาะ" คู่กัน
"""
from __future__ import annotations

from typing import List

import classify
import config
import periods
import sections
import ui
from queries import clinic_lists, common, remission, remission_claim

TITLE = "เบาหวาน (DM)"
GREEN, AMBER, RED, GREY = "#16a34a", "#f59e0b", "#ef4444", "#94a3b8"
NODATA = "ไม่มีข้อมูล"


def summarize_hba1c(latest: List[dict], registry: int) -> dict:
    g = {"lt7": 0, "7to79": 0, "ge8": 0}
    ge9 = 0
    for r in latest:
        grp = classify.hba1c_group(r["value"])
        if grp:
            g[grp] += 1
            if r["value"] >= 9:
                ge9 += 1
    tested = sum(g.values())
    return {**g, "ge9": ge9, "tested": tested, "registry": registry, "no_value": max(registry - tested, 0),
            "lt7_pct": ui.pct(g["lt7"], registry), "tested_pct": ui.pct(tested, registry)}


def status_by_hn(latest: List[dict]) -> dict:
    """HN → 'controlled' (HbA1c <7) | 'partial' (≥7) | None (ไม่มีค่า)"""
    out = {}
    for r in latest:
        grp = classify.hba1c_group(r["value"])
        out[r["hn"]] = None if grp is None else ("controlled" if grp == "lt7" else "partial")
    return out


def _core(clinic, p, prev):
    registry = common.registry_count(clinic, p)
    latest = common.latest_lab_by_hn(config.LAB_HBA1C, clinic, p)
    return {"registry": registry, "prev_registry": common.registry_count(clinic, prev),
            "visits": common.visit_count(clinic, p), "visited": common.visited_patients(clinic, p),
            "latest": latest, "summary": summarize_hba1c(latest, registry), "label": p.label}


def _monthly(clinic, p):
    return {"labels": [label for _d, label in periods.months(p)],
            "series": [{"name": "ครั้งที่มารับบริการ", "values": common.monthly_visits(clinic, p), "color": "#1d6ff2"},
                       {"name": "ผู้ป่วยรายใหม่ (ขึ้นทะเบียน)", "values": common.new_members_by_month(clinic, p), "color": "#10b981"}]}


def _tested_pct(codes, clinic, p, registry, allow_zero=False):
    if not codes:
        return None
    return ui.pct(sum(1 for r in common.latest_lab_by_hn(list(codes), clinic, p, allow_zero) if r["value"] is not None), registry)


def _screening(clinic, p, core):
    reg = core["registry"]
    statin = (ui.pct(len(common.drug_hns(config.DRUG_STATIN, clinic, p)), reg) if config.DRUG_STATIN else None)
    items = [("HbA1c", core["summary"]["tested_pct"]), ("eGFR", _tested_pct([config.LAB_EGFR], clinic, p, reg)),
             ("ไมโครอัลบูมิน/UACR", _tested_pct(config.LAB_UACR, clinic, p, reg, allow_zero=True)),
             ("ไขมัน LDL", _tested_pct(config.LAB_LDL, clinic, p, reg)),
             ("ตรวจจอประสาทตา", None), ("ตรวจเท้า", None), ("ได้รับยา statin", statin)]
    # ตา/เท้า: ตารางบันทึกการคัดกรองภาวะแทรกซ้อนใน HOSxP นี้ว่าง จึงไม่มีข้อมูล (ฝั่ง HDC มีเฉพาะการตรวจตา)
    return {"type": "table", "title": "การตรวจภาวะแทรกซ้อนประจำปี (ร้อยละของผู้ป่วยในทะเบียน)",
            "columns": ["รายการ", "ผลการดำเนินงาน"],
            "rows": [[name, ui.fmt_pct(v) if v is not None else NODATA] for name, v in items]}


def _watch(clinic, p):
    hypo = len(common.icd_hns(config.ICD_HYPOGLYCEMIA, p, clinic))
    aki = len(common.icd_hns(config.ICD_AKI, p, clinic))
    return {"type": "tiles", "title": "ภาวะเฝ้าระวัง (นับจากรหัสโรค ICD-10)", "items": [
        {"label": "น้ำตาลในเลือดต่ำ", "value": ui.fmt_int(hypo), "sub": "ราย (รหัส " + ",".join(config.ICD_HYPOGLYCEMIA) + ")", "tone": "orange"},
        {"label": "ไตวายเฉียบพลัน (AKI)", "value": ui.fmt_int(aki), "sub": "ราย (รหัส " + ",".join(config.ICD_AKI) + ")", "tone": "red"}]}


def _urgent(clinic, p, summary):
    gaps = common.followup_gaps(clinic, p, min(p.end, common.today()))
    L = clinic_lists.link
    return {"type": "tiles", "title": "กลุ่มที่ต้องติดตามเร่งด่วน", "items": [
        {"label": "HbA1c ≥9", "value": ui.fmt_int(summary["ge9"]), "sub": "ราย (ผลล่าสุด)", "tone": "red", "list": L("dm", "ge9", summary["ge9"])},
        {"label": "ขาดนัด >3 เดือน", "value": ui.fmt_int(gaps["lost_3m"]), "sub": "ราย (ไม่มี visit ใน 90 วัน)", "tone": "purple",
         "list": L("dm", "lost_3m", gaps["lost_3m"])},
        {"label": "นัดเลยกำหนด", "value": ui.fmt_int(gaps["overdue"]), "sub": "ราย", "tone": "blue", "list": L("dm", "overdue", gaps["overdue"])}]}


def _recent(clinic, p):
    d = common.daily_counts(clinic, p, [config.LAB_HBA1C])
    cols = ["วันที่", "รายการ", "จำนวน"]
    if not d:
        return {"title": "รายการล่าสุด", "columns": cols, "rows": []}
    day = ui.thai_date(d["date"])
    return {"title": "รายการล่าสุด (วันที่มีผู้รับบริการล่าสุด)", "columns": cols,
            "rows": [[day, "ผู้รับบริการ DM (ครั้ง)", ui.fmt_int(d["visits"])],
                     [day, "ผู้ป่วยที่เจาะ HbA1c (ราย)", ui.fmt_int(d["labs"])]]}


def _chip(value, target):
    if value is None:
        return {"text": NODATA, "chip": "warn"}
    return {"text": "ผ่าน", "chip": "ok"} if value >= target else {"text": "ต่ำกว่าเป้า", "chip": "bad"}


def _kpis(core):
    s, reg = core["summary"], core["registry"]
    return [
        {"label": "ผู้ป่วยในทะเบียน", "value": ui.fmt_int(reg), "unit": "ราย", "tone": "blue", "icon": "users",
         "sub": f"มารับบริการ {core['visits']:,} ครั้ง", "delta": ui.delta(reg, core["prev_registry"])},
        {"label": "ควบคุมได้ (HbA1c <7%)", "value": ui.fmt_int(s["lt7"]), "unit": "ราย", "tone": "green", "icon": "droplet",
         "sub": f"{ui.fmt_pct(s['lt7_pct'])} ของทะเบียน"},
        {"label": "ควบคุมไม่ได้ (HbA1c ≥8%)", "value": ui.fmt_int(s["ge8"]), "unit": "ราย", "tone": "orange", "icon": "triangle-alert",
         "sub": f"{ui.fmt_pct(ui.pct(s['ge8'], reg))} ของทะเบียน"},
        {"label": "ติดตามต่อเนื่อง", "value": ui.fmt_int(core["visited"]), "unit": "ราย", "tone": "purple", "icon": "calendar-check",
         "sub": f"{ui.fmt_pct(ui.pct(core['visited'], reg))} ของทะเบียนมารับบริการ"}]


def _donut(core):
    s = core["summary"]
    return {"title": "สถานะการควบคุมเบาหวาน (HbA1c ล่าสุดรายคน)", "center": ui.fmt_pct(s["lt7_pct"]),
            "total_label": f"ผู้ป่วย DM ในทะเบียน {core['registry']:,} ราย (เจาะ HbA1c {ui.fmt_pct(s['tested_pct'])})",
            "parts": [("ควบคุมได้ (<7%)", s["lt7"], GREEN), ("ปานกลาง (7–7.9%)", s["7to79"], AMBER),
                      ("ควบคุมไม่ได้ (≥8%)", s["ge8"], RED), ("ไม่ได้เจาะ HbA1c", s["no_value"], GREY)],
            "lists": [clinic_lists.link("dm", g, n) for g, n in
                      (("lt7", s["lt7"]), ("7to79", s["7to79"]), ("ge8", s["ge8"]), ("no_a1c", s["no_value"]))]}


def _table(core):
    s = core["summary"]
    follow = ui.pct(core["visited"], core["registry"])
    L = clinic_lists.link
    return {"title": f"ตัวชี้วัดสำคัญ DM Clinic · {core['label']}", "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลการดำเนินงาน", "สถานะ"],
            "rows": [[{"text": "ร้อยละผู้ป่วยควบคุมน้ำตาลได้ (HbA1c <7% ค่าล่าสุดรายคน)", "list": L("dm", "above7", s["7to79"] + s["ge8"])},
                      f"≥ {config.TARGET_DM_CONTROL:.0f}%", ui.fmt_pct(s["lt7_pct"]), _chip(s["lt7_pct"], config.TARGET_DM_CONTROL)],
                     [{"text": "ร้อยละผู้ป่วยที่ได้เจาะ HbA1c ในช่วง", "list": L("dm", "no_a1c", s["no_value"])},
                      "—", ui.fmt_pct(s["tested_pct"]), ""],
                     [{"text": "ร้อยละผู้ป่วยมารับบริการต่อเนื่อง", "list": L("dm", "not_visited", core["registry"] - core["visited"])},
                      f"≥ {config.TARGET_FOLLOWUP:.0f}%", ui.fmt_pct(follow), _chip(follow, config.TARGET_FOLLOWUP)]]}


def _notes(core):
    s, out = core["summary"], []
    if s["lt7_pct"] is not None and s["lt7_pct"] < config.TARGET_DM_CONTROL:
        out.append({"tone": "warn", "text": f"ควบคุมน้ำตาลได้ (HbA1c <7%) {ui.fmt_pct(s['lt7_pct'])} ต่ำกว่าเป้า {config.TARGET_DM_CONTROL:.0f}% "
                                            f"(ตัวหารรวมผู้ที่ไม่ได้เจาะ HbA1c {s['no_value']:,} ราย)"})
    if s["registry"] and s["no_value"]:
        out.append({"tone": "info", "text": f"ผู้ป่วย {s['no_value']:,} ราย ({ui.fmt_pct(ui.pct(s['no_value'], s['registry']))}) ไม่มีผล HbA1c ในช่วงนี้ — "
                                            "กลุ่มที่ไม่ได้ตรวจมักเป็นกลุ่มเสี่ยง ควรได้รับการเจาะและติดตาม"})
    if s["ge9"]:
        out.append({"tone": "warn", "text": f"ผู้ป่วย HbA1c ≥9% {s['ge9']:,} ราย ควรทบทวนแผนการรักษาเร่งด่วน"})
    return out


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        from queries import hdc_views
        return hdc_views.build_dm(p)
    clinic, prev = config.CLINIC_DM, periods.previous(p)
    data = {"title": TITLE, "subtitle": "ติดตามการควบคุมระดับน้ำตาลสะสมของผู้ป่วยในทะเบียนคลินิก DM (ข้อมูล รพ. จาก HOSxP)",
            "monthly_title": "แนวโน้มผู้รับบริการและผู้ป่วยรายใหม่รายเดือน"}
    core = sections.safe("HbA1c", _core, clinic, p, prev)
    if "error" in core:
        data.update(kpis=core, donut=core, table=core)
        data["extra"] = [{"error": "ภาวะแทรกซ้อนและการติดตาม: ดึงข้อมูลไม่ได้"}]
    else:
        data.update(kpis=_kpis(core), donut=_donut(core), table=_table(core),
                    notes=_notes(core) + remission.notes(p) + remission_claim.notes())
        status = status_by_hn(core["latest"])
        data["extra"] = [sections.safe("DM remission", remission.section, p),
                         sections.safe("เบิกงบบริการ DM Remission", remission_claim.section, p),
                         sections.safe("ภาวะแทรกซ้อนประจำปี", _screening, clinic, p, core),
                         sections.safe("ภาวะเฝ้าระวัง", _watch, clinic, p),
                         sections.safe("กลุ่มเร่งด่วน", _urgent, clinic, p, core["summary"]),
                         sections.safe("แยกกลุ่มอายุ", common.group_table, clinic, p, status, "age", "ควบคุมน้ำตาลได้ (HbA1c <7%) "),
                         sections.safe("แยกเพศ", common.group_table, clinic, p, status, "sex", "ควบคุมน้ำตาลได้ (HbA1c <7%) ")]
    data["monthly"] = sections.safe("แนวโน้มรายเดือน", _monthly, clinic, p)
    data["recent"] = sections.safe("รายการล่าสุด", _recent, clinic, p)
    return data

"""หน้า COPD / หืด — ทะเบียนคลินิก COPD (024) และหืด (023)

ตัวเลขผู้ป่วยนับ HN ไม่ซ้ำ (ผู้ที่อยู่ทั้งสองทะเบียนนับครั้งเดียว) · ตัวหารของร้อยละ = ผู้ป่วยในทะเบียนที่ยังติดตาม
ร้อยละตรวจสมรรถภาพปอด/ยาพ่นควบคุม นับจากรหัสหัตถการ/ยาที่ตั้งผ่าน env — ตั้งว่างแล้วจะแสดง "ไม่มีข้อมูล"
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import List

import config
import periods
import sections
import ui
from queries import clinic_lists, common

TITLE = "COPD / หืด"
NODATA = "ไม่มีข้อมูล"
BLUE, TEAL, GREEN, GREY = "#2563eb", "#0ea5e9", "#16a34a", "#94a3b8"
GROUPS = {"all": "COPD + หืด", "copd": "COPD", "asthma": "หืด (Asthma)"}


def grp_clinics(grp: str) -> List[str]:
    return {"copd": [config.CLINIC_COPD], "asthma": [config.CLINIC_ASTHMA]}.get(grp, [config.CLINIC_COPD, config.CLINIC_ASTHMA])


def _norm(grp):
    return grp if grp in GROUPS else "all"


def _share(codes, registry):
    """ร้อยละของทะเบียนที่มีรายการในชุดรหัส · ชุดรหัสว่าง (ไม่ได้ตั้งค่า) → None = ไม่มีข้อมูล"""
    return None if not codes else ui.pct(len(codes & registry), len(registry))


def _core(p, grp):
    clinics = grp_clinics(grp)
    regs = {c: set(common.registry_hns(c, p)) for c in clinics}
    registry = set().union(*regs.values())
    visited = set().union(*(common.visited_hns(c, p) for c in clinics)) & registry
    on = min(p.end, common.today())
    icd = (config.ICD_COPD if grp == "copd" else config.ICD_ASTHMA if grp == "asthma" else config.ICD_COPD + config.ICD_ASTHMA)
    gap_hns = set()
    for c, ids in ((config.CLINIC_COPD, config.ICD_COPD), (config.CLINIC_ASTHMA, config.ICD_ASTHMA)):
        if c in regs:
            gap_hns |= common.icd_hns(ids, p) - regs[c]
    # สมรรถภาพปอดมักตรวจครั้งเดียวตอนวินิจฉัย จึงนับย้อนหลังทุกช่วงเวลาจนถึงสิ้นช่วงที่ดู
    spiro = (common.drug_hns(config.PROC_SPIROMETRY, None, replace(p, start=date(1990, 1, 1)))
             if config.PROC_SPIROMETRY else None)
    inhaler = common.drug_hns(config.DRUG_INHALER_CONTROLLER, None, p) if config.DRUG_INHALER_CONTROLLER else None
    lost_hns = set().union(*(common.followup_hns(c, p, on)["lost_3m"] for c in clinics))
    return {"grp": grp, "regs": regs, "registry": registry, "visited": visited, "label": p.label,
            "lost": len(lost_hns), "lost_hns": lost_hns, "gap": len(gap_hns), "gap_hns": gap_hns,
            "admits": common.icd_admissions(icd, p), "spiro": spiro, "inhaler": inhaler}


def _monthly(p, grp):
    per = [common.monthly_visits(c, p) for c in grp_clinics(grp)]
    return {"labels": [label for _d, label in periods.months(p)],
            "series": [{"name": "ครั้งที่มารับบริการ", "values": [sum(v) for v in zip(*per)], "color": "#1d6ff2"}]}


def _kpis(core):
    reg, n = core["registry"], len(core["registry"])
    sub = " · ".join(f"{'COPD' if c == config.CLINIC_COPD else 'หืด'} {len(h):,}" for c, h in core["regs"].items())
    return [
        {"label": "ผู้ป่วยในทะเบียน (ไม่ซ้ำ)", "value": ui.fmt_int(n), "unit": "ราย", "tone": "blue", "icon": "wind", "sub": sub},
        {"label": "มารับบริการในช่วง", "value": ui.fmt_int(len(core["visited"])), "unit": "ราย", "tone": "green", "icon": "calendar-check",
         "sub": f"{ui.fmt_pct(ui.pct(len(core['visited']), n))} ของทะเบียน"},
        {"label": "Admit ด้วย COPD/หืด", "value": ui.fmt_int(core["admits"]), "unit": "ครั้ง", "tone": "red", "icon": "triangle-alert",
         "sub": "ทั้งโรงพยาบาล นับ an ไม่ซ้ำ"},
        {"label": "ขาดนัด >3 เดือน", "value": ui.fmt_int(core["lost"]), "unit": "ราย", "tone": "purple", "icon": "calendar-check",
         "sub": "ไม่มี visit ใน 90 วัน"}]


def _donut(core):
    reg, n = core["registry"], len(core["registry"])
    L = clinic_lists.link
    if len(core["regs"]) == 2:
        nc, na = len(core["regs"][config.CLINIC_COPD]), len(core["regs"][config.CLINIC_ASTHMA])
        return {"title": "ทะเบียนผู้ป่วยแยกโรค", "center": ui.fmt_int(n) if n else "—",
                "total_label": f"ผู้ป่วยไม่ซ้ำ {n:,} ราย", "parts": [("COPD", nc, BLUE), ("หืด (Asthma)", na, TEAL)],
                "lists": [L("copd", "reg_copd", nc), L("copd", "reg_asthma", na)]}
    v = len(core["visited"])
    return {"title": "การมารับบริการของผู้ป่วยในทะเบียน", "center": ui.fmt_pct(ui.pct(v, n)),
            "total_label": f"ผู้ป่วยในทะเบียน {n:,} ราย",
            "parts": [("มารับบริการในช่วง", v, GREEN), ("ไม่ได้มารับบริการ", n - v, GREY)],
            "lists": [L("copd", "visited", v), L("copd", "not_visited", n - v)]}


def _chip(value, target):
    if value is None:
        return {"text": NODATA, "chip": "warn"}
    return {"text": "ผ่าน", "chip": "ok"} if value >= target else {"text": "ต่ำกว่าเป้า", "chip": "bad"}


def _table(core):
    reg = core["registry"]
    sp, ih = _share(core["spiro"], reg), _share(core["inhaler"], reg)
    follow = ui.pct(len(core["visited"]), len(reg))
    L = clinic_lists.link
    no_sp = len(reg - core["spiro"]) if core["spiro"] is not None else 0
    no_ih = len(reg - core["inhaler"]) if core["inhaler"] is not None else 0
    return {"title": f"ตัวชี้วัดสำคัญ {GROUPS[core['grp']]} · {core['label']}", "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลการดำเนินงาน", "สถานะ"],
            "rows": [[{"text": "ร้อยละที่เคยได้รับการตรวจสมรรถภาพปอด (ทุกช่วงเวลา)", "list": L("copd", "no_spiro", no_sp)},
                      "—", ui.fmt_pct(sp) if sp is not None else NODATA, ""],
                     [{"text": "ร้อยละที่ได้รับยาพ่นควบคุมอาการ", "list": L("copd", "no_inhaler", no_ih)},
                      "—", ui.fmt_pct(ih) if ih is not None else NODATA, ""],
                     [{"text": "ร้อยละผู้ป่วยมารับบริการต่อเนื่อง", "list": L("copd", "not_visited", len(reg) - len(core["visited"]))},
                      f"≥ {config.TARGET_FOLLOWUP:.0f}%", ui.fmt_pct(follow), _chip(follow, config.TARGET_FOLLOWUP)]]}


def _gap_tiles(core):
    return {"type": "tiles", "title": "ติดตามผู้ป่วยและช่องว่างของทะเบียน", "items": [
        {"label": "ผู้ป่วยมีรหัสโรคแต่ไม่อยู่ในทะเบียน", "value": ui.fmt_int(core["gap"]), "tone": "orange",
         "sub": "ราย (รหัส " + ",".join(config.ICD_COPD + config.ICD_ASTHMA) + ") — ควรทบทวนเพื่อขึ้นทะเบียน",
         "list": clinic_lists.link("copd", "gap", core["gap"])},
        {"label": "ขาดนัด >3 เดือน", "value": ui.fmt_int(core["lost"]), "tone": "purple", "sub": "ราย (ไม่มี visit ใน 90 วัน)",
         "list": clinic_lists.link("copd", "lost_3m", core["lost"])}]}


def _notes(core):
    out = [{"tone": "info", "text": "ยังไม่พบแหล่งข้อมูลสถานะสูบบุหรี่ใน HOSxP จึงไม่แสดงตัวชี้วัดการสูบบุหรี่"}]
    if core["gap"]:
        out.append({"tone": "warn", "text": f"พบผู้ป่วย {core['gap']:,} ราย ที่มีรหัสโรค COPD/หืดในช่วงนี้แต่ยังไม่อยู่ในทะเบียนคลินิก ควรทบทวนเพื่อขึ้นทะเบียนและติดตาม"})
    return out


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        from queries import hdc_views
        return hdc_views.build_copd(p)
    grp = _norm((opts or {}).get("grp", "all"))
    data = {"title": TITLE, "subtitle": f"ผู้ป่วยในทะเบียนคลินิก {GROUPS[grp]} (ข้อมูล รพ. จาก HOSxP)",
            "monthly_title": "แนวโน้มจำนวนครั้งที่มารับบริการรายเดือน"}
    core = sections.safe("ทะเบียน COPD/หืด", _core, p, grp)
    if "error" in core:
        data.update(kpis=core, donut=core, table=core, extra=[core])
    else:
        data.update(kpis=_kpis(core), donut=_donut(core), table=_table(core), extra=[_gap_tiles(core)], notes=_notes(core))
    data["monthly"] = sections.safe("แนวโน้มรายเดือน", _monthly, p, grp)
    return data

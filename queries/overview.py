"""หน้าภาพรวม NCD — สรุป 6 โรคจากข้อมูลของแต่ละหน้า (ใช้แคชหน้าร่วมกัน) + ผู้ป่วยไม่ซ้ำข้ามโรค

การ์ดของแต่ละโรคอ่านจาก KPI ใบที่ 1 (จำนวนผู้ป่วย) และใบที่ 2 (ตัวชี้วัดหลัก) ของหน้านั้น จึงไม่ซ้ำ query
ผู้ป่วยหนึ่งคนอยู่ได้หลายโรค (เช่น HT∩DM) — "ผู้ป่วย NCD ไม่ซ้ำ" นับ HN ไม่ซ้ำ ไม่ใช่ผลรวมของแต่ละโรค
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Set

import config
import db
import pages
import periods
import sections
import ui
from queries import common

TITLE = "ภาพรวม NCD"
KEYS = ["ht", "dm", "ckd", "warfarin", "copd", "cvd"]
STYLE = {"ht": ("blue", "activity"), "dm": ("orange", "droplet"), "ckd": ("teal", "bean"),
         "warfarin": ("purple", "pill"), "copd": ("green", "wind"), "cvd": ("red", "heart-pulse")}
COLORS = {"ht": "#1d6ff2", "dm": "#f97316"}


def distinct_patients(sets: Dict[str, Set[str]]) -> dict:
    """HN ไม่ซ้ำข้ามโรค (HT∩DM และอื่น ๆ ซ้อนกันได้)"""
    all_hns: Dict[str, int] = {}
    for hns in sets.values():
        for hn in hns:
            all_hns[hn] = all_hns.get(hn, 0) + 1
    return {"total_unique": len(all_hns), "by_disease": {k: len(v) for k, v in sets.items()},
            "overlap_ht_dm": len(sets.get("ht", set()) & sets.get("dm", set())),
            "multi_disease": sum(1 for c in all_hns.values() if c > 1)}


def _in_thread(fn, *args):
    """รันใน worker thread แล้วคืน connection ของเธรดนั้น (db.py เก็บ connection ต่อเธรด)"""
    try:
        return fn(*args)
    finally:
        db.close()


def _patient_sets(p) -> Dict[str, Set[str]]:
    from queries import ckd

    def ckd_set():
        return set(ckd._core(p)["cohort"])

    jobs = {
        "ht": lambda: set(common.registry_hns(config.CLINIC_HT, p)),
        "dm": lambda: set(common.registry_hns(config.CLINIC_DM, p)),
        "ckd": ckd_set,
        "warfarin": lambda: common.drug_hns(config.DRUG_WARFARIN, None, p),
        "copd": lambda: set(common.registry_hns(config.CLINIC_COPD, p)) | set(common.registry_hns(config.CLINIC_ASTHMA, p)),
        "cvd": lambda: common.icd_hns(config.ICD_STROKE + config.ICD_AMI, p),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = {k: ex.submit(_in_thread, fn) for k, fn in jobs.items()}
    out, failed = {}, []
    for k, f in futures.items():
        try:
            out[k] = f.result()
        except Exception:       # noqa: BLE001
            failed.append(k)
    if failed:
        # ห้ามนับโรคที่ query ล้มเป็นชุดว่างแล้วแสดงตัวเลขต่ำเกินจริงโดยไม่เตือน — ให้ส่วน "ผู้ป่วยไม่ซ้ำ" แสดงข้อผิดพลาดแทน (และไม่แคช)
        raise RuntimeError("ชุดผู้ป่วยล้ม: " + ",".join(failed))
    return out


def _trend(p) -> dict:
    fys = [p.fy - 2, p.fy - 1, p.fy]
    return {"labels": [f"ปีงบ {fy}" for fy in fys],
            "series": [{"name": "ผู้ป่วย HT ในทะเบียน", "color": COLORS["ht"],
                        "values": [common.registry_count(config.CLINIC_HT, periods.make(fy)) for fy in fys]},
                       {"name": "ผู้ป่วย DM ในทะเบียน", "color": COLORS["dm"],
                        "values": [common.registry_count(config.CLINIC_DM, periods.make(fy)) for fy in fys]}]}


def _ok(data):
    return "page_error" not in data and isinstance(data.get("kpis"), list) and len(data["kpis"]) >= 2


def _card(key, data):
    tone, icon = STYLE[key]
    title = pages.title_of(key)
    if not _ok(data):
        return {"label": title, "value": "—", "tone": tone, "icon": icon, "sub": "ดึงข้อมูลไม่ได้"}
    k0, k1 = data["kpis"][0], data["kpis"][1]
    return {"label": title, "value": k0["value"], "unit": k0.get("unit"), "tone": tone, "icon": icon,
            "sub": f"{k1['label']} {k1['value']}{(' ' + k1['unit']) if k1.get('unit') else ''}"}


def _row(key, data):
    title = pages.title_of(key)
    if not _ok(data):
        return [title, "—", "—", "—"]
    k0, k1 = data["kpis"][0], data["kpis"][1]
    return [title, k0["value"], k1["label"], f"{k1['value']} · {k1['sub']}" if k1.get("sub") else k1["value"]]


def _notes(datas):
    out = []
    for key, data in datas.items():
        warn = next((n for n in (data.get("notes") or []) if n.get("tone") == "warn"), None) if isinstance(data.get("notes"), list) else None
        if warn:
            out.append({"tone": "warn", "text": f"{pages.title_of(key)}: {warn['text']}"})
    return out


def _unique_tiles(p):
    d = distinct_patients(_patient_sets(p))
    return {"type": "tiles", "title": "ผู้ป่วย NCD ไม่ซ้ำ (นับ HN ครั้งเดียว)", "items": [
        {"label": "ผู้ป่วย NCD ไม่ซ้ำ", "value": ui.fmt_int(d["total_unique"]), "sub": "ราย (ทุกโรครวมกัน)", "tone": "blue"},
        {"label": "อยู่ทั้ง HT และ DM", "value": ui.fmt_int(d["overlap_ht_dm"]), "sub": "ราย", "tone": "purple"},
        {"label": "มีมากกว่า 1 โรค", "value": ui.fmt_int(d["multi_disease"]), "sub": "ราย (ควรดูแลแบบองค์รวม)", "tone": "orange"}]}


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        from queries import hdc_views
        return hdc_views.build_overview(p)
    with ThreadPoolExecutor(max_workers=len(KEYS)) as ex:
        results = list(ex.map(lambda k: _in_thread(pages.get, k, p, "hosxp"), KEYS))
    datas = dict(zip(KEYS, results))
    return {"incomplete": any(pages.has_error(d) for d in datas.values()),
            "title": TITLE, "subtitle": "สรุปผู้ป่วยโรคไม่ติดต่อเรื้อรัง 6 กลุ่ม (ข้อมูล รพ. จาก HOSxP)",
            "monthly_title": "แนวโน้มจำนวนผู้ป่วยในทะเบียน HT/DM 3 ปีงบ",
            "kpis": [_card(k, datas[k]) for k in KEYS],
            "monthly": sections.safe("แนวโน้ม 3 ปีงบ", _trend, p),
            "table": {"title": "ตัวชี้วัดหลักของแต่ละโรค", "columns": ["โรค/คลินิก", "ผู้ป่วย", "ตัวชี้วัดหลัก", "ผลลัพธ์"],
                      "rows": [_row(k, datas[k]) for k in KEYS]},
            "extra": [sections.safe("ผู้ป่วยไม่ซ้ำ", _unique_tiles, p)],
            "notes": _notes(datas)}

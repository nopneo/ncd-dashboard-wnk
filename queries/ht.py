"""หน้า HT — คลินิกโรคความดันโลหิตสูง

นับ "ควบคุมได้" รายคนจากความดันล่าสุดที่ valid ของปีงบ ตัวหาร = ผู้ป่วยในทะเบียนที่ยังติดตาม
(คนที่ไม่มีค่าความดันนับในตัวหาร และแสดงร้อยละที่ได้รับการวัดคู่กัน)
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Tuple

import classify
import config
import db
import periods
import sections
import ui
from queries import clinic_lists, common

TITLE = "ความดันโลหิตสูง (HT)"
COLORS = {"controlled": "#16a34a", "partial": "#f59e0b", "uncontrolled": "#ef4444", "none": "#94a3b8"}


def bp_series_by_hn(clinic: str, p) -> Dict[str, List[Tuple]]:
    """HN → [(วันที่, sbp, dbp)] เรียงตามวันที่ เฉพาะค่าที่ valid_bp"""
    rows = db.fetch("select s.hn, s.bps sbp, s.bpd dbp, s.vstdate d from opdscreen s "
                    "where s.vstdate between %(start)s and %(end)s and s.bps is not null "
                    f"and s.hn in ({common.MEMBER_SUBQUERY}) order by s.hn, s.vstdate, s.vn",
                    common._mp(clinic, p.start, p.end))
    out: Dict[str, List[Tuple]] = {}
    for r in rows:
        if classify.valid_bp(r["sbp"], r["dbp"]):
            out.setdefault(r["hn"], []).append((r["d"], r["sbp"], r["dbp"]))
    for s in out.values():
        s.sort(key=lambda t: t[0])
    return out


def latest_rows(series: Dict[str, List[Tuple]]) -> List[dict]:
    return [{"hn": hn, "sbp": s[-1][1], "dbp": s[-1][2], "date": s[-1][0]} for hn, s in series.items()]


def summarize(latest: List[dict], registry: int) -> dict:
    """นับกลุ่มความดันล่าสุด · ตัวหารของร้อยละ = registry (ไม่ใช่เฉพาะคนที่มีค่า)"""
    groups = {"controlled": 0, "partial": 0, "uncontrolled": 0}
    for r in latest:
        g = classify.bp_group(r["sbp"], r["dbp"])
        if g:
            groups[g] += 1
    tested = sum(groups.values())
    return {**groups, "no_value": max(registry - tested, 0), "registry": registry, "tested": tested,
            "controlled_pct": ui.pct(groups["controlled"], registry), "tested_pct": ui.pct(tested, registry)}


def uncontrolled_streak(series: List[Tuple], n: int = 2) -> bool:
    """n ครั้งล่าสุดไม่ผ่านเกณฑ์ <140/90 ทั้งหมด (therapeutic inertia)"""
    if len(series) < n:
        return False
    return all(classify.bp_group(s, d) != "controlled" for _d, s, d in series[-n:])


def _core(clinic, p, prev):
    registry = common.registry_count(clinic, p)
    series = bp_series_by_hn(clinic, p)
    return {
        "registry": registry, "prev_registry": common.registry_count(clinic, prev),
        "visits": common.visit_count(clinic, p), "visited": common.visited_patients(clinic, p),
        "series": series, "summary": summarize(latest_rows(series), registry),
    }


def _monthly(clinic, p):
    return {"labels": [label for _d, label in periods.months(p)],
            "series": [{"name": "ครั้งที่มารับบริการ", "values": common.monthly_visits(clinic, p), "color": "#1d6ff2"}]}


def _risk_tiles(clinic, p, series):
    crisis = sum(1 for s in series.values() if any(sb >= 180 or db_ >= 110 for _d, sb, db_ in s))
    streak = sum(1 for s in series.values() if uncontrolled_streak(s))
    gaps = common.followup_gaps(clinic, p, min(p.end, common.today()))
    L = clinic_lists.link
    return {"type": "tiles", "title": "ความเสี่ยงและการติดตาม", "items": [
        {"label": "ควบคุมไม่ได้ติดต่อกัน ≥2 ครั้ง", "value": ui.fmt_int(streak), "sub": "ราย (ทบทวนการปรับยา)", "tone": "orange",
         "list": L("ht", "streak", streak)},
        {"label": "ความดันวิกฤต ≥180/110", "value": ui.fmt_int(crisis), "sub": "ราย (มีค่าอย่างน้อย 1 ครั้งในช่วง)", "tone": "red",
         "list": L("ht", "crisis", crisis)},
        {"label": "ขาดนัด >3 เดือน", "value": ui.fmt_int(gaps["lost_3m"]), "sub": "ราย", "tone": "purple", "list": L("ht", "lost_3m", gaps["lost_3m"])},
        {"label": "นัดเลยกำหนด", "value": ui.fmt_int(gaps["overdue"]), "sub": "ราย", "tone": "blue", "list": L("ht", "overdue", gaps["overdue"])}]}


def _group_table(clinic, p, series, key):
    status = {hn: classify.bp_group(s[-1][1], s[-1][2]) for hn, s in series.items()}
    return common.group_table(clinic, p, status, key, "ควบคุมความดันได้")


def _recent(clinic, p):
    row = db.fetch_one(
        "select o.vstdate d, count(*) visits, sum(s.bps is not null) bp, sum(s.bps >= 160 or s.bpd >= 100) high "
        "from ovst o left join opdscreen s on s.vn = o.vn "
        "where o.vstdate between %(since)s and %(asof)s "
        f"and o.hn in ({common.MEMBER_SUBQUERY}) group by o.vstdate order by o.vstdate desc limit 1",
        common._mp(clinic, p.start, p.end, since=min(p.end, common.today()) - timedelta(days=30),
                   asof=min(p.end, common.today())))
    if not row:
        return {"title": "รายการล่าสุด", "columns": ["วันที่", "รายการ", "จำนวน"], "rows": []}
    d = ui.thai_date(row["d"])
    return {"title": "รายการล่าสุด (วันที่มีผู้รับบริการล่าสุด)", "columns": ["วันที่", "รายการ", "จำนวน (ครั้ง)"],
            "rows": [[d, "ผู้รับบริการ HT Clinic", ui.fmt_int(db.num(row["visits"]))],
                     [d, "วัดความดันโลหิต", ui.fmt_int(db.num(row["bp"]))],
                     [d, "ความดัน ≥160/100", ui.fmt_int(db.num(row["high"]))]]}


def _chip(value, target):
    if value is None:
        return {"text": "ไม่มีข้อมูล", "chip": "warn"}
    return {"text": "ผ่าน", "chip": "ok"} if value >= target else {"text": "ต่ำกว่าเป้า", "chip": "bad"}


def _kpis(core):
    s, reg = core["summary"], core["registry"]
    visited_pct = ui.pct(core["visited"], reg)
    return [
        {"label": "ผู้ป่วยในทะเบียน", "value": ui.fmt_int(reg), "unit": "ราย", "tone": "blue", "icon": "users",
         "sub": f"มารับบริการ {core['visits']:,} ครั้ง", "delta": ui.delta(reg, core["prev_registry"])},
        {"label": "ควบคุมได้ (<140/90)", "value": ui.fmt_int(s["controlled"]), "unit": "ราย", "tone": "green",
         "icon": "circle-check", "sub": f"{ui.fmt_pct(s['controlled_pct'])} ของทะเบียน"},
        {"label": "ควบคุมไม่ได้ (≥160/100)", "value": ui.fmt_int(s["uncontrolled"]), "unit": "ราย", "tone": "red",
         "icon": "triangle-alert", "sub": f"{ui.fmt_pct(ui.pct(s['uncontrolled'], reg))} ของทะเบียน"},
        {"label": "ติดตามต่อเนื่อง", "value": ui.fmt_int(core["visited"]), "unit": "ราย", "tone": "purple",
         "icon": "calendar-check", "sub": f"{ui.fmt_pct(visited_pct)} ของทะเบียนมารับบริการ"},
    ]


def _donut(core):
    s = core["summary"]
    return {"title": "สถานะการควบคุมความดันโลหิต (ค่าล่าสุดรายคน)", "center": ui.fmt_pct(s["controlled_pct"]),
            "total_label": f"ผู้ป่วยในทะเบียน {core['registry']:,} ราย",
            "parts": [("ควบคุมได้ (<140/90)", s["controlled"], COLORS["controlled"]),
                      ("บางส่วน (140–159 / 90–99)", s["partial"], COLORS["partial"]),
                      ("ควบคุมไม่ได้ (≥160/100)", s["uncontrolled"], COLORS["uncontrolled"]),
                      ("ไม่มีค่าความดัน", s["no_value"], COLORS["none"])],
            "lists": [clinic_lists.link("ht", g, n) for g, n in (("controlled", s["controlled"]), ("partial", s["partial"]),
                                                                 ("uncontrolled", s["uncontrolled"]), ("no_bp", s["no_value"]))]}


def _table(core):
    s = core["summary"]
    follow = ui.pct(core["visited"], core["registry"])
    L = clinic_lists.link
    return {"title": f"ตัวชี้วัดสำคัญ HT Clinic · {core['label']}", "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลการดำเนินงาน", "สถานะ"],
            "rows": [
                [{"text": "ร้อยละผู้ป่วยควบคุมความดันได้ (<140/90 ค่าล่าสุดรายคน)",
                  "list": L("ht", "not_controlled", s["partial"] + s["uncontrolled"])},
                 f"≥ {config.TARGET_HT_CONTROL:.0f}%", ui.fmt_pct(s["controlled_pct"]), _chip(s["controlled_pct"], config.TARGET_HT_CONTROL)],
                [{"text": "ร้อยละผู้ป่วยที่ได้รับการวัดความดันในช่วง", "list": L("ht", "no_bp", s["no_value"])},
                 "—", ui.fmt_pct(s["tested_pct"]), ""],
                [{"text": "ร้อยละผู้ป่วยมารับบริการต่อเนื่อง", "list": L("ht", "not_visited", core["registry"] - core["visited"])},
                 f"≥ {config.TARGET_FOLLOWUP:.0f}%", ui.fmt_pct(follow), _chip(follow, config.TARGET_FOLLOWUP)]]}


def _notes(core):
    s, out = core["summary"], []
    if s["controlled_pct"] is not None and s["controlled_pct"] < config.TARGET_HT_CONTROL:
        out.append({"tone": "warn", "text": f"ควบคุมความดันได้ {ui.fmt_pct(s['controlled_pct'])} ต่ำกว่าเป้า {config.TARGET_HT_CONTROL:.0f}% "
                                            f"(ตัวหารรวมผู้ที่ไม่มีค่าความดัน {s['no_value']:,} ราย)"})
    if s["registry"] and s["no_value"]:
        out.append({"tone": "info", "text": f"ผู้ป่วย {s['no_value']:,} ราย ({ui.fmt_pct(ui.pct(s['no_value'], s['registry']))}) ไม่มีค่าความดันในช่วงนี้ — "
                                            "กลุ่มนี้ควรได้รับการติดตามและวัดความดัน"})
    if s["uncontrolled"]:
        out.append({"tone": "warn", "text": f"ผู้ป่วยควบคุมไม่ได้ (≥160/100) {s['uncontrolled']:,} ราย ควรทบทวนการใช้ยาและการปฏิบัติตัว"})
    return out


def build(p, src: str = "hosxp", opts=None) -> dict:
    if src == "hdc":
        from queries import hdc_views
        return hdc_views.build_ht(p)
    clinic, prev = config.CLINIC_HT, periods.previous(p)
    data = {"title": TITLE, "subtitle": "ติดตามการควบคุมความดันโลหิตของผู้ป่วยในทะเบียนคลินิก HT (ข้อมูล รพ. จาก HOSxP)",
            "monthly_title": "แนวโน้มจำนวนครั้งที่มารับบริการรายเดือน"}
    core = sections.safe("ความดันโลหิต", _core, clinic, p, prev)
    if "error" in core:
        data.update(kpis=core, donut=core, table=core)
    else:
        core["label"] = p.label
        data.update(kpis=_kpis(core), donut=_donut(core), table=_table(core), notes=_notes(core))
    data["monthly"] = sections.safe("แนวโน้มรายเดือน", _monthly, clinic, p)
    series = core.get("series") if "error" not in core else None
    if series is None:
        data["extra"] = [{"error": "ความเสี่ยงและการติดตาม: ดึงข้อมูลไม่ได้"}]
    else:
        data["extra"] = [sections.safe("ความเสี่ยงและการติดตาม", _risk_tiles, clinic, p, series),
                         sections.safe("แยกกลุ่มอายุ", _group_table, clinic, p, series, "age"),
                         sections.safe("แยกเพศ", _group_table, clinic, p, series, "sex")]
    data["recent"] = sections.safe("รายการล่าสุด", _recent, clinic, p)
    return data

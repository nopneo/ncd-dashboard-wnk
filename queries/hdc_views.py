"""มุมมอง HDC (ระดับอำเภอ) ของแต่ละหน้า — รูปแบบ dict เดียวกับ build() ของฝั่ง HOSxP

ความหมายคอลัมน์ที่ใช้ดู docs/hdc_columns.md · คอลัมน์ที่ยืนยันความหมายไม่ได้จะไม่แสดง
ตัวเลข HDC เป็นนิยามของ HDC (ทั้งอำเภอ) ต่างจาก HOSxP — ไม่นำมาหักล้างกันตรง ๆ
"""
from __future__ import annotations

from datetime import datetime
from typing import List

import config
import hdc
import periods
import ui
from queries import common

GREEN, RED, AMBER, GREY = "#16a34a", "#ef4444", "#f59e0b", "#94a3b8"
NA = "ดึงข้อมูล HDC ไม่ได้"


def total(res, prefix: str) -> float:
    """ผลรวมคอลัมน์ที่ขึ้นต้นด้วย prefix (เช่น result_group1..5)"""
    return sum(v for k, v in res.totals.items() if k.startswith(prefix))


def month_values(res) -> List[float]:
    """result10, result11, result12, result01 … result09 (ต.ค.→ก.ย.)"""
    order = ["10", "11", "12", "01", "02", "03", "04", "05", "06", "07", "08", "09"]
    return [res.totals.get("result" + m, 0.0) for m in order]


def monthly_incidence(res, p, name: str, color: str = "#1d6ff2") -> dict:
    if res.error:
        return {"error": res.error}
    fy = res.fallback_fy or p.fy        # ไม่มีข้อมูลปีงบที่เลือก → ป้ายเดือนตามปีงบของข้อมูลที่แสดงจริง
    return {"labels": [label for _d, label in periods.months(periods.make(fy))],
            "series": [{"name": name, "values": [int(v) for v in month_values(res)], "color": color}]}


def monthly_multi(items, p) -> dict:
    """กราฟรายเดือนหลายชุด [(ผล, ชื่อ, สี)] — ชุดที่ดึงไม่ได้ข้ามไป · ดึงไม่ได้ทุกชุด → error"""
    ok = [(r, n, c) for r, n, c in items if not r.error]
    if not ok:
        return {"error": items[0][0].error}
    fy = ok[0][0].fallback_fy or p.fy
    return {"labels": [label for _d, label in periods.months(periods.make(fy))],
            "series": [{"name": n, "values": [int(v) for v in month_values(r)], "color": c} for r, n, c in ok]}


#: ผลคัดกรองความเสี่ยงของ HDC (s_ht_screen_risk / s_dm_screen_risk) — ร้อยละของผู้ได้รับการคัดกรอง (result)
RISK_GROUPS = [("normal", "ปกติ"), ("risk", "กลุ่มเสี่ยง"), ("high_risk", "กลุ่มเสี่ยงสูง / สงสัยป่วย"), ("ill", "ป่วย (พบจากการคัดกรอง)")]


def screen_risk_table(res, title: str) -> dict:
    if res.error:
        return {"error": res.error, "title": title}
    screened = res.totals.get("result", 0.0)
    return {"title": f"{title} · คัดกรอง {ui.fmt_int(screened)} คน", "columns": ["ผลการคัดกรอง", "จำนวน (คน)", "ร้อยละของผู้ได้รับการคัดกรอง"],
            "rows": [[name, ui.fmt_int(res.totals.get(k, 0.0)), ui.fmt_pct(ui.pct(res.totals.get(k, 0.0), screened))]
                     for k, name in RISK_GROUPS]}


def _rate_res(label, sub, res, num, den, target=None):
    """แถวร้อยละจากผล HDC หนึ่งตาราง — ดึงไม่ได้ = แสดงข้อความแทนตัวเลข (แถวอื่นไม่เสีย)"""
    if res.error:
        return [{"text": label, "sub": sub}, {"text": "—", "cls": "nw"}, {"text": NA}, {"text": "—", "cls": "nw"}, ""]
    return _rate_row(label, sub, res.totals.get(num, 0.0), res.totals.get(den, 0.0), target)


def kpi(label, value, sub, tone, icon, unit="ราย"):
    return {"label": label, "value": value, "unit": unit, "sub": sub, "tone": tone, "icon": icon}


def unit_table(res, title: str, num_key: str, den_key: str, columns: List[str]) -> dict:
    """ตารางเทียบรายหน่วยบริการ (รพ.สต.) เรียงตามอัตรา — หน่วยที่ตัวหารเป็นศูนย์ไม่แสดง"""
    if res.error:
        return {"error": res.error}
    rows = [(code, u.get(den_key, 0.0), u.get(num_key, 0.0)) for code, u in res.by_unit.items()
            if code and u.get(den_key, 0.0) > 0]
    try:
        names = common.hospital_names([c for c, _d, _n in rows])
    except Exception:       # noqa: BLE001 — ไม่มีชื่อก็แสดงรหัสแทน
        names = {c: c for c, _d, _n in rows}
    rows.sort(key=lambda r: (-(r[2] / r[1]), r[0]))
    return {"title": title, "columns": columns,
            "rows": [[names.get(c, c), ui.fmt_int(den), ui.fmt_int(num), ui.fmt_pct(ui.pct(num, den))]
                     for c, den, num in rows]}


def notes(results, p) -> list:
    out = []
    if p.scope != "year":
        out.append({"tone": "info", "text": "ข้อมูล HDC แสดงเป็นทั้งปีงบประมาณ — ตัวกรองช่วงข้อมูลไม่มีผลกับฝั่ง HDC"})
    fb = sorted({r.fallback_fy for r in results if r.fallback_fy})
    if fb:
        d = datetime.fromisoformat(min(r.fetched_at for r in results if r.fallback_fy and r.fetched_at)).date()
        out.append({"tone": "warn", "text": f"HDC ยังไม่มีข้อมูลปีงบประมาณ {p.fy} — แสดงข้อมูลล่าสุดที่เคยดึงไว้ของปีงบประมาณ {fb[-1]} "
                                            f"(ดึงเมื่อ {ui.thai_date(d)}) ไม่ใช่ตัวเลขของปีงบที่เลือก · ระบบตรวจ HDC ใหม่วันละครั้ง"})
    stale = [r.fetched_at for r in results if r.stale and not r.fallback_fy and r.fetched_at]
    if stale:
        d = datetime.fromisoformat(min(stale)).date()
        out.append({"tone": "warn", "text": f"เชื่อมต่อ HDC ไม่ได้ในขณะนี้ — บางส่วนเป็นข้อมูลที่ดึงไว้เมื่อ {ui.thai_date(d)}"})
    out.append({"tone": "info", "text": "ตัวเลข HDC เป็นนิยามของ HDC (ทั้งอำเภอ ตามทะเบียนผู้ป่วยในเขต) ต่างจากฝั่ง HOSxP ที่นับเฉพาะผู้มารับบริการ รพ. "
                                        "จึงไม่ควรนำสองฝั่งมาหักล้างกันตรง ๆ"})
    return out


def as_of(results) -> str:
    dates = [r.fetched_at for r in results if r.fetched_at]
    return ui.thai_date(datetime.fromisoformat(min(dates)).date()) if dates else ""


def build_ht(p) -> dict:
    ctl = hdc.get("s_ht_control", p.fy)
    scr = hdc.get("s_ht_screen", p.fy)
    inc = hdc.get("s_ht_incidence", p.fy)
    pop = hdc.get("s_ht_pop_age", p.fy)
    risk = hdc.get("s_ht_screen_risk", p.fy)
    results = [ctl, scr, inc, pop, risk]

    def ok(r, fn):
        return NA if r.error else fn(r)

    bp, res_, target = (ctl.totals.get(k, 0.0) for k in ("bp", "result", "target"))
    ctl_pct = ui.pct(res_, bp)
    kpis = [
        kpi("ผู้ป่วย HT ในเขต (HDC)", ok(pop, lambda r: ui.fmt_int(total(r, "result_group"))), "ทะเบียนผู้ป่วยในเขตรับผิดชอบ", "blue", "users"),
        kpi("วัดความดัน ≥2 ครั้ง", ok(ctl, lambda r: ui.fmt_int(bp)), "" if ctl.error else f"{ui.fmt_pct(ui.pct(bp, target))} ของผู้ป่วยในเขต", "purple", "calendar-check"),
        kpi("ควบคุมได้", ok(ctl, lambda r: ui.fmt_int(res_)), "" if ctl.error else f"{ui.fmt_pct(ctl_pct)} ของที่วัดความดัน", "green", "circle-check"),
        kpi("ผู้ป่วยรายใหม่ปีงบ", ok(inc, lambda r: ui.fmt_int(r.totals.get("result"))), "นับตามปีงบประมาณ", "orange", "trending-up"),
        kpi("คัดกรอง HT (≥35 ปี)", ok(scr, lambda r: ui.fmt_int(r.totals.get("result"))),
            "" if scr.error else f"{ui.fmt_pct(ui.pct(scr.totals.get('result'), scr.totals.get('target')))} ของเป้าหมาย", "teal", "search", unit="คน"),
    ]
    donut = ({"error": ctl.error} if ctl.error else
             {"title": "การควบคุมความดันโลหิต (HDC · ผู้ที่วัดความดัน ≥2 ครั้ง)", "center": ui.fmt_pct(ctl_pct),
              "total_label": f"ผู้ป่วยที่วัดความดัน ≥2 ครั้ง {int(bp):,} ราย",
              "parts": [("ควบคุมได้", int(res_), GREEN), ("ควบคุมไม่ได้", int(max(bp - res_, 0)), RED)]})
    return {"title": "ความดันโลหิตสูง (HT) · HDC", "subtitle": "ข้อมูลระดับอำเภอจาก HDC (MoPH Open Data)", "as_of": as_of(results),
            "monthly_title": "ผู้ป่วย HT รายใหม่รายเดือน (HDC)",
            "kpis": kpis, "monthly": monthly_incidence(inc, p, "ผู้ป่วยรายใหม่"), "donut": donut,
            "table": unit_table(ctl, "เปรียบเทียบอัตราควบคุมความดันได้รายหน่วยบริการ (HDC)", "result", "bp",
                                ["หน่วยบริการ", "วัดความดัน ≥2 ครั้ง", "ควบคุมได้", "ร้อยละ"]),
            "extra": [screen_risk_table(risk, "ผลการคัดกรองความดันโลหิต (HDC · ประชาชน ≥35 ปี)")],
            "notes": notes(results, p)}


def _rate_row(label, sub, num, den, target):
    pct = ui.pct(num, den)
    return [{"text": label, "sub": sub}, {"text": f"≥ {target:g}%" if target is not None else "—", "cls": "nw"},
            {"text": f"{ui.fmt_int(num)} / {ui.fmt_int(den)}", "cls": "nw"}, {"text": ui.fmt_pct(pct), "cls": "nw"},
            ui.target_chip(pct, target)]


def remission_tables(res) -> list:
    """DM remission ตัวชี้วัด 10.2 จาก s_dm_remission_coverage: b=B2 เข้าเกณฑ์ · b1=B1 สมัครใจเข้าร่วม clinic (1I20)
    b3/b4 = เข้าร่วม ไม่มี/มีภาวะแทรกซ้อน · a=A1 เข้าสู่ระยะสงบ · a2/a3 แยกตามภาวะแทรกซ้อน"""
    title = "DM remission · ตัวชี้วัด 10.2 (HDC)"
    utitle = "DM remission รายหน่วยบริการ (HDC)"
    if res.error:
        return [{"error": res.error, "title": title}]
    t = res.totals
    g = {k: t.get(k, 0.0) for k in ("b", "b1", "b3", "b4", "a", "a2", "a3")}
    rows = [_rate_row("ร้อยละผู้ป่วย DM ชนิดที่ 2 ที่เข้าสู่ระยะสงบ ต่อผู้เข้าร่วม NCDs remission clinic (A1/B1)",
                      "HbA1c <6.5% 2 ครั้ง ห่าง 90–180 วัน โดยไม่ใช้ยาลดน้ำตาล", g["a"], g["b1"], config.TARGET_DM_REMISSION),
            _rate_row("ร้อยละที่เข้าสู่ระยะสงบ ต่อผู้ป่วยที่เข้าเกณฑ์ทั้งหมด (A1/B2)", "เป้า ≥1% เฉพาะปีงบ 2568", g["a"], g["b"], None),
            _rate_row("ร้อยละผู้เข้าเกณฑ์ที่สมัครใจเข้าร่วม NCDs remission clinic (B1/B2)", "บันทึกรหัสกิจกรรม 1I20", g["b1"], g["b"], None),
            _rate_row("— กลุ่มไม่มีภาวะแทรกซ้อน (A2/B3)", "", g["a2"], g["b3"], None),
            _rate_row("— กลุ่มมีภาวะแทรกซ้อน (A3/B4)", "", g["a3"], g["b4"], None)]
    units = [(c, u) for c, u in res.by_unit.items() if c and u.get("b", 0.0) > 0]
    try:
        names = common.hospital_names([c for c, _u in units])
    except Exception:       # noqa: BLE001
        names = {c: c for c, _u in units}
    units.sort(key=lambda x: (-x[1].get("b1", 0.0), -x[1].get("b", 0.0), x[0]))
    return [{"title": title, "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลงาน (ราย)", "ร้อยละ", "สถานะ"], "rows": rows, "wide": True},
            {"title": utitle, "columns": ["หน่วยบริการ", "เข้าเกณฑ์ (B2)", "เข้าร่วม clinic (B1)", "ระยะสงบ (A1)", "ร้อยละ A1/B1"],
             "rows": [[names.get(c, c), ui.fmt_int(u.get("b")), ui.fmt_int(u.get("b1")), ui.fmt_int(u.get("a")),
                       ui.fmt_pct(ui.pct(u.get("a"), u.get("b1")))] for c, u in units]}]


def build_dm(p) -> dict:
    """DM ฝั่ง HDC — ไม่แสดงอัตราควบคุมน้ำตาล (คอลัมน์ HbA1c ของ HDC ไม่สอดคล้องกัน ดู docs/hdc_columns.md)"""
    scr = hdc.get("s_dm_screen", p.fy)
    inc = hdc.get("s_dm_incidence", p.fy)
    pop = hdc.get("s_dm_pop_age", p.fy)
    ret = hdc.get("s_dm_retina_kpi", p.fy)
    rem = hdc.get("s_dm_remission_coverage", p.fy)
    foot = hdc.get("s_dm_foot", p.fy)
    risk = hdc.get("s_dm_screen_risk", p.fy)
    results = [scr, inc, pop, ret, rem, foot, risk]
    comp = {"title": "การตรวจภาวะแทรกซ้อน DM (HDC)", "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลงาน (ราย)", "ร้อยละ", "สถานะ"], "wide": True,
            "rows": [_rate_res("ร้อยละผู้ป่วย DM ได้รับการตรวจจอประสาทตา", "ตาราง s_dm_retina_kpi · ค่าน้อย ระวังการตีความ", ret, "result", "target"),
                     _rate_res("ร้อยละผู้ป่วย DM ได้รับการตรวจเท้า", "ตาราง s_dm_foot", foot, "result", "target"),
                     _rate_res("— ในผู้ที่ตรวจเท้า พบความผิดปกติ", "ยิ่งพบเร็วยิ่งป้องกันแผล/ตัดขาได้", foot, "abnormal1", "result")]}

    def ok(r, fn):
        return NA if r.error else fn(r)

    sc_pct = ui.pct(scr.totals.get("result"), scr.totals.get("target"))
    rt_pct = ui.pct(ret.totals.get("result"), ret.totals.get("target"))
    kpis = [
        kpi("ผู้ป่วย DM ในเขต (HDC)", ok(pop, lambda r: ui.fmt_int(total(r, "result_group"))), "ทะเบียนผู้ป่วยในเขตรับผิดชอบ", "blue", "users"),
        kpi("ผู้ป่วยรายใหม่ปีงบ", ok(inc, lambda r: ui.fmt_int(r.totals.get("result"))), "นับตามปีงบประมาณ", "orange", "trending-up"),
        kpi("คัดกรอง DM (≥35 ปี)", ok(scr, lambda r: ui.fmt_int(r.totals.get("result"))),
            "" if scr.error else f"{ui.fmt_pct(sc_pct)} ของเป้าหมาย", "teal", "search", unit="คน"),
        kpi("ตรวจจอประสาทตา", ok(ret, lambda r: ui.fmt_int(r.totals.get("result"))),
            "" if ret.error else f"{ui.fmt_pct(rt_pct)} ของเป้าหมาย (ค่าน้อย ระวังการตีความ)", "purple", "target"),
        kpi("DM remission (HDC)", ok(rem, lambda r: ui.fmt_int(r.totals.get("a"))),
            "" if rem.error else f"{ui.fmt_pct(ui.pct(rem.totals.get('a'), rem.totals.get('b1')))} ของผู้เข้าร่วม clinic "
                                 f"{ui.fmt_int(rem.totals.get('b1'))} ราย", "green", "circle-check"),
    ]
    return {"title": "เบาหวาน (DM) · HDC", "subtitle": "ข้อมูลระดับอำเภอจาก HDC (MoPH Open Data)", "as_of": as_of(results),
            "monthly_title": "ผู้ป่วย DM รายใหม่รายเดือน (HDC)",
            "kpis": kpis, "monthly": monthly_incidence(inc, p, "ผู้ป่วยรายใหม่"),
            "table": unit_table(scr, "เปรียบเทียบอัตราการคัดกรอง DM รายหน่วยบริการ (HDC)", "result", "target",
                                ["หน่วยบริการ", "เป้าหมายคัดกรอง", "ได้รับการคัดกรอง", "ร้อยละ"]),
            "extra": remission_tables(rem) + [comp, screen_risk_table(risk, "ผลการคัดกรองเบาหวาน (HDC · ประชาชน ≥35 ปี)")],
            "notes": notes(results, p) + [{"tone": "info", "text": "ฝั่ง HDC ไม่แสดงอัตราควบคุมน้ำตาล เพราะคอลัมน์ HbA1c ของ HDC ไม่สอดคล้องกัน — ดูอัตราควบคุมจากฝั่ง HOSxP"}]}


#: ตัวชี้วัดคลินิกชะลอไตเสื่อมของ HDC (ระดับ รพ.): (ตาราง, ชื่อ, ชื่อเป้าใน config หรือ None)
#: ใช้เฉพาะคอลัมน์ target/result (ทั้งปี) — target1..4/result1..4 ยังยืนยันความหมายไม่ได้ จึงไม่แสดง
#: ตารางที่ความหมายเกณฑ์ไม่ชัด (Hb, HbA1c, ความดัน, Statin, UPCR) ไม่ใส่เป้า → ไม่ตัดสินผ่าน/ไม่ผ่าน
HDC_CKD_KPIS = [
    ("s_kpi_ckd_egfr", "ร้อยละผู้ป่วย CKD ที่มีอัตราการลดลงของ eGFR <5 ml/min/1.73m²/ปี", "TARGET_CKD_EGFR"),
    ("s_kpi_ckd_bp", "ร้อยละผู้ป่วย CKD ที่ควบคุมความดันโลหิตได้ตามเกณฑ์", None),
    ("s_kpi_ckd_acei_arb", "ร้อยละผู้ป่วย CKD ที่ได้รับยา ACEI/ARB", "TARGET_CKD_ACEI_ARB"),
    ("s_kpi_ckd_hb", "ร้อยละผู้ป่วย CKD ที่มีระดับ Hb ตามเกณฑ์", None),
    ("s_kpi_ckd_hba1c", "ร้อยละผู้ป่วย DM ที่มี CKD ควบคุม HbA1c ได้ตามเกณฑ์", None),
    ("s_kpi_ckd_statin", "ร้อยละผู้ป่วย CKD ที่ได้รับยา Statin", None),
    ("s_kpi_ckd_upcr", "ร้อยละผู้ป่วย CKD ที่ได้ตรวจ UPCR", None),
]


def ckd_kpi_table(p) -> tuple:
    """(ตาราง, ผลดึงทุกตาราง) — ตารางที่ดึงไม่ได้เสียเฉพาะแถวนั้น"""
    rows, results = [], []
    for table, label, target_name in HDC_CKD_KPIS:
        r = hdc.get(table, p.fy)
        results.append(r)
        target = getattr(config, target_name) if target_name else None
        name = {"text": label, "sub": f"ตาราง HDC {table}"}
        tgt = {"text": f"≥ {target:g}%" if target is not None else "—", "cls": "nw"}
        if r.error:
            rows.append([name, tgt, {"text": NA}, {"text": "—", "cls": "nw"}, ""])
            continue
        num, den = r.totals.get("result", 0.0), r.totals.get("target", 0.0)
        pct = ui.pct(num, den)
        rows.append([name, tgt, {"text": f"{ui.fmt_int(num)} / {ui.fmt_int(den)}", "cls": "nw"},
                     {"text": ui.fmt_pct(pct), "cls": "nw"}, ui.target_chip(pct, target)])
    return ({"title": "ตัวชี้วัดคลินิก CKD (HDC · ผู้ป่วยที่ รพ. ดูแล)",
             "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลงาน (ราย)", "ร้อยละ", "สถานะ"], "rows": rows, "wide": True}, results)


def unit_counts(res, title: str, key: str, columns: List[str]) -> dict:
    """จำนวนรายหน่วยบริการ เรียงมากไปน้อย (ไม่คิดร้อยละ — ตัวหารของตารางนี้ยังยืนยันความหมายไม่ได้)"""
    if res.error:
        return {"error": res.error, "title": title}
    rows = [(c, u.get(key, 0.0)) for c, u in res.by_unit.items() if c]
    try:
        names = common.hospital_names([c for c, _n in rows])
    except Exception:       # noqa: BLE001
        names = {c: c for c, _n in rows}
    rows.sort(key=lambda r: (-r[1], r[0]))
    return {"title": title, "columns": columns, "rows": [[names.get(c, c), ui.fmt_int(n)] for c, n in rows]}


def build_ckd(p) -> dict:
    stg = hdc.get("s_ckd_stage_typearea", p.fy)
    scr = hdc.get("s_kpi_ckd_screen", p.fy)
    inc = hdc.get("s_kpi_ckd_incidence", p.fy)
    kpi_table, kpi_results = ckd_kpi_table(p)
    results = [stg, scr, inc] + kpi_results

    def ok(r, fn):
        return NA if r.error else fn(r)

    g = {k: stg.totals.get(k, 0.0) for k in ("stage1", "stage2", "stage3", "stage4", "stage5")}
    tot = sum(g.values())
    sc_pct = ui.pct(scr.totals.get("result"), scr.totals.get("target"))
    kpis = [
        kpi("ผู้ป่วย CKD ในเขต (HDC)", ok(stg, lambda r: ui.fmt_int(tot)), "ระยะ 1–5 ตามพื้นที่ typearea", "blue", "bean"),
        kpi("CKD ระยะ 3–5", ok(stg, lambda r: ui.fmt_int(g["stage3"] + g["stage4"] + g["stage5"])),
            "" if stg.error else f"{ui.fmt_pct(ui.pct(g['stage3'] + g['stage4'] + g['stage5'], tot))} ของผู้ป่วย CKD", "teal", "activity"),
        kpi("CKD รายใหม่ปีงบ (HDC)", ok(inc, lambda r: ui.fmt_int(r.totals.get("result"))), "ทั้งอำเภอ นับตามปีงบประมาณ", "orange", "trending-up"),
        kpi("คัดกรอง CKD", ok(scr, lambda r: ui.fmt_int(r.totals.get("result"))),
            "" if scr.error else f"{ui.fmt_pct(sc_pct)} ของเป้าหมาย", "purple", "search", unit="คน"),
    ]
    donut = ({"error": stg.error} if stg.error else
             {"title": "สัดส่วนผู้ป่วย CKD ตามระยะ (HDC)", "center": ui.fmt_int(tot), "total_label": f"ผู้ป่วย CKD ในเขต {int(tot):,} ราย",
              "parts": [("ระยะ 1", int(g["stage1"]), BLUE_), ("ระยะ 2", int(g["stage2"]), "#0ea5e9"), ("ระยะ 3", int(g["stage3"]), GREEN),
                        ("ระยะ 4", int(g["stage4"]), AMBER), ("ระยะ 5", int(g["stage5"]), RED)]})
    return {"title": "ไตเรื้อรัง (CKD) · HDC", "subtitle": "ข้อมูลระดับอำเภอจาก HDC (MoPH Open Data)", "as_of": as_of(results),
            "kpis": kpis, "donut": donut,
            "table": unit_table(scr, "เปรียบเทียบอัตราการคัดกรอง CKD รายหน่วยบริการ (HDC)", "result", "target",
                                ["หน่วยบริการ", "เป้าหมายคัดกรอง", "ได้รับการคัดกรอง", "ร้อยละ"]),
            "extra": [kpi_table, unit_counts(inc, "ผู้ป่วย CKD รายใหม่รายหน่วยบริการ (HDC)", "result",
                                             ["หน่วยบริการ", "CKD รายใหม่ (ราย)"])],
            "notes": notes(results, p) + [{"tone": "info", "text":
                "ตัวชี้วัดคลินิก CKD ของ HDC นับผู้ป่วยที่ รพ. ดูแลตามนิยามของ HDC — ความหมายเกณฑ์ใช้ตามชื่อตาราง "
                "(ยังไม่ได้เทียบพจนานุกรมข้อมูลทางการ) จึงใส่เป้าเฉพาะข้อที่ชัดเจน · HDC ไม่มีรายชื่อผู้ป่วย "
                "ดูรายชื่อได้จากฝั่ง HOSxP เมื่อเปิดในเครือข่าย รพ."}]}


BLUE_ = "#2563eb"


def build_copd(p) -> dict:
    pop = hdc.get("s_copd_pop_age", p.fy)
    inc = hdc.get("s_copd_incidence", p.fy)
    ast = hdc.get("s_asthma_incidence", p.fy)
    results = [pop, inc, ast]

    def ok(r, fn):
        return NA if r.error else fn(r)

    kpis = [kpi("ผู้ป่วย COPD ในเขต (HDC)", ok(pop, lambda r: ui.fmt_int(total(r, "result_group"))), "ทะเบียนผู้ป่วยในเขตรับผิดชอบ", "blue", "wind"),
            kpi("ผู้ป่วย COPD รายใหม่ปีงบ", ok(inc, lambda r: ui.fmt_int(r.totals.get("result"))), "นับตามปีงบประมาณ", "orange", "trending-up"),
            kpi("หืดรายใหม่ปีงบ (HDC)", ok(ast, lambda r: ui.fmt_int(r.totals.get("result"))),
                "" if ast.error else f"{ui.fmt_per100k(ast.totals.get('result'), ast.totals.get('target'))} ต่อแสนประชากร", "teal", "trending-up")]
    return {"title": "COPD / หืด · HDC", "subtitle": "ข้อมูล COPD และหืดระดับอำเภอจาก HDC", "as_of": as_of(results),
            "monthly_title": "ผู้ป่วยรายใหม่รายเดือน (HDC)", "kpis": kpis,
            "monthly": monthly_multi([(inc, "COPD รายใหม่", "#1d6ff2"), (ast, "หืดรายใหม่", "#0ea5e9")], p), "notes": notes(results, p)}


def build_cvd(p) -> dict:
    pop = hdc.get("s_stroke_pop_age", p.fy)
    ihd = hdc.get("s_ihd_incidence", p.fy)
    stemi = hdc.get("s_stemi_death", p.fy)
    risk = hdc.get("s_kpi_cvd_risk", p.fy)
    results = [pop, ihd, stemi, risk]

    def ok(r, fn):
        return NA if r.error else fn(r)

    # s_stemi_death: targetq1..4 = ผู้ป่วย STEMI รายไตรมาส · resultq1..4 = เสียชีวิต (ระดับ รพ.)
    st_n, st_dead = total(stemi, "targetq"), total(stemi, "resultq")
    kpis = [kpi("ผู้ป่วย stroke ในเขต (HDC)", ok(pop, lambda r: ui.fmt_int(total(r, "result_group"))), "ทะเบียนผู้ป่วยในเขตรับผิดชอบ", "purple", "heart-pulse"),
            kpi("IHD รายใหม่ปีงบ (HDC)", ok(ihd, lambda r: ui.fmt_int(r.totals.get("result"))),
                "" if ihd.error else f"{ui.fmt_per100k(ihd.totals.get('result'), ihd.totals.get('target'))} ต่อแสนประชากร", "orange", "trending-up"),
            kpi("ผู้ป่วย STEMI (HDC)", ok(stemi, lambda r: ui.fmt_int(st_n)),
                "" if stemi.error else f"เสียชีวิต {ui.fmt_int(st_dead)} ราย", "red", "activity")]
    table = {"title": "ตัวชี้วัด CVD (HDC)", "columns": ["ตัวชี้วัด", "เป้าหมาย", "ผลงาน (ราย)", "ร้อยละ", "สถานะ"], "wide": True,
             "rows": [_rate_res("ตัวชี้วัด CVD Risk ของผู้ป่วย DM/HT", "ตาราง s_kpi_cvd_risk · ใช้ตามชื่อตาราง ยังไม่ยืนยันนิยามตัวตั้ง/ตัวหาร",
                                risk, "result", "target"),
                      (_rate_row("อัตราตายของผู้ป่วย STEMI", "ตาราง s_stemi_death · ยิ่งต่ำยิ่งดี", st_dead, st_n, None) if not stemi.error
                       else _rate_res("อัตราตายของผู้ป่วย STEMI", "ตาราง s_stemi_death", stemi, "x", "x"))]}
    return {"title": "หลอดเลือดสมอง/หัวใจ (CVD) · HDC", "subtitle": "ข้อมูลระดับอำเภอจาก HDC (MoPH Open Data)", "as_of": as_of(results),
            "kpis": kpis, "extra": [table, unit_table(risk, "ตัวชี้วัด CVD Risk รายหน่วยบริการ (HDC)", "result", "target",
                                                      ["หน่วยบริการ", "ตัวหาร", "ตัวตั้ง", "ร้อยละ"])],
            "notes": notes(results, p)}


def build_overview(p) -> dict:
    """ภาพรวมระดับอำเภอจาก HDC — ผู้ป่วยในเขตของแต่ละโรค + ควบคุม/คัดกรอง/รายใหม่ของ HT และ DM"""
    t = {name: hdc.get(name, p.fy) for name in (
        "s_ht_pop_age", "s_dm_pop_age", "s_ckd_stage_typearea", "s_copd_pop_age", "s_stroke_pop_age",
        "s_ht_control", "s_ht_screen", "s_dm_screen", "s_ht_incidence", "s_dm_incidence")}
    results = list(t.values())

    def ok(r, fn):
        return NA if r.error else fn(r)

    ctl = t["s_ht_control"]
    ctl_pct = ui.pct(ctl.totals.get("result"), ctl.totals.get("bp"))
    kpis = [
        kpi("HT ในเขต", ok(t["s_ht_pop_age"], lambda r: ui.fmt_int(total(r, "result_group"))), "ผู้ป่วยในเขตรับผิดชอบ", "blue", "activity"),
        kpi("DM ในเขต", ok(t["s_dm_pop_age"], lambda r: ui.fmt_int(total(r, "result_group"))), "ผู้ป่วยในเขตรับผิดชอบ", "orange", "droplet"),
        kpi("CKD ในเขต", ok(t["s_ckd_stage_typearea"], lambda r: ui.fmt_int(sum(r.totals.get(f"stage{i}", 0.0) for i in range(1, 6)))), "ระยะ 1–5", "teal", "bean"),
        kpi("COPD ในเขต", ok(t["s_copd_pop_age"], lambda r: ui.fmt_int(total(r, "result_group"))), "ผู้ป่วยในเขตรับผิดชอบ", "green", "wind"),
        kpi("Stroke ในเขต", ok(t["s_stroke_pop_age"], lambda r: ui.fmt_int(total(r, "result_group"))), "ผู้ป่วยในเขตรับผิดชอบ", "red", "heart-pulse"),
        kpi("HT ควบคุมได้", ok(ctl, lambda r: ui.fmt_pct(ctl_pct)), "ของผู้ที่วัดความดัน ≥2 ครั้ง", "purple", "circle-check", unit=""),
    ]

    def pct_row(name, r, num, den):
        return [name, ui.fmt_pct(ui.pct(r.totals.get(num), r.totals.get(den))) if not r.error else NA]

    table = {"title": "คัดกรองและผู้ป่วยรายใหม่ (HDC)", "columns": ["ตัวชี้วัด", "ผลลัพธ์"],
             "rows": [pct_row("คัดกรอง HT (≥35 ปี) ร้อยละของเป้าหมาย", t["s_ht_screen"], "result", "target"),
                      pct_row("คัดกรอง DM (≥35 ปี) ร้อยละของเป้าหมาย", t["s_dm_screen"], "result", "target"),
                      ["HT รายใหม่ปีงบ (ราย)", NA if t["s_ht_incidence"].error else ui.fmt_int(t["s_ht_incidence"].totals.get("result"))],
                      ["DM รายใหม่ปีงบ (ราย)", NA if t["s_dm_incidence"].error else ui.fmt_int(t["s_dm_incidence"].totals.get("result"))]]}
    return {"title": "ภาพรวม NCD · HDC", "subtitle": "ข้อมูลระดับอำเภอจาก HDC (MoPH Open Data)", "as_of": as_of(results),
            "kpis": kpis, "table": table, "notes": notes(results, p)}

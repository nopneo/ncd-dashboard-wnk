"""Data Audit — ตรวจว่ารหัสที่แอปสมมติไว้ตรงกับข้อมูลของโรงพยาบาลนี้หรือไม่ (หน้า /check และ setup_check.py)

รหัสใน HOSxP ของแต่ละ รพ. ไม่เหมือนกัน ถ้าไม่ตรงตัวเลขจะเพี้ยนโดยไม่มีข้อความเตือน
ทุกแถวแสดง "แอปใช้" เทียบ "พบในข้อมูล" และค่า env ที่ควรตั้ง · แสดงเฉพาะจำนวนนับ ไม่มีข้อมูลรายคน
status: ok = ตรงและมีข้อมูล · warn = ควรตรวจ (เช่น ไม่พบผู้ป่วย/ไม่ได้ตั้งค่า) · error = ไม่พบรหัสนี้ในฐาน
"""
from __future__ import annotations

import ipaddress
import os
from datetime import date, datetime
from typing import Dict, List

import config
import db
import hdc
import ui
from queries import common


#: IP ภายในมาตรฐาน — ระบุเอง ไม่ใช้ ip.is_private เพราะนับช่วงสาธารณะบางช่วงเป็น private ด้วย
#: (เช่น 203.0.113.0/24, 198.18.0.0/15, 100.64.0.0/10 บางรุ่นของ Python)
_LAN_NETS = [ipaddress.ip_network(n) for n in
             ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")]


def is_lan(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address((addr or "").strip())
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in n for n in _LAN_NETS)


def host_allowed(host: str) -> bool:
    """NCD_ALLOWED_HOSTS (คั่นด้วย ,) = ชื่อโดเมนที่เปิดหน้ารายชื่อ / /check ได้ เช่น lan.wnkhos.go.th
    กันเว็บอื่นใช้ DNS rebinding ให้เบราว์เซอร์ของเจ้าหน้าที่ดึงรายชื่อออกไป · ว่าง = ไม่ตรวจ"""
    allowed = {h.strip().lower() for h in os.getenv("NCD_ALLOWED_HOSTS", "").split(",") if h.strip()}
    if not allowed:
        return True
    h = (host or "").lower()
    h = h.split("]")[0] + "]" if h.startswith("[") else h.rsplit(":", 1)[0]
    return h in allowed


def request_allowed(remote_addr: str, headers) -> bool:
    """เปิด /check เฉพาะ LAN — ต้องเป็น LAN ทุกที่อยู่ที่เกี่ยวข้อง (หลัง reverse proxy REMOTE_ADDR คือ proxy จึงตรวจ X-Forwarded-For ด้วย)"""
    addrs = [remote_addr]
    for name in ("X-Forwarded-For", "CF-Connecting-IP", "X-Real-IP"):
        v = headers.get(name)
        if v:
            addrs += [a.strip() for a in v.split(",") if a.strip()]
    return all(is_lan(a) for a in addrs)


def data_audited() -> bool:
    return os.getenv("NCD_DATA_AUDITED") == "1"


def summary(rows: List[dict]) -> Dict[str, int]:
    return {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "warn", "error")}


def _row(item, uses, found, status, hint=""):
    return {"item": item, "app_uses": uses, "found": found, "status": status, "env_hint": hint}


def _status(names_found: bool, count: int) -> str:
    return "error" if not names_found else "ok" if count > 0 else "warn"


# --- ส่วนตรวจแต่ละกลุ่ม -------------------------------------------------------------

def _clinics(p):
    rows = []
    for label, env, code in (("HT", "CLINIC_HT", config.CLINIC_HT), ("DM", "CLINIC_DM", config.CLINIC_DM),
                             ("COPD", "CLINIC_COPD", config.CLINIC_COPD), ("หืด", "CLINIC_ASTHMA", config.CLINIC_ASTHMA)):
        name = db.fetch_one("select c.clinic, c.name from clinic c where c.clinic = %(c)s", {"c": code}).get("name")
        n = common.registry_count(code, p)
        rows.append(_row(f"คลินิก {label}", f"รหัส {code}", f"ชื่อ: {name or 'ไม่พบรหัสนี้ในตาราง clinic'} · ผู้ในทะเบียน {n:,} ราย",
                         _status(bool(name), n), "NCD_" + env))
    top = db.fetch("select m.clinic, c.name, count(*) n from clinicmember m left join clinic c on c.clinic = m.clinic "
                   "where coalesce(m.discharge, 'N') <> 'Y' group by m.clinic, c.name order by n desc limit 10", {})
    rows.append(_row("คลินิกที่มีสมาชิกมากที่สุดในฐานนี้", "—",
                     " · ".join(f"{r['clinic']} {r['name'] or '?'} ({int(r['n']):,})" for r in top) or "ไม่พบ", "ok",
                     "ใช้เทียบเมื่อรหัสคลินิกของ รพ. ไม่ตรง"))
    return rows


def _lab_row(label, env, codes, p, allow_zero=False):
    if not codes:
        return _row(f"lab {label}", "ไม่ได้ตั้งค่า", "ไม่ได้ตั้งค่า — หน้าจะแสดง \"ไม่มีข้อมูล\"", "warn", "NCD_" + env)
    ph, params = common._in("l", [str(c) for c in codes])
    names = db.fetch(f"select i.lab_items_code, i.lab_items_name from lab_items i where i.lab_items_code in ({ph})", params)
    params.update(start=p.start, end=p.end)
    n = common._n(db.fetch_one("select count(distinct h.hn) n from lab_head h join lab_order o on o.lab_order_number = h.lab_order_number "
                               f"where o.lab_items_code in ({ph}) and h.order_date between %(start)s and %(end)s", params))
    found = ", ".join(f"{r['lab_items_code']} {r['lab_items_name']}" for r in names) or "ไม่พบรหัสนี้ในตาราง lab_items"
    status, extra = _status(bool(names), n), ""
    if status == "ok":
        results = common.latest_lab_by_hn(list(codes), None, p, allow_zero)
        if results:
            ratio = round(100.0 * sum(1 for r in results if r["value"] is not None) / len(results))
            extra = f" · อ่านเป็นตัวเลขได้ {ratio}% ของผู้ที่มีผล"
            if ratio < 90:
                status, extra = "warn", extra + " — ตรวจรูปแบบผล lab (หน่วย/ข้อความ) ไม่เช่นนั้นตัวเลขจะต่ำกว่าจริง"
    return _row(f"lab {label}", "รหัส " + ",".join(str(c) for c in codes), f"{found} · มีผลในช่วง {n:,} ราย{extra}", status, "NCD_" + env)


def _labs(p):
    return [_lab_row("HbA1c", "LAB_HBA1C", [config.LAB_HBA1C], p), _lab_row("INR", "LAB_INR", [config.LAB_INR], p),
            _lab_row("eGFR", "LAB_EGFR", [config.LAB_EGFR], p), _lab_row("LDL", "LAB_LDL", config.LAB_LDL, p),
            _lab_row("ไมโครอัลบูมิน/UACR", "LAB_UACR", config.LAB_UACR, p, allow_zero=True),
            _lab_row("Hemoglobin (Hb)", "LAB_HB", config.LAB_HB, p), _lab_row("Hematocrit (Hct)", "LAB_HCT", config.LAB_HCT, p)]


def _item_row(label, env, table, key, codes, p):
    if not codes:
        return _row(label, "ไม่ได้ตั้งค่า", "ไม่ได้ตั้งค่า — หน้าจะแสดง \"ไม่มีข้อมูล\"", "warn", "NCD_" + env)
    ph, params = common._in("c", codes)
    names = db.fetch(f"select t.{key} icode, t.name from {table} t where t.{key} in ({ph})", params)
    n = len(common.drug_hns(codes, None, p))
    found = ", ".join(f"{r['icode']} {r['name']}" for r in names) or f"ไม่พบรหัสนี้ในตาราง {table}"
    return _row(label, "รหัส " + ",".join(codes), f"{found} · จ่าย/ทำในช่วง {n:,} ราย", _status(bool(names), n), "NCD_" + env)


def _pp_row(p):
    codes = config.PP_REMISSION
    if not codes:
        return _row("รหัสกิจกรรม NCDs remission clinic", "ไม่ได้ตั้งค่า", "ไม่ได้ตั้งค่า — ตาราง DM remission จะว่าง", "warn", "NCD_PP_REMISSION")
    ph, params = common._in("c", codes)
    names = db.fetch(f"select t.pp_special_code code, t.pp_special_type_name name from pp_special_type t where t.pp_special_code in ({ph})", params)
    n = len(common.pp_special_hns(codes, p))
    found = ", ".join(f"{r['name']}" for r in names) or "ไม่พบรหัสนี้ใน pp_special_type"
    return _row("รหัสกิจกรรม NCDs remission clinic (pp_special)", "รหัส " + ",".join(codes), f"{found} · บันทึกในช่วง {n:,} ราย",
                _status(bool(names), n), "NCD_PP_REMISSION")


def _drugs(p):
    return [_item_row("ยา warfarin", "DRUG_WARFARIN", "drugitems", "icode", config.DRUG_WARFARIN, p),
            _item_row("ยา statin", "DRUG_STATIN", "drugitems", "icode", config.DRUG_STATIN, p),
            _item_row("ยาต้านเกล็ดเลือด", "DRUG_ANTIPLATELET", "drugitems", "icode", config.DRUG_ANTIPLATELET, p),
            _item_row("ยา ACEI/ARB (ชะลอไตเสื่อม)", "DRUG_ACEI_ARB", "drugitems", "icode", config.DRUG_ACEI_ARB, p),
            _item_row("ยาลดน้ำตาล (DM remission)", "DRUG_DM", "drugitems", "icode", config.DRUG_DM, p),
            _pp_row(p),
            _item_row("ยาพ่นควบคุม COPD/หืด", "DRUG_INHALER_CONTROLLER", "drugitems", "icode", config.DRUG_INHALER_CONTROLLER, p),
            _item_row("หัตถการ Spirometry", "PROC_SPIROMETRY", "nondrugitems", "icode", config.PROC_SPIROMETRY, p)]


_ICD = [("Stroke", "ICD_STROKE"), ("AMI", "ICD_AMI"), ("COPD", "ICD_COPD"), ("หืด", "ICD_ASTHMA"), ("CKD (N18)", "ICD_CKD"),
        ("ล้างไต/Dialysis", "ICD_DIALYSIS"), ("น้ำตาลต่ำ", "ICD_HYPOGLYCEMIA"), ("AKI", "ICD_AKI"), ("เลือดออก", "ICD_BLEEDING")]


def _icd(p):
    rows = []
    for label, env in _ICD:
        codes = getattr(config, env)
        n = len(common.icd_hns(codes, p))
        rows.append(_row(f"ICD-10 {label}", "ขึ้นต้นด้วย " + ",".join(codes) if codes else "ไม่ได้ตั้งค่า",
                         f"พบผู้ป่วย {n:,} ราย ในช่วง (นับจากรหัสโรค)", "ok" if n else "warn", "NCD_" + env))
    sample = db.fetch_one("select d.icd10 from ovstdiag d where d.icd10 like 'E11%%' limit 1", {}).get("icd10")
    rows.append(_row("รูปแบบรหัส ICD-10 ที่เก็บ", "ไม่มีจุด เช่น E119", f"ตัวอย่างที่พบ: {sample or 'ไม่พบ'}",
                     "warn" if (not sample or "." in sample) else "ok", "ตั้ง NCD_ICD_* ให้ตรงรูปแบบ (มี/ไม่มีจุด)"))
    return rows


def _discharge(p):
    ph, params = common._in("s", config.DCHSTTS_DEAD)
    n = 0
    if config.DCHSTTS_DEAD:
        params.update(start=p.start, end=p.end)
        n = common._n(db.fetch_one(f"select count(*) n from ipt i where i.dchdate between %(start)s and %(end)s and i.dchstts in ({ph})", params))
    return [_row("สถานะจำหน่ายตาย (ipt.dchstts)", "สถานะ " + (",".join(config.DCHSTTS_DEAD) or "ไม่ได้ตั้งค่า"),
                 f"พบการจำหน่ายสถานะนี้ {n:,} ครั้งในช่วง", "ok" if n else "warn", "NCD_DCHSTTS_DEAD")]


def _visits(p):
    d = db.fetch_one("select max(vstdate) d from ovst", {}).get("d")
    stale = d is None or (date.today() - d).days > 14
    return [_row("visit ล่าสุด (ovst)", "ข้อมูลควรเป็นปัจจุบัน", f"{ui.thai_date(d)}" if d else "ไม่พบข้อมูล", "warn" if stale else "ok")]


def _hdc(p):
    entries = {k: v for k, v in hdc._load().items() if k.endswith(f"|{p.fy}")}
    if not entries:
        return [_row("HDC แคชปีงบ", f"ปีงบ {p.fy}", "ยังไม่มีข้อมูล HDC ของปีงบนี้ (HDC อาจยังไม่ปล่อย) — หน้า HDC จะแสดงข้อมูลล่าสุดที่เคยดึงไว้ของปีก่อนหน้า · ระบบถามใหม่วันละครั้ง", "warn", "NCD_HDC_DISTRICT")]
    latest = max(datetime.fromisoformat(v["fetched_at"]) for v in entries.values())
    return [_row("HDC แคชปีงบ", f"อำเภอ {hdc.DISTRICT}", f"แคช {len(entries)} ตาราง · ดึงล่าสุด {ui.thai_date(latest.date())}", "ok", "NCD_HDC_DISTRICT")]


def _thresholds(p):
    return [_row("เกณฑ์ INR ในเกณฑ์รักษา", f"{config.INR_LOW:g}–{config.INR_HIGH:g}", "ตั้งตามแนวทางของคลินิก", "ok", "NCD_INR_LOW / NCD_INR_HIGH"),
            _row("เป้า TTR", f"≥ {config.TTR_TARGET:g}%", "ตั้งตามเป้าหมายของ รพ.", "ok", "NCD_TTR_TARGET"),
            _row("เกณฑ์ควบคุมน้ำตาล (A1c)", f"< {config.HBA1C_TARGET:g}%", "ตั้งตามแนวทาง/เป้าของ รพ.", "ok", "NCD_HBA1C_TARGET"),
            _row("เป้า HT/DM ควบคุมได้", f"≥ {config.TARGET_HT_CONTROL:g}% / ≥ {config.TARGET_DM_CONTROL:g}%", "ค่าเริ่มต้นของ รพ.วังน้ำเขียว — ปรับตามเป้าของ รพ.", "ok",
                  "NCD_TARGET_HT_CONTROL / NCD_TARGET_DM_CONTROL"),
            _row("เกณฑ์ภาวะซีดใน CKD", f"Hb > {config.CKD_HB_MIN:g} g/dl หรือ Hct > {config.CKD_HCT_MIN:g}%", "ตั้งตามแนวทางคลินิกไต", "ok",
                  "NCD_CKD_HB_MIN / NCD_CKD_HCT_MIN"),
            _row("เกณฑ์ HbA1c ใน DM ที่มี CKD 3–4", f"< {config.CKD_DM_HBA1C_TARGET:g}%", "แนวทางเวชปฏิบัติใช้ 6.5–7.5% — ตั้งให้ตรงกับที่คลินิกใช้", "ok",
                  "NCD_CKD_DM_HBA1C_TARGET"),
            _row("เป้าชะลอไตเสื่อม ACEI/ARB · ซีด · HbA1c", f"> {config.TARGET_CKD_ACEI_ARB:g}% · > {config.TARGET_CKD_ANEMIA:g}% · > {config.TARGET_CKD_DM_A1C:g}%",
                  "ค่าเริ่มต้นตามตัวชี้วัด Service Plan ไต — ปรับตามเป้าของ รพ.", "ok",
                  "NCD_TARGET_CKD_ACEI_ARB / NCD_TARGET_CKD_ANEMIA / NCD_TARGET_CKD_DM_A1C"),
            _row("เกณฑ์ DM remission", f"HbA1c < {config.REMISSION_HBA1C:g}% 2 ครั้ง ห่าง {config.REMISSION_MIN_DAYS}–{config.REMISSION_MAX_DAYS} วัน · เป้า ≥ {config.TARGET_DM_REMISSION:g}%",
                 "ตามนิยามตัวชี้วัด HDC 10.2 (กองโรคไม่ติดต่อ)", "ok",
                 "NCD_REMISSION_HBA1C / NCD_REMISSION_MIN_DAYS / NCD_REMISSION_MAX_DAYS / NCD_TARGET_DM_REMISSION"),
            _row("เกณฑ์เบิกงบ DM Remission",
                 f"lifestyle {config.CLAIM_LIFESTYLE_DAYS} วัน / หยุดยา {config.CLAIM_DRUGFREE_DAYS} วัน · ครั้ง 1→2 ≥{config.CLAIM_PAIR_MIN_DAYS} วัน"
                 + (f" ≤{config.CLAIM_PAIR_MAX_DAYS}" if config.CLAIM_PAIR_MAX_DAYS else " (ไม่จำกัด)")
                 + f" · ครั้ง 2→3 {config.CLAIM_MAINT_MIN_DAYS}–{config.CLAIM_MAINT_MAX_DAYS} วัน · {config.CLAIM_SUCCESS_BAHT:,.0f}/{config.CLAIM_MAINT_BAHT:,.0f} บาท",
                 "ตามกรอบแนวทางงบบริการ DM Remission (สิ่งที่ส่งมาด้วย ๒) — ตรวจกับประกาศฉบับล่าสุด", "ok",
                 "NCD_CLAIM_* (LIFESTYLE_DAYS, DRUGFREE_DAYS, PAIR_MIN_DAYS, PAIR_MAX_DAYS, MAINT_MIN_DAYS, MAINT_MAX_DAYS, SUCCESS_BAHT, MAINT_BAHT)"),
            _row("เป้า HDC: eGFR ลดลง <5/ปี", f"≥ {config.TARGET_CKD_EGFR:g}%", "ตัวชี้วัดกระทรวง — ปรับตามเป้าของ รพ.", "ok",
                  "NCD_TARGET_CKD_EGFR")]


SECTIONS = [("คลินิก", _clinics), ("lab", _labs), ("ยา/หัตถการ", _drugs), ("รหัสโรค", _icd), ("สถานะจำหน่าย", _discharge),
            ("visit ล่าสุด", _visits), ("HDC", _hdc), ("เกณฑ์", _thresholds)]


def audit(p) -> List[dict]:
    rows: List[dict] = []
    for name, fn in SECTIONS:
        try:
            rows += fn(p)
        except Exception as e:      # noqa: BLE001 — ส่วนที่ล้มกลายเป็นแถวผิดพลาด ส่วนอื่นยังตรวจต่อ
            rows.append(_row(f"ตรวจ{name}", "—", f"ตรวจไม่สำเร็จ ({type(e).__name__})", "error"))
    return rows

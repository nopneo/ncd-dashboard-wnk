"""บล็อกหน้าต่างเตือน DM Remission สำหรับ SYS_VN_SCRIPT ของ HOSxP (ต่อเข้ากับ script เตือน Sepsis ที่มีอยู่)

เตือนเมื่อบันทึกหน้าซักประวัติ/ตรวจ ของผู้ป่วยที่มีรหัสกิจกรรม 1I20 และ
  HbA1c ล่าสุด < 6.5 และ ไม่ได้รับยาลดน้ำตาลตั้งแต่วันที่ตรวจนั้น  (= อยู่ระหว่างทางเข้าสู่ระยะสงบ)
หน้าต่าง: แบบเดียวกับหน้าต่างเตือน Sepsis (TForm แถบหัว + กล่องเนื้อหา + ปุ่มรับทราบ) โทนม่วง info-neon
  หัว "DM REMISSION : ห้ามสั่งยาลดน้ำตาล" · HbA1c ล่าสุด + จำนวนวัน · สิ่งที่ต้องทำ 4 ข้อ (รวมเวลานัดเจาะครั้งถัดไป)
  state 10 = ผลล่าสุดยังไม่ครบ 90 วัน (บอกจำนวนวันที่เหลือ)
  state 20 = 90-180 วัน ถึงช่วงเจาะแล้ว
  state 30 = เกิน 180 วัน ควรเจาะวันนี้
สถานะการเบิกที่ละเอียด (ครั้งที่ 1/2/3, lifestyle 180 วัน, หยุดยา 90 วัน) ดูที่หน้า DM ของ NCD Dashboard — หน้าต่างนี้เป็นตัวเตือนหน้างาน

ข้อจำกัด script engine (ดู sepsis_bundle/hosxp_alert/README.md): literal <= 255 ตัว, อักษร TIS-620 เท่านั้น,
ค่าจาก getsqldata ที่จะต่อข้อความต้องเป็น concat(...) + 0, ไม่ใช้ else/procedure/try — ทุกค่าเปรียบเทียบเป็นช่วงตัวเลข
บล็อกมีตัวแปรของตัวเอง (ขึ้นต้น rm) ไม่พึ่งตัวแปรของส่วน Sepsis
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Tuple

VAR_BEGIN = "// === NCD DM REMISSION ALERT (var) BEGIN ==="
VAR_END = "// === NCD DM REMISSION ALERT (var) END ==="
BODY_BEGIN = "// === NCD DM REMISSION ALERT BEGIN === (install_remission_alert.py - อย่าแก้ในบล็อกนี้ด้วยมือ)"
BODY_END = "// === NCD DM REMISSION ALERT END ==="
LITERAL_MAX = 200
LITERAL = re.compile(r"'(?:[^'\n]|'')*'")
SKIP_FORMS = ("frmLabOrder", "ERDetailEntryForm")
VARS = [(v, "string") for v in ("rmform", "rmvn", "rmhn", "rmon", "rmstate", "rma1", "rmd1", "rmleft", "rmhead", "rmtodo", "rmcrlf")] + [
    ("rmfrm", "TForm"), ("rmtop", "TPanel"), ("rmbox", "TPanel"), ("rmbar", "TPanel"),
    ("rmlb1", "TLabel"), ("rmlb2", "TLabel"), ("rmlb3", "TLabel"), ("rmlb4", "TLabel"), ("rmbtn", "TButton")]


def bgr(hex_color: str) -> int:
    """สี #RRGGBB → ตัวเลข TColor (BGR) — script engine ของ HOSxP ไม่รู้จักชื่อสี เช่น clRed"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r + g * 256 + b * 65536


#: โทน info-neon (คราม-ม่วงลาเวนเดอร์) ให้ต่างจากหน้าต่าง Sepsis (น้ำเงิน/แดง) จนแยกออกได้ทันที
C_BG, C_TOP, C_BOX, C_NAVY, C_TEXT, C_TODO = (bgr(c) for c in ("#F4F3FE", "#4A3AC8", "#EEEBFF", "#25277E", "#464666", "#4B2BB8"))


@dataclass
class Config:
    lab: str = "271"                         # lab_items_code ของ HbA1c (NCD_LAB_HBA1C)
    drugs: List[str] = field(default_factory=lambda: [
        "1000052", "1560201", "1000292", "1000053", "1560202", "1000270", "1000060", "1670004", "1000390", "1670002",
        "1561201", "1000232", "1000460"])   # ยาลดน้ำตาลทุกชนิด (NCD_DRUG_DM)
    pp: str = "1I20"                         # pp_special_code ของ NCDs remission clinic
    cut: float = 6.5
    due: int = 90                            # ห่างจากผลล่าสุดอย่างน้อย (วัน) ก่อนเจาะครั้งถัดไป
    mx: int = 180                            # เกินนี้ = เลยช่วง ควรเจาะทันที
    probe: bool = False                      # ฉบับตรวจ: ขึ้นข้อความ RM1-RM4 ทุกขั้น (ฐานทดสอบเท่านั้น)
    demo_hn: str = ""                        # ทดสอบบนฐานจริง: ข้อความ RM + บังคับหน้าต่าง เฉพาะ HN นี้ (ผู้ป่วยทดสอบ)


def _q(codes) -> str:
    return ", ".join(f'"{c}"' for c in codes)


def _latest(cfg: Config, expr: str) -> str:
    """subquery ค่าจากผล HbA1c ล่าสุดที่เป็นตัวเลข 3-25 (ค่าผิดรูป/ข้อความไม่นับ)"""
    return (f"(select {expr} from lab_head h join lab_order o on o.lab_order_number = h.lab_order_number "
            f'where h.hn = "{{HN}}" and o.lab_items_code in ({_q([cfg.lab])}) and o.lab_order_result + 0 between 3 and 25 '
            "order by h.order_date desc, h.lab_order_number desc limit 1)")


def sqls(cfg: Config) -> dict:
    """SQL ที่บล็อกใช้ ({HN} = ตำแหน่ง HN ของ visit) — ใช้ทั้งสร้าง script และตรวจกับข้อมูลจริง"""
    cut = float(cfg.cut)
    return {
        "reg": ("select concat(count(*)) + 0 from pp_special s join pp_special_type t on t.pp_special_type_id = s.pp_special_type_id "
                f'where t.pp_special_code in ({_q([cfg.pp])}) and s.hn = "{{HN}}"'),
        "state": (f"select concat(case when x.a1 is null or x.a1 >= {cut} then 0 when x.ld is not null and x.ld >= x.d then 0 "
                  f"when datediff(curdate(), x.d) < {cfg.due} then 10 when datediff(curdate(), x.d) <= {cfg.mx} then 20 else 30 end) + 0 "
                  f"from (select {_latest(cfg, 'o.lab_order_result + 0')} a1, {_latest(cfg, 'h.order_date')} d, "
                  f'(select max(r.vstdate) from opitemrece r where r.hn = "{{HN}}" and r.icode in ({_q(cfg.drugs)})) ld) x'),
        "a1": f"select concat(coalesce({_latest(cfg, 'o.lab_order_result + 0')}, 0)) + 0",
        "d1": f"select concat(coalesce({_latest(cfg, 'datediff(curdate(), h.order_date)')}, 0)) + 0",
        "left": f"select concat(coalesce({_latest(cfg, f'{cfg.due} - datediff(curdate(), h.order_date)')}, 0)) + 0",
    }


def _chunks(s: str, limit: int = LITERAL_MAX) -> List[str]:
    """ตัดข้อความที่ช่องว่างนอก "..." ให้แต่ละท่อน <= limit (ต่อกลับได้ข้อความเดิม)"""
    cuts, inq = [], False
    for i, ch in enumerate(s):
        if ch == '"':
            inq = not inq
        elif ch == " " and not inq:
            cuts.append(i)
    parts, start = [], 0
    while len(s) - start > limit:
        ok = [c for c in cuts if start < c <= start + limit]
        end = ok[-1] if ok else next((c for c in cuts if c > start), len(s))
        parts.append(s[start:end])
        start = end
    parts.append(s[start:])
    return [p for p in parts if p]


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def pas_sql(sql: str) -> str:
    """SQL → นิพจน์ Pascal: ท่อน literal <= 200 ตัว ต่อด้วย + และแทน {HN} ด้วยตัวแปร rmhn"""
    out = []
    for chunk in _chunks(sql):              # ตัดทั้งประโยคก่อน (เครื่องหมาย " ยังเป็นคู่) แล้วค่อยแยกตรง {HN}
        for i, part in enumerate(chunk.split("{HN}")):
            if i:
                out.append("rmhn")
            if part:
                out.append(_lit(part))
    return " +\n    ".join(out)


def build_block(cfg: Config) -> Tuple[str, str]:
    """(ข้อความประกาศตัวแปร, ข้อความส่วนทำงาน) — บรรทัดคั่นด้วย \\n"""
    q = sqls(cfg)
    skip = " and ".join(f"(rmform <> '{f}')" for f in SKIP_FORMS)
    var = "\n".join([VAR_BEGIN] + [f"{v} : {t};" for v, t in VARS] + [VAR_END])

    demo = cfg.demo_hn
    if demo and not re.fullmatch(r"[0-9A-Za-z]{1,20}", demo):
        raise ValueError("demo_hn ต้องเป็นตัวเลข/อักษรอังกฤษ 1-20 ตัว")

    def probe(text):
        if cfg.probe:
            return f"\n  showmessage({text});"
        if demo and "RM1" not in text:          # RM1 อยู่ก่อนอ่าน HN — โหมด demo เริ่มที่ RM2
            return f"\nif rmhn = '{demo}' then\nbegin\n    showmessage({text});\nend;"
        return ""
    force = (f"\nif rmhn = '{demo}' then\nbegin\n  if rmstate < 5 then\n  begin\n    rmstate := '10';\n  end;\nend;"
             if demo else "")
    body = f"""{BODY_BEGIN}
rmcrlf := chr(13) + chr(10);
rmform := Screen.ActiveForm.Name;
rmon := '0';
rmstate := '0';{probe("'RM1 form=' + rmform")}
if {skip} then
begin
  rmvn := GetGlobalValue('VN');
  rmhn := getsqldata('select hn from ovst where vn="' + rmvn + '" ');{probe("'RM2 vn=' + rmvn + ' hn=' + rmhn")}
  rmon := getsqldata({pas_sql(q["reg"])});
end;{probe("'RM3 on=' + rmon")}
if rmon > 0 then
begin
  rmstate := getsqldata({pas_sql(q["state"])});
end;{probe("'RM4 state=' + rmstate")}{force}
if rmstate > 5 then
begin
  rma1 := getsqldata({pas_sql(q["a1"])});
  rmd1 := getsqldata({pas_sql(q["d1"])});
  rmhead := '';
  if rmstate < 15 then
  begin
    rmleft := getsqldata({pas_sql(q["left"])});
    rmhead := 'นัดเจาะ HbA1c ครั้งถัดไปเมื่อครบ {cfg.due} วันจากผลล่าสุด (อีก ' + rmleft + ' วัน)';
  end;
  if (rmstate > 15) and (rmstate < 25) then
  begin
    rmhead := 'ถึงช่วงเจาะ HbA1c ครั้งถัดไปแล้ว ({cfg.due}-{cfg.mx} วัน) - ควรเจาะวันนี้';
  end;
  if rmstate > 25 then
  begin
    rmhead := 'ผลล่าสุดเกิน {cfg.mx} วันแล้ว - ควรเจาะ HbA1c วันนี้';
  end;
  rmtodo := '1. ห้ามสั่งยาลดน้ำตาลทุกชนิด (เสียสิทธิ์เบิกงบ DM Remission)' + rmcrlf +
            '2. ' + rmhead + rmcrlf +
            '3. ให้คำแนะนำอาหาร / ออกกำลังกาย / ลดน้ำหนักต่อเนื่อง' + rmcrlf +
            '4. ดูสถานะการเบิกรายคน: NCD Dashboard หน้า DM (เครือข่าย รพ.)';
{_window(cfg)}
end;
{BODY_END}"""
    return var, body


def _ctl(name: str, kind: str, parent: str, props: List[Tuple[str, str]]) -> str:
    """สร้างคอนโทรลแบบเดียวกับหน้าต่าง Sepsis ที่ใช้งานจริง (Create → Parent → คุณสมบัติทีละบรรทัด)"""
    lines = [f"  {name} := {kind}.Create(rmfrm);", f"  {name}.Parent := {parent};"]
    lines += [f"  {name}.{k} := {v};" for k, v in props]
    return "\n".join(lines)


def _label(name, parent, left, top, height, color, caption):
    return _ctl(name, "TLabel", parent, [("Left", str(left)), ("Top", str(top)), ("Font.Name", "'Tahoma'"),
                                         ("Font.Height", str(-height)), ("Font.Color", str(color)), ("Caption", caption)])


def _window(cfg: Config) -> str:
    """หน้าต่างแจ้งเตือนแบบเดียวกับ Sepsis (TForm + แถบหัว + กล่องเนื้อหา + ปุ่มรับทราบ) โทนม่วง info-neon
    ใช้เฉพาะคำสั่ง/คุณสมบัติที่หน้าต่าง Sepsis ใช้อยู่แล้ว · สีเป็นตัวเลข BGR · ไม่มี procedure/try/else"""
    panel = [("BevelOuter", "0"), ("ParentBackground", "False")]
    parts = [
        "  rmfrm := TForm.Create(nil);",
        "  rmfrm.Caption := 'DMRemissionNoticeForm';",
        "  rmfrm.BorderStyle := 3;",
        "  rmfrm.Position := 4;",
        "  rmfrm.Width := 820;",
        "  rmfrm.Height := 500;",
        f"  rmfrm.Color := {C_BG};",
        "  rmfrm.Font.Name := 'Tahoma';",
        _ctl("rmtop", "TPanel", "rmfrm", [("Align", "1"), ("Height", "56")] + panel + [
            ("Color", str(C_TOP)), ("Font.Name", "'Tahoma'"), ("Font.Color", "16777215"), ("Font.Height", "-26"),
            ("Caption", "'DM REMISSION : ห้ามสั่งยาลดน้ำตาล'")]),
        _label("rmlb1", "rmfrm", 24, 72, 22, C_NAVY, "rmhead"),
        _ctl("rmbox", "TPanel", "rmfrm", [("Left", "24"), ("Top", "112"), ("Width", "760"), ("Height", "276")] + panel + [
            ("Color", str(C_BOX)), ("Caption", "''")]),
        _ctl("rmbar", "TPanel", "rmbox", [("Align", "3"), ("Width", "10")] + panel + [("Color", str(C_TOP)), ("Caption", "''")]),
        _label("rmlb2", "rmbox", 30, 14, 30, C_NAVY, "'HbA1c ล่าสุด ' + rma1 + ' %     เมื่อ ' + rmd1 + ' วันก่อน'"),
        _label("rmlb3", "rmbox", 30, 58, 18, C_TEXT,
               "'ไม่ได้รับยาลดน้ำตาลตั้งแต่ผลนี้ - กำลังเข้าสู่ระยะสงบ (NCDs remission clinic)'"),
        _label("rmlb4", "rmbox", 30, 100, 20, C_TODO, "rmtodo"),
        _ctl("rmbtn", "TButton", "rmfrm", [("Left", "650"), ("Top", "404"), ("Width", "134"), ("Height", "40"),
                                           ("Font.Name", "'Tahoma'"), ("Font.Height", "-18"), ("Caption", "'รับทราบ'"),
                                           ("ModalResult", "1")]),
        "  rmfrm.ShowModal;",
        "  rmfrm.Free;",
    ]
    return "\n".join(parts)


def _nl(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def installed(script: str) -> bool:
    return BODY_BEGIN in (script or "")


def strip(script: str) -> str:
    """ลบบล็อก DM Remission ออก (คืน script เดิมก่อนติดตั้ง)"""
    nl = _nl(script)
    out, skip = [], False
    for ln in script.split(nl):
        if ln.startswith(VAR_BEGIN) or ln.startswith(BODY_BEGIN.split(" (")[0]):
            skip = True
            continue
        if skip and (ln.startswith(VAR_END) or ln.startswith(BODY_END)):
            skip = False
            continue
        if not skip:
            out.append(ln)
    return nl.join(out)


def merge(script: str, cfg: Config) -> str:
    """ใส่บล็อกลง script: ตัวแปรก่อนบรรทัด begin หลัก · ส่วนทำงานก่อน end; ตัวสุดท้าย · ติดตั้งซ้ำ = แทนที่บล็อกเดิม"""
    base = strip(script or "")
    nl = _nl(base) if base else "\r\n"
    lines = base.split(nl)
    stripped = [ln.strip().lower() for ln in lines]
    if "var" not in stripped or "begin" not in stripped:
        raise ValueError("script ไม่มีส่วน var / begin หลัก — รูปแบบไม่ตรงกับที่รองรับ ให้รวมเอง")
    begin = stripped.index("begin", stripped.index("var"))
    last_end = max((i for i, s in enumerate(stripped) if s in ("end;", "end.")), default=-1)
    if last_end <= begin:
        raise ValueError("หา end; ปิดท้ายของ script ไม่พบ — ให้รวมเอง")
    var, body = build_block(cfg)
    new = lines[:begin] + var.split("\n") + lines[begin:last_end] + body.split("\n") + lines[last_end:]
    return nl.join(new)


def alert_state(points: List[Tuple[date, float]], drug_dates: List[date], today: date, cfg: Config) -> int:
    """แบบ Python ของ SQL "state" (ใช้ทดสอบ/ตรวจกับข้อมูลจริง) — 0 ไม่เตือน · 10 / 20 / 30"""
    pts = sorted(p for p in points if 3 <= p[1] <= 25 and p[0] <= today)
    if not pts:
        return 0
    d, v = pts[-1]
    if v >= cfg.cut:
        return 0
    if any(x >= d for x in drug_dates if x <= today):
        return 0
    days = (today - d).days
    return 10 if days < cfg.due else 20 if days <= cfg.mx else 30

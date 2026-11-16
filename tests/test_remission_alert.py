"""หน้าต่างเตือน DM Remission ใน HOSxP (บล็อกใน SYS_VN_SCRIPT ต่อท้าย script เตือน Sepsis เดิม)"""
import re
from datetime import date

import pytest

from hosxp_alert import remission_alert as ra

D = date
SEPSIS_LIKE = "\r\n".join([
    "// SYS_VN_SCRIPT - Sepsis", "var", "fvn : string;", "fage : string;", "", "begin", "",
    "fvn := GetGlobalValue('VN');", "if fage > 14 then", "begin", "  showmessage('x');", "end;", "", "", "end;"])
CFG = ra.Config()


def test_block_is_safe_for_hosxp_script_engine():
    v, b = ra.build_block(CFG)
    text = v + b
    text.encode("tis-620")                                        # อักษรนอก TIS-620 ทำให้ script หยุดเงียบ
    for bad in ("≥", "—", "·", "°", "clRed", "fsBold"):
        assert bad not in text
    code = ra.LITERAL.sub("''", text)                                 # ตรวจเฉพาะโค้ด Pascal (ไม่นับข้อความ SQL)
    for word in ("procedure", "try", "except", "finally", "else"):
        assert not re.search(rf"\b{word}\b", code, re.I)
    for lit in ra.LITERAL.findall(b):
        assert len(lit) - 2 <= ra.LITERAL_MAX                       # literal เกิน 255 = script หยุดเงียบ
    assert ";\n  else" not in text and "; else" not in text
    assert '"1I20"' in b and '"271"' in b and '"1000052"' in b and "6.5" in b


@pytest.mark.parametrize("name", ["reg", "state", "a1", "d1", "left"])
def test_pascal_literals_join_back_to_the_exact_sql(name):
    sql = ra.sqls(CFG)[name]
    expr = ra.pas_sql(sql)
    tokens = re.findall(r"'(?:[^']|'')*'|rmhn", expr)
    back = "".join("{HN}" if t == "rmhn" else t[1:-1].replace("''", "'") for t in tokens)
    assert back == sql
    assert all(len(t) - 2 <= ra.LITERAL_MAX for t in tokens if t != "rmhn")


def test_merge_inserts_vars_before_main_begin_and_body_before_last_end():
    out = ra.merge(SEPSIS_LIKE, CFG)
    lines = out.split("\r\n")
    begin = lines.index("begin")
    assert any("rmstate : string;" in ln for ln in lines[:begin])
    body_start = next(i for i, ln in enumerate(lines) if ra.BODY_BEGIN in ln)
    assert body_start > lines.index("end;") and lines[-1] == "end;"      # หลังบล็อก Sepsis ก่อน end; สุดท้าย
    assert "showmessage('x');" in out                                    # ของเดิมอยู่ครบ


def test_merge_is_idempotent_and_strip_restores_original():
    once = ra.merge(SEPSIS_LIKE, CFG)
    assert ra.merge(once, CFG) == once
    assert ra.strip(once) == SEPSIS_LIKE
    assert ra.installed(once) and not ra.installed(SEPSIS_LIKE)


def test_merge_refuses_unknown_script_shape():
    with pytest.raises(ValueError):
        ra.merge("showmessage('x');", CFG)
    with pytest.raises(ValueError):
        ra.merge("", CFG)


@pytest.mark.parametrize("pts,drugs,expected", [
    ([], [], 0),
    ([(D(2026, 10, 1), 7.1)], [], 0),                                   # ล่าสุด >=6.5
    ([(D(2026, 10, 1), 6.2)], [D(2026, 10, 1)], 0),                     # ได้ยาวันเดียวกัน/หลังผล = ยังใช้ยา
    ([(D(2026, 10, 1), 6.2)], [D(2026, 5, 1)], 10),                     # 44 วัน รอครบ 90
    ([(D(2026, 7, 1), 6.2)], [], 20),                                   # 136 วัน ถึงช่วงเจาะ
    ([(D(2026, 3, 1), 6.2)], [], 30),                                   # 258 วัน เลย 180
    ([(D(2026, 10, 1), 6.2), (D(2026, 11, 1), 30.0)], [], 10),          # ค่าผิดรูป (>25) ไม่นับ — ใช้ผลที่ถูกล่าสุด
])
def test_python_mirror_of_alert_state(pts, drugs, expected):
    assert ra.alert_state(pts, drugs, D(2026, 11, 14), CFG) == expected


def test_alert_is_a_custom_window_like_sepsis():
    v, b = ra.build_block(CFG)
    for decl in ("rmfrm : TForm;", "rmtop : TPanel;", "rmbox : TPanel;", "rmbar : TPanel;", "rmbtn : TButton;", "rmlb1 : TLabel;"):
        assert decl in v
    for stmt in ("rmfrm := TForm.Create(nil);", "rmfrm.BorderStyle := 3;", "rmfrm.Position := 4;", "rmbtn.ModalResult := 1;",
                 "rmfrm.ShowModal;", "rmfrm.Free;", "'รับทราบ'"):
        assert stmt in b
    assert "showmessage(rmmsg)" not in b                                   # ไม่ใช้กล่องข้อความธรรมดาแล้ว
    assert re.search(r"rmtop\.Color := \d+;", b) and "ParentBackground := False;" in b
    assert b.index("rmfrm.ShowModal;") < b.index("rmfrm.Free;") < b.index(ra.BODY_END)
    for stmt in ("rmhead := ", "อีก ' + rmleft"):
        assert stmt in b


def test_bgr_colour_helper():
    assert ra.bgr("#4A3AC8") == 74 + 58 * 256 + 200 * 65536
    assert ra.bgr("#FFFFFF") == 16777215


def test_probe_build_shows_each_step_and_default_build_does_not():
    _v, normal = ra.build_block(ra.Config())
    assert "RM1" not in normal
    _v, probe = ra.build_block(ra.Config(probe=True))
    for step in ("RM1", "RM2", "RM3", "RM4"):
        assert f"showmessage('{step}" in probe
    assert probe.index("RM1") < probe.index("RM2") < probe.index("RM3") < probe.index("RM4")
    probe.encode("tis-620")
    for lit in ra.LITERAL.findall(probe):
        assert len(lit) - 2 <= ra.LITERAL_MAX


def test_demo_hn_shows_probe_and_window_only_for_that_patient():
    _v, b = ra.build_block(ra.Config(demo_hn="0009999"))
    assert "if rmhn = '0009999' then" in b
    assert "showmessage('RM1" not in b                                  # ก่อนรู้ HN ไม่ขึ้นอะไร
    for step in ("RM2", "RM3", "RM4"):
        assert f"showmessage('{step}" in b
    for line in b.split("\n"):                                          # showmessage ทุกบรรทัดอยู่ใต้เงื่อนไข HN
        if "showmessage(" in line:
            assert line.startswith("    ")
    assert "rmstate := '10';" in b and b.index("rmstate := '10';") < b.index("if rmstate > 5 then")
    _v, normal = ra.build_block(ra.Config())
    assert "0009999" not in normal and "rmstate := '10';" not in normal


@pytest.mark.parametrize("bad", ["1' or '1'='1", "00 01", "x" * 21, "เอชเอ็น"])
def test_demo_hn_must_be_plain_code(bad):
    with pytest.raises(ValueError):
        ra.build_block(ra.Config(demo_hn=bad))


def test_state_sql_uses_configured_codes_and_thresholds():
    cfg = ra.Config(lab="999", drugs=["A1", "B2"], pp="ZZ", cut=7.0, due=60, mx=150)
    _v, b = ra.build_block(cfg)
    assert '"999"' in b and '"A1", "B2"' in b and '"ZZ"' in b and ">= 7.0" in b and "< 60" in b and "<= 150" in b
